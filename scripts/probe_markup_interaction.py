#!/usr/bin/env python3
"""X11 input probe for markup press-on-existing, Esc, and pan.

Evidence class
--------------
Scenarios, in order: ``press-on-existing``, ``esc-dirty``, ``pan``.
When ``DISPLAY`` is set, ``xdotool`` is on ``PATH``, and
``QT_QPA_PLATFORM`` is not ``offscreen``, each scenario constructs a
``MarkupEditor`` on an in-memory pixmap, drives it with ``xdotool``, and
closes it. The editor is not opened through ``MainWindow``; the gestures
live on the editor and its view. The product open path is inventoried
separately.

Under offscreen, or with no ``DISPLAY``, ``--self-check`` prints
``skipped: no display`` and exits 0. It does not synthesize input and
call that an X11 result. Offscreen numbers are not Windows evidence.

This script is not product code. It does not write into ``docs/`` or the
git tree. Hint ``QSettings`` go to a temporary INI under ``TMPDIR`` when
that variable is set, otherwise the platform temp directory
(``TEMP`` / ``TMP`` on Windows).

    .venv/bin/python scripts/probe_markup_interaction.py --help
    TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
        .venv/bin/python scripts/probe_markup_interaction.py --self-check
    TMPDIR=/tmp DISPLAY=:1 QT_QPA_PLATFORM=xcb PYTHONPATH=. \\
        .venv/bin/python scripts/probe_markup_interaction.py
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCENARIOS = ("press-on-existing", "esc-dirty", "pan")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Drive the markup editor with real X11 input via xdotool. "
            "Not product code. Offscreen runs are not X11 or Windows evidence."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Offscreen and headless runs print 'skipped: no display' and do "
            "not invent input events. A real run needs DISPLAY and xdotool."
        ),
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help=(
            "Under offscreen or without DISPLAY, print "
            "'skipped: no display' and exit 0."
        ),
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=SCENARIOS,
        help="Run only this scenario. Repeat to run several. Default: all three.",
    )
    return parser


def _skip_reason() -> str | None:
    platform = os.environ.get("QT_QPA_PLATFORM") or ""
    if platform == "offscreen" or not os.environ.get("DISPLAY"):
        return "no display"
    if shutil.which("xdotool") is None:
        return "xdotool missing"
    return None


def _xdo(*args: str) -> dict:
    try:
        completed = subprocess.run(
            ["xdotool", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        return {"args": list(args), "returncode": None, "error": f"timeout: {exc}"}
    return {
        "args": list(args),
        "returncode": int(completed.returncode),
        "stdout": (completed.stdout or "")[-400:],
        "stderr": (completed.stderr or "")[-400:],
    }


def _release_inputs() -> None:
    if shutil.which("xdotool") is None:
        return
    subprocess.run(
        [
            "xdotool",
            "keyup", "shift",
            "keyup", "space",
            "mouseup", "1",
            "mouseup", "2",
            "mouseup", "3",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=3,
    )


def _pump(app, seconds: float = 0.25) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


def _wid(widget) -> str:
    widget.winId()
    return str(int(widget.winId()))


def _redirect_qsettings(directory: Path) -> None:
    from PyQt5.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(directory))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(directory))


def _pixmap():
    from PyQt5.QtGui import QColor, QPainter, QPixmap

    pixmap = QPixmap(1400, 900)
    pixmap.fill(QColor("#f7f4ee"))
    painter = QPainter(pixmap)
    try:
        painter.fillRect(80, 70, 220, 140, QColor("#dbe7ff"))
    finally:
        painter.end()
    return pixmap


def _close_editor(editor) -> None:
    from PyQt5 import sip

    if editor is None:
        return
    try:
        if sip.isdeleted(editor):
            return
    except (RuntimeError, TypeError):
        return
    try:
        editor.close()
    except RuntimeError:
        return


def _selectable_items(editor) -> list[dict]:
    from PyQt5.QtWidgets import QGraphicsItem

    rows = []
    for item in editor._scene.items():
        if item is editor._background_item:
            continue
        if not (item.flags() & QGraphicsItem.ItemIsSelectable):
            continue
        rows.append(
            {
                "type": type(item).__name__,
                "pos": [float(item.pos().x()), float(item.pos().y())],
                "selected": bool(item.isSelected()),
            }
        )
    return rows


def _view_facts(editor) -> dict:
    view = editor._view
    transform = view.transform()
    horizontal = view.horizontalScrollBar()
    vertical = view.verticalScrollBar()
    return {
        "zoom": float(editor._zoom),
        "transform_dx": float(transform.dx()),
        "transform_dy": float(transform.dy()),
        "horizontal": int(horizontal.value()),
        "vertical": int(vertical.value()),
        "horizontal_maximum": int(horizontal.maximum()),
        "vertical_maximum": int(vertical.maximum()),
        "selectable_items": len(_selectable_items(editor)),
    }


def _prepare(editor, app) -> None:
    editor.resize(960, 640)
    editor.show()
    editor.raise_()
    editor.activateWindow()
    _pump(app, 0.25)
    _xdo("windowactivate", "--sync", _wid(editor))
    editor.actual_size()
    _pump(app, 0.15)


def _global_scene_point(editor, scene_x: float, scene_y: float):
    from PyQt5.QtCore import QPoint, QPointF

    view_point = editor._view.mapFromScene(QPointF(scene_x, scene_y))
    return editor._view.viewport().mapToGlobal(QPoint(view_point))


def _scenario_press_on_existing(app, directory: Path) -> dict:
    from PyQt5.QtCore import QRectF, QSettings

    from mf4_analyzer.ui.markup.editor import MarkupEditor

    editor = MarkupEditor(_pixmap(), on_done=None)
    editor.set_hint_settings(
        QSettings(str(directory / "press-hints.ini"), QSettings.IniFormat)
    )
    try:
        _prepare(editor, app)
        editor.set_tool("rect")
        rect = editor.add_rect_item(QRectF(80, 70, 140, 90))
        _pump(app, 0.1)
        before_pos = [float(rect.pos().x()), float(rect.pos().y())]
        before_items = _selectable_items(editor)
        center = _global_scene_point(editor, 150, 115)
        end = _global_scene_point(editor, 174, 127)
        commands = [
            _xdo("mousemove", "--sync", str(center.x()), str(center.y())),
            _xdo("mousedown", "1"),
        ]
        _pump(app, 0.05)
        commands.append(_xdo("mousemove", "--sync", str(end.x()), str(end.y())))
        _pump(app, 0.1)
        commands.append(_xdo("mouseup", "1"))
        _pump(app, 0.15)
        after_pos = [float(rect.pos().x()), float(rect.pos().y())]
        return {
            "scenario": "press-on-existing",
            "status": "observed",
            "tool": editor._tool,
            "before_items": before_items,
            "after_items": _selectable_items(editor),
            "existing_pos_before": before_pos,
            "existing_pos_after": after_pos,
            "xdotool": commands,
            "note": (
                "Rect tool, press inside an existing hollow rectangle and "
                "drag 24 px. A moved existing item and no new item is the "
                "M-1 observation."
            ),
        }
    finally:
        _close_editor(editor)
        app.processEvents()


def _scenario_esc_dirty(app, directory: Path) -> dict:
    from PyQt5.QtCore import QRectF, QSettings
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.markup.editor import MarkupEditor

    done_calls: list[bool] = []
    editor = MarkupEditor(
        _pixmap(),
        on_done=lambda _pix: done_calls.append(True),
    )
    editor.set_hint_settings(
        QSettings(str(directory / "esc-hints.ini"), QSettings.IniFormat)
    )
    try:
        _prepare(editor, app)
        editor.add_rect_item(QRectF(40, 40, 80, 50))
        _pump(app, 0.1)
        before = {
            "visible": bool(editor.isVisible()),
            "undo_clean": bool(editor._undo_stack.isClean()),
            "undo_count": int(editor._undo_stack.count()),
            "on_done_calls": len(done_calls),
        }
        command = _xdo("key", "Escape")
        _pump(app, 0.3)
        modal = QApplication.activeModalWidget()
        return {
            "scenario": "esc-dirty",
            "status": "observed",
            "before": before,
            "after": {
                "visible": bool(editor.isVisible()),
                "undo_clean": bool(editor._undo_stack.isClean()),
                "on_done_calls": len(done_calls),
                "active_modal": None if modal is None else type(modal).__name__,
            },
            "xdotool": [command],
            "note": (
                "Esc with a dirty undo stack. Closing with no modal confirm "
                "and on_done not called is the M-2 observation."
            ),
        }
    finally:
        _close_editor(editor)
        app.processEvents()


def _ensure_scroll_range(editor, app) -> None:
    editor.actual_size()
    app.processEvents()
    for _ in range(4):
        horizontal = editor._view.horizontalScrollBar().maximum()
        vertical = editor._view.verticalScrollBar().maximum()
        if horizontal > 0 or vertical > 0:
            return
        editor.zoom_by(1.5)
        app.processEvents()


def _scenario_pan(app, directory: Path) -> dict:
    from PyQt5.QtCore import QSettings

    from mf4_analyzer.ui.markup.editor import MarkupEditor

    editor = MarkupEditor(_pixmap(), on_done=None)
    editor.set_hint_settings(
        QSettings(str(directory / "pan-hints.ini"), QSettings.IniFormat)
    )
    try:
        _prepare(editor, app)
        editor.set_tool("select")
        _ensure_scroll_range(editor, app)
        before = _view_facts(editor)
        origin = _global_scene_point(editor, 200, 160)
        moved = _global_scene_point(editor, 280, 220)
        commands = [
            _xdo("mousemove", "--sync", str(origin.x()), str(origin.y())),
            _xdo("mousedown", "2"),
        ]
        _pump(app, 0.05)
        commands.append(_xdo("mousemove", "--sync", str(moved.x()), str(moved.y())))
        _pump(app, 0.1)
        commands.append(_xdo("mouseup", "2"))
        _pump(app, 0.15)
        after_middle = _view_facts(editor)
        commands.append(_xdo("mousemove", "--sync", str(origin.x()), str(origin.y())))
        commands.append(_xdo("keydown", "space"))
        commands.append(_xdo("mousedown", "1"))
        _pump(app, 0.05)
        commands.append(_xdo("mousemove", "--sync", str(moved.x()), str(moved.y())))
        _pump(app, 0.1)
        commands.append(_xdo("mouseup", "1"))
        commands.append(_xdo("keyup", "space"))
        _pump(app, 0.15)
        after_space = _view_facts(editor)
        return {
            "scenario": "pan",
            "status": "observed",
            "before": before,
            "after_middle_drag": after_middle,
            "after_space_left_drag": after_space,
            "xdotool": commands,
            "note": (
                "Middle-drag, then Space+left-drag, after zooming until a "
                "scrollbar has range. Unchanged scroll values are the M-3 "
                "no-pan observation."
            ),
        }
    finally:
        _close_editor(editor)
        app.processEvents()


_SCENARIO_FUNCS = {
    "press-on-existing": _scenario_press_on_existing,
    "esc-dirty": _scenario_esc_dirty,
    "pan": _scenario_pan,
}


def _run(names: list[str]) -> int:
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["probe_markup_interaction"])
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("TraceLabProbe")
    app.setApplicationName("MarkupInteractionProbe")
    results = []
    tmp_root = os.environ.get("TMPDIR")
    temp_kwargs = {"prefix": "tracelab-markup-input-"}
    if tmp_root:
        temp_kwargs["dir"] = tmp_root
    try:
        with tempfile.TemporaryDirectory(**temp_kwargs) as tmp:
            directory = Path(tmp)
            _redirect_qsettings(directory)
            for name in names:
                try:
                    results.append(_SCENARIO_FUNCS[name](app, directory))
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        {
                            "scenario": name,
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc(),
                        }
                    )
    finally:
        _release_inputs()
        app.processEvents()
    payload = {
        "evidence_class": "x11-real-input",
        "offscreen_is_x11_evidence": False,
        "offscreen_is_windows_evidence": False,
        "platform": os.environ.get("QT_QPA_PLATFORM") or "native",
        "display": os.environ.get("DISPLAY") or "",
        "editor": "MarkupEditor directly; not MainWindow._open_markup_editor",
        "scenarios": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if results and all(item.get("status") != "error" for item in results) else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reason = _skip_reason()
    if reason == "no display":
        print("skipped: no display")
        print(
            "reason: QT_QPA_PLATFORM=offscreen or DISPLAY is unset. "
            "Spontaneous X11 input was not synthesized.",
            file=sys.stderr,
        )
        print(
            "evidence: skipped scenarios are not X11 evidence and not Windows evidence",
            file=sys.stderr,
        )
        return 0
    if reason is not None:
        print(f"skipped: {reason}")
        print(
            "evidence: xdotool is required for the X11 scenarios",
            file=sys.stderr,
        )
        return 0
    names = list(args.scenario) if args.scenario else list(SCENARIOS)
    return _run(names)


if __name__ == "__main__":
    raise SystemExit(main())
