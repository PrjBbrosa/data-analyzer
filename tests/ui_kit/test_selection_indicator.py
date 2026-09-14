"""Contracts for the shared selected-background plate helper."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QEvent, QPoint, QRect, QTimer
from PyQt5.QtGui import QColor, QFont, QImage
from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QWidget

from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS
from mf4_analyzer.ui_kit.motion import (
    POLICY_LIGHT,
    POLICY_OFF,
    POLICY_REDUCED,
    selection_easing,
)
from mf4_analyzer.ui_kit.widgets.selection_indicator import (
    SelectionIndicator,
    SelectionIndicatorStyle,
)
from mf4_analyzer.ui_kit.widgets.segmented_choice import SegmentedChoice
from mf4_analyzer.ui_kit import load_stylesheet


_HELPER_SRC = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui_kit"
    / "widgets"
    / "selection_indicator.py"
)


def _style() -> SelectionIndicatorStyle:
    return SelectionIndicatorStyle(
        fill=CONTROL_COLORS["CONTROL_SURFACE_TOP"],
        border=CONTROL_COLORS["CONTROL_SELECT_LINE"],
        disabled_fill=CONTROL_COLORS["CONTROL_DISABLED_BG"],
        disabled_border=CONTROL_COLORS["CONTROL_DISABLED_LINE"],
        radius=5,
    )


@pytest.fixture
def production_stylesheet(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        yield qapp
    finally:
        qapp.setStyleSheet(previous)


def _pixel(image: QImage, x: float, y: float) -> QColor:
    dpr = float(image.devicePixelRatio() or 1.0)
    px = min(max(int(round(x * dpr)), 0), image.width() - 1)
    py = min(max(int(round(y * dpr)), 0), image.height() - 1)
    return QColor(image.pixel(px, py))


def _channel_distance(left: QColor, right: QColor) -> int:
    return max(
        abs(left.red() - right.red()),
        abs(left.green() - right.green()),
        abs(left.blue() - right.blue()),
    )


def _host_plate_corners(host: QWidget, plate: QWidget) -> tuple[QImage, list[QColor]]:
    image = host.grab().toImage()
    origin = plate.mapTo(host, QPoint(0, 0))
    width = max(plate.width() - 1, 0)
    height = max(plate.height() - 1, 0)
    # Extreme corners of the plate widget sit outside the 5–6px radius. The
    # 1px antialiased stroke can tint the bottom/right bounding-box pixels,
    # so parent-surface checks use the top corners plus a 1px inward sample
    # that is still outside the fill.
    points = (
        (origin.x(), origin.y()),
        (origin.x() + width, origin.y()),
        (origin.x() + 1, origin.y() + 1),
        (origin.x() + width - 1, origin.y() + 1),
    )
    return image, [_pixel(image, x, y) for x, y in points]


def _mapped_rect(host: QWidget, button: QPushButton) -> QRect:
    return QRect(button.mapTo(host, QPoint(0, 0)), button.size())


def _qt_interpolate_rect(start: QRect, end: QRect, progress: float) -> QRect:
    def lerp(start_value: int, end_value: int) -> int:
        return int(start_value + (end_value - start_value) * progress)

    return QRect(
        lerp(start.x(), end.x()),
        lerp(start.y(), end.y()),
        lerp(start.width(), end.width()),
        lerp(start.height(), end.height()),
    )


def _naive_equal_split(host: QWidget, count: int, index: int, height: int) -> QRect:
    width = host.width() // count
    return QRect(width * index, 0, width, height)


def _make_host(qtbot, qapp, widths: tuple[int, ...]) -> tuple[QWidget, list[QPushButton]]:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    buttons: list[QPushButton] = []
    for index, width in enumerate(widths):
        button = QPushButton(f"B{index}" + ("X" * (width // 12)), host)
        button.setCheckable(True)
        button.setChecked(False)
        button.setFixedWidth(width)
        button.setFixedHeight(24)
        layout.addWidget(button)
        buttons.append(button)
    host.setFixedSize(sum(widths), 24)
    qtbot.addWidget(host)
    host.show()
    qapp.processEvents()
    return host, buttons


def _make_indicator(
    host: QWidget,
    buttons: list[QPushButton],
    *,
    duration_name: str = "selection_control",
) -> SelectionIndicator:
    return SelectionIndicator(
        host,
        buttons=buttons,
        duration_name=duration_name,
        style=_style(),
    )


def test_style_is_frozen_strings_and_int():
    style = _style()
    assert style.fill == CONTROL_COLORS["CONTROL_SURFACE_TOP"]
    assert style.border == CONTROL_COLORS["CONTROL_SELECT_LINE"]
    assert style.disabled_fill == CONTROL_COLORS["CONTROL_DISABLED_BG"]
    assert style.disabled_border == CONTROL_COLORS["CONTROL_DISABLED_LINE"]
    assert style.radius == 5
    with pytest.raises(Exception):
        style.fill = "#000000"


@pytest.mark.parametrize(
    "widths",
    [
        (40, 90),
        (40, 80, 120),
        (30, 50, 70, 90, 110),
    ],
)
def test_rest_geometry_matches_mapped_unequal_buttons(qtbot, qapp, widths):
    host, buttons = _make_host(qtbot, qapp, widths)
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)

    for index, button in enumerate(buttons):
        indicator.follow(button, animate=False)
        plate = indicator._plate
        mapped = _mapped_rect(host, button)
        assert plate is not None
        assert not plate.isHidden()
        assert plate.geometry() == mapped
        assert QRect(indicator.driver().current()) == mapped
        assert not indicator.driver().is_active()
        naive = _naive_equal_split(host, len(buttons), index, button.height())
        if mapped != naive:
            assert plate.geometry() != naive

    if len(buttons) >= 3:
        middle = buttons[len(buttons) // 2]
        indicator.follow(middle, animate=False)
        half = QRect(
            host.width() // 2 - middle.width() // 2,
            0,
            middle.width(),
            middle.height(),
        )
        assert indicator._plate.geometry() == _mapped_rect(host, middle)
        assert indicator._plate.geometry() != half
        assert middle.x() != host.width() // 2


def test_follow_none_hides_and_stops(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80, 120))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[1], animate=True)
    assert indicator.driver() is not None
    assert indicator.driver().is_active()

    indicator.follow(None)
    assert indicator._plate is None or indicator._plate.isHidden()
    assert indicator.driver() is None or not indicator.driver().is_active()
    indicator.follow(None)
    indicator.snap_to_selection()
    assert indicator._plate is None or indicator._plate.isHidden()


def test_same_target_does_not_restart(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (50, 90))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    driver = indicator.driver()
    generation = driver.generation()
    indicator.follow(buttons[0], animate=True)
    assert driver.generation() == generation
    assert not driver.is_active()
    indicator.follow(buttons[0], animate=False)
    assert driver.generation() == generation
    assert not driver.is_active()


@pytest.mark.parametrize(
    "duration_name, expected_ms",
    [
        ("selection_control", 300),
        ("selection_navigation", 320),
    ],
)
def test_light_follow_interpolates_rect_and_lands_exactly(
    qtbot, qapp, duration_name, expected_ms,
):
    host, buttons = _make_host(qtbot, qapp, (40, 80, 120))
    indicator = _make_indicator(host, buttons, duration_name=duration_name)
    indicator.set_motion_policy(POLICY_LIGHT)
    start_button, end_button = buttons[0], buttons[1]
    indicator.follow(start_button, animate=False)
    start = _mapped_rect(host, start_button)
    end = _mapped_rect(host, end_button)
    assert indicator._plate.geometry() == start

    indicator.follow(end_button, animate=True)
    driver = indicator.driver()
    clock = driver.clock()
    assert driver.is_active()
    assert clock.duration() == expected_ms
    used = clock.easingCurve()
    assert used.valueForProgress(0.25) == pytest.approx(0.735, abs=0.005)
    assert used.valueForProgress(0.50) == pytest.approx(0.937, abs=0.005)

    clock.setCurrentTime(0)
    assert QRect(driver.current()) == start
    assert indicator._plate.geometry() == start

    clock.setCurrentTime(expected_ms // 4)
    expected_25 = _qt_interpolate_rect(
        start, end, selection_easing().valueForProgress(0.25)
    )
    assert QRect(driver.current()) == expected_25
    assert indicator._plate.geometry() == expected_25
    assert expected_25 != start
    assert expected_25 != end

    clock.setCurrentTime(expected_ms // 2)
    expected_50 = _qt_interpolate_rect(
        start, end, selection_easing().valueForProgress(0.50)
    )
    assert QRect(driver.current()) == expected_50
    assert indicator._plate.geometry() == expected_50
    assert expected_50.x() >= expected_25.x()

    clock.setCurrentTime(expected_ms)
    assert QRect(driver.current()) == end
    assert indicator._plate.geometry() == end
    assert not driver.is_active()
    assert clock.state() == clock.Stopped


def test_animate_false_snaps_while_visible(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 90, 70))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[2], animate=False)
    driver = indicator.driver()
    assert not driver.is_active()
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[2])
    assert QRect(driver.current()) == _mapped_rect(host, buttons[2])


@pytest.mark.parametrize("policy", (POLICY_OFF, POLICY_REDUCED, None))
def test_off_and_reduced_have_no_active_driver(qtbot, qapp, policy):
    host, buttons = _make_host(qtbot, qapp, (40, 80))
    indicator = _make_indicator(host, buttons)
    if policy is not None:
        indicator.set_motion_policy(policy)
    indicator.follow(buttons[1], animate=True)
    assert indicator.driver() is None or not indicator.driver().is_active()
    assert indicator._plate is None or indicator._plate.isHidden()


def test_ancestor_and_individual_disable_use_disabled_chrome(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (60, 100, 80))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    target = buttons[1]
    indicator.follow(target, animate=False)
    plate = indicator._plate
    assert indicator._effective_chrome() == (_style().fill, _style().border)
    image = plate.grab().toImage()
    center = QColor(image.pixel(plate.width() // 2, plate.height() // 2)).name()
    assert center == QColor(_style().fill).name()

    target.setEnabled(False)
    qapp.processEvents()
    plate.update()
    plate.repaint()
    assert host.isEnabled()
    assert not target.isEnabled()
    assert indicator._effective_chrome() == (
        _style().disabled_fill,
        _style().disabled_border,
    )
    disabled_image = plate.grab().toImage()
    disabled_center = QColor(
        disabled_image.pixel(plate.width() // 2, plate.height() // 2)
    ).name()
    assert disabled_center == QColor(_style().disabled_fill).name()
    assert disabled_center != QColor(_style().fill).name()
    assert not indicator.driver().is_active()

    target.setEnabled(True)
    host.setEnabled(False)
    qapp.processEvents()
    plate.update()
    plate.repaint()
    assert not target.isEnabled()
    assert indicator._effective_chrome() == (
        _style().disabled_fill,
        _style().disabled_border,
    )
    ancestor_image = plate.grab().toImage()
    ancestor_center = QColor(
        ancestor_image.pixel(plate.width() // 2, plate.height() // 2)
    ).name()
    assert ancestor_center == QColor(_style().disabled_fill).name()


def test_hide_show_target_snaps_without_replay(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80, 120))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[1], animate=True)
    driver = indicator.driver()
    driver.clock().setCurrentTime(75)
    assert driver.is_active()
    mid = QRect(driver.current())
    assert mid != _mapped_rect(host, buttons[1])

    buttons[1].hide()
    qapp.processEvents()
    assert not driver.is_active()
    assert indicator._plate is None or indicator._plate.isHidden()

    buttons[1].show()
    qapp.processEvents()
    assert not driver.is_active()
    assert not indicator._plate.isHidden()
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[1])
    assert QRect(driver.current()) == _mapped_rect(host, buttons[1])


def test_resize_and_font_snap_and_leave_driver_inactive(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80, 120))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[2], animate=True)
    driver = indicator.driver()
    driver.clock().setCurrentTime(75)
    assert driver.is_active()

    buttons[2].setFixedWidth(160)
    host.setFixedWidth(40 + 80 + 160)
    qapp.processEvents()
    assert not driver.is_active()
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[2])

    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[1], animate=True)
    driver.clock().setCurrentTime(60)
    assert driver.is_active()
    font = QFont(host.font())
    font.setPointSize(max(font.pointSize(), 12) + 6)
    host.setFont(font)
    qapp.processEvents()
    assert not driver.is_active()
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[1])


def test_delete_later_host_does_not_callback_into_deleted_objects(qapp):
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    buttons = []
    for index in range(2):
        button = QPushButton(f"B{index}", host)
        button.setFixedSize(60, 24)
        layout.addWidget(button)
        buttons.append(button)
    host.setFixedSize(120, 24)
    host.show()
    qapp.processEvents()
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[1], animate=True)
    plate = indicator._plate
    driver = indicator.driver()
    assert plate is not None and driver is not None
    assert driver.is_active()

    host.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert sip.isdeleted(host)
    assert sip.isdeleted(indicator)
    assert sip.isdeleted(plate)
    assert sip.isdeleted(driver)
    assert all(sip.isdeleted(button) for button in buttons)


def test_delete_later_target_stops_without_using_deleted_wrapper(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (50, 70, 90))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    target = buttons[1]
    indicator.follow(buttons[0], animate=False)
    indicator.follow(target, animate=True)
    driver = indicator.driver()
    assert driver.is_active()

    target.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.processEvents()
    assert sip.isdeleted(target)
    assert not sip.isdeleted(host)
    assert not sip.isdeleted(indicator)
    assert driver is None or sip.isdeleted(driver) or not driver.is_active()
    indicator.snap_to_selection()
    indicator.follow(None)
    indicator.follow(buttons[0], animate=False)
    assert not sip.isdeleted(indicator)
    assert indicator.driver() is None or not indicator.driver().is_active()
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[0])


def test_idle_driver_inactive_after_snap_and_has_no_second_timer(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[1], animate=False)
    driver = indicator.driver()
    assert driver is not None
    assert not driver.is_active()
    assert driver.clock().state() == driver.clock().Stopped
    assert host.findChildren(QTimer) == []
    assert indicator.findChildren(QTimer) == []


def test_helper_does_not_write_checked_state(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80, 50))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    assert all(not button.isChecked() for button in buttons)
    indicator.follow(buttons[2], animate=True)
    indicator.follow(buttons[0], animate=False)
    indicator.snap_to_selection()
    assert all(not button.isChecked() for button in buttons)


def test_helper_source_does_not_own_business_state_or_import_ui():
    source = _HELPER_SRC.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_HELPER_SRC))
    attrs = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "setChecked" not in attrs
    assert "isChecked" not in attrs
    assert "clicked" not in attrs
    assert "currentIndex" not in attrs
    assert "setCurrentIndex" not in attrs
    assert "QButtonGroup" not in names
    assert "QComboBox" not in names
    assert not any(
        name == "mf4_analyzer.ui" or name.startswith("mf4_analyzer.ui.")
        for name in imported
    )
    assert "MainWindow" not in names


def test_illegal_targets_hide_and_do_not_go(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    stray_host = QWidget()
    qtbot.addWidget(stray_host)
    stray = QPushButton("stray", stray_host)
    stray.show()
    qapp.processEvents()

    indicator.follow(stray, animate=True)
    assert indicator.driver() is None or not indicator.driver().is_active()
    assert indicator._plate is None or indicator._plate.isHidden()

    buttons[1].setFixedSize(0, 0)
    qapp.processEvents()
    indicator.follow(buttons[1], animate=True)
    assert indicator.driver() is None or not indicator.driver().is_active()
    assert indicator._plate is None or indicator._plate.isHidden()


def test_event_filter_does_not_consume_mouse_or_key(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    assert indicator.eventFilter(host, QEvent(QEvent.MouseButtonPress)) is False
    assert indicator.eventFilter(buttons[0], QEvent(QEvent.KeyPress)) is False


def test_interrupt_continues_from_displayed_rect(qtbot, qapp):
    host, buttons = _make_host(qtbot, qapp, (40, 80, 120))
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    indicator.follow(buttons[2], animate=True)
    driver = indicator.driver()
    driver.clock().setCurrentTime(75)
    mid = QRect(driver.current())
    assert mid not in (
        _mapped_rect(host, buttons[0]),
        _mapped_rect(host, buttons[2]),
    )
    indicator.follow(buttons[0], animate=True)
    assert driver.is_active()
    assert QRect(driver.clock().startValue()) == mid
    assert QRect(driver.target()) == _mapped_rect(host, buttons[0])
    driver.clock().setCurrentTime(300)
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[0])
    assert not driver.is_active()


def test_optional_style_fields_keep_the_five_argument_constructor():
    style = SelectionIndicatorStyle(
        fill="#FFFFFF",
        border="#CDD8E8",
        disabled_fill="#F3F5F8",
        disabled_border="#E2E7EE",
        radius=5,
    )
    assert style.fill_bottom is None
    assert style.hover_fill is None
    assert style.inset == (0, 0, 0, 0)
    assert style.compact_inset is None


def _assert_corners_match(host: QWidget, plate: QWidget, expected: QColor, *, tol: int = 18):
    _image, corners = _host_plate_corners(host, plate)
    white = QColor(CONTROL_COLORS["CONTROL_SURFACE_TOP"])
    for corner in corners:
        assert _channel_distance(corner, expected) <= tol, (
            corner.name(), expected.name(), [item.name() for item in corners]
        )
        if expected.name() != white.name():
            assert _channel_distance(corner, expected) < _channel_distance(corner, white), (
                corner.name(), expected.name()
            )


def test_production_qss_plate_corners_keep_track_and_tinted_parents(
    qtbot, qapp, production_stylesheet,
):
    from PyQt5.QtWidgets import QComboBox

    choice = SegmentedChoice()
    combo = QComboBox()
    combo.addItem("左", "left")
    combo.addItem("右", "right")
    choice.bind(combo)
    choice.set_motion_policy(POLICY_LIGHT)
    choice.resize(260, 32)
    qtbot.addWidget(choice)
    choice.show()
    production_stylesheet.processEvents()
    plate = choice._selection_pill
    assert plate is not None
    _assert_corners_match(choice, plate, QColor(CONTROL_COLORS["CONTROL_TRACK"]))

    tint = QColor("#C8E0FF")
    host, buttons = _make_host(qtbot, qapp, (70, 110))
    host.setStyleSheet(f"background-color: {tint.name()};")
    for button in buttons:
        button.setStyleSheet(
            "background-color: transparent; border-width: 0px; border-style: none;"
        )
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    indicator.follow(buttons[0], animate=False)
    production_stylesheet.processEvents()
    host.repaint()
    _assert_corners_match(host, indicator._plate, tint)

    white_host, white_buttons = _make_host(qtbot, qapp, (80, 90))
    white_host.setStyleSheet("background-color: #FFFFFF;")
    for button in white_buttons:
        button.setStyleSheet(
            "background-color: transparent; border-width: 0px; border-style: none;"
        )
    white_indicator = _make_indicator(white_host, white_buttons)
    white_indicator.set_motion_policy(POLICY_LIGHT)
    white_indicator.follow(white_buttons[1], animate=False)
    production_stylesheet.processEvents()
    white_host.repaint()
    _assert_corners_match(
        white_host, white_indicator._plate, QColor("#FFFFFF"),
    )


def test_mid_frame_plate_corners_do_not_leave_a_white_block(
    qtbot, qapp, production_stylesheet,
):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QComboBox

    choice = SegmentedChoice()
    combo = QComboBox()
    combo.addItem("左", "left")
    combo.addItem("右", "right")
    choice.bind(combo)
    choice.set_motion_policy(POLICY_LIGHT)
    choice.resize(260, 32)
    qtbot.addWidget(choice)
    choice.show()
    production_stylesheet.processEvents()
    first, second = choice.buttons()
    driver = choice._motion_driver
    QTest.mouseClick(second, Qt.LeftButton)
    track = QColor(CONTROL_COLORS["CONTROL_TRACK"])
    for fraction in (0.25, 0.50):
        driver.clock().setCurrentTime(int(300 * fraction))
        choice.repaint()
        production_stylesheet.processEvents()
        plate = choice._selection_pill
        assert plate is not None and not plate.isHidden()
        _assert_corners_match(choice, plate, track)
        mid = plate.geometry()
        assert mid != first.geometry()
        assert mid != second.geometry()


def test_available_dpr_samples_plate_corners_on_unequal_and_disabled_buttons(
    qtbot, qapp, production_stylesheet,
):
    host, buttons = _make_host(qtbot, qapp, (40, 90, 70))
    host.setStyleSheet(
        f"background-color: {CONTROL_COLORS['CONTROL_TRACK']};"
    )
    for button in buttons:
        button.setStyleSheet(
            "background-color: transparent; border-width: 0px; border-style: none;"
        )
    indicator = _make_indicator(host, buttons)
    indicator.set_motion_policy(POLICY_LIGHT)
    screen = production_stylesheet.primaryScreen()
    dpr = float(screen.devicePixelRatio()) if screen is not None else 1.0
    assert dpr >= 1.0
    track = QColor(CONTROL_COLORS["CONTROL_TRACK"])
    for button in buttons:
        indicator.follow(button, animate=False)
        production_stylesheet.processEvents()
        host.repaint()
        _assert_corners_match(host, indicator._plate, track)
    buttons[1].setEnabled(False)
    indicator.follow(buttons[1], animate=False)
    production_stylesheet.processEvents()
    host.repaint()
    _assert_corners_match(host, indicator._plate, track)
    indicator.follow(buttons[2], animate=True)
    indicator.follow(buttons[0], animate=True)
    indicator.driver().clock().setCurrentTime(300)
    production_stylesheet.processEvents()
    assert indicator._plate.geometry() == _mapped_rect(host, buttons[0])
    _assert_corners_match(host, indicator._plate, track)
