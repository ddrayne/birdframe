"""Art styles loaded from markdown files; daily rotation or a pinned choice."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"


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
