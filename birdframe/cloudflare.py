"""Publish the public site on Cloudflare Pages: free static hosting at
https://<project>.pages.dev (or your own domain), with no limit on visits.

The project is looked up, and created on first use, through Cloudflare's REST
API; the files go up with Cloudflare's own uploader, Wrangler, run by npx.
Wrangler sends only the files Cloudflare doesn't already have, so a typical
update is the page plus a new painting. It runs without a shell, from a
folder of its own, with the API token passed only in its environment (never
on a command line, where other users could read it).

Setup: a Cloudflare API token with the permission Account › Cloudflare
Pages › Edit (`birdframe set-key cloudflare`), plus `cloudflare_project` and
`cloudflare_account_id` in config.toml. Wrangler needs Node.js 22 or newer.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import httpx

from birdframe import secrets

API = "https://api.cloudflare.com/client/v4"
WRANGLER = "wrangler@4"
MIN_NODE = 22
BRANCH = "main"                    # the production branch of projects made here
MAX_FILES = 20_000                 # Pages' per-site limit on the free plan
PROJECT_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,56}[a-z0-9])?$")
TOKEN_HELP = ("create one at dash.cloudflare.com › My Profile › API Tokens with "
              "Account › Cloudflare Pages › Edit, then run: birdframe set-key cloudflare")


class CloudflareError(RuntimeError):
    pass


def node_major(which: Callable = shutil.which, run: Callable = subprocess.run) -> int | None:
    """The installed Node.js major version, or None without Node."""
    node = which("node")
    if not node:
        return None
    try:
        out = run([node, "--version"], capture_output=True, text=True, timeout=20).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _errors(response) -> list[dict]:
    try:
        return response.json().get("errors") or []
    except (ValueError, AttributeError):
        return []


def _api_error(response) -> str:
    """Cloudflare's own words for a failed API call, made actionable."""
    errors = _errors(response)
    codes = {e.get("code") for e in errors}
    if response.status_code in (401, 403) or codes & {10000, 9106, 9109}:
        return f"Cloudflare refused the API token — {TOKEN_HELP}"
    if codes & {7003, 7000}:
        return "Cloudflare doesn't know that account — check cloudflare_account_id in config.toml"
    detail = "; ".join(str(e.get("message")) for e in errors if e.get("message"))
    return f"Cloudflare API error {response.status_code}" + (f": {detail}" if detail else "")


def _wrangler_error(output: str) -> str:
    """The useful lines of a failed Wrangler run (its [ERROR] lines if any)."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    errors = [line for line in lines if "[ERROR]" in line or line.startswith("✘")]
    text = " ".join(errors or lines[-3:])
    if "Authentication error" in text or "[code: 10000]" in text:
        return f"Cloudflare refused the API token — {TOKEN_HELP}"
    if "More than one account" in text:
        return "the token can reach several Cloudflare accounts — set cloudflare_account_id in config.toml"
    return text[:500] or "wrangler failed without saying why"


class CloudflarePages:
    """Uploads a built site folder to one Pages project. Call it to publish;
    it returns the site's address."""

    def __init__(self, project: str, account_id: str, out_dir: Path, *,
                 workdir: Path | None = None, token: Callable[[], str | None] | None = None,
                 http_get: Callable = httpx.get, http_post: Callable = httpx.post,
                 run: Callable = subprocess.run, which: Callable = shutil.which,
                 timeout: float = 900):
        self.project = (project or "").strip()
        self.account_id = (account_id or "").strip()
        self.out_dir = Path(out_dir)
        self.workdir = Path(workdir) if workdir else self.out_dir.parent / ".birdframe-wrangler"
        self._token = token or (lambda: secrets.get_key("cloudflare"))
        self._get, self._post = http_get, http_post
        self._run, self._which = run, which
        self.timeout = timeout
        self._url: str | None = None

    def problems(self, node: bool = True) -> list[str]:
        """Whatever would stop a publish right now, in words (doctor shows these)."""
        found = []
        if not PROJECT_NAME.match(self.project):
            found.append(f"cloudflare_project {self.project!r} isn't a valid Pages project name "
                         "(lowercase letters, digits and dashes, up to 58)")
        if not re.fullmatch(r"[0-9a-f]{32}", self.account_id):
            found.append("set cloudflare_account_id in config.toml (32 hex characters: "
                         "the Account ID on your Cloudflare dashboard)")
        if not self._token():
            found.append(f"no Cloudflare API token — {TOKEN_HELP}")
        if not node:
            return found
        major = node_major(self._which, self._run)
        if major is None or not self._which("npx"):
            found.append(f"Cloudflare's uploader needs Node.js {MIN_NODE}+ "
                         "(macOS: brew install node; Raspberry Pi: see the README)")
        elif major < MIN_NODE:
            found.append(f"Node.js {major} is too old for Cloudflare's uploader; it needs {MIN_NODE}+")
        return found

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    def site_url(self) -> str:
        """https://<subdomain>.pages.dev, creating the project the first time.
        Cloudflare adds a suffix when the plain name is taken elsewhere."""
        if self._url:
            return self._url
        problems = self.problems(node=False)
        if problems:
            raise CloudflareError("; ".join(problems))
        base = f"{API}/accounts/{self.account_id}/pages/projects"
        response = self._get(f"{base}/{self.project}", headers=self._headers(), timeout=30)
        if response.status_code == 404 or any(e.get("code") == 8000007 for e in _errors(response)):
            response = self._post(base, headers=self._headers(), timeout=30,
                                  json={"name": self.project, "production_branch": BRANCH})
        if response.status_code >= 300:
            raise CloudflareError(_api_error(response))
        project = response.json()["result"]
        if project.get("production_branch") not in (None, BRANCH):
            raise CloudflareError(
                f"the Pages project {self.project!r} publishes from the branch "
                f"{project['production_branch']!r}; birdframe publishes to {BRANCH!r}. "
                "Use a new project name, or change its production branch in the dashboard.")
        self._url = f"https://{project['subdomain']}"
        return self._url

    def __call__(self) -> str:
        problems = self.problems()
        if problems:
            raise CloudflareError("; ".join(problems))
        files = sum(1 for p in self.out_dir.rglob("*") if p.is_file())
        if files > MAX_FILES:
            raise CloudflareError(f"the site has {files} files; Cloudflare Pages takes "
                                  f"{MAX_FILES}. Set archive_keep_days to publish fewer paintings.")
        url = self.site_url()
        self.workdir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "CLOUDFLARE_API_TOKEN": self._token() or "",
               "CLOUDFLARE_ACCOUNT_ID": self.account_id,
               "WRANGLER_SEND_METRICS": "false", "FORCE_COLOR": "0"}
        args = [self._which("npx"), "--yes", WRANGLER, "pages", "deploy", str(self.out_dir),
                "--project-name", self.project, "--branch", BRANCH, "--commit-dirty=true"]
        # Its own folder, so Wrangler never picks up some other project's config.
        done = self._run(args, cwd=self.workdir, env=env, capture_output=True,
                         text=True, timeout=self.timeout)
        if done.returncode != 0:
            raise CloudflareError(_wrangler_error(f"{done.stdout}\n{done.stderr}"))
        return url
