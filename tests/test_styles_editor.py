import pytest

from birdframe.styles import (
    slugify, save_style, delete_style, get_style, load_styles, style_to_markdown, Style,
)


def test_slugify():
    assert slugify("Art Nouveau!") == "art-nouveau"
    assert slugify("  Ukiyo-e  ") == "ukiyo-e"
    assert slugify("") == ""


def test_save_and_reload_roundtrip(tmp_path):
    slug = save_style(tmp_path, "My Bold Style", "A bold print of {scene}.", "gradients, text")
    assert slug == "my-bold-style"
    reloaded = get_style(tmp_path, "my-bold-style")
    assert reloaded.prompt == "A bold print of {scene}."
    assert "gradients" in reloaded.avoid
    assert load_styles(tmp_path)[0].name == "my-bold-style"


def test_save_requires_scene_placeholder(tmp_path):
    with pytest.raises(ValueError):
        save_style(tmp_path, "bad", "no placeholder here")


def test_save_rejects_empty_name(tmp_path):
    with pytest.raises(ValueError):
        save_style(tmp_path, "!!!", "of {scene}")


def test_overwrite_existing(tmp_path):
    save_style(tmp_path, "s", "first {scene}")
    save_style(tmp_path, "s", "second {scene}")
    assert get_style(tmp_path, "s").prompt == "second {scene}"
    assert len(load_styles(tmp_path)) == 1


def test_delete_style(tmp_path):
    save_style(tmp_path, "temp", "of {scene}")
    assert delete_style(tmp_path, "temp") is True
    assert get_style(tmp_path, "temp") is None
    assert delete_style(tmp_path, "temp") is False


def test_markdown_omits_empty_avoid():
    md = style_to_markdown(Style("x", "of {scene}", ""))
    assert "## Avoid" not in md
    assert "## Prompt" in md
