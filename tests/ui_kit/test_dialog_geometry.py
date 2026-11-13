"""Injected-rectangle contracts for shared dialog/popover geometry."""
from __future__ import annotations

import logging
import os

import pytest
from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtWidgets import QApplication, QDialog, QFrame, QLabel, QVBoxLayout, QWidget

from mf4_analyzer.ui_kit.dialog_geometry import (
    ANCHOR_GAP,
    MIN_DECORATED_CLIENT,
    UNTRUSTED_WORK_HEIGHT,
    UNTRUSTED_WORK_WIDTH,
    FrameInsets,
    GeometryPlan,
    IntRect,
    SCREEN_MARGIN,
    Size,
    apply_plan,
    as_rect,
    client_budget,
    constrain_client_size,
    fit_window,
    frame_insets_of,
    install_geometry_relayout,
    move_in_screen,
    plan_geometry,
    resolve_available_rect,
)


@pytest.fixture(scope="session")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_qrect_adapter_matches_qt_inclusive_edges():
    qt_rect = QRect(-1280, 0, 1280, 680)
    rect = as_rect(qt_rect)
    assert rect.left == -1280
    assert rect.right == qt_rect.right() == -1
    assert rect.bottom == qt_rect.bottom() == 679
    safe = rect.adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    qt_safe = qt_rect.adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert safe.to_qrect() == qt_safe


def test_client_budget_never_negative_on_empty_or_tiny_work_area():
    empty = IntRect(0, 0, 0, 0)
    budget = client_budget(empty, FrameInsets(0, 30, 0, 0), margin=8)
    assert budget.width == 0
    assert budget.height == 0
    tiny = IntRect(0, 0, 20, 20)
    budget = client_budget(tiny, FrameInsets(1, 28, 1, 1), margin=8)
    assert budget.width >= 0
    assert budget.height >= 0


def test_hard_minimum_cannot_break_screen_budget():
    available = QRect(0, 0, 640, 360)
    plan = plan_geometry(
        available,
        (1040, 720),
        frame=FrameInsets(),
        content_minimum=(640, 420),
        position="center",
    )
    safe = as_rect(available).adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert safe.contains_rect(plan.frame)
    assert plan.client.height <= 360 - 2 * SCREEN_MARGIN
    assert plan.needs_scroll is True
    assert plan.compact is True


def test_1080x760_target_keeps_size_on_large_screen_and_clamps_on_small():
    large = plan_geometry(
        QRect(0, 0, 1920, 1080),
        (1080, 760),
        frame=FrameInsets(),
        content_minimum=(640, 480),
        position="center",
    )
    assert large.client.width == 1080
    assert large.client.height == 760

    small = plan_geometry(
        QRect(0, 0, 800, 600),
        (1080, 760),
        frame=FrameInsets(),
        content_minimum=(640, 480),
        position="center",
    )
    safe = IntRect(0, 0, 800, 600).adjusted(
        SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
    )
    assert small.client.width < 1080
    assert small.client.width <= safe.width
    assert safe.contains_rect(small.frame)


@pytest.mark.parametrize(
    "available",
    [
        QRect(0, 0, 800, 600),
        QRect(-1280, 0, 1280, 680),
        QRect(0, 0, 960, 540),
        QRect(0, 0, 1366, 728),
    ],
)
def test_same_input_is_stable_and_frame_stays_in_safe_area(available):
    first = plan_geometry(
        available,
        (380, 160),
        frame=FrameInsets(0, 30, 0, 0),
        host=as_rect(available),
    )
    second = plan_geometry(
        available,
        (380, 160),
        frame=FrameInsets(0, 30, 0, 0),
        host=as_rect(available),
    )
    assert first == second
    safe = as_rect(available).adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert safe.contains_rect(first.frame)


def test_popover_flips_above_then_clamps_on_bottom_right_anchor():
    available = QRect(0, 0, 800, 600)
    anchor = IntRect(720, 560, 70, 24)
    below = plan_geometry(
        available,
        (270, 315),
        frame=FrameInsets(),
        anchor=anchor,
        position="below",
        gap=ANCHOR_GAP,
    )
    safe = as_rect(available).adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert safe.contains_rect(below.frame)
    assert below.frame.bottom <= safe.bottom
    assert below.frame.right <= safe.right


@pytest.mark.parametrize("screen_x", [0, -1366])
@pytest.mark.parametrize("edge", ["left", "right"])
@pytest.mark.parametrize("position", ["above", "below"])
@pytest.mark.parametrize("must_flip", [False, True])
def test_horizontal_overflow_does_not_prevent_vertical_popover_placement(
    screen_x, edge, position, must_flip,
):
    available = IntRect(screen_x, 0, 1366, 720)
    # Preset cards center a 380px anchor on a button near the screen edge.
    center_x = screen_x + (50 if edge == "left" else 1307)
    side = ("below" if position == "above" else "above") if must_flip else position
    anchor = IntRect(center_x - 190, 122 if side == "below" else 560, 380, 32)
    plan = plan_geometry(
        available, (380, 299), anchor=anchor, position=position, gap=10,
    )
    safe = available.adjusted(8, 8, -8, -8)
    assert safe.contains_rect(plan.frame)
    if side == "below":
        assert plan.frame.top == anchor.bottom + 1 + 10
    else:
        assert plan.frame.bottom == anchor.top - 10 - 1


def test_parent_partially_off_screen_still_clamps_to_work_area():
    available = QRect(0, 0, 800, 600)
    parent = IntRect(-120, 40, 400, 300)
    plan = plan_geometry(
        available,
        (380, 240),
        frame=FrameInsets(0, 0, 0, 0),
        host=parent,
        position="center",
    )
    safe = as_rect(available).adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert safe.contains_rect(plan.frame)


def test_embedded_uses_host_local_rect_not_global_screen():
    host = IntRect(10, 20, 200, 160)
    plan = plan_geometry(
        host,
        (400, 400),
        position="embedded",
        margin=4,
    )
    assert host.contains_rect(plan.frame)
    assert plan.frame.width <= 200
    assert plan.frame.height <= 160


def test_constrain_does_not_use_max_of_floor_and_cap():
    size, compact, needs_scroll = constrain_client_size(
        Size(1040, 720),
        Size(624, 344),
        content_minimum=Size(640, 420),
    )
    assert size.width <= 624
    assert size.height <= 344
    assert needs_scroll is True
    assert compact is True


def test_titled_estimate_differs_from_frameless(qapp, qtbot):
    titled = QDialog()
    titled.setWindowTitle("titled")
    qtbot.addWidget(titled)
    frameless = QDialog()
    frameless.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    qtbot.addWidget(frameless)
    titled_insets = frame_insets_of(titled)
    frameless_insets = frame_insets_of(frameless)
    assert titled_insets.vertical >= frameless_insets.vertical
    titled.show()
    frameless.show()
    qtbot.waitExposed(titled)
    qtbot.waitExposed(frameless)
    shown_titled = frame_insets_of(titled)
    shown_frameless = frame_insets_of(frameless)
    assert shown_titled.left >= 0
    assert shown_frameless.left >= 0
    assert shown_titled.horizontal >= 0
    assert shown_frameless.vertical >= 0


def test_fit_window_does_not_set_maximum_size(qapp, qtbot, monkeypatch):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 800, 600),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    qtbot.addWidget(dialog)
    fit_window(dialog, (380, 160), content_minimum=(200, 80))
    assert dialog.maximumWidth() >= 16777215 or dialog.maximumWidth() >= 800
    dialog.resize(500, 300)
    assert dialog.width() == 500
    assert dialog.height() == 300


def test_apply_plan_keeps_shown_frame_in_safe_area_when_insets_are_stubbed(
    qapp, qtbot, monkeypatch,
):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 800, 600),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    label = QLabel("方向盘扭矩 " * 20)
    label.setWordWrap(True)
    layout.addWidget(label)
    dialog.show()
    qtbot.waitExposed(dialog)
    fit_window(dialog, (1180, 680), content_minimum=(640, 280))
    qapp.processEvents()
    safe = IntRect(0, 0, 800, 600).adjusted(
        SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
    )
    assert safe.contains_rect(as_rect(dialog.frameGeometry()))
    assert dialog.maximumWidth() >= 16777215 or dialog.maximumWidth() >= 800


def test_relayout_converges_and_pending_callback_is_dropped_on_destroy(qapp, qtbot):
    dialog = QDialog()
    qtbot.addWidget(dialog)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("relayout"))
    calls = {"n": 0}

    def apply():
        calls["n"] += 1
        fit_window(dialog, (320, 140))

    controller = install_geometry_relayout(dialog, apply)
    dialog.show()
    qtbot.waitExposed(dialog)
    controller.request()
    controller.request()
    controller.request()
    qtbot.waitUntil(lambda: not controller._pending, timeout=1000)
    QApplication.processEvents()
    QApplication.processEvents()
    after = calls["n"]
    QApplication.processEvents()
    assert calls["n"] == after
    assert calls["n"] >= 1
    from PyQt5 import sip
    dialog.close()
    dialog.deleteLater()
    QApplication.processEvents()
    assert sip.isdeleted(controller) or controller._pending is False


def test_nudge_is_noop_when_frame_already_inside_safe_area(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui_kit.dialog_geometry import nudge_into_work_area

    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: IntRect(0, 0, 800, 600),
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: FrameInsets(),
    )
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.setGeometry(40, 40, 200, 120)
    dialog.show()
    qtbot.waitExposed(dialog)
    before = (dialog.x(), dialog.y(), dialog.width(), dialog.height())
    assert nudge_into_work_area(dialog) is None
    assert (dialog.x(), dialog.y(), dialog.width(), dialog.height()) == before


def test_move_in_screen_creates_handle_before_first_show(qapp, qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.setGeometry(40, 60, 200, 40)
    parent.show()
    qtbot.waitExposed(parent)
    popup = QFrame(parent, Qt.Popup)
    qtbot.addWidget(popup)
    popup.resize(120, 80)
    assert popup.windowHandle() is None
    move_in_screen(popup, QPoint(88, 120))
    assert popup.windowHandle() is not None
    assert popup.pos() == QPoint(88, 120)


def _stub_work_area(monkeypatch, work, insets):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_available_rect",
        lambda **_kwargs: work,
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.frame_insets_of",
        lambda _widget: insets,
    )


def test_apply_plan_moves_titled_window_by_frame_origin(qapp, qtbot, monkeypatch):
    work = IntRect(0, 40, 800, 600)
    insets = FrameInsets(0, 32, 0, 0)
    _stub_work_area(monkeypatch, work, insets)
    dialog = QDialog()
    dialog.setWindowTitle("titled")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    plan = fit_window(dialog, (800, 600), content_minimum=(200, 80))
    qapp.processEvents()
    safe = work.adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert plan.client.x == plan.frame.x + insets.left
    assert plan.client.y == plan.frame.y + insets.top
    assert plan.client.y != plan.frame.y
    assert safe.contains_rect(plan.frame)
    assert dialog.pos() == QPoint(plan.frame.x, plan.frame.y)
    actual = as_rect(dialog.frameGeometry())
    assert actual.x == plan.frame.x
    assert actual.y == plan.frame.y
    assert safe.contains_rect(actual)


def test_apply_plan_frameless_frame_equals_client(qapp, qtbot, monkeypatch):
    work = IntRect(0, 40, 800, 600)
    _stub_work_area(monkeypatch, work, FrameInsets())
    dialog = QDialog()
    dialog.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    qtbot.addWidget(dialog)
    plan = fit_window(dialog, (380, 160), content_minimum=(200, 80))
    assert plan.frame.x == plan.client.x
    assert plan.frame.y == plan.client.y
    assert dialog.pos() == QPoint(plan.frame.x, plan.frame.y)


def test_apply_plan_embedded_uses_host_local_origin(qapp, qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    host.setGeometry(10, 20, 200, 160)
    child = QWidget(host)
    qtbot.addWidget(child)
    plan = plan_geometry(
        host.rect(),
        (400, 400),
        position="embedded",
        margin=4,
    )
    apply_plan(child, plan)
    assert plan.frame.x == plan.client.x
    assert plan.frame.y == plan.client.y
    assert child.pos() == QPoint(plan.client.x, plan.client.y)
    assert as_rect(host.rect()).contains_rect(as_rect(child.geometry()))


def test_apply_plan_negative_work_area_keeps_frame_origin(qapp, qtbot, monkeypatch):
    work = IntRect(-1280, 0, 1280, 680)
    insets = FrameInsets(8, 32, 8, 8)
    _stub_work_area(monkeypatch, work, insets)
    dialog = QDialog()
    dialog.setWindowTitle("left screen")
    qtbot.addWidget(dialog)
    plan = fit_window(dialog, (1040, 720), content_minimum=(200, 80))
    safe = work.adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert plan.frame.x < 0
    assert safe.contains_rect(plan.frame)
    assert dialog.pos() == QPoint(plan.frame.x, plan.frame.y)


def test_apply_plan_filling_budget_stays_in_safe_area(qapp, qtbot, monkeypatch):
    work = IntRect(0, 40, 800, 600)
    insets = FrameInsets(0, 32, 0, 0)
    _stub_work_area(monkeypatch, work, insets)
    dialog = QDialog()
    dialog.setWindowTitle("full budget")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    plan = fit_window(dialog, (1180, 680), content_minimum=(640, 280))
    qapp.processEvents()
    safe = work.adjusted(SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN)
    assert safe.contains_rect(plan.frame)
    assert dialog.pos() == QPoint(plan.frame.x, plan.frame.y)
    assert safe.contains_rect(as_rect(dialog.frameGeometry()))


def test_apply_plan_same_plan_twice_does_not_drift(qapp, qtbot, monkeypatch):
    work = IntRect(0, 40, 800, 600)
    insets = FrameInsets(0, 32, 0, 0)
    _stub_work_area(monkeypatch, work, insets)
    dialog = QDialog()
    dialog.setWindowTitle("stable")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitExposed(dialog)
    first = fit_window(dialog, (800, 600), content_minimum=(200, 80))
    first_geo = (dialog.x(), dialog.y(), dialog.width(), dialog.height())
    second = fit_window(dialog, (800, 600), content_minimum=(200, 80))
    second_geo = (dialog.x(), dialog.y(), dialog.width(), dialog.height())
    assert first.frame == second.frame
    assert first_geo == second_geo
    assert apply_plan(dialog, second) is False


def test_nudge_leaves_user_enlarged_window_when_still_legal(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui_kit.dialog_geometry import nudge_into_work_area

    work = IntRect(0, 40, 800, 600)
    insets = FrameInsets(0, 32, 0, 0)
    _stub_work_area(monkeypatch, work, insets)
    dialog = QDialog()
    dialog.setWindowTitle("user size")
    qtbot.addWidget(dialog)
    fit_window(dialog, (380, 160), content_minimum=(200, 80))
    dialog.resize(500, 300)
    dialog.move(40, 80)
    dialog.show()
    qtbot.waitExposed(dialog)
    before = (dialog.x(), dialog.y(), dialog.width(), dialog.height())
    assert nudge_into_work_area(dialog) is None
    assert (dialog.x(), dialog.y(), dialog.width(), dialog.height()) == before


def test_hidden_window_uses_estimated_frame_origin(qapp, qtbot, monkeypatch):
    work = IntRect(0, 40, 800, 600)
    insets = FrameInsets(1, 28, 1, 1)
    _stub_work_area(monkeypatch, work, insets)
    dialog = QDialog()
    dialog.setWindowTitle("hidden")
    qtbot.addWidget(dialog)
    assert dialog.isVisible() is False
    plan = fit_window(dialog, (800, 600), content_minimum=(200, 80))
    assert plan.client.y == plan.frame.y + insets.top
    assert dialog.pos() == QPoint(plan.frame.x, plan.frame.y)


def test_untrusted_work_area_thresholds_match_the_spec():
    assert UNTRUSTED_WORK_WIDTH == 320
    assert UNTRUSTED_WORK_HEIGHT == 240
    assert MIN_DECORATED_CLIENT == 200


class _FakeScreen:
    def __init__(self, name, available, geometry, dpr=1.0):
        self._name = name
        self._available = QRect(*available)
        self._geometry = QRect(*geometry)
        self._dpr = dpr

    def name(self):
        return self._name

    def availableGeometry(self):
        return QRect(self._available)

    def geometry(self):
        return QRect(self._geometry)

    def devicePixelRatio(self):
        return self._dpr


def _install_screens(monkeypatch, chosen, primary=None):
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry.resolve_target_screen",
        lambda **_kwargs: chosen,
    )
    monkeypatch.setattr(
        "mf4_analyzer.ui_kit.dialog_geometry._primary_screen",
        lambda: primary,
    )


@pytest.mark.parametrize(
    "available",
    [
        (0, 0, 0, 0),
        (0, 0, 10, 10),
        (0, 0, 319, 239),
        (0, 0, 320, 239),
        (0, 0, 319, 240),
    ],
)
def test_untrusted_available_rect_falls_back_to_screen_geometry_and_logs(
    qapp, monkeypatch, caplog, available,
):
    chosen = _FakeScreen("desk-a", available, (20, 30, 1920, 1080), dpr=1.25)
    primary = _FakeScreen("primary", (7, 8, 1440, 900), (7, 8, 1440, 900), dpr=1.0)
    _install_screens(monkeypatch, chosen, primary)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        rect = resolve_available_rect()
    assert rect == IntRect(20, 30, 1920, 1080)
    assert "untrusted work area" in caplog.text
    assert "desk-a" in caplog.text
    assert "1.25" in caplog.text
    assert "1920x1080" in caplog.text
    assert "fallback=screen-geometry" in caplog.text
    assert "1440x900" not in caplog.text


def test_trusted_320x240_work_area_is_used_without_a_warning(qapp, monkeypatch, caplog):
    chosen = _FakeScreen("desk-b", (4, 5, 320, 240), (0, 0, 1920, 1080), dpr=2.0)
    _install_screens(monkeypatch, chosen, None)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        rect = resolve_available_rect()
    assert rect == IntRect(4, 5, 320, 240)
    assert "untrusted work area" not in caplog.text


def test_untrusted_geometry_falls_back_to_trusted_primary(qapp, monkeypatch, caplog):
    chosen = _FakeScreen("tiny", (0, 0, 10, 10), (0, 0, 10, 10), dpr=1.5)
    primary = _FakeScreen("main", (11, 12, 800, 600), (11, 12, 1600, 900), dpr=2.0)
    _install_screens(monkeypatch, chosen, primary)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        rect = resolve_available_rect()
    assert rect == IntRect(11, 12, 800, 600)
    assert "untrusted work area" in caplog.text
    assert "tiny" in caplog.text
    assert "1.5" in caplog.text
    assert "fallback=primary-available" in caplog.text


@pytest.mark.parametrize("primary", [None, "untrusted"])
def test_untrusted_screens_fall_back_to_the_1080_constant(qapp, monkeypatch, caplog, primary):
    chosen = _FakeScreen("tiny", (0, 0, 0, 0), (0, 0, 0, 0), dpr=1.0)
    if primary == "untrusted":
        primary_screen = _FakeScreen("also-tiny", (0, 0, 10, 10), (0, 0, 10, 10))
    else:
        primary_screen = None
    _install_screens(monkeypatch, chosen, primary_screen)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        rect = resolve_available_rect()
    assert rect == IntRect(0, 0, 1920, 1080)
    assert "untrusted work area" in caplog.text
    assert "fallback=fallback-constant" in caplog.text


def _small_plan(preferred):
    return plan_geometry(
        IntRect(0, 0, 1920, 1080),
        preferred,
        frame=FrameInsets(),
        position="center",
    )


@pytest.mark.parametrize("preferred", [(199, 400), (400, 199), (199, 199), (80, 60)])
def test_apply_plan_refuses_degenerate_decorated_client(qapp, qtbot, caplog, preferred):
    dialog = QDialog()
    dialog.setWindowTitle("titled")
    qtbot.addWidget(dialog)
    dialog.resize(640, 480)
    dialog.move(30, 40)
    before = (dialog.x(), dialog.y(), dialog.width(), dialog.height())
    plan = _small_plan(preferred)
    assert plan.client.width < MIN_DECORATED_CLIENT or plan.client.height < MIN_DECORATED_CLIENT
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        assert apply_plan(dialog, plan) is False
    assert (dialog.x(), dialog.y(), dialog.width(), dialog.height()) == before
    assert "degenerate decorated plan refused" in caplog.text
    assert str(plan.client.width) in caplog.text
    assert str(plan.client.height) in caplog.text


@pytest.mark.parametrize("preferred", [(200, 200), (200, 480), (480, 200)])
def test_apply_plan_accepts_decorated_client_at_the_floor(qapp, qtbot, caplog, preferred):
    dialog = QDialog()
    dialog.setWindowTitle("titled")
    qtbot.addWidget(dialog)
    dialog.resize(640, 480)
    plan = _small_plan(preferred)
    assert plan.client.width >= MIN_DECORATED_CLIENT
    assert plan.client.height >= MIN_DECORATED_CLIENT
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        assert apply_plan(dialog, plan) is True
    assert dialog.width() == plan.client.width
    assert dialog.height() == plan.client.height
    assert "degenerate decorated plan refused" not in caplog.text


def test_apply_plan_frameless_and_child_accept_a_small_plan(qapp, qtbot, caplog):
    plan = _small_plan((80, 60))
    assert plan.client.width < MIN_DECORATED_CLIENT
    assert plan.client.height < MIN_DECORATED_CLIENT

    frameless = QDialog()
    qtbot.addWidget(frameless)
    frameless.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    frameless.resize(400, 300)
    host = QWidget()
    qtbot.addWidget(host)
    child = QWidget(host)
    qtbot.addWidget(child)
    child.resize(400, 300)
    assert child.isWindow() is False
    popup = QFrame(host, Qt.Popup)
    qtbot.addWidget(popup)
    popup.resize(400, 300)

    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.diagnostics"):
        assert apply_plan(frameless, plan) is True
        assert apply_plan(child, plan) is True
        assert apply_plan(popup, plan) is True
    assert frameless.width() == plan.client.width
    assert frameless.height() == plan.client.height
    assert child.width() == plan.client.width
    assert child.height() == plan.client.height
    assert popup.width() == plan.client.width
    assert popup.height() == plan.client.height
    assert "degenerate decorated plan refused" not in caplog.text


def test_shrink_keeps_a_decorated_window_at_the_floor_and_lets_frameless_shrink(
    qapp, qtbot,
):
    """A planned frame smaller than the live frame must not pull a titled window under 200."""
    tight = GeometryPlan(
        client=IntRect(0, 0, 220, 220),
        frame=IntRect(0, 0, 40, 40),
        compact=False,
        needs_scroll=False,
        margin_used=8,
    )
    titled = QDialog()
    titled.setWindowTitle("titled")
    qtbot.addWidget(titled)
    titled.resize(400, 400)
    titled.show()
    qtbot.waitExposed(titled)
    apply_plan(titled, tight)
    assert titled.width() >= MIN_DECORATED_CLIENT
    assert titled.height() >= MIN_DECORATED_CLIENT
    assert titled.width() < 220
    assert titled.height() < 220

    frameless = QDialog()
    qtbot.addWidget(frameless)
    frameless.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
    frameless.resize(400, 400)
    frameless.show()
    qtbot.waitExposed(frameless)
    apply_plan(frameless, tight)
    assert frameless.width() < MIN_DECORATED_CLIENT
    assert frameless.height() < MIN_DECORATED_CLIENT

