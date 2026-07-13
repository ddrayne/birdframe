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

    def generate(self, when, force_paid=False, species_days=None,
                 style_name=None, force_new=False, created_at=None):
        self.calls += 1
        self.forced.append(force_paid)
        self.species_days_arg = species_days
        self.style_name_arg = style_name
        self.force_new_arg = force_new
        self.when_arg = when
        self.created_at_arg = created_at
        self.out_path.write_bytes(b"PNGBYTES")
        artist = self
        names = [s.common_name for s in species_days] if species_days is not None else ["European Robin"]

        class R:
            id = 1
            path = str(artist.out_path)
            style = style_name or "ukiyo-e"
            species = names
        return R()

    def art_direction(self, when, species_days=None):
        return {
            "day": when.strftime("%Y-%m-%d"),
            "profile": {
                "species_count": 1, "detection_count": 1, "dominant_share": 1.0,
                "evenness": 0, "hours": [0] * 6 + [1] + [0] * 17,
                "dawn_share": 1.0, "dusk_share": 0, "night_share": 0,
                "active_span_hours": 1, "debut_count": 1, "season": "summer",
                "weather": "clear", "archetype": "Singular voice",
                "tags": ["summer", "dawn-heavy"], "summary": "A singular dawn voice.",
            },
            "species": [{"common_name": "European Robin", "scientific_name": "Erithacus rubecula",
                         "count": 1, "first_heard": "06:00", "last_heard": "06:00",
                         "best_confidence": .9}],
            "recommendations": [{"name": "ukiyo-e", "score": 10,
                                 "matched": ["summer"], "reason": "It suits summer."}],
        }


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
                     styles_dir=styles_dir, preview_dir=tmp_path / "previews",
                     backup_dir=tmp_path / "backups")
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
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200 and favicon.headers["content-type"] == "image/png"


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
    resp2 = client.post("/api/settings", json={"chunk_seconds": 5.0})  # not in editable list
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
    assert ctx.config.style_mode == "responsive"


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


def test_today_annotates_reliability_and_sorts_tentative_last(tmp_path):
    from datetime import datetime as _dt
    store = Store(tmp_path / "db.sqlite")
    # a solid blackbird and an implausible, confident "grebe"
    for h in range(3):
        store.add_detection(Detection(_dt(2026, 7, 5, 6, h), "Turdus merula", "Eurasian Blackbird", 0.95))
    store.add_detection(Detection(_dt(2026, 7, 5, 7), "Podiceps cristatus", "Great Crested Grebe", 0.86))
    ctx = AppContext(store=store, artist=FakeArtist(tmp_path / "i.png"),
                     publisher=FakePublisher(), now=lambda: _dt(2026, 7, 5, 12),
                     config=Config.load(tmp_path / "c.toml"),
                     geo_lookup={"Turdus merula": 0.97, "Podiceps cristatus": 0.048})
    client = TestClient(create_app(ctx))
    data = client.get("/api/today").json()
    names = [s["common_name"] for s in data["species"]]
    assert names[0] == "Eurasian Blackbird"          # confirmed first
    assert names[-1] == "Great Crested Grebe"         # tentative last
    grebe = data["species"][-1]
    assert grebe["tier"] == "tentative"
    assert "unusual for this area" in grebe["reasons"]
    black = data["species"][0]
    assert black["tier"] == "confirmed"


def test_census_and_export(tmp_path):
    from datetime import datetime as _dt
    store = Store(tmp_path / "db.sqlite")
    store.add_detection(Detection(_dt(2026, 6, 1, 6), "Turdus merula", "Eurasian Blackbird", 0.9))
    store.add_detection(Detection(_dt(2026, 7, 5, 7), "Turdus merula", "Eurasian Blackbird", 0.95))
    store.add_detection(Detection(_dt(2026, 7, 5, 8), "Erithacus rubecula", "European Robin", 0.8))
    ctx = AppContext(store=store, artist=FakeArtist(tmp_path / "i.png"),
                     publisher=FakePublisher(), now=lambda: _dt(2026, 7, 5, 12),
                     config=Config.load(tmp_path / "c.toml"),
                     geo_lookup={"Turdus merula": 0.97, "Erithacus rubecula": 0.7})
    client = TestClient(create_app(ctx))
    c = client.get("/api/census").json()
    assert c["totals"]["species"] == 2
    assert c["totals"]["detections"] == 3
    assert len(c["hours"]) == 24
    bb = next(e for e in c["life_list"] if e["common_name"] == "Eurasian Blackbird")
    assert bb["first_day"] == "2026-06-01" and bb["total"] == 2 and bb["days"] == 2
    assert bb["tier"] == "confirmed"
    csv = client.get("/api/export.csv")
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    assert "Eurasian Blackbird" in csv.text


def test_journal_index_and_historical_day_are_addressable(tmp_path):
    from datetime import datetime as _dt
    store, ctx, client = _client(tmp_path)
    store.add_detection(Detection(_dt(2026, 7, 5, 7), "Turdus merula", "Eurasian Blackbird", 0.92))
    journal = client.get("/api/journal").json()
    assert journal["days"][0]["day"] == "2026-07-05"
    assert journal["days"][0]["detections"] == 2
    day = client.get("/api/day/2026-07-05").json()
    assert day["species_count"] == 2
    assert len(day["quarters"]) == 96 and len(day["hours"]) == 24
    assert len(day["quarter_species"]) == 96 and len(day["hour_species"]) == 24
    assert {s["common_name"] for s in day["species"]} == {"European Robin", "Eurasian Blackbird"}
    assert client.get("/api/day/not-a-date").status_code == 400


def test_species_dossier_exposes_detail_without_changing_rows(tmp_path):
    from datetime import datetime as _dt
    store, ctx, client = _client(tmp_path)
    store.add_detection(Detection(_dt(2026, 7, 5, 6, 5), "Erithacus rubecula", "European Robin", 0.8))
    before = store.totals()["detections"]
    dossier = client.get("/api/species/European Robin").json()
    assert dossier["total"] == 2
    assert dossier["daily"][0]["detections"] == 2
    assert len(dossier["confidence_histogram"]) == 10
    assert "observations" in dossier and "images" in dossier and "companions" in dossier
    assert dossier["rank"] == 1 and dossier["share"] == 1.0
    rows = client.get("/api/species/European Robin/detections?limit=1").json()
    assert len(rows["detections"]) == 1
    assert store.totals()["detections"] == before       # every view is read-only


def test_patterns_filters_reliability_layers_without_deleting_data(tmp_path):
    from datetime import datetime as _dt
    store = Store(tmp_path / "db.sqlite")
    for minute in range(3):
        store.add_detection(Detection(_dt(2026, 7, 5, 6, minute), "Turdus merula", "Eurasian Blackbird", 0.95))
    store.add_detection(Detection(_dt(2026, 7, 5, 7), "Podiceps cristatus", "Great Crested Grebe", 0.86))
    ctx = AppContext(store=store, artist=FakeArtist(tmp_path / "i.png"),
                     publisher=FakePublisher(), now=lambda: _dt(2026, 7, 5, 12),
                     config=Config.load(tmp_path / "c.toml"),
                     geo_lookup={"Turdus merula": 0.97, "Podiceps cristatus": 0.048})
    client = TestClient(create_app(ctx))
    all_rows = client.get("/api/patterns").json()
    solid = client.get("/api/patterns?tiers=confirmed").json()
    assert all_rows["totals"]["detections"] == 4
    assert solid["totals"]["detections"] == 3
    assert solid["by_species"][0]["common_name"] == "Eurasian Blackbird"
    assert store.totals()["detections"] == 4


def test_health_endpoint(tmp_path):
    _, ctx, client = _client(tmp_path)
    h = client.get("/api/health").json()
    assert "listening" in h and "openai_key_set" in h
    assert h["openai_key_set"] is False       # no image client in fixture
    assert "archive_bytes" in h and "species_today" in h
    assert "backup_count" in h and "backup_latest" in h


def test_manual_backup_endpoint_creates_restore_point(tmp_path):
    _, _, client = _client(tmp_path)
    response = client.post("/api/backup")
    assert response.status_code == 200
    body = response.json()
    assert body["created"].startswith("birdframe-2026-07-05-")
    assert body["bytes"] > 0
    health = client.get("/api/health").json()
    assert health["backup_count"] == 1
    assert health["backup_latest"] == body["created"]


def test_generate_creates_gallery_image_without_posting(tmp_path):
    store, ctx, client = _client(tmp_path)
    resp = client.post("/api/generate", json={"style": "linocut"})
    assert resp.status_code == 200 and resp.json()["status"] == "started"
    for _ in range(50):
        st = client.get("/api/generate/status").json()
        if st["state"] == "done":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and st["image_id"] == 1
    assert ctx.artist.style_name_arg == "linocut"   # style threaded through
    assert ctx.artist.force_new_arg is True          # fresh entry for the studio
    assert ctx.publisher.published == []             # NOT posted to the frame


def test_art_direction_and_historical_generation_are_day_addressable(tmp_path):
    _, ctx, client = _client(tmp_path)
    direction = client.get("/api/art-direction/2026-07-05")
    assert direction.status_code == 200
    assert direction.json()["profile"]["archetype"] == "Singular voice"
    assert direction.json()["recommendations"][0]["name"] == "ukiyo-e"
    assert direction.json()["editions"] == []

    response = client.post(
        "/api/generate", json={"style": "linocut", "day": "2026-07-05"})
    assert response.status_code == 200
    for _ in range(50):
        status = client.get("/api/generate/status").json()
        if status["state"] == "done":
            break
        time.sleep(.02)
    assert ctx.artist.when_arg.date().isoformat() == "2026-07-05"
    assert ctx.artist.created_at_arg == datetime(2026, 7, 5, 12)
    assert client.post("/api/generate", json={"day": "2026-07-06"}).status_code == 400


def test_style_metadata_and_mode_api(tmp_path):
    _, ctx, client = _client(tmp_path)
    response = client.put("/api/styles/new", json={
        "name": "Garden Clock", "prompt": "A clock of {scene}.", "avoid": "labels",
        "collection": "Data Portraits", "description": "Time becomes form.",
        "lineage": "phenology", "medium": "screenprint", "palette": "indigo",
        "affinities": ["dawn-heavy"], "source": "https://example.com",
    })
    assert response.status_code == 200
    style = next(s for s in client.get("/api/styles").json()["styles"]
                 if s["name"] == "garden-clock")
    assert style["collection"] == "Data Portraits"
    assert style["affinities"] == ["dawn-heavy"]
    assert client.post("/api/styles/mode/rotate").json()["mode"] == "rotate"
    assert ctx.config.style_mode == "rotate"


def test_post_image_async_publishes_and_marks(tmp_path):
    from datetime import datetime as _dt
    store, ctx, client = _client(tmp_path)
    img_id = store.add_image(_dt(2026, 7, 5, 12), str(tmp_path / "x.png"), "linocut", "p", ["Robin"])
    (tmp_path / "x.png").write_bytes(b"PNG")
    resp = client.post(f"/api/post/{img_id}")
    assert resp.json()["status"] == "started"
    for _ in range(50):
        st = client.get("/api/post/status").json()
        if st["state"] == "done":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and st["publish"] == "posted"
    assert ctx.publisher.forced[-1] is True           # explicit post forces override
    assert store.get_image(img_id).posted_at is not None


def test_post_missing_image_404(tmp_path):
    _, _, client = _client(tmp_path)
    assert client.post("/api/post/999").status_code == 404


def test_history_flags_on_frame(tmp_path):
    from datetime import datetime as _dt
    store, ctx, client = _client(tmp_path)
    a = store.add_image(_dt(2026, 7, 5, 10), "/a.png", "s", "p", ["A"])
    b = store.add_image(_dt(2026, 7, 5, 11), "/b.png", "s", "p", ["B"])
    store.mark_posted(a, _dt(2026, 7, 5, 10, 5))
    store.mark_posted(b, _dt(2026, 7, 5, 11, 5))       # b posted more recently
    imgs = {i["id"]: i for i in client.get("/api/history").json()["images"]}
    assert imgs[b]["on_frame"] is True
    assert imgs[a]["on_frame"] is False


def test_species_extra_reference_audio_and_range_map(tmp_path, mocker):
    _, ctx, client = _client(tmp_path)

    class Resp:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    def fake_get(url, **kw):
        if "page/summary/" in url:
            return Resp({"title": "Common blackbird"})
        if "page/media-list/" in url:
            return Resp({"items": [
                {"type": "image", "title": "File:Status_iucn_3.1_LC.svg"},   # filtered out
                {"type": "audio", "title": "File:A_random_wingbeat.ogg"},
                {"type": "audio", "title": "File:Common_Blackbird_song_(Turdus_merula).ogg"},
                {"type": "image", "title": "File:Turdus_merula_distribution_map.png"},
            ]})
        if "api.gbif.org" in url:
            return Resp({"usageKey": 2490719})
        raise AssertionError("unexpected url " + url)

    mocker.patch("httpx.get", side_effect=fake_get)
    d = client.get("/api/species-extra/Turdus merula").json()
    # prefers the 'song' recording over the earlier wingbeat clip
    assert d["reference_audio"].endswith("Common_Blackbird_song_%28Turdus_merula%29.ogg")
    assert d["reference_title"] == "Common Blackbird song (Turdus merula)"
    # a real distribution map, not the IUCN status badge
    assert d["range_map"].endswith("Turdus_merula_distribution_map.png?width=640")
    assert d["gbif_url"] == "https://www.gbif.org/species/2490719"


def test_species_extra_survives_missing_data(tmp_path, mocker):
    _, ctx, client = _client(tmp_path)
    mocker.patch("httpx.get", side_effect=RuntimeError("network down"))
    d = client.get("/api/species-extra/Nonexistent species").json()
    assert d == {"reference_audio": None, "reference_title": None,
                 "range_map": None, "gbif_url": None}


def test_frame_status_proxy(tmp_path, mocker):
    _, ctx, client = _client(tmp_path)
    import birdframe.web.app as appmod
    mocker.patch.object(appmod.__dict__.setdefault("httpx", __import__("httpx")), "get",
                        return_value=mocker.Mock(status_code=200,
                                                 json=lambda: {"busy": False, "source": "birdframe"}))
    d = client.get("/api/frame/status").json()
    assert d["reachable"] is True and d["source"] == "birdframe"
