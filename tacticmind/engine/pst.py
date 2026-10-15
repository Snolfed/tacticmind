"""Materiał i tablice pozycyjne (piece-square tables) w wersji „tapered”.

Każda figura ma dwie wartości: dla gry środkowej (mg) i dla końcówki (eg).
Ocena końcowa to średnia ważona fazą gry: im mniej figur na planszy, tym
większa waga końcówki. Dzięki temu np. król w grze środkowej chowa się za
pionami, a w końcówce idzie do centrum.

Tablice są z perspektywy białych i zapisane „tak, jak widać planszę”:
pierwszy wiersz to 8. rząd (a8..h8), ostatni to 1. rząd (a1..h1).
Dla czarnych odbijamy planszę w pionie.

Plansza (board.py) sumuje te wartości przyrostowo przy każdym ruchu, więc
funkcja oceny nie musi ich liczyć od zera.
"""

from collections.abc import Mapping, Sequence

from .constants import BISHOP, BLACK, KING, KNIGHT, PAWN, QUEEN, ROOK, WHITE, make_piece, on_board

#: Wartości materiału [pusty, pion, skoczek, goniec, wieża, hetman, król].
MATERIAL_MG = (0, 100, 320, 330, 500, 950, 0)
MATERIAL_EG = (0, 120, 300, 320, 540, 980, 0)

#: Wkład figur w fazę gry (24 = komplet figur, 0 = same piony i króle).
PHASE_WEIGHT = (0, 0, 1, 1, 2, 4, 0)
MAX_PHASE = 24

# fmt: off
PAWN_MG = (
     0,   0,   0,   0,   0,   0,   0,   0,
    50,  50,  50,  50,  50,  50,  50,  50,
    10,  10,  20,  30,  30,  20,  10,  10,
     5,   5,  10,  25,  25,  10,   5,   5,
     0,   0,   0,  20,  20,   0,   0,   0,
     5,  -5, -10,   0,   0, -10,  -5,   5,
     5,  10,  10, -20, -20,  10,  10,   5,
     0,   0,   0,   0,   0,   0,   0,   0,
)
PAWN_EG = (
     0,   0,   0,   0,   0,   0,   0,   0,
    80,  80,  80,  80,  80,  80,  80,  80,
    50,  50,  50,  50,  50,  50,  50,  50,
    30,  30,  30,  30,  30,  30,  30,  30,
    15,  15,  15,  15,  15,  15,  15,  15,
     5,   5,   5,   5,   5,   5,   5,   5,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
)
KNIGHT_PST = (
   -50, -40, -30, -30, -30, -30, -40, -50,
   -40, -20,   0,   0,   0,   0, -20, -40,
   -30,   0,  10,  15,  15,  10,   0, -30,
   -30,   5,  15,  20,  20,  15,   5, -30,
   -30,   0,  15,  20,  20,  15,   0, -30,
   -30,   5,  10,  15,  15,  10,   5, -30,
   -40, -20,   0,   5,   5,   0, -20, -40,
   -50, -40, -30, -30, -30, -30, -40, -50,
)
BISHOP_PST = (
   -20, -10, -10, -10, -10, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,  10,  10,   5,   0, -10,
   -10,   5,   5,  10,  10,   5,   5, -10,
   -10,   0,  10,  10,  10,  10,   0, -10,
   -10,  10,  10,  10,  10,  10,  10, -10,
   -10,   5,   0,   0,   0,   0,   5, -10,
   -20, -10, -10, -10, -10, -10, -10, -20,
)
ROOK_MG = (
     0,   0,   0,   0,   0,   0,   0,   0,
     5,  10,  10,  10,  10,  10,  10,   5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
    -5,   0,   0,   0,   0,   0,   0,  -5,
     0,   0,   0,   5,   5,   0,   0,   0,
)
ROOK_EG = (
     5,   5,   5,   5,   5,   5,   5,   5,
    10,  10,  10,  10,  10,  10,  10,  10,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
     0,   0,   0,   0,   0,   0,   0,   0,
)
QUEEN_PST = (
   -20, -10, -10,  -5,  -5, -10, -10, -20,
   -10,   0,   0,   0,   0,   0,   0, -10,
   -10,   0,   5,   5,   5,   5,   0, -10,
    -5,   0,   5,   5,   5,   5,   0,  -5,
     0,   0,   5,   5,   5,   5,   0,  -5,
   -10,   5,   5,   5,   5,   5,   0, -10,
   -10,   0,   5,   0,   0,   0,   0, -10,
   -20, -10, -10,  -5,  -5, -10, -10, -20,
)
KING_MG = (
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -30, -40, -40, -50, -50, -40, -40, -30,
   -20, -30, -30, -40, -40, -30, -30, -20,
   -10, -20, -20, -20, -20, -20, -20, -10,
    20,  20,   0,   0,   0,   0,  20,  20,
    20,  30,  10,   0,   0,  10,  30,  20,
)
KING_EG = (
   -50, -40, -30, -20, -20, -30, -40, -50,
   -30, -20, -10,   0,   0, -10, -20, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  30,  40,  40,  30, -10, -30,
   -30, -10,  20,  30,  30,  20, -10, -30,
   -30, -30,   0,   0,   0,   0, -30, -30,
   -50, -30, -30, -30, -30, -30, -30, -50,
)
# fmt: on

_PST_MG = {PAWN: PAWN_MG, KNIGHT: KNIGHT_PST, BISHOP: BISHOP_PST, ROOK: ROOK_MG, QUEEN: QUEEN_PST, KING: KING_MG}
_PST_EG = {PAWN: PAWN_EG, KNIGHT: KNIGHT_PST, BISHOP: BISHOP_PST, ROOK: ROOK_EG, QUEEN: QUEEN_PST, KING: KING_EG}


def pst_index(sq: int, color: int) -> int:
    """Indeks w tablicy 64-elementowej dla pola 0x88 (dla czarnych odbicie w pionie)."""
    rank, file = sq >> 4, sq & 7
    return (7 - rank) * 8 + file if color == WHITE else rank * 8 + file


def _build(material: Sequence[int], tables: Mapping[int, Sequence[int]]) -> list[int]:
    """Tablica [figura*128 + pole] = materiał + PST, ze znakiem (+ białe, − czarne)."""
    combined = [0] * (16 * 128)
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        for piece_type, table in tables.items():
            piece = make_piece(color, piece_type)
            for sq in range(128):
                if on_board(sq):
                    combined[piece * 128 + sq] = sign * (material[piece_type] + table[pst_index(sq, color)])
    return combined


#: Gotowe sumy materiał+PST dla gry środkowej i końcówki (używa ich board.py).
PSQ_MG = _build(MATERIAL_MG, _PST_MG)
PSQ_EG = _build(MATERIAL_EG, _PST_EG)
#: Faza gry dla kodu figury.
PIECE_PHASE = [PHASE_WEIGHT[p & 7] if 0 < (p & 7) <= KING else 0 for p in range(16)]
