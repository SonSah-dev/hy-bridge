from pathlib import Path

import pytest

from armtranslate.config import Config, load_config, parse_device

ROOT = Path(__file__).resolve().parent.parent


def test_defaults_match_d010():
    c = Config()
    assert c.audio.mic_device is None and c.audio.system_device is None
    assert c.segmentation.end_pause_ms == 1000   # D-010 default 600, changed by D-016
    assert c.segmentation.max_segment_s == 8.0
    assert c.speakers.min_segment_s == 1.0
    assert c.speakers.similarity_threshold is None
    assert c.speakers.max_remote_speakers == 4
    assert c.scenario.remote_participants == 2 and c.scenario.separate_devices


def test_example_file_loads_to_defaults():
    assert load_config(ROOT / "config.example.toml") == Config()


@pytest.mark.parametrize("raw, expected", [
    (None, None), ("default", None), ("", None), ("3", 3), (3, 3), ("Headset", "Headset"),
])
def test_parse_device(raw, expected):
    assert parse_device(raw) == expected


def test_overrides(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[audio]\nsystem_device = "Realtek"\n[speakers]\nmin_segment_s = 2\n', encoding="utf-8")
    c = load_config(f, ["audio.mic_device=5", "speakers.similarity_threshold=0.7",
                        "audio.fill_gaps=false", "scenario.call_app=Zoom"])
    assert c.audio.system_device == "Realtek"
    assert c.audio.mic_device == 5
    assert c.speakers.min_segment_s == 2.0
    assert c.speakers.similarity_threshold == 0.7
    assert c.audio.fill_gaps is False
    assert c.scenario.call_app == "Zoom"


@pytest.mark.parametrize("override", ["audio.mic=1", "nope.key=1", "audio.fill_gaps=maybe", "novalue"])
def test_bad_overrides_are_errors(override):
    with pytest.raises(ValueError):
        load_config(None, [override])


def test_both_sources_on_by_default():
    a = Config().audio
    assert a.use_mic and a.use_system
    assert load_config(None, ["audio.use_system=false"]).audio.use_system is False
