import pytest

from armtranslate.scoring import char_errors, edit_distance, normalize, number_to_hy, word_errors


@pytest.mark.parametrize("n, words", [
    (0, "զրո"), (4, "չորս"), (10, "տասը"), (12, "տասներկու"), (21, "քսանմեկ"),
    (50, "հիսուն"), (100, "հարյուր"), (305, "երեք հարյուր հինգ"),
    (1000, "հազար"), (2022, "երկու հազար քսաներկու"), (1999, "հազար ինը հարյուր իննսունինը"),
])
def test_number_to_hy(n, words):
    assert number_to_hy(n) == words


def test_number_out_of_range():
    with pytest.raises(ValueError):
        number_to_hy(1_000_000)


def test_normalize_punctuation_case_and_ligature():
    assert normalize("Բարև, ես ծրագրավորող եմ։") == "բարեւ ես ծրագրավորող եմ"
    assert normalize("Կկրկնե՞ք։") == "կկրկնեք"


def test_digits_equal_number_words():
    assert char_errors("արդեն 4 տարի։", "արդեն չորս տարի") == (0, len("արդեն չորս տարի"))


def test_latin_kept():
    assert normalize("AI/ML production") == "ai ml production"


def test_edit_distance_and_rates():
    assert edit_distance("abc", "axc") == 1
    assert edit_distance("", "ab") == 2
    assert word_errors("ես եմ", "ես էի") == (1, 2)
