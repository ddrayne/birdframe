"""Render the birdframe app icon (PWA / dock) at any size with Pillow.

A simple, recognisable emblem: a stylised bird perched, in warm cream on the
pine-green accent, inside a rounded square — no external assets needed.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

_GREEN = (46, 106, 79)     # accent
_CREAM = (245, 246, 240)
_GOLD = (196, 135, 43)     # dawn-gold, for the eye/beak accent


def render_icon(size: int) -> bytes:
    # Supersample for smooth edges, then downscale.
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=_GREEN)

    # Bird: body, head, tail, wing, beak — plump songbird silhouette.
    cx, cy = s * 0.46, s * 0.54
    body_r = s * 0.20
    d.ellipse([cx - body_r, cy - body_r * 0.85, cx + body_r, cy + body_r * 1.05], fill=_CREAM)
    head_r = s * 0.115
    hx, hy = cx + body_r * 0.72, cy - body_r * 0.75
    d.ellipse([hx - head_r, hy - head_r, hx + head_r, hy + head_r], fill=_CREAM)
    # tail
    d.polygon([(cx - body_r * 0.75, cy + body_r * 0.1),
               (cx - body_r * 1.7, cy - body_r * 0.25),
               (cx - body_r * 0.7, cy + body_r * 0.6)], fill=_CREAM)
    # wing
    d.ellipse([cx - body_r * 0.55, cy - body_r * 0.35,
               cx + body_r * 0.75, cy + body_r * 0.75], fill=_GREEN)
    # beak
    d.polygon([(hx + head_r * 0.6, hy - head_r * 0.1),
               (hx + head_r * 1.7, hy + head_r * 0.05),
               (hx + head_r * 0.6, hy + head_r * 0.4)], fill=_GOLD)
    # eye
    er = head_r * 0.22
    d.ellipse([hx + head_r * 0.05 - er, hy - er, hx + head_r * 0.05 + er, hy + er], fill=_GREEN)
    # perch line
    d.rounded_rectangle([s * 0.2, cy + body_r * 1.15, s * 0.8, cy + body_r * 1.30],
                        radius=s * 0.02, fill=_GOLD)

    img = img.resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()
