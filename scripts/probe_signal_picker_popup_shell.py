"""Capture real Windows desktop evidence for rounded popup shells.

This intentionally does not use ``QT_QPA_PLATFORM=offscreen`` or
``QWidget.grab()``.  It displays a high-contrast host and captures the desktop
composition with ``QScreen.grabWindow(0)`` after the native windows settle.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PyQt5.QtCore import (
    PYQT_VERSION_STR,
    QEventLoop,
    QPoint,
    QRect,
    QT_VERSION_STR,
    QTimer,
    Qt,
)
from PyQt5.QtGui import QPalette
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
from mf4_analyzer.ui_kit.glass_tooltip import _GlassTooltipPopup


HOST_RGB = (196, 24, 67)
PIXEL_TOLERANCE = 8
EVIDENCE_DIR = (
    Path(__file__).resolve().parents[1]
    / ".superpowers"
    / "sdd"
    / "2026-07-31-mpl-packaging-and-popup-black-edge"
    / "popup-shell-evidence"
)


def _settle(milliseconds: int = 350) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec_()


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], text=True, encoding="utf-8"
    ).strip()


def _has_interactive_windows_desktop() -> bool:
    """Return whether the process can open the active Windows input desktop."""
    if sys.platform != "win32":
        return False
    import ctypes

    desktop = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        return False
    ctypes.windll.user32.CloseDesktop(desktop)
    return True


def _pixel_at(image, screen, global_point: QPoint):
    dpr = screen.devicePixelRatio()
    screen_geometry = screen.geometry()
    x = round((global_point.x() - screen_geometry.x()) * dpr)
    y = round((global_point.y() - screen_geometry.y()) * dpr)
    if not (0 <= x < image.width() and 0 <= y < image.height()):
        raise ValueError(f"desktop sample {global_point.x()}, {global_point.y()} is outside capture")
    color = image.pixelColor(x, y)
    return {
        "global": [global_point.x(), global_point.y()],
        "capture": [x, y],
        "rgb": [color.red(), color.green(), color.blue()],
        "name": color.name(),
    }


def _corner_samples(image, screen, widget):
    origin = widget.frameGeometry().topLeft()
    # These points lie inside the native window bounds but beyond the 8-10px
    # rounded surface. A rectangular backing would overwrite host pink here.
    points = {
        "top_left": QPoint(origin.x() + 1, origin.y() + 1),
        "top_right": QPoint(origin.x() + widget.width() - 2, origin.y() + 1),
        "bottom_left": QPoint(origin.x() + 1, origin.y() + widget.height() - 2),
        "bottom_right": QPoint(
            origin.x() + widget.width() - 2, origin.y() + widget.height() - 2
        ),
    }
    return {name: _pixel_at(image, screen, point) for name, point in points.items()}


def _is_host_rgb(sample: dict) -> bool:
    return all(abs(actual - wanted) <= PIXEL_TOLERANCE for actual, wanted in zip(sample["rgb"], HOST_RGB))


def _capture_surface(screen, widget, name: str):
    desktop = screen.grabWindow(0)
    image = desktop.toImage()
    rect = widget.frameGeometry()
    dpr = screen.devicePixelRatio()
    screen_geometry = screen.geometry()
    crop = QRect(
        round((rect.x() - screen_geometry.x()) * dpr),
        round((rect.y() - screen_geometry.y()) * dpr),
        round(rect.width() * dpr),
        round(rect.height() * dpr),
    ).adjusted(-4, -4, 4, 4)
    desktop.save(str(EVIDENCE_DIR / f"{name}-desktop.png"))
    desktop.copy(crop).save(str(EVIDENCE_DIR / f"{name}-crop.png"))
    samples = _corner_samples(image, screen, widget)
    return {
        "screen_geometry_logical": [
            screen_geometry.x(), screen_geometry.y(),
            screen_geometry.width(), screen_geometry.height(),
        ],
        "desktop_pixel_size": [desktop.width(), desktop.height()],
        "geometry_logical": [rect.x(), rect.y(), rect.width(), rect.height()],
        "content_origin_global": [
            widget.mapToGlobal(QPoint(0, 0)).x(),
            widget.mapToGlobal(QPoint(0, 0)).y(),
        ],
        "corners": samples,
        "passed": all(_is_host_rgb(sample) for sample in samples.values()),
    }


def main() -> int:
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        raise RuntimeError("desktop probe requires the real Windows Qt platform")
    if not _has_interactive_windows_desktop():
        # Keep this explicit so a CI service cannot emit misleading pixel
        # evidence from a non-interactive Window Station.
        raise RuntimeError("desktop probe requires an interactive Windows session")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    host = QWidget()
    host.setWindowTitle("SignalPicker popup shell desktop probe")
    host.setWindowFlags(host.windowFlags() | Qt.WindowStaysOnTopHint)
    host.resize(760, 560)
    palette = host.palette()
    palette.setColor(QPalette.Window, Qt.GlobalColor.transparent)
    host.setPalette(palette)
    host.setAutoFillBackground(False)
    host.setStyleSheet(f"background: rgb({HOST_RGB[0]}, {HOST_RGB[1]}, {HOST_RGB[2]});")
    picker = SignalPickerPopup(["Speed", "Torque", "BatteryVoltage"], parent=host)
    picker.setGeometry(120, 90, 360, 36)
    host.show()
    host.raise_()
    host.activateWindow()
    _settle()

    picker.show_popup()
    _settle()
    screen = QApplication.screenAt(picker._popup.mapToGlobal(QPoint(0, 0)))
    if screen is None:
        raise RuntimeError("could not identify the screen containing SignalPicker")
    host_reference_image = screen.grabWindow(0).toImage()
    host_reference = _pixel_at(
        host_reference_image, screen, host.mapToGlobal(QPoint(16, host.height() - 16))
    )
    signal_evidence = _capture_surface(screen, picker._popup, "signal-picker")
    signal_evidence["host_reference"] = host_reference
    signal_evidence["host_reference_matches_expected"] = _is_host_rgb(host_reference)

    tooltip = _GlassTooltipPopup.instance()
    tooltip.show_for("Glass tooltip shell", host.mapToGlobal(QPoint(340, 58)))
    _settle()
    tooltip_screen = QApplication.screenAt(tooltip.mapToGlobal(QPoint(0, 0)))
    if tooltip_screen is None:
        raise RuntimeError("could not identify the screen containing glass tooltip")
    tooltip_evidence = _capture_surface(tooltip_screen, tooltip, "glass-tooltip")

    evidence = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "qt_platform": QApplication.platformName(),
        "qt_version": QT_VERSION_STR,
        "pyqt_version": PYQT_VERSION_STR,
        "dpr": screen.devicePixelRatio(),
        "host_geometry_logical": [
            host.geometry().x(), host.geometry().y(), host.width(), host.height()
        ],
        "expected_host_rgb": list(HOST_RGB),
        "tolerance": PIXEL_TOLERANCE,
        "branch": _git("branch", "--show-current"),
        "sha": _git("rev-parse", "HEAD"),
        "signal_picker": signal_evidence,
        "glass_tooltip": tooltip_evidence,
    }
    (EVIDENCE_DIR / "pixel-evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    tooltip.hide()
    picker.hide_popup()
    host.close()
    return 0 if signal_evidence["passed"] and tooltip_evidence["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
