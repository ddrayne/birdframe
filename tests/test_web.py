from datetime import datetime

from fastapi.testclient import TestClient

from birdframe.web.app import create_app, AppContext
from birdframe.config import Config
from birdframe.store import Store, Detection


class FakeArtist:
    def __init__(self, out_path):
        self.calls = 0
        self.forced = []
        self.out_path = out_path

    def generate(self, when, force_paid=False):
        self.calls += 1
        self.forced.append(force_paid)
        self.out_path.write_bytes(b"PNGBYTES")
        artist = self

        class R:
            id = 1
            path = str(artist.out_path)
            style = "ukiyo-e"
            species = ["European Robin"]
        return R()


class FakePublishResult:
    status = "posted"
    detail = ""


class FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, png):
        self.published.append(png)
        return FakePublishResult()


def _client(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9))
    config = Config.load(tmp_path / "config.toml")
    applied = []
    ctx = AppContext(store=store, artist=FakeArtist(tmp_path / "img.png"),
                     publisher=FakePublisher(), now=lambda: datetime(2026, 7, 5, 12),
                     config=config, apply_settings=lambda: applied.append(True))
    ctx._applied = applied
    return store, ctx, TestClient(create_app(ctx))


def test_today_endpoint_lists_species(tmp_path):
    _, _, client = _client(tmp_path)
    resp = client.get("/api/today")
    assert resp.status_code == 200
    data = resp.json()
    assert data["species"][0]["common_name"] == "European Robin"
    assert data["species"][0]["count"] == 1


def test_post_now_generates_and_publishes(tmp_path):
    store, ctx, client = _client(tmp_path)
    resp = client.post("/api/post-now")
    assert resp.status_code == 200
    assert ctx.artist.calls == 1
    assert ctx.artist.forced == [True]        # dashboard Post Now forces a real image
    assert len(ctx.publisher.published) == 1
    assert resp.json()["publish"] == "posted"


def test_index_served(tmp_path):
    _, _, client = _client(tmp_path)
    assert client.get("/").status_code == 200


def test_get_settings_returns_grouped_values(tmp_path):
    _, _, client = _client(tmp_path)
    data = client.get("/api/settings").json()
    keys = {f["key"] for g in data["groups"] for f in g["fields"]}
    assert "post_mode" in keys
    assert "max_paid_images_per_day" in keys
    # confidence_threshold is flagged as needing a restart
    conf = next(f for g in data["groups"] for f in g["fields"] if f["key"] == "confidence_threshold")
    assert conf["restart"] is True


def test_post_settings_saves_and_applies(tmp_path):
    _, ctx, client = _client(tmp_path)
    resp = client.post("/api/settings", json={"post_mode": "manual",
                                              "max_paid_images_per_day": "3"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["saved"]) == {"post_mode", "max_paid_images_per_day"}
    assert ctx.config.post_mode == "manual"
    assert ctx.config.max_paid_images_per_day == 3      # coerced to int
    assert ctx._applied == [True]                        # apply_settings ran
    # persisted to disk
    assert Config.load(ctx.config.path).post_mode == "manual"


def test_post_settings_rejects_bad_value_and_unknown_key(tmp_path):
    _, ctx, client = _client(tmp_path)
    resp = client.post("/api/settings", json={"max_paid_images_per_day": "lots"})
    assert resp.status_code == 400
    assert "max_paid_images_per_day" in resp.json()["fields"]
    resp2 = client.post("/api/settings", json={"latitude": 10.0})  # not in editable list
    assert resp2.status_code == 400
