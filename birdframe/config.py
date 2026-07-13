"""User settings, persisted as TOML. Secrets live in the Keychain, not here."""
from __future__ import annotations

from dataclasses import dataclass, asdict, fields
from pathlib import Path

import tomlkit

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "birdframe" / "config.toml"

DEFAULTS = {
    "latitude": 55.95,
    "longitude": -3.19,
    "input_device": "",            # "" = system default input
    "confidence_threshold": 0.55,
    "geo_floor": 0.03,             # light sanity gate; marginal species are shown but marked tentative
    "blocked_species": [],         # common names you've vetoed as "not here"
    "chunk_seconds": 15.0,
    "chunk_overlap_seconds": 1.5,
    "post_mode": "daily",          # daily | live | manual
    "post_time": "21:00",
    "live_min_gap_minutes": 120,
    "live_window_start": "08:00",
    "live_window_end": "22:00",
    "frame_url": "http://pi-inky-impression.local:5000",
    "frame_hold_minutes": 0,       # 0 = don't hold the shared frame (a hold also blocks birdframe's own next post)
    "frame_saturation": 0.6,
    "style_mode": "responsive",    # responsive | rotate | pinned
    "pinned_style": "",
    "openai_model": "gpt-image-2",  # current flagship image model
    "image_quality": "high",
    "min_species_for_image": 1,    # below this, post the free poster (no paid call)
    "max_paid_images_per_day": 1,  # hard cap on paid gpt-image-1 calls per day
    "capture_window_minutes": 60,  # 'capture current birds' looks back this far
    "archive_keep_days": 0,        # prune generated images older than this (0 = keep all)
    "backup_keep_days": 30,        # daily online SQLite snapshots (0 = keep forever)
    "daily_restart_hour": 4,       # self-restart at this hour to bound resource creep (-1 = never)
    "min_species_confidence": 0.0,   # hard hide floor; 0 = show everything, marked by reliability tier
    "dashboard_port": 8355,
}


@dataclass
class Config:
    latitude: float
    longitude: float
    input_device: str
    confidence_threshold: float
    geo_floor: float
    blocked_species: list
    chunk_seconds: float
    chunk_overlap_seconds: float
    post_mode: str
    post_time: str
    live_min_gap_minutes: int
    live_window_start: str
    live_window_end: str
    frame_url: str
    frame_hold_minutes: int
    frame_saturation: float
    style_mode: str
    pinned_style: str
    openai_model: str
    image_quality: str
    min_species_for_image: int
    max_paid_images_per_day: int
    capture_window_minutes: int
    archive_keep_days: int
    backup_keep_days: int
    daily_restart_hour: int
    min_species_confidence: float
    dashboard_port: int
    path: Path = DEFAULT_CONFIG_PATH

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "Config":
        path = Path(path)
        values = dict(DEFAULTS)
        if path.exists():
            parsed = tomlkit.parse(path.read_text())
            known = {f.name for f in fields(cls)} - {"path"}
            for key, val in parsed.items():
                if key in known:
                    # Unwrap tomlkit's typed items to plain Python, so the values
                    # round-trip cleanly (asdict can't rebuild a tomlkit Array).
                    values[key] = val.unwrap() if hasattr(val, "unwrap") else val
        return cls(path=path, **values)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = tomlkit.document()
        data = asdict(self)
        data.pop("path")
        for key, val in data.items():
            doc[key] = val
        self.path.write_text(tomlkit.dumps(doc))
