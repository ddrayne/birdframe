from birdframe.styles import load_styles, choose_style, DEFAULT_STYLES_DIR


def _write(dir, name, prompt, avoid=""):
    body = f"# {name}\n\n## Prompt\n{prompt}\n"
    if avoid:
        body += f"\n## Avoid\n{avoid}\n"
    (dir / f"{name}.md").write_text(body)


def test_load_styles(tmp_path):
    _write(tmp_path, "ukiyo-e", "A woodblock print of {scene}.", "gradients")
    styles = load_styles(tmp_path)
    assert styles[0].name == "ukiyo-e"
    assert "{scene}" in styles[0].prompt
    assert "gradients" in styles[0].avoid


def test_choose_style_rotates_by_day_index(tmp_path):
    _write(tmp_path, "a", "x")
    _write(tmp_path, "b", "y")
    styles = load_styles(tmp_path)   # sorted by name: a, b
    assert choose_style(styles, mode="rotate", day_index=0).name == "a"
    assert choose_style(styles, mode="rotate", day_index=1).name == "b"
    assert choose_style(styles, mode="rotate", day_index=2).name == "a"


def test_choose_style_pinned(tmp_path):
    _write(tmp_path, "a", "x")
    _write(tmp_path, "b", "y")
    styles = load_styles(tmp_path)
    assert choose_style(styles, mode="pinned", pinned="b").name == "b"


def test_shipped_styles_are_valid():
    styles = load_styles(DEFAULT_STYLES_DIR)
    assert len(styles) == 6
    for s in styles:
        assert "{scene}" in s.prompt
        assert s.avoid  # every shipped style lists things to avoid
