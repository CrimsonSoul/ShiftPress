"""Export Windows icon sizes from the approved, image-generated icon.png.

The PNG is the canonical artwork: never redraw or overwrite it during export.
Pillow is a development dependency only; the application loads the ICO with Tk.

Usage:
    .venv/bin/python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> None:
    """Write icon.ico while preserving the source PNG and its prompt metadata."""
    root = Path(__file__).resolve().parent.parent
    with Image.open(root / "icon.png") as master:
        master.convert("RGBA").save(
            root / "icon.ico", sizes=[(n, n) for n in ICO_SIZES]
        )
    print(f"wrote {root / 'icon.ico'} from {root / 'icon.png'}")


if __name__ == "__main__":
    main()
