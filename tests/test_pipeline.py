import io
import json

import numpy as np

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
