"""Art styles loaded from markdown files; daily rotation or a pinned choice."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"

# A fixed, representative scene so style previews are comparable to each other.
SAMPLE_SCENE = ("an Edinburgh garden on a bright spring morning: a European Robin "
                "singing prominently, with a Common Blackbird, a Blue Tit and a "
                "Eurasian Wren nearby")


@dataclass
class Style:
    name: str
    prompt: str
    avoid: str = ""


def _section(text: str, header: str) -> str:
    m = re.search(rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)",
                  text, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def load_styles(styles_dir: Path = DEFAULT_STYLES_DIR) -> list[Style]:
    styles = []
    for path in sorted(Path(styles_dir).glob("*.md")):
        text = path.read_text()
        styles.append(Style(
            name=path.stem,
            prompt=_section(text, "Prompt"),
            avoid=_section(text, "Avoid"),
        ))
    return styles


def choose_style(styles, mode="rotate", day_index=0, pinned="") -> Style:
    if not styles:
        raise ValueError("no styles available")
    if mode == "pinned" and pinned:
        for s in styles:
            if s.name == pinned:
                return s
    return styles[day_index % len(styles)]


def slugify(name: str) -> str:
    """A safe, stable filename stem for a style (also its display name)."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def style_to_markdown(style: Style) -> str:
    md = f"# {style.name}\n\n## Prompt\n{style.prompt.strip()}\n"
    if style.avoid.strip():
        md += f"\n## Avoid\n{style.avoid.strip()}\n"
    return md


def get_style(styles_dir: Path, name: str) -> Style | None:
    for s in load_styles(styles_dir):
        if s.name == slugify(name):
            return s
    return None


def save_style(styles_dir: Path, name: str, prompt: str, avoid: str = "") -> str:
    """Create or overwrite a style markdown file. Returns the slug used."""
    slug = slugify(name)
    if not slug:
        raise ValueError("style name must contain letters or digits")
    if "{scene}" not in prompt:
        raise ValueError("prompt must include the {scene} placeholder")
    Path(styles_dir).mkdir(parents=True, exist_ok=True)
    path = Path(styles_dir) / f"{slug}.md"
    path.write_text(style_to_markdown(Style(slug, prompt, avoid)))
    return slug


def delete_style(styles_dir: Path, name: str) -> bool:
    path = Path(styles_dir) / f"{slugify(name)}.md"
    if path.exists():
        path.unlink()
        return True
    return False
