"""0x88 board representation: game state, FEN, making and unmaking moves.

Details of the square, piece and move encoding are in ``constants.py``.
The board incrementally maintains:
 - the Zobrist hash (``hash``), for the transposition table and repetition detection,
 - material+PST sums for the middlegame and endgame (``mg``, ``eg``) and the game
   phase (``phase``), so the evaluation function doesn't recompute them in every leaf.
"""

from __future__ import annotations

from .constants import (
    BLACK,
    CASTLE_BK,
    CASTLE_BQ,
    CASTLE_WK,
    CASTLE_WQ,
    EMPTY,
    FLAG_CASTLE,
    FLAG_DOUBLE,
    FLAG_EP,
    KING,
    PAWN,
    PIECE_CHARS,
    SQUARES,
    START_FEN,
    WHITE,
    make_piece,
    parse_square,
    square_name,
)
from .pst import PIECE_PHASE, PSQ_EG, PSQ_MG
from .zobrist import CASTLE_KEYS, EP_KEYS, PIECE_KEYS, SIDE_KEY

#: After a move from/to square ``sq``, castling rights become ``castling & CASTLE_MASK[sq]``.
CASTLE_MASK = [15] * 128
CASTLE_MASK[0] = 15 & ~CASTLE_WQ  # a1
CASTLE_MASK[4] = 15 & ~(CASTLE_WK | CASTLE_WQ)  # e1
CASTLE_MASK[7] = 15 & ~CASTLE_WK  # h1
CASTLE_MASK[112] = 15 & ~CASTLE_BQ  # a8
CASTLE_MASK[116] = 15 & ~(CASTLE_BK | CASTLE_BQ)  # e8
CASTLE_MASK[119] = 15 & ~CASTLE_BK  # h8


def piece_to_char(piece: int) -> str:
    ch = PIECE_CHARS[piece & 7]
    return ch.upper() if (piece >> 3) == WHITE else ch


class Board:
    """A chess position on a 0x88 board with make/unmake."""

    __slots__ = ("sq", "side", "castling", "ep", "halfmove", "fullmove", "kings", "hash", "mg", "eg", "phase", "stack")

    def __init__(self, fen: str = START_FEN) -> None:
        self.sq: list[int] = [EMPTY] * 128
        self.side = WHITE
        self.castling = 0
        self.ep = -1  # en passant target square, or -1
        self.halfmove = 0  # counter for the 50-move rule
        self.fullmove = 1
        self.kings = [-1, -1]  # king squares [white, black]
        self.hash = 0
        self.mg = 0
        self.eg = 0
        self.phase = 0
        # Undo stack: (move, captured piece, castling, ep, halfmove, hash, mg, eg, phase).
        # The hashes on the stack are also used to detect position repetitions.
        self.stack: list[tuple[int, int, int, int, int, int, int, int, int]] = []
        self.load_fen(fen)

    # ------------------------------------------------------------------ FEN
    def load_fen(self, fen: str) -> None:
        parts = fen.split()
        if len(parts) < 4:
            raise ValueError(f"Invalid FEN: {fen}")
        placement, side, castling, ep = parts[:4]
        rows = placement.split("/")
        if len(rows) != 8:
            raise ValueError(f"Invalid FEN (number of ranks): {fen}")
        self.sq = [EMPTY] * 128
        self.kings = [-1, -1]
        for r, row in enumerate(rows):
            rank = 7 - r
            file = 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                    continue
                piece_type = PIECE_CHARS.find(ch.lower())
                if piece_type <= 0 or file > 7:
                    raise ValueError(f"Invalid FEN (piece '{ch}'): {fen}")
                color = WHITE if ch.isupper() else BLACK
                sq = rank * 16 + file
                self.sq[sq] = make_piece(color, piece_type)
                if piece_type == KING:
                    self.kings[color] = sq
                file += 1
            if file != 8:
                raise ValueError(f"Invalid FEN (rank length): {fen}")
        if self.kings[0] < 0 or self.kings[1] < 0:
            raise ValueError(f"FEN without a king: {fen}")
        self.side = BLACK if side == "b" else WHITE
        self.castling = (
            (CASTLE_WK if "K" in castling else 0)
            | (CASTLE_WQ if "Q" in castling else 0)
            | (CASTLE_BK if "k" in castling else 0)
            | (CASTLE_BQ if "q" in castling else 0)
        )
        self.ep = -1 if ep == "-" else parse_square(ep)
        self.halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1
        self.stack = []
        self.refresh()

    def fen(self) -> str:
        rows = []
        for rank in range(7, -1, -1):
            row, empty = "", 0
            for file in range(8):
                piece = self.sq[rank * 16 + file]
                if piece == EMPTY:
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece_to_char(piece)
            rows.append(row + (str(empty) if empty else ""))
        castling = "".join(
            ch for bit, ch in ((CASTLE_WK, "K"), (CASTLE_WQ, "Q"), (CASTLE_BK, "k"), (CASTLE_BQ, "q")) if self.castling & bit
        )
        return " ".join(
            (
                "/".join(rows),
                "w" if self.side == WHITE else "b",
                castling or "-",
                square_name(self.ep) if self.ep >= 0 else "-",
                str(self.halfmove),
                str(self.fullmove),
            )
        )

    def copy(self) -> Board:
        return Board(self.fen())

    def refresh(self) -> None:
        """Recompute the hash and evaluation sums from scratch (after loading a FEN; in consistency tests)."""
        h = mg = eg = phase = 0
        for sq in SQUARES:
            piece = self.sq[sq]
            if piece:
                h ^= PIECE_KEYS[piece * 128 + sq]
                mg += PSQ_MG[piece * 128 + sq]
                eg += PSQ_EG[piece * 128 + sq]
                phase += PIECE_PHASE[piece]
        if self.side == BLACK:
            h ^= SIDE_KEY
        h ^= CASTLE_KEYS[self.castling]
        if self.ep >= 0:
            h ^= EP_KEYS[self.ep]
        self.hash, self.mg, self.eg, self.phase = h, mg, eg, phase

    # ------------------------------------------------------- make / unmake
    def make_move(self, move: int) -> None:
        """Make a pseudo-legal move (legality is checked by ``movegen.make_legal_move``)."""
        sq = self.sq
        frm = move & 0x7F
        to = (move >> 7) & 0x7F
        promo = (move >> 14) & 7
        piece = sq[frm]
        us = self.side
        captured = sq[to]
        h = self.hash
        mg = self.mg
        eg = self.eg
        phase = self.phase

        # Remove the old castling rights and en passant square from the hash.
        h ^= CASTLE_KEYS[self.castling]
        if self.ep >= 0:
            h ^= EP_KEYS[self.ep]

        if move & FLAG_EP:
            # En passant: the captured pawn stands behind the target square.
            cap_sq = to - 16 if us == WHITE else to + 16
            captured = sq[cap_sq]
            sq[cap_sq] = EMPTY
            idx = captured * 128 + cap_sq
            h ^= PIECE_KEYS[idx]
            mg -= PSQ_MG[idx]
            eg -= PSQ_EG[idx]
        elif captured:
            idx = captured * 128 + to
            h ^= PIECE_KEYS[idx]
            mg -= PSQ_MG[idx]
            eg -= PSQ_EG[idx]
            phase -= PIECE_PHASE[captured]

        self.stack.append((move, captured, self.castling, self.ep, self.halfmove, self.hash, self.mg, self.eg, self.phase))

        # Move the piece; on promotion the new piece is placed on the target square.
        sq[frm] = EMPTY
        idx = piece * 128 + frm
        h ^= PIECE_KEYS[idx]
        mg -= PSQ_MG[idx]
        eg -= PSQ_EG[idx]
        placed = make_piece(us, promo) if promo else piece
        if promo:
            phase += PIECE_PHASE[placed]
        sq[to] = placed
        idx = placed * 128 + to
        h ^= PIECE_KEYS[idx]
        mg += PSQ_MG[idx]
        eg += PSQ_EG[idx]

        if piece & 7 == KING:
            self.kings[us] = to
            if move & FLAG_CASTLE:
                # Castling: move the rook too.
                rook_from, rook_to = (to + 1, to - 1) if to > frm else (to - 2, to + 1)
                rook = sq[rook_from]
                sq[rook_from] = EMPTY
                sq[rook_to] = rook
                h ^= PIECE_KEYS[rook * 128 + rook_from] ^ PIECE_KEYS[rook * 128 + rook_to]
                mg += PSQ_MG[rook * 128 + rook_to] - PSQ_MG[rook * 128 + rook_from]
                eg += PSQ_EG[rook * 128 + rook_to] - PSQ_EG[rook * 128 + rook_from]

        self.castling &= CASTLE_MASK[frm] & CASTLE_MASK[to]
        self.ep = (frm + to) >> 1 if move & FLAG_DOUBLE else -1
        self.halfmove = 0 if (piece & 7) == PAWN or captured else self.halfmove + 1
        if us == BLACK:
            self.fullmove += 1
        self.side = us ^ 1

        h ^= SIDE_KEY ^ CASTLE_KEYS[self.castling]
        if self.ep >= 0:
            h ^= EP_KEYS[self.ep]
        self.hash = h
        self.mg = mg
        self.eg = eg
        self.phase = phase

    def unmake_move(self) -> None:
        """Undo the last move, restoring the state saved on the stack."""
        move, captured, castling, ep, halfmove, h, mg, eg, phase = self.stack.pop()
        sq = self.sq
        frm = move & 0x7F
        to = (move >> 7) & 0x7F
        self.side ^= 1
        us = self.side
        if us == BLACK:
            self.fullmove -= 1

        moved = sq[to]
        original = make_piece(us, PAWN) if (move >> 14) & 7 else moved
        sq[frm] = original
        if move & FLAG_EP:
            sq[to] = EMPTY
            sq[to - 16 if us == WHITE else to + 16] = captured
        else:
            sq[to] = captured

        if original & 7 == KING:
            self.kings[us] = frm
            if move & FLAG_CASTLE:
                rook_from, rook_to = (to + 1, to - 1) if to > frm else (to - 2, to + 1)
                sq[rook_from] = sq[rook_to]
                sq[rook_to] = EMPTY

        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.hash = h
        self.mg = mg
        self.eg = eg
        self.phase = phase

    def last_move(self) -> int:
        return self.stack[-1][0] if self.stack else 0

    def is_repetition(self) -> bool:
        """Has the current position already occurred since the last irreversible move?

        In search a single repetition is treated as a draw (further play would
        lead to threefold repetition).
        """
        stack = self.stack
        n = len(stack)
        stop = max(0, n - self.halfmove)
        h = self.hash
        for i in range(n - 2, stop - 1, -2):
            if stack[i][5] == h:
                return True
        return False
