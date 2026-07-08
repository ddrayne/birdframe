"""Publish the day's picture to the shared Inky Frame. Never fight the frame."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import httpx

log = logging.getLogger("birdframe")


@dataclass
class PublishResult:
    status: str  # posted | held | unreachable
    detail: str = ""


def _default_post(url, files, data, timeout):
    # Fail fast if the frame can't be reached (unreachable/mDNS), but allow a
    # long read — the Pi can take ~30s to answer while refreshing the e-ink.
    t = httpx.Timeout(connect=6.0, read=timeout, write=timeout, pool=timeout)
    return httpx.post(url, files=files, data=data, timeout=t)


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

    def publish(self, png_bytes: bytes, force: bool = False) -> PublishResult:
        url = f"{self.frame_url}/display"
        data = {"source": "birdframe", "hold_minutes": self.hold_minutes,
                "saturation": self.saturation}
        if force:
            # Explicit user action → override any hold another source placed.
            data["force"] = "1"
        last = ""
        for attempt in range(self.max_retries):
            try:
                files = {"file": ("birdframe.png", png_bytes, "image/png")}
                resp = self.http_post(url, files, data, self.timeout)
                if resp.status_code in (200, 202):
                    return PublishResult("posted")
                if resp.status_code == 409:
                    # Someone else is holding the frame — leave it be.
                    return PublishResult("held", "frame held by another source")
                last = f"HTTP {resp.status_code}"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.max_retries - 1:
                time.sleep(self.backoff * (attempt + 1))
        # Surface the failure — silent frame failures were undiagnosable before.
        log.warning("Could not reach the frame at %s after %d tries: %s",
                    url, self.max_retries, last)
        return PublishResult("unreachable", last)
