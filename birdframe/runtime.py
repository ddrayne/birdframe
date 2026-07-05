"""Thread orchestration and the shared runtime state (no rumps/macOS here)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from birdframe.styles import slugify

log = logging.getLogger("birdframe")


class Runtime:
    def __init__(self, config, store, detector, artist, publisher,
                 now: Callable[[], datetime] = datetime.now,
                 clips_dir=None, on_first_ever=None):
        self.config = config
        self.store = store
        self.detector = detector
        self.artist = artist
        self.publisher = publisher
        self.now = now
        self.clips_dir = Path(clips_dir) if clips_dir else None
        self.on_first_ever = on_first_ever    # callback(common_name) for notifications
        self.new_species_today = False
        self.last_post: datetime | None = None
        self.last_detection_at: datetime | None = None
        self.status = "starting"
        self._seen_today: set[str] = set()
        self._today = now().date()
        self._lock = threading.Lock()

    @classmethod
    def for_test(cls, store, detector, now):
        rt = cls.__new__(cls)
        rt.config = None
        rt.store = store
        rt.detector = detector
        rt.artist = None
        rt.publisher = None
        rt.now = now
        rt.clips_dir = None
        rt.on_first_ever = None
        rt.new_species_today = False
        rt.last_post = None
        rt.last_detection_at = None
        rt.status = "starting"
        rt._seen_today = set()
        rt._today = now().date()
        rt._lock = threading.Lock()
        return rt

    def on_chunk(self, audio, when: datetime) -> None:
        self.roll_day(when)
        dets = self.detector.predict_chunk(audio, self.detector.sample_rate, when)
        with self._lock:
            for det in dets:
                first_ever = self.store.first_ever(det.common_name)
                self.store.add_detection(det)
                self.last_detection_at = when
                self._save_clip(audio, det, when)
                if det.common_name not in self._seen_today:
                    self._seen_today.add(det.common_name)
                    self.new_species_today = True
                    if first_ever and self.on_first_ever:
                        try:
                            self.on_first_ever(det.common_name)
                        except Exception:
                            pass

    def _save_clip(self, audio, det, when: datetime) -> None:
        """Keep the best-sounding clip per species per day, so you can listen back."""
        if self.clips_dir is None:
            return
        day = when.strftime("%Y-%m-%d")
        best = self.store.best_clip_confidence(day, det.common_name)
        if best is not None and det.confidence <= best:
            return
        try:
            import soundfile as sf
            day_dir = self.clips_dir / day
            day_dir.mkdir(parents=True, exist_ok=True)
            path = day_dir / f"{slugify(det.common_name)}.ogg"
            sf.write(str(path), audio, self.detector.sample_rate,
                     format="OGG", subtype="VORBIS")
            self.store.upsert_clip(day, det.common_name, det.scientific_name,
                                   det.confidence, str(path), when)
        except Exception as exc:  # never let clip-saving break detection
            log.warning("Could not save clip for %s: %s", det.common_name, exc)

    def roll_day(self, when: datetime) -> None:
        if when.date() != self._today:
            self._today = when.date()
            self._seen_today = set()
            self.new_species_today = False

    def scheduler_state(self, now: datetime):
        from birdframe.scheduler import SchedulerState
        c = self.config
        return SchedulerState(
            mode=c.post_mode, post_time=c.post_time, last_post=self.last_post,
            live_min_gap_minutes=c.live_min_gap_minutes,
            live_window_start=c.live_window_start, live_window_end=c.live_window_end,
            new_species_today=self.new_species_today,
        )

    def tick(self, now: datetime | None = None) -> None:
        from birdframe.scheduler import decide
        now = now or self.now()
        if decide(self.scheduler_state(now), now):
            self.post_now(now)

    def post_now(self, when: datetime | None = None, force_paid: bool = False) -> str:
        when = when or self.now()
        rec = self.artist.generate(when, force_paid=force_paid)
        if rec is None:
            return "nothing to post"          # no birds, or nothing changed
        with open(rec.path, "rb") as fh:
            # An explicit user post (force_paid) also overrides any frame hold.
            result = self.publisher.publish(fh.read(), force=force_paid)
        if result.status == "posted":
            self.store.mark_posted(rec.id, when)
        self.last_post = when
        self.new_species_today = False
        return result.status

    def species_today(self):
        return self.store.species_for_day(self.now())
