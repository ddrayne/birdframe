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


def _artist(tmp_path, image_client, styles=None, **kw):
    store = Store(tmp_path / "db.sqlite")
    artist = Artist(
        store=store, styles=styles or [Style("ukiyo-e", "print of {scene}", "gradients")],
        image_client=image_client, archive_dir=tmp_path / "images",
        weather_fn=lambda lat, lon, when: "light rain",
        latitude=55.95, longitude=-3.19, **kw,
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


def test_no_birds_returns_none_no_empty_image(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client)  # no detections added
    rec = artist.generate(when=datetime(2026, 7, 5, 21))
    assert rec is None                            # empty → no image, nothing gallery'd
    client.generate.assert_not_called()           # and no paid OpenAI call
    assert store.recent_images() == []


def test_unchanged_species_reuses_without_gallery_dupe(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client)
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9))
    first = artist.generate(when=datetime(2026, 7, 5, 12))
    assert first is not None
    again = artist.generate(when=datetime(2026, 7, 5, 13))  # same species, same day
    assert again.id == first.id                   # reuses the existing picture
    assert len(store.recent_images()) == 1        # no duplicate added to the gallery
    assert client.generate.call_count == 1        # and no second paid render


def test_no_mic_no_detections_is_free(tmp_path, mocker):
    # No mic == no detections; a scheduled post must not spend.
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client)
    artist.generate(when=datetime(2026, 7, 5, 21))
    client.generate.assert_not_called()


def test_daily_cap_limits_paid_calls(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client, max_paid_images_per_day=1)
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9))
    artist.generate(when=datetime(2026, 7, 5, 12))   # 1st paid render
    artist.generate(when=datetime(2026, 7, 5, 13))   # capped → free poster
    assert client.generate.call_count == 1


def test_force_paid_bypasses_threshold_and_cap(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client, max_paid_images_per_day=1,
                            min_species_for_image=5)
    # One bird (below the 5-species threshold) and the daily cap already spent —
    # a forced Post Now must still render a real image.
    store.add_image(datetime(2026, 7, 5, 9), "/tmp/x.png", "linocut", "p", ["Prior Bird"])
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9))
    rec = artist.generate(when=datetime(2026, 7, 5, 21), force_paid=True)
    client.generate.assert_called_once()          # spent despite threshold + cap
    assert rec.style == "ukiyo-e"


def test_min_species_threshold(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = _png()
    store, artist = _artist(tmp_path, client, min_species_for_image=3)
    for i, (sci, com) in enumerate([("A a", "Alpha"), ("B b", "Beta")]):
        store.add_detection(Detection(datetime(2026, 7, 5, 6 + i), sci, com, 0.9))
    artist.generate(when=datetime(2026, 7, 5, 21))   # only 2 species < 3
    client.generate.assert_not_called()
