"""Cockpit ``QMainWindow``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
Plan: ``docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md``
Polish wave: ``docs/analyzer/acquisition/specs/2026-05-15-cockpit-polish-wave-spec.md``

Current deliverables wired up here:

- Toolbar with A2L/output controls, Settings, segment marker,
  mode label (`采集 / 回放 / 历史`), REC indicator, and stateful main
  button (`连接 ECU` / `● 采集` / `■ Stop && 复盘`).
- 32 px health strip beneath the toolbar driven by
  ``HealthAggregator.poll_once()`` polled on a ``QTimer`` at
  ``thresholds.HEALTH_POLL_INTERVAL_S``.
- Three-pane center body: A2L left pane, center live cards, right
  state-aware inspector.
- Real read-only Replay tab and manifest-backed History tab.
- Four-state machine (in :mod:`state`) driving page transitions,
  control freeze, and button labels.
- ``RingBuffer.watermark_changed`` (the non-Qt observer shim) bridged
  to a Qt slot via the shim's ``connect`` API: 30 fps for
  green/yellow_low, 10 fps for red/red_drop, auto-stop on
  red_drop_sustained.
- Stop/flush/finalize, ReviewModal, archive, and Analyzer handoff.
  The no-controller demo path still uses a small placeholder modal.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAction,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.backends import (
    FakeRecorderBackend,
    RecorderBackend,
)
from mf4_analyzer.acquisition_capture.config_store import ConfigSchemaError
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import SessionSummary
from mf4_analyzer.acquisition_capture.health import HealthAggregator
from mf4_analyzer.acquisition_capture.ring_buffer import RingBuffer
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_ui.history_tab import HistoryTab
from mf4_analyzer.acquisition_ui.replay_tab import ReplayTab
from mf4_analyzer.acquisition_ui.review_modal import (
    ACTION_SAVE_AND_ARCHIVE,
    ReviewContext,
    ReviewModal,
    StopFlushFinalizeResult,
    run_stop_flush_finalize,
)
from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    CockpitStateMachine,
)
from mf4_analyzer.acquisition_ui.widgets.escalation_bar import EscalationBar
from mf4_analyzer.acquisition_ui.widgets.health_strip import HealthStrip
from mf4_analyzer.acquisition_ui.widgets.left_pane import LeftPane
from ._defs import (
    DEFAULT_LIVE_PIN_COUNT,
    HISTORY_TAB_TITLE,
    MODE_SEGMENTS,
    REPLAY_TAB_TITLE,
)
from ._toolbar_mixin import ToolbarMixin
from ._connection_mixin import ConnectionMixin
from ._polling_mixin import PollingMixin
from ._settings_mixin import SettingsMixin
from ._capture_session_mixin import CaptureSessionMixin

from can_logger.p0.a2l_probe import MeasurementSummary


class _PlaceholderReviewModal(QDialog):
    """Fallback review modal for paths without a session result."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewModalPlaceholder")
        self.setWindowTitle("复盘（无会话数据）")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(QLabel("本次录制没有可复盘的会话数据。"))
        layout.addWidget(QLabel("点击「关闭」回到「已连接 · 待机」状态。"))
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class CockpitMainWindow(
    ToolbarMixin,
    ConnectionMixin,
    PollingMixin,
    SettingsMixin,
    CaptureSessionMixin,
    QMainWindow,
):
    """Acquisition Cockpit window — same-process partner of Analyzer.

    Construction parameters:

    ``backend``
        A ``RecorderBackend`` instance. Defaults to
        :class:`FakeRecorderBackend` so ``--demo`` works on macOS
        without Vector packages.
    ``health_aggregator``
        Optional pre-configured ``HealthAggregator``. The window
        installs its own probes for the demo path (Hw stub, fake
        Can/Xcp/Daq/Rec snapshots that pull from the live state).
    ``initial_pool``
        Optional list of ``MeasurementSummary`` to seed the left
        pane in demo mode.
    ``allow_fake_backend``
        Explicit opt-in for the demo path. Production/vehicle
        windows should leave this false so a failed Vector swap blocks
        the connection attempt instead of silently starting synthetic
        data.
    """

    # Public Qt signals — the auto-stop handler is wired here.
    auto_stop_requested = pyqtSignal(str)  # arg: reason ("ring_buffer" / "disk")

    # Re-arm gating constants for the dropped-frame prompt (B5).
    # ``REARM_S`` is the minimum wall-clock interval between two prompts;
    # ``REARM_DELTA`` is the minimum new drops the user must accumulate
    # before re-prompting. Both gates must clear so a one-off click on
    # the close button can't drown the user during a single bad burst,
    # but persistent drops still surface a second time.
    _DROPPED_PROMPT_REARM_S = 5.0
    _DROPPED_PROMPT_REARM_DELTA = 200

    def __init__(
        self,
        *,
        backend: RecorderBackend | None = None,
        health_aggregator: HealthAggregator | None = None,
        initial_pool: Iterable[MeasurementSummary] | None = None,
        config_path: Path | None = None,
        allow_fake_backend: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AcquisitionCockpit")
        self.setWindowTitle("MF4 采集 Cockpit")
        self.resize(1280, 760)
        # Spec §S4.2 — clamp the window so the toolbar's primary action
        # and REC indicator never clip when the user drags the frame
        # narrower than ~1100px. Additive; resize(1280, 760) stays.
        self.setMinimumSize(960, 600)
        self._settings_load_error: str | None = None
        self._load_threshold_overrides()

        # ----- core state ------------------------------------------------
        self._state_machine = CockpitStateMachine()
        self._state_machine.subscribe(self._on_state_changed)
        self._backend: RecorderBackend = backend or FakeRecorderBackend()
        self._external_backend = backend is not None and not isinstance(
            backend, FakeRecorderBackend
        )
        self._owns_vector_backend = False
        self._ring = RingBuffer(capacity=thresholds.DEFAULT_RING_CAPACITY)
        # Bridge the non-Qt observer to a Qt slot. The shim's connect
        # API matches pyqtSignal.connect — synchronous, single-arg.
        self._ring.watermark_changed.connect(self._on_ring_watermark_changed)
        self._target_fps = thresholds.LIVE_FPS_NORMAL
        self._connection_attempt_started: float | None = None
        self._connection_ever_attempted: bool = False
        self._first_frame_ts: float | None = None
        self._rec_start_ts: float | None = None
        self._stream_start_ts: float | None = None
        self._a2l_name: str | None = None
        # Last observed hardware availability (from the health poll's
        # ``snapshot.hw.ok``). Cached so the disconnected connection
        # checklist (B-5) can be refreshed from state transitions /
        # selection edits without re-polling the aggregator. ``None`` =
        # not yet probed → grey ``off`` dot.
        self._last_hw_ok: bool | None = None
        self._output_dir_label = "data/runs"
        self._cumulative_rx_count = 0
        self._cumulative_dropped = 0
        # Dropped-frame prompt re-arming: replaced the single-shot
        # ``_dropped_prompt_shown`` latch with a (timestamp, count)
        # pair so the user is re-notified when frames keep dropping
        # after the first prompt is dismissed (B5).
        self._dropped_prompt_last_ts: float | None = None
        self._dropped_prompt_last_count: int = 0
        self._fake_rec_state: str = "off"
        self._fake_last_rx_monotonic: float | None = None
        self._fake_xcp_connected: bool = False
        self._fake_can_load_pct: float | None = None
        self._transport_config = None
        self._ifdata_xcp = None
        self._allow_fake_backend = bool(allow_fake_backend)
        if self._allow_fake_backend:
            self.setWindowTitle(self.windowTitle() + " · 演示模式")
        # T1-6: optional persistent config path. When set, the cockpit
        # rehydrates Transport on startup and writes it back on every
        # Settings save. ``None`` keeps the legacy in-memory-only
        # behavior used by the bulk of the test fixtures.
        self._config_path: Path | None = (
            Path(config_path) if config_path is not None else None
        )
        # User-supplied A2L pool for the left pane (None in pure demo).
        self._initial_pool = tuple(initial_pool or ())
        # Spec 2026-07-08 §G6 — 固定实时显示。
        self._manual_pins: list[str] = []
        self._pin_customized: bool = False
        # CaptureSessionMixin owns the real CaptureController lifecycle.
        # Tests can still inject a controller via
        # :meth:`set_capture_controller`.
        # ``_last_session_summary`` carries the ``auto_stop=True`` flag
        # forward to the review modal path.
        self._capture_controller: CaptureController | None = None
        self._last_session_summary: SessionSummary | None = None
        self._review_modal: QDialog | None = None
        self._settings_dialog = None
        self._connection_warning_box: QMessageBox | None = None
        # The most recent stop/flush/finalize run, used by tests and
        # history/review flows to introspect ordering.
        self._last_stop_result: StopFlushFinalizeResult | None = None
        self._write_rate_prev: tuple[int, float] | None = None
        # Optional Analyzer handoff sink — tests inject a spy to
        # observe ``MainWindow.load_file`` calls without spinning up a
        # real Analyzer window. When ``None`` the cockpit walks
        # ``QApplication.topLevelWidgets()`` to find an Analyzer instance.
        self._analyzer_handoff: "Callable[[str], None] | None" = None  # type: ignore[name-defined]
        # The review-modal action selected on
        # the last review modal close (one of the four spec action
        # constants, or ``None`` when the modal was dismissed without
        # an explicit click or the placeholder path was used).
        self._last_review_action: str | None = None
        # Optional manifest target for ``保存并归档``. Tests pass tmp_path
        # manifests via :meth:`set_manifest_target`.
        self._manifest_path: Path | None = None

        # ----- health aggregator ----------------------------------------
        # Hook the aggregator's probes into the Cockpit's own simulated
        # state so the demo path produces realistic snapshots.
        self._health_aggregator = health_aggregator or HealthAggregator(
            hw_probe=self._probe_hw,
            can_probe=self._probe_can,
            xcp_probe=self._probe_xcp,
            daq_probe=self._probe_daq,
            rec_probe=self._probe_rec,
        )

        # ----- timers ----------------------------------------------------
        # Health poll — caller-driven per spec.
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(int(thresholds.HEALTH_POLL_INTERVAL_S * 1000))
        self._health_timer.timeout.connect(self._poll_health)

        # Live data poll. Repaints at ``self._target_fps``.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(int(1000 / self._target_fps))
        self._live_timer.timeout.connect(self._poll_live)

        # Idle selection edits change the backend's selected stream
        # only after a short debounce (spec 2026-07-07 F5).
        self._idle_restart_timer = QTimer(self)
        self._idle_restart_timer.setSingleShot(True)
        self._idle_restart_timer.setInterval(300)
        self._idle_restart_timer.timeout.connect(
            self._restart_idle_stream_for_selection
        )

        # ----- UI scaffolding -------------------------------------------
        self._build_ui()
        self._apply_state_to_ui(CockpitState.DISCONNECTED, CockpitState.DISCONNECTED)
        if self._initial_pool:
            self._left_pane.set_pool(self._initial_pool)

        # T1-6: hydrate from acquisition_config.yaml AFTER _build_ui so
        # the toolbar chip / left pane both exist when we push values
        # into them.
        self._hydrate_from_config_path()
        if not self._health_timer.isActive():
            self._health_timer.start()
        self._poll_health()

    # ------------------------------------------------------------------
    # UI scaffolding
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toolbar = self._build_toolbar()
        outer.addWidget(self._toolbar)

        self._health_strip = HealthStrip(self)
        self._health_strip.levels_changed.connect(self._on_health_levels_changed)
        outer.addWidget(self._health_strip)

        # Mode tabs — spec §Toolbar: `采集 / 回放 / 历史`.
        self._mode_tabs = QTabWidget(self)
        self._mode_tabs.setObjectName("cockpitModeTabs")
        self._neutralize_mode_tab_bar()
        # 采集 page is the three-pane layout.
        self._mode_tabs.addTab(self._build_acquisition_page(), "采集")
        self._replay_tab = ReplayTab(parent=self)
        self._mode_tabs.addTab(self._replay_tab, REPLAY_TAB_TITLE)
        self._history_tab = HistoryTab(parent=self)
        self._history_tab.analyzer_open_requested.connect(
            self._on_analyzer_open_requested
        )
        self._mode_tabs.addTab(self._history_tab, HISTORY_TAB_TITLE)
        self._mode_tabs.currentChanged.connect(self._on_mode_tab_changed)
        outer.addWidget(self._mode_tabs, stretch=1)
        self._sync_mode_segment(self._mode_tabs.currentIndex())

        self.setCentralWidget(central)
        self._status = QStatusBar(self)
        self.setStatusBar(self._status)
        self._backend_badge = QLabel(self)
        self._backend_badge.setObjectName("cockpitBackendBadge")
        self._status.addPermanentWidget(self._backend_badge)
        self._help_btn = QToolButton(self)
        self._help_btn.setObjectName("cockpitHelpButton")
        self._help_btn.setText("?")
        self._help_btn.setToolTip("采集使用说明")
        self._help_btn.setAutoRaise(True)
        self._help_btn.setCursor(Qt.PointingHandCursor)
        self._help_btn.setFixedSize(24, 24)
        self._help_btn.clicked.connect(self._open_acquisition_guide)
        self._status.addPermanentWidget(self._help_btn)

        # Escalation banner: a single-row overlay ABOVE the status bar (Spec
        # §B6). Parented to the window and NOT added to ``outer``, so its
        # appear/disappear never reflows the splitter / LiveCardGrid. A single
        # ``bar.apply(state)`` drives both the banner and the strip's REC
        # pulse via the wired ``applied`` signal.
        self._escalation_bar = EscalationBar(self)
        self._escalation_bar.applied.connect(self._health_strip.apply_escalation)
        self._escalation_bar.details_requested.connect(
            self._health_strip.open_chip_detail
        )
        self._escalation_bar.reanchor(self._status)

        self._update_backend_badge()
        self._update_status_bar()
        if self._settings_load_error:
            self._status.showMessage(f"设置加载失败: {self._settings_load_error}")

    def _load_threshold_overrides(self) -> None:
        try:
            thresholds.apply_overrides(thresholds.load_user_settings())
        except (ConfigSchemaError, OSError, UnicodeDecodeError) as exc:
            self._settings_load_error = str(exc)
            logger.warning("could not load acquisition settings: %s", exc)

    def _on_mode_tab_changed(self, index: int) -> None:
        self._sync_mode_segment(index if index >= 0 else 0)

    # ------------------------------------------------------------------
    # State transitions / button label management
    # ------------------------------------------------------------------

    def _on_state_changed(
        self, old: CockpitState, new: CockpitState
    ) -> None:
        self._apply_state_to_ui(old, new)

    def _apply_state_to_ui(
        self, old: CockpitState, new: CockpitState
    ) -> None:
        if hasattr(self, "_segment_action"):
            segment_visible = new == CockpitState.RECORDING
            self._segment_action.setVisible(segment_visible)
            if hasattr(self, "_segment_btn"):
                self._segment_btn.setVisible(segment_visible)
        if new == CockpitState.DISCONNECTED:
            self._main_btn.setText("连接 ECU")
            self._main_btn.setEnabled(True)
            self._set_visual_property(self._main_btn, "cockpitAction", "connect")
            self._rec_indicator.setText("● REC OFF")
            self._set_visual_property(self._rec_indicator, "recState", "off")
            # Preflight pill visible but disabled (`连接后可用`) while
            # disconnected (Spec §B2 visibility contract).
            if hasattr(self, "_health_strip"):
                self._health_strip.apply_preflight(state="disconnected")
            self._update_status_bar()
            self._center.set_recording(False, None)
            # B-5: the guide canvas hosts the connection checklist while
            # disconnected (the removed right pane's destination, B-4).
            self._update_connection_checklist()
        elif new == CockpitState.CONNECTED_IDLE:
            self._main_btn.setText("● 采集")
            self._set_visual_property(self._main_btn, "cockpitAction", "record")
            self._rec_indicator.setText("● REC OFF")
            self._set_visual_property(self._rec_indicator, "recState", "off")
            self._center.set_recording(False, None)
            self._refresh_idle_preflight()
            self._update_status_bar()
            # Update record-button enabled state based on latest health.
            self._update_record_button_enabled()
            # B-5: leaving disconnected retires the checklist (the guide
            # canvas is replaced by live cards anyway).
            self._center.set_connection_checklist(None)
        elif new == CockpitState.RECORDING:
            if self._rec_start_ts is None:
                self._rec_start_ts = time.monotonic()
            self._main_btn.setText("■ Stop && 复盘")
            self._main_btn.setEnabled(True)
            self._set_visual_property(self._main_btn, "cockpitAction", "stop")
            self._rec_indicator.setText("● REC")
            self._set_visual_property(self._rec_indicator, "recState", "recording")
            self._left_pane.set_frozen(True)
            self._center.set_recording(True, self._rec_start_ts)
            # Recording hides the preflight pill; the strip is a fixed-height
            # row so this never reflows the body (Spec §B2 zero-shift).
            if hasattr(self, "_health_strip"):
                self._health_strip.apply_preflight(state="recording")
            self._update_status_bar()
            self._center.set_connection_checklist(None)
        elif new == CockpitState.REVIEW_MODAL:
            self._main_btn.setEnabled(False)
            self._set_visual_property(self._main_btn, "cockpitAction", "disabled")
            self._rec_indicator.setText("● REC OFF")
            self._set_visual_property(self._rec_indicator, "recState", "off")
            self._left_pane.set_frozen(False)
            self._status.showMessage("复盘")
            self._open_review_modal()

    def _update_connection_checklist(
        self, snapshot: "HealthSnapshot | None" = None
    ) -> None:
        """Refresh the disconnected-state center checklist (B-5).

        The three rows are derived from STRUCTURED state — A2L parsed,
        hardware available, current selection feasible — never by parsing
        free text. This is a no-op destination (``None``) unless the state
        machine is currently disconnected; :meth:`_apply_state_to_ui`
        already hides the list on every other state.
        """
        if not hasattr(self, "_center"):
            return
        if self._state_machine.state != CockpitState.DISCONNECTED:
            return
        if snapshot is not None:
            self._last_hw_ok = snapshot.hw.ok

        # Row 1 — A2L parsed: a user-loaded A2L stamps ``_a2l_name``; the
        # demo / injected path seeds ``_initial_pool`` instead.
        a2l_loaded = self._a2l_name is not None or bool(self._initial_pool)
        if a2l_loaded:
            a2l_state = "ok"
            a2l_detail = self._a2l_name or "已载入"
        else:
            a2l_state = "pending"
            a2l_detail = "未载入"

        # Row 2 — hardware available: cached from the last health poll.
        hw_ok = self._last_hw_ok
        if hw_ok is None:
            hw_state, hw_detail = "off", "未探测"
        elif hw_ok:
            hw_state, hw_detail = "ok", "正常"
        else:
            hw_state, hw_detail = "pending", "未连接"

        # Row 3 — current selection feasible: at least one measurement
        # selected in the left pane.
        selection = (
            self._left_pane.current_selection()
            if hasattr(self, "_left_pane")
            else []
        )
        count = len(selection)
        if count > 0:
            sel_state, sel_detail = "ok", f"{count} 项已选"
        else:
            sel_state, sel_detail = "pending", "未选择"

        self._center.set_connection_checklist(
            [
                ("a2l", "A2L 已解析", a2l_state, a2l_detail),
                ("hw", "硬件可用", hw_state, hw_detail),
                ("selection", "当前选择可行", sel_state, sel_detail),
            ]
        )

    # ------------------------------------------------------------------
    # Main button handler
    # ------------------------------------------------------------------

    def _on_main_button(self) -> None:
        st = self._state_machine.state
        if st == CockpitState.DISCONNECTED:
            self._begin_connection_attempt()
        elif st == CockpitState.CONNECTED_IDLE:
            self._start_recording()
        elif st == CockpitState.RECORDING:
            self.request_stop_and_review()
        # Review modal close is driven by the dialog's finished signal.

    def request_stop_and_review(self, *, auto_stop: bool = False) -> None:
        """Run stop/flush/finalize and open review.

        Called from:
        - the toolbar Stop button (``_on_main_button``),
        - the dropped-frames prompt's ``停止并复盘`` button,
        - the auto-stop request slot (when the user is mid-recording).

        ``auto_stop=True`` arms ``SessionSummary.auto_stop`` even when
        the controller's own summary did not flag it (the auto-stop
        request can arrive from the disk-free predicate, which doesn't
        flow through the controller's auto-stop accounting).
        """
        if self._state_machine.state != CockpitState.RECORDING:
            return
        self._rec_start_ts = None
        # Build expected_channels verbatim from the current selection so
        # the post-record diagnostics check matches the writer's
        # channel-naming contract (spec §Recorder Backend).
        selection = (
            self._left_pane.current_selection()
            if hasattr(self, "_left_pane")
            else []
        )
        expected_channels: tuple[str, ...] = tuple(m.name for m in selection)
        result: StopFlushFinalizeResult | None = None
        finalized = False
        if self._capture_controller is not None:
            try:
                result = run_stop_flush_finalize(
                    controller=self._capture_controller,
                    expected_channels=expected_channels,
                    compute_sha=False,  # SHA on archive only — review modal decides
                )
                finalized = True
                self._last_stop_result = result
                if auto_stop:
                    result.summary.auto_stop = True
                self._last_session_summary = result.summary
            except Exception as exc:  # noqa: BLE001 — keep UI responsive on stop error
                logger.exception("stop/flush/finalize failed: %s", exc)
                # Surface to the status bar; stay in Recording so the
                # user can retry.
                self._status.showMessage(f"停止失败: {exc}")
                return
        else:
            # No controller/result — arm a stub summary so
            # downstream callers can still inspect ``auto_stop``.
            self._last_session_summary = SessionSummary(auto_stop=auto_stop)
            finalized = True

        # Drive the state machine.
        self._state_machine.request_stop_recording(finalized=finalized)
        # ``_apply_state_to_ui(REVIEW_MODAL)`` will open the modal in
        # response to the state change. It picks the real review modal
        # when ``result is not None`` and falls back to the no-session
        # placeholder otherwise.

    def _reset_connection_attempt_state(self) -> None:
        self._connection_attempt_started = None
        self._stream_start_ts = None
        self._first_frame_ts = None
        self._fake_xcp_connected = False
        self._fake_rec_state = "off"
        self._fake_can_load_pct = None

    def _stop_backend_best_effort(self, backend: RecorderBackend) -> None:
        try:
            backend.stop()
        except Exception as exc:  # noqa: BLE001 - cleanup must not mask UI flow
            logger.warning("backend cleanup failed: %s", exc)

    def resizeEvent(self, event):  # noqa: N802 - Qt API name
        """Keep the escalation overlay anchored above the status bar.

        The banner is an overlay (not in the body layout), so re-anchoring it
        on resize can never shift the splitter / ``LiveCardGrid`` geometry.
        """
        super().resizeEvent(event)
        bar = getattr(self, "_escalation_bar", None)
        if bar is not None and hasattr(self, "_status"):
            bar.reanchor(self._status)

    def closeEvent(self, event):  # noqa: N802 - Qt API name
        """Drain timers and the backend before destruction (B4).

        Without this, closing the cockpit window while a Vector backend
        is running leaks the hardware handle: the next connection
        attempt fails with 'channel busy'. Timers fire against a
        destroyed parent and Qt logs warnings. Best-effort everywhere
        because closeEvent must not raise.
        """
        try:
            if getattr(self, "_live_timer", None) is not None and self._live_timer.isActive():
                self._live_timer.stop()
        except Exception:  # noqa: BLE001 - cleanup best-effort
            pass
        try:
            if getattr(self, "_health_timer", None) is not None and self._health_timer.isActive():
                self._health_timer.stop()
        except Exception:  # noqa: BLE001 - cleanup best-effort
            pass
        try:
            if getattr(self, "_backend", None) is not None:
                self._stop_backend_best_effort(self._backend)
        except Exception:  # noqa: BLE001 - cleanup best-effort
            pass
        super().closeEvent(event)

    def _start_recording(self) -> None:
        # Spec: red health disables record. The button enabled state
        # already enforces this — defensive double-check here.
        if not self._main_btn.isEnabled():
            return
        levels = self._health_strip.current_levels()
        if any(level == "red" for level in levels.values()):
            return
        if not self._begin_capture_session():
            return
        self._rec_start_ts = time.monotonic()
        self._fake_rec_state = "recording"
        self._cumulative_rx_count = 0
        self._cumulative_dropped = 0
        # Re-arm the dropped-frame prompt for the new session (B5).
        self._dropped_prompt_last_ts = None
        self._dropped_prompt_last_count = 0
        self._state_machine.request_start_recording()

    def _open_review_modal(self) -> None:
        """Open the review modal when stop/flush/finalize ran,
        otherwise fall back to the no-session placeholder.

        Spec §State Machine `ReviewModal` requires the four-action set;
        the real :class:`ReviewModal` implements it. The placeholder
        remains for the no-controller fallback path so the four-state cycle
        is observable end-to-end during development.
        """
        if self._last_stop_result is not None:
            # CR3 finding 4: ReviewContext.expected_channels MUST equal
            # the selected measurement names tuple that was passed into
            # diagnostics — NOT PreflightResult.channels (which is just
            # "what we ended up writing" and so silences the manifest's
            # missing-channel detection forever). Fall back to a fresh
            # selection only when the stop sequence ran with no expected
            # channels (demo / no-selection paths).
            selected_names = self._last_stop_result.selected_measurement_names
            if not selected_names:
                selected_names = tuple(
                    m.name for m in (
                        self._left_pane.current_selection()
                        if hasattr(self, "_left_pane")
                        else []
                    )
                )
            ctx = ReviewContext(
                mf4_path=Path(self._last_stop_result.summary.output_mf4),
                sidecar_path=self._last_stop_result.sidecar_path,
                summary=self._last_stop_result.summary,
                preflight=self._last_stop_result.preflight,
                preflight_sidecar_path=self._last_stop_result.preflight_sidecar_path,
                expected_channels=selected_names,
                manifest_path=self._manifest_path,
            )
            modal = ReviewModal(ctx, self)
            modal.analyzer_open_requested.connect(self._on_analyzer_open_requested)
            modal.finished.connect(self._on_review_modal_closed)
            modal.open()
            self._review_modal = modal
        else:
            # No controller/result — placeholder so the cycle terminates.
            modal = _PlaceholderReviewModal(self)
            modal.finished.connect(self._on_review_modal_closed)
            modal.open()
            self._review_modal = modal

    def _on_review_modal_closed(self, _result: int) -> None:
        # Capture the chosen action (real modal only) BEFORE the
        # reference is dropped, so callers / tests can introspect.
        modal = self._review_modal
        if isinstance(modal, ReviewModal):
            self._last_review_action = modal.chosen_action
            if (
                self._last_review_action == ACTION_SAVE_AND_ARCHIVE
                and hasattr(self, "_history_tab")
            ):
                self._history_tab.reload()
        self._review_modal = None
        # Reset stop_result so the next REVIEW_MODAL entry rebuilds
        # context from a fresh stop sequence.
        self._last_stop_result = None
        try:
            self._state_machine.request_review_close()
        except ValueError:
            # Modal closed after the state moved elsewhere — ignore.
            pass
        if self._capture_controller is not None:
            self._teardown_capture_session()
            self._resume_idle_stream()

    def _on_analyzer_open_requested(self, mf4_path: str) -> None:
        """Bridge the review modal's ``在 Analyzer 打开`` signal to the
        public Analyzer handoff (``MainWindow.load_file``).

        Production path walks ``QApplication.topLevelWidgets()`` to find
        an existing Analyzer ``MainWindow``; if none exists we create
        one. Tests inject ``_analyzer_handoff`` to spy.
        """
        if self._analyzer_handoff is not None:
            try:
                self._analyzer_handoff(mf4_path)
            except Exception:  # noqa: BLE001
                logger.exception("analyzer handoff sink raised")
            return
        # Production path: find or create the Analyzer MainWindow.
        try:
            from PyQt5.QtWidgets import QApplication

            from mf4_analyzer.ui.main_window import MainWindow as AnalyzerMainWindow

            analyzer: AnalyzerMainWindow | None = None
            for w in QApplication.topLevelWidgets():
                if isinstance(w, AnalyzerMainWindow):
                    analyzer = w
                    break
            if analyzer is None:
                analyzer = AnalyzerMainWindow()
                analyzer.show()
            analyzer.load_file(mf4_path)
            analyzer.raise_()
            analyzer.activateWindow()
        except Exception:  # noqa: BLE001
            logger.exception("could not hand off MF4 to Analyzer")

    # ------------------------------------------------------------------
    # Controller injection.
    # ------------------------------------------------------------------

    def set_capture_controller(
        self, controller: CaptureController | None
    ) -> None:
        """Attach the live :class:`CaptureController` for auto-stop wiring.

        CaptureSessionMixin calls this after constructing and starting
        the controller. Tests inject a spy/mock here to assert
        ``stop()`` is invoked on auto-stop.
        """
        self._capture_controller = controller

    def set_analyzer_handoff(
        self, handoff: Callable[[str], None] | None
    ) -> None:
        """Inject a sink for ``在 Analyzer 打开`` handoff.

        Production path walks ``QApplication.topLevelWidgets()`` to find
        an existing Analyzer ``MainWindow`` and calls its public
        ``load_file`` method. Tests inject a spy here so the modal can
        be exercised without spinning up a real Analyzer window.
        """
        self._analyzer_handoff = handoff

    def set_manifest_target(self, manifest_path: Path | str | None) -> None:
        """Set the project manifest path used by ``保存并归档``.

        When ``None`` the archive action reports "no manifest
        configured" rather than crashing.
        """
        self._manifest_path = Path(manifest_path) if manifest_path else None
        if hasattr(self, "_history_tab"):
            self._history_tab.set_manifest_path(self._manifest_path)

    def _open_acquisition_guide(self) -> None:
        from mf4_analyzer.help import open_guide

        if not open_guide("acquisition"):
            self._status.showMessage("找不到采集使用说明")

    @property
    def last_session_summary(self) -> SessionSummary | None:
        """Most recent :class:`SessionSummary` (None until auto-stop or
        the normal stop path produces one). Carries the
        ``auto_stop=True`` flag for the review modal."""
        return self._last_session_summary

    @property
    def last_stop_result(self) -> StopFlushFinalizeResult | None:
        """Most recent :class:`StopFlushFinalizeResult`.

        Tests inspect ``last_stop_result.order`` to assert the
        stop/flush/finalize sequence ran in the spec-mandated order.
        """
        return self._last_stop_result

    @property
    def last_review_action(self) -> str | None:
        """Last action chosen on the real :class:`ReviewModal` (one of
        the four spec action constants, or ``None`` when the placeholder
        modal was used / the modal was dismissed)."""
        return self._last_review_action

    @property
    def review_modal(self) -> "QDialog | None":
        """The currently open review modal (None when not in
        :data:`CockpitState.REVIEW_MODAL`)."""
        return self._review_modal

    # ------------------------------------------------------------------
    # Health levels → record button + REC indicator
    # ------------------------------------------------------------------

    def _on_health_levels_changed(self, levels: dict) -> None:
        # Mirror REC chip into the toolbar indicator property for QSS.
        rec_level = levels.get("REC", "off")
        if rec_level == "red":
            self._rec_indicator.setText("● REC ERROR")
            self._set_visual_property(self._rec_indicator, "recState", "error")
        elif rec_level == "yellow":
            self._rec_indicator.setText("● REC WARN")
            self._set_visual_property(self._rec_indicator, "recState", "warn")
        elif self._state_machine.state == CockpitState.RECORDING:
            self._rec_indicator.setText("● REC")
            self._set_visual_property(self._rec_indicator, "recState", "recording")
        else:
            self._rec_indicator.setText("● REC OFF")
            self._set_visual_property(self._rec_indicator, "recState", "off")
        self._update_record_button_enabled()

    def _update_record_button_enabled(self) -> None:
        if self._state_machine.state != CockpitState.CONNECTED_IDLE:
            return
        levels = self._health_strip.current_levels()
        if any(level == "red" for level in levels.values()):
            self._main_btn.setEnabled(False)
            self._set_visual_property(self._main_btn, "cockpitAction", "disabled")
        else:
            self._main_btn.setEnabled(True)
            self._set_visual_property(self._main_btn, "cockpitAction", "record")

    # ------------------------------------------------------------------
    # Right-panel refreshers
    # ------------------------------------------------------------------

    def _effective_pinned_names(self) -> list[str]:
        """有效 pin 集（spec 2026-07-08 §G6）。

        未定制 = 先勾的前 DEFAULT_LIVE_PIN_COUNT 个；已定制 = 手动名单 ∩ 当前选择。
        """
        order = self._left_pane.selection_order()
        if not self._pin_customized:
            return order[:DEFAULT_LIVE_PIN_COUNT]
        selected = set(order)
        return [n for n in self._manual_pins if n in selected]

    def _ensure_pin_customized(self) -> None:
        if not self._pin_customized:
            self._manual_pins = list(self._effective_pinned_names())
            self._pin_customized = True

    def pin_channel(self, name: str) -> None:
        self._ensure_pin_customized()
        if name not in self._manual_pins:
            self._manual_pins.append(name)
        self._refresh_center_cards()

    def _on_pin_toggle(self, name: str) -> None:
        if name in self._effective_pinned_names():
            self.unpin_channel(name)
        else:
            self.pin_channel(name)

    def unpin_channel(self, name: str) -> None:
        self._ensure_pin_customized()
        if name in self._manual_pins:
            self._manual_pins.remove(name)
        self._refresh_center_cards()

    def reset_pins(self) -> None:
        self._manual_pins = []
        self._pin_customized = False
        self._refresh_center_cards()

    def _refresh_center_cards(self, explicit=None) -> None:
        """中央卡片唯一刷新入口（spec §G6）。

        ``explicit``：demo DemoSignal 兜底路径 —— 原样显示、绕过 pin。
        pin 操作只走这里，绝不触发 `_idle_restart_timer`（纯显示层）。
        """
        if explicit is not None:
            self._center.set_signals(
                [(m.name, m.unit, m.event) for m in explicit]
            )
            self._center.set_monitor_summary(None)
            return

        selection = self._left_pane.current_selection()
        by_name = {m.name: m for m in selection}
        pinned = [n for n in self._effective_pinned_names() if n in by_name]
        self._center.set_signals(
            [(n, by_name[n].unit, by_name[n].event) for n in pinned]
        )

        total = len(selection)
        if total > len(pinned):
            self._center.set_monitor_summary(
                f"已选 {total} · 实时显示 {len(pinned)} · 其余通道仍会录制"
            )
        else:
            self._center.set_monitor_summary(None)

    def _refresh_idle_preflight(self) -> None:
        # Spec §B2: connected-idle feeds the five preflight numbers to the
        # health-strip preflight pill. The old right-hand ``IdlePreflightPage``
        # was removed with the capture right pane (B-4); recording health now
        # flows to the REC chip / bottom facts via ``_poll_health``.
        selection = self._left_pane.current_selection()
        # Demo mode: no real A2L event capacity — fabricate a
        # generous mapping so the DAQ row reads green when at least
        # one measurement has an event.
        event_capacity = {
            m.event: 32 for m in selection if m.event is not None
        }
        disk_free_bytes = self._estimate_disk_free_bytes()
        if hasattr(self, "_health_strip"):
            self._health_strip.apply_preflight(
                selection=selection,
                event_capacity=event_capacity,
                disk_free_bytes=disk_free_bytes,
                state="idle",
            )

    def _check_recording_auto_stop(self) -> None:
        if self._estimate_disk_free_bytes() < thresholds.DISK_FREE_AUTO_STOP_BYTES:
            self._on_auto_stop_request("disk")

    # ------------------------------------------------------------------
    # Selection change handler
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        # Disconnected selection changes now feed the central connection
        # checklist (B-5) — the guide canvas is the right pane's replacement
        # destination (B-4). Connected-idle edits still restart the stream.
        if self._state_machine.state == CockpitState.DISCONNECTED:
            self._update_connection_checklist()
        elif self._state_machine.state == CockpitState.CONNECTED_IDLE:
            self._refresh_center_cards()
            self._refresh_idle_preflight()
            self._idle_restart_timer.start()

    # ------------------------------------------------------------------
    # Test helpers / accessors
    # ------------------------------------------------------------------

    @property
    def state_machine(self) -> CockpitStateMachine:
        return self._state_machine

    @property
    def ring_buffer(self) -> RingBuffer:
        return self._ring

    @property
    def health_strip(self) -> HealthStrip:
        return self._health_strip

    @property
    def left_pane(self) -> LeftPane:
        return self._left_pane

    @property
    def main_button(self) -> QPushButton:
        return self._main_btn

    @property
    def mode_tabs(self) -> QTabWidget:
        return self._mode_tabs

    @property
    def replay_tab(self) -> ReplayTab:
        return self._replay_tab

    @property
    def history_tab(self) -> HistoryTab:
        return self._history_tab

    @property
    def settings_action(self) -> QAction:
        return self._settings_action

    @property
    def segment_action(self) -> QAction:
        return self._segment_action
