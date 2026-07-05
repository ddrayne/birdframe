"""Compose a day's picture: rollup -> prompt -> image gen -> caption -> archive."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("birdframe")

from birdframe.compose import compose_final, fallback_poster  # noqa: E402
from birdframe.reliability import GEO_DEFAULT, assess, for_artwork  # noqa: E402
from birdframe.rollup import build_prompt, build_scene  # noqa: E402
from birdframe.store import ImageRecord, Store  # noqa: E402
from birdframe.styles import Style, choose_style  # noqa: E402


class Artist:
    def __init__(self, store: Store, styles: list[Style], image_client,
                 archive_dir: Path, weather_fn, latitude: float, longitude: float,
                 style_mode: str = "rotate", pinned_style: str = "",
                 min_species_for_image: int = 1, max_paid_images_per_day: int = 1,
                 min_species_confidence: float = 0.0, geo_lookup=None):
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
        self.geo_lookup = geo_lookup or {}

    def _reliable(self, species_days):
        """Keep only birds trustworthy AND plausible enough for the picture —
        tentative detections and confident-but-implausible ones (e.g. a cluster
        of hallucinated water birds) don't belong in the day's artwork."""
        out = []
        for s in species_days:
            geo = self.geo_lookup.get(s.scientific_name, GEO_DEFAULT)
            if for_artwork(assess(s.best_confidence, geo, s.count), geo):
                out.append(s)
        return out

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
        # The artwork celebrates only trustworthy birds; tentative ones are shown
        # on the dashboard but kept out of the picture.
        species_days = self._reliable(species_days)
        species_names = [s.common_name for s in species_days]
        if not species_names:
            return None                       # nothing reliable to picture
        todays = [im for im in self.store.recent_images(limit=12)
                  if im.generated_at.date() == when.date() and im.species == species_names]
        # Reuse an existing *real* picture of the same birds (no dupe, no respend).
        # Never lock onto a fallback poster — those should keep retrying a real render.
        real = next((im for im in todays if "(fallback)" not in im.style), None)
        if real is not None:
            return real
        first_ever = self.store.first_ever_on_day(when)
        weather = self.weather_fn(self.latitude, self.longitude, when)
        scene = build_scene(species_days, first_ever, weather, when)
        day_index = when.toordinal()
        style = choose_style(self.styles, self.style_mode, day_index, self.pinned_style)
        prompt = build_prompt(style, scene)

        style_label = style.name
        final = None
        spend = self._may_spend(len(species_days), when, force_paid)
        log.info("Artist: %d species, force=%s, image_client=%s, spending=%s",
                 len(species_names), force_paid, self.image_client is not None, spend)
        if spend:
            try:
                art_bytes = self.image_client.generate(prompt)
                final = compose_final(art_bytes, when, species_names)
            except Exception as exc:
                log.warning("Image generation failed (%s: %s) — using fallback poster",
                            type(exc).__name__, exc)
                final = None  # fall through to the free poster
        if final is None:
            final = fallback_poster(when, species_names)
            style_label = f"{style.name} (fallback)"
            # Don't pile up identical fallback posters; reuse an existing one.
            if todays:
                return todays[0]

        filename = when.strftime("%Y-%m-%d-%H%M%S") + ".png"
        path = self.archive_dir / filename
        path.write_bytes(final)
        image_id = self.store.add_image(when, str(path), style_label, prompt, species_names)
        return self.store.get_image(image_id)
