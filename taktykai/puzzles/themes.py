"""Motywy z bazy zadań Lichess: nazwy w bieżącym języku (z modułu i18n) i podział na motywy „meta”."""

from ..i18n import has, t

#: Motywy opisujące długość/ocenę/źródło zadania, a nie umiejętność — model gracza ich nie śledzi.
META_THEMES = frozenset(
    {"short", "long", "veryLong", "oneMove", "master", "masterVsMaster", "superGM", "crushing", "advantage", "equality"}
)


def theme_name(theme: str) -> str:
    """Nazwa motywu w bieżącym języku (albo oryginalna, jeśli nie ma tłumaczenia)."""
    key = f"theme.{theme}"
    return t(key) if has(key) else theme


def skill_themes(themes: tuple[str, ...] | list[str]) -> list[str]:
    """Motywy, w których mierzymy skuteczność gracza (bez motywów „meta”)."""
    return [theme for theme in themes if theme not in META_THEMES]
