from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from birdframe import seasons
from birdframe.seasons import DayProfile, Heard, SeasonArchive, Sun, analyse, fold_day, sun_for
from birdframe.store import Detection, Store

LONDON = ZoneInfo("Europe/London")
START = date(2026, 7, 6)
# A plain Edinburgh-ish day: night until 02:40, dawn window from then.
SUN = Sun(dawn=220.0, sunrise=280.0, sunset=1310.0, dusk=1370.0)


def _day(i: int) -> str:
    return (START + timedelta(days=i)).isoformat()


def _heard(n=20, best=0.9, morning=None, evening=None, night=0, sci="Sci name"):
    return Heard(scientific_name=sci, detections=n, best=best, first="05:00:00",
                 last="20:00:00", morning=morning, evening=evening, night=night)


def _season(plan: dict[str, set[int]], days: int, **heard) -> list[DayProfile]:
    """Profiles for `days` listening days; plan maps species to the day
    indexes it was heard on."""
    profiles = []
    for i in range(days):
        species = {name: _heard(**heard) for name, on in plan.items() if i in on}
        if species:
            profiles.append(DayProfile(_day(i), tuple([1] * 96), species, SUN))
    return profiles


def _status(result: dict) -> dict[str, str]:
    return {s["common_name"]: s["status"] for s in result["species"]}


def test_sun_times_match_edinburgh_almanac():
    midsummer = sun_for(date(2026, 7, 5), 55.95, -3.19, LONDON)
    autumn = sun_for(date(2026, 9, 30), 55.95, -3.19, LONDON)
    # 04:35 / 21:58 BST and 07:13 / 18:50 BST, to the minute or two
    assert abs(midsummer.sunrise - (4 * 60 + 35)) <= 2
    assert abs(midsummer.sunset - (21 * 60 + 58)) <= 2
    assert abs(autumn.sunrise - (7 * 60 + 13)) <= 2
    assert abs(autumn.sunset - (18 * 60 + 50)) <= 2
    assert midsummer.dawn < midsummer.sunrise < midsummer.sunset < midsummer.dusk


def test_sun_times_follow_the_clocks_changing():
    before = sun_for(date(2026, 10, 24), 55.95, -3.19, LONDON)
    after = sun_for(date(2026, 10, 26), 55.95, -3.19, LONDON)
    assert 50 <= before.sunrise - after.sunrise <= 62     # BST ends: sunrise jumps an hour earlier


def test_polar_summer_has_no_night():
    svalbard = sun_for(date(2026, 6, 21), 78.2, 15.6, ZoneInfo("Europe/Oslo"))
    assert svalbard.sunrise is None and svalbard.sunset is None and svalbard.dusk is None
    assert seasons.night_hours(svalbard) == (None, None)


def _row(name, quarter, n, first, last=None, best=0.9):
    stamp = lambda hms: f"2026-07-06T{hms}"  # noqa: E731
    return {"common_name": name, "scientific_name": "Sci " + name, "quarter": quarter,
            "n": n, "best": best, "first": stamp(first), "last": stamp(last or first)}


def test_fold_day_finds_when_each_voice_gets_going():
    # Sunrise 04:40: the dawn window opens at 02:40.
    rows = [
        _row("Robin", 9, 1, "02:20:00"),             # a stray call at night
        _row("Robin", 13, 1, "03:16:00"),            # not yet busy
        _row("Robin", 14, 6, "03:31:10", "03:44:00"),  # gets going here…
        _row("Robin", 15, 12, "03:45:00", "03:59:00"),  # …and keeps going
        _row("Robin", 20, 30, "05:00:00", "05:14:00"),
        _row("Robin", 86, 5, "21:30:00", "21:44:00"),
        _row("Robin", 87, 4, "21:46:00", "21:59:30"),
        _row("Gull", 8, 9, "02:00:00", "02:14:00"),  # calling all night…
        _row("Gull", 12, 9, "03:00:00", "03:14:00"),
        _row("Gull", 24, 40, "06:00:00", "06:14:00"),
        _row("Wren", 13, 2, "03:20:00", "03:21:00"),  # two chance pairs, never
        _row("Wren", 18, 2, "04:30:00", "04:31:00"),  # two quarter-hours in a row
    ]
    day = fold_day("2026-07-06", rows, SUN)
    robin, gull, wren = day.species["Robin"], day.species["Gull"], day.species["Wren"]
    assert robin.detections == 59 and robin.first == "02:20:00" and robin.last == "21:59:30"
    assert robin.morning == 211.2                     # 03:31:10, not the 02:20 stray
    assert robin.evening == 1319.5                    # 21:59:30
    assert robin.night == 1                           # only the stray falls in the night
    assert gull.morning is None                       # already busy before dawn
    assert wren.morning is None                       # never got going in earnest
    assert sum(day.quarters) == 121 and day.quarters[14] == 6


def test_fold_day_without_a_sun_still_counts():
    day = fold_day("2026-07-06", [_row("Robin", 20, 5, "05:00:00")], Sun(None, None, None, None))
    assert day.species["Robin"].detections == 5
    assert day.species["Robin"].morning is None and day.species["Robin"].night == 0


def test_comings_and_goings_are_told_by_unlikely_silences():
    days = 60
    plan = {
        "Resident": set(range(days)),
        "Swift": set(range(0, 30)),                   # gone after day 29
        "Goose": set(range(40, days)),                # new from day 40
        "Whimbrel": {25, 26, 27, 28},                 # passing through
        "Jay": {12},                                  # a single visit
        "Sparrowhawk": {3, 21, 39, 57},               # now and then
        "Thrush": set(range(0, 10)) | set(range(35, days)),   # a long silent spell
        "Wobbly": set(range(days)) - set(range(40, 50)),  # ten days: not yet a spell
    }
    result = analyse(_season(plan, days), today=START + timedelta(days=days))
    status = _status(result)
    assert status == {
        "Resident": "resident", "Swift": "departed", "Goose": "arrived",
        "Whimbrel": "passage", "Jay": "brief", "Sparrowhawk": "occasional",
        "Thrush": "resident", "Wobbly": "resident"}
    swift = next(s for s in result["species"] if s["common_name"] == "Swift")
    assert swift["quiet_for"] == 30 and swift["last"] == _day(29)
    thrush = next(s for s in result["species"] if s["common_name"] == "Thrush")
    assert thrush["silences"] == [{"from": _day(9), "to": _day(35), "days": 25}]
    # The season chart reads through the season: leavers, passers-by, newcomers…
    order = [s["status"] for s in result["species"]]
    assert order == sorted(order, key=seasons.STATUS_ORDER.index)
    assert result["counts"]["departed"] == 1 and result["counts"]["species"] == 8


def test_a_short_silence_is_not_a_departure():
    plan = {"Swift": set(range(0, 30)), "Resident": set(range(36))}
    status = _status(analyse(_season(plan, 36), today=START + timedelta(days=36)))
    assert status["Swift"] == "resident"              # six quiet days: too soon to say


def test_today_is_never_counted_as_a_silent_day():
    plan = {"Swift": set(range(0, 30)), "Resident": set(range(37))}
    profiles = _season(plan, 37)                       # day 36 is today, under way
    still = _status(analyse(profiles, today=START + timedelta(days=36)))
    assert still["Swift"] == "resident"               # 6 finished silent days + today
    done = _status(analyse(profiles, today=START + timedelta(days=37)))
    assert done["Swift"] == "departed"                # today finished: 7 silent days


def test_doubtful_species_stay_out_of_the_story():
    profiles = _season({"Robin": set(range(30))}, 30)
    for i in (3, 9):
        profiles[i].species["Great Crested Grebe"] = _heard(n=1, best=0.62, sci="Podiceps cristatus")
    result = analyse(profiles, today=START + timedelta(days=30),
                     geo_lookup={"Sci name": 0.9, "Podiceps cristatus": 0.04})
    assert [s["common_name"] for s in result["species"]] == ["Robin"]
    assert result["counts"]["doubtful"] == 1
    doubtful = result["visitors"]["doubtful"]
    assert doubtful[0]["common_name"] == "Great Crested Grebe"
    assert "unusual for this area" in doubtful[0]["reasons"]
    assert all("Grebe" not in line for line in result["story"])


def test_notable_visitors_are_rare_or_brief_but_reliable():
    profiles = _season({"Robin": set(range(30)), "Nuthatch": {4}, "Crossbill": set(range(30))}, 30)
    for p in profiles:
        if "Crossbill" in p.species:
            p.species["Crossbill"] = _heard(sci="Loxia curvirostra")
    result = analyse(profiles, today=START + timedelta(days=30),
                     geo_lookup={"Sci name": 0.9, "Loxia curvirostra": 0.15})
    notable = {v["common_name"]: v["why"] for v in result["visitors"]["notable"]}
    assert notable == {"Crossbill": ["uncommon here"], "Nuthatch": ["heard on a single day"]}
    assert any("least expected visitor: Crossbill" in line for line in result["story"])


def test_a_young_record_calls_nothing_brief():
    # Five days in, a bird heard twice is simply not yet heard often.
    young = analyse(_season({"Robin": set(range(5)), "Coal Tit": {1, 3}}, 5),
                    today=START + timedelta(days=5), geo_lookup={"Sci name": 0.9})
    assert young["visitors"]["notable"] == []
    older = analyse(_season({"Robin": set(range(30)), "Coal Tit": {1, 3}}, 30),
                    today=START + timedelta(days=30), geo_lookup={"Sci name": 0.9})
    assert [v["common_name"] for v in older["visitors"]["notable"]] == ["Coal Tit"]


def _light_season(days=30, night_owl=True):
    profiles = []
    for i in range(days):
        sun = Sun(dawn=220.0 + i, sunrise=280.0 + i * 2, sunset=1310.0 - i * 2, dusk=1370.0 - i)
        species = {
            "Robin": _heard(morning=sun.sunrise - 60, evening=sun.sunset + 10),
            "Sparrow": _heard(morning=sun.sunrise + 5, evening=sun.sunset - 30),
        }
        if night_owl:   # heard mostly at night, so it never times the dawn
            species["Owl"] = _heard(n=10, night=9, morning=sun.sunrise - 110,
                                    evening=sun.sunset + 115)
        profiles.append(DayProfile(_day(i), tuple([1] * 96), species, sun))
    return profiles


def test_the_chorus_is_timed_against_the_sun_without_night_birds():
    result = analyse(_light_season(), today=START + timedelta(days=30))
    light = result["light"]
    assert light["offset"] == -60                      # the robin, an hour before sunrise
    assert light["evening_offset"] == 10
    assert light["start"]["sunrise"] == 286.0 and light["now"]["sunrise"] == 332.0
    assert [r["common_name"] for r in light["roster"]] == ["Robin", "Sparrow"]
    assert light["roster"][0]["median"] == -60 and light["roster"][1]["median"] == 5
    assert result["records"]["earliest_voice"] == {
        "day": _day(0), "at": "03:40", "common_name": "Robin"}
    night = result["night"]["species"]
    assert night[0]["common_name"] == "Owl" and night[0]["nocturnal"] is True
    assert any("1 h before sunrise" in line for line in result["story"])
    assert any("Sunrise has moved from 04:46 to 05:32" in line for line in result["story"])


def test_trends_compare_lately_with_before_and_weigh_volume():
    profiles = []
    for i in range(50):
        late = i >= 29
        profiles.append(DayProfile(_day(i), tuple([1] * 96), {
            "Robin": _heard(n=300 if late else 100),
            "Goldcrest": _heard(n=8 if late else 2),
            "Pigeon": _heard(n=60 if late else 150),
            "Wren": _heard(n=40),
        }, SUN))
    trends = analyse(profiles, today=START + timedelta(days=50))["trends"]
    assert trends["since"] == _day(29)
    assert [r["common_name"] for r in trends["rising"]] == ["Robin", "Goldcrest"]
    assert [r["common_name"] for r in trends["falling"]] == ["Pigeon"]
    robin = trends["rising"][0]
    assert (robin["earlier_rate"], robin["recent_rate"]) == (100.0, 300.0)
    assert robin["weekly"][-1] == 300.0
    assert seasons._times(robin) == "3.0 times as much"
    assert seasons._times(trends["falling"][0]) == "40% as much"


def test_records_growth_and_chronicle():
    plan = {"Robin": set(range(40)), "Wren": set(range(40)), "Jay": {20},
            "Goose": set(range(25, 40)), "Swift": set(range(0, 18))}
    result = analyse(_season(plan, 40), today=START + timedelta(days=40))
    growth = result["growth"]
    assert growth["points"][0] == {"day": _day(0), "total": 3}
    assert growth["points"][-1]["total"] == 5
    kinds = {(e["kind"], e.get("species")) for e in result["chronicle"]}
    assert {("arrival", "Goose"), ("departure", "Swift"), ("first", "Jay"),
            ("start", None), ("record", None)} <= kinds
    days = [e["day"] for e in result["chronicle"]]
    assert days == sorted(days, reverse=True)          # newest first
    assert result["records"]["most_faithful"] == {"common_name": "Robin", "days": 40, "of": 40}


def test_story_needs_a_few_weeks_before_it_tells_comings_and_goings():
    result = analyse(_season({"Robin": set(range(5))}, 5), today=START + timedelta(days=5))
    assert result["story"][0] == "Since 6 July, 5 days of listening have found 1 well-supported species."
    assert "few weeks" in result["story"][1]
    assert result["trends"] is None


def test_an_empty_archive_is_an_empty_story():
    result = analyse([], today=START)
    assert result["species"] == [] and result["story"] == [] and result["listening_days"] == 0


def test_season_archive_rereads_only_days_that_can_still_change(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    robin = ("Erithacus rubecula", "European Robin")
    for day in (1, 2, 4, 5):                          # nothing heard on the 3rd
        store.add_detection(Detection(datetime(2026, 7, day, 6), *robin, 0.9))
    reads = []
    real = store.day_profile
    store.day_profile = lambda day: reads.append(day) or real(day)
    archive = SeasonArchive(store, 55.95, -3.19, LONDON)
    today = date(2026, 7, 5)
    assert [p.day for p in archive.profiles(today)] == [
        "2026-07-01", "2026-07-02", "2026-07-04", "2026-07-05"]
    assert len(reads) == 5                            # every calendar day, once
    reads.clear()
    archive.profiles(today)
    assert reads == ["2026-07-04", "2026-07-05"]      # yesterday and today only
    archive.clear()
    reads.clear()
    archive.profiles(today)
    assert len(reads) == 5
    assert SeasonArchive(Store(tmp_path / "empty.sqlite"), 55.95, -3.19).profiles(today) == []
