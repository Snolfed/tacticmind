"""Makes the window icon for Windows, ``web/public/icon.ico``, from ``web/public/icon.png``.

pywebview's Windows window loads its icon with ``System.Drawing.Icon``, which takes only real .ico files: given the
PNG it throws "Argument 'picture' must be a picture that can be used as a Icon" and the window never opens.

Usage::

    pip install pillow
    python scripts/make_icon.py     # then npm run build in web/ copies it into tacticmind/web/static

The sizes up to 128 px are classic 32-bit bitmaps with their transparency mask, which every Windows reader takes; the
256 px one is PNG-compressed, as in Windows' own icons.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "web" / "public" / "icon.png"
TARGET = ROOT / "web" / "public" / "icon.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def bitmap(image: Image.Image) -> bytes:
    """A 32-bit DIB as an .ico stores it: header with doubled height, bottom-up BGRA rows, then the 1-bit AND mask."""
    width, height = image.size
    pixels = image.tobytes("raw", "BGRA")
    stride = width * 4
    colour = b"".join(pixels[y * stride : (y + 1) * stride] for y in reversed(range(height)))
    mask_stride = (width + 31) // 32 * 4
    mask = bytearray()
    for y in reversed(range(height)):
        row = bytearray(mask_stride)
        for x in range(width):
            if pixels[y * stride + x * 4 + 3] == 0:  # fully transparent: shows the background
                row[x // 8] |= 0x80 >> (x % 8)
        mask += row
    header = struct.pack("<IiiHHIIiiII", 40, width, height * 2, 1, 32, 0, len(colour) + len(mask), 0, 0, 0, 0)
    return header + colour + bytes(mask)


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return out.getvalue()


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    images = []
    for size in SIZES:
        scaled = source if source.size == (size, size) else source.resize((size, size), Image.Resampling.LANCZOS)
        images.append((size, png(scaled) if size >= 256 else bitmap(scaled)))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    TARGET.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + entries + b"".join(data for _, data in images))
    print(f"{TARGET.relative_to(ROOT)}: {', '.join(str(size) for size in SIZES)} px")


if __name__ == "__main__":
    main()
