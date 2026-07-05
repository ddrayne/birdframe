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
