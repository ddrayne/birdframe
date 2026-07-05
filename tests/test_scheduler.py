from datetime import datetime

from birdframe.scheduler import decide, SchedulerState


def _state(**kw):
    base = dict(mode="daily", post_time="21:00", last_post=None,
                live_min_gap_minutes=120, live_window_start="08:00",
                live_window_end="22:00", new_species_today=False)
    base.update(kw)
    return SchedulerState(**base)


def test_daily_fires_once_at_post_time():
    st = _state(mode="daily", last_post=None)
    assert decide(st, datetime(2026, 7, 5, 21, 0)) == "daily"
    st2 = _state(mode="daily", last_post=datetime(2026, 7, 5, 21, 0))
    assert decide(st2, datetime(2026, 7, 5, 21, 5)) is None


def test_daily_does_not_fire_before_time():
    st = _state(mode="daily", last_post=None)
    assert decide(st, datetime(2026, 7, 5, 20, 59)) is None


def test_manual_never_fires():
    st = _state(mode="manual", new_species_today=True)
    assert decide(st, datetime(2026, 7, 5, 21, 0)) is None


def test_live_fires_on_new_species_within_window_respecting_gap():
    st = _state(mode="live", new_species_today=True, last_post=None)
    assert decide(st, datetime(2026, 7, 5, 10, 0)) == "live"
    st2 = _state(mode="live", new_species_today=True,
                 last_post=datetime(2026, 7, 5, 9, 30))
    assert decide(st2, datetime(2026, 7, 5, 10, 0)) is None
    # outside the daytime window (daily final edition already posted at 21:00)
    st3 = _state(mode="live", new_species_today=True,
                 last_post=datetime(2026, 7, 5, 21, 0))
    assert decide(st3, datetime(2026, 7, 5, 23, 0)) is None


def test_live_still_does_daily_final_edition():
    st = _state(mode="live", new_species_today=False, last_post=None)
    assert decide(st, datetime(2026, 7, 5, 21, 0)) == "daily"
