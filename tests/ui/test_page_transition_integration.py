"""ChartStack's local page-transition bridge contracts.

The compositor itself is covered by ``test_page_transition.py``.  These tests
exercise the bridge which owns the important ordering: a normal navigation
commits first, the outgoing page is copied once, a target canvas must report a
natural paint, and only then may ChartStack fade that source over the live
target.  It never synchronously captures the incoming endpoint.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, duration_ms


class _NaturalPaintFence(QObject):
    """A deterministic canvas-side natural-paint acknowledgement seam."""

    presentation_paint_acknowledged = pyqtSignal(object)
    presentation_content_invalidated = pyqtSignal()

    def __init__(self, *, accepts_request=True) -> None:
        super().__init__()
        self.accepts_request = accepts_request
        self.requests = []

    def request_presentation_paint_ack(self, request_id) -> bool:
        self.requests.append(request_id)
        return self.accepts_request

    def acknowledge(self, request_id=None) -> None:
        self.presentation_paint_acknowledged.emit(
            self.requests[-1] if request_id is None else request_id,
        )


class _LiveTarget(QWidget):
    """A real QWidget target: natural paint admits the fade, later paints must not cancel it."""

    presentation_paint_acknowledged = pyqtSignal(object)
    presentation_content_invalidated = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.requests = []
        self.paints = 0
        self._pending = None
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def request_presentation_paint_ack(self, request_id) -> bool:
        self.requests.append(request_id)
        self._pending = request_id
        self.update()
        return True

    def paintEvent(self, event):  # noqa: N802 - Qt callback spelling
        self.paints += 1
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#20a060"))
        finally:
            painter.end()
        pending = self._pending
        if pending is not None:
            self._pending = None
            self.presentation_paint_acknowledged.emit(pending)


def _stack(qtbot) -> ChartStack:
    chart_stack = ChartStack()
    qtbot.addWidget(chart_stack)
    chart_stack.resize(900, 560)
    chart_stack.show()
    qtbot.waitExposed(chart_stack)
    return chart_stack


def _frame(widget, color: str) -> QPixmap:
    pixmap = QPixmap(max(1, widget.width()), max(1, widget.height()))
    pixmap.fill(QColor(color))
    return pixmap


def _install_endpoint_spy(monkeypatch, chart_stack):
    controller = chart_stack.page_transition()
    calls = []

    def _capture(widget, *, exclude_overlay=False):
        calls.append((widget, exclude_overlay, controller._overlay.isVisible()))
        return _frame(widget, "#204080" if not exclude_overlay else "#d08020")

    monkeypatch.setattr(controller, "capture_local_endpoint", _capture)
    return calls


def _begin_light_transition(chart_stack, monkeypatch):
    chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    chart_stack.set_page_transition_enabled_sections(("time", "fft"))
    calls = _install_endpoint_spy(monkeypatch, chart_stack)
    token = chart_stack.begin_page_transition(
        source_section="time",
        source_view_id="view-A",
        target_section="fft",
        target_view_id="view-B",
        pane_signature=("single",),
    )
    assert token is not None
    return token, calls


def _plot_surface_image_bytes(chart_stack) -> int:
    rect = chart_stack.page_transition_plot_surface_rect()
    return max(0, rect.width()) * max(0, rect.height()) * 4


def test_policy_off_does_not_capture_or_open_a_transition_session(qtbot, monkeypatch):
    chart_stack = _stack(qtbot)
    chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    calls = _install_endpoint_spy(monkeypatch, chart_stack)

    token = chart_stack.begin_page_transition(
        source_section="time",
        source_view_id="view-A",
        target_section="fft",
        target_view_id="view-B",
    )

    assert token is None
    assert calls == []
    assert not chart_stack.page_transition().is_pending()
    assert chart_stack.page_transition().image_bytes() == 0


def test_measured_policy_does_not_enable_an_unadmitted_section(qtbot, monkeypatch):
    chart_stack = _stack(qtbot)
    chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    chart_stack.set_page_transition_enabled_sections(("time",))
    calls = _install_endpoint_spy(monkeypatch, chart_stack)

    token = chart_stack.begin_page_transition(
        source_section="fft",
        source_view_id="view-A",
        target_section="fft",
        target_view_id="view-B",
    )

    assert token is None
    assert calls == []
    assert chart_stack.page_transition().image_bytes() == 0


def test_light_transition_waits_for_natural_paint_then_fades_to_live_target(
    qtbot, monkeypatch,
):
    chart_stack = _stack(qtbot)
    token, calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _NaturalPaintFence()

    duration = duration_ms("page_transition", POLICY_LIGHT)
    assert duration == 240
    assert calls == [(chart_stack.stack, False, False)]
    assert chart_stack.request_page_transition_target(token, [fence])
    assert fence.requests == [token]
    # ``is_pending`` means "departure copied but target not armed".  Once the
    # fence is armed the one-frame source is retained, but no blend may run.
    assert not chart_stack.page_transition().is_pending()
    assert not chart_stack.page_transition().is_active()
    assert chart_stack.page_transition().image_bytes() == (
        _plot_surface_image_bytes(chart_stack)
    )
    assert len(calls) == 1

    # This replaces the former fixed-delay readiness assumption: only the
    # canvas's natural paint acknowledgement admits the crossfade.
    fence.acknowledge()

    # A GraphicsView paint callback must never synchronously grab another
    # QWidget.  The held source fades over the real target that natural paint
    # already proved, so no target endpoint is copied at all.
    assert calls == [(chart_stack.stack, False, False)]
    assert chart_stack.page_transition().is_active()
    assert chart_stack.page_transition().image_bytes() == (
        _plot_surface_image_bytes(chart_stack)
    )

    chart_stack.page_transition()._driver.clock().setCurrentTime(duration)
    qtbot.waitUntil(lambda: not chart_stack.page_transition().is_active())
    assert chart_stack.page_transition().image_bytes() == 0


def test_explicit_presentation_capture_cancels_active_transition(qtbot, monkeypatch):
    chart_stack = _stack(qtbot)
    token, _calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _NaturalPaintFence()
    assert chart_stack.request_page_transition_target(token, [fence])
    fence.acknowledge()
    qtbot.waitUntil(chart_stack.page_transition().is_active)

    # Copy/export must show the settled live page, never an old blend.  The
    # return value is intentionally incidental to this lifecycle contract.
    chart_stack.grab_presentation_pixmap(chart_stack.canvas_time, scale=1.0)

    assert not chart_stack.page_transition().is_active()
    assert not chart_stack.page_transition().is_pending()
    assert chart_stack.page_transition().image_bytes() == 0


def test_rapid_redirect_keeps_bridge_captured_visible_source_on_single_image_path(
    qtbot, monkeypatch,
):
    """The real bridge must feed a complete A/B capture into B -> C."""
    chart_stack = _stack(qtbot)
    chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    chart_stack.set_page_transition_enabled_sections(("time",))
    controller = chart_stack.page_transition()
    captures = iter(("#ff0000", "#7f0080"))

    def _capture(widget, *, exclude_overlay=False):
        return _frame(widget, next(captures))

    monkeypatch.setattr(controller, "capture_local_endpoint", _capture)
    token_b = chart_stack.begin_page_transition(
        source_section="time",
        source_view_id="view-A",
        target_section="time",
        target_view_id="view-B",
    )
    assert token_b is not None
    fence_b = _NaturalPaintFence()
    assert chart_stack.request_page_transition_target(token_b, (fence_b,))
    fence_b.acknowledge()
    assert controller.is_active()
    duration = duration_ms("page_transition", POLICY_LIGHT)
    controller._driver.clock().setCurrentTime(duration // 2)

    token_c = chart_stack.begin_page_transition(
        source_section="time",
        source_view_id="view-B",
        target_section="time",
        target_view_id="view-C",
    )

    assert token_c is not None
    assert controller._overlay._source.toImage().pixelColor(8, 8) == QColor("#7f0080")
    fence_c = _NaturalPaintFence()
    assert chart_stack.request_page_transition_target(token_c, (fence_c,))
    fence_c.acknowledge()
    controller._driver.clock().setCurrentTime(duration)
    qtbot.waitUntil(lambda: not controller.is_active())


def test_split_entry_cancels_a_single_pane_transition_and_its_paint_fence(
    qtbot, monkeypatch,
):
    chart_stack = _stack(qtbot)
    token, _calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _NaturalPaintFence()
    assert chart_stack.request_page_transition_target(token, (fence,))
    assert chart_stack._page_transition_ready_slots

    chart_stack.enter_split()

    assert chart_stack.page_transition().image_bytes() == 0
    assert chart_stack._page_transition_target is None
    assert chart_stack._page_transition_ready_slots == []
    fence.acknowledge(token)
    assert not chart_stack.page_transition().is_active()


def test_stale_ack_cannot_start_live_target_fade_and_rejected_ack_request_cancels(
    qtbot, monkeypatch,
):
    chart_stack = _stack(qtbot)
    token, calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _NaturalPaintFence()
    assert chart_stack.request_page_transition_target(token, [fence])

    # A signal from an obsolete render must not start a blend for the live
    # request.
    fence.acknowledge(object())
    assert len(calls) == 1
    assert not chart_stack.page_transition().is_pending()
    assert not chart_stack.page_transition().is_active()

    chart_stack.cancel_page_transition("new-selection")
    next_token, next_calls = _begin_light_transition(chart_stack, monkeypatch)
    rejected = _NaturalPaintFence(accepts_request=False)
    assert not chart_stack.request_page_transition_target(next_token, [rejected])
    assert next_calls == [(chart_stack.stack, False, False)]
    assert not chart_stack.page_transition().is_pending()
    assert not chart_stack.page_transition().is_active()
    assert chart_stack.page_transition().image_bytes() == 0


class _PaintAckOnlyFence(QObject):
    """Managed-canvas paint-ack without a content-invalidation contract."""

    presentation_paint_acknowledged = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.requests = []

    def request_presentation_paint_ack(self, request_id) -> bool:
        self.requests.append(request_id)
        return True

    def acknowledge(self, request_id=None) -> None:
        self.presentation_paint_acknowledged.emit(
            self.requests[-1] if request_id is None else request_id,
        )


def test_paint_ack_without_content_signal_does_not_start_fade(
    qtbot, monkeypatch,
):
    """E1: missing content fence is direct-terminal, not an optional listen."""
    chart_stack = _stack(qtbot)
    token, calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _PaintAckOnlyFence()
    cancelled = []
    chart_stack.page_transition().transition_cancelled.connect(cancelled.append)

    assert not chart_stack.request_page_transition_target(token, [fence])
    assert cancelled == ["target-has-no-content-fence"]
    assert fence.requests == []
    assert not chart_stack.page_transition().is_pending()
    assert not chart_stack.page_transition().is_active()
    assert chart_stack.page_transition().image_bytes() == 0
    assert calls == [(chart_stack.stack, False, False)]
    fence.acknowledge(token)
    assert not chart_stack.page_transition().is_active()


def _arm_live_target(qtbot, chart_stack, monkeypatch):
    token, _calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _LiveTarget(chart_stack)
    fence.setGeometry(8, 8, 160, 100)
    fence.show()
    qtbot.waitExposed(fence)
    assert chart_stack.request_page_transition_target(token, [fence])
    qtbot.waitUntil(chart_stack.page_transition().is_active, timeout=1000)
    return token, fence


def test_live_widget_natural_paint_completes_fade_without_manual_clock(
    qtbot, monkeypatch,
):
    chart_stack = _stack(qtbot)
    cancelled = []
    finished = []
    controller = chart_stack.page_transition()
    controller.transition_cancelled.connect(cancelled.append)
    controller.transition_finished.connect(finished.append)
    _token, fence = _arm_live_target(qtbot, chart_stack, monkeypatch)

    fence.update()
    QApplication.processEvents()
    QApplication.processEvents()

    assert controller.is_active()
    assert cancelled == []

    qtbot.waitUntil(lambda: not controller.is_active(), timeout=1500)
    assert cancelled == []
    assert finished
    assert controller.image_bytes() == 0
    assert chart_stack._page_transition_content_slots == []
    assert fence.updatesEnabled()


def test_ready_content_replacement_cancels_live_fade(qtbot, monkeypatch):
    chart_stack = _stack(qtbot)
    cancelled = []
    chart_stack.page_transition().transition_cancelled.connect(cancelled.append)
    _token, fence = _arm_live_target(qtbot, chart_stack, monkeypatch)
    assert chart_stack._page_transition_content_slots

    fence.presentation_content_invalidated.emit()

    assert cancelled == ["target-content-invalidated"]
    assert chart_stack.page_transition().image_bytes() == 0
    assert chart_stack._page_transition_target is None
    assert chart_stack._page_transition_content_slots == []


def test_pending_content_replacement_drops_cover_before_ack(qtbot, monkeypatch):
    chart_stack = _stack(qtbot)
    token, _calls = _begin_light_transition(chart_stack, monkeypatch)
    fence = _NaturalPaintFence()
    cancelled = []
    chart_stack.page_transition().transition_cancelled.connect(cancelled.append)
    assert chart_stack.request_page_transition_target(token, [fence])
    assert not chart_stack.page_transition().is_active()

    fence.presentation_content_invalidated.emit()

    assert cancelled == ["target-content-invalidated"]
    assert chart_stack.page_transition().image_bytes() == 0
    fence.acknowledge(token)
    assert not chart_stack.page_transition().is_active()


def test_rapid_live_redirect_cleans_up_and_finishes_on_c(qtbot, monkeypatch):
    chart_stack = _stack(qtbot)
    chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    chart_stack.set_page_transition_enabled_sections(("time",))
    controller = chart_stack.page_transition()
    captures = iter(("#ff0000", "#7f0080"))

    def _capture(widget, *, exclude_overlay=False):
        return _frame(widget, next(captures))

    monkeypatch.setattr(controller, "capture_local_endpoint", _capture)
    cancelled = []
    finished = []
    controller.transition_cancelled.connect(cancelled.append)
    controller.transition_finished.connect(finished.append)

    token_b = chart_stack.begin_page_transition(
        source_section="time",
        source_view_id="view-A",
        target_section="time",
        target_view_id="view-B",
    )
    fence_b = _LiveTarget(chart_stack)
    fence_b.setGeometry(8, 8, 160, 100)
    fence_b.show()
    assert chart_stack.request_page_transition_target(token_b, (fence_b,))
    qtbot.waitUntil(controller.is_active, timeout=1000)

    token_c = chart_stack.begin_page_transition(
        source_section="time",
        source_view_id="view-B",
        target_section="time",
        target_view_id="view-C",
    )
    assert token_c is not None
    fence_c = _LiveTarget(chart_stack)
    fence_c.setGeometry(8, 8, 160, 100)
    fence_c.show()
    assert chart_stack.request_page_transition_target(token_c, (fence_c,))
    qtbot.waitUntil(controller.is_active, timeout=1000)
    qtbot.waitUntil(lambda: not controller.is_active(), timeout=1500)

    assert cancelled == []
    assert finished
    assert controller.image_bytes() == 0


def test_time_tab_switch_completes_natural_fade(qtbot, qapp, loaded_csv):
    """Production View switch must restore, naturally ack, and finish without Paint cancel."""
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1400, 820)
    window.show()
    qtbot.waitExposed(window)
    window.load_file(loaded_csv)
    qapp.processEvents()
    window._on_view_new()
    qapp.processEvents()

    controller = window.chart_stack.page_transition()
    cancelled = []
    finished = []
    started = []
    controller.transition_started.connect(started.append)
    controller.transition_cancelled.connect(cancelled.append)
    controller.transition_finished.connect(finished.append)
    if window.view_manager.active != 0:
        window._switch_view(0)
        qtbot.waitUntil(
            lambda: controller.image_bytes() == 0 and not controller.is_active(),
            timeout=2500,
        )
        started.clear()
        cancelled.clear()
        finished.clear()

    stack = window.chart_stack.stack
    probe = controller.capture_local_endpoint(stack)
    assert not probe.isNull(), (
        f"outgoing capture empty: stack={stack.size()} visible={stack.isVisible()}"
    )

    viewport = window.canvas_time._glw.viewport()
    under_paints = []

    class _UnderPaintCounter(QObject):
        def eventFilter(self, watched, event):  # noqa: N802 - Qt callback spelling
            if event.type() == QEvent.Paint:
                under_paints.append(True)
            return False

    counter = _UnderPaintCounter(viewport)
    viewport.installEventFilter(counter)

    window.view_tabbar.switch_requested.emit(1)

    qtbot.waitUntil(
        lambda: bool(finished) or bool(cancelled),
        timeout=2500,
    )
    viewport.removeEventFilter(counter)
    assert cancelled == [], cancelled
    assert finished
    assert started
    assert not controller.is_active()
    assert controller.image_bytes() == 0
    assert window.view_manager.active == 1
    # Overlay frames must not drive a 60 Hz GraphicsView replay.  A few
    # natural/quality paints during the handoff are expected.
    assert len(under_paints) <= 8, len(under_paints)
