import numpy as np
import pytest

from armtranslate.audio import DeviceError, FrameAssembler, resolve_device, wall_time
from armtranslate.config import AudioConfig

WASAPI, MME = 2, 0
DEVICES = [
    {"index": 0, "name": "Microphone Array (Realtek)", "hostApi": MME, "maxInputChannels": 2},
    {"index": 5, "name": "Microphone Array (Realtek)", "hostApi": WASAPI, "maxInputChannels": 2},
    {"index": 6, "name": "Headset Microphone (Jabra)", "hostApi": WASAPI, "maxInputChannels": 1},
    {"index": 7, "name": "Speakers (Realtek) [Loopback]", "hostApi": WASAPI, "maxInputChannels": 2,
     "isLoopbackDevice": True},
    {"index": 8, "name": "Headset Earphone (Jabra) [Loopback]", "hostApi": WASAPI,
     "maxInputChannels": 2, "isLoopbackDevice": True},
    {"index": 9, "name": "Speakers (Realtek)", "hostApi": WASAPI, "maxInputChannels": 0},
]


def pick(spec, kind, default=None):
    return resolve_device(DEVICES, spec, kind, default, WASAPI)["index"]


def test_defaults_and_indices():
    assert pick(None, "mic", default=5) == 5
    assert pick(None, "system", default=7) == 7
    assert pick(6, "mic") == 6
    assert pick(0, "mic") == 0  # an explicit index may name a non-WASAPI device


def test_name_substring_is_case_insensitive_and_kind_aware():
    assert pick("jabra", "mic") == 6
    assert pick("jabra", "system") == 8
    assert pick("speakers", "system") == 7


@pytest.mark.parametrize("spec, kind", [
    (7, "mic"),            # loopback used as a mic
    (5, "system"),         # mic used as system audio
    (9, "system"),         # output device itself is not capturable
    (42, "mic"),           # no such index
    ("nothing", "mic"),
    (None, "mic"),         # no default available
])
def test_errors(spec, kind):
    with pytest.raises(DeviceError):
        pick(spec, kind)


def test_name_matching_ignores_non_wasapi_duplicates():
    assert pick("realtek", "mic") == 5


def test_ambiguous_name_is_an_error():
    with pytest.raises(DeviceError, match="several"):
        pick("loopback", "system")


def chunk(n_frames, channels=2, value=1000):
    return (np.full((n_frames, channels), value, dtype=np.int16)).tobytes()


def run(assembler, chunks):
    out = []
    for raw, t in chunks:
        f = assembler.push(raw, t)
        if f is not None:
            out.append(f)
    return out


def total_s(frames, rate=16_000):
    return sum(len(f.samples) for f in frames) / rate


def test_continuous_stream_resamples_without_gaps():
    a = FrameAssembler("mic", 48_000, 2, AudioConfig())
    block = 960  # 20 ms at 48 kHz
    frames = run(a, [(chunk(block), 1.0 + 0.02 * (i + 1)) for i in range(100)])  # 2 s
    assert a.gaps_filled == 0 and a.resyncs == 0
    assert total_s(frames) == pytest.approx(2.0, abs=0.05)  # soxr holds back a few tens of ms
    assert all(f.samples.dtype == np.float32 and f.rate == 16_000 for f in frames)
    assert np.median(frames[-1].samples) == pytest.approx(1000 / 32768, rel=0.01)
    for prev, cur in zip(frames, frames[1:]):  # timestamps are contiguous
        assert cur.t_start == pytest.approx(prev.t_end, abs=1e-6)
    # output sample k maps to input time start + k/rate, so the resampler delay never skews time
    assert frames[0].t_start == pytest.approx(wall_time(1.0), abs=1e-6)


def test_jitter_below_threshold_is_not_a_gap():
    a = FrameAssembler("mic", 48_000, 2, AudioConfig(gap_threshold_ms=200))
    times = [1.02, 1.04, 1.20, 1.21, 1.22, 1.23]  # one late callback, then a burst
    run(a, [(chunk(960), t) for t in times])
    assert a.gaps_filled == 0


def test_loopback_silence_is_filled_and_timestamps_follow_wall_clock():
    a = FrameAssembler("system", 48_000, 2, AudioConfig())
    frames = run(a, [(chunk(960), 1.02), (chunk(960), 1.04),
                     (chunk(960), 4.06)])               # 3 s of nothing, then data again
    assert a.gaps_filled == 1
    assert a.gap_filled_s == pytest.approx(3.0, abs=0.001)
    assert total_s(frames) == pytest.approx(3.06, abs=0.05)
    assert frames[0].t_start == pytest.approx(wall_time(1.0), abs=1e-6)
    for prev, cur in zip(frames, frames[1:]):
        assert cur.t_start == pytest.approx(prev.t_end, abs=1e-6)
    assert wall_time(4.06) - 0.05 < frames[-1].t_end <= wall_time(4.06)


def test_idle_emits_silence_only_past_threshold():
    a = FrameAssembler("system", 48_000, 2, AudioConfig(gap_threshold_ms=200))
    run(a, [(chunk(960), 1.02)])
    assert a.idle(1.10) is None
    f = a.idle(2.02)
    assert f is not None and a.gap_filled_s == pytest.approx(1.0, abs=0.001)
    assert np.all(f.samples[-8000:] == 0)  # the head is held-back audio from before the gap


def test_silence_from_stream_start_is_filled():
    a = FrameAssembler("system", 48_000, 2, AudioConfig())
    a.anchor(1.0)
    f = a.idle(3.0)                     # loopback never delivered anything
    assert f is not None and a.gap_filled_s == pytest.approx(2.0, abs=0.001)
    assert a.leading_fill_s == pytest.approx(2.0, abs=0.001) and a.gaps_filled == 0
    assert f.t_start == pytest.approx(wall_time(1.0), abs=1e-6)


def test_one_silent_stretch_counts_as_one_gap():
    a = FrameAssembler("system", 48_000, 2, AudioConfig(gap_threshold_ms=200))
    run(a, [(chunk(960), 1.02)])
    for i in range(1, 11):
        a.idle(1.02 + 0.25 * i)         # polled repeatedly during 2.5 s of silence
    run(a, [(chunk(960), 3.6)])
    assert a.gaps_filled == 1 and a.gap_filled_s == pytest.approx(2.5, abs=0.001)


def test_startup_delay_is_filled_exactly_and_not_counted_as_gap():
    a = FrameAssembler("mic", 48_000, 2, AudioConfig(gap_threshold_ms=200))
    a.anchor(1.0)
    frames = run(a, [(chunk(960), 1.14), (chunk(960), 1.16)])  # first data 120 ms after start
    assert a.leading_fill_s == pytest.approx(0.12, abs=0.001) and a.gaps_filled == 0
    assert frames[0].t_start == pytest.approx(wall_time(1.0), abs=1e-6)


def test_fill_gaps_can_be_disabled():
    a = FrameAssembler("system", 48_000, 2, AudioConfig(fill_gaps=False))
    run(a, [(chunk(960), 1.02), (chunk(960), 4.06)])
    assert a.gaps_filled == 0 and a.idle(9.0) is None


def test_fast_device_clock_resyncs():
    a = FrameAssembler("mic", 48_000, 2, AudioConfig(gap_threshold_ms=200))
    run(a, [(chunk(48_000), 1.0)] + [(chunk(48_000), 1.0) for _ in range(3)])  # 4 s in 0 s
    assert a.resyncs >= 1
