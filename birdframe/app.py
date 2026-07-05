"""Entry point: build everything from config + Keychain and run forever."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from birdframe import secrets
from birdframe.artist import Artist
from birdframe.config import Config
from birdframe.publisher import Publisher
from birdframe.runtime import Runtime
from birdframe.store import Store
from birdframe.styles import load_styles
from birdframe.weather import describe_weather

DATA_DIR = Path.home() / ".local" / "share" / "birdframe"
LOG_PATH = Path.home() / "Library" / "Logs" / "birdframe.log"

log = logging.getLogger("birdframe")


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH)]
    # Add a console handler only when attached to a terminal (a foreground run).
    # Under launchd, stdout+stderr are already redirected to this same log file,
    # so a StreamHandler would write every line to it a second time.
    if sys.stderr is not None and sys.stderr.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,  # own the root config even if an imported lib pre-configured it
    )


def _lan_ip() -> str | None:
    """Best-effort local network IP for sharing the dashboard on the LAN."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # no packets sent; just picks the route
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        return None


def _start_caffeinate() -> None:
    """Keep the Mac awake (idle) while birdframe runs, so it hears the dawn chorus."""
    try:
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    except Exception as exc:  # non-fatal
        log.warning("caffeinate unavailable: %s", exc)


def build_runtime(config: Config) -> Runtime:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DATA_DIR / "birdframe.sqlite")

    from birdframe.detector import Detector
    log.info("Loading BirdNET models and building Edinburgh whitelist…")
    detector = Detector(
        latitude=config.latitude, longitude=config.longitude,
        threshold=config.confidence_threshold, geo_floor=config.geo_floor,
        when=datetime.now(), blocklist=config.blocked_species,
    )
    log.info("Whitelist: %d plausible local species", len(detector.whitelist))

    api_key = secrets.get_openai_key()
    image_client = None
    if api_key:
        from birdframe.image_client import OpenAIImageClient
        image_client = OpenAIImageClient(api_key=api_key, model=config.openai_model,
                                         quality=config.image_quality)
    else:
        log.warning("No OpenAI key set — pictures will use the fallback poster. "
                    "Set one with: birdframe set-key")

    artist = Artist(
        store=store, styles=load_styles(), image_client=image_client,
        archive_dir=DATA_DIR / "images", weather_fn=describe_weather,
        latitude=config.latitude, longitude=config.longitude,
        style_mode=config.style_mode, pinned_style=config.pinned_style,
        min_species_for_image=config.min_species_for_image,
        max_paid_images_per_day=config.max_paid_images_per_day,
        min_species_confidence=config.min_species_confidence,
        geo_lookup=getattr(detector, "geo_by_scientific", {}),
    )
    publisher = Publisher(
        frame_url=config.frame_url, hold_minutes=config.frame_hold_minutes,
        saturation=config.frame_saturation,
    )
    _prune_archive(DATA_DIR / "images", config)
    return Runtime(config=config, store=store, detector=detector,
                   artist=artist, publisher=publisher,
                   clips_dir=DATA_DIR / "clips", on_first_ever=_notify_first_ever,
                   notify=_notify)


def _prune_archive(images_dir: Path, config) -> None:
    """Keep the image archive from growing without bound. 0 = keep everything."""
    keep = getattr(config, "archive_keep_days", 0) or 0
    if keep <= 0 or not Path(images_dir).exists():
        return
    import time
    cutoff = time.time() - keep * 86400
    for f in Path(images_dir).glob("*.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _notify_first_ever(common_name: str) -> None:
    """A life-list first — celebrate it with a macOS notification."""
    _notify("New bird for your window! 🐦", f"First time hearing a {common_name}.")


def _notify(title: str, message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {message!r} with title {title!r} sound name "Glass"'],
            check=False, timeout=5)
    except Exception as exc:  # notifications are best-effort
        log.debug("notification failed: %s", exc)


def _start_listener(runtime: Runtime, config: Config) -> None:
    from birdframe.listener import AudioListener

    def on_status(s: str) -> None:
        was_ok = runtime.status == "listening"
        runtime.status = s
        log.info("listener: %s", s)
        if s.startswith("audio error") and was_ok:
            _notify("Microphone problem", "birdframe lost the audio input and is retrying.")

    listener = AudioListener(
        sample_rate=runtime.detector.sample_rate,
        chunk_seconds=config.chunk_seconds,
        overlap_seconds=config.chunk_overlap_seconds,
        device=config.input_device or None,
        on_chunk=runtime.on_chunk,
        on_status=on_status,
    )
    runtime.listener = listener  # so the menu bar can pause/resume it
    listener.start()


def _start_dashboard(runtime: Runtime, config: Config) -> None:
    import uvicorn

    from birdframe.web.app import AppContext, create_app

    def apply_settings() -> None:
        """Push live-applicable config changes onto the running objects. The
        scheduler reads runtime.config each tick, so mode/time/live-window apply
        automatically; the artist and publisher hold their own copies."""
        runtime.config = config
        runtime.detector.blocklist = set(config.blocked_species or ())
        runtime.artist.min_species_for_image = config.min_species_for_image
        runtime.artist.max_paid_images_per_day = config.max_paid_images_per_day
        runtime.artist.min_species_confidence = config.min_species_confidence
        runtime.artist.style_mode = config.style_mode
        runtime.artist.pinned_style = config.pinned_style
        runtime.publisher.frame_url = config.frame_url.rstrip("/")
        runtime.publisher.hold_minutes = config.frame_hold_minutes
        runtime.publisher.saturation = config.frame_saturation

    from birdframe.styles import DEFAULT_STYLES_DIR

    text_client = None
    key = secrets.get_openai_key()
    if key:
        try:
            from openai import OpenAI
            text_client = OpenAI(api_key=key, timeout=30)
        except Exception:
            text_client = None

    ctx = AppContext(store=runtime.store, artist=runtime.artist,
                     publisher=runtime.publisher, config=config,
                     apply_settings=apply_settings,
                     styles_dir=DEFAULT_STYLES_DIR,
                     preview_dir=DATA_DIR / "style_previews",
                     geo_lookup=getattr(runtime.detector, "geo_by_scientific", {}),
                     runtime=runtime, text_client=text_client)
    app = create_app(ctx)
    # Bind to all interfaces so other devices on the home network can reach it.
    server = uvicorn.Server(uvicorn.Config(
        app, host="0.0.0.0", port=config.dashboard_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    lan_ip = _lan_ip()
    log.info("Dashboard at http://localhost:%d", config.dashboard_port)
    if lan_ip:
        log.info("On your network at http://%s:%d", lan_ip, config.dashboard_port)


def _set_key_interactive() -> int:
    """`birdframe set-key` — prompt for the OpenAI key without echoing it or
    leaving it in shell history, then store it in the macOS Keychain."""
    import getpass

    key = getpass.getpass("OpenAI API key (input hidden): ").strip()
    if not key:
        print("No key entered — nothing changed.")
        return 1
    secrets.set_openai_key(key)
    print("Saved to the macOS Keychain. birdframe will use it on next run.")
    return 0


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "set-key":
        raise SystemExit(_set_key_interactive())
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: birdframe [set-key]\n"
              "  (no args)  run the listener, menu bar, and dashboard\n"
              "  set-key    store your OpenAI API key in the macOS Keychain")
        raise SystemExit(0)

    _setup_logging()
    _start_caffeinate()
    config = Config.load()
    runtime = build_runtime(config)
    _start_listener(runtime, config)
    _start_dashboard(runtime, config)

    from birdframe.menubar import BirdframeMenuBar
    log.info("birdframe is listening. Mode: %s", config.post_mode)
    BirdframeMenuBar(runtime, config.dashboard_port).run()


if __name__ == "__main__":
    main()
