"""Material and piece-square tables, "tapered" version.

Each piece has two values: one for the middlegame (mg) and one for the endgame (eg).
The final score is the average weighted by game phase: the fewer pieces on the
board, the greater the endgame weight. This way, for example, the king hides
behind its pawns in the middlegame but walks to the centre in the endgame.

The tables are from White's perspective and written "as the board is seen":
the first row is the 8th rank (a8..h8), the last is the 1st rank (a1..h1).
For Black the board is mirrored vertically.

The board (board.py) sums these values incrementally on every move, so the
evaluation function doesn't have to compute them from scratch.
"""

from collections.abc import Mapping, Sequence

from .constants import BISHOP, BLACK, KING, KNIGHT, PAWN, QUEEN, ROOK, WHITE, make_piece, on_board

#: Material values [empty, pawn, knight, bishop, rook, queen, king].
MATERIAL_MG = (0, 100, 320, 330, 500, 950, 0)
MATERIAL_EG = (0, 120, 300, 320, 540, 980, 0)

#: Piece contribution to the game phase (24 = all pieces, 0 = only pawns and kings).
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
    """Index into a 64-element table for a 0x88 square (mirrored vertically for Black)."""
    rank, file = sq >> 4, sq & 7
    return (7 - rank) * 8 + file if color == WHITE else rank * 8 + file


def _build(material: Sequence[int], tables: Mapping[int, Sequence[int]]) -> list[int]:
    """Table [piece*128 + square] = material + PST, signed (+ white, - black)."""
    combined = [0] * (16 * 128)
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        for piece_type, table in tables.items():
            piece = make_piece(color, piece_type)
            for sq in range(128):
                if on_board(sq):
                    combined[piece * 128 + sq] = sign * (material[piece_type] + table[pst_index(sq, color)])
    return combined


#: Precomputed material+PST sums for the middlegame and endgame (used by board.py).
PSQ_MG = _build(MATERIAL_MG, _PST_MG)
PSQ_EG = _build(MATERIAL_EG, _PST_EG)
#: Game phase per piece code.
PIECE_PHASE = [PHASE_WEIGHT[p & 7] if 0 < (p & 7) <= KING else 0 for p in range(16)]
