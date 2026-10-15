"""Paleta kolorów TacticMind — własny, ciemny motyw „nocnego granatu” z akcentami turkusu (gracz)
i fioletu (AI). Szachownica w chłodnych, stalowo-niebieskich tonach."""

from __future__ import annotations

Color = tuple[int, ...]

# Tło (gradient pionowy) i powierzchnie kart
BG_TOP = (15, 17, 26)
BG_BOTTOM = (21, 24, 36)
SURFACE = (27, 31, 45)
SURFACE_2 = (35, 40, 57)
SURFACE_3 = (45, 51, 71)
BORDER = (52, 59, 82)
BORDER_SOFT = (40, 46, 64)
SHADOW = (5, 6, 12)

# Tekst
TEXT = (238, 241, 248)
TEXT_SOFT = (203, 209, 225)
MUTED = (142, 150, 175)
DIM = (98, 106, 132)

# Akcenty
ACCENT = (45, 212, 191)  # turkus — gracz, sukces, marka
ACCENT_2 = (20, 184, 166)
ACCENT_DARK = (15, 118, 110)
VIOLET = (167, 139, 250)  # fiolet — AI
VIOLET_2 = (139, 92, 246)
AMBER = (251, 191, 36)
ORANGE = (251, 146, 60)
ROSE = (251, 113, 133)
RED = (244, 63, 94)
RED_DARK = (159, 18, 57)
BLUE = (96, 165, 250)
GREEN = (52, 211, 153)

# Szachownica
BOARD_LIGHT = (232, 235, 242)
BOARD_DARK = (121, 141, 178)
COORD_ON_LIGHT = (104, 122, 158)
COORD_ON_DARK = (226, 231, 241)

#: Podświetlenie ostatniego ruchu, zaznaczenie, podpowiedź, szach, kropki legalnych ruchów.
LAST_MOVE = (94, 234, 212, 110)
SELECTED = (251, 191, 36, 120)
HINT = VIOLET
CHECK = RED
DOT = (15, 23, 42, 70)

#: Genialny ruch (!!) — jasny cyjan, jak na chess.com.
BRILLIANT = (34, 211, 238)

#: Strzałki silnika: najlepszy ruch turkusowy, drugi i trzeci półprzezroczyste.
ENGINE_ARROWS: tuple[Color, ...] = ((45, 212, 191, 215), (45, 212, 191, 105), (167, 139, 250, 100))
#: Strzałki rysowane prawym przyciskiem myszy: bez klawisza / Shift / Ctrl / Alt.
USER_ARROW = (251, 191, 36, 205)
USER_ARROW_SHIFT = (244, 63, 94, 205)
USER_ARROW_CTRL = (96, 165, 250, 205)
USER_ARROW_ALT = (45, 212, 191, 205)

RADIUS = 14
GUTTER = 18
