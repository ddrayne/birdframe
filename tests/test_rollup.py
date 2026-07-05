from datetime import datetime

from birdframe.store import SpeciesDay
from birdframe.rollup import build_scene, season_for, build_prompt
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
    assert build_prompt(style, "a wren") == "Paint a wren."
