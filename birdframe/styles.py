"""Editable art directions, their history, and data-responsive selection."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"

# A fixed, representative scene so style previews are comparable to each other.
SAMPLE_SCENE = ("an Edinburgh garden on a bright spring morning: a European Robin "
                "singing prominently, with a Common Blackbird, a Blue Tit and a "
                "Eurasian Wren nearby")


@dataclass(frozen=True)
class Style:
    name: str
    prompt: str
    avoid: str = ""
    collection: str = "Uncategorised"
    description: str = ""
    lineage: str = ""
    medium: str = ""
    palette: str = ""
    affinities: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class StyleRecommendation:
    """One explainable place in the art director's ranked shortlist."""

    style: Style
    score: int
    matched: tuple[str, ...]
    reason: str


def _section(text: str, header: str) -> str:
    m = re.search(rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
                  text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _items(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        item.strip().lower().replace(" ", "-")
        for item in re.split(r"[,\n]", value)
        if item.strip()
    ))


def load_styles(styles_dir: Path = DEFAULT_STYLES_DIR) -> list[Style]:
    styles = []
    for path in sorted(Path(styles_dir).glob("*.md")):
        text = path.read_text()
        styles.append(Style(
            name=path.stem,
            prompt=_section(text, "Prompt"),
            avoid=_section(text, "Avoid"),
            collection=_section(text, "Collection") or "Uncategorised",
            description=_section(text, "Description"),
            lineage=_section(text, "Lineage"),
            medium=_section(text, "Medium"),
            palette=_section(text, "Palette"),
            affinities=_items(_section(text, "Affinities")),
            source=_section(text, "Source"),
        ))
    return styles


_TAG_LABELS = {
    "all-day": "an all-day soundscape",
    "autumn": "an autumn day",
    "changeable": "changeable weather",
    "clear": "clear weather",
    "dawn-heavy": "a dawn-led chorus",
    "dominant-species": "one commanding voice",
    "dusk-heavy": "an evening-led chorus",
    "even-chorus": "a balanced chorus",
    "first-arrival": "a first arrival",
    "fog": "a misty day",
    "night-active": "a nocturnal soundscape",
    "rain": "a rain-washed day",
    "snow": "a snowy day",
    "sparse": "a quiet, spacious day",
    "species-rich": "a species-rich chorus",
    "spring": "a spring day",
    "summer": "a summer day",
    "winter": "a winter day",
    "wind": "a windswept day",
}


def _profile_tags(profile: Any) -> tuple[str, ...]:
    if profile is None:
        return ()
    tags = profile.get("tags", ()) if isinstance(profile, dict) else getattr(profile, "tags", ())
    return tuple(str(tag).lower().replace(" ", "-") for tag in tags)


def _recommendation_reason(style: Style, matched: tuple[str, ...]) -> str:
    if matched:
        qualities = [_TAG_LABELS.get(tag, tag.replace("-", " ")) for tag in matched[:2]]
        fit = " and ".join(qualities)
        medium = f"Its {style.medium}" if style.medium else "Its visual language"
        return f"{medium} is especially suited to {fit}."
    return "A contrasting interpretation chosen to keep the daily collection surprising."


def recommend_styles(styles, profile=None, day_index: int = 0) -> list[StyleRecommendation]:
    """Rank styles by their declared affinities, with deterministic variety."""
    if not styles:
        return []
    tags = set(_profile_tags(profile))
    weights = {
        "night-active": 26, "dawn-heavy": 24, "dusk-heavy": 22,
        "all-day": 18, "first-arrival": 15, "dominant-species": 12,
        "even-chorus": 12, "species-rich": 10, "sparse": 10,
        "rain": 6, "snow": 6, "fog": 6, "wind": 6, "clear": 4,
        "changeable": 3, "spring": 3, "summer": 3, "autumn": 3, "winter": 3,
    }
    ranked = []
    total = len(styles)
    for index, style in enumerate(styles):
        matched = tuple(sorted(
            (tag for tag in style.affinities if tag in tags),
            key=lambda tag: (-weights.get(tag, 1), style.affinities.index(tag)),
        ))
        # Specific affinities matter; ordinal distance makes ties rotate without
        # adding randomness, so the same archive day always gets the same answer.
        score = sum(weights.get(tag, 1) for tag in matched)
        tie_break = (index - day_index) % total
        ranked.append((score, tie_break, style, matched))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2].name))
    return [
        StyleRecommendation(style, score, matched, _recommendation_reason(style, matched))
        for score, _, style, matched in ranked
    ]


def choose_style(styles, mode="rotate", day_index=0, pinned="", profile=None) -> Style:
    if not styles:
        raise ValueError("no styles available")
    if mode == "pinned" and pinned:
        for s in styles:
            if s.name == pinned:
                return s
    if mode == "responsive":
        return recommend_styles(styles, profile, day_index)[0].style
    return styles[day_index % len(styles)]


def style_choice_reason(style: Style, styles, mode: str, day_index: int,
                        pinned: str = "", profile=None, explicit: bool = False) -> str:
    if explicit:
        return "Chosen by you for this edition."
    if mode == "pinned" and pinned == style.name:
        return "Pinned as your house style."
    if mode == "responsive":
        for recommendation in recommend_styles(styles, profile, day_index):
            if recommendation.style.name == style.name:
                return recommendation.reason
    return "Today's turn in the collection."


def slugify(name: str) -> str:
    """A safe, stable filename stem for a style (also its display name)."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def style_to_markdown(style: Style) -> str:
    md = f"# {style.name}\n"
    metadata = (
        ("Collection", style.collection if style.collection != "Uncategorised" else ""),
        ("Description", style.description),
        ("Lineage", style.lineage),
        ("Medium", style.medium),
        ("Palette", style.palette),
        ("Affinities", ", ".join(style.affinities)),
        ("Source", style.source),
    )
    for header, value in metadata:
        if value.strip():
            md += f"\n## {header}\n{value.strip()}\n"
    md += f"\n## Prompt\n{style.prompt.strip()}\n"
    if style.avoid.strip():
        md += f"\n## Avoid\n{style.avoid.strip()}\n"
    return md


def get_style(styles_dir: Path, name: str) -> Style | None:
    for s in load_styles(styles_dir):
        if s.name == slugify(name):
            return s
    return None


def save_style(styles_dir: Path, name: str, prompt: str, avoid: str = "",
               collection: str = "Uncategorised", description: str = "",
               lineage: str = "", medium: str = "", palette: str = "",
               affinities=(), source: str = "") -> str:
    """Create or overwrite a style markdown file. Returns the slug used."""
    slug = slugify(name)
    if not slug:
        raise ValueError("style name must contain letters or digits")
    if "{scene}" not in prompt:
        raise ValueError("prompt must include the {scene} placeholder")
    Path(styles_dir).mkdir(parents=True, exist_ok=True)
    path = Path(styles_dir) / f"{slug}.md"
    if isinstance(affinities, str):
        affinities = _items(affinities)
    else:
        affinities = tuple(str(item).strip().lower().replace(" ", "-")
                           for item in affinities if str(item).strip())
    path.write_text(style_to_markdown(Style(
        slug, prompt, avoid, collection or "Uncategorised", description,
        lineage, medium, palette, affinities, source,
    )))
    return slug


def delete_style(styles_dir: Path, name: str) -> bool:
    path = Path(styles_dir) / f"{slugify(name)}.md"
    if path.exists():
        path.unlink()
        return True
    return False
