"""Composite the generated art + a caption strip into a 1200x1600 PNG."""
from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

FRAME_W, FRAME_H = 1200, 1600
CAPTION_H = 100
ART_H = FRAME_H - CAPTION_H  # 1500


def _font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Georgia.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (w, h), method=Image.LANCZOS)


def compose_final(art_bytes: bytes, date: datetime, species: list[str]) -> bytes:
    art = _fit_cover(Image.open(io.BytesIO(art_bytes)), FRAME_W, ART_H)
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), (250, 248, 242))
    canvas.paste(art, (0, 0))
    draw = ImageDraw.Draw(canvas)
    date_str = _date_str(date)
    draw.text((30, ART_H + 18), date_str, fill=(30, 30, 30), font=_font(34))
    names = ", ".join(species) if species else "a quiet day — no birds detected"
    names = _truncate(names, 90)
    draw.text((30, ART_H + 58), names, fill=(70, 70, 70), font=_font(24))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def fallback_poster(date: datetime, species: list[str]) -> bytes:
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), (247, 244, 236))
    draw = ImageDraw.Draw(canvas)
    draw.text((60, 80), "Birds heard today", fill=(30, 30, 30), font=_font(64))
    draw.text((60, 170), _date_str(date), fill=(90, 90, 90), font=_font(36))
    y = 300
    if not species:
        draw.text((60, y), "A quiet day — none detected.", fill=(60, 60, 60), font=_font(40))
    for name in species[:20]:
        draw.text((60, y), f"·  {name}", fill=(40, 40, 40), font=_font(44))
        y += 62
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def _date_str(date: datetime) -> str:
    # %-d is platform-specific; build the day number without a leading zero by hand.
    return date.strftime(f"%A {date.day} %B %Y")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip(", ") + "…"
