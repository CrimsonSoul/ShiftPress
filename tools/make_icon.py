"""Regenerate the ShiftPress application icon.

Geometry is expressed as a fraction of the canvas, so the mark is resolution
independent. The values come from reading the mark at true 16px: a 0.020 gap
collapses the Night sheet to a sliver and 0.050 reduces it to a bare corner.

Requires Pillow, which is a development dependency only. The running
application loads icon.ico through Tkinter and needs no imaging library.

Usage:
    .venv/bin/python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 1024
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

GROUND = "#16171A"  # window charcoal
NIGHT = "#38BDF8"  # night_accent
DAY = "#F2B340"  # day_accent

TILE_RADIUS = 0.12  # "gently softened corners" per DESIGN.md Shapes
SHEET_RADIUS = 0.035
SHEET_W = 0.42
SHEET_H = 0.50
OFFSET = 0.19
GAP = 0.035


def render(size: int = CANVAS) -> Image.Image:
    """Draw the icon at *size* square.

    Args:
        size: Edge length in pixels.

    Returns:
        An RGBA image of the mark.
    """
    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, s, s], radius=int(s * TILE_RADIUS), fill=GROUND)

    r = int(s * SHEET_RADIUS)
    nx0 = s * (0.5 - SHEET_W / 2 - OFFSET / 2)
    ny0 = s * (0.5 - SHEET_H / 2 - OFFSET / 2)
    nx1, ny1 = nx0 + s * SHEET_W, ny0 + s * SHEET_H
    dx0, dy0 = nx0 + s * OFFSET, ny0 + s * OFFSET
    dx1, dy1 = dx0 + s * SHEET_W, dy0 + s * SHEET_H

    # Night sheet sits behind, up and left.
    d.rounded_rectangle([nx0, ny0, nx1, ny1], radius=r, fill=NIGHT)
    # Ground-coloured gap keeps the two sheets legible at 16px.
    g = s * GAP
    d.rounded_rectangle([dx0 - g, dy0 - g, dx1 + g, dy1 + g], radius=r, fill=GROUND)
    # Day sheet sits in front, down and right.
    d.rounded_rectangle([dx0, dy0, dx1, dy1], radius=r, fill=DAY)
    return im


def main() -> None:
    """Write icon.png and icon.ico to the repository root."""
    root = Path(__file__).resolve().parent.parent
    master = render()
    master.save(root / "icon.png")
    master.save(root / "icon.ico", sizes=[(n, n) for n in ICO_SIZES])
    print(f"wrote {root / 'icon.png'} and {root / 'icon.ico'}")


if __name__ == "__main__":
    main()
