"""Draws TacticMind's own piece set: slim silhouettes, a thin dark outline and flat cel shading.

Usage::

    python scripts/make_pieces.py               # writes web/public/pieces/*.svg
    python scripts/make_pieces.py --out DIR     # somewhere else (e.g. to compare)

Every piece is a list of filled parts painted in order (a body, a collar, a plinth …). Each part is filled with the
side's colour, gets a band of shade along its right edge (the part's own shape, shifted left and painted over the
shade, so the band follows the outline) and then its outline. Details (the king's arches, the knight's eye) are drawn
on top; the bishop's slit is cut out of the whole piece with a mask. Coordinates are in a 100×100 box; the pieces
stand on y = 90.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "pieces"

#: Colours of each side: fill, the shade along the right edge, the outline.
STYLE: dict[str, dict[str, str]] = {
    "w": {"fill": "#ffffff", "shade": "#d2d2d2", "line": "#3c3c3c"},
    "b": {"fill": "#5c5c5c", "shade": "#454545", "line": "#262626"},
}
LINE_WIDTH = 2.8
#: Width of the shaded band along the right edge of each part.
SHADE = 6.5
SLIT_WIDTH = 4.0
SCALE = 1.06


def rounded(x0: float, x1: float, y0: float, y1: float, r: float = 3) -> str:
    """A rounded rectangle: plinths and collars."""
    return (
        f"M{x0 + r} {y0} H{x1 - r} Q{x1} {y0} {x1} {y0 + r} V{y1 - r} Q{x1} {y1} {x1 - r} {y1} "
        f"H{x0 + r} Q{x0} {y1} {x0} {y1 - r} V{y0 + r} Q{x0} {y0} {x0 + r} {y0} Z"
    )


def circle(cx: float, cy: float, r: float) -> str:
    return f"M{cx - r} {cy} A{r} {r} 0 1 0 {cx + r} {cy} A{r} {r} 0 1 0 {cx - r} {cy} Z"


@dataclass
class Piece:
    #: Filled parts painted in order; a later part's outline separates it from the earlier ones.
    parts: list[str]
    #: (path, "line" | "dot" | "inset") drawn on top: a stroke, a dot in the outline colour, a shaded inset shape.
    details: list[tuple[str, str]] = field(default_factory=list)
    #: A slit cut through the piece (the bishop's mitre).
    slit: str | None = None


BASE = rounded(21, 79, 79, 90, 3.5)

PIECES: dict[str, Piece] = {
    "P": Piece(
        parts=[
            "M42 46 C42 58 36 69 30 80 H70 C64 69 58 58 58 46 Z",
            rounded(37, 63, 41, 48, 3),
            circle(50, 30, 11.5),
            rounded(25, 75, 79, 90, 3.5),
        ],
    ),
    "R": Piece(
        parts=[
            "M27 13 H37 V20 H45 V13 H55 V20 H63 V13 H73 V30 Q73 34 69 35 L67 63 Q68 73 76 80 H24 "
            "Q32 73 33 63 L31 35 Q27 34 27 30 Z",
            BASE,
        ],
        details=[("M31.5 35 H68.5", "line")],
    ),
    "N": Piece(
        parts=[
            "M75 80 C78 62 77 42 66 28 C63 24 60 22 58 21 L59 11 L50 17 C41 18 33 23 28 31 L21 43 "
            "C19 47 20 52 24 54 C28 56 32 55 35 52 C39 50 43 49 46 46 C46 55 37 63 34 80 Z",
            BASE,
        ],
        details=[(circle(38, 32, 2.6), "dot")],
    ),
    "B": Piece(
        parts=[
            "M41 64 H59 Q60 74 68 80 H32 Q40 74 41 64 Z",
            "M50 19 C62 26 69 39 67 52 C66 60 62 65 59 68 H41 C38 65 34 60 33 52 C31 39 38 26 50 19 Z",
            circle(50, 14, 5.5),
            BASE,
        ],
        slit="M66 31 L51 46",
    ),
    "Q": Piece(
        parts=[
            "M30 70 L19 34 Q30 45 36 46 L37 24 Q43 37 47 41 L50 17 L53 41 Q57 37 63 24 L64 46 Q70 45 81 34 L70 70 Z",
            circle(19, 33, 4.5),
            circle(37, 23, 4.5),
            circle(50, 16, 5),
            circle(63, 23, 4.5),
            circle(81, 33, 4.5),
            rounded(28, 72, 68, 75, 3),
            BASE,
        ],
    ),
    "K": Piece(
        parts=[
            "M47 5 H53 V10 H58 V16 H53 V24 H47 V16 H42 V10 H47 Z",
            "M50 33 C54 25 63 22 71 26 C80 31 81 44 75 53 L69 67 H31 L25 53 C19 44 20 31 29 26 C37 22 46 25 50 33 Z",
            rounded(29, 71, 66, 73, 3),
            "M33 73 H67 L69 80 H31 Z",
            BASE,
        ],
        details=[
            ("M47 63 C47 49 43 37 36 36 C29 35 27 45 32 53 L36 63 Z", "inset"),
            ("M53 63 C53 49 57 37 64 36 C71 35 73 45 68 53 L64 63 Z", "inset"),
        ],
    ),
}


def svg(color: str, letter: str) -> str:
    s = STYLE[color]
    piece = PIECES[letter]
    defs: list[str] = []
    body: list[str] = []
    if piece.slit:
        defs.append(
            '<mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><rect width="100" height="100" fill="#fff"/>'
            f'<path d="{piece.slit}" fill="none" stroke="#000" stroke-width="{SLIT_WIDTH}" stroke-linecap="round"/></mask>'
        )
        body.append('<g mask="url(#m)">')
    stroke = f'fill="none" stroke="{s["line"]}" stroke-width="{LINE_WIDTH}" stroke-linejoin="round"'
    for i, d in enumerate(piece.parts):
        defs.append(f'<clipPath id="c{i}"><path d="{d}"/></clipPath>')
        body.append(f'<path d="{d}" fill="{s["shade"]}"/>')
        body.append(f'<g clip-path="url(#c{i})"><path d="{d}" fill="{s["fill"]}" transform="translate({-SHADE} 0)"/></g>')
        if piece.slit and d == piece.parts[1]:  # the slit's own edges, inside the mitre only
            width = SLIT_WIDTH + 2 * LINE_WIDTH
            body.append(f'<path d="{piece.slit}" fill="none" stroke="{s["line"]}" stroke-width="{width}" stroke-linecap="round" clip-path="url(#c{i})"/>')
        body.append(f'<path d="{d}" {stroke}/>')
    if piece.slit:
        body.append("</g>")
    for d, kind in piece.details:
        if kind == "line":
            body.append(f'<path d="{d}" {stroke}/>')
        elif kind == "inset":
            body.append(f'<path d="{d}" fill="{s["shade"]}" stroke="{s["line"]}" stroke-width="{LINE_WIDTH * 0.8}" stroke-linejoin="round"/>')
        else:
            body.append(f'<path d="{d}" fill="{s["line"]}"/>')
    # Drawn a little larger than the box's grid, standing on y = 91: a piece fills its square like on chess.com.
    content = f'<g transform="translate(50 91) scale({SCALE}) translate(-50 -90)">{"".join(body)}</g>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs>{"".join(defs)}</defs>{content}</svg>\n'


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT, help=f"output folder (default: {OUT.relative_to(ROOT)})")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for color in STYLE:
        for letter in PIECES:
            (args.out / f"{color}{letter}.svg").write_text(svg(color, letter), encoding="utf-8")
    print(f"12 pieces -> {args.out}")


if __name__ == "__main__":
    main()
