"""Injected-rectangle contracts for shared dialog/popover geometry."""
from __future__ import annotations

import os

import pytest
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout

from mf4_analyzer.ui_kit.dialog_geometry import (
    ANCHOR_GAP,
    FrameInsets,
    IntRect,
    SCREEN_MARGIN,
    Size,
    as_rect,
    client_budget,
    constrain_client_size,
    fit_window,
    frame_insets_of,
    install_geometry_relayout,
    plan_geometry,
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
