"""Concrete image backend: OpenAI gpt-image family. Key comes from the Keychain.

Note: the gpt-image models are slow (gpt-image-2 at good quality is ~2 minutes),
so callers should run generation off any request/UI thread.
"""
from __future__ import annotations

import base64
import time


class OpenAIImageClient:
    SIZE = "1024x1536"  # portrait; composed to 1200x1600 downstream

    def __init__(self, api_key: str, model: str = "gpt-image-2",
                 quality: str = "high", sdk=None, max_retries: int = 3,
                 backoff: float = 2.0, timeout: float = 300.0):
        self.model = model
        self.quality = quality
        self.max_retries = max_retries
        self.backoff = backoff
        if sdk is not None:
            self._client = sdk
        else:
            from openai import OpenAI
            # gpt-image generations are slow; give the HTTP layer room.
            self._client = OpenAI(api_key=api_key, timeout=timeout)

    def _image_bytes(self, item) -> bytes:
        """gpt-image models return base64; some models/paths return a URL."""
        b64 = getattr(item, "b64_json", None)
        if b64:
            return base64.b64decode(b64)
        url = getattr(item, "url", None)
        if url:
            import httpx
            return httpx.get(url, timeout=60).content
        raise RuntimeError("image response had neither b64_json nor url")

    def generate(self, prompt: str) -> bytes:
        last = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.images.generate(
                    model=self.model, prompt=prompt, size=self.SIZE,
                    quality=self.quality, n=1,
                )
                # A 200 that we can't turn into bytes is a bug, not a transient
                # error — don't burn another paid generation retrying it.
                return self._image_bytes(resp.data[0])
            except Exception as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
        raise last
