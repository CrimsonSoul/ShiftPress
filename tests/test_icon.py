"""Every Windows icon size must come from the same generated master."""

from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageChops

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


def test_icon_png_is_full_resolution():
    """The generated master retains its resolution for future exports."""
    with Image.open(ROOT / "icon.png") as im:
        assert im.width == im.height
        assert im.width >= 1024
        assert im.mode in ("RGB", "RGBA")


def test_icon_ico_carries_every_windows_size():
    """Windows picks a size per context; a missing one gets a blurry upscale."""
    with Image.open(ROOT / "icon.ico") as ico:
        assert set(ico.info["sizes"]) == REQUIRED_ICO_SIZES


def test_every_windows_frame_matches_the_png_master():
    """Title bars, taskbar, Explorer and Tk must not show different artwork."""
    with Image.open(ROOT / "icon.png") as master, Image.open(ROOT / "icon.ico") as ico:
        for size in REQUIRED_ICO_SIZES:
            expected = master.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
            actual = ico.ico.getimage(size)
            assert not ImageChops.difference(
                actual.convert("RGB"), expected.convert("RGB")
            ).getbbox()


def test_export_preserves_the_source_artwork(tmp_path):
    """Rebuilding the ICO must never redraw or overwrite the approved PNG."""
    tool = tmp_path / "tools" / "make_icon.py"
    tool.parent.mkdir()
    shutil.copyfile(ROOT / "tools" / "make_icon.py", tool)
    master = tmp_path / "icon.png"
    Image.new("RGB", (1024, 1024), (238, 234, 242)).save(master)
    original = master.read_bytes()

    subprocess.run([sys.executable, str(tool)], check=True, capture_output=True)

    assert master.read_bytes() == original
    with Image.open(tmp_path / "icon.ico") as ico:
        assert set(ico.info["sizes"]) == REQUIRED_ICO_SIZES
        assert ico.ico.getimage((16, 16)).convert("RGB").getpixel((8, 8)) == (
            238,
            234,
            242,
        )
