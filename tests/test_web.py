from datetime import datetime

from fastapi.testclient import TestClient

from birdframe.web.app import create_app, AppContext
from birdframe.store import Store, Detection


class FakeArtist:
    def __init__(self, out_path):
        self.calls = 0
        self.out_path = out_path

    def generate(self, when):
        self.calls += 1
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
    ctx = AppContext(store=store, artist=FakeArtist(tmp_path / "img.png"),
                     publisher=FakePublisher(), now=lambda: datetime(2026, 7, 5, 12))
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
    assert len(ctx.publisher.published) == 1
    assert resp.json()["publish"] == "posted"


def test_index_served(tmp_path):
    _, _, client = _client(tmp_path)
    assert client.get("/").status_code == 200
