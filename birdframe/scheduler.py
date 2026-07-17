"""When to generate + publish. Pure decision logic; the runner just ticks it."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

_SLOT_RE = re.compile(r"^(\d{1,2}):(\d{2})(?:\s+(.*\S))?$")


@dataclass
class SchedulerState:
    mode: str                        # daily | live | manual
    slots: list                      # [("HH:MM", "label"), ...] sorted by time
    last_post: datetime | None
    live_min_gap_minutes: int
    live_window_start: str
    live_window_end: str
    new_species_today: bool


def parse_slots(post_times: str, fallback_post_time: str) -> list[tuple[str, str]]:
    """Parse 'HH:MM [label], HH:MM [label], …' into sorted (time, label) slots.

    Malformed entries and duplicate times are dropped; an empty result falls
    back to a single slot at the legacy post_time, so old configs keep working.
    """
    slots: dict[str, str] = {}
    for part in (post_times or "").split(","):
        m = _SLOT_RE.match(part.strip())
        if not m:
            continue
        h, mnt = int(m.group(1)), int(m.group(2))
        if not (0 <= h <= 23 and 0 <= mnt <= 59):
            continue
        slots.setdefault(f"{h:02d}:{mnt:02d}", m.group(3) or "")
    if not slots:
        return [(fallback_post_time, "")]
    return sorted(slots.items())


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _due_slot(slots: list, last_post: datetime | None,
              now: datetime) -> tuple[str, str] | None:
    """The latest of today's slots at/before now that hasn't been handled yet.

    Picking the *latest* is the catch-up rule: after a sleep or restart that
    missed several slots, only the most recent one fires — never a burst.
    """
    due = [s for s in slots if _parse_hm(s[0]) <= (now.hour, now.minute)]
    if not due:
        return None
    slot = due[-1]                    # slots are sorted by time
    if last_post is not None and last_post.date() == now.date():
        h, m = _parse_hm(slot[0])
        slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if last_post >= slot_dt:
            return None               # this slot (or a later action) already handled
    return slot


def decide(state: SchedulerState, now: datetime) -> tuple[str, tuple[str, str] | None] | None:
    """Return ("daily", slot), ("live", None), or None."""
    if state.mode == "manual":
        return None

    # Both daily and live honour the fixed scheduled editions.
    slot = _due_slot(state.slots, state.last_post, now)
    if slot is not None:
        return ("daily", slot)

    if state.mode == "live" and state.new_species_today:
        start = _parse_hm(state.live_window_start)
        end = _parse_hm(state.live_window_end)
        if not (start <= (now.hour, now.minute) <= end):
            return None
        if state.last_post is not None:
            gap = (now - state.last_post).total_seconds() / 60
            if gap < state.live_min_gap_minutes:
                return None
        return ("live", None)
    return None
