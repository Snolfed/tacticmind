"""Piece graphics drawn from Unicode chess symbols (Noto Sans Symbols 2 font).

White piece = filled symbol in white + outline symbol in a dark colour.
Black piece = filled symbol in a dark colour + light inner lines.
Pieces are rendered at double resolution and filtered down — edges come out
smoother than with plain text rendering. No image files are needed.
"""

from __future__ import annotations

import chess
import pygame

from . import fonts

_FILLED = {chess.KING: "♚", chess.QUEEN: "♛", chess.ROOK: "♜", chess.BISHOP: "♝", chess.KNIGHT: "♞", chess.PAWN: "♟"}
_OUTLINE = {chess.KING: "♔", chess.QUEEN: "♕", chess.ROOK: "♖", chess.BISHOP: "♗", chess.KNIGHT: "♘", chess.PAWN: "♙"}
_SUPERSAMPLE = 2
#: The king and queen symbols in this font are narrow (they look squeezed) — we widen them horizontally.
_WIDTH_SCALE = {chess.KING: 1.22, chess.QUEEN: 1.14}

_cache: dict[tuple[str, int], pygame.Surface] = {}


def _layer(text: str, size: int, color: tuple[int, int, int]) -> pygame.Surface:
    return fonts.font(size, "symbols").render(text, True, color)


def piece_surface(piece: chess.Piece, square_size: int) -> pygame.Surface:
    """Surface with the piece fitted to a square of side ``square_size``."""
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
    # Widening is done together with downscaling from double resolution, so edges stay crisp.
    width = cropped.get_width() / _SUPERSAMPLE * _WIDTH_SCALE.get(piece.piece_type, 1.0)
    width = min(width, square_size * 0.94)
    target = (max(1, round(width)), max(1, cropped.get_height() // _SUPERSAMPLE))
    surf = pygame.transform.smoothscale(cropped, target)
    _cache[key] = surf
    return surf
