"""Stałe silnika: kody figur, kodowanie ruchów, tablice pól planszy 0x88.

Plansza 0x88 to tablica 128 pól (16 kolumn × 8 rzędów), z których używamy
tylko lewej połowy (kolumny 0–7). Indeks pola = rząd * 16 + kolumna, gdzie
a1 = 0, h1 = 7, a8 = 112. Sztuczka 0x88: pole leży na planszy wtedy i tylko
wtedy, gdy ``(pole & 0x88) == 0`` — wyjście poza planszę wykrywamy jedną
operacją bitową.

Figury kodujemy jako ``kolor * 8 + typ`` (typ: 1 = pion … 6 = król,
kolor: 0 = białe, 1 = czarne). Puste pole = 0.
"""

WHITE = 0
BLACK = 1

EMPTY = 0
PAWN = 1
KNIGHT = 2
BISHOP = 3
ROOK = 4
QUEEN = 5
KING = 6

PIECE_CHARS = " pnbrqk"

# Prawa do roszady jako bity.
CASTLE_WK = 1
CASTLE_WQ = 2
CASTLE_BK = 4
CASTLE_BQ = 8

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# ---------------------------------------------------------------------------
# Kodowanie ruchu w jednej liczbie całkowitej (brak obiektów = szybciej):
# bity 0–6: pole startowe, 7–13: pole docelowe, 14–16: typ figury promocji,
# bity 17+: flagi.
# ---------------------------------------------------------------------------
FLAG_CAPTURE = 1 << 17
FLAG_EP = 1 << 18
FLAG_CASTLE = 1 << 19
FLAG_DOUBLE = 1 << 20
CAPTURE_MASK = FLAG_CAPTURE | FLAG_EP


def make_piece(color: int, piece_type: int) -> int:
    return (color << 3) | piece_type


def encode_move(frm: int, to: int, promo: int = 0, flags: int = 0) -> int:
    return frm | (to << 7) | (promo << 14) | flags


def move_from(move: int) -> int:
    return move & 0x7F


def move_to(move: int) -> int:
    return (move >> 7) & 0x7F


def move_promo(move: int) -> int:
    return (move >> 14) & 7


def is_capture(move: int) -> bool:
    return (move & CAPTURE_MASK) != 0


# ---------------------------------------------------------------------------
# Pola
# ---------------------------------------------------------------------------
def on_board(sq: int) -> bool:
    return (sq & 0x88) == 0


def square_name(sq: int) -> str:
    return "abcdefgh"[sq & 7] + str((sq >> 4) + 1)


def parse_square(name: str) -> int:
    if len(name) != 2 or name[0] not in "abcdefgh" or name[1] not in "12345678":
        return -1
    return (int(name[1]) - 1) * 16 + "abcdefgh".index(name[0])


#: 64 prawdziwe pola planszy (indeksy 0x88) — pętle po planszy omijają niewidzialną połowę.
SQUARES = [sq for sq in range(128) if on_board(sq)]

KNIGHT_OFFSETS = (33, 31, 18, 14, -33, -31, -18, -14)
KING_OFFSETS = (1, -1, 16, -16, 17, 15, -17, -15)
BISHOP_DIRS = (17, 15, -17, -15)
ROOK_DIRS = (16, -16, 1, -1)


def _targets(sq: int, offsets: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sq + off for off in offsets if on_board(sq + off))


def _rays(sq: int, dirs: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    rays = []
    for d in dirs:
        ray = []
        t = sq + d
        while on_board(t):
            ray.append(t)
            t += d
        if ray:
            rays.append(tuple(ray))
    return tuple(rays)


# Tablice liczone raz przy starcie (dzięki sztuczce 0x88). W pętlach generatora
# używamy gotowych list pól zamiast za każdym razem sprawdzać krawędzie planszy.
KNIGHT_TARGETS = [_targets(sq, KNIGHT_OFFSETS) if on_board(sq) else () for sq in range(128)]
KING_TARGETS = [_targets(sq, KING_OFFSETS) if on_board(sq) else () for sq in range(128)]
BISHOP_RAYS = [_rays(sq, BISHOP_DIRS) if on_board(sq) else () for sq in range(128)]
ROOK_RAYS = [_rays(sq, ROOK_DIRS) if on_board(sq) else () for sq in range(128)]
QUEEN_RAYS = [BISHOP_RAYS[sq] + ROOK_RAYS[sq] for sq in range(128)]
#: Pola, z których pion danego koloru atakuje pole sq (biały pion z sq-15/sq-17).
PAWN_ATTACKERS = (
    [_targets(sq, (-15, -17)) if on_board(sq) else () for sq in range(128)],
    [_targets(sq, (15, 17)) if on_board(sq) else () for sq in range(128)],
)
