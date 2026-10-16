"""Zobrist hashing.

Each (piece, square) combination, the side to move, the castling rights and
the en passant square get a random 64-bit number. A position's hash is the XOR
of the numbers describing its elements. The advantage is incremental updating:
making a move takes a few XORs instead of recomputing the hash from scratch.
"""

import random

_rng = random.Random(0x7A6B5C4D)  # fixed seed = reproducible hashes


def _rand64() -> int:
    return _rng.getrandbits(64)


#: Piece keys: index = piece_code * 128 + square_0x88.
PIECE_KEYS = [_rand64() for _ in range(16 * 128)]
#: Side-to-move key (XORed in when Black is to move).
SIDE_KEY = _rand64()
#: Castling rights keys (16 combinations of 4 bits).
CASTLE_KEYS = [_rand64() for _ in range(16)]
#: En passant square keys (index = 0x88 square).
EP_KEYS = [_rand64() for _ in range(128)]
