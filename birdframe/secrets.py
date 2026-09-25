"""API keys and tokens (OpenAI, Gemini, Cloudflare), kept out of config.toml
and out of the logs.

Precedence when reading: the provider's environment variable wins if set
(OPENAI_API_KEY / GEMINI_API_KEY / CLOUDFLARE_API_TOKEN — handy for one-off
runs and CI). Otherwise, on a Mac, the login Keychain. A headless Linux box
such as a Raspberry Pi has no keychain to ask (and a desktop keyring there can
block forever on an unlock prompt nobody will see), so there keys live in
~/.config/birdframe/secrets.env: a file only its owner can read (0600), never
the config file, written by `birdframe set-key`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import keyring

_SERVICE = "birdframe"
_PROVIDERS = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
    "cloudflare": ("cloudflare_api_token", "CLOUDFLARE_API_TOKEN"),
}
KEYCHAIN = sys.platform == "darwin"
SECRETS_FILE = Path.home() / ".config" / "birdframe" / "secrets.env"


def _provider(provider: str) -> tuple[str, str]:
    try:
        return _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"unknown key provider: {provider!r}") from None


def _read_file() -> dict[str, str]:
    try:
        text = SECRETS_FILE.read_text()
    except OSError:
        return {}
    values = {}
    for line in text.splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name and not name.startswith("#"):
            values[name.strip()] = value.strip()
    return values


def _write_file(values: dict[str, str]) -> None:
    """Replace the secrets file atomically; it is created 0600, so no other
    user ever sees it, not even for a moment."""
    SECRETS_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    body = "# birdframe keys — written by `birdframe set-key`; keep this file private.\n"
    body += "".join(f"{name}={value}\n" for name, value in sorted(values.items()))
    fd, tmp = tempfile.mkstemp(prefix=".secrets-", dir=SECRETS_FILE.parent)  # mode 0600
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(body)
        os.replace(tmp, SECRETS_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def storage_name() -> str:
    """Where `set_key` keeps keys on this machine, for messages."""
    return "the macOS Keychain" if KEYCHAIN else str(SECRETS_FILE)


def file_is_private() -> bool:
    """False when the secrets file exists but other users could read it."""
    try:
        return not SECRETS_FILE.stat().st_mode & 0o077
    except OSError:
        return True


def set_key(provider: str, key: str) -> None:
    """Persist a provider's key: the Keychain on a Mac, the 0600 file elsewhere."""
    user, env_var = _provider(provider)
    key = key.strip()
    if not key or any(ch.isspace() for ch in key):
        raise ValueError("a key is one line with no spaces")
    if KEYCHAIN:
        keyring.set_password(_SERVICE, user, key)
        return
    values = _read_file()
    values[env_var] = key
    _write_file(values)


def get_key(provider: str) -> str | None:
    """Resolve a provider's key: environment variable first, then the Keychain
    (Mac) or the secrets file (Linux)."""
    user, env_var = _provider(provider)
    env = os.environ.get(env_var)
    if env:
        return env.strip()
    if KEYCHAIN:
        return keyring.get_password(_SERVICE, user)
    return _read_file().get(env_var) or None


def set_openai_key(key: str) -> None:
    set_key("openai", key)


def get_openai_key() -> str | None:
    return get_key("openai")


def has_openai_key() -> bool:
    return bool(get_openai_key())
