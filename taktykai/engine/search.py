"""Wyszukiwanie najlepszego ruchu: negamax z cięciami alfa-beta.

Najważniejsze elementy (szczegóły i pseudokod w README):
 - negamax: minimaks zapisany jedną funkcją; wynik dla przeciwnika to wynik
   dla nas ze zmienionym znakiem: max(a, b) = -min(-a, -b),
 - alfa-beta: przestajemy przeglądać ruchy, gdy wiadomo, że przeciwnik i tak
   nie dopuści do tej pozycji (cięcie beta),
 - iterative deepening: liczymy głębokość 1, 2, 3… aż skończy się czas;
   wynik płytszej iteracji porządkuje ruchy w głębszej,
 - quiescence search: w liściach dogrywamy bicia, żeby nie oceniać pozycji
   w połowie wymiany (efekt horyzontu),
 - porządkowanie ruchów: ruch z PV/TT, bicia wg MVV-LVA, ruchy killer,
   history heuristic,
 - tablica transpozycji z haszem Zobrista,
 - wyniki matowe z odległością do mata (szybszy mat = lepszy),
 - MultiPV: 3 najlepsze ruchy z dokładnymi ocenami.
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
    #: Maksymalna głębokość iteracji (w półruchach).
    max_depth: int = 64
    #: Limit czasu w milisekundach.
    time_ms: int = 2000
    #: Liczba linii kandydujących (MultiPV).
    multi_pv: int = 1
    #: Czy zapisywać mini-drzewo (dwa pierwsze poziomy) do wizualizacji.
    record_tree: bool = False


@dataclass(slots=True)
class RootMove:
    move: int
    score: int = -INF
    #: Czy wynik jest dokładny (a nie tylko górnym ograniczeniem po fail-low).
    exact: bool = False
    pv: list[int] = field(default_factory=list)


class SearchStopped(Exception):
    """Przerwanie wyszukiwania (czas minął albo przyszła komenda stop)."""


class Searcher:
    """Silnik wyszukiwania z iterative deepening; jedna instancja na wiele zapytań."""

    def __init__(self, tt_entries: int = 400_000) -> None:
        self.tt = TranspositionTable(tt_entries)
        #: Zwraca True, gdy trzeba przerwać liczenie (komenda stop z interfejsu).
        self.should_stop: Callable[[], bool] | None = None
        #: Wywoływane co ok. 100 ms w trakcie liczenia (liczniki na żywo).
        self.on_progress: Callable[[SearchProgress], None] | None = None

        # Dwa ruchy killer na każdy poziom: ciche ruchy, które ostatnio dały cięcie.
        self.killers = [[0, 0] for _ in range(MAX_PLY + 1)]
        # History heuristic: jak często ruch (figura, pole docelowe) dawał cięcie.
        self.history = [0] * (16 * 128)
        # Trójkątna tablica głównego wariantu: pv_table[ply] = najlepsza linia od poziomu ply.
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

        # Statystyki
        self.nodes = 0
        self.qnodes = 0
        self.cutoffs = 0
        self.tt_hits = 0
        self.searched_moves = 0
        self.pruned_moves = 0
        self.seldepth = 0

        # Rejestrowanie mini-drzewa
        self.recording = False
        self.tree_root: list[TreeNode] = []
        self.current_root_node: TreeNode | None = None

    # ------------------------------------------------------------------ API
    def start(self, board: Board, limits: SearchLimits) -> None:
        """Przygotowuje wyszukiwanie dla pozycji (plansza jest modyfikowana i przywracana)."""
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
        # Historię „postarzamy” zamiast zerować — wiedza z poprzedniej pozycji wciąż się przydaje.
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
        """Ostatnia ukończona głębokość (albo informacja o macie/pacie w korzeniu)."""
        return self.last_info if self.last_info is not None else self._terminal_info()

    def iterate(self) -> SearchInfo | None:
        """Liczy kolejną głębokość (jeden krok iterative deepening).

        Zwraca informacje o ukończonej głębokości albo None, gdy wyszukiwanie się skończyło.
        """
        if self.finished:
            return None
        depth = self.depth_done + 1
        elapsed = time.perf_counter() - self.start_time
        # Nie zaczynaj nowej głębokości, gdy zużyto ponad połowę czasu — i tak by się nie skończyła.
        if depth > self.limits.max_depth or (depth > 1 and elapsed > self.limits.time_ms / 1000 * 0.5):
            self.finished = True
            return None
        self.can_stop_on_time = depth > 1
        self.current_depth = depth
        root_stack = len(self.board.stack)
        try:
            self._search_root(depth)
        except SearchStopped:
            # Przerwanie w środku drzewa: cofnij ruchy, które zostały na planszy.
            while len(self.board.stack) > root_stack:
                self.board.unmake_move()
            self.current_root_node = None
            self.finished = True
            return None
        self.depth_done = depth
        info = self._build_info(depth)
        self.last_info = info

        # Na głębokości d pełne przeszukanie widzi każdego mata w co najwyżej d półruchach,
        # więc znaleziony mat już się nie poprawi — kończymy wcześniej.
        best = self.root_moves[0]
        if abs(best.score) > MATE_BOUND and depth >= MATE - abs(best.score):
            self.finished = True
        return info

    def search(
        self, board: Board, limits: SearchLimits, on_info: Callable[[SearchInfo], None] | None = None
    ) -> SearchInfo:
        """Wyszukiwanie synchroniczne do końca (testy, skrypty, benchmark)."""
        self.start(board, limits)
        while not self.finished:
            info = self.iterate()
            if info is not None and on_info is not None:
                on_info(info)
        return self.result()

    # ------------------------------------------------------- korzeń (MultiPV)
    def _search_root(self, depth: int) -> None:
        """Przeszukanie korzenia na danej głębokości.

        MultiPV realizujemy jednym przebiegiem: alfa dla kolejnego ruchu to wynik
        K-tego najlepszego ruchu znalezionego do tej pory. Ruchy z pierwszej
        trójki dostają więc dokładne oceny, a gorsze są szybko odcinane (fail-low).
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
                # Wariant = ruch z korzenia + to, co wróciło z poziomu 1.
                rm.pv = [rm.move] + self.pv_table[1]
                top.append(rm)
                top.sort(key=lambda r: r.score, reverse=True)
                if len(top) > k:
                    top.pop()
        self.current_root_node = None

        # Kolejność na następną iterację: najlepsze dokładne wyniki na początku.
        self.root_moves.sort(key=lambda r: (r.score, r.exact), reverse=True)
        best = self.root_moves[0]
        self.tt.store(board.hash, depth, TT_EXACT, best.score, best.move)
        if self.recording:
            sign = 1 if self.root_side == 0 else -1
            tree.sort(key=lambda n: sign * n.score.value if n.score else -INF, reverse=True)
            self.tree_root = tree

    # ------------------------------------------------- negamax z alfa-betą
    def _negamax(self, depth: int, alpha: int, beta: int, ply: int) -> int:
        board = self.board
        self.pv_table[ply] = []
        if ply >= MAX_PLY - 1:
            return evaluate(board)

        # Remisy: powtórzenie pozycji i reguła 50 ruchów (brak materiału wykrywa funkcja oceny).
        if board.halfmove >= 100 or board.is_repetition():
            return 0

        checked = in_check(board)
        if checked:
            depth += 1  # przedłużenie szacha: nie urywaj liczenia w trakcie ataku na króla
        if depth <= 0:
            return self._quiesce(alpha, beta, ply)

        self.nodes += 1
        if (self.nodes & 1023) == 0:
            self._check_time()
        if ply > self.seldepth:
            self.seldepth = ply

        # Tablica transpozycji: może od razu dać wynik albo przynajmniej najlepszy ruch.
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
                        # Cięcie beta: przeciwnik ma już lepszą alternatywę, reszta ruchów jest zbędna.
                        self.cutoffs += 1
                        self.pruned_moves += count - i - 1
                        if record:
                            self._record_pruned(moves, i + 1)
                        if not (move & CAPTURE_MASK) and not (move >> 14) & 7:
                            self._remember_quiet_cutoff(move, depth, ply)
                        break

        if legal == 0:
            # Brak legalnych ruchów: mat (im bliżej korzenia, tym gorzej) albo pat.
            return -MATE + ply if checked else 0

        flag = TT_LOWER if best >= beta else TT_EXACT if best > original_alpha else TT_UPPER
        self.tt.store(board.hash, depth, flag, _score_to_tt(best, ply), best_move)
        return best

    def _quiesce(self, alpha: int, beta: int, ply: int) -> int:
        """Quiescence search: w liściu dogrywamy tylko bicia (i promocje), aż pozycja się uspokoi.

        „Stand pat” = ocena statyczna; strona na ruchu nie musi bić, jeśli bicia jej szkodzą.
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

        # W szachu trzeba rozważyć wszystkie odpowiedzi — inaczej przeoczylibyśmy mata.
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
                # Delta pruning: nawet zbicie tej figury z zapasem nie podniesie alfy.
                if best + victim + 200 < alpha:
                    continue
                # Złe bicie: droższa figura bije tańszą na bronionym polu — w liściu to strata.
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

    # ------------------------------------------------- porządkowanie ruchów
    def _score_moves(self, moves: list[int], tt_move: int, ply: int) -> list[int]:
        """Oceny ruchów do sortowania. Im lepszy ruch na początku, tym więcej cięć alfa-beta.

        Kolejność: ruch z TT/PV > bicia wg MVV-LVA > promocje > killery > history.
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
                # MVV-LVA: najcenniejsza ofiara, najtańszy napastnik.
                victim = PAWN if move & FLAG_EP else sq[(move >> 7) & 0x7F] & 7
                score = 1_000_000 + victim * 100 - (sq[move & 0x7F] & 7)
                if promo == QUEEN:
                    score += 500
            elif promo == QUEEN:
                score = 950_000
            elif promo:
                score = -100_000  # słaba promocja (wieża/goniec/skoczek) na koniec
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
        # Ruch został już cofnięty, więc figura stoi na polu startowym.
        idx = self.board.sq[move & 0x7F] * 128 + ((move >> 7) & 0x7F)
        self.history[idx] += depth * depth
        if self.history[idx] > 400_000:
            self.history = [h >> 1 for h in self.history]

    # ------------------------------------------- czas, statystyki, mini-drzewo
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
        """Zapisuje odpowiedź przeciwnika (poziom 2 drzewa) do mini-drzewa."""
        node = self.current_root_node
        if node is None:
            return
        # ``score`` jest z perspektywy strony na ruchu na poziomie 1 (przeciwnika korzenia).
        bound: Bound = "upper" if score <= alpha else "lower" if score >= beta else "exact"
        node.children.append(TreeNode(move_to_uci(move), to_white_score(score, self.root_side ^ 1), bound))

    def _record_pruned(self, moves: list[int], start: int) -> None:
        """Ruchy, których alfa-beta w ogóle nie sprawdziła (po cięciu)."""
        node = self.current_root_node
        if node is None:
            return
        board = self.board
        for move in moves[start:]:
            if make_legal_move(board, move):
                board.unmake_move()
                node.children.append(TreeNode(move_to_uci(move), None, pruned=True))

    def _extend_pv(self, pv: list[int], max_length: int) -> list[int]:
        """Gdy wariant jest krótszy niż głębokość (np. przez cięcie z TT), dociągamy go z tablicy transpozycji."""
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
        """Mat lub pat już w korzeniu (albo przerwanie przed ukończeniem głębokości 1)."""
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
    """Wybiera najlepiej oceniony z pozostałych ruchów (sortowanie przez wybór, leniwie).

    Leniwie, bo po cięciu beta reszty listy i tak nie potrzebujemy sortować.
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
    """Wynik matowy w TT zapisujemy względem bieżącego węzła, a nie korzenia."""
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
    """Wygodna funkcja: najlepszy ruch dla pozycji (testy, skrypty)."""
    board = fen_or_board if isinstance(fen_or_board, Board) else Board(fen_or_board)
    params = SearchLimits(max_depth=64, time_ms=5000, multi_pv=1)
    for key, value in limits.items():
        setattr(params, key, value)
    return Searcher().search(board, params)
