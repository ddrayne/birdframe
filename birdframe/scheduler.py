"""When to generate + publish. Pure decision logic; the runner just ticks it."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SchedulerState:
    mode: str            # daily | live | manual
    post_time: str       # "HH:MM"
    last_post: datetime | None
    live_min_gap_minutes: int
    live_window_start: str
    live_window_end: str
    new_species_today: bool


def _parse_hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _posted_today(last_post: datetime | None, now: datetime) -> bool:
    return last_post is not None and last_post.date() == now.date()


def _daily_due(state: SchedulerState, now: datetime) -> bool:
    h, m = _parse_hm(state.post_time)
    at_or_after = (now.hour, now.minute) >= (h, m)
    return at_or_after and not _posted_today(state.last_post, now)


def decide(state: SchedulerState, now: datetime) -> str | None:
    """Return 'daily', 'live', or None."""
    if state.mode == "manual":
        return None

    # Both daily and live honour the fixed daily 'final edition'.
    if _daily_due(state, now):
        return "daily"

    if state.mode == "live" and state.new_species_today:
        start = _parse_hm(state.live_window_start)
        end = _parse_hm(state.live_window_end)
        if not (start <= (now.hour, now.minute) <= end):
            return None
        if state.last_post is not None:
            gap = (now - state.last_post).total_seconds() / 60
            if gap < state.live_min_gap_minutes:
                return None
        return "live"
    return None
