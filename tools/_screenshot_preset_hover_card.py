"""Reproduce the preset hover card to inspect title/subtitle overlap.

The user reports the card title (e.g. 振动类) and subtitle
(已保存参数快照 · 来源：FFT) render piled on top of each other. This
harness builds a _PresetHoverCard with the live QSS, shows it, screenshots
it, and prints the global geometry of the title / subtitle / section labels
so we can see whether their rectangles overlap.

Output: .pytest-tmp/preset-hover-card.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _configure_high_dpi() -> None:
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    from PyQt5.QtCore import QCoreApplication, Qt
    from PyQt5.QtGui import QGuiApplication
    for name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        attr = getattr(Qt, name, None)
        if attr is not None:
            QCoreApplication.setAttribute(attr, True)
    policy = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy is not None and hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy.PassThrough)


_configure_high_dpi()

from PyQt5.QtWidgets import QApplication, QLabel  # noqa: E402

from mf4_analyzer.ui_kit.icons import ensure_icon_cache  # noqa: E402
from mf4_analyzer.ui.inspector_sections import (  # noqa: E402
    _PresetHoverCard,
    PresetBar,
)


def _load_qss(app: QApplication) -> None:
    qss_path = REPO_ROOT / "mf4_analyzer" / "ui_kit" / "style.qss"
    template = qss_path.read_text(encoding="utf-8")
    icon_paths = ensure_icon_cache()
    rendered = template
    for key, value in icon_paths.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    app.setStyleSheet(rendered)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    _load_qss(app)

    card = _PresetHoverCard()
    # Optionally re-attach the old drop-shadow effect to demonstrate the
    # fractional/high-DPI QGraphicsEffect blur the fix removed (SHADOW=1).
    if os.environ.get("SHADOW") == "1":
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        panel = card.findChild(type(card), "presetHoverPanel") or card._panel
        eff = QGraphicsDropShadowEffect(card._panel)
        eff.setBlurRadius(34)
        eff.setOffset(0, 12)
        eff.setColor(QColor(15, 23, 42, 44))
        card._panel.setGraphicsEffect(eff)
    card.set_summary(
        name="振动类",
        params={"window": "hanning", "nfft": 2048, "overlap": 50,
                "avg_mode": "单帧", "amp_y": "Linear",
                "x_auto": True, "y_auto": True},
        kind="fft",
        label_map=PresetBar._SUMMARY_LABELS,
        current_params={},
        builtin=True,
    )
    card.show()
    app.processEvents()
    app.processEvents()

    out_dir = REPO_ROOT / ".pytest-tmp"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "preset-hover-card.png"
    card.grab().save(str(out_path))
    print(f"saved: {out_path}  card={card.width()}x{card.height()}")

    # Dump every QLabel's text + geometry to spot vertical overlap.
    for lbl in card.findChildren(QLabel):
        g = lbl.geometry()
        sh = lbl.sizeHint()
        print(
            f"  [{lbl.objectName() or 'QLabel'}] "
            f"y={g.y()} h={g.height()} (sizeHint h={sh.height()}) "
            f"text={lbl.text()[:24]!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
