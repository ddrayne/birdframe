"""Entry point: build everything from config + stored keys and run forever —
under the macOS menu bar, or headless on Linux (a Raspberry Pi)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from birdframe import host, secrets
from birdframe.artist import Artist
from birdframe.config import Config
from birdframe.publisher import Publisher
from birdframe.runtime import Runtime
from birdframe.store import Store
from birdframe.styles import load_styles
from birdframe.weather import describe_weather

DATA_DIR = Path.home() / ".local" / "share" / "birdframe"
LOG_PATH = host.LOG_PATH
# BirdNET's regional plausibility per species, saved at startup so the public
# site can judge reliability without loading the model (`birdframe publish`).
GEO_PATH = DATA_DIR / "geo.json"
# When and what the public site last uploaded, so restarts don't re-upload.
PUBLIC_STATE_PATH = DATA_DIR / "public-site.json"

log = logging.getLogger("birdframe")


def _setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH)]
    # Add a console handler only when attached to a terminal (a foreground run).
    # Under launchd or systemd, stdout+stderr are already redirected to this
    # same log file, so a StreamHandler would write every line to it twice.
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


def _make_image_client(config: Config):
    """The paid painter selected by config.image_provider, or None if that
    provider's key is missing (the day then gets the free fallback poster)."""
    if config.image_provider not in ("openai", "gemini"):
        log.warning("Unknown image_provider %r in config — pictures will use "
                    "the fallback poster. Use 'openai' or 'gemini'.",
                    config.image_provider)
        return None
    key = secrets.get_key(config.image_provider)
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
    try:
        GEO_PATH.write_text(json.dumps(getattr(detector, "geo_by_scientific", {})))
    except OSError as exc:
        log.warning("Could not save the plausibility map: %s", exc)

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
        place_name=config.place_name,
    )
    from birdframe.scheduler import parse_slots
    artist.scheduled_slot_count = len(parse_slots(config.post_times, config.post_time))
    publisher = Publisher(
        frame_url=config.frame_url, hold_minutes=config.frame_hold_minutes,
        saturation=config.frame_saturation,
    )
    _prune_archive(DATA_DIR / "images", config)
    return Runtime(config=config, store=store, detector=detector,
                   artist=artist, publisher=publisher,
                   clips_dir=DATA_DIR / "clips", backup_dir=backup_dir,
                   on_first_ever=_notify_first_ever,
                   notify=host.notify)


def _prune_archive(images_dir: Path, config) -> None:
    """Keep the image archive from growing without bound. 0 = keep everything."""
    keep = getattr(config, "archive_keep_days", 0) or 0
    if keep <= 0 or not Path(images_dir).exists():
        return
    import time
    cutoff = time.time() - keep * 86400
    # Cached thumbnails in derived/ are rebuilt on demand, so they age out too.
    for f in [*Path(images_dir).glob("*.png"), *Path(images_dir).glob("derived/*")]:
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _notify_first_ever(common_name: str) -> None:
    """A life-list first — celebrate it with a notification."""
    host.notify("New bird for your window! 🐦", f"First time hearing a {common_name}.")


def _first_notice_in(marker: Path, hours: float, now: float | None = None) -> bool:
    """True at most once per `hours`, remembered across restarts in a marker
    file's mtime — a crash loop must never become a notification storm."""
    import time
    now = time.time() if now is None else now
    try:
        if now - marker.stat().st_mtime < hours * 3600:
            return False
    except OSError:
        pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
        os.utime(marker, (now, now))
    except OSError:
        pass
    return True


def _start_listener(runtime: Runtime, config: Config) -> None:
    from birdframe.listener import AudioListener

    def on_status(s: str) -> None:
        was_ok = runtime.status == "listening"
        runtime.status = s
        log.info("listener: %s", s)
        trouble = s.startswith(("audio error", "recovering", "detector error"))
        if trouble and was_ok and _first_notice_in(DATA_DIR / ".notice-audio", hours=0.5):
            host.notify("Microphone recovery",
                        "birdframe found an unhealthy audio stream and is reconnecting it.")

    listener = AudioListener(
        sample_rate=runtime.detector.sample_rate,
        chunk_seconds=config.chunk_seconds,
        overlap_seconds=config.chunk_overlap_seconds,
        device=config.input_device or None,
        on_chunk=runtime.on_chunk,
        on_status=on_status,
        callback_timeout_seconds=config.audio_callback_timeout_seconds,
        detector_timeout_seconds=config.audio_detector_timeout_seconds,
        process_restart_failures=config.audio_process_restart_failures,
        flat_chunks=config.audio_flat_chunks,
        flat_dynamic_dbfs=config.audio_flat_dynamic_dbfs,
    )
    runtime.listener = listener  # so the menu bar can pause/resume it
    listener.start()


def _start_health_watchdog(runtime: Runtime) -> None:
    """Independently recycle the process if BirdNET stops making progress.

    Stream-level faults are repaired inside AudioListener. A detector call that
    never returns cannot be interrupted safely in Python, so this supervisor
    exits the process and the service manager (launchd's KeepAlive, systemd's
    Restart=always) starts a clean model session. Keeping this off the AppKit
    thread means UI trouble cannot disable recovery.
    """
    import time

    def supervise() -> None:
        while True:
            time.sleep(5)
            listener = getattr(runtime, "listener", None)
            if listener is None:
                continue
            health = listener.health_snapshot()
            if not health["restart_required"]:
                continue
            reason = health["restart_reason"] or "audio pipeline stalled"
            log.error("Watchdog is restarting birdframe: %s", reason)
            if _first_notice_in(DATA_DIR / ".notice-restart", hours=6):
                runtime.notify(
                    "Birdframe is restarting",
                    "The audio pipeline could not recover locally; it will be back in a moment.")
            os._exit(70)

    threading.Thread(target=supervise, name="birdframe-watchdog", daemon=True).start()


def _scheduler_step(runtime: Runtime, now: datetime, exit_process=os._exit) -> None:
    """One scheduler beat: the nightly freshness restart, then any due post."""
    if runtime.should_restart_for_freshness(now):
        # A clean daily restart re-resolves the frame's mDNS name and bounds
        # any slow resource creep. The service manager brings it right back.
        log.info("Nightly freshness restart")
        exit_process(0)
        return
    runtime.tick(now)


def _public_dir(config: Config) -> Path | None:
    """Where the public site is built: public_site_dir, or a folder of our
    own when it only goes to Cloudflare. None = no public site."""
    if config.public_site_dir:
        return Path(config.public_site_dir).expanduser()
    if config.cloudflare_project:
        return DATA_DIR / "public-site"
    return None


def _site_deploy(config: Config, out_dir: Path):
    """How a built site is published: your own command, Cloudflare Pages, or
    not at all (the folder is the site)."""
    if config.public_deploy_command:
        from birdframe.public_site import deploy
        command = config.public_deploy_command

        def run_command() -> None:
            deploy(out_dir, command)
        return run_command
    if config.cloudflare_project:
        from birdframe.cloudflare import CloudflarePages
        return CloudflarePages(config.cloudflare_project, config.cloudflare_account_id,
                               out_dir, workdir=DATA_DIR / "wrangler")
    return None


def _site_builder(store, styles, config: Config, out_dir: Path, deploy, geo: dict):
    def build() -> dict:
        from birdframe.public_site import build_site
        base_url = config.public_site_url
        if not base_url and hasattr(deploy, "site_url"):
            try:                        # link previews need an absolute address
                base_url = deploy.site_url()
            except Exception as exc:
                log.warning("Couldn't look up the public site's address: %s", exc)
        return build_site(store, styles, out_dir, place=config.place_name,
                          title=config.public_site_title, base_url=base_url, geo_lookup=geo)
    return build


def _make_site_publisher(runtime: Runtime, config: Config):
    """The public site's background publisher, or None when not configured."""
    out_dir = _public_dir(config)
    if out_dir is None:
        return None
    from birdframe.public_site import SitePublisher
    deploy = _site_deploy(config, out_dir)
    build = _site_builder(runtime.store, runtime.artist.styles, config, out_dir, deploy,
                          getattr(runtime.detector, "geo_by_scientific", {}))
    return SitePublisher(build, latest=runtime.store.latest_image_id, deploy=deploy,
                         state_path=PUBLIC_STATE_PATH)


def _start_scheduler(runtime: Runtime, site=None) -> None:
    """Posting gets its own thread. It used to run inside the menu bar's timer
    on the AppKit main thread, so a multi-minute paid render (plus frame
    retries) froze the menu, and the nightly restart check, while it ran.
    The public site, if any, is rebuilt on its own thread when it falls due."""
    import time

    def run() -> None:
        while True:
            try:
                _scheduler_step(runtime, datetime.now())
            except Exception:
                log.exception("Scheduler tick failed")
            if site is not None:
                site.maybe_publish()
            time.sleep(30)

    threading.Thread(target=run, name="birdframe-scheduler", daemon=True).start()


def _start_dashboard(runtime: Runtime, config: Config, site=None) -> None:
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
        # The schedule is the budget: each slot may spend one paid render.
        from birdframe.scheduler import parse_slots
        runtime.artist.scheduled_slot_count = len(
            parse_slots(config.post_times, config.post_time))
        runtime.artist.min_species_confidence = config.min_species_confidence
        runtime.artist.style_mode = config.style_mode
        runtime.artist.pinned_style = config.pinned_style
        runtime.artist.place_name = config.place_name
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
                     runtime=runtime, text_client=text_client, public_site=site)
    app = create_app(ctx)
    # Bind to all interfaces so other devices on the home network can reach it.
    server = uvicorn.Server(uvicorn.Config(
        app, host="0.0.0.0", port=config.dashboard_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    lan_ip = _lan_ip()
    log.info("Dashboard at http://localhost:%d", config.dashboard_port)
    if lan_ip:
        log.info("On your network at http://%s:%d", lan_ip, config.dashboard_port)


_KEY_LABELS = {"openai": "OpenAI API key", "gemini": "Gemini API key",
               "cloudflare": "Cloudflare API token"}


def _set_key_interactive(provider: str = "openai") -> int:
    """`birdframe set-key [openai|gemini|cloudflare]` — prompt for the key
    without echoing it or leaving it in shell history, then store it in the
    macOS Keychain (or, on Linux, the private secrets file)."""
    import getpass

    if provider not in _KEY_LABELS:
        print(f"Unknown provider {provider!r} — use 'openai', 'gemini' or 'cloudflare'.")
        return 1
    key = getpass.getpass(f"{_KEY_LABELS[provider]} (input hidden): ").strip()
    if not key:
        print("No key entered — nothing changed.")
        return 1
    try:
        secrets.set_key(provider, key)
    except ValueError as exc:
        print(f"Not saved: {exc}.")
        return 1
    print(f"Saved to {secrets.storage_name()}. birdframe will use it on next run.")
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
    if not secrets.file_is_private():
        print(f"  {warn} secrets file   {secrets.SECRETS_FILE} is readable by other users — "
              f"run: chmod 600 {secrets.SECRETS_FILE}")
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
        hint = ("  (sudo apt install libportaudio2)"
                if "PortAudio" in str(exc) and not host.IS_MAC else "")
        print(f"  {warn} microphone     could not query input devices: {exc}{hint}")
    import httpx
    frame = config.frame_url.rstrip("/")
    if not frame:
        print("    inky frame     not configured (paintings are archived, not posted)")
    else:
        try:
            r = httpx.get(f"{frame}/status", timeout=5)
            print(f"  {ok if r.status_code == 200 else warn} inky frame     {frame} — HTTP {r.status_code}")
        except Exception:
            print(f"  {warn} inky frame     {frame} — unreachable (birdframe still runs; images are archived)")
    out_dir = _public_dir(config)
    if out_dir is None:
        print("    public site    off (set public_site_dir or cloudflare_project in config.toml)")
    else:
        print(f"  {ok} public site    builds into {out_dir}")
        deploy = _site_deploy(config, out_dir)
        if config.public_deploy_command:
            print(f"  {ok} publishing     with your public_deploy_command")
        elif hasattr(deploy, "problems"):
            problems = deploy.problems()
            for problem in problems:
                print(f"  {warn} cloudflare     {problem}")
            if not problems:
                print(f"  {ok} cloudflare     Pages project '{config.cloudflare_project}' — ready")
    from birdframe.compose import FONT_PATHS
    font = next((Path(f).stem for f in FONT_PATHS if Path(f).exists()), None)
    print(f"  {ok} caption font   {font}" if font else
          f"  {warn} caption font   none found; captions use Pillow's plain face "
          "(sudo apt install fonts-dejavu-core)")
    from birdframe.detector import model_options
    runtime_name = "LiteRT" if model_options() else "TensorFlow"
    print(f"    birdnet        runs its models on {runtime_name}")
    print(f"\n  dashboard will be at http://localhost:{config.dashboard_port}")
    if not host.IS_MAC:
        import socket
        print(f"  and on your network at http://{socket.gethostname()}.local:{config.dashboard_port}")
    return 0


def _publish_site(argv: list[str]) -> int:
    """`birdframe publish [folder]` — build the public, read-only site now,
    and publish it where config.toml says (a named folder is only built)."""
    from birdframe.public_site import SitePublisher
    config = Config.load()
    out_dir = Path(argv[1]).expanduser() if len(argv) > 1 else _public_dir(config)
    if out_dir is None:
        print("Name a folder to build into, e.g.  birdframe publish ~/Sites/birdframe\n"
              "or set public_site_dir (or cloudflare_project) in ~/.config/birdframe/config.toml.")
        return 1
    store = Store(DATA_DIR / "birdframe.sqlite")
    geo = json.loads(GEO_PATH.read_text()) if GEO_PATH.exists() else {}
    if not geo:
        print("Note: no plausibility map yet (run birdframe once); reliability "
              "is judged on confidence alone.")
    deploy = _site_deploy(config, out_dir) if len(argv) <= 1 else None
    publisher = SitePublisher(
        _site_builder(store, load_styles(), config, out_dir, deploy, geo),
        latest=store.latest_image_id, deploy=deploy,
        state_path=PUBLIC_STATE_PATH if deploy else None)
    summary = publisher.run_once(force_deploy=True)
    if publisher.status["error"]:
        print(f"Publishing failed: {publisher.status['error']}")
        return 1
    paintings, birds = summary["paintings"], summary["species"]
    print(f"Built {paintings} painting{'' if paintings == 1 else 's'} and "
          f"{birds} bird{'' if birds == 1 else 's'} into {out_dir}")
    if deploy is None:
        print(f"Preview it:  python3 -m http.server --directory {out_dir} 8356")
    else:
        print(f"Published{': ' + publisher.status['url'] if publisher.status.get('url') else '.'}")
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
        subprocess.run(["tail", "-n", "50", "-f", str(service.LOG_PATH)], check=False)
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
    if argv and argv[0] == "publish":
        raise SystemExit(_publish_site(argv))
    if argv and argv[0] in _SERVICE_CMDS:
        raise SystemExit(_run_service(argv[0]))
    if argv and argv[0] in ("-h", "--help"):
        where = "the macOS Keychain" if host.IS_MAC else "~/.config/birdframe/secrets.env"
        manager = "LaunchAgent" if host.IS_MAC else "systemd user service"
        print("Usage: birdframe [command]\n\n"
              "  (no args)  run the listener and dashboard in the foreground"
              + (" (with the menu bar)" if host.IS_MAC else "") + "\n"
              f"  set-key [openai|gemini|cloudflare]  store a key in {where} (default: openai)\n"
              "  doctor     check location, keys, microphone, frame and public site\n"
              "  backup     create a restore-ready database snapshot now\n"
              "  publish [folder]  build the public, read-only site (and deploy it if configured)\n\n"
              "Run it forever (background service):\n"
              f"  install    start at {'login' if host.IS_MAC else 'boot'} and keep running ({manager})\n"
              "  uninstall  remove the background service\n"
              "  start / stop / restart / status\n"
              "  logs       follow the log"
              + ("\n  make-app   create a double-clickable Birdframe.app in ~/Applications"
                 if host.IS_MAC else ""))
        raise SystemExit(0)

    _setup_logging()
    host.keep_awake()
    config = Config.load()
    runtime = build_runtime(config)
    _start_listener(runtime, config)
    _start_health_watchdog(runtime)
    site = _make_site_publisher(runtime, config)
    _start_dashboard(runtime, config, site)
    _start_scheduler(runtime, site)

    log.info("birdframe is listening. Mode: %s", config.post_mode)
    if host.IS_MAC:
        from birdframe.menubar import BirdframeMenuBar
        BirdframeMenuBar(runtime, config.dashboard_port).run()
    else:
        _serve_headless(runtime)
        # Exit without interpreter teardown: the audio and model threads live
        # in native code, and tearing Python down under them can abort.
        logging.shutdown()
        os._exit(0)


def _serve_headless(runtime: Runtime, stop: threading.Event | None = None) -> None:
    """No menu bar off macOS: the main thread waits for systemd's SIGTERM (or
    Ctrl-C), then lets go of the microphone. The workers are daemon threads,
    and every store write is already committed, so nothing else needs saving."""
    import signal

    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: stop.set())
    while not stop.wait(60):
        pass
    log.info("Stopping: releasing the microphone")
    listener = getattr(runtime, "listener", None)
    if listener is not None:
        listener.stop()
        listener.join(timeout=3)


if __name__ == "__main__":
    main()
