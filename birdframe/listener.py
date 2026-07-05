"""Audio capture. Chunker (pure, tested) + AudioListener (sounddevice thread)."""
from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Callable

import numpy as np


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

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

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
