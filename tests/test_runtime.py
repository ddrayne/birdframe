from datetime import datetime

from birdframe.runtime import Runtime
from birdframe.store import Store, Detection


class FakeDetector:
    sample_rate = 48000

    def __init__(self, dets):
        self._dets = dets

    def predict_chunk(self, audio, sr, when):
        return self._dets


def test_chunk_callback_records_detections_and_tracks_new_species(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    det = FakeDetector([Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9)])
    rt = Runtime.for_test(store=store, detector=det, now=lambda: datetime(2026, 7, 5, 6))
    rt.on_chunk(audio=b"", when=datetime(2026, 7, 5, 6))
    assert store.species_for_day(datetime(2026, 7, 5, 6))[0].common_name == "European Robin"
    assert rt.new_species_today is True


def test_repeated_species_does_not_reflag(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    det = FakeDetector([Detection(datetime(2026, 7, 5, 6), "Erithacus rubecula", "European Robin", 0.9)])
    rt = Runtime.for_test(store=store, detector=det, now=lambda: datetime(2026, 7, 5, 6))
    rt.on_chunk(audio=b"", when=datetime(2026, 7, 5, 6))
    rt.new_species_today = False  # pretend we posted
    rt.on_chunk(audio=b"", when=datetime(2026, 7, 5, 7))  # same species again
    assert rt.new_species_today is False


def test_saves_best_clip_and_notifies_first_ever(tmp_path):
    import numpy as np
    store = Store(tmp_path / "db.sqlite")

    class Det:
        sample_rate = 48000

        def predict_chunk(self, audio, sr, when):
            return [Detection(when, "Erithacus rubecula", "European Robin", 0.8)]

    firsts = []
    rt = Runtime.for_test(store=store, detector=Det(), now=lambda: datetime(2026, 7, 5, 6))
    rt.clips_dir = tmp_path / "clips"
    rt.on_first_ever = firsts.append
    audio = np.zeros(48000, dtype=np.float32)
    rt.on_chunk(audio=audio, when=datetime(2026, 7, 5, 6))
    # clip written and recorded
    clip = store.clip_path("2026-07-05", "European Robin")
    assert clip is not None and (tmp_path / "clips").exists()
    from pathlib import Path
    assert Path(clip).exists()
    assert store.best_clip_confidence("2026-07-05", "European Robin") == 0.8
    assert firsts == ["European Robin"]      # notified once, first-ever


def test_failed_post_retries_until_frame_returns(tmp_path):
    from datetime import datetime as _dt
    store = Store(tmp_path / "db.sqlite")
    img = tmp_path / "pic.png"; img.write_bytes(b"PNG")
    rec_id = store.add_image(_dt(2026, 7, 8, 21), str(img), "linocut", "p", ["Robin"])

    class Art:
        def generate(self, when, force_paid=False):
            return store.get_image(rec_id)

    class Pub:
        def __init__(self): self.result = "unreachable"; self.calls = 0
        def publish(self, png, force=False): self.calls += 1; return _R(self.result)

    class _R:
        def __init__(self, s): self.status = s; self.detail = ""

    rt = Runtime.for_test(store=store, detector=None, now=lambda: _dt(2026, 7, 8, 21))
    rt.artist, rt.publisher = Art(), Pub()
    # scheduled post fails → becomes pending, not marked posted
    rt.post_now(_dt(2026, 7, 8, 21))
    assert rt._pending_post_id == rec_id
    assert store.get_image(rec_id).posted_at is None
    # a later tick retries; still down → stays pending
    rt.publisher.result = "unreachable"
    rt.retry_pending_post(_dt(2026, 7, 8, 21, 5))
    assert rt._pending_post_id == rec_id
    # frame returns → posts and clears the pending flag
    rt.publisher.result = "posted"
    rt.retry_pending_post(_dt(2026, 7, 8, 21, 10))
    assert rt._pending_post_id is None
    assert store.get_image(rec_id).posted_at is not None


def test_should_restart_for_freshness(tmp_path):
    from types import SimpleNamespace
    store = Store(tmp_path / "db.sqlite")

    class Det:
        sample_rate = 48000

        def predict_chunk(self, a, sr, w):
            return []

    rt = Runtime.for_test(store=store, detector=Det(), now=lambda: datetime(2026, 7, 8, 0))
    rt.config = SimpleNamespace(daily_restart_hour=4)
    rt._started = datetime(2026, 7, 8, 0)
    assert rt.should_restart_for_freshness(datetime(2026, 7, 8, 4, 0)) is True   # 4am, up 4h
    assert rt.should_restart_for_freshness(datetime(2026, 7, 8, 3, 0)) is False  # wrong hour
    assert rt.should_restart_for_freshness(datetime(2026, 7, 8, 4, 0)) is True
    rt._started = datetime(2026, 7, 8, 2, 30)                                    # up only 1.5h
    assert rt.should_restart_for_freshness(datetime(2026, 7, 8, 4, 0)) is False
    rt.config = SimpleNamespace(daily_restart_hour=-1)                           # disabled
    rt._started = datetime(2026, 7, 8, 0)
    assert rt.should_restart_for_freshness(datetime(2026, 7, 8, 4, 0)) is False


def test_new_species_flag_resets_next_day(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    det = FakeDetector([])
    rt = Runtime.for_test(store=store, detector=det, now=lambda: datetime(2026, 7, 5, 23))
    rt.new_species_today = True
    rt.roll_day(datetime(2026, 7, 6, 0, 1))  # crosses midnight into a new day
    assert rt.new_species_today is False


def test_runtime_ensures_one_daily_online_backup(tmp_path):
    from types import SimpleNamespace
    store = Store(tmp_path / "db.sqlite")
    rt = Runtime.for_test(
        store=store, detector=FakeDetector([]),
        now=lambda: datetime(2026, 7, 13, 12))
    rt.config = SimpleNamespace(backup_keep_days=30)
    rt.backup_dir = tmp_path / "backups"
    assert rt.ensure_backup(datetime(2026, 7, 13, 12)).exists()
    assert len(list(rt.backup_dir.glob("*.sqlite"))) == 1
    assert rt.ensure_backup(datetime(2026, 7, 13, 18)) is None
    assert len(list(rt.backup_dir.glob("*.sqlite"))) == 1


# ── scheduled posts: slot handling, poster guard, unchanged skip ─────────────

class _Res:
    def __init__(self, s): self.status = s; self.detail = ""


class _Pub:
    def __init__(self): self.calls = 0
    def publish(self, png, force=False): self.calls += 1; return _Res("posted")


def _sched_rt(tmp_path, artist, now, post_times="06:30 dawn, 21:00 evening"):
    from types import SimpleNamespace
    store = Store(tmp_path / "db.sqlite")
    rt = Runtime.for_test(store=store, detector=None, now=now)
    rt.artist, rt.publisher = artist, _Pub()
    rt.config = SimpleNamespace(
        post_mode="daily", post_times=post_times, post_time="21:00",
        live_min_gap_minutes=120, live_window_start="08:00",
        live_window_end="22:00", daily_restart_hour=-1, backup_keep_days=0,
    )
    notes = []
    rt.notify = lambda title, msg: notes.append(title)
    return store, rt, notes


def test_scheduled_poster_never_replaces_a_real_painting(tmp_path):
    """THE bug fix: budget spent → fallback poster generated → but a real
    painting already sits on the frame today, so the slot skips + notifies."""
    from datetime import datetime as _dt
    img = tmp_path / "poster.png"; img.write_bytes(b"PNG")

    store = None  # closed over below

    class Art:
        def generate(self, when, trigger="manual", slot_label="", **kw):
            rid = store.add_image(when, str(img), "riso (fallback)", "p", ["Robin"],
                                  trigger=trigger)
            return store.get_image(rid)

    store, rt, notes = _sched_rt(tmp_path, Art(), now=lambda: _dt(2026, 7, 5, 21, 0))
    # a real painting was posted at dawn
    real = store.add_image(_dt(2026, 7, 5, 6, 30), str(img), "linocut", "p", ["Robin"])
    store.mark_posted(real, _dt(2026, 7, 5, 6, 31))
    rt.tick(_dt(2026, 7, 5, 21, 0))
    assert rt.publisher.calls == 0                # poster NOT posted over the painting
    assert notes                                  # user was told why
    assert rt.last_post == _dt(2026, 7, 5, 21, 0) # slot handled; won't refire


def test_scheduled_poster_posts_on_an_empty_day(tmp_path):
    """First edition of a quiet day: nothing real posted yet → the poster still
    goes up (the frame never misses its daily report)."""
    from datetime import datetime as _dt
    img = tmp_path / "poster.png"; img.write_bytes(b"PNG")
    store = None

    class Art:
        def generate(self, when, trigger="manual", slot_label="", **kw):
            rid = store.add_image(when, str(img), "riso (fallback)", "p", ["Robin"],
                                  trigger=trigger)
            return store.get_image(rid)

    store, rt, notes = _sched_rt(tmp_path, Art(), now=lambda: _dt(2026, 7, 5, 6, 30))
    rt.tick(_dt(2026, 7, 5, 6, 30))
    assert rt.publisher.calls == 1


def test_unchanged_species_slot_skips_republish(tmp_path):
    """Artist reuse returned an already-posted painting → nothing new to say →
    skip quietly with a notification."""
    from datetime import datetime as _dt
    img = tmp_path / "pic.png"; img.write_bytes(b"PNG")
    store = None
    rec_holder = {}

    class Art:
        def generate(self, when, trigger="manual", slot_label="", **kw):
            return store.get_image(rec_holder["id"])   # the reuse path

    store, rt, notes = _sched_rt(tmp_path, Art(), now=lambda: _dt(2026, 7, 5, 21, 0))
    rec_holder["id"] = store.add_image(_dt(2026, 7, 5, 6, 30), str(img),
                                       "linocut", "p", ["Robin"])
    store.mark_posted(rec_holder["id"], _dt(2026, 7, 5, 6, 31))
    rt.tick(_dt(2026, 7, 5, 21, 0))
    assert rt.publisher.calls == 0
    assert notes
    # and the slot does not re-fire on the next tick
    rt.tick(_dt(2026, 7, 5, 21, 1))
    assert rt.publisher.calls == 0


def test_slot_label_threaded_to_artist(tmp_path):
    from datetime import datetime as _dt
    img = tmp_path / "pic.png"; img.write_bytes(b"PNG")
    store = None
    seen = {}

    class Art:
        def generate(self, when, trigger="manual", slot_label="", **kw):
            seen["trigger"], seen["label"] = trigger, slot_label
            rid = store.add_image(when, str(img), "linocut", "p", ["Robin"],
                                  trigger=trigger)
            return store.get_image(rid)

    store, rt, notes = _sched_rt(tmp_path, Art(), now=lambda: _dt(2026, 7, 5, 6, 30))
    rt.tick(_dt(2026, 7, 5, 6, 30))
    assert seen == {"trigger": "scheduled", "label": "dawn"}
    assert rt.publisher.calls == 1


def test_restart_rehydrates_last_post_from_store(tmp_path):
    """A mid-day restart must not re-fire an already-handled slot."""
    from datetime import datetime as _dt
    store = Store(tmp_path / "db.sqlite")
    img = tmp_path / "pic.png"; img.write_bytes(b"PNG")
    rid = store.add_image(_dt(2026, 7, 5, 6, 30), str(img), "linocut", "p", ["Robin"])
    store.mark_posted(rid, _dt(2026, 7, 5, 6, 31))

    class Art:
        def generate(self, **kw):
            raise AssertionError("should not generate — slot already handled")

    rt = Runtime(config=None, store=store, detector=None, artist=Art(),
                 publisher=None, now=lambda: _dt(2026, 7, 5, 7, 0))
    assert rt.last_post == _dt(2026, 7, 5, 6, 31)
