"""Audio capture, signal health, and self-healing stream supervision.

The callback thread does the minimum possible work.  A capture thread turns
blocks into chunks and watches the signal; a separate detector thread runs
BirdNET.  Keeping those responsibilities separate lets the capture watchdog
continue working even if inference becomes slow or wedges entirely.
"""
from __future__ import annotations

import hashlib
import queue
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

import numpy as np


def _ensure_input_unmuted(device: str | None) -> bool:
    from birdframe.coreaudio import ensure_input_unmuted
    return ensure_input_unmuted(device)


def _dbfs(value: float) -> float:
    return float(20 * np.log10(max(float(value), 1e-12)))


@dataclass(frozen=True)
class SignalReading:
    """A compact, testable description of one captured audio chunk."""

    rms_dbfs: float
    peak_dbfs: float
    dynamic_rms_dbfs: float
    dc_offset: float
    dc_dominance_db: float
    suspicious_reason: str | None = None


def inspect_signal(samples: np.ndarray, *,
                   min_dynamic_dbfs: float = -90.0,
                   max_dc_dominance_db: float = 15.0) -> SignalReading:
    """Measure whether a chunk contains changing audio rather than a flat feed.

    A disconnected USB interface can keep returning a non-zero constant, so
    raw loudness alone is insufficient.  We also measure the signal after
    removing its mean and reject a feed dominated by DC offset.
    """
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return SignalReading(-240.0, -240.0, -240.0, 0.0, 0.0,
                             "empty audio buffer")
    mean = float(np.mean(audio))
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    peak = float(np.max(np.abs(audio)))
    centered = audio.astype(np.float64) - mean
    dynamic_rms = float(np.sqrt(np.mean(centered * centered)))
    rms_dbfs = _dbfs(rms)
    dynamic_dbfs = _dbfs(dynamic_rms)
    dominance = max(0.0, rms_dbfs - dynamic_dbfs)
    reason = None
    if dynamic_dbfs <= min_dynamic_dbfs:
        reason = "no changing audio"
    elif abs(mean) >= 1e-3 and dominance >= max_dc_dominance_db:
        reason = "audio is dominated by a fixed DC level"
    return SignalReading(
        rms_dbfs=rms_dbfs,
        peak_dbfs=_dbfs(peak),
        dynamic_rms_dbfs=dynamic_dbfs,
        dc_offset=mean,
        dc_dominance_db=dominance,
        suspicious_reason=reason,
    )


class SignalMonitor:
    """Require repeated evidence before declaring a signal flat or frozen."""

    def __init__(self, bad_chunks: int = 3, min_dynamic_dbfs: float = -90.0):
        self.bad_chunks = max(1, int(bad_chunks))
        self.min_dynamic_dbfs = float(min_dynamic_dbfs)
        self._bad_streak = 0
        self._same_streak = 0
        self._last_digest: bytes | None = None

    def reset(self) -> None:
        self._bad_streak = 0
        self._same_streak = 0
        self._last_digest = None

    def observe(self, samples: np.ndarray) -> tuple[SignalReading, str | None]:
        reading = inspect_signal(samples, min_dynamic_dbfs=self.min_dynamic_dbfs)
        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        stride = max(1, audio.size // 512)
        digest = hashlib.blake2s(audio[::stride].tobytes(), digest_size=8).digest()
        self._same_streak = self._same_streak + 1 if digest == self._last_digest else 0
        self._last_digest = digest
        self._bad_streak = self._bad_streak + 1 if reading.suspicious_reason else 0
        if self._same_streak >= max(1, self.bad_chunks - 1):
            return reading, "the audio device is repeating the same buffer"
        if self._bad_streak >= self.bad_chunks:
            return reading, reading.suspicious_reason
        return reading, None


class Chunker:
    """Accumulates mono samples and emits fixed-size chunks with overlap."""

    def __init__(self, chunk_samples: int, overlap_samples: int):
        self.chunk_samples = chunk_samples
        self.overlap_samples = overlap_samples
        self._buf = np.empty(0, dtype=np.float32)

    def reset(self) -> None:
        self._buf = np.empty(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> list[np.ndarray]:
        self._buf = np.concatenate([self._buf, samples.astype(np.float32)])
        chunks = []
        step = self.chunk_samples - self.overlap_samples
        while len(self._buf) >= self.chunk_samples:
            chunks.append(self._buf[: self.chunk_samples].copy())
            self._buf = self._buf[step:]
        return chunks


class _RestartStream(RuntimeError):
    pass


class AudioListener:
    """Capture continuously, reopening unhealthy streams automatically.

    `health_snapshot()` is deliberately independent from detection counts: a
    quiet day is healthy when fresh, changing audio continues to arrive.
    """

    def __init__(self, sample_rate: int, chunk_seconds: float,
                 overlap_seconds: float, device: str | None,
                 on_chunk: Callable[[np.ndarray, datetime], None],
                 on_status: Callable[[str], None] = lambda s: None,
                 now: Callable[[], datetime] = datetime.now,
                 monotonic: Callable[[], float] = time.monotonic,
                 callback_timeout_seconds: float = 10.0,
                 detector_timeout_seconds: float = 120.0,
                 process_restart_failures: int = 2,
                 flat_chunks: int = 3,
                 flat_dynamic_dbfs: float = -90.0,
                 ensure_unmuted: Callable[[str | None], bool] = _ensure_input_unmuted):
        self.sample_rate = sample_rate
        self.chunk_seconds = float(chunk_seconds)
        self.device = device or None
        self.on_chunk = on_chunk
        self.on_status = on_status
        self.now = now
        self.monotonic = monotonic
        self.callback_timeout_seconds = float(callback_timeout_seconds)
        self.detector_timeout_seconds = float(detector_timeout_seconds)
        self.process_restart_failures = max(1, int(process_restart_failures))
        self.ensure_unmuted = ensure_unmuted
        self._chunker = Chunker(
            chunk_samples=int(chunk_seconds * sample_rate),
            overlap_samples=int(overlap_seconds * sample_rate),
        )
        self._signal_monitor = SignalMonitor(flat_chunks, flat_dynamic_dbfs)
        self._block_q: queue.Queue = queue.Queue(maxsize=4096)
        self._chunk_q: queue.Queue = queue.Queue(maxsize=4)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._restart_stream = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._detector_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = "starting"
        self._detail = "waiting for the first audio chunk"
        self._stream_started_at: float | None = None
        self._last_callback_at: float | None = None
        self._last_chunk_at: float | None = None
        self._processing_started_at: float | None = None
        self._processing_completed_at: float | None = None
        self._last_reading: SignalReading | None = None
        self._restart_reason: str | None = None
        self._fatal_reason: str | None = None
        self._stream_restarts = 0
        self._recovery_failures = 0
        self._open_failures = 0
        self._healthy_chunks = 0
        self._dropped_blocks = 0
        self._dropped_chunks = 0
        self._consecutive_dropped_chunks = 0
        self._last_callback_status: str | None = None
        self._ever_received_callback = False
        self._automatic_unmutes = 0

    def start(self) -> None:
        self._detector_thread = threading.Thread(
            target=self._detect_run, name="birdframe-detector", daemon=True)
        self._capture_thread = threading.Thread(
            target=self._capture_run, name="birdframe-audio", daemon=True)
        self._detector_thread.start()
        self._capture_thread.start()

    def pause(self) -> None:
        self._paused.set()
        self._set_state("paused", "listening is paused by the user")

    def resume(self) -> None:
        self._paused.clear()
        self._set_state("starting", "waiting for fresh audio after resume")

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def stop(self) -> None:
        self._stop.set()
        self._restart_stream.set()

    def _set_state(self, state: str, detail: str = "") -> None:
        with self._lock:
            self._state = state
            self._detail = detail

    def _request_stream_restart(self, reason: str) -> None:
        with self._lock:
            self._restart_reason = reason
        self._restart_stream.set()

    def _drain(self, q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def _capture_run(self) -> None:
        import sounddevice as sd
        while not self._stop.is_set():
            try:
                self._drain(self._block_q)
                self._chunker.reset()
                self._signal_monitor.reset()
                self._restart_stream.clear()
                try:
                    if self.ensure_unmuted(self.device):
                        with self._lock:
                            self._automatic_unmutes += 1
                        self.on_status("unmuted microphone input")
                except Exception as exc:
                    # A control-query failure must never prevent capture. The
                    # signal watchdog will still catch a muted/flat feed.
                    self.on_status(f"audio control warning: {exc}")
                with sd.InputStream(samplerate=self.sample_rate, channels=1,
                                    dtype="float32", device=self.device,
                                    callback=self._sd_callback):
                    with self._lock:
                        self._stream_started_at = self.monotonic()
                        self._last_callback_at = None
                        self._restart_reason = None
                        self._open_failures = 0
                    self._set_state("starting", "audio stream opened; checking signal")
                    self.on_status("listening")
                    while not self._stop.is_set():
                        if self._restart_stream.is_set():
                            with self._lock:
                                reason = self._restart_reason or "audio stream requested recovery"
                            raise _RestartStream(reason)
                        try:
                            block = self._block_q.get(timeout=0.5)
                        except queue.Empty:
                            with self._lock:
                                last = self._last_callback_at
                                started = self._stream_started_at
                            age = self.monotonic() - (last if last is not None else started)
                            if age > self.callback_timeout_seconds:
                                raise _RestartStream(
                                    f"no audio callback for {int(age)} seconds")
                            continue
                        if self._paused.is_set():
                            continue
                        for chunk in self._chunker.push(block):
                            reading, problem = self._signal_monitor.observe(chunk)
                            with self._lock:
                                self._last_reading = reading
                                self._last_chunk_at = self.monotonic()
                            if problem:
                                raise _RestartStream(problem)
                            self._healthy_chunks += 1
                            if self._healthy_chunks >= 10:
                                self._recovery_failures = 0
                            self._set_state("listening", "healthy changing audio")
                            self._queue_chunk(chunk, self.now())
            except _RestartStream as exc:
                self._recover(str(exc))
            except Exception as exc:  # device vanished, permission lost, etc.
                self._recover(f"audio error: {exc}")

    def _recover(self, reason: str) -> None:
        self._stream_restarts += 1
        self._recovery_failures += 1
        self._healthy_chunks = 0
        # CoreAudio gives a reconnected USB device a new AudioObjectID. PortAudio
        # can keep its old catalogue for the lifetime of the process, causing
        # every subsequent InputStream open to fail with -9986. Repeated opens
        # cannot repair that state; launchd must rebuild PortAudio in a clean
        # process. Only escalate if this process previously received callbacks,
        # otherwise an unplugged-at-startup mic would create a restart loop.
        if "Error opening InputStream" in reason:
            self._open_failures += 1
        if (self._ever_received_callback and
                self._open_failures >= self.process_restart_failures):
            with self._lock:
                self._fatal_reason = (
                    "PortAudio could not bind the reconnected microphone after "
                    f"{self._open_failures} open attempts")
        self._set_state("recovering", reason)
        self.on_status(f"recovering: {reason}")
        delay = min(300.0, 5.0 * (2 ** min(self._recovery_failures - 1, 6)))
        self._stop.wait(delay)

    def _queue_chunk(self, chunk: np.ndarray, when: datetime) -> None:
        try:
            self._chunk_q.put_nowait((chunk, when))
        except queue.Full:
            try:
                self._chunk_q.get_nowait()  # discard oldest; remain close to real time
            except queue.Empty:
                pass
            self._chunk_q.put_nowait((chunk, when))
            with self._lock:
                self._dropped_chunks += 1
                self._consecutive_dropped_chunks += 1
                if self._consecutive_dropped_chunks >= 3:
                    self._fatal_reason = "BirdNET cannot keep up with live audio"

    def _detect_run(self) -> None:
        while not self._stop.is_set():
            try:
                chunk, when = self._chunk_q.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                self._processing_started_at = self.monotonic()
            try:
                self.on_chunk(chunk, when)
            except Exception as exc:
                with self._lock:
                    self._fatal_reason = f"BirdNET processing failed: {exc}"
                self.on_status(f"detector error: {exc}")
                return
            finally:
                with self._lock:
                    self._processing_started_at = None
                    self._processing_completed_at = self.monotonic()
                    if self._chunk_q.qsize() <= 1:
                        self._consecutive_dropped_chunks = 0

    def _sd_callback(self, indata, frames, time_info, status):
        now = self.monotonic()
        with self._lock:
            self._ever_received_callback = True
            self._last_callback_at = now
            if status:
                self._last_callback_status = str(status)
        if status:
            # PortAudio often keeps the callback alive after USB re-enumeration;
            # explicitly leave the stale stream so the outer loop can re-resolve
            # the configured device name.
            self._request_stream_restart(f"audio callback reported: {status}")
            return
        block = indata[:, 0].copy()
        try:
            self._block_q.put_nowait(block)
        except queue.Full:
            try:
                self._block_q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._block_q.put_nowait(block)
            except queue.Full:
                pass
            with self._lock:
                self._dropped_blocks += 1

    def health_snapshot(self, now_monotonic: float | None = None) -> dict:
        """Return truthful liveness, suitable for UI and external watchdogs."""
        now = self.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            state, detail = self._state, self._detail
            callback_at = self._last_callback_at
            chunk_at = self._last_chunk_at
            stream_at = self._stream_started_at
            processing_at = self._processing_started_at
            fatal = self._fatal_reason
            reading = self._last_reading
            callback_status = self._last_callback_status
            restarts = self._stream_restarts
            open_failures = self._open_failures
            automatic_unmutes = self._automatic_unmutes
            dropped_blocks = self._dropped_blocks
            dropped_chunks = self._dropped_chunks
        callback_age = None if callback_at is None else max(0.0, now - callback_at)
        chunk_age = None if chunk_at is None else max(0.0, now - chunk_at)
        processing_age = None if processing_at is None else max(0.0, now - processing_at)
        restart_required = False
        restart_reason = None
        if fatal:
            state, detail = "restart required", fatal
            restart_required, restart_reason = True, fatal
        elif processing_age is not None and processing_age > self.detector_timeout_seconds:
            state = "detector stalled"
            detail = f"BirdNET has not finished a chunk for {int(processing_age)} seconds"
            restart_required, restart_reason = True, detail
        elif state in ("starting", "listening") and stream_at is not None:
            reference = callback_at if callback_at is not None else stream_at
            if now - reference > self.callback_timeout_seconds:
                state = "audio stalled"
                detail = f"no audio callback for {int(now - reference)} seconds"
        healthy = state == "listening" and callback_age is not None
        return {
            "healthy": healthy,
            "state": state,
            "detail": detail,
            "last_callback_ago_s": None if callback_age is None else int(callback_age),
            "last_audio_chunk_ago_s": None if chunk_age is None else int(chunk_age),
            "detector_processing_ago_s": None if processing_age is None else int(processing_age),
            "signal": asdict(reading) if reading else None,
            "stream_restarts": restarts,
            "consecutive_open_failures": open_failures,
            "automatic_unmutes": automatic_unmutes,
            "dropped_audio_blocks": dropped_blocks,
            "dropped_detector_chunks": dropped_chunks,
            "last_callback_status": callback_status,
            "restart_required": restart_required,
            "restart_reason": restart_reason,
        }
