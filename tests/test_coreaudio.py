from birdframe.coreaudio import _fourcc, ensure_input_unmuted


class FakeCoreAudio:
    def __init__(self, muted=True):
        self.muted = muted
        self.writes = []

    def devices(self): return [7, 8]
    def default_input_device(self): return 8
    def name(self, device): return {7: "Webcam", 8: "USB Microphone"}[device]
    def input_muted(self, device): return self.muted if device == 8 else None

    def set_input_muted(self, device, muted):
        self.writes.append((device, muted))
        self.muted = muted


def test_fourcc_matches_coreaudio_integer_representation():
    assert _fourcc("mute") == 0x6D757465


def test_clears_hidden_mute_on_named_input():
    sdk = FakeCoreAudio(muted=True)
    assert ensure_input_unmuted("USB Microphone", sdk) is True
    assert sdk.writes == [(8, False)]


def test_already_unmuted_or_missing_device_is_a_noop():
    sdk = FakeCoreAudio(muted=False)
    assert ensure_input_unmuted("USB Microphone", sdk) is False
    assert ensure_input_unmuted("Not present", sdk) is False
    assert sdk.writes == []


def test_empty_name_uses_default_input():
    sdk = FakeCoreAudio(muted=True)
    assert ensure_input_unmuted(None, sdk) is True
    assert sdk.writes == [(8, False)]
