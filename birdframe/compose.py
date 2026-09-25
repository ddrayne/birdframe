"""Composite the generated art + a caption strip into a 1200x1600 PNG."""
from __future__ import annotations

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps

FRAME_W, FRAME_H = 1200, 1600
CAPTION_H = 100
ART_H = FRAME_H - CAPTION_H  # 1500
PAPER = (250, 248, 242)
# The frame dithers onto six inks whose "white" is a light grey, so any grey
# text comes out as a speckle of black and white dots. Captions use pure black.
INK = (0, 0, 0)
# A render within this fraction of the art area's shape fills it (a few pixels
# are trimmed); anything further off is fitted whole, never cropped.
FILL_TOLERANCE = 0.03


def _font(size: int):
    for path in ("/System/Library/Fonts/Supplemental/Georgia.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    # Pillow's bundled font scales too; without a size it is a tiny bitmap.
    return ImageFont.load_default(size)


def _fit_art(img: Image.Image, w: int, h: int) -> Image.Image:
    """Fill w×h when the render is (nearly) that shape, e.g. a native 4:5
    render; otherwise scale to fit *inside* w×h so no bird at an edge is lost
    (a 2:3 render is letterboxed). Small renders are scaled up, not centred
    in a wide border."""
    img = img.convert("RGB")
    if abs(img.width / img.height - w / h) <= FILL_TOLERANCE * (w / h):
        return ImageOps.fit(img, (w, h), Image.LANCZOS)
    return ImageOps.contain(img, (w, h), Image.LANCZOS)


def _names_line(draw: ImageDraw.ImageDraw, species: list[str], font, width: int) -> str:
    """As many whole names as fit on the line, then "+ N more"."""
    for shown in range(len(species), 0, -1):
        rest = len(species) - shown
        line = ", ".join(species[:shown]) + (f" + {rest} more" if rest else "")
        if draw.textlength(line, font=font) <= width:
            return line
    return _truncate(", ".join(species), 90)


def compose_final(art_bytes: bytes, date: datetime, species: list[str],
                  label: str = "") -> bytes:
    art = _fit_art(Image.open(io.BytesIO(art_bytes)), FRAME_W, ART_H)
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), PAPER)
    # Centre the picture in the art area (only a mismatched shape leaves a border).
    canvas.paste(art, ((FRAME_W - art.width) // 2, (ART_H - art.height) // 2))
    draw = ImageDraw.Draw(canvas)
    date_str = _caption_date(date, label)
    draw.text((30, ART_H + 18), date_str, fill=INK, font=_font(34))
    names_font = _font(24)
    names = (_names_line(draw, species, names_font, FRAME_W - 60) if species
             else "a quiet day — no birds detected")
    draw.text((30, ART_H + 58), names, fill=INK, font=names_font)
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def fallback_poster(date: datetime, species: list[str], label: str = "") -> bytes:
    canvas = Image.new("RGB", (FRAME_W, FRAME_H), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.text((60, 80), "Birds heard today", fill=INK, font=_font(64))
    draw.text((60, 170), _caption_date(date, label), fill=INK, font=_font(36))
    y = 300
    if not species:
        draw.text((60, y), "A quiet day — none detected.", fill=INK, font=_font(40))
    for name in species[:20]:
        draw.text((60, y), f"·  {name}", fill=INK, font=_font(44))
        y += 62
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def thumbnail_jpeg(image_bytes: bytes, width: int) -> bytes:
    """A small JPEG of a frame picture for galleries — a phone showing a card
    105px wide shouldn't download and decode a 3 MB, 1200×1600 PNG."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img.thumbnail((width, width * 4), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=82, optimize=True, progressive=True)
    return out.getvalue()


def _date_str(date: datetime) -> str:
    # %-d is platform-specific; build the day number without a leading zero by hand.
    return date.strftime(f"%A {date.day} %B %Y")


def _caption_date(date: datetime, label: str = "") -> str:
    """The caption's first line: the date, plus the slot label when one exists —
    'Thursday 17 July 2026 · dawn'."""
    return f"{_date_str(date)} · {label}" if label else _date_str(date)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip(", ") + "…"
