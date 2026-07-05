"""OpenAI API key storage in the macOS Keychain."""
from __future__ import annotations

import keyring

_SERVICE = "birdframe"
_USER = "openai_api_key"


def set_openai_key(key: str) -> None:
    keyring.set_password(_SERVICE, _USER, key)


def get_openai_key() -> str | None:
    return keyring.get_password(_SERVICE, _USER)
