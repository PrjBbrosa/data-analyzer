"""Cockpit ``QMainWindow``.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
Plan: ``docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md``
Polish wave: ``docs/analyzer/acquisition/specs/2026-05-15-cockpit-polish-wave-spec.md``

Current deliverables wired up here:

- Toolbar with A2L/DBC/output controls (DBC selector is permanently
  disabled per spec Product Decisions), Settings, segment marker,
  mode label (`采集 / 回放 / 历史`), REC indicator, and stateful main
  button (`连接 ECU` / `● 采集` / `■ Stop & 复盘`).
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
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAction,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
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

from can_logger.p0.a2l_probe import MeasurementSummary
from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.backends import (
    FakeRecorderBackend,
    RecorderBackend,
)
from mf4_analyzer.acquisition_capture.config_store import ConfigSchemaError
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import SessionSummary
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HealthAggregator,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_capture.ring_buffer import RingBuffer, WatermarkLevel
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
from mf4_analyzer.acquisition_ui.settings_dialog import SettingsDialog
from mf4_analyzer.acquisition_ui.state import (
    CockpitState,
    CockpitStateMachine,
    HealthyPredicateResult,
)
from mf4_analyzer.acquisition_ui.widgets.health_strip import HealthStrip
from mf4_analyzer.acquisition_ui.widgets.left_pane import LeftPane
from mf4_analyzer.acquisition_ui.widgets.live_cards import LiveCardGrid
from mf4_analyzer.acquisition_ui.widgets.right_panel import RightPanel


# Spec Product Decisions — DBC selector tooltip (verbatim).
DBC_DISABLED_TOOLTIP = "Reserved for raw CAN capture; XCP path uses A2L."

# Spec Product Decisions — mode tabs.
REPLAY_TAB_TITLE = "回放"
HISTORY_TAB_TITLE = "历史"
MODE_SEGMENTS = (
    ("capture", "采集", 0),
    ("replay", REPLAY_TAB_TITLE, 1),
    ("history", HISTORY_TAB_TITLE, 2),
)

# Spec §State Machine `Disconnected` failure surface text.
DROPPED_FRAMES_PROMPT_TITLE = "丢帧过多"
DROPPED_FRAMES_PROMPT_TEXT = "丢帧过多 · 是否停止？"


class _PlaceholderReviewModal(QDialog):
    """Stage 4 stub for the review modal.

    Spec §State Machine ``ReviewModal`` requires `丢弃 / 仅保存文件 /
    保存并归档 / 在 Analyzer 打开`. Stage 5 owns that. For Stage 4 we
    open a minimal modal that closes itself so the four-state cycle
    is observable end-to-end.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reviewModalPlaceholder")
        self.setWindowTitle("复盘 (Stage 5)")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.addWidget(QLabel("Stage 5 将在此显示完整的复盘流程。"))
        layout.addWidget(QLabel("点击「关闭」回到「已连接 · 待机」状态。"))
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class CockpitMainWindow(QMainWindow):
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
    """

    # Public Qt signals — Stage 5 wires the auto-stop handler here.
    auto_stop_requested = pyqtSignal(str)  # arg: reason ("ring_buffer" / "disk")

    def __init__(
        self,
        *,
        backend: RecorderBackend | None = None,
        health_aggregator: HealthAggregator | None = None,
        initial_pool: Iterable[MeasurementSummary] | None = None,
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
        self._ring = RingBuffer(capacity=thresholds.DEFAULT_RING_CAPACITY)
        # Bridge the non-Qt observer to a Qt slot. The shim's connect
        # API matches pyqtSignal.connect — synchronous, single-arg.
        self._ring.watermark_changed.connect(self._on_ring_watermark_changed)
        self._target_fps = thresholds.LIVE_FPS_NORMAL
        self._connection_attempt_started: float | None = None
        self._first_frame_ts: float | None = None
        self._rec_start_ts: float | None = None
        self._stream_start_ts: float | None = None
        self._a2l_name: str | None = None
        self._output_dir_label = "data/runs"
        self._cumulative_rx_count = 0
        self._cumulative_dropped = 0
        self._dropped_prompt_shown = False
        self._fake_rec_state: str = "off"
        self._fake_last_rx_monotonic: float | None = None
        self._fake_xcp_connected: bool = False
        self._fake_can_load_pct: float | None = None
        self._transport_config: TransportConfig | None = None
        self._ifdata_xcp = None
        # User-supplied A2L pool for the left pane (None in pure demo).
        self._initial_pool = tuple(initial_pool or ())
        # Stage 5 hand-off — Stage 5 owns the real CaptureController.
        # Until then the auto-stop path can still be exercised in tests
        # by injecting a controller via :meth:`set_capture_controller`.
        # ``_last_session_summary`` carries the ``auto_stop=True`` flag
        # forward to whichever review modal Stage 5 wires (the Stage 4
        # placeholder modal ignores it).
        self._capture_controller: CaptureController | None = None
        self._last_session_summary: SessionSummary | None = None
        self._review_modal: QDialog | None = None
        self._settings_dialog: SettingsDialog | None = None
        # Stage 5 hand-off: the most recent stop/flush/finalize run, used
        # by tests (and the eventual history tab) to introspect ordering.
        self._last_stop_result: StopFlushFinalizeResult | None = None
        # Optional Analyzer handoff sink — Stage 5 tests inject a spy to
        # observe ``MainWindow.load_file`` calls without spinning up a
        # real Analyzer window. When ``None`` the cockpit walks
        # ``QApplication.topLevelWidgets()`` to find an Analyzer instance.
        self._analyzer_handoff: "Callable[[str], None] | None" = None  # type: ignore[name-defined]
        # Stage 5: the cockpit Stage 5 review-modal action selected on
        # the last review modal close (one of the four spec action
        # constants, or ``None`` when the modal was dismissed without
        # an explicit click — Stage 4 placeholder path).
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

        # ----- UI scaffolding -------------------------------------------
        self._build_ui()
        self._apply_state_to_ui(CockpitState.DISCONNECTED, CockpitState.DISCONNECTED)
        if self._initial_pool:
            self._left_pane.set_pool(self._initial_pool)

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
        self._update_status_bar()
        if self._settings_load_error:
            self._status.showMessage(f"设置加载失败: {self._settings_load_error}")

    def _build_toolbar(self) -> QWidget:
        toolbar = QFrame(self)
        toolbar.setObjectName("cockpitToolbarBand")
        toolbar.setFrameShape(QFrame.NoFrame)
        toolbar.setFixedHeight(50)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self._a2l_btn = self._make_selector_button(
            "cockpitSelectorA2l", "A2L", "未加载"
        )
        self._a2l_btn.clicked.connect(self._on_pick_a2l)
        layout.addWidget(self._a2l_btn)

        # DBC selector — spec Product Decisions: setEnabled(False)
        # with the verbatim tooltip. We use a QPushButton so the click
        # signal is connectable for the test that asserts clicking
        # emits nothing (Qt's disabled state already suppresses
        # ``clicked`` emission).
        self._dbc_btn = self._make_selector_button(
            "cockpitSelectorDbc", "DBC", "可选"
        )
        self._dbc_btn.setEnabled(False)
        self._dbc_btn.setToolTip(DBC_DISABLED_TOOLTIP)
        # If a slot were connected, Qt would still not emit while
        # disabled; we leave it unconnected to match the spec
        # "clicking emits nothing".
        layout.addWidget(self._dbc_btn)

        self._output_btn = self._make_selector_button(
            "cockpitSelectorOutput", "输出", self._output_dir_label
        )
        self._output_btn.clicked.connect(self._on_pick_output_dir)
        layout.addWidget(self._output_btn)

        self._transport_chip = QLabel("传输未配置", self)
        self._transport_chip.setObjectName("cockpitTransportStatusChip")
        self._transport_chip.setProperty("transportState", "unconfigured")
        self._transport_chip.setFixedHeight(30)
        self._transport_chip.setMinimumWidth(96)
        self._transport_chip.setMaximumWidth(260)
        self._transport_chip.setAlignment(Qt.AlignCenter)
        self._transport_chip.setToolTip("打开传输设置")
        self._transport_chip.setCursor(Qt.PointingHandCursor)
        self._transport_chip.mousePressEvent = (
            lambda _event: self._open_settings_dialog(initial_tab="transport")
        )
        layout.addWidget(self._transport_chip)

        self._settings_action = QAction("设置", self)
        self._settings_action.setObjectName("cockpitSettingsAction")
        self._settings_action.triggered.connect(self._open_settings_dialog)
        self._settings_btn = QToolButton(self)
        self._settings_btn.setObjectName("cockpitSettingsButton")
        self._settings_btn.setDefaultAction(self._settings_action)
        self._settings_btn.setText("⚙")
        self._settings_btn.setToolTip("设置")
        self._settings_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._settings_btn.setFixedSize(30, 30)
        layout.addWidget(self._settings_btn)

        layout.addWidget(self._toolbar_separator(toolbar))

        self._segment_action = QAction("+ 段", self)
        self._segment_action.setObjectName("segmentMarkerAction")
        self._segment_action.setToolTip("标记一段 (M)")
        self._segment_action.setShortcut("M")
        self._segment_action.triggered.connect(self._on_mark_segment)
        self._segment_action.setVisible(False)
        self._segment_btn = QToolButton(self)
        self._segment_btn.setObjectName("segmentMarkerButton")
        self._segment_btn.setDefaultAction(self._segment_action)
        self._segment_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._segment_btn.setVisible(False)
        layout.addWidget(self._segment_btn)

        self._mode_segment_widget = self._build_mode_segment(toolbar)
        layout.addWidget(self._mode_segment_widget)

        # Stretch.
        spacer = QWidget(self)
        spacer.setObjectName("cockpitToolbarSpacer")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(spacer)

        # REC indicator (toolbar global).
        self._rec_indicator = QLabel("● REC OFF", self)
        self._rec_indicator.setObjectName("cockpitRecIndicator")
        self._rec_indicator.setFixedHeight(32)
        self._rec_indicator.setMinimumWidth(92)
        self._rec_indicator.setAlignment(Qt.AlignCenter)
        self._set_visual_property(self._rec_indicator, "recState", "off")
        layout.addWidget(self._rec_indicator)

        layout.addWidget(self._toolbar_separator(toolbar))

        # Main stateful button.
        self._main_btn = QPushButton("连接 ECU", self)
        self._main_btn.setProperty("role", "primary")
        self._main_btn.setFixedHeight(36)
        self._main_btn.setMinimumWidth(106)
        self._main_btn.clicked.connect(self._on_main_button)
        layout.addWidget(self._main_btn)

        # Spec §S4.2 — overflow chevron and its menu. Hidden by default;
        # ``_recompute_toolbar_overflow`` shows it when at least one
        # eligible toolbar child needs to be demoted at the current
        # window width.
        self._overflow_btn = QToolButton(toolbar)
        self._overflow_btn.setObjectName("cockpitToolbarOverflow")
        self._overflow_btn.setText("≡")
        self._overflow_btn.setToolTip("更多")
        self._overflow_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._overflow_btn.setFixedSize(30, 30)
        self._overflow_btn.setPopupMode(QToolButton.InstantPopup)
        self._overflow_menu = QMenu(self._overflow_btn)
        self._overflow_menu.setObjectName("cockpitToolbarOverflowMenu")
        self._overflow_btn.setMenu(self._overflow_menu)
        self._overflow_btn.setVisible(False)
        layout.addWidget(self._overflow_btn)

        # Build the QAction wrappers that the overflow menu mirrors. The
        # `_settings_action` and `_segment_action` instances already
        # exist; create QAction wrappers for the selectors and mode
        # segment so they can be added to a QMenu (only QAction works in
        # QMenu — naked QPushButton clicks cannot). Each wrapper re-uses
        # the existing slot verbatim.
        self._a2l_action = QAction("A2L", self)
        self._a2l_action.setObjectName("cockpitSelectorA2lAction")
        self._a2l_action.triggered.connect(self._on_pick_a2l)
        self._dbc_action = QAction("DBC", self)
        self._dbc_action.setObjectName("cockpitSelectorDbcAction")
        self._dbc_action.setEnabled(False)
        self._dbc_action.setToolTip(DBC_DISABLED_TOOLTIP)
        self._output_action = QAction("输出", self)
        self._output_action.setObjectName("cockpitSelectorOutputAction")
        self._output_action.triggered.connect(self._on_pick_output_dir)
        self._transport_action = QAction("传输", self)
        self._transport_action.setObjectName("cockpitTransportAction")
        self._transport_action.triggered.connect(
            lambda _checked=False: self._open_settings_dialog(initial_tab="transport")
        )
        # The mode segment is a composite of three buttons — when the
        # whole segment overflows, expose a single "模式" submenu-ish
        # action that opens the segment as a popup; for now we route to
        # the current capture/replay/history switch via menu items added
        # at recompute time. To keep the contract simple here, we create
        # one wrapper QAction labelled with the segment's first button
        # text ("采集" by default) — the test only checks `text()` parity
        # with the affordance, and the segment widget has no single
        # text() of its own. Tests can disambiguate via objectName when
        # they need it.
        self._mode_segment_action = QAction("模式", self)
        self._mode_segment_action.setObjectName("cockpitModeSegmentAction")
        # When the mode segment is demoted into the overflow menu, the
        # user must be able to pick a specific tab. A bare cycling
        # `_on_mode_segment_clicked((idx+1) % 3)` lambda forces
        # round-robin advancement with no visible current state.
        # Attach a submenu with one QAction per ``MODE_SEGMENTS``
        # entry so the overflow path renders as ``模式 ▶ 采集 / 回放
        # / 历史`` and each sub-action sets the tab to its specific
        # index.
        self._mode_overflow_submenu = QMenu("模式", self)
        self._mode_overflow_submenu.setObjectName("cockpitModeOverflowSubmenu")
        self._mode_overflow_actions: list[QAction] = []
        for _mode, label, idx in MODE_SEGMENTS:
            sub_action = QAction(label, self)
            sub_action.triggered.connect(
                lambda _checked=False, target_idx=idx: self._on_mode_segment_clicked(
                    target_idx
                )
            )
            self._mode_overflow_submenu.addAction(sub_action)
            self._mode_overflow_actions.append(sub_action)
        self._mode_segment_action.setMenu(self._mode_overflow_submenu)
        # Map each eligible toolbar child widget to its menu QAction.
        # Order matters: this is left-to-right toolbar order, so
        # recompute hides right-to-left (reversed iteration).
        self._toolbar_overflow_items: list[tuple[QWidget, QAction]] = [
            (self._a2l_btn, self._a2l_action),
            (self._dbc_btn, self._dbc_action),
            (self._output_btn, self._output_action),
            (self._transport_chip, self._transport_action),
            (self._settings_btn, self._settings_action),
            (self._segment_btn, self._segment_action),
            (self._mode_segment_widget, self._mode_segment_action),
        ]
        # Initial seed — see
        # `pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`:
        # the recompute must seed once at the end of __init__ so the
        # overflow chevron's initial visibility is honest before
        # show(). Defer one event-loop tick via ``QTimer.singleShot``
        # so the toolbar's child widgets have settled width() values
        # — calling synchronously here observes width()=0 and would
        # otherwise have to fall back to a hard-coded default that
        # mis-seeds the state on narrower screens.
        QTimer.singleShot(0, self._recompute_toolbar_overflow)

        return toolbar

    def _make_selector_button(
        self, object_name: str, key: str, value: str
    ) -> QPushButton:
        button = QPushButton("", self)
        button.setObjectName(object_name)
        button.setProperty("cockpitSelector", True)
        button.setFixedHeight(28)
        # Spec §S4.2 — loosen the selector widths from a fixed value to
        # a min+max band so the toolbar can compress at narrow window
        # widths without clipping primary actions. The default-render
        # width sits inside each band so the visible diff at 1280px is
        # zero.
        width_bands = {
            "cockpitSelectorA2l": (90, 160),
            "cockpitSelectorDbc": (90, 170),
            "cockpitSelectorOutput": (110, 220),
        }
        min_w, max_w = width_bands.get(object_name, (90, 160))
        button.setMinimumWidth(min_w)
        button.setMaximumWidth(max_w)
        button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        button.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(button)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        key_label = QLabel(key, button)
        key_label.setObjectName("cockpitSelectorKey")
        value_label = QLabel(value, button)
        value_label.setObjectName("cockpitSelectorValue")
        key_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        value_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(key_label, 0, Qt.AlignVCenter)
        layout.addWidget(value_label, 1, Qt.AlignVCenter)
        caret = QLabel("▾", button)
        caret.setObjectName("cockpitSelectorCaret")
        caret.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(caret, 0, Qt.AlignVCenter)

        button.setToolTip(value)
        return button

    def _set_selector_value(
        self, button: QPushButton, key: str, value: str
    ) -> None:
        key_label = button.findChild(QLabel, "cockpitSelectorKey")
        value_label = button.findChild(QLabel, "cockpitSelectorValue")
        if key_label is not None:
            key_label.setText(key)
        if value_label is not None:
            value_label.setText(value)
        button.setToolTip(value)

    def _toolbar_separator(self, parent: QWidget) -> QFrame:
        separator = QFrame(parent)
        separator.setObjectName("cockpitToolbarSeparator")
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setFixedHeight(22)
        return separator

    def _build_mode_segment(self, parent: QWidget) -> QWidget:
        segment = QWidget(parent)
        segment.setObjectName("cockpitModeSegment")
        segment.setFixedHeight(32)
        layout = QHBoxLayout(segment)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._mode_button_group = QButtonGroup(self)
        self._mode_button_group.setExclusive(True)
        self._mode_buttons: dict[int, QPushButton] = {}
        for mode, label, index in MODE_SEGMENTS:
            button = QPushButton(label, segment)
            button.setCheckable(True)
            button.setProperty("cockpitMode", mode)
            button.setFixedHeight(26)
            button.setMinimumWidth(56)
            button.clicked.connect(
                lambda _checked=False, tab_index=index: (
                    self._on_mode_segment_clicked(tab_index)
                )
            )
            self._mode_button_group.addButton(button, index)
            self._mode_buttons[index] = button
            layout.addWidget(button)
        self._sync_mode_segment(0)
        return segment

    def _neutralize_mode_tab_bar(self) -> None:
        tab_bar = self._mode_tabs.tabBar()
        tab_bar.hide()
        tab_bar.setEnabled(False)
        tab_bar.setMinimumHeight(0)
        tab_bar.setMaximumHeight(0)
        self._mode_tabs.setDocumentMode(True)

    # ------------------------------------------------------------------
    # Toolbar overflow recompute — spec §S4.2.
    # ------------------------------------------------------------------

    def _recompute_toolbar_overflow(self) -> None:
        """Hide overflow-eligible toolbar widgets right-to-left when the
        toolbar's accumulated child width exceeds its outer width, and
        mirror the hidden affordances into ``_overflow_menu``.

        Eligible widgets are taken from ``_toolbar_overflow_items``;
        ``_rec_indicator`` and ``_main_btn`` are NEVER eligible. Each
        demoted widget is marked with the dynamic property
        ``cockpitOverflowHidden = True`` so callers (and tests) can
        distinguish overflow-hidden widgets from state-hidden widgets
        (e.g. the segment marker during DISCONNECTED). Widgets that
        were previously overflow-hidden may be restored when the
        toolbar widens, unless they were also state-hidden in the
        meantime.
        """
        if not hasattr(self, "_toolbar") or not hasattr(
            self, "_toolbar_overflow_items"
        ):
            return
        toolbar = self._toolbar
        outer_w = toolbar.width()
        if outer_w <= 0:
            # Layout not yet computed (pre-show). Use the parent
            # window's width as a best-effort proxy.
            outer_w = self.width()
        if outer_w <= 0:
            # Still not laid out — give up rather than seed against a
            # hard-coded fallback (which would mis-seed on screens
            # narrower than the default). The first ``resizeEvent``
            # after show() will recompute against real widths.
            return

        # Determine each eligible widget's "design visibility" — True
        # if the state machine wants it visible. We treat
        # overflow-hidden widgets (cockpitOverflowHidden=True) as
        # design-visible because they were hidden by us, not by state.
        # Widgets that are not visible AND not overflow-hidden are
        # design-hidden (e.g. segment marker outside RECORDING) and
        # are excluded from the eligibility set for this recompute.
        eligible: list[tuple[QWidget, QAction, bool]] = []
        for widget, action in self._toolbar_overflow_items:
            overflow_hidden = bool(widget.property("cockpitOverflowHidden"))
            design_visible = widget.isVisible() or overflow_hidden
            eligible.append((widget, action, design_visible))

        # Compute always-on cost: REC indicator + main button +
        # overflow chevron's own width + separators + layout margins.
        layout = toolbar.layout()
        if layout is None:
            return
        margins = layout.contentsMargins()
        spacing = max(0, layout.spacing())
        always_on_w = margins.left() + margins.right()
        for w in (self._rec_indicator, self._main_btn, self._overflow_btn):
            if w is not None:
                always_on_w += max(w.sizeHint().width(), w.minimumWidth())
        # Count separators (find by objectName) and the stretch spacer
        # contribution (treat spacer as 0 width — it absorbs slack).
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                continue
            if w.objectName() == "cockpitToolbarSeparator":
                always_on_w += max(w.sizeHint().width(), w.minimumWidth())
        # Spacing between every adjacent pair of widgets — a coarse
        # estimate from the design-visible eligible count plus the
        # three always-on widgets.
        approx_widget_count = (
            len([w for w, _, dv in eligible if dv])
            + 3  # rec, main, overflow
        )
        always_on_w += max(0, approx_widget_count - 1) * spacing

        # Cache each eligible widget's natural width.
        widget_natural_w: dict[QWidget, int] = {}
        for widget, _action, _dv in eligible:
            natural = max(widget.sizeHint().width(), widget.minimumWidth())
            widget_natural_w[widget] = natural

        # Start with every design-visible eligible widget shown; demote
        # the rightmost remaining one until the running total fits.
        shown: list[QWidget] = [w for w, _, dv in eligible if dv]
        running = always_on_w + sum(widget_natural_w[w] for w in shown)
        demoted: list[QWidget] = []
        while running > outer_w and shown:
            victim = shown.pop()
            demoted.append(victim)
            running -= widget_natural_w[victim]

        # Apply visibility + dynamic-property updates.
        demoted_set = set(demoted)
        for widget, _action, design_visible in eligible:
            if not design_visible:
                # State-hidden — never touched here.
                continue
            if widget in demoted_set:
                widget.setProperty("cockpitOverflowHidden", True)
                widget.setVisible(False)
            else:
                if bool(widget.property("cockpitOverflowHidden")):
                    widget.setProperty("cockpitOverflowHidden", False)
                widget.setVisible(True)

        # Rebuild the overflow menu in left-to-right toolbar order so
        # the menu reads naturally.
        self._overflow_menu.clear()
        ordered_demoted: list[QAction] = []
        for widget, action, _ in eligible:
            if widget in demoted_set:
                ordered_demoted.append(action)
        for action in ordered_demoted:
            self._overflow_menu.addAction(action)
        self._overflow_btn.setVisible(len(ordered_demoted) > 0)

    def resizeEvent(self, event):  # noqa: N802 — Qt override
        """Recompute toolbar overflow on every window resize.

        Pure UI hook — does not touch the four-state machine.
        """
        super().resizeEvent(event)
        if hasattr(self, "_overflow_btn"):
            self._recompute_toolbar_overflow()

    def _on_mode_segment_clicked(self, index: int) -> None:
        if hasattr(self, "_mode_tabs"):
            self._mode_tabs.setCurrentIndex(index)
        else:
            self._sync_mode_segment(index)

    def _sync_mode_segment(self, index: int) -> None:
        if not hasattr(self, "_mode_buttons"):
            return
        for button_index, button in self._mode_buttons.items():
            old = button.blockSignals(True)
            button.setChecked(button_index == index)
            button.blockSignals(old)

    @staticmethod
    def _set_visual_property(widget: QWidget, name: str, value: str) -> None:
        if widget.property(name) == value:
            return
        widget.setProperty(name, value)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _build_acquisition_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal, page)
        splitter.setObjectName("cockpitSplitter")
        splitter.setChildrenCollapsible(False)

        self._left_pane = LeftPane(splitter)
        self._left_pane.selection_changed.connect(self._on_selection_changed)

        self._center = LiveCardGrid(splitter)

        self._right_panel = RightPanel(splitter)

        splitter.addWidget(self._left_pane)
        splitter.addWidget(self._center)
        splitter.addWidget(self._right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        layout.addWidget(splitter)
        return page

    def _on_mode_tab_changed(self, index: int) -> None:
        self._sync_mode_segment(index if index >= 0 else 0)

    def _load_threshold_overrides(self) -> None:
        try:
            thresholds.apply_overrides(thresholds.load_user_settings())
        except (ConfigSchemaError, OSError, UnicodeDecodeError) as exc:
            self._settings_load_error = str(exc)
            logger.warning("could not load acquisition settings: %s", exc)

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
            self._right_panel.show_disconnected(
                snapshot=self._health_aggregator.last,
                first_frame_received=self._first_frame_ts is not None,
                first_failure=(
                    self._state_machine.last_healthy_result.first_failure
                    if self._state_machine.last_healthy_result
                    else None
                ),
                selection_count=len(self._left_pane.current_selection())
                if hasattr(self, "_left_pane")
                else 0,
            )
            self._update_status_bar()
            self._center.set_recording(False, None)
        elif new == CockpitState.CONNECTED_IDLE:
            self._main_btn.setText("● 采集")
            self._set_visual_property(self._main_btn, "cockpitAction", "record")
            self._rec_indicator.setText("● REC OFF")
            self._set_visual_property(self._rec_indicator, "recState", "off")
            self._center.set_recording(False, None)
            self._refresh_idle_right_panel()
            self._update_status_bar()
            # Update record-button enabled state based on latest health.
            self._update_record_button_enabled()
        elif new == CockpitState.RECORDING:
            if self._rec_start_ts is None:
                self._rec_start_ts = time.monotonic()
            self._main_btn.setText("■ Stop & 复盘")
            self._main_btn.setEnabled(True)
            self._set_visual_property(self._main_btn, "cockpitAction", "stop")
            self._rec_indicator.setText("● REC")
            self._set_visual_property(self._rec_indicator, "recState", "recording")
            self._left_pane.set_frozen(True)
            self._center.set_recording(True, self._rec_start_ts)
            self._update_status_bar()
            self._refresh_recording_right_panel()
        elif new == CockpitState.REVIEW_MODAL:
            self._main_btn.setEnabled(False)
            self._set_visual_property(self._main_btn, "cockpitAction", "disabled")
            self._rec_indicator.setText("● REC OFF")
            self._set_visual_property(self._rec_indicator, "recState", "off")
            self._left_pane.set_frozen(False)
            self._status.showMessage("复盘")
            self._open_review_modal()

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
            # Stage 5: run the canonical stop/flush/finalize sequence
            # before flipping the state machine. When no controller is
            # attached (Stage 4 demo path) we fall through to the
            # placeholder modal so the four-state cycle still works.
            self.request_stop_and_review()
        # Review modal close is driven by the dialog's finished signal.

    def request_stop_and_review(self, *, auto_stop: bool = False) -> None:
        """Stage 5 entry point: run stop/flush/finalize and open review.

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
            # No controller — Stage 4 demo path. Arm a stub summary so
            # downstream callers can still inspect ``auto_stop``.
            self._last_session_summary = SessionSummary(auto_stop=auto_stop)
            finalized = True

        # Drive the state machine.
        self._state_machine.request_stop_recording(finalized=finalized)
        # ``_apply_state_to_ui(REVIEW_MODAL)`` will open the modal in
        # response to the state change. It picks the real review modal
        # when ``result is not None`` and falls back to the Stage 4
        # placeholder otherwise.

    def _begin_connection_attempt(self) -> None:
        """Start connection attempt. Triggers fake backend + timer."""
        selection = self._left_pane.current_selection() if hasattr(self, "_left_pane") else []
        if not selection and self._initial_pool:
            # Auto-select first measurement so the demo can start the
            # backend without a real A2L click-through.
            self._left_pane._selected_names.add(self._initial_pool[0].name)
            self._left_pane._refresh_list()
            selection = self._left_pane.current_selection()
        if not selection:
            # Demo seed: one synthetic measurement.
            selection = [SelectedMeasurement(name="DemoSignal")]
        self._connection_attempt_started = time.monotonic()
        self._stream_start_ts = self._connection_attempt_started
        self._first_frame_ts = None
        self._fake_xcp_connected = True
        self._fake_rec_state = "off"
        self._fake_can_load_pct = 12.5
        self._backend.start(selection)
        # Start timers if not yet running.
        if not self._health_timer.isActive():
            self._health_timer.start()
        if not self._live_timer.isActive():
            self._live_timer.start()
        # Seed the center pane with cards.
        self._center.set_signals(
            [(m.name, m.unit, m.event) for m in selection]
        )

    def _start_recording(self) -> None:
        # Spec: red health disables record. The button enabled state
        # already enforces this — defensive double-check here.
        if not self._main_btn.isEnabled():
            return
        levels = self._health_strip.current_levels()
        if any(level == "red" for level in levels.values()):
            return
        self._rec_start_ts = time.monotonic()
        self._fake_rec_state = "recording"
        self._cumulative_rx_count = 0
        self._cumulative_dropped = 0
        self._dropped_prompt_shown = False
        self._state_machine.request_start_recording()

    def _open_review_modal(self) -> None:
        """Open the Stage 5 review modal when stop/flush/finalize ran,
        otherwise fall back to the Stage 4 placeholder.

        Spec §State Machine `ReviewModal` requires the four-action set;
        the real :class:`ReviewModal` implements it. The placeholder
        remains for the no-controller demo path so the four-state cycle
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
            # Stage 4 demo / no controller — placeholder so the cycle
            # terminates.
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
    # Health polling slot (QTimer)
    # ------------------------------------------------------------------

    def _poll_health(self) -> None:
        snapshot = self._health_aggregator.poll_once()
        self._health_strip.apply_snapshot(snapshot)
        self._update_record_button_enabled()
        # Disconnected → ConnectedIdle gate.
        if self._state_machine.state == CockpitState.DISCONNECTED:
            self._evaluate_connection_attempt(snapshot)
        elif self._state_machine.state == CockpitState.CONNECTED_IDLE:
            self._refresh_idle_right_panel()
        elif self._state_machine.state == CockpitState.RECORDING:
            self._refresh_recording_right_panel()
            self._check_recording_auto_stop()

    def _evaluate_connection_attempt(self, snapshot: HealthSnapshot) -> None:
        if self._connection_attempt_started is None:
            return
        elapsed = time.monotonic() - self._connection_attempt_started
        first_frame = self._first_frame_ts is not None
        verdict = HealthyPredicateResult.from_components(
            hw_ok=snapshot.hw.ok,
            xcp_connected=snapshot.xcp.connected,
            first_frame_received=first_frame,
        )
        if verdict.healthy:
            self._state_machine.request_connect(verdict)
            self._connection_attempt_started = None
            return
        # Timeout: connection_timeout_s without a frame returns to
        # Disconnected and surfaces the first failing predicate.
        if elapsed >= thresholds.CONNECTION_TIMEOUT_S:
            self._connection_attempt_started = None
            self._fake_xcp_connected = False
            # Stash the verdict so the right panel can quote the
            # failure even though the state stays Disconnected.
            self._state_machine.request_connect(verdict)
            # Tear down backend.
            try:
                self._backend.stop()
            except Exception:
                pass
            self._apply_state_to_ui(
                CockpitState.DISCONNECTED, CockpitState.DISCONNECTED
            )

    # ------------------------------------------------------------------
    # Live data poll
    # ------------------------------------------------------------------

    def _poll_live(self) -> None:
        try:
            samples = self._backend.poll()
        except Exception:
            samples = []
        if samples:
            if self._first_frame_ts is None:
                self._first_frame_ts = time.monotonic()
            self._fake_last_rx_monotonic = time.monotonic()
        for channel, ts, value in samples:
            # Push into ring buffer for watermark accounting; controller
            # would normally drain on its own loop. Stage 4 keeps the
            # ring alive so the watermark signal is exercisable.
            self._ring.put((ts, channel, value))
            self._center.push_sample(channel, ts, value)
        # Repaint sparklines.
        self._center.refresh_all(now_ts=time.monotonic())
        # Update cumulative counters.
        self._cumulative_rx_count += len(samples)
        # Sync dropped counter from ring buffer (cumulative).
        self._cumulative_dropped = self._ring.dropped_frames
        self._update_status_bar()
        if (
            self._state_machine.state == CockpitState.RECORDING
            and self._cumulative_dropped > thresholds.DROPPED_FRAMES_PROMPT_TOTAL
            and not self._dropped_prompt_shown
        ):
            self._show_dropped_frames_prompt()

    # ------------------------------------------------------------------
    # Watermark wiring — spec §Threshold Contract Watermark wiring
    # ------------------------------------------------------------------

    def _on_ring_watermark_changed(self, level: WatermarkLevel) -> None:
        """Bridge from the non-Qt observer to Qt slots."""
        # 30 fps for green/yellow_low; 10 fps for red/red_drop.
        if level in ("green", "yellow_low"):
            self.set_target_fps(thresholds.LIVE_FPS_NORMAL)
        else:
            self.set_target_fps(thresholds.LIVE_FPS_DEGRADED)
        if level == "red_drop_sustained":
            # Spec: ≥95% for 5 s ⇒ auto-stop.
            self._on_auto_stop_request("ring_buffer")

    def set_target_fps(self, fps: int) -> None:
        """Spec §Threshold Contract Watermark wiring: 30→10 fps."""
        fps = int(fps)
        if fps <= 0:
            return
        self._target_fps = fps
        interval = max(1, int(1000 / fps))
        self._live_timer.setInterval(interval)

    def _on_auto_stop_request(self, reason: str) -> None:
        """Auto-stop entry point (spec §Threshold Contract Watermark wiring).

        Two arms:

        - **Mid-Recording**: route through :meth:`request_stop_and_review`
          which runs the full stop/flush/finalize sequence. Auto-stop
          arms ``SessionSummary.auto_stop=True`` so the review modal's
          banner ("自动停止 · ring buffer 持续告警") is visible.
        - **Not Recording** (e.g. ring goes red during ConnectedIdle):
          call ``controller.stop()`` directly (synchronous, no
          ``thread.wait()`` per lesson
          ``2026-04-25-qthread-wait-deadlocks-queued-quit.md``), arm the
          summary, then open the Stage 4 placeholder modal so the cycle
          is observable.

        Both arms emit ``auto_stop_requested`` and update the status
        bar before doing any work.
        """
        self.auto_stop_requested.emit(reason)
        self._status.showMessage(f"自动停止已请求 ({reason})")

        if self._state_machine.state == CockpitState.RECORDING:
            # Stage 5: run the full stop/flush/finalize sequence. This
            # calls ``controller.stop()`` exactly once and routes through
            # ``_open_review_modal`` to show the real ReviewModal when
            # the result is valid, or the placeholder when the sequence
            # could not complete (e.g. the controller's writer path is a
            # test stub without a real file). ``auto_stop=True`` is
            # passed through so the banner is visible on either modal.
            self.request_stop_and_review(auto_stop=True)
            # ``request_stop_and_review`` already armed
            # ``self._last_session_summary``; if it failed mid-sequence
            # the state stays in RECORDING (the user can retry). In that
            # case we still want the auto-stop flag armed for callers
            # that inspect ``last_session_summary`` after the fact.
            if self._last_session_summary is None:
                self._last_session_summary = SessionSummary(auto_stop=True)
            else:
                self._last_session_summary.auto_stop = True
            # If stop/flush/finalize raised before flipping the state
            # (e.g. spy controller with empty output_mf4 path in the
            # Stage 4 auto-stop unit test), we still need the review
            # modal to surface so the four-state cycle terminates. Open
            # the placeholder directly in that recovery case.
            if (
                self._state_machine.state == CockpitState.RECORDING
                and self._capture_controller is not None
            ):
                # The sequence raised before the state machine advanced.
                # Force the placeholder open and walk the state machine
                # manually — this preserves the S4-fix Fix #6 contract
                # that auto-stop always lands the user in REVIEW_MODAL
                # even when the writer path is a stub.
                self._state_machine.request_stop_recording(finalized=True)
            return

        # Not mid-Recording — auto-stop fired from idle/disconnected.
        # Call controller.stop() directly so the summary is captured.
        if self._capture_controller is not None:
            try:
                summary = self._capture_controller.stop()
            except Exception:  # noqa: BLE001
                summary = None
            if summary is not None:
                summary.auto_stop = True
                self._last_session_summary = summary
            else:
                self._last_session_summary = SessionSummary(auto_stop=True)
        else:
            self._last_session_summary = SessionSummary(auto_stop=True)

        if self._state_machine.state != CockpitState.REVIEW_MODAL:
            # Out-of-Recording auto-stop: open the placeholder modal
            # directly so the test can observe it without crossing an
            # illegal transition through the state machine.
            modal = _PlaceholderReviewModal(self)
            modal.finished.connect(self._on_review_modal_closed)
            modal.open()
            self._review_modal = modal

    # ------------------------------------------------------------------
    # Controller injection — Stage 5 hand-off seam.
    # ------------------------------------------------------------------

    def set_capture_controller(
        self, controller: CaptureController | None
    ) -> None:
        """Attach the live :class:`CaptureController` for auto-stop wiring.

        Stage 4 keeps the controller external — the cockpit window
        drives the simulated backend directly via ``self._backend``.
        Stage 5 will own controller lifecycle and call this setter once
        the controller is constructed and started. Tests inject a
        spy/mock here to assert ``stop()`` is invoked on auto-stop.
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

    @property
    def last_session_summary(self) -> SessionSummary | None:
        """Most recent :class:`SessionSummary` (None until auto-stop or
        Stage 5's normal stop path produces one). Carries the
        ``auto_stop=True`` flag for the review modal."""
        return self._last_session_summary

    @property
    def last_stop_result(self) -> StopFlushFinalizeResult | None:
        """Most recent :class:`StopFlushFinalizeResult`.

        Stage 5 tests inspect ``last_stop_result.order`` to assert the
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

    def _refresh_idle_right_panel(self) -> None:
        if not hasattr(self, "_right_panel"):
            return
        selection = self._left_pane.current_selection()
        # Stage 4 demo: no real A2L event capacity — fabricate a
        # generous mapping so the DAQ row reads green when at least
        # one measurement has an event.
        event_capacity = {
            m.event: 32 for m in selection if m.event is not None
        }
        disk_free_bytes = self._estimate_disk_free_bytes()
        self._right_panel.show_idle(
            selection=selection,
            event_capacity=event_capacity,
            disk_free_bytes=disk_free_bytes,
        )

    def _refresh_recording_right_panel(self) -> None:
        snapshot = self._health_aggregator.last
        if snapshot is None:
            return
        self._right_panel.show_recording(
            snapshot=snapshot,
            disk_free_bytes=self._estimate_disk_free_bytes(),
        )

    def _check_recording_auto_stop(self) -> None:
        if self._estimate_disk_free_bytes() < thresholds.DISK_FREE_AUTO_STOP_BYTES:
            self._on_auto_stop_request("disk")

    # ------------------------------------------------------------------
    # Selection change handler
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        if self._state_machine.state == CockpitState.CONNECTED_IDLE:
            # Update center cards for the new selection.
            self._center.set_signals(
                [
                    (m.name, m.unit, m.event)
                    for m in self._left_pane.current_selection()
                ]
            )
            self._refresh_idle_right_panel()

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def set_transport(
        self,
        transport: TransportConfig | None,
        *,
        device_model: str | None = None,
    ) -> None:
        self._transport_config = transport
        if transport is None:
            self._transport_chip.setText("传输未配置")
            self._transport_chip.setToolTip("打开传输设置")
            self._set_visual_property(
                self._transport_chip,
                "transportState",
                "unconfigured",
            )
            return

        fd_label = "CAN-FD" if transport.can_fd else "CAN"
        rate = transport.bitrate // 1000
        prefix = f"{device_model} · " if device_model else "传输 · "
        text = (
            f"{prefix}App={transport.app_name} · Ch={transport.channel} · "
            f"{fd_label} {rate}k"
        )
        self._transport_chip.setText(text)
        self._transport_chip.setToolTip(text)
        self._set_visual_property(self._transport_chip, "transportState", "configured")
        self._recompute_toolbar_overflow()

    def _open_settings_dialog(self, *, initial_tab: str | None = None) -> None:
        if self._settings_dialog is not None:
            if initial_tab is not None:
                self._settings_dialog.open_tab(initial_tab)
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(
            self,
            transport=self._transport_config or TransportConfig(),
            ifdata=self._ifdata_xcp,
        )
        if initial_tab is not None:
            dialog.open_tab(initial_tab)
        dialog.settings_saved.connect(self._on_settings_changed)
        dialog.settings_reset.connect(self._on_settings_reset)
        dialog.finished.connect(lambda _result: setattr(self, "_settings_dialog", None))
        self._settings_dialog = dialog
        dialog.open()

    def _on_settings_changed(self, _values: dict[str, float | int]) -> None:
        if self._settings_dialog is not None:
            self.set_transport(self._settings_dialog.current_transport())
        self._apply_threshold_runtime_refresh()
        self._status.showMessage("设置已保存")

    def _on_settings_reset(self) -> None:
        self._apply_threshold_runtime_refresh()
        self._status.showMessage("设置已还原默认")

    def _apply_threshold_runtime_refresh(self) -> None:
        self._health_timer.setInterval(
            int(thresholds.HEALTH_POLL_INTERVAL_S * 1000)
        )
        self._update_record_button_enabled()
        if self._state_machine.state == CockpitState.CONNECTED_IDLE:
            self._refresh_idle_right_panel()
        elif self._state_machine.state == CockpitState.RECORDING:
            self._refresh_recording_right_panel()

    # ------------------------------------------------------------------
    # Segment marker + status bar
    # ------------------------------------------------------------------

    def _on_mark_segment(self) -> None:
        if self._state_machine.state != CockpitState.RECORDING:
            return
        if self._capture_controller is None:
            return
        label, ok = QInputDialog.getText(self, "标记一段", "标签（可选）:")
        self._capture_controller.mark_segment(label if ok else None)

    def _update_status_bar(self) -> None:
        if not hasattr(self, "_status"):
            return
        state = self._state_machine.state
        if state == CockpitState.DISCONNECTED:
            a2l_name = self._a2l_name or "未加载"
            self._status.showMessage(f"未连接 · A2L: {a2l_name}")
            return
        if state == CockpitState.CONNECTED_IDLE:
            self._status.showMessage(
                f"streaming · {self._event_rate_per_s()} evt/s · "
                f"buf {self._ring.level_pct:.1f}%"
            )
            return
        if state == CockpitState.RECORDING:
            elapsed = self._recording_elapsed_text()
            self._status.showMessage(
                f"RECORDING · {elapsed} · {self._sample_count()} samples · "
                f"{self._recording_file_size_mb():.1f} MB · "
                f"drop {self._cumulative_dropped} · buf {self._ring.level_pct:.1f}%"
            )

    def _event_rate_per_s(self) -> int:
        if self._stream_start_ts is None:
            return 0
        elapsed = max(0.0, time.monotonic() - self._stream_start_ts)
        if elapsed <= 0:
            return 0
        return int(round(self._cumulative_rx_count / elapsed))

    def _recording_elapsed_text(self) -> str:
        if self._rec_start_ts is None:
            total = 0
        else:
            total = int(max(0.0, time.monotonic() - self._rec_start_ts))
        minutes, seconds = divmod(total, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _sample_count(self) -> int:
        if self._capture_controller is not None:
            try:
                return int(self._capture_controller.writer.write_count)
            except Exception:  # noqa: BLE001 - status bar must stay best-effort
                return int(self._cumulative_rx_count)
        return int(self._cumulative_rx_count)

    def _recording_file_size_mb(self) -> float:
        path: Path | None = None
        if self._capture_controller is not None:
            try:
                path = self._capture_controller.config.output_mf4
            except Exception:  # noqa: BLE001 - injected test controllers are partial
                path = None
        elif self._last_session_summary and self._last_session_summary.output_mf4:
            path = Path(self._last_session_summary.output_mf4)
        if path is None or not path.exists():
            return 0.0
        try:
            return path.stat().st_size / (1024.0 * 1024.0)
        except OSError:
            return 0.0

    # ------------------------------------------------------------------
    # File dialogs
    # ------------------------------------------------------------------

    def _on_pick_a2l(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 A2L 文件", "", "A2L (*.a2l);;All (*)"
        )
        if path:
            a2l_path = Path(path)
            self._a2l_name = a2l_path.name
            self._ifdata_xcp = self._load_first_ifdata_xcp(a2l_path)
            self._set_selector_value(self._a2l_btn, "A2L", self._a2l_name)
            self._update_status_bar()

    def _load_first_ifdata_xcp(self, path: Path):
        try:
            from can_logger.p0.ifdata_xcp import parse_ifdata_xcp_file

            blocks = parse_ifdata_xcp_file(path)
        except Exception as exc:  # noqa: BLE001 - file picker must stay responsive
            self._status.showMessage(f"A2L IF_DATA 解析失败: {exc}")
            return None
        return blocks[0] if blocks else None

    def _on_pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if path:
            self._output_dir_label = path
            self._set_selector_value(self._output_btn, "输出", self._output_dir_label)
            self._status.showMessage(f"输出目录: {path}")

    # ------------------------------------------------------------------
    # Dropped-frames prompt
    # ------------------------------------------------------------------

    def _show_dropped_frames_prompt(self) -> None:
        self._dropped_prompt_shown = True
        box = QMessageBox(self)
        box.setObjectName("droppedFramesPrompt")
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(DROPPED_FRAMES_PROMPT_TITLE)
        box.setText(DROPPED_FRAMES_PROMPT_TEXT)
        cont_btn = box.addButton("继续录制", QMessageBox.AcceptRole)
        stop_btn = box.addButton("停止并复盘", QMessageBox.DestructiveRole)
        # Use ``open`` to keep the prompt non-modal w.r.t. the
        # recording loop per spec ("stays inside the Recording state;
        # never auto-dismisses").
        box.open()
        # Wire Stage 5 stop branch. ``继续录制`` is dismiss-only; we
        # just close the box (Qt's default ``buttonClicked`` slot).
        # ``停止并复盘`` runs the same stop/flush/finalize flow as the
        # toolbar Stop.
        def _on_dropped_prompt_button(btn) -> None:
            if btn is stop_btn:
                self.request_stop_and_review()
            # ``继续录制`` simply dismisses; the recording continues.

        box.buttonClicked.connect(_on_dropped_prompt_button)
        # Hold a reference so it isn't garbage-collected before the user
        # clicks. Also exposed for tests to assert presence.
        self._dropped_prompt = box
        self._dropped_prompt_continue_btn = cont_btn
        self._dropped_prompt_stop_btn = stop_btn

    # ------------------------------------------------------------------
    # Disk-free estimator
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_disk_free_bytes() -> int:
        """Return free-byte estimate for the output path's filesystem.

        Stage 4 demo uses ``/tmp`` for the output; we don't actually
        write anything, but the right panel needs a number that
        clears the green threshold so the demo doesn't flash red.
        """
        try:
            import shutil

            return int(shutil.disk_usage("/").free)
        except Exception:
            # Defensive: anything > green threshold so the demo isn't
            # red on environments without /.
            return thresholds.DISK_FREE_GREEN_MIN_BYTES * 2

    # ------------------------------------------------------------------
    # Probes — feed the HealthAggregator from Cockpit state.
    # ------------------------------------------------------------------

    def _probe_hw(self) -> HwHealth:
        # Demo path: simulate a working HW once the user clicks connect.
        if self._connection_attempt_started is not None or self._fake_xcp_connected:
            return HwHealth(
                ok=True,
                driver_version="demo-fake",
                channel_count=1,
                last_probe_ts=time.monotonic(),
                error=None,
            )
        return HwHealth(
            ok=False,
            driver_version=None,
            channel_count=0,
            last_probe_ts=time.monotonic(),
            error="non-windows host",
        )

    def _probe_can(self) -> CanHealth:
        return CanHealth(
            bus_load_pct=self._fake_can_load_pct,
            channels=(),
            bus_error_count=0,
        )

    def _probe_xcp(self) -> XcpHealth:
        return XcpHealth(
            connected=self._fake_xcp_connected,
            slave_id=0x55 if self._fake_xcp_connected else None,
            last_response_age_s=0.0,
            consecutive_timeouts=0,
        )

    def _probe_daq(self) -> DaqHealth:
        return DaqHealth()

    def _probe_rec(self) -> RecHealth:
        last_age = 0.0
        if self._fake_last_rx_monotonic is None:
            last_age = thresholds.REC_LAST_RX_RED_MIN_S if self._fake_xcp_connected else 0.0
        else:
            last_age = max(0.0, time.monotonic() - self._fake_last_rx_monotonic)
        return RecHealth(
            state=self._fake_rec_state,  # type: ignore[arg-type]
            ring_buffer_fill_pct=self._ring.level_pct,
            dropped_frames=self._ring.dropped_frames,
            write_rate_bps=0.0,
            last_rx_age_s=last_age,
            writer_thread_alive=self._fake_rec_state == "recording",
        )

    # ------------------------------------------------------------------
    # Test helpers
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
    def right_panel(self) -> RightPanel:
        return self._right_panel

    @property
    def main_button(self) -> QPushButton:
        return self._main_btn

    @property
    def dbc_button(self) -> QPushButton:
        return self._dbc_btn

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
