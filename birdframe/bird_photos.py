"""A small, attributed Wikimedia field guide, cached off the detector thread.

Photos illustrate the species, not an individual seen at the window. A failed
lookup leaves the observatory usable; misses retry the next day. Only a bounded
number of new species is fetched per build, with no store lock held for I/O.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
from pathlib import Path
import time
from urllib.parse import quote, urlsplit
from html.parser import HTMLParser

from PIL import Image

USER_AGENT = 'Birdframe/1.0 (https://github.com/ddrayne/mac-birdnet; bird observatory)'


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    return ' '.join(html.unescape(' '.join(parser.parts)).split())


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + '.partial')
    partial.write_bytes(data)
    partial.replace(path)


def fetch_bird(scientific: str, cache_dir: Path, http_get) -> dict:
    """Resolve one Wikipedia page and Commons photo, retaining its credits."""
    def get(url, **kwargs):
        response = http_get(url, headers={'User-Agent': USER_AGENT}, timeout=6,
                            follow_redirects=True, **kwargs)
        response.raise_for_status()
        return response

    pages = get('https://en.wikipedia.org/w/api.php', params={
        'action': 'query', 'format': 'json', 'redirects': 1,
        'titles': scientific, 'prop': 'pageimages|extracts',
        'piprop': 'name', 'exintro': 1, 'explaintext': 1,
    }).json().get('query', {}).get('pages', {})
    page = next(iter(pages.values()), {})
    if not page.get('pageimage'):
        return {}
    info_pages = get('https://commons.wikimedia.org/w/api.php', params={
        'action': 'query', 'format': 'json', 'titles': 'File:' + page['pageimage'],
        'prop': 'imageinfo', 'iiprop': 'url|extmetadata', 'iiurlwidth': 640,
    }).json().get('query', {}).get('pages', {})
    infos = next(iter(info_pages.values()), {}).get('imageinfo', [])
    if not infos:
        return {}
    info = infos[0]
    meta = info.get('extmetadata', {})
    value = lambda name: _plain(meta.get(name, {}).get('value', ''))
    license_name, author = value('LicenseShortName'), value('Artist')
    # Publish only an identified free license, with the complete author credit.
    if not author or not (license_name.startswith(('CC BY', 'CC0', 'Public domain'))):
        return {}
    source = info.get('descriptionurl', '')
    if urlsplit(source).hostname != 'commons.wikimedia.org':
        return {}
    license_url = value('LicenseUrl')
    if urlsplit(license_url).scheme != 'https' or urlsplit(license_url).hostname != 'creativecommons.org':
        license_url = source
    url = info.get('thumburl', '')
    if urlsplit(url).hostname not in ('upload.wikimedia.org', 'thumb.wikimedia.org'):
        return {}
    content = get(url).content
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert('RGB')
        image.thumbnail((960, 960), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, 'WEBP', quality=82)
    blob = out.getvalue()
    filename = hashlib.sha256(blob).hexdigest()[:20] + '.webp'
    _write(cache_dir / filename, blob)
    # A short introduction, linked and credited separately from the photograph.
    intro = page.get('extract', '').split('\n')[0]
    if len(intro) > 500:
        intro = intro[:497].rsplit(' ', 1)[0] + '…'
    return {'file': filename, 'author': author, 'license': license_name,
            'licenseUrl': license_url, 'source': source,
            'article': 'https://en.wikipedia.org/wiki/' + quote(page['title'].replace(' ', '_')),
            'intro': intro, 'alterations': 'Resized and converted to WebP'}


def enrich_species(species: list[dict], cache_dir: Path, out_dir: Path, *,
                   http_get=None, max_fetch: int = 2, now: float | None = None) -> None:
    """Reuse cached photographs and resolve a few missing entries each build."""
    if http_get is None:
        import httpx
        http_get = httpx.get
    now = time.time() if now is None else now
    cache_dir = Path(cache_dir)
    fetched = 0
    for bird in sorted(species, key=lambda b: -b['count']):
        key = hashlib.sha256(bird['scientific'].encode()).hexdigest()[:20]
        record_path = cache_dir / (key + '.json')
        try:
            record = json.loads(record_path.read_text())
        except (OSError, ValueError):
            record = {}
        photo = record.get('photo', {})
        if photo and not (cache_dir / photo['file']).is_file():
            record, photo = {}, {}
        if not photo and now - record.get('checked', -86400) >= 86400 and fetched < max_fetch:
            fetched += 1
            try:
                photo = fetch_bird(bird['scientific'], cache_dir, http_get)
            except Exception:
                photo = {}
            _write(record_path, json.dumps({'checked': now, 'photo': photo}).encode())
        if photo:
            target = out_dir / 'birds' / photo['file']
            if not target.exists():
                _write(target, (cache_dir / photo['file']).read_bytes())
            bird['photo'] = {k: v for k, v in photo.items() if k != 'file'}
            bird['photo']['url'] = 'birds/' + photo['file']
    keep = {Path(b['photo']['url']).name for b in species if b.get('photo')}
    if (out_dir / 'birds').exists():
        for stale in (out_dir / 'birds').glob('*.webp'):
            if stale.name not in keep:
                stale.unlink()
