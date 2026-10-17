"""Opt-in export of saved best-of-day bird recordings, never a live microphone."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import io
import json
from pathlib import Path

import soundfile as sf


def export_recordings(store, species: list[dict], daily: dict, out_dir: Path) -> int:
    """Read one indexed day at a time; release the store lock before file I/O.

    Content-addressed files let a better clip replace yesterday's URL safely,
    and prevent browser caches retaining an older, weaker identification.
    """
    by_name = {bird['name']: bird for bird in species}
    clips_by_slug = defaultdict(list)
    keep = set()
    audio_dir = out_dir / 'audio'
    for day, payload in daily.items():
        for row in store.clips_for_day(day):
            bird = by_name.get(row['common_name'])
            if bird is None:
                continue
            try:
                source = Path(row['path'])
                before = source.stat()
                blob = source.read_bytes()
                after = source.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    continue  # the detector is still saving this recording
                info = sf.info(io.BytesIO(blob))
                if info.format != 'OGG' or not 0 < info.duration <= 60:
                    continue
            except (OSError, RuntimeError):
                continue
            digest = hashlib.sha256(blob).hexdigest()[:20]
            name = digest + '.ogg'
            target = audio_dir / name
            if not target.exists():
                audio_dir.mkdir(parents=True, exist_ok=True)
                partial = target.with_suffix('.partial')
                partial.write_bytes(blob)
                partial.replace(target)
            keep.add(name)
            clip = {'day': day, 'url': 'audio/' + name,
                    'confidence': round(row['confidence'], 3),
                    'duration': round(info.duration, 1)}
            clips_by_slug[bird['slug']].append(clip)
            for record in payload['birds']:
                if record['slug'] == bird['slug']:
                    record['clip'] = clip
                    break
    recordings_dir = out_dir / 'recordings'
    keep_indexes = set()
    for bird in species:
        clips = sorted(clips_by_slug[bird['slug']], key=lambda c: c['day'], reverse=True)
        bird['clipCount'] = len(clips)
        if not clips:
            continue
        bird['clip'] = max(clips, key=lambda c: (c['confidence'], c['day']))
        content = json.dumps(clips, separators=(',', ':')).encode()
        version = hashlib.sha256(content).hexdigest()[:12]
        filename = bird['slug'] + '.json'
        bird['recordings'] = 'recordings/' + filename + '?v=' + version
        keep_indexes.add(filename)
        target = recordings_dir / filename
        if not target.exists() or target.read_bytes() != content:
            recordings_dir.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix('.partial')
            partial.write_bytes(content)
            partial.replace(target)
    for folder, allowed, pattern in ((audio_dir, keep, '*.ogg'),
                                     (recordings_dir, keep_indexes, '*.json')):
        if folder.exists():
            for stale in folder.glob(pattern):
                if stale.name not in allowed:
                    stale.unlink()
    return sum(len(clips) for clips in clips_by_slug.values())
