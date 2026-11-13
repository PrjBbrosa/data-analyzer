#!/usr/bin/env python3
"""X11 input probe for UltraView deactivation, wheel, cursor, drag, and select.

Evidence class
--------------
Scenarios, in order: ``deactivation``, ``wheel``, ``handle-cursor``,
``card-drag``, ``author-select``. When ``DISPLAY`` is set, ``xdotool`` is
on ``PATH``, and ``QT_QPA_PLATFORM`` is not ``offscreen``, the script
constructs a real ``MainWindow``, calls ``open_ultraview()``, and drives
the window with ``xdotool``. It prints one JSON object and closes every
window it opened.

Under offscreen, or with no ``DISPLAY``, ``--self-check`` prints
``skipped: no display`` and exits 0. It does not synthesize
``QTest`` / ``sendEvent`` input and then call that an X11 result.
Offscreen numbers are not Windows evidence and are not X11 evidence.

This script is not product code. It does not write into ``docs/`` or the
git tree. ``MainWindow`` preferences are redirected to a temporary INI
under ``TMPDIR`` when that variable is set, otherwise the platform temp
directory (``TEMP`` / ``TMP`` on Windows). The deactivation scenario may
leave Space held in the app; that observation is recorded, then Space and
any pan are cleared before the next scenario.

    .venv/bin/python scripts/probe_ultraview_interaction.py --help
    TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
        .venv/bin/python scripts/probe_ultraview_interaction.py --self-check
    TMPDIR=/tmp DISPLAY=:1 QT_QPA_PLATFORM=xcb PYTHONPATH=. \\
        .venv/bin/python scripts/probe_ultraview_interaction.py
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

SCENARIOS = (
    "deactivation",
    "wheel",
    "handle-cursor",
    "card-drag",
    "author-select",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Drive UltraView with real X11 input via xdotool. "
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
            "'skipped: no display' and exit 0. With DISPLAY and xdotool, "
            "run the scenarios and close the windows."
        ),
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=SCENARIOS,
        help="Run only this scenario. Repeat to run several. Default: all five.",
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


def _temp_directory(prefix: str):
    """Honor ``TMPDIR`` when set; otherwise use the platform temp dir.

    A hardcoded ``/tmp`` fallback raises ``FileNotFoundError`` on Windows
    when ``TMPDIR`` is unset and the drive has no ``\\tmp``.
    """
    root = os.environ.get("TMPDIR")
    if root:
        return tempfile.TemporaryDirectory(prefix=prefix, dir=root)
    return tempfile.TemporaryDirectory(prefix=prefix)


def _release_gesture_state(session: _Session) -> None:
    """Clear Space-pan left behind by the deactivation scenario.

    The U-1 reading is already in that scenario's result. Later scenarios
    share this session; a stuck ``space_down`` makes left-drag a board pan,
    so card-drag and author-select would measure the wrong gesture.
    """
    _xdo("keyup", "space")
    page = session.page
    note = getattr(page, "note_space", None)
    if callable(note):
        note(False)
    cancel = getattr(page, "_cancel_board_gestures", None)
    if callable(cancel):
        cancel()
    controller = getattr(page, "_viewport_ctrl", None)
    end_pan = getattr(controller, "end_board_pan", None) if controller is not None else None
    if callable(end_pan):
        end_pan()
    _pump(session.app, 0.05)


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


def _cursor_name(shape) -> str:
    from PyQt5.QtCore import Qt

    names = {
        int(Qt.ArrowCursor): "ArrowCursor",
        int(Qt.UpArrowCursor): "UpArrowCursor",
        int(Qt.CrossCursor): "CrossCursor",
        int(Qt.IBeamCursor): "IBeamCursor",
        int(Qt.WaitCursor): "WaitCursor",
        int(Qt.SizeVerCursor): "SizeVerCursor",
        int(Qt.SizeHorCursor): "SizeHorCursor",
        int(Qt.SizeBDiagCursor): "SizeBDiagCursor",
        int(Qt.SizeFDiagCursor): "SizeFDiagCursor",
        int(Qt.SizeAllCursor): "SizeAllCursor",
        int(Qt.BlankCursor): "BlankCursor",
        int(Qt.SplitVCursor): "SplitVCursor",
        int(Qt.SplitHCursor): "SplitHCursor",
        int(Qt.PointingHandCursor): "PointingHandCursor",
        int(Qt.ForbiddenCursor): "ForbiddenCursor",
        int(Qt.OpenHandCursor): "OpenHandCursor",
        int(Qt.ClosedHandCursor): "ClosedHandCursor",
        int(Qt.WhatsThisCursor): "WhatsThisCursor",
        int(Qt.BusyCursor): "BusyCursor",
    }
    try:
        value = int(shape)
    except (TypeError, ValueError):
        return str(shape)
    return names.get(value, str(value))


def _cursor_at(widget) -> dict:
    from PyQt5.QtWidgets import QApplication

    if widget is None:
        return {"widget": None}
    cursor = widget.cursor()
    override = QApplication.overrideCursor()
    return {
        "widget": type(widget).__name__,
        "objectName": widget.objectName(),
        "shape": _cursor_name(cursor.shape()),
        "override": None if override is None else _cursor_name(override.shape()),
    }


def _bar_facts(bar) -> dict:
    return {
        "value": int(bar.value()),
        "singleStep": int(bar.singleStep()),
        "pageStep": int(bar.pageStep()),
        "minimum": int(bar.minimum()),
        "maximum": int(bar.maximum()),
    }


def _isolate_settings(directory: Path) -> None:
    from PyQt5.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(directory))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(directory))
    ini = str(directory / "qsettings.ini")

    def _factory(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    import mf4_analyzer.ui.batch_settings as batch_settings
    import mf4_analyzer.ui.inspector_sections as inspector_pkg
    import mf4_analyzer.ui.inspector_sections._helpers as helpers
    import mf4_analyzer.ui.inspector_sections.collapsible as collapsible
    import mf4_analyzer.ui.inspector_sections.persistent_top as persistent_top
    import mf4_analyzer.ui.inspector_sections.presets as presets
    import mf4_analyzer.ui.recent_files as recent_files

    batch_settings._default_settings = _factory
    recent_files._default_settings = _factory
    helpers._preset_settings = _factory
    inspector_pkg._preset_settings = _factory
    collapsible._preset_settings = _factory
    persistent_top._preset_settings = _factory
    presets._preset_settings = _factory


class _WindowEventCounter:
    """Count activate/deactivate deliveries. Not a product event filter class."""

    def __init__(self, parent) -> None:
        from PyQt5.QtCore import QEvent, QObject

        class _Filter(QObject):
            def __init__(self) -> None:
                super().__init__()
                self.window_deactivate = 0
                self.window_activate = 0

            def eventFilter(self, watched, event):  # noqa: N802
                kind = event.type()
                if kind == QEvent.WindowDeactivate:
                    self.window_deactivate += 1
                elif kind == QEvent.WindowActivate:
                    self.window_activate += 1
                return False

        self._filter = _Filter()
        parent.installEventFilter(self._filter)

    def reset(self) -> None:
        self._filter.window_deactivate = 0
        self._filter.window_activate = 0

    def facts(self) -> dict:
        return {
            "window_deactivate": int(self._filter.window_deactivate),
            "window_activate": int(self._filter.window_activate),
        }


class _Session:
    def __init__(self, app, window, sheet, page, other, page_counter, sheet_counter) -> None:
        self.app = app
        self.window = window
        self.sheet = sheet
        self.page = page
        self.other = other
        self.page_counter = page_counter
        self.sheet_counter = sheet_counter

    def close(self) -> None:
        from PyQt5 import sip

        for widget in (self.sheet, self.other, self.window):
            if widget is None:
                continue
            try:
                if sip.isdeleted(widget):
                    continue
            except (RuntimeError, TypeError):
                continue
            try:
                widget.close()
            except RuntimeError:
                continue
        self.app.processEvents()


def _open_session(app, directory: Path) -> _Session:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QWidget

    from mf4_analyzer.ui.main_window.window import MainWindow

    _isolate_settings(directory)
    window = MainWindow()
    window.resize(1400, 900)
    window.move(40, 40)
    window.show()
    _pump(app, 0.3)
    window.open_ultraview()
    _pump(app, 0.4)
    sheet = getattr(window, "_ultraview_sheet", None)
    if sheet is None:
        raise RuntimeError("open_ultraview() did not leave _ultraview_sheet")
    page = getattr(sheet, "_page", None)
    if page is None:
        raise RuntimeError("UltraViewSheet has no page")
    other = QWidget(None, Qt.Window)
    other.setWindowTitle("probe-deactivation-other")
    other.resize(280, 180)
    other.move(40, 40)
    other.show()
    _pump(app, 0.2)
    return _Session(
        app,
        window,
        sheet,
        page,
        other,
        _WindowEventCounter(page),
        _WindowEventCounter(sheet),
    )


def _viewport_center_global(page):
    from PyQt5.QtCore import QPoint

    viewport = page._board_scroll.viewport()
    center = viewport.rect().center()
    return viewport.mapToGlobal(QPoint(center))


def _scenario_deactivation(session: _Session) -> dict:
    from PyQt5.QtWidgets import QApplication

    page = session.page
    session.page_counter.reset()
    session.sheet_counter.reset()
    target = _viewport_center_global(page)
    commands = []
    commands.append(_xdo("mousemove", "--sync", str(target.x()), str(target.y())))
    commands.append(_xdo("windowactivate", "--sync", _wid(session.sheet)))
    _pump(session.app, 0.2)
    before = {
        "space_down": bool(page._viewport.space_down()),
        "router_installed": bool(page._viewport_router._installed),
        "viewport_cursor": _cursor_at(page._board_scroll.viewport()),
        "sheet_active": bool(session.sheet.isActiveWindow()),
    }
    commands.append(_xdo("keydown", "space"))
    _pump(session.app, 0.25)
    after_keydown = {
        "space_down": bool(page._viewport.space_down()),
        "viewport_cursor": _cursor_at(page._board_scroll.viewport()),
        "sheet_active": bool(session.sheet.isActiveWindow()),
    }
    commands.append(_xdo("windowactivate", "--sync", _wid(session.other)))
    _pump(session.app, 0.25)
    commands.append(_xdo("keyup", "space"))
    _pump(session.app, 0.2)
    commands.append(_xdo("windowactivate", "--sync", _wid(session.sheet)))
    _pump(session.app, 0.25)
    after = {
        "space_down": bool(page._viewport.space_down()),
        "panning": bool(page._viewport.is_panning()),
        "router_installed": bool(page._viewport_router._installed),
        "viewport_cursor": _cursor_at(page._board_scroll.viewport()),
        "sheet_active": bool(session.sheet.isActiveWindow()),
        "active_window": type(QApplication.activeWindow()).__name__
        if QApplication.activeWindow() is not None
        else None,
        "page_events": session.page_counter.facts(),
        "sheet_events": session.sheet_counter.facts(),
    }
    return {
        "scenario": "deactivation",
        "status": "observed",
        "before": before,
        "after_keydown": after_keydown,
        "after_switch_release_and_return": after,
        "xdotool": commands,
        "note": (
            "Space is pressed on UltraView, released while another window is "
            "active, then UltraView is activated again. space_down staying "
            "true is the U-1 observation."
        ),
    }


def _scenario_wheel(session: _Session) -> dict:
    page = session.page
    target = _viewport_center_global(page)
    scroll = page._board_scroll
    commands = [_xdo("mousemove", "--sync", str(target.x()), str(target.y()))]
    _pump(session.app, 0.15)
    before = {
        "horizontal": _bar_facts(scroll.horizontalScrollBar()),
        "vertical": _bar_facts(scroll.verticalScrollBar()),
    }
    commands.append(_xdo("click", "5"))
    _pump(session.app, 0.2)
    after_plain = {
        "horizontal": _bar_facts(scroll.horizontalScrollBar()),
        "vertical": _bar_facts(scroll.verticalScrollBar()),
    }
    commands.append(_xdo("keydown", "shift"))
    commands.append(_xdo("click", "5"))
    commands.append(_xdo("keyup", "shift"))
    _pump(session.app, 0.2)
    after_shift = {
        "horizontal": _bar_facts(scroll.horizontalScrollBar()),
        "vertical": _bar_facts(scroll.verticalScrollBar()),
    }
    plain_dy = after_plain["vertical"]["value"] - before["vertical"]["value"]
    shift_dy = after_shift["vertical"]["value"] - after_plain["vertical"]["value"]
    shift_dx = after_shift["horizontal"]["value"] - after_plain["horizontal"]["value"]
    return {
        "scenario": "wheel",
        "status": "observed",
        "before": before,
        "after_plain_wheel_down": after_plain,
        "after_shift_wheel_down": after_shift,
        "plain_vertical_delta": plain_dy,
        "shift_vertical_delta": shift_dy,
        "shift_horizontal_delta": shift_dx,
        "xdotool": commands,
        "note": (
            "One plain wheel notch, then one Shift+wheel notch. "
            "A vertical delta near pageStep is the U-3 page-jump observation."
        ),
    }


def _place_card(session: _Session) -> dict:
    from mf4_analyzer.ui.ultraview_state import UltraViewRef

    window = session.window
    manager = getattr(window, "view_manager", None)
    view = manager.get(0) if manager is not None else None
    view_id = getattr(view, "view_id", None)
    if view_id is None:
        return {"placed": False, "reason": "view_manager has no view 0"}
    ref = UltraViewRef("time", str(view_id))
    window._ultraview._apply_add_ref(ref)
    window._ultraview.refresh_page()
    _pump(session.app, 0.3)
    card = session.page.card_widget(ref.section, ref.view_id)
    if card is None or card.width() < 20 or card.height() < 20:
        return {
            "placed": False,
            "reason": "card widget missing or smaller than 20 px",
            "ref": {"section": ref.section, "view_id": ref.view_id},
        }
    session.page._free_grid.interaction().select_only_card(ref)
    session.page._free_grid._apply_selection_flags()
    _pump(session.app, 0.1)
    return {"placed": True, "ref": ref, "card": card}


def _point_facts(session: _Session, card, local_x: int, local_y: int) -> dict:
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication

    global_pos = card.mapToGlobal(QPoint(int(local_x), int(local_y)))
    _xdo("mousemove", "--sync", str(global_pos.x()), str(global_pos.y()))
    _pump(session.app, 0.15)
    leaf = QApplication.widgetAt(global_pos)
    return {
        "local": [int(local_x), int(local_y)],
        "global": [int(global_pos.x()), int(global_pos.y())],
        "leaf": _cursor_at(leaf),
        "card": _cursor_at(card),
        "board": _cursor_at(session.page._free_grid),
    }


def _scenario_handle_cursor(session: _Session) -> dict:
    placed = _place_card(session)
    if not placed.get("placed"):
        return {"scenario": "handle-cursor", "status": "blocked", **placed}
    card = placed["card"]
    inside = _point_facts(session, card, max(0, card.width() - 4), card.height() // 2)
    border = _point_facts(session, card, max(0, card.width() - 1), card.height() // 2)
    center = _point_facts(session, card, card.width() // 2, card.height() // 2)
    return {
        "scenario": "handle-cursor",
        "status": "observed",
        "ref": {
            "section": placed["ref"].section,
            "view_id": placed["ref"].view_id,
        },
        "card_size": [int(card.width()), int(card.height())],
        "selected": bool(card.model().selected),
        "inside_4px": inside,
        "border_1px": border,
        "center": center,
        "note": (
            "Pointer is moved with xdotool. Selection is armed through the "
            "board interaction owner so the hover sample is not a missed click. "
            "Arrow at the inner 4 px edge and a resize cursor only after the "
            "1 px border is the U-4 observation."
        ),
    }


def _ghost_facts(session: _Session, pointer_x: int, pointer_y: int) -> dict:
    overlay = session.page._free_grid._overlay
    rect = overlay._ghost_rect
    if rect is None:
        return {"ghost": None, "pointer": [pointer_x, pointer_y]}
    top_left = overlay.mapToGlobal(rect.topLeft())
    return {
        "ghost": [int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())],
        "ghost_global": [int(top_left.x()), int(top_left.y())],
        "pointer": [pointer_x, pointer_y],
        "pointer_minus_ghost_x": int(pointer_x - top_left.x()),
        "pointer_minus_ghost_y": int(pointer_y - top_left.y()),
    }


def _scenario_card_drag(session: _Session) -> dict:
    from PyQt5.QtCore import QPoint

    placed = _place_card(session)
    if not placed.get("placed"):
        return {"scenario": "card-drag", "status": "blocked", **placed}
    card = placed["card"]
    origin = card.mapToGlobal(QPoint(card.width() // 2, card.height() // 2))
    samples = []
    _xdo("mousemove", "--sync", str(origin.x()), str(origin.y()))
    _xdo("mousedown", "1")
    _pump(session.app, 0.05)
    for step in range(1, 61):
        pointer_x = origin.x() + step
        pointer_y = origin.y()
        _xdo("mousemove", "--sync", str(pointer_x), str(pointer_y))
        session.app.processEvents()
        if step == 1 or step % 10 == 0 or step == 60:
            samples.append(_ghost_facts(session, pointer_x, pointer_y))
    _xdo("mouseup", "1")
    _pump(session.app, 0.15)
    return {
        "scenario": "card-drag",
        "status": "observed",
        "card_size": [int(card.width()), int(card.height())],
        "drag_px": 60,
        "samples": samples,
        "note": (
            "Left-drag 60 px at 1 px steps from the card center. "
            "Ghost positions that jump by a cell, or sit more than 1 px "
            "from the pointer, are the U-6 observation."
        ),
    }


def _scenario_author_select(session: _Session) -> dict:
    from PyQt5.QtCore import QPoint

    from mf4_analyzer.ultraview_core.model import BoardBox, ShapeObject
    from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import (
        board_box_to_pixels,
    )

    shape = ShapeObject(
        object_id="probe-shape-1",
        kind="shape",
        box=BoardBox(2, 2, 3, 2),
    )
    board = session.window._ultraview.board
    board.author_objects.append(shape)
    session.window._ultraview.refresh_page()
    _pump(session.app, 0.3)
    grid = session.page._free_grid
    mapped = board_box_to_pixels(
        (shape.box.x, shape.box.y, shape.box.width, shape.box.height),
        grid.metrics(),
        origin_offset=grid.workspace_origin_offset(),
    )
    if mapped is None:
        return {
            "scenario": "author-select",
            "status": "blocked",
            "reason": "shape did not map to pixels",
        }
    x, y, width, height = (int(mapped[0]), int(mapped[1]), int(mapped[2]), int(mapped[3]))
    start = grid.mapToGlobal(QPoint(x - 24, y - 24))
    end = grid.mapToGlobal(QPoint(x + width + 24, y + height + 24))
    tool = grid.interaction().active_tool()
    _xdo("mousemove", "--sync", str(start.x()), str(start.y()))
    _xdo("mousedown", "1")
    _pump(session.app, 0.05)
    _xdo("mousemove", "--sync", str(end.x()), str(end.y()))
    _pump(session.app, 0.1)
    _xdo("mouseup", "1")
    _pump(session.app, 0.2)
    return {
        "scenario": "author-select",
        "status": "observed",
        "tool": tool,
        "object_id": shape.object_id,
        "pixel_box": [x, y, width, height],
        "author_selection_ids": sorted(grid.author_selection_ids()),
        "card_selection": [
            {"section": ref.section, "view_id": ref.view_id}
            for ref in grid.interaction().card_selection()
        ],
        "note": (
            "A rectangle drag encloses one shape object on the real "
            "coordinator's board. An empty author_selection_ids is the "
            "U-7 box-select observation."
        ),
    }


_SCENARIO_FUNCS = {
    "deactivation": _scenario_deactivation,
    "wheel": _scenario_wheel,
    "handle-cursor": _scenario_handle_cursor,
    "card-drag": _scenario_card_drag,
    "author-select": _scenario_author_select,
}


def _run(names: list[str]) -> int:
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["probe_ultraview_interaction"])
    app.setQuitOnLastWindowClosed(False)
    app.setOrganizationName("TraceLabProbe")
    app.setApplicationName("UltraViewInteractionProbe")
    session = None
    results = []
    try:
        with _temp_directory("tracelab-ultraview-input-") as tmp:
            try:
                session = _open_session(app, Path(tmp))
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "scenario": "setup",
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc(),
                    }
                )
            else:
                for name in names:
                    try:
                        results.append(_SCENARIO_FUNCS[name](session))
                    except Exception as exc:  # noqa: BLE001
                        results.append(
                            {
                                "scenario": name,
                                "status": "error",
                                "error": f"{type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(),
                            }
                        )
                    if name == "deactivation":
                        _release_gesture_state(session)
    finally:
        _release_inputs()
        if session is not None:
            session.close()
        app.processEvents()
    payload = {
        "evidence_class": "x11-real-input",
        "offscreen_is_x11_evidence": False,
        "offscreen_is_windows_evidence": False,
        "platform": os.environ.get("QT_QPA_PLATFORM") or "native",
        "display": os.environ.get("DISPLAY") or "",
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
