from birdframe.reliability import assess, is_reliable


def test_clear_common_repeated_is_confirmed():
    a = assess(best_confidence=0.98, geo_plausibility=0.97, count=10)  # blackbird
    assert a.tier == "confirmed"
    assert a.score >= 0.9
    assert is_reliable(a)


def test_confident_but_implausible_is_tentative():
    # Great crested grebe: acoustically confident, but very unlikely in a garden.
    a = assess(best_confidence=0.87, geo_plausibility=0.048, count=3)
    assert a.tier == "tentative"
    assert "unusual for this area" in a.reasons
    assert not is_reliable(a)


def test_plausible_but_faint_and_once_is_downgraded():
    a = assess(best_confidence=0.58, geo_plausibility=0.7, count=1)  # robin, faint, once
    assert a.tier in ("tentative", "probable")
    assert "heard only once" in a.reasons
    assert "a faint match" in a.reasons


def test_uncommon_here_is_capped_at_probable():
    # Moorhen: modest confidence, uncommon for the area, heard a few times.
    # Should never be "confirmed" — that's reserved for expected birds.
    a = assess(best_confidence=0.77, geo_plausibility=0.238, count=4)
    assert "uncommon here" in a.reasons
    assert a.tier == "probable"


def test_modest_confidence_never_confirmed():
    # 0.65 is a soft match — even a common, repeated bird stays "probable".
    a = assess(best_confidence=0.65, geo_plausibility=0.9, count=6)
    assert a.tier == "probable"
    assert "a soft match" in a.reasons


def test_common_clear_repeated_is_confirmed():
    a = assess(best_confidence=0.82, geo_plausibility=0.62, count=5)  # magpie-ish, solid
    assert a.tier == "confirmed"


def test_very_clear_plausible_once_stays_high():
    a = assess(best_confidence=0.95, geo_plausibility=0.7, count=1)
    assert a.tier in ("confirmed", "probable")
    assert "heard only once" in a.reasons


def test_score_orders_sensibly():
    strong = assess(0.95, 0.9, 8).score
    weak = assess(0.6, 0.05, 1).score
    assert strong > weak
