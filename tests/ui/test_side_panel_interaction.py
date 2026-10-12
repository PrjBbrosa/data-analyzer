"""Real strip / overlay / controller interaction.

Existing side-panel tests emit ``peek_requested`` / ``mouse_left`` on a bare
widget. These cases drive the production ``SidePanelStrip`` enter/leave
handlers and the controller's peek watch. They do not call
``peek_requested.emit()`` or ``mouse_left.emit()``.

Offscreen Qt delivers ``QEvent.Enter`` / ``QEvent.Leave`` through
``QApplication.sendEvent``. The 150 ms open delay and 600 ms grace are the
production defaults. Popups and dialogs are shown with ``popup()`` / ``show()``
/ ``done()``; ``exec_()`` is stubbed to fail in this suite.
"""
import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QObject, QPoint, Qt
from PyQt5.QtGui import QCursor
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.ui.side_panels import (
    PanelState,
    PeekOverlay,
    Side,
    SidePanelController,
    SidePanelStrip,
)


class _Toggle(QObject):
    """Toolbar-button stand-in: clicked -> the controller's click event."""

    def __init__(self, controller):
        super().__init__(controller)
        self._controller = controller
        self.button = QPushButton("panel")
        self.button.setFixedSize(48, 22)
        self.button.clicked.connect(self.on_clicked)

    def on_clicked(self, _checked=False):
        from mf4_analyzer.ui.side_panels import Ev

        self._controller._dispatch(Ev.CLICK)


class _OverlayMarks(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.entered = 0
        self.left = 0

    def on_entered(self):
        self.entered += 1

    def on_left(self):
        self.left += 1


def _wire(qtbot, side, managed=True):
    host = QWidget()
    host.resize(1200, 700)
    root = QVBoxLayout(host)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    splitter = QSplitter(Qt.Horizontal)
    navigator = QWidget()
    navigator.setMinimumWidth(50)
    chart = QWidget()
    chart.setObjectName("chart")
    chart.setMinimumWidth(100)
    inspector = QWidget()
    inspector.setMinimumWidth(50)
    splitter.addWidget(navigator)
    splitter.addWidget(chart)
    splitter.addWidget(inspector)
    splitter.setSizes([250, 700, 250])
    splitter.setCollapsible(0, True)
    splitter.setCollapsible(1, False)
    splitter.setCollapsible(2, True)

    if side is Side.RIGHT:
        panel = inspector
        index = 2
    else:
        panel = navigator
        index = 0
    strip = SidePanelStrip(side, hover_delay_ms=150, parent=host)
    overlay = PeekOverlay(host)
    controller = SidePanelController(
        side=side,
        splitter=splitter,
        panel=panel,
        panel_index=index,
        strip=strip,
        overlay=overlay,
        host=host,
        collapse_delay_ms=600,
        default_width=250,
        canvas=chart,
        parent=host,
    )
    toggle = _Toggle(controller)
    marks = _OverlayMarks(host)
    overlay.mouse_entered.connect(marks.on_entered)
    overlay.mouse_left.connect(marks.on_left)

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    if side is Side.LEFT:
        row.addWidget(strip)
    row.addWidget(splitter, 1)
    if side is Side.RIGHT:
        row.addWidget(strip)
    root.addWidget(toggle.button)
    root.addLayout(row, 1)

    host.show()
    if managed:
        qtbot.addWidget(host)
    return controller, splitter, panel, strip, overlay, toggle, marks, index


def _collapse(entry, controller, splitter, toggle, index):
    if entry == "toolbar-click":
        QTest.mouseClick(toggle.button, Qt.LeftButton)
        return
    sizes = list(splitter.sizes())
    sizes[1] += sizes[index]
    sizes[index] = 0
    splitter.setSizes(sizes)
    controller.on_splitter_moved()


def _post(widget, event_type):
    QApplication.sendEvent(widget, QEvent(event_type))


def _park_outside(host, _anchor=None):
    """Park on the chart. The left overlay covers the toolbar button at y=0."""
    host.move(0, 0)
    QApplication.processEvents()
    QCursor.setPos(400, 280)
    QApplication.processEvents()


def _peek(qtbot, controller, strip):
    _post(strip, QEvent.Enter)
    qtbot.waitUntil(lambda: controller.state == PanelState.PEEK, timeout=1000)
    assert controller._app_filter_installed is True


def _fill(panel):
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(2, 2, 2, 2)
    first = QPushButton("first", panel)
    second = QPushButton("second", panel)
    edit = QLineEdit(panel)
    for widget in (first, second, edit):
        widget.setFixedHeight(22)
        layout.addWidget(widget)
    QApplication.processEvents()
    return first, second, edit


def _assert_grace_then_hidden(qtbot, controller):
    assert controller.state == PanelState.PEEK
    assert controller._collapse_timer.isActive() is True
    qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=2000)
    assert controller._collapse_timer.isActive() is False
    assert controller._app_filter_installed is False


def test_strip_leave_to_chart_collapses_after_grace(qtbot, side, entry):
    controller, splitter, panel, strip, overlay, toggle, marks, index = _wire(
        qtbot, side,
    )
    _collapse(entry, controller, splitter, toggle, index)
    assert controller.state == PanelState.HIDDEN
    assert strip.isVisible()

    _peek(qtbot, controller, strip)
    assert panel.parent() is overlay
    assert overlay.isVisible()

    # Rail directly to the chart: leave the strip, never enter the overlay.
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    try:
        _assert_grace_then_hidden(qtbot, controller)
    except AssertionError as exc:
        raise AssertionError(
            "strip→chart did not collapse: "
            f"state={controller.state.name} "
            f"collapse_timer_active={controller._collapse_timer.isActive()} "
            f"overlay_entered={marks.entered} overlay_left={marks.left} "
            f"side={side.name} entry={entry}"
        ) from exc
    assert panel.parent() is not overlay
    assert overlay.isVisible() is False


def test_overlay_leave_to_chart_collapses_after_grace(qtbot, side):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _post(overlay, QEvent.Enter)
    _park_outside(strip.parent(), toggle.button)
    _post(overlay, QEvent.Leave)
    _assert_grace_then_hidden(qtbot, controller)
    assert panel.parent() is not overlay


def test_overlay_to_rail_stays_open(qtbot, side):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _post(overlay, QEvent.Enter)
    _post(overlay, QEvent.Leave)
    _post(strip, QEvent.Enter)
    assert controller._collapse_timer.isActive() is False
    assert controller.state == PanelState.PEEK
    assert panel.parent() is overlay
    qtbot.wait(800)
    assert controller.state == PanelState.PEEK
    assert panel.parent() is overlay
    assert controller._app_filter_installed is True


def test_strip_to_overlay_does_not_reparent(qtbot, side):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _post(strip, QEvent.Leave)
    _post(overlay, QEvent.Enter)
    assert controller.state == PanelState.PEEK
    assert panel.parent() is overlay
    assert controller._collapse_timer.isActive() is False
    qtbot.wait(800)
    assert controller.state == PanelState.PEEK
    assert panel.parent() is overlay


def test_child_to_child_stays_open_without_reparent(qtbot, side):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    first, second, _edit = _fill(panel)
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    QApplication.processEvents()
    _post(overlay, QEvent.Enter)
    _post(first, QEvent.Leave)
    _post(second, QEvent.Enter)
    assert controller._collapse_timer.isActive() is False
    assert controller.state == PanelState.PEEK
    assert panel.parent() is overlay
    qtbot.wait(800)
    assert controller.state == PanelState.PEEK
    assert panel.parent() is overlay
    assert first.parent() is panel
    assert second.parent() is panel


def test_reentry_within_grace_cancels_collapse(qtbot, side):
    controller, splitter, _panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    assert controller.state == PanelState.PEEK
    assert controller._collapse_timer.isActive() is True
    _post(overlay, QEvent.Enter)
    assert controller._collapse_timer.isActive() is False
    assert controller.state == PanelState.PEEK
    qtbot.wait(800)
    assert controller.state == PanelState.PEEK
    assert controller._app_filter_installed is True


def test_leave_outside_window_collapses_after_grace(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    strip.parent().move(0, 0)
    QCursor.setPos(-40, -40)
    QApplication.processEvents()
    _post(strip, QEvent.Leave)
    _assert_grace_then_hidden(qtbot, controller)


def test_focus_does_not_keep_peek_alive(qtbot, side):
    controller, splitter, panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _edit_host, _second, edit = _fill(panel)
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    strip.parent().activateWindow()
    edit.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert edit.hasFocus() is True
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    _assert_grace_then_hidden(qtbot, controller)


def test_early_timeout_does_not_collapse_before_deadline(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    assert controller._collapse_timer.isActive() is True
    deadline = controller._grace_deadline
    controller._on_collapse_timeout()
    assert controller.state == PanelState.PEEK
    assert controller._collapse_timer.isActive() is True
    assert controller._grace_deadline == deadline
    qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=2000)
    assert controller._app_filter_installed is False


def test_owned_transient_blocks_until_it_closes(qtbot, side, transient_kind):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    first, _second, edit = _fill(panel)
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    assert controller._collapse_timer.isActive() is True
    transient = _open_transient(transient_kind, panel, first, edit)
    try:
        QApplication.processEvents()
        qtbot.wait(800)
        assert controller.state == PanelState.PEEK, transient_kind
        assert panel.parent() is overlay
        assert controller._collapse_timer.isActive() is False
        _close_transient(transient)
        QApplication.processEvents()
        qtbot.wait(30)
        _park_outside(strip.parent(), toggle.button)
        qtbot.wait(30)
        assert controller.state == PanelState.PEEK
        assert controller._collapse_timer.isActive() is True
        qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=2000)
    finally:
        _close_transient(transient)


def test_unrelated_popup_does_not_block_collapse(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    chart = splitter.widget(1)
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    menu = QMenu(chart)
    menu.addAction("unrelated")
    try:
        menu.popup(QPoint(30, 30))
        QApplication.processEvents()
        assert QApplication.activePopupWidget() is menu
        qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=2000)
        assert controller._collapse_timer.isActive() is False
        assert menu.isVisible() is True
    finally:
        menu.close()


def test_drag_release_collapses_only_after_release(qtbot, side):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    first, _second, _edit = _fill(panel)
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    QApplication.processEvents()
    assert first.width() > 0 and first.height() > 0
    _post(overlay, QEvent.Enter)
    QTest.mousePress(first, Qt.LeftButton)
    try:
        assert QApplication.mouseButtons() & Qt.LeftButton
        _park_outside(strip.parent(), toggle.button)
        assert QApplication.mouseButtons() & Qt.LeftButton
        _post(overlay, QEvent.Leave)
        qtbot.wait(800)
        assert controller.state == PanelState.PEEK
        assert panel.parent() is overlay
        QTest.mouseRelease(first, Qt.LeftButton)
        qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=500)
        assert panel.parent() is not overlay
    finally:
        if QApplication.mouseButtons() & Qt.LeftButton:
            QTest.mouseRelease(first, Qt.LeftButton)


def test_twenty_peek_collapse_cycles_clear_the_watch(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    host = strip.parent()
    for _cycle in range(20):
        _peek(qtbot, controller, strip)
        _park_outside(host, toggle.button)
        _post(strip, QEvent.Leave)
        _assert_grace_then_hidden(qtbot, controller)


def test_resize_while_peeking_keeps_the_watch(qtbot, side):
    controller, splitter, _panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    host = strip.parent()
    host.resize(1000, 620)
    controller.reposition()
    assert controller.state == PanelState.PEEK
    assert overlay.height() == host.height()
    assert controller._app_filter_installed is True
    assert controller._collapse_timer.isActive() is False


def test_hide_minimize_deactivate_and_close_clear_peek(qtbot, side, lifecycle):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    host = strip.parent()
    if lifecycle == "hide":
        host.hide()
    elif lifecycle == "minimize":
        host.setWindowState(host.windowState() | Qt.WindowMinimized)
    elif lifecycle == "deactivate":
        QApplication.sendEvent(host.window(), QEvent(QEvent.WindowDeactivate))
    elif lifecycle == "close":
        host.close()
    else:
        raise AssertionError(lifecycle)
    QApplication.processEvents()
    qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=1000)
    assert controller._collapse_timer.isActive() is False
    assert controller._app_filter_installed is False
    assert panel.parent() is not overlay


def test_hide_during_hover_delay_does_not_peek(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _post(strip, QEvent.Enter)
    assert controller.state == PanelState.HIDDEN
    strip.parent().hide()
    qtbot.wait(400)
    assert controller.state == PanelState.HIDDEN
    assert controller._app_filter_installed is False


def test_destroy_removes_the_application_filter(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side, managed=False,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    assert controller._app_filter_installed is True
    host = strip.parent()
    host.deleteLater()
    qtbot.waitUntil(lambda: sip.isdeleted(host), timeout=1000)
    QApplication.sendEvent(QApplication.instance(), QEvent(QEvent.User))
    QApplication.processEvents()


def test_strip_click_pins_and_does_not_autohide(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    QTest.mouseClick(strip, Qt.LeftButton)
    assert controller.state == PanelState.PINNED
    assert controller._app_filter_installed is False
    assert controller._collapse_timer.isActive() is False
    _post(strip, QEvent.Leave)
    qtbot.wait(800)
    assert controller.state == PanelState.PINNED


def test_toolbar_click_from_peek_pins(qtbot, side):
    controller, splitter, _panel, strip, _overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    QTest.mouseClick(toggle.button, Qt.LeftButton)
    assert controller.state == PanelState.PINNED
    assert controller._collapse_timer.isActive() is False
    _park_outside(strip.parent(), toggle.button)
    _post(strip, QEvent.Leave)
    qtbot.wait(800)
    assert controller.state == PanelState.PINNED


def test_owned_modal_finishes_then_collapses(qtbot, side):
    controller, splitter, panel, strip, overlay, toggle, _marks, _index = _wire(
        qtbot, side,
    )
    _collapse("toolbar-click", controller, splitter, toggle, _index)
    _peek(qtbot, controller, strip)
    dialog = QDialog(panel)
    dialog.setModal(True)
    dialog.setWindowModality(Qt.ApplicationModal)
    finished = []
    dialog.finished.connect(finished.append)
    try:
        dialog.show()
        QApplication.processEvents()
        assert controller.state == PanelState.PEEK
        assert panel.parent() is overlay
        _park_outside(strip.parent(), toggle.button)
        _post(strip, QEvent.Leave)
        qtbot.wait(800)
        assert controller.state == PanelState.PEEK
        assert panel.parent() is overlay
        dialog.done(QDialog.Accepted)
        QApplication.processEvents()
        qtbot.wait(30)
        assert finished == [QDialog.Accepted]
        _park_outside(strip.parent(), toggle.button)
        qtbot.wait(30)
        assert controller.state == PanelState.PEEK
        assert controller._collapse_timer.isActive() is True
        qtbot.waitUntil(lambda: controller.state == PanelState.HIDDEN, timeout=2000)
    finally:
        if not sip.isdeleted(dialog):
            dialog.close()


def _open_transient(kind, panel, button, edit):
    if kind == "menu":
        menu = QMenu(button)
        menu.addAction("keep")
        menu.popup(QPoint(24, 24))
        QApplication.processEvents()
        assert QApplication.activePopupWidget() is menu
        return menu
    if kind == "completer":
        completer = QCompleter(["alpha", "alpine"], edit)
        edit.setCompleter(completer)
        edit.setFocus(Qt.OtherFocusReason)
        edit.setText("al")
        completer.setCompletionPrefix("al")
        completer.complete()
        QApplication.processEvents()
        popup = completer.popup()
        assert popup.isVisible() is True
        return popup
    if kind == "combo":
        combo = QComboBox(panel)
        combo.addItems(["red", "blue"])
        combo.show()
        QApplication.processEvents()
        combo.showPopup()
        QApplication.processEvents()
        popup = QApplication.activePopupWidget()
        assert popup is not None and popup is not combo
        popup._combo_owner = combo
        return popup
    if kind == "dialog":
        dialog = QDialog(panel)
        dialog.setModal(True)
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.show()
        QApplication.processEvents()
        assert QApplication.activeModalWidget() is dialog
        return dialog
    raise AssertionError(kind)


def _close_transient(widget):
    if widget is None or sip.isdeleted(widget):
        return
    combo = getattr(widget, "_combo_owner", None)
    if combo is not None and not sip.isdeleted(combo):
        combo.hidePopup()
    if isinstance(widget, QDialog):
        if widget.isVisible():
            widget.done(QDialog.Rejected)
        return
    if not sip.isdeleted(widget):
        widget.close()


def pytest_generate_tests(metafunc):
    names = set(metafunc.fixturenames)
    if "side" in names and "entry" in names:
        metafunc.parametrize(
            "side,entry",
            [
                (Side.RIGHT, "toolbar-click"),
                (Side.RIGHT, "splitter-drag"),
                (Side.LEFT, "toolbar-click"),
                (Side.LEFT, "splitter-drag"),
            ],
            ids=[
                "right-toolbar-click",
                "right-splitter-drag",
                "left-toolbar-click",
                "left-splitter-drag",
            ],
        )
    elif "side" in names:
        metafunc.parametrize("side", [Side.LEFT, Side.RIGHT], ids=["left", "right"])
    if "transient_kind" in names:
        metafunc.parametrize(
            "transient_kind", ["menu", "completer", "combo", "dialog"],
        )
    if "lifecycle" in names:
        metafunc.parametrize(
            "lifecycle", ["hide", "minimize", "deactivate", "close"],
        )


# --- Real MainWindow inspector, peeked through the production controller ---

_ANALYSIS_WINDOWS = (
    ("fft", "fft_ctx", "combo_win", "_fft_section", "hamming"),
    ("fft_time", "fft_time_ctx", "combo_win", "_tf_section", "blackman"),
    ("order", "order_ctx", "combo_win", "_order_section", "bartlett"),
    ("frf", "frf_ctx", "combo_window", None, "hamming"),
)


def _synthetic_recording(tmp_path):
    """CSV whose time axis is an explicit column. The test does not set fs."""
    import numpy as np
    import pandas as pd

    time_s = np.linspace(0.0, 1.2, 1200)
    frame = pd.DataFrame({
        "time": time_s,
        "torque": np.sin(2.0 * np.pi * 8.0 * time_s),
    })
    path = tmp_path / "peek_torque.csv"
    frame.to_csv(path, index=False)
    return path, time_s


def _boot_main(qtbot, tmp_path):
    import numpy as np

    from mf4_analyzer.ui.main_window import MainWindow

    path, time_s = _synthetic_recording(tmp_path)
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1500, 720)
    win.move(0, 0)
    win.show()
    qtbot.waitExposed(win)
    win._load_one(str(path))
    assert len(win.files) == 1
    fd = next(iter(win.files.values()))
    assert len(fd.time_array) == len(time_s)
    np.testing.assert_allclose(fd.time_array[0], time_s[0])
    np.testing.assert_allclose(fd.time_array[-1], time_s[-1])
    assert "torque" in fd.get_signal_channels()
    return win


def _reject_compute(monkeypatch, win):
    def reject(name):
        def _call(*_args, **_kwargs):
            raise AssertionError(name + " ran without a compute click")
        return _call

    for name in ("do_fft", "do_fft_time", "do_order_time", "do_frf"):
        monkeypatch.setattr(win, name, reject(name))


def _hide_pinned_right(win):
    ctrl = win._panel_ctrl_right
    assert ctrl.state == PanelState.PINNED
    splitter = win.splitter
    sizes = list(splitter.sizes())
    splitter.setSizes([sizes[0], sizes[1] + sizes[2], 0])
    ctrl.on_splitter_moved()
    QApplication.processEvents()
    assert ctrl.state == PanelState.HIDDEN


def _peek_right(qtbot, win):
    ctrl = win._panel_ctrl_right
    assert ctrl.state == PanelState.HIDDEN
    _post(win._strip_right, QEvent.Enter)
    qtbot.waitUntil(lambda: ctrl.state == PanelState.PEEK, timeout=1500)
    assert win.inspector.isVisible()
    assert win.inspector.parent() is win._overlay_right
    return ctrl


def _leave_peek(qtbot, win):
    ctrl = win._panel_ctrl_right
    assert ctrl.state == PanelState.PEEK
    win.move(0, 0)
    QApplication.processEvents()
    QCursor.setPos(420, 280)
    QApplication.processEvents()
    _post(win._overlay_right, QEvent.Leave)
    _post(win._strip_right, QEvent.Leave)
    qtbot.waitUntil(lambda: ctrl.state == PanelState.HIDDEN, timeout=2500)


def _ensure_right_hidden(qtbot, win):
    state = win._panel_ctrl_right.state
    if state == PanelState.PINNED:
        _hide_pinned_right(win)
    elif state == PanelState.PEEK:
        _leave_peek(qtbot, win)
    assert win._panel_ctrl_right.state == PanelState.HIDDEN


def _enter_mode(win, mode):
    win.toolbar._set_mode(mode)
    QApplication.processEvents()
    assert win.chart_stack.current_mode() == mode
    assert win.inspector.current_mode() == mode
    if mode in win.analysis_managers:
        win._attach_files_to_active_context(list(win.files))
        QApplication.processEvents()


def _expand_param_section(section):
    if section is None or section.is_expanded():
        return
    section.btn_collapser.click()
    QApplication.processEvents()
    assert section.is_expanded()


def _choose_enabled_text(widget, text):
    assert widget.isEnabled()
    assert widget.isVisible()
    widget.setCurrentText(text)
    QApplication.processEvents()
    assert widget.currentText() == text


def _focused_analysis_state(win, section):
    return win._analysis_state_for_dispatch(section)


def test_right_peek_operates_enabled_controls_in_five_modes(qtbot, tmp_path, monkeypatch):
    """Time, spectrum, spectrogram, order, and FRF keep an enabled edit."""
    win = _boot_main(qtbot, tmp_path)
    _reject_compute(monkeypatch, win)
    _hide_pinned_right(win)

    _ensure_right_hidden(qtbot, win)
    _peek_right(qtbot, win)
    top = win.inspector.top
    # 全时段 leaves the start/end editors read-only; that is not a miss.
    assert top.combo_range.currentText() == "全时段"
    assert top.spin_start.isReadOnly()
    assert top.spin_end.isReadOnly()
    specified = top.choice_range.buttons()[1]
    assert specified.isEnabled() and specified.isVisible()
    specified.click()
    QApplication.processEvents()
    assert top.combo_range.currentText() == "指定范围"
    assert top.range_enabled() is True
    _leave_peek(qtbot, win)
    _peek_right(qtbot, win)
    assert top.combo_range.currentText() == "指定范围"
    assert top.range_enabled() is True

    for mode, ctx_name, widget_name, section_name, text in _ANALYSIS_WINDOWS:
        _ensure_right_hidden(qtbot, win)
        _enter_mode(win, mode)
        _peek_right(qtbot, win)
        ctx = getattr(win.inspector, ctx_name)
        if section_name is not None:
            _expand_param_section(getattr(ctx, section_name))
        widget = getattr(ctx, widget_name)
        _choose_enabled_text(widget, text)
        state = _focused_analysis_state(win, mode)
        assert state.params.get("window") == text
        _leave_peek(qtbot, win)
        _peek_right(qtbot, win)
        assert widget.currentText() == text
        assert _focused_analysis_state(win, mode).params.get("window") == text


def _select_torque(combo):
    assert combo.isEnabled() and combo.isVisible()
    for index in range(combo.count()):
        data = combo.itemData(index)
        if data is not None and data[1] == "torque":
            combo.setCurrentIndex(index)
            QApplication.processEvents()
            assert combo.currentData()[1] == "torque"
            return
    raise AssertionError("torque was not offered in the signal combo")


def _commit_db_reference(editor, text):
    assert editor.isEnabled() and editor.isVisible()
    line = editor.lineEdit()
    line.setFocus()
    line.selectAll()
    QTest.keyClicks(line, text)
    QTest.keyClick(editor, Qt.Key_Return)
    QApplication.processEvents()


def _heatmap_view_range(win):
    canvas = win._analysis_page("fft_time").pane_canvas(0)
    return tuple(tuple(span) for span in canvas._plot.vb.viewRange())


def _wheel_inspector(win):
    from PyQt5.QtCore import QPoint, QPointF
    from PyQt5.QtGui import QWheelEvent

    scroll = win.inspector._scroll
    bar = scroll.verticalScrollBar()
    if bar.maximum() <= bar.minimum():
        win.resize(1500, 420)
        QApplication.processEvents()
    assert bar.maximum() > bar.minimum()
    before = bar.value()
    viewport = scroll.viewport()
    pos = QPointF(viewport.rect().center())
    wheel = QWheelEvent(
        pos,
        viewport.mapToGlobal(pos.toPoint()),
        QPoint(0, -80),
        QPoint(0, -120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    assert QApplication.sendEvent(viewport, wheel)
    QApplication.processEvents()
    if bar.value() == before:
        bar.setFocus()
        QTest.keyClick(scroll, Qt.Key_PageDown)
        QApplication.processEvents()
    assert bar.value() != before
    return bar.value()


def test_fft_time_peek_edits_controls_scrolls_and_runs_compute(
    qtbot, tmp_path, monkeypatch
):
    from mf4_analyzer.ui.analysis_result_state import snapshot_request

    win = _boot_main(qtbot, tmp_path)
    calls = []
    real_compute = win.do_fft_time

    def counted(*args, **kwargs):
        calls.append(True)
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(win, "do_fft_time", counted)
    _hide_pinned_right(win)
    _enter_mode(win, "fft_time")
    _peek_right(qtbot, win)
    assert calls == []
    assert not win._analysis_jobs.is_busy("fft_time")

    ctx = win.inspector.fft_time_ctx
    _select_torque(ctx.combo_sig)
    specified = win.inspector.top.choice_range.buttons()[1]
    assert specified.isEnabled()
    specified.click()
    QApplication.processEvents()
    assert win.inspector.top.combo_range.currentText() == "指定范围"
    _expand_param_section(ctx._tf_section)
    _choose_enabled_text(ctx.combo_nfft, "512")
    _choose_enabled_text(ctx.combo_win, "blackman")
    assert ctx.spin_overlap.isEnabled() and ctx.spin_overlap.isVisible()
    ctx.spin_overlap.setValue(60)
    QApplication.processEvents()
    assert ctx.spin_overlap.value() == 60
    scroll = win.inspector._scroll
    scroll.ensureWidgetVisible(ctx.spin_db_ref)
    QApplication.processEvents()
    _commit_db_reference(ctx.spin_db_ref, "0.002")
    assert ctx.db_reference_control.mode() == "manual"
    assert ctx.spin_db_ref.value() == pytest.approx(0.002)
    chart_before = _heatmap_view_range(win)
    scrolled = _wheel_inspector(win)
    assert _heatmap_view_range(win) == chart_before
    assert calls == []

    _leave_peek(qtbot, win)
    _peek_right(qtbot, win)
    assert ctx.combo_sig.currentData()[1] == "torque"
    assert win.inspector.top.combo_range.currentText() == "指定范围"
    assert ctx.combo_nfft.currentText() == "512"
    assert ctx.combo_win.currentText() == "blackman"
    assert ctx.spin_overlap.value() == 60
    assert ctx.spin_db_ref.value() == pytest.approx(0.002)
    assert win.inspector._scroll.verticalScrollBar().value() == scrolled

    # Compute stays on 全时段 so the range-confirm dialog is not part of this path.
    win.inspector.top.choice_range.buttons()[0].click()
    QApplication.processEvents()
    assert win.inspector.top.range_enabled() is False
    assert calls == []
    assert ctx.btn_compute.isEnabled()
    scroll.ensureWidgetVisible(ctx.btn_compute)
    QTest.mouseClick(ctx.btn_compute, Qt.LeftButton)
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=3000)

    def computed():
        state = _focused_analysis_state(win, "fft_time")
        binding = state.panes[0].result_binding
        return binding is not None and bool(binding.keys)

    qtbot.waitUntil(computed, timeout=30000)
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_busy("fft_time"), timeout=5000,
    )
    state = _focused_analysis_state(win, "fft_time")
    pane = state.panes[0]
    request = snapshot_request(state, pane)
    binding = pane.result_binding
    revision = pane.request_revision
    assert binding.stale is False
    _leave_peek(qtbot, win)
    assert snapshot_request(state, pane) == request
    assert pane.result_binding is binding
    assert pane.request_revision == revision
    assert not binding.stale


def test_cross_view_edit_stays_on_the_focused_view(qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.ui.analysis_result_state import snapshot_request

    win = _boot_main(qtbot, tmp_path)
    _reject_compute(monkeypatch, win)
    _hide_pinned_right(win)
    _enter_mode(win, "fft")
    _peek_right(qtbot, win)
    ctx = win.inspector.fft_ctx
    _expand_param_section(ctx._fft_section)
    _choose_enabled_text(ctx.combo_win, "blackman")
    manager = win.analysis_managers["fft"]
    original = manager.get(0)
    assert original.params.get("window") == "blackman"
    original_request = snapshot_request(original, original.panes[0])
    original_binding = original.panes[0].result_binding
    original_revision = original.panes[0].request_revision

    win._on_analysis_new("fft")
    QApplication.processEvents()
    assert manager.active == 1
    assert original.params.get("window") == "blackman"
    assert snapshot_request(original, original.panes[0]) == original_request
    _ensure_right_hidden(qtbot, win)
    _peek_right(qtbot, win)
    _expand_param_section(ctx._fft_section)
    _choose_enabled_text(ctx.combo_win, "hamming")
    focused = _focused_analysis_state(win, "fft")
    assert focused is manager.get(1)
    assert focused.params.get("window") == "hamming"
    assert original.params.get("window") == "blackman"
    assert original.panes[0].request_revision == original_revision
    assert original.panes[0].result_binding is original_binding

    focused_request = snapshot_request(focused, focused.panes[0])
    focused_binding = focused.panes[0].result_binding
    focused_revision = focused.panes[0].request_revision
    _leave_peek(qtbot, win)
    assert snapshot_request(original, original.panes[0]) == original_request
    assert original.panes[0].result_binding is original_binding
    assert original.panes[0].request_revision == original_revision
    assert snapshot_request(focused, focused.panes[0]) == focused_request
    assert focused.panes[0].result_binding is focused_binding
    assert focused.panes[0].request_revision == focused_revision
