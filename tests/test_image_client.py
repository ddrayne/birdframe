import base64

import pytest

from birdframe.image_client import GeminiImageClient, OpenAIImageClient


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


def _gemini_resp(mocker, parts):
    return mocker.Mock(candidates=[mocker.Mock(content=mocker.Mock(parts=parts))])


def _image_part(mocker, data):
    return mocker.Mock(inline_data=mocker.Mock(data=data))


def _text_part(mocker):
    return mocker.Mock(inline_data=None)


def test_gemini_returns_image_bytes(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_text_part(mocker), _image_part(mocker, b"PNGDATA")])
    client = GeminiImageClient(api_key="AIza-test", sdk=fake)
    assert client.generate("a robin in a garden") == b"PNGDATA"
    kwargs = fake.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3-pro-image"
    assert kwargs["config"]["image_config"]["aspect_ratio"] == "4:5"
    assert kwargs["config"]["image_config"]["image_size"] == "2K"


def test_gemini_quality_maps_to_size(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_image_part(mocker, b"x")])
    GeminiImageClient(api_key="k", quality="medium", sdk=fake).generate("p")
    kwargs = fake.models.generate_content.call_args.kwargs
    assert kwargs["config"]["image_config"]["image_size"] == "1K"


def test_gemini_base64_string_data(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_image_part(mocker, base64.b64encode(b"PNGDATA").decode())])
    client = GeminiImageClient(api_key="k", sdk=fake)
    assert client.generate("p") == b"PNGDATA"


def test_gemini_no_image_part_raises_without_retry_burn(mocker):
    """A 200 with only text (e.g. a refusal) is a hard error, and must not
    burn paid retries."""
    fake = mocker.Mock()
    fake.models.generate_content.return_value = _gemini_resp(
        mocker, [_text_part(mocker)])
    client = GeminiImageClient(api_key="k", sdk=fake, max_retries=3, backoff=0)
    with pytest.raises(RuntimeError):
        client.generate("p")
    assert fake.models.generate_content.call_count == 1


def test_gemini_retries_then_raises(mocker):
    fake = mocker.Mock()
    fake.models.generate_content.side_effect = RuntimeError("boom")
    client = GeminiImageClient(api_key="k", sdk=fake, max_retries=3, backoff=0)
    with pytest.raises(RuntimeError):
        client.generate("p")
    assert fake.models.generate_content.call_count == 3
