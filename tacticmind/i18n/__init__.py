"""Tłumaczenia interfejsu (i18n).

Każdy język to osobny moduł z jednym słownikiem ``STRINGS`` (klucz → tekst
z polami ``{nazwa}``). Żeby dodać język, wystarczy skopiować ``en.py`` jako np.
``de.py``, przetłumaczyć wartości i dopisać kod języka do ``LANGUAGES``.

Użycie::

    from tacticmind.i18n import t, tn
    t("play.best_move")                      # „Najlepszy ruch!” / “Best move!”
    t("thought.same", d=4, move="Hxf7+", score="+3.2")
    tn("reason.easier", 3)                   # liczba mnoga zależna od języka
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from . import en, pl

#: Dostępne języki: kod → (nazwa własna, moduł z tekstami).
LANGUAGES: dict[str, tuple[str, ModuleType]] = {
    "pl": ("Polski", pl),
    "en": ("English", en),
}
DEFAULT_LANGUAGE = "pl"

_language = DEFAULT_LANGUAGE
_listeners: list[Callable[[str], None]] = []


def set_language(code: str) -> None:
    """Zmienia język całej aplikacji (nieznany kod = język domyślny)."""
    global _language
    code = code if code in LANGUAGES else DEFAULT_LANGUAGE
    if code == _language:
        return
    _language = code
    for listener in list(_listeners):
        listener(code)


def get_language() -> str:
    return _language


def on_change(listener: Callable[[str], None]) -> None:
    """Rejestruje funkcję wywoływaną po zmianie języka."""
    _listeners.append(listener)


def _strings(code: str) -> dict[str, str]:
    strings: dict[str, str] = LANGUAGES[code][1].STRINGS
    return strings


def has(key: str) -> bool:
    return key in _strings(_language) or key in _strings(DEFAULT_LANGUAGE)


def t(key: str, **params: object) -> str:
    """Tekst w bieżącym języku. Brakujący klucz: tekst polski, a w ostateczności sam klucz."""
    text = _strings(_language).get(key) or _strings(DEFAULT_LANGUAGE).get(key) or key
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def plural_form(n: int, code: str | None = None) -> str:
    """Forma liczby mnogiej: 'one' | 'few' | 'many' (polski ma trzy formy, angielski dwie)."""
    code = code or _language
    n = abs(n)
    if code == "pl":
        if n == 1:
            return "one"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    return "one" if n == 1 else "many"


def tn(key: str, n: int, **params: object) -> str:
    """Tekst z liczbą: szuka klucza ``key.one`` / ``key.few`` / ``key.many``."""
    form = plural_form(n)
    for candidate in (f"{key}.{form}", f"{key}.many", key):
        if has(candidate):
            return t(candidate, n=n, **params)
    return key


def fmt_decimal(value: float, digits: int = 1) -> str:
    """Liczba dziesiętna z separatorem właściwym dla języka (12,5 / 12.5)."""
    text = f"{value:.{digits}f}"
    return text.replace(".", t("fmt.decimal"))


def fmt_int(value: int) -> str:
    """Liczba całkowita z separatorem tysięcy (12 345 / 12,345)."""
    return f"{value:,}".replace(",", t("fmt.thousands_sep"))


def fmt_compact(value: float) -> str:
    """Krótki zapis dużych liczb: 12,3 tys. / 12.3k, 1,23 mln / 1.23M."""
    if value >= 1_000_000:
        return fmt_decimal(value / 1_000_000, 2) + t("fmt.millions")
    if value >= 10_000:
        return fmt_decimal(value / 1000, 1) + t("fmt.thousands")
    return fmt_int(int(value))
