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


_ORDER = {"tentative": 0, "probable": 1, "confirmed": 2}


def _cap(tier: str, ceiling: str) -> str:
    """Never let `tier` exceed `ceiling`."""
    return tier if _ORDER[tier] <= _ORDER[ceiling] else ceiling


def assess(best_confidence: float, geo_plausibility: float, count: int) -> Assessment:
    # Normalise each axis to 0–1.
    conf = _clamp((best_confidence - 0.5) / 0.45)      # 0.50→0, 0.95→1
    geo = _clamp(geo_plausibility / 0.35)              # 0.35+→1, 0.05→0.14
    corr = _clamp((count - 1) / 4)                     # 1→0, 5+→1

    score = 0.40 * conf + 0.35 * geo + 0.25 * corr
    tier = "confirmed" if score >= 0.66 else "probable" if score >= 0.42 else "tentative"

    reasons: list[str] = []

    # Geographic plausibility — the signal confidence can't provide. "Confirmed"
    # is reserved for birds genuinely expected here; anything less common is
    # capped, no matter how confident or repeated (repeated identical false
    # positives are a real BirdNET failure mode).
    if geo_plausibility < 0.10:
        reasons.append("unusual for this area")
        tier = "tentative"
    elif geo_plausibility < 0.30:
        reasons.append("uncommon here")
        tier = _cap(tier, "probable")

    # Corroboration.
    if count == 1:
        reasons.append("heard only once")
        if best_confidence < 0.75:
            tier = _cap(tier, "probable")

    # Acoustic clarity — "confirmed" needs a genuinely clear match (≥0.70).
    if best_confidence < 0.60:
        reasons.append("a faint match")
        tier = _cap(tier, "tentative")
    elif best_confidence < 0.70:
        reasons.append("a soft match")
        tier = _cap(tier, "probable")

    if tier == "confirmed" and not reasons:
        reasons.append("heard clearly and often")

    return Assessment(tier=tier, score=round(score, 2), reasons=reasons)


def is_reliable(a: Assessment) -> bool:
    """Trustworthy enough to show prominently (not tucked away as doubtful)."""
    return a.tier in ("confirmed", "probable")


# Habitat-agnostic plausibility floor for the artwork: BirdNET's geo model treats
# some wetland birds as regionally possible even where there's no water, so a
# whole cluster of confident-but-implausible water birds can slip through. The
# picture should only celebrate birds both trustworthy AND genuinely likely here.
ARTWORK_GEO_FLOOR = 0.30


def for_artwork(a: Assessment, geo_plausibility: float) -> bool:
    if a.tier == "confirmed":
        return True
    if a.tier == "probable" and geo_plausibility >= ARTWORK_GEO_FLOOR:
        return True
    return False
