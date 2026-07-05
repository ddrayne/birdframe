import time
from datetime import datetime

from fastapi.testclient import TestClient

from birdframe.web.app import create_app, AppContext
from birdframe.config import Config
from birdframe.store import Store, Detection
from birdframe.styles import save_style


class FakeImageClient:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return b"PREVIEWPNG"


class FakeArtist:
    def __init__(self, out_path, image_client=None, styles=None):
        self.calls = 0
        self.forced = []
        self.out_path = out_path
        self.image_client = image_client
        self.styles = styles or []

    def generate(self, when, force_paid=False, species_days=None):
        self.calls += 1
        self.forced.append(force_paid)
        self.species_days_arg = species_days
        self.out_path.write_bytes(b"PNGBYTES")
        artist = self
        names = [s.common_name for s in species_days] if species_days is not None else ["European Robin"]

        class R:
            id = 1
            path = str(artist.out_path)
            style = "ukiyo-e"
            species = names
        return R()


class FakePublishResult:
    status = "posted"
    detail = ""


class FakePublisher:
    def __init__(self):
        self.published = []
        self.forced = []

    def publish(self, png, force=False):
        self.published.append(png)
        self.forced.append(force)
        return FakePublishResult()


def _client(tmp_path, image_client=None):
    store = Store(tmp_path / "db.sqlite")
    store.add_detection(Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9))
    config = Config.load(tmp_path / "config.toml")
    styles_dir = tmp_path / "styles"
    save_style(styles_dir, "ukiyo-e", "A woodblock of {scene}.", "gradients")
    save_style(styles_dir, "linocut", "A linocut of {scene}.")
    applied = []
    ctx = AppContext(store=store,
                     artist=FakeArtist(tmp_path / "img.png", image_client=image_client),
                     publisher=FakePublisher(), now=lambda: datetime(2026, 7, 5, 12),
                     config=config, apply_settings=lambda: applied.append(True),
                     styles_dir=styles_dir, preview_dir=tmp_path / "previews")
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
    assert ctx.publisher.forced == [True]     # explicit post overrides any frame hold
    assert resp.json()["publish"] == "posted"


def test_index_served(tmp_path):
    _, _, client = _client(tmp_path)
    assert client.get("/").status_code == 200


def test_now_endpoint_reports_latest_and_feed(tmp_path):
    store, ctx, client = _client(tmp_path)
    # add a more recent detection than the fixture's 06:00 robin
    store.add_detection(Detection(datetime(2026, 7, 5, 11, 30), "Turdus merula", "Common Blackbird", 0.77))
    data = client.get("/api/now").json()
    assert data["latest"]["common_name"] == "Common Blackbird"
    assert data["latest"]["at"] == "11:30:00"
    assert data["feed"][0]["common_name"] == "Common Blackbird"
    assert data["today_species_count"] == 2
    assert data["window_species"][0]["scientific_name"] == "Turdus merula"
    assert isinstance(data["activity"], list) and len(data["activity"]) == 24
    assert sum(data["activity"]) >= 1


def test_now_endpoint_empty_is_graceful(tmp_path):
    store = Store(tmp_path / "empty.sqlite")
    from birdframe.config import Config
    ctx = AppContext(store=store, artist=FakeArtist(tmp_path / "i.png"),
                     publisher=FakePublisher(), now=lambda: datetime(2026, 7, 5, 12),
                     config=Config.load(tmp_path / "c.toml"))
    client = TestClient(create_app(ctx))
    data = client.get("/api/now").json()
    assert data["latest"] is None
    assert data["feed"] == []


def test_capture_uses_window_species_and_forces_paid(tmp_path):
    store, ctx, client = _client(tmp_path)
    # birds within the last 60 min of "now" (12:00): one at 11:30
    store.add_detection(Detection(datetime(2026, 7, 5, 11, 30), "Turdus merula", "Common Blackbird", 0.77))
    resp = client.post("/api/capture")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "started"
    assert "Common Blackbird" in body["species"]            # window species used
    assert "European Robin" not in body["species"]          # 06:00 robin outside the 60-min window
    # background job runs; wait for completion
    for _ in range(50):
        st = client.get("/api/capture/status").json()
        if st["state"] == "done":
            break
        time.sleep(0.02)
    assert st["state"] == "done"
    assert ctx.artist.forced[-1] is True                    # explicit action forced a real image
    assert ctx.publisher.forced[-1] is True                 # and overrode any frame hold


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


def test_list_styles_includes_sample_prompt_and_pinned(tmp_path):
    _, ctx, client = _client(tmp_path)
    ctx.config.style_mode = "pinned"
    ctx.config.pinned_style = "linocut"
    data = client.get("/api/styles").json()
    names = {s["name"] for s in data["styles"]}
    assert {"ukiyo-e", "linocut"} <= names
    lino = next(s for s in data["styles"] if s["name"] == "linocut")
    assert lino["pinned"] is True
    assert "linocut of" in lino["sample_prompt"].lower()
    assert data["key_set"] is False  # no image client in this fixture


def test_create_and_reload_style(tmp_path):
    _, ctx, client = _client(tmp_path)
    resp = client.put("/api/styles/new", json={"name": "Bauhaus Poster",
                                               "prompt": "A Bauhaus poster of {scene}.",
                                               "avoid": "clutter"})
    assert resp.status_code == 200
    assert resp.json()["saved"] == "bauhaus-poster"
    # reloaded onto the (fake) artist
    assert "bauhaus-poster" in {s.name for s in ctx.artist.styles}
    assert "bauhaus-poster" in {s["name"] for s in client.get("/api/styles").json()["styles"]}


def test_create_style_rejects_missing_placeholder(tmp_path):
    _, _, client = _client(tmp_path)
    resp = client.put("/api/styles/x", json={"name": "x", "prompt": "no placeholder"})
    assert resp.status_code == 400


def test_delete_style_but_not_the_last(tmp_path):
    _, _, client = _client(tmp_path)
    assert client.delete("/api/styles/linocut").json()["deleted"] is True
    # only ukiyo-e remains; refuse to delete it
    resp = client.delete("/api/styles/ukiyo-e")
    assert resp.status_code == 400


def test_pin_and_unpin(tmp_path):
    _, ctx, client = _client(tmp_path)
    assert client.post("/api/styles/ukiyo-e/pin").json()["pinned"] == "ukiyo-e"
    assert ctx.config.style_mode == "pinned"
    assert ctx.config.pinned_style == "ukiyo-e"
    client.post("/api/styles/unpin")
    assert ctx.config.style_mode == "rotate"


def test_preview_requires_key(tmp_path):
    _, _, client = _client(tmp_path)  # no image client
    resp = client.post("/api/styles/ukiyo-e/preview")
    assert resp.status_code == 400


def test_preview_generates_and_serves_image(tmp_path):
    fake_client = FakeImageClient()
    _, ctx, client = _client(tmp_path, image_client=fake_client)
    resp = client.post("/api/styles/ukiyo-e/preview")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    # generation runs in a background thread; wait for it to finish
    for _ in range(50):
        if client.get("/api/styles/ukiyo-e/preview-status").json()["status"] == "ready":
            break
        time.sleep(0.02)
    assert "woodblock" in fake_client.prompts[0].lower()   # used the style's prompt
    img = client.get("/api/styles/ukiyo-e/preview.png")
    assert img.status_code == 200
    assert img.content == b"PREVIEWPNG"


def test_block_species_removes_and_persists(tmp_path):
    from datetime import datetime as _dt
    store, ctx, client = _client(tmp_path)
    store.add_detection(Detection(_dt(2026, 7, 5, 7), "Podiceps cristatus", "Great Crested Grebe", 0.86))
    resp = client.post("/api/block", json={"name": "Great Crested Grebe"})
    assert resp.status_code == 200
    assert resp.json()["removed_detections"] == 1
    assert "Great Crested Grebe" in ctx.config.blocked_species
    # purged from the data
    assert all(s.common_name != "Great Crested Grebe"
               for s in store.species_for_day(_dt(2026, 7, 5, 12)))
    # persisted + unblock works
    assert "Great Crested Grebe" in Config.load(ctx.config.path).blocked_species
    client.post("/api/unblock", json={"name": "Great Crested Grebe"})
    assert ctx.config.blocked_species == []
