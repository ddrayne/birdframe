"""OpenAI API key storage.

Precedence when reading: the OPENAI_API_KEY environment variable wins if set
(handy for one-off runs and CI), otherwise the macOS Keychain. The key is never
written to config files or logs.
"""
from __future__ import annotations

import os

import keyring

_SERVICE = "birdframe"
_USER = "openai_api_key"
_ENV_VAR = "OPENAI_API_KEY"


def set_openai_key(key: str) -> None:
    """Persist the key in the macOS Keychain."""
    keyring.set_password(_SERVICE, _USER, key.strip())


def get_openai_key() -> str | None:
    """Resolve the key: environment variable first, then the Keychain."""
    env = os.environ.get(_ENV_VAR)
    if env:
        return env.strip()
    return keyring.get_password(_SERVICE, _USER)


def has_openai_key() -> bool:
    return bool(get_openai_key())
