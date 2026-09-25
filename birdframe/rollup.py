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


_PRECIPITATION = ("rain", "drizzle", "shower", "snow", "sleet")

# Number-free phrases for the day's rhythm. Counts in a prompt tend to come
# back as printed digits, or as that many birds.
_CHARACTER = {
    "dawn-heavy": "most of its song came at dawn",
    "dusk-heavy": "its chorus gathered toward evening",
    "night-active": "voices carried on into the night",
    "all-day": "song ran from early until late",
    "species-rich": "an unusually varied chorus",
    "even-chorus": "many voices in balance",
    "dominant-species": "one voice held the day",
    "sparse": "a quiet, spacious day",
}


# A note that only restates the archetype is left out.
_ARCHETYPE_NOTES = {
    "Dawn chorus": "dawn-heavy", "Evening gathering": "dusk-heavy",
    "Night watch": "night-active", "All-day soundscape": "all-day",
    "Singular voice": "dominant-species", "Quiet garden": "sparse",
}


def _a(phrase: str) -> str:
    return f"{'an' if phrase[:1].lower() in 'aeiou' else 'a'} {phrase}"


def _setting(weather: str, season: str, tod: str) -> str:
    moment = _a(f"{season} {tod}")
    if any(word in weather for word in _PRECIPITATION):
        return f"an Edinburgh garden on {moment} in {weather}"   # "... in light rain"
    return f"an Edinburgh garden on {moment} under {weather} skies"


def _voice(s: SpeciesDay) -> str:
    # The scientific name pins down the exact species where English names
    # differ between checklists and field guides.
    return f"{s.common_name} ({s.scientific_name})" if s.scientific_name else s.common_name


def _character(profile: ArtProfile) -> str:
    skip = _ARCHETYPE_NOTES.get(profile.archetype)
    notes = [_CHARACTER[tag] for tag in profile.tags if tag in _CHARACTER and tag != skip]
    return f"the day's character: {_a(profile.archetype.lower())}" + (
        f" — {', '.join(notes[:3])}" if notes else "")


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
    parts = [_setting(weather, season, tod)]
    lead = ranked[0]
    parts.append(f"the {_voice(lead)} singing prominently as the day's leading voice")
    others = [_voice(s) for s in ranked[1:6]]
    if others:
        joined = others[0] if len(others) == 1 else f"{', '.join(others[:-1])} and {others[-1]}"
        parts.append(f"with {joined} nearby")
    if len(species) > 1:     # with one voice these would only repeat the lead
        parts.append(f"the {dawn.common_name} opened the dawn chorus")
        parts.append(f"the {latest.common_name} sang latest into the {tod}")
    debuts = [s.common_name for s in ranked if s.common_name in first_ever]
    if debuts:
        parts.append("heard here for the very first time today, and quietly honoured: "
                     + ", ".join(debuts))
    if profile is not None:
        parts.append(_character(profile))
        parts.append("translate the day's activity into visual rhythm, layering and negative "
                     "space, never into a literal number of individual birds")
    return "; ".join(parts)


ACCURACY = ("Render every bird's plumage, size, beak shape and markings accurately "
            "and true to the real species, so each is recognisable to a birdwatcher, "
            "and keep their sizes true to one another.")

# The picture hangs on an e-ink frame across a room; clear value structure
# survives its limited palette far better than faint washes.
DISPLAY = ("It will hang on an e-ink picture frame, so let the composition read "
           "clearly from across a room, with confident tonal contrast.")


def build_prompt(style: Style, scene: str) -> str:
    prompt = style.prompt.replace("{scene}", scene).strip()
    prompt += f"\n\n{ACCURACY} {DISPLAY}"
    if style.avoid:
        prompt += f"\n\nAvoid: {style.avoid}"
    return prompt
