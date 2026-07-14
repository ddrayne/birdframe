"""The image-client factory picks the backend from config.image_provider."""
from birdframe.app import _make_image_client
from birdframe.config import Config
from birdframe.image_client import GeminiImageClient, OpenAIImageClient


def _config(tmp_path, provider):
    cfg = Config.load(tmp_path / "config.toml")
    cfg.image_provider = provider
    return cfg


def test_openai_selected(tmp_path, mocker):
    mocker.patch("birdframe.secrets.get_key", return_value="sk-test")
    client = _make_image_client(_config(tmp_path, "openai"))
    assert isinstance(client, OpenAIImageClient)


def test_gemini_selected(tmp_path, mocker):
    mocker.patch("birdframe.secrets.get_key", return_value="AIza-test")
    client = _make_image_client(_config(tmp_path, "gemini"))
    assert isinstance(client, GeminiImageClient)
    assert client.model == "gemini-3-pro-image"


def test_missing_key_returns_none(tmp_path, mocker):
    mocker.patch("birdframe.secrets.get_key", return_value=None)
    assert _make_image_client(_config(tmp_path, "gemini")) is None


def test_unknown_provider_returns_none_with_warning(tmp_path, caplog):
    """A typo'd image_provider must not crash startup — warn and fall back to
    the free poster path."""
    with caplog.at_level("WARNING", logger="birdframe"):
        assert _make_image_client(_config(tmp_path, "gemeni")) is None
    assert "Unknown image_provider" in caplog.text
