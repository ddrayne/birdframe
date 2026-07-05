"""Entry point: build everything from config + Keychain and run forever."""
from __future__ import annotations

import logging
import os
import subprocess
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()],
    )


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
        when=datetime.now(),
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
                    "Set one with birdframe.secrets.set_openai_key(...).")

    artist = Artist(
        store=store, styles=load_styles(), image_client=image_client,
        archive_dir=DATA_DIR / "images", weather_fn=describe_weather,
        latitude=config.latitude, longitude=config.longitude,
        style_mode=config.style_mode, pinned_style=config.pinned_style,
    )
    publisher = Publisher(
        frame_url=config.frame_url, hold_minutes=config.frame_hold_minutes,
        saturation=config.frame_saturation,
    )
    return Runtime(config=config, store=store, detector=detector,
                   artist=artist, publisher=publisher)


def _start_listener(runtime: Runtime, config: Config) -> None:
    from birdframe.listener import AudioListener

    def on_status(s: str) -> None:
        runtime.status = s
        log.info("listener: %s", s)

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

    ctx = AppContext(store=runtime.store, artist=runtime.artist,
                     publisher=runtime.publisher)
    app = create_app(ctx)
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=config.dashboard_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    log.info("Dashboard at http://localhost:%d", config.dashboard_port)


def main() -> None:
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
