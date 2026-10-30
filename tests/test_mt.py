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


# ----------------------------------------------------------------- repetition guard (D-023)
from armtranslate.mt import is_degenerate, repeat_run  # noqa: E402

# Real NLLB loops from logged runs (tuning data); the Armenian sources had no repetition.
LOOPS = [
    ("Հլավ,, հլա, այդիկե միդե դ այս կին, հյուրուտի, տեսուս Դայ էնյուջո։", "Well, " * 40 + "well"),
    ("Ի ջան, հը լավ գո, հետի որ գոհա ջան, էն անուններ չգիտի, դամ էլ, որ։",
     "Oh, yeah, yeah, yeah, yeah, yeah, yeah, yeah, yeah."),
    ("Աքատամ շատ լավ Սոն ա ջան գրիլա Սոնա Ան, հիմա այդ օրինակ՝ էս ինչ ջան։",
     "I'm good at that. Sonja, sonja, sonja, sonja, sonja."),
    ("Լավան, ինչպես ես հա արյու, լավ դուք ինչ եք վարել հայ հա արյուր։",
     "Lavan, like me, what have you done, what have you done, what have you done, I'm good."),
    ("Հլավ, օ հլա, այդ միդե այս գն, հյուրուի, դ Դահնյուջոզի։", "Oh, oh, oh, that's the price, the guest."),
]

# Correct translations that repeat: real repetition in the Armenian, or a mild x2.
VALID = [
    ("Այո, այո, այո, հասկացա։", "Yes, yes, yes, I got it."),
    ("Մի րոպե, մի րոպե, մի րոպե, ես չհասկացա։", "One minute, one minute, one minute, I didn't understand."),
    ("Ես աշխատում եմ, աշխատում եմ, աշխատում եմ։", "I'm working, I'm working, I'm working."),
    ("Շնորհակալություն, շնորհակալություն, շատ շնորհակալություն։",       # source x2, output x3
     "Thank you, thank you, thank you very much."),
    ("Հա, հա, հա, շատ ծիծաղելի է։", "Oh, oh, oh, oh, that is so ridiculous."),    # source x3, output x4
    ("Շնորհակալություն։", "Thank you. Thank you."),                       # NLLB x2 (mic-04): left alone
    ("Շատ, շատ լավ էր։", "It was very, very good."),
    ("Մեկ, երկու, երեք, չորս, հինգ։", "One, two, three, four, five."),
    ("Ես", "Yes."),
    ("", ""),
]


@pytest.mark.parametrize("hy, en", LOOPS)
def test_loops_are_degenerate(hy, en):
    assert is_degenerate(hy, en)


@pytest.mark.parametrize("hy, en", VALID)
def test_valid_repetition_is_kept(hy, en):
    assert not is_degenerate(hy, en)


def test_repeat_run():
    assert repeat_run("Well, well, WELL.") == 3
    assert repeat_run("what have you done, what have you done") == 2      # a 4-word phrase
    assert repeat_run("a b a b a b") == 3
    assert repeat_run("one two three") == 1 and repeat_run("") == 1
    assert repeat_run("Այո, այո") == 2                                     # Armenian words too
