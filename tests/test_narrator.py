from birdframe.narrator import narrate


def test_fallback_without_client():
    s = narrate(["European Robin", "Common Blackbird"], "light rain", "summer", "evening")
    assert "Robin" in s and "rain" in s
    assert "!" not in s


def test_fallback_empty_day():
    s = narrate([], "clear", "winter", "morning")
    assert "quiet" in s.lower()


def test_uses_client_when_present(mocker):
    client = mocker.Mock()
    msg = mocker.Mock(); msg.content = "The blackbird held the drizzled garden until dusk."
    client.chat.completions.create.return_value = mocker.Mock(choices=[mocker.Mock(message=msg)])
    s = narrate(["Common Blackbird"], "drizzle", "summer", "dusk", client=client)
    assert s == "The blackbird held the drizzled garden until dusk."
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4.1-mini"


def test_client_error_falls_back(mocker):
    client = mocker.Mock()
    client.chat.completions.create.side_effect = RuntimeError("down")
    s = narrate(["European Robin"], "clear", "spring", "morning", client=client)
    assert "Robin" in s  # template fallback
