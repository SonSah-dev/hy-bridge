import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "spikes"))
from audio_capture_spike import active_fraction  # noqa: E402

RATE = 16_000


def test_active_fraction_catches_a_mostly_silent_stream():
    # 2 s of loud audio then 28 s of near silence: whole-file RMS passes, this must not
    y = np.concatenate([np.full(2 * RATE, 0.1), np.full(28 * RATE, 1e-5)]).astype(np.float32)
    assert active_fraction(y, RATE) == round(2 / 30, 3)


def test_active_fraction_bounds():
    assert active_fraction(np.zeros(10, np.float32), RATE) == 0.0
    assert active_fraction(np.full(3 * RATE, 0.05, np.float32), RATE) == 1.0
