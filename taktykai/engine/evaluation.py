"""Funkcja oceny pozycji.

Ocena = materiał + tablice pozycyjne (PST) + mobilność + bezpieczeństwo króla
+ struktura pionków + para gońców. Każdy składnik ma wartość dla gry środkowej
(mg) i końcówki (eg); wynik to średnia ważona fazą gry („tapered eval”).

Materiał i PST plansza sumuje przyrostowo przy każdym ruchu (``board.mg``,
``board.eg``), tutaj dokładamy tylko składniki zależne od układu figur.

Wynik jest w centypionach (100 = jeden pion). ``evaluate`` zwraca go
z perspektywy strony na ruchu — tego wymaga negamax.
"""

from __future__ import annotations

from dataclasses import dataclass

from .board import Board
from .constants import (
    BISHOP,
    BISHOP_RAYS,
    BLACK,
    KING,
    KNIGHT,
    KNIGHT_TARGETS,
    PAWN,
    QUEEN_RAYS,
    ROOK,
    ROOK_RAYS,
    SQUARES,
    WHITE,
)
from .pst import MATERIAL_EG, MATERIAL_MG, MAX_PHASE

#: Mobilność: premia za każde dostępne pole ponad typową liczbę pól (mg, eg).
MOBILITY_MG = (0, 0, 4, 5, 2, 1, 0)
MOBILITY_EG = (0, 0, 4, 5, 4, 2, 0)
MOBILITY_BASE = (0, 0, 4, 6, 6, 12, 0)

#: Premia za piona przechodniego wg rzędu (z perspektywy właściciela).
PASSED_MG = (0, 5, 10, 15, 25, 40, 60, 0)
PASSED_EG = (0, 10, 20, 35, 60, 95, 140, 0)

#: Waga „przyciągania” do wrogiego króla (tropizm) — część bezpieczeństwa króla.
TROPISM = (0, 0, 2, 1, 2, 4, 0)

BISHOP_PAIR = (30, 50)
DOUBLED = (10, 20)
ISOLATED = (10, 15)


@dataclass(slots=True)
class EvalBreakdown:
    """Rozbicie oceny na składniki (perspektywa białych, centypiony) — do panelu w UI."""

    material: int
    pst: int
    mobility: int
    king_safety: int
    pawns: int
    bishop_pair: int
    phase: int
    total: int


def evaluate(board: Board) -> int:
    """Ocena z perspektywy strony na ruchu (wywoływana w liściach drzewa)."""
    score = evaluate_white(board)
    return score if board.side == WHITE else -score


def evaluate_white(board: Board) -> int:
    """Ocena z perspektywy białych."""
    return _evaluate(board, None)


def explain(board: Board) -> EvalBreakdown:
    """Ocena rozbita na składniki (wolniej, tylko dla interfejsu i testów)."""
    parts: dict[str, int] = {}
    _evaluate(board, parts)
    return EvalBreakdown(**parts)


def _taper(mg: int, eg: int, phase: int) -> int:
    return (mg * phase + eg * (MAX_PHASE - phase)) // MAX_PHASE


def _evaluate(board: Board, parts: dict[str, int] | None) -> int:
    sq = board.sq
    phase = min(board.phase, MAX_PHASE)

    # Liczba pionów na kolumnach i ich najdalej/najbliżej wysunięte rzędy.
    pawn_count = ([0] * 8, [0] * 8)
    pawn_min = ([8] * 8, [8] * 8)
    pawn_max = ([-1] * 8, [-1] * 8)
    mob_mg = [0, 0]
    mob_eg = [0, 0]
    tropism = [0, 0]  # presja figur danego koloru na wrogiego króla
    bishops = [0, 0]
    kings = board.kings
    any_pawn = False

    for s in SQUARES:
        piece = sq[s]
        if not piece:
            continue
        kind = piece & 7
        color = piece >> 3
        if kind == PAWN:
            any_pawn = True
            f = s & 7
            r = s >> 4
            pawn_count[color][f] += 1
            if r < pawn_min[color][f]:
                pawn_min[color][f] = r
            if r > pawn_max[color][f]:
                pawn_max[color][f] = r
            continue
        if kind == KING:
            continue
        if kind == BISHOP:
            bishops[color] += 1

        # Mobilność: liczba pól, na które figura może pójść (puste lub z wrogą figurą).
        mobility = 0
        if kind == KNIGHT:
            for t in KNIGHT_TARGETS[s]:
                target = sq[t]
                if not target or (target >> 3) != color:
                    mobility += 1
        else:
            rays = BISHOP_RAYS[s] if kind == BISHOP else ROOK_RAYS[s] if kind == ROOK else QUEEN_RAYS[s]
            for ray in rays:
                for t in ray:
                    target = sq[t]
                    if not target:
                        mobility += 1
                    else:
                        if (target >> 3) != color:
                            mobility += 1
                        break
        extra = mobility - MOBILITY_BASE[kind]
        mob_mg[color] += extra * MOBILITY_MG[kind]
        mob_eg[color] += extra * MOBILITY_EG[kind]
        # Tropizm: im bliżej wrogiego króla stoi figura, tym groźniejszy atak.
        enemy_king = kings[color ^ 1]
        distance = max(abs((enemy_king & 7) - (s & 7)), abs((enemy_king >> 4) - (s >> 4)))
        tropism[color] += (7 - distance) * TROPISM[kind]

    # Brak materiału do mata: same króle albo król z jedną lekką figurą.
    if not any_pawn and board.phase <= 1:
        if parts is not None:
            parts.update(material=0, pst=0, mobility=0, king_safety=0, pawns=0, bishop_pair=0, phase=phase, total=0)
        return 0

    # Struktura pionków: zdwojone, izolowane, przechodnie.
    pawns_mg = [0, 0]
    pawns_eg = [0, 0]
    for color in (WHITE, BLACK):
        own = pawn_count[color]
        enemy_min = pawn_min[color ^ 1]
        enemy_max = pawn_max[color ^ 1]
        mg = eg = 0
        for f in range(8):
            n = own[f]
            if not n:
                continue
            if n > 1:
                mg -= DOUBLED[0] * (n - 1)
                eg -= DOUBLED[1] * (n - 1)
            if (f == 0 or not own[f - 1]) and (f == 7 or not own[f + 1]):
                mg -= ISOLATED[0] * n
                eg -= ISOLATED[1] * n
            # Pion przechodni: przed najdalej wysuniętym pionem nie ma wrogich pionów
            # na tej samej ani na sąsiednich kolumnach.
            lo, hi = max(0, f - 1), min(7, f + 1)
            if color == WHITE:
                rank = pawn_max[WHITE][f]
                passed = all(enemy_max[g] <= rank for g in range(lo, hi + 1))
                rel = rank
            else:
                rank = pawn_min[BLACK][f]
                passed = all(enemy_min[g] >= rank for g in range(lo, hi + 1))
                rel = 7 - rank
            if passed:
                mg += PASSED_MG[rel]
                eg += PASSED_EG[rel]
        pawns_mg[color] = mg
        pawns_eg[color] = eg

    # Bezpieczeństwo króla (tylko gra środkowa): osłona pionków minus presja wrogich figur.
    shield_w = _king_shield(board, WHITE, pawn_count)
    shield_b = _king_shield(board, BLACK, pawn_count)
    king_mg = (shield_w - tropism[BLACK]) - (shield_b - tropism[WHITE])

    pair_mg = pair_eg = 0
    if bishops[WHITE] >= 2:
        pair_mg += BISHOP_PAIR[0]
        pair_eg += BISHOP_PAIR[1]
    if bishops[BLACK] >= 2:
        pair_mg -= BISHOP_PAIR[0]
        pair_eg -= BISHOP_PAIR[1]

    mg_total = board.mg + (mob_mg[0] - mob_mg[1]) + (pawns_mg[0] - pawns_mg[1]) + king_mg + pair_mg
    eg_total = board.eg + (mob_eg[0] - mob_eg[1]) + (pawns_eg[0] - pawns_eg[1]) + pair_eg
    total = _taper(mg_total, eg_total, phase)

    if parts is not None:
        mat_mg = mat_eg = 0
        for s in SQUARES:
            piece = sq[s]
            if piece:
                sign = 1 if piece >> 3 == WHITE else -1
                mat_mg += sign * MATERIAL_MG[piece & 7]
                mat_eg += sign * MATERIAL_EG[piece & 7]
        material = _taper(mat_mg, mat_eg, phase)
        parts.update(
            material=material,
            pst=_taper(board.mg - mat_mg, board.eg - mat_eg, phase),
            mobility=_taper(mob_mg[0] - mob_mg[1], mob_eg[0] - mob_eg[1], phase),
            king_safety=_taper(king_mg, 0, phase),
            pawns=_taper(pawns_mg[0] - pawns_mg[1], pawns_eg[0] - pawns_eg[1], phase),
            bishop_pair=_taper(pair_mg, pair_eg, phase),
            phase=phase,
            total=total,
        )
    return total


def _king_shield(board: Board, color: int, pawn_count: tuple[list[int], list[int]]) -> int:
    """Osłona króla: premia za własne piony przed królem, kara za brak osłony i otwarte linie."""
    king = board.kings[color]
    k_file, k_rank = king & 7, king >> 4
    home = 0 if color == WHITE else 7
    if abs(k_rank - home) > 1:
        return -20  # król wyszedł z ukrycia
    step = 16 if color == WHITE else -16
    own_pawn = (color << 3) | PAWN
    sq = board.sq
    own = pawn_count[color]
    enemy = pawn_count[color ^ 1]
    score = 0
    for f in range(max(0, k_file - 1), min(7, k_file + 1) + 1):
        one = (king & 0x70) + f + step
        two = one + step
        if not (one & 0x88) and sq[one] == own_pawn:
            score += 12
        elif not (two & 0x88) and sq[two] == own_pawn:
            score += 6
        else:
            score -= 12
        if not own[f]:
            score -= 15 if not enemy[f] else 8  # linia otwarta / półotwarta przy królu
    return score


def piece_value(kind: int) -> int:
    """Wartość figury (gra środkowa) — do porządkowania i przycinania bić."""
    return MATERIAL_MG[kind]


__all__ = ["evaluate", "evaluate_white", "explain", "piece_value", "EvalBreakdown"]
