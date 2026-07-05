"""Thread orchestration and the shared runtime state (no rumps/macOS here)."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable


class Runtime:
    def __init__(self, config, store, detector, artist, publisher,
                 now: Callable[[], datetime] = datetime.now):
        self.config = config
        self.store = store
        self.detector = detector
        self.artist = artist
        self.publisher = publisher
        self.now = now
        self.new_species_today = False
        self.last_post: datetime | None = None
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
        rt.new_species_today = False
        rt.last_post = None
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
                self.store.add_detection(det)
                if det.common_name not in self._seen_today:
                    self._seen_today.add(det.common_name)
                    self.new_species_today = True

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

    def post_now(self, when: datetime | None = None) -> str:
        when = when or self.now()
        rec = self.artist.generate(when)
        with open(rec.path, "rb") as fh:
            result = self.publisher.publish(fh.read())
        if result.status == "posted":
            self.store.mark_posted(rec.id, when)
        self.last_post = when
        self.new_species_today = False
        return result.status

    def species_today(self):
        return self.store.species_for_day(self.now())
