"""Notacja szachowa w języku interfejsu (warstwa UI, korzysta z python-chess).

Silnik zwraca ruchy w UCI (np. ``f3f7``); tu zamieniamy je na SAN z literami
figur właściwymi dla języka: po polsku K — król, H — hetman, W — wieża,
G — goniec, S — skoczek; po angielsku K, Q, R, B, N.
"""

from __future__ import annotations

from functools import lru_cache

import chess

from ..i18n import LANGUAGES, get_language

_ENGLISH = "KQRBN"


def localize_san(san: str, language: str | None = None) -> str:
    """``Qxf7+`` → ``Hxf7+`` (po polsku). Roszady i kolumny (małe litery) bez zmian."""
    if san.startswith("O-O"):
        return san
    pieces: str = LANGUAGES[language or get_language()][1].STRINGS.get("notation.pieces", _ENGLISH)
    if pieces == _ENGLISH:
        return san
    return san.translate(str.maketrans(_ENGLISH, pieces))


def to_polish(san: str) -> str:
    """SAN z polskimi literami figur (niezależnie od bieżącego języka)."""
    return localize_san(san, "pl")


def move_san(board: chess.Board, move: chess.Move) -> str:
    return localize_san(board.san(move))


def uci_san(fen: str, uci: str) -> str:
    board = chess.Board(fen)
    try:
        return move_san(board, chess.Move.from_uci(uci))
    except (ValueError, AssertionError):
        return uci


def san_list(fen: str, ucis: list[str], limit: int | None = None) -> list[str]:
    """Wariant UCI jako lista ruchów SAN (przerywa na pierwszym nielegalnym ruchu)."""
    board = chess.Board(fen)
    result = []
    for uci in ucis[:limit] if limit else ucis:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            break
        if move not in board.legal_moves:
            break
        result.append(move_san(board, move))
        board.push(move)
    return result


def format_line(fen: str, ucis: list[str], limit: int | None = 8) -> str:
    """Wariant z numerami ruchów, np. ``1. Hxf7+ Kxf7 2. Sg5+`` (numeracja od 1 dla czytelności)."""
    return _format_line(fen, tuple(ucis), limit, get_language())


@lru_cache(maxsize=2048)
def _format_line(fen: str, ucis: tuple[str, ...], limit: int | None, language: str) -> str:
    """Wersja z pamięcią podręczną (interfejs rysuje te same warianty 60 razy na sekundę)."""
    del language  # część klucza pamięci podręcznej: litery figur zależą od języka
    ucis_list = list(ucis)
    white_to_move = chess.Board(fen).turn == chess.WHITE
    parts = []
    number = 1
    for i, san in enumerate(san_list(fen, ucis_list, limit)):
        white = white_to_move if i % 2 == 0 else not white_to_move
        if white:
            parts.append(f"{number}. {san}")
        else:
            parts.append(f"{number}... {san}" if i == 0 else san)
            number += 1
    return " ".join(parts)
