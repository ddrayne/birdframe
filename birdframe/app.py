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


def _make_image_client(config: Config):
    """The paid painter selected by config.image_provider, or None if that
    provider's key is missing (the day then gets the free fallback poster)."""
    try:
        key = secrets.get_key(config.image_provider)
    except ValueError:
        log.warning("Unknown image_provider %r in config — pictures will use "
                    "the fallback poster. Use 'openai' or 'gemini'.",
                    config.image_provider)
        return None
    if not key:
        log.warning(
            "No %s key set — pictures will use the fallback poster. "
            "Set one with: birdframe set-key %s",
            config.image_provider, config.image_provider)
        return None
    if config.image_provider == "gemini":
        from birdframe.image_client import GeminiImageClient
        return GeminiImageClient(api_key=key, model=config.gemini_model,
                                 quality=config.image_quality)
    from birdframe.image_client import OpenAIImageClient
    return OpenAIImageClient(api_key=key, model=config.openai_model,
                             quality=config.image_quality)


def build_runtime(config: Config) -> Runtime:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DATA_DIR / "birdframe.sqlite")
    backup_dir = DATA_DIR / "backups"
    from birdframe.backups import create_daily_backup
    try:
        path, created = create_daily_backup(
            store, backup_dir, datetime.now(), config.backup_keep_days)
        if created:
            log.info("Database backup created: %s", path)
    except Exception as exc:
        # A backup problem must be visible, but must never stop listening.
        log.warning("Database backup failed: %s", exc)

    from birdframe.detector import Detector
    log.info("Loading BirdNET models and building Edinburgh whitelist…")
    detector = Detector(
        latitude=config.latitude, longitude=config.longitude,
        threshold=config.confidence_threshold, geo_floor=config.geo_floor,
        when=datetime.now(), blocklist=config.blocked_species,
    )
    log.info("Whitelist: %d plausible local species", len(detector.whitelist))

    image_client = _make_image_client(config)

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
                   clips_dir=DATA_DIR / "clips", backup_dir=backup_dir,
                   on_first_ever=_notify_first_ever,
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


def _osa_quote(s: str) -> str:
    """A safe AppleScript string literal (double-quoted, escaped)."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _notify(title: str, message: str) -> None:
    try:
        script = (f"display notification {_osa_quote(message)} "
                  f"with title {_osa_quote(title)} sound name \"Glass\"")
        subprocess.run(["osascript", "-e", script], check=False, timeout=5,
                       capture_output=True)  # don't spam osascript errors into the log
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
        # Rebuild the paid painter so provider/model/quality switches apply
        # without a restart (cheap: clients are lazy, no network on construct).
        runtime.artist.image_client = _make_image_client(config)
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
                     backup_dir=DATA_DIR / "backups",
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


def _set_key_interactive(provider: str = "openai") -> int:
    """`birdframe set-key [openai|gemini]` — prompt for the key without echoing
    it or leaving it in shell history, then store it in the macOS Keychain."""
    import getpass

    if provider not in ("openai", "gemini"):
        print(f"Unknown provider {provider!r} — use 'openai' or 'gemini'.")
        return 1
    label = {"openai": "OpenAI", "gemini": "Gemini"}[provider]
    key = getpass.getpass(f"{label} API key (input hidden): ").strip()
    if not key:
        print("No key entered — nothing changed.")
        return 1
    secrets.set_key(provider, key)
    print("Saved to the macOS Keychain. birdframe will use it on next run.")
    return 0


def _doctor() -> int:
    """`birdframe doctor` — check the setup and print what's ready or missing."""
    ok = "✓"
    warn = "⚠"
    config = Config.load()
    print("birdframe setup check\n")
    print(f"  location        {config.latitude}, {config.longitude}")
    if config.image_provider not in ("openai", "gemini"):
        print(f"  {warn} image provider  '{config.image_provider}' is not a valid image_provider — "
              "use 'openai' or 'gemini' (art uses a text poster until fixed)")
    for provider, label in (("openai", "OpenAI key"), ("gemini", "Gemini key")):
        key = secrets.get_key(provider)
        active = provider == config.image_provider
        if key:
            print(f"  {ok} {label:<14} set" + ("  (selected painter)" if active else ""))
        elif active:
            print(f"  {warn} {label:<14} missing — run 'birdframe set-key {provider}' "
                  "(art uses a text poster without it)")
        else:
            print(f"    {label:<14} not set (not selected)")
    try:
        import sounddevice as sd
        default_in = sd.query_devices(kind="input")["name"]
        print(f"  {ok} microphone     default input: {default_in}")
    except Exception as exc:
        print(f"  {warn} microphone     could not query input devices: {exc}")
    import httpx
    frame = config.frame_url.rstrip("/")
    try:
        r = httpx.get(f"{frame}/status", timeout=5)
        print(f"  {ok if r.status_code == 200 else warn} inky frame     {frame} — HTTP {r.status_code}")
    except Exception:
        print(f"  {warn} inky frame     {frame} — unreachable (birdframe still runs; images are archived)")
    print(f"\n  dashboard will be at http://localhost:{config.dashboard_port}")
    return 0


def _backup_now() -> int:
    """Create a manual restore point without loading BirdNET or the microphone."""
    from birdframe.backups import create_manual_backup
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    store = Store(DATA_DIR / "birdframe.sqlite")
    path = create_manual_backup(store, DATA_DIR / "backups", datetime.now())
    print(f"Database backup created: {path}")
    return 0


_SERVICE_CMDS = {"install", "uninstall", "start", "stop", "restart", "status", "make-app", "logs"}


def _run_service(cmd: str) -> int:
    from birdframe import service
    if cmd == "logs":
        subprocess.run(["tail", "-f", str(service.LOG_PATH)], check=False)
        return 0
    fn = {"install": service.install, "uninstall": service.uninstall,
          "start": service.start, "stop": service.stop, "restart": service.restart,
          "status": service.status, "make-app": service.make_app}[cmd]
    print(fn())
    return 0


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "set-key":
        raise SystemExit(_set_key_interactive(argv[1] if len(argv) > 1 else "openai"))
    if argv and argv[0] == "doctor":
        raise SystemExit(_doctor())
    if argv and argv[0] == "backup":
        raise SystemExit(_backup_now())
    if argv and argv[0] in _SERVICE_CMDS:
        raise SystemExit(_run_service(argv[0]))
    if argv and argv[0] in ("-h", "--help"):
        print("Usage: birdframe [command]\n\n"
              "  (no args)  run the listener, menu bar, and dashboard in the foreground\n"
              "  set-key [openai|gemini]  store an API key in the macOS Keychain (default: openai)\n"
              "  doctor     check location, keys, microphone and frame\n"
              "  backup     create a restore-ready database snapshot now\n\n"
              "Run it forever (background service):\n"
              "  install    start at login and keep running (LaunchAgent)\n"
              "  uninstall  remove the background service\n"
              "  start / stop / restart / status\n"
              "  logs       follow the log\n"
              "  make-app   create a double-clickable Birdframe.app in ~/Applications")
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
