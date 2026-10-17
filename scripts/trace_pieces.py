"""Cuts the game's pieces out of Juras's drawing (``scripts/pieces_sheet.png``) and traces them into SVG.

Usage::

    pip install numpy pillow vtracer
    python scripts/trace_pieces.py              # writes web/public/pieces/*.svg
    python scripts/trace_pieces.py --out DIR    # somewhere else (e.g. to compare)

The sheet has the black pieces in the top row and the white ones below, in the order R N B Q K P, on a flat grey
background. A piece is what the background cannot reach when it is flooded from the edges (the dark outline stops
it); grey areas closed in by the outline (the king's windows) are holes. Each piece is scaled up, split into its flat
colours (outline, shade, fill and, on the black pieces, the highlight) and traced with vtracer. The paths are then
moved into a 100×100 box, the piece standing on y = 91 and centred on its base, all with the same scale, so the
pieces keep the sizes of the drawing.
"""

from __future__ import annotations

import argparse
import re
import tempfile
from collections import deque
from pathlib import Path

import numpy as np
import vtracer
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SHEET = Path(__file__).resolve().parent / "pieces_sheet.png"
OUT = ROOT / "web" / "public" / "pieces"
ORDER = "RNBQKP"
#: Each piece is traced at this many times the sheet's resolution.
UP = 8
#: Box units per sheet pixel (the king, 100 px tall, becomes 87 units).
UNIT = 0.87
#: Where the pieces stand.
GROUND = 91.0
#: Flat colours of each side, darkest first: (upper luminance limit of the class, colour).
PALETTE: dict[str, list[tuple[float, str]]] = {
    "b": [(40, "#060507"), (75, "#444243"), (112, "#555355"), (256, "#929193")],
    "w": [(150, "#040406"), (226, "#d0d1d3"), (256, "#f7f8f9")],
}
#: The shade class: bands of it thinner than about one sheet pixel are just the blend between outline and fill.
SHADE = 1
#: Width of the outline around the piece, in traced pixels (a little over one sheet pixel, like the drawn line).
OUTLINE = round(UP * 1.25)


def flood_background(image: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Pixels of the background colour reachable from the sheet's edges."""
    close = np.abs(image - background).max(axis=2) < 14
    reached = np.zeros(close.shape, bool)
    reached[0, :], reached[-1, :], reached[:, 0], reached[:, -1] = close[0, :], close[-1, :], close[:, 0], close[:, -1]
    while True:
        grown = reached.copy()
        grown[1:, :] |= reached[:-1, :]
        grown[:-1, :] |= reached[1:, :]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        grown &= close
        if (grown == reached).all():
            return reached
        reached = grown


def components(mask: np.ndarray, min_size: int = 1) -> list[np.ndarray]:
    """Connected parts of a mask (8-neighbourhood), each as a boolean mask."""
    seen = np.zeros(mask.shape, bool)
    height, width = mask.shape
    parts = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        seen[y, x] = True
        queue, points = deque([(y, x)]), []
        while queue:
            cy, cx = queue.popleft()
            points.append((cy, cx))
            for ny in (cy - 1, cy, cy + 1):
                for nx in (cx - 1, cx, cx + 1):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        if len(points) >= min_size:
            part = np.zeros(mask.shape, bool)
            ys, xs = zip(*points)
            part[list(ys), list(xs)] = True
            parts.append(part)
    return parts


def grow(mask: np.ndarray, steps: int = 1, within: np.ndarray | None = None, round_: bool = False) -> np.ndarray:
    """The mask grown by ``steps`` pixels (4-neighbourhood), optionally only into ``within``.

    ``round_`` adds the diagonals every other step: an octagon, close to a circle, so a band grown along a slanted edge
    is about as wide as along a straight one.
    """
    for step in range(steps):
        grown = mask.copy()
        grown[1:, :] |= mask[:-1, :]
        grown[:-1, :] |= mask[1:, :]
        grown[:, 1:] |= mask[:, :-1]
        grown[:, :-1] |= mask[:, 1:]
        if round_ and step % 2:
            grown[1:, 1:] |= mask[:-1, :-1]
            grown[1:, :-1] |= mask[:-1, 1:]
            grown[:-1, 1:] |= mask[1:, :-1]
            grown[:-1, :-1] |= mask[1:, 1:]
        mask = grown if within is None else grown & (within | mask)
    return mask


def coverage(shape: np.ndarray, lum: np.ndarray, background: float) -> np.ndarray:
    """How much of each sheet pixel the piece covers: all of its inner pixels, and those on its edge by how dark they
    are, so the light blend between the outline and the background falls outside the piece."""
    edge = shape & grow(~shape)
    ink = np.clip((background - lum) / (background - 10), 0, 1)
    return np.where(edge, ink, shape.astype(float))


def holes(piece: np.ndarray, image: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Background-grey areas inside a piece that the outline closes all around (not shade, which touches the fill)."""
    grey = piece & (np.abs(image - background).max(axis=2) < 12)
    lum = image.mean(axis=2)
    found = np.zeros(piece.shape, bool)
    for area in components(grey):
        ring = grow(area, 2) & ~area
        if area.sum() >= 6 and (lum[ring] < 170).mean() > 0.75:
            found |= area
    return found


def smooth_classes(classes: np.ndarray, count: int, radius: float) -> np.ndarray:
    """Each pixel takes the class that dominates around it: smooth borders instead of the sheet's pixel steps."""
    weights = [
        np.asarray(Image.fromarray((classes == c).astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(radius)), float)
        for c in range(count)
    ]
    return np.argmax(np.stack(weights), axis=0)


def classify(crop: Image.Image, mask: Image.Image, side: str) -> np.ndarray:
    """The scaled-up piece as RGBA in its flat colours (transparent outside); ``mask`` is its coverage."""
    width, height = crop.size
    palette = PALETTE[side]
    big = np.asarray(crop.resize((width * UP, height * UP), Image.Resampling.LANCZOS)).astype(float)
    edge = mask.resize((width * UP, height * UP), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(UP * 0.45))
    alpha = np.asarray(edge) > 127
    classes = smooth_classes(np.digitize(big.mean(axis=2), [limit for limit, _ in palette[:-1]]), len(palette), UP * 0.45)
    # A thin band of shade along the outline is only the blend between outline and fill.
    shade = classes == SHADE
    size = UP + 1
    opened = Image.fromarray(shade.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))
    classes[shade & ~(np.asarray(opened) > 127)] = SHADE + 1
    # The outline all around the piece, as even as in the drawing (along the edge the thin line blends into the fill).
    classes[grow(~alpha, OUTLINE, round_=True) & alpha] = 0
    colours = np.array([[int(colour[i : i + 2], 16) for i in (1, 3, 5)] for _, colour in palette], np.uint8)
    rgba = np.zeros((height * UP, width * UP, 4), np.uint8)
    rgba[..., :3] = colours[classes]
    rgba[..., 3] = alpha * 255
    return rgba


TOKEN = re.compile(r"[A-Za-z]|-?\d+(?:\.\d+)?")


def trace(rgba: np.ndarray, scale: float, dx: float, dy: float) -> list[str]:
    """vtracer paths of the piece, moved into the 100×100 box: x' = x·scale + dx, y' = y·scale + dy."""
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder, "piece.png"), Path(folder, "piece.svg")
        Image.fromarray(rgba).save(source)
        vtracer.convert_image_to_svg_py(
            str(source), str(target), colormode="color", hierarchical="stacked", mode="spline", filter_speckle=UP * 2,
            color_precision=8, layer_difference=4, corner_threshold=60, length_threshold=4.0, max_iterations=10,
            splice_threshold=45, path_precision=2,
        )  # fmt: skip
        svg = target.read_text(encoding="utf-8")
    paths = []
    for d, fill, tx, ty in re.findall(r'<path d="([^"]+)" fill="(#[0-9A-Fa-f]{6})" transform="translate\(([-\d.]+),([-\d.]+)\)"', svg):
        offset = (float(tx), float(ty))
        out: list[str] = []
        axis = 0  # vtracer writes absolute M/C/L/Z commands: the numbers alternate x, y
        for token in TOKEN.findall(d):
            if token.isalpha():
                out.append(token)
                axis = 0
                continue
            value = (float(token) + offset[axis]) * scale + (dx, dy)[axis]
            out.append(f"{value:.1f}".removesuffix(".0"))
            axis = 1 - axis
        compact = re.sub(r" ?([A-Za-z]) ?", r"\1", " ".join(out))
        paths.append(f'<path d="{compact}" fill="{fill.lower()}"/>')
    return paths


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sheet", type=Path, default=SHEET, help="the drawing of all twelve pieces")
    parser.add_argument("--out", type=Path, default=OUT, help=f"output folder (default: {OUT.relative_to(ROOT)})")
    args = parser.parse_args(argv)
    sheet = Image.open(args.sheet).convert("RGB")
    image = np.asarray(sheet).astype(float)
    border = np.concatenate([image[0], image[-1], image[:, 0], image[:, -1]])
    background = np.median(border, axis=0)
    pieces = components(~flood_background(image, background), min_size=500)
    if len(pieces) != 12:
        raise SystemExit(f"expected 12 pieces on the sheet, found {len(pieces)}")
    middle = image.shape[0] / 2
    pieces.sort(key=lambda piece: (np.nonzero(piece)[0].mean() > middle, np.nonzero(piece)[1].mean()))
    args.out.mkdir(parents=True, exist_ok=True)
    for index, piece in enumerate(pieces):
        side, letter = "bw"[index // 6], ORDER[index % 6]
        ys, xs = np.nonzero(piece)
        pad = 4
        x0, y0, x1, y1 = xs.min() - pad, ys.min() - pad, xs.max() + pad + 1, ys.max() + pad + 1
        shape = piece & ~holes(piece, image, background)
        crop = sheet.crop((int(x0), int(y0), int(x1), int(y1)))
        cover = coverage(shape, image.mean(axis=2), float(background.mean()))
        mask = Image.fromarray(np.round(cover[y0:y1, x0:x1] * 255).astype(np.uint8))
        bottom = ys.max() + 1
        base = xs[ys >= ys.max() - 6].astype(float)
        centre = (base.min() + base.max() + 1) / 2  # the middle of the base, not of the whole piece (the knight)
        scale = UNIT / UP
        paths = trace(classify(crop, mask, side), scale, 50 + (x0 - centre) * UNIT, GROUND + (y0 - bottom) * UNIT)
        body = "".join(paths)
        (args.out / f"{side}{letter}.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{body}</svg>\n', encoding="utf-8")
    print(f"12 pieces -> {args.out}")


if __name__ == "__main__":
    main()
