"""Public observatory data, derived from indexed quarter-hour aggregates.

Each day is read separately so the detector can take the store lock between
queries. No event IDs, exact timestamps, sound files or device data leave here.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json


def observatory_data(store, species: list[dict], days: list[str], *,
                     profiles: list | None = None, sun_lookup=None) -> tuple[list[dict], dict]:
    by_name = {bird['name']: bird for bird in species}
    histories: dict[str, list] = defaultdict(list)
    payloads, summaries = {}, []
    for day in sorted(days, reverse=True):
        quarters, richness, voices = [0] * 96, [0] * 96, []
        birds: dict[str, dict] = {}
        rows = [row for row in store.day_profile(day) if row['common_name'] in by_name]
        if profiles is not None and sun_lookup is not None:
            from birdframe.seasons import fold_day
            profiles.append(fold_day(day, rows, sun_lookup(day)))
        for row in rows:
            known = by_name.get(row['common_name'])
            if known is None:
                continue
            slot, count = row['quarter'], row['n']
            bird = birds.setdefault(known['slug'], {
                'slug': known['slug'], 'count': 0, 'best': 0.0,
                'first': '24:00', 'last': '00:00', 'hours': [0] * 24,
            })
            bird['count'] += count
            bird['best'] = round(max(bird['best'], row['best']), 3)
            bird['first'] = min(bird['first'], row['first'][11:16])
            bird['last'] = max(bird['last'], row['last'][11:16])
            bird['hours'][slot // 4] += count
            quarters[slot] += count
            richness[slot] += 1
            voices.append([slot, known['slug'], count])
        ranked = sorted(birds.values(), key=lambda bird: (-bird['count'], bird['slug']))
        for bird in ranked:
            histories[bird['slug']].append([day, bird['count']])
        hours = [sum(quarters[h * 4:h * 4 + 4]) for h in range(24)]
        summary = {
            'day': day, 'count': sum(quarters), 'species': len(ranked), 'hours': hours,
            'first': min((b['first'] for b in ranked), default=None),
            'last': max((b['last'] for b in ranked), default=None),
            'top': [b['slug'] for b in ranked[:5]],
        }
        payloads[day] = {**summary, 'quarters': quarters, 'richness': richness,
                         'birds': ranked, 'voices': sorted(voices)}
        summaries.append(summary)
    recent, previous = set(sorted(days)[-7:]), set(sorted(days)[-14:-7])
    for bird in species:
        bird['history'] = sorted(histories[bird['slug']])
        bird['recent'] = sum(n for day, n in bird['history'] if day in recent)
        bird['previous'] = sum(n for day, n in bird['history'] if day in previous)
    presence = {b['slug']: {day for day, n in b['history']} for b in species}
    for bird in species:
        shared = sorted(({'slug': other['slug'], 'days': len(
            presence[bird['slug']] & presence[other['slug']])}
            for other in species if other is not bird),
            key=lambda item: (-item['days'], item['slug']))
        bird['companions'] = [item for item in shared[:4] if item['days']]
    return summaries, payloads


def day_version(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def season_data(profiles: list, today, geo_lookup: dict) -> dict:
    """Reuse the internal season analysis, exporting public aggregate views only."""
    from birdframe.seasons import analyse
    story = analyse(profiles, today, geo_lookup)
    events = []
    for event in story['chronicle']:
        event = dict(event)
        if event['kind'] == 'arrival':
            event['title'] = f"First {event['species']} recorded"
        elif event['kind'] == 'passage':
            event['title'] = f"A spell of {event['species']} records"
        elif event['kind'] == 'departure':
            event['title'] = f"{event['species']} goes quiet"
        events.append(event)
    labels = {'departed': 'Gone quiet', 'passage': 'A concentrated spell',
              'arrived': 'New in recent records', 'resident': 'Regular voice',
              'occasional': 'Occasional voice', 'brief': 'Brief record'}
    return {**{key: story[key] for key in ('light', 'night', 'trends', 'records', 'growth')},
            'chronicle': events,
            'statuses': {bird['common_name']: labels[bird['status']]
                         for bird in story['species']}}
