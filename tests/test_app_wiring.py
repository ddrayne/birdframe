"""The image-client factory picks the backend from config.image_provider."""
from birdframe import app
from birdframe.app import _make_image_client
from birdframe.cloudflare import CloudflarePages
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


def test_public_site_goes_where_config_says(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert app._public_dir(cfg) is None and app._site_deploy(cfg, tmp_path) is None
    cfg.cloudflare_project = "window"
    assert app._public_dir(cfg) == app.DATA_DIR / "public-site"
    assert isinstance(app._site_deploy(cfg, tmp_path), CloudflarePages)
    cfg.public_site_dir = str(tmp_path / "mysite")
    assert app._public_dir(cfg) == tmp_path / "mysite"
    cfg.public_deploy_command = "rsync -a {dir}/ host:site/"
    own = app._site_deploy(cfg, tmp_path)
    assert callable(own) and not isinstance(own, CloudflarePages)  # your own command wins


def test_link_previews_use_the_hosted_address(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("birdframe.public_site.build_site", lambda *a, **k: seen.update(k) or {})

    class Host:
        def site_url(self):
            return "https://window.pages.dev"
    cfg = Config.load(tmp_path / "config.toml")
    app._site_builder(None, [], cfg, tmp_path, Host(), {})()
    assert seen["base_url"] == "https://window.pages.dev"
    cfg.public_site_url = "https://birds.example.org"      # a custom domain wins
    app._site_builder(None, [], cfg, tmp_path, Host(), {})()
    assert seen["base_url"] == "https://birds.example.org"
