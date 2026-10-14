"""Skalowanie interfejsu do rozdzielczości okna.

Cały interfejs jest projektowany dla okna 1360×860 (układ szeroki) albo 560×1000
(układ wąski, jak telefon). Przy innym rozmiarze wszystkie odległości i czcionki
mnożymy przez współczynnik ``scale()`` — dzięki temu na ekranie 4K tekst nie jest
maleńki, a w małym oknie nic nie wychodzi poza ramki.
"""

from __future__ import annotations

BASE_WIDE = (1360, 860)
BASE_NARROW = (560, 1000)
MIN_SCALE = 0.68
MAX_SCALE = 2.6

_scale = 1.0


def is_wide(width: int, height: int) -> bool:
    """Układ szeroki (panel obok szachownicy) czy wąski (panel pod nią)."""
    return width >= 860 and width / max(1, height) > 1.1


def compute_scale(width: int, height: int) -> float:
    base_w, base_h = BASE_WIDE if is_wide(width, height) else BASE_NARROW
    return max(MIN_SCALE, min(MAX_SCALE, min(width / base_w, height / base_h)))


def set_scale(value: float) -> None:
    global _scale
    _scale = value


def scale() -> float:
    return _scale


def px(value: float) -> int:
    """Odległość w pikselach po przeskalowaniu (co najmniej 1 dla wartości dodatnich)."""
    scaled = round(value * _scale)
    return max(1, scaled) if value > 0 else scaled


def fs(size: float) -> int:
    """Rozmiar czcionki po przeskalowaniu (nie mniej niż 9 px, żeby tekst był czytelny)."""
    return max(9, round(size * _scale))
