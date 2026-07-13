"""Turn a day's detections into a scene description for the image prompt."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
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


@dataclass(frozen=True)
class ArtProfile:
    """The day's acoustic character, expressed without changing its data."""

    species_count: int
    detection_count: int
    dominant_share: float
    evenness: float
    hours: tuple[int, ...]
    dawn_share: float
    dusk_share: float
    night_share: float
    active_span_hours: int
    debut_count: int
    season: str
    weather: str
    archetype: str
    tags: tuple[str, ...]
    summary: str


def _weather_tags(weather: str) -> list[str]:
    text = weather.lower()
    tags = []
    for needle, tag in (("rain", "rain"), ("drizzle", "rain"),
                        ("fog", "fog"), ("mist", "fog"),
                        ("snow", "snow"), ("sleet", "snow"),
                        ("wind", "wind"), ("gale", "wind"),
                        ("clear", "clear"), ("sun", "clear")):
        if needle in text and tag not in tags:
            tags.append(tag)
    return tags or ["changeable"]


def build_art_profile(species: list[SpeciesDay], hours: list[int] | tuple[int, ...],
                      first_ever: set[str], weather: str, when: datetime) -> ArtProfile:
    """Build a deterministic art-direction fingerprint from existing rollups."""
    clock = tuple((list(hours) + [0] * 24)[:24])
    counts = [max(0, species_day.count) for species_day in species]
    total = sum(counts)
    species_count = len(species)
    dominant_share = max(counts, default=0) / total if total else 0.0
    if species_count > 1 and total:
        proportions = [count / total for count in counts if count]
        evenness = -sum(p * math.log(p) for p in proportions) / math.log(species_count)
    else:
        evenness = 0.0
    heard = sum(clock)
    basis = heard or total or 1
    dawn_share = sum(clock[4:10]) / basis
    dusk_share = sum(clock[17:22]) / basis
    night_share = (sum(clock[:4]) + sum(clock[22:])) / basis
    active = [hour for hour, count in enumerate(clock) if count]
    span = active[-1] - active[0] + 1 if active else 0
    debuts = sum(s.common_name in first_ever for s in species)

    tags = [season_for(when)]
    tags.extend(_weather_tags(weather))
    if species_count <= 3 or total <= 8:
        tags.append("sparse")
    if species_count >= 7:
        tags.append("species-rich")
    if dominant_share >= .62:
        tags.append("dominant-species")
    elif species_count >= 3 and evenness >= .72:
        tags.append("even-chorus")
    if dawn_share >= .42:
        tags.append("dawn-heavy")
    if dusk_share >= .34:
        tags.append("dusk-heavy")
    if night_share >= .28:
        tags.append("night-active")
    if span >= 13:
        tags.append("all-day")
    if debuts:
        tags.append("first-arrival")

    if not species_count:
        archetype = "Quiet garden"
    elif species_count == 1 or dominant_share >= .72:
        archetype = "Singular voice"
    elif species_count >= 8 and evenness >= .65:
        archetype = "Many-voiced chorus"
    elif dawn_share >= .42:
        archetype = "Dawn chorus"
    elif dusk_share >= .34:
        archetype = "Evening gathering"
    elif night_share >= .28:
        archetype = "Night watch"
    elif span >= 13:
        archetype = "All-day soundscape"
    else:
        archetype = "Garden ensemble"

    if dawn_share >= max(dusk_share, night_share, .25):
        cadence = "strongest around dawn"
    elif dusk_share >= max(dawn_share, night_share, .25):
        cadence = "gathering toward evening"
    elif night_share >= max(dawn_share, dusk_share, .2):
        cadence = "with an unusual nocturnal presence"
    elif span:
        cadence = f"moving across {span} active hours"
    else:
        cadence = "held in generous quiet"
    summary = (f"{archetype}: {species_count} species and {total} detections, "
               f"{cadence}.")
    return ArtProfile(
        species_count, total, round(dominant_share, 3), round(evenness, 3), clock,
        round(dawn_share, 3), round(dusk_share, 3), round(night_share, 3), span,
        debuts, season_for(when), weather, archetype, tuple(dict.fromkeys(tags)), summary,
    )


def profile_to_dict(profile: ArtProfile) -> dict:
    data = asdict(profile)
    data["hours"] = list(profile.hours)
    data["tags"] = list(profile.tags)
    return data


def build_scene(species: list[SpeciesDay], first_ever: set[str],
                weather: str, when: datetime, profile: ArtProfile | None = None) -> str:
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
    if profile is not None:
        parts.append(f"the acoustic character of the day was {profile.summary.lower()}")
        parts.append("translate detection volume into visual rhythm, layering and negative "
                     "space, never into a literal number of individual birds")
    return "; ".join(parts)


ACCURACY = ("Render every bird's plumage, size, beak shape and markings accurately "
            "and true to the real species, so each is recognisable to a birdwatcher.")


def build_prompt(style: Style, scene: str) -> str:
    prompt = style.prompt.replace("{scene}", scene).strip()
    prompt += f"\n\n{ACCURACY}"
    if style.avoid:
        prompt += f"\n\nAvoid: {style.avoid}"
    return prompt
