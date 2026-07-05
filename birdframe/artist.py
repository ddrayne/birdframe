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
                 style_mode: str = "rotate", pinned_style: str = "",
                 min_species_for_image: int = 1, max_paid_images_per_day: int = 1,
                 min_species_confidence: float = 0.0):
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
        self.min_species_for_image = min_species_for_image
        self.max_paid_images_per_day = max_paid_images_per_day
        self.min_species_confidence = min_species_confidence

    def _may_spend(self, species_count: int, when: datetime, force_paid: bool) -> bool:
        """Whether a paid gpt-image-1 call is allowed right now.

        A real render costs money, so an *automatic* post only spends when there
        is an image client, the day cleared the species threshold, and we are
        still under the daily paid-image cap. An explicit user action
        (force_paid, e.g. clicking Post Now) bypasses the threshold and cap.
        """
        if self.image_client is None:
            return False
        if force_paid:
            return True
        if species_count < self.min_species_for_image:
            return False
        return self.store.count_paid_images_for_day(when) < self.max_paid_images_per_day

    def generate(self, when: datetime, force_paid: bool = False,
                 species_days=None) -> ImageRecord | None:
        """Paint a picture of the given birds. Returns None (no image made, none
        posted) when there are no birds to show, or when nothing has changed
        since the last picture today — so empty or duplicate frames never enter
        the gallery."""
        if species_days is None:
            species_days = self.store.species_for_day(
                when, min_confidence=self.min_species_confidence)
        species_names = [s.common_name for s in species_days]
        if not species_names:
            return None                       # nothing heard — never make an empty picture
        for prev in self.store.recent_images(limit=8):
            if prev.generated_at.date() == when.date() and prev.species == species_names:
                # Same birds as an existing picture today — reuse it (so callers
                # can still post/override the frame) without adding a gallery dupe.
                return prev
        first_ever = self.store.first_ever_on_day(when)
        weather = self.weather_fn(self.latitude, self.longitude, when)
        scene = build_scene(species_days, first_ever, weather, when)
        day_index = when.toordinal()
        style = choose_style(self.styles, self.style_mode, day_index, self.pinned_style)
        prompt = build_prompt(style, scene)

        style_label = style.name
        final = None
        if self._may_spend(len(species_days), when, force_paid):
            try:
                art_bytes = self.image_client.generate(prompt)
                final = compose_final(art_bytes, when, species_names)
            except Exception:
                final = None  # fall through to the free poster
        if final is None:
            final = fallback_poster(when, species_names)
            style_label = f"{style.name} (fallback)"

        filename = when.strftime("%Y-%m-%d-%H%M%S") + ".png"
        path = self.archive_dir / filename
        path.write_bytes(final)
        image_id = self.store.add_image(when, str(path), style_label, prompt, species_names)
        return self.store.get_image(image_id)
