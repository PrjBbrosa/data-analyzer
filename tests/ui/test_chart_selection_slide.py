"""C1/C2 selected-background plates on time and frequency chart cards."""
from __future__ import annotations

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QPushButton, QVBoxLayout, QWidget

from mf4_analyzer.ui.chart_stack.cards import (
    FrequencyCursorCard,
    FrfChartCard,
    TimeChartCard,
)
from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, POLICY_REDUCED


def _mapped(host: QWidget, button: QPushButton) -> QRect:
    return QRect(button.mapTo(host, QPoint(0, 0)), button.size())


def _plates(widget: QWidget) -> list[QWidget]:
    return [
        child
        for child in widget.findChildren(QWidget)
        if child.objectName() == "selectionIndicatorPlate"
    ]


def _indicator(card, name: str):
    helper = card._choice_indicators.get(name)
    assert helper is not None
    return helper


def _driver(card, name: str):
    helper = _indicator(card, name)
    driver = helper.driver()
    assert driver is not None
    return driver


def _show_card(qtbot, qapp, card, *, width=1200, height=360):
    card.resize(width, height)
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    qapp.processEvents()
    return card


def _time_card(qtbot, qapp, **kwargs):
    return _show_card(qtbot, qapp, TimeChartCard(TimeDomainCanvasPG()), **kwargs)


def _fft_card(qtbot, qapp, **kwargs):
    return _show_card(
        qtbot,
        qapp,
        FrequencyCursorCard(PgLineCanvas(), annotations=True, chart_mode="fft"),
        **kwargs,
    )


def _frf_card(qtbot, qapp, **kwargs):
    return _show_card(qtbot, qapp, FrfChartCard(PgFrfCanvas()), **kwargs)


def test_time_card_has_two_independent_choice_plates(qtbot, qapp):
    card = _time_card(qtbot, qapp)
    assert card.motion_policy() == POLICY_LIGHT
    plates = _plates(card.toolbar)
    assert len(plates) == 2
    plot = _indicator(card, "plot")
    cursor = _indicator(card, "cursor")
    assert plot is not cursor
    assert plot._host is card.toolbar
    assert cursor._host is card.toolbar
    assert plot._buttons == (card.btn_subplot, card.btn_overlay)
    assert cursor._buttons == (
        card._cursor_buttons["off"],
        card._cursor_buttons["single"],
        card._cursor_buttons["dual"],
    )
    plot_plate = plot._plate
    cursor_plate = cursor._plate
    assert plot_plate is not None and cursor_plate is not None
    assert plot_plate is not cursor_plate
    assert plot_plate.geometry() == _mapped(card.toolbar, card.btn_subplot)
    assert cursor_plate.geometry() == _mapped(card.toolbar, card._cursor_buttons["off"])
    assert plot_plate.geometry() != cursor_plate.geometry()

    plot_driver = _driver(card, "plot")
    cursor_driver = _driver(card, "cursor")
    QTest.mouseClick(card.btn_overlay, Qt.LeftButton)
    assert card.plot_mode() == "overlay"
    assert plot_driver.is_active()
    assert plot_driver.clock().duration() == 300
    assert not cursor_driver.is_active()
    assert cursor_plate.geometry() == _mapped(card.toolbar, card._cursor_buttons["off"])

    plot_driver.clock().setCurrentTime(300)
    QTest.mouseClick(card._cursor_buttons["dual"], Qt.LeftButton)
    assert card.cursor_mode() == "dual"
    assert cursor_driver.is_active()
    assert cursor_driver.clock().duration() == 300
    assert not plot_driver.is_active()
    assert plot_plate.geometry() == _mapped(card.toolbar, card.btn_overlay)


@pytest.mark.parametrize("factory", (_fft_card, _frf_card))
def test_frequency_cards_have_one_cursor_triple_plate(qtbot, qapp, factory):
    card = factory(qtbot, qapp)
    assert card.motion_policy() == POLICY_LIGHT
    plates = _plates(card.toolbar)
    assert len(plates) == 1
    helper = _indicator(card, "cursor")
    assert helper._host is card.toolbar
    assert helper._buttons == (
        card._cursor_buttons["off"],
        card._cursor_buttons["single"],
        card._cursor_buttons["dual"],
    )
    assert helper._plate.geometry() == _mapped(
        card.toolbar, card._cursor_buttons["off"]
    )
    assert "plot" not in card._choice_indicators


def test_user_click_animates_program_setters_snap(qtbot, qapp):
    card = _time_card(qtbot, qapp)
    plot_spy = QSignalSpy(card.plot_mode_changed)
    cursor_spy = QSignalSpy(card.cursor_mode_changed)
    plot_driver = _driver(card, "plot")
    cursor_driver = _driver(card, "cursor")
    plot_plate = _indicator(card, "plot")._plate
    cursor_plate = _indicator(card, "cursor")._plate

    QTest.mouseClick(card.btn_overlay, Qt.LeftButton)
    assert card.plot_mode() == "overlay"
    assert list(plot_spy) == [["overlay"]]
    assert plot_driver.is_active()
    assert plot_driver.clock().duration() == 300
    plot_driver.clock().setCurrentTime(75)
    mid = QRect(plot_driver.current())
    assert card.btn_subplot.x() < mid.x() < card.btn_overlay.x()
    assert plot_plate.geometry() == mid
    plot_driver.clock().setCurrentTime(300)
    assert not plot_driver.is_active()
    assert plot_plate.geometry() == _mapped(card.toolbar, card.btn_overlay)
    assert list(plot_spy) == [["overlay"]]

    card.set_plot_mode("subplot")
    assert card.plot_mode() == "subplot"
    assert list(plot_spy) == [["overlay"], ["subplot"]]
    assert not plot_driver.is_active()
    assert plot_plate.geometry() == _mapped(card.toolbar, card.btn_subplot)

    QTest.mouseClick(card._cursor_buttons["single"], Qt.LeftButton)
    assert card.cursor_mode() == "single"
    assert list(cursor_spy) == [["single"]]
    assert cursor_driver.is_active()
    cursor_driver.clock().setCurrentTime(300)
    assert not cursor_driver.is_active()

    card.set_cursor_mode("dual")
    assert card.cursor_mode() == "dual"
    assert list(cursor_spy) == [["single"], ["dual"]]
    assert not cursor_driver.is_active()
    assert cursor_plate.geometry() == _mapped(
        card.toolbar, card._cursor_buttons["dual"]
    )


def test_reentrant_mode_signal_leaves_indicator_on_effective_choice(qtbot, qapp):
    """A slot may synchronously replace the requested choice while emitting."""
    time = _time_card(qtbot, qapp)
    fft = _fft_card(qtbot, qapp)

    def redirect_plot(mode):
        if mode == "overlay":
            time.set_plot_mode("subplot")

    def redirect_time_cursor(mode):
        if mode == "dual":
            time.set_cursor_mode("off")

    def redirect_frequency_cursor(mode):
        if mode == "dual":
            fft.set_cursor_mode("off")

    time.plot_mode_changed.connect(redirect_plot)
    time.cursor_mode_changed.connect(redirect_time_cursor)
    fft.cursor_mode_changed.connect(redirect_frequency_cursor)

    time._on_plot_mode_clicked("overlay")
    assert time.plot_mode() == "subplot"
    assert _indicator(time, "plot")._target is time.btn_subplot

    time._on_cursor_mode_clicked("dual")
    assert time.cursor_mode() == "off"
    assert _indicator(time, "cursor")._target is time._cursor_buttons["off"]

    fft._on_cursor_mode_clicked("dual")
    assert fft.cursor_mode() == "off"
    assert _indicator(fft, "cursor")._target is fft._cursor_buttons["off"]


def test_frequency_user_click_animates_setters_and_sync_snap(qtbot, qapp):
    card = _fft_card(qtbot, qapp)
    spy = QSignalSpy(card.cursor_mode_changed)
    driver = _driver(card, "cursor")
    plate = _indicator(card, "cursor")._plate
    compute = {"n": 0}
    orig = card.canvas.set_cursor_mode

    def _count(mode):
        compute["n"] += 1
        return orig(mode)

    card.canvas.set_cursor_mode = _count

    QTest.mouseClick(card._cursor_buttons["single"], Qt.LeftButton)
    assert card.cursor_mode() == "single"
    assert card.canvas.cursor_mode() == "single"
    assert list(spy) == [["single"]]
    assert compute["n"] == 1
    assert driver.is_active()
    assert driver.clock().duration() == 300
    driver.clock().setCurrentTime(300)
    assert not driver.is_active()
    assert compute["n"] == 1
    assert list(spy) == [["single"]]

    card.set_cursor_mode("dual")
    assert card.cursor_mode() == "dual"
    assert list(spy) == [["single"], ["dual"]]
    assert compute["n"] == 2
    assert not driver.is_active()
    assert plate.geometry() == _mapped(card.toolbar, card._cursor_buttons["dual"])

    card.sync_frequency_cursor_control()
    assert not driver.is_active()
    assert compute["n"] == 2
    assert list(spy) == [["single"], ["dual"]]


def test_split_focus_target_snaps_without_source_emit(qtbot, qapp):
    source = _fft_card(qtbot, qapp)
    target = _fft_card(qtbot, qapp)
    source.set_frequency_cursor_target_provider(lambda: target)
    source_spy = QSignalSpy(source.cursor_mode_changed)
    target_spy = QSignalSpy(target.cursor_mode_changed)
    source_driver = _driver(source, "cursor")
    target_driver = _driver(target, "cursor")
    source_compute = {"n": 0}
    target_compute = {"n": 0}
    source_orig = source.canvas.set_cursor_mode
    target_orig = target.canvas.set_cursor_mode

    def _count_source(mode):
        source_compute["n"] += 1
        return source_orig(mode)

    def _count_target(mode):
        target_compute["n"] += 1
        return target_orig(mode)

    source.canvas.set_cursor_mode = _count_source
    target.canvas.set_cursor_mode = _count_target

    QTest.mouseClick(source._cursor_buttons["dual"], Qt.LeftButton)

    assert target.cursor_mode() == "dual"
    assert target.canvas.cursor_mode() == "dual"
    assert source.canvas.cursor_mode() == "off"
    assert list(source_spy) == []
    assert list(target_spy) == [["dual"]]
    assert source_compute["n"] == 0
    assert target_compute["n"] == 1
    assert not source_driver.is_active()
    assert not target_driver.is_active()
    assert _indicator(source, "cursor")._plate.geometry() == _mapped(
        source.toolbar, source._cursor_buttons["dual"]
    )
    assert _indicator(target, "cursor")._plate.geometry() == _mapped(
        target.toolbar, target._cursor_buttons["dual"]
    )

    target.set_cursor_mode("single", notify=False)
    source.sync_frequency_cursor_control()
    assert list(source_spy) == []
    assert list(target_spy) == [["dual"]]
    assert not source_driver.is_active()
    assert source._cursor_buttons["single"].isChecked()


def test_focus_target_change_snaps_in_flight_source(qtbot, qapp):
    source = _fft_card(qtbot, qapp)
    target = _fft_card(qtbot, qapp)
    driver = _driver(source, "cursor")
    spy = QSignalSpy(source.cursor_mode_changed)
    QTest.mouseClick(source._cursor_buttons["single"], Qt.LeftButton)
    driver.clock().setCurrentTime(75)
    assert driver.is_active()
    assert list(spy) == [["single"]]

    source.set_frequency_cursor_target_provider(lambda: target)
    assert not driver.is_active()
    assert list(spy) == [["single"]]
    assert source.canvas.cursor_mode() == "single"
    assert source._cursor_buttons["off"].isChecked()
    assert _indicator(source, "cursor")._plate.geometry() == _mapped(
        source.toolbar, source._cursor_buttons["off"]
    )


def test_ctrl_digit_shortcuts_animate_and_hidden_card_does_not_steal(qtbot, qapp):
    holder = QWidget()
    layout = QVBoxLayout(holder)
    time = TimeChartCard(TimeDomainCanvasPG())
    fft = FrequencyCursorCard(PgLineCanvas(), annotations=True, chart_mode="fft")
    layout.addWidget(time)
    layout.addWidget(fft)
    holder.resize(1200, 720)
    qtbot.addWidget(holder)
    holder.show()
    qapp.processEvents()
    fft.hide()
    qapp.processEvents()
    time.setFocus(Qt.OtherFocusReason)

    plot_spy = QSignalSpy(time.plot_mode_changed)
    cursor_spy = QSignalSpy(time.cursor_mode_changed)
    fft_spy = QSignalSpy(fft.cursor_mode_changed)
    plot_driver = _driver(time, "plot")
    cursor_driver = _driver(time, "cursor")

    QTest.keyClick(time, Qt.Key_2, Qt.ControlModifier)
    assert time.plot_mode() == "overlay"
    assert list(plot_spy) == [["overlay"]]
    assert plot_driver.is_active()
    plot_driver.clock().setCurrentTime(300)

    QTest.keyClick(time, Qt.Key_4, Qt.ControlModifier)
    assert time.cursor_mode() == "single"
    assert list(cursor_spy) == [["single"]]
    assert cursor_driver.is_active()
    cursor_driver.clock().setCurrentTime(300)

    QTest.keyClick(time, Qt.Key_5, Qt.ControlModifier)
    assert time.cursor_mode() == "dual"
    QTest.keyClick(time, Qt.Key_3, Qt.ControlModifier)
    assert time.cursor_mode() == "off"
    QTest.keyClick(time, Qt.Key_1, Qt.ControlModifier)
    assert time.plot_mode() == "subplot"

    assert fft.cursor_mode() == "off"
    assert list(fft_spy) == []
    QTest.keyClick(fft, Qt.Key_5, Qt.ControlModifier)
    assert fft.cursor_mode() == "off"
    assert list(fft_spy) == []
    for shortcut in fft._frequency_cursor_shortcuts:
        assert shortcut.parentWidget() is fft
        assert not fft.isVisible()


def test_same_value_noop_and_notify_false(qtbot, qapp):
    time = _time_card(qtbot, qapp)
    fft = _fft_card(qtbot, qapp)
    plot_spy = QSignalSpy(time.plot_mode_changed)
    time_cursor_spy = QSignalSpy(time.cursor_mode_changed)
    fft_spy = QSignalSpy(fft.cursor_mode_changed)
    hints = {"n": 0}
    orig_hint = time._refresh_bottom_hint

    def _hint(*args, **kwargs):
        hints["n"] += 1
        return orig_hint(*args, **kwargs)

    time._refresh_bottom_hint = _hint
    compute = {"n": 0}
    orig_set = fft.canvas.set_cursor_mode

    def _set(mode):
        compute["n"] += 1
        return orig_set(mode)

    fft.canvas.set_cursor_mode = _set

    time.set_plot_mode("subplot")
    time.set_cursor_mode("off")
    assert list(plot_spy) == []
    assert list(time_cursor_spy) == []
    assert hints["n"] == 0
    assert not _driver(time, "plot").is_active()
    assert not _driver(time, "cursor").is_active()

    time.set_plot_mode("overlay")
    assert hints["n"] == 1
    assert list(plot_spy) == [["overlay"]]
    time.set_plot_mode("overlay")
    assert hints["n"] == 1
    assert list(plot_spy) == [["overlay"]]

    fft.set_cursor_mode("single", notify=False)
    assert fft.cursor_mode() == "single"
    assert fft._cursor_buttons["single"].isChecked()
    assert list(fft_spy) == []
    assert compute["n"] == 1
    assert not _driver(fft, "cursor").is_active()
    assert _indicator(fft, "cursor")._plate.geometry() == _mapped(
        fft.toolbar, fft._cursor_buttons["single"]
    )

    fft.set_cursor_mode("single")
    assert list(fft_spy) == []
    QTest.mouseClick(fft._cursor_buttons["single"], Qt.LeftButton)
    assert list(fft_spy) == []
    assert not _driver(fft, "cursor").is_active()


def test_ancestor_disabled_uses_disabled_chrome_and_deletelater_stops(qapp):
    parent = QWidget()
    layout = QVBoxLayout(parent)
    card = TimeChartCard(TimeDomainCanvasPG())
    layout.addWidget(card)
    parent.resize(1200, 360)
    parent.show()
    qapp.processEvents()
    helper = _indicator(card, "plot")
    driver = _driver(card, "plot")
    QTest.mouseClick(card.btn_overlay, Qt.LeftButton)
    driver.clock().setCurrentTime(40)
    assert driver.is_active()

    parent.setEnabled(False)
    qapp.processEvents()
    assert not card.btn_overlay.isEnabled()
    assert helper._effective_chrome() == (
        CONTROL_COLORS["CONTROL_DISABLED_BG"],
        CONTROL_COLORS["CONTROL_DISABLED_LINE"],
    )
    assert not driver.is_active()
    assert card.plot_mode() == "overlay"

    parent.setEnabled(True)
    qapp.processEvents()
    assert helper._effective_chrome() == (
        CONTROL_COLORS["CONTROL_SURFACE_TOP"],
        CONTROL_COLORS["CONTROL_SELECT_LINE"],
    )

    helpers = [item for item in card._choice_indicators.values() if item is not None]
    plates = [item._plate for item in helpers if item._plate is not None]
    drivers = [item.driver() for item in helpers if item.driver() is not None]
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert sip.isdeleted(card)
    assert all(sip.isdeleted(item) for item in helpers)
    assert all(sip.isdeleted(item) for item in plates)
    assert all(sip.isdeleted(item) for item in drivers)


def test_narrow_hidden_and_policy_restore_do_not_relayout_canvas(qtbot, qapp):
    card = _time_card(qtbot, qapp, width=1600, height=400)
    canvas_size = card.canvas.size()
    actions = list(card.toolbar.actions())
    plot_driver = _driver(card, "plot")
    QTest.mouseClick(card.btn_overlay, Qt.LeftButton)
    plot_driver.clock().setCurrentTime(60)
    assert plot_driver.is_active()
    assert card.canvas.size() == canvas_size

    card.resize(520, 400)
    qapp.processEvents()
    assert not plot_driver.is_active()
    assert _indicator(card, "plot")._plate.geometry() == _mapped(
        card.toolbar, card.btn_overlay
    )
    assert list(card.toolbar.actions()) == actions

    overlay_action = card._toolbar_action_for_widget(card.btn_overlay)
    assert overlay_action is not None
    overlay_action.setVisible(False)
    qapp.processEvents()
    assert not card.btn_overlay.isVisible()
    plate = _indicator(card, "plot")._plate
    assert plate is None or plate.isHidden()
    overlay_action.setVisible(True)
    qapp.processEvents()
    assert card.btn_overlay.isVisible()
    assert _indicator(card, "plot")._plate.geometry() == _mapped(
        card.toolbar, card.btn_overlay
    )

    assert "background-color: transparent" in card.toolbar.styleSheet()
    assert "border:" not in card.toolbar.styleSheet().replace("border-color", "")
    card.set_motion_policy(POLICY_OFF)
    assert card.toolbar.styleSheet() == ""
    assert _indicator(card, "plot")._plate is None or _indicator(
        card, "plot"
    )._plate.isHidden()
    card.set_motion_policy(POLICY_REDUCED)
    assert card.toolbar.styleSheet() == ""
    card.set_motion_policy(POLICY_LIGHT)
    assert "background-color: transparent" in card.toolbar.styleSheet()
    assert not _driver(card, "plot").is_active()
    assert card.canvas.width() > 0
