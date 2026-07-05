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
        if whitelist and name not in whitelist:
            continue
        sci, common = parse_species_name(name)
        out.append(Detection(when, sci, common, float(confidence)))
    return out


def _row_field(row, key: str):
    """Read a field from a structured-array row or an object, defensively."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError, ValueError):
        return getattr(row, key)


def _rows_to_pairs(result) -> list[tuple[str, float]]:
    """Normalise a BirdNET prediction result to (species_name, confidence) pairs.

    The structured array's field names have varied across birdnet versions, so
    resolve the name/confidence columns from the dtype rather than hard-coding.
    """
    arr = result.to_structured_array()
    dtype = getattr(arr, "dtype", None)
    names = getattr(dtype, "names", None)
    if names:
        name_field = next((n for n in names if "species" in n.lower() or "name" in n.lower()), names[0])
        conf_field = next((n for n in names if "conf" in n.lower() or "score" in n.lower() or "prob" in n.lower()), names[-1])
    else:
        name_field, conf_field = "species_name", "confidence"
    pairs = []
    for row in arr:
        pairs.append((str(_row_field(row, name_field)), float(_row_field(row, conf_field))))
    return pairs


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
        return {name for name, conf in _rows_to_pairs(result) if conf >= floor}

    def refresh_whitelist(self, lat, lon, floor, when) -> None:
        self.whitelist = self._build_whitelist(lat, lon, floor, when)

    def _extract(self, result) -> list[tuple[str, float]]:
        return _rows_to_pairs(result)

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
