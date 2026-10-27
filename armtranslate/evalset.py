"""Evaluation set: manifest format, validation and clip trimming (DECISIONS.md D-012).

`eval/manifest.jsonl` holds one JSON object per clip; audio paths are relative to the
manifest's folder. Steps 3 and 4 load the set through `load_manifest`.
"""
from __future__ import annotations

import json
import re
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

RATE = 16_000
SOURCES = ("mic", "system")
ID_PATTERN = re.compile(r"^(mic|call)-\d{2,3}$")
ARMENIAN = re.compile(r"[Ա-և]")  # Armenian letters (upper, lower, ligature)

# Length targets from D-012. Checked as warnings: the set is still usable if one is missed.
MIN_CLIPS = 15
SHORT_MAX_S, MIN_SHORT = 1.5, 2
LONG_MIN_S, MIN_LONG = 9.0, 2
MAX_CLIP_S = 15.0
DURATION_TOLERANCE_S = 0.05


@dataclass
class Clip:
    id: str
    audio: str                 # path relative to the manifest folder
    source: str                # "mic" or "system"
    speaker: str               # "me" for the mic; remote speaker label for call clips
    duration_s: float
    hy: str = ""               # Armenian reference, exactly as spoken
    en: str = ""               # short English reference translation
    prompt: str = ""           # prompt id from eval/prompts.md, if any
    notes: str = ""
    recorded: str = ""         # ISO timestamp

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class ManifestError(ValueError):
    pass


def load_manifest(path: str | Path) -> list[Clip]:
    path = Path(path)
    if not path.exists():
        return []
    clips = []
    names = {f for f in Clip.__dataclass_fields__}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ManifestError(f"{path.name} line {n}: not valid JSON ({e.msg})") from None
        if not isinstance(row, dict):
            raise ManifestError(f"{path.name} line {n}: expected a JSON object")
        unknown = set(row) - names
        if unknown:
            raise ManifestError(f"{path.name} line {n}: unknown field(s) {sorted(unknown)}")
        try:
            clips.append(Clip(**row))
        except TypeError as e:
            raise ManifestError(f"{path.name} line {n}: {e}") from None
    return clips


def save_manifest(path: str | Path, clips: list[Clip]) -> None:
    text = "".join(c.to_json() + "\n" for c in clips)
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def _sort_key(c: "Clip") -> tuple:
    prefix, _, num = c.id.partition("-")
    return (prefix, int(num) if num.isdigit() else 0, c.id)


def upsert(clips: list[Clip], clip: Clip) -> list[Clip]:
    """Replace the row with the same id (keeping its texts if the new row has none), else append."""
    out = []
    replaced = False
    for c in clips:
        if c.id == clip.id:
            clip.hy = clip.hy or c.hy
            clip.en = clip.en or c.en
            clip.notes = clip.notes or c.notes
            out.append(clip)
            replaced = True
        else:
            out.append(c)
    if not replaced:
        out.append(clip)
    return sorted(out, key=_sort_key)


def next_id(clips: list[Clip], source: str) -> str:
    prefix = "mic" if source == "mic" else "call"
    used = [_sort_key(c)[1] for c in clips if c.id.startswith(prefix + "-")]
    return f"{prefix}-{(max(used) + 1) if used else 1:02d}"


# ----------------------------------------------------------------- audio helpers

def read_wav(path: Path) -> tuple[np.ndarray, int, int]:
    """-> (float32 samples, rate, channels). Only 16-bit PCM is accepted."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ManifestError(f"{path.name}: expected 16-bit PCM, got {8 * w.getsampwidth()}-bit")
        raw = w.readframes(w.getnframes())
        rate, ch = w.getframerate(), w.getnchannels()
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0, rate, ch


def write_wav(path: Path, y: np.ndarray, rate: int = RATE) -> None:
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def speech_bounds(y: np.ndarray, rate: int = RATE, pad_s: float = 0.25,
                  floor_dbfs: float = -50.0, below_peak_db: float = 35.0) -> tuple[int, int] | None:
    """Sample range covering the voiced part plus padding, or None if nothing is voiced.

    A 20 ms frame counts as voiced when it is louder than both `floor_dbfs` and
    (loudest frame - `below_peak_db`), so quiet rooms and noise suppression both work.
    """
    hop = int(rate * 0.02)
    n = len(y) // hop
    if n == 0:
        return None
    frames = y[: n * hop].reshape(n, hop).astype(np.float64)
    db = 20 * np.log10(np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-12)
    voiced = np.flatnonzero(db > max(floor_dbfs, db.max() - below_peak_db))
    if voiced.size == 0 or db.max() <= floor_dbfs:
        return None
    pad = int(pad_s * rate)
    return max(0, voiced[0] * hop - pad), min(len(y), (voiced[-1] + 1) * hop + pad)


# ----------------------------------------------------------------- validation

@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def check(manifest: str | Path, draft: bool = False) -> Report:
    """Validate the eval set. With `draft`, missing reference texts are warnings, not errors."""
    manifest = Path(manifest)
    r = Report()
    try:
        clips = load_manifest(manifest)
    except ManifestError as e:
        r.errors.append(str(e))
        return r
    if not manifest.exists():
        r.errors.append(f"{manifest} does not exist; record a clip first")
        return r

    seen: set[str] = set()
    durations = []
    for c in clips:
        where = c.id or "<no id>"
        if not ID_PATTERN.match(c.id):
            r.errors.append(f"{where}: id must look like mic-01 or call-01")
        if c.id in seen:
            r.errors.append(f"{where}: duplicate id")
        seen.add(c.id)
        if c.source not in SOURCES:
            r.errors.append(f"{where}: source must be one of {SOURCES}, got {c.source!r}")
        if c.source == "mic" and not c.id.startswith("mic-"):
            r.errors.append(f"{where}: mic clips use the mic- prefix")
        if c.source == "system" and not c.id.startswith("call-"):
            r.errors.append(f"{where}: system-audio clips use the call- prefix")
        if not c.speaker:
            r.errors.append(f"{where}: speaker is empty")

        missing = r.warnings if draft else r.errors
        if not c.hy.strip():
            missing.append(f"{where}: Armenian reference (hy) is empty")
        elif not ARMENIAN.search(c.hy):
            r.errors.append(f"{where}: hy contains no Armenian letters")
        if not c.en.strip():
            missing.append(f"{where}: English reference (en) is empty")
        elif ARMENIAN.search(c.en):
            r.errors.append(f"{where}: en contains Armenian letters; is it in the wrong field?")

        path = manifest.parent / c.audio
        if not path.exists():
            r.errors.append(f"{where}: audio file {c.audio} not found")
            continue
        try:
            y, rate, ch = read_wav(path)
        except (ManifestError, wave.Error, EOFError) as e:
            r.errors.append(f"{where}: unreadable WAV ({e})")
            continue
        if rate != RATE or ch != 1:
            r.errors.append(f"{where}: expected 16 kHz mono, got {rate} Hz {ch} ch")
        actual = len(y) / rate / max(ch, 1)
        durations.append(actual)
        if abs(actual - c.duration_s) > DURATION_TOLERANCE_S:
            r.errors.append(f"{where}: duration_s {c.duration_s} but file is {actual:.2f} s")
        if actual > MAX_CLIP_S:
            r.warnings.append(f"{where}: {actual:.1f} s is longer than {MAX_CLIP_S:.0f} s")
        if y.size and np.abs(y).max() >= 0.999:
            r.warnings.append(f"{where}: clipping detected")

    short = sum(d < SHORT_MAX_S for d in durations)
    long_ = sum(d >= LONG_MIN_S for d in durations)
    if len(clips) < MIN_CLIPS:
        r.warnings.append(f"{len(clips)} clips; target is at least {MIN_CLIPS}")
    if short < MIN_SHORT:
        r.warnings.append(f"{short} clips under {SHORT_MAX_S} s; target is at least {MIN_SHORT}")
    if long_ < MIN_LONG:
        r.warnings.append(f"{long_} clips of {LONG_MIN_S:.0f} s or more; target is at least {MIN_LONG}")
    r.summary = {
        "clips": len(clips),
        "by_source": {s: sum(c.source == s for c in clips) for s in SOURCES},
        "total_s": round(sum(durations), 1),
        f"under_{SHORT_MAX_S}s": short,
        f"{LONG_MIN_S:.0f}s_or_more": long_,
        "with_hy": sum(bool(c.hy.strip()) for c in clips),
        "with_en": sum(bool(c.en.strip()) for c in clips),
    }
    return r
