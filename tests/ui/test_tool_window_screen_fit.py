"""Tool-window screen fit: Batch/UltraView share geometry without extra Board fits."""
from __future__ import annotations

import logging

import pytest
from PyQt5 import sip
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import QDialog, QWidget

from mf4_analyzer.ui.drawers.batch._geometry import fit_dialog_to_available_screen
from mf4_analyzer.ui.drawers.ultraview.sheet import UltraViewSheet
from mf4_analyzer.ui_kit.dialog_geometry import (
    MIN_DECORATED_CLIENT,
    FrameInsets,
    IntRect,
    SCREEN_MARGIN,
)


def test_tool_window_helper_caps_to_compact_work_area(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    qtbot.addWidget(dialog)
    fit_dialog_to_available_screen(dialog, None, 1080, 760, min_w=640, min_h=480)
    assert dialog.width() <= 640 - 2 * SCREEN_MARGIN
    assert dialog.height() <= 360 - 2 * SCREEN_MARGIN


def test_ultraview_present_fits_board_once(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 1280, 800),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )

    class _Page(QWidget):
        def __init__(self):
            super().__init__()
            self.fits = 0

        def fit_on_open(self):
            self.fits += 1

    page = _Page()
    sheet = UltraViewSheet(None, page)
    qtbot.addWidget(sheet)
    sheet.present()
    qtbot.waitExposed(sheet)
    assert page.fits == 1
    sheet.show()
    qapp.processEvents()
    assert page.fits == 1


def _stub_large_screen(monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 1920, 1080),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )


def _pump(qapp):
    for _ in range(4):
        qapp.processEvents()


def test_fit_dialog_minimum_does_not_exceed_the_applied_client(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 640, 360),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    dialog.setWindowTitle("tool")
    qtbot.addWidget(dialog)
    before_max = dialog.maximumSize()
    fit_dialog_to_available_screen(dialog, None, 1080, 760, min_w=640, min_h=480)
    assert dialog.width() <= 640 - 2 * SCREEN_MARGIN
    assert dialog.height() <= 360 - 2 * SCREEN_MARGIN
    assert dialog.minimumWidth() > 0
    assert dialog.minimumHeight() > 0
    assert dialog.minimumWidth() <= dialog.width()
    assert dialog.minimumHeight() <= dialog.height()
    assert dialog.minimumHeight() == dialog.height()
    assert dialog.maximumSize() == before_max
    dialog.resize(50, 50)
    assert dialog.width() >= dialog.minimumWidth()
    assert dialog.height() >= dialog.minimumHeight()
    assert dialog.width() >= MIN_DECORATED_CLIENT
    assert dialog.height() >= MIN_DECORATED_CLIENT


def test_refused_plan_resizes_to_the_content_minimum(qapp, qtbot, monkeypatch, caplog):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 100, 100),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    dialog.setWindowTitle("tool")
    qtbot.addWidget(dialog)
    dialog.resize(320, 240)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        fit_dialog_to_available_screen(dialog, None, 1080, 760, min_w=640, min_h=480)
    assert dialog.width() == 640
    assert dialog.height() == 480
    assert dialog.minimumWidth() == 640
    assert dialog.minimumHeight() == 480
    assert dialog.minimumWidth() <= dialog.width()
    assert dialog.minimumHeight() <= dialog.height()
    assert "degenerate decorated plan refused" in caplog.text


def test_ultraview_minimum_blocks_a_tiny_resize(qapp, qtbot, monkeypatch, caplog):
    _stub_large_screen(monkeypatch)
    page = QWidget()
    qtbot.addWidget(page)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        sheet = UltraViewSheet(None, page)
        qtbot.addWidget(sheet)
        sheet.show()
        qtbot.waitExposed(sheet)
        _pump(qapp)
    assert sheet.minimumWidth() == 800
    assert sheet.minimumHeight() == 560
    sheet.resize(50, 50)
    assert sheet.width() >= sheet.minimumWidth()
    assert sheet.height() >= sheet.minimumHeight()
    assert sheet.width() >= MIN_DECORATED_CLIENT
    assert sheet.height() >= MIN_DECORATED_CLIENT
    assert "tool-window-geometry-recovered" not in caplog.text


def test_batch_minimum_blocks_a_tiny_resize(qapp, qtbot, monkeypatch, caplog):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    _stub_large_screen(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.show()
        qtbot.waitExposed(sheet)
        _pump(qapp)
    assert sheet.minimumWidth() == 640
    assert sheet.minimumHeight() == 480
    sheet.resize(50, 50)
    assert sheet.width() >= sheet.minimumWidth()
    assert sheet.height() >= sheet.minimumHeight()
    assert sheet.width() >= MIN_DECORATED_CLIENT
    assert sheet.height() >= MIN_DECORATED_CLIENT
    assert "tool-window-geometry-recovered" not in caplog.text


def _force_zero_client(widget):
    widget.setMinimumSize(0, 0)
    widget.resize(0, 0)


@pytest.mark.parametrize("kind", ["ultraview", "batch"])
def test_zero_client_before_show_recovers_once(qapp, qtbot, monkeypatch, caplog, kind):
    _stub_large_screen(monkeypatch)
    if kind == "ultraview":
        page = QWidget()
        qtbot.addWidget(page)
        sheet = UltraViewSheet(None, page)
    else:
        from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

        sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    _force_zero_client(sheet)
    assert sheet.width() < MIN_DECORATED_CLIENT
    assert sheet.height() < MIN_DECORATED_CLIENT
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        sheet.show()
        qtbot.waitExposed(sheet)
        _pump(qapp)
        _pump(qapp)
    assert sheet.width() >= MIN_DECORATED_CLIENT
    assert sheet.height() >= MIN_DECORATED_CLIENT
    assert sheet.minimumWidth() > 0
    assert sheet.minimumHeight() > 0
    assert sheet.minimumWidth() <= sheet.width()
    assert sheet.minimumHeight() <= sheet.height()
    recovered = [
        record for record in caplog.records
        if record.getMessage().startswith("tool-window-geometry-recovered")
    ]
    assert len(recovered) == 1
    assert "tool-window-geometry-recovered" in recovered[0].getMessage()


def test_layout_diagnostics_record_tool_window_phases_and_skip_document_text(
    qapp, qtbot, monkeypatch, caplog,
):
    monkeypatch.setenv("TRACELAB_LAYOUT_DIAGNOSTICS", "1")
    monkeypatch.delenv("TRACELAB_LAYOUT_PROBE", raising=False)
    page = QWidget()
    qtbot.addWidget(page)
    secret = "/secret/user/steering-torque.mf4"
    with caplog.at_level(logging.INFO, logger="mf4_analyzer.diagnostics"):
        sheet = UltraViewSheet(None, page)
        qtbot.addWidget(sheet)
        sheet.setWindowTitle(secret)
        sheet.show()
        qtbot.waitExposed(sheet)
        _pump(qapp)
    for phase in ("construct-end", "show-enter", "show-return", "after-show-tick"):
        assert phase in caplog.text
    assert "planned_client" in caplog.text
    assert "planned_frame" in caplog.text
    assert "budget" in caplog.text
    assert "frame_insets" in caplog.text
    assert "available" in caplog.text
    assert "geometry" in caplog.text
    assert "dpr" in caplog.text
    assert secret not in caplog.text


def test_layout_probe_env_enables_the_same_geometry_record(qapp, qtbot, monkeypatch, caplog):
    monkeypatch.delenv("TRACELAB_LAYOUT_DIAGNOSTICS", raising=False)
    monkeypatch.setenv("TRACELAB_LAYOUT_PROBE", "1")
    page = QWidget()
    qtbot.addWidget(page)
    with caplog.at_level(logging.INFO, logger="mf4_analyzer.diagnostics"):
        sheet = UltraViewSheet(None, page)
        qtbot.addWidget(sheet)
        sheet.show()
        qtbot.waitExposed(sheet)
        _pump(qapp)
    assert "construct-end" in caplog.text
    assert "after-show-tick" in caplog.text


def test_geometry_trace_stays_quiet_when_the_switch_is_off(qapp, qtbot, monkeypatch, caplog):
    monkeypatch.delenv("TRACELAB_LAYOUT_DIAGNOSTICS", raising=False)
    monkeypatch.delenv("TRACELAB_LAYOUT_PROBE", raising=False)
    page = QWidget()
    qtbot.addWidget(page)
    with caplog.at_level(logging.INFO, logger="mf4_analyzer.diagnostics"):
        sheet = UltraViewSheet(None, page)
        qtbot.addWidget(sheet)
        sheet.show()
        qtbot.waitExposed(sheet)
        _pump(qapp)
    assert "tool-window-geometry" not in caplog.text
    assert "construct-end" not in caplog.text


class _SpontaneousShow(QShowEvent):
    def spontaneous(self):  # noqa: D102
        return True


def _new_tool_sheet(qtbot, kind):
    if kind == "ultraview":
        page = QWidget()
        qtbot.addWidget(page)
        sheet = UltraViewSheet(None, page)
    else:
        from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

        sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    return sheet


def _patch_nudge(monkeypatch, calls, *, resize=None):
    def nudge(widget, **_kwargs):
        calls.append(widget)
        if resize is not None:
            widget.resize(*resize)

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.nudge_into_work_area",
        nudge,
    )


@pytest.mark.parametrize("kind", ["ultraview", "batch"])
def test_spontaneous_show_does_not_nudge(qapp, qtbot, monkeypatch, kind):
    calls = []
    _patch_nudge(monkeypatch, calls)
    sheet = _new_tool_sheet(qtbot, kind)
    sheet.showEvent(_SpontaneousShow())
    assert calls == []


@pytest.mark.parametrize("kind", ["ultraview", "batch"])
def test_normal_show_still_nudges_once(qapp, qtbot, monkeypatch, kind):
    calls = []
    _patch_nudge(monkeypatch, calls)
    sheet = _new_tool_sheet(qtbot, kind)
    sheet.show()
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["ultraview", "batch"])
@pytest.mark.parametrize("how", ["maximized", "fullscreen", "minimized"])
def test_special_window_state_show_does_not_nudge(
    qapp, qtbot, monkeypatch, kind, how,
):
    calls = []
    _patch_nudge(monkeypatch, calls, resize=(211, 211))
    sheet = _new_tool_sheet(qtbot, kind)
    if how == "minimized":
        sheet.showMinimized()
        assert sheet.isMinimized()
    elif how == "fullscreen":
        sheet.setWindowState(Qt.WindowFullScreen)
        sheet.show()
        assert sheet.isFullScreen()
    else:
        sheet.setWindowState(Qt.WindowMaximized)
        sheet.show()
        assert sheet.isMaximized()
    assert calls == []
    assert (sheet.width(), sheet.height()) != (211, 211)


@pytest.mark.parametrize("kind", ["ultraview", "batch"])
def test_screen_changed_nudges_once_and_disconnects_on_close(
    qapp, qtbot, monkeypatch, kind,
):
    calls = []
    _patch_nudge(monkeypatch, calls)
    sheet = _new_tool_sheet(qtbot, kind)
    sheet.show()
    handle = sheet.windowHandle()
    assert handle is not None
    calls.clear()
    handle.screenChanged.emit(handle.screen())
    assert len(calls) == 1

    sheet.setWindowState(Qt.WindowMaximized)
    calls.clear()
    handle.screenChanged.emit(handle.screen())
    assert len(calls) == 1

    sheet.hide()
    sheet.show()
    calls.clear()
    handle = sheet.windowHandle()
    handle.screenChanged.emit(handle.screen())
    assert len(calls) == 1

    sheet.close()
    if not sip.isdeleted(sheet):
        handle = sheet.windowHandle()
        if handle is not None and not sip.isdeleted(handle):
            before = len(calls)
            handle.screenChanged.emit(handle.screen())
            assert len(calls) == before


def test_markup_editor_refused_plan_keeps_content_minimum(qapp, qtbot, monkeypatch, caplog):
    """D-M5 uses the shared floor: a degenerate plan is not applied."""
    from PyQt5.QtGui import QColor, QPixmap

    from mf4_analyzer.ui.markup.editor import MarkupEditor

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 100, 100),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    pixmap = QPixmap(400, 300)
    pixmap.fill(QColor("#f7f7f7"))
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        editor = MarkupEditor(pixmap)
        qtbot.addWidget(editor)
    assert editor.width() == 720
    assert editor.height() == 480
    assert editor.minimumWidth() == 720
    assert editor.minimumHeight() == 480
    assert editor.width() >= MIN_DECORATED_CLIENT
    assert editor.height() >= MIN_DECORATED_CLIENT
    assert "degenerate decorated plan refused" in caplog.text


def test_present_clears_minimized_and_keeps_maximized(qapp, qtbot):
    from mf4_analyzer.ui.drawers.batch._geometry import (
        present_independent_tool_window,
    )

    dialog = QDialog()
    dialog.setWindowTitle("tool")
    qtbot.addWidget(dialog)
    dialog.resize(420, 300)
    dialog.show()
    dialog.setWindowState(Qt.WindowMaximized | Qt.WindowMinimized)
    qapp.processEvents()
    assert dialog.isMinimized()
    assert dialog.isMaximized()
    present_independent_tool_window(dialog)
    qapp.processEvents()
    assert not dialog.isMinimized()
    assert dialog.isMaximized()
