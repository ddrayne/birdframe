"""A public, read-only edition of the journal: a static site anyone can visit.

`build_site` renders the local archive into a folder of HTML, CSS, JS, JSON
and WebP images that any static host can serve (GitHub Pages, Cloudflare
Pages, Netlify, a Raspberry Pi). Nothing on it can write back to birdframe,
and it leaves out what shouldn't leave the house: coordinates, audio, raw
detections, the frame's address, and doubtful identifications (only
confirmed and probable species appear).
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import logging
import re
import shlex
import subprocess
import threading
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from PIL import Image, features

from birdframe.reliability import GEO_DEFAULT, assess, is_reliable, rarity_label
from birdframe.rollup import CHARACTER_PHRASES
from birdframe.styles import slugify

log = logging.getLogger("birdframe")

TEMPLATE_DIR = Path(__file__).resolve().parent / "public_template"
IMAGE_WIDTHS = (480, 960, 1200)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_bytes(data)
    partial.replace(path)


def _edition_id(image_path: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", Path(image_path).stem)


def _title_case(style: str) -> str:
    return re.sub(r"\b\w", lambda m: m.group(0).upper(), style.replace("-", " "))


def _encode_widths(src: Path, images_dir: Path, edition_id: str) -> dict[str, str]:
    """Each painting at a few widths, encoded once and reused on later builds."""
    webp = features.check("webp")
    ext, fmt = ("webp", "WEBP") if webp else ("jpg", "JPEG")
    urls: dict[str, str] = {}
    art = None
    for width in IMAGE_WIDTHS:
        name = f"{edition_id}-{width}.{ext}"
        target = images_dir / name
        if not target.exists() or target.stat().st_mtime < src.stat().st_mtime:
            if art is None:
                with Image.open(src) as opened:
                    art = opened.convert("RGB")
            copy = art.copy()
            copy.thumbnail((width, width * 2), Image.LANCZOS)
            out = io.BytesIO()
            copy.save(out, format=fmt, quality=76)
            _write_atomic(target, out.getvalue())
        urls[str(width)] = f"images/{name}"
    return urls


# Reasons the art director records for the owner, reworded for strangers.
_OWNER_REASONS = {
    "Chosen by you for this edition.": "Chosen by hand for this painting.",
    "Pinned as your house style.": "Painted in the house style.",
}


def _character(profile: dict | None) -> str:
    """The day's character in words, e.g. "A dawn chorus: many voices in balance"."""
    if not profile or not profile.get("archetype"):
        return ""
    notes = [CHARACTER_PHRASES[tag] for tag in profile.get("tags", ()) if tag in CHARACTER_PHRASES]
    line = profile["archetype"]
    return f"{line}: {', '.join(notes[:2])}" if notes else line


def _presence(days_heard: list[str], start: date, span: int) -> str:
    """A '0'/'1' string, one character per calendar day from `start`."""
    marks = ["0"] * span
    for day in days_heard:
        offset = (date.fromisoformat(day) - start).days
        if 0 <= offset < span:
            marks[offset] = "1"
    return "".join(marks)


def _on(day: str) -> str:
    when = date.fromisoformat(day)
    return f"{when.day} {when:%B}"


def _highlights(species: list[dict], paintings: list[dict], days: list[dict],
                openers: dict[str, int], have_geo: bool) -> list[dict]:
    """A few true things about the season, each about a different bird."""
    if not species:
        return []
    by_name = {s["name"]: s for s in species}
    featured: set[str] = set()
    found = []

    def note(label: str, bird: dict | None, text: str) -> None:
        if bird:
            featured.add(bird["name"])
            found.append({"label": label, "bird": bird["slug"], "text": text})

    def best(score: Callable[[dict], tuple]) -> dict | None:
        return max((s for s in species if s["name"] not in featured), key=score, default=None)

    companion = best(lambda s: (s["days"], s["name"]))
    note("The constant companion", companion, f"Heard on {companion['days']} of {len(days)} days")
    opener = best(lambda s: (openers.get(s["name"], 0), s["name"]))
    if opener and openers.get(opener["name"]):
        note("Opens the dawn chorus", opener,
             f"First to sing on {openers[opener['name']]} mornings")
    painted = Counter(name for p in paintings for name in p["birds"] if name in by_name)
    muse = best(lambda s: (painted.get(s["name"], 0), s["name"]))
    if muse and painted.get(muse["name"]):
        count = painted[muse["name"]]
        note("Often painted", muse, "In every painting so far" if count == len(paintings)
             else f"In {count} of {len(paintings)} paintings")
    newest = best(lambda s: (s["first"], s["name"]))
    note("Newest arrival", newest, f"First heard on {_on(newest['first'])}" if newest else "")
    if have_geo:
        rarest = best(lambda s: (-s["geo"], s["name"]))
        if rarest and rarest["geo"] < 0.30:
            note("Least expected here", rarest,
                 f"{rarest['rarity'].capitalize()}, yet heard on {rarest['days']} days")
    if days:
        richest = max(days, key=lambda d: (d["species"], d["day"]))
        found.append({"label": "The richest day", "day": richest["day"],
                      "text": f"{richest['species']} species on {_on(richest['day'])}"})
    return found


def build_site(store, styles, out_dir: Path, *, place: str = "Edinburgh",
               title: str = "", base_url: str = "", geo_lookup: dict | None = None,
               now: datetime | None = None) -> dict:
    """Write (or refresh) the public site in `out_dir` and return a summary.

    Incremental: paintings already encoded are reused, and files for
    paintings no longer in the archive are removed.
    """
    now = now or datetime.now()
    out_dir = Path(out_dir).expanduser()
    geo_lookup = geo_lookup or {}
    title = title or f"The {place} Window"
    style_by_name = {s.name: s for s in styles}

    # Birds: only the well-supported ones leave the house.
    hours = {row["common_name"]: row["hours"] for row in store.pattern_summary()["by_species"]}
    heard = store.species_days_heard()
    species = []
    for row in store.life_list():
        geo = geo_lookup.get(row["scientific_name"], GEO_DEFAULT)
        if not is_reliable(assess(row["best"], geo, row["total"])):
            continue
        rhythm = hours.get(row["common_name"]) or [0] * 24
        top = max(rhythm) or 1
        species.append({
            "slug": slugify(row["common_name"]), "name": row["common_name"],
            "scientific": row["scientific_name"], "first": row["first_day"],
            "last": row["last_day"], "days": row["days"], "peak": row["peak_hour"],
            "rhythm": [round(value / top, 3) for value in rhythm],
            "rarity": rarity_label(geo), "geo": round(geo, 3),
        })
    names = {s["name"] for s in species}

    # Days, newest first, with their paintings.
    journal = store.journal_days(limit=366)
    listening = [row["day"] for row in journal]
    start = date.fromisoformat(min(listening)) if listening else now.date()
    span = (date.fromisoformat(max(listening)) - start).days + 1 if listening else 0
    for s in species:
        s["presence"] = _presence(heard.get(s["name"], []), start, span)
    activity = {row["day"]: row["hours"] for row in store.activity_matrix(days=366)}
    day_birds: dict[str, int] = Counter(
        day for name in names for day in heard.get(name, []))

    images_dir = out_dir / "images"
    art_dir = out_dir / "art"
    paintings, keep, hero_src = [], set(), None
    for rec in store.recent_images(limit=100_000):
        src = Path(rec.path)
        if "(fallback)" in rec.style or not src.exists():
            continue                      # text posters aren't paintings
        hero_src = hero_src or src        # newest first
        edition_id = _edition_id(rec.path)
        style = style_by_name.get(rec.style)
        urls = _encode_widths(src, images_dir, edition_id)
        keep.update(Path(url).name for url in urls.values())
        _write_atomic(art_dir / f"{edition_id}.json", json.dumps(
            {"prompt": rec.prompt}, ensure_ascii=False).encode())
        keep.add(f"{edition_id}.json")
        paintings.append({
            "id": edition_id, "day": rec.source_day,
            "made": rec.generated_at.isoformat(timespec="minutes"),
            "style": _title_case(rec.style), "collection": style.collection if style else "",
            "medium": style.medium if style else "", "lineage": style.lineage if style else "",
            "reason": _OWNER_REASONS.get(rec.style_reason, rec.style_reason),
            "character": _character(rec.art_profile),
            "birds": [name for name in rec.species if name in names],
            "frame": rec.posted_at is not None, "images": urls,
        })

    by_day: dict[str, list[str]] = {}
    for p in paintings:
        by_day.setdefault(p["day"], []).append(p["id"])
    days = []
    for row in journal:
        top_hour = max(activity.get(row["day"], [0])) or 1
        days.append({
            "day": row["day"], "species": day_birds.get(row["day"], 0),
            "top": [s["common_name"] for s in row["top_species"] if s["common_name"] in names][:4],
            "new": [name for name in row["new_species"] if name in names],
            "rhythm": [round(v / top_hour, 3) for v in activity.get(row["day"], [0] * 24)],
            "paintings": by_day.get(row["day"], []),
        })

    last_heard = next(({"name": d.common_name, "at": d.timestamp.isoformat(timespec="minutes")}
                       for d in store.recent_detections(limit=50) if d.common_name in names), None)
    site = {
        "title": title, "place": place, "url": base_url.rstrip("/"),
        "generated": now.isoformat(timespec="minutes"),
        "since": min(listening) if listening else None,
        "until": max(listening) if listening else None,
        "listeningDays": len(listening), "lastHeard": last_heard,
        "highlights": _highlights(species, paintings, days, store.dawn_openers(),
                                  have_geo=bool(geo_lookup)),
        "paintings": paintings, "species": species, "days": days,
    }
    for s in species:
        s.pop("geo")                       # used for highlights only

    # The shell: template + data, with assets fingerprinted for caching.
    assets = {}
    for name in ("site.css", "site.js"):
        content = (TEMPLATE_DIR / name).read_bytes()
        _write_atomic(out_dir / "assets" / name, content)
        assets[name] = hashlib.sha256(content).hexdigest()[:10]
    og_image = ""
    if hero_src:
        _write_atomic(out_dir / "og.jpg", _og_image(hero_src))
        og_image = f"{site['url']}/og.jpg" if site["url"] else "og.jpg"
    description = (f"Birds heard at a window in {place}, painted each day. "
                   f"{len(species)} species since {site['since'] or 'the first morning'}.")
    data = json.dumps(site, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = (TEMPLATE_DIR / "index.html").read_text()
    for token, value in {
        "%%TITLE%%": html.escape(title), "%%DESCRIPTION%%": html.escape(description),
        "%%OG_IMAGE%%": html.escape(og_image), "%%CSS_V%%": assets["site.css"],
        "%%JS_V%%": assets["site.js"], "%%DATA%%": data,
    }.items():
        page = page.replace(token, value)
    _write_atomic(out_dir / "index.html", page.encode())

    for folder in (images_dir, art_dir):   # drop what the archive no longer has
        for stale in (p for p in folder.glob("*") if p.name not in keep) if folder.exists() else ():
            stale.unlink()
    return {"paintings": len(paintings), "species": len(species), "days": len(days),
            "path": str(out_dir)}


def _og_image(src: Path) -> bytes:
    """A link-preview image: the latest painting as a JPEG."""
    with Image.open(src) as art:
        out = io.BytesIO()
        art.convert("RGB").save(out, format="JPEG", quality=85)
        return out.getvalue()


def deploy(out_dir: Path, command: str, timeout: float = 600) -> str:
    """Run the configured deploy command ({dir} is the built folder). Split
    like a shell would, but never run through one."""
    args = [part.replace("{dir}", str(out_dir)) for part in shlex.split(command)]
    done = subprocess.run(args, cwd=out_dir, capture_output=True, text=True,
                          timeout=timeout, check=True)
    return done.stdout.strip()


class SitePublisher:
    """Rebuilds (and optionally deploys) the public site off the main loop:
    after each new painting, and otherwise at most every `refresh_seconds`
    so the season's figures stay current."""

    def __init__(self, build: Callable[[], dict], latest: Callable[[], int | None],
                 deploy_command: str = "", out_dir: Path | None = None,
                 refresh_seconds: float = 3600, clock: Callable[[], float] = time.monotonic):
        self.build = build
        self.latest = latest
        self.deploy_command = deploy_command
        self.out_dir = out_dir
        self.refresh_seconds = refresh_seconds
        self.clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._built_for: int | None = None
        self._last_attempt: float | None = None
        self.status: dict = {"built_at": None, "error": None, "running": False}

    def due(self) -> bool:
        if self._running:
            return False
        if self._last_attempt is None or self.latest() != self._built_for:
            return True
        return self.clock() - self._last_attempt >= self.refresh_seconds

    def maybe_publish(self) -> bool:
        return self.publish_now() if self.due() else False

    def publish_now(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self.status["running"] = True
        threading.Thread(target=self.run_once, name="birdframe-public-site", daemon=True).start()
        return True

    def run_once(self) -> dict:
        latest = self.latest()
        try:
            summary = self.build()
            if self.deploy_command and self.out_dir:
                deploy(self.out_dir, self.deploy_command)
            self._built_for = latest
            self.status.update(summary, built_at=datetime.now().isoformat(timespec="seconds"),
                               error=None)
            return summary
        except Exception as exc:  # a failed build must never disturb listening
            log.warning("Public site build failed: %s", exc)
            self.status["error"] = str(exc)
            return {}
        finally:
            self._last_attempt = self.clock()
            with self._lock:
                self._running = False
                self.status["running"] = False

