"""Engine constants: piece codes, move encoding, 0x88 board square tables.

The 0x88 board is an array of 128 squares (16 files x 8 ranks), of which only
the left half (files 0-7) is used. Square index = rank * 16 + file, where
a1 = 0, h1 = 7, a8 = 112. The 0x88 trick: a square is on the board if and only
if ``(square & 0x88) == 0``, so leaving the board is detected with a single
bitwise operation.

Pieces are encoded as ``color * 8 + type`` (type: 1 = pawn ... 6 = king,
color: 0 = white, 1 = black). Empty square = 0.
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

# Castling rights as bits.
CASTLE_WK = 1
CASTLE_WQ = 2
CASTLE_BK = 4
CASTLE_BQ = 8

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# ---------------------------------------------------------------------------
# A move encoded in a single integer (no objects = faster):
# bits 0-6: origin square, 7-13: target square, 14-16: promotion piece type,
# bits 17+: flags.
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
# Squares
# ---------------------------------------------------------------------------
def on_board(sq: int) -> bool:
    return (sq & 0x88) == 0


def square_name(sq: int) -> str:
    return "abcdefgh"[sq & 7] + str((sq >> 4) + 1)


def parse_square(name: str) -> int:
    if len(name) != 2 or name[0] not in "abcdefgh" or name[1] not in "12345678":
        return -1
    return (int(name[1]) - 1) * 16 + "abcdefgh".index(name[0])


#: The 64 real board squares (0x88 indices); board loops skip the invisible half.
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


# Tables computed once at startup (thanks to the 0x88 trick). The generator loops
# use ready-made square lists instead of checking the board edges every time.
KNIGHT_TARGETS = [_targets(sq, KNIGHT_OFFSETS) if on_board(sq) else () for sq in range(128)]
KING_TARGETS = [_targets(sq, KING_OFFSETS) if on_board(sq) else () for sq in range(128)]
BISHOP_RAYS = [_rays(sq, BISHOP_DIRS) if on_board(sq) else () for sq in range(128)]
ROOK_RAYS = [_rays(sq, ROOK_DIRS) if on_board(sq) else () for sq in range(128)]
QUEEN_RAYS = [BISHOP_RAYS[sq] + ROOK_RAYS[sq] for sq in range(128)]
#: Squares from which a pawn of the given color attacks square sq (a white pawn from sq-15/sq-17).
PAWN_ATTACKERS = (
    [_targets(sq, (-15, -17)) if on_board(sq) else () for sq in range(128)],
    [_targets(sq, (15, 17)) if on_board(sq) else () for sq in range(128)],
)
