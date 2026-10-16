"""Themes from the Lichess puzzle database: names in the current language (from the i18n module) and the split into "meta" themes."""

from ..i18n import has, t

#: Themes describing the puzzle's length/evaluation/source rather than a skill — the player model does not track them.
META_THEMES = frozenset(
    {"short", "long", "veryLong", "oneMove", "master", "masterVsMaster", "superGM", "crushing", "advantage", "equality"}
)


def theme_name(theme: str) -> str:
    """Theme name in the current language (or the original one if there is no translation)."""
    key = f"theme.{theme}"
    return t(key) if has(key) else theme


def skill_themes(themes: tuple[str, ...] | list[str]) -> list[str]:
    """Themes in which we measure the player's accuracy (without the "meta" themes)."""
    return [theme for theme in themes if theme not in META_THEMES]
