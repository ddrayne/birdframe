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


def test_new_species_flag_resets_next_day(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    det = FakeDetector([])
    rt = Runtime.for_test(store=store, detector=det, now=lambda: datetime(2026, 7, 5, 23))
    rt.new_species_today = True
    rt.roll_day(datetime(2026, 7, 6, 0, 1))  # crosses midnight into a new day
    assert rt.new_species_today is False
