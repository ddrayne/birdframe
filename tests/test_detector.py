import numpy as np
from datetime import datetime

from birdframe.detector import Detector, parse_species_name, filter_detections, week_of_year


def test_parse_species_name():
    sci, common = parse_species_name("Erithacus rubecula_European Robin")
    assert sci == "Erithacus rubecula"
    assert common == "European Robin"


def test_week_of_year_in_range():
    assert 1 <= week_of_year(datetime(2026, 1, 1)) <= 48
    assert 1 <= week_of_year(datetime(2026, 12, 31)) <= 48
    assert week_of_year(datetime(2026, 7, 5)) == 25


def test_filter_detections_applies_confidence_and_whitelist():
    raw = [
        ("Erithacus rubecula_European Robin", 0.91),
        ("Turdus merula_Common Blackbird", 0.40),   # below threshold
        ("Ara macao_Scarlet Macaw", 0.99),          # not on whitelist
    ]
    whitelist = {"Erithacus rubecula_European Robin", "Turdus merula_Common Blackbird"}
    when = datetime(2026, 7, 5, 6)
    dets = filter_detections(raw, whitelist, threshold=0.55, when=when)
    assert len(dets) == 1
    assert dets[0].common_name == "European Robin"
    assert dets[0].timestamp == when


def test_blocklist_vetoes_species():
    raw = [
        ("Erithacus rubecula_European Robin", 0.9),
        ("Podiceps cristatus_Great Crested Grebe", 0.87),   # confident but vetoed
    ]
    whitelist = {"Erithacus rubecula_European Robin", "Podiceps cristatus_Great Crested Grebe"}
    dets = filter_detections(raw, whitelist, threshold=0.5, when=datetime(2026, 7, 5, 6),
                             blocklist={"Great Crested Grebe"})
    assert [d.common_name for d in dets] == ["European Robin"]


def test_predict_chunk_uses_model(mocker):
    det = Detector.__new__(Detector)          # bypass __init__ (no real model)
    det.threshold = 0.55
    det.blocklist = set()
    det.whitelist = {"Erithacus rubecula_European Robin"}
    fake_result = mocker.Mock()
    fake_result.to_structured_array.return_value = [
        {"species_name": "Erithacus rubecula_European Robin", "confidence": 0.8},
    ]
    det._acoustic = mocker.Mock()
    det._acoustic.predict_arrays.return_value = fake_result
    det._extract = Detector._extract.__get__(det)
    out = det.predict_chunk(np.zeros(48000, dtype=np.float32), 48000, datetime(2026, 7, 5, 6))
    assert out[0].common_name == "European Robin"
    det._acoustic.predict_arrays.assert_called_once()
