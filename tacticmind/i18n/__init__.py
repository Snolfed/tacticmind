"""User interface translations (i18n).

Each language is a separate module with a single ``STRINGS`` dictionary (key → text
with ``{name}`` fields). To add a language, copy ``en.py`` as e.g. ``de.py``,
translate the values and add the language code to ``LANGUAGES``.

Usage::

    from tacticmind.i18n import t, tn
    t("play.best_move")                      # "Best move!" / "Najlepszy ruch!"
    t("thought.same", d=4, move="Qxf7+", score="+3.2")
    tn("reason.easier", 3)                   # language-dependent plural
"""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from . import en, pl

#: Available languages: code → (native name, module with the texts).
LANGUAGES: dict[str, tuple[str, ModuleType]] = {
    "en": ("English", en),
    "pl": ("Polski", pl),
}
DEFAULT_LANGUAGE = "en"

_language = DEFAULT_LANGUAGE
_listeners: list[Callable[[str], None]] = []


def set_language(code: str) -> None:
    """Change the language of the whole application (unknown code = default language)."""
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
    """Register a function to be called after the language changes."""
    _listeners.append(listener)


def _strings(code: str) -> dict[str, str]:
    strings: dict[str, str] = LANGUAGES[code][1].STRINGS
    return strings


def has(key: str) -> bool:
    return key in _strings(_language) or key in _strings(DEFAULT_LANGUAGE)


def t(key: str, **params: object) -> str:
    """Text in the current language. Missing key: the default-language text, or as a last resort the key itself."""
    text = _strings(_language).get(key) or _strings(DEFAULT_LANGUAGE).get(key) or key
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def plural_form(n: int, code: str | None = None) -> str:
    """Plural form: 'one' | 'few' | 'many' (Polish has three forms, English two)."""
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
    """Text with a number: looks up the key ``key.one`` / ``key.few`` / ``key.many``."""
    form = plural_form(n)
    for candidate in (f"{key}.{form}", f"{key}.many", key):
        if has(candidate):
            return t(candidate, n=n, **params)
    return key


def fmt_decimal(value: float, digits: int = 1) -> str:
    """Decimal number with the language's decimal separator (12.5 / 12,5)."""
    text = f"{value:.{digits}f}"
    return text.replace(".", t("fmt.decimal"))


def fmt_int(value: int) -> str:
    """Integer with a thousands separator (12,345 / 12 345)."""
    return f"{value:,}".replace(",", t("fmt.thousands_sep"))


def fmt_compact(value: float) -> str:
    """Compact form of large numbers: 12.3k / 12,3 tys., 1.23M / 1,23 mln."""
    if value >= 1_000_000:
        return fmt_decimal(value / 1_000_000, 2) + t("fmt.millions")
    if value >= 10_000:
        return fmt_decimal(value / 1000, 1) + t("fmt.thousands")
    return fmt_int(int(value))
