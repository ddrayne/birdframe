from birdframe import secrets as secretmod


def test_set_and_get_key(mocker):
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    mocker.patch.object(secretmod.keyring, "get_password",
                        side_effect=lambda s, u: store.get((s, u)))
    secretmod.set_openai_key("sk-abc")
    assert secretmod.get_openai_key() == "sk-abc"


def test_get_missing_returns_none(mocker):
    mocker.patch.object(secretmod.keyring, "get_password", return_value=None)
    assert secretmod.get_openai_key() is None
