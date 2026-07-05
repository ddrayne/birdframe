from birdframe.publisher import Publisher


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.text = ""


def test_publish_success_202():
    posts = []

    def fake_post(url, files, data, timeout):
        posts.append((url, files, data))
        return FakeResponse(202)

    pub = Publisher("http://frame.local:5000", hold_minutes=180, saturation=0.6,
                    http_post=fake_post)
    result = pub.publish(b"PNGBYTES")
    assert result.status == "posted"
    assert posts[0][0] == "http://frame.local:5000/display"
    assert posts[0][2]["source"] == "birdframe"
    assert posts[0][2]["hold_minutes"] == 180
    assert "force" not in posts[0][2]        # automatic posts stay polite


def test_publish_force_overrides_hold():
    posts = []

    def fake_post(url, files, data, timeout):
        posts.append(data)
        return FakeResponse(202)

    pub = Publisher("http://frame.local:5000", hold_minutes=180, saturation=0.6,
                    http_post=fake_post)
    pub.publish(b"PNGBYTES", force=True)
    assert posts[0]["force"] == "1"          # explicit post overrides the hold


def test_publish_held_409_is_not_retried():
    calls = {"n": 0}

    def fake_post(url, files, data, timeout):
        calls["n"] += 1
        return FakeResponse(409)

    pub = Publisher("http://frame.local:5000", hold_minutes=180, saturation=0.6,
                    http_post=fake_post, max_retries=3, backoff=0)
    result = pub.publish(b"PNGBYTES")
    assert result.status == "held"
    assert calls["n"] == 1


def test_publish_network_error_retries_then_fails():
    calls = {"n": 0}

    def boom(url, files, data, timeout):
        calls["n"] += 1
        raise ConnectionError("frame offline")

    pub = Publisher("http://frame.local:5000", hold_minutes=0, saturation=0.6,
                    http_post=boom, max_retries=3, backoff=0)
    result = pub.publish(b"PNGBYTES")
    assert result.status == "unreachable"
    assert calls["n"] == 3
