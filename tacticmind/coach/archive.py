"""Saved games with the coach: moves, move classes, evaluations and comments, plus PGN export.

A finished game is stored in the profile as a list of plies (``CoachGameRecord.plies``), so it can be
opened again later in the review: the same board, badges, coach comments and better-move arrows as right
after the game. Comments are stored as data (``Phrase`` trees, see ``advice.py``), not as text, so an
old game still speaks the current interface language.

Evaluations are kept from White's perspective in the engine's units (centipawns, mate = ±(32000 − plies)).
They come from the analyses the coach already makes during the game - no extra engine time is spent.
"""

from __future__ import annotations

import io
import time
from collections.abc import Sequence
from typing import Any

import chess
import chess.pgn

from ..engine.types import MATE, MATE_BOUND
from ..i18n import t
from .advice import Comment, Features, Line, Material, Phrase, PieceName, San, Score, render_comment
from .game import CoachGame, MoveRecord
from .review import CLASSES, win_percent

#: PGN annotation symbols (NAG) for move classes.
_NAGS = {
    "brilliant": chess.pgn.NAG_BRILLIANT_MOVE,
    "great": chess.pgn.NAG_GOOD_MOVE,
    "inaccuracy": chess.pgn.NAG_DUBIOUS_MOVE,
    "mistake": chess.pgn.NAG_MISTAKE,
    "blunder": chess.pgn.NAG_BLUNDER,
}


# ---------------------------------------------------------------------------
# Comments <-> JSON
# ---------------------------------------------------------------------------
def encode_item(item: object) -> object:
    """An explanation element as JSON (a dict with the type in ``t``; plain values stay as they are)."""
    if isinstance(item, Phrase):
        data: dict[str, object] = {"t": "phrase", "key": item.key, "params": [[name, encode_item(value)] for name, value in item.params]}
        if item.count is not None:
            data["count"] = item.count
        return data
    if isinstance(item, San):
        return {"t": "san", "fen": item.fen, "uci": item.uci}
    if isinstance(item, Line):
        return {"t": "line", "fen": item.fen, "ucis": list(item.ucis)}
    if isinstance(item, PieceName):
        return {"t": "piece", "type": item.piece_type}
    if isinstance(item, Material):
        return {"t": "material", "points": item.points}
    if isinstance(item, Score):
        return {"t": "score", "value": item.value}
    if isinstance(item, Features):
        return {"t": "features", "items": [encode_item(p) for p in item.items]}
    if isinstance(item, (str, int, float, bool)) or item is None:
        return item
    return str(item)


def decode_item(data: object) -> object:
    if not isinstance(data, dict):
        return data
    kind = data.get("t")
    if kind == "phrase":
        params = tuple((str(pair[0]), decode_item(pair[1])) for pair in data.get("params", []) if isinstance(pair, list) and len(pair) == 2)
        count = data.get("count")
        return Phrase(str(data.get("key", "")), params, count if isinstance(count, int) else None)
    if kind == "san":
        return San(str(data.get("fen", "")), str(data.get("uci", "")))
    if kind == "line":
        return Line(str(data.get("fen", "")), tuple(str(u) for u in data.get("ucis", [])))
    if kind == "piece":
        return PieceName(int(data.get("type", chess.PAWN)))
    if kind == "material":
        return Material(int(data.get("points", 0)))
    if kind == "score":
        return Score(int(data.get("value", 0)))
    if kind == "features":
        return Features(tuple(p for p in (decode_item(i) for i in data.get("items", [])) if isinstance(p, Phrase)))
    return str(data)


def encode_comment(comment: Comment) -> list[object]:
    return [encode_item(p) for p in comment]


def decode_comment(data: object) -> Comment:
    if not isinstance(data, list):
        return ()
    return tuple(p for p in (decode_item(item) for item in data) if isinstance(p, Phrase))


# ---------------------------------------------------------------------------
# Plies <-> JSON
# ---------------------------------------------------------------------------
def encode_plies(records: Sequence[MoveRecord]) -> list[dict[str, Any]]:
    return [
        {
            "uci": r.uci,
            "player": r.by_player,
            "cls": r.classification,
            "acc": None if r.accuracy is None else round(r.accuracy, 1),
            "best": r.best_uci,
            "score": r.score,
            "comment": encode_comment(r.comment),
        }
        for r in records
    ]


def decode_plies(start_fen: str, plies: object) -> list[MoveRecord] | None:
    """Rebuilds the move records; ``None`` when the saved moves are not legal (a damaged file)."""
    if not isinstance(plies, list):
        return None
    try:
        board = chess.Board(start_fen)
    except ValueError:
        return None
    records: list[MoveRecord] = []
    for ply in plies:
        if not isinstance(ply, dict):
            return None
        try:
            move = chess.Move.from_uci(str(ply.get("uci", "")))
        except ValueError:
            return None
        if move not in board.legal_moves:
            return None
        cls = ply.get("cls")
        acc = ply.get("acc")
        best = ply.get("best")
        score = ply.get("score")
        records.append(
            MoveRecord(
                fen_before=board.fen(),
                uci=move.uci(),
                by_player=bool(ply.get("player")),
                classification=cls if cls in CLASSES else None,  # type: ignore[arg-type]
                accuracy=float(acc) if isinstance(acc, (int, float)) and not isinstance(acc, bool) else None,
                comment=decode_comment(ply.get("comment")),
                best_uci=best if isinstance(best, str) else None,
                score=score if isinstance(score, int) and not isinstance(score, bool) else None,
            )
        )
        board.push(move)
    return records


# ---------------------------------------------------------------------------
# Evaluation graph
# ---------------------------------------------------------------------------
def eval_curve(records: Sequence[MoveRecord]) -> list[float]:
    """White's winning chance (0–100) after every ply, starting with the initial position (50).

    A ply without an evaluation (an opening-book move) keeps the previous value."""
    values = [50.0]
    for record in records:
        values.append(values[-1] if record.score is None else round(win_percent(record.score), 1))
    return values


# ---------------------------------------------------------------------------
# PGN
# ---------------------------------------------------------------------------
def _pgn_eval(value: int) -> str:
    if abs(value) > MATE_BOUND:
        plies = MATE - abs(value)
        moves = (plies + 1) // 2
        return f"#{moves}" if value > 0 else f"#-{moves}"
    return f"{value / 100:.2f}"


def game_pgn(game: CoachGame, timestamp: float | None = None) -> str:
    """The game in PGN: player names, result, move classes as annotation symbols (!!, !, ?!, ?, ??),
    the engine evaluation (``[%eval]``, readable by Lichess and chess.com) and the coach's comments
    on the player's moves in the current language."""
    pgn = chess.pgn.Game()
    when = time.localtime(timestamp if timestamp is not None else time.time())
    you = t("coach.you")
    coach = f"{t('coach.name')} ({game.elo})"
    white, black = (you, coach) if game.player_color == chess.WHITE else (coach, you)
    if game.result is None:
        result = "*"
    elif game.result == "draw":
        result = "1/2-1/2"
    else:
        player_won = game.result == "win"
        result = "1-0" if (game.player_color == chess.WHITE) == player_won else "0-1"
    pgn.headers["Event"] = t("pgn.event")
    pgn.headers["Site"] = "TacticMind"
    pgn.headers["Date"] = time.strftime("%Y.%m.%d", when)
    pgn.headers["Round"] = "-"
    pgn.headers["White"] = white
    pgn.headers["Black"] = black
    pgn.headers["Result"] = result
    pgn.headers["WhiteElo" if game.player_color == chess.BLACK else "BlackElo"] = str(game.elo)
    if game.reason:
        pgn.headers["Termination"] = t(f"coach.reason.{game.reason}")
    if game.start_fen != chess.STARTING_FEN:
        pgn.setup(chess.Board(game.start_fen))
    node: chess.pgn.GameNode = pgn
    for record in game.records:
        node = node.add_variation(record.move)
        nag = _NAGS.get(record.classification or "")
        if nag is not None:
            node.nags.add(nag)
        parts: list[str] = []
        if record.score is not None:
            parts.append(f"[%eval {_pgn_eval(record.score)}]")
        if record.by_player and record.comment:
            parts.append(render_comment(record.comment))
        node.comment = " ".join(parts)
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=True)
    return pgn.accept(exporter)


def pgn_filename(timestamp: float | None = None) -> str:
    return time.strftime("tacticmind-%Y-%m-%d-%H%M%S.pgn", time.localtime(timestamp if timestamp is not None else time.time()))


def read_pgn(text: str) -> chess.pgn.Game | None:
    """Reads a PGN back (used by the tests to check that the export is valid)."""
    return chess.pgn.read_game(io.StringIO(text))
