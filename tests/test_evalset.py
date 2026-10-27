import sys
from pathlib import Path

import numpy as np
import pytest

from armtranslate.evalset import (RATE, Clip, ManifestError, check, load_manifest, next_id,
                                  save_manifest, speech_bounds, upsert, write_wav)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
from record_clip import load_prompts  # noqa: E402

HY = "Բարև, ես ծրագրավորող եմ։"
EN = "Hello, I am a programmer."


def tone(seconds, level=0.1):
    t = np.arange(int(seconds * RATE)) / RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def make_clip(tmp, cid, seconds, hy=HY, en=EN, source="mic"):
    (tmp / "audio").mkdir(exist_ok=True)
    write_wav(tmp / "audio" / f"{cid}.wav", tone(seconds))
    return Clip(id=cid, audio=f"audio/{cid}.wav", source=source,
                speaker="me" if source == "mic" else "remote-A",
                duration_s=round(seconds, 3), hy=hy, en=en)


def full_set(tmp):
    lengths = [1.0, 1.2, 1.4] + [4.0] * 10 + [10.0, 11.0]
    return [make_clip(tmp, f"mic-{i:02d}", s) for i, s in enumerate(lengths, 1)]


def test_roundtrip_keeps_armenian_readable(tmp_path):
    m = tmp_path / "manifest.jsonl"
    save_manifest(m, [make_clip(tmp_path, "mic-01", 2.0)])
    assert HY in m.read_text(encoding="utf-8")  # not \\u-escaped
    assert load_manifest(m)[0].hy == HY


def test_missing_manifest_loads_empty(tmp_path):
    assert load_manifest(tmp_path / "none.jsonl") == []


@pytest.mark.parametrize("line, msg", [
    ("{not json", "line 1: not valid JSON"),
    ('{"id": "mic-01", "colour": "red"}', "unknown field"),
    ("[1, 2]", "expected a JSON object"),
])
def test_bad_rows_name_the_line(tmp_path, line, msg):
    m = tmp_path / "manifest.jsonl"
    m.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ManifestError, match=msg):
        load_manifest(m)


def test_upsert_rerecord_keeps_texts_and_sorts(tmp_path):
    a = make_clip(tmp_path, "mic-02", 2.0)
    b = make_clip(tmp_path, "mic-10", 2.0)
    redo = Clip(id="mic-02", audio="audio/mic-02.wav", source="mic", speaker="me", duration_s=3.0)
    out = upsert([b, a], redo)
    assert [c.id for c in out] == ["mic-02", "mic-10"]
    assert out[0].duration_s == 3.0 and out[0].hy == HY and out[0].en == EN


def test_next_id():
    clips = [Clip("mic-01", "", "mic", "me", 1.0), Clip("mic-07", "", "mic", "me", 1.0)]
    assert next_id(clips, "mic") == "mic-08"
    assert next_id(clips, "system") == "call-01"
    assert next_id([], "mic") == "mic-01"


def test_speech_bounds_trims_silence_with_padding():
    y = np.concatenate([np.full(RATE, 1e-5), tone(2.0), np.full(RATE, 1e-5)]).astype(np.float32)
    start, end = speech_bounds(y)
    assert start == pytest.approx(0.75 * RATE, abs=0.02 * RATE)
    assert end == pytest.approx(3.25 * RATE, abs=0.02 * RATE)


def test_speech_bounds_none_for_silence():
    assert speech_bounds(np.full(2 * RATE, 1e-5, np.float32)) is None
    assert speech_bounds(np.zeros(10, np.float32)) is None


def test_complete_set_passes(tmp_path):
    m = tmp_path / "manifest.jsonl"
    save_manifest(m, full_set(tmp_path))
    r = check(m)
    assert r.ok, r.errors
    assert r.warnings == []
    assert r.summary["clips"] == 15 and r.summary["under_1.5s"] == 3


def test_missing_text_is_error_unless_draft(tmp_path):
    m = tmp_path / "manifest.jsonl"
    clips = full_set(tmp_path)
    clips[0].hy = ""
    clips[1].en = ""
    save_manifest(m, clips)
    assert len(check(m).errors) == 2
    d = check(m, draft=True)
    assert d.ok and len(d.warnings) == 2


@pytest.mark.parametrize("field, value, msg", [
    ("hy", "Hello", "no Armenian letters"),
    ("en", HY, "wrong field"),
    ("duration_s", 9.0, "duration_s"),
    ("source", "phone", "source must be"),
    ("audio", "audio/missing.wav", "not found"),
    ("id", "clip1", "id must look like"),
])
def test_field_errors(tmp_path, field, value, msg):
    m = tmp_path / "manifest.jsonl"
    clips = full_set(tmp_path)
    setattr(clips[3], field, value)
    save_manifest(m, clips)
    r = check(m)
    assert not r.ok and any(msg in e for e in r.errors), r.errors


def test_wrong_format_wav_is_an_error(tmp_path):
    import wave
    m = tmp_path / "manifest.jsonl"
    clips = full_set(tmp_path)
    with wave.open(str(tmp_path / "audio" / "mic-04.wav"), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(48_000)
        w.writeframes(np.zeros(48_000 * 2 * 4, np.int16).tobytes())
    save_manifest(m, clips)
    assert any("16 kHz mono" in e for e in check(m).errors)


def test_duplicate_ids_and_length_targets(tmp_path):
    m = tmp_path / "manifest.jsonl"
    clips = [make_clip(tmp_path, "mic-01", 4.0), make_clip(tmp_path, "mic-01", 4.0)]
    save_manifest(m, clips)
    r = check(m)
    assert any("duplicate" in e for e in r.errors)
    assert any("target is at least 15" in w for w in r.warnings)
    assert any("under 1.5 s" in w for w in r.warnings)


def test_prompts_file_parses():
    prompts = load_prompts(ROOT / "eval" / "prompts.md")
    assert sorted(prompts) == [f"p{i:02d}" for i in range(1, 16)]
    assert "Python" in prompts["p15"]
