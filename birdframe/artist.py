"""Compose a day's picture: rollup -> prompt -> image gen -> caption -> archive."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from birdframe.compose import compose_final, fallback_poster
from birdframe.rollup import build_prompt, build_scene
from birdframe.store import ImageRecord, Store
from birdframe.styles import Style, choose_style


class Artist:
    def __init__(self, store: Store, styles: list[Style], image_client,
                 archive_dir: Path, weather_fn, latitude: float, longitude: float,
                 style_mode: str = "rotate", pinned_style: str = ""):
        self.store = store
        self.styles = styles
        self.image_client = image_client
        self.archive_dir = Path(archive_dir)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.weather_fn = weather_fn
        self.latitude = latitude
        self.longitude = longitude
        self.style_mode = style_mode
        self.pinned_style = pinned_style

    def generate(self, when: datetime) -> ImageRecord:
        species_days = self.store.species_for_day(when)
        species_names = [s.common_name for s in species_days]
        first_ever = self.store.first_ever_on_day(when)
        weather = self.weather_fn(self.latitude, self.longitude, when)
        scene = build_scene(species_days, first_ever, weather, when)
        day_index = when.toordinal()
        style = choose_style(self.styles, self.style_mode, day_index, self.pinned_style)
        prompt = build_prompt(style, scene)

        style_label = style.name
        try:
            if self.image_client is None:
                raise RuntimeError("no image client configured")
            art_bytes = self.image_client.generate(prompt)
            final = compose_final(art_bytes, when, species_names)
        except Exception:
            final = fallback_poster(when, species_names)
            style_label = f"{style.name} (fallback)"

        filename = when.strftime("%Y-%m-%d-%H%M%S") + ".png"
        path = self.archive_dir / filename
        path.write_bytes(final)
        image_id = self.store.add_image(when, str(path), style_label, prompt, species_names)
        return self.store.get_image(image_id)
