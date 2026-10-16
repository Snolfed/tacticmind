"""Draws TacticMind's own piece set: chunky silhouettes, a thick dark outline and a soft bevel.

Usage::

    python scripts/make_pieces.py               # writes web/public/pieces/*.svg
    python scripts/make_pieces.py --out DIR     # somewhere else (e.g. to compare)

Every piece is a list of filled parts painted in order (a body, a collar, a plinth …). Each part gets a vertical
gradient, a light rim along its upper-left inner edge and a dark rim along its lower-right one (the part's own outline,
shifted and clipped to the part), then the outline itself. The bishop's slit is cut out of the whole piece with a mask.
Coordinates are in a 100×100 box; the pieces stand on y = 92.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "public" / "pieces"

#: Colours of each side: body gradient, outline, bevel rims, details and the plinth gradient.
STYLE: dict[str, dict[str, str]] = {
    "w": {
        "top": "#ffffff",
        "bottom": "#d9d9d9",
        "line": "#3a3a3a",
        "light": "rgba(255,255,255,0.95)",
        "dark": "rgba(0,0,0,0.13)",
        "base_top": "#f2f2f2",
        "base_bottom": "#c9c9c9",
    },
    "b": {
        "top": "#5e5e5e",
        "bottom": "#3a3a3a",
        "line": "#252525",
        "light": "rgba(255,255,255,0.20)",
        "dark": "rgba(0,0,0,0.30)",
        "base_top": "#4e4e4e",
        "base_bottom": "#2f2f2f",
    },
}
LINE_WIDTH = 4.2
SLIT_WIDTH = 5.0


def plinth(x0: float, x1: float, y0: float, y1: float, r: float = 5) -> str:
    """A rounded slab the piece stands on."""
    return (
        f"M{x0 + r} {y0} H{x1 - r} Q{x1} {y0} {x1} {y0 + r} V{y1 - r} Q{x1} {y1} {x1 - r} {y1} "
        f"H{x0 + r} Q{x0} {y1} {x0} {y1 - r} V{y0 + r} Q{x0} {y0} {x0 + r} {y0} Z"
    )


def circle(cx: float, cy: float, r: float) -> str:
    return f"M{cx - r} {cy} A{r} {r} 0 1 0 {cx + r} {cy} A{r} {r} 0 1 0 {cx - r} {cy} Z"


@dataclass
class Piece:
    #: (path, "body" | "base") painted in order; a later part's outline separates it from the earlier ones.
    parts: list[tuple[str, str]]
    #: (path, "line" | "dot") drawn on top in the outline colour.
    details: list[tuple[str, str]] = field(default_factory=list)
    #: A slit cut through the piece (the bishop's mitre).
    slit: str | None = None


COLLAR = "M29 64 H71 Q74 64 74 67 V72 Q74 75 71 75 H29 Q26 75 26 72 V67 Q26 64 29 64 Z"

PIECES: dict[str, Piece] = {
    "P": Piece(
        parts=[
            ("M39 43 H61 C62 57 77 65 79 81 H21 C23 65 38 57 39 43 Z", "body"),
            (circle(50, 29.5, 15), "body"),
            (plinth(17, 83, 79, 92), "base"),
        ],
    ),
    "R": Piece(
        parts=[
            ("M30 32 H70 L71 68 Q72 75 79 80 H21 Q28 75 29 68 Z", "body"),
            (
                "M21 12 Q21 10 23 10 H34 Q36 10 36 12 V17 H43 V12 Q43 10 45 10 H55 Q57 10 57 12 V17 H64 V12 Q64 10 66 10 "
                "H77 Q79 10 79 12 V28 Q79 33 73 34 H27 Q21 33 21 28 Z",
                "body",
            ),
            (plinth(14, 86, 79, 92), "base"),
        ],
    ),
    "N": Piece(
        parts=[
            (
                "M24 81 C24 70 32 62 41 57 C34 57 28 59 22 59 C15 59 11 55 11 49 C11 43 15 39 20 35 "
                "C27 28 34 21 41 17 L43 7 L54 14 C70 16 82 30 84 48 C85 62 81 72 80 81 Z",
                "body",
            ),
            (plinth(15, 85, 79, 92), "base"),
        ],
        details=[
            ("M58 17 C70 26 76 40 75 60", "line"),  # mane
            (circle(37, 28, 3), "dot"),  # eye
            (circle(17, 46, 1.8), "dot"),  # nostril
        ],
    ),
    "B": Piece(
        parts=[
            ("M50 14 C65 24 73 38 71 54 C70 63 64 69 61 72 H39 C36 69 30 63 29 54 C27 38 35 24 50 14 Z", "body"),
            (circle(50, 11, 5.5), "body"),
            ("M35 69 H65 Q68 69 68 72 V75 Q68 78 65 78 H35 Q32 78 32 75 V72 Q32 69 35 69 Z", "body"),
            (plinth(21, 79, 79, 92), "base"),
        ],
        slit="M70 32 Q58 37 49 48",
    ),
    "Q": Piece(
        parts=[
            ("M29 67 L16 31 Q27 41 33 45 L32 21 Q40 33 45 41 L50 16 L55 41 Q60 33 68 21 L67 45 Q73 41 84 31 L71 67 Z", "body"),
            (circle(16, 30, 6), "body"),
            (circle(32, 20, 6), "body"),
            (circle(50, 14, 6.5), "body"),
            (circle(68, 20, 6), "body"),
            (circle(84, 30, 6), "body"),
            (COLLAR, "body"),
            (plinth(15, 85, 78, 92), "base"),
        ],
    ),
    "K": Piece(
        parts=[
            ("M46 4 H54 V10 H60 V18 H54 V26 H46 V18 H40 V10 H46 Z", "body"),  # cross
            ("M50 31 C55 23 65 20 74 25 C85 31 86 47 79 56 L72 67 H28 L21 56 C14 47 15 31 26 25 C35 20 45 23 50 31 Z", "body"),
            (COLLAR, "body"),
            (plinth(15, 85, 78, 92), "base"),
        ],
        details=[("M50 33 C48 42 48 52 50 63", "line")],
    ),
}


def svg(color: str, letter: str) -> str:
    s = STYLE[color]
    piece = PIECES[letter]
    defs = [
        f'<linearGradient id="g" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="{s["top"]}"/>'
        f'<stop offset="1" stop-color="{s["bottom"]}"/></linearGradient>',
        f'<linearGradient id="gb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{s["base_top"]}"/>'
        f'<stop offset="1" stop-color="{s["base_bottom"]}"/></linearGradient>',
    ]
    body: list[str] = []
    if piece.slit:
        defs.append(
            '<mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100"><rect width="100" height="100" fill="#fff"/>'
            f'<path d="{piece.slit}" fill="none" stroke="#000" stroke-width="{SLIT_WIDTH}" stroke-linecap="round"/></mask>'
        )
        body.append('<g mask="url(#m)">')
    for i, (d, kind) in enumerate(piece.parts):
        defs.append(f'<clipPath id="c{i}"><path d="{d}"/></clipPath>')
        body.append(f'<path d="{d}" fill="{"url(#gb)" if kind == "base" else "url(#g)"}"/>')
        body.append(
            f'<g clip-path="url(#c{i})" fill="none" stroke-width="4">'
            f'<path d="{d}" stroke="{s["dark"]}" transform="translate(-2.2 -2.2)"/>'
            f'<path d="{d}" stroke="{s["light"]}" transform="translate(2 2)"/></g>'
        )
        if piece.slit and i == 0:  # the slit's own edges, inside the body only
            width = SLIT_WIDTH + 1.6 * LINE_WIDTH
            body.append(f'<path d="{piece.slit}" fill="none" stroke="{s["line"]}" stroke-width="{width}" stroke-linecap="round" clip-path="url(#c0)"/>')
        body.append(f'<path d="{d}" fill="none" stroke="{s["line"]}" stroke-width="{LINE_WIDTH}" stroke-linejoin="round"/>')
    if piece.slit:
        body.append("</g>")
    for d, kind in piece.details:
        if kind == "line":
            body.append(f'<path d="{d}" fill="none" stroke="{s["line"]}" stroke-width="3" stroke-linecap="round"/>')
        else:
            body.append(f'<path d="{d}" fill="{s["line"]}"/>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs>{"".join(defs)}</defs>{"".join(body)}</svg>\n'


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
