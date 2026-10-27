import pytest

from armtranslate.mt import Translator, model_dir


def test_model_dir_names():
    assert model_dir("nllb", "int8").name == "nllb-600m-ct2-int8"
    assert model_dir("opus", "float32").name == "opus-mt-hy-en-ct2-float32"


def test_unknown_family():
    with pytest.raises(ValueError):
        Translator("google")


def test_missing_model(tmp_path):
    pytest.importorskip("ctranslate2")
    with pytest.raises(FileNotFoundError):
        Translator("opus", path=tmp_path)
