"""Presentation-only contracts for chart page-transition composition."""
from __future__ import annotations

import logging

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap, QWheelEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

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


class _InputSurface(QWidget):
    """A real hit-tested chart stand-in that records delivered input."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.events = []
        self.setFocusPolicy(Qt.StrongFocus)

    def event(self, event):  # noqa: N802 - Qt callback spelling
        if event.type() in {
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseMove,
            QEvent.MouseButtonDblClick,
            QEvent.Wheel,
            QEvent.ContextMenu,
            QEvent.KeyPress,
            QEvent.KeyRelease,
        }:
            self.events.append(event.type())
        return super().event(event)


class _ColorHost(QWidget):
    """Small paintable host used to check the actual visible redirect frame."""

    def __init__(self, color: str) -> None:
        super().__init__()
        self._color = QColor(color)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt callback spelling
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), self._color)
        finally:
            painter.end()


def test_transition_is_off_by_default_and_retains_no_frames(qtbot):
    controller = _controller(qtbot, policy=POLICY_OFF)

    assert not controller.begin_departure(_token("A"), _frame("#204080"))
    assert not controller.is_pending()
    assert not controller.is_active()
    assert controller.image_bytes() == 0


def test_target_ack_starts_crossfade_and_finished_releases_frames(qtbot):
    controller = _controller(qtbot)
    source = _token("A")
    target = _token("B")
    duration = duration_ms("page_transition", POLICY_LIGHT)

    assert duration == 240
    assert controller.begin_departure(source, _frame("#204080"))
    assert controller.is_pending()
    assert controller.arm_target(target)
    assert controller.accept_target(target, _frame("#d08020"))
    assert controller.is_active()
    assert controller.image_bytes() == 2 * 240 * 160 * 4
    assert controller._overlay.testAttribute(Qt.WA_TransparentForMouseEvents)

    controller._driver.clock().setCurrentTime(duration // 2)
    assert 0.0 < controller._overlay._progress < 1.0
    controller._driver.clock().setCurrentTime(duration)
    qtbot.waitUntil(lambda: not controller.is_active())

    assert controller.image_bytes() == 0
    assert not controller._overlay.isVisible()


def test_pending_chart_input_is_blocked_but_first_ready_input_settles_then_hits_once(
    qtbot,
):
    """Never let a real hit target act on data hidden by the outgoing frame."""
    controller = _controller(qtbot)
    surface = _InputSurface(controller._host)
    surface.setGeometry(controller._host.rect())
    surface.show()
    source = _token("A")
    target = _token("B")

    assert controller.begin_departure(source, _frame("#204080"))
    assert controller.arm_target(target)
    assert controller.watch_input_targets(target, (surface,))

    hit = QApplication.widgetAt(surface.mapToGlobal(surface.rect().center()))
    assert hit is surface
    QTest.mousePress(hit, Qt.LeftButton)
    QTest.mouseMove(hit, hit.rect().center())
    QTest.mouseRelease(hit, Qt.LeftButton)
    center = hit.rect().center()
    QApplication.sendEvent(
        hit,
        QWheelEvent(
            QPointF(center), QPointF(hit.mapToGlobal(center)), QPoint(),
            QPoint(0, 120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase,
            False,
        ),
    )
    surface.setFocus(Qt.OtherFocusReason)
    QTest.keyClick(surface, Qt.Key_Left)
    assert surface.events == []
    assert controller._overlay.isVisible()

    assert controller.accept_target(target)
    QTest.mouseClick(hit, Qt.LeftButton)

    assert surface.events == [QEvent.MouseButtonPress, QEvent.MouseButtonRelease]
    assert not controller.is_active()
    assert controller.image_bytes() == 0


def test_single_image_redirect_uses_the_visible_a_b_frame_before_fading_to_c(
    qtbot,
):
    """The normal no-target-pixmap path must not drop B during A -> B -> C."""
    host = _ColorHost("#0000ff")
    host.resize(240, 160)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    controller = PageTransitionController(host, policy=POLICY_LIGHT)
    source = _token("A")
    target_b = _token("B")
    target_c = _token("C")

    assert controller.begin_departure(source, _frame("#ff0000"))
    assert controller.arm_target(target_b)
    assert controller.accept_target(target_b)
    duration = duration_ms("page_transition", POLICY_LIGHT)
    controller._driver.clock().setCurrentTime(duration // 2)
    visible_before_redirect = host.grab().toImage().pixelColor(120, 80)

    assert controller.begin_departure(
        target_b, controller.capture_local_endpoint(host),
    )
    redirect_source = controller._overlay._source.toImage().pixelColor(120, 80)
    assert redirect_source.rgba() == visible_before_redirect.rgba()

    host.set_color("#00a040")
    QApplication.processEvents()
    assert controller.arm_target(target_c)
    assert controller.accept_target(target_c)
    controller._driver.clock().setCurrentTime(duration)
    qtbot.waitUntil(lambda: not controller.is_active())
    final = host.grab().toImage().pixelColor(120, 80)
    assert final == QColor("#00a040")


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
    controller._driver.clock().setCurrentTime(
        duration_ms("page_transition", POLICY_LIGHT) // 2,
    )

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


def test_cropped_overlay_accepts_matching_host_token(qtbot):
    """Overlay may be a plot-surface subset; host rect still gates geometry."""
    controller = _controller(qtbot)
    overlay_rect = QRect(20, 30, 160, 80)
    frame = QPixmap(overlay_rect.width(), overlay_rect.height())
    frame.fill(QColor("#204080"))
    token = controller.begin_transition(
        source_section="time", source_view_id="A",
        target_section="fft", target_view_id="B",
        source_pixmap=frame, overlay_rect=overlay_rect,
    )
    assert token is not None
    assert token.section == "fft"
    assert token.rect == controller._host.rect()
    assert controller._overlay.geometry() == overlay_rect
    assert controller._overlay.size() == frame.size()
    assert controller.accept_target(token)
    assert controller.is_active()
    controller.cancel("overlay-rect-probe")
    assert controller.image_bytes() == 0


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


class _LiveInputSurface(_InputSurface):
    """A real QWidget hit surface that also paints, like a GraphicsView viewport."""

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.paints = 0
        self.color = QColor("#20a060")

    def paintEvent(self, event):  # noqa: N802 - Qt callback spelling
        self.paints += 1
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), self.color)
        finally:
            painter.end()


def test_ordinary_ready_paint_does_not_cancel_live_fade(qtbot):
    """A natural expose after target-ready must not be treated as invalidation.

    Production watches the real canvas/viewport QWidget.  Existing QObject
    fences never receive ``QEvent.Paint``, so clock-jump tests cannot catch
    this path.  Do not skip to the token duration before the expose.
    """
    controller = _controller(qtbot)
    surface = _LiveInputSurface(controller._host)
    surface.setGeometry(controller._host.rect())
    surface.show()
    qtbot.waitExposed(surface)
    source = _token("A")
    target = _token("B")
    cancelled = []
    finished = []
    controller.transition_cancelled.connect(cancelled.append)
    controller.transition_finished.connect(finished.append)

    assert controller.begin_departure(source, _frame("#204080"))
    assert controller.arm_target(target)
    assert controller.watch_input_targets(target, (surface,))
    assert controller.accept_target(target)
    assert controller.is_active()

    surface.update()
    QApplication.processEvents()
    QApplication.processEvents()

    assert controller.is_active()
    assert cancelled == []
    assert controller._overlay._progress < 1.0

    qtbot.waitUntil(lambda: not controller.is_active(), timeout=1500)
    assert cancelled == []
    assert finished
    assert controller.image_bytes() == 0


def test_host_close_cancels_ready_fade_and_releases_frames(qtbot):
    controller = _controller(qtbot)
    cancelled = []
    controller.transition_cancelled.connect(cancelled.append)
    assert controller.begin_departure(_token("A"), _frame("#204080"))
    assert controller.arm_target(_token("B"))
    assert controller.accept_target(_token("B"), _frame("#d08020"))
    assert controller.is_active()

    controller._host.close()
    qtbot.waitUntil(lambda: controller.image_bytes() == 0)

    assert "host-geometry-or-lifecycle" in cancelled
    assert not controller.is_active()


def test_missing_natural_ack_times_out_without_starting_a_fade(qtbot):
    controller = _controller(qtbot)
    cancelled = []
    controller.transition_cancelled.connect(cancelled.append)
    target = _token("B")
    assert controller.begin_departure(_token("A"), _frame("#204080"))
    assert controller.arm_target(target)
    controller._target_ack_watchdog.setInterval(20)
    assert controller.watch_target_ack(target)
    qtbot.waitUntil(lambda: controller.image_bytes() == 0, timeout=1000)
    assert cancelled == ["target-paint-timeout"]
    assert not controller.is_active()


def test_target_paint_timeout_warns_with_section_and_view_before_cancel(qtbot, caplog):
    """The 1000 ms watchdog stays; expiry logs Section/View identity, then cancels."""
    controller = _controller(qtbot)
    assert controller._target_ack_watchdog.interval() == 1000
    target = _token("fft-view")
    logged_before_cancel = []

    def _on_cancel(reason):
        logged_before_cancel.append((reason, [record.getMessage() for record in caplog.records]))

    controller.transition_cancelled.connect(_on_cancel)
    assert controller.begin_departure(_token("time-view"), _frame("#204080"))
    assert controller.arm_target(target)
    controller._target_ack_watchdog.setInterval(20)
    with caplog.at_level(
        logging.WARNING, logger="mf4_analyzer.ui.chart_stack.page_transition",
    ):
        assert controller.watch_target_ack(target)
        qtbot.waitUntil(lambda: bool(logged_before_cancel), timeout=1000)

    assert logged_before_cancel
    reason, messages_at_cancel = logged_before_cancel[0]
    assert reason == "target-paint-timeout"
    assert len(messages_at_cancel) == 1
    message = messages_at_cancel[0]
    assert "section=time" in message
    assert "view=fft-view" in message
    assert not controller.is_active()
