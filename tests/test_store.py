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
