"""How much to trust a detection — a general, honest treatment of false positives.

BirdNET can be acoustically confident about a bird that is implausible for the
place and season (a great crested grebe in a city garden), and a genuine bird
can be heard faintly just once. Rather than silently hiding or hard-blocking, we
weigh three independent signals and *tell the user why* a detection is doubtful:

  1. how clearly it was heard   — the acoustic confidence
  2. how expected it is here     — the geographic plausibility (BirdNET geo model)
  3. how much it corroborates    — how many times it was heard

The output is a tier (confirmed / probable / tentative), a 0–1 reliability
score for sorting, and plain-language reasons. Tentative birds are shown, but
clearly marked, and kept out of the day's artwork.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# When a species' geographic plausibility is unknown, assume it's ordinary
# enough not to penalise it (absence of data is not evidence of implausibility).
GEO_DEFAULT = 0.30

TIERS = ("confirmed", "probable", "tentative")


@dataclass
class Assessment:
    tier: str
    score: float
    reasons: list[str] = field(default_factory=list)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def assess(best_confidence: float, geo_plausibility: float, count: int) -> Assessment:
    # Normalise each axis to 0–1.
    conf = _clamp((best_confidence - 0.5) / 0.45)      # 0.50→0, 0.95→1
    geo = _clamp(geo_plausibility / 0.30)              # 0.30+→1, 0.05→0.17
    corr = _clamp((count - 1) / 4)                     # 1→0, 5+→1

    score = 0.40 * conf + 0.35 * geo + 0.25 * corr
    tier = "confirmed" if score >= 0.66 else "probable" if score >= 0.42 else "tentative"

    reasons: list[str] = []

    # Geographic plausibility — the signal confidence can't provide.
    if geo_plausibility < 0.10:
        reasons.append("unusual for this area")
        tier = "tentative"                             # very unlikely here → always flag
    elif geo_plausibility < 0.25:
        reasons.append("uncommon here")

    # Corroboration.
    if count == 1:
        reasons.append("heard only once")
        if best_confidence < 0.75 and tier == "confirmed":
            tier = "probable"

    # Acoustic clarity.
    if best_confidence < 0.60:
        reasons.append("a faint match")
        if tier == "confirmed":
            tier = "probable"
    elif best_confidence < 0.72:
        reasons.append("a soft match")

    if tier == "confirmed" and not reasons:
        reasons.append("heard clearly and often")

    return Assessment(tier=tier, score=round(score, 2), reasons=reasons)


def is_reliable(a: Assessment) -> bool:
    """Trustworthy enough to celebrate in the day's picture."""
    return a.tier in ("confirmed", "probable")
