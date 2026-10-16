"""Opening book: lines to study, "book" moves and opening name recognition.

Each opening is one main line (in English SAN - the way python-chess writes it) and the side
the student plays. The explanation of every ply lives in the translations: ``opening.<id>.<ply>``
(plies counted from 1), the name in ``opening.<id>.name``, a short description in ``opening.<id>.desc``.

Opening names are recognised by position (EPD), not by move order - so a different move order
(transposition) is recognised too. The name of a game is the name of the deepest named position
the game passed through (this is how chess.com and Lichess do it).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import chess

from ..i18n import t


@dataclass(frozen=True)
class Opening:
    id: str
    eco: str
    #: The side the student plays (White in the Italian Game, Black in the Sicilian Defence...).
    side: chess.Color
    #: Main line in SAN.
    moves: tuple[str, ...]
    #: From which ply the position carries this opening's name (e.g. the Italian Game from 3. Bc4 = ply 5).
    name_from: int


def _line(text: str) -> tuple[str, ...]:
    return tuple(text.split())


W, B = chess.WHITE, chess.BLACK

#: Openings to study - 6 for White, 9 for Black (5 against 1. e4 and 4 against 1. d4).
OPENINGS: tuple[Opening, ...] = (
    Opening("italian", "C50", W, _line("e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 d6 O-O O-O"), 5),
    Opening("ruy_lopez", "C84", W, _line("e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O"), 5),
    Opening("scotch", "C45", W, _line("e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6 Nxc6 bxc6 e5 Qe7 Qe2 Nd5 c4 Nb6"), 5),
    Opening("queens_gambit", "D37", W, _line("d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 Nbd7"), 3),
    Opening("london", "D02", W, _line("d4 d5 Bf4 Nf6 e3 c5 c3 Nc6 Nd2 e6 Ngf3 Bd6 Bg3 O-O Bd3"), 3),
    Opening("english", "A29", W, _line("c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5 Bg2 Nb6 O-O Be7"), 1),
    Opening("sicilian_najdorf", "B90", B, _line("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6 f3 Be7"), 10),
    Opening("french", "C11", B, _line("e4 e6 d4 d5 Nc3 Nf6 e5 Nfd7 f4 c5 Nf3 Nc6 Be3 cxd4 Nxd4 Bc5"), 2),
    Opening("caro_kann", "B18", B, _line("e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6 h4 h6 Nf3 Nd7 h5 Bh7"), 2),
    Opening("scandinavian", "B01", B, _line("e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6 Bc4 Bf5 Bd2 e6"), 2),
    Opening("two_knights", "C55", B, _line("e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Be7 O-O O-O Re1 d6"), 6),
    Opening("slav", "D17", B, _line("d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5 e3 e6 Bxc4 Bb4 O-O O-O"), 4),
    Opening("kings_indian", "E97", B, _line("d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6 d5 Ne7"), 6),
    Opening("nimzo_indian", "E32", B, _line("d4 Nf6 c4 e6 Nc3 Bb4 Qc2 O-O a3 Bxc3+ Qxc3 b6 Bg5 Bb7"), 6),
    Opening("grunfeld", "D85", B, _line("d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7 Nf3 c5 Be3 Qa5"), 6),
)

#: General position names that are not separate lessons (e.g. "Open Game" after 1. e4 e5).
FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("kings_pawn", _line("e4")),
    ("queens_pawn", _line("d4")),
    ("reti", _line("Nf3")),
    ("open_game", _line("e4 e5")),
    ("kings_knight", _line("e4 e5 Nf3")),
    ("petrov", _line("e4 e5 Nf3 Nf6")),
    ("kings_gambit", _line("e4 e5 f4")),
    ("vienna", _line("e4 e5 Nc3")),
    ("sicilian", _line("e4 c5")),
    ("pirc", _line("e4 d6")),
    ("modern", _line("e4 g6")),
    ("alekhine", _line("e4 Nf6")),
    ("closed_game", _line("d4 d5")),
    ("qgd", _line("d4 d5 c4 e6")),
    ("qga", _line("d4 d5 c4 dxc4")),
    ("indian", _line("d4 Nf6")),
    ("dutch", _line("d4 f5")),
    ("benoni", _line("d4 Nf6 c4 c5")),
    ("queens_indian", _line("d4 Nf6 c4 e6 Nf3 b6")),
)


def epd(board: chess.Board) -> str:
    """Position without move counters - the same position reached by different routes has the same key."""
    return board.epd()


@cache
def line_ucis(opening_id: str) -> tuple[str, ...]:
    """Main line of the opening in UCI."""
    board = chess.Board()
    ucis = []
    for san in opening_by_id(opening_id).moves:
        move = board.parse_san(san)
        ucis.append(move.uci())
        board.push(move)
    return tuple(ucis)


def opening_by_id(opening_id: str) -> Opening:
    for opening in OPENINGS:
        if opening.id == opening_id:
            return opening
    raise KeyError(opening_id)


@dataclass(frozen=True)
class _Index:
    #: Position → (priority, name id). Higher priority = more specific name.
    names: dict[str, tuple[int, str]]
    #: Position → book moves (UCI → how many lines play it).
    book: dict[str, dict[str, int]]
    #: (position, move) → (opening id, ply number) - where to take the move's explanation from.
    comments: dict[tuple[str, str], tuple[str, int]]


@cache
def _index() -> _Index:
    names: dict[str, tuple[int, str]] = {}
    book: dict[str, dict[str, int]] = {}
    comments: dict[tuple[str, str], tuple[str, int]] = {}

    def name(key: str, priority: int, name_id: str) -> None:
        if key not in names or names[key][0] < priority:
            names[key] = (priority, name_id)

    # Name priority = how "deep" in theory it is defined: a family 2 × number of plies,
    # a study opening 2 × the ply from which the name applies, + 1 (on a tie the lesson wins).
    for family, moves in FAMILIES:
        board = chess.Board()
        for san in moves:
            board.push_san(san)
        name(epd(board), 2 * len(moves), family)
    for opening in OPENINGS:
        board = chess.Board()
        for ply, san in enumerate(opening.moves, start=1):
            move = board.parse_san(san)
            key = epd(board)
            book.setdefault(key, {})
            book[key][move.uci()] = book[key].get(move.uci(), 0) + 1
            comments.setdefault((key, move.uci()), (opening.id, ply))
            board.push(move)
            if ply >= opening.name_from:
                name(epd(board), 2 * opening.name_from + 1, opening.id)
    return _Index(names, book, comments)


def opening_at(moves: list[chess.Move], start: chess.Board | None = None) -> str | None:
    """Name id of the opening (a study opening or a family) after playing ``moves`` from the starting position.

    The name can only become more specific: after the "Queen's Gambit Declined", later positions of the
    Queen's Gambit main line do not revert the name to a more general one.
    """
    board = start.copy(stack=False) if start is not None else chess.Board()
    names = _index().names
    found: tuple[int, str] | None = names.get(epd(board))
    for move in moves:
        board.push(move)
        entry = names.get(epd(board))
        if entry is not None and (found is None or entry[0] >= found[0]):
            found = entry
    return found[1] if found else None


def opening_name(name_id: str) -> str:
    return t(f"opening.{name_id}.name")


def book_moves(board: chess.Board) -> dict[str, int]:
    """Book moves in this position (UCI → weight = in how many lines it occurs)."""
    return dict(_index().book.get(epd(board), {}))


def is_book_move(board: chess.Board, move: chess.Move) -> bool:
    return move.uci() in _index().book.get(epd(board), {})


def move_comment(board: chess.Board, move: chess.Move) -> tuple[str, int] | None:
    """(opening id, ply) with the explanation of this move in this position, if it is a move from one of the lines."""
    return _index().comments.get((epd(board), move.uci()))


def comment_key(opening_id: str, ply: int) -> str:
    return f"opening.{opening_id}.{ply}"
