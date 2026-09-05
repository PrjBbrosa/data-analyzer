"""Deterministic contracts for the S01 MotionButton sample."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt5.QtCore import QEvent, QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPalette
from PyQt5.QtTest import QSignalSpy, QTest
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.control_style import CONTROL_COLORS, CONTROL_HEIGHTS, set_control_role
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui_kit.motion import (
    DURATION_MS,
    POLICY_LIGHT,
    POLICY_OFF,
    POLICY_REDUCED,
    duration_ms,
)
from mf4_analyzer.ui_kit.widgets.motion_button import (
    SAMPLE_LABELS,
    MotionButton,
    make_sample_button,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MOTION_BUTTON_SRC = (
    _REPO_ROOT / "mf4_analyzer" / "ui_kit" / "widgets" / "motion_button.py"
)
_ROLES = ("primary", "secondary", "quiet", "icon")


@pytest.fixture
def production_stylesheet(qapp):
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        yield qapp
    finally:
        qapp.setStyleSheet(previous)


def _center(widget: QWidget) -> QPoint:
    return QPoint(widget.width() // 2, widget.height() // 2)


def _send_enter(widget: QWidget) -> None:
    widget.setAttribute(Qt.WA_UnderMouse, True)
    QApplication.sendEvent(widget, QEvent(QEvent.Enter))
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _send_leave(widget: QWidget) -> None:
    widget.setAttribute(Qt.WA_UnderMouse, False)
    QApplication.sendEvent(widget, QEvent(QEvent.Leave))
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _prepare(button: QWidget, *, width: int = 112, height: int = 32) -> QWidget:
    button.resize(width, height)
    button.show()
    QApplication.processEvents()
    return button


def _white_host() -> QWidget:
    host = QWidget()
    host.setAutoFillBackground(True)
    palette = host.palette()
    palette.setColor(QPalette.Window, QColor("#FFFFFF"))
    host.setPalette(palette)
    return host


def _twin_buttons(role: str, *, height: int = 32, width: int = 112, host: QWidget | None = None):
    label = SAMPLE_LABELS[role]
    ref = QPushButton(label, host)
    motion = MotionButton(label, host)
    size = "compact" if role == "icon" else "base"
    set_control_role(ref, role, size=size)
    set_control_role(motion, role, size=size)
    if role == "icon":
        icon = Icons.search()
        ref.setIcon(icon)
        motion.setIcon(icon)
        ref.setIconSize(motion.iconSize())
    _prepare(ref, width=width, height=height)
    _prepare(motion, width=width, height=height)
    if host is not None:
        ref.move(16, 16)
        motion.move(16 + width + 16, 16)
        host.resize(width * 2 + 48, height + 32)
        host.show()
        QApplication.processEvents()
    return ref, motion


def _widget_image(widget: QWidget) -> QImage:
    parent = widget.parentWidget()
    if parent is None:
        return widget.grab().toImage()
    top_left = widget.mapTo(parent, QPoint(0, 0))
    return parent.grab().toImage().copy(top_left.x(), top_left.y(), widget.width(), widget.height())


def _fill_sample(widget: QWidget) -> QColor:
    image = _widget_image(widget)
    x = min(6, max(1, widget.width() // 8))
    y = widget.height() // 2
    return QColor(image.pixel(x, y))


def _color_delta(left: QColor, right: QColor) -> int:
    return max(
        abs(left.red() - right.red()),
        abs(left.green() - right.green()),
        abs(left.blue() - right.blue()),
        abs(left.alpha() - right.alpha()),
    )


def _chrome_estimate(image: QImage) -> QColor:
    return QColor(image.pixel(min(6, image.width() - 2), image.height() // 2))


def _ink_stats(image: QImage, chrome: QColor, *, threshold: int = 28):
    width = image.width()
    height = image.height()
    count = 0
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            color = QColor(image.pixel(x, y))
            if _color_delta(color, chrome) <= threshold:
                continue
            count += 1
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    bbox = QRect() if count == 0 else QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
    return count, bbox


def _assert_render_match(
    reference: QWidget,
    actual: QWidget,
    *,
    edge_px: int = 1,
    edge_slop: int = 0,
    interior_slop: int = 0,
    text_pixel_slop: int | None = None,
) -> None:
    ref_img = _widget_image(reference)
    act_img = _widget_image(actual)
    assert ref_img.size() == act_img.size()
    chrome = _chrome_estimate(ref_img)
    worst_edge = 0
    worst_interior = 0
    worst_ink = 0
    width = ref_img.width()
    height = ref_img.height()
    ink_slop = interior_slop if text_pixel_slop is None else text_pixel_slop
    for y in range(height):
        for x in range(width):
            ref = QColor(ref_img.pixel(x, y))
            act = QColor(act_img.pixel(x, y))
            delta = _color_delta(ref, act)
            on_edge = x < edge_px or y < edge_px or x >= width - edge_px or y >= height - edge_px
            if on_edge:
                worst_edge = max(worst_edge, delta)
                continue
            if _color_delta(ref, chrome) > 28:
                worst_ink = max(worst_ink, delta)
            else:
                worst_interior = max(worst_interior, delta)
    assert worst_interior <= interior_slop
    assert worst_edge <= edge_slop
    assert worst_ink <= ink_slop
    inset = max(edge_px, 4)
    if width > inset * 2 and height > inset * 2:
        ref_inner = ref_img.copy(inset, inset, width - inset * 2, height - inset * 2)
        act_inner = act_img.copy(inset, inset, width - inset * 2, height - inset * 2)
        ref_count, ref_bbox = _ink_stats(ref_inner, chrome)
        act_count, act_bbox = _ink_stats(act_inner, chrome)
        if ref_count:
            assert act_count >= int(ref_count * 0.98)
            assert not act_bbox.isNull()
            assert act_bbox.adjusted(-1, -1, 1, 1).contains(ref_bbox)


def test_default_policy_is_off_and_creates_no_active_animation(qtbot):
    button = MotionButton("确定")
    qtbot.addWidget(button)
    _prepare(button)
    assert button.motion_policy() == POLICY_OFF
    assert not button._hover_driver.is_active()
    assert not button._press_driver.is_active()
    _send_enter(button)
    button.setDown(True)
    button.setDown(False)
    assert not button._hover_driver.is_active()
    assert not button._press_driver.is_active()
    button.set_motion_policy(POLICY_LIGHT)
    button.set_motion_policy(None)
    assert button.motion_policy() == POLICY_OFF
    assert not button._hover_driver.is_active()
    assert not button._press_driver.is_active()


def test_reduced_policy_snaps_without_active_clock(qtbot, production_stylesheet):
    button = make_sample_button("primary")
    qtbot.addWidget(button)
    _prepare(button)
    button.set_motion_policy(POLICY_REDUCED)
    _send_enter(button)
    button.setDown(True)
    assert button._hover_driver.current() == 0.0
    assert button._press_driver.current() == 0.0
    assert not button._hover_driver.is_active()
    assert not button._press_driver.is_active()


@pytest.mark.parametrize("role", _ROLES)
def test_hover_progress_0_25_50_100_and_interrupt(qtbot, production_stylesheet, role):
    edge = 28 if role == "icon" else 32
    width = edge if role == "icon" else 112
    button = make_sample_button(role, icon_edge=edge)
    qtbot.addWidget(button)
    _prepare(button, width=width, height=edge)
    button.set_motion_policy(POLICY_LIGHT)

    _send_enter(button)
    clock = button._hover_driver.clock()
    assert clock.duration() == DURATION_MS["hover_in"]
    assert duration_ms("hover_in", POLICY_LIGHT) == 100

    clock.setCurrentTime(0)
    at_0 = float(button._hover_driver.current())
    fill_0 = _fill_sample(button)
    assert at_0 == pytest.approx(0.0)

    clock.setCurrentTime(25)
    at_25 = float(button._hover_driver.current())
    fill_25 = _fill_sample(button)
    clock.setCurrentTime(50)
    at_50 = float(button._hover_driver.current())
    fill_50 = _fill_sample(button)
    clock.setCurrentTime(100)
    at_100 = float(button._hover_driver.current())
    fill_100 = _fill_sample(button)

    assert 0.0 < at_25 < at_50 < 1.0
    assert at_100 == pytest.approx(1.0)
    assert _color_delta(fill_25, fill_0) > 0 or role == "icon"
    assert _color_delta(fill_50, fill_25) > 0 or _color_delta(fill_100, fill_0) > 0
    assert _color_delta(fill_100, fill_0) > 0

    _send_leave(button)
    button._hover_driver.snap(0.0)
    _send_enter(button)
    button._hover_driver.clock().setCurrentTime(40)
    mid = float(button._hover_driver.current())
    assert mid not in (0.0, 1.0)
    _send_leave(button)
    assert button._hover_driver.target() == 0.0
    assert button._hover_driver.clock().startValue() == pytest.approx(mid)
    assert button._hover_driver.current() == pytest.approx(mid)
    assert button._hover_driver.clock().duration() == DURATION_MS["hover_out"]
    button._hover_driver.clock().setCurrentTime(80)
    assert float(button._hover_driver.current()) == pytest.approx(0.0)


def test_press_is_immediate_and_release_progress_is_manual(qtbot, production_stylesheet):
    button = make_sample_button("secondary")
    qtbot.addWidget(button)
    _prepare(button)
    button.set_motion_policy(POLICY_LIGHT)
    _send_enter(button)
    button._hover_driver.clock().setCurrentTime(100)

    button.setDown(True)
    assert float(button._press_driver.current()) == pytest.approx(1.0)
    assert not button._press_driver.is_active()
    pressed_fill = _fill_sample(button)

    button.setDown(False)
    clock = button._press_driver.clock()
    assert clock.duration() == DURATION_MS["release"]
    clock.setCurrentTime(0)
    assert float(button._press_driver.current()) == pytest.approx(1.0)
    clock.setCurrentTime(20)
    at_25 = float(button._press_driver.current())
    clock.setCurrentTime(40)
    at_50 = float(button._press_driver.current())
    clock.setCurrentTime(80)
    at_100 = float(button._press_driver.current())
    assert 0.0 < at_50 < 1.0
    assert at_25 > at_50
    assert at_100 == pytest.approx(0.0)
    assert _color_delta(_fill_sample(button), pressed_fill) > 0


def test_disabled_stops_motion_and_uses_disabled_chrome(qtbot, production_stylesheet):
    button = make_sample_button("primary")
    qtbot.addWidget(button)
    _prepare(button)
    button.set_motion_policy(POLICY_LIGHT)
    _send_enter(button)
    button._hover_driver.clock().setCurrentTime(50)
    assert button._hover_driver.is_active()

    button.setEnabled(False)
    assert not button._hover_driver.is_active()
    assert not button._press_driver.is_active()
    assert float(button._hover_driver.current()) == pytest.approx(0.0)
    assert float(button._press_driver.current()) == pytest.approx(0.0)
    fill = _fill_sample(button)
    disabled = QColor(CONTROL_COLORS["CONTROL_DISABLED_BG"])
    assert _color_delta(fill, disabled) <= 18


@pytest.mark.parametrize(
    ("role", "width", "height"),
    (
        ("primary", 112, CONTROL_HEIGHTS["base"]),
        ("secondary", 112, CONTROL_HEIGHTS["base"]),
        ("quiet", 112, CONTROL_HEIGHTS["base"]),
        ("icon", 28, 28),
        ("icon", 24, 24),
    ),
)
def test_hit_rect_and_size_hint_stay_fixed(
    qtbot, production_stylesheet, role, width, height
):
    button = make_sample_button(role, icon_edge=height if role == "icon" else None)
    qtbot.addWidget(button)
    _prepare(button, width=width, height=height)
    button.set_motion_policy(POLICY_LIGHT)
    baseline_hint = button.sizeHint()
    baseline_min = button.minimumSizeHint()
    baseline_size = button.size()
    baseline_rect = QRect(button.rect())
    center = _center(button)
    assert button.hitButton(center)

    _send_enter(button)
    button._hover_driver.clock().setCurrentTime(50)
    button.setDown(True)
    button.setDown(False)
    button.setFocus()
    QApplication.sendEvent(button, QEvent(QEvent.FocusIn))
    button.setEnabled(False)
    button.setEnabled(True)

    assert button.sizeHint() == baseline_hint
    assert button.minimumSizeHint() == baseline_min
    assert button.size() == baseline_size
    assert button.rect() == baseline_rect
    assert button.hitButton(center)
    assert not button.hitButton(QPoint(-1, center.y()))


def test_clicked_moment_matches_plain_push_button(qtbot, production_stylesheet):
    ref, motion = _twin_buttons("primary")
    qtbot.addWidget(ref)
    qtbot.addWidget(motion)
    motion.set_motion_policy(POLICY_LIGHT)
    ref_spy = QSignalSpy(ref.clicked)
    motion_spy = QSignalSpy(motion.clicked)

    QTest.mousePress(ref, Qt.LeftButton, pos=_center(ref))
    QTest.mousePress(motion, Qt.LeftButton, pos=_center(motion))
    assert len(ref_spy) == len(motion_spy) == 0

    QTest.mouseRelease(ref, Qt.LeftButton, pos=_center(ref))
    QTest.mouseRelease(motion, Qt.LeftButton, pos=_center(motion))
    assert len(ref_spy) == len(motion_spy) == 1

    QTest.mousePress(ref, Qt.LeftButton, pos=_center(ref))
    QTest.mousePress(motion, Qt.LeftButton, pos=_center(motion))
    QTest.mouseRelease(ref, Qt.LeftButton, pos=QPoint(-24, _center(ref).y()))
    QTest.mouseRelease(motion, Qt.LeftButton, pos=QPoint(-24, _center(motion).y()))
    assert len(ref_spy) == len(motion_spy) == 1


@pytest.mark.parametrize("role", _ROLES)
def test_motion_off_end_state_matches_qpushbutton(
    qtbot, production_stylesheet, role
):
    height = 28 if role == "icon" else 32
    width = 28 if role == "icon" else 112
    ref, motion = _twin_buttons(role, height=height, width=width)
    qtbot.addWidget(ref)
    qtbot.addWidget(motion)
    assert motion.motion_policy() == POLICY_OFF
    _assert_render_match(ref, motion)

    _send_enter(ref)
    _send_enter(motion)
    QApplication.processEvents()
    _assert_render_match(ref, motion)

    ref.setDown(True)
    motion.setDown(True)
    QApplication.processEvents()
    _assert_render_match(ref, motion)

    ref.setDown(False)
    motion.setDown(False)
    ref.setEnabled(False)
    motion.setEnabled(False)
    QApplication.processEvents()
    _assert_render_match(ref, motion)


@pytest.mark.parametrize("role", ("primary", "secondary", "quiet"))
def test_motion_on_end_state_keeps_text_and_allows_narrow_aa(
    qtbot, production_stylesheet, role
):
    host = _white_host()
    qtbot.addWidget(host)
    ref, motion = _twin_buttons(role, host=host)
    motion.set_motion_policy(POLICY_LIGHT)
    _send_enter(ref)
    _send_enter(motion)
    QTest.mouseMove(ref, _center(ref))
    QApplication.processEvents()
    motion._hover_driver.snap(1.0)
    fill_delta = _color_delta(_fill_sample(ref), _fill_sample(motion))
    assert fill_delta <= 20
    _assert_render_match(
        ref,
        motion,
        edge_px=9,
        edge_slop=255,
        interior_slop=28,
        text_pixel_slop=80,
    )


def test_sample_factory_covers_four_roles_and_compact_icon_sizes(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    buttons = {
        "primary": make_sample_button("primary", host),
        "secondary": make_sample_button("secondary", host),
        "quiet": make_sample_button("quiet", host),
        "icon28": make_sample_button("icon", host, icon_edge=28),
        "icon24": make_sample_button("icon", host, icon_edge=24),
    }
    host.resize(640, 80)
    host.show()
    QApplication.processEvents()

    assert buttons["primary"].text() == "确定"
    assert buttons["secondary"].text() == "取消"
    assert buttons["quiet"].text() == "更多"
    assert buttons["icon28"].text() == ""
    assert not buttons["icon28"].icon().isNull()
    assert buttons["icon28"].width() == buttons["icon28"].height() == 28
    assert buttons["icon24"].width() == buttons["icon24"].height() == 24
    for role, key in (("primary", "primary"), ("secondary", "secondary"), ("quiet", "quiet"), ("icon", "icon28")):
        assert buttons[key].property("role") == role
        assert buttons[key].motion_policy() == POLICY_OFF


def test_focus_and_default_stay_visible_when_motion_is_on(qtbot, production_stylesheet):
    ref, motion = _twin_buttons("primary")
    qtbot.addWidget(ref)
    qtbot.addWidget(motion)
    idle = MotionButton(motion.text())
    qtbot.addWidget(idle)
    set_control_role(idle, "primary", size="base")
    _prepare(idle, width=112, height=32)
    idle.set_motion_policy(POLICY_LIGHT)

    ref.setDefault(True)
    motion.setDefault(True)
    motion.set_motion_policy(POLICY_LIGHT)
    motion.setFocus()
    QApplication.processEvents()

    assert motion.sizeHint() == ref.sizeHint()
    assert motion.size() == ref.size()
    focused = motion.grab().toImage()
    plain = idle.grab().toImage()
    assert focused.size() == plain.size()
    changed = 0
    for y in range(focused.height()):
        for x in range(focused.width()):
            if focused.pixel(x, y) != plain.pixel(x, y):
                changed += 1
    assert changed > 0


def test_hide_snaps_and_stops_clocks(qtbot, production_stylesheet):
    button = make_sample_button("quiet")
    qtbot.addWidget(button)
    _prepare(button)
    button.set_motion_policy(POLICY_LIGHT)
    _send_enter(button)
    button._hover_driver.clock().setCurrentTime(40)
    assert button._hover_driver.is_active()
    button.hide()
    assert not button._hover_driver.is_active()
    assert not button._press_driver.is_active()
    assert float(button._hover_driver.current()) == pytest.approx(0.0)


def test_source_has_no_lambda_signal_connections():
    tree = ast.parse(_MOTION_BUTTON_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "connect":
            continue
        assert node.args
        assert not isinstance(node.args[0], ast.Lambda)
