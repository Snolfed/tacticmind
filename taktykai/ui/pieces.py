"""Grafika figur rysowana z symboli szachowych Unicode (czcionka Noto Sans Symbols 2).

Biała figura = wypełniony symbol w kolorze białym + symbol konturowy w ciemnym.
Czarna figura = wypełniony symbol w ciemnym kolorze + jasne linie wewnętrzne.
Figury renderujemy w podwójnej rozdzielczości i zmniejszamy filtrem — krawędzie są
gładsze niż przy zwykłym renderowaniu tekstu. Nie potrzebujemy plików graficznych.
"""

from __future__ import annotations

import chess
import pygame

from . import fonts

_FILLED = {chess.KING: "♚", chess.QUEEN: "♛", chess.ROOK: "♜", chess.BISHOP: "♝", chess.KNIGHT: "♞", chess.PAWN: "♟"}
_OUTLINE = {chess.KING: "♔", chess.QUEEN: "♕", chess.ROOK: "♖", chess.BISHOP: "♗", chess.KNIGHT: "♘", chess.PAWN: "♙"}
_SUPERSAMPLE = 2
#: Symbole króla i hetmana w tej czcionce są wąskie (wyglądają na „ściśnięte”) — poszerzamy je w poziomie.
_WIDTH_SCALE = {chess.KING: 1.22, chess.QUEEN: 1.14}

_cache: dict[tuple[str, int], pygame.Surface] = {}


def _layer(text: str, size: int, color: tuple[int, int, int]) -> pygame.Surface:
    return fonts.font(size, "symbols").render(text, True, color)


def piece_surface(piece: chess.Piece, square_size: int) -> pygame.Surface:
    """Powierzchnia z figurą dopasowaną do pola o boku ``square_size``."""
    key = (piece.symbol(), square_size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    size = max(8, int(square_size * 0.86)) * _SUPERSAMPLE
    filled = _FILLED[piece.piece_type]
    outline = _OUTLINE[piece.piece_type]
    base = _layer(filled, size, (0, 0, 0))
    pad = 3 * _SUPERSAMPLE
    canvas = pygame.Surface((base.get_width() + 2 * pad, base.get_height() + 2 * pad), pygame.SRCALPHA)
    shadow = _layer(filled, size, (0, 0, 0))
    shadow.set_alpha(60)
    canvas.blit(shadow, (pad + _SUPERSAMPLE, pad + 2 * _SUPERSAMPLE))
    if piece.color == chess.WHITE:
        canvas.blit(_layer(filled, size, (250, 251, 253)), (pad, pad))
        canvas.blit(_layer(outline, size, (24, 27, 38)), (pad, pad))
    else:
        canvas.blit(_layer(filled, size, (30, 33, 44)), (pad, pad))
        inner = _layer(outline, size, (128, 136, 160))
        inner.set_alpha(150)
        canvas.blit(inner, (pad, pad))
    bounds = canvas.get_bounding_rect()
    cropped = canvas.subsurface(bounds).copy()
    # Poszerzenie robimy razem ze zmniejszaniem z podwójnej rozdzielczości, więc krawędzie zostają ostre.
    width = cropped.get_width() / _SUPERSAMPLE * _WIDTH_SCALE.get(piece.piece_type, 1.0)
    width = min(width, square_size * 0.94)
    target = (max(1, round(width)), max(1, cropped.get_height() // _SUPERSAMPLE))
    surf = pygame.transform.smoothscale(cropped, target)
    _cache[key] = surf
    return surf
