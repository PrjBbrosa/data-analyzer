"""One-shot offscreen screenshot of FFTTimeContextual after Wave 2a.

Renders the Inspector pane (FFTTime mode) under
``QT_QPA_PLATFORM=offscreen`` so the spinbox stepper-removal change can
be eyeballed end-to-end:

* full numeric value + suffix visible (e.g. ``20000.00 Hz``)
* no right-side gutter on QSpinBox / QDoubleSpinBox
* QComboBox::drop-down arrow still drawn

Output:
    .pytest-tmp/inspector-after-spinbox-button-removal.png

Usage:
    QT_QPA_PLATFORM=offscreen .venv/bin/python \\
        tools/_screenshot_inspector_after_spinbox_button_removal.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure offscreen even if the caller forgot to export it.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from PyQt5.QtCore import QSize  # noqa: E402
from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QScrollArea,
    QVBoxLayout,
)

from mf4_analyzer.ui.icons import ensure_icon_cache  # noqa: E402
from mf4_analyzer.ui.inspector_sections import (  # noqa: E402
    FFTTimeContextual,
)


def _load_qss(app: QApplication) -> None:
    """Mirror ``mf4_analyzer.app._load_stylesheet`` so the screenshot
    renders with the same QSS the live app uses."""
    qss_path = REPO_ROOT / "mf4_analyzer" / "ui" / "style.qss"
    template = qss_path.read_text(encoding="utf-8")
    icon_paths = ensure_icon_cache()
    rendered = template
    for key, value in icon_paths.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    app.setStyleSheet(rendered)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    _load_qss(app)

    panel = FFTTimeContextual()
    # Set the same field values the brief calls out so they show their
    # full content on screen — Fs, freq min/max, time/freq res, dB ref.
    panel.spin_fs.setValue(48000.0)
    panel.spin_x_max.setValue(20000.0)  # frequency upper edge: '20000.00 Hz'
    panel.spin_x_min.setValue(0.0)
    panel.spin_y_min.setValue(-10.0)
    panel.spin_y_max.setValue(120.0)
    panel.spin_z_floor.setValue(-80.0)
    panel.spin_z_ceiling.setValue(0.0)
    panel.spin_db_ref.setValue(2e-5)
    # Force x-axis to manual so spin_x_min/max are enabled and not greyed.
    panel.chk_x_auto.setChecked(False)
    panel.chk_y_auto.setChecked(False)
    panel.chk_z_auto.setChecked(False)

    # Wrap in a scroll area so it visually matches Inspector.
    host = QFrame()
    host.setObjectName("inspectorScrollHost")
    layout = QVBoxLayout(host)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.addWidget(panel)
    layout.addStretch()

    scroll = QScrollArea()
    scroll.setObjectName("inspectorScroll")
    scroll.setWidget(host)
    scroll.setWidgetResizable(True)
    # Default Inspector width = ~360 px (Precision Light right pane).
    scroll.resize(QSize(360, 760))
    scroll.show()

    app.processEvents()
    app.processEvents()

    out_dir = REPO_ROOT / ".pytest-tmp"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "inspector-after-spinbox-button-removal.png"
    pixmap = scroll.grab()
    pixmap.save(str(out_path))

    # Diagnostics: visible-text-area width inside spin_x_max (the
    # '20000.00 Hz' demo spin in the brief).
    line_edit = panel.spin_x_max.lineEdit()
    print(
        f"saved: {out_path}\n"
        f"  size: {pixmap.width()}x{pixmap.height()}\n"
        f"  spin_x_max.width()           = {panel.spin_x_max.width()}\n"
        f"  spin_x_max.lineEdit().width()= {line_edit.width()}\n"
        f"  spin_x_max.text()            = {panel.spin_x_max.text()!r}\n"
        f"  spin_x_max.suffix()          = {panel.spin_x_max.suffix()!r}\n"
        f"  spin_fs.text()               = {panel.spin_fs.text()!r}\n"
        f"  combo_amp_unit options       = "
        f"{[panel.combo_amp_unit.itemText(i) for i in range(panel.combo_amp_unit.count())]}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
