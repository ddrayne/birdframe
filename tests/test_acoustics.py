import numpy as np

from birdframe.acoustics import measure_detection


def test_segment_loudness_and_quiet_background_are_measured():
    sample_rate = 1000
    audio = np.zeros(2000, dtype=np.float32)
    t = np.arange(500) / sample_rate
    audio[750:1250] = 0.5 * np.sin(2 * np.pi * 50 * t)
    metrics = measure_detection(audio, sample_rate, 0.75, 1.25)
    assert metrics is not None
    assert -9.2 < metrics.rms_dbfs < -8.8
    assert -6.2 < metrics.peak_dbfs < -5.8
    assert metrics.noise_floor_dbfs == -120.0
    assert metrics.snr_db > 110


def test_empty_audio_has_no_metrics():
    assert measure_detection([], 48000) is None
