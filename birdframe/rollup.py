"""Turn a day's detections into a scene description for the image prompt."""
from __future__ import annotations

from datetime import datetime

from birdframe.store import SpeciesDay
from birdframe.styles import Style

_SEASONS = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn",
            10: "autumn", 11: "autumn"}


def season_for(when: datetime) -> str:
    return _SEASONS[when.month]


def _time_of_day(when: datetime) -> str:
    h = when.hour
    if h < 8:
        return "early morning"
    if h < 12:
        return "morning"
    if h < 17:
        return "afternoon"
    if h < 21:
        return "evening"
    return "dusk"


def build_scene(species: list[SpeciesDay], first_ever: set[str],
                weather: str, when: datetime) -> str:
    season = season_for(when)
    tod = _time_of_day(when)
    if not species:
        return (f"a quiet Edinburgh garden on a {weather} {season} {tod}, "
                f"with no birds singing today")
    ranked = species  # already sorted by count desc from the store
    dawn = min(species, key=lambda s: s.first_heard)
    latest = max(species, key=lambda s: s.last_heard)
    parts = [f"an Edinburgh garden on a {weather} {season} {tod}"]
    lead = ranked[0]
    parts.append(f"{lead.common_name} singing prominently (heard {lead.count} "
                 f"times today)")
    for s in ranked[1:6]:
        parts.append(s.common_name)
    parts.append(f"{dawn.common_name} opened the dawn chorus")
    parts.append(f"{latest.common_name} sang latest into the {tod}")
    debuts = [s.common_name for s in ranked if s.common_name in first_ever]
    if debuts:
        parts.append("first ever heard here today: " + ", ".join(debuts))
    return "; ".join(parts)


def build_prompt(style: Style, scene: str) -> str:
    prompt = style.prompt.replace("{scene}", scene).strip()
    if style.avoid:
        prompt += f"\n\nAvoid: {style.avoid}"
    return prompt
