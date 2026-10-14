"""Ikona aplikacji: biały pion na zaokrąglonym kwadracie z gradientem turkus → fiolet.

Ikona jest rysowana w kodzie (bez plików graficznych). Polecenie
``python -m taktykai.ui.icon`` zapisuje ją też jako ``taktykai/assets/icon.png``
(np. do skrótu na pulpicie).
"""

from __future__ import annotations

import os
from pathlib import Path

import chess
import pygame

from . import gfx, theme
from .pieces import piece_surface

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "icon.png"


def app_icon(size: int = 256) -> pygame.Surface:
    """Ikona o boku ``size`` pikseli (z przezroczystymi rogami)."""
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    margin = round(size * 0.04)
    tile = pygame.Rect(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = round(size * 0.22)
    gfx.rrect_gradient(surf, theme.ACCENT, theme.VIOLET_2, tile, radius)
    # Delikatny połysk w górnej części kafelka.
    gloss = tile.inflate(-round(size * 0.08), -round(size * 0.5)).move(0, -round(size * 0.18))
    gfx.rrect(surf, (255, 255, 255, 38), gloss, gloss.height // 2)
    pawn = piece_surface(chess.Piece(chess.PAWN, chess.WHITE), round(size * 1.12))
    surf.blit(pawn, pawn.get_rect(center=(size // 2, round(size * 0.53))))
    return surf


def save_icon(path: Path = ICON_PATH, size: int = 256) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(app_icon(size), str(path))
    return path


if __name__ == "__main__":
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    print(f"Zapisano ikonę: {save_icon()}")
