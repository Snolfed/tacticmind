"""Best move search: negamax with alpha-beta cutoffs.

Key elements (details and pseudocode in the README):
 - negamax: minimax written as a single function; the opponent's score is our
   score with the sign flipped: max(a, b) = -min(-a, -b),
 - alpha-beta: we stop examining moves once it is known that the opponent
   won't allow this position anyway (beta cutoff),
 - iterative deepening: search depth 1, 2, 3... until time runs out;
   the result of a shallower iteration orders the moves in the deeper one,
 - quiescence search: at the leaves we play out captures so as not to evaluate
   a position in the middle of an exchange (horizon effect),
 - move ordering: PV/TT move, MVV-LVA captures, killer moves,
   history heuristic,
 - transposition table with Zobrist hashing,
 - mate scores with distance to mate (faster mate = better),
 - MultiPV: the 3 best moves with exact scores.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from .board import Board
from .constants import CAPTURE_MASK, FLAG_EP, PAWN, QUEEN
from .evaluation import evaluate, piece_value
from .movegen import generate_moves, in_check, is_square_attacked, legal_moves, make_legal_move, move_to_uci
from .tt import TT_EXACT, TT_LOWER, TT_UPPER, TranspositionTable
from .types import (
    INFINITY,
    MATE,
    MATE_BOUND,
    Bound,
    EngineScore,
    PvLine,
    SearchInfo,
    SearchProgress,
    Terminal,
    TreeNode,
    to_white_score,
)

MAX_PLY = 64
INF = INFINITY


@dataclass(slots=True)
class SearchLimits:
    #: Maximum iteration depth (in plies).
    max_depth: int = 64
    #: Time limit in milliseconds.
    time_ms: int = 2000
    #: Number of candidate lines (MultiPV).
    multi_pv: int = 1
    #: Whether to record the mini tree (first two levels) for visualisation.
    record_tree: bool = False


@dataclass(slots=True)
class RootMove:
    move: int
    score: int = -INF
    #: Whether the score is exact (and not just an upper bound after a fail-low).
    exact: bool = False
    pv: list[int] = field(default_factory=list)


class SearchStopped(Exception):
    """Search interrupted (time ran out or a stop command arrived)."""


class Searcher:
    """Search engine with iterative deepening; one instance serves many queries."""

    def __init__(self, tt_entries: int = 400_000) -> None:
        self.tt = TranspositionTable(tt_entries)
        #: Returns True when the search must stop (stop command from the UI).
        self.should_stop: Callable[[], bool] | None = None
        #: Called every ~100 ms during the search (live counters).
        self.on_progress: Callable[[SearchProgress], None] | None = None

        # Two killer moves per ply: quiet moves that recently caused a cutoff.
        self.killers = [[0, 0] for _ in range(MAX_PLY + 1)]
        # History heuristic: how often a move (piece, target square) caused a cutoff.
        self.history = [0] * (16 * 128)
        # Triangular principal variation table: pv_table[ply] = best line from ply onwards.
        self.pv_table: list[list[int]] = [[] for _ in range(MAX_PLY + 1)]

        self.board = Board()
        self.limits = SearchLimits()
        self.root_moves: list[RootMove] = []
        self.root_side = 0
        self.root_fen = ""
        self.depth_done = 0
        self.finished = True
        self.stopped = False
        self.can_stop_on_time = False
        self.start_time = 0.0
        self.deadline = 0.0
        self.last_progress = 0.0
        self.current_depth = 0
        self.last_info: SearchInfo | None = None
        self.terminal: Terminal | None = None

        # Statistics
        self.nodes = 0
        self.qnodes = 0
        self.cutoffs = 0
        self.tt_hits = 0
        self.searched_moves = 0
        self.pruned_moves = 0
        self.seldepth = 0

        # Mini tree recording
        self.recording = False
        self.tree_root: list[TreeNode] = []
        self.current_root_node: TreeNode | None = None

    # ------------------------------------------------------------------ API
    def start(self, board: Board, limits: SearchLimits) -> None:
        """Prepare a search for the position (the board is modified and restored)."""
        self.board = board
        self.limits = limits
        self.root_side = board.side
        self.root_fen = board.fen()
        self.nodes = self.qnodes = self.cutoffs = self.tt_hits = 0
        self.searched_moves = self.pruned_moves = self.seldepth = 0
        self.depth_done = 0
        self.finished = False
        self.stopped = False
        self.last_info = None
        self.killers = [[0, 0] for _ in range(MAX_PLY + 1)]
        # "Age" the history instead of clearing it; knowledge from the previous position is still useful.
        self.history = [h >> 2 for h in self.history]
        self.tt.new_search()
        self.start_time = time.perf_counter()
        self.deadline = self.start_time + limits.time_ms / 1000
        self.last_progress = self.start_time

        moves = legal_moves(board)
        self.root_moves = [RootMove(m, pv=[m]) for m in moves]
        self.terminal = None
        if not moves:
            self.terminal = "checkmate" if in_check(board) else "stalemate"
            self.finished = True

    def is_finished(self) -> bool:
        return self.finished

    def result(self) -> SearchInfo:
        """The last completed depth (or checkmate/stalemate info at the root)."""
        return self.last_info if self.last_info is not None else self._terminal_info()

    def iterate(self) -> SearchInfo | None:
        """Search the next depth (one iterative deepening step).

        Return info about the completed depth, or None when the search has finished.
        """
        if self.finished:
            return None
        depth = self.depth_done + 1
        elapsed = time.perf_counter() - self.start_time
        # Don't start a new depth once over half the time is used; it would not finish anyway.
        if depth > self.limits.max_depth or (depth > 1 and elapsed > self.limits.time_ms / 1000 * 0.5):
            self.finished = True
            return None
        self.can_stop_on_time = depth > 1
        self.current_depth = depth
        root_stack = len(self.board.stack)
        try:
            self._search_root(depth)
        except SearchStopped:
            # Interrupted mid-tree: undo the moves left on the board.
            while len(self.board.stack) > root_stack:
                self.board.unmake_move()
            self.current_root_node = None
            self.finished = True
            return None
        self.depth_done = depth
        info = self._build_info(depth)
        self.last_info = info

        # At depth d a full search sees every mate in at most d plies,
        # so the mate found won't improve any more: stop early.
        best = self.root_moves[0]
        if abs(best.score) > MATE_BOUND and depth >= MATE - abs(best.score):
            self.finished = True
        return info

    def search(
        self, board: Board, limits: SearchLimits, on_info: Callable[[SearchInfo], None] | None = None
    ) -> SearchInfo:
        """Synchronous search to completion (tests, scripts, benchmark)."""
        self.start(board, limits)
        while not self.finished:
            info = self.iterate()
            if info is not None and on_info is not None:
                on_info(info)
        return self.result()

    # ------------------------------------------------------- root (MultiPV)
    def _search_root(self, depth: int) -> None:
        """Search the root at the given depth.

        MultiPV is done in a single pass: alpha for the next move is the score of
        the K-th best move found so far. Moves in the top three thus get exact
        scores, while worse ones are cut off quickly (fail-low).
        """
        board = self.board
        k = min(self.limits.multi_pv, len(self.root_moves))
        top: list[RootMove] = []
        self.recording = self.limits.record_tree
        tree: list[TreeNode] = []

        for rm in self.root_moves:
            alpha = top[k - 1].score if len(top) >= k else -INF
            node = None
            if self.recording:
                node = TreeNode(move_to_uci(rm.move), None)
                self.current_root_node = node
            board.make_move(rm.move)
            score = -self._negamax(depth - 1, -INF, -alpha, 1)
            board.unmake_move()
            self.searched_moves += 1
            rm.score = score
            rm.exact = score > alpha
            if node is not None:
                node.score = to_white_score(score, self.root_side)
                node.bound = "exact" if rm.exact else "upper"
                tree.append(node)
            if rm.exact:
                # Line = root move + whatever came back from ply 1.
                rm.pv = [rm.move] + self.pv_table[1]
                top.append(rm)
                top.sort(key=lambda r: r.score, reverse=True)
                if len(top) > k:
                    top.pop()
        self.current_root_node = None

        # Order for the next iteration: best exact scores first.
        self.root_moves.sort(key=lambda r: (r.score, r.exact), reverse=True)
        best = self.root_moves[0]
        self.tt.store(board.hash, depth, TT_EXACT, best.score, best.move)
        if self.recording:
            sign = 1 if self.root_side == 0 else -1
            tree.sort(key=lambda n: sign * n.score.value if n.score else -INF, reverse=True)
            self.tree_root = tree

    # ------------------------------------------------- negamax with alpha-beta
    def _negamax(self, depth: int, alpha: int, beta: int, ply: int) -> int:
        board = self.board
        self.pv_table[ply] = []
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        # Draws: repetition and the 50-move rule (insufficient material is detected by the evaluation).
        if board.halfmove >= 100 or board.is_repetition():
            return 0

        checked = in_check(board)
        if checked:
            depth += 1  # check extension: don't cut the search short during an attack on the king
        if depth <= 0:
            return self._quiesce(alpha, beta, ply)

        self.nodes += 1
        if (self.nodes & 1023) == 0:
            self._check_time()
        if ply > self.seldepth:
            self.seldepth = ply

        # Transposition table: may give the result right away, or at least the best move.
        tt_move = 0
        entry = self.tt.probe(board.hash)
        if entry is not None:
            self.tt_hits += 1
            e_depth, e_flag, e_score, tt_move, _ = entry
            if e_depth >= depth:
                tt_score = _score_from_tt(e_score, ply)
                if (
                    e_flag == TT_EXACT
                    or (e_flag == TT_LOWER and tt_score >= beta)
                    or (e_flag == TT_UPPER and tt_score <= alpha)
                ):
                    if ply == 1 and self.current_root_node is not None:
                        self.current_root_node.tt_cut = True
                    return tt_score

        moves = generate_moves(board)
        scores = self._score_moves(moves, tt_move, ply)
        record = self.recording and ply == 1 and self.current_root_node is not None
        original_alpha = alpha
        best = -INF
        best_move = 0
        legal = 0
        count = len(moves)

        for i in range(count):
            move = _pick_move(moves, scores, i)
            if not make_legal_move(board, move):
                continue
            legal += 1
            score = -self._negamax(depth - 1, -beta, -alpha, ply + 1)
            board.unmake_move()
            self.searched_moves += 1
            if record:
                self._record_child(move, score, alpha, beta)

            if score > best:
                best = score
                best_move = move
                if score > alpha:
                    alpha = score
                    self.pv_table[ply] = [move] + self.pv_table[ply + 1]
                    if score >= beta:
                        # Beta cutoff: the opponent already has a better alternative; the remaining moves are unnecessary.
                        self.cutoffs += 1
                        self.pruned_moves += count - i - 1
                        if record:
                            self._record_pruned(moves, i + 1)
                        if not (move & CAPTURE_MASK) and not (move >> 14) & 7:
                            self._remember_quiet_cutoff(move, depth, ply)
                        break

        if legal == 0:
            # No legal moves: checkmate (the closer to the root, the worse) or stalemate.
            return -MATE + ply if checked else 0

        flag = TT_LOWER if best >= beta else TT_EXACT if best > original_alpha else TT_UPPER
        self.tt.store(board.hash, depth, flag, _score_to_tt(best, ply), best_move)
        return best

    def _quiesce(self, alpha: int, beta: int, ply: int) -> int:
        """Quiescence search: at a leaf, play out only captures (and promotions) until the position is quiet.

        "Stand pat" = static evaluation; the side to move doesn't have to capture if captures hurt it.
        """
        board = self.board
        self.nodes += 1
        self.qnodes += 1
        if (self.nodes & 1023) == 0:
            self._check_time()
        self.pv_table[ply] = []
        if ply > self.seldepth:
            self.seldepth = ply
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        checked = in_check(board)
        best = -INF
        if not checked:
            stand_pat = evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            if stand_pat > alpha:
                alpha = stand_pat
            best = stand_pat

        # In check all replies must be considered, otherwise we would miss mates.
        moves = generate_moves(board, captures_only=not checked)
        scores = self._score_moves(moves, 0, ply)
        sq = board.sq
        them = board.side ^ 1
        legal = 0
        for i in range(len(moves)):
            move = _pick_move(moves, scores, i)
            if not checked and not (move >> 14) & 7:
                to = (move >> 7) & 0x7F
                victim = piece_value(PAWN if move & FLAG_EP else sq[to] & 7)
                # Delta pruning: even capturing this piece with a margin won't raise alpha.
                if best + victim + 200 < alpha:
                    continue
                # Bad capture: a more valuable piece takes a cheaper one on a defended square; at a leaf that's a loss.
                if piece_value(sq[move & 0x7F] & 7) > victim + 50 and is_square_attacked(board, to, them):
                    continue
            if not make_legal_move(board, move):
                continue
            legal += 1
            score = -self._quiesce(-beta, -alpha, ply + 1)
            board.unmake_move()
            if score > best:
                best = score
                if score > alpha:
                    alpha = score
                    if score >= beta:
                        self.cutoffs += 1
                        break
        if checked and legal == 0:
            return -MATE + ply
        return best

    # ------------------------------------------------- move ordering
    def _score_moves(self, moves: list[int], tt_move: int, ply: int) -> list[int]:
        """Move scores for sorting. The better the first move, the more alpha-beta cutoffs.

        Order: TT/PV move > MVV-LVA captures > promotions > killers > history.
        """
        sq = self.board.sq
        killer1, killer2 = self.killers[ply]
        history = self.history
        scores = []
        for move in moves:
            if move == tt_move:
                scores.append(2_000_000)
                continue
            promo = (move >> 14) & 7
            if move & CAPTURE_MASK:
                # MVV-LVA: most valuable victim, least valuable attacker.
                victim = PAWN if move & FLAG_EP else sq[(move >> 7) & 0x7F] & 7
                score = 1_000_000 + victim * 100 - (sq[move & 0x7F] & 7)
                if promo == QUEEN:
                    score += 500
            elif promo == QUEEN:
                score = 950_000
            elif promo:
                score = -100_000  # underpromotion (rook/bishop/knight) last
            elif move == killer1:
                score = 900_000
            elif move == killer2:
                score = 800_000
            else:
                score = history[sq[move & 0x7F] * 128 + ((move >> 7) & 0x7F)]
            scores.append(score)
        return scores

    def _remember_quiet_cutoff(self, move: int, depth: int, ply: int) -> None:
        killers = self.killers[ply]
        if killers[0] != move:
            killers[1] = killers[0]
            killers[0] = move
        # The move has already been undone, so the piece stands on its origin square.
        idx = self.board.sq[move & 0x7F] * 128 + ((move >> 7) & 0x7F)
        self.history[idx] += depth * depth
        if self.history[idx] > 400_000:
            self.history = [h >> 1 for h in self.history]

    # ------------------------------------------- time, statistics, mini tree
    def _check_time(self) -> None:
        now = time.perf_counter()
        if self.should_stop is not None and self.should_stop():
            self.stopped = True
        if self.can_stop_on_time and now >= self.deadline:
            self.stopped = True
        if self.on_progress is not None and now - self.last_progress >= 0.1:
            self.last_progress = now
            elapsed = now - self.start_time
            self.on_progress(
                SearchProgress(
                    id=0,
                    depth=self.current_depth,
                    nodes=self.nodes,
                    nps=int(self.nodes / max(elapsed, 1e-3)),
                    cutoffs=self.cutoffs,
                    tt_hits=self.tt_hits,
                    time_ms=int(elapsed * 1000),
                )
            )
        if self.stopped:
            raise SearchStopped

    def _record_child(self, move: int, score: int, alpha: int, beta: int) -> None:
        """Record the opponent's reply (tree level 2) in the mini tree."""
        node = self.current_root_node
        if node is None:
            return
        # ``score`` is from the perspective of the side to move at ply 1 (the root's opponent).
        bound: Bound = "upper" if score <= alpha else "lower" if score >= beta else "exact"
        node.children.append(TreeNode(move_to_uci(move), to_white_score(score, self.root_side ^ 1), bound))

    def _record_pruned(self, moves: list[int], start: int) -> None:
        """Moves that alpha-beta never examined (after a cutoff)."""
        node = self.current_root_node
        if node is None:
            return
        board = self.board
        for move in moves[start:]:
            if make_legal_move(board, move):
                board.unmake_move()
                node.children.append(TreeNode(move_to_uci(move), None, pruned=True))

    def _extend_pv(self, pv: list[int], max_length: int) -> list[int]:
        """When the line is shorter than the depth (e.g. due to a TT cutoff), extend it from the transposition table."""
        board = self.board
        result = list(pv)
        for move in pv:
            board.make_move(move)
        made = len(pv)
        while len(result) < max_length:
            entry = self.tt.probe(board.hash)
            if entry is None or entry[3] == 0 or entry[3] not in legal_moves(board):
                break
            board.make_move(entry[3])
            made += 1
            result.append(entry[3])
            if board.is_repetition():
                break
        for _ in range(made):
            board.unmake_move()
        return result

    def _build_info(self, depth: int) -> SearchInfo:
        elapsed = max(time.perf_counter() - self.start_time, 1e-3)
        k = min(self.limits.multi_pv, len(self.root_moves))
        lines: list[PvLine] = []
        for i in range(k):
            rm = self.root_moves[i]
            if not rm.exact and i > 0:
                break
            pv = self._extend_pv(rm.pv, max(depth, len(rm.pv)))
            lines.append(PvLine(move_to_uci(rm.move), to_white_score(rm.score, self.root_side), [move_to_uci(m) for m in pv]))
        main = lines[0]
        total = self.searched_moves + self.pruned_moves
        return SearchInfo(
            id=0,
            fen=self.root_fen,
            depth=depth,
            seldepth=max(self.seldepth, depth),
            score_cp=main.score.cp,
            mate_in=main.score.mate,
            score=main.score,
            best_move=main.move,
            pv=main.pv,
            multi_pv=lines,
            nodes=self.nodes,
            qnodes=self.qnodes,
            nps=int(self.nodes / elapsed),
            cutoffs=self.cutoffs,
            tt_hits=self.tt_hits,
            pruned_percent=round(100 * self.pruned_moves / total, 1) if total else 0.0,
            time_ms=int(elapsed * 1000),
            tree=self.tree_root if self.recording else [],
        )

    def _terminal_info(self) -> SearchInfo:
        """Checkmate or stalemate at the root (or interruption before depth 1 completed)."""
        mated = self.terminal == "checkmate"
        if mated:
            value = -MATE if self.root_side == 0 else MATE
            score = EngineScore(None, 0, value)
        else:
            score = EngineScore(0, None, 0)
        return SearchInfo(
            id=0,
            fen=self.root_fen,
            depth=0,
            seldepth=0,
            score_cp=score.cp,
            mate_in=score.mate,
            score=score,
            best_move="",
            pv=[],
            multi_pv=[],
            nodes=self.nodes,
            qnodes=self.qnodes,
            nps=0,
            cutoffs=self.cutoffs,
            tt_hits=self.tt_hits,
            pruned_percent=0.0,
            time_ms=int((time.perf_counter() - self.start_time) * 1000),
            tree=[],
            terminal=self.terminal,
        )


def _pick_move(moves: list[int], scores: list[int], start: int) -> int:
    """Pick the highest-scored remaining move (lazy selection sort).

    Lazy, because after a beta cutoff the rest of the list doesn't need sorting anyway.
    """
    best_index = start
    best_score = scores[start]
    for j in range(start + 1, len(moves)):
        if scores[j] > best_score:
            best_score = scores[j]
            best_index = j
    if best_index != start:
        moves[start], moves[best_index] = moves[best_index], moves[start]
        scores[start], scores[best_index] = scores[best_index], scores[start]
    return moves[start]


def _score_to_tt(score: int, ply: int) -> int:
    """Mate scores are stored in the TT relative to the current node, not the root."""
    if score > MATE_BOUND:
        return score + ply
    if score < -MATE_BOUND:
        return score - ply
    return score


def _score_from_tt(score: int, ply: int) -> int:
    if score > MATE_BOUND:
        return score - ply
    if score < -MATE_BOUND:
        return score + ply
    return score


def find_best_move(fen_or_board: str | Board, **limits: int | bool) -> SearchInfo:
    """Convenience function: the best move for a position (tests, scripts)."""
    board = fen_or_board if isinstance(fen_or_board, Board) else Board(fen_or_board)
    params = SearchLimits(max_depth=64, time_ms=5000, multi_pv=1)
    for key, value in limits.items():
        setattr(params, key, value)
    return Searcher().search(board, params)
