#!/usr/bin/env python3
"""Tool-window geometry probe for UltraView, Batch, and the markup editor.

Evidence class
--------------
Prints one JSON object on stdout. Each window record has screen
``geometry`` / ``availableGeometry`` / device pixel ratio, frame insets,
and client size at four moments: ``construct-end``, ``showEvent-enter``,
``showEvent-return``, and ``event-loop-tick`` (a 0 ms timer queued after
``show`` / ``present`` returns, so work that ``showEvent`` itself posted
has already run).

``QT_QPA_PLATFORM=offscreen`` numbers are not Windows evidence and are not
a substitute for a real Windows display (CLAUDE.md Gotchas). A native Linux
or Wine reading is not a Windows frame-inset measurement either. This
script is not product code. It does not write into ``docs/`` or the git
tree. Batch preferences and the markup hint store go to a temporary INI
under ``TMPDIR`` when that variable is set, otherwise the platform temp
directory (``TEMP`` / ``TMP`` on Windows).

Run from a source checkout, including a Windows source tree beside a
frozen build. The script imports ``mf4_analyzer``; it is not packed inside
the frozen executable.

    .venv/bin/python scripts/probe_tool_window_geometry.py --help
    TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
        .venv/bin/python scripts/probe_tool_window_geometry.py --self-check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_MOMENTS = (
    "construct-end",
    "showEvent-enter",
    "showEvent-return",
    "event-loop-tick",
)


def _platform() -> str:
    return str(os.environ.get("QT_QPA_PLATFORM") or "native")


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description=(
            "Print UltraView / Batch / markup tool-window geometry. "
            "Not product code. Offscreen numbers are not Windows evidence."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Offscreen (QT_QPA_PLATFORM=offscreen) numbers are not Windows "
            "evidence. --self-check constructs UltraViewSheet around a plain "
            "QWidget and does not require MainWindow."
        ),
    )


def _redirect_qsettings(directory: Path) -> None:
    """Keep bare QSettings() off the real MF4Analyzer/DataAnalyzer store."""
    from PyQt5.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(directory))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(directory))


def _rect(value) -> dict[str, int]:
    return {
        "x": int(value.x()),
        "y": int(value.y()),
        "width": int(value.width()),
        "height": int(value.height()),
    }


def _snapshot(widget, moment: str) -> dict:
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui_kit.dialog_geometry import (
        _ESTIMATED_TITLE_INSETS,
        frame_insets_of,
    )

    app = QApplication.instance()
    screens = []
    if app is not None:
        for screen in app.screens():
            screens.append(
                {
                    "name": screen.name(),
                    "geometry": _rect(screen.geometry()),
                    "availableGeometry": _rect(screen.availableGeometry()),
                    "devicePixelRatio": float(screen.devicePixelRatio()),
                }
            )
    insets = frame_insets_of(widget)
    handle = widget.windowHandle()
    handle_margins = None
    if handle is not None:
        margins = handle.frameMargins()
        handle_margins = {
            "left": int(margins.left()),
            "top": int(margins.top()),
            "right": int(margins.right()),
            "bottom": int(margins.bottom()),
        }
    return {
        "moment": moment,
        "client": {"width": int(widget.width()), "height": int(widget.height())},
        "geometry": _rect(widget.geometry()),
        "frameGeometry": _rect(widget.frameGeometry()),
        "minimumSize": {
            "width": int(widget.minimumWidth()),
            "height": int(widget.minimumHeight()),
        },
        "visible": bool(widget.isVisible()),
        "frame_insets": {
            "left": int(insets.left),
            "top": int(insets.top),
            "right": int(insets.right),
            "bottom": int(insets.bottom),
        },
        "windowHandle_frameMargins": handle_margins,
        "estimated_title_insets_constant": list(_ESTIMATED_TITLE_INSETS),
        "screens": screens,
    }


def _close_widget(widget) -> None:
    from PyQt5 import sip

    if widget is None or sip.isdeleted(widget):
        return
    timer = getattr(widget, "_recompute_timer", None)
    if timer is not None:
        try:
            timer.stop()
        except RuntimeError:
            pass
    try:
        widget.close()
    except RuntimeError:
        return
    if sip.isdeleted(widget):
        return
    widget.deleteLater()


def _exercise(widget, *, present: bool) -> dict:
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    moments: list[dict] = []
    error = None

    def _log(moment: str) -> None:
        try:
            moments.append(_snapshot(widget, moment))
        except Exception as exc:  # noqa: BLE001 - probe must report, not hide
            moments.append({"moment": moment, "error": f"{type(exc).__name__}: {exc}"})

    widget._probe_log = _log
    _log("construct-end")
    state = {"timed_out": False}
    try:
        if present and callable(getattr(widget, "present", None)):
            widget.present()
        else:
            widget.show()
            widget.raise_()
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    def _tick() -> None:
        _log("event-loop-tick")
        app.quit()

    def _timeout() -> None:
        state["timed_out"] = True
        app.quit()

    QTimer.singleShot(0, _tick)
    QTimer.singleShot(3000, _timeout)
    app.exec_()
    _close_widget(widget)
    app.processEvents()
    found = {item.get("moment") for item in moments}
    return {
        "moments": moments,
        "moments_present": [name for name in _MOMENTS if name in found],
        "timed_out": state["timed_out"],
        "error": error,
    }


def _open_ultraview(records: list[dict]) -> bool:
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.drawers.ultraview.sheet import UltraViewSheet

    class _ProbeUltraView(UltraViewSheet):
        def showEvent(self, event):  # noqa: N802 - Qt override
            log = getattr(self, "_probe_log", None)
            if callable(log):
                log("showEvent-enter")
            super().showEvent(event)
            if callable(log):
                log("showEvent-return")

    page = QWidget()
    page.setObjectName("probeUltraViewPage")
    try:
        sheet = _ProbeUltraView(None, page)
        record = _exercise(sheet, present=True)
        record["window"] = "ultraview"
        record["constructed"] = True
    except Exception as exc:  # noqa: BLE001
        record = {
            "window": "ultraview",
            "constructed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "moments": [],
            "moments_present": [],
        }
    records.append(record)
    return bool(record.get("constructed")) and set(_MOMENTS).issubset(
        set(record.get("moments_present") or [])
    )


def _open_batch(records: list[dict], directory: Path) -> None:
    from PyQt5.QtCore import QSettings

    from mf4_analyzer.ui.batch_settings import BatchPanelPrefsStore
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    import mf4_analyzer.ui.batch_settings as batch_settings

    ini = str(directory / "batch-prefs.ini")

    def _factory(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    batch_settings._default_settings = _factory

    class _ProbeBatch(BatchSheet):
        def showEvent(self, event):  # noqa: N802 - Qt override
            log = getattr(self, "_probe_log", None)
            if callable(log):
                log("showEvent-enter")
            super().showEvent(event)
            if callable(log):
                log("showEvent-return")

    try:
        store = BatchPanelPrefsStore(QSettings(ini, QSettings.IniFormat))
        sheet = _ProbeBatch(None, {}, prefs_store=store)
        record = _exercise(sheet, present=True)
        record["window"] = "batch"
        record["constructed"] = True
        record["note"] = "Constructed with an empty file list and an isolated INI. No project."
    except Exception as exc:  # noqa: BLE001
        record = {
            "window": "batch",
            "constructed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "moments": [],
            "moments_present": [],
            "note": "BatchSheet was not constructible in this process.",
        }
    records.append(record)


def _open_markup(records: list[dict], directory: Path) -> None:
    from PyQt5.QtCore import QSettings
    from PyQt5.QtGui import QColor, QPainter, QPixmap

    from mf4_analyzer.ui.markup.editor import MarkupEditor

    class _ProbeMarkup(MarkupEditor):
        def showEvent(self, event):  # noqa: N802 - Qt override
            log = getattr(self, "_probe_log", None)
            if callable(log):
                log("showEvent-enter")
            super().showEvent(event)
            if callable(log):
                log("showEvent-return")

    pixmap = QPixmap(320, 180)
    pixmap.fill(QColor("#f4f1ea"))
    painter = QPainter(pixmap)
    try:
        painter.fillRect(24, 24, 120, 72, QColor("#dbe7ff"))
    finally:
        painter.end()
    try:
        editor = _ProbeMarkup(pixmap, on_done=None, parent=None)
        editor.set_hint_settings(
            QSettings(str(directory / "markup-hints.ini"), QSettings.IniFormat)
        )
        record = _exercise(editor, present=False)
        record["window"] = "markup"
        record["constructed"] = True
    except Exception as exc:  # noqa: BLE001
        record = {
            "window": "markup",
            "constructed": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "moments": [],
            "moments_present": [],
        }
    records.append(record)


def _run(self_check: bool) -> int:
    from PyQt5.QtWidgets import QApplication

    platform = _platform()
    offscreen = platform == "offscreen"
    windows_evidence = sys.platform.startswith("win") and not offscreen
    app = QApplication.instance() or QApplication(["probe_tool_window_geometry"])
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("TraceLabProbe")
    app.setApplicationName("ToolWindowGeometry")
    records: list[dict] = []
    ultraview_ok = False
    tmp_root = os.environ.get("TMPDIR")
    temp_kwargs = {"prefix": "tracelab-tool-geometry-"}
    if tmp_root:
        temp_kwargs["dir"] = tmp_root
    with tempfile.TemporaryDirectory(**temp_kwargs) as tmp:
        directory = Path(tmp)
        _redirect_qsettings(directory)
        ultraview_ok = _open_ultraview(records)
        if not self_check:
            _open_batch(records, directory)
            _open_markup(records, directory)
    if offscreen:
        print(
            "evidence: offscreen numbers are not Windows evidence",
            file=sys.stderr,
        )
    elif not windows_evidence:
        print(
            "evidence: this process is not a Windows measurement "
            f"(QT_QPA_PLATFORM={platform}, sys.platform={sys.platform})",
            file=sys.stderr,
        )
    else:
        print("evidence: Windows native geometry", file=sys.stderr)
    payload = {
        "evidence_class": "tool-window-geometry",
        "offscreen_is_windows_evidence": False,
        "windows_evidence": windows_evidence,
        "self_check": self_check,
        "platform": platform,
        "offscreen": offscreen,
        "sys_platform": sys.platform,
        "windows": records,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if self_check:
        return 0 if ultraview_ok else 1
    if not ultraview_ok:
        return 1
    failed = [
        item["window"]
        for item in records
        if item.get("window") in {"batch", "markup"} and not item.get("constructed")
    ]
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    parser.add_argument(
        "--self-check",
        action="store_true",
        help=(
            "Construct UltraViewSheet around a plain QWidget, print geometry, "
            "and exit 0. Offscreen numbers are not Windows evidence."
        ),
    )
    args = parser.parse_args(argv)
    return _run(bool(args.self_check))


if __name__ == "__main__":
    raise SystemExit(main())
