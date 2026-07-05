"""A short, evocative sentence about the day's birdlife — the story of the day.

Uses a cheap text model when a key is available; falls back to a tidy template
otherwise, so the feature always works.
"""
from __future__ import annotations

import logging

log = logging.getLogger("birdframe")

SYSTEM = (
    "You are a nature writer. In ONE short, warm sentence (max 30 words), evoke a "
    "day of birdsong heard at a window. Be specific and grounded — no clichés, no "
    "exclamation marks, no lists. British spelling."
)


def _fallback(species: list[str], weather: str, season: str, tod: str) -> str:
    if not species:
        return f"A quiet {weather} {season} {tod} — the garden kept its own counsel."
    lead = species[0]
    others = species[1:3]
    tail = (" with " + " and ".join(others)) if others else ""
    return f"A {weather} {season} {tod}: the {lead} led the garden{tail}."


def narrate(species: list[str], weather: str, season: str, tod: str,
            dawn_bird: str | None = None, client=None, model: str = "gpt-4.1-mini") -> str:
    if client is None:
        return _fallback(species, weather, season, tod)
    facts = (f"Weather: {weather}. Season: {season}. Time: {tod}. "
             f"Birds heard (most first): {', '.join(species) if species else 'none'}. "
             + (f"First to sing at dawn: {dawn_bird}." if dawn_bird else ""))
    try:
        resp = client.chat.completions.create(
            model=model, temperature=0.8, max_tokens=60,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": facts}],
        )
        text = resp.choices[0].message.content.strip().strip('"')
        return text or _fallback(species, weather, season, tod)
    except Exception as exc:  # never let narration break anything
        log.warning("Narration failed (%s) — using template", exc)
        return _fallback(species, weather, season, tod)
