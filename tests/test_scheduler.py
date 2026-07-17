from datetime import datetime

from birdframe.scheduler import decide, parse_slots, SchedulerState


def _state(**kw):
    base = dict(mode="daily", slots=[("21:00", "")], last_post=None,
                live_min_gap_minutes=120, live_window_start="08:00",
                live_window_end="22:00", new_species_today=False)
    base.update(kw)
    return SchedulerState(**base)


# ── parse_slots ──────────────────────────────────────────────────────────────

def test_parse_slots_empty_synthesizes_legacy_post_time():
    assert parse_slots("", "21:00") == [("21:00", "")]


def test_parse_slots_times_with_optional_labels():
    assert parse_slots("06:30 dawn, 12:00, 21:00 evening", "20:00") == [
        ("06:30", "dawn"), ("12:00", ""), ("21:00", "evening"),
    ]


def test_parse_slots_sorts_drops_malformed_and_duplicates():
    assert parse_slots("21:00 dusk, nonsense, 6:30 dawn, 25:99, 21:00", "20:00") == [
        ("06:30", "dawn"), ("21:00", "dusk"),
    ]


def test_parse_slots_all_malformed_falls_back_to_legacy():
    assert parse_slots("gibberish, more junk", "21:00") == [("21:00", "")]


# ── daily slots ──────────────────────────────────────────────────────────────

def test_daily_fires_once_at_post_time():
    st = _state(last_post=None)
    assert decide(st, datetime(2026, 7, 5, 21, 0)) == ("daily", ("21:00", ""))
    st2 = _state(last_post=datetime(2026, 7, 5, 21, 0))
    assert decide(st2, datetime(2026, 7, 5, 21, 5)) is None


def test_daily_does_not_fire_before_time():
    st = _state(last_post=None)
    assert decide(st, datetime(2026, 7, 5, 20, 59)) is None


def test_multi_slot_fires_each_once_as_day_advances():
    slots = [("06:30", "dawn"), ("12:00", ""), ("21:00", "evening")]
    st = _state(slots=slots, last_post=None)
    assert decide(st, datetime(2026, 7, 5, 6, 30)) == ("daily", ("06:30", "dawn"))
    st = _state(slots=slots, last_post=datetime(2026, 7, 5, 6, 30))
    assert decide(st, datetime(2026, 7, 5, 6, 31)) is None
    assert decide(st, datetime(2026, 7, 5, 12, 0)) == ("daily", ("12:00", ""))
    st = _state(slots=slots, last_post=datetime(2026, 7, 5, 12, 0))
    assert decide(st, datetime(2026, 7, 5, 20, 59)) is None
    assert decide(st, datetime(2026, 7, 5, 21, 0)) == ("daily", ("21:00", "evening"))
    st = _state(slots=slots, last_post=datetime(2026, 7, 5, 21, 0))
    assert decide(st, datetime(2026, 7, 5, 23, 59)) is None


def test_catch_up_fires_only_latest_missed_slot():
    # Mac slept through dawn and midday; on wake only the latest missed slot fires.
    slots = [("06:30", "dawn"), ("12:00", "midday"), ("21:00", "evening")]
    st = _state(slots=slots, last_post=datetime(2026, 7, 4, 21, 0))
    assert decide(st, datetime(2026, 7, 5, 13, 15)) == ("daily", ("12:00", "midday"))
    # After handling it, nothing more until the evening slot.
    st = _state(slots=slots, last_post=datetime(2026, 7, 5, 13, 15))
    assert decide(st, datetime(2026, 7, 5, 13, 16)) is None


def test_slot_fires_again_next_day():
    slots = [("06:30", "dawn"), ("21:00", "")]
    st = _state(slots=slots, last_post=datetime(2026, 7, 4, 21, 0))
    assert decide(st, datetime(2026, 7, 5, 6, 30)) == ("daily", ("06:30", "dawn"))


def test_late_started_post_does_not_refire_same_slot():
    # A slot handled late (e.g. posted 21:07 for the 21:00 slot) stays handled.
    st = _state(last_post=datetime(2026, 7, 5, 21, 7))
    assert decide(st, datetime(2026, 7, 5, 21, 8)) is None


# ── manual / live (unchanged behavior, new return shape) ────────────────────

def test_manual_never_fires():
    st = _state(mode="manual", new_species_today=True)
    assert decide(st, datetime(2026, 7, 5, 21, 0)) is None


def test_live_fires_on_new_species_within_window_respecting_gap():
    st = _state(mode="live", new_species_today=True, last_post=None)
    assert decide(st, datetime(2026, 7, 5, 10, 0)) == ("live", None)
    st2 = _state(mode="live", new_species_today=True,
                 last_post=datetime(2026, 7, 5, 9, 30))
    assert decide(st2, datetime(2026, 7, 5, 10, 0)) is None
    # outside the daytime window (daily final edition already posted at 21:00)
    st3 = _state(mode="live", new_species_today=True,
                 last_post=datetime(2026, 7, 5, 21, 0))
    assert decide(st3, datetime(2026, 7, 5, 23, 0)) is None


def test_live_still_does_daily_final_edition():
    st = _state(mode="live", new_species_today=False, last_post=None)
    assert decide(st, datetime(2026, 7, 5, 21, 0)) == ("daily", ("21:00", ""))
