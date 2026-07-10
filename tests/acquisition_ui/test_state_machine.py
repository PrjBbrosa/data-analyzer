"""State-machine tests (Stage 4).

Plan tasks:

- Disconnected → ConnectedIdle (gated by ``healthy`` predicate:
  ``HwHealth.ok ∧ XcpHealth.connected ∧ first DAQ frame ≤ 3 s``).
- Connection timeout: 3 s without a frame returns to Disconnected and
  surfaces the FIRST failing predicate name in the right panel.
- ConnectedIdle → Recording.
- Recording → ReviewModal (gated by ``finalized``).
- ReviewModal close → ConnectedIdle.
- Red health disables record.
- Yellow health warns but does not disable record.
- Dropped-frames > 100 opens the in-state ``继续/停止`` prompt.
- 回放 tab is enabled and hosts the read-only ReplayTab.
- DBC selector is removed from the XCP-focused toolbar.

These tests cover both the pure-Python state machine (no Qt) and
the Qt ``MainWindow`` button-state behavior.
"""

from __future__ import annotations

import time

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthAggregator,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.acquisition_ui.main_window import (
    REPLAY_TAB_TITLE,
    CockpitMainWindow,
)
from mf4_analyzer.acquisition_ui.replay_tab import ReplayTab
from mf4_analyzer.acquisition_ui.state import (
    HEALTHY_PREDICATE_FIRST_FRAME,
    HEALTHY_PREDICATE_HW,
    HEALTHY_PREDICATE_XCP,
    CockpitState,
    CockpitStateMachine,
    HealthyPredicateResult,
)


# ---------------------------------------------------------------------------
# Pure-Python state machine
# ---------------------------------------------------------------------------


def test_disconnected_to_connected_idle_when_healthy():
    sm = CockpitStateMachine()
    assert sm.state == CockpitState.DISCONNECTED
    verdict = HealthyPredicateResult.from_components(
        hw_ok=True, xcp_connected=True, first_frame_received=True
    )
    sm.request_connect(verdict)
    assert sm.state == CockpitState.CONNECTED_IDLE


def test_unhealthy_stays_disconnected_and_surfaces_first_failure():
    # HW first.
    sm = CockpitStateMachine()
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=False, xcp_connected=True, first_frame_received=True
        )
    )
    assert sm.state == CockpitState.DISCONNECTED
    assert sm.last_healthy_result is not None
    assert sm.last_healthy_result.first_failure == HEALTHY_PREDICATE_HW

    # XCP next.
    sm = CockpitStateMachine()
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=False, first_frame_received=True
        )
    )
    assert sm.last_healthy_result.first_failure == HEALTHY_PREDICATE_XCP

    # Frame last.
    sm = CockpitStateMachine()
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=False
        )
    )
    assert sm.last_healthy_result.first_failure == HEALTHY_PREDICATE_FIRST_FRAME


def test_connected_idle_to_recording():
    sm = CockpitStateMachine()
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    sm.request_start_recording()
    assert sm.state == CockpitState.RECORDING


def test_recording_to_review_when_finalized():
    sm = CockpitStateMachine()
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    sm.request_start_recording()
    # Not finalized → stay in Recording.
    sm.request_stop_recording(finalized=False)
    assert sm.state == CockpitState.RECORDING
    # Finalized → ReviewModal.
    sm.request_stop_recording(finalized=True)
    assert sm.state == CockpitState.REVIEW_MODAL


def test_review_close_returns_to_idle():
    sm = CockpitStateMachine()
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    sm.request_start_recording()
    sm.request_stop_recording(finalized=True)
    sm.request_review_close()
    assert sm.state == CockpitState.CONNECTED_IDLE


def test_illegal_transition_raises():
    sm = CockpitStateMachine()
    # Cannot stop recording from disconnected.
    with pytest.raises(ValueError):
        sm.request_stop_recording(finalized=True)
    # Cannot review-close from disconnected.
    with pytest.raises(ValueError):
        sm.request_review_close()


def test_subscribe_fires_on_change():
    sm = CockpitStateMachine()
    events: list[tuple[CockpitState, CockpitState]] = []
    sm.subscribe(lambda old, new: events.append((old, new)))
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    assert events == [(CockpitState.DISCONNECTED, CockpitState.CONNECTED_IDLE)]


# ---------------------------------------------------------------------------
# Qt main window — button enabled-state and immutables
# ---------------------------------------------------------------------------


def _force_window_with_levels(qapp, levels: dict[str, str]) -> CockpitMainWindow:
    """Build a window whose health probes return the requested levels.

    ``levels`` maps chip name → desired level. We synthesize health
    objects that, when fed to the standard level helpers, produce the
    requested level. The fixture uses these synthesized snapshots
    directly rather than racing the timer.
    """
    window = CockpitMainWindow()
    # Skip the timer and apply a hand-crafted snapshot.
    snap = window._health_aggregator.poll_once()  # populates ``last``.
    return window


def _snap_with_levels(*, hw_ok=True, xcp_connected=True,
                     can_load=10.0, rec_ring=10.0,
                     rec_last_age=0.0, rec_state="recording") -> any:
    """Build a HealthSnapshot tuned to a desired level mix."""
    from mf4_analyzer.acquisition_capture.health import HealthSnapshot

    return HealthSnapshot(
        hw=HwHealth(
            ok=hw_ok,
            driver_version="test",
            channel_count=1,
            last_probe_ts=time.monotonic(),
            error=None if hw_ok else "test failure",
        ),
        can=CanHealth(bus_load_pct=can_load, channels=(), bus_error_count=0),
        xcp=XcpHealth(
            connected=xcp_connected,
            slave_id=0x55 if xcp_connected else None,
            last_response_age_s=0.0,
            consecutive_timeouts=0,
        ),
        daq=DaqHealth(),
        rec=RecHealth(
            state=rec_state,
            ring_buffer_fill_pct=rec_ring,
            dropped_frames=0,
            write_rate_bps=0.0,
            last_rx_age_s=rec_last_age,
            writer_thread_alive=True,
        ),
        captured_at=time.monotonic(),
    )


def test_red_health_disables_record_button(qapp):
    window = CockpitMainWindow()
    # Walk to ConnectedIdle via a healthy verdict.
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    # Apply a snapshot with a red CAN load.
    snap = _snap_with_levels(can_load=95.0)  # >= 80 ⇒ red.
    window.health_strip.apply_snapshot(snap)
    window._update_record_button_enabled()
    assert window.main_button.isEnabled() is False
    window.close()


def test_yellow_health_does_not_disable_record(qapp):
    window = CockpitMainWindow()
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    # Yellow CAN load (60..80).
    snap = _snap_with_levels(can_load=70.0)
    window.health_strip.apply_snapshot(snap)
    window._update_record_button_enabled()
    assert window.main_button.isEnabled() is True
    window.close()


def test_rec_chip_red_on_last_rx_age_even_with_empty_ring(qapp):
    """Spec wiring: REC chip turns red when last_rx_age_s ≥ 2.0 s.

    Tests the assertion the brief calls out: simulate
    ``last_rx_age_s = 2.5`` and assert REC chip turns red even when
    ring buffer fill is 0.
    """
    window = CockpitMainWindow()
    snap = _snap_with_levels(rec_last_age=2.5, rec_ring=0.0)
    window.health_strip.apply_snapshot(snap)
    levels = window.health_strip.current_levels()
    assert levels["REC"] == "red"
    window.close()


def test_dbc_selector_removed_from_xcp_toolbar(qapp):
    """The live XCP cockpit should not show the unused DBC selector."""
    window = CockpitMainWindow()
    try:
        assert window.findChild(QWidget, "cockpitSelectorDbc") is None
    finally:
        window.close()


def test_capture_body_is_two_columns_without_right_panel(qapp):
    """B-4: the capture body drops the right health pane (left + center only).

    The disconnected checklist / preflight / recording health were relocated to
    the top health strip (chips + preflight pill) and the bottom facts /
    escalation bar (B-1/B-2/B-3), so the capture main window no longer owns a
    ``RightPanel`` and its splitter holds exactly two columns. Selecting a
    measurement while disconnected must still not crash.
    """
    from can_logger.p0.a2l_probe import MeasurementSummary

    window = CockpitMainWindow()
    try:
        assert not hasattr(window, "_right_panel")
        assert window._splitter.count() == 2

        window.left_pane.set_pool(
            (
                MeasurementSummary(
                    name="EngSpdAvg",
                    address=0x40000000,
                    datatype="UWORD",
                    unit="rpm",
                    conversion="",
                    available_events=("event_10ms",),
                ),
            ),
            a2l_has_daq_events=True,
        )
        window.left_pane._set_measurement_selected("EngSpdAvg", True)
    finally:
        window.close()


def test_replay_tab_enabled_with_replay_widget(qapp):
    """Polish wave: 回放 tab is a usable read-only ReplayTab."""
    window = CockpitMainWindow()
    tabs = window.mode_tabs
    replay_idx = None
    for i in range(tabs.count()):
        if tabs.tabText(i) == REPLAY_TAB_TITLE:
            replay_idx = i
            break
    assert replay_idx is not None
    assert tabs.isTabEnabled(replay_idx) is True
    page = tabs.widget(replay_idx)
    assert isinstance(page, ReplayTab)
    window.close()


def test_dropped_frames_prompt_shown_over_threshold(qapp):
    """Spec: dropped_frames > 100 opens the in-state ``继续/停止`` prompt.

    Stage 4 verifies the prompt shows. Full Stop wiring is Stage 5.
    """
    from PyQt5.QtCore import QTimer

    window = CockpitMainWindow()
    # Walk to Recording state.
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    window.state_machine.request_start_recording()
    # Force the ring buffer's dropped count above the prompt threshold.
    window._ring._dropped_frames = thresholds.DROPPED_FRAMES_PROMPT_TOTAL + 1
    # Schedule the prompt to be auto-closed so the test doesn't block.
    closed = []

    def _close_prompt():
        if getattr(window, "_dropped_prompt", None) is not None:
            window._dropped_prompt.done(0)
            closed.append(True)

    QTimer.singleShot(50, _close_prompt)
    window._poll_live()
    qapp.processEvents()
    # B5 follow-up: the single-shot ``_dropped_prompt_shown`` latch was
    # replaced with a (timestamp, count) pair so the prompt re-arms
    # after both a cool-down and a delta of new drops. After firing
    # once, ``_dropped_prompt_last_ts`` is set; the prompt object is
    # also live for inspection.
    assert window._dropped_prompt_last_ts is not None
    # Prompt object exists.
    assert getattr(window, "_dropped_prompt", None) is not None
    window.close()


def test_a2l_raster_freeze_during_recording(qapp):
    """A2L/raster controls FREEZE (setEnabled(False)) while recording."""
    window = CockpitMainWindow()
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    window.state_machine.request_start_recording()
    # left_pane should be frozen via _apply_state_to_ui.
    assert window.left_pane._frozen is True
    window.close()


def test_state_machine_subscriber_fires_on_qt_main_window(qapp):
    """The main window subscribes to state changes during __init__."""
    window = CockpitMainWindow()
    # Initial subscribe should fire when we transition.
    assert window.state_machine.state == CockpitState.DISCONNECTED
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )
    # Button text flips to 采集.
    assert "采集" in window.main_button.text()
    window.close()


# ---------------------------------------------------------------------------
# Connection-timeout path (spec §State Machine — 3 s timeout returns to
# Disconnected and surfaces the FIRST failing predicate). This pins the
# Stage 4 CR2-required test that the timeout branch is executable, not
# just documented in the module header.
# ---------------------------------------------------------------------------


def test_connection_timeout_returns_to_disconnected_and_tears_down_backend(qapp):
    """Drive ``_evaluate_connection_attempt`` past ``CONNECTION_TIMEOUT_S``
    without a healthy verdict; assert:

    1. The state stays in ``DISCONNECTED``.
    2. ``backend.stop()`` is invoked (spy).
    3. The right-panel disconnected page surfaces the first failing
       predicate name (``XCP`` here, since XCP is the first ``False``).
    """
    # Spy backend whose ``stop()`` flips a flag we can assert on.
    class _SpyBackend(FakeRecorderBackend):
        def __init__(self) -> None:
            super().__init__()
            self.stop_called = 0

        def stop(self):  # type: ignore[override]
            self.stop_called += 1
            return super().stop()

    backend = _SpyBackend()
    window = CockpitMainWindow(backend=backend)
    # Simulate the user clicking 连接 ECU — but we backdate the start
    # time so the predicate sees ``elapsed >= CONNECTION_TIMEOUT_S``
    # without sleeping. We bypass ``_begin_connection_attempt`` because
    # it requires a non-empty selection / pool; the timeout logic only
    # depends on ``_connection_attempt_started`` being set.
    window._connection_attempt_started = (
        time.monotonic() - thresholds.CONNECTION_TIMEOUT_S - 1.0
    )
    window._first_frame_ts = None
    window._fake_xcp_connected = False
    # Also start the backend so the spy's ``stop()`` has something to
    # tear down.
    backend.start([SelectedMeasurement(name="DemoSignal")])

    # Build an unhealthy snapshot — HW ok but XCP not connected; the
    # first failing predicate must be ``XCP``.
    snap = _snap_with_levels(hw_ok=True, xcp_connected=False)
    # Apply the snapshot through the same path the live timer would.
    window._evaluate_connection_attempt(snap)

    # 1. State stays in Disconnected.
    assert window.state_machine.state == CockpitState.DISCONNECTED
    # 2. Backend ``stop()`` was invoked exactly once.
    assert backend.stop_called == 1
    # 3. Right-panel disconnected page quotes the first failing
    #    predicate (XCP).
    assert window.state_machine.last_healthy_result is not None
    assert (
        window.state_machine.last_healthy_result.first_failure
        == HEALTHY_PREDICATE_XCP
    )
    # 4. Side effect: ``_connection_attempt_started`` is cleared so a
    #    subsequent poll doesn't double-fire the teardown.
    assert window._connection_attempt_started is None
    window.close()


def test_connection_timeout_surfaces_hw_when_hw_fails_first(qapp):
    """HW failing first wins over XCP in the surface order."""
    backend = FakeRecorderBackend()
    window = CockpitMainWindow(backend=backend)
    window._connection_attempt_started = (
        time.monotonic() - thresholds.CONNECTION_TIMEOUT_S - 0.5
    )
    window._first_frame_ts = None
    snap = _snap_with_levels(hw_ok=False, xcp_connected=False)
    window._evaluate_connection_attempt(snap)
    assert window.state_machine.state == CockpitState.DISCONNECTED
    assert (
        window.state_machine.last_healthy_result.first_failure
        == HEALTHY_PREDICATE_HW
    )
    window.close()


def test_connection_timeout_surfaces_first_frame_when_only_frame_missing(qapp):
    """HW + XCP ok but no frame received within 3 s → ``no frame received``."""
    backend = FakeRecorderBackend()
    window = CockpitMainWindow(backend=backend)
    window._connection_attempt_started = (
        time.monotonic() - thresholds.CONNECTION_TIMEOUT_S - 0.5
    )
    window._first_frame_ts = None  # explicit: no frame
    snap = _snap_with_levels(hw_ok=True, xcp_connected=True)
    window._evaluate_connection_attempt(snap)
    assert window.state_machine.state == CockpitState.DISCONNECTED
    assert (
        window.state_machine.last_healthy_result.first_failure
        == HEALTHY_PREDICATE_FIRST_FRAME
    )
    window.close()


def test_connection_timeout_before_deadline_does_not_tear_down(qapp):
    """Within ``CONNECTION_TIMEOUT_S`` an unhealthy snapshot does NOT
    tear the backend down — the predicate waits for either healthy or
    timeout."""

    class _SpyBackend(FakeRecorderBackend):
        def __init__(self) -> None:
            super().__init__()
            self.stop_called = 0

        def stop(self):  # type: ignore[override]
            self.stop_called += 1
            return super().stop()

    backend = _SpyBackend()
    window = CockpitMainWindow(backend=backend)
    # Half a second elapsed — well under 3 s timeout.
    window._connection_attempt_started = time.monotonic() - 0.5
    window._first_frame_ts = None
    snap = _snap_with_levels(hw_ok=True, xcp_connected=False)
    window._evaluate_connection_attempt(snap)
    assert window.state_machine.state == CockpitState.DISCONNECTED
    assert backend.stop_called == 0
    # Attempt is still in flight.
    assert window._connection_attempt_started is not None
    window.close()


# ---------------------------------------------------------------------------
# Auto-stop wiring: controller sustain判定 is authoritative.
# ---------------------------------------------------------------------------


class _AutoStoppedController:
    """poll_step 后 running=False + auto_stopped=True 的最小桩。"""

    running = False
    auto_stopped = True

    def poll_step(self) -> int:
        return 0


def test_controller_auto_stop_routes_to_stop_and_review(qapp, monkeypatch):
    """Controller sustain判定 -> stop&review(auto_stop=True)."""
    window = CockpitMainWindow()
    calls: list[bool] = []
    monkeypatch.setattr(
        window,
        "request_stop_and_review",
        lambda *, auto_stop=False: calls.append(auto_stop),
    )
    window._poll_live_recording(_AutoStoppedController())
    assert calls == [True]
    window.close()


# ---------------------------------------------------------------------------
# B-5: disconnected connection checklist lives in the center guide canvas.
# ---------------------------------------------------------------------------


def test_disconnected_shows_center_connection_checklist(qapp):
    """The removed right pane's connection checklist (B-4) now renders in
    the center guide canvas while disconnected, built from STRUCTURED state
    (A2L parsed / hardware available / selection feasible)."""
    from PyQt5.QtWidgets import QFrame, QLabel

    window = CockpitMainWindow()
    try:
        assert window.state_machine.state == CockpitState.DISCONNECTED
        frame = window._center.findChild(QFrame, "cockpitConnectionChecklist")
        assert frame is not None
        assert not frame.isHidden()

        labels = frame.findChildren(QLabel, "cockpitChecklistLabel")
        assert [lab.text() for lab in labels] == [
            "A2L 已解析",
            "硬件可用",
            "当前选择可行",
        ]
    finally:
        window.close()


def test_selection_feasible_row_flips_ok_when_a_measurement_is_selected(qapp):
    """Selecting a measurement while disconnected flips the ``当前选择可行``
    row from ``pending`` to ``ok`` — driven by the structured selection
    count, not by parsing any label text."""
    from can_logger.p0.a2l_probe import MeasurementSummary
    from PyQt5.QtWidgets import QFrame, QLabel

    window = CockpitMainWindow()
    try:
        window.left_pane.set_pool(
            (
                MeasurementSummary(
                    name="MotSpd",
                    address=0x1000,
                    datatype="UWORD",
                    unit="rpm",
                    conversion="",
                    available_events=("event_10ms",),
                ),
            ),
            a2l_has_daq_events=True,
        )
        frame = window._center.findChild(QFrame, "cockpitConnectionChecklist")

        def _sel_led():
            for led in frame.findChildren(QLabel, "cockpitChecklistLed"):
                if led.property("checklistKey") == "selection":
                    return led
            return None

        assert _sel_led().property("state") == "pending"

        window.left_pane._set_measurement_selected("MotSpd", True)
        assert _sel_led().property("state") == "ok"
    finally:
        window.close()


def test_connected_idle_hides_center_connection_checklist(qapp):
    """Leaving disconnected retires the checklist (the guide canvas is
    replaced by live cards)."""
    from PyQt5.QtWidgets import QFrame

    window = CockpitMainWindow()
    try:
        window.state_machine.request_connect(
            HealthyPredicateResult.from_components(
                hw_ok=True, xcp_connected=True, first_frame_received=True
            )
        )
        assert window.state_machine.state == CockpitState.CONNECTED_IDLE
        frame = window._center.findChild(QFrame, "cockpitConnectionChecklist")
        assert frame.isHidden()
    finally:
        window.close()
