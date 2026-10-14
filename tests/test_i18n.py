"""Tłumaczenia: komplet kluczy w każdym języku, liczba mnoga, formaty liczb, notacja."""

import re

import pytest

from taktykai.brain.notation import localize_san
from taktykai.i18n import LANGUAGES, en, fmt_compact, fmt_decimal, pl, plural_form, set_language, t, tn


def _base_keys(strings: dict[str, str]) -> set[str]:
    """Klucze bez końcówek liczby mnogiej (.one/.few/.many) — każdy język ma ich inny zestaw."""
    return {re.sub(r"\.(one|few|many)$", "", key) for key in strings}


@pytest.mark.parametrize("code", list(LANGUAGES))
def test_every_language_has_every_key(code: str) -> None:
    strings = LANGUAGES[code][1].STRINGS
    assert _base_keys(strings) == _base_keys(pl.STRINGS)


@pytest.mark.parametrize("code", list(LANGUAGES))
def test_placeholders_match_polish(code: str) -> None:
    strings = LANGUAGES[code][1].STRINGS
    for key, text in strings.items():
        reference = pl.STRINGS.get(key) or pl.STRINGS.get(re.sub(r"\.(one|few)$", ".many", key), "")
        assert set(re.findall(r"{(\w+)}", text)) == set(re.findall(r"{(\w+)}", reference)), key


def test_switching_language() -> None:
    assert t("play.best_move") == "Najlepszy ruch!"
    set_language("en")
    assert t("play.best_move") == "Best move!"
    assert t("thought.same", d=4, move="Qxf7+", score="+3.2") == "Depth 4: still Qxf7+ (+3.2)."
    set_language("xx")  # nieznany język = domyślny
    assert t("play.best_move") == "Najlepszy ruch!"


def test_plural_forms() -> None:
    assert [plural_form(n, "pl") for n in (1, 2, 4, 5, 12, 22, 25)] == ["one", "few", "few", "many", "many", "few", "many"]
    assert tn("reason.easier", 3).startswith("3 porażki")
    assert tn("reason.easier", 5).startswith("5 porażek")
    set_language("en")
    assert tn("reason.easier", 1).startswith("1 failure in")
    assert tn("reason.easier", 3).startswith("3 failures")


def test_number_formats_and_notation() -> None:
    assert fmt_decimal(12.5) == "12,5"
    assert fmt_compact(12_345) == "12,3 tys."
    assert localize_san("Qxf7+") == "Hxf7+"
    set_language("en")
    assert fmt_decimal(12.5) == "12.5"
    assert fmt_compact(1_234_567) == "1.23M"
    assert localize_san("Qxf7+") == "Qxf7+"
    assert localize_san("Nf3", "pl") == "Sf3"
    assert en.STRINGS["notation.pieces"] == "KQRBN"
