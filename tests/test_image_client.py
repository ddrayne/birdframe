import base64

import pytest

from birdframe.image_client import OpenAIImageClient


def test_generate_returns_decoded_bytes(mocker):
    fake = mocker.Mock()
    fake.images.generate.return_value = mocker.Mock(
        data=[mocker.Mock(b64_json=base64.b64encode(b"PNGDATA").decode())]
    )
    client = OpenAIImageClient(api_key="sk-test", model="gpt-image-1",
                               quality="high", sdk=fake)
    out = client.generate("a robin in a garden")
    assert out == b"PNGDATA"
    fake.images.generate.assert_called_once()
    kwargs = fake.images.generate.call_args.kwargs
    assert kwargs["model"] == "gpt-image-1"
    assert kwargs["size"] == "1024x1536"


def test_generate_retries_then_raises(mocker):
    fake = mocker.Mock()
    fake.images.generate.side_effect = RuntimeError("boom")
    client = OpenAIImageClient(api_key="sk-test", model="gpt-image-1",
                               quality="high", sdk=fake, max_retries=3, backoff=0)
    with pytest.raises(RuntimeError):
        client.generate("x")
    assert fake.images.generate.call_count == 3
