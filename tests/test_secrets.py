import stat

import pytest

from birdframe import secrets as secretmod


@pytest.fixture(autouse=True)
def on_a_mac(monkeypatch):
    """The Keychain tests below describe the Mac; file-store tests opt out."""
    monkeypatch.setattr(secretmod, "KEYCHAIN", True)


@pytest.fixture
def on_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(secretmod, "KEYCHAIN", False)
    monkeypatch.setattr(secretmod, "SECRETS_FILE", tmp_path / "birdframe" / "secrets.env")
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    return secretmod.SECRETS_FILE


def test_set_and_get_key(mocker):
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    mocker.patch.object(secretmod.keyring, "get_password",
                        side_effect=lambda s, u: store.get((s, u)))
    mocker.patch.dict(secretmod.os.environ, {}, clear=False)
    secretmod.os.environ.pop("OPENAI_API_KEY", None)
    secretmod.set_openai_key("sk-abc")
    assert secretmod.get_openai_key() == "sk-abc"
    assert secretmod.has_openai_key() is True


def test_get_missing_returns_none(mocker):
    mocker.patch.object(secretmod.keyring, "get_password", return_value=None)
    mocker.patch.dict(secretmod.os.environ, {}, clear=False)
    secretmod.os.environ.pop("OPENAI_API_KEY", None)
    assert secretmod.get_openai_key() is None
    assert secretmod.has_openai_key() is False


def test_env_var_takes_precedence_over_keychain(mocker):
    mocker.patch.object(secretmod.keyring, "get_password", return_value="sk-from-keychain")
    mocker.patch.dict(secretmod.os.environ, {"OPENAI_API_KEY": "sk-from-env"})
    assert secretmod.get_openai_key() == "sk-from-env"


def test_gemini_key_roundtrip(mocker):
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    mocker.patch.object(secretmod.keyring, "get_password",
                        side_effect=lambda s, u: store.get((s, u)))
    mocker.patch.dict(secretmod.os.environ, {}, clear=False)
    secretmod.os.environ.pop("GEMINI_API_KEY", None)
    secretmod.set_key("gemini", "AIza-test")
    assert secretmod.get_key("gemini") == "AIza-test"
    assert ("birdframe", "gemini_api_key") in store


def test_openai_keychain_entry_name_unchanged(mocker):
    """Existing users' Keychain entries must keep working."""
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    secretmod.set_key("openai", "sk-abc")
    assert ("birdframe", "openai_api_key") in store


def test_gemini_env_var_precedence(mocker):
    mocker.patch.object(secretmod.keyring, "get_password", return_value="from-keychain")
    mocker.patch.dict(secretmod.os.environ, {"GEMINI_API_KEY": "from-env"})
    assert secretmod.get_key("gemini") == "from-env"


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        secretmod.get_key("dalle")


def test_linux_keys_live_in_a_private_file_not_the_keyring(on_linux, mocker):
    keyring_set = mocker.patch.object(secretmod.keyring, "set_password")
    keyring_get = mocker.patch.object(secretmod.keyring, "get_password")
    secretmod.set_key("openai", "  sk-abc  ")
    secretmod.set_key("cloudflare", "cf-token")
    assert secretmod.get_key("openai") == "sk-abc"
    assert secretmod.get_key("cloudflare") == "cf-token"
    assert secretmod.get_key("gemini") is None
    # Never the keyring: a headless box can block forever on its unlock prompt.
    keyring_set.assert_not_called()
    keyring_get.assert_not_called()
    assert stat.S_IMODE(on_linux.stat().st_mode) == 0o600
    assert secretmod.file_is_private()
    assert "OPENAI_API_KEY=sk-abc" in on_linux.read_text()


def test_linux_env_var_still_wins(on_linux, monkeypatch):
    secretmod.set_key("gemini", "from-file")
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert secretmod.get_key("gemini") == "from-env"


def test_linux_setting_one_key_keeps_the_others(on_linux):
    secretmod.set_key("openai", "sk-1")
    secretmod.set_key("gemini", "AIza-1")
    secretmod.set_key("openai", "sk-2")
    assert secretmod.get_key("openai") == "sk-2"
    assert secretmod.get_key("gemini") == "AIza-1"
    assert not list(on_linux.parent.glob(".secrets-*"))  # no temp files left behind


def test_a_key_must_be_one_line(on_linux):
    with pytest.raises(ValueError):
        secretmod.set_key("openai", "sk-abc\nEVIL=1")
    assert not on_linux.exists()


def test_file_readable_by_others_is_flagged(on_linux):
    secretmod.set_key("openai", "sk-abc")
    on_linux.chmod(0o644)
    assert not secretmod.file_is_private()
