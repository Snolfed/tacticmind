"""TacticMind colour palette — a custom dark "midnight navy" theme with teal (player)
and violet (AI) accents. The board uses cool, steel-blue tones."""

from __future__ import annotations

Color = tuple[int, ...]

# Background (vertical gradient) and card surfaces
BG_TOP = (15, 17, 26)
BG_BOTTOM = (21, 24, 36)
SURFACE = (27, 31, 45)
SURFACE_2 = (35, 40, 57)
SURFACE_3 = (45, 51, 71)
BORDER = (52, 59, 82)
BORDER_SOFT = (40, 46, 64)
SHADOW = (5, 6, 12)

# Text
TEXT = (238, 241, 248)
TEXT_SOFT = (203, 209, 225)
MUTED = (142, 150, 175)
DIM = (98, 106, 132)

# Accents
ACCENT = (45, 212, 191)  # teal — player, success, brand
ACCENT_2 = (20, 184, 166)
ACCENT_DARK = (15, 118, 110)
VIOLET = (167, 139, 250)  # violet — AI
VIOLET_2 = (139, 92, 246)
AMBER = (251, 191, 36)
ORANGE = (251, 146, 60)
ROSE = (251, 113, 133)
RED = (244, 63, 94)
RED_DARK = (159, 18, 57)
BLUE = (96, 165, 250)
GREEN = (52, 211, 153)

# Board
BOARD_LIGHT = (232, 235, 242)
BOARD_DARK = (121, 141, 178)
COORD_ON_LIGHT = (104, 122, 158)
COORD_ON_DARK = (226, 231, 241)

#: Last-move highlight, selection, hint, check, legal-move dots.
LAST_MOVE = (94, 234, 212, 110)
SELECTED = (251, 191, 36, 120)
HINT = VIOLET
CHECK = RED
DOT = (15, 23, 42, 70)

#: Brilliant move (!!) — bright cyan, as on chess.com.
BRILLIANT = (34, 211, 238)

#: Engine arrows: best move in teal, second and third semi-transparent.
ENGINE_ARROWS: tuple[Color, ...] = ((45, 212, 191, 215), (45, 212, 191, 105), (167, 139, 250, 100))
#: Arrows drawn with the right mouse button: no modifier / Shift / Ctrl / Alt.
USER_ARROW = (251, 191, 36, 205)
USER_ARROW_SHIFT = (244, 63, 94, 205)
USER_ARROW_CTRL = (96, 165, 250, 205)
USER_ARROW_ALT = (45, 212, 191, 205)

RADIUS = 14
GUTTER = 18
