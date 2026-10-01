"""The long view: how the window's birdlife changes through the seasons.

Each listening day is folded once (`fold_day`) from the store's per-day summary
into a small profile, and `analyse` turns the profiles into the season's story:
who arrived and who went quiet, how the chorus follows the sun, which voices
grew louder or quieter, the surprises, the records, and a dated chronicle.
Everything here is pure (no clock, network or database) apart from
`SeasonArchive`, the thin cache that reads one day at a time from the store.

The same honesty rules as the rest of birdframe apply:

- Counts are BirdNET detections, never numbers of birds.
- A bird has "gone quiet", not "left": it may only have stopped calling. A
  silence counts when it is unlikely to be chance: a bird still heard on a
  share r of days would go unheard for g listening days with chance
  (1 - r)^g, and only silences below SILENCE_CHANCE are told.
- Only confirmed and probable species make the story. Doubtful ones are
  listed apart, to listen to and judge.
- Dawn, dusk and night come from the sun at the configured place, so they
  follow the season (and the clocks changing) like the birds do.
"""
from __future__ import annotations

import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from statistics import median, quantiles

from birdframe.reliability import GEO_DEFAULT, assess, rarity_label

SILENCE_CHANCE = 0.01   # a silence less likely than this to be chance is real news
MIN_SILENCE = 7         # listening days unheard before a bird has gone quiet (or was new)
MIN_SPELL = 14          # a silent spell inside the record worth telling
MIN_DAYS = 3            # days heard before a bird can arrive, go quiet or pass through
BRIEF_DAYS = 2          # heard on no more days than this: a brief visit
RESIDENT_SHARE = 0.5    # heard on at least this share of days: a constant companion
DAWN_WINDOW = (-120, 240)   # minutes around sunrise that hold the morning's first voice
DUSK_WINDOW = (-240, 120)   # minutes around sunset that hold the evening's last voice
# A species' morning starts when it gets going and keeps going: two busy
# quarter-hours in a row, each with at least ONSET_MIN detections and
# ONSET_SHARE of its busiest quarter-hour in the window. A stray call isn't
# dawn, and a bird already that busy in the hour before the window (an owl,
# or a gull calling all night) didn't wake with the sun at all, so it has no
# morning that day (likewise at dusk).
ONSET_MIN = 2
ONSET_SHARE = 0.20
ONSET_LEAD = 60
# A bird heard per hour of night at least this share of its rate per hour of
# day keeps night hours (an owl, a calling oystercatcher, geese and migrants
# overhead): it says nothing about when the chorus wakes, so dawn and dusk
# timings leave it out.
NIGHT_RATIO = 0.25
MIN_MORNINGS = 7        # mornings a species needs to take a place in the dawn roster
MORNING_SHARE = 0.25    # …or this share of the record, if that is more
RECENT_DAYS = 21        # the "lately" compared against everything before it
MIN_EARLIER_DAYS = 14   # trends need at least this much history before "lately"
TREND_RATIO = 1.6       # this much louder (or quieter) per day is a change worth telling
MIN_TREND_DETECTIONS = 40
FOUNDING_DAYS = 7       # firsts in the first week are the founding roll call, not news
UNCOMMON_GEO = 0.30     # below this, a species is uncommon here (reliability's own line)
MILESTONES = (10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500)
# How the season chart orders its groups: the leavers, the passers-by and the
# newcomers first, so reading down the chart reads through the season.
STATUS_ORDER = ("departed", "passage", "arrived", "resident", "occasional", "brief")


@dataclass(frozen=True)
class Sun:
    """One day's sun, in minutes after local midnight; None when the event
    doesn't happen that day (polar summer or winter)."""
    dawn: float | None      # civil dawn: the sun 6° below the horizon
    sunrise: float | None
    sunset: float | None
    dusk: float | None


def local_zone(day: date) -> tzinfo:
    """This machine's UTC offset on `day`. Detections are stamped in local
    time, so the sun must be too; noon is clear of any clock change."""
    return timezone(datetime(day.year, day.month, day.day, 12).astimezone().utcoffset())


@lru_cache(maxsize=4096)
def sun_for(day: date, latitude: float, longitude: float, tz: tzinfo | None = None) -> Sun:
    from astral import Observer
    from astral import sun as solar

    zone = tz or local_zone(day)
    observer = Observer(latitude=latitude, longitude=longitude)

    def minutes(event) -> float | None:
        try:
            when = event(observer, date=day, tzinfo=zone)
        except ValueError:          # the sun never rises, sets or gets that low
            return None
        return round((when.date() - day).days * 1440 + when.hour * 60
                     + when.minute + when.second / 60, 1)

    return Sun(dawn=minutes(solar.dawn), sunrise=minutes(solar.sunrise),
               sunset=minutes(solar.sunset), dusk=minutes(solar.dusk))


@dataclass(frozen=True)
class Heard:
    """One species on one listening day."""
    scientific_name: str
    detections: int
    best: float
    first: str                  # "HH:MM:SS"
    last: str
    morning: float | None       # minutes after midnight when it got going around sunrise
    evening: float | None       # …and when it last called in earnest around sunset
    night: int                  # detections after dark (see `night_hours`)


@dataclass(frozen=True)
class DayProfile:
    day: str
    quarters: tuple[int, ...]   # every detection, by quarter-hour (96 slots)
    species: dict[str, Heard]
    sun: Sun

    @property
    def detections(self) -> int:
        return sum(self.quarters)


def _minutes(ts: str) -> float:
    return int(ts[11:13]) * 60 + int(ts[14:16]) + int(ts[17:19]) / 60


def night_hours(sun: Sun) -> tuple[float | None, float | None]:
    """Night, in minutes after midnight: from the end of civil dusk until the
    dawn window opens two hours before sunrise, so the dawn chorus (which
    starts before civil dawn) isn't counted as night song. None where it
    doesn't apply: there is no civil dusk on a midsummer night up north."""
    ends = sun.sunrise + DAWN_WINDOW[0] if sun.sunrise is not None else sun.dawn
    return ends, sun.dusk


def _night_length(sun: Sun) -> float:
    ends, starts = night_hours(sun)
    return (max(0.0, ends) if ends is not None else 0.0) + \
        (max(0.0, 1440 - starts) if starts is not None else 0.0)


def _onset(slots: dict[int, dict], window: tuple[float, float] | None,
           last: bool = False) -> float | None:
    """When a species got going inside a window: the first detection of the
    first two busy quarter-hours in a row, in minutes (with `last`, when it
    settled: the last detection of the last two)."""
    if window is None:
        return None
    mid = {q: q * 15 + 7.5 for q in slots}
    inside = [q for q in sorted(slots) if window[0] <= mid[q] <= window[1]]
    if not inside:
        return None
    need = max(ONSET_MIN, math.ceil(ONSET_SHARE * max(slots[q]["n"] for q in inside)))
    beyond = ((window[1], window[1] + ONSET_LEAD) if last
              else (window[0] - ONSET_LEAD, window[0]))
    if any(slots[q]["n"] >= need for q in slots if beyond[0] <= mid[q] < beyond[1]):
        return None                 # calling all night: it didn't keep the sun's hours
    busy = {q for q in inside if slots[q]["n"] >= need}
    # Getting going means keeping going: a chance pair of night calls fills
    # one quarter-hour, not two in a row.
    step = -1 if last else 1
    sustained = [q for q in sorted(busy, reverse=last) if q + step in busy]
    if not sustained:
        return None
    return round(_minutes(slots[sustained[0]]["last"] if last else slots[sustained[0]]["first"]), 1)


def fold_day(day: str, rows: list[dict], sun: Sun) -> DayProfile:
    """Fold `Store.day_profile` rows into a DayProfile.

    A quarter-hour belongs to a window (dawn, dusk, night) when its midpoint
    does; exact times come from the rows themselves. The windows are
    generous, so a quarter-hour's rounding never matters.
    """
    def window(anchor, span):
        return None if anchor is None else (anchor + span[0], anchor + span[1])

    quarters = [0] * 96
    slots: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in rows:
        quarters[int(row["quarter"])] += row["n"]
        slots[row["common_name"]][int(row["quarter"])] = row
    dawn, dusk = window(sun.sunrise, DAWN_WINDOW), window(sun.sunset, DUSK_WINDOW)
    night_ends, night_starts = night_hours(sun)
    species = {}
    for name, by_quarter in slots.items():
        heard = list(by_quarter.values())
        dark = sum(r["n"] for q, r in by_quarter.items()
                   if (night_ends is not None and q * 15 + 7.5 < night_ends)
                   or (night_starts is not None and q * 15 + 7.5 > night_starts))
        species[name] = Heard(
            scientific_name=heard[0]["scientific_name"],
            detections=sum(r["n"] for r in heard), best=max(r["best"] for r in heard),
            first=min(r["first"] for r in heard)[11:19], last=max(r["last"] for r in heard)[11:19],
            morning=_onset(by_quarter, dawn), evening=_onset(by_quarter, dusk, last=True),
            night=dark)
    return DayProfile(day=day, quarters=tuple(quarters), species=species, sun=sun)


class SeasonArchive:
    """The archive folded day by day, remembering days that can't change.

    A day is settled once the next has passed: a detection may be stamped a
    moment before midnight and written just after it, so yesterday and today
    are re-read on every visit and everything older only once. Each day is a
    separate store call, so the detector can take the store's lock between
    days. Call `clear` when history is rewritten (a species purged as "not
    here").
    """

    def __init__(self, store, latitude: float, longitude: float, tz: tzinfo | None = None):
        self.store = store
        self.latitude = latitude
        self.longitude = longitude
        self.tz = tz
        self._settled: dict[str, DayProfile | None] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._settled.clear()

    def profiles(self, today: date) -> list[DayProfile]:
        first, last = self.store.listening_span()
        if first is None:
            return []
        settled = (today - timedelta(days=1)).isoformat()
        found = []
        with self._lock:
            day, end = date.fromisoformat(first), date.fromisoformat(last)
            while day <= end:
                key = day.isoformat()
                if key in self._settled:
                    profile = self._settled[key]
                else:
                    rows = self.store.day_profile(key)
                    profile = fold_day(key, rows, sun_for(
                        day, self.latitude, self.longitude, self.tz)) if rows else None
                    if key < settled:
                        self._settled[key] = profile
                if profile is not None:
                    found.append(profile)
                day += timedelta(days=1)
        return found


# ---------------------------------------------------------------------------
# Analysis

@dataclass
class _Bird:
    name: str
    scientific_name: str
    days: list[str] = field(default_factory=list)   # listening days heard, oldest first
    first_at: str = ""                               # time of day it was first ever heard
    detections: int = 0
    best: float = 0.0
    geo: float = GEO_DEFAULT
    tier: str = "tentative"
    reasons: list[str] = field(default_factory=list)
    status: str = "brief"
    quiet_for: int = 0          # finished listening days since it was last heard
    observed: int = 0           # listening days from its first record to now
    spells: list[dict] = field(default_factory=list)
    night: int = 0              # detections after dark…
    night_minutes: float = 0.0  # …over this much darkness on the days it was heard
    day_minutes: float = 0.0

    @property
    def nocturnal(self) -> bool:
        if not self.night or not self.night_minutes:
            return False
        by_day = (self.detections - self.night) / self.day_minutes if self.day_minutes else 0
        return not by_day or (self.night / self.night_minutes) / by_day >= NIGHT_RATIO


def _long(day: str) -> str:
    when = date.fromisoformat(day)
    return f"{when.day} {when:%B}"


def _between(first: str, last: str) -> str:
    """Two days as prose: '18 and 23 August', or '28 August and 3 September'."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    return f"{a.day} and {_long(last)}" if (a.year, a.month) == (b.year, b.month) \
        else f"{_long(first)} and {_long(last)}"


def _heard_on(heard: int, of: int) -> str:
    return f"all {of} days" if heard == of else f"{heard} of the {of} days"


def _times(trend: dict) -> str:
    """A trend's size in words: "3.0 times as much", "about half as much"."""
    ratio = trend["recent_rate"] / trend["earlier_rate"] if trend["earlier_rate"] else trend["ratio"]
    if ratio >= 1:
        return f"{ratio:.1f} times as much"
    for low, high, words in ((0.45, 0.56, "half"), (0.30, 0.37, "a third"),
                             (0.23, 0.27, "a quarter"), (0.18, 0.22, "a fifth")):
        if low <= ratio <= high:
            return f"about {words} as much"
    return f"{round(ratio * 100)}% as much"


def _clock(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    hours, mins = divmod(int(round(minutes)), 60)
    return f"{hours % 24:02d}:{mins:02d}"


def _duration(minutes: float) -> str:
    hours, mins = divmod(int(round(abs(minutes))), 60)
    if not hours:
        return f"{mins} min"
    return f"{hours} h {mins:02d} min" if mins else f"{hours} h"


def _mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _monday(day: str) -> date:
    when = date.fromisoformat(day)
    return when - timedelta(days=when.weekday())


def _roster(profiles: list[DayProfile], geo_lookup: dict) -> dict[str, _Bird]:
    birds: dict[str, _Bird] = {}
    for profile in profiles:
        for name, heard in profile.species.items():
            bird = birds.get(name)
            if bird is None:
                bird = birds[name] = _Bird(name, heard.scientific_name, first_at=heard.first)
            bird.days.append(profile.day)
            bird.detections += heard.detections
            bird.best = max(bird.best, heard.best)
            dark = _night_length(profile.sun)
            bird.night += heard.night
            bird.night_minutes += dark
            bird.day_minutes += 1440 - dark
    for bird in birds.values():
        bird.geo = geo_lookup.get(bird.scientific_name, GEO_DEFAULT)
        verdict = assess(bird.best, bird.geo, bird.detections)
        bird.tier, bird.reasons = verdict.tier, verdict.reasons
    return birds


def _classify(birds: dict[str, _Bird], days: list[str], today_open: bool) -> None:
    """Sort each bird into a status by how its record starts, ends and breaks.

    `rate` is how often it was heard between its first and last record,
    shrunk by two imaginary silent days so that a short run of records
    proves little. Today, still under way, never counts as a silent day.
    """
    index = {day: i for i, day in enumerate(days)}
    total = len(days)
    for bird in birds.values():
        first, last = index[bird.days[0]], index[bird.days[-1]]
        heard = len(bird.days)
        rate = heard / (last - first + 3)
        unfinished = 1 if today_open and bird.days[-1] != days[-1] else 0
        bird.quiet_for = total - 1 - last - unfinished
        bird.observed = total - first - unfinished
        gone = (heard >= MIN_DAYS and bird.quiet_for >= MIN_SILENCE
                and (1 - rate) ** bird.quiet_for < SILENCE_CHANCE)
        new = (heard >= MIN_DAYS and first >= MIN_SILENCE
               and (1 - rate) ** first < SILENCE_CHANCE)
        bird.spells = []
        for before, after in zip(bird.days, bird.days[1:]):
            gap = index[after] - index[before] - 1
            if gap >= MIN_SPELL and (1 - rate) ** gap < SILENCE_CHANCE:
                bird.spells.append({"from": before, "to": after, "days": gap})
        if heard <= BRIEF_DAYS:
            bird.status = "brief"
        elif gone and new:
            bird.status = "passage"
        elif gone:
            bird.status = "departed"
        elif new:
            bird.status = "arrived"
        elif heard / total >= RESIDENT_SHARE:
            bird.status = "resident"
        else:
            bird.status = "occasional"


def _weeks(profiles: list[DayProfile], reliable: dict[str, _Bird]):
    """Monday-to-Sunday weeks: listening effort and voices, plus each
    well-supported species' days heard and detections per week."""
    start, end = _monday(profiles[0].day), _monday(profiles[-1].day)
    weeks, voices = [], []
    when = start
    while when <= end:
        weeks.append({"start": when.isoformat(), "days": 0, "detections": 0, "species": 0})
        voices.append(set())
        when += timedelta(days=7)
    presence = {name: [0] * len(weeks) for name in reliable}
    volume = {name: [0] * len(weeks) for name in reliable}
    slot_of = {}
    for profile in profiles:
        slot = (_monday(profile.day) - start).days // 7
        slot_of[profile.day] = slot
        weeks[slot]["days"] += 1
        weeks[slot]["detections"] += profile.detections
        for name, heard in profile.species.items():
            if name in reliable:
                presence[name][slot] += 1
                volume[name][slot] += heard.detections
                voices[slot].add(name)
    for week, heard in zip(weeks, voices):
        week["species"] = len(heard)
    return weeks, presence, volume, slot_of


def _light(complete: list[DayProfile], chorus: dict[str, _Bird]) -> list[dict]:
    """Per finished day: the sun, and the first and last voices of the chorus."""
    rows = []
    for profile in complete:
        mornings = [(h.morning, name) for name, h in profile.species.items()
                    if name in chorus and h.morning is not None]
        evenings = [(h.evening, name) for name, h in profile.species.items()
                    if name in chorus and h.evening is not None]
        first = min(mornings) if mornings else (None, None)
        last = max(evenings) if evenings else (None, None)
        sun = profile.sun
        rows.append({"day": profile.day, "dawn": sun.dawn, "sunrise": sun.sunrise,
                     "sunset": sun.sunset, "dusk": sun.dusk,
                     "first": first[0], "first_species": first[1],
                     "last": last[0], "last_species": last[1]})
    return rows


def _light_summary(rows: list[dict]) -> dict | None:
    mornings = [r for r in rows if r["first"] is not None and r["sunrise"] is not None]
    evenings = [r for r in rows if r["last"] is not None and r["sunset"] is not None]
    if not mornings:
        return None

    def period(chunk):
        return {"from": chunk[0]["day"], "to": chunk[-1]["day"],
                "sunrise": _mean(r["sunrise"] for r in chunk),
                "first": _mean(r["first"] for r in chunk),
                "sunset": _mean(r["sunset"] for r in chunk),
                "last": _mean(r["last"] for r in chunk),
                "daylight": _mean(r["sunset"] - r["sunrise"] for r in chunk
                                  if r["sunset"] is not None)}

    return {
        "start": period(mornings[:7]), "now": period(mornings[-7:]),
        "mornings": len(mornings),
        "offset": round(median(r["first"] - r["sunrise"] for r in mornings)),
        "evening_offset": (round(median(r["last"] - r["sunset"] for r in evenings))
                           if evenings else None),
    }


def _dawn_roster(complete: list[DayProfile], chorus: dict[str, _Bird]) -> list[dict]:
    """Who wakes first: when each regular dawn voice gets going, against sunrise."""
    offsets: dict[str, list[float]] = defaultdict(list)
    for profile in complete:
        if profile.sun.sunrise is None:
            continue
        for name, heard in profile.species.items():
            if name in chorus and heard.morning is not None:
                offsets[name].append(heard.morning - profile.sun.sunrise)
    need = max(MIN_MORNINGS, round(MORNING_SHARE * len(complete)))
    rows = []
    for name, values in offsets.items():
        if len(values) < need:
            continue
        q1, mid, q3 = quantiles(values, n=4, method="inclusive")
        rows.append({"common_name": name, "median": round(mid), "q1": round(q1),
                     "q3": round(q3), "mornings": len(values)})
    rows.sort(key=lambda r: (r["median"], r["common_name"]))
    return rows


def _night(profiles: list[DayProfile], reliable: dict[str, _Bird],
           slot_of: dict[str, int], n_weeks: int) -> dict:
    per: dict[str, dict] = {}
    weekly = [0] * n_weeks
    for profile in profiles:
        for name, heard in profile.species.items():
            if name not in reliable or not heard.night:
                continue
            entry = per.setdefault(name, {"common_name": name, "nights": 0,
                                          "detections": 0, "first": profile.day,
                                          "nocturnal": reliable[name].nocturnal})
            entry["nights"] += 1
            entry["detections"] += heard.night
            entry["last"] = profile.day
            weekly[slot_of[profile.day]] += heard.night
    rows = sorted(per.values(), key=lambda e: (-e["nights"], -e["detections"], e["common_name"]))
    return {"species": rows[:10], "weekly": weekly}


def _trends(complete: list[DayProfile], reliable: dict[str, _Bird],
            weeks: list[dict], volume: dict[str, list[int]]) -> dict | None:
    """Louder or quieter lately: detections a day over the last RECENT_DAYS
    finished listening days against everything before, for birds heard
    throughout (arrivals and departures tell their own story)."""
    if len(complete) < RECENT_DAYS + MIN_EARLIER_DAYS:
        return None
    recent, earlier = complete[-RECENT_DAYS:], complete[:-RECENT_DAYS]
    rising, falling = [], []
    for name, bird in reliable.items():
        if bird.status not in ("resident", "occasional"):
            continue
        now = sum(p.species[name].detections for p in recent if name in p.species)
        before = sum(p.species[name].detections for p in earlier if name in p.species)
        if now + before < MIN_TREND_DETECTIONS:
            continue
        rate_now, rate_before = now / len(recent), before / len(earlier)
        ratio = (rate_now + 1) / (rate_before + 1)
        # Not heard at all lately is a silence, not a quieter voice.
        if 1 / TREND_RATIO < ratio < TREND_RATIO or not now:
            continue
        item = {
            "common_name": name, "scientific_name": bird.scientific_name,
            "recent_rate": round(rate_now, 1), "earlier_rate": round(rate_before, 1),
            "ratio": round(ratio, 2),
            "recent_presence": round(sum(name in p.species for p in recent) / len(recent), 2),
            "earlier_presence": round(sum(name in p.species for p in earlier) / len(earlier), 2),
            "weekly": [round(n / w["days"], 1) if w["days"] else None
                       for n, w in zip(volume[name], weeks)],
        }
        (rising if ratio > 1 else falling).append(item)

    # The size of a change and the size of the voice both matter: a robin
    # tripling outranks a rarity going from one call a day to four.
    def salience(item):
        loud = max(item["recent_rate"], item["earlier_rate"])
        return abs(math.log(item["ratio"])) * math.log1p(loud)

    rising.sort(key=salience, reverse=True)
    falling.sort(key=salience, reverse=True)
    return {"recent_days": RECENT_DAYS, "since": recent[0].day,
            "rising": rising[:5], "falling": falling[:5]}


def _bird_item(bird: _Bird, **extra) -> dict:
    return {"common_name": bird.name, "scientific_name": bird.scientific_name,
            "tier": bird.tier, "reasons": bird.reasons, "geo": round(bird.geo, 3),
            "rarity": rarity_label(bird.geo), "first": bird.days[0], "last": bird.days[-1],
            "days": len(bird.days), "detections": bird.detections,
            "best_confidence": round(bird.best, 2), **extra}


def _visitors(birds: dict[str, _Bird], have_geo: bool, young: bool) -> dict:
    """Uncommon, passing or brief well-supported birds, and the doubtful.
    In a `young` record every bird not yet heard often looks brief, so only
    rarity makes a bird notable until there are a couple of weeks to go on."""
    notable = []
    for bird in birds.values():
        if bird.tier == "tentative":
            continue
        why = []
        if have_geo and bird.geo < UNCOMMON_GEO:
            why.append(rarity_label(bird.geo))
        if bird.status == "brief" and not young:
            why.append("heard on a single day" if len(bird.days) == 1 else "heard on two days")
        elif bird.status == "passage":
            why.append("passed through")
        if why:
            notable.append(_bird_item(bird, why=why, status=bird.status))
    notable.sort(key=lambda b: (b["geo"] if have_geo else 0, b["days"], b["common_name"]))
    doubtful = sorted((b for b in birds.values() if b.tier == "tentative"),
                      key=lambda b: (-b.best, b.name))
    return {"notable": notable[:12],
            "doubtful": [_bird_item(b, status=b.status) for b in doubtful[:12]],
            "doubtful_total": len(doubtful)}


def _records(profiles: list[DayProfile], light: list[dict],
             reliable: dict[str, _Bird]) -> dict:
    records: dict = {}
    if not reliable:
        return records

    def voices(profile: DayProfile) -> int:
        return sum(name in reliable for name in profile.species)

    richest = max(profiles, key=voices)
    busiest = max(profiles, key=lambda p: p.detections)
    records["richest_day"] = {"day": richest.day, "species": voices(richest)}
    records["busiest_day"] = {"day": busiest.day, "detections": busiest.detections}
    mornings = [r for r in light if r["first"] is not None]
    evenings = [r for r in light if r["last"] is not None]
    if mornings:
        early = min(mornings, key=lambda r: r["first"])
        records["earliest_voice"] = {"day": early["day"], "at": _clock(early["first"]),
                                     "common_name": early["first_species"]}
    if evenings:
        late = max(evenings, key=lambda r: r["last"])
        records["latest_voice"] = {"day": late["day"], "at": _clock(late["last"]),
                                   "common_name": late["last_species"]}
    spans = [r for r in light if r["first"] is not None and r["last"] is not None]
    if spans:
        long = max(spans, key=lambda r: r["last"] - r["first"])
        records["longest_chorus"] = {"day": long["day"], "minutes": round(long["last"] - long["first"]),
                                     "from": _clock(long["first"]), "to": _clock(long["last"])}
    faithful = max(reliable.values(), key=lambda b: (len(b.days), b.detections))
    loudest = max(reliable.values(), key=lambda b: (b.detections, len(b.days)))
    records["most_faithful"] = {"common_name": faithful.name, "days": len(faithful.days),
                                "of": len(profiles)}
    records["most_heard"] = {"common_name": loudest.name, "detections": loudest.detections}
    return records


def _growth(profiles: list[DayProfile], reliable: dict[str, _Bird]) -> dict:
    """The life list of well-supported species, accumulating day by day."""
    firsts = sorted((b.days[0], b.first_at, b.name) for b in reliable.values())
    points, j = [], 0
    for profile in profiles:
        while j < len(firsts) and firsts[j][0] <= profile.day:
            j += 1
        points.append({"day": profile.day, "total": j})
    milestones = [{"count": m, "day": firsts[m - 1][0], "common_name": firsts[m - 1][2]}
                  for m in MILESTONES if m <= len(firsts)]
    return {"points": points, "milestones": milestones}


def _chronicle(days: list[str], reliable: dict[str, _Bird], growth: dict,
               records: dict) -> list[dict]:
    """The season's dated events, newest first."""
    founding_end = days[min(FOUNDING_DAYS, len(days)) - 1]
    founders = sum(1 for b in reliable.values() if b.days[0] <= founding_end)
    events = [{"day": days[0], "kind": "start", "title": "The journal begins",
               "detail": f"{founders} well-supported species in the first "
                         f"{min(FOUNDING_DAYS, len(days))} days of listening."}]
    for bird in reliable.values():
        heard = len(bird.days)
        if bird.status == "arrived":
            events.append({"day": bird.days[0], "kind": "arrival", "species": bird.name,
                           "title": f"{bird.name} arrives",
                           "detail": f"Heard on {_heard_on(heard, bird.observed)} since."})
        elif bird.status == "passage":
            events.append({"day": bird.days[0], "kind": "passage", "species": bird.name,
                           "title": f"{bird.name} passes through",
                           "detail": f"Heard on {heard} days between "
                                     f"{_between(bird.days[0], bird.days[-1])}."})
        elif bird.days[0] > founding_end:
            events.append({"day": bird.days[0], "kind": "first", "species": bird.name,
                           "title": f"First {bird.name}",
                           "detail": "New to the window's life list."})
        if bird.status == "departed":
            events.append({"day": bird.days[-1], "kind": "departure", "species": bird.name,
                           "title": f"Last {bird.name}",
                           "detail": f"Heard on {heard} days until then; not in the "
                                     f"{bird.quiet_for} listening days since."})
        for spell in bird.spells:
            events.append({"day": spell["to"], "kind": "return", "species": bird.name,
                           "title": f"{bird.name} heard again",
                           "detail": f"After {spell['days']} silent listening days, "
                                     f"since {_long(spell['from'])}."})
    for stone in growth["milestones"]:
        if stone["day"] > founding_end:
            events.append({"day": stone["day"], "kind": "milestone", "species": stone["common_name"],
                           "title": f"{stone['count']} species",
                           "detail": f"{stone['common_name']} became the "
                                     f"{_ordinal(stone['count'])} species on the life list."})
    if "richest_day" in records:
        rich = records["richest_day"]
        events.append({"day": rich["day"], "kind": "record", "title": "The richest day",
                       "detail": f"{rich['species']} well-supported species in one day."})
    order = {kind: i for i, kind in enumerate(
        ("record", "milestone", "arrival", "first", "passage", "return", "departure", "start"))}
    events.sort(key=lambda e: (e["day"], -order[e["kind"]]), reverse=True)
    return events


def _story(days: list[str], complete: list[DayProfile], birds: dict[str, _Bird],
           reliable: dict[str, _Bird], light: dict | None, trends: dict | None,
           visitors: dict) -> list[str]:
    """The season in a few plain paragraphs, strongest facts first: an
    opening line, then the comings and goings, the light, and lately."""
    doubtful = sum(1 for b in birds.values() if b.tier == "tentative")
    opening = (f"Since {_long(days[0])}, {len(days)} {'day' if len(days) == 1 else 'days'} "
               f"of listening {'has' if len(days) == 1 else 'have'} found {len(reliable)} "
               f"well-supported species"
               + (f", and {doubtful} more too doubtful to count." if doubtful else "."))
    if len(complete) < 2 * MIN_SILENCE:
        return [opening, "Arrivals, departures and the shifting dawn need a few weeks of "
                         "listening to show; this page fills in as the season turns."]

    def by(status: str) -> list[_Bird]:
        return [b for b in reliable.values() if b.status == status]

    movement, light_lines, lately = [], [], []
    departed = by("departed")
    # The regulars' silences say most; told in the order they fell quiet.
    gone = sorted(sorted(departed, key=lambda b: -len(b.days))[:3], key=lambda b: b.days[-1])
    if gone:
        lead = f"Of the {len(departed)} species gone quiet, " if len(departed) > len(gone) else ""
        movement.append(lead + _join(
            [f"{gone[0].name} has not been heard since {_long(gone[0].days[-1])}"]
            + [f"{b.name} since {_long(b.days[-1])}" for b in gone[1:]]) + ".")
    new = sorted(by("arrived"), key=lambda b: b.days[0])
    if len(new) == 1:
        b = new[0]
        movement.append(f"{b.name} arrived on {_long(b.days[0])} and has been heard on "
                        f"{_heard_on(len(b.days), b.observed)} since.")
    elif new:
        movement.append("New this season: " + _join(
            [f"{b.name} from {_long(b.days[0])}" for b in new[:4]]) + ".")
    passing = sorted(by("passage"), key=lambda b: b.days[0])
    if passing:
        movement.append(_join([f"{b.name} passed through between "
                               f"{_between(b.days[0], b.days[-1])}" for b in passing[:2]]) + ".")
    spells = sorted(((s, b) for b in reliable.values() for s in b.spells),
                    key=lambda item: -item[0]["days"])
    if spells:
        spell, b = spells[0]
        movement.append(f"{b.name} fell silent for {spell['days']} listening days after "
                        f"{_long(spell['from'])}, and was heard again on {_long(spell['to'])}.")
    if light and light["mornings"] >= 2 * MIN_SILENCE:
        start, now = light["start"], light["now"]
        if abs((now["sunrise"] or 0) - (start["sunrise"] or 0)) >= 20:
            light_lines.append(
                f"Sunrise has moved from {_clock(start['sunrise'])} to {_clock(now['sunrise'])}, "
                f"and the first voice of the morning with it, from {_clock(start['first'])} "
                f"to {_clock(now['first'])}.")
        offset = light["offset"]
        light_lines.append("The first voice usually comes "
                           + (f"{_duration(offset)} {'before' if offset < 0 else 'after'} sunrise."
                              if abs(offset) >= 5 else "with the sunrise."))
    if trends and (trends["rising"] or trends["falling"]):
        up = trends["rising"][0] if trends["rising"] else None
        down = trends["falling"][0] if trends["falling"] else None
        first = up or down
        sentence = (f"Over the last {trends['recent_days']} days, {first['common_name']} has been "
                    f"heard {_times(first)} a day as before")
        if up and down:
            sentence += f", and {down['common_name']} only {_times(down)}"
        lately.append(sentence + ".")
    mentioned = {b.name for b in gone + new[:4] + passing[:2]}
    surprise = next((v for v in visitors["notable"] if v["common_name"] not in mentioned
                     and v["geo"] < UNCOMMON_GEO), None)
    if surprise:
        lately.append(f"The least expected visitor: {surprise['common_name']}, "
                      f"{surprise['rarity']}, heard on "
                      + (f"{_long(surprise['first'])}." if surprise["days"] == 1
                         else f"{surprise['days']} days."))
    return [opening] + [" ".join(lines) for lines in (movement, light_lines, lately) if lines]


def _empty(today: str) -> dict:
    return {"today": today, "since": None, "until": None, "listening_days": 0,
            "story": [], "counts": {}, "weeks": [], "species": [], "light": None,
            "clock": [], "night": {"species": [], "weekly": []}, "trends": None,
            "visitors": {"notable": [], "doubtful": [], "doubtful_total": 0},
            "records": {}, "growth": {"points": [], "milestones": []}, "chronicle": [],
            "methods": _methods()}


def _methods() -> dict:
    return {"silence_chance": SILENCE_CHANCE, "min_silence": MIN_SILENCE,
            "min_spell": MIN_SPELL, "min_days": MIN_DAYS, "brief_days": BRIEF_DAYS,
            "resident_share": RESIDENT_SHARE, "dawn_window": DAWN_WINDOW,
            "dusk_window": DUSK_WINDOW, "recent_days": RECENT_DAYS,
            "trend_ratio": TREND_RATIO}


def analyse(profiles: list[DayProfile], today: date, geo_lookup: dict | None = None) -> dict:
    """The season's story from day profiles (see the module docstring)."""
    geo_lookup = geo_lookup or {}
    profiles = sorted((p for p in profiles if p.species), key=lambda p: p.day)
    if not profiles:
        return _empty(today.isoformat())
    days = [p.day for p in profiles]
    today_open = days[-1] == today.isoformat()
    complete = profiles[:-1] if today_open else profiles

    birds = _roster(profiles, geo_lookup)
    _classify(birds, days, today_open)
    reliable = {name: b for name, b in birds.items() if b.tier in ("confirmed", "probable")}
    # Dawn and dusk are timed by the birds that keep the sun's hours.
    chorus = {name: b for name, b in reliable.items() if not b.nocturnal}
    weeks, presence, volume, slot_of = _weeks(profiles, reliable)
    light_days = _light(complete, chorus)
    light = _light_summary(light_days)
    trends = _trends(complete, reliable, weeks, volume)
    visitors = _visitors(birds, have_geo=bool(geo_lookup), young=len(complete) < 2 * MIN_SILENCE)
    records = _records(profiles, light_days, reliable)
    growth = _growth(profiles, reliable)

    order = {status: i for i, status in enumerate(STATUS_ORDER)}
    within = {"departed": lambda b: (b.days[-1], b.name),
              "passage": lambda b: (b.days[0], b.name),
              "arrived": lambda b: (b.days[0], b.name),
              "resident": lambda b: (-b.detections, b.name),
              "occasional": lambda b: (-len(b.days), b.name),
              "brief": lambda b: (b.days[0], b.name)}
    chart = sorted(reliable.values(), key=lambda b: (order[b.status], within[b.status](b)))
    counts = {status: sum(b.status == status for b in reliable.values()) for status in STATUS_ORDER}
    counts.update(species=len(reliable),
                  doubtful=sum(b.tier == "tentative" for b in birds.values()))
    return {
        "today": today.isoformat(), "since": days[0], "until": days[-1],
        "listening_days": len(days),
        "story": _story(days, complete, birds, reliable, light, trends, visitors),
        "counts": counts,
        "weeks": weeks,
        "species": [_bird_item(b, status=b.status, share=round(len(b.days) / len(days), 3),
                               quiet_for=b.quiet_for, observed=b.observed, silences=b.spells,
                               presence=presence[b.name], volume=volume[b.name])
                    for b in chart],
        "light": None if light is None else {**light, "days": light_days,
                                             "roster": _dawn_roster(complete, chorus)},
        "clock": [{"day": p.day, "q": list(p.quarters), "sunrise": p.sun.sunrise,
                   "sunset": p.sun.sunset} for p in profiles],
        "night": _night(profiles, reliable, slot_of, len(weeks)),
        "trends": trends,
        "visitors": visitors,
        "records": records,
        "growth": growth,
        "chronicle": _chronicle(days, reliable, growth, records),
        "methods": _methods(),
    }
