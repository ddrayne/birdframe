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
                 clips_dir=None, backup_dir=None, on_first_ever=None, notify=None):
        self.config = config
        self.store = store
        self.detector = detector
        self.artist = artist
        self.publisher = publisher
        self.now = now
        self.clips_dir = Path(clips_dir) if clips_dir else None
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self.on_first_ever = on_first_ever    # callback(common_name) for notifications
        self.notify = notify or (lambda title, msg: None)
        self.new_species_today = False
        # Rehydrate from the store so a mid-day restart doesn't re-fire a
        # schedule slot that already posted.
        self.last_post: datetime | None = store.last_posted_at() if store else None
        self.last_detection_at: datetime | None = None
        self._pending_post_id: int | None = None
        self.status = "starting"
        self._seen_today: set[str] = set()
        self._today = now().date()
        self._started = now()
        self._last_backup_day = None
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
        rt.backup_dir = None
        rt.on_first_ever = None
        rt.notify = lambda title, msg: None
        rt.new_species_today = False
        rt.last_post = None
        rt.last_detection_at = None
        rt._pending_post_id = None
        rt.status = "starting"
        rt._seen_today = set()
        rt._today = now().date()
        rt._started = now()
        rt._last_backup_day = None
        rt._lock = threading.Lock()
        return rt

    def should_restart_for_freshness(self, now: datetime) -> bool:
        """True once a day at the configured quiet hour, after a few hours up —
        a clean self-restart bounds any slow resource creep (memory, TF state).
        The LaunchAgent brings it right back."""
        hour = getattr(self.config, "daily_restart_hour", -1)
        if hour is None or hour < 0:
            return False
        up_hours = (now - self._started).total_seconds() / 3600
        return now.hour == hour and up_hours >= 3

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
        from birdframe.scheduler import SchedulerState, parse_slots
        c = self.config
        return SchedulerState(
            mode=c.post_mode,
            slots=parse_slots(getattr(c, "post_times", ""), c.post_time),
            last_post=self.last_post,
            live_min_gap_minutes=c.live_min_gap_minutes,
            live_window_start=c.live_window_start, live_window_end=c.live_window_end,
            new_species_today=self.new_species_today,
        )

    def tick(self, now: datetime | None = None) -> None:
        from birdframe.scheduler import decide
        now = now or self.now()
        self.ensure_backup(now)
        decision = decide(self.scheduler_state(now), now)
        if decision:
            trigger, slot = decision
            self.scheduled_post(now, trigger, slot)
        else:
            self.retry_pending_post(now)      # keep trying a frame that was down

    def scheduled_post(self, when: datetime, trigger: str,
                       slot: tuple[str, str] | None) -> str:
        """An automatic post (schedule slot or live edition), with the guards a
        manual 'Post now' deliberately skips: never repost an unchanged picture,
        and never replace a real painting with a fallback poster."""
        # Handled up front: a skipped or failed slot must not re-fire every tick.
        self.last_post = when
        label = slot[1] if slot else ""
        rec = self.artist.generate(
            when, trigger="scheduled" if trigger == "daily" else "live",
            slot_label=label)
        if rec is None:
            return "nothing to post"          # no reliable birds yet
        edition = label or (slot[0] if slot else "live")
        if rec.posted_at is not None:
            # The artist reused the picture already on the frame — same birds.
            self.notify("Nothing new to post",
                        f"The {edition} edition was skipped — same birds as the "
                        "picture already on the frame.")
            return "unchanged"
        if "(fallback)" in rec.style and self.store.real_posted_on_day(
                when.strftime("%Y-%m-%d")):
            # Budget spent or the painter failed; a poster never covers a painting.
            self.notify("Kept today's painting on the frame",
                        f"The {edition} edition would have been a text poster, "
                        "so it was skipped.")
            return "kept painting"
        with open(rec.path, "rb") as fh:
            result = self.publisher.publish(fh.read())
        if result.status == "posted":
            self.store.mark_posted(rec.id, when)
            self._pending_post_id = None
        elif result.status == "unreachable":
            self._pending_post_id = rec.id    # retry on later ticks until it lands
            self.notify("Couldn't reach the frame",
                        "The picture is saved and will post itself when the frame returns.")
        self.new_species_today = False
        return result.status

    def ensure_backup(self, now: datetime | None = None):
        """Create at most one consistent database snapshot per calendar day."""
        if self.backup_dir is None:
            return None
        now = now or self.now()
        if self._last_backup_day == now.date():
            return None
        from birdframe.backups import create_daily_backup
        try:
            path, created = create_daily_backup(
                self.store, self.backup_dir, now,
                keep_days=getattr(self.config, "backup_keep_days", 30),
            )
            self._last_backup_day = now.date()
            if created:
                log.info("Database backup created: %s", path)
            return path
        except Exception as exc:
            log.warning("Database backup failed: %s", exc)
            return None

    def retry_pending_post(self, now: datetime | None = None) -> str | None:
        """If an automatic post couldn't reach the frame, quietly retry it (on
        each tick) until the frame reappears — so a dropped connection self-heals."""
        pending = getattr(self, "_pending_post_id", None)
        if pending is None:
            return None
        now = now or self.now()
        rec = self.store.get_image(pending)
        if rec is None:
            self._pending_post_id = None
            return None
        with open(rec.path, "rb") as fh:
            result = self.publisher.publish(fh.read(), force=True)
        if result.status in ("posted", "held"):
            if result.status == "posted":
                self.store.mark_posted(rec.id, now)
                self.notify("Picture posted 🐦", "The frame came back — today's picture is up.")
            self._pending_post_id = None
        return result.status

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
            self._pending_post_id = None
        elif result.status == "unreachable":
            self._pending_post_id = rec.id    # retry on later ticks until it lands
            self.notify("Couldn't reach the frame",
                        "Today's picture is saved and will post itself when the frame returns.")
        self.last_post = when
        self.new_species_today = False
        return result.status

    def species_today(self):
        return self.store.species_for_day(self.now())
