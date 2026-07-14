"""Per-provider API key storage (OpenAI / Gemini).

Precedence when reading: the provider's environment variable wins if set
(OPENAI_API_KEY / GEMINI_API_KEY — handy for one-off runs and CI), otherwise
the macOS Keychain. Keys are never written to config files or logs.
"""
from __future__ import annotations

import os

import keyring

_SERVICE = "birdframe"
_PROVIDERS = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
}


def _provider(provider: str) -> tuple[str, str]:
    try:
        return _PROVIDERS[provider]
    except KeyError:
        raise ValueError(f"unknown image provider: {provider!r}") from None


def set_key(provider: str, key: str) -> None:
    """Persist a provider's key in the macOS Keychain."""
    user, _ = _provider(provider)
    keyring.set_password(_SERVICE, user, key.strip())


def get_key(provider: str) -> str | None:
    """Resolve a provider's key: environment variable first, then the Keychain."""
    user, env_var = _provider(provider)
    env = os.environ.get(env_var)
    if env:
        return env.strip()
    return keyring.get_password(_SERVICE, user)


def set_openai_key(key: str) -> None:
    set_key("openai", key)


def get_openai_key() -> str | None:
    return get_key("openai")


def has_openai_key() -> bool:
    return bool(get_openai_key())
