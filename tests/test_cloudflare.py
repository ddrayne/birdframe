"""Cloudflare Pages publishing: setup checks, project lookup, and the upload."""
import json

import pytest

from birdframe import cloudflare
from birdframe.cloudflare import CloudflareError, CloudflarePages

ACCOUNT = "0123456789abcdef0123456789abcdef"


class Response:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _which(name):
    return f"/usr/bin/{name}"


def _pages(tmp_path, *, get=None, post=None, run=None, token="cf-secret", **kw):
    out = tmp_path / "site"
    out.mkdir(exist_ok=True)
    (out / "index.html").write_text("<!doctype html>")
    calls = {"get": [], "post": [], "run": []}

    def http_get(url, **k):
        calls["get"].append((url, k))
        return get or Response(200, {"result": {"subdomain": "window.pages.dev",
                                                "production_branch": "main"}})

    def http_post(url, **k):
        calls["post"].append((url, k))
        return post or Response(200, {"result": {"subdomain": "window-4xz.pages.dev",
                                                 "production_branch": "main"}})

    def fake_run(args, **k):
        calls["run"].append((args, k))
        if args[-1] == "--version":
            return Done(stdout="v22.11.0\n")
        return run or Done(stdout="✨ Deployment complete!")

    pages = CloudflarePages("window", ACCOUNT, out, workdir=tmp_path / "wrangler",
                            token=lambda: token, http_get=http_get, http_post=http_post,
                            run=fake_run, which=kw.get("which", _which))
    return pages, calls


def test_upload_runs_wrangler_without_a_shell_and_keeps_the_token_off_the_command_line(tmp_path):
    pages, calls = _pages(tmp_path)
    assert pages() == "https://window.pages.dev"
    args, kw = calls["run"][-1]
    assert args == ["/usr/bin/npx", "--yes", "wrangler@4", "pages", "deploy",
                    str(tmp_path / "site"), "--project-name", "window",
                    "--branch", "main", "--commit-dirty=true"]
    assert "cf-secret" not in " ".join(args)
    assert kw["env"]["CLOUDFLARE_API_TOKEN"] == "cf-secret"
    assert kw["env"]["CLOUDFLARE_ACCOUNT_ID"] == ACCOUNT
    assert kw["cwd"] == tmp_path / "wrangler" and kw["cwd"].is_dir()
    assert "shell" not in kw
    url, request = calls["get"][0]
    assert url.endswith(f"/accounts/{ACCOUNT}/pages/projects/window")
    assert request["headers"] == {"Authorization": "Bearer cf-secret"}


def test_first_publish_creates_the_project(tmp_path):
    missing = Response(404, {"success": False, "errors": [{"code": 8000007, "message": "Project not found"}]})
    pages, calls = _pages(tmp_path, get=missing)
    assert pages() == "https://window-4xz.pages.dev"      # Cloudflare's suffix is kept
    url, request = calls["post"][0]
    assert url.endswith(f"/accounts/{ACCOUNT}/pages/projects")
    assert request["json"] == {"name": "window", "production_branch": "main"}


def test_a_project_on_another_branch_is_refused(tmp_path):
    other = Response(200, {"result": {"subdomain": "window.pages.dev", "production_branch": "production"}})
    pages, calls = _pages(tmp_path, get=other)
    with pytest.raises(CloudflareError, match="production"):
        pages()
    assert not [c for c in calls["run"] if "deploy" in c[0]]  # nothing uploaded as a preview


def test_a_refused_token_says_which_permission_is_needed(tmp_path):
    denied = Response(403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
    pages, _ = _pages(tmp_path, get=denied)
    with pytest.raises(CloudflareError, match="Cloudflare Pages › Edit"):
        pages()


def test_a_failed_upload_reports_wranglers_error(tmp_path):
    failed = Done(1, stdout="Uploading…", stderr="✘ [ERROR] A request to the Cloudflare API failed. [code: 8000000]\n")
    pages, _ = _pages(tmp_path, run=failed)
    with pytest.raises(CloudflareError, match=r"\[code: 8000000\]"):
        pages()


def test_setup_problems_are_explained(tmp_path):
    pages, _ = _pages(tmp_path)
    assert pages.problems() == []
    pages.project, pages.account_id = "My Window!", "nope"
    pages._token = lambda: None
    found = " | ".join(pages.problems())
    assert "isn't a valid Pages project name" in found
    assert "cloudflare_account_id" in found
    assert "birdframe set-key cloudflare" in found


def test_node_must_be_new_enough(tmp_path):
    pages, _ = _pages(tmp_path)
    pages._run = lambda args, **k: Done(stdout="v20.19.2\n")
    assert any("Node.js 20 is too old" in p for p in pages.problems())
    pages._which = lambda name: None
    assert any("needs Node.js 22+" in p for p in pages.problems())
    with pytest.raises(CloudflareError):
        pages()


def test_too_many_files_is_caught_before_uploading(tmp_path, monkeypatch):
    monkeypatch.setattr(cloudflare, "MAX_FILES", 1)
    pages, calls = _pages(tmp_path)
    (tmp_path / "site" / "extra.json").write_text(json.dumps({}))
    with pytest.raises(CloudflareError, match="archive_keep_days"):
        pages()
    assert not [c for c in calls["run"] if "deploy" in c[0]]


def test_no_api_call_without_a_token(tmp_path):
    pages, calls = _pages(tmp_path, token=None)
    with pytest.raises(CloudflareError, match="set-key cloudflare"):
        pages.site_url()
    assert calls["get"] == [] and calls["post"] == []
