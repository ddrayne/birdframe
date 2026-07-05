"""SQLite persistence for detections and generated images."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Detection:
    timestamp: datetime
    scientific_name: str
    common_name: str
    confidence: float


@dataclass
class SpeciesDay:
    common_name: str
    scientific_name: str
    count: int
    first_heard: datetime
    last_heard: datetime
    peak_hour: int
    best_confidence: float


@dataclass
class ImageRecord:
    id: int
    generated_at: datetime
    path: str
    style: str
    prompt: str
    species: list[str]
    posted_at: datetime | None


_ISO = "%Y-%m-%dT%H:%M:%S"


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._conn:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY,
                    ts TEXT NOT NULL,
                    day TEXT NOT NULL,
                    scientific_name TEXT NOT NULL,
                    common_name TEXT NOT NULL,
                    confidence REAL NOT NULL)"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_det_day ON detections(day)")
            # Best audio clip per species per day (a recording you can listen to).
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS clips (
                    day TEXT NOT NULL,
                    common_name TEXT NOT NULL,
                    scientific_name TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    path TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    PRIMARY KEY (day, common_name))"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    path TEXT NOT NULL,
                    style TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    species TEXT NOT NULL,
                    posted_at TEXT)"""
            )

    def add_detection(self, det: Detection) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO detections (ts, day, scientific_name, common_name, confidence)"
                " VALUES (?, ?, ?, ?, ?)",
                (det.timestamp.strftime(_ISO), det.timestamp.strftime("%Y-%m-%d"),
                 det.scientific_name, det.common_name, det.confidence),
            )

    @staticmethod
    def _aggregate(rows, min_confidence: float = 0.0) -> list[SpeciesDay]:
        """Roll raw detection rows up into per-species summaries, most-heard first.

        A species is only included if its *best* detection clears min_confidence,
        so a one-off low-confidence guess (a classic BirdNET false positive) is
        dropped from what we report — without deleting the raw data."""
        agg: dict[str, dict] = {}
        for r in rows:
            ts = datetime.strptime(r["ts"], _ISO)
            a = agg.setdefault(r["common_name"], {
                "scientific_name": r["scientific_name"], "count": 0,
                "first": ts, "last": ts, "best": 0.0, "hours": {},
            })
            a["count"] += 1
            a["first"] = min(a["first"], ts)
            a["last"] = max(a["last"], ts)
            a["best"] = max(a["best"], r["confidence"])
            a["hours"][ts.hour] = a["hours"].get(ts.hour, 0) + 1
        result = [
            SpeciesDay(
                common_name=name, scientific_name=a["scientific_name"], count=a["count"],
                first_heard=a["first"], last_heard=a["last"],
                peak_hour=max(a["hours"], key=a["hours"].get), best_confidence=a["best"],
            )
            for name, a in agg.items()
            if a["best"] >= min_confidence
        ]
        result.sort(key=lambda s: s.count, reverse=True)
        return result

    def species_for_day(self, when: datetime, min_confidence: float = 0.0) -> list[SpeciesDay]:
        rows = self._conn.execute(
            "SELECT ts, scientific_name, common_name, confidence FROM detections WHERE day = ?",
            (when.strftime("%Y-%m-%d"),),
        ).fetchall()
        return self._aggregate(rows, min_confidence)

    def species_in_window(self, start: datetime, end: datetime,
                          min_confidence: float = 0.0) -> list[SpeciesDay]:
        """Species heard within an arbitrary [start, end] window — powers the
        'capture current birds' snapshot of the recent live soundscape."""
        rows = self._conn.execute(
            "SELECT ts, scientific_name, common_name, confidence FROM detections"
            " WHERE ts >= ? AND ts <= ?",
            (start.strftime(_ISO), end.strftime(_ISO)),
        ).fetchall()
        return self._aggregate(rows, min_confidence)

    def recent_detections(self, limit: int = 50, min_confidence: float = 0.0) -> list[Detection]:
        """The most recent individual detections, newest first — the live feed."""
        rows = self._conn.execute(
            "SELECT ts, scientific_name, common_name, confidence FROM detections"
            " WHERE confidence >= ? ORDER BY ts DESC, id DESC LIMIT ?",
            (min_confidence, limit),
        ).fetchall()
        return [
            Detection(datetime.strptime(r["ts"], _ISO), r["scientific_name"],
                      r["common_name"], r["confidence"])
            for r in rows
        ]

    def activity_buckets(self, start: datetime, end: datetime, n: int = 24,
                         min_confidence: float = 0.0) -> list[int]:
        """Detection counts split into n equal time buckets across [start, end] —
        a little sparkline of the recent rhythm of song."""
        rows = self._conn.execute(
            "SELECT ts FROM detections WHERE ts >= ? AND ts <= ? AND confidence >= ?",
            (start.strftime(_ISO), end.strftime(_ISO), min_confidence),
        ).fetchall()
        span = max(1.0, (end - start).total_seconds())
        buckets = [0] * n
        for r in rows:
            ts = datetime.strptime(r["ts"], _ISO)
            idx = int((ts - start).total_seconds() / span * n)
            buckets[min(n - 1, max(0, idx))] += 1
        return buckets

    def best_clip_confidence(self, day: str, common_name: str) -> float | None:
        r = self._conn.execute(
            "SELECT confidence FROM clips WHERE day = ? AND common_name = ?",
            (day, common_name),
        ).fetchone()
        return r["confidence"] if r else None

    def upsert_clip(self, day, common_name, scientific_name, confidence, path, ts) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO clips (day, common_name, scientific_name, confidence, path, ts)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(day, common_name) DO UPDATE SET"
                "   confidence=excluded.confidence, path=excluded.path, ts=excluded.ts,"
                "   scientific_name=excluded.scientific_name",
                (day, common_name, scientific_name, confidence, path, ts.strftime(_ISO)),
            )

    def clip_path(self, day: str, common_name: str) -> str | None:
        r = self._conn.execute(
            "SELECT path FROM clips WHERE day = ? AND common_name = ?",
            (day, common_name),
        ).fetchone()
        return r["path"] if r else None

    def species_with_clips(self, day: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT common_name FROM clips WHERE day = ?", (day,)
        ).fetchall()
        return {r["common_name"] for r in rows}

    def delete_species(self, common_name: str) -> int:
        """Purge all recorded detections (and clips) of a species (a vetoed false positive)."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM clips WHERE common_name = ?", (common_name,))
            cur = self._conn.execute(
                "DELETE FROM detections WHERE common_name = ?", (common_name,))
            return cur.rowcount

    def life_list(self) -> list[dict]:
        """Every species ever heard: first/last date, total count, best confidence."""
        rows = self._conn.execute(
            "SELECT common_name, scientific_name, MIN(day) AS first_day,"
            " MAX(day) AS last_day, COUNT(*) AS total, MAX(confidence) AS best,"
            " COUNT(DISTINCT day) AS days"
            " FROM detections GROUP BY common_name ORDER BY first_day, common_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def hour_histogram(self) -> list[int]:
        """All-time detection counts by hour of day (0–23) — the daily rhythm."""
        buckets = [0] * 24
        for r in self._conn.execute("SELECT ts FROM detections").fetchall():
            buckets[datetime.strptime(r["ts"], _ISO).hour] += 1
        return buckets

    def daily_counts(self, limit: int = 60) -> list[dict]:
        rows = self._conn.execute(
            "SELECT day, COUNT(DISTINCT common_name) AS species, COUNT(*) AS detections"
            " FROM detections GROUP BY day ORDER BY day DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def totals(self) -> dict:
        r = self._conn.execute(
            "SELECT COUNT(DISTINCT common_name) AS species, COUNT(*) AS detections,"
            " COUNT(DISTINCT day) AS days, MIN(day) AS since FROM detections"
        ).fetchone()
        return dict(r)

    def all_detections(self):
        """Every detection, oldest first — for CSV export."""
        return self._conn.execute(
            "SELECT ts, common_name, scientific_name, confidence FROM detections ORDER BY ts"
        ).fetchall()

    def last_detection_time(self) -> datetime | None:
        r = self._conn.execute("SELECT MAX(ts) AS ts FROM detections").fetchone()
        return datetime.strptime(r["ts"], _ISO) if r and r["ts"] else None

    def first_ever(self, common_name: str) -> bool:
        """True if this species has never been detected before (a life-list first)."""
        r = self._conn.execute(
            "SELECT 1 FROM detections WHERE common_name = ? LIMIT 1", (common_name,)
        ).fetchone()
        return r is None

    def first_ever_on_day(self, when: datetime) -> set[str]:
        """Species whose earliest-ever detection date is this day."""
        day = when.strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT common_name, MIN(day) AS first_day FROM detections GROUP BY common_name"
        ).fetchall()
        return {r["common_name"] for r in rows if r["first_day"] == day}

    def add_image(self, generated_at, path, style, prompt, species) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO images (generated_at, path, style, prompt, species)"
                " VALUES (?, ?, ?, ?, ?)",
                (generated_at.strftime(_ISO), path, style, prompt, json.dumps(species)),
            )
            return cur.lastrowid

    def get_image(self, image_id: int) -> ImageRecord | None:
        r = self._conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if r is None:
            return None
        return ImageRecord(
            id=r["id"], generated_at=datetime.strptime(r["generated_at"], _ISO),
            path=r["path"], style=r["style"], prompt=r["prompt"],
            species=json.loads(r["species"]),
            posted_at=datetime.strptime(r["posted_at"], _ISO) if r["posted_at"] else None,
        )

    def count_paid_images_for_day(self, when: datetime) -> int:
        """Images generated on this day via a real (paid) render — fallback
        posters are labelled '... (fallback)' and are free, so exclude them."""
        day = when.strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM images WHERE substr(generated_at, 1, 10) = ?"
            " AND style NOT LIKE '%(fallback)%'",
            (day,),
        ).fetchone()
        return row["n"]

    def recent_images(self, limit: int = 50) -> list[ImageRecord]:
        rows = self._conn.execute(
            "SELECT id FROM images ORDER BY generated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self.get_image(r["id"]) for r in rows]

    def mark_posted(self, image_id: int, when: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE images SET posted_at = ? WHERE id = ?",
                (when.strftime(_ISO), image_id),
            )
