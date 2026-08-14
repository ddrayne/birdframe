import numpy as np

from birdframe.listener import AudioListener, Chunker, SignalMonitor, inspect_signal


def test_chunker_emits_when_full():
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


def test_signal_inspection_accepts_changing_audio():
    t = np.arange(48000, dtype=np.float32) / 48000
    audio = (0.08 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    reading = inspect_signal(audio)
    assert reading.suspicious_reason is None
    assert reading.dynamic_rms_dbfs > -30
    assert abs(reading.dc_offset) < 1e-4


def test_signal_monitor_rejects_repeated_flat_usb_feed_after_confirmation():
    monitor = SignalMonitor(bad_chunks=3)
    stuck = np.full(48000, 0.0075, dtype=np.float32)
    assert monitor.observe(stuck)[1] is None
    assert monitor.observe(stuck)[1] is None
    reason = monitor.observe(stuck)[1]
    assert reason is not None


def test_signal_monitor_does_not_confuse_quiet_noise_with_a_dead_mic():
    monitor = SignalMonitor(bad_chunks=3)
    noise = np.random.default_rng(7).normal(0, 0.0002, 48000).astype(np.float32)
    for _ in range(5):
        reading, reason = monitor.observe(noise + np.random.default_rng().normal(
            0, 1e-7, noise.shape).astype(np.float32))
        assert reason is None
    assert reading.dynamic_rms_dbfs > -90


def _listener(clock, **kwargs):
    return AudioListener(
        sample_rate=48000, chunk_seconds=15, overlap_seconds=1.5,
        device="USB Microphone", on_chunk=lambda audio, when: None,
        monotonic=lambda: clock[0], **kwargs)


def test_callback_status_requests_a_fresh_stream_after_usb_cycle():
    clock = [10.0]
    listener = _listener(clock)

    class BadStatus:
        def __bool__(self): return True
        def __str__(self): return "device changed"

    listener._sd_callback(np.zeros((32, 1), dtype=np.float32), 32, None, BadStatus())
    assert listener._restart_stream.is_set()
    health = listener.health_snapshot()
    assert health["last_callback_status"] == "device changed"


def test_health_requests_process_restart_when_detector_stalls():
    clock = [200.0]
    listener = _listener(clock, detector_timeout_seconds=120)
    with listener._lock:
        listener._state = "listening"
        listener._last_callback_at = 200.0
        listener._processing_started_at = 50.0
    health = listener.health_snapshot()
    assert health["state"] == "detector stalled"
    assert health["healthy"] is False
    assert health["restart_required"] is True


def test_health_catches_callback_stall_even_if_stream_is_still_open():
    clock = [30.0]
    listener = _listener(clock, callback_timeout_seconds=10)
    with listener._lock:
        listener._state = "listening"
        listener._stream_started_at = 0.0
        listener._last_callback_at = 5.0
    health = listener.health_snapshot()
    assert health["state"] == "audio stalled"
    assert health["healthy"] is False
