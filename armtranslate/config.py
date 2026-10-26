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
    end_pause_ms: int = 600                # end of phrase; trades latency vs completeness (Step 8)
    max_segment_s: float = 8.0             # forced cut, keeps monologues within the 5 s budget


@dataclass(frozen=True)
class SpeakerConfig:
    min_segment_s: float = 1.0             # shorter segments are not used to assign a speaker
    similarity_threshold: float | None = None  # to be measured in Step 7
    max_remote_speakers: int = 4           # safety cap; the brief requires at least 2


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
