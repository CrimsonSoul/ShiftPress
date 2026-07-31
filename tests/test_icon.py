"""The shipped icon assets must stay in spec and in palette."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_ICO_SIZES = {
    (16, 16),
    (24, 24),
    (32, 32),
    (48, 48),
    (64, 64),
    (128, 128),
    (256, 256),
}


def test_icon_png_is_full_resolution_rgba():
    """PyInstaller and the Tk fallback both read the PNG master."""
    with Image.open(ROOT / "icon.png") as im:
        assert im.size == (1024, 1024)
        assert im.mode == "RGBA"


def test_icon_ico_carries_every_windows_size():
    """Windows picks a size per context; a missing one gets a blurry upscale."""
    with Image.open(ROOT / "icon.ico") as ico:
        assert set(ico.info["sizes"]) == REQUIRED_ICO_SIZES


def test_icon_uses_the_committed_shift_tokens():
    """The icon shares the app's palette rather than inventing its own."""
    with Image.open(ROOT / "icon.png") as im:
        colors = {c for _, c in im.convert("RGB").getcolors(maxcolors=1_000_000)}

    assert (0x38, 0xBD, 0xF8) in colors  # night_accent
    assert (0xF2, 0xB3, 0x40) in colors  # day_accent
    assert (0x16, 0x17, 0x1A) in colors  # window charcoal ground
