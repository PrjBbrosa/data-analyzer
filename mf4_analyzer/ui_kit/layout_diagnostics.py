"""Collect UI layout facts for the existing diagnostics logger.

This module must stay import-safe for ``ui_kit``: no ``mf4_analyzer.ui``
or ``acquisition_ui`` imports. It does not log full business paths or
user document contents. Default emission is a single environment record;
per-control details require an explicit detailed flag or
``TRACELAB_LAYOUT_PROBE=1``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import sys
from pathlib import Path

from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

from mf4_analyzer.diagnostics import throttled

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover
    sip = None


_LOGGER = logging.getLogger("mf4_analyzer.diagnostics")
_QSS_PATH = Path(__file__).resolve().parent / "style.qss"
_ENV_EMITTED = False
_QT_OVERRIDE_KEYS = (
    "QT_ENABLE_HIGHDPI_SCALING",
    "QT_AUTO_SCREEN_SCALE_FACTOR",
    "QT_SCALE_FACTOR",
    "QT_SCALE_FACTOR_ROUNDING_POLICY",
    "QT_FONT_DPI",
    "QT_QPA_PLATFORM",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    "QT_SCREEN_SCALE_FACTORS",
)


def layout_probe_enabled() -> bool:
    return os.environ.get("TRACELAB_LAYOUT_PROBE") == "1"


def detailed_layout_enabled() -> bool:
    if layout_probe_enabled():
        return True
    return os.environ.get("TRACELAB_LAYOUT_DIAGNOSTICS") == "1"


def qss_identity() -> dict[str, str]:
    if not _QSS_PATH.is_file():
        return {"qss_path": str(_QSS_PATH), "qss_sha256": "", "qss_bytes": "0"}
    data = _QSS_PATH.read_bytes()
    return {
        "qss_path": "mf4_analyzer/ui_kit/style.qss",
        "qss_sha256": hashlib.sha256(data).hexdigest()[:16],
        "qss_bytes": str(len(data)),
    }


def _alive(widget) -> bool:
    if widget is None:
        return False
    if sip is not None and sip.isdeleted(widget):
        return False
    return True


def _font_facts(font: QFont) -> dict[str, str | int]:
    return {
        "family": font.family(),
        "point_size": int(font.pointSize()),
        "pixel_size": int(font.pixelSize()),
        "weight": int(font.weight()),
        "bold": bool(font.bold()),
    }


def collect_environment_facts(widget: QWidget | None = None) -> dict:
    """Low-frequency environment snapshot. Safe with no widget."""
    app = QApplication.instance()
    facts: dict = {
        "qt": QT_VERSION_STR,
        "pyqt": PYQT_VERSION_STR,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "platform_plugin": "",
        "style": "",
        "font": {},
        "screens": [],
        "qt_overrides": {
            key: os.environ[key] for key in _QT_OVERRIDE_KEYS if key in os.environ
        },
        **qss_identity(),
    }
    if app is None:
        return facts
    try:
        facts["platform_plugin"] = app.platformName()
        style = app.style()
        facts["style"] = style.objectName() if style is not None else ""
        facts["font"] = _font_facts(app.font())
        screens = []
        for screen in app.screens():
            available = screen.availableGeometry()
            screens.append({
                "name": screen.name(),
                "dpr": float(screen.devicePixelRatio()),
                "logical_dpi": (float(screen.logicalDotsPerInchX()), float(screen.logicalDotsPerInchY())),
                "available": {
                    "x": available.x(),
                    "y": available.y(),
                    "width": available.width(),
                    "height": available.height(),
                },
            })
        facts["screens"] = screens
    except RuntimeError:
        pass
    if widget is not None and _alive(widget):
        facts["widget_object_name"] = widget.objectName()
        facts["widget_class"] = type(widget).__name__
    return facts


def _button_facts(widget: QWidget) -> list[dict]:
    rows = []
    for button in widget.findChildren(QPushButton):
        if not _alive(button):
            continue
        text = button.text()
        metrics = button.fontMetrics()
        text_width = metrics.horizontalAdvance(text.replace("&", ""))
        rows.append({
            "object_name": button.objectName(),
            "label_len": len(text),
            "text_width": int(text_width),
            "width": int(button.width()),
            "height": int(button.height()),
            "role": button.property("messageBoxRole") or button.property("role") or "",
        })
    return rows


def collect_widget_layout_facts(
    widget: QWidget,
    *,
    prompt_id: str | None = None,
) -> dict:
    """Per-widget geometry. ``prompt_id`` is the stable identity, not the copy."""
    if widget is None:
        raise TypeError("widget is required")
    if not _alive(widget):
        raise RuntimeError("widget has been deleted")
    geo = widget.geometry()
    frame = widget.frameGeometry()
    facts = {
        "prompt_id": prompt_id or widget.objectName() or type(widget).__name__,
        "class": type(widget).__name__,
        "object_name": widget.objectName(),
        "visible": bool(widget.isVisible()),
        "client": {
            "x": geo.x(), "y": geo.y(),
            "width": geo.width(), "height": geo.height(),
        },
        "frame": {
            "x": frame.x(), "y": frame.y(),
            "width": frame.width(), "height": frame.height(),
        },
        "min_size": {
            "width": widget.minimumWidth(),
            "height": widget.minimumHeight(),
        },
        "font": _font_facts(widget.font()),
        "buttons": _button_facts(widget),
    }
    return facts


def emit_layout_facts(facts: dict, *, detailed: bool = False) -> None:
    """Log facts. Serialization failure is reported and does not abort."""
    if not facts:
        raise TypeError("facts is required")
    if not detailed and not detailed_layout_enabled():
        payload = {
            key: facts[key]
            for key in (
                "qt", "pyqt", "platform_plugin", "style", "font",
                "screens", "qt_overrides", "qss_sha256", "prompt_id",
            )
            if key in facts
        }
        if not payload:
            payload = {"prompt_id": facts.get("prompt_id", "")}
    else:
        payload = facts
    try:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        _LOGGER.warning("layout diagnostics serialization failed: %s", exc)
        return
    throttled(_LOGGER, "layout_diagnostics", logging.INFO, "layout_diagnostics %s", text)


def emit_environment_once(widget: QWidget | None = None) -> None:
    global _ENV_EMITTED
    if _ENV_EMITTED:
        return
    _ENV_EMITTED = True
    emit_layout_facts(collect_environment_facts(widget), detailed=False)


def reset_environment_emission_for_tests() -> None:
    global _ENV_EMITTED
    _ENV_EMITTED = False
