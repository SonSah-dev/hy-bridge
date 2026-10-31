"""Settings and test assumptions (DECISIONS.md D-010).

Every value here is a provisional default, not a requirement; the challenge brief stays the
source of truth. Defaults can be overridden by a TOML file (see config.example.toml) and then
by `--set section.key=value` on the command line. Unknown sections or keys are an error, so a
typo never silently falls back to a default.
"""
from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

# A device is chosen by: None ("default"), an int (device index) or a str (name substring).
DeviceSpec = int | str | None


@dataclass(frozen=True)
class AudioConfig:
    use_mic: bool = True                   # capture the microphone ("Me")
    use_system: bool = True                # capture system audio (the call, via loopback) (D-019)
    mic_device: DeviceSpec = None          # None = Windows default WASAPI input
    system_device: DeviceSpec = None       # None = loopback of the Windows default output
    sample_rate: int = 16_000              # pipeline format: mono float32 at this rate
    block_ms: int = 20                     # capture callback size
    fill_gaps: bool = True                 # insert silence when loopback stops delivering data
    gap_threshold_ms: int = 200            # missing audio longer than this counts as a gap;
                                           # must exceed normal callback jitter (Step 1 measures it)
    queue_seconds: float = 10.0            # buffered audio per source before chunks are dropped


@dataclass(frozen=True)
class SegmentationConfig:
    end_pause_ms: int = 1000               # end of phrase; 600 split spontaneous sentences (D-016)
    max_segment_s: float = 6.0             # forced cut, keeps monologues within the 5 s budget (D-031)
    vad_threshold: float = 0.5             # Silero speech probability that starts speech
    pre_roll_ms: int = 200                 # audio kept before speech onset, so first syllables survive
    min_speech_ms: int = 250               # shorter voiced bursts (clicks, coughs) are dropped


@dataclass(frozen=True)
class AsrConfig:
    threads: int = 2                       # onnxruntime intra-op threads; 2 beat the default (D-013)
    unclear_mean_logprob: float | None = -0.3   # mean token log-prob below this: "[unclear]" (D-022)
    unclear_low_share: float | None = 0.15      # or this share of tokens under p=0.5; None = off


@dataclass(frozen=True)
class MtConfig:
    family: str = "nllb"                   # "nllb" (CC-BY-NC) or "opus" (Apache-2.0, weaker) (D-015)
    compute: str = "int8"                  # converted weights: "int8" or "float32"
    size: str = "1.3b"                     # NLLB size: "1.3b" (FLEURS chrF 64.6) or "600m" (60.8) (D-028)
    no_repeat_ngram: int = 4               # never repeat a 4-gram while decoding (stops loops); 0 = off
    beam_size: int = 2
    short_beam_size: int = 4               # for 1-3 word segments not in the phrasebook (D-017)
    threads: int = 4
    repeat_min_run: int | None = 3         # output phrase repeated this often in a row (and 2 more
                                           # than in the source): "[unclear]"; None = off (D-023)
    block_profanity: bool = True           # vulgar English output -> "[unclear]" (D-026)
    deadline_s: float | None = 4.5         # last voice -> English; a translation predicted to finish
                                           # later goes to the fallback model; None = off (D-031)
    fallback_size: str = "600m"            # NLLB size used then; "" = no fallback (D-031)


@dataclass(frozen=True)
class TextConfig:
    glossary: str = "glossary.tsv"         # Armenian-letter spellings -> terms, applied before MT; "" = off
    numbers_to_digits: bool = True         # spelled-out numbers >= 10 become digits before MT
    phrasebook: str = "phrasebook.tsv"     # short replies translated directly; "" = off (D-017)
    names: str = "names.tsv"               # names -> Latin letters before MT; "" = off (D-021)
    gazetteer: str = ""                    # "gazetteer.tsv" = Wikidata names; off: no gain with 1.3B (D-028)
    min_letters: int = 2                   # segments with fewer Armenian letters are not shown


@dataclass(frozen=True)
class SpeakerConfig:
    enabled: bool = True                   # false: system audio is labelled "Remote" (D-020)
    min_segment_s: float = 1.0             # shorter segments never create or move a speaker
    new_speaker_min_s: float = 2.0         # shorter segments may join a speaker, never start one (D-020)
    similarity_threshold: float = 0.35     # cosine to a speaker's centroid; tuned on the test call (D-020)
    short_threshold: float | None = None   # for shorter segments; None = similarity_threshold
    max_remote_speakers: int = 4           # safety cap; the brief requires at least 2
    threads: int = 2                       # onnxruntime threads for the speaker embedding


@dataclass(frozen=True)
class ScenarioConfig:
    """Describes the test/interview setup. Recorded in reports; no code branches on it."""
    remote_participants: int = 2
    separate_devices: bool = True
    turn_taking: bool = True
    call_app: str = "unspecified"
    output_setup: str = "unspecified"      # e.g. "headphones", "speakers"


@dataclass(frozen=True)
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    segmentation: SegmentationConfig = field(default_factory=SegmentationConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    mt: MtConfig = field(default_factory=MtConfig)
    text: TextConfig = field(default_factory=TextConfig)
    speakers: SpeakerConfig = field(default_factory=SpeakerConfig)
    scenario: ScenarioConfig = field(default_factory=ScenarioConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_device(value: Any) -> DeviceSpec:
    """'default'/''/None -> None, digits -> index, anything else -> name substring."""
    if value is None or isinstance(value, int):
        return value
    s = str(value).strip()
    if s == "" or s.lower() == "default":
        return None
    return int(s) if s.isdigit() else s


def _coerce(section: str, key: str, value: Any, current: Any) -> Any:
    if key.endswith("_device"):
        return parse_device(value)
    if isinstance(value, str) and not isinstance(current, str):
        value = _parse_scalar(value)
    if isinstance(current, bool) and not isinstance(value, bool):
        raise ValueError(f"{section}.{key} must be true or false, got {value!r}")
    if isinstance(current, float) and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    return value


def _parse_scalar(s: str) -> Any:
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if s.lower() in ("none", "null"):
        return None
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    return s


def _apply(cfg: Config, section: str, values: dict[str, Any], origin: str) -> Config:
    sections = {f.name for f in fields(Config)}
    if section not in sections:
        raise ValueError(f"{origin}: unknown section [{section}]; expected one of {sorted(sections)}")
    sub = getattr(cfg, section)
    known = {f.name for f in fields(sub)}
    updates = {}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"{origin}: unknown key {section}.{key}; expected one of {sorted(known)}")
        updates[key] = _coerce(section, key, value, getattr(sub, key))
    return replace(cfg, **{section: replace(sub, **updates)})


def load_config(path: str | Path | None = None, overrides: list[str] | None = None) -> Config:
    cfg = Config()
    if path is not None:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        for section, values in data.items():
            if not isinstance(values, dict):
                raise ValueError(f"{path}: top-level key {section!r} must be a [section]")
            cfg = _apply(cfg, section, values, str(path))
    for item in overrides or []:
        name, sep, raw = item.partition("=")
        section, dot, key = name.strip().partition(".")
        if not sep or not dot:
            raise ValueError(f"--set expects section.key=value, got {item!r}")
        cfg = _apply(cfg, section, {key: raw.strip()}, "--set")
    return cfg
