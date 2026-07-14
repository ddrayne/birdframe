"""Concrete image backends: OpenAI gpt-image family and Google Gemini image
models. Keys come from the Keychain.

Note: image generation is slow (gpt-image-2 at good quality is ~2 minutes),
so callers should run generation off any request/UI thread.
"""
from __future__ import annotations

import base64
import time


class NoImageError(RuntimeError):
    """The API returned 200 but no usable image — a bug or blocked prompt, not
    a transient failure; retrying would only burn paid generations."""


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
        raise NoImageError("image response had neither b64_json nor url")

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
            except NoImageError:
                raise
            except Exception as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
        raise last


class GeminiImageClient:
    # 4:5 exactly fills the frame's 1200x1500 art area (no letterbox bars).
    ASPECT_RATIO = "4:5"

    def __init__(self, api_key: str, model: str = "gemini-3-pro-image",
                 quality: str = "high", sdk=None, max_retries: int = 3,
                 backoff: float = 2.0, timeout: float = 300.0):
        self.model = model
        self.image_size = "2K" if quality == "high" else "1K"
        self.max_retries = max_retries
        self.backoff = backoff
        if sdk is not None:
            self._client = sdk
        else:
            from google import genai
            # google-genai takes its HTTP timeout in milliseconds.
            self._client = genai.Client(
                api_key=api_key,
                http_options={"timeout": int(timeout * 1000)})

    def _image_bytes(self, resp) -> bytes:
        # A fully blocked prompt returns no candidates at all (only
        # prompt_feedback) — same hard-error treatment as a text-only reply.
        candidates = getattr(resp, "candidates", None)
        content = candidates[0].content if candidates else None
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            raise NoImageError("Gemini response contained no candidates/parts")
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                data = inline.data
                if isinstance(data, str):
                    return base64.b64decode(data)
                return data
        # A 200 with no image (e.g. a text-only safety refusal) is a bug or a
        # blocked prompt, not a transient error — don't burn paid retries on it.
        raise NoImageError("Gemini response contained no image part")

    def generate(self, prompt: str) -> bytes:
        last = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=prompt,
                    config={
                        "response_modalities": ["TEXT", "IMAGE"],
                        "image_config": {
                            "aspect_ratio": self.ASPECT_RATIO,
                            "image_size": self.image_size,
                        },
                    },
                )
                return self._image_bytes(resp)
            except NoImageError:
                raise
            except Exception as exc:
                last = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
        raise last
