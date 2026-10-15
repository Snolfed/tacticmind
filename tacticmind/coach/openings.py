"""Książka otwarć: linie do nauki, ruchy „z teorii” i rozpoznawanie nazw debiutów.

Każde otwarcie to jedna główna linia (w SAN, po angielsku — tak zapisuje ją python-chess) i strona,
którą gra uczeń. Objaśnienie każdego półruchu jest w tłumaczeniach: ``opening.<id>.<półruch>``
(półruchy liczone od 1), nazwa w ``opening.<id>.name``, krótki opis w ``opening.<id>.desc``.

Nazwy debiutów rozpoznajemy po pozycji (EPD), a nie po kolejności ruchów — dzięki temu
przestawienie ruchów (transpozycja) też jest rozpoznane. Nazwą partii jest nazwa najgłębszej
nazwanej pozycji, przez którą partia przeszła (tak działa to na chess.com i Lichess).
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
    #: Strona, którą gra uczeń (białe w partii włoskiej, czarne w obronie sycylijskiej…).
    side: chess.Color
    #: Główna linia w SAN.
    moves: tuple[str, ...]
    #: Od którego półruchu pozycja nosi nazwę tego otwarcia (np. partia włoska od 3. Gc4 = 5. półruch).
    name_from: int


def _line(text: str) -> tuple[str, ...]:
    return tuple(text.split())


W, B = chess.WHITE, chess.BLACK

#: Otwarcia do nauki — po 6 dla białych, 9 dla czarnych (5 przeciw 1. e4 i 4 przeciw 1. d4).
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

#: Ogólne nazwy pozycji, które nie są osobnymi lekcjami (np. „partia otwarta” po 1. e4 e5).
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
    """Pozycja bez liczników ruchów — ta sama pozycja osiągnięta różną drogą ma ten sam klucz."""
    return board.epd()


@cache
def line_ucis(opening_id: str) -> tuple[str, ...]:
    """Główna linia otwarcia w UCI."""
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
    #: Pozycja → (priorytet, id nazwy). Wyższy priorytet = nazwa bardziej szczegółowa.
    names: dict[str, tuple[int, str]]
    #: Pozycja → ruchy z teorii (UCI → ile linii go gra).
    book: dict[str, dict[str, int]]
    #: (pozycja, ruch) → (id otwarcia, numer półruchu) — skąd wziąć objaśnienie ruchu.
    comments: dict[tuple[str, str], tuple[str, int]]


@cache
def _index() -> _Index:
    names: dict[str, tuple[int, str]] = {}
    book: dict[str, dict[str, int]] = {}
    comments: dict[tuple[str, str], tuple[str, int]] = {}

    def name(key: str, priority: int, name_id: str) -> None:
        if key not in names or names[key][0] < priority:
            names[key] = (priority, name_id)

    # Priorytet nazwy = jak „głęboko” w teorii jest zdefiniowana: rodzina 2 × liczba półruchów,
    # otwarcie do nauki 2 × półruch, od którego obowiązuje nazwa, + 1 (przy remisie wygrywa lekcja).
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
    """Id nazwy debiutu (otwarcia albo rodziny) po zagraniu ``moves`` od pozycji początkowej.

    Nazwa może się tylko uszczegóławiać: po „gambicie hetmańskim odrzuconym” dalsze pozycje głównej
    linii gambitu hetmańskiego nie cofają nazwy do ogólniejszej.
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
    """Ruchy z teorii w tej pozycji (UCI → waga = w ilu liniach występuje)."""
    return dict(_index().book.get(epd(board), {}))


def is_book_move(board: chess.Board, move: chess.Move) -> bool:
    return move.uci() in _index().book.get(epd(board), {})


def move_comment(board: chess.Board, move: chess.Move) -> tuple[str, int] | None:
    """(id otwarcia, półruch) z objaśnieniem tego ruchu w tej pozycji, jeśli to ruch z którejś linii."""
    return _index().comments.get((epd(board), move.uci()))


def comment_key(opening_id: str, ply: int) -> str:
    return f"opening.{opening_id}.{ply}"
