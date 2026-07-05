from datetime import datetime

from birdframe.weather import describe_weather, _code_to_phrase


def test_code_to_phrase():
    assert _code_to_phrase(0) == "clear"
    assert "rain" in _code_to_phrase(61)
    assert _code_to_phrase(999) == "changeable"


def test_describe_weather_uses_daily_code():
    def fake_get(url, params):
        return {"daily": {"weathercode": [61]}}
    phrase = describe_weather(55.95, -3.19, datetime(2026, 7, 5), http_get=fake_get)
    assert "rain" in phrase


def test_describe_weather_falls_back_on_error():
    def boom(url, params):
        raise RuntimeError("network down")
    assert describe_weather(55.95, -3.19, datetime(2026, 7, 5), http_get=boom) == "changeable"
