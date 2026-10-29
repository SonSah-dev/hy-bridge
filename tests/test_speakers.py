import io

import numpy as np

from armtranslate.evalset import read_wav
from armtranslate.pipeline import FileSource, RecordingSource, Worker
from armtranslate.speakers import UNKNOWN, SpeakerLabeler, SpeakerTracker, fbank
from armtranslate.vad import Segment

RNG = np.random.default_rng(0)
A, B, C = (v / np.linalg.norm(v) for v in RNG.normal(size=(3, 256)))


def near(v, noise=0.3):
    """Another 'utterance' of the voice v: cosine to v of about 0.9."""
    e = v + noise * RNG.normal(size=256) / np.sqrt(256)
    return e / np.linalg.norm(e)


def test_fbank_shape_and_mean_normalised():
    y = (0.1 * np.sin(2 * np.pi * 300 * np.arange(16_000) / 16_000)).astype(np.float32)
    f = fbank(y)
    assert f.shape == (98, 80)                        # Kaldi snip_edges: 1 + (16000 - 400) // 160
    assert np.allclose(f.mean(axis=0), 0, atol=1e-4)
    assert fbank(np.zeros(100, np.float32)).shape == (0, 80)


def test_turn_taking_keeps_one_label_each():
    t = SpeakerTracker(0.5, min_segment_s=1.0)
    labels = [t.assign(near(v), 3.0)[0] for v in [A, B] * 6]
    assert labels == ["Speaker 1", "Speaker 2"] * 6
    assert t.counts == [6, 6]


def test_return_after_silence_keeps_label():
    t = SpeakerTracker(0.5)
    assert [t.assign(near(v), 3.0)[0] for v in (A, B)] == ["Speaker 1", "Speaker 2"]
    assert t.assign(near(A), 3.0)[0] == "Speaker 1"   # time plays no part: centroids never expire


def test_short_segment_borrows_label_but_never_creates():
    t = SpeakerTracker(0.5, min_segment_s=1.0)
    label, info = t.assign(near(A), 0.6)
    assert label == UNKNOWN and info["decision"] == "short-unknown" and t.counts == []
    t.assign(near(A), 3.0)
    label, info = t.assign(near(A), 0.6)
    assert label == "Speaker 1" and info["decision"] == "short-match"
    assert t.counts == [1]                            # the short one did not move the centroid
    assert t.assign(near(B), 0.6)[0] == UNKNOWN       # unlike everyone known: no new speaker


def test_medium_segment_joins_but_never_starts_a_speaker():
    t = SpeakerTracker(0.5, min_segment_s=1.0, new_speaker_min_s=2.0)
    label, info = t.assign(near(A), 1.5)              # nobody known yet: like the call's first replies
    assert label == UNKNOWN and info["decision"] == "unknown" and t.counts == []
    t.assign(near(A), 3.0)
    assert t.assign(near(A), 1.5)[0] == "Speaker 1" and t.counts == [2]   # joins, moves the centroid
    assert t.assign(near(B), 1.5)[0] == UNKNOWN and len(t.counts) == 1
    assert t.assign(near(B), 2.5)[0] == "Speaker 2"


def test_short_threshold_is_separate():
    t = SpeakerTracker(0.99, min_segment_s=1.0, short_threshold=0.5)
    t.assign(A, 3.0)
    assert t.assign(near(A), 0.6)[0] == "Speaker 1"


def test_cap_assigns_nearest_instead_of_new_label():
    t = SpeakerTracker(0.5, max_speakers=2)
    t.assign(near(A), 3.0)
    t.assign(near(B), 3.0)
    label, info = t.assign(near(C), 3.0)
    assert label in ("Speaker 1", "Speaker 2") and info["decision"] == "cap"
    assert len(t.counts) == 2


def test_worker_labels_only_system_audio():
    calls = []
    labeler = SpeakerLabeler(lambda s: calls.append(len(s)) or near(A), SpeakerTracker(0.5))
    out = io.StringIO()
    w = Worker(lambda s: "Բարեւ ձեզ", lambda s: "Hello", out=out, speakers=labeler)
    samples = np.zeros(32_000, np.float32)
    r_sys = w.process(Segment("system", 0, 0, 0, samples))
    r_mic = w.process(Segment("mic", 0, 0, 0, samples))
    assert (r_sys.label, r_mic.label) == ("Speaker 1", "Me")
    assert r_sys.speaker["decision"] == "new" and r_mic.speaker is None
    assert calls == [32_000]                          # the mic is never embedded
    assert "Speaker 1: Բարեւ ձեզ" in out.getvalue()


def test_noise_segment_never_creates_a_speaker():
    tracker = SpeakerTracker(0.5)
    w = Worker(lambda s: "«.", lambda s: "x", out=io.StringIO(), speakers=SpeakerLabeler(lambda s: A, tracker))
    assert w.process(Segment("system", 0, 0, 0, np.zeros(32_000, np.float32))) is None
    assert tracker.counts == []


def test_without_speakers_system_is_remote():
    w = Worker(lambda s: "Բարեւ", lambda s: "Hi", out=io.StringIO())
    assert w.process(Segment("system", 0, 0, 0, np.zeros(16_000, np.float32))).label == "Remote"


def test_recording_source_saves_what_it_delivers(tmp_path):
    from armtranslate.evalset import write_wav
    y = (0.2 * np.sin(np.arange(16_000) / 5)).astype(np.float32)
    write_wav(tmp_path / "in.wav", y)
    rec = RecordingSource(FileSource(tmp_path / "in.wav", "system", realtime=False, lead_s=0, tail_s=0),
                          tmp_path / "out.wav")
    rec.start()
    while rec.read(timeout=0) is not None:
        pass
    assert rec.finished                               # attributes pass through to the source
    rec.stop()
    got, rate, _ = read_wav(tmp_path / "out.wav")
    assert rate == 16_000 and np.allclose(got, y, atol=1e-4)
