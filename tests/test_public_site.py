"""The public site: what it publishes, what it never does, and how it's rebuilt."""
import io
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image

from birdframe.public_site import SitePublisher, build_site, deploy
from birdframe.store import Detection, Store
from birdframe.styles import Style


def _png(path: Path) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (1200, 1600), (60, 110, 80)).save(buf, format="PNG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())
    return str(path)


def _archive(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    for minute in range(6):                  # a well-supported robin
        store.add_detection(Detection(datetime(2026, 7, 5, 6, minute), "Erithacus rubecula",
                                      "European Robin", 0.93))
    store.add_detection(Detection(datetime(2026, 7, 6, 7, 0), "Erithacus rubecula",
                                  "European Robin", 0.9))
    store.add_detection(Detection(datetime(2026, 7, 5, 7, 0), "Podiceps cristatus",
                                  "Great Crested Grebe", 0.88))       # implausible here
    store.upsert_clip("2026-07-05", "European Robin", "Erithacus rubecula", 0.93,
                      "/private/clip.ogg", datetime(2026, 7, 5, 6))
    painting = store.add_image(datetime(2026, 7, 5, 21), _png(tmp_path / "images" / "2026-07-05-210000-000000.png"),
                               "linocut", "A linocut of an Edinburgh garden", ["European Robin"],
                               style_reason="Chosen by you for this edition.",
                               art_profile={"archetype": "Singular voice", "tags": ["sparse"]},
                               trigger="scheduled")
    store.mark_posted(painting, datetime(2026, 7, 5, 21))
    store.add_image(datetime(2026, 7, 6, 21), _png(tmp_path / "images" / "2026-07-06-210000-000000.png"),
                    "linocut (fallback)", "poster", ["European Robin"], trigger="scheduled")
    return store


def _data(out: Path) -> dict:
    page = (out / "index.html").read_text()
    return json.loads(page.split('type="application/json">', 1)[1].split("</script>", 1)[0])


STYLES = [Style("linocut", "A linocut of {scene}.", collection="Print Traditions", medium="linocut")]
GEO = {"Erithacus rubecula": 0.9, "Podiceps cristatus": 0.04}


def test_site_publishes_paintings_and_trusted_birds_only(tmp_path):
    store, out = _archive(tmp_path), tmp_path / "site"
    summary = build_site(store, STYLES, out, place="Edinburgh", geo_lookup=GEO,
                         now=datetime(2026, 7, 6, 22))
    assert summary["paintings"] == 1 and summary["species"] == 1
    data = _data(out)
    assert [s["name"] for s in data["species"]] == ["European Robin"]   # no implausible grebe
    painting = data["paintings"][0]
    assert painting["frame"] is True and painting["style"] == "Linocut"
    assert painting["reason"] == "Chosen by hand for this painting."     # not "by you"
    assert painting["character"].startswith("Singular voice")
    assert sorted(p.name for p in (out / "images").iterdir()) == [
        f"2026-07-05-210000-000000-{w}.{ext}" for w in (1200, 480, 960)
        for ext in [Path(painting["images"]["480"]).suffix[1:]]]
    assert json.loads((out / "art" / f"{painting['id']}.json").read_text())["prompt"].startswith("A linocut")
    everything = "".join(p.read_text(errors="ignore") for p in out.rglob("*")
                         if p.suffix in (".html", ".json", ".js", ".css"))
    for private in ("Podiceps", "55.95", "clip.ogg", "fallback", "Great Crested Grebe"):
        assert private not in everything, private
    assert "The Edinburgh Window" in (out / "index.html").read_text()


def test_rebuild_reuses_images_and_drops_ones_no_longer_archived(tmp_path):
    store, out = _archive(tmp_path), tmp_path / "site"
    build_site(store, STYLES, out, geo_lookup=GEO)
    image = next((out / "images").iterdir())
    before = image.stat().st_mtime_ns
    build_site(store, STYLES, out, geo_lookup=GEO)
    assert image.stat().st_mtime_ns == before                  # not re-encoded
    (tmp_path / "images" / "2026-07-05-210000-000000.png").unlink()
    build_site(store, STYLES, out, geo_lookup=GEO)
    assert list((out / "images").iterdir()) == [] and list((out / "art").iterdir()) == []


def test_an_empty_journal_still_builds_a_page(tmp_path):
    out = tmp_path / "site"
    summary = build_site(Store(tmp_path / "db.sqlite"), STYLES, out, place="Boston")
    assert summary.pop("fingerprint")
    assert summary == {"paintings": 0, "species": 0, "days": 0, "path": str(out)}
    assert "The Boston Window" in (out / "index.html").read_text()
    assert "immutable" in (out / "_headers").read_text()     # cache rules for Pages/Netlify


def test_fingerprint_changes_with_the_birds_not_the_clock(tmp_path):
    store, out = _archive(tmp_path), tmp_path / "site"
    first = build_site(store, STYLES, out, geo_lookup=GEO, now=datetime(2026, 7, 6, 22))
    again = build_site(store, STYLES, out, geo_lookup=GEO, now=datetime(2026, 7, 6, 23))
    assert again["fingerprint"] == first["fingerprint"]
    store.add_detection(Detection(datetime(2026, 7, 6, 23, 30), "Erithacus rubecula",
                                  "European Robin", 0.92))
    later = build_site(store, STYLES, out, geo_lookup=GEO, now=datetime(2026, 7, 6, 23))
    assert later["fingerprint"] != first["fingerprint"]
    art = next((out / "art").iterdir())
    before = art.stat().st_mtime_ns
    build_site(store, STYLES, out, geo_lookup=GEO, now=datetime(2026, 7, 6, 23))
    assert art.stat().st_mtime_ns == before            # unchanged files aren't rewritten


def test_deploy_never_runs_through_a_shell(tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    command = f'{sys.executable} -c "import sys; open(sys.argv[1] + \'/deployed\', \'w\')" {{dir}} ; touch pwned'
    deploy(out, command)                       # "; touch pwned" arrives as plain arguments
    assert (out / "deployed").exists()
    assert not (out / "pwned").exists() and not Path("pwned").exists()


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def test_publisher_rebuilds_for_new_paintings_and_hourly():
    clock, latest, builds = Clock(), [1], []
    publisher = SitePublisher(lambda: builds.append(1) or {"paintings": 1},
                              latest=lambda: latest[0], clock=clock)
    assert publisher.due()
    publisher.run_once()
    assert builds == [1] and publisher.status["paintings"] == 1 and publisher.status["error"] is None
    assert not publisher.due()                         # nothing new, too soon
    latest[0] = 2
    assert publisher.due()                             # a new painting
    publisher.run_once()
    clock.now += 3601
    assert publisher.due()                             # hourly refresh


def _uploading(tmp_path, clock, latest, fingerprint, uploads, fail=None):
    def upload():
        if fail and fail[0]:
            raise RuntimeError(fail[0])
        uploads.append(latest[0])
        return "https://window.pages.dev"
    return SitePublisher(lambda: {"paintings": 1, "fingerprint": fingerprint[0]},
                         latest=lambda: latest[0], deploy=upload, clock=clock,
                         state_path=tmp_path / "public-site.json")


def test_publisher_uploads_new_paintings_at_once_and_changes_every_few_hours(tmp_path):
    clock, latest, fingerprint, uploads = Clock(), [1], ["a"], []
    publisher = _uploading(tmp_path, clock, latest, fingerprint, uploads)
    publisher.run_once()
    assert uploads == [1] and publisher.status["url"] == "https://window.pages.dev"
    clock.now += 3601                                  # hourly rebuild, nothing changed
    publisher.run_once()
    assert uploads == [1]
    fingerprint[0] = "b"                               # birds heard, but only an hour on
    clock.now += 3601
    publisher.run_once()
    assert uploads == [1]
    clock.now += 5 * 3600                              # six hours since the last upload
    publisher.run_once()
    assert uploads == [1, 1]
    latest[0] = 2                                      # a new painting goes up at once
    assert publisher.due()
    publisher.run_once()
    assert uploads == [1, 1, 2]


def test_publisher_backs_off_after_a_failed_upload(tmp_path):
    clock, latest, uploads, fail = Clock(), [1], [], ["network is down"]
    publisher = _uploading(tmp_path, clock, latest, ["a"], uploads, fail)
    publisher.run_once()
    assert publisher.status["error"] == "network is down"
    clock.now += 30                                    # the scheduler's next beat
    assert not publisher.due()                         # no rebuild-and-upload loop
    clock.now += 1800
    fail[0] = None
    assert publisher.due()                             # the painting still owes an upload
    publisher.run_once()
    assert uploads == [1] and publisher.status["error"] is None


def test_publisher_remembers_its_last_upload_across_restarts(tmp_path):
    clock, latest, uploads = Clock(), [7], []
    _uploading(tmp_path, clock, latest, ["a"], uploads).run_once()
    restarted = _uploading(tmp_path, clock, latest, ["a"], uploads)
    assert restarted.status["url"] == "https://window.pages.dev"
    restarted.run_once()                               # rebuilds locally…
    assert uploads == [7]                              # …but a restart alone uploads nothing
    restarted.run_once(force_deploy=True)              # "Publish now" always sends
    assert uploads == [7, 7]


def test_publisher_records_a_failed_build_without_raising():
    def boom():
        raise RuntimeError("disk full")
    publisher = SitePublisher(boom, latest=lambda: 1)
    assert publisher.run_once() == {}
    assert publisher.status["error"] == "disk full" and not publisher.status["running"]
