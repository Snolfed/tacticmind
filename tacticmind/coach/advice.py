"""Słowne wyjaśnienia trenera: co robi ruch, czym grozi przeciwnik i jaki ruch byłby lepszy.

Wyjaśnienia są **danymi** (``Phrase`` — klucz tłumaczenia + parametry), a nie gotowym tekstem.
Tekst powstaje dopiero przy rysowaniu (``render``), więc po zmianie języka w trakcie partii
wszystkie komentarze trenera od razu mówią w nowym języku, z właściwymi literami figur w notacji.

Skąd trener wie, co powiedzieć (bez modelu językowego — tylko reguły i wyniki silnika):
 - **co robi ruch** — proste fakty z pozycji: bicie, szach, roszada, atak na figurę (także dwie
   naraz — widełki), zabranie figury spod ataku, osłona figury, rozwój, walka o centrum, wieża
   na otwartej linii,
 - **co było lepsze** — najlepszy ruch i wariant z analizy silnika (MultiPV) przed ruchem gracza;
   bilans materiału na końcu wariantu mówi, czy lepszy ruch wygrywał materiał albo dawał mata,
 - **czym grozi przeciwnik** — wariant silnika po ruchu gracza: mat albo strata materiału.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from ..brain.notation import format_line, uci_san
from ..brain.thoughts import material
from ..engine.types import MATE, MATE_BOUND, EngineScore, format_score
from ..i18n import t, tn
from .review import WEAK, Classification

Person = str  # "you" (gracz) | "me" (trener) | "it" (proponowany ruch)

_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
_NAMES = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
_CENTER = {chess.D4, chess.E4, chess.D5, chess.E5}
_HOME = {
    chess.WHITE: {chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT, chess.C1: chess.BISHOP, chess.F1: chess.BISHOP},
    chess.BLACK: {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT, chess.C8: chess.BISHOP, chess.F8: chess.BISHOP},
}


# ---------------------------------------------------------------------------
# Elementy wyjaśnień (tłumaczone przy rysowaniu)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class San:
    """Ruch w notacji SAN z literami figur w języku interfejsu."""

    fen: str
    uci: str


@dataclass(frozen=True)
class Line:
    """Wariant z numerami ruchów, np. „1. Hxf7+ Kxf7 2. Sg5+”."""

    fen: str
    ucis: tuple[str, ...]


@dataclass(frozen=True)
class PieceName:
    """Nazwa figury w bierniku („skoczka”, „wieżę” / “knight”, “rook”)."""

    piece_type: int


@dataclass(frozen=True)
class Material:
    """Ilość materiału w pionach: „piona”, „figurę”, „wieżę”, „hetmana” albo „5 pkt materiału”."""

    points: int


@dataclass(frozen=True)
class Score:
    """Ocena z perspektywy gracza (wartość silnika, mat = ±(32000 − półruchy))."""

    value: int


@dataclass(frozen=True)
class Phrase:
    key: str
    params: tuple[tuple[str, object], ...] = ()
    #: Liczba do odmiany (klucz z końcówkami .one/.few/.many), np. „2 błędy”, „5 błędów”.
    count: int | None = None


@dataclass(frozen=True)
class Features:
    """Lista cech ruchu połączona spójnikiem („rozwijasz skoczka i walczysz o centrum”)."""

    items: tuple[Phrase, ...]


def phrase(key: str, **params: object) -> Phrase:
    return Phrase(key, tuple(params.items()))


Comment = tuple[Phrase, ...]


def render(item: object) -> str:
    """Zamiana elementu wyjaśnienia na tekst w bieżącym języku."""
    if isinstance(item, Phrase):
        params = {name: render(value) for name, value in item.params}
        if item.count is not None:
            return tn(item.key, item.count, **params)
        return t(item.key, **params)
    if isinstance(item, San):
        return uci_san(item.fen, item.uci)
    if isinstance(item, Line):
        return format_line(item.fen, list(item.ucis), None)
    if isinstance(item, PieceName):
        return t(f"piece.acc.{_NAMES[item.piece_type]}")
    if isinstance(item, Material):
        named = {1: "pawn", 3: "piece", 5: "rook", 9: "queen"}.get(item.points)
        return t(f"material.{named}") if named else t("material.points", n=item.points)
    if isinstance(item, Score):
        return _format_value(item.value)
    if isinstance(item, Features):
        texts = [render(p) for p in item.items]
        if len(texts) <= 1:
            return "".join(texts)
        return ", ".join(texts[:-1]) + t("list.and") + texts[-1]
    return str(item)


def render_comment(comment: Comment) -> str:
    """Kilka zdań komentarza, każde zaczęte wielką literą."""
    return " ".join(_capitalize(render(p)) for p in comment if p.key)


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _format_value(value: int) -> str:
    if abs(value) > MATE_BOUND:
        plies = MATE - abs(value)
        moves = (plies + 1) // 2
        return f"M{moves}" if value > 0 else f"-M{moves}"
    return format_score(EngineScore(value, None, value)).replace(".", t("fmt.decimal"))


# ---------------------------------------------------------------------------
# Fakty o pozycji
# ---------------------------------------------------------------------------
def is_hanging(board: chess.Board, square: chess.Square) -> bool:
    """Figura „wisi”: jest atakowana i nie ma obrony albo atakuje ją tańsza figura."""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type == chess.KING:
        return False
    attackers = board.attackers(not piece.color, square)
    if not attackers:
        return False
    if not board.attackers(piece.color, square):
        return True
    cheapest = min(_VALUES[board.piece_type_at(sq) or chess.PAWN] or 100 for sq in attackers)
    return cheapest < _VALUES[piece.piece_type]


def _hanging_pieces(board: chess.Board, color: chess.Color) -> set[chess.Square]:
    return {sq for sq, piece in board.piece_map().items() if piece.color == color and piece.piece_type != chess.PAWN and is_hanging(board, sq)}


def move_features(board: chess.Board, move: chess.Move, person: Person, limit: int = 2) -> Features:
    """Najważniejsze cechy ruchu (co najwyżej ``limit``), od najważniejszych."""
    piece = board.piece_at(move.from_square)
    if piece is None:
        return Features(())
    me = piece.color
    after = board.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return Features((Phrase(f"feat.mate.{person}"),))
    found: list[Phrase] = []
    if board.is_castling(move):
        found.append(Phrase(f"feat.castle.{person}"))
    elif move.promotion:
        found.append(phrase(f"feat.promote.{person}", piece=PieceName(move.promotion)))
    if board.is_capture(move):
        victim = chess.PAWN if board.is_en_passant(move) else board.piece_type_at(move.to_square) or chess.PAWN
        found.append(phrase(f"feat.capture.{person}", piece=PieceName(victim), square=chess.square_name(move.to_square)))

    # Nowe cele ruszonej figury: cenniejsze od niej albo bez obrony (bez pionów i króla).
    moved = after.piece_type_at(move.to_square) or piece.piece_type
    targets = []
    for sq in after.attacks(move.to_square):
        target = after.piece_at(sq)
        if target is None or target.color == me or target.piece_type in (chess.PAWN, chess.KING):
            continue
        if _VALUES[target.piece_type] > _VALUES[moved] or not after.attackers(target.color, sq):
            targets.append(sq)
    targets.sort(key=lambda sq: -_VALUES[after.piece_type_at(sq) or chess.PAWN])
    check = after.is_check()
    if len(targets) >= 2:
        a, b = (after.piece_type_at(sq) or chess.PAWN for sq in targets[:2])
        found.append(phrase(f"feat.fork.{person}", a=PieceName(a), b=PieceName(b)))
    elif check and targets:
        found.append(phrase(f"feat.fork.{person}", a=PieceName(chess.KING), b=PieceName(after.piece_type_at(targets[0]) or chess.PAWN)))
    else:
        if check:
            found.append(Phrase(f"feat.check.{person}"))
        if targets:
            found.append(phrase(f"feat.attack.{person}", piece=PieceName(after.piece_type_at(targets[0]) or chess.PAWN), square=chess.square_name(targets[0])))

    hanging_before = _hanging_pieces(board, me)
    hanging_after = _hanging_pieces(after, me)
    if move.from_square in hanging_before and move.to_square not in hanging_after and not board.is_capture(move):
        found.append(phrase(f"feat.escape.{person}", piece=PieceName(piece.piece_type)))
    else:
        saved = [sq for sq in hanging_before if sq != move.from_square and sq not in hanging_after and after.piece_at(sq)]
        if saved:
            sq = saved[0]
            found.append(phrase(f"feat.defend.{person}", piece=PieceName(after.piece_type_at(sq) or chess.PAWN), square=chess.square_name(sq)))
    if board.fullmove_number <= 15 and _HOME[me].get(move.from_square) == piece.piece_type:
        found.append(phrase(f"feat.develop.{person}", piece=PieceName(piece.piece_type)))
    if piece.piece_type == chess.PAWN and move.to_square in _CENTER:
        found.append(Phrase(f"feat.center.{person}"))
    if piece.piece_type == chess.ROOK and not board.is_castling(move):
        file = chess.square_file(move.to_square)
        if not any(chess.square_file(sq) == file for sq in after.pieces(chess.PAWN, me)):
            found.append(Phrase(f"feat.open_file.{person}"))
    if not found:
        square = chess.square_name(move.to_square)
        if piece.piece_type == chess.PAWN:
            found.append(phrase(f"feat.pawn.{person}", square=square))
        else:
            found.append(phrase(f"feat.improve.{person}", piece=PieceName(piece.piece_type), square=square))
    return Features(tuple(found[:limit]))


def material_after(board: chess.Board, pv: list[str], color: chess.Color, plies: int) -> tuple[int, int]:
    """Zmiana materiału (w pionach) dla ``color`` po co najwyżej ``plies`` półruchach wariantu.

    Zwraca (zmiana, liczba półruchów do pokazania). Liczymy do końca pełnej wymiany: jeśli ostatni
    ruch był biciem, a następny ruch wariantu jest odbiciem, doliczamy także odbicie. Ciche ruchy
    na końcu wariantu (po których bilans już się nie zmienia) odcinamy — komentarz kończy się
    na ruchu, który naprawdę zabiera materiał.
    """
    start = material(board, color)
    work = board.copy(stack=False)
    values: list[int] = []
    for uci in pv:
        move = chess.Move.from_uci(uci)
        if move not in work.legal_moves:
            break
        if len(values) >= plies and not (work.move_stack and work.is_capture(move) and move.to_square == work.peek().to_square):
            break
        work.push(move)
        values.append(material(work, color) - start)
    if not values:
        return 0, 0
    final = values[-1]
    shown = len(values)
    while shown > 1 and values[shown - 2] == final:
        shown -= 1
    return final, shown


def _mate_moves(value: int) -> int:
    return (MATE - abs(value) + 1) // 2


# ---------------------------------------------------------------------------
# Komentarze trenera
# ---------------------------------------------------------------------------
def player_comment(
    board: chess.Board,
    move: chess.Move,
    cls: Classification,
    best_uci: str | None,
    best_pv: list[str],
    best_value: int,
    played_value: int,
    reply_pv: list[str],
) -> Comment:
    """Komentarz do ruchu gracza (wartości ocen z perspektywy gracza).

    :param board: pozycja przed ruchem,
    :param best_pv: wariant najlepszego ruchu (od niego),
    :param reply_pv: najlepszy wariant przeciwnika po ruchu gracza.
    """
    me = board.turn
    fen = board.fen()
    parts: list[Phrase] = []
    if cls not in WEAK:
        parts.append(phrase("coach.you_did", features=move_features(board, move, "you")))
        if cls == "brilliant":
            parts.append(Phrase("coach.brilliant_note"))
        elif cls == "great":
            parts.append(Phrase("coach.great_note"))
        elif cls == "good" and best_uci and best_uci != move.uci():
            parts.append(phrase("coach.slightly_better", move=San(fen, best_uci)))
        return tuple(parts)

    after = board.copy(stack=False)
    after.push(move)
    after_fen = after.fen()
    # 1. Co się stanie po ruchu gracza.
    if played_value < -MATE_BOUND and reply_pv:
        n = _mate_moves(played_value)
        parts.append(phrase("coach.allows_mate", line=Line(after_fen, tuple(reply_pv[: 2 * n - 1]))))
    elif reply_pv:
        change, played = material_after(after, reply_pv, me, 4)
        if change <= -1 and played:
            parts.append(phrase("coach.loses", line=Line(after_fen, tuple(reply_pv[:played])), material=Material(-change)))
        elif played_value < best_value - 100:
            parts.append(phrase("coach.reply_advantage", move=San(after_fen, reply_pv[0])))
    # 2. Co było lepsze i dlaczego.
    if best_uci and best_uci != move.uci():
        if best_value > MATE_BOUND:
            n = _mate_moves(best_value)
            if n <= 1:
                parts.append(phrase("coach.better_mate1", move=San(fen, best_uci)))
            else:
                parts.append(phrase("coach.better_mate", move=San(fen, best_uci), n=n, line=Line(fen, tuple(best_pv[: 2 * n - 1]))))
        else:
            gain, played = material_after(board, best_pv or [best_uci], me, 3)
            if gain >= 1 and played:
                parts.append(phrase("coach.better_wins", move=San(fen, best_uci), material=Material(gain), line=Line(fen, tuple(best_pv[:played]))))
            else:
                best_move = chess.Move.from_uci(best_uci)
                parts.append(phrase("coach.better", move=San(fen, best_uci), features=move_features(board, best_move, "it")))
    parts.append(phrase("coach.eval_change", before=Score(best_value), after=Score(played_value)))
    return tuple(parts)


def find_threat(board: chess.Board, threatening: chess.Color) -> Phrase | None:
    """Czym grozi ``threatening`` (ta strona właśnie wykonała ruch): matem albo zbiciem wiszącej figury."""
    if board.is_check() or board.is_game_over():
        return None
    null = board.copy(stack=False)
    null.push(chess.Move.null())
    for move in list(null.legal_moves):
        null.push(move)
        mate = null.is_checkmate()
        null.pop()
        if mate:
            return Phrase("coach.threat_mate")
    victims = sorted(_hanging_pieces(board, not threatening), key=lambda sq: -_VALUES[board.piece_type_at(sq) or chess.PAWN])
    if victims:
        sq = victims[0]
        return phrase("coach.threat_piece", piece=PieceName(board.piece_type_at(sq) or chess.PAWN), square=chess.square_name(sq))
    return None


def trainer_comment(board: chess.Board, move: chess.Move) -> Comment:
    """Trener objaśnia własny ruch i ostrzega przed swoją groźbą."""
    parts = [phrase("coach.trainer_move", move=San(board.fen(), move.uci()), features=move_features(board, move, "me"))]
    after = board.copy(stack=False)
    after.push(move)
    threat = find_threat(after, board.turn)
    if threat is not None:
        parts.append(threat)
    return tuple(parts)


def book_comment(board: chess.Board, move: chess.Move, name_id: str | None, comment_key: str | None, trainer: bool) -> Comment:
    """Komentarz do ruchu z teorii: nazwa debiutu i objaśnienie ruchu z linii otwarcia."""
    parts: list[Phrase] = []
    san = San(board.fen(), move.uci())
    name = Phrase(f"opening.{name_id}.name") if name_id else None
    if trainer:
        parts.append(phrase("coach.trainer_book", move=san, name=name) if name else phrase("coach.trainer_book_plain", move=san))
    else:
        parts.append(phrase("coach.book_named", name=name) if name else Phrase("coach.book"))
    if comment_key:
        parts.append(Phrase(comment_key))
    return tuple(parts)
