import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "robin.wav"


@pytest.mark.skipif(not FIXTURE.exists(), reason="no fixture audio")
@pytest.mark.skipif(os.environ.get("BIRDFRAME_SMOKE") != "1", reason="opt-in smoke test")
def test_detector_finds_something_in_real_audio():
    import soundfile as sf

    from birdframe.detector import Detector

    audio, sr = sf.read(str(FIXTURE))
    if audio.ndim > 1:
        audio = audio[:, 0]
    det = Detector(latitude=55.95, longitude=-3.19, threshold=0.1, geo_floor=0.0,
                   when=datetime(2026, 7, 5, 6))
    out = det.predict_chunk(audio.astype(np.float32), sr, datetime(2026, 7, 5, 6))
    print([(d.common_name, round(d.confidence, 3)) for d in out])
    assert isinstance(out, list)
