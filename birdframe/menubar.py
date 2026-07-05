"""macOS menu bar app (rumps). Thin UI over Runtime; all logic lives elsewhere."""
from __future__ import annotations

import threading
import webbrowser

import rumps


class BirdframeMenuBar(rumps.App):
    def __init__(self, runtime, dashboard_port: int):
        super().__init__("🐦", quit_button=None)
        self.runtime = runtime
        self.dashboard_port = dashboard_port
        self.menu = [
            rumps.MenuItem("Species today: …", callback=None),
            None,
            rumps.MenuItem("Post now", callback=self._post_now),
            rumps.MenuItem("Pause listening", callback=self._toggle_pause),
            None,
            rumps.MenuItem("Open dashboard", callback=self._open_dashboard),
            None,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]
        self._paused = False
        self._timer = rumps.Timer(self._tick, 30)
        self._timer.start()

    def _tick(self, _):
        try:
            self.runtime.tick()
            species = self.runtime.species_today()
            n = len(species)
            trouble = self.runtime.status.startswith("audio error")
            self.title = "⚠️🐦" if trouble else "🐦"
            self.menu["Species today: …"].title = f"Species today: {n}"
        except Exception as exc:  # never let the UI thread die
            self.menu["Species today: …"].title = f"(error: {exc})"

    def _post_now(self, _):
        # Explicit user action → force a real (paid) image if a key is set.
        threading.Thread(target=lambda: self.runtime.post_now(force_paid=True),
                         daemon=True).start()
        rumps.notification("birdframe", "Painting the day's birds", "Posting to the frame…")

    def _toggle_pause(self, item):
        self._paused = not self._paused
        listener = getattr(self.runtime, "listener", None)
        if self._paused:
            if listener:
                listener.pause()
            item.title = "Resume listening"
        else:
            if listener:
                listener.resume()
            item.title = "Pause listening"

    def _open_dashboard(self, _):
        webbrowser.open(f"http://localhost:{self.dashboard_port}")
