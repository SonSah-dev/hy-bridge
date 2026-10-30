from pathlib import Path

import pytest

from armtranslate.phrasebook import Phrasebook, transliterate

ROOT = Path(__file__).resolve().parent.parent
PB = Phrasebook(ROOT / "phrasebook.tsv")


@pytest.mark.parametrize("hy, en", [
    ("Հաջողություն։", "Good luck."),
    ("Ողջույն Սոնա ջան։", "Hello, Sona."),
    ("Ողջույն, Սանաան։", "Hello, Sanaan."),
    ("Այո, իհարկե։", "Yes, of course."),
    ("Շնորհակալություն։", "Thank you."),
    ("Չէ։", "No."),
    ("Ջան.", "Dear."),
    ("Մամ ջան։", "Mom."),
    ("Բարև ձեզ", "Hello."),
    ("Ողջույն Սոնաջան։", "Hello, Sona."),                 # ջան glued on by the ASR
    ("Առայժմ Satenik։", "Bye for now, Satenik."),       # name already in Latin (names.tsv)
    ("Կգ։", "kg."),                                     # unit alone; NLLB invented a question (D-025)
    ("Տոկոս։", "Percent."),
])
def test_lookup(hy, en):
    assert PB.lookup(hy) == en


@pytest.mark.parametrize("hy", [
    "Արամ ջան։",                                  # a name alone is not a phrase: falls back to MT
    "Ողջույն ինչ ես անում",                       # lower-case words after a greeting are not names
    "Նոր տարբերակը տալիս է հնարավորություններ։",  # too long
])
def test_no_match(hy):
    assert PB.lookup(hy) is None


@pytest.mark.parametrize("hy, en", [("Սոնա", "Sona"), ("Երևան", "Yerevan"), ("Անահիտ", "Anahit"),
                                    ("Ոսկան", "Voskan"), ("Գյումրի", "Gyumri"), ("Արթուր", "Artur")])
def test_transliterate(hy, en):
    assert transliterate(hy) == en


def test_bad_line(tmp_path):
    f = tmp_path / "p.tsv"
    f.write_text("no tab\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Phrasebook(f)
