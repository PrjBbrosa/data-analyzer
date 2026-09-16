"""ChartStack's local page-transition bridge contracts.

The compositor itself is covered by ``test_page_transition.py``.  These tests
exercise the bridge which owns the important ordering: a normal navigation
commits first, the outgoing page is copied once, a target canvas must report a
natural paint, and only then may ChartStack fade that source over the live
target.  It never synchronously captures the incoming endpoint.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF, duration_ms


class _NaturalPaintFence(QObject):
    """A deterministic canvas-side natural-paint acknowledgement seam."""

    presentation_paint_acknowledged = pyqtSignal(object)

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

    assert duration_ms("page_transition", POLICY_LIGHT) == 300
    assert calls == [(chart_stack.stack, False, False)]
    assert chart_stack.request_page_transition_target(token, [fence])
    assert fence.requests == [token]
    # ``is_pending`` means "departure copied but target not armed".  Once the
    # fence is armed the one-frame source is retained, but no blend may run.
    assert not chart_stack.page_transition().is_pending()
    assert not chart_stack.page_transition().is_active()
    assert chart_stack.page_transition().image_bytes() == (
        chart_stack.stack.width() * chart_stack.stack.height() * 4
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
        chart_stack.stack.width() * chart_stack.stack.height() * 4
    )

    chart_stack.page_transition()._driver.clock().setCurrentTime(300)
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
    controller._driver.clock().setCurrentTime(150)

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
    controller._driver.clock().setCurrentTime(300)
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
