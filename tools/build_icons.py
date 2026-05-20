"""Build TraceLab app icons from the source SVG.

Renders ``assets/icons/tracelab.svg`` at multiple resolutions via QtSvg,
then packages into:

- ``assets/icons/tracelab.ico``   Windows multi-resolution (16/32/48/64/128/256)
- ``assets/icons/tracelab.icns``  macOS multi-resolution (macOS only; needs ``iconutil``)
- ``assets/icons/tracelab_{N}.png``  intermediate PNGs (kept; runtime ``QIcon`` loads these)

Usage:
    .venv/bin/python tools/build_icons.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets" / "icons"
SVG = ASSETS / "tracelab.svg"

PNG_SIZES = (16, 32, 48, 64, 128, 256, 512, 1024)
ICO_SIZES = (16, 32, 48, 64, 128, 256)


def render_pngs() -> None:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QGuiApplication, QImage, QPainter
    from PyQt5.QtSvg import QSvgRenderer

    QGuiApplication.instance() or QGuiApplication(sys.argv)

    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise RuntimeError(f"SVG failed to load: {SVG}")

    for size in PNG_SIZES:
        img = QImage(size, size, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        renderer.render(painter)
        painter.end()
        out = ASSETS / f"tracelab_{size}.png"
        img.save(str(out), "PNG")
        print(f"  PNG  {out.relative_to(REPO)}")


def build_ico() -> None:
    from PIL import Image

    # Pillow's ICO save uses the source image's resolution as the ceiling.
    # Feed it the largest PNG so it can produce every requested size via LANCZOS downsampling.
    src = Image.open(ASSETS / "tracelab_256.png").convert("RGBA")
    out = ASSETS / "tracelab.ico"
    src.save(str(out), format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"  ICO  {out.relative_to(REPO)} ({len(ICO_SIZES)} resolutions)")


def build_icns() -> None:
    if sys.platform != "darwin":
        print("  ICNS skipped (requires macOS iconutil)")
        return
    if shutil.which("iconutil") is None:
        print("  ICNS skipped (iconutil not found)")
        return

    iconset = ASSETS / "tracelab.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()

    # Mapping: (source PNG size, iconset filename) — iconutil requires this exact naming
    mapping = [
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ]
    for src_size, dest_name in mapping:
        shutil.copy(ASSETS / f"tracelab_{src_size}.png", iconset / dest_name)

    out = ASSETS / "tracelab.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", "-o", str(out), str(iconset)],
        check=True,
    )
    shutil.rmtree(iconset)
    print(f"  ICNS {out.relative_to(REPO)}")


def main() -> None:
    if not SVG.exists():
        raise SystemExit(f"Missing source SVG: {SVG}")
    ASSETS.mkdir(parents=True, exist_ok=True)

    print("Rendering PNGs from SVG...")
    render_pngs()
    print("Building .ico...")
    build_ico()
    print("Building .icns...")
    build_icns()
    print("\nDone.")


if __name__ == "__main__":
    main()
