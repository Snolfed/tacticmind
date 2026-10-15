"""Perft (performance test) liczy wszystkie liście drzewa legalnych ruchów.

Wartości referencyjne pochodzą z Chess Programming Wiki — jeśli generator ma
jakikolwiek błąd (roszady, en passant, promocje, związania), liczby się nie zgodzą.
"""

import pytest

from tacticmind.engine.board import Board
from tacticmind.engine.constants import START_FEN
from tacticmind.engine.movegen import perft

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POSITION_3 = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
POSITION_4 = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
POSITION_5 = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"


@pytest.mark.parametrize("depth, expected", [(1, 20), (2, 400), (3, 8_902), (4, 197_281)])
def test_perft_start(depth: int, expected: int) -> None:
    assert perft(Board(START_FEN), depth) == expected


@pytest.mark.parametrize("depth, expected", [(1, 48), (2, 2_039), (3, 97_862)])
def test_perft_kiwipete(depth: int, expected: int) -> None:
    assert perft(Board(KIWIPETE), depth) == expected


@pytest.mark.parametrize("depth, expected", [(1, 14), (2, 191), (3, 2_812), (4, 43_238)])
def test_perft_position_3(depth: int, expected: int) -> None:
    assert perft(Board(POSITION_3), depth) == expected


# Dodatkowe pozycje z CPW: promocje z biciem, roszady pod szachem, bicie w przelocie.
@pytest.mark.parametrize("depth, expected", [(1, 6), (2, 264), (3, 9_467)])
def test_perft_position_4(depth: int, expected: int) -> None:
    assert perft(Board(POSITION_4), depth) == expected


@pytest.mark.parametrize("depth, expected", [(1, 44), (2, 1_486), (3, 62_379)])
def test_perft_position_5(depth: int, expected: int) -> None:
    assert perft(Board(POSITION_5), depth) == expected


@pytest.mark.parametrize("fen", [START_FEN, KIWIPETE, POSITION_3, POSITION_4, POSITION_5])
def test_fen_roundtrip_and_incremental_state(fen: str) -> None:
    """FEN wraca bez zmian, a hasz i sumy oceny liczone przyrostowo zgadzają się z liczonymi od zera."""
    from tacticmind.engine.movegen import legal_moves

    board = Board(fen)
    assert board.fen() == fen
    for move in legal_moves(board):
        board.make_move(move)
        expected = (board.hash, board.mg, board.eg, board.phase)
        board.refresh()
        assert (board.hash, board.mg, board.eg, board.phase) == expected
        for reply in legal_moves(board):
            board.make_move(reply)
            snapshot = (board.hash, board.mg, board.eg, board.phase)
            board.refresh()
            assert (board.hash, board.mg, board.eg, board.phase) == snapshot
            board.unmake_move()
        board.unmake_move()
    assert board.fen() == fen
