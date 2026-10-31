import io
import json

import numpy as np
import pytest

from armtranslate.config import SegmentationConfig
from armtranslate.evalset import write_wav
from armtranslate.pipeline import FileSource, Worker, latency_summary, run
from armtranslate.vad import Segment, Segmenter


def tone(seconds, level=0.3):
    t = np.arange(int(seconds * 16_000)) / 16_000
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def energy_vad(chunk):
    return 0.9 if np.sqrt(np.mean(chunk ** 2)) > 0.05 else 0.0


def test_worker_logs_and_prints():
    out, log = io.StringIO(), io.StringIO()
    clock = iter([100.0, 101.2])
    w = Worker(lambda s: "Բարեւ", lambda s: f"EN({s})", fix=lambda s: s + "!", out=out, log=log,
               clock=lambda: next(clock))
    seg = Segment("mic", t_start=98.0, t_last_voice=99.0, t_emit=99.6, samples=np.zeros(16_000, np.float32))
    r = w.process(seg)
    assert r.latency_s == 2.2 and r.queue_s == 0.4
    assert r.en == "EN(Բարեւ!)" and r.hy_fixed == "Բարեւ!"
    assert "Me: Բարեւ!  →  EN(Բարեւ!)" in out.getvalue()      # shows the text that was translated
    assert json.loads(log.getvalue())["label"] == "Me"


def test_empty_transcript_is_skipped():
    w = Worker(lambda s: "  ", lambda s: "x", out=io.StringIO())
    assert w.process(Segment("mic", 0, 0, 0, np.zeros(10, np.float32))) is None


def test_file_to_lines_end_to_end(tmp_path):
    y = np.concatenate([tone(1.0), np.zeros(32_000, np.float32), tone(1.5)])  # 2 s gap > end_pause_ms
    write_wav(tmp_path / "a.wav", y)
    src = FileSource(tmp_path / "a.wav", realtime=False)
    out = io.StringIO()
    w = Worker(lambda s: f"Ձայն {len(s) / 16_000:.1f}", lambda s: s, out=out)
    run({"mic": src}, {"mic": Segmenter("mic", energy_vad, SegmentationConfig())}, w)
    lines = out.getvalue().strip().splitlines()
    assert len(lines) == 2
    assert latency_summary(w.results)["segments"] == 2


def test_latency_summary_empty():
    assert latency_summary([]) == {"segments": 0}


def test_noise_segments_not_shown():
    out = io.StringIO()
    w = Worker(lambda s: "«.", lambda s: "What is it?", out=out)
    assert w.process(Segment("mic", 0, 0, 0, np.zeros(10, np.float32))) is None
    assert w.skipped == 1 and out.getvalue() == ""
    w.transcribe = lambda s: "Ե։"                       # one letter: still noise
    assert w.process(Segment("mic", 0, 0, 0, np.zeros(10, np.float32))) is None


def test_two_sources_interleave_with_labels(tmp_path):
    # mic speaks first, the call answers while the mic is silent, then both overlap
    mic = np.concatenate([tone(1.0), np.zeros(48_000, np.float32), tone(1.0), np.zeros(32_000, np.float32)])
    sysa = np.concatenate([np.zeros(28_000, np.float32), tone(1.0), np.zeros(24_000, np.float32),
                           tone(1.2), np.zeros(32_000, np.float32)])
    write_wav(tmp_path / "m.wav", mic)
    write_wav(tmp_path / "s.wav", sysa)
    sources = {"mic": FileSource(tmp_path / "m.wav", "mic", realtime=False),
               "system": FileSource(tmp_path / "s.wav", "system", realtime=False)}
    segs = {n: Segmenter(n, energy_vad, SegmentationConfig()) for n in sources}
    out = io.StringIO()
    w = Worker(lambda s: "Ձայն", lambda s: s, out=out)
    run(sources, segs, w)
    assert [r.label for r in w.results].count("Me") == 2
    assert [r.label for r in w.results].count("Remote") == 2
    starts = [r.t_start for r in w.results]
    assert starts[0] == min(starts)                    # the mic phrase came first and printed first


def test_realtime_file_source_does_not_block_when_not_due(tmp_path):
    write_wav(tmp_path / "a.wav", tone(1.0))
    src = FileSource(tmp_path / "a.wav", realtime=True, lead_s=0.0)
    src.start()
    assert src.read(timeout=0) is None                 # first 20 ms frame is not captured yet
    assert src.read(timeout=0.05) is not None          # waits for it when allowed to
    assert not src.finished


def test_unclear_segment_is_not_translated():
    from armtranslate.asr import is_unclear
    calls, out = [], io.StringIO()
    w = Worker(lambda s: ("Տ գրված ծ ին բալ", {"mean_logprob": -0.48, "low_share": 0.29}),
               lambda s: calls.append(s) or "invented", out=out,
               unclear=lambda text, conf: is_unclear(conf, -0.3, 0.15))
    r = w.process(Segment("mic", 0, 0, 0, np.zeros(16_000, np.float32)))
    assert r.en == "[unclear]" and r.unclear and calls == []
    assert "Me: Տ գրված ծ ին բալ  →  [unclear]" in out.getvalue()
    assert r.asr_conf == {"mean_logprob": -0.48, "low_share": 0.29}
    assert latency_summary(w.results)["unclear"] == 1


def test_confident_segment_is_translated():
    from armtranslate.asr import is_unclear
    w = Worker(lambda s: ("Ես Լուսինեն եմ։", {"mean_logprob": -0.04, "low_share": 0.0}),
               lambda s: "My name is Lusine.", out=io.StringIO(),
               unclear=lambda text, conf: is_unclear(conf, -0.3, 0.15))
    r = w.process(Segment("mic", 0, 0, 0, np.zeros(16_000, np.float32)))
    assert r.en == "My name is Lusine." and not r.unclear


def test_is_unclear_thresholds():
    from armtranslate.asr import is_unclear
    assert is_unclear({"mean_logprob": -0.31, "low_share": 0.0}, -0.3, 0.15)
    assert is_unclear({"mean_logprob": -0.1, "low_share": 0.15}, -0.3, 0.15)
    assert not is_unclear({"mean_logprob": -0.29, "low_share": 0.14}, -0.3, 0.15)
    assert not is_unclear({"mean_logprob": -0.9, "low_share": 0.9}, None, None)   # switched off


def test_looping_translation_becomes_unclear():
    from armtranslate.mt import is_degenerate
    w = Worker(lambda s: ("Ի ջան, հը լավ գո", {"mean_logprob": -0.21, "low_share": 0.06}),
               lambda s: "Oh, yeah, yeah, yeah, yeah, yeah.", out=io.StringIO(),
               unclear=lambda text, conf: False, degenerate=is_degenerate)
    r = w.process(Segment("mic", 0, 0, 0, np.zeros(16_000, np.float32)))
    assert (r.en, r.unclear, r.unclear_reason) == ("[unclear]", True, "mt-repeat")


def test_asr_unclear_keeps_its_reason_and_skips_mt():
    from armtranslate.mt import is_degenerate
    calls = []
    w = Worker(lambda s: ("Տ գրված", {"mean_logprob": -0.48, "low_share": 0.29}),
               lambda s: calls.append(s) or "x", out=io.StringIO(),
               unclear=lambda text, conf: True, degenerate=is_degenerate)
    r = w.process(Segment("mic", 0, 0, 0, np.zeros(16_000, np.float32)))
    assert (r.en, r.unclear_reason, calls) == ("[unclear]", "asr", [])


def test_valid_repetition_is_printed():
    from armtranslate.mt import is_degenerate
    w = Worker(lambda s: "Այո, այո, այո, հասկացա։", lambda s: "Yes, yes, yes, I got it.", out=io.StringIO(),
               degenerate=is_degenerate)
    r = w.process(Segment("mic", 0, 0, 0, np.zeros(16_000, np.float32)))
    assert r.en == "Yes, yes, yes, I got it." and not r.unclear


def test_profane_translation_becomes_unclear():
    from armtranslate.mt import is_profane
    w = Worker(lambda s: ("Եղ որդի խճյուղին։", {"mean_logprob": -0.217, "low_share": 0.111}),
               lambda s: "Be the son of a bitch.", out=io.StringIO(),
               unclear=lambda text, conf: False, profane=is_profane)
    r = w.process(Segment("mic", 0, 0, 0, np.zeros(16_000, np.float32)))
    assert (r.en, r.unclear_reason) == ("[unclear]", "mt-profanity")


class BudgetTranslate:
    def __init__(self, fallback):
        self.budgets, self.fallback, self.used_fallback = [], fallback, False

    def __call__(self, text, budget_s=None):
        self.budgets.append(budget_s)
        self.used_fallback = self.fallback
        return "EN"


def test_deadline_budget_passed_to_mt_and_fallback_logged():
    clock = iter([100.0, 100.6, 102.0])                 # dequeue, budget computed, printed
    mt = BudgetTranslate(fallback=True)
    w = Worker(lambda s: "Բարեւ", mt, out=io.StringIO(), clock=lambda: next(clock), mt_deadline_s=4.5)
    seg = Segment("mic", t_start=92.0, t_last_voice=100.0, t_emit=100.0, samples=np.zeros(16_000, np.float32))
    r = w.process(seg)
    assert mt.budgets == [pytest.approx(3.9)] and r.mt_fallback


def test_no_deadline_calls_mt_without_budget():
    w = Worker(lambda s: "Բարեւ", lambda s: "EN", out=io.StringIO())
    seg = Segment("mic", t_start=92.0, t_last_voice=100.0, t_emit=100.0, samples=np.zeros(16_000, np.float32))
    assert not w.process(seg).mt_fallback
