"""Presentation-only contracts for chart page-transition composition."""
from __future__ import annotations

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.page_transition import (
    PageTransitionController,
    PresentationToken,
)
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, duration_ms


def _token(view_id: str, generation: int = 7) -> PresentationToken:
    return PresentationToken(
        section="time", view_id=view_id, request_generation=generation,
        host_epoch=3, rect=QRect(0, 0, 240, 160), device_pixel_ratio=1.0,
    )


def _frame(color: str) -> QPixmap:
    frame = QPixmap(240, 160)
    frame.fill(QColor(color))
    return frame


def _controller(qtbot, *, policy=POLICY_LIGHT):
    host = QWidget()
    host.resize(240, 160)
    qtbot.addWidget(host)
    host.show()
    return PageTransitionController(host, policy=policy)


def test_transition_is_off_by_default_and_retains_no_frames(qtbot):
    controller = _controller(qtbot, policy=POLICY_OFF)

    assert not controller.begin_departure(_token("A"), _frame("#204080"))
    assert not controller.is_pending()
    assert not controller.is_active()
    assert controller.image_bytes() == 0


def test_target_ack_starts_300ms_crossfade_and_finished_releases_frames(qtbot):
    controller = _controller(qtbot)
    source = _token("A")
    target = _token("B")

    assert duration_ms("page_transition", POLICY_LIGHT) == 300
    assert controller.begin_departure(source, _frame("#204080"))
    assert controller.is_pending()
    assert controller.arm_target(target)
    assert controller.accept_target(target, _frame("#d08020"))
    assert controller.is_active()
    assert controller.image_bytes() == 2 * 240 * 160 * 4
    assert controller._overlay.testAttribute(Qt.WA_TransparentForMouseEvents)

    controller._driver.clock().setCurrentTime(150)
    assert 0.0 < controller._overlay._progress < 1.0
    controller._driver.clock().setCurrentTime(300)
    qtbot.waitUntil(lambda: not controller.is_active())

    assert controller.image_bytes() == 0
    assert not controller._overlay.isVisible()


def test_stale_or_wrong_geometry_target_never_starts_animation(qtbot):
    controller = _controller(qtbot)
    source = _token("A")
    target = _token("B")

    assert controller.begin_departure(source, _frame("#204080"))
    assert controller.arm_target(target)
    assert not controller.accept_target(_token("old", generation=6), _frame("#d08020"))
    wrong_geometry = PresentationToken(
        **{**target.__dict__, "rect": QRect(0, 0, 241, 160)}
    )
    assert not controller.accept_target(wrong_geometry, _frame("#d08020"))
    assert not controller.is_active()
    assert controller.image_bytes() == 240 * 160 * 4


def test_rapid_a_b_c_keeps_two_endpoint_frames_and_cancel_releases_them(qtbot):
    controller = _controller(qtbot)
    assert controller.begin_departure(_token("A"), _frame("#204080"))
    assert controller.arm_target(_token("B"))
    assert controller.accept_target(_token("B"), _frame("#d08020"))
    controller._driver.clock().setCurrentTime(150)

    # A new navigation samples only the displayed blend, then replaces B.
    assert controller.begin_departure(_token("B"), _frame("#d08020"))
    assert controller.arm_target(_token("C"))
    assert controller.accept_target(_token("C"), _frame("#209050"))
    assert controller.image_bytes() == 2 * 240 * 160 * 4

    controller.cancel("resize")
    assert not controller.is_active()
    assert not controller.is_pending()
    assert controller.image_bytes() == 0


def test_host_resize_cancels_pending_endpoint_before_it_can_be_accepted(qtbot):
    controller = _controller(qtbot)
    assert controller.begin_departure(_token("A"), _frame("#204080"))
    assert controller.arm_target(_token("B"))

    controller._host.resize(241, 160)
    qtbot.waitUntil(lambda: controller.image_bytes() == 0)

    assert not controller.accept_target(_token("B"), _frame("#d08020"))
    assert not controller.is_active()


def test_local_endpoint_capture_is_host_scoped_and_excludes_active_overlay(qtbot):
    controller = _controller(qtbot)
    source = _frame("#204080")
    assert controller.begin_departure(_token("A"), source)

    captured = controller.capture_local_endpoint(
        controller._host, exclude_overlay=True,
    )
    assert not captured.isNull()
    assert captured.size() == controller._host.size()
    assert controller._overlay.isVisible()

    outsider = QWidget()
    qtbot.addWidget(outsider)
    outsider.resize(240, 160)
    outsider.show()
    assert controller.capture_local_endpoint(outsider).isNull()


def test_begin_transition_mints_one_generation_for_its_two_endpoints(qtbot):
    controller = _controller(qtbot)
    target = controller.begin_transition(
        source_section="time", source_view_id="A",
        target_section="fft", target_view_id="B",
        source_pixmap=_frame("#204080"), pane_signature=("single",),
    )

    assert target is not None
    assert target.section == "fft"
    assert target.view_id == "B"
    assert target.pane_signature == ("single",)
    assert controller._source_token.request_generation == target.request_generation


def test_local_source_endpoint_is_not_reused_after_a_redirect_blend(qtbot):
    controller = _controller(qtbot)
    source = _token("A")
    assert controller.begin_departure(source, _frame("#204080"))
    assert not controller.local_source_endpoint("time", "A").isNull()
    assert controller.arm_target(_token("B"))
    assert controller.accept_target(_token("B"), _frame("#d08020"))

    assert controller.begin_departure(_token("B"), _frame("#d08020"))
    assert controller.local_source_endpoint("time", "B").isNull()
