from pathlib import Path

import pytest

from armtranslate.textfix import TextFixer, apply_glossary, apply_names, load_glossary, numbers_to_digits

ROOT = Path(__file__).resolve().parent.parent
GLOSSARY = load_glossary(ROOT / "glossary.tsv")


@pytest.mark.parametrize("asr, fixed", [
    ("փայթենը օգտագործում եմ", "Python-ը օգտագործում եմ"),
    ("աշխատել եմ ամազոնում և գուգլում", "աշխատել եմ Amazon-ում և Google-ում"),
    ("վերժեն քընթրոլի համար", "version control-ի համար"),
    ("մեծ փրադաքշ պրոյեկտներում", "մեծ production պրոյեկտներում"),
    ("Գիթը", "Git-ը"),
    ("գիթար", "գիթար"),                 # unknown ending: not a glossary word
])
def test_glossary(asr, fixed):
    assert apply_glossary(asr, GLOSSARY) == fixed


@pytest.mark.parametrize("text, expected", [
    ("երկու հազար քսաներկու թվականի", "2022 թվականի"),
    ("երկուազար քսաներկու թվականի", "2022 թվականի"),
    ("հիսուն հոգուց", "50 հոգուց"),
    ("երեք հարյուր հինգ", "305"),
    ("հազար ինը հարյուր իննսունինը", "1999"),
    ("չորս տարի", "չորս տարի"),          # under 10: left as words
    ("մեկ հարց", "մեկ հարց"),
    ("տասներկու, քսան", "12, 20"),
    ("քսան հինգ", "25"),
    ("երկու երեք", "երկու երեք"),
])
def test_numbers(text, expected):
    assert numbers_to_digits(text) == expected


def test_bad_glossary_line(tmp_path):
    f = tmp_path / "g.tsv"
    f.write_text("no tab here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_glossary(f)


def test_fixer_off():
    assert TextFixer(None, numbers=False)("երկու հազար") == "երկու հազար"


def test_armenian_punctuation_is_a_boundary():
    assert apply_glossary("եւ՛ Գուգլում՝ երեք", GLOSSARY) == "եւ՛ Google-ում՝ երեք"
    assert numbers_to_digits("հիսուն՝") == "50՝"


# Cases from the live Step 5 runs (D-017): ASR variants must convert correctly or not at all.
@pytest.mark.parametrize("text, expected", [
    ("Տասներեք հազար ութ հարյուր քառասոուն։", "13840։"),                   # քառասոուն ~ քառասուն
    ("հազար ին հարյուր ութսունութ թվականին", "1988 թվականին"),              # ին ~ ինը before a scale
    ("Հազար ինը հարյուր ութսանութ թվականին", "1988 թվականին"),              # ութսանութ ~ ութսունութ
    ("Ես քսանուերեք տարեկան", "Ես 23 տարեկան"),                             # tens + ու + ones
    ("պարունակում է հինինգ հարյուր յոթանասուն հազար բառ",                    # stutter: leave the words
     "պարունակում է հինինգ հարյուր յոթանասուն հազար բառ"),
    ("Մոտակա տասներեք ժամը", "Մոտակա 13 ժամը"),
    ("երեկ եկավ", "երեկ եկավ"),                                              # yesterday is not three
])
def test_numbers_live_cases(text, expected):
    assert numbers_to_digits(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Այստեղ խոսացողի համար։", "Այստեղ խոսացողի համար։"),   # համար ("for") is not հազար
    ("քառասոուն", "քառասոուն"),                              # a lone variant is not converted
])
def test_numbers_no_false_variants(text, expected):
    assert numbers_to_digits(text) == expected


@pytest.mark.parametrize("asr, fixed", [                       # live run 2026-10-27 21:45 (D-018)
    ("Գիթը օգտագործվում է վեժին քընթրոլի համար։", "Git-ը օգտագործվում է version control-ի համար։"),
    ("Վժըն քընթռոլ։", "version control։"),
    ("Ամազո՞։", "Amazon՞։"),
    ("Հայայիթենը օգտագործում եմ", "Python-ը օգտագործում եմ"),
    ("ինչպես ջավասքրփթ է", "ինչպես JavaScript է"),
    ("գիծը", "գիծը"),                                            # short entries stay exact: not Git
    ("Ամառն էր", "Ամառն էր"),                                     # not Amazon
])
def test_glossary_fuzzy(asr, fixed):
    assert apply_glossary(asr, GLOSSARY) == fixed


def test_glossary_fuzzy_false_positive_from_replay():
    assert apply_glossary("Այնին աշխատանքը", GLOSSARY) == "Այնին աշխատանքը"   # not Python
    assert apply_glossary("Այթինը ծրագրավորման լեզու է", GLOSSARY) == "Python-ը ծրագրավորման լեզու է"


# ----------------------------------------------------------------- names (D-021)
NAMES = load_glossary(ROOT / "names.tsv")


@pytest.mark.parametrize("asr, fixed", [
    ("Առայժմ Սաթթենիկ ջան։", "Առայժմ Satenik։"),                 # misspelt, ջան dropped
    ("Ես Լուսինեն եմ։", "Ես Lusine-ն եմ։"),                          # ending kept
    ("Լավ Գոհա ջան, դուք մեզ լսո՞ւմ եք։", "Լավ Gohar, դուք մեզ լսո՞ւմ եք։"),
    ("Բարեւ, Սոնաջան։", "Բարեւ, Sona։"),                              # glued endearment
    ("քո եւ Սաթենիկի զրույցը", "քո եւ Satenik-ի զրույցը"),
    ("քաղաք Վանաձորից", "քաղաք Vanadzor-ից"),
    ("Մամ ջան։", "Մամ ջան։"),                                          # not a name: left alone
    ("Կրթությունս Հայաստանի", "Կրթությունս Հայաստանի"),               # NLLB knows it: not listed
])
def test_names(asr, fixed):
    assert apply_names(asr, NAMES) == fixed


def test_names_short_entries_exact_only():
    assert apply_names("Սոնի", NAMES) == "Սոնի"          # 4-letter Սոնա: no fuzzy match


def test_textfixer_applies_names_after_glossary():
    fix = TextFixer(ROOT / "glossary.tsv", names=ROOT / "names.tsv")
    assert fix("Սաթենիկ ջան, փայթենը գիտես՞") == "Satenik, Python-ը գիտես՞"


def test_held_out_false_matches_are_blocked():          # FLEURS test split (D-024)
    assert apply_glossary("Լայթեն վարչապետի հետ", GLOSSARY) == "Լայթեն վարչապետի հետ"   # Layton, not Python
    assert apply_names("ինչպես լուսինն է ձգողության", NAMES) == "ինչպես լուսինն է ձգողության"  # the moon
    assert apply_names("Լուսինն էլ", NAMES) == "Lusine էլ"                              # capitalised: a name


# ----------------------------------------------------------------- clock times (D-025)
from armtranslate.textfix import times_to_digits  # noqa: E402


@pytest.mark.parametrize("asr, fixed", [
    ("Ժամը ութն անց կես է։", "Ժամը 8:30 է։"),
    ("ութն անց երեսուն", "8:30"),
    ("ութն անց երեսուն երկու", "8:32"),
    ("Ժամը ինն անց քառորդին կհանդիպենք։", "Ժամը 9:15-ին կհանդիպենք։"),
    ("տասներկուսն անց տասը", "12:10"),
    ("մեկն անց կեսին", "1:30-ին"),
    ("երեք օր անց", "երեք օր անց"),                      # "three days later": not a time
    ("երկու ժամ անց կգամ", "երկու ժամ անց կգամ"),
    ("նա անց կացրեց", "նա անց կացրեց"),
    ("Ուութթանց կես։", "Ուութթանց կես։"),                 # garbled hour (live run): left alone
])
def test_times(asr, fixed):
    assert times_to_digits(asr) == fixed


def test_textfixer_converts_times_before_numbers():
    assert TextFixer(None)("Ժամը ութն անց երեսուն է։") == "Ժամը 8:30 է։"
    assert TextFixer(None, numbers=False)("ութն անց կես") == "ութն անց կես"


@pytest.mark.parametrize("asr, fixed", [
    ("մոտեցեք ութանց կես։", "մոտեցեք 8:30։"),           # hour glued onto անց (mic test, D-026)
    ("մոտեցեք ութնանց կես։", "մոտեցեք 8:30։"),
    ("իննանց քառորդին", "9:15-ին"),
    ("կանանց կես", "կանանց կես"),                         # "of women": not an hour
])
def test_glued_times(asr, fixed):
    assert times_to_digits(asr) == fixed


def test_kog_after_number_is_kg():
    fix = TextFixer(None)
    assert fix("980 կոգ։") == "980 կգ։" and fix("Յոթ հարյուր կոգ։") == "700 կգ։"
    assert fix("կոգ") == "կոգ"                            # only after a number


# ----------------------------------------------------------------- gazetteer (D-026)
from armtranslate.textfix import Gazetteer  # noqa: E402


@pytest.fixture
def gaz(tmp_path):
    f = tmp_path / "g.tsv"
    f.write_text("# test\nԴսեղ\tDsegh\tplace\nՀովհաննես Թումանյան\tHovhannes Tumanyan\tperson\n"
                 "Թումանյան\tTumanyan\tsurname\nՀովհաննես\tHovhannes\tgiven\nԼոռու մարզ\tLori Province\tplace\n"
                 "Արեւ\tArev\tplace\nԱն\tAn\tplace\n", encoding="utf-8")
    return Gazetteer(f)


@pytest.mark.parametrize("asr, fixed", [
    ("Թումանյանը ծնվել է Դսեղ գյուղում։", "Թումանյանը ծնվել է Dsegh գյուղում։"),   # first word: skipped
    ("Մեծ գրող Հովհաննես Թումանյանը ծնվել է։", "Մեծ գրող Hovhannes Tumanyan-ը ծնվել է։"),
    ("Հովհաննես Թումանյանը ծնվել է։", "Hovhannes Tumanyan-ը ծնվել է։"),           # two words: allowed first
    ("Ես Լոռու մարզից եմ։", "Ես Lori Province-ից եմ։"),
    ("Այսօր Արեւը պայծառ է։", "Այսօր Arev-ը պայծառ է։"),                           # capitalised mid-sentence
    ("Արեւը ծագեց։", "Արեւը ծագեց։"),                                             # sentence start: common word
    ("այսօր արեւը պայծառ է", "այսօր արեւը պայծառ է"),                             # lower case: never
    ("Ասաց Ան։", "Ասաց Ան։"),                                                     # under 4 letters
])
def test_gazetteer(gaz, asr, fixed):
    assert gaz(asr) == fixed


def test_gazetteer_after_names_and_glossary(tmp_path, gaz):
    fix = TextFixer(ROOT / "glossary.tsv", names=ROOT / "names.tsv")
    fix.gazetteer = gaz
    assert fix("Բարեւ Սաթենիկ ջան, դու Դսեղից ես՞") == "Բարեւ Satenik, դու Dsegh-ից ես՞"


def test_gazetteer_off():
    assert Gazetteer(None)("Ես Դսեղից եմ") == "Ես Դսեղից եմ"


@pytest.mark.parametrize("asr, fixed", [                 # NLLB: դրամ -> "drachmas"; AMD stays (D-029)
    ("Սուրճն արժե 500 դրամ։", "Սուրճն արժե 500 AMD։"),
    ("Մեկ դոլարն արժե երեք հարյուր իննսուն դրամ։", "Մեկ դոլարն արժե 390 AMD։"),
    ("Գնեցի 2000 դրամով։", "Գնեցի 2000 AMD-ով։"),
    ("Դրամ չունեմ։", "Դրամ չունեմ։"),                     # "money": no number, left alone
    ("500 դրամատուն", "500 դրամատուն"),                   # another word
])
def test_dram_after_number_is_amd(asr, fixed):
    assert TextFixer(None)(asr) == fixed


@pytest.mark.parametrize("asr", ["Հարեւ ձեզ։", "Պարեւ ձեզ։", "Տարեւ ձեզ։", "Վարեւ ձեզ։", "Այարեւ ձեզ։",
                                 "Հարարեւ ձեզ։", "Այեւ ձեզ։", "պարեւ ձեզ", "Բարեւ ձեզ։"])
def test_clipped_greeting_is_restored(asr):              # the mic's gate cuts the start of Բ (D-032)
    from armtranslate.textfix import fix_greeting
    assert fix_greeting(asr).lower().startswith("բարեւ ձեզ")


def test_greeting_keeps_the_rest():
    from armtranslate.textfix import fix_greeting
    assert fix_greeting("Պարեւ ձեզ Սաթենիկ ջան։") == "Բարեւ ձեզ Սաթենիկ ջան։"


@pytest.mark.parametrize("text", ["Ձեզ եւս։", "Թերեւս ձեզ համար։", "Երեւ ձեզ։", "Ես Պարեւ ձեզ ասացի։",
                                  "Հարեւան ձեզ։", "Պարեւ ձեզանից։", "Պարեւ։"])
def test_greeting_fix_leaves_other_text(text):
    from armtranslate.textfix import fix_greeting
    assert fix_greeting(text) == text


@pytest.mark.parametrize("asr", ["Հեւ ձեզ։", "Հեք ձեզ։", "Հեց ձեզ։", "Հովհեւ ծեզ։", "Պարեւ ծեզ։"])
def test_more_clipped_greetings_are_restored(asr):   # live 2026-11-01 (D-032)
    from armtranslate.textfix import fix_greeting
    assert fix_greeting(asr) == "Բարեւ ձեզ։"


@pytest.mark.parametrize("text", ["Նաեւ ձեզ։", "Հեւ։", "Հեւալով ձեզ մոտ եկա։", "Հեքիաթ ձեզ համար։"])
def test_real_phrases_near_greeting_stay(text):
    from armtranslate.textfix import fix_greeting
    assert fix_greeting(text) == text


@pytest.mark.parametrize("text, noise", [("Հովհ։", True), ("Հովհ.", True), ("«Հովհ է։", True), ("Հովհ ծ։", True),
                                         ("Հովհաննես։", False), ("Հովհ, ինչպես ես։", False)])
def test_bare_hovh_is_noise(text, noise):
    from armtranslate.textfix import is_noise
    assert is_noise(text) == noise
