"""The few things that differ between a Mac with a menu bar and a headless
Linux box such as a Raspberry Pi: where the log lives, keeping the machine
awake, and desktop notifications. Everything else runs the same on both."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"

log = logging.getLogger("birdframe")


def log_path() -> Path:
    """~/Library/Logs on a Mac; the XDG state directory elsewhere."""
    if IS_MAC:
        return Path.home() / "Library" / "Logs" / "birdframe.log"
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "birdframe" / "birdframe.log"


LOG_PATH = log_path()


def keep_awake() -> None:
    """Keep a Mac from idle-sleeping through the dawn chorus. A Pi never sleeps."""
    if not IS_MAC:
        return
    try:
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    except Exception as exc:  # non-fatal
        log.warning("caffeinate unavailable: %s", exc)


def _osa_quote(s: str) -> str:
    """A safe AppleScript string literal (double-quoted, escaped)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title: str, message: str) -> None:
    """A desktop notification on a Mac. A headless box has no desktop, so
    there it is a log line; the dashboard shows the same health anyway."""
    if not IS_MAC:
        log.info("%s: %s", title, message)
        return
    try:
        script = (f"display notification {_osa_quote(message)} "
                  f"with title {_osa_quote(title)} sound name \"Glass\"")
        subprocess.run(["osascript", "-e", script], check=False, timeout=5,
                       capture_output=True)  # don't spam osascript errors into the log
    except Exception as exc:  # notifications are best-effort
        log.debug("notification failed: %s", exc)
