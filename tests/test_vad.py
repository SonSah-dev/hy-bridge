import numpy as np
import pytest

from armtranslate.audio import AudioFrame
from armtranslate.config import SegmentationConfig
from armtranslate.vad import CHUNK, CHUNK_S, RATE, Segmenter


class ScriptedVad:
    """Speech probability from a schedule of (start_s, end_s) voiced intervals."""

    def __init__(self, voiced):
        self.voiced, self.t = voiced, 0.0

    def __call__(self, chunk):
        mid = self.t + CHUNK_S / 2
        self.t += CHUNK_S
        return 0.9 if any(a <= mid < b for a, b in self.voiced) else 0.05


def run(voiced, total_s, cfg=None, t0=1000.0, frame_s=0.02):
    cfg = cfg or SegmentationConfig()
    seg = Segmenter("mic", ScriptedVad(voiced), cfg)
    n = int(frame_s * RATE)
    out = []
    for i in range(int(total_s / frame_s)):
        out += seg.push(AudioFrame("mic", t0 + i * frame_s, np.zeros(n, np.float32)))
    return out + seg.flush(), seg


def test_single_phrase_ends_after_pause():
    segs, _ = run([(1.0, 3.0)], 5.0)
    assert len(segs) == 1
    s = segs[0]
    assert s.t_last_voice - 1000 == pytest.approx(3.0, abs=CHUNK_S)
    assert s.t_start - 1000 == pytest.approx(1.0 - 0.2, abs=CHUNK_S)       # pre-roll
    assert s.t_emit - s.t_last_voice == pytest.approx(1.0, abs=CHUNK_S)     # end_pause_ms
    assert not s.forced
    assert s.duration_s < 2.6                                                # trailing pause trimmed


def test_short_gap_does_not_split():
    segs, _ = run([(1.0, 2.0), (2.3, 3.0)], 5.0)
    assert len(segs) == 1


def test_long_gap_splits():
    segs, _ = run([(1.0, 2.0), (3.0, 4.0)], 6.0)
    assert len(segs) == 2


def test_forced_cut_at_max_segment():
    segs, _ = run([(0.5, 20.0)], 22.0)
    assert [s.forced for s in segs][:2] == [True, True]
    assert all(s.duration_s <= 8.0 + CHUNK_S for s in segs)
    assert sum(s.duration_s for s in segs) == pytest.approx(19.5 + 0.2, abs=0.5)


def test_short_burst_dropped():
    segs, seg = run([(1.0, 1.1)], 3.0)
    assert segs == [] and seg.dropped_short == 1


def test_flush_closes_open_segment():
    segs, _ = run([(1.0, 5.0)], 3.0)
    assert len(segs) == 1


def test_frames_not_multiple_of_chunk():
    segs, _ = run([(1.0, 2.0)], 4.0, frame_s=0.013)
    assert len(segs) == 1
    assert len(segs[0].samples) % CHUNK == 0 or not segs[0].forced


def test_forced_cut_lands_in_a_dip():
    # continuous speech except a 0.2 s dip at 7.4 s; the cut at 8.3 s (incl. pre-roll) moves back to it
    segs, _ = run([(0.5, 7.4), (7.6, 12.0)], 14.0)
    first = segs[0]
    assert first.forced
    assert first.t_start + first.duration_s - 1000 == pytest.approx(7.5, abs=0.1)
    assert segs[1].t_start == pytest.approx(first.t_start + first.duration_s, abs=1e-6)
