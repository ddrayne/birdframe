"""The background loops wired up in app.main: scheduling and notice throttling."""
from datetime import datetime

from birdframe.app import _first_notice_in, _scheduler_step


class FakeRuntime:
    def __init__(self, restart=False):
        self.restart = restart
        self.ticks = []

    def should_restart_for_freshness(self, now):
        return self.restart

    def tick(self, now=None):
        self.ticks.append(now)


def test_scheduler_step_ticks_with_the_given_time():
    runtime, now = FakeRuntime(), datetime(2026, 9, 25, 21, 0)
    _scheduler_step(runtime, now, exit_process=lambda code: None)
    assert runtime.ticks == [now]


def test_scheduler_step_restarts_before_posting():
    exits = []
    runtime = FakeRuntime(restart=True)
    _scheduler_step(runtime, datetime(2026, 9, 25, 4, 0), exit_process=exits.append)
    assert exits == [0]
    assert runtime.ticks == []


def test_notice_is_throttled_across_restarts(tmp_path):
    marker = tmp_path / ".notice-restart"
    assert _first_notice_in(marker, hours=6, now=1_000_000)
    # A fresh process (same marker on disk) inside the window stays quiet…
    assert not _first_notice_in(marker, hours=6, now=1_000_000 + 60)
    assert not _first_notice_in(marker, hours=6, now=1_000_000 + 5 * 3600)
    # …and speaks again once the window has passed.
    assert _first_notice_in(marker, hours=6, now=1_000_000 + 6 * 3600 + 1)
