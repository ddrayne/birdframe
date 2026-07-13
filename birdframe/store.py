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
    source_day: str | None = None
    style_reason: str = ""
    art_profile: dict | None = None


_ISO = "%Y-%m-%dT%H:%M:%S"


def _pack_time_species(counts: dict[str, int], limit: int = 8) -> dict:
    """Compact a time bucket while preserving how many voices it contained."""
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "species_count": len(ranked),
        "species": [{"common_name": name, "count": count}
                    for name, count in ranked[:limit]],
    }


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
            # Read-only dashboard exploration grows much faster than the original
            # day view. These indexes do not alter a detection; they keep species
            # dossiers and date-range charts responsive as the archive reaches
            # hundreds of thousands of rows.
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_det_species_ts"
                " ON detections(common_name, ts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_det_day_species"
                " ON detections(day, common_name)"
            )
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
            # Art-direction provenance is additive: old archives remain valid,
            # while new editions can explain the day they portray and why their
            # visual language was chosen.
            image_columns = {r["name"] for r in self._conn.execute(
                "PRAGMA table_info(images)").fetchall()}
            for name, definition in (
                ("source_day", "TEXT"),
                ("style_reason", "TEXT NOT NULL DEFAULT ''"),
                ("art_profile", "TEXT"),
            ):
                if name not in image_columns:
                    self._conn.execute(f"ALTER TABLE images ADD COLUMN {name} {definition}")

    def backup_to(self, path: Path) -> None:
        """Write a transactionally consistent copy, including committed WAL data."""
        destination = sqlite3.connect(str(path))
        try:
            with self._lock:
                self._conn.backup(destination)
            result = destination.execute("PRAGMA quick_check").fetchone()
            if not result or result[0] != "ok":
                raise sqlite3.DatabaseError("backup failed SQLite quick_check")
        finally:
            destination.close()

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

    def hours_for_day(self, when: datetime, species_names=None) -> list[int]:
        """24-hour activity for a day, optionally limited to an assessed set.

        This is a read-only lens over existing detections. Passing an empty set
        intentionally produces an empty clock rather than falling back to all.
        """
        rows = self._conn.execute(
            "SELECT ts, common_name FROM detections WHERE day = ?",
            (when.strftime("%Y-%m-%d"),),
        ).fetchall()
        allowed = None if species_names is None else set(species_names)
        hours = [0] * 24
        for row in rows:
            if allowed is None or row["common_name"] in allowed:
                hours[int(row["ts"][11:13])] += 1
        return hours

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
        """Every species ever heard: first/last date, total count, best confidence,
        earliest & latest time-of-day heard, and the hour it's most active."""
        rows = self._conn.execute(
            "SELECT common_name, scientific_name, MIN(day) AS first_day,"
            " MAX(day) AS last_day, COUNT(*) AS total, MAX(confidence) AS best,"
            " COUNT(DISTINCT day) AS days,"
            " MIN(substr(ts, 12, 5)) AS earliest, MAX(substr(ts, 12, 5)) AS latest"
            " FROM detections GROUP BY common_name ORDER BY first_day, common_name"
        ).fetchall()
        # peak hour per species (a small extra pass; datasets are modest)
        peak = {}
        for r in self._conn.execute(
                "SELECT common_name, substr(ts,12,2) AS hh, COUNT(*) n"
                " FROM detections GROUP BY common_name, hh").fetchall():
            cur = peak.get(r["common_name"])
            if cur is None or r["n"] > cur[1]:
                peak[r["common_name"]] = (int(r["hh"]), r["n"])
        out = []
        for r in rows:
            d = dict(r)
            d["peak_hour"] = peak.get(r["common_name"], (0, 0))[0]
            out.append(d)
        return out

    def species_with_any_clip(self) -> set[str]:
        rows = self._conn.execute("SELECT DISTINCT common_name FROM clips").fetchall()
        return {r["common_name"] for r in rows}

    def best_clip_for_species(self, common_name: str) -> dict | None:
        """The clearest recording of a species across all days (highest confidence)."""
        r = self._conn.execute(
            "SELECT day, path, confidence FROM clips WHERE common_name = ?"
            " ORDER BY confidence DESC LIMIT 1", (common_name,)).fetchone()
        return dict(r) if r else None

    def clips_for_species(self, common_name: str) -> list[dict]:
        """Every saved best-of-day clip for a species, newest first."""
        rows = self._conn.execute(
            "SELECT day, confidence, path, ts FROM clips WHERE common_name = ?"
            " ORDER BY day DESC", (common_name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def clips_for_day(self, day: str) -> list[dict]:
        """Saved clips for a day, clearest first."""
        rows = self._conn.execute(
            "SELECT common_name, scientific_name, confidence, path, ts"
            " FROM clips WHERE day = ? ORDER BY confidence DESC, common_name",
            (day,),
        ).fetchall()
        return [dict(r) for r in rows]

    def activity_matrix(self, days: int = 14) -> list[dict]:
        """Recent day × hour detection counts — a heatmap of when the garden sings."""
        recent_days = [r["day"] for r in self._conn.execute(
            "SELECT DISTINCT day FROM detections ORDER BY day DESC LIMIT ?", (days,)).fetchall()]
        recent_days = sorted(recent_days)
        idx = {d: i for i, d in enumerate(recent_days)}
        grid = [[0] * 24 for _ in recent_days]
        if recent_days:
            rows = self._conn.execute(
                "SELECT day, substr(ts,12,2) AS hh, COUNT(*) n FROM detections"
                " WHERE day >= ? GROUP BY day, hh", (recent_days[0],)).fetchall()
            for r in rows:
                if r["day"] in idx:
                    grid[idx[r["day"]]][int(r["hh"])] += r["n"]
        return [{"day": d, "hours": grid[i]} for i, d in enumerate(recent_days)]

    def species_detail(self, common_name: str) -> dict | None:
        """Everything about one species: its activity clock, span, and daily counts."""
        rows = self._conn.execute(
            "SELECT ts, day, confidence FROM detections WHERE common_name = ? ORDER BY ts",
            (common_name,)).fetchall()
        if not rows:
            return None
        hours = [0] * 24
        daily: dict[str, int] = {}
        for r in rows:
            hours[int(r["ts"][11:13])] += 1
            daily[r["day"]] = daily.get(r["day"], 0) + 1
        sci = self._conn.execute(
            "SELECT scientific_name FROM detections WHERE common_name=? LIMIT 1",
            (common_name,)).fetchone()["scientific_name"]
        return {
            "common_name": common_name, "scientific_name": sci,
            "total": len(rows), "days": len(daily),
            "first_day": rows[0]["day"], "last_day": rows[-1]["day"],
            "earliest": min(r["ts"][11:16] for r in rows),   # earliest time-of-day ever heard
            "latest": max(r["ts"][11:16] for r in rows),     # latest time-of-day ever heard
            "best_confidence": max(r["confidence"] for r in rows),
            "hours": hours,
            "daily": [{"day": d, "n": daily[d]} for d in sorted(daily)],
        }

    def species_dossier(self, common_name: str, start_day: str | None = None) -> dict | None:
        """Longitudinal aggregates for one species without changing raw rows.

        ``start_day`` scopes charts and observations while lifetime first/last
        remain available to the caller through ``species_detail``/life-list data.
        Counts are BirdNET detections, deliberately not inferred bird counts.
        """
        where = "common_name = ?"
        params: list[object] = [common_name]
        if start_day:
            where += " AND day >= ?"
            params.append(start_day)

        summary = self._conn.execute(
            "SELECT common_name, MIN(scientific_name) AS scientific_name,"
            " COUNT(*) AS total, COUNT(DISTINCT day) AS days,"
            " MIN(day) AS first_day, MAX(day) AS last_day,"
            " MIN(substr(ts,12,5)) AS earliest, MAX(substr(ts,12,5)) AS latest,"
            " MAX(confidence) AS best_confidence, AVG(confidence) AS avg_confidence"
            f" FROM detections WHERE {where}", params,
        ).fetchone()
        if summary is None or not summary["total"]:
            return None

        hours = [0] * 24
        for r in self._conn.execute(
                "SELECT CAST(substr(ts,12,2) AS INTEGER) AS hour, COUNT(*) AS n"
                f" FROM detections WHERE {where} GROUP BY hour", params).fetchall():
            hours[r["hour"]] = r["n"]

        daily_rows = self._conn.execute(
            "SELECT day, COUNT(*) AS detections, MAX(confidence) AS best_confidence,"
            " AVG(confidence) AS avg_confidence, MIN(substr(ts,12,5)) AS first_time,"
            " MAX(substr(ts,12,5)) AS last_time"
            f" FROM detections WHERE {where} GROUP BY day ORDER BY day", params,
        ).fetchall()

        confidence = [0] * 10
        for r in self._conn.execute(
                "SELECT confidence" f" FROM detections WHERE {where}", params).fetchall():
            confidence[min(9, max(0, int(r["confidence"] * 10)))] += 1

        # A companion means both species appeared in the same 15-minute soundscape
        # bucket. It is an exploratory relationship, not a biological claim.
        companion_params: list[object] = [common_name]
        target_where = "common_name = ?"
        if start_day:
            target_where += " AND day >= ?"
            companion_params.append(start_day)
        companions = self._conn.execute(
            "WITH target AS ("
            " SELECT DISTINCT day, substr(ts,12,2) AS hh,"
            " CAST(CAST(substr(ts,15,2) AS INTEGER) / 15 AS INTEGER) AS quarter"
            f" FROM detections WHERE {target_where}"
            ") SELECT d.common_name, MIN(d.scientific_name) AS scientific_name,"
            " COUNT(DISTINCT d.day || substr(d.ts,12,2) ||"
            " CAST(CAST(substr(d.ts,15,2) AS INTEGER) / 15 AS INTEGER)) AS shared_windows"
            " FROM detections d JOIN target t ON d.day=t.day"
            " AND substr(d.ts,12,2)=t.hh"
            " AND CAST(CAST(substr(d.ts,15,2) AS INTEGER) / 15 AS INTEGER)=t.quarter"
            " WHERE d.common_name != ?"
            + (" AND d.day >= ?" if start_day else "") +
            " GROUP BY d.common_name ORDER BY shared_windows DESC, d.common_name LIMIT 8",
            companion_params + [common_name] + ([start_day] if start_day else []),
        ).fetchall()

        return {
            **dict(summary),
            "hours": hours,
            "confidence_histogram": confidence,
            "daily": [dict(r) for r in daily_rows],
            "companions": [dict(r) for r in companions],
        }

    def species_observations(self, common_name: str, limit: int = 100,
                             before: str | None = None,
                             start_day: str | None = None) -> list[dict]:
        """Newest raw detection rows for a species, cursor-paginated by timestamp."""
        params: list[object] = [common_name]
        extra = ""
        if before:
            extra = " AND ts < ?"
            params.append(before)
        if start_day:
            extra += " AND day >= ?"
            params.append(start_day)
        params.append(max(1, min(int(limit), 250)))
        rows = self._conn.execute(
            "SELECT id, ts, day, confidence FROM detections"
            " WHERE common_name = ?" + extra + " ORDER BY ts DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def species_image_appearances(self, common_name: str, limit: int = 24) -> list[dict]:
        """Generated artworks whose stored species list contains this species."""
        rows = self._conn.execute(
            "SELECT id, generated_at, source_day, style, species, posted_at FROM images"
            " ORDER BY generated_at DESC"
        ).fetchall()
        out = []
        for r in rows:
            try:
                names = json.loads(r["species"])
            except (TypeError, json.JSONDecodeError):
                names = []
            if common_name in names:
                item = dict(r)
                item["species"] = names
                out.append(item)
                if len(out) >= limit:
                    break
        return out

    def images_for_day(self, day: str) -> list[dict]:
        """Generated artworks for a journal day, newest first."""
        rows = self._conn.execute(
            "SELECT id, generated_at, source_day, style, species, posted_at FROM images"
            " WHERE COALESCE(source_day, substr(generated_at,1,10)) = ?"
            " ORDER BY generated_at DESC",
            (day,),
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["species"] = json.loads(item["species"])
            except (TypeError, json.JSONDecodeError):
                item["species"] = []
            out.append(item)
        return out

    def journal_days(self, limit: int = 90) -> list[dict]:
        """Compact newest-first day summaries for the field journal index."""
        day_rows = self._conn.execute(
            "SELECT day, COUNT(*) AS detections, COUNT(DISTINCT common_name) AS species,"
            " MIN(substr(ts,12,5)) AS first_time, MAX(substr(ts,12,5)) AS last_time"
            " FROM detections GROUP BY day ORDER BY day DESC LIMIT ?",
            (max(1, min(int(limit), 366)),),
        ).fetchall()
        days = [r["day"] for r in day_rows]
        if not days:
            return []
        placeholders = ",".join("?" for _ in days)
        species_rows = self._conn.execute(
            "SELECT day, common_name, MIN(scientific_name) AS scientific_name,"
            " COUNT(*) AS count, MAX(confidence) AS best_confidence"
            f" FROM detections WHERE day IN ({placeholders})"
            " GROUP BY day, common_name ORDER BY day DESC, count DESC",
            days,
        ).fetchall()
        by_day: dict[str, list[dict]] = {d: [] for d in days}
        for r in species_rows:
            by_day[r["day"]].append(dict(r))

        first_rows = self._conn.execute(
            "SELECT common_name, MIN(day) AS first_day FROM detections GROUP BY common_name"
        ).fetchall()
        debuts: dict[str, list[str]] = {d: [] for d in days}
        for r in first_rows:
            if r["first_day"] in debuts:
                debuts[r["first_day"]].append(r["common_name"])

        image_rows = self._conn.execute(
            "SELECT id, COALESCE(source_day, substr(generated_at,1,10)) AS day,"
            " generated_at, style, posted_at"
            f" FROM images WHERE COALESCE(source_day, substr(generated_at,1,10))"
            f" IN ({placeholders})"
            " ORDER BY generated_at DESC", days,
        ).fetchall()
        images: dict[str, list[dict]] = {d: [] for d in days}
        for r in image_rows:
            images[r["day"]].append(dict(r))

        return [{
            **dict(r),
            "top_species": by_day[r["day"]][:5],
            "new_species": sorted(debuts[r["day"]]),
            "images": images[r["day"]],
        } for r in day_rows]

    def day_detail(self, day: str) -> dict | None:
        """A complete historical day assembled from existing detections."""
        rows = self._conn.execute(
            "SELECT ts, scientific_name, common_name, confidence"
            " FROM detections WHERE day = ? ORDER BY ts", (day,),
        ).fetchall()
        if not rows:
            return None
        species = self._aggregate(rows)
        hours = [0] * 24
        quarters = [0] * 96
        hour_voices: list[dict[str, int]] = [{} for _ in range(24)]
        quarter_voices: list[dict[str, int]] = [{} for _ in range(96)]
        for r in rows:
            hour = int(r["ts"][11:13])
            minute = int(r["ts"][14:16])
            quarter = hour * 4 + minute // 15
            hours[hour] += 1
            quarters[quarter] += 1
            name = r["common_name"]
            hour_voices[hour][name] = hour_voices[hour].get(name, 0) + 1
            quarter_voices[quarter][name] = quarter_voices[quarter].get(name, 0) + 1
        return {
            "day": day,
            "detections": len(rows),
            "species_count": len(species),
            "first_detection": {
                "at": rows[0]["ts"][11:19], "common_name": rows[0]["common_name"],
                "scientific_name": rows[0]["scientific_name"],
            },
            "last_detection": {
                "at": rows[-1]["ts"][11:19], "common_name": rows[-1]["common_name"],
                "scientific_name": rows[-1]["scientific_name"],
            },
            "hours": hours,
            "quarters": quarters,
            "hour_species": [_pack_time_species(bucket) for bucket in hour_voices],
            "quarter_species": [_pack_time_species(bucket) for bucket in quarter_voices],
            "species": species,
        }

    def pattern_summary(self, start_day: str | None = None,
                        species_names: list[str] | None = None) -> dict:
        """Range/tier-filterable aggregates for the Patterns view."""
        clauses = []
        params: list[object] = []
        if start_day:
            clauses.append("day >= ?")
            params.append(start_day)
        if species_names is not None:
            if not species_names:
                return {"totals": {"species": 0, "detections": 0, "days": 0, "since": None},
                        "hours": [0] * 24, "hour_species": [], "daily": [],
                        "heatmap": [], "by_species": []}
            placeholders = ",".join("?" for _ in species_names)
            clauses.append(f"common_name IN ({placeholders})")
            params.extend(species_names)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""

        total = self._conn.execute(
            "SELECT COUNT(DISTINCT common_name) AS species, COUNT(*) AS detections,"
            " COUNT(DISTINCT day) AS days, MIN(day) AS since FROM detections" + where,
            params,
        ).fetchone()
        hours = [0] * 24
        for r in self._conn.execute(
                "SELECT CAST(substr(ts,12,2) AS INTEGER) AS hour, COUNT(*) AS n"
                " FROM detections" + where + " GROUP BY hour", params).fetchall():
            hours[r["hour"]] = r["n"]
        daily = [dict(r) for r in self._conn.execute(
            "SELECT day, COUNT(DISTINCT common_name) AS species, COUNT(*) AS detections"
            " FROM detections" + where + " GROUP BY day ORDER BY day", params,
        ).fetchall()]
        by_species = [dict(r) for r in self._conn.execute(
            "SELECT common_name, MIN(scientific_name) AS scientific_name,"
            " COUNT(*) AS detections, COUNT(DISTINCT day) AS days,"
            " MAX(confidence) AS best_confidence, MAX(day) AS last_day"
            " FROM detections" + where +
            " GROUP BY common_name ORDER BY detections DESC, common_name", params,
        ).fetchall()]
        rhythms = {row["common_name"]: [0] * 24 for row in by_species}
        hour_voices: list[dict[str, int]] = [{} for _ in range(24)]
        for r in self._conn.execute(
                "SELECT common_name, CAST(substr(ts,12,2) AS INTEGER) AS hour,"
                " COUNT(*) AS n FROM detections" + where +
                " GROUP BY common_name, hour", params).fetchall():
            rhythms[r["common_name"]][r["hour"]] = r["n"]
            hour_voices[r["hour"]][r["common_name"]] = r["n"]
        for row in by_species:
            row["hours"] = rhythms[row["common_name"]]

        heatmap = []
        for d in daily[-30:]:
            heatmap.append({"day": d["day"], "hours": [0] * 24,
                            "species": [None] * 24})
        heat_idx = {r["day"]: r for r in heatmap}
        if heatmap:
            heat_clauses = list(clauses) + ["day >= ?"]
            heat_params = list(params) + [heatmap[0]["day"]]
            heat_where = " WHERE " + " AND ".join(heat_clauses)
            heat_voices = {r["day"]: [{} for _ in range(24)] for r in heatmap}
            for r in self._conn.execute(
                    "SELECT day, CAST(substr(ts,12,2) AS INTEGER) AS hour,"
                    " common_name, COUNT(*) AS n FROM detections" + heat_where +
                    " GROUP BY day, hour, common_name",
                    heat_params).fetchall():
                if r["day"] in heat_idx:
                    heat_idx[r["day"]]["hours"][r["hour"]] += r["n"]
                    heat_voices[r["day"]][r["hour"]][r["common_name"]] = r["n"]
            for row in heatmap:
                row["species"] = [_pack_time_species(bucket, limit=5)
                                  for bucket in heat_voices[row["day"]]]
        return {"totals": dict(total), "hours": hours,
                "hour_species": [_pack_time_species(bucket) for bucket in hour_voices],
                "daily": daily, "heatmap": heatmap, "by_species": by_species}

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

    def detection_count(self, start_day: str | None = None) -> int:
        """Cheap denominator for date-scoped shares without building chart data."""
        if start_day:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM detections WHERE day >= ?", (start_day,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM detections").fetchone()
        return int(row["n"])

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

    def add_image(self, generated_at, path, style, prompt, species,
                  source_day: str | None = None, style_reason: str = "",
                  art_profile: dict | None = None) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO images (generated_at, path, style, prompt, species,"
                " source_day, style_reason, art_profile) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (generated_at.strftime(_ISO), path, style, prompt, json.dumps(species),
                 source_day or generated_at.strftime("%Y-%m-%d"), style_reason,
                 json.dumps(art_profile) if art_profile is not None else None),
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
            source_day=r["source_day"] or r["generated_at"][:10],
            style_reason=r["style_reason"] or "",
            art_profile=json.loads(r["art_profile"]) if r["art_profile"] else None,
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
