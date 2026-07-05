from datetime import datetime

from birdframe.store import Store, Detection


def _dt(h, m=0):
    return datetime(2026, 7, 5, h, m, 0)


def test_add_and_count_species_for_day(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(_dt(5, 2), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(_dt(6, 0), "Erithacus rubecula", "European Robin", 0.7))
    s.add_detection(Detection(_dt(7, 0), "Turdus merula", "Common Blackbird", 0.8))
    rows = s.species_for_day(datetime(2026, 7, 5, 12))
    by_name = {r.common_name: r for r in rows}
    assert by_name["European Robin"].count == 2
    assert by_name["European Robin"].first_heard == _dt(5, 2)
    assert by_name["European Robin"].best_confidence == 0.9
    assert rows[0].common_name == "European Robin"


def test_first_ever_species(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(datetime(2026, 6, 1, 8), "Turdus merula", "Common Blackbird", 0.8))
    s.add_detection(Detection(_dt(7), "Turdus merula", "Common Blackbird", 0.8))
    s.add_detection(Detection(_dt(8), "Erithacus rubecula", "European Robin", 0.8))
    first_ever = s.first_ever_on_day(datetime(2026, 7, 5, 12))
    assert first_ever == {"European Robin"}


def test_min_confidence_filters_false_positives(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    # a confident robin, and a single low-confidence "grebe" (likely a false positive)
    s.add_detection(Detection(_dt(6), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(_dt(7), "Podiceps cristatus", "Great Crested Grebe", 0.52))
    all_species = {sp.common_name for sp in s.species_for_day(_dt(12))}
    assert "Great Crested Grebe" in all_species          # kept in the raw data
    filtered = {sp.common_name for sp in s.species_for_day(_dt(12), min_confidence=0.65)}
    assert filtered == {"European Robin"}                 # grebe dropped from the report
    feed = s.recent_detections(min_confidence=0.65)
    assert all(d.common_name == "European Robin" for d in feed)


def test_clip_upsert_keeps_best_and_serves_path(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    assert s.best_clip_confidence("2026-07-05", "European Robin") is None
    s.upsert_clip("2026-07-05", "European Robin", "Erithacus rubecula", 0.7, "/a.ogg", _dt(6))
    assert s.best_clip_confidence("2026-07-05", "European Robin") == 0.7
    s.upsert_clip("2026-07-05", "European Robin", "Erithacus rubecula", 0.9, "/b.ogg", _dt(7))
    assert s.best_clip_confidence("2026-07-05", "European Robin") == 0.9
    assert s.clip_path("2026-07-05", "European Robin") == "/b.ogg"   # upgraded to the better clip
    assert s.species_with_clips("2026-07-05") == {"European Robin"}


def test_first_ever_flag(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    assert s.first_ever("European Robin") is True
    s.add_detection(Detection(_dt(6), "Erithacus rubecula", "European Robin", 0.9))
    assert s.first_ever("European Robin") is False


def test_recent_detections_newest_first(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(_dt(5), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(_dt(7), "Turdus merula", "Common Blackbird", 0.8))
    s.add_detection(Detection(_dt(6), "Troglodytes troglodytes", "Eurasian Wren", 0.7))
    recent = s.recent_detections(limit=2)
    assert [d.common_name for d in recent] == ["Common Blackbird", "Eurasian Wren"]
    assert recent[0].confidence == 0.8


def test_species_in_window(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(_dt(5), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(_dt(9), "Turdus merula", "Common Blackbird", 0.8))
    s.add_detection(Detection(_dt(9, 30), "Turdus merula", "Common Blackbird", 0.6))
    window = s.species_in_window(_dt(8), _dt(10))
    assert len(window) == 1
    assert window[0].common_name == "Common Blackbird"
    assert window[0].count == 2


def test_image_record_roundtrip(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    img_id = s.add_image(datetime(2026, 7, 5, 21), "/tmp/x.png", "ukiyo-e", "a prompt", ["European Robin"])
    img = s.get_image(img_id)
    assert img.path == "/tmp/x.png"
    assert img.style == "ukiyo-e"
    assert img.species == ["European Robin"]
    assert img.posted_at is None
    s.mark_posted(img_id, datetime(2026, 7, 5, 21, 1))
    assert s.get_image(img_id).posted_at == datetime(2026, 7, 5, 21, 1)
