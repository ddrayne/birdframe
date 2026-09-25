from datetime import datetime

from birdframe.store import SpeciesDay
from birdframe.rollup import (
    build_art_profile, build_scene, season_for, build_prompt, profile_to_dict,
)
from birdframe.styles import Style


def _sd(name, count, first_h, last_h, best=0.9):
    return SpeciesDay(name, name.lower(), count, datetime(2026, 7, 5, first_h),
                      datetime(2026, 7, 5, last_h), first_h, best)


def test_season_for_northern_hemisphere():
    assert season_for(datetime(2026, 1, 15)) == "winter"
    assert season_for(datetime(2026, 7, 5)) == "summer"
    assert season_for(datetime(2026, 10, 20)) == "autumn"


def test_build_scene_mentions_top_species_and_dawn_and_weather():
    species = [_sd("European Robin", 47, 5, 20), _sd("Common Blackbird", 12, 4, 21)]
    scene = build_scene(species, first_ever={"European Robin"},
                        weather="light rain", when=datetime(2026, 7, 5, 21))
    assert "Edinburgh" in scene
    assert "European Robin" in scene
    assert "light rain" in scene
    assert "summer" in scene
    assert scene.index("European Robin") < scene.index("Common Blackbird")


def test_build_scene_handles_no_birds():
    scene = build_scene([], first_ever=set(), weather="clear", when=datetime(2026, 7, 5, 21))
    assert "quiet" in scene.lower()


def test_build_prompt_fills_placeholder_and_appends_avoid():
    style = Style("ukiyo-e", "A woodblock print of {scene}.", "gradients")
    prompt = build_prompt(style, "an Edinburgh garden with a robin")
    assert prompt.startswith("A woodblock print of an Edinburgh garden with a robin.")
    assert "Avoid: gradients" in prompt


def test_build_prompt_without_avoid():
    style = Style("plain", "Paint {scene}.", "")
    prompt = build_prompt(style, "a wren")
    assert prompt.startswith("Paint a wren.")
    assert "accurately" in prompt          # plumage-accuracy guidance always appended
    assert "Avoid:" not in prompt


def test_art_profile_turns_rhythm_into_an_explainable_fingerprint():
    species = [_sd("Robin", 12, 5, 8), _sd("Blackbird", 10, 5, 9),
               _sd("Wren", 9, 6, 10), _sd("Blue Tit", 8, 7, 11)]
    hours = [0] * 24
    hours[5:9] = [8, 11, 10, 6]
    profile = build_art_profile(
        species, hours, {"Wren"}, "light rain", datetime(2026, 4, 12, 21))
    assert profile.archetype == "Dawn chorus"
    assert {"spring", "rain", "dawn-heavy", "first-arrival", "even-chorus"} <= set(profile.tags)
    assert profile.detection_count == 39
    assert profile.active_span_hours == 4
    assert profile_to_dict(profile)["hours"][5] == 8
    scene = build_scene(species, {"Wren"}, "light rain",
                        datetime(2026, 4, 12, 21), profile)
    assert "visual rhythm" in scene
    assert "never into a literal number" in scene


def _named(name, sci, count, first_h, last_h):
    return SpeciesDay(name, sci, count, datetime(2026, 9, 24, first_h),
                      datetime(2026, 9, 24, last_h), first_h, 0.9)


def test_scene_carries_no_numbers_for_the_painter_to_letter_or_count():
    import re
    species = [_named("European Robin", "Erithacus rubecula", 312, 5, 21),
               _named("Eurasian Blackbird", "Turdus merula", 120, 4, 20),
               _named("Eurasian Wren", "Troglodytes troglodytes", 81, 6, 19)]
    hours = [0] * 24
    hours[4:10] = [20, 60, 90, 70, 40, 30]
    when = datetime(2026, 9, 24, 21)
    profile = build_art_profile(species, hours, set(), "light rain", when)
    scene = build_scene(species, set(), "light rain", when, profile)
    assert not re.search(r"\d", scene)
    assert "European Robin (Erithacus rubecula)" in scene       # species pinned down
    assert "an autumn dusk in light rain" in scene
    assert "a dawn chorus" in scene


def test_scene_weather_reads_naturally_for_sky_and_precipitation():
    robin = [_named("European Robin", "Erithacus rubecula", 3, 6, 7)]
    assert "under partly cloudy skies" in build_scene(
        robin, set(), "partly cloudy", datetime(2026, 7, 5, 10))
    assert "in heavy drizzle" in build_scene(
        robin, set(), "heavy drizzle", datetime(2026, 7, 5, 10))


def test_prompt_asks_for_true_relative_sizes_and_frame_legibility():
    prompt = build_prompt(Style("plain", "Paint {scene}.", ""), "a wren")
    assert "sizes true to one another" in prompt
    assert "e-ink" in prompt
