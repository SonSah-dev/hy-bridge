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


class FakeTranslator:
    def __init__(self):
        self.calls = []

    def translate(self, text, beam_size=None):
        self.calls.append((text, beam_size))
        return "MT"


def test_segment_translator_routes_by_length(tmp_path):
    from armtranslate.mt import SegmentTranslator
    from armtranslate.phrasebook import Phrasebook
    pb = tmp_path / "p.tsv"
    pb.write_text("հաջողություն\tGood luck.\n", encoding="utf-8")
    fake = FakeTranslator()
    st = SegmentTranslator(fake, Phrasebook(pb), short_beam=4)
    assert st("Հաջողություն։") == "Good luck." and fake.calls == []
    st("Արամ ջան։")
    assert fake.calls[-1] == ("Արամ ջան.", 4)                   # short: wider beam, ։ -> .
    long = "Նոր տարբերակը տալիս է հնարավորություններ։"
    st(long)
    assert fake.calls[-1] == (long, None)                       # long: unchanged, default beam


def test_bare_number_not_sent_to_mt():
    from armtranslate.mt import SegmentTranslator
    fake = FakeTranslator()
    assert SegmentTranslator(fake)("13840։") == "13840." and fake.calls == []
