"""Echo detection in shadow mode (D-030): synthetic cases, pipeline wiring, replays of the recorded calls."""
import io
from pathlib import Path

import numpy as np
import pytest

from armtranslate.audio import AudioFrame
from armtranslate.config import EchoConfig, SegmentationConfig
from armtranslate.echo import EchoDetector, measure
from armtranslate.evalset import write_wav
from armtranslate.pipeline import FileSource, Worker, run
from armtranslate.vad import Segmenter

R = 16_000
CFG = EchoConfig()
ROOT = Path(__file__).resolve().parent.parent


def speech(seconds, seed, level=0.3):
    """Speech-like noise: syllables (~4/s) with changing formant bands and short pauses."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * R), np.float32)
    pos = 0
    while pos < len(out):
        n = int(rng.uniform(0.12, 0.3) * R)
        f = np.fft.rfft(rng.standard_normal(n))
        freqs = np.fft.rfftfreq(n, 1 / R)
        shape = sum(np.exp(-((freqs - rng.uniform(lo, hi)) / 120) ** 2) for lo, hi in ((300, 900), (900, 2500)))
        syl = np.fft.irfft(f * shape, n) * np.hanning(n)
        syl = syl / (np.abs(syl).max() + 1e-9) * level
        out[pos:pos + n] = syl[:len(out) - pos]
        pos += n + int(rng.uniform(0.02, 0.12) * R)
    return out


def echo_of(system, delay_s, gain=0.05, seed=9):
    """What the laptop mic hears from its speakers: delayed, coloured, much quieter, plus room noise."""
    d = int(delay_s * R)
    y = np.concatenate([np.zeros(d, np.float32), system])[:len(system)]
    y = np.convolve(y, np.ones(4) / 4, mode="same") * gain        # crude speaker/room colouring
    return (y + np.random.default_rng(seed).standard_normal(len(y)) * 1e-4).astype(np.float32)


def check(mic, system):
    """Measure a mic segment against system audio that starts max_lag before it."""
    pad = np.zeros(int(CFG.max_lag_ms / 1000 * R), np.float32)
    return measure(mic, np.concatenate([pad, system]), CFG)


@pytest.mark.parametrize("delay_s", [0.0, 0.3, 0.75])
def test_echo_of_call_is_suspect(delay_s):
    call = speech(2.0, seed=1)
    m = check(echo_of(call, delay_s), call)
    assert m["suspect"], m
    assert abs(m["lag_ms"] - delay_s * 1000) <= 64
    assert m["level_db"] < 0


def test_own_speech_with_call_silent_is_not_suspect():
    m = check(speech(2.0, seed=2), np.zeros(2 * R, np.float32))
    assert not m["suspect"] and m["overlap_s"] == 0


def test_own_speech_over_call_at_normal_level_is_not_suspect():
    call = speech(2.0, seed=1, level=0.1)            # live: own voice +10..+54 dB above the call
    mic = speech(2.0, seed=2) + echo_of(call, 0.15)
    m = check(mic, call)
    assert not m["suspect"], m
    assert m["level_db"] > CFG.max_level_db


def test_short_overlap_is_not_suspect():
    call = np.zeros(2 * R, np.float32)
    call[R:R + int(0.2 * R)] = speech(0.2, seed=1)                  # 0.2 s of call speech
    m = check(echo_of(call, 0.0), call)
    assert m["overlap_s"] < CFG.min_overlap_s and not m["suspect"]


def test_own_speech_after_the_call_stops_is_not_suspect():
    """The call talks in the first second, you answer in the second: mic-only time protects you."""
    call = np.concatenate([speech(1.0, seed=1), np.zeros(R, np.float32)])
    mic = echo_of(call, 0.1) + np.concatenate([np.zeros(R, np.float32), speech(1.0, seed=2, level=0.1)])
    m = check(mic, call)
    assert m["mic_only_s"] >= CFG.max_mic_only_s and not m["suspect"], m


def test_quiet_speech_over_loud_call_can_be_flagged():
    """Known limit (D-030): a soft interruption under loud call audio looks like echo.
    This is why the detector only logs and never hides a line."""
    call = speech(2.0, seed=1, level=0.9)
    mic = echo_of(call, 0.15, gain=0.3) + speech(2.0, seed=2, level=0.02)
    m = check(mic, call)
    assert m["level_db"] < CFG.max_level_db


def test_no_system_audio_received():
    det = EchoDetector(CFG)
    m = det.check(speech(1.0, seed=2), 100.0)
    assert not m["suspect"] and m["overlap_s"] == 0


def test_detector_places_frames_by_time_and_fills_gaps():
    det = EchoDetector(CFG)
    det.feed(AudioFrame("system", 10.0, np.ones(160, np.float32)))
    det.feed(AudioFrame("system", 10.02, np.full(160, 2, np.float32)))
    det.feed(AudioFrame("system", 10.1, np.full(160, 3, np.float32)))      # 60 ms gap before
    y = det.system_audio(10.0, 10.11)
    assert y[0] == 1 and y[200] == 0 and y[330] == 2 and y[1000] == 0 and y[1700] == 3
    assert det.covers(10.11) and not det.covers(10.2)


def test_detector_forgets_old_audio():
    det = EchoDetector(CFG, keep_s=1.0)
    for i in range(100):
        det.feed(AudioFrame("system", i * 0.02, np.ones(320, np.float32)))
    assert det.system_audio(0.0, 0.5).sum() == 0 and det.system_audio(1.5, 1.9).sum() > 0


def energy_vad(chunk):
    return 0.9 if np.sqrt(np.mean(chunk ** 2)) > 0.005 else 0.0


def _two_source_run(tmp_path, echo):
    call = np.concatenate([np.zeros(R, np.float32), speech(2.0, seed=1), np.zeros(int(3.5 * R), np.float32)])
    me = np.concatenate([np.zeros(5 * R, np.float32), speech(1.5, seed=2)])
    mic = (echo_of(call, 0.15, gain=0.1) + me).astype(np.float32)
    write_wav(tmp_path / "mic.wav", mic)
    write_wav(tmp_path / "sys.wav", call)
    src = {"mic": FileSource(tmp_path / "mic.wav", "mic", realtime=False),
           "system": FileSource(tmp_path / "sys.wav", "system", realtime=False)}
    seg = {n: Segmenter(n, energy_vad, SegmentationConfig()) for n in src}
    out = io.StringIO()
    w = Worker(lambda s: f"Ձայն {len(s) / R:.1f}", lambda s: s, out=out, log=io.StringIO())
    run(src, seg, w, echo=echo)
    return w, out.getvalue()


def test_shadow_mode_logs_but_changes_nothing(tmp_path):
    w_off, out_off = _two_source_run(tmp_path, None)
    w_on, out_on = _two_source_run(tmp_path, EchoDetector(CFG))
    strip = lambda s: [line.split("] ", 1)[1] for line in s.splitlines()]   # noqa: E731 (wall clock differs)
    assert strip(out_on) == strip(out_off)                       # every line still shown, same text and order
    mic = [r for r in w_on.results if r.source == "mic"]
    assert [r.echo_suspect for r in mic] == [True, False]        # the echo, then my own phrase
    assert all(r.echo["covered"] for r in mic)
    assert all(r.echo is None and r.echo_suspect is None for r in w_on.results if r.source == "system")
    assert all(r.echo is None for r in w_off.results)
    assert '"echo_suspect": true' in w_on.log.getvalue()


def test_measurement_error_never_costs_a_line(tmp_path):
    det = EchoDetector(CFG)
    det.check = lambda *a: 1 / 0
    w, out = _two_source_run(tmp_path, det)
    mic = [r for r in w.results if r.source == "mic"]
    assert len(mic) == 2 and all(r.echo_suspect is None and "ZeroDivisionError" in r.echo["error"] for r in mic)


# Replays of the two recorded live calls (recordings are private, not in git: skipped elsewhere).
# Times are seconds from the start of the recording; segmentation is Silero's, as live.
CALLS = {
    "20261031-160647": {"echo": [8.6, 23.8, 61.1, 69.5],
                        "own": [4.7, 15.3, 27.8, 38.0, 41.5, 51.4, 57.6, 65.5, 77.4, 84.4, 89.1, 99.7]},
    "20261029-202643": {"echo": [], "own": None},                 # None: every mic segment is mine
}


@pytest.mark.parametrize("call", CALLS)
def test_replay_recorded_call(call):
    run_dir = ROOT / "runs" / call
    from armtranslate.vad import DEFAULT_VAD_PATH, SileroVad
    if not (run_dir / "input-mic.wav").exists() or not DEFAULT_VAD_PATH.exists():
        pytest.skip("recording or VAD model not available")
    src = {n: FileSource(run_dir / f"input-{n}.wav", n, realtime=False, lead_s=0, tail_s=1.5)
           for n in ("mic", "system")}
    seg = {n: Segmenter(n, SileroVad(), SegmentationConfig()) for n in src}
    w = Worker(lambda s: "Աա", lambda s: s, out=io.StringIO())
    run(src, seg, w, echo=EchoDetector(CFG))
    from armtranslate.audio import wall_time
    t0 = wall_time(src["mic"]._t0)
    mic = [(round(r.t_start - t0, 1), r.echo_suspect) for r in w.results if r.source == "mic"]
    flagged = [t for t, s in mic if s]
    expect = CALLS[call]
    assert flagged == pytest.approx(expect["echo"], abs=0.3)
    own = expect["own"] if expect["own"] is not None else [t for t, _ in mic]
    assert not any(abs(t - f) < 0.3 for t in own for f in flagged)   # no real speech flagged
