"""Pure acoustic measurements for a BirdNET detection segment."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


_DB_FLOOR = -120.0


@dataclass(frozen=True)
class AcousticMetrics:
    rms_dbfs: float
    peak_dbfs: float
    noise_floor_dbfs: float
    snr_db: float


def _dbfs(amplitude: float) -> float:
    if not np.isfinite(amplitude) or amplitude <= 0:
        return _DB_FLOOR
    return max(_DB_FLOOR, 20.0 * float(np.log10(min(amplitude, 1.0))))


def _rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def _noise_amplitude(samples: np.ndarray, sample_rate: int) -> float:
    """Estimate ambient noise from the quietest fifth of 50 ms windows."""
    frame = max(1, int(sample_rate * 0.05))
    levels = [_rms(samples[i:i + frame]) for i in range(0, len(samples), frame)
              if len(samples[i:i + frame]) >= max(1, frame // 2)]
    return float(np.percentile(levels, 20)) if levels else _rms(samples)


def measure_detection(audio, sample_rate: int,
                      start_s: float | None = None,
                      end_s: float | None = None) -> AcousticMetrics | None:
    """Measure one detected call without retaining any additional audio.

    BirdNET supplies segment offsets. Audio outside that segment estimates the
    ambient floor; if offsets are unavailable, quiet windows in the whole chunk
    are used instead.
    """
    if isinstance(audio, (bytes, bytearray, memoryview)):
        return None
    samples = np.asarray(audio, dtype=np.float64).reshape(-1)
    if samples.size == 0 or sample_rate <= 0:
        return None
    samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)

    start = 0
    end = len(samples)
    if start_s is not None and end_s is not None and end_s > start_s:
        start = max(0, min(len(samples), int(float(start_s) * sample_rate)))
        end = max(start + 1, min(len(samples), int(float(end_s) * sample_rate)))
    segment = samples[start:end]
    if segment.size == 0:
        segment = samples
        start, end = 0, len(samples)

    outside = np.concatenate((samples[:start], samples[end:]))
    noise_source = outside if outside.size >= max(1, sample_rate // 4) else samples
    rms_dbfs = _dbfs(_rms(segment))
    peak_dbfs = _dbfs(float(np.max(np.abs(segment))))
    noise_floor_dbfs = _dbfs(_noise_amplitude(noise_source, sample_rate))
    return AcousticMetrics(
        rms_dbfs=round(rms_dbfs, 3),
        peak_dbfs=round(peak_dbfs, 3),
        noise_floor_dbfs=round(noise_floor_dbfs, 3),
        snr_db=round(rms_dbfs - noise_floor_dbfs, 3),
    )
