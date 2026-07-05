import base64
import io
from datetime import datetime

from PIL import Image

from birdframe.artist import Artist
from birdframe.store import Store, Detection
from birdframe.styles import Style


def _png():
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1536), (100, 120, 90)).save(buf, format="PNG")
    return buf.getvalue()


def _artist(tmp_path, image_client, styles=None):
    store = Store(tmp_path / "db.sqlite")
    artist = Artist(
        store=store, styles=styles or [Style("ukiyo-e", "print of {scene}", "gradients")],
        image_client=image_client, archive_dir=tmp_path / "images",
        weather_fn=lambda lat, lon, when: "light rain",
        latitude=55.95, longitude=-3.19,
    )
    return store, artist


def test_generate_creates_image_record_and_file(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client)
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9))
    rec = artist.generate(when=datetime(2026, 7, 5, 21))
    assert rec.style == "ukiyo-e"
    assert "European Robin" in rec.species
    img = Image.open(rec.path)
    assert img.size == (1200, 1600)
    client.generate.assert_called_once()
    assert "European Robin" in client.generate.call_args.args[0]


def test_generate_falls_back_to_poster_on_openai_error(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.side_effect = RuntimeError("api down")
    store, artist = _artist(tmp_path, client)
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Turdus merula", "Common Blackbird", 0.9))
    rec = artist.generate(when=datetime(2026, 7, 5, 21))
    assert Image.open(rec.path).size == (1200, 1600)
    assert rec.style.endswith("(fallback)")
