"""The background loops wired up in app.main: scheduling and notice throttling."""
from datetime import datetime

import os
import signal
import threading

from birdframe.app import _first_notice_in, _scheduler_step, _serve_headless


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


class FakeListener:
    def __init__(self):
        self.calls = []

    def stop(self):
        self.calls.append("stop")

    def join(self, timeout=None):
        self.calls.append("join")


class ListeningRuntime:
    def __init__(self):
        self.listener = FakeListener()


def test_headless_releases_the_microphone_when_stopped():
    runtime, stop = ListeningRuntime(), threading.Event()
    stop.set()
    _serve_headless(runtime, stop)
    assert runtime.listener.calls == ["stop", "join"]


def test_headless_stops_on_sigterm():
    """systemd stops a service with SIGTERM; that must end the wait promptly."""
    runtime = ListeningRuntime()
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    timer = threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGTERM))
    try:
        timer.start()
        _serve_headless(runtime)
    finally:
        timer.cancel()
        for sig, handler in saved.items():
            signal.signal(sig, handler)
    assert runtime.listener.calls == ["stop", "join"]
