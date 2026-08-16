"""Rendered and interaction contracts for the shared :class:`PillSwitch`."""
from __future__ import annotations

import inspect

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QRegion
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.widgets.pill_switch import PillSwitch
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS


def _render_at_dpr(widget: PillSwitch, dpr: int) -> QImage:
    """Render the production widget at a logical DPR without screenshot mocks."""
    image = QImage(
        widget.width() * dpr,
        widget.height() * dpr,
        QImage.Format_ARGB32_Premultiplied,
    )
    image.setDevicePixelRatio(float(dpr))
    image.fill(Qt.transparent)
    painter = QPainter(image)
    # DrawChildren only: the default DrawWindowBackground fills the logical
    # rect with the app QWidget background (white under production QSS),
    # which at dpr=2 leaks past the 1px track stroke at x=0 and is then
    # counted as the white knob.
    widget.render(painter, QPoint(), QRegion(), QWidget.DrawChildren)
    painter.end()
    return image


def _logical_pixel(image: QImage, dpr: int, x: int, y: int) -> QColor:
    return image.pixelColor(x * dpr, y * dpr)


def _distance(actual: QColor, expected: QColor) -> int:
    return sum(
        abs(getattr(actual, channel)() - getattr(expected, channel)())
        for channel in ("red", "green", "blue")
    )


def _knob_center_x(image: QImage, dpr: int) -> float:
    """Recover the white knob centre from the real rendered centreline."""
    bright_x = [
        x
        for x in range(44)
        if min(
            _logical_pixel(image, dpr, x, 12).red(),
            _logical_pixel(image, dpr, x, 12).green(),
            _logical_pixel(image, dpr, x, 12).blue(),
        ) >= 253
    ]
    assert bright_x, "the white knob must remain visibly distinct from its track"
    return (min(bright_x) + max(bright_x)) / 2.0


@pytest.mark.parametrize("checked, expected_knob_x", [(False, 11.0), (True, 33.0)])
@pytest.mark.parametrize("dpr", [1, 2])
def test_pill_switch_keeps_44x24_geometry_and_centered_knob_at_each_dpr(
    qtbot, checked, expected_knob_x, dpr
):
    switch = PillSwitch()
    qtbot.addWidget(switch)
    switch.setChecked(checked)

    assert switch.sizeHint().width() == 44
    assert switch.sizeHint().height() == 24
    assert switch.minimumSize().width() == 44
    assert switch.minimumSize().height() == 24
    assert switch.maximumSize().width() == 44
    assert switch.maximumSize().height() == 24

    image = _render_at_dpr(switch, dpr)
    assert image.devicePixelRatioF() == float(dpr)
    assert _knob_center_x(image, dpr) == pytest.approx(expected_knob_x, abs=0.5)


@pytest.mark.parametrize("checked", [False, True])
def test_pill_switch_off_and_on_tracks_use_the_shared_control_palette(qtbot, checked):
    switch = PillSwitch()
    qtbot.addWidget(switch)
    switch.setChecked(checked)

    image = _render_at_dpr(switch, 1)
    track_top = _logical_pixel(image, 1, 22, 5)
    track_bottom = _logical_pixel(image, 1, 22, 19)
    border = _logical_pixel(image, 1, 22, 2)

    if checked:
        assert _distance(track_top, QColor(CONTROL_COLORS["CONTROL_ACCENT_HI"])) < 42
        assert _distance(track_bottom, QColor(CONTROL_COLORS["CONTROL_ACCENT"])) < 42
        # The 1px antialiased rounded edge blends with the transparent render
        # target, so allow a small coverage tolerance at this exact boundary.
        assert _distance(border, QColor(CONTROL_COLORS["CONTROL_ACCENT_BORDER"])) < 64
    else:
        # The off track deliberately remains cold-grey rather than becoming
        # a second weak blue action.  Its boundary remains visible.
        assert track_top.saturation() < 35
        assert track_bottom.saturation() < 35
        assert _distance(border, track_top) > 15


@pytest.mark.parametrize("checked", [False, True])
def test_pill_switch_hover_and_pressed_change_ink_not_geometry(qtbot, qapp, checked):
    switch = PillSwitch()
    qtbot.addWidget(switch)
    switch.setChecked(checked)
    switch.move(80, 80)
    switch.show()
    qapp.processEvents()
    # A session-wide QApplication can retain the previous test's mouse
    # position; explicitly leave the widget before recording its idle ink.
    QTest.mouseMove(switch, QPoint(100, 100))
    qapp.processEvents()

    idle = _render_at_dpr(switch, 1)
    baseline_geometry = switch.geometry()
    baseline_hint = switch.sizeHint()

    QTest.mouseMove(switch, QPoint(22, 12))
    qapp.processEvents()
    hover = _render_at_dpr(switch, 1)

    QTest.mousePress(switch, Qt.LeftButton, Qt.NoModifier, QPoint(22, 12))
    qapp.processEvents()
    pressed = _render_at_dpr(switch, 1)

    assert switch.geometry() == baseline_geometry
    assert switch.sizeHint() == baseline_hint
    assert _knob_center_x(hover, 1) == _knob_center_x(idle, 1)
    assert _knob_center_x(pressed, 1) == _knob_center_x(idle, 1)
    assert _distance(_logical_pixel(idle, 1, 22, 12), _logical_pixel(hover, 1, 22, 12)) > 5
    assert _distance(_logical_pixel(hover, 1, 22, 12), _logical_pixel(pressed, 1, 22, 12)) > 5

    QTest.mouseRelease(switch, Qt.LeftButton, Qt.NoModifier, QPoint(22, 12))


@pytest.mark.parametrize("checked", [False, True])
def test_pill_switch_disabled_track_border_and_knob_remain_distinct(qtbot, checked):
    switch = PillSwitch()
    qtbot.addWidget(switch)
    switch.setChecked(checked)
    switch.setEnabled(False)

    image = _render_at_dpr(switch, 1)
    track = _logical_pixel(image, 1, 22, 12)
    border = _logical_pixel(image, 1, 22, 2)
    knob_x = 33 if checked else 11
    knob = _logical_pixel(image, 1, knob_x, 12)

    assert track.saturation() < 20
    assert _distance(border, track) > 12
    assert knob.lightness() > track.lightness() + 8


def test_pill_switch_preserves_checkable_click_and_keyboard_contract(qtbot, qapp):
    switch = PillSwitch()
    qtbot.addWidget(switch)
    switch.show()
    qapp.processEvents()

    clicked = QSignalSpy(switch.clicked)
    toggled = QSignalSpy(switch.toggled)

    switch.setChecked(True)
    assert switch.isChecked()
    assert len(clicked) == 0
    assert list(toggled) == [[True]]

    switch.click()
    assert not switch.isChecked()
    assert len(clicked) == 1
    assert list(toggled)[-1] == [False]

    switch.setFocus()
    QTest.keyClick(switch, Qt.Key_Space)
    assert switch.isChecked()
    assert len(clicked) == 2
    assert list(toggled)[-1] == [True]

    switch.setEnabled(False)
    QTest.keyClick(switch, Qt.Key_Space)
    QTest.mouseClick(switch, Qt.LeftButton, Qt.NoModifier, QPoint(22, 12))
    assert switch.isChecked()
    assert len(clicked) == 2
    assert len(toggled) == 3


def test_pill_switch_painter_has_no_timer_or_qsettings_side_effect_path(qtbot):
    import mf4_analyzer.ui.widgets.pill_switch as pill_switch_module

    switch = PillSwitch()
    qtbot.addWidget(switch)
    source = inspect.getsource(pill_switch_module)

    assert "QSettings" not in source
    assert "QTimer" not in source
    assert not [child for child in switch.children() if child.metaObject().className() == "QTimer"]
    assert "CONTROL_COLORS" in source
