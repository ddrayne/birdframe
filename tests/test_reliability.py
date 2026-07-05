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


def test_uncommon_here_noted_but_not_always_tentative():
    a = assess(best_confidence=0.77, geo_plausibility=0.24, count=3)  # moorhen-ish
    assert "uncommon here" in a.reasons
    assert a.tier in ("probable", "confirmed")


def test_very_clear_plausible_once_stays_high():
    a = assess(best_confidence=0.95, geo_plausibility=0.7, count=1)
    assert a.tier in ("confirmed", "probable")
    assert "heard only once" in a.reasons


def test_score_orders_sensibly():
    strong = assess(0.95, 0.9, 8).score
    weak = assess(0.6, 0.05, 1).score
    assert strong > weak
