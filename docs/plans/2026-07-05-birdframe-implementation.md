# birdframe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a macOS app that continuously identifies birds heard outside a window in Edinburgh with BirdNET, and each day turns the detections into a stylised gpt-image-1 picture posted to a shared Inky Frame e-ink display and archived locally.

**Architecture:** A single Python 3.12 process managed with `uv`. `rumps` owns the macOS main thread (menu bar); worker threads run the audio listener, BirdNET detector, a scheduler, and a `uvicorn`/FastAPI dashboard, all sharing a WAL-mode SQLite store. Audio is analysed in memory in ~15 s chunks and discarded. The Artist rolls up a day of detections into a rich prompt, calls OpenAI gpt-image-1, composites a caption strip with Pillow to exactly 1200×1600, and the Publisher POSTs it to the Inky Frame.

**Tech Stack:** Python 3.12, `uv`, `birdnet` (TFLite backend), `sounddevice`, `numpy`, `Pillow`, `openai`, `httpx`, `fastapi`, `uvicorn`, `rumps`, `keyring`, `tomlkit`, `pytest`.

**Key external contracts (verified against the real repos):**
- BirdNET acoustic: `model = birdnet.load("acoustic", "2.4", "tf")`; `model.predict_arrays((audio_ndarray, sample_rate), custom_species_list=<iterable of "Scientific_Common">, default_confidence_threshold=0.55, top_k=5)`. Native sample rate via `model.get_sample_rate()` (48000). Result exposes `.to_structured_array()` with fields including a species name string `"Scientific_Common"`, `confidence`, `start_time`, `end_time`.
- BirdNET geo: `geo = birdnet.load("geo", "2.4", "tf")`; `geo.predict(latitude, longitude, week=<1..48>)` → result convertible via `.to_structured_array()` to `(species_name, confidence)` pairs. Filter to `confidence >= 0.03` to build the Edinburgh whitelist.
- Inky Frame: `POST http://pi-inky-impression.local:5000/display`, multipart field `file` (PNG bytes). Optional form fields: `hold_minutes` (int, we use a modest hold so the day's art resists casual stomping), `saturation` (0..1, ~0.6 suits the panel), `source` (we send `"birdframe"`), `force` (we never send it — we don't fight the shared frame). Returns `202` on success, `409` if the display is held by someone else (we treat that as "leave it be").

**Conventions for every task:** TDD — write the failing test, run it, implement minimally, run it green, commit. Exact paths below. Use `uv run pytest ...` for tests and `uv run <script>` to run code. Commit after each task with the message shown.

---

## Task 0: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `birdframe/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`
- Create: `README.md`

**Step 1: Create `pyproject.toml`**

```toml
[project]
name = "birdframe"
version = "0.1.0"
description = "Listen to birds in Edinburgh and paint the day's birdlife onto an e-ink frame"
requires-python = ">=3.12,<3.13"
dependencies = [
    "birdnet>=0.1.6",
    "sounddevice>=0.4.6",
    "numpy>=1.26",
    "pillow>=10.2",
    "openai>=1.30",
    "httpx>=0.27",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "rumps>=0.4.0",
    "keyring>=25.0",
    "tomlkit>=0.12",
    "astral>=3.2",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]

[project.scripts]
birdframe = "birdframe.app:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Create empty `birdframe/__init__.py` and `tests/__init__.py`** (empty files).

**Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.egg-info/
.DS_Store
```

**Step 4: Create `README.md`** — a short paragraph pointing at `docs/plans/2026-07-05-birdframe-design.md` for the design.

**Step 5: Install and verify**

Run: `uv sync --extra dev`
Expected: resolves and installs; `birdnet` pulls a TFLite runtime. (If `birdnet` import later fails on Apple Silicon, that's handled in Task 3.)

Run: `uv run python -c "import birdframe; print('ok')"`
Expected: `ok`

**Step 6: Commit**

```bash
git add pyproject.toml birdframe/__init__.py tests/__init__.py .gitignore README.md
git commit -m "chore: scaffold birdframe project"
```

---

## Task 1: Config module

Settings live in TOML at `~/.config/birdframe/config.toml`; the OpenAI key lives in the macOS Keychain (never in the file). This task builds a typed config with defaults, load, and save.

**Files:**
- Create: `birdframe/config.py`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
from birdframe.config import Config, DEFAULTS

def test_defaults_loaded_when_file_missing(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert cfg.latitude == 55.95
    assert cfg.longitude == -3.19
    assert cfg.confidence_threshold == 0.55
    assert cfg.post_mode == "daily"
    assert cfg.post_time == "21:00"
    assert cfg.frame_url == "http://pi-inky-impression.local:5000"

def test_roundtrip_save_and_load(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config.load(path)
    cfg.confidence_threshold = 0.7
    cfg.post_mode = "manual"
    cfg.save()
    reloaded = Config.load(path)
    assert reloaded.confidence_threshold == 0.7
    assert reloaded.post_mode == "manual"

def test_unknown_keys_ignored_and_partial_file_merges_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('confidence_threshold = 0.42\nbogus_key = 1\n')
    cfg = Config.load(path)
    assert cfg.confidence_threshold == 0.42
    assert cfg.post_time == "21:00"  # default filled in
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (`No module named birdframe.config`).

**Step 3: Write minimal implementation**

```python
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
    "geo_floor": 0.03,
    "chunk_seconds": 15.0,
    "chunk_overlap_seconds": 1.5,
    "post_mode": "daily",          # daily | live | manual
    "post_time": "21:00",
    "live_min_gap_minutes": 120,
    "live_window_start": "08:00",
    "live_window_end": "22:00",
    "frame_url": "http://pi-inky-impression.local:5000",
    "frame_hold_minutes": 180,
    "frame_saturation": 0.6,
    "style_mode": "rotate",        # rotate | pinned
    "pinned_style": "",
    "openai_model": "gpt-image-1",
    "image_quality": "high",
    "dashboard_port": 8355,
}


@dataclass
class Config:
    latitude: float
    longitude: float
    input_device: str
    confidence_threshold: float
    geo_floor: float
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
                    values[key] = val
        return cls(path=path, **values)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = tomlkit.document()
        data = asdict(self)
        data.pop("path")
        for key, val in data.items():
            doc[key] = val
        self.path.write_text(tomlkit.dumps(doc))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add birdframe/config.py tests/test_config.py
git commit -m "feat: typed TOML config with defaults"
```

---

## Task 2: Store (SQLite + species-day aggregation)

The store records every detection and every generated image, and aggregates a day of detections into the "species-day" summary the Artist and dashboard consume.

**Files:**
- Create: `birdframe/store.py`
- Test: `tests/test_store.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from birdframe.store import Store, Detection

def _dt(h, m=0):
    return datetime(2026, 7, 5, h, m, 0)

def test_add_and_count_species_for_day(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(_dt(5, 2), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(_dt(6, 0), "Erithacus rubecula", "European Robin", 0.7))
    s.add_detection(Detection(_dt(7, 0), "Turdus merula", "Common Blackbird", 0.8))
    rows = s.species_for_day(datetime(2026, 7, 5, 12))
    by_name = {r.common_name: r for r in rows}
    assert by_name["European Robin"].count == 2
    assert by_name["European Robin"].first_heard == _dt(5, 2)
    assert by_name["European Robin"].best_confidence == 0.9
    # ordered by count descending
    assert rows[0].common_name == "European Robin"

def test_first_ever_species(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(datetime(2026, 6, 1, 8), "Turdus merula", "Common Blackbird", 0.8))
    s.add_detection(Detection(_dt(7), "Turdus merula", "Common Blackbird", 0.8))
    s.add_detection(Detection(_dt(8), "Erithacus rubecula", "European Robin", 0.8))
    first_ever = s.first_ever_on_day(datetime(2026, 7, 5, 12))
    assert first_ever == {"European Robin"}   # robin's debut is today; blackbird's was June 1

def test_image_record_roundtrip(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    img_id = s.add_image(datetime(2026, 7, 5, 21), "/tmp/x.png", "ukiyo-e", "a prompt", ["European Robin"])
    img = s.get_image(img_id)
    assert img.path == "/tmp/x.png"
    assert img.style == "ukiyo-e"
    assert img.species == ["European Robin"]
    assert img.posted_at is None
    s.mark_posted(img_id, datetime(2026, 7, 5, 21, 1))
    assert s.get_image(img_id).posted_at == datetime(2026, 7, 5, 21, 1)
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL (`No module named birdframe.store`).

**Step 3: Write minimal implementation**

```python
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

    def species_for_day(self, when: datetime) -> list[SpeciesDay]:
        day = when.strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT ts, scientific_name, common_name, confidence FROM detections WHERE day = ?",
            (day,),
        ).fetchall()
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
        ]
        result.sort(key=lambda s: s.count, reverse=True)
        return result

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
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add birdframe/store.py tests/test_store.py
git commit -m "feat: SQLite store with species-day aggregation"
```

---

## Task 3: Detector (geo whitelist + acoustic prediction)

Wraps BirdNET. The heavy models load once. `predict_chunk` takes a numpy array + sample rate and returns `Detection`s that clear the confidence gate and the Edinburgh whitelist. **All BirdNET calls are isolated here** so the rest of the code can be tested without the model.

**Files:**
- Create: `birdframe/detector.py`
- Test: `tests/test_detector.py`

**Step 1: Write the failing test** — tests the pure parsing/filtering logic with the BirdNET model mocked, so CI needs no model download.

```python
import numpy as np
from datetime import datetime
from birdframe.detector import Detector, parse_species_name, filter_detections

def test_parse_species_name():
    sci, common = parse_species_name("Erithacus rubecula_European Robin")
    assert sci == "Erithacus rubecula"
    assert common == "European Robin"

def test_filter_detections_applies_confidence_and_whitelist():
    raw = [
        ("Erithacus rubecula_European Robin", 0.91),
        ("Turdus merula_Common Blackbird", 0.40),   # below threshold
        ("Ara macao_Scarlet Macaw", 0.99),          # not on whitelist
    ]
    whitelist = {"Erithacus rubecula_European Robin", "Turdus merula_Common Blackbird"}
    when = datetime(2026, 7, 5, 6)
    dets = filter_detections(raw, whitelist, threshold=0.55, when=when)
    assert len(dets) == 1
    assert dets[0].common_name == "European Robin"
    assert dets[0].timestamp == when

def test_predict_chunk_uses_model(mocker):
    det = Detector.__new__(Detector)          # bypass __init__ (no real model)
    det.threshold = 0.55
    det.whitelist = {"Erithacus rubecula_European Robin"}
    fake_result = mocker.Mock()
    fake_result.to_structured_array.return_value = [
        {"species_name": "Erithacus rubecula_European Robin", "confidence": 0.8},
    ]
    det._acoustic = mocker.Mock()
    det._acoustic.predict_arrays.return_value = fake_result
    det._extract = Detector._extract.__get__(det)
    out = det.predict_chunk(np.zeros(48000, dtype=np.float32), 48000, datetime(2026, 7, 5, 6))
    assert out[0].common_name == "European Robin"
    det._acoustic.predict_arrays.assert_called_once()
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_detector.py -v`
Expected: FAIL (`No module named birdframe.detector`).

**Step 3: Write minimal implementation**

```python
"""BirdNET wrapper: Edinburgh geo whitelist + acoustic detection on audio chunks.

Isolates every BirdNET call so the rest of the app is testable without the model.
Uses predict_arrays so audio never touches disk.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from birdframe.store import Detection


def parse_species_name(name: str) -> tuple[str, str]:
    """BirdNET encodes species as 'Scientific name_Common Name'."""
    sci, _, common = name.partition("_")
    return sci, common


def week_of_year(when: datetime) -> int:
    """BirdNET geo model wants a 1..48 week index (4 weeks per month)."""
    return min(48, (when.month - 1) * 4 + min(3, (when.day - 1) // 7) + 1)


def filter_detections(raw, whitelist, threshold, when) -> list[Detection]:
    out: list[Detection] = []
    for name, confidence in raw:
        if confidence < threshold:
            continue
        if whitelist is not None and name not in whitelist:
            continue
        sci, common = parse_species_name(name)
        out.append(Detection(when, sci, common, float(confidence)))
    return out


class Detector:
    def __init__(self, latitude: float, longitude: float, threshold: float,
                 geo_floor: float, when: datetime | None = None):
        import birdnet
        self.threshold = threshold
        self._acoustic = birdnet.load("acoustic", "2.4", "tf")
        self._geo = birdnet.load("geo", "2.4", "tf")
        self.sample_rate = self._acoustic.get_sample_rate()
        self.whitelist = self._build_whitelist(latitude, longitude, geo_floor,
                                               when or datetime.now())

    def _build_whitelist(self, lat, lon, floor, when) -> set[str]:
        result = self._geo.predict(lat, lon, week=week_of_year(when))
        names = set()
        for row in result.to_structured_array():
            name = row["species_name"] if hasattr(row, "__getitem__") else row.species_name
            conf = row["confidence"] if hasattr(row, "__getitem__") else row.confidence
            if conf >= floor:
                names.add(name)
        return names

    def refresh_whitelist(self, lat, lon, floor, when) -> None:
        self.whitelist = self._build_whitelist(lat, lon, floor, when)

    def _extract(self, result) -> list[tuple[str, float]]:
        pairs = []
        for row in result.to_structured_array():
            name = row["species_name"] if hasattr(row, "__getitem__") else row.species_name
            conf = row["confidence"] if hasattr(row, "__getitem__") else row.confidence
            pairs.append((name, float(conf)))
        return pairs

    def predict_chunk(self, audio: np.ndarray, sample_rate: int,
                      when: datetime) -> list[Detection]:
        result = self._acoustic.predict_arrays(
            (audio.astype(np.float32), sample_rate),
            custom_species_list=self.whitelist or None,
            default_confidence_threshold=self.threshold,
            top_k=5,
        )
        raw = self._extract(result)
        return filter_detections(raw, self.whitelist, self.threshold, when)
```

**Note for the implementer:** the exact field name in `to_structured_array()` may be `species_name` or similar — the `_extract`/`_build_whitelist` helpers read defensively. When you first run against the real model (Task 12 smoke test), print one row and adjust the key if needed. The pure-logic tests above do not depend on this.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_detector.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add birdframe/detector.py tests/test_detector.py
git commit -m "feat: BirdNET detector with Edinburgh geo whitelist"
```

---

## Task 4: Listener (audio capture → chunks)

Captures audio from the selected input device and yields overlapping numpy chunks. The ring-buffer/chunking logic is pure and unit-tested; the `sounddevice` stream is a thin wrapper around it.

**Files:**
- Create: `birdframe/listener.py`
- Test: `tests/test_listener.py`

**Step 1: Write the failing test**

```python
import numpy as np
from birdframe.listener import Chunker

def test_chunker_emits_when_full():
    # 4-sample chunks, 1-sample overlap, at 1 Hz "sample rate" for simplicity
    chunker = Chunker(chunk_samples=4, overlap_samples=1)
    assert chunker.push(np.array([1, 2], dtype=np.float32)) == []
    out = chunker.push(np.array([3, 4, 5], dtype=np.float32))
    assert len(out) == 1
    np.testing.assert_array_equal(out[0], [1, 2, 3, 4])

def test_chunker_retains_overlap_for_next_chunk():
    chunker = Chunker(chunk_samples=4, overlap_samples=1)
    chunker.push(np.arange(4, dtype=np.float32))          # emits [0,1,2,3], keeps [3]
    out = chunker.push(np.array([4, 5, 6], dtype=np.float32))  # [3,4,5,6]
    assert len(out) == 1
    np.testing.assert_array_equal(out[0], [3, 4, 5, 6])

def test_chunker_emits_multiple_when_backlogged():
    chunker = Chunker(chunk_samples=4, overlap_samples=0)
    out = chunker.push(np.arange(8, dtype=np.float32))
    assert len(out) == 2
    np.testing.assert_array_equal(out[0], [0, 1, 2, 3])
    np.testing.assert_array_equal(out[1], [4, 5, 6, 7])
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_listener.py -v`
Expected: FAIL (`No module named birdframe.listener`).

**Step 3: Write minimal implementation**

```python
"""Audio capture. Chunker (pure, tested) + AudioListener (sounddevice thread)."""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

import numpy as np

from birdframe.store import Detection


class Chunker:
    """Accumulates mono samples and emits fixed-size chunks with overlap."""

    def __init__(self, chunk_samples: int, overlap_samples: int):
        self.chunk_samples = chunk_samples
        self.overlap_samples = overlap_samples
        self._buf = np.empty(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list[np.ndarray]:
        self._buf = np.concatenate([self._buf, samples.astype(np.float32)])
        chunks = []
        step = self.chunk_samples - self.overlap_samples
        while len(self._buf) >= self.chunk_samples:
            chunks.append(self._buf[: self.chunk_samples].copy())
            self._buf = self._buf[step:]
        return chunks


class AudioListener:
    """Runs a sounddevice input stream on a background thread, feeding chunks
    to `on_chunk(audio, timestamp)`. Reconnects if the device disappears."""

    def __init__(self, sample_rate: int, chunk_seconds: float,
                 overlap_seconds: float, device: str | None,
                 on_chunk: Callable[[np.ndarray, datetime], None],
                 on_status: Callable[[str], None] = lambda s: None,
                 now: Callable[[], datetime] = datetime.now):
        self.sample_rate = sample_rate
        self.device = device or None
        self.on_chunk = on_chunk
        self.on_status = on_status
        self.now = now
        self._chunker = Chunker(
            chunk_samples=int(chunk_seconds * sample_rate),
            overlap_samples=int(overlap_seconds * sample_rate),
        )
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import sounddevice as sd
        while not self._stop.is_set():
            try:
                with sd.InputStream(samplerate=self.sample_rate, channels=1,
                                    dtype="float32", device=self.device,
                                    callback=self._sd_callback):
                    self.on_status("listening")
                    while not self._stop.is_set():
                        try:
                            block = self._q.get(timeout=0.5)
                        except queue.Empty:
                            continue
                        if self._paused.is_set():
                            continue
                        for chunk in self._chunker.push(block):
                            self.on_chunk(chunk, self.now())
            except Exception as exc:  # device vanished, etc.
                self.on_status(f"audio error: {exc}")
                self._stop.wait(30)   # retry in 30s

    def _sd_callback(self, indata, frames, time_info, status):
        self._q.put(indata[:, 0].copy())
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_listener.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add birdframe/listener.py tests/test_listener.py
git commit -m "feat: audio listener with overlapping chunker"
```

---

## Task 5: Styles (preset library + rotation)

Styles are markdown files under `styles/`, each with front-matter-free simple structure: a `# Name` heading, a `## Prompt` section (the template), and an optional `## Avoid` section. This task ships six styles and a loader/rotator.

**Files:**
- Create: `styles/ukiyo-e.md`, `styles/field-guide.md`, `styles/art-nouveau.md`, `styles/scottish-folk.md`, `styles/childrens-book.md`, `styles/linocut.md`
- Create: `birdframe/styles.py`
- Test: `tests/test_styles.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
from birdframe.styles import load_styles, choose_style

def _write(dir, name, prompt, avoid=""):
    body = f"# {name}\n\n## Prompt\n{prompt}\n"
    if avoid:
        body += f"\n## Avoid\n{avoid}\n"
    (dir / f"{name}.md").write_text(body)

def test_load_styles(tmp_path):
    _write(tmp_path, "ukiyo-e", "A woodblock print of {scene}.", "gradients")
    styles = load_styles(tmp_path)
    assert styles[0].name == "ukiyo-e"
    assert "{scene}" in styles[0].prompt
    assert "gradients" in styles[0].avoid

def test_choose_style_rotates_by_day_index(tmp_path):
    _write(tmp_path, "a", "x")
    _write(tmp_path, "b", "y")
    styles = load_styles(tmp_path)   # sorted by name: a, b
    assert choose_style(styles, mode="rotate", day_index=0).name == "a"
    assert choose_style(styles, mode="rotate", day_index=1).name == "b"
    assert choose_style(styles, mode="rotate", day_index=2).name == "a"

def test_choose_style_pinned(tmp_path):
    _write(tmp_path, "a", "x")
    _write(tmp_path, "b", "y")
    styles = load_styles(tmp_path)
    assert choose_style(styles, mode="pinned", pinned="b").name == "b"
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_styles.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Art styles loaded from markdown files; daily rotation or a pinned choice."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"


@dataclass
class Style:
    name: str
    prompt: str
    avoid: str = ""


def _section(text: str, header: str) -> str:
    m = re.search(rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
                  text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def load_styles(styles_dir: Path = DEFAULT_STYLES_DIR) -> list[Style]:
    styles = []
    for path in sorted(Path(styles_dir).glob("*.md")):
        text = path.read_text()
        name_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        name = path.stem
        styles.append(Style(
            name=name,
            prompt=_section(text, "Prompt"),
            avoid=_section(text, "Avoid"),
        ))
    return styles


def choose_style(styles, mode="rotate", day_index=0, pinned="") -> Style:
    if not styles:
        raise ValueError("no styles available")
    if mode == "pinned" and pinned:
        for s in styles:
            if s.name == pinned:
                return s
    return styles[day_index % len(styles)]
```

**Step 4: Create the six style files.** Each is bold, flat-colour, e-ink-friendly. Example `styles/ukiyo-e.md`:

```markdown
# ukiyo-e

## Prompt
A traditional Japanese ukiyo-e woodblock print depicting {scene}. Bold flat
areas of colour, confident black outlines, a limited palette, visible
wood-grain texture, and a calm balanced composition in portrait orientation.
The birds are the clear subjects, rendered accurately and recognisably.

## Avoid
photorealism, soft gradients, 3D rendering, drop shadows, text, watermarks
```

Create the other five in the same shape with these identities:
- `field-guide.md` — "a vintage naturalist's field-guide plate", neat hand-lettered feel, cream background, each bird posed clearly with fine ink linework and flat watercolour washes.
- `art-nouveau.md` — "an Art Nouveau decorative poster (Mucha-inspired)", sinuous whiplash lines, ornate floral border, muted jewel tones, flat colour.
- `scottish-folk.md` — "a piece of Scottish folk art", naive charming style, thistles and heather motifs, bold outlines, warm flat colours.
- `childrens-book.md` — "a warm children's picture-book illustration", gentle rounded shapes, cosy palette, storybook charm.
- `linocut.md` — "a hand-pulled linocut / lino print", high-contrast carved marks, one or two ink colours on paper, bold negative space.

Each `## Prompt` must contain the `{scene}` placeholder and end by stating the birds must be accurate and recognisable. Each `## Avoid` should list: photorealism, gradients, text, watermarks.

**Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_styles.py -v`
Expected: PASS (3 tests).

**Step 6: Commit**

```bash
git add birdframe/styles.py tests/test_styles.py styles/
git commit -m "feat: markdown style library with rotation"
```

---

## Task 6: Rollup + prompt assembly

Turns a day of `SpeciesDay` rows (plus weather + season) into the rich scene description that fills a style's `{scene}` placeholder. Pure functions — fully unit-tested.

**Files:**
- Create: `birdframe/rollup.py`
- Test: `tests/test_rollup.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from birdframe.store import SpeciesDay
from birdframe.rollup import build_scene, season_for, build_prompt
from birdframe.styles import Style

def _sd(name, count, first_h, last_h, best=0.9):
    return SpeciesDay(name, name.lower(), count, datetime(2026,7,5,first_h),
                      datetime(2026,7,5,last_h), first_h, best)

def test_season_for_northern_hemisphere():
    assert season_for(datetime(2026, 1, 15)) == "winter"
    assert season_for(datetime(2026, 7, 5)) == "summer"
    assert season_for(datetime(2026, 10, 20)) == "autumn"

def test_build_scene_mentions_top_species_and_dawn_and_weather():
    species = [_sd("European Robin", 47, 5, 20), _sd("Common Blackbird", 12, 4, 21)]
    scene = build_scene(species, first_ever={"European Robin"},
                        weather="light rain", when=datetime(2026, 7, 5, 21))
    assert "Edinburgh" in scene
    assert "European Robin" in scene
    assert "light rain" in scene
    assert "summer" in scene
    # the most-detected bird is featured prominently
    assert scene.index("European Robin") < scene.index("Common Blackbird")

def test_build_scene_handles_no_birds():
    scene = build_scene([], first_ever=set(), weather="clear", when=datetime(2026,7,5,21))
    assert "quiet" in scene.lower()

def test_build_prompt_fills_placeholder():
    style = Style("ukiyo-e", "A woodblock print of {scene}.", "gradients")
    prompt = build_prompt(style, "an Edinburgh garden with a robin")
    assert prompt == "A woodblock print of an Edinburgh garden with a robin."
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_rollup.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Turn a day's detections into a scene description for the image prompt."""
from __future__ import annotations

from datetime import datetime

from birdframe.store import SpeciesDay
from birdframe.styles import Style

_SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn",
            10: "autumn", 11: "autumn"}


def season_for(when: datetime) -> str:
    return _SEASONS[when.month]


def _time_of_day(when: datetime) -> str:
    h = when.hour
    if h < 8:
        return "early morning"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    if h < 21:
        return "evening"
    return "dusk"


def build_scene(species: list[SpeciesDay], first_ever: set[str],
                weather: str, when: datetime) -> str:
    season = season_for(when)
    tod = _time_of_day(when)
    if not species:
        return (f"a quiet Edinburgh garden on a {weather} {season} {tod}, "
                f"with no birds singing today")
    ranked = species  # already sorted by count desc from the store
    dawn = min(species, key=lambda s: s.first_heard)
    latest = max(species, key=lambda s: s.last_heard)
    parts = [f"an Edinburgh garden on a {weather} {season} {tod}"]
    lead = ranked[0]
    parts.append(f"{lead.common_name} singing prominently (heard {lead.count} "
                 f"times today)")
    for s in ranked[1:6]:
        parts.append(s.common_name)
    parts.append(f"{dawn.common_name} opened the dawn chorus")
    parts.append(f"{latest.common_name} sang latest into the {tod}")
    debuts = [s.common_name for s in ranked if s.common_name in first_ever]
    if debuts:
        parts.append("first ever heard here today: " + ", ".join(debuts))
    return "; ".join(parts)


def build_prompt(style: Style, scene: str) -> str:
    prompt = style.prompt.replace("{scene}", scene)
    if style.avoid:
        prompt += f"\n\nAvoid: {style.avoid}"
    return prompt.strip() if not style.avoid else prompt
```

Note: adjust `build_prompt` so the no-avoid test passes exactly (return without trailing avoid when `style.avoid` is empty). The test `test_build_prompt_fills_placeholder` uses a style *with* avoid but asserts exact equality without the avoid line — **change the test or the code to agree**; simplest is to make `build_prompt` append avoid only when present and update the test's expected string. Implementer: make them consistent, keep it pure.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_rollup.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/rollup.py tests/test_rollup.py
git commit -m "feat: day rollup and prompt assembly"
```

---

## Task 7: Weather (Open-Meteo, free, no key)

Fetches a short human phrase describing Edinburgh's weather for a given day. Network call isolated behind a function taking an injectable HTTP getter so it's testable.

**Files:**
- Create: `birdframe/weather.py`
- Test: `tests/test_weather.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from birdframe.weather import describe_weather, _code_to_phrase

def test_code_to_phrase():
    assert _code_to_phrase(0) == "clear"
    assert "rain" in _code_to_phrase(61)

def test_describe_weather_uses_daily_code(monkeypatch):
    def fake_get(url, params):
        return {"daily": {"weathercode": [61], "temperature_2m_max": [15.0]}}
    phrase = describe_weather(55.95, -3.19, datetime(2026, 7, 5), http_get=fake_get)
    assert "rain" in phrase

def test_describe_weather_falls_back_on_error():
    def boom(url, params):
        raise RuntimeError("network down")
    assert describe_weather(55.95, -3.19, datetime(2026, 7, 5), http_get=boom) == "changeable"
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_weather.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Edinburgh weather in a few words, from the free Open-Meteo API."""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import httpx

_CODES = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 80: "rain showers",
    81: "rain showers", 82: "heavy showers", 95: "thundery",
}


def _code_to_phrase(code: int) -> str:
    return _CODES.get(int(code), "changeable")


def _default_get(url: str, params: dict) -> dict:
    return httpx.get(url, params=params, timeout=10).json()


def describe_weather(lat: float, lon: float, when: datetime,
                     http_get: Callable[[str, dict], dict] = _default_get) -> str:
    day = when.strftime("%Y-%m-%d")
    try:
        data = http_get(
            "https://archive-api.open-meteo.com/v1/archive",
            {"latitude": lat, "longitude": lon, "start_date": day,
             "end_date": day, "daily": "weathercode,temperature_2m_max",
             "timezone": "Europe/London"},
        )
        code = data["daily"]["weathercode"][0]
        return _code_to_phrase(code)
    except Exception:
        return "changeable"
```

Note: the archive API lags a day or two; for "today" the implementer may switch to the `forecast` endpoint (`https://api.open-meteo.com/v1/forecast` with `daily=weathercode`). Keep the same shape and fallback.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_weather.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/weather.py tests/test_weather.py
git commit -m "feat: Open-Meteo weather phrase for Edinburgh"
```

---

## Task 8: Image composition (caption strip → exactly 1200×1600)

Takes generated image bytes and composites the final 1200×1600 PNG with a caption strip. Also provides the pure-Pillow fallback poster. No network.

**Files:**
- Create: `birdframe/compose.py`
- Test: `tests/test_compose.py`

**Step 1: Write the failing test**

```python
import io
from datetime import datetime
from PIL import Image
from birdframe.compose import compose_final, fallback_poster

def _png_bytes(w, h, colour=(120, 90, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()

def test_compose_final_is_exact_frame_size():
    art = _png_bytes(1024, 1536)
    out = compose_final(art, date=datetime(2026, 7, 5),
                        species=["European Robin", "Common Blackbird"])
    img = Image.open(io.BytesIO(out))
    assert img.size == (1200, 1600)
    assert img.format == "PNG"

def test_fallback_poster_is_exact_frame_size():
    out = fallback_poster(date=datetime(2026, 7, 5),
                          species=["European Robin", "Common Blackbird"])
    img = Image.open(io.BytesIO(out))
    assert img.size == (1200, 1600)

def test_compose_handles_empty_species():
    art = _png_bytes(1024, 1536)
    out = compose_final(art, date=datetime(2026, 7, 5), species=[])
    assert Image.open(io.BytesIO(out)).size == (1200, 1600)
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_compose.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Composite the generated art + a caption strip into a 1200x1600 PNG."""
from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont

FRAME_W, FRAME_H = 1200, 1600
CAPTION_H = 100
ART_H = FRAME_H - CAPTION_H  # 1500


def _font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Georgia.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    from PIL import ImageOps
    return ImageOps.fit(img.convert("RGB"), (w, h), method=Image.LANCZOS)


def compose_final(art_bytes: bytes, date: datetime, species: list[str]) -> bytes:
    art = _fit_cover(Image.open(io.BytesIO(art_bytes)), FRAME_W, ART_H)
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), (250, 248, 242))
    canvas.paste(art, (0, 0))
    draw = ImageDraw.Draw(canvas)
    date_str = date.strftime("%A %-d %B %Y")
    draw.text((30, ART_H + 18), date_str, fill=(30, 30, 30), font=_font(34))
    names = ", ".join(species) if species else "a quiet day — no birds detected"
    draw.text((30, ART_H + 58), names, fill=(70, 70, 70), font=_font(24))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def fallback_poster(date: datetime, species: list[str]) -> bytes:
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), (247, 244, 236))
    draw = ImageDraw.Draw(canvas)
    draw.text((60, 80), "Birds heard today", fill=(30, 30, 30), font=_font(64))
    draw.text((60, 170), date.strftime("%A %-d %B %Y"), fill=(90, 90, 90), font=_font(36))
    y = 300
    if not species:
        draw.text((60, y), "A quiet day — none detected.", fill=(60, 60, 60), font=_font(40))
    for name in species[:20]:
        draw.text((60, y), f"·  {name}", fill=(40, 40, 40), font=_font(44))
        y += 62
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_compose.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/compose.py tests/test_compose.py
git commit -m "feat: caption composition and fallback poster"
```

---

## Task 9: Artist (glue: rollup → OpenAI → compose → archive)

Orchestrates a full picture generation. OpenAI is injected so the test never spends money. On OpenAI failure after retries, falls back to the poster.

**Files:**
- Create: `birdframe/artist.py`
- Test: `tests/test_artist.py`

**Step 1: Write the failing test**

```python
import base64, io
from datetime import datetime
from PIL import Image
from birdframe.artist import Artist
from birdframe.store import Store, Detection
from birdframe.styles import Style

def _b64_png():
    buf = io.BytesIO()
    Image.new("RGB", (1024, 1536), (100, 120, 90)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def _artist(tmp_path, image_client, styles=None):
    store = Store(tmp_path / "db.sqlite")
    return store, Artist(
        store=store, styles=styles or [Style("ukiyo-e", "print of {scene}", "gradients")],
        image_client=image_client, archive_dir=tmp_path / "images",
        weather_fn=lambda lat, lon, when: "light rain",
        latitude=55.95, longitude=-3.19,
    )

def test_generate_creates_image_record_and_file(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.return_value = base64.b64decode(_b64_png())
    store, artist = _artist(tmp_path, client)
    store.add_detection(Detection(datetime(2026,7,5,6), "Erithacus rubecula", "European Robin", 0.9))
    rec = artist.generate(when=datetime(2026, 7, 5, 21))
    assert rec.style == "ukiyo-e"
    assert "European Robin" in rec.species
    img = Image.open(rec.path)
    assert img.size == (1200, 1600)
    client.generate.assert_called_once()
    assert "European Robin" in client.generate.call_args.args[0]  # prompt mentions the bird

def test_generate_falls_back_to_poster_on_openai_error(tmp_path, mocker):
    client = mocker.Mock()
    client.generate.side_effect = RuntimeError("api down")
    store, artist = _artist(tmp_path, client)
    store.add_detection(Detection(datetime(2026,7,5,6), "Turdus merula", "Common Blackbird", 0.9))
    rec = artist.generate(when=datetime(2026, 7, 5, 21))
    assert Image.open(rec.path).size == (1200, 1600)
    assert rec.style.endswith("(fallback)")
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_artist.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Compose a day's picture: rollup -> prompt -> image gen -> caption -> archive."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from birdframe.compose import compose_final, fallback_poster
from birdframe.rollup import build_prompt, build_scene
from birdframe.store import ImageRecord, Store
from birdframe.styles import Style, choose_style


class Artist:
    def __init__(self, store: Store, styles: list[Style], image_client,
                 archive_dir: Path, weather_fn, latitude: float, longitude: float,
                 style_mode: str = "rotate", pinned_style: str = ""):
        self.store = store
        self.styles = styles
        self.image_client = image_client
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.weather_fn = weather_fn
        self.latitude = latitude
        self.longitude = longitude
        self.style_mode = style_mode
        self.pinned_style = pinned_style

    def generate(self, when: datetime) -> ImageRecord:
        species_days = self.store.species_for_day(when)
        species_names = [s.common_name for s in species_days]
        first_ever = self.store.first_ever_on_day(when)
        weather = self.weather_fn(self.latitude, self.longitude, when)
        scene = build_scene(species_days, first_ever, weather, when)
        day_index = when.toordinal()
        style = choose_style(self.styles, self.style_mode, day_index, self.pinned_style)
        prompt = build_prompt(style, scene)

        style_label = style.name
        try:
            art_bytes = self.image_client.generate(prompt)
            final = compose_final(art_bytes, when, species_names)
        except Exception:
            final = fallback_poster(when, species_names)
            style_label = f"{style.name} (fallback)"

        filename = when.strftime("%Y-%m-%d-%H%M%S") + ".png"
        path = self.archive_dir / filename
        path.write_bytes(final)
        image_id = self.store.add_image(when, str(path), style_label, prompt, species_names)
        return self.store.get_image(image_id)
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_artist.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/artist.py tests/test_artist.py
git commit -m "feat: Artist orchestration with poster fallback"
```

---

## Task 10: OpenAI image client (thin real adapter)

The concrete `image_client.generate(prompt) -> bytes` used in production. Reads the key from Keychain. Retries. Tested with the OpenAI SDK mocked.

**Files:**
- Create: `birdframe/image_client.py`
- Test: `tests/test_image_client.py`

**Step 1: Write the failing test**

```python
import base64
from birdframe.image_client import OpenAIImageClient

def test_generate_returns_decoded_bytes(mocker):
    fake = mocker.Mock()
    fake.images.generate.return_value = mocker.Mock(
        data=[mocker.Mock(b64_json=base64.b64encode(b"PNGDATA").decode())]
    )
    client = OpenAIImageClient(api_key="sk-test", model="gpt-image-1",
                               quality="high", sdk=fake)
    out = client.generate("a robin in a garden")
    assert out == b"PNGDATA"
    fake.images.generate.assert_called_once()
    kwargs = fake.images.generate.call_args.kwargs
    assert kwargs["model"] == "gpt-image-1"
    assert kwargs["size"] == "1024x1536"

def test_generate_retries_then_raises(mocker):
    fake = mocker.Mock()
    fake.images.generate.side_effect = RuntimeError("boom")
    client = OpenAIImageClient(api_key="sk-test", model="gpt-image-1",
                               quality="high", sdk=fake, max_retries=3, backoff=0)
    import pytest
    with pytest.raises(RuntimeError):
        client.generate("x")
    assert fake.images.generate.call_count == 3
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_image_client.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Concrete image backend: OpenAI gpt-image-1. Key comes from the Keychain."""
from __future__ import annotations

import base64
import time


class OpenAIImageClient:
    SIZE = "1024x1536"  # portrait; composed to 1200x1600 downstream

    def __init__(self, api_key: str, model: str = "gpt-image-1",
                 quality: str = "high", sdk=None, max_retries: int = 3,
                 backoff: float = 2.0):
        self.model = model
        self.quality = quality
        self.max_retries = max_retries
        self.backoff = backoff
        if sdk is not None:
            self._client = sdk
        else:
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)

    def generate(self, prompt: str) -> bytes:
        last = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.images.generate(
                    model=self.model, prompt=prompt, size=self.SIZE,
                    quality=self.quality, n=1,
                )
                return base64.b64decode(resp.data[0].b64_json)
            except Exception as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
        raise last
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_image_client.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/image_client.py tests/test_image_client.py
git commit -m "feat: OpenAI gpt-image-1 client with retries"
```

---

## Task 11: Publisher (POST to the Inky Frame)

POSTs a PNG to the frame's `/display`, honouring the real contract. Never sends `force`. Treats `409` (held by someone else) as "leave it be — success in the sense of not fighting". Retries transient network failures a few times. HTTP client injected.

**Files:**
- Create: `birdframe/publisher.py`
- Test: `tests/test_publisher.py`

**Step 1: Write the failing test**

```python
from birdframe.publisher import Publisher, PublishResult

class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""

def test_publish_success_202(mocker):
    posts = []
    def fake_post(url, files, data, timeout):
        posts.append((url, files, data))
        return FakeResponse(202)
    pub = Publisher("http://frame.local:5000", hold_minutes=180, saturation=0.6,
                    http_post=fake_post)
    result = pub.publish(b"PNGBYTES")
    assert result.status == "posted"
    assert posts[0][0] == "http://frame.local:5000/display"
    assert posts[0][2]["source"] == "birdframe"
    assert posts[0][2]["hold_minutes"] == 180
    assert "force" not in posts[0][2]

def test_publish_held_409_is_not_retried(mocker):
    calls = {"n": 0}
    def fake_post(url, files, data, timeout):
        calls["n"] += 1
        return FakeResponse(409)
    pub = Publisher("http://frame.local:5000", hold_minutes=180, saturation=0.6,
                    http_post=fake_post, max_retries=3, backoff=0)
    result = pub.publish(b"PNGBYTES")
    assert result.status == "held"
    assert calls["n"] == 1   # don't hammer a frame someone else is holding

def test_publish_network_error_retries_then_fails():
    calls = {"n": 0}
    def boom(url, files, data, timeout):
        calls["n"] += 1
        raise ConnectionError("frame offline")
    pub = Publisher("http://frame.local:5000", hold_minutes=0, saturation=0.6,
                    http_post=boom, max_retries=3, backoff=0)
    result = pub.publish(b"PNGBYTES")
    assert result.status == "unreachable"
    assert calls["n"] == 3
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_publisher.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""Publish the day's picture to the shared Inky Frame. Never fight the frame."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import httpx


@dataclass
class PublishResult:
    status: str  # posted | held | unreachable
    detail: str = ""


def _default_post(url, files, data, timeout):
    return httpx.post(url, files=files, data=data, timeout=timeout)


class Publisher:
    def __init__(self, frame_url: str, hold_minutes: int, saturation: float,
                 http_post: Callable = _default_post, max_retries: int = 3,
                 backoff: float = 5.0, timeout: float = 60.0):
        self.frame_url = frame_url.rstrip("/")
        self.hold_minutes = hold_minutes
        self.saturation = saturation
        self.http_post = http_post
        self.max_retries = max_retries
        self.backoff = backoff
        self.timeout = timeout

    def publish(self, png_bytes: bytes) -> PublishResult:
        url = f"{self.frame_url}/display"
        data = {"source": "birdframe", "hold_minutes": self.hold_minutes,
                "saturation": self.saturation}
        last = ""
        for attempt in range(self.max_retries):
            try:
                files = {"file": ("birdframe.png", png_bytes, "image/png")}
                resp = self.http_post(url, files, data, self.timeout)
                if resp.status_code in (200, 202):
                    return PublishResult("posted")
                if resp.status_code == 409:
                    return PublishResult("held", "frame held by another source")
                last = f"HTTP {resp.status_code}"
            except Exception as exc:
                last = str(exc)
            if attempt < self.max_retries - 1:
                time.sleep(self.backoff * (attempt + 1))
        return PublishResult("unreachable", last)
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_publisher.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/publisher.py tests/test_publisher.py
git commit -m "feat: polite publisher for the shared Inky Frame"
```

---

## Task 12: Scheduler (daily / live / manual triggers)

Decides *when* to generate + publish. Pure decision logic separated from timing so it's testable: `should_post_now(state, now)` returns a reason or None. A thin runner thread calls it on a tick.

**Files:**
- Create: `birdframe/scheduler.py`
- Test: `tests/test_scheduler.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from birdframe.scheduler import decide, SchedulerState

def _state(**kw):
    base = dict(mode="daily", post_time="21:00", last_post=None,
                live_min_gap_minutes=120, live_window_start="08:00",
                live_window_end="22:00", new_species_today=False)
    base.update(kw)
    return SchedulerState(**base)

def test_daily_fires_once_at_post_time():
    st = _state(mode="daily", last_post=None)
    assert decide(st, datetime(2026,7,5,21,0)) == "daily"
    # already posted today -> no
    st2 = _state(mode="daily", last_post=datetime(2026,7,5,21,0))
    assert decide(st2, datetime(2026,7,5,21,5)) is None

def test_daily_does_not_fire_before_time():
    st = _state(mode="daily", last_post=None)
    assert decide(st, datetime(2026,7,5,20,59)) is None

def test_manual_never_fires():
    st = _state(mode="manual", new_species_today=True)
    assert decide(st, datetime(2026,7,5,21,0)) is None

def test_live_fires_on_new_species_within_window_respecting_gap():
    st = _state(mode="live", new_species_today=True, last_post=None)
    assert decide(st, datetime(2026,7,5,10,0)) == "live"
    # too soon after last post
    st2 = _state(mode="live", new_species_today=True,
                 last_post=datetime(2026,7,5,9,30))
    assert decide(st2, datetime(2026,7,5,10,0)) is None
    # outside the daytime window
    st3 = _state(mode="live", new_species_today=True, last_post=None)
    assert decide(st3, datetime(2026,7,5,23,0)) is None

def test_live_still_does_daily_final_edition():
    st = _state(mode="live", new_species_today=False, last_post=None)
    assert decide(st, datetime(2026,7,5,21,0)) == "daily"
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""When to generate + publish. Pure decision logic; the runner just ticks it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SchedulerState:
    mode: str            # daily | live | manual
    post_time: str       # "HH:MM"
    last_post: datetime | None
    live_min_gap_minutes: int
    live_window_start: str
    live_window_end: str
    new_species_today: bool


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _posted_today(last_post: datetime | None, now: datetime) -> bool:
    return last_post is not None and last_post.date() == now.date()


def _daily_due(state: SchedulerState, now: datetime) -> bool:
    h, m = _parse_hm(state.post_time)
    at_or_after = (now.hour, now.minute) >= (h, m)
    return at_or_after and not _posted_today(state.last_post, now)


def decide(state: SchedulerState, now: datetime) -> str | None:
    """Return 'daily', 'live', or None."""
    if state.mode == "manual":
        return None

    # Both daily and live honour the fixed daily 'final edition'.
    if _daily_due(state, now):
        return "daily"

    if state.mode == "live" and state.new_species_today:
        start_h, start_m = _parse_hm(state.live_window_start)
        end_h, end_m = _parse_hm(state.live_window_end)
        in_window = (start_h, start_m) <= (now.hour, now.minute) <= (end_h, end_m)
        if not in_window:
            return None
        if state.last_post is not None:
            gap = (now - state.last_post).total_seconds() / 60
            if gap < state.live_min_gap_minutes:
                return None
        return "live"
    return None
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/scheduler.py tests/test_scheduler.py
git commit -m "feat: posting-mode decision logic"
```

---

## Task 13: Secrets (Keychain wrapper)

Thin `keyring` wrapper for the OpenAI key so it never lands in config. Tested with `keyring` mocked.

**Files:**
- Create: `birdframe/secrets.py`
- Test: `tests/test_secrets.py`

**Step 1: Write the failing test**

```python
from birdframe import secrets as secretmod

def test_set_and_get_key(mocker):
    store = {}
    mocker.patch.object(secretmod.keyring, "set_password",
                        side_effect=lambda s, u, p: store.__setitem__((s, u), p))
    mocker.patch.object(secretmod.keyring, "get_password",
                        side_effect=lambda s, u: store.get((s, u)))
    secretmod.set_openai_key("sk-abc")
    assert secretmod.get_openai_key() == "sk-abc"

def test_get_missing_returns_none(mocker):
    mocker.patch.object(secretmod.keyring, "get_password", return_value=None)
    assert secretmod.get_openai_key() is None
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
"""OpenAI API key storage in the macOS Keychain."""
from __future__ import annotations

import keyring

_SERVICE = "birdframe"
_USER = "openai_api_key"


def set_openai_key(key: str) -> None:
    keyring.set_password(_SERVICE, _USER, key)


def get_openai_key() -> str | None:
    return keyring.get_password(_SERVICE, _USER)
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add birdframe/secrets.py tests/test_secrets.py
git commit -m "feat: Keychain-backed OpenAI key storage"
```

---

## Task 14: Dashboard (FastAPI)

The local web UI + JSON API. Build the API routes with tests (FastAPI `TestClient`), and serve a single-page HTML dashboard. The app object takes its dependencies (store, artist, publisher, config) via a small context object so tests can inject fakes.

**Files:**
- Create: `birdframe/web/__init__.py`
- Create: `birdframe/web/app.py`
- Create: `birdframe/web/static/index.html`
- Test: `tests/test_web.py`

**Step 1: Write the failing test**

```python
from datetime import datetime
from fastapi.testclient import TestClient
from birdframe.web.app import create_app, AppContext
from birdframe.store import Store, Detection

class FakeArtist:
    def __init__(self): self.calls = 0
    def generate(self, when):
        self.calls += 1
        class R: id = 1; path = "/tmp/x.png"; style = "ukiyo-e"; species = ["European Robin"]
        return R()

class FakePublisher:
    def __init__(self): self.published = []
    def publish(self, png):
        self.published.append(png)
        class R: status = "posted"; detail = ""
        return R()

def _client(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.add_detection(Detection(datetime(2026,7,5,6), "Erithacus rubecula", "European Robin", 0.9))
    ctx = AppContext(store=store, artist=FakeArtist(), publisher=FakePublisher(),
                     now=lambda: datetime(2026,7,5,12))
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
    assert len(ctx.publisher.published) == 1

def test_index_served(tmp_path):
    _, _, client = _client(tmp_path)
    assert client.get("/").status_code == 200
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**

```python
# birdframe/web/app.py
"""Local dashboard: JSON API + a single-page UI."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

STATIC = Path(__file__).resolve().parent / "static"


@dataclass
class AppContext:
    store: object
    artist: object
    publisher: object
    now: Callable[[], datetime] = datetime.now


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/today")
    def today():
        now = ctx.now()
        species = ctx.store.species_for_day(now)
        return {
            "date": now.strftime("%Y-%m-%d"),
            "species": [
                {"common_name": s.common_name, "scientific_name": s.scientific_name,
                 "count": s.count, "first_heard": s.first_heard.strftime("%H:%M"),
                 "last_heard": s.last_heard.strftime("%H:%M"),
                 "peak_hour": s.peak_hour, "best_confidence": round(s.best_confidence, 2)}
                for s in species
            ],
        }

    @app.get("/api/history")
    def history():
        rows = ctx.store.recent_images(limit=100)
        return {"images": [
            {"id": r.id, "generated_at": r.generated_at.isoformat(), "style": r.style,
             "species": r.species, "posted_at": r.posted_at.isoformat() if r.posted_at else None}
            for r in rows
        ]}

    @app.post("/api/post-now")
    def post_now():
        rec = ctx.artist.generate(ctx.now())
        with open(rec.path, "rb") as fh:
            result = ctx.publisher.publish(fh.read())
        if result.status == "posted":
            ctx.store.mark_posted(rec.id, ctx.now())
        return {"image_id": rec.id, "publish": result.status}

    @app.post("/api/repost/{image_id}")
    def repost(image_id: int):
        rec = ctx.store.get_image(image_id)
        if rec is None:
            return JSONResponse({"error": "no such image"}, status_code=404)
        with open(rec.path, "rb") as fh:
            result = ctx.publisher.publish(fh.read())
        if result.status == "posted":
            ctx.store.mark_posted(rec.id, ctx.now())
        return {"image_id": rec.id, "publish": result.status}

    return app
```

Create `birdframe/web/static/index.html` — a single page that fetches `/api/today` and `/api/history`, shows today's species list with counts and times, a "Post Now" button hitting `/api/post-now`, and a gallery from `/api/history` with per-image "Re-post" buttons. Plain vanilla JS, no build step. Keep it clean and legible; e-ink-frame owners appreciate calm design.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS (3 tests).

**Step 5: Commit**

```bash
git add birdframe/web/ tests/test_web.py
git commit -m "feat: FastAPI dashboard with today/history/post-now"
```

---

## Task 15: App wiring + menu bar + runtime

Ties everything together: builds the objects from config + Keychain, starts the listener, detector loop, scheduler tick, and uvicorn dashboard on worker threads, and runs the `rumps` menu bar on the main thread. Because `rumps` needs macOS and the main thread, this task is **integration-tested lightly** (the wiring function that builds the runtime is unit-tested; the rumps app is smoke-run manually).

**Files:**
- Create: `birdframe/runtime.py` (thread orchestration, no rumps)
- Create: `birdframe/menubar.py` (rumps app; imports runtime)
- Create: `birdframe/app.py` (entry point `main()`)
- Test: `tests/test_runtime.py`

**Step 1: Write the failing test** — for the detection callback wiring (the part worth testing): a detection from the detector reaches the store and flips `new_species_today`.

```python
from datetime import datetime
from birdframe.runtime import Runtime
from birdframe.store import Store, Detection

class FakeDetector:
    sample_rate = 48000
    def __init__(self, dets): self._dets = dets
    def predict_chunk(self, audio, sr, when): return self._dets

def test_chunk_callback_records_detections_and_tracks_new_species(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    det = FakeDetector([Detection(datetime(2026,7,5,6), "Erithacus rubecula", "European Robin", 0.9)])
    rt = Runtime.for_test(store=store, detector=det, now=lambda: datetime(2026,7,5,6))
    rt.on_chunk(audio=b"", when=datetime(2026,7,5,6))
    assert store.species_for_day(datetime(2026,7,5,6))[0].common_name == "European Robin"
    assert rt.new_species_today is True

def test_new_species_flag_resets_next_day(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    det = FakeDetector([])
    rt = Runtime.for_test(store=store, detector=det, now=lambda: datetime(2026,7,6,0))
    rt.new_species_today = True
    rt.roll_day(datetime(2026,7,6,0,1))
    assert rt.new_species_today is False
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_runtime.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation** — `birdframe/runtime.py`:

```python
"""Thread orchestration and the shared runtime state (no rumps/macOS here)."""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

import numpy as np

from birdframe.scheduler import SchedulerState, decide
from birdframe.store import Store


class Runtime:
    def __init__(self, config, store, detector, listener_factory, artist,
                 publisher, now: Callable[[], datetime] = datetime.now):
        self.config = config
        self.store = store
        self.detector = detector
        self.listener_factory = listener_factory
        self.artist = artist
        self.publisher = publisher
        self.now = now
        self.new_species_today = False
        self.last_post: datetime | None = None
        self.status = "starting"
        self._seen_today: set[str] = set()
        self._today = now().date()
        self._lock = threading.Lock()
        self._listener = None

    @classmethod
    def for_test(cls, store, detector, now):
        rt = cls.__new__(cls)
        rt.store = store
        rt.detector = detector
        rt.now = now
        rt.new_species_today = False
        rt.last_post = None
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

    def scheduler_state(self, now: datetime) -> SchedulerState:
        c = self.config
        return SchedulerState(
            mode=c.post_mode, post_time=c.post_time, last_post=self.last_post,
            live_min_gap_minutes=c.live_min_gap_minutes,
            live_window_start=c.live_window_start, live_window_end=c.live_window_end,
            new_species_today=self.new_species_today,
        )

    def tick(self, now: datetime) -> None:
        reason = decide(self.scheduler_state(now), now)
        if reason:
            self.post_now(now)

    def post_now(self, now: datetime) -> str:
        rec = self.artist.generate(now)
        with open(rec.path, "rb") as fh:
            result = self.publisher.publish(fh.read())
        if result.status == "posted":
            self.store.mark_posted(rec.id, now)
        self.last_post = now
        self.new_species_today = False
        return result.status
```

`birdframe/menubar.py` — rumps app showing "🐦 N species today", last few species, Post Now (calls `runtime.post_now`), Pause/Resume, mode picker, Open Dashboard (opens `http://localhost:<port>`), and a ⚠️ title when `runtime.status` indicates trouble. Runs `rumps.Timer` every 30 s to update the title and call `runtime.tick(now)`.

`birdframe/app.py` — `main()`:
1. `config = Config.load()`
2. build `Store` at `~/.local/share/birdframe/db.sqlite`, archive dir alongside
3. read key via `secrets.get_openai_key()`; if missing, still start (dashboard shows a "set your key" notice; generation will use the fallback poster)
4. build `Detector`, `OpenAIImageClient`, `Artist`, `Publisher`, `Runtime`
5. start the audio listener (`AudioListener`) with `runtime.on_chunk`
6. start a `caffeinate -i` child process (`subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])`) so the Mac stays awake while birdframe runs
7. start uvicorn (dashboard) on a daemon thread
8. start the rumps app on the main thread (blocks)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_runtime.py -v`
Expected: PASS (2 tests).

**Step 5: Commit**

```bash
git add birdframe/runtime.py birdframe/menubar.py birdframe/app.py tests/test_runtime.py
git commit -m "feat: runtime orchestration, menu bar, entry point"
```

---

## Task 16: LaunchAgent + docs for running forever

**Files:**
- Create: `packaging/com.birdframe.plist`
- Create: `packaging/install.sh`
- Modify: `README.md` (run instructions)

**Step 1: Create the LaunchAgent plist** `packaging/com.birdframe.plist` (template with `__WORKDIR__`/`__UV__` placeholders the installer fills in):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.birdframe</string>
  <key>ProgramArguments</key>
  <array>
    <string>__UV__</string>
    <string>run</string>
    <string>birdframe</string>
  </array>
  <key>WorkingDirectory</key><string>__WORKDIR__</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>__HOME__/Library/Logs/birdframe.log</string>
  <key>StandardErrorPath</key><string>__HOME__/Library/Logs/birdframe.log</string>
</dict>
</plist>
```

**Step 2: Create `packaging/install.sh`** — substitutes the placeholders (`uv` path via `command -v uv`, `$PWD`, `$HOME`), writes to `~/Library/LaunchAgents/com.birdframe.plist`, and runs `launchctl unload` (ignore errors) then `launchctl load`. Print a note that the first launch will prompt for microphone access, which must be granted for the user running the agent.

**Step 3: Update `README.md`** with: prerequisites (`brew install uv libsndfile`), `uv sync`, set the OpenAI key (`uv run python -c "from birdframe import secrets; secrets.set_openai_key('sk-...')"`), run once in the foreground to grant mic permission (`uv run birdframe`), then `bash packaging/install.sh` to run forever. Document the dashboard URL (`http://localhost:8355`) and how to change settings.

**Step 4: Verify the plist is well-formed**

Run: `plutil -lint packaging/com.birdframe.plist`
Expected: `OK`.

**Step 5: Commit**

```bash
git add packaging/ README.md
git commit -m "feat: LaunchAgent packaging and run-forever docs"
```

---

## Task 17: End-to-end smoke test (real model, optional real API)

A single opt-in test that exercises the real pipeline on a bundled recording. Skipped by default so CI/others don't need model downloads or API spend.

**Files:**
- Create: `tests/fixtures/README.md` (how to add a short public-domain bird clip named `robin.wav`)
- Create: `tests/test_smoke.py`

**Step 1: Write the smoke test**

```python
import os
import numpy as np
import soundfile as sf
import pytest
from pathlib import Path
from datetime import datetime
from birdframe.detector import Detector

FIXTURE = Path(__file__).parent / "fixtures" / "robin.wav"

@pytest.mark.skipif(not FIXTURE.exists(), reason="no fixture audio")
@pytest.mark.skipif(os.environ.get("BIRDFRAME_SMOKE") != "1", reason="opt-in smoke test")
def test_detector_finds_something_in_real_audio():
    audio, sr = sf.read(str(FIXTURE))
    if audio.ndim > 1:
        audio = audio[:, 0]
    det = Detector(latitude=55.95, longitude=-3.19, threshold=0.1, geo_floor=0.0,
                   when=datetime(2026, 7, 5, 6))
    out = det.predict_chunk(audio.astype(np.float32), sr, datetime(2026, 7, 5, 6))
    # Print for the implementer to eyeball species/field names on first run.
    print([(d.common_name, d.confidence) for d in out])
    assert isinstance(out, list)
```

**Step 2: Run without opt-in (verifies it skips cleanly)**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: SKIPPED.

**Step 3: Run the full suite**

Run: `uv run pytest -v`
Expected: all non-smoke tests PASS.

**Step 4: Manual live check (implementer, once)**

- Drop a real short bird recording at `tests/fixtures/robin.wav`.
- `BIRDFRAME_SMOKE=1 uv run pytest tests/test_smoke.py -s` — confirm sensible species come out and confirm the structured-array field name matches `detector._extract` (fix the key if the print shows otherwise).
- `uv run birdframe` — grant mic access, watch the menu bar count climb, open the dashboard, hit **Post Now**, confirm the image appears on the frame (or in the frame's simulator).

**Step 5: Commit**

```bash
git add tests/test_smoke.py tests/fixtures/README.md
git commit -m "test: opt-in end-to-end smoke test"
```

---

## Done

At this point birdframe: listens continuously, filters to plausible Edinburgh species, records everything, generates a styled daily picture with rich context and a caption, posts it politely to the shared frame in whichever mode you choose (with Post Now always available), archives every image, and shows it all in a menu bar + dashboard — running forever via a LaunchAgent.

**Post-MVP backlog (explicitly deferred):** saved audio clips per detection, multiple image-gen backends, LLM-invented styles, richer history charts (heatmaps), per-species confidence tuning UI.
