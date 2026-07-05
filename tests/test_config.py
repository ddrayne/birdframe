from birdframe.config import Config


def test_defaults_loaded_when_file_missing(tmp_path):
    cfg = Config.load(tmp_path / "config.toml")
    assert cfg.latitude == 55.95
    assert cfg.longitude == -3.19
    assert cfg.confidence_threshold == 0.55
    assert cfg.post_mode == "daily"
    assert cfg.post_time == "21:00"
    assert cfg.frame_url == "http://pi-inky-impression.local:5000"


def test_roundtrip_save_and_load(tmp_path):
    path = tmp_path / "config.toml"
    cfg = Config.load(path)
    cfg.confidence_threshold = 0.7
    cfg.post_mode = "manual"
    cfg.save()
    reloaded = Config.load(path)
    assert reloaded.confidence_threshold == 0.7
    assert reloaded.post_mode == "manual"


def test_list_field_roundtrips(tmp_path):
    # blocked_species is a list; tomlkit-wrapped values must save cleanly
    path = tmp_path / "config.toml"
    cfg = Config.load(path)
    cfg.blocked_species = ["Great Crested Grebe", "Mallard"]
    cfg.save()
    reloaded = Config.load(path)
    assert reloaded.blocked_species == ["Great Crested Grebe", "Mallard"]
    reloaded.save()  # must not raise on a tomlkit-loaded list
    assert Config.load(path).blocked_species == ["Great Crested Grebe", "Mallard"]


def test_unknown_keys_ignored_and_partial_file_merges_defaults(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('confidence_threshold = 0.42\nbogus_key = 1\n')
    cfg = Config.load(path)
    assert cfg.confidence_threshold == 0.42
    assert cfg.post_time == "21:00"  # default filled in
