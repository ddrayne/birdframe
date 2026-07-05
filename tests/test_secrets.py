from birdframe import secrets as secretmod


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
