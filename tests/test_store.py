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


def test_life_list_has_time_of_day_and_peak(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(datetime(2026, 7, 5, 5, 2), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(datetime(2026, 7, 5, 5, 40), "Erithacus rubecula", "European Robin", 0.8))
    s.add_detection(Detection(datetime(2026, 7, 5, 20, 10), "Erithacus rubecula", "European Robin", 0.7))
    r = s.life_list()[0]
    assert r["earliest"] == "05:02" and r["latest"] == "20:10"
    assert r["peak_hour"] == 5      # 2 of 3 detections in the 05:00 hour


def test_species_detail_and_activity_matrix(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    for h in (5, 5, 6, 21):
        s.add_detection(Detection(datetime(2026, 7, 5, h, 0), "Turdus merula", "Common Blackbird", 0.9))
    s.add_detection(Detection(datetime(2026, 7, 6, 5, 0), "Turdus merula", "Common Blackbird", 0.8))
    d = s.species_detail("Common Blackbird")
    assert d["total"] == 5 and d["days"] == 2
    assert d["hours"][5] == 3 and d["hours"][21] == 1
    assert d["earliest"] == "05:00" and d["latest"] == "21:00"
    assert [x["day"] for x in d["daily"]] == ["2026-07-05", "2026-07-06"]
    assert s.species_detail("Nonexistent Bird") is None
    m = s.activity_matrix(days=14)
    assert {x["day"] for x in m} == {"2026-07-05", "2026-07-06"}
    assert m[0]["hours"][5] == 2      # day 5 had two 05:00 detections
    assert m[1]["hours"][5] == 1      # day 6 had one


def test_best_clip_for_species(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    assert s.best_clip_for_species("European Robin") is None
    s.upsert_clip("2026-07-05", "European Robin", "Erithacus rubecula", 0.7, "/d5.ogg", _dt(6))
    s.upsert_clip("2026-07-06", "European Robin", "Erithacus rubecula", 0.95, "/d6.ogg", _dt(6))
    best = s.best_clip_for_species("European Robin")
    assert best["path"] == "/d6.ogg" and best["confidence"] == 0.95   # clearest across days
    assert s.species_with_any_clip() == {"European Robin"}


def test_species_dossier_keeps_raw_rows_and_builds_longitudinal_views(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    # Robin and blackbird share two 15-minute soundscape windows.
    for when, confidence in [
        (datetime(2026, 7, 5, 5, 2), 0.8),
        (datetime(2026, 7, 5, 5, 8), 0.9),
        (datetime(2026, 7, 6, 6, 1), 0.7),
    ]:
        s.add_detection(Detection(when, "Erithacus rubecula", "European Robin", confidence))
    s.add_detection(Detection(datetime(2026, 7, 5, 5, 10), "Turdus merula", "Eurasian Blackbird", 0.95))
    s.add_detection(Detection(datetime(2026, 7, 6, 6, 12), "Turdus merula", "Eurasian Blackbird", 0.92))

    d = s.species_dossier("European Robin")
    assert d["total"] == 3 and d["days"] == 2
    assert d["daily"][0]["detections"] == 2
    assert d["hours"][5] == 2 and sum(d["confidence_histogram"]) == 3
    assert d["companions"][0]["common_name"] == "Eurasian Blackbird"
    assert d["companions"][0]["shared_windows"] == 2
    assert len(s.species_observations("European Robin", limit=2)) == 2

    recent = s.species_dossier("European Robin", start_day="2026-07-06")
    assert recent["total"] == 1 and recent["first_day"] == "2026-07-06"


def test_journal_day_and_pattern_aggregates(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    s.add_detection(Detection(datetime(2026, 7, 5, 5, 2), "Erithacus rubecula", "European Robin", 0.9))
    s.add_detection(Detection(datetime(2026, 7, 5, 5, 18), "Turdus merula", "Eurasian Blackbird", 0.8))
    s.add_detection(Detection(datetime(2026, 7, 6, 8, 4), "Erithacus rubecula", "European Robin", 0.85))

    journal = s.journal_days()
    assert [d["day"] for d in journal] == ["2026-07-06", "2026-07-05"]
    assert journal[1]["new_species"] == ["Eurasian Blackbird", "European Robin"]
    detail = s.day_detail("2026-07-05")
    assert detail["detections"] == 2 and detail["species_count"] == 2
    assert detail["quarters"][5 * 4] == 1 and detail["quarters"][5 * 4 + 1] == 1
    assert detail["hour_species"][5]["species_count"] == 2
    assert detail["quarter_species"][5 * 4]["species"][0]["common_name"] == "European Robin"

    robin_only = s.pattern_summary(species_names=["European Robin"])
    assert robin_only["totals"]["detections"] == 2
    assert robin_only["by_species"][0]["common_name"] == "European Robin"
    assert robin_only["by_species"][0]["hours"][5] == 1
    assert robin_only["hour_species"][5]["species"][0]["common_name"] == "European Robin"
    assert len(robin_only["heatmap"]) == 2
    assert robin_only["heatmap"][0]["species"][5]["species_count"] == 1
