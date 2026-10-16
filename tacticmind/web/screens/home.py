"""Home screen: game title, description, buttons and a decorative board on which the AI shows a mate."""

from __future__ import annotations

from typing import Any

from ...brain.notation import uci_san
from ...i18n import t
from .base import WebScreen

#: Position on the decorative board: Scholar's mate — the AI shows the move Qxf7# with an arrow.
DEMO_FEN = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
DEMO_MOVE = "h5f7"
DEMO_LAST = "f1c4"


class HomeScreen(WebScreen):
    def snapshot(self) -> dict[str, Any]:
        profile = self.app.profile
        rating = f"{round(profile.rating)}" + (f" ± {round(profile.rd)}" if profile.rd is not None else "")
        solved = sum(1 for record in profile.history if record.solved)
        source = t("source.full") if self.app.puzzle_source == "full" else t("source.starter")
        return {
            "info": t("home.rating", rating=rating) + " · " + t("home.solved", n=solved),
            "source": t("home.source", n=len(self.app.puzzles), source=source),
            "demo": {"fen": DEMO_FEN, "last": DEMO_LAST, "move": DEMO_MOVE, "label": f"AI: {uci_san(DEMO_FEN, DEMO_MOVE)}  (M1)"},
        }
