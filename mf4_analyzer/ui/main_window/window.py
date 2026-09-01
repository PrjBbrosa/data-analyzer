"""MainWindow: top-level QMainWindow assembling the application UI."""
# Phase 2 complete: no legacy shims remain. The 3-pane topology
# (Toolbar + FileNavigator + ChartStack + Inspector) is the only owner
# of state; MainWindow is a router between them.

import importlib
import sys

import numpy as np
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from collections import OrderedDict

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QColorDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QStatusBar,
    QWidget,
)
from PyQt5.QtCore import QEvent, QEventLoop, QTimer, Qt

from ...io import DataLoader, FileData, HAS_ASAMMDF
from ...signal import (
    FFTAnalyzer,
    assess_speed_for_order,
    energy_band_fmax,
    resolve_nfft,
    resolve_order_nfft,
)
from ... import app_meta
from ... import db_reference
from ..compute_progress import ComputeProgressWidget
from ..plot_risk import PlotRisk, PlotRiskLevel, estimate_time_overlay_risk
from ..time_xaxis import (
    CHANNEL_MODE,
    EXACT_SOURCE,
    PER_SOURCE_NAME,
    TIME_MODE,
    CursorXAxisContext,
    CustomXAxisSpec,
    TimePlotIssue,
    apply_unit_cohort,
    channel_unit,
    resolve_custom_xaxis,
    selection_payload,
    spec_from_selection,
)
from ..navigator_order import NavigatorOrderState
from .. import hints

from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text
from ._sentinel import _INSPECTOR_TIME_RANGE
from ._state_holders import (
    CustomXAxisState,
    ProjectRestoreHealth,
    TimeRenderGate,
    ViewFocusState,
)
from ._analysis_mixin import AnalysisMixin
from ._drop_import_mixin import DropImportMixin
from ._fft_mixin import FFTMixin
from ._order_mixin import OrderMixin
from ._fft_time_mixin import FFTTimeMixin
from ._frf_mixin import FrfMixin
from ._channel_scope_mixin import ChannelScopeMixin
from ._project_io_mixin import ProjectIOMixin
from ._view_mixin import ViewMixin


# v2: default off (glyph-only ``?``). Bumped so prior "on" prefs do not keep
# crushed rotating copy next to the QuickRef entry after this product change.
_STATUS_HINTS_VISIBLE_SETTINGS_KEY = "quickref/status_hints_visible_v2"


@dataclass
class TimePlotSlot:
    """One attempted ``(fid, channel)`` in workspace order.

    Success slots carry the drawable row(s) for that target (original plus an
    optional filtered companion). Recoverable failures carry a placeholder
    issue so subplot layout can keep the row instead of collapsing it.
    """

    key: tuple[str, str]
    kind: str
    issue: TimePlotIssue | None = None
    rows: list = field(default_factory=list)

    def placeholder_row(self):
        fid, channel = self.key
        issue = self.issue
        source = str((issue.source_label if issue is not None else "") or fid)
        target = str((issue.target_channel if issue is not None else "") or channel)
        detail = str((issue.detail if issue is not None else "") or "无法绘制")
        return (
            f"{source} / {target}",
            True,
            np.array([], dtype=float),
            np.array([], dtype=float),
            "#9aa0a6",
            "",
            str(fid),
            {
                "placeholder": True,
                "placeholder_reason": detail,
                "placeholder_code": issue.code if issue is not None else "",
                "target_channel": target,
            },
        )


@dataclass
class TimePlotBuildResult:
    """One authoritative TimeDomain payload plus its render accounting."""

    rows: list = field(default_factory=list)
    issues: list[TimePlotIssue] = field(default_factory=list)
    attempted_channel_keys: set[tuple[str, str]] = field(default_factory=set)
    successful_channel_keys: set[tuple[str, str]] = field(default_factory=set)
    slots: list = field(default_factory=list)
    # ``None`` = time mode / no drawable custom-X cohort resolved.
    # ``""`` = a drawable custom-X cohort whose known unit is empty.
    x_unit: str | None = None

    def __bool__(self):
        return bool(self.rows)

    def render_rows(self, mode):
        """Rows the canvas should consume for ``mode``.

        Overlay keeps success-only rows. Subplot walks ``slots`` so placeholders
        stay in workspace order; tests that only populate ``rows`` still work.
        """
        if mode == "subplot" and self.slots:
            out = []
            for slot in self.slots:
                if slot.kind == "success":
                    out.extend(slot.rows)
                else:
                    out.append(slot.placeholder_row())
            return out
        return list(self.rows)


class SurfaceStatusBar(QStatusBar):
    """QStatusBar API, displayed as the bottom rounded surface inside the tray."""

    HEIGHT = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("surfaceStatusBar")
        self.setContentsMargins(8, 1, 8, 1)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(self.HEIGHT)
        # Native QStatusBar paints showMessage() into a left gutter. Once the
        # QuickRef bar occupies that side, the gutter crushes into a glyph
        # remnant beside '?'. Keep currentMessage() for callers; never paint.
        self._logical_message = ""
        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(self.clearMessage)

    def showMessage(self, message, timeout=0):  # noqa: N802 - Qt API
        self._logical_message = str(message or "")
        self._message_timer.stop()
        super().showMessage("", 0)
        if int(timeout or 0) > 0 and self._logical_message:
            self._message_timer.start(int(timeout))

    def currentMessage(self):  # noqa: N802 - Qt API
        return self._logical_message

    def clearMessage(self):  # noqa: N802 - Qt API
        self._message_timer.stop()
        self._logical_message = ""
        super().clearMessage()

    def event(self, event):
        result = super().event(event)
        if event.type() in (
            QEvent.LayoutRequest,
            QEvent.Resize,
            QEvent.Show,
            QEvent.PolishRequest,
        ):
            self._center_hosted_widgets()
        return result

    def _center_hosted_widgets(self):
        """Keep hosted chrome inside the 1px hairline and vertically centered.

        QStatusBar top-aligns permanent widgets. A 26px hint in a 32px pill
        then sits high and its opaque fill can still kiss the bottom stroke.
        """
        inner_top = 1
        inner_h = max(0, self.height() - 2)
        names = {
            "chartHintBar",
            "surfaceHelpButton",
            "surfaceVersionButton",
            "plotRiskLabel",
            "computeProgressWidget",
        }
        for child in list(self.children()):
            if not isinstance(child, QWidget) or child.parent() is not self:
                continue
            # Native QStatusBar may still create an unnamed QLabel for the
            # temporary message. Hide it even if our showMessage() override
            # already suppressed the paint-path copy.
            if not child.objectName() and isinstance(child, QLabel):
                child.hide()
                child.setFixedWidth(0)
                continue
            if child.width() <= 2 and not child.objectName():
                child.hide()
                continue
            if child.objectName() not in names:
                continue
            h = child.height()
            if h <= 0:
                continue
            y = inner_top + max(0, (inner_h - h) // 2)
            if child.y() != y:
                child.move(child.x(), y)


class MainWindow(
    DropImportMixin, AnalysisMixin, FFTMixin, OrderMixin, FFTTimeMixin, FrfMixin,
    ChannelScopeMixin, ProjectIOMixin, ViewMixin, QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(app_meta.WINDOW_TITLE)
        self.setGeometry(100, 100, 1450, 850);
        # Spec §9 minimum window size: 1100 × 640.
        self.setMinimumSize(1100, 640)
        self.files = OrderedDict();
        self.navigator_order = NavigatorOrderState()
        self._fc = 0;
        self._active = None
        self._project_path = None
        # Applied custom-X state and time-domain View focus each live in one
        # named holder (spec D-E2).  Built before _init_ui() so the property
        # shims below always have a target.
        self._custom_xaxis = CustomXAxisState()
        self._view_focus = ViewFocusState()
        # Serializes the time render pipeline against re-entrant View
        # switches (see TimeRenderGate + ViewMixin._time_render_scope).
        self._time_render = TimeRenderGate()
        # Stage 1 degraded-save guard: missing project sources / dropped pane
        # refs. Mutations go through the holder (not multi-file rebinds).
        self._project_restore_health = ProjectRestoreHealth()
        try:
            self._blf_dbc_history = self._load_recent_blf_dbc_history()
        except Exception:
            self._blf_dbc_history = []
        from ..analysis_jobs import AnalysisJobService
        self._analysis_jobs = AnalysisJobService(self)
        self._last_batch_preset = None
        self._batch_sheet = None
        self._ultraview_sheet = None
        self._acquisition_cockpit_window = None
        # dB-reference-defaults Task 5: MainWindow owns the ONE shared
        # settings/service instance injected into all three Contextual
        # controls (spec §11.1 "MainWindow/Inspector 共享一个 service/store").
        from ..db_reference_settings import DbReferenceSettingsStore
        self.db_reference_store = DbReferenceSettingsStore(
            self._db_reference_settings()
        )
        self._init_ui()
        self._init_channel_scope()
        # D-E1: the cross-section analysis helpers get their collaborators
        # injected by name instead of reaching through `self`.  Built after
        # _init_ui() because inspector / chart_stack / analysis_managers are
        # created there.  `files` is passed as a provider: the attribute is
        # rebound on project open/close, so a captured mapping would go stale.
        from .analysis_context import AnalysisContext
        self._analysis_context = AnalysisContext(
            inspector=self.inspector,
            chart_stack=self.chart_stack,
            analysis_managers=self.analysis_managers,
            db_reference_store=self.db_reference_store,
            files_provider=lambda: self.files,
        )
        from functools import partial
        from .fft_time_coordinator import (
            FftTimeCoordinator,
            make_fft_time_analysis_key,
        )
        fft_time_cache = self.analysis_caches['fft_time']
        self._fft_time_coordinator = FftTimeCoordinator(
            fft_time_cache,
            self._analysis_jobs,
            partial(make_fft_time_analysis_key, fft_time_cache.make_key),
            store_result=lambda view_id, pane_idx, key, result: (
                self._store_analysis_result(
                    'fft_time', view_id, pane_idx, key, result
                )
            ),
        )
        from .frf_coordinator import FrfCoordinator
        self._frf_coordinator = FrfCoordinator(
            self.analysis_caches['frf'],
            self._analysis_jobs,
            store_result=lambda view_id, pane_idx, key, result: (
                self._store_analysis_result(
                    'frf', view_id, pane_idx, key, result
                )
            ),
            parent=self,
        )
        from .ultraview_coordinator import UltraViewCoordinator
        self._ultraview = UltraViewCoordinator(self, parent=self)
        from .wwt_import_coordinator import WwtImportCoordinator
        self._wwt_import = WwtImportCoordinator(self)
        self._init_drop_import()
        self._connect()

    # -- compatibility shims for the custom-X holder (spec D-E2) -----------
    # State moved onto ``self._custom_xaxis``; these keep the historical
    # attribute names readable and writable so callers outside this package
    # (``ui/view_bridge.py`` reads them via ``getattr``) and tests that poke
    # them directly need no change. New code should use the holder.

    @property
    def _custom_xaxis_spec(self):
        return self._custom_xaxis.spec

    @_custom_xaxis_spec.setter
    def _custom_xaxis_spec(self, value):
        self._custom_xaxis.spec = value

    @property
    def _custom_xaxis_fid(self):
        return self._custom_xaxis.fid

    @_custom_xaxis_fid.setter
    def _custom_xaxis_fid(self, value):
        self._custom_xaxis.fid = value

    @property
    def _custom_xaxis_ch(self):
        return self._custom_xaxis.ch

    @_custom_xaxis_ch.setter
    def _custom_xaxis_ch(self, value):
        self._custom_xaxis.ch = value

    @property
    def _custom_xlabel(self):
        return self._custom_xaxis.xlabel

    @_custom_xlabel.setter
    def _custom_xlabel(self, value):
        self._custom_xaxis.xlabel = value

    # -- compatibility shim for the section progress tokens (spec D-E2) ----
    # The tokens now live on AnalysisJobService, whose batch lifetime they
    # follow. This keeps the old dict-shaped access working for tests that
    # poke individual sections.

    @property
    def _analysis_progress_tokens(self):
        return self._analysis_jobs.progress_tokens

    @_analysis_progress_tokens.setter
    def _analysis_progress_tokens(self, value):
        self._analysis_jobs.progress_tokens = value

    # -- compatibility shims for the View-focus holder (spec D-E2) ---------

    @property
    def _primary_view_idx(self):
        return self._view_focus.primary

    @_primary_view_idx.setter
    def _primary_view_idx(self, value):
        self._view_focus.primary = value

    @property
    def _secondary_view_idx(self):
        return self._view_focus.secondary

    @_secondary_view_idx.setter
    def _secondary_view_idx(self, value):
        self._view_focus.secondary = value

    @property
    def _focused_view_idx(self):
        return self._view_focus.focused

    @_focused_view_idx.setter
    def _focused_view_idx(self, value):
        self._view_focus.focused = value

    def _db_reference_settings(self):
        """``QSettings`` for the shared dB-reference catalog store.

        Reuses the SAME isolatable factory the Inspector preset bars already
        call (``_preset_settings()``) instead of constructing
        ``QSettings("MF4Analyzer", "DataAnalyzer")`` directly. Tests
        monkeypatch that one factory to an isolated ini file under
        ``tmp_path`` (``tests/ui/conftest.py::_isolate_qsettings``); a fresh
        direct ``QSettings(org, app)`` call here uses the NativeFormat
        2-arg convenience constructor regardless of ``QSettings.
        setDefaultFormat``/``setPath`` (verified: it still resolves to the
        real macOS plist / Windows registry), so it would silently read/
        write the REAL native preferences store on every MainWindow-
        constructing test -- exactly the pollution class that fixture
        exists to prevent (mirrors the existing
        ``_project_io_mixin._blf_dbc_settings`` fallback pattern)."""
        from ..inspector_sections._helpers import _preset_settings
        return _preset_settings()

    def _init_ui(self):
        from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget
        from PyQt5.QtCore import Qt

        from ..chart_stack import ChartStack
        from ..file_navigator import FileNavigator
        from ..inspector import Inspector
        from ..toolbar import Toolbar
        from .. import view_bridge
        from ..view_state import TIME_DOMAIN_MAX_VIEWS, ViewManager

        cw = QWidget()
        self.setCentralWidget(cw)
        cw.setObjectName("centralTray")
        root = QVBoxLayout(cw)
        # Playground-tuned panel chrome (tracelab-panel-playground.html):
        #   top rhythm 3+44+3 (tray -> topbar -> three-pane row),
        #   outer side/bottom margin 5px,
        #   inter-pane gap 3px (the tray-colored QSplitter handle below),
        #   panel corner radius 7px (FileNavigator/ChartStack/Inspector QSS).
        root.setContentsMargins(5, 3, 5, 5)
        root.setSpacing(3)

        self.toolbar = Toolbar(self)
        root.addWidget(self.toolbar)

        from PyQt5.QtWidgets import QHBoxLayout
        from ..side_panels import Side, SidePanelStrip, PeekOverlay, SidePanelController

        splitter = QSplitter(Qt.Horizontal, self)
        self.splitter = splitter
        self.navigator = FileNavigator(self)
        self.chart_stack = ChartStack(self)
        self.chart_stack.set_source_label_resolver(self._cursor_fid_short_name)
        self.inspector = Inspector(self)
        splitter.addWidget(self.navigator)
        splitter.addWidget(self.chart_stack)
        splitter.addWidget(self.inspector)
        splitter.setSizes([250, 900, 288])
        splitter.setStretchFactor(0, 0)  # navigator: no stretch
        splitter.setStretchFactor(1, 1)  # chart_stack: absorbs all extra width
        splitter.setStretchFactor(2, 0)  # inspector: no stretch
        # Collapsible left/right so a handle-drag to the edge hides the panel
        # (SidePanelController.on_splitter_moved picks that up). Canvas never collapses.
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, True)
        splitter.setHandleWidth(3)
        self.navigator.setMinimumWidth(220)
        self.chart_stack.setMinimumWidth(400)
        self.inspector.setMinimumWidth(self.inspector.maximumWidth())

        # Edge strips flank the splitter; each is visible only while its side is
        # hidden. Wrapping the splitter in an HBox keeps the strips out of the
        # toolbar's vertical band.
        self._strip_left = SidePanelStrip(Side.LEFT)
        self._strip_right = SidePanelStrip(Side.RIGHT)
        strip_row = QWidget(self)
        self._strip_row = strip_row
        row = QHBoxLayout(strip_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._strip_left)
        row.addWidget(splitter, stretch=1)
        row.addWidget(self._strip_right)
        root.addWidget(strip_row, stretch=1)

        # Peek overlays are parented to the splitter row (NOT cw) so they float
        # over the canvas region only and never cover the toolbar; they are child
        # widgets (never top-level frameless windows) to avoid macOS native shadow.
        self._overlay_left = PeekOverlay(strip_row)
        self._overlay_right = PeekOverlay(strip_row)
        # canvas=self.chart_stack -> width changes are taken from the canvas pane,
        # looked up by live index so cross-side peek doesn't drift the index.
        # peek_width = inspector's docked width so the narrow navigator peeks out
        # to the same width as the right pane (L/R peek symmetry).
        self._panel_ctrl_left = SidePanelController(
            side=Side.LEFT, splitter=splitter, panel=self.navigator, panel_index=0,
            strip=self._strip_left, overlay=self._overlay_left, host=strip_row,
            default_width=250, canvas=self.chart_stack,
            peek_width=self.inspector.maximumWidth(), parent=self,
        )
        self._panel_ctrl_right = SidePanelController(
            side=Side.RIGHT, splitter=splitter, panel=self.inspector, panel_index=2,
            strip=self._strip_right, overlay=self._overlay_right, host=strip_row,
            default_width=288, canvas=self.chart_stack, parent=self,
        )
        splitter.splitterMoved.connect(
            lambda *_: (self._panel_ctrl_left.on_splitter_moved(),
                        self._panel_ctrl_right.on_splitter_moved())
        )

        # Convenience aliases pointing to children of ChartStack / Navigator —
        # these are real widgets reachable via the new topology, not shims.
        self.canvas_time = self.chart_stack.canvas_time
        self.canvas_fft = self.chart_stack.canvas_fft
        self.canvas_order = self.chart_stack.canvas_order
        self.canvas_fft_time = self.chart_stack.canvas_fft_time
        self.canvas_frf = self.chart_stack.canvas_frf
        self.channel_list = self.navigator.channel_list
        self.navigator.set_projection_role("time")
        # Time-domain cap is TIME_DOMAIN_MAX_VIEWS; analysis managers keep
        # MAX_VIEWS. ViewTabBar reads the per-manager value for ``+`` disable
        # and overflow.
        self.view_manager = ViewManager(self, max_views=TIME_DOMAIN_MAX_VIEWS)
        self._view_bridge = view_bridge
        self.view_tabbar = self.chart_stack.attach_view_tabbar(self.view_manager)
        self._view_focus.bind(active=self.view_manager.active, partner=None)

        # V7 Step 2: per-section analysis view managers (owned by ChartStack so
        # the per-section ViewTabBar can dereference a real manager at
        # construction) + per-section LRU result caches (owned here).
        from ..analysis_cache import AnalysisResultCache, FrfAnalysisResultCache
        from ._state_holders import AnalysisPinBook
        self.analysis_managers = self.chart_stack.analysis_managers
        # Pin book: holder owns the slot map (state-ownership ratchet).
        self._analysis_pins = AnalysisPinBook()
        self.analysis_caches = {
            'fft': AnalysisResultCache(
                32,
                pinned_provider=lambda: self._pinned_keys_for_section('fft'),
            ),
            'fft_time': AnalysisResultCache(
                12,
                pinned_provider=lambda: self._pinned_keys_for_section(
                    'fft_time'
                ),
            ),
            'frf': FrfAnalysisResultCache(
                12,
                pinned_provider=lambda: self._pinned_keys_for_section('frf'),
            ),
            'order': AnalysisResultCache(
                12,
                pinned_provider=lambda: self._pinned_keys_for_section('order'),
            ),
        }
        # `_applying_analysis_view` is AnalysisMixin's own re-entrancy guard;
        # its default lives with the owner (see AnalysisMixin) so exactly one
        # file writes it.
        # Post-load auto-recompute queue. A saved project carries each analysis
        # view's compute params + signal sources but NOT the numeric results
        # (recompute-on-open). open_project seeds this with every
        # (section, view_id) that has sources, then dispatches all of them
        # after the window finishes opening so every View returns to its
        # computed state without waiting for the user to visit the tab.
        self._analysis_restore_pending = set()
        # Identity of the inputs behind the last fft-canvas render. Re-entering
        # fft mode with the same signature reuses the retained stacked-page
        # canvas instead of wiping + rebuilding it (keeps the computed spectrum
        # alive across section round-trips and skips the preview rebuild cost).
        self._fft_last_render_sig = None

        self._status_hints_visible = self._load_status_hints_visible()
        self.statusBar = SurfaceStatusBar(self)
        root.addWidget(self.statusBar)
        self._status_hint_bar = None
        self._install_status_hint_bar(self.chart_stack.current_mode())
        self.chart_stack.mode_changed.connect(self._install_status_hint_bar)
        self.statusBar.showMessage("Ready")
        self._install_plot_risk_label()
        self._install_compute_progress()
        self._install_update_indicator()

        # Floating toast: parent is the main window so it floats above the
        # central canvas. Clearance is derived at show time from real bottom
        # chrome heights (status + View tabs), not a construct-time magic number.
        from ..widgets import Toast
        self._toast = Toast(self, margin_provider=self._toast_bottom_chrome_clearance)
        from ..markup import CopyThumbnail
        self._copy_thumbnail = CopyThumbnail(self)
        self._copy_thumbnail.clicked.connect(self._open_markup_editor)
        self._markup_editor = None

        # 操作速查 panel: lazy singleton + a global "?" shortcut that toggles it.
        self._quickref_panel = None
        self._install_quickref_shortcut()

    def _install_quickref_shortcut(self):
        """Bind '?' (and Shift+/ on layouts where ? needs Shift) to the panel."""
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        self._quickref_shortcut = QShortcut(QKeySequence(Qt.Key_Question), self)
        self._quickref_shortcut.setContext(Qt.ApplicationShortcut)
        self._quickref_shortcut.activated.connect(self.toggle_quickref_panel)

    def toggle_quickref_panel(self):
        """Show/hide the 操作速查 quick-reference panel (lazy singleton)."""
        if self._quickref_panel is None:
            from ..quickref_panel import QuickRefPanel
            from ...help import open_guide
            self._quickref_panel = QuickRefPanel(
                self,
                open_guide=open_guide,
                bottom_hints_visible=self.status_hints_visible(),
                set_bottom_hints_visible=self.set_status_hints_visible,
            )
        self._quickref_panel.toggle(anchor_widget=self)

    def _install_update_indicator(self):
        """Far-right status-bar update affordance: a cloud-download icon
        (no text, hover '检查更新') + the app version, linking to the release
        page."""
        from PyQt5.QtCore import Qt, QSize
        from PyQt5.QtWidgets import QToolButton
        from ...ui_kit.icons import Icons
        from ... import app_meta

        # 软件说明 icon sits to the LEFT of the version/update affordance.
        # Permanent widgets pack left→right in add order, so add this one
        # FIRST and the update button SECOND. 操作速查入口在 hint bar 左侧。
        import qtawesome as qta

        self._help_btn = QToolButton(self)
        self._help_btn.setObjectName("surfaceHelpButton")
        self._help_btn.setIcon(qta.icon('mdi.book-open-variant', color='#5b6472'))
        self._help_btn.setIconSize(QSize(18, 18))
        self._help_btn.setAutoRaise(True)
        self._help_btn.setCursor(Qt.PointingHandCursor)
        self._help_btn.setToolTip("软件说明")
        self._help_btn.clicked.connect(self._open_software_manual)
        self.statusBar.addPermanentWidget(self._help_btn)

        self._update_btn = QToolButton(self)
        self._update_btn.setObjectName("surfaceVersionButton")
        self._update_btn.setIcon(Icons.cloud_download())
        self._update_btn.setIconSize(QSize(18, 18))
        self._update_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._update_btn.setText(app_meta.APP_VERSION)
        self._update_btn.setAutoRaise(True)
        self._update_btn.setCursor(Qt.PointingHandCursor)
        self._update_btn.setToolTip(f"检查更新\n{app_meta.APP_CREDIT}")
        self._update_btn.clicked.connect(self._open_release_page)

        self.statusBar.addPermanentWidget(self._update_btn)
        status_layout = self.statusBar.layout()
        if status_layout is not None:
            status_layout.setAlignment(self._help_btn, Qt.AlignVCenter)
            status_layout.setAlignment(self._update_btn, Qt.AlignVCenter)

    def _install_plot_risk_label(self) -> None:
        self._plot_risk_label = QLabel(self)
        self._plot_risk_label.setObjectName("plotRiskLabel")
        self._plot_risk_label.setMinimumWidth(0)
        self._plot_risk_label.setMaximumWidth(520)
        self._plot_risk_label.setSizePolicy(
            QSizePolicy.Maximum, QSizePolicy.Fixed
        )
        self._plot_risk_label.setVisible(False)
        self.statusBar.addPermanentWidget(self._plot_risk_label, 0)

    def _install_compute_progress(self) -> None:
        self._compute_progress = ComputeProgressWidget(self)
        self._active_compute_progress_token = None
        self.statusBar.addPermanentWidget(self._compute_progress, 0)

    def _restore_progress_token(self):
        jobs = getattr(self, "_analysis_jobs", None)
        if jobs is None:
            return None
        return jobs.progress_token("restore")

    def _begin_compute_progress(
        self,
        label: str,
        total: int | None = None,
        token: object | None = None,
        *,
        process_events: bool = True,
    ) -> object:
        restore = self._restore_progress_token()
        if restore is not None and token is None:
            # Project restore owns the status-bar slot until it finishes.
            # A nested time-plot / section batch must not replace that token
            # or drain the restore pump with processEvents.
            return restore
        active_token = token if token is not None else object()
        self._active_compute_progress_token = active_token
        self._compute_progress.begin(label, total)
        if process_events and restore is None:
            # ExcludeUserInputEvents, never a bare processEvents(): this pump
            # exists only so the bar reaches the screen before a long
            # synchronous render. Delivering the queued clicks/keys here runs
            # the next View switch INSIDE the render that is still building
            # the previous one (see TimeRenderGate). Input stays queued and is
            # handled in order once the render returns.
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        return active_token

    def _update_compute_progress(
        self,
        current: int,
        total: int,
        label: str | None = None,
        token: object | None = None,
        *,
        process_events: bool = False,
        flush_events: bool = False,
    ) -> None:
        if self._active_compute_progress_token is None:
            return
        if (
            token is not None
            and token is not self._active_compute_progress_token
        ):
            return
        self._compute_progress.set_progress(current, total, label)
        restore = self._restore_progress_token()
        if process_events or flush_events:
            # Default path: repaint only the tiny status-bar widget.  Draining
            # the entire Qt queue during chart rebuild can paint the previous
            # plot mid-flight.  File-load passes ``flush_events=True`` so the
            # long synchronous import still lets the bar/label reach the screen.
            self._compute_progress.repaint()
        if restore is not None and process_events and not flush_events:
            # Full processEvents would nested-run the restore pump (beachball
            # + stolen navigator capture). Paint only.
            return
        if flush_events:
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _finish_compute_progress(
        self,
        label: str | None = None,
        token: object | None = None,
    ) -> None:
        restore = self._restore_progress_token()
        if restore is not None and (token is None or token is restore):
            # Section workers / time-plot finally blocks must not hide the
            # restore bar while later Views are still queued.
            return
        if (
            token is not None
            and token is not self._active_compute_progress_token
        ):
            return
        self._compute_progress.finish(label)
        self._active_compute_progress_token = None

    def _show_plot_risk(self, risk: PlotRisk) -> None:
        label = getattr(self, "_plot_risk_label", None)
        if label is None:
            return
        if risk.level is PlotRiskLevel.OK:
            self._clear_plot_risk()
            return
        label.setProperty("riskLevel", risk.level.value)
        label.setText(self._format_plot_risk_text(risk))
        label.setToolTip("\n".join(risk.reasons))
        label.style().unpolish(label)
        label.style().polish(label)
        label.setVisible(True)

    def _clear_plot_risk(self) -> None:
        label = getattr(self, "_plot_risk_label", None)
        if label is None:
            return
        label.clear()
        label.setToolTip("")
        label.setProperty("riskLevel", "")
        label.style().unpolish(label)
        label.style().polish(label)
        label.setVisible(False)

    def _format_plot_risk_text(self, risk: PlotRisk) -> str:
        points = self._format_count_zh(risk.sample_total, "点")
        prefix = "滤波 + 叠加" if risk.filter_enabled else "叠加模式"
        suffix = "风险较高" if risk.level is PlotRiskLevel.DANGER else "可能卡顿"
        return (
            f"{prefix}：{risk.channel_count} 个通道 / "
            f"{risk.series_count} 条曲线 / {points}，{suffix}"
        )

    def _format_count_zh(self, value: int, unit: str) -> str:
        value = int(value)
        if value >= 10_000_000:
            return f"{value / 10_000_000:.1f} 千万{unit}"
        if value >= 10_000:
            return f"{value / 10_000:.1f} 万{unit}"
        return f"{value} {unit}"

    def _open_software_manual(self):
        """Open the whole-app TraceLab usage manual in the default browser."""
        from ...help import open_guide
        if not open_guide('manual'):
            self.toast("找不到软件说明文件", 'warn')

    def _open_release_page(self):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        from ... import app_meta
        QDesktopServices.openUrl(QUrl(app_meta.RELEASE_URL))

    def _install_status_hint_bar(self, mode=None):
        """Keep exactly one mode hint bar in the global status line.

        The QuickRef ``?`` is part of that bar and remains available even when
        the optional hint text is disabled.
        """
        mode = mode or self.chart_stack.current_mode()
        target = self.chart_stack.hint_bar_for_mode(mode)
        current = getattr(self, "_status_hint_bar", None)
        if current is target and target.parentWidget() is self.statusBar:
            self._set_status_hint_text_visible(target, self.status_hints_visible())
            return
        if current is not None:
            self.statusBar.removeWidget(current)
            current.hide()
            current.setParent(None)
        self._status_hint_bar = self.chart_stack.take_hint_bar(mode, self.statusBar)
        self.statusBar.insertPermanentWidget(0, self._status_hint_bar, 1)
        status_layout = self.statusBar.layout()
        if status_layout is not None:
            status_layout.setAlignment(self._status_hint_bar, Qt.AlignVCenter)
        self._set_status_hint_text_visible(
            self._status_hint_bar, self.status_hints_visible()
        )

    @staticmethod
    def _set_status_hint_text_visible(bar, visible):
        """Toggle hint copy while retaining the existing QuickRef ``?`` entry."""
        if bar is None:
            return
        bar.setVisible(True)
        for name in ("chartHintContext", "chartHintDiscovery"):
            label = bar.findChild(QLabel, name, Qt.FindDirectChildrenOnly)
            if label is not None:
                # Keeping the labels in the layout preserves the original
                # left-anchored geometry of the ``?`` button. Hiding them
                # outright makes QHBoxLayout center the lone visible button.
                label.setVisible(True)
                label.setStyleSheet("" if visible else "color: transparent;")

    def _status_hint_settings(self):
        """Use the app's isolatable settings factory for the QuickRef toggle."""
        from ..inspector_sections._helpers import _preset_settings
        return _preset_settings()

    def _load_status_hints_visible(self):
        try:
            return bool(self._status_hint_settings().value(
                _STATUS_HINTS_VISIBLE_SETTINGS_KEY,
                False,
                type=bool,
            ))
        except Exception:
            return False

    def status_hints_visible(self):
        return bool(getattr(self, "_status_hints_visible", False))

    def set_status_hints_visible(self, visible):
        """Show/hide bottom hint text and persist the preference.

        Default is off: the status line keeps only the ``?`` QuickRef entry so
        rotating/discovery copy cannot be crushed into a clipped remnant next
        to the button. Users can still re-enable hints from the QuickRef panel.
        """
        visible = bool(visible)
        self._status_hints_visible = visible
        try:
            settings = self._status_hint_settings()
            settings.setValue(_STATUS_HINTS_VISIBLE_SETTINGS_KEY, visible)
            settings.sync()
        except Exception:
            pass
        bar = getattr(self, "_status_hint_bar", None)
        self._set_status_hint_text_visible(bar, visible)
        panel = getattr(self, "_quickref_panel", None)
        if panel is not None:
            panel.set_bottom_hints_visible(visible)

    def _toast_bottom_chrome_clearance(self):
        """Sum real bottom-chrome heights so the toast clears View tabs.

        Layout bottom-up: SurfaceStatusBar (hosts the mode hint bar) sits at
        the window edge; the active ViewTabBar sits just above it inside the
        chart pane. A small breathing gap keeps the toast from kissing the
        View row. Falls through to Toast.DEFAULT_BOTTOM_MARGIN only when
        chrome widgets are not yet measurable.
        """
        gap = 12
        total = gap
        status = getattr(self, "statusBar", None)
        if status is not None and status.isVisible():
            h = int(status.height() or 0)
            if h > 0:
                total += h
        tabbar = self._visible_view_tabbar()
        if tabbar is not None and tabbar.isVisible():
            h = int(tabbar.height() or 0)
            if h > 0:
                total += h
        # If nothing measurable yet (very early init), keep the historical
        # fallback so offscreen hosts still clear a typical chrome stack.
        if total <= gap:
            from ..widgets import Toast
            return Toast.DEFAULT_BOTTOM_MARGIN
        return total

    def _visible_view_tabbar(self):
        chart = getattr(self, "chart_stack", None)
        if chart is None:
            return getattr(self, "view_tabbar", None)
        mode = chart.current_mode()
        if mode == "time":
            return getattr(self, "view_tabbar", None)
        page = {
            "fft": getattr(chart, "page_fft", None),
            "fft_time": getattr(chart, "page_fft_time", None),
            "frf": getattr(chart, "page_frf", None),
            "order": getattr(chart, "page_order", None),
        }.get(mode)
        return getattr(page, "tabbar", None) if page is not None else None

    def _channel_editor_toast_host(self):
        """Drawer that should own toasts: open, not closing, not mid-fallback.

        Export keeps the drawer open, so feedback paints on it. Apply emits
        then ``accept()``, so routing onto that surface would vanish with it.
        A fallback already in flight must not bounce back into the drawer.
        """
        if getattr(self, "_toast_forwarding", False):
            return None
        drawer = getattr(self, "_channel_editor_drawer", None)
        if drawer is None or not drawer.isVisible():
            return None
        if getattr(drawer, "is_closing", False):
            return None
        if getattr(drawer, "_forwarding", False):
            return None
        return drawer

    # ---- public toast helper ----
    def toast(self, msg, level='info'):
        """Show a transient acknowledgement toast at the bottom of the window.

        While the channel-editor drawer is modal and visible, paint on the
        drawer instead — MainWindow's toast would sit *under* it.
        """
        if not msg:
            return
        drawer = self._channel_editor_toast_host()
        if drawer is not None:
            self._toast_forwarding = True
            try:
                drawer.toast(msg, level)
                return
            finally:
                self._toast_forwarding = False
        self._toast.show_message(msg, level=level)

    def _status_message(self, message, timeout=0):
        """Status-bar feedback; during channel-editor modal, surface via toast.

        The modal drawer occludes the main status bar, so the same text rides
        the drawer's self-owned toast (BatchSheet pattern). Apply is about to
        close the drawer, so that path stays on the main status bar.
        """
        drawer = self._channel_editor_toast_host()
        if drawer is not None:
            drawer.toast(message, "info")
            return
        self.statusBar.showMessage(message, timeout)

    def _warn_action_blocked(self, message):
        """Surface an explicit user action that cannot proceed."""
        self.statusBar.showMessage(message, 3000)
        self.toast(message, "warning")

    def _publish_copied_pixmap(self, pix):
        """Publish a freshly captured chart-card pixmap.

        Clipboard + toast are the primary acknowledgement; the thumbnail is an
        optional second-step editor entry point.
        """
        if pix is None or pix.isNull():
            return
        QApplication.clipboard().setPixmap(pix)
        msg = "已复制到剪贴板 · 可直接粘贴"
        self.statusBar.showMessage(msg, 2000)
        self.toast(msg, 'success')
        self._copy_thumbnail.present(pix)

    def _publish_annotated_pixmap(self, pix):
        """Publish the edited image without re-opening the thumbnail loop."""
        if pix is None or pix.isNull():
            return
        QApplication.clipboard().setPixmap(pix)
        msg = "已复制(含标注)"
        self.statusBar.showMessage(msg, 2000)
        self.toast(msg, 'success')

    def _create_markup_editor(self, pix, on_done):
        from ..markup import MarkupEditor
        return MarkupEditor(pix, on_done=on_done, parent=self)

    def _open_markup_editor(self, pix):
        if pix is None or pix.isNull():
            return
        editor = self._create_markup_editor(pix, self._publish_annotated_pixmap)
        self._markup_editor = editor
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, '_toast') and self._toast.isVisible():
            self._toast._reposition()
        if hasattr(self, '_panel_ctrl_left'):
            self._panel_ctrl_left.reposition()
            self._panel_ctrl_right.reposition()

    def moveEvent(self, e):
        super().moveEvent(e)
        if hasattr(self, '_panel_ctrl_left'):
            self._panel_ctrl_left.reposition()
            self._panel_ctrl_right.reposition()

    def _on_analysis_job_finished(self, section, ctx, result):
        if section == 'order':
            self._on_order_job_finished(ctx, result)
        finisher = getattr(self, "_finish_analysis_restore_if_idle", None)
        if callable(finisher):
            QTimer.singleShot(0, finisher)

    def _on_analysis_job_failed(self, section, ctx, error):
        if section == 'order':
            self._on_order_job_failed(ctx, error)
        finisher = getattr(self, "_finish_analysis_restore_if_idle", None)
        if callable(finisher):
            QTimer.singleShot(0, finisher)

    def _on_analysis_job_progress(self, section, done, total):
        if section == 'fft_time':
            self._on_fft_time_job_progress(done, total)
        elif section == 'frf':
            self._on_frf_job_progress(done, total)
        elif section == 'order':
            self._on_order_job_progress(done, total)

    def _connect(self):
        # --- New-module wiring ---
        self._analysis_jobs.finished.connect(self._on_analysis_job_finished)
        self._analysis_jobs.failed.connect(self._on_analysis_job_failed)
        self._analysis_jobs.progress.connect(self._on_analysis_job_progress)
        self._fft_time_coordinator.render_requested.connect(
            self._on_fft_time_render_requested
        )
        self._fft_time_coordinator.failed.connect(self._on_fft_time_failed)
        self._fft_time_coordinator.batch_started.connect(
            self._on_fft_time_batch_started
        )
        self._frf_coordinator.render_requested.connect(
            self._on_frf_render_requested
        )
        self._frf_coordinator.failed.connect(self._on_frf_failed)
        self._frf_coordinator.job_queued.connect(self._on_frf_job_queued)
        self.toolbar.open_requested.connect(self.open_files_or_project)
        self.toolbar.save_project_requested.connect(self.save_project_via_dialog)
        self.toolbar.save_project_as_requested.connect(self.save_project_as_via_dialog)
        self.toolbar.batch_requested.connect(self.open_batch)
        self.chart_stack.open_ultraview_requested.connect(self.open_ultraview)
        self.chart_stack.open_ultraview_unplaced_requested.connect(
            self.open_ultraview_unplaced
        )
        self.toolbar.acquisition_cockpit_requested.connect(self.open_acquisition_cockpit)
        self.toolbar.mode_changed.connect(self._on_mode_changed)
        self.chart_stack.image_captured.connect(
            lambda pix: self._publish_copied_pixmap(pix)
        )
        self.inspector.preset_acknowledged.connect(
            lambda level, msg: self.toast(msg, level)
        )

        self.navigator.channels_changed.connect(self._ch_changed)
        self.navigator.visibility_changed.connect(
            self._on_time_channel_visibility_changed
        )
        self.navigator.channel_editor_requested.connect(self.open_editor)
        self.navigator.file_activated.connect(self._on_file_activated)
        self.navigator.file_close_requested.connect(self._on_file_close_requested)
        self.navigator.file_group_close_requested.connect(self._close_files)
        self.navigator.close_all_requested.connect(self._on_close_all_requested)
        self.navigator.files_attach_requested.connect(
            self._attach_files_from_drop
        )
        self.navigator.file_order_requested.connect(
            self._on_file_order_requested
        )
        self.navigator.channel_order_requested.connect(
            self._on_channel_order_requested
        )
        self.navigator.files_detach_requested.connect(
            self._detach_files_from_active_context
        )
        self.navigator.follow_prefs_changed.connect(
            self._on_follow_prefs_changed
        )
        self.navigator.channel_config_save_requested.connect(
            self._save_current_channel_config
        )
        self.navigator.channel_config_apply_requested.connect(
            self._apply_selected_channel_config
        )
        self.navigator.channel_config_manage_requested.connect(
            self._manage_channel_config
        )
        self.navigator.channel_config_selection_changed.connect(
            self._on_channel_config_selection_changed
        )
        self.navigator.primary_channel_requested.connect(
            self._on_primary_channel_requested
        )
        self.navigator.channel_context_menu_requested.connect(
            lambda: self.chart_stack.mark_discovered("channel.right_click")
        )
        self.channel_list.axis_groups_changed.connect(self._ch_changed)

        # Canvas cursor signals are owned by ChartStack; MainWindow doesn't
        # need to subscribe (ChartStack updates the pill itself).

        # Inspector signals wire up in Phase 2 when real sections land. In
        # Phase 1, these are no-ops but must exist so Task 2.x edits are
        # minimal additions rather than rewrites.
        self.inspector.plot_time_requested.connect(
            lambda: self.plot_time(user_initiated=True)
        )
        self.navigator.record_curve_visibility_toggled.connect(
            self._on_record_curve_visibility_toggled
        )
        # Live display toggles for the filter overlay: 显示原始 / 显示滤波后
        # flip the visibility of the EXISTING curves on the focused time canvas
        # without a re-plot (秒生效，不重绘). The axis/row stays put — a companion
        # dashed trace shares its source channel's ViewBox, so hiding the
        # original must NOT tear the axis down.
        fp = getattr(self.inspector, "filter_panel", None)
        if fp is not None:
            fp.original_visibility_changed.connect(self._on_show_original_toggled)
            fp.filtered_visibility_changed.connect(self._on_show_filtered_toggled)
        self.inspector.fft_requested.connect(self.do_fft)
        self.inspector.frf_requested.connect(self.do_frf)
        self.inspector.frf_view_in_time_requested.connect(
            self._view_frf_pair_in_time_domain
        )
        self.inspector.frf_ctx.pair_changed.connect(self._on_frf_pair_changed)
        self.inspector.frf_ctx.compute_params_changed.connect(
            self._on_frf_compute_params_changed
        )
        self.inspector.frf_ctx.display_params_changed.connect(
            self._on_frf_display_params_changed
        )
        self.inspector.order_time_requested.connect(self.do_order_time)
        for _analysis_section, _analysis_ctx in (
            ('fft', self.inspector.fft_ctx),
            ('fft_time', self.inspector.fft_time_ctx),
            ('order', self.inspector.order_ctx),
        ):
            _analysis_ctx.compute_params_changed.connect(
                lambda params, section=_analysis_section:
                self._on_analysis_compute_params_changed(section, params)
            )
            _analysis_ctx.display_params_changed.connect(
                lambda params, section=_analysis_section:
                self._on_analysis_display_params_changed(section, params)
            )
        # dB reference is display-only: changing it while in FFT mode should
        # immediately re-render without recompute. Re-evaluate _fft_render_signature
        # (which now includes db_reference) so the stale-check in _enter_fft_mode
        # detects the change and re-draws from cache.
        self.inspector.fft_ctx.spin_db_ref.valueChanged.connect(
            lambda _: self._on_db_reference_value_edited(
                'fft', self._enter_fft_mode,
            )
        )
        # Order dB reference is display-only: changing it re-renders from cache
        # (do_order_time hits cache, calls _render_order_on, no worker dispatch).
        self.inspector.order_ctx.spin_db_ref.valueChanged.connect(
            lambda _: self._on_db_reference_value_edited(
                'order', self.do_order_time,
            )
        )
        # FFT-vs-Time dB reference is also display-only.  Changing it should
        # take the normal cache-hit render path (force=False) so the current
        # SpectrogramResult is redrawn with the new render-time reference
        # without scheduling a needless recompute.
        self.inspector.fft_time_ctx.spin_db_ref.valueChanged.connect(
            lambda _: self._on_db_reference_value_edited(
                'fft_time', lambda: self.do_fft_time(force=False),
            )
        )
        # dB-reference-defaults Task 5: every section's manage button opens
        # the ONE shared DbReferenceDefaultsDialog editing the ONE global
        # catalog service (spec §11.1); each lambda only carries which
        # section/View was focused when its own button was clicked.
        for _drc_section in ('fft', 'fft_time', 'order'):
            self._analysis_ctx(_drc_section).db_reference_control.manage_requested.connect(
                lambda s=_drc_section: self._open_db_reference_dialog(s)
            )
        # dB-reference-defaults nudge feed (spec S5 / A17), ordering fix: a
        # genuine user commit on an Auto-mode editor auto-promotes to Manual
        # INSIDE DbReferenceControl._on_editor_value_committed, which fires
        # the editor's base ``valueChanged`` (wired above, driving the
        # existing re-render) BEFORE it flips the mode -- so a stamp read off
        # ``valueChanged`` alone can observe the STALE pre-flip mode for that
        # one keystroke. ``control.value_committed`` is re-emitted from that
        # SAME handler strictly AFTER any mode flip, so re-stamping there
        # (additive, no render effect) always lands on the correct final
        # mode/value.
        for _drc_section in ('fft', 'fft_time', 'order'):
            self._analysis_ctx(_drc_section).db_reference_control.value_committed.connect(
                lambda _v, s=_drc_section: self._stamp_db_reference_nudge_facts(s)
            )
        self.inspector.xaxis_apply_requested.connect(self._apply_xaxis)
        self.inspector.xaxis_drop_hint_dismissed.connect(
            self._on_xaxis_drop_hint_dismissed
        )
        self.inspector.rebuild_time_requested.connect(self._show_rebuild_popover)
        self.inspector.tick_density_changed.connect(self._update_all_tick_density_pair)
        self.chart_stack.tick_density_changed.connect(self._update_all_tick_density_pair)
        self.inspector.remark_toggled.connect(
            lambda enabled: self.chart_stack.set_annotation_enabled('fft', enabled)
        )
        self.chart_stack.annotation_enabled_changed.connect(
            self._on_annotation_enabled_changed
        )
        self.chart_stack.cursor_mode_changed.connect(self._on_cursor_mode_changed)
        self.chart_stack.analysis_cursor_mode_changed.connect(
            self._on_analysis_cursor_mode_changed
        )
        self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)
        self.chart_stack.focus_changed.connect(self._on_chart_focus_changed)
        self.chart_stack.channel_drop_requested.connect(self._on_time_channel_drop)
        self.chart_stack.quickref_requested.connect(self.toggle_quickref_panel)
        self.chart_stack.home_triggered.connect(
            lambda: self._hint_focused_pane("复位")
        )
        # P2 Task 9 1b: the secondary (compare) pane's own 分屏/叠加 control
        # asks for a layout replot of just that canvas, X-window preserved.
        self.chart_stack.set_secondary_replot_callback(
            self._replot_secondary_preserving_xlim
        )
        self.inspector.signal_changed.connect(self._on_inspector_signal_changed)
        # Auto-NFFT preview data hooks: the collapsed 谱参数 headers resolve their
        # displayed 自动(N) through the SAME data-aware resolvers the compute paths
        # use (resolve_order_nfft / resolve_nfft), so a low-Fs / short capture no
        # longer advertises a meaningless 8192. Pull-based: each provider reads the
        # current selection + inspector time range on demand.
        self.inspector.order_ctx.set_auto_nfft_provider(self._order_preview_revs)
        self.inspector.fft_ctx.set_auto_nfft_provider(self._fft_preview_n_samples)
        self.inspector.fft_time_ctx.set_auto_nfft_provider(
            self._fft_time_preview_n_samples
        )
        self.view_tabbar.switch_requested.connect(self._switch_view)
        self.view_tabbar.new_requested.connect(self._on_view_new)
        self.view_tabbar.delete_requested.connect(self._on_view_delete)
        self.view_tabbar.overflow_delete_requested.connect(
            self._on_overflow_view_delete
        )
        self.view_tabbar.close_others_requested.connect(self._on_view_close_others)
        self.view_tabbar.close_all_requested.connect(self._on_view_close_all)
        self.view_tabbar.duplicate_requested.connect(self._on_view_duplicate)
        self.view_tabbar.rename_requested.connect(self._on_time_view_rename)
        self.view_tabbar.color_requested.connect(self._on_view_color)
        self.view_tabbar.reorder_requested.connect(self.view_manager.reorder)
        self.view_tabbar.split_requested.connect(self.view_manager.set_split)
        self.view_tabbar.clear_split_requested.connect(self._on_view_clear_split)
        self.view_manager.active_changed.connect(self._apply_active_view)
        self.view_manager.split_changed.connect(self._on_view_split)
        self._install_view_shortcuts()

        # V7 Step 2: per-section analysis tab bars ↔ managers. The ViewTabBar
        # already self-connects views_changed/active_changed/split_changed to
        # its own refresh in __init__, so here we only wire the user-intent
        # signals into the manager and the manager.active_changed into the
        # view-switch pipeline (_on_analysis_view_switched). split_requested /
        # clear_split_requested mean "add / remove the second pane of THIS
        # view" for analysis sections (panes live inside the view, not the
        # time-domain cross-view pairing).
        for sec, page in (
            ('fft', self.chart_stack.page_fft),
            ('fft_time', self.chart_stack.page_fft_time),
            ('frf', self.chart_stack.page_frf),
            ('order', self.chart_stack.page_order),
        ):
            mgr = self.analysis_managers[sec]
            bar = page.tabbar
            bar.switch_requested.connect(
                lambda idx, s=sec: self._on_analysis_switch(s, idx))
            bar.new_requested.connect(
                lambda s=sec: self._on_analysis_new(s))
            bar.delete_requested.connect(
                lambda idx, s=sec: self._on_analysis_delete(s, idx))
            bar.overflow_delete_requested.connect(
                partial(self._on_analysis_delete, sec))
            bar.close_others_requested.connect(
                partial(self._on_analysis_close_others, sec))
            bar.close_all_requested.connect(
                partial(self._on_analysis_close_all, sec))
            bar.rename_requested.connect(
                partial(self._on_analysis_view_rename, sec))
            bar.duplicate_requested.connect(
                lambda idx, s=sec: self._on_analysis_duplicate(s, idx))
            bar.color_requested.connect(
                lambda idx, s=sec: self._on_analysis_color(s, idx))
            bar.reorder_requested.connect(mgr.reorder)
            bar.split_requested.connect(
                lambda _idx, s=sec: self._on_analysis_split(s, True))
            bar.clear_split_requested.connect(
                lambda _idx, s=sec: self._on_analysis_split(s, False))
            mgr.active_changed.connect(
                lambda idx, s=sec: self._on_analysis_view_switched(s, idx))
            page.focus_changed.connect(
                lambda idx, s=sec: self._on_analysis_focus_changed(s, idx))
            # V8: compare toggle write-back. The page's buttons emit an EDGE
            # (key, on) — write it onto the active view's state.compare so a
            # later view switch reads it back (closes the x_linked/levels
            # write-back loop; V7 only READ state.compare).
            page.compare_toggled.connect(
                lambda key, on, s=sec: self._on_analysis_compare_toggled(
                    s, key, on))
            # V8: colorbar-drag → inspector Z sync. Heatmap sections only
            # (fft is a line section with no colorbar / no levels_changed).
            # While levels are locked the page already mirrors the drag onto
            # BOTH pane canvases internally (_on_locked_levels_changed); this
            # MainWindow path is the SEPARATE concern of echoing the FOCUSED
            # pane's dragged range back into the inspector Z controls. Pane 1
            # is wired later in _connect_new_pane (it does not exist yet).
            if sec in {'fft_time', 'order'}:
                self._wire_heatmap_levels_echo(page.pane_canvas(0), sec, 0)
            else:
                self._connect_fft_preview_range_signal(page.pane_canvas(0), 0)
            if sec in {'fft', 'fft_time', 'order'}:
                self._wire_analysis_viewport_intent(page.pane_canvas(0), sec, 0)

        # FFT vs Time primary compute.
        self.inspector.fft_time_requested.connect(
            lambda: self.do_fft_time(force=False)
        )
        # Fs auto-sync for fft_time_ctx — mirrors what
        # _on_inspector_signal_changed does for fft / order via the
        # original Inspector.signal_changed channel. Routed through the
        # T6 reviewer Important #2 relay so the panel's Fs spinbox
        # tracks the selected signal's source-file Fs.
        self.inspector.fft_time_signal_changed.connect(
            self._on_fft_time_signal_changed
        )
        # Populate xaxis channel candidates whenever user flips to 'channel' mode.
        self.inspector.top.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._on_xaxis_mode_changed('channel' if i == 1 else 'time')
        )

        # Applied custom-X state.  The immutable spec is authoritative; the
        # legacy fid/channel fields are retained only as exact-source adapters
        # for old callers while View persistence migrates.
        self._custom_xaxis.clear()
        # Phase 1 item 4: track range-filter and plot-mode state across
        # plot_time() calls so we can fire the appropriate envelope-cache
        # invalidation when either changes (the cache is keyed on raw
        # (data_id, channel, xlim, pixel_width) and does NOT know whether
        # the source arrays were range-filtered or which plot layout was
        # active when the entry was inserted).
        self._last_range_state = None   # (enabled, lo, hi) or None
        self._last_plot_mode = None     # 'overlay' / 'subplot' / None
        self._last_filter_state_by_canvas = {}  # id(canvas) -> filter state
        self._last_time_render_context_by_canvas = {}
        # Overlay primary-axis pick: (fid, ch) chosen via the channel
        # right-click 设为左轴 menu. When set AND still checked AND in overlay
        # mode, plot_time reorders the checked list so this channel is index 0
        # (bound to the left axis). Cleared/ignored otherwise.
        self._overlay_primary = None
        self.inspector.top.chk_range.toggled.connect(
            self._on_time_range_enabled_changed
        )
        self.inspector.top.max_range_requested.connect(
            self._on_time_range_max_requested
        )
        xrange_changed = getattr(self.canvas_time, 'xrange_changed', None)
        if xrange_changed is not None:
            xrange_changed.connect(self._on_time_canvas_xrange_changed)
        self._connect_canvas_range_signals(self.canvas_time)
        self._connect_channel_color_sync(self.canvas_time)

        # ── Toolbar sidebar toggle buttons ───────────────────────────────────
        from ..side_panels import Ev, PanelState
        self.toolbar.nav_panel_toggled.connect(self._on_nav_panel_toggled)
        self.toolbar.inspector_panel_toggled.connect(
            lambda: self._panel_ctrl_right._dispatch(Ev.CLICK)
        )
        # Sync checked state when panel state changes (includes drag-collapse).
        self._panel_ctrl_left.state_changed.connect(
            self._on_left_panel_state_changed
        )
        self._panel_ctrl_right.state_changed.connect(
            lambda s: self.toolbar.set_inspector_open(s == PanelState.PINNED)
        )

    # Time-domain View pipeline (_apply_active_view, _on_view_split,
    # _render_view_to_canvas, _switch_view, _capture_focused_view, view
    # shortcuts, ...) lives in _view_mixin.ViewMixin — composed via base list.

    # Per-section analysis view routing + cross-cutting helpers
    # (_analysis_page, _pane_time_range_for, _mask_time_range,
    # _analysis_cache_key, _capture_active_analysis_view, _on_analysis_*, ...)
    # live in _analysis_mixin.AnalysisMixin — composed via the base list.

    # -- render glue (shared by cache-switch and compute paths) ---------
    def _file_display_name(self, fid):
        fd = self.files.get(fid)
        if fd is None:
            return str(fid)
        return getattr(fd, 'short_name', None) or str(fid)

    def _cursor_fid_short_name(self, fid):
        fd = self.files.get(fid)
        if fd is None:
            return ""
        return str(getattr(fd, "short_name", "") or "")

    def _sync_fft_source_summary(self, checked=None):
        if checked is None:
            checked = self.navigator.get_checked_channels()
        labels = []
        for item in checked or []:
            if len(item) < 2:
                continue
            fid, ch = item[0], item[1]
            labels.append(f"{self._file_display_name(fid)} · {ch}")
        setter = getattr(self.inspector.fft_ctx, 'set_source_summary', None)
        if callable(setter):
            setter(labels)

    def _fft_trace_for_source(self, fid, ch, time_range=_INSPECTOR_TIME_RANGE):
        fd = self.files.get(fid)
        if fd is None or ch not in fd.data.columns:
            return None, None
        t = np.asarray(fd.time_array, dtype=float)
        sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
        if (
            time_range is _INSPECTOR_TIME_RANGE
            and self.inspector.top.range_enabled()
        ):
            time_range = self.inspector.top.range_values()
        if time_range is _INSPECTOR_TIME_RANGE:
            time_range = None
        t, sig = self._mask_time_range(t, sig, time_range=time_range)
        return t, sig

    def _fft_time_preview_entries(
        self, checked=None, time_range=_INSPECTOR_TIME_RANGE
    ):
        if checked is None:
            checked = self.navigator.get_checked_channels()
        sources = []
        if checked:
            for item in checked:
                if len(item) < 2:
                    continue
                color = item[2] if len(item) >= 3 else '#2563eb'
                sources.append((item[0], item[1], color))
        else:
            sig = self.inspector.fft_ctx.current_signal()
            if sig:
                sources.append((sig[0], sig[1], '#2563eb'))

        entries = []
        for fid, ch, color in sources:
            t, sig = self._fft_trace_for_source(fid, ch, time_range=time_range)
            if t is None or sig is None or len(sig) == 0:
                continue
            entries.append({
                'label': f"{self._file_display_name(fid)} · {ch}",
                'color': color or '#2563eb',
                'time': t,
                'signal': sig,
                'fid': fid,
                'channel': ch,
            })
        return entries

    def _refresh_fft_time_preview(self, clear_spectrum=True):
        if self.chart_stack.current_mode() != 'fft':
            return
        page = self.chart_stack.page_fft
        canvas = page.pane_canvas(page.focused_index())
        entries = self._fft_time_preview_entries()
        plot_preview = getattr(canvas, 'plot_time_preview', None)
        if callable(plot_preview):
            plot_preview(entries, title="时域预览",
                         clear_spectrum=clear_spectrum)
            xt, yt = self.inspector.top.tick_density()
            canvas.set_tick_density(xt, yt)
        # The fft canvas now matches the current inputs (a selection change
        # routes here too); record the signature so a later section round-trip
        # with the same inputs can skip the rebuild.
        self._fft_last_render_sig = self._fft_render_signature()

    def _fft_reference_identity_for_source(self, fid, ch):
        """A per-source ``(value, unit, quantity)`` identity tuple (spec §15
        C1 / §16) -- the render-signature counterpart of the per-entry
        resolution :meth:`_fft_entry_from_cache` converts with. Changing
        EITHER quantity would change the rendered curve (value drives the
        dB conversion + axis reference text, quantity drives the axis word
        for a non-mixed label), so both belong in the identity even though
        only ``(value, unit)`` decides the exact-vs-mixed axis split."""
        resolution = self._resolve_db_reference_for_source('fft', (fid, ch))
        return (resolution.value, resolution.unit, resolution.quantity)

    def _fft_render_signature(self):
        """Identity of everything the fft-canvas render depends on that can
        change while another section is showing. Two fft-mode entries with the
        same signature show identical content, so the retained stacked-page
        canvas may be reused untouched (no spectrum wipe, no preview rebuild).

        Only fft *inputs* go in here: the navigator selection (shared across
        sections), the compute params (cache-key inputs), the time-range
        filter (drives the preview), the dB/linear display toggle, and
        (Task 6 Step 6.5) the dB-reference View mode + EACH checked source's
        OWN resolved reference identity + the catalog service revision (Auto
        View only -- a Manual View's identity already reflects the single
        control value, so the revision counter is irrelevant to it and would
        force spurious re-renders on every unrelated catalog edit). Tracking
        per-source identity (not a single global control value bound only to
        the first checked channel) is what lets a catalog/metadata change on
        ANY checked source -- not just the first -- invalidate this signature.
        The remaining fft knobs live in the fft-only inspector that is hidden
        in other sections, so they cannot drift while away."""
        checked = [
            (row[0], row[1])
            for row in self.navigator.get_checked_channels()
            if len(row) >= 2
        ]
        sources = tuple((str(fid), str(ch)) for fid, ch in checked)
        params = self._analysis_compute_params('fft')
        range_sig = None
        if self.inspector.top.range_enabled():
            try:
                range_sig = tuple(
                    float(v) for v in self.inspector.top.range_values())
            except Exception:
                range_sig = None
        fft_display_params = self.inspector.fft_ctx.current_params()
        amp_y = fft_display_params.get('amp_y', 'Linear')
        db_reference_mode = fft_display_params.get('db_reference_mode', 'auto')
        per_source_identity = tuple(
            self._fft_reference_identity_for_source(fid, ch)
            for fid, ch in checked
        )
        revision = (
            self.db_reference_store.revision
            if db_reference_mode == 'auto' else None
        )
        return (
            sources, tuple(sorted(params.items())), range_sig, amp_y,
            db_reference_mode, per_source_identity, revision,
        )

    def _fft_any_source_cached(self, state):
        cache = self.analysis_caches['fft']
        for pane_idx, pane in enumerate(state.panes):
            for fid, ch in pane.sources:
                key = self._analysis_cache_key(
                    'fft', fid, ch, pane_idx=pane_idx)
                if cache.get(key) is not None:
                    return True
        return False

    def _enter_fft_mode(self):
        """Render the fft section on mode entry without the blanket wipe the old
        ``_refresh_fft_time_preview`` default did.

        The stacked page is never destroyed, so when nothing changed since the
        last fft render its spectrum + preview are still on the canvas — skip
        all work (fixes both the vanishing spectrum and the re-entry lag). When
        the inputs did change, restore the spectrum from cache (also redraws the
        preview); fall back to a bare time preview only when no source is
        cached.

        Mode entry already applied the target View's params/sources via
        ``_apply_active_analysis_context``. This path must NOT capture live
        Inspector params back onto that View (Stage 1 source-isolation F2).
        """
        if self.chart_stack.current_mode() != 'fft' or not self.files:
            return
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        # Sync navigator checkbox → focused pane sources only. Params / range
        # stay owned by the state that was just applied on mode entry.
        if not self._analysis_restore_pending:
            self._capture_analysis_sources('fft', state)
        # 进入 FFT 时按当前勾选的焦点源刷新 Auto 的 dB reference。
        # rerender=False：只刷识别不重算；Manual View 在 helper 内 no-op。
        self._resolve_and_apply_db_reference('fft')
        signature = self._fft_render_signature()
        if signature == self._fft_last_render_sig:
            return
        self._fft_last_render_sig = signature
        if self._fft_any_source_cached(state):
            self._render_analysis_view_from_cache('fft', state)
        else:
            page = self.chart_stack.page_fft
            canvas = page.pane_canvas(page.focused_index())
            if getattr(canvas, 'has_result', lambda: False)():
                self._refresh_fft_time_preview(clear_spectrum=False)
            else:
                self._refresh_fft_time_preview()

    def _fft_entry_from_cache(
        self, result, fid, ch, color, time_range=_INSPECTOR_TIME_RANGE
    ):
        """Build a plot_spectra entry from a cached FFT result.

        ``result`` is the raw compute tuple ``(freq, amp, psd)`` (linear). The
        dB/linear display transform is applied here from the CURRENT inspector
        axis toggle, so toggling dB re-renders without recompute (display-only
        knobs are excluded from the cache key). Task 6 (spec §15 C1): the
        reference used to convert THIS entry is resolved from ITS OWN
        ``(fid, ch)`` source via the section's current View mode + the shared
        catalog service snapshot -- NOT a single control value shared by
        every overlay curve -- so a mixed-reference overlay converts each
        curve with its own reference. The resolution is attached as stable
        entry metadata (``db_reference_resolution``) regardless of the
        Linear/dB toggle (Linear labelling still wants the source's unit/
        quantity); ``amp_for_xlim`` always stays the raw LINEAR amplitude."""
        freq, amp, _psd = result
        p = self.inspector.fft_ctx.current_params()
        amp_y = p.get('amp_y', 'Linear')
        resolution = self._resolve_db_reference_for_source('fft', (fid, ch))
        if amp_y == 'dB':
            amp_disp = self._amplitude_to_db(amp, resolution.value)
        else:
            amp_disp = amp
        label = f"{self._file_display_name(fid)} · {ch}"
        t, sig = self._fft_trace_for_source(fid, ch, time_range=time_range)
        return {
            'label': label,
            'color': color or '#2563eb',
            'freq': freq,
            'amp': amp_disp,
            'amp_for_xlim': amp,
            'time': [] if t is None else t,
            'signal': [] if sig is None else sig,
            'db_reference_resolution': resolution,
            'fid': fid,
            'channel': ch,
        }

    def _fft_apply_amplitude_display(self, entries, amp_y, weighting):
        """Compute the FFT amplitude axis label and attach a per-curve
        ``legend_label`` to each entry (spec §14 / §15 C1, plan Task 6 Step
        6.3), from each entry's own ``db_reference_resolution`` (Step 6.2).

        Every entry sharing ONE ``(value, unit)`` identity -> the EXACT
        canonical axis label (:func:`db_reference.format_amplitude_label`);
        every curve's ``legend_label`` is just its base ``label`` (the axis
        alone already discloses the single shared reference unambiguously).
        Two or more distinct identities -> the axis collapses to
        ``'Amplitude (dB[A] · per-curve reference)'`` and EVERY curve's
        ``legend_label`` gets its own compact ``dB[A] re ...`` disclosure
        appended (:func:`db_reference.format_reference_note`) -- never let
        one source's reference become the global axis (spec stop-gate).
        ``label`` itself is NEVER rewritten: the lower time-preview row
        reuses these same entry dicts and must show NO reference suffix
        (spec: "time preview 的线性 trace 不附 dB reference").

        Entries built outside :meth:`_fft_entry_from_cache` (legacy hand-
        built dicts in a few direct-call tests) simply lack
        ``db_reference_resolution`` -- treated as an unresolved/generic
        source rather than crashing, so those call sites keep working."""
        output_scale = 'db' if amp_y == 'dB' else 'linear'
        resolutions = [e.get('db_reference_resolution') for e in entries]
        known = [r for r in resolutions if r is not None]
        identities = {(r.value, r.unit) for r in known}
        mixed = len(identities) > 1
        if mixed:
            single = None
        elif known:
            single = known[0]
        elif output_scale == 'db':
            # No resolution metadata at all (legacy direct-call entries) --
            # degrade to the same neutral "dB re 1" a genuinely-unresolved
            # generic source would get, rather than crashing.
            single = db_reference.DbReferenceResolution(
                value=1.0, unit='', quantity='', source='generic')
        else:
            single = None
        amp_label = db_reference.format_amplitude_label(
            single, weighting=weighting, output_scale=output_scale, mixed=mixed,
        )
        for e, resolution in zip(entries, resolutions):
            if mixed and resolution is not None and output_scale == 'db':
                note = db_reference.format_reference_note(
                    resolution, weighting=weighting)
                e['legend_label'] = f"{e['label']} · {note}"
            else:
                e['legend_label'] = e['label']
        return amp_label

    def _plot_fft_entries(self, entries, canvas=None):
        """Render a pane's FFT overlay entries with axis labels/limits pulled
        from the current inspector state."""
        if canvas is None:
            canvas = self.canvas_fft
        if not entries:
            return
        p = self.inspector.fft_ctx.current_params()
        amp_y = p.get('amp_y', 'Linear')
        weighting = p.get('weighting', 'None')
        amp_label = self._fft_apply_amplitude_display(entries, amp_y, weighting)
        x_auto = bool(p.get('x_auto', p.get('autoscale', True)))
        x_min = float(p.get('x_min', 0.0))
        x_max = float(p.get('x_max', 0.0))
        if x_auto:
            xmax = max(
                self._fft_auto_xlim(
                    entry['freq'], entry.get('amp_for_xlim', entry['amp'])
                )
                for entry in entries
            )
            xlim = (0.0, xmax)
        elif x_max > x_min:
            xlim = (x_min, x_max)
        else:
            xlim = (0.0, self.inspector.fft_ctx.fs() / 2)
        canvas.plot_spectra(
            entries,
            xlim=xlim,
            amp_label=amp_label,
            title=f'FFT · {len(entries)} 条曲线',
            y_auto=bool(p.get('y_auto', True)),
            y_min=float(p.get('y_min', 0.0)),
            y_max=float(p.get('y_max', 0.0)),
        )
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)
        self._restore_analysis_canvas_viewport('fft', canvas)

    def _render_cached_heatmap(self, section, canvas, result, source=None):
        """Render a cached heatmap result on ``canvas`` using the current
        section inspector's display options. ``source`` is the ``(fid, ch)``
        this specific pane's cached ``result`` came from -- threaded through
        to ``_render_fft_time_on``/``_render_order_on`` for a per-pane-accurate
        dB-reference resolution (spec §15 C2/C3); without it the view-switch /
        project-open cache-restore render path falls back to the generic
        resolution instead of the pane's own saved source."""
        if section == 'fft_time':
            p = self.inspector.fft_time_ctx.get_params()
            self._render_fft_time_on(canvas, result, p, source=source)
        else:
            self._render_order_on(canvas, result, source=source)

    # _on_view_new / _on_view_delete / _on_view_duplicate / _on_view_color /
    # _restore_view_axis_opts / _applied_xaxis_opts / _capture_range_change_into_view /
    # _replot_secondary_preserving_xlim / _replot_canvas_for_view
    # live in _view_mixin.ViewMixin — composed into MainWindow via base list.

    def _snapshot_xaxis_controls(self):
        top = self.inspector.top
        bound_summary = getattr(top, "curve_bound_xaxis_summary", None)
        return {
            "mode": top.xaxis_mode(),
            "channel_data": top._combo_xaxis_ch.currentData(),
            "label": top.xaxis_label(),
            "auto_label": getattr(top, "_xlabel_auto_from_channel", False),
            "curve_bound_summary": (
                bound_summary() if callable(bound_summary) else ""
            ),
        }

    def _restore_xaxis_controls_snapshot(self, snapshot):
        if not snapshot:
            return
        top = self.inspector.top
        old_mode = top.combo_xaxis.blockSignals(True)
        old_combo = top._combo_xaxis_ch.blockSignals(True)
        old_label = top.edit_xlabel.blockSignals(True)
        line_edit = top._combo_xaxis_ch.lineEdit()
        old_line = line_edit.blockSignals(True) if line_edit is not None else False
        try:
            mode = snapshot.get("mode") or "time"
            top.set_xaxis_mode(mode)
            top._combo_xaxis_ch.setEnabled(mode == "channel")
            if mode == "channel":
                data = snapshot.get("channel_data")
                for i in range(top._combo_xaxis_ch.count()):
                    if top._combo_xaxis_ch.itemData(i) == data:
                        top._combo_xaxis_ch.setCurrentIndex(i)
                        break
            top.edit_xlabel.setText(snapshot.get("label") or "")
            top._xlabel_auto_from_channel = bool(snapshot.get("auto_label", False))
        finally:
            top.edit_xlabel.blockSignals(old_label)
            top._combo_xaxis_ch.blockSignals(old_combo)
            top.combo_xaxis.blockSignals(old_mode)
            if line_edit is not None:
                line_edit.blockSignals(old_line)
        update_xaxis_row = getattr(top, '_update_xaxis_channel_row_visible', None)
        if callable(update_xaxis_row):
            update_xaxis_row(top.combo_xaxis.currentIndex())
        restore_bound = getattr(top, "set_curve_bound_xaxis_summary", None)
        if callable(restore_bound) and snapshot.get("curve_bound_summary"):
            restore_bound(snapshot["curve_bound_summary"])

    def _set_tick_density_controls_silent(self, xt, yt):
        xt = int(xt)
        yt = int(yt)
        top = self.inspector.top
        old_xt = top.spin_xt.blockSignals(True)
        old_yt = top.spin_yt.blockSignals(True)
        try:
            top.spin_xt.setValue(xt)
            top.spin_yt.setValue(yt)
        finally:
            top.spin_yt.blockSignals(old_yt)
            top.spin_xt.blockSignals(old_xt)
        setter = getattr(self.chart_stack, 'set_tick_density_controls', None)
        if callable(setter):
            setter(xt, yt)

    def _on_nav_panel_toggled(self):
        from ..side_panels import Ev

        self._panel_ctrl_left._dispatch(Ev.CLICK)

    def _on_left_panel_state_changed(self, state):
        from ..side_panels import PanelState

        self.toolbar.set_nav_open(state == PanelState.PINNED)

    def _on_mode_changed(self, mode):
        old_mode = self.chart_stack.current_mode()
        uv = getattr(self, "_ultraview", None)
        source_modes = ("time", "fft", "fft_time", "frf", "order")
        opening = getattr(self, "_opening_project", False)
        if old_mode != mode and not opening:
            if old_mode == "time":
                self._capture_focused_view()
            elif old_mode in self.analysis_managers:
                self._capture_active_analysis_view(old_mode)
        if uv is not None and mode in source_modes:
            uv.note_source_mode(mode)
        self.chart_stack.set_mode(mode)
        self.inspector.set_mode(mode)
        self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
        if mode in {"fft", "fft_time", "order"}:
            # dB-reference-defaults nudge feed (spec S5 / A17): a section
            # entered without any signal/value/mode change since its last
            # visit still needs a fresh stamp -- additive, no render effect.
            self._stamp_db_reference_nudge_facts(mode)
        # Full-apply the target context so live navigator / Inspector / canvas
        # never keep the outgoing mode's selection (Stage 1 source isolation).
        if mode == "time":
            self.navigator.set_projection_role("time")
            idx = getattr(self, "_focused_view_idx", None)
            if idx is None:
                idx = self.view_manager.active
            if idx is not None and 0 <= idx < len(self.view_manager.views):
                self._project_view_controls(idx)
            # §6.2 auto re-plot on entering time mode with checked channels.
            # Defer by one tick: QStackedWidget has not yet laid out the newly
            # visible canvas, and drawing now paints onto a backing store that
            # is discarded when the layout pass fires (observed regression:
            # plot blanks after fft → time toggle).
            if (
                self.files
                and self.navigator.get_checked_channels()
                and not opening
            ):
                # Project open already plots via `_apply_active_view`. A
                # deferred replot here would processEvents into the restore
                # pump and freeze the UI (macOS beachball).
                QTimer.singleShot(0, self._plot_time_preserving_xlim)
        elif mode in self.analysis_managers:
            # D8: hide the Time View record subtree when leaving Time. The
            # sync entry itself no-ops to empty rows whenever mode != "time".
            self._sync_record_curve_tree()
            role = (
                "fft_sources" if mode == "fft" else "analysis_candidates"
            )
            self.navigator.set_projection_role(role)
            # Stage 1.1 item 3: fill empty target View from time focus before
            # the apply pipeline projects it. Do not hook view-switch.
            self._maybe_fill_empty_analysis_on_mode_entry(mode)
            if mode == "fft":
                # Always apply target View params/sources/range first so live
                # Inspector never overwrites the destination state. Canvas
                # restore stays deferred in `_enter_fft_mode` so an unchanged
                # signature can reuse retained curves without a blank flash.
                self._apply_active_analysis_context(
                    mode, render=False, apply_params=True
                )
                if self.files:
                    QTimer.singleShot(0, self._enter_fft_mode)
            else:
                self._apply_active_analysis_context(mode)

    def _maybe_fill_empty_analysis_on_mode_entry(self, mode):
        """Item 3: copy time-focus attachments into an empty analysis View."""
        prefs = self.navigator.follow_prefs()
        if (
            not prefs.fill_on_mode_entry
            or getattr(self, "_opening_project", False)
            or getattr(self, "_restoring_project", False)
        ):
            return
        from .file_scope_follow import resolve_mode_entry_fill

        resolved = self._active_analysis_view_state(mode)
        time_resolved = self._focused_time_view_state()
        target_att = (
            list(resolved[2].attached_file_ids) if resolved is not None else []
        )
        time_att = (
            list(time_resolved[1].attached_file_ids)
            if time_resolved is not None
            else []
        )
        fill = resolve_mode_entry_fill(target_att, time_att, self.files)
        if not fill:
            return
        added = self._attach_files_to_active_analysis_view(mode, fill)
        if added and time_resolved is not None:
            self.toast(
                f"已填充 {len(added)} 个文件 · 来自 {time_resolved[1].name}",
                "success",
            )

    def _on_cursor_mode_changed(self, mode):
        if self.chart_stack.split_active():
            self._apply_cursor_mode_to_canvas(self.canvas_time, mode)
            self._apply_cursor_mode_to_canvas(
                self.chart_stack.secondary_canvas(), mode
            )
            return

        self._apply_cursor_mode_to_canvas(self.chart_stack.focused_canvas(), mode)

    def _apply_cursor_mode_to_canvas(self, canvas, mode):
        if canvas is None:
            return
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self.view_manager.get(idx).cursor_mode = mode
        setter = getattr(self.chart_stack, "set_cursor_mode_for_canvas", None)
        if callable(setter):
            setter(canvas, mode)
        else:
            canvas.set_cursor_visible(mode != 'off')
            canvas.set_dual_cursor_mode(mode == 'dual')

    def _on_plot_mode_changed(self, mode):
        """Toggle 分↔叠 without losing the user's current x-zoom.

        User-request 2026-05-20: re-plotting on mode toggle rebuilds the
        axes (``plot_channels`` calls ``canvas.clear()`` → ``fig.clear()``
        → new ``add_subplot``), which lets matplotlib autoscale x back to
        the full data extent. We snapshot the *visible* x window on the
        outgoing primary axis, run the replot, then re-apply that window
        on the freshly built primary axis. Y autoscale is left alone —
        each layout has its own per-series Y extents.

        Notes per the lessons-learned corpus:
        - `pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md`:
          ``plot_channels`` re-connects the xlim_changed listener against
          the new primary axis at the tail of its body, so the
          ``set_xlim`` below fires the listener on the correct (new) axis.
        - `pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`:
          the envelope-cache refresh debounce must be drained AFTER the
          ``set_xlim`` mutation that re-schedules it, not before. We use
          a try/finally so any early-return path inside ``plot_time``
          (no files, no checked channels, overlay-cap user-rejected) is
          still safe — the finally just flushes whatever pending refresh
          the no-op state left behind (almost always none).
        - `pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md`:
          ``plot_time`` already diff-gates the envelope-cache invalidation
          on ``_last_plot_mode != mode`` so the wipe fires exactly once
          per mode change. With the cache cleared, the first refresh
          tick AFTER ``set_xlim`` re-primes against the preserved xlim.
        """
        canvas = self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            state = self.view_manager.get(idx)
            self._view_bridge.capture_controls_into(state, self, canvas)
            state.plot_mode = mode
        self._hint_focused_pane("分叠")
        self._replot_canvas_for_view(idx, canvas)

    def _plot_time_preserving_xlim(self):
        cur_xlim = self._safe_capture_primary_xlim()
        try:
            self.plot_time()
        finally:
            if cur_xlim is not None:
                self._safe_restore_primary_xlim(cur_xlim)

    def _on_primary_channel_requested(self, fid, ch):
        """User picked 设为左轴 on a channel. Make it the overlay primary
        (left-axis) channel and replot preserving the current x-window.

        Only meaningful in overlay mode; in subplot/single each channel has
        its own axis so there is no single "left" to assign. We still store
        the pick so it applies if the user later switches to overlay, but the
        replot only reorders when overlay is active (plot_time guards that).

        When the active section is FFT, also promote the matching time-preview
        source to the left axis (same product verb, preview-local state).

        The pick belongs to the FOCUSED View, not just the window. Every path
        that re-projects a View onto a canvas (``_project_view_controls`` /
        ``_render_view_to_canvas`` → ``view_bridge.apply_controls_from_state``)
        rewrites ``self._overlay_primary`` from ``ViewState.overlay_primary``,
        so a pick left only on the window was silently reverted to the first
        checked channel by the next 加入文件 / 应用通道配置 / 打开项目 /
        View 投射 — and never made it into a saved project. Capturing the
        focused View here (same helper ``_switch_view`` uses, so in split it
        lands on the pane that owns the focus) makes the pick part of the
        View's own state. Guarded on ``_applying_view`` so we never write back
        into a View while one is mid-projection.
        """
        self._overlay_primary = (fid, ch)
        if not getattr(self, '_applying_view', False):
            if self.chart_stack.current_mode() == 'time':
                self._capture_focused_view()
            else:
                # A1: do not capture analysis-projected attached/checked/colors
                # onto the time View. Persist only the overlay-primary pick.
                self._capture_overlay_primary_into_focused_view()
        mode = self.chart_stack.current_mode()
        if mode == 'fft':
            canvas = getattr(self, 'canvas_fft', None)
            promote = getattr(canvas, 'promote_time_entry_to_left_by_channel', None)
            if callable(promote) and promote(fid, ch):
                return
        self._plot_time_preserving_xlim()

    def _safe_capture_primary_xlim(self):
        """Return ``(lo, hi)`` for the focused card's x-axis, or None.

        Targets ``chart_stack.focused_canvas()`` so the xlim-preserving replot
        path (``_plot_time_preserving_xlim`` → ``plot_time``) reads from the
        same pane it is about to redraw. Outside split this is the primary
        ``self.canvas_time``. None is returned when no primary axis is live
        (e.g. the canvas was just cleared, no files loaded, no checked
        channels) — in that case there is nothing to preserve. Defensive
        ``try/except`` because matplotlib raises on a destroyed axes.
        """
        return self._safe_capture_xlim_for(self.chart_stack.focused_canvas())

    def _safe_capture_xlim_for(self, canvas):
        """Canvas-generic ``(lo, hi)`` snapshot, or None (P2 Task 9 1b).

        Used by both the focused-canvas path and the secondary (compare) pane
        replot so each pane preserves its OWN visible X window across a
        layout flip. None when no live primary axis (idle / cleared)."""
        ax = getattr(canvas, '_primary_xaxis_ax', None)
        if ax is None:
            return None
        try:
            lo, hi = ax.get_xlim()
        except Exception:
            return None
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return None
        return (float(lo), float(hi))

    def _safe_restore_primary_xlim(self, xlim):
        """Re-apply ``xlim`` to the new primary x-axis after a replot.

        Skips when the replot produced no axes (idle state) or when the
        underlying time-domain extent is incompatible with the captured
        window (e.g. closed file changed the extent dramatically). The
        compatibility check is intentionally loose: as long as the
        captured window overlaps the new axis' autoscaled extent, we
        keep it; otherwise we let autoscale stand.

        Targets ``chart_stack.focused_canvas()`` to match the capture side
        above; outside split that is ``self.canvas_time``.
        """
        self._safe_restore_xlim_for(self.chart_stack.focused_canvas(), xlim)

    def _safe_restore_xlim_for(self, canvas, xlim):
        """Canvas-generic counterpart of :meth:`_safe_restore_primary_xlim`
        (P2 Task 9 1b). Re-applies ``xlim`` to ``canvas`` only when the new
        layout's autoscale window still overlaps the captured window, then
        drains the debounced envelope refresh (see flush-after-axis-mutation
        lesson)."""
        ax = getattr(canvas, '_primary_xaxis_ax', None)
        if ax is None:
            return
        try:
            cur_lo, cur_hi = ax.get_xlim()
        except Exception:
            return
        new_lo, new_hi = xlim
        # Two ways the captured window can stop belonging to what is drawn:
        #   1. zero / degenerate overlap with the new axis window — the extent
        #      is outright incompatible (file closed, channel set swapped).
        #      Use <= / >= so a single tangent point counts as no overlap
        #      instead of locking onto a one-pixel slice.
        #   2. it overlaps but overruns the plotted data — a window sized for
        #      a longer recording, leaving the chart mostly blank.
        # Either way, abandoning the window is not enough on its own: a replot
        # onto existing axes leaves X untouched, so returning here would keep
        # the very window just rejected. Frame the new extent instead.
        if (
            new_hi <= cur_lo
            or new_lo >= cur_hi
            or not self._preserved_xlim_fits_data(
                canvas, new_lo, new_hi,
            )
        ):
            frame = getattr(canvas, 'frame_x_to_data', None)
            if callable(frame):
                try:
                    frame()
                except Exception:
                    pass
            return
        try:
            ax.set_xlim(new_lo, new_hi)
        except Exception:
            return
        # The set_xlim above fires the xlim_changed listener and schedules
        # a 40 ms debounced envelope refresh. Drain it synchronously so
        # the post-toggle frame is the full-detail envelope, not a stale
        # one rendered from the previous mode's last refresh.
        flush = getattr(canvas, '_flush_pending_refresh', None)
        if callable(flush):
            try:
                flush()
            except Exception:
                pass

    @staticmethod
    def _preserved_xlim_fits_data(canvas, lo, hi):
        """Is a carried-over X window still a window *into* the new data?

        Preserving X across a replot exists so ticking a channel on or off
        does not yank the viewport away from wherever the user zoomed. That
        only makes sense while the carried window still sits inside what is
        drawn. When the replot swapped in a shorter recording, the old window
        keeps its old width and the chart ends up mostly blank to the right —
        49.5 s of data framed by a 185 s window left over from another file.
        The overlap check above passes there (the ranges do intersect), so it
        cannot catch this on its own.

        Rule: keep the window only when it lies within the plotted extent;
        otherwise let the fresh ``_set_xrange_to_data_union`` framing stand.
        Zooming in is preserved (a zoom window is a subset by construction);
        a full-view window survives too, since it equals the extent. Data
        growing longer than the window is left alone on purpose — that is a
        legitimate "stay where I am looking" case, and Home reframes it.

        """
        union = None
        getter = getattr(canvas, 'get_data_x_union', None)
        if callable(getter):
            try:
                union = getter()
            except Exception:
                union = None
        if union is None:
            return True                      # nothing plotted to judge against
        union_lo, union_hi = union
        span = union_hi - union_lo
        if not np.isfinite(span) or span <= 0:
            return True
        # 1% of the extent absorbs float drift and pyqtgraph's own rounding
        # on the full-view case without admitting a visibly empty margin.
        tol = 0.01 * span
        return lo >= union_lo - tol and hi <= union_hi + tol

    def _on_time_canvas_xrange_changed(self, lo, hi):
        if self.chart_stack.current_mode() != 'time':
            return
        # In split mode: skip update when focus is on the secondary canvas so
        # the inspector shows the focused pane's range, not the primary's.
        if (self.chart_stack.split_active()
                and self.chart_stack.focused_canvas() is not self.canvas_time):
            return
        self._sync_time_range_inputs_from_visible_xlim((lo, hi))

    def _on_secondary_canvas_xrange_changed(self, lo, hi):
        if self.chart_stack.current_mode() != 'time':
            return
        if self.chart_stack.focused_canvas() is self.chart_stack.secondary_canvas():
            self._sync_time_range_inputs_from_visible_xlim((lo, hi))

    def _sync_time_range_inputs_from_visible_xlim(self, xlim=None):
        if getattr(self, '_applying_view', False):
            return False
        # Inspector range values are in acquisition time. If a custom channel
        # is the visible X axis, that viewport is in channel units and must not
        # overwrite the time-range controls.
        spec = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())
        if spec.mode == CHANNEL_MODE:
            return False
        if xlim is None:
            xlim = self._safe_capture_primary_xlim()
        if xlim is None:
            return False
        lo, hi = xlim
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return False
        self.inspector.top.set_range_values(lo, hi)
        return True

    def _on_fft_preview_range_changed(self, pane_idx, lo, hi):
        """Sync inspector start/end from the FFT time-preview viewport.

        Aligns with Time-Domain: pan/zoom only drafts the spinboxes. The
        analysis window is armed only while「使用选定时间范围」is checked
        (or via explicit arming such as FRF「取时域范围」/ compute confirm).
        「全部」is view-all only and does not arm the checkbox.
        """
        if self.chart_stack.current_mode() != 'fft':
            return False
        page = self.chart_stack.page_fft
        if pane_idx != page.focused_index():
            return False
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return False
        top = self.inspector.top
        top.set_range_values(lo, hi)
        # Unchecked: leave pane.time_range alone (None = full span on compute).
        if not top.range_enabled():
            return True
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        state.panes[pane_idx].time_range = (float(lo), float(hi))
        return True

    def _time_data_extent(self):
        """Return ``(lo, hi)`` covering every loaded file's time base.

        Fallback when nothing is plotted yet. Prefer
        :meth:`_plotted_time_extent` for「全部」and draft-local checks.
        """
        lo = None
        hi = None
        for fd in self.files.values():
            times = getattr(fd, 'time_array', None)
            if times is None or len(times) == 0:
                continue
            try:
                t0 = float(times[0])
                t1 = float(times[-1])
            except Exception:
                continue
            if not (np.isfinite(t0) and np.isfinite(t1)):
                continue
            lo = t0 if lo is None else min(lo, t0)
            hi = t1 if hi is None else max(hi, t1)
        if lo is None or hi is None:
            return 0.0, 0.0
        return float(lo), float(hi)

    def _plotted_time_extent(self):
        """Return ``(lo, hi)`` spanning channels currently drawn on the chart.

        「全部」must frame to what is *plotted*, not the longest loaded file in
        the channel tree. Prefer the focused canvas data union (same extent
        Home uses); then checked-channel file time bases; then the active
        analysis View's attached sources; finally all files.

        Analysis modes read the current analysis page's focused pane canvas.
        ``chart_stack.focused_canvas()`` is a time-domain contract and would
        frame to a leftover Time View curve.
        """
        mode = self.chart_stack.current_mode()
        managers = getattr(self, 'analysis_managers', None) or {}
        canvas = None
        if mode in managers:
            try:
                page = self._analysis_page(mode)
                canvas = page.focused_canvas() if page is not None else None
            except Exception:
                canvas = None
        if canvas is None:
            canvas = self.chart_stack.focused_canvas()
        getter = getattr(canvas, 'get_data_x_union', None)
        if callable(getter):
            try:
                union = getter()
            except Exception:
                union = None
            if union is not None:
                lo, hi = float(union[0]), float(union[1])
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    return lo, hi
        combined = getattr(canvas, '_combined_time_bounds', None)
        if callable(combined):
            try:
                bounds = combined()
            except Exception:
                bounds = None
            if bounds is not None:
                lo, hi = float(bounds[0]), float(bounds[1])
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    return lo, hi

        checked = None
        for attr in ('navigator', 'channel_list'):
            owner = getattr(self, attr, None)
            get = getattr(owner, 'get_checked_channels', None) if owner else None
            if callable(get):
                try:
                    checked = get()
                except Exception:
                    checked = None
                if checked:
                    break
        if checked:
            lo = hi = None
            for item in checked:
                if len(item) < 2:
                    continue
                fid = item[0]
                fd = self.files.get(fid)
                if fd is None:
                    continue
                times = getattr(fd, 'time_array', None)
                if times is None or len(times) == 0:
                    continue
                try:
                    t0 = float(times[0])
                    t1 = float(times[-1])
                except Exception:
                    continue
                if not (np.isfinite(t0) and np.isfinite(t1)):
                    continue
                lo = t0 if lo is None else min(lo, t0)
                hi = t1 if hi is None else max(hi, t1)
            if lo is not None and hi is not None and hi > lo:
                return float(lo), float(hi)

        # Analysis modes clear the channel-tree checks, so fall back to the
        # active analysis View's attached sources before the global union.
        if mode in managers:
            try:
                mgr = managers[mode]
                attached = list(mgr.get(mgr.active).attached_file_ids)
            except Exception:
                attached = []
            if attached:
                lo = hi = None
                for fid in attached:
                    fd = self.files.get(fid)
                    if fd is None:
                        continue
                    times = getattr(fd, 'time_array', None)
                    if times is None or len(times) == 0:
                        continue
                    try:
                        t0 = float(times[0])
                        t1 = float(times[-1])
                    except Exception:
                        continue
                    if not (np.isfinite(t0) and np.isfinite(t1)):
                        continue
                    lo = t0 if lo is None else min(lo, t0)
                    hi = t1 if hi is None else max(hi, t1)
                if lo is not None and hi is not None and hi > lo:
                    return float(lo), float(hi)

        return self._time_data_extent()

    def _on_time_range_max_requested(self):
        """「全部」：查看全部 — 复位可见时间轴到**已绘制**通道的最长全程。

        只草稿 spinbox（与未勾选时的视口同步一致），**不**勾选「使用选定
        时间范围」，也**不**写入 ``pane.time_range`` / View 过滤窗口。
        范围取自图面已 plot 的通道（canvas data union / 勾选通道），
        **不是**通道树里所有已加载文件的最长时基。
        """
        top = self.inspector.top
        lo, hi = self._plotted_time_extent()
        if not (hi > lo):          # 还没有数据 / 没有可用的整段范围
            return
        # Keep spinbox limits fresh before drafting values; stale/narrow limits
        # would otherwise clamp the data extent back to the old UI maximum.
        top.set_range_limits(lo, hi)
        top.set_range_values(lo, hi)
        mode = self.chart_stack.current_mode()
        canvas = self.chart_stack.focused_canvas()
        if mode == 'time':
            # Home to plotted data only — do not expand past drawn curves to a
            # longer unloaded-or-unchecked source in the tree.
            reset = getattr(canvas, 'reset_view_to_data_extents', None)
            if callable(reset):
                reset()
            return
        if mode == 'fft':
            reset = getattr(canvas, 'reset_view_to_data_extents', None)
            if callable(reset):
                reset()
            return
        # fft_time / order / frf: draft-only; compute still uses checkbox.

    def _on_time_range_enabled_changed(self, enabled):
        mode = self.chart_stack.current_mode()
        if mode in self.analysis_managers:
            manager = self.analysis_managers[mode]
            state = manager.get(manager.active)
            page = self._analysis_page(mode)
            pane_idx = page.focused_index()
            before = self._normalize_analysis_time_range(
                state.panes[pane_idx].time_range
            )
            if mode == 'fft' and enabled:
                # Match Time-Domain: arming the checkbox pulls the current
                # preview viewport into start/end before capture.
                canvas = page.pane_canvas(pane_idx)
                get_xlim = getattr(canvas, 'get_time_preview_xlim', None)
                if callable(get_xlim):
                    xlim = get_xlim()
                    if xlim is not None:
                        lo, hi = xlim
                        if (
                            np.isfinite(lo) and np.isfinite(hi) and hi > lo
                        ):
                            self.inspector.top.set_range_values(lo, hi)
            self._capture_analysis_time_range(mode, state, pane_idx=pane_idx)
            if mode == 'frf' and state.panes[pane_idx].time_range != before:
                self._dirty_frf_pane(state, pane_idx, clear_effective=True)
            if mode == 'fft':
                self._refresh_fft_time_preview(clear_spectrum=False)
                if not enabled:
                    canvas = page.pane_canvas(pane_idx)
                    reset = getattr(
                        canvas, '_reset_time_preview_to_extents', None)
                    if callable(reset):
                        reset()
            return
        canvas = self.chart_stack.focused_canvas()
        xaxis_draft = self._snapshot_xaxis_controls()
        try:
            if enabled:
                xlim = None
                get_xlim = getattr(canvas, 'get_visible_xlim', None)
                if callable(get_xlim):
                    xlim = get_xlim()
                self._sync_time_range_inputs_from_visible_xlim(xlim)
            idx = self._view_index_for_canvas(canvas)
            if idx is not None and 0 <= idx < len(self.view_manager.views):
                self._capture_range_change_into_view(
                    self.view_manager.get(idx), canvas
                )
            if self.files and self.navigator.get_checked_channels():
                self._replot_canvas_for_view(idx, canvas)
        finally:
            self._restore_xaxis_controls_snapshot(xaxis_draft)

    def _on_annotation_enabled_changed(self, mode, enabled):
        if mode == 'fft':
            chk = self.inspector.fft_ctx.chk_remark
            if chk.isChecked() != bool(enabled):
                chk.blockSignals(True)
                chk.setChecked(bool(enabled))
                chk.blockSignals(False)

    def _update_all_tick_density_pair(self, xt, yt):
        xt = int(xt)
        yt = int(yt)
        self._set_tick_density_controls_silent(xt, yt)
        canvas = self.chart_stack.focused_canvas()
        canvas.set_tick_density(xt, yt)
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            state = self.view_manager.get(idx)
            self._view_bridge.capture_controls_into(state, self, canvas)
            axis_opts = dict(state.axis_opts or {})
            axis_opts['tick_density'] = {'x': int(xt), 'y': int(yt)}
            state.axis_opts = axis_opts
        # M5/M11: canvas_fft (PgLineCanvas) and canvas_order
        # (PgHeatmapCanvas) are pyqtgraph widgets — no ``fig``/``draw_idle``.
        # Their set_tick_density takes the same inspector tick COUNTS the
        # old MaxNLocator(nbins=...) loop consumed, so the knob semantics hold.
        for page in (
            self.chart_stack.page_fft,
            self.chart_stack.page_fft_time,
            self.chart_stack.page_frf,
            self.chart_stack.page_order,
        ):
            for pane_idx in range(page.pane_count()):
                page.pane_canvas(pane_idx).set_tick_density(xt, yt)

    def _show_rebuild_popover(self, anchor, mode='fft'):
        """Open the 重建时间轴 modal popover for the active selection.

        Returns ``True`` only when the user clicked Accept AND the
        time-axis rebuild side-effects ran (Fs pushed to contextuals,
        per-fid FFT vs Time cache cleared, status/toast emitted).
        Returns ``False`` on early bailout (no selectable signal) and
        on user cancel (``QDialog.Rejected``). Existing slot callers
        ignore the return; T11 (non-uniform UX fix) consumes it to
        decide whether to auto-retry the FFT vs Time compute.
        """
        from PyQt5.QtWidgets import QDialog
        if mode == 'fft':
            sig_data = self.inspector.fft_ctx.current_signal()
        elif mode == 'fft_time':
            # T5 flagged: fft_time_ctx is the source of truth for the
            # FFT vs Time panel's 重建时间轴 button. Without this branch
            # the popover would query order_ctx (wrong selection) when
            # the relay fires with mode='fft_time'.
            sig_data = self.inspector.fft_time_ctx.current_signal()
        else:
            sig_data = self.inspector.order_ctx.current_signal()
        target_fid = sig_data[0] if sig_data and sig_data[0] in self.files else self._active
        if not target_fid or target_fid not in self.files:
            self.toast("请先选择信号", "warning")
            return False
        fd = self.files[target_fid]
        from ..drawers.rebuild_time_popover import RebuildTimePopover
        pop = RebuildTimePopover(self, fd.filename, fd.fs)
        pop.show_at(anchor)
        if pop.exec_() == QDialog.Accepted:
            new_fs = pop.new_fs()
            old_max = fd.time_array[-1] if len(fd.time_array) else 0
            fd.rebuild_time_axis(new_fs)
            new_max = fd.time_array[-1] if len(fd.time_array) else 0
            current_hi = self.inspector.top.spin_end.maximum()
            self.inspector.top.set_range_limits(0, max(current_hi, new_max))
            # All per-fid analysis caches must be invalidated when the time axis
            # is rebuilt: the new Fs changes the frequency-axis scale for cached
            # FFT / Order results as well as the SpectrogramResult timing for
            # FFT-vs-Time. Use the single unified entry point so no cache is
            # silently left with stale data (问题① fix — previously only the
            # legacy LRU was cleared, leaving analysis_caches['fft'] and
            # analysis_caches['order'] with stale entries).
            self._invalidate_all_analysis_caches_for_fid(target_fid)
            for ctx in (
                self.inspector.fft_ctx,
                self.inspector.fft_time_ctx,
                self.inspector.order_ctx,
            ):
                sig_data = ctx.current_signal()
                if sig_data is not None and sig_data[0] == target_fid:
                    ctx.set_fs(new_fs)
            self.plot_time()
            self.statusBar.showMessage(
                f"时间轴已重建: {fd.short_name} | Fs={new_fs} | {old_max:.1f}s → {new_max:.3f}s"
            )
            self.toast(
                f"已重建时间轴 · Fs={new_fs}",
                "success",
            )
            return True
        return False

    def _unit_for_signal(self, data):
        """Resolve the channel unit for a ``(fid, ch)`` signal payload.

        Returns an empty string when the file/channel is unknown — callers
        pass that on to ``set_recommended_for_unit`` which falls back to the
        default (均衡) recommendation for unrecognized units.
        """
        if not data:
            return None
        fid, ch = data
        fd = self.files.get(fid)
        if fd is None or not hasattr(fd, 'channel_units'):
            return ''
        return fd.channel_units.get(ch, '') or ''

    def _apply_audio_weighting_default(self, data):
        # A8: View restore is projection, not user input. Echoing an audio
        # source while `_applying_analysis_view` must not overwrite a stored
        # weighting=None with the convenience A default (and must not fan
        # that default into hidden sibling section contextuals). Loading an
        # audio file still applies A — that path is outside the apply window.
        if self._applying_analysis_view:
            return
        if not data:
            return
        fid, _ch = data
        fd = self.files.get(fid)
        is_audio_source = getattr(fd, 'is_audio_source', None)
        try:
            is_audio = bool(is_audio_source()) if callable(is_audio_source) else False
        except Exception:
            is_audio = False
        if not is_audio:
            return
        for ctx in (
            self.inspector.fft_ctx,
            self.inspector.fft_time_ctx,
            self.inspector.order_ctx,
        ):
            ctx.set_weighting_default('A')

    def _on_inspector_signal_changed(self, mode, data):
        """Fs auto-sync per §6.3: spin_fs reflects selected signal's source file Fs.

        Also drives the per-unit preset 推荐 highlight on the FFT / Order
        contextual preset bars — ``data=None`` (cleared selection) clears the
        highlight.
        """
        # FFT and Order share the same source signal selector contract for
        # recommendations. Keep both preset bars in sync regardless of which
        # contextual emitted the change; Fs sync below remains mode-specific.
        unit = self._unit_for_signal(data)
        if mode in ('fft', 'order'):
            self.inspector.fft_ctx.set_recommended_for_unit(unit)
            self.inspector.order_ctx.set_recommended_for_unit(unit)
        self._apply_audio_weighting_default(data)
        # dB-reference-defaults Task 5: an Auto View re-resolves against the
        # (possibly just-changed) focused source; a Manual View no-ops
        # inside the helper (spec §8.1/§8.4). Also covers a pane FOCUS
        # switch, since _apply_analysis_sources echoes the newly-focused
        # pane's saved source through this same combo -> signal_changed path.
        if mode in ('fft', 'order'):
            self._resolve_and_apply_db_reference(mode)
        if not data:
            return
        fid, _ch = data
        if fid not in self.files:
            return
        fd = self.files[fid]
        fs = fd.fs
        if mode == 'fft':
            self.inspector.fft_ctx.set_fs(fs)
            # FFT source selection changed: keep the computed spectrum but
            # mark it stale (no auto-recompute); the live preview still
            # refreshes to the new source below via plot_time_preview.
            self._refresh_fft_time_preview(clear_spectrum=False)
        elif mode == 'order':
            self.inspector.order_ctx.set_fs(fs)

    def _on_fft_time_signal_changed(self, data):
        """Fs auto-sync for the FFT vs Time panel — mirrors the
        ``_on_inspector_signal_changed`` Fs behavior for the
        ``fft_time_ctx`` route. Reviewer Important #2 hand-off.

        Also drives the per-unit preset 推荐 highlight on the FFT-vs-Time
        preset bar (``data=None`` clears it)."""
        unit = self._unit_for_signal(data)
        self.inspector.fft_time_ctx.set_recommended_for_unit(unit)
        self._apply_audio_weighting_default(data)
        # dB-reference-defaults Task 5: see the matching comment in
        # _on_inspector_signal_changed.
        self._resolve_and_apply_db_reference('fft_time')
        if not data:
            return
        fid, _ch = data
        if fid not in self.files:
            return
        fd = self.files[fid]
        self.inspector.fft_time_ctx.set_fs(fd.fs)

    def _on_db_reference_value_edited(self, section, rerender_fn):
        """A manual dB-reference value commit changes the nudge-eligible fact
        set (mode/value) immediately, ahead of the existing display-only
        re-render this ``valueChanged`` wiring already schedules -- additive
        stamping (spec 2026-07-12 S5 / A17), no render/resolve-logic change.
        ``rerender_fn`` is the SAME callable each ``_connect`` call site
        already deferred via ``QTimer.singleShot(0, ...)``."""
        if (
            self._applying_analysis_view
            or getattr(self._analysis_ctx(section), "_applying_preset", False)
            or self.chart_stack.current_mode() != section
        ):
            return
        self._sync_active_analysis_params(section)
        self._stamp_db_reference_nudge_facts(section)
        QTimer.singleShot(0, rerender_fn)

    def _open_db_reference_dialog(
        self,
        section,
        *,
        view_control=None,
        on_catalog_saved=None,
        on_view_mode_committed=None,
    ):
        """Manage-button entry point (dB-reference-defaults Task 5): every
        section's manage button opens the SAME shared dialog editing the
        ONE global catalog service; only the '当前 View' toggle default
        targets the section that was focused when its button was clicked
        (spec §11.1)."""
        from ..db_reference_dialog import DbReferenceDefaultsDialog
        ctx = self._analysis_ctx(section)
        control = view_control or ctx.db_reference_control
        dlg = DbReferenceDefaultsDialog(
            self, self.db_reference_store,
            current_mode=control.mode(),
            current_effective_summary=control.full_source_text(),
        )
        dlg.catalog_saved.connect(
            lambda s=section: self._on_db_reference_catalog_saved(s)
        )
        if callable(on_catalog_saved):
            dlg.catalog_saved.connect(on_catalog_saved)
        if view_control is None:
            dlg.view_mode_committed.connect(
                lambda mode, s=section: self._on_db_reference_view_mode_committed(s, mode)
            )
        elif callable(on_view_mode_committed):
            dlg.view_mode_committed.connect(on_view_mode_committed)
        dlg.exec_()

    def set_active_file(self, fid):
        """Public entrypoint matching §12.1 contract."""
        self._on_file_activated(fid)

    def _on_file_activated(self, fid):
        self._active = fid
        self._update_info()
        if fid and fid in self.files:
            fd = self.files[fid]
            # Only push Fs to each contextual if its signal dropdown points at
            # the active file (or has no selection yet). Per §6.3 Fs rule.
            for ctx in (
                self.inspector.fft_ctx,
                self.inspector.fft_time_ctx,
                self.inspector.order_ctx,
            ):
                sig_data = ctx.current_signal()
                if sig_data is None or sig_data[0] == fid:
                    ctx.set_fs(fd.fs)
            if len(fd.time_array):
                max_t = max(
                    (f.time_array[-1] for f in self.files.values() if len(f.time_array)),
                    default=0,
                )
                self.inspector.top.set_range_limits(0, max_t)
        self.toolbar.set_enabled_for_mode(
            self.toolbar.current_mode(), has_file=bool(self.files)
        )

    def _on_file_order_requested(self, fids, target_fids, placement):
        if not self.navigator_order.move_file_block(fids, target_fids, placement):
            return
        self.navigator.project_file_order(self.navigator_order.file_fids())
        self._replot_visible_time_after_order_change()

    def _on_channel_order_requested(self, fid, channel, target_channel, placement):
        widget = self.navigator.channel_list
        if widget.btn_selected_only.isChecked():
            visible = [
                item.data(0, Qt.UserRole)[2]
                for item in widget._iter_channel_items()
                if (
                    not item.isHidden()
                    and item.data(0, Qt.UserRole)
                    and item.data(0, Qt.UserRole)[0] == "channel"
                    and str(item.data(0, Qt.UserRole)[1]) == str(fid)
                )
            ]
            moved = self.navigator_order.move_channel_among_visible(
                fid, channel, target_channel, placement, visible
            )
        else:
            moved = self.navigator_order.move_channel(
                fid, channel, target_channel, placement
            )
        if not moved:
            return
        widget.project_channel_order(fid, self.navigator_order.channel_order(fid))
        self._replot_visible_time_after_order_change()

    def _replot_visible_time_after_order_change(self):
        """Rebuild visible time panes from workspace order without clearing caches."""
        if self.chart_stack.current_mode() != "time":
            return
        canvases = [self.canvas_time]
        secondary = self.chart_stack.secondary_canvas()
        if secondary is not None and secondary not in canvases:
            canvases.append(secondary)
        seen = set()
        for canvas in canvases:
            if canvas is None or id(canvas) in seen:
                continue
            seen.add(id(canvas))
            idx = self._view_index_for_canvas(canvas)
            if idx is None:
                continue
            self._replot_canvas_for_view(idx, canvas, preserve_xlim=True)

    def _on_file_close_requested(self, fid):
        self._close(fid)

    def _close_files(self, fids):
        """Atomically close every logical source in a physical file group.

        Dependencies across the whole group are summarized once. Cancel keeps
        all members; confirm force-closes each so partial success is impossible.

        A single-member group (the common case: an ordinary file's own close
        button also routes here via the navigator's group-close request)
        keeps the itemized ``_close`` feedback — filename in the toast. A
        genuine multi-source group (e.g. an HDF file split into several
        ``LoadedSource`` entries) would otherwise fire one toast + one full
        plot-state reset per fid; those are suppressed per-fid (``notify=
        False``) and replaced with a single aggregated summary after the
        loop, since ``_reset_plot_state`` only reflects final ``self.files``/
        ``self._active`` state and is safe to defer to the end.
        """
        ordered = []
        seen = set()
        for raw in fids or ():
            fid = str(raw)
            if fid in self.files and fid not in seen:
                seen.add(fid)
                ordered.append(fid)
        if not ordered:
            return
        from .analysis_source_scope import collect_source_uses

        uses = []
        for fid in ordered:
            uses.extend(
                collect_source_uses(
                    fid,
                    time_views=self.view_manager.views,
                    analysis_managers=self.analysis_managers,
                )
            )
        if uses and not self._confirm_global_file_close(
            uses, files=tuple(ordered),
        ):
            return
        group_close = len(ordered) > 1
        affected = (
            self._time_view_ids_using_fids(ordered) if group_close else ()
        )
        closed = []
        for fid in ordered:
            if fid in self.files:
                self._close(fid, force=True, notify=not group_close)
                closed.append(fid)
        if group_close and closed:
            self._present_after_sources_closed()
            self._reset_plot_state(scope='file')
            self._invalidate_ultraview_previews_for_time_views(affected)
            self.statusBar.showMessage(
                f"已关闭 {len(closed)} 个来源 | 剩余 {len(self.files)} 文件"
            )
            self.toast(
                f"已关闭 {len(closed)} 个来源 · 剩余 {len(self.files)} 文件",
                "info",
            )

    def _on_close_all_requested(self):
        # Single product confirm (dependency summary + close-all) lives here;
        # the navigator only requests — it must not show a second dialog.
        self.close_all()

    def _on_xaxis_mode_changed(self, mode):
        """横坐标模式切换 — populate Inspector candidates when switching to 'channel'.

        Accepts 'channel'/'time' strings (Inspector wire) or 1/0 ints (legacy
        callers such as _reset_plot_state) for backwards compatibility.
        """
        if mode == 1:
            mode = 'channel'
        elif mode == 0:
            mode = 'time'
        if mode == 'channel':
            self._refresh_xaxis_candidates()

    def _build_xaxis_candidates(self):
        checked_fids = []
        for fid, _ch, _color in self.navigator.get_checked_channels():
            if fid in self.files and fid not in checked_fids:
                checked_fids.append(fid)
        source_fids = checked_fids
        if not source_fids:
            try:
                attached = self.view_manager.get(
                    self.view_manager.active
                ).attached_file_ids
            except (AttributeError, IndexError):
                attached = ()
            source_fids = [
                fid for fid in attached
                if fid in self.files
            ]
        if not source_fids:
            source_fids = list(self.files)

        channel_order = []
        seen = set()
        # Keep every loaded channel discoverable even when the current View's
        # coverage denominator is narrower. This preserves the useful
        # "choose X before attaching/checking Y" workflow; out-of-scope names
        # simply report 0/N until their source joins the scope.
        for fid in self.files:
            for channel in self.files[fid].channels:
                if channel not in seen:
                    seen.add(channel)
                    channel_order.append(channel)

        denominator = len(source_fids)
        cands = []
        for channel in channel_order:
            available = sum(
                1 for fid in source_fids
                if channel in self.files[fid].data.columns
            )
            cands.append((
                f"{channel} · {available}/{denominator} 文件可用",
                (PER_SOURCE_NAME, None, channel),
            ))

        applied = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())
        applied_payload = selection_payload(applied)
        if applied.mode == CHANNEL_MODE and applied.channel:
            if applied.resolver == PER_SOURCE_NAME:
                if applied_payload not in {payload for _text, payload in cands}:
                    cands.append((
                        f"{applied.channel} · 0/{denominator} 文件可用",
                        applied_payload,
                    ))
            elif applied.resolver == EXACT_SOURCE and applied_payload is not None:
                source = self.files.get(applied.source_fid)
                if (
                    source is not None
                    and applied.channel in source.data.columns
                ):
                    source_label = getattr(source, 'short_name', '')
                    cands.append((
                        f"[{source_label}] {applied.channel} · 历史精确来源",
                        applied_payload,
                    ))
        return cands

    def _refresh_xaxis_candidates(self):
        bound_summary = getattr(
            self.inspector.top, "curve_bound_xaxis_summary", None,
        )
        if callable(bound_summary) and bound_summary():
            return
        self.inspector.top.set_xaxis_candidates(self._build_xaxis_candidates())

    def _validate_custom_xaxis_source(self):
        spec = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())
        if spec.mode != CHANNEL_MODE:
            return
        # Logical per-source selections survive provider churn; a later file
        # load can make the same channel available again.  Exact legacy state
        # retains the historical fail-closed behaviour when its owner vanishes.
        if spec.resolver == PER_SOURCE_NAME:
            return
        fd = self.files.get(spec.source_fid)
        if fd is not None and spec.channel in fd.data.columns:
            return
        self._custom_xaxis.clear()
        self.inspector.top.set_xaxis_mode('time')

    def _refresh_channel_dependent_controls(self):
        self._validate_custom_xaxis_source()
        self._update_combos()
        if self.inspector.top.xaxis_mode() == 'channel':
            self._refresh_xaxis_candidates()

    def _on_xaxis_drop_hint_dismissed(self):
        """Keep the drag-to-X tip in the footer after the Inspector banner closes."""
        self.toast(hints.XAXIS_DROP_PANEL_DISMISSED_TOAST, "info")
        card = self.chart_stack.focused_card()
        text = hints.hint_text("time.drop_set_xaxis")
        flash = getattr(card, "flash_hint", None)
        if callable(flash) and text:
            flash(text)

    def _apply_xaxis(self):
        """应用横坐标设置"""
        canvas = self.chart_stack.focused_canvas()
        mode = self.inspector.top.xaxis_mode()
        if mode == 'time':
            spec = CustomXAxisSpec(
                mode='time',
                label=self.inspector.top.xaxis_label() or '',
            )
        else:
            data = self.inspector.top.xaxis_channel_data()
            if not data:
                self.toast("请选择横坐标通道", "warning")
                return
            raw_label = self.inspector.top.xaxis_label()
            selected = spec_from_selection(data, label=raw_label)
            if selected.mode != CHANNEL_MODE or not selected.channel:
                self.toast("横坐标选择无效", "warning")
                return
            label = (
                raw_label if raw_label and raw_label != 'Time (s)' else None
            ) or selected.channel
            spec = CustomXAxisSpec(
                mode=selected.mode,
                resolver=selected.resolver,
                channel=selected.channel,
                source_fid=selected.source_fid,
                label=label,
            )
        return MainWindow.apply_time_xaxis_spec(
            self, spec, canvas, sync_inspector=False,
        )

    def apply_time_xaxis_spec(self, spec, canvas=None, *, sync_inspector=True):
        """Apply one custom-X spec to ``canvas`` (Inspector and drop share this)."""
        canvas = canvas or self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(canvas)
        previous_spec = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())
        spec = spec or CustomXAxisSpec()
        # NOTE: write through the compatibility shims rather than
        # ``self._custom_xaxis`` directly.  ``tests/ui/test_task4_cache_
        # invalidation.py`` drives this with a ``SimpleNamespace`` standing in
        # for a narrow MainWindow protocol and then asserts on these attribute
        # names, so the holder does not exist on ``self`` here.
        self._custom_xlabel = spec.label or None
        self._custom_xaxis_spec = spec
        if spec.mode == CHANNEL_MODE and spec.resolver == EXACT_SOURCE:
            self._custom_xaxis_fid = spec.source_fid
            self._custom_xaxis_ch = spec.channel
        else:
            self._custom_xaxis_fid = None
            self._custom_xaxis_ch = None

        if sync_inspector:
            self._sync_inspector_to_xaxis_spec(spec)

        current_spec = self._custom_xaxis_spec
        x_source_changed = (
            previous_spec.mode,
            previous_spec.resolver,
            previous_spec.source_fid,
            previous_spec.channel,
        ) != (
            current_spec.mode,
            current_spec.resolver,
            current_spec.source_fid,
            current_spec.channel,
        )

        # Cache invalidation site 5: the t-array bound to every plotted
        # channel just changed (time-axis ↔ custom-channel x-axis), so
        # every (data_id, channel, xlim, pixel_width) entry is now stale.
        # Monotonicity cache is also re-keyed by the new fid/ch pair, so
        # wipe it to be safe.
        if x_source_changed:
            invalidate_envelope = getattr(canvas, 'invalidate_envelope_cache', None)
            if callable(invalidate_envelope):
                invalidate_envelope("custom-x changed")
            invalidate_mono = getattr(canvas, 'invalidate_monotonicity_cache', None)
            if callable(invalidate_mono):
                invalidate_mono()
        # Custom X can affect every plotted file, so keep this as a whole
        # FFT-vs-Time-section invalidation rather than a per-fid eviction.
        # FFT and Order do not consume this display control, so their caches
        # remain valid and must not be needlessly evicted.
        if x_source_changed:
            caches = getattr(self, 'analysis_caches', None)
            if isinstance(caches, dict) and 'fft_time' in caches:
                caches['fft_time'].clear()
            clearer = getattr(self, '_clear_analysis_section_pins', None)
            if callable(clearer):
                clearer('fft_time')
        views = getattr(getattr(self, 'view_manager', None), 'views', ())
        if idx is not None and 0 <= idx < len(views):
            state = self.view_manager.get(idx)
            self._view_bridge.capture_controls_into(state, self, canvas)
            if x_source_changed:
                # A different X source changes coordinate semantics, so a
                # saved time/custom-channel window is not meaningful. Keep
                # Y limits and every other View option, but let the new X
                # data extent establish the viewport.
                state.xlim = None
        if self.files and self.chart_stack.current_mode() == 'time':
            rendered = self._replot_canvas_for_view(
                idx,
                canvas,
                preserve_xlim=not x_source_changed,
            )
        else:
            rendered = self.plot_time()
        incomplete = (
            current_spec.mode == CHANNEL_MODE
            and isinstance(rendered, TimePlotBuildResult)
            and (
                not rendered.successful_channel_keys
                or len(rendered.successful_channel_keys)
                < len(rendered.attempted_channel_keys)
            )
        )
        if incomplete:
            # Keep the applied spec. The render path already installed the
            # empty hint / placeholder / N/M pill. Do not overwrite those
            # facts with a contradictory success message or toast.
            return rendered
        status = getattr(self, 'statusBar', None)
        if status is not None:
            status.showMessage("横坐标已更新")
        if not self._hint_focused_pane("坐标设置"):
            self.toast("横坐标已更新", "success")
        return rendered

    def _sync_inspector_to_xaxis_spec(self, spec):
        top = getattr(getattr(self, 'inspector', None), 'top', None)
        if top is None:
            return
        old_mode = top.combo_xaxis.blockSignals(True)
        old_combo = top._combo_xaxis_ch.blockSignals(True)
        old_label = top.edit_xlabel.blockSignals(True)
        line_edit = top._combo_xaxis_ch.lineEdit()
        old_line = line_edit.blockSignals(True) if line_edit is not None else False
        try:
            if spec.mode == CHANNEL_MODE:
                top.set_xaxis_mode('channel')
                top._combo_xaxis_ch.setEnabled(True)
            else:
                top.set_xaxis_mode('time')
                top._combo_xaxis_ch.setEnabled(False)
        finally:
            top.edit_xlabel.blockSignals(old_label)
            top._combo_xaxis_ch.blockSignals(old_combo)
            top.combo_xaxis.blockSignals(old_mode)
            if line_edit is not None:
                line_edit.blockSignals(old_line)
        if spec.mode == CHANNEL_MODE:
            self._refresh_xaxis_candidates()
            payload = selection_payload(spec)
            top.set_xaxis_channel_data(payload)
            top.set_xaxis_label(spec.label or spec.channel or '')
            top._xlabel_auto_from_channel = False
        else:
            top.set_xaxis_label(spec.label or '')

    def _on_time_channel_drop(self, canvas, key, zone):
        """Join a dragged channel to the drop-target time View, or set custom X."""
        if getattr(self, "_opening_project", False) or getattr(self, "_restoring_project", False):
            return
        if self.chart_stack.current_mode() != "time":
            return
        if self._projection_role() != "time":
            return
        try:
            from PyQt5 import sip
            if canvas is None or sip.isdeleted(canvas):
                return
        except (RuntimeError, TypeError):
            if canvas is None:
                return
        if not isinstance(key, (tuple, list)) or len(key) != 2:
            return
        fid, channel = str(key[0]), str(key[1])
        fd = self.files.get(fid)
        if fd is None or channel not in fd.data.columns:
            return
        card_for = getattr(self.chart_stack, "_card_for_canvas", None)
        card = card_for(canvas) if callable(card_for) else None
        if card is not None and self.chart_stack.split_active():
            self.chart_stack.set_focused_card(card)
        if zone == "xaxis":
            spec = CustomXAxisSpec(
                mode=CHANNEL_MODE,
                resolver=PER_SOURCE_NAME,
                source_fid=None,
                channel=channel,
                label=channel,
            )
            self.apply_time_xaxis_spec(spec, canvas, sync_inspector=True)
            return
        self._add_channel_to_time_view(canvas, fid, channel)

    def _add_channel_to_time_view(self, canvas, fid, channel):
        idx = self._view_index_for_canvas(canvas)
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        state = self.view_manager.get(idx)
        fid = str(fid)
        channel = str(channel)
        if fid not in state.attached_file_ids:
            state.attached_file_ids.append(fid)
        key = (fid, channel)
        existed = key in {(str(item[0]), str(item[1])) for item in state.checked}
        if not existed:
            state.checked.append(key)
        self._project_view_controls(idx)
        refresh = getattr(self, "_refresh_channel_config_context", None)
        if callable(refresh):
            refresh()
        if existed:
            self.toast("通道已在当前 View 中", "info")
        self._replot_canvas_for_view(idx, canvas, preserve_xlim=True)

    def _reset_cursors(self):
        """Reset both single and dual cursor state on the time-domain canvas.

        Uses the canvas-provided ``reset_cursor_state()`` seam so the
        upcoming pyqtgraph TimeDomain canvas (Phase 1 of the migration —
        see ``docs/superpowers/specs/2026-05-28-pyqtgraph-timedomain-migration-design.md``
        §5.5) can swap in without changing this call site. ``getattr``
        fallback retains the legacy direct-mutation path for older
        canvases that have not yet adopted the seam.
        """
        reset = getattr(self.canvas_time, "reset_cursor_state", None)
        if callable(reset):
            reset()
        else:
            self.canvas_time._ax = self.canvas_time._bx = None
            self.canvas_time._placing = 'A'
            self.canvas_time.draw_idle()
        self.chart_stack.clear_cursor_pill()
        self.statusBar.showMessage("游标已重置")
        self.toast("游标已重置", "info")

    # open_files_or_project / save_project_via_dialog / load_files / load_file
    # live in _project_io_mixin.ProjectIOMixin (composed via the base list).
    # open_acquisition_cockpit stays here (patches main_window.importlib).
    def open_acquisition_cockpit(self) -> None:
        try:
            cockpit_module = importlib.import_module(
                "mf4_analyzer.acquisition_ui.main_window"
            )
        except ModuleNotFoundError:
            # Analyzer-only ("lite") builds ship without the acquisition_ui /
            # acquisition_capture packages (tools/build_windows_folder_lite.ps1
            # omits them from PyInstaller's hiddenimports). The cockpit entry
            # point stays wired but degrades gracefully instead of surfacing an
            # ImportError traceback.
            QMessageBox.information(
                self,
                "采集功能不可用",
                "此为分析版，不包含数据采集（驾驶舱）功能。\n"
                "如需采集，请使用完整版。",
            )
            return
        CockpitMainWindow = cockpit_module.CockpitMainWindow

        for window in QApplication.topLevelWidgets():
            if isinstance(window, CockpitMainWindow):
                if not window.isVisible():
                    window.show()
                window.raise_()
                window.activateWindow()
                return

        from mf4_analyzer.acquisition_capture.config_store import (
            CONFIG_FILENAME,
            default_recent_path,
        )

        config_path = default_recent_path().parent / CONFIG_FILENAME
        cockpit = CockpitMainWindow(config_path=config_path)
        self._acquisition_cockpit_window = cockpit
        cockpit.show()

    # _load_one / _close / save_project / open_project / close_all live in
    # _project_io_mixin.ProjectIOMixin — composed into MainWindow via base list.

    def _update_info(self):
        """Surface active-file summary via the status bar (no more lbl_info shim)."""
        if not self.files:
            self.statusBar.showMessage("未加载文件")
            return
        parts = [
            f"{'▶' if fid == self._active else '  '} {fd.short_name}: {len(fd.data)}"
            for fid, fd in self.files.items()
        ]
        self.statusBar.showMessage(" | ".join(parts))

    def _reset_plot_state(self, scope='file'):
        """Wipe plot-related state after a file close.
        scope in {'file', 'all'}; both paths currently share code.
        """
        self.chart_stack.full_reset_all()
        self.chart_stack.clear_cursor_pill()
        # Stats strip
        self.chart_stack.stats_strip.update_stats({})
        # Chart-card cursor mode → back to 'off' default (spec §8)
        self.chart_stack.set_cursor_mode('off')
        self._refresh_channel_dependent_controls()
        if not self.files:
            self.inspector.top.set_range_limits(0, 0)
            self.inspector.top.spin_start.setValue(0)
            self.inspector.top.spin_end.setValue(0)
        else:
            max_t = max(
                (fd.time_array[-1] for fd in self.files.values() if len(fd.time_array)),
                default=0,
            )
            self.inspector.top.set_range_limits(0, max_t)
            lo, hi = self.inspector.top.range_values()
            if hi > max_t:
                self.inspector.top.spin_end.setValue(max_t)
            if lo > max_t:
                self.inspector.top.spin_start.setValue(0)
            if self._active in self.files:
                fs = self.files[self._active].fs
                self.inspector.fft_ctx.set_fs(fs)
                self.inspector.order_ctx.set_fs(fs)
        # Re-plot remaining channels (or clear if empty)
        self.plot_time()

    def _analysis_section_label(self, section):
        return {
            'fft': '频谱',
            'fft_time': '时频',
            'frf': 'FRF',
            'order': '阶次',
        }.get(section, section)

    def _analysis_scope_fids(self, section=None):
        """Still-loaded fids for one analysis section's active View.

        Retired as a shared Time-View scope: each section reads its own
        ``AnalysisViewState.attached_file_ids``. Prefer
        ``_refresh_analysis_candidates`` for live picker updates.
        """
        from .analysis_source_scope import analysis_scope_fids

        if section is None:
            section = self.chart_stack.current_mode()
        if section not in self.analysis_managers:
            return list(self.files)
        mgr = self.analysis_managers[section]
        if not mgr.views:
            return list(self.files)
        return analysis_scope_fids(mgr.get(mgr.active), self.files)

    def _candidate_rows_for_fids(self, fids):
        sig_cands = []
        for fid in fids:
            fd = self.files.get(fid)
            if fd is None:
                continue
            px = f"[{fd.short_name}] "
            for ch in fd.get_signal_channels():
                sig_cands.append((px + ch, (fid, ch)))
        return sig_cands

    def _refresh_analysis_candidates(self, section=None):
        """Rebuild analysis signal pickers from each section's active View.

        ``section`` given → only that section. ``None`` → every analysis
        section (file load / global close / channel edit). Combos already
        blockSignals inside ``set_*_candidates`` so refresh must not capture
        into PaneState.
        """
        sections = (
            (section,)
            if section in self.analysis_managers
            else tuple(self.analysis_managers)
        )
        for sec in sections:
            fids = self._analysis_scope_fids(sec)
            sig_cands = self._candidate_rows_for_fids(fids)
            ctx = self._analysis_ctx(sec)
            if sec == 'frf':
                ctx.set_channel_candidates(sig_cands)
            else:
                ctx.set_signal_candidates(sig_cands)
                if sec == 'order':
                    ctx.set_rpm_candidates(list(sig_cands))
        if section is None or section == 'fft':
            self._sync_fft_source_summary()

    def _update_combos(self):
        """Compatibility wrapper: refresh every analysis section's candidates.

        Retires the old Time-View-scoped shared candidate list. Callers that
        still invoke ``_update_combos`` after a global file/channel universe
        change get the new section-aware behavior.
        """
        self._refresh_analysis_candidates()

    def _confirm_global_file_close(self, uses, *, files=None, close_all=False):
        """Confirm cascading unload when Views still reference the file(s).

        Default button is Cancel. Tests monkeypatch this to force accept/reject
        without a dialog.
        """
        from PyQt5.QtWidgets import QMessageBox

        uses = list(uses or ())
        file_count = len(files or ())
        if not uses and not close_all:
            return True
        if not uses and close_all:
            box = QMessageBox(self)
            box.setWindowTitle("关闭全部文件")
            box.setIcon(QMessageBox.Question)
            box.setText(f"关闭全部 {file_count or len(self.files)} 个文件？")
            close_btn = box.addButton(
                "关闭并从所有 View 移除", QMessageBox.AcceptRole
            )
            cancel = box.addButton("取消", QMessageBox.RejectRole)
            box.setDefaultButton(cancel)
            fit_message_box_buttons_to_text(box)
            box.exec_()
            return box.clickedButton() is close_btn

        time_views = {
            (u.domain, u.view_id)
            for u in uses
            if u.domain == "time" and u.role == "attachment"
        }
        analysis_views = {
            (u.domain, u.view_id)
            for u in uses
            if u.domain != "time" and u.role == "attachment"
        }
        role_uses = [u for u in uses if u.role != "attachment"]
        summary_lines = [
            f"时域 View：{len(time_views)}",
            f"分析 View：{len(analysis_views)}",
            f"来源角色：{len(role_uses)}",
        ]
        detail = []
        for use in uses[:12]:
            where = use.view_name or use.view_id or "?"
            role = use.role
            ch = f" · {use.channel}" if use.channel else ""
            detail.append(f"{use.domain} / {where} / {role}{ch}")
        if len(uses) > 12:
            detail.append(f"…另有 {len(uses) - 12} 处引用")

        box = QMessageBox(self)
        box.setWindowTitle(
            "关闭全部文件" if close_all else "关闭文件"
        )
        box.setIcon(QMessageBox.Warning)
        if close_all:
            box.setText(
                f"关闭全部 {file_count or len(self.files)} 个文件前，"
                "发现仍被 View 引用的来源。"
            )
        else:
            box.setText("关闭文件前发现仍被 View 引用的来源。")
        box.setInformativeText(
            "\n".join(summary_lines)
            + ("\n\n" + "\n".join(detail) if detail else "")
        )
        close_btn = box.addButton(
            "关闭并从所有 View 移除", QMessageBox.AcceptRole
        )
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is close_btn

    def _confirm_global_channel_delete(self, uses):
        from PyQt5.QtWidgets import QMessageBox

        uses = list(uses or ())
        if not uses:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("删除通道")
        box.setIcon(QMessageBox.Warning)
        box.setText(
            f"删除通道前发现 {len(uses)} 处 View 引用。"
            "继续将从所有 View 移除这些引用。"
        )
        remove = box.addButton(
            "关闭并从所有 View 移除", QMessageBox.AcceptRole
        )
        cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        return box.clickedButton() is remove

    def _on_chart_focus_changed(self, secondary_focused):
        if not self.chart_stack.split_active():
            return
        self._capture_focused_view()
        self.view_tabbar.set_split_focus(secondary_focused)
        if secondary_focused:
            self._view_focus.focused = self._view_focus.secondary
            which = "对比"
        else:
            self._view_focus.focused = self._view_focus.primary
            which = "主"
        if self._focused_view_idx is not None:
            self._sync_focus_accent()
            self._project_view_controls(self._focused_view_idx)
        self.statusBar.showMessage(f"聚焦{which}视图：通道勾选将作用于此栏", 2000)

    def _projection_role(self):
        getter = getattr(self.navigator, "projection_role", None)
        if callable(getter):
            return getter()
        return "time"

    def _ch_changed(self):
        role = self._projection_role()
        if role == "analysis_candidates":
            # Candidate-tree checkboxes are non-editable; ignore defensive
            # emissions so they cannot write Time or Analysis state.
            return
        if role == "fft_sources":
            mgr = self.analysis_managers["fft"]
            state = mgr.get(mgr.active)
            self._capture_analysis_sources("fft", state)
            self._sync_fft_source_summary()
            self._resolve_and_apply_db_reference("fft")
            self._refresh_fft_time_preview(clear_spectrum=False)
            return

        # Time projection: capture into the focused TimeDomain View only.
        # Cache invalidation is deferred until `_plot_time_on_canvas` reports
        # an explicit full-rebuild reason; visibility-only deltas retain
        # unchanged envelopes.
        focused = self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(focused)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self._view_bridge.capture_canvas_ranges_into(
                self.view_manager.get(idx), focused
            )
            self._view_bridge.capture_controls_into(
                self.view_manager.get(idx), self, focused
            )
        if self.files and self.chart_stack.current_mode() == "time":
            self._replot_canvas_for_view(idx, focused)
        self._refresh_channel_config_context()

    def _on_time_channel_visibility_changed(self, fid, channel, visible):
        """Persist and redraw an eye toggle on the focused TimeDomain View."""
        focused = self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(focused)
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return

        state = self.view_manager.get(idx)
        # Capture ranges before rebuilding so a hidden subplot keeps its Y
        # window and can restore it when the eye is opened again.
        self._view_bridge.capture_canvas_ranges_into(state, focused)
        self._view_bridge.capture_controls_into(state, self, focused)
        if self.chart_stack.current_mode() != 'time':
            return
        rendered = self._replot_canvas_for_view(idx, focused)
        if rendered is False and visible:
            # Re-opening an eye can cross the existing overlay risk threshold.
            # A cancelled warning means the UI must return to the prior hidden
            # state instead of showing an eye whose curve was not rendered.
            self.navigator.set_channel_visible(
                fid, channel, False, emit=False
            )
            self._view_bridge.capture_controls_into(state, self, focused)
            self._replot_canvas_for_view(idx, focused)

    def _restore_checked_channels(self, checked):
        self.channel_list.set_checked_channels(checked)

    def plot_time(self, *, user_initiated=False):
        # Route channel-check replots to the focused time card. Outside
        # side-by-side compare, focused_canvas() is the primary self.canvas_time
        # so this is byte-identical to the old behaviour; while split is active
        # and the secondary card is focused, the replot lands on the secondary
        # canvas instead. update_primary_ui stays gated on whether the focused
        # canvas IS the primary, so the stats strip / status bar / cache
        # bookkeeping only fire for the primary pane.
        focused = self.chart_stack.focused_canvas()
        # The scope makes this render non-reentrant: the progress pump inside
        # _plot_time_on_canvas can deliver a queued 0 ms timer, and a View
        # switch running there would rebuild THIS canvas underneath us.
        with self._time_render_scope():
            return self._plot_time_on_canvas(
                focused,
                update_primary_ui=(focused is self.canvas_time),
                user_initiated=user_initiated,
            )

    @staticmethod
    def _time_plot_issue_text(issue):
        source = issue.source_label or issue.source_fid
        target = issue.target_channel or "未知通道"
        return f"{source} / {target}：{issue.detail}"

    def _set_time_plot_diagnostics(self, canvas, result=None):
        card_for_canvas = getattr(self.chart_stack, '_card_for_canvas', None)
        card = card_for_canvas(canvas) if callable(card_for_canvas) else None
        setter = getattr(card, 'set_time_plot_diagnostics', None)
        if not callable(setter):
            return
        if result is None:
            setter(attempted=0, successful=0, details=())
            return
        setter(
            attempted=len(result.attempted_channel_keys),
            successful=len(result.successful_channel_keys),
            details=tuple(
                self._time_plot_issue_text(issue) for issue in result.issues
            ),
        )

    def _time_axis_label(self, unit=None):
        """Return the visible time-domain X-axis title.

        A custom X source has its own physical unit. Keep the Inspector's
        editable label as entered, but append the source unit only for the
        rendered title so View state and label editing remain compatible.
        """
        applied = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())
        label = self._custom_xlabel or applied.label or self.inspector.top.xaxis_label()
        if applied.mode != CHANNEL_MODE or not applied.channel:
            return label or 'Time (s)'

        label = label or str(applied.channel)
        if unit is None:
            if applied.resolver == EXACT_SOURCE:
                fd = self.files.get(applied.source_fid)
                unit = channel_unit(fd, applied.channel) if fd is not None else ''
            else:
                unit = next((
                    channel_unit(fd, applied.channel)
                    for fd in self.files.values()
                    if applied.channel in fd.data.columns
                ), '')
        unit = str(unit).strip()
        unit_token = f'({unit})'
        if unit and unit_token not in label:
            return f'{label} {unit_token}'
        return label

    def _time_canvases(self):
        """Time-domain canvases to live-toggle. Includes the focused canvas
        (primary outside split, secondary while split) plus the primary so a
        toggle while split affects both panes that show the time domain."""
        seen = []
        for c in (self.chart_stack.focused_canvas(), self.canvas_time):
            if c is not None and c not in seen and hasattr(c, "_channel_lines"):
                seen.append(c)
        return seen

    def _on_show_original_toggled(self, visible):
        """显示原始 live toggle: hide/show the solid originals on the built
        chart WITHOUT a re-plot. Falls back to a full plot only if nothing was
        toggled (e.g. nothing plotted yet) so the chart still appears."""
        if self.chart_stack.current_mode() != 'time':
            return
        any_toggled = False
        for c in self._time_canvases():
            setter = getattr(c, "set_original_lines_visible", None)
            if callable(setter) and setter(visible):
                any_toggled = True
        if not any_toggled and self.files:
            self.plot_time()

    def _on_show_filtered_toggled(self, visible):
        """显示滤波后 live toggle: hide/show the dashed filtered companions on
        the built chart WITHOUT a re-plot. If no companion exists yet (filter
        just enabled but not plotted), fall back to a full plot so the overlay
        appears."""
        if self.chart_stack.current_mode() != 'time':
            return
        any_toggled = False
        for c in self._time_canvases():
            setter = getattr(c, "set_companion_lines_visible", None)
            if callable(setter) and setter(visible):
                any_toggled = True
        if not any_toggled and visible and self.files:
            # Turning the filtered overlay ON with no companion bound yet →
            # need a real plot to compute + bind the dashed traces.
            self.plot_time()

    def _estimate_current_time_overlay_risk(self, mode: str, checked) -> PlotRisk:
        if self.inspector.top.range_enabled():
            time_range = self.inspector.top.range_values()
        else:
            time_range = None

        filter_enabled = False
        show_original = True
        show_filtered = False
        fp = getattr(self.inspector, "filter_panel", None)
        if fp is not None and fp.is_enabled():
            spec = fp.filter_spec()
            show_original = fp.show_original()
            show_filtered = fp.show_filtered()
            filter_enabled = (spec.cutoff > 0) or (
                spec.cutoff_lo > 0 and spec.cutoff_hi > 0
            )

        return estimate_time_overlay_risk(
            checked=checked,
            files=self.files,
            mode=mode,
            time_range=time_range,
            filter_enabled=filter_enabled,
            show_original=show_original,
            show_filtered=show_filtered,
        )

    def _confirm_overlay_risk(self, risk: PlotRisk) -> bool:
        body = (
            f"叠加模式将绘制 {risk.channel_count} 个通道、"
            f"{risk.series_count} 条曲线，约 "
            f"{self._format_count_zh(risk.sample_total, '点')}。\n"
            "这可能导致明显卡顿。是否继续？"
        )
        if risk.filter_enabled:
            body += "\n当前还启用了滤波，会额外增加计算时间。"
        result = QMessageBox.question(
            self,
            "叠加模式数据量较大",
            body,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return result == QMessageBox.Yes

    def _restore_previous_time_plot_mode(self, prev_mode, canvas=None) -> None:
        if prev_mode not in ('subplot', 'overlay'):
            return
        target = canvas or self.chart_stack.focused_canvas()
        setter = getattr(self.chart_stack, "set_plot_mode_for_canvas", None)
        if callable(setter):
            setter(target, prev_mode)
        else:
            self.chart_stack.set_plot_mode(prev_mode)

        idx = self._view_index_for_canvas(target)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self.view_manager.get(idx).plot_mode = prev_mode
        if target is self.canvas_time:
            self._last_plot_mode = prev_mode

    def _checked_with_overlay_primary(self, checked):
        """Keep workspace order, then pin the overlay left-axis pick at index 0.

        Overlay「设为左轴」is a View-local left-axis owner, not a second tree
        order. Subplot callers must not use this helper.
        """
        primary = getattr(self, "_overlay_primary", None)
        if primary is None or not checked:
            return list(checked)
        pfid, pch = str(primary[0]), str(primary[1])
        out = list(checked)
        primary_idx = next(
            (
                i for i, item in enumerate(out)
                if str(item[0]) == pfid and str(item[1]) == pch
            ),
            None,
        )
        if primary_idx is not None and primary_idx != 0:
            out.insert(0, out.pop(primary_idx))
        return out

    def _active_time_curve_bindings(self):
        """Return ``curve_bindings`` for the active TimeDomain View.

        Record-only Y (``y_ref.kind == "wwt_record"``) has no Navigator
        identity. Callers must parse these before treating an empty
        checked set as "nothing to plot".
        """
        if not hasattr(self, "view_manager"):
            return []
        try:
            active_state = self.view_manager.get(self.view_manager.active)
        except (IndexError, TypeError):
            return []
        return list(getattr(active_state, "curve_bindings", None) or [])

    @staticmethod
    def _bindings_include_record_only(bindings) -> bool:
        return any(
            getattr(getattr(binding, "y_ref", None), "kind", "") == "wwt_record"
            for binding in bindings or ()
        )

    def _plot_time_on_canvas(
        self,
        canvas,
        update_primary_ui=True,
        defer_first_frame=False,
        user_initiated=False,
        *,
        defer_axis_finalize=False,
    ):
        """Plot time data; deferred finalization leaves it to the caller."""
        if not self.files:
            self._set_time_plot_diagnostics(canvas)
            canvas.clear()
            canvas.draw()
            if update_primary_ui:
                self.chart_stack.stats_strip.update_stats({})
            if user_initiated:
                self._warn_action_blocked("请先打开数据文件")
            return
        all_checked = self.channel_list.get_checked_channels()
        order = getattr(self, "navigator_order", None)
        if order is not None:
            all_checked = order.order_checked(all_checked)
        # U-Can View 6/7 (and synthetic record-only fixtures) are valid XY
        # with checked=[]. Parse bindings before the Navigator empty-checked
        # early return so those rows still reach _build_time_plot_data.
        curve_bindings = self._active_time_curve_bindings()
        has_record_only = self._bindings_include_record_only(curve_bindings)
        if not all_checked and not has_record_only:
            self._set_time_plot_diagnostics(canvas)
            mode = self.chart_stack.plot_mode_for_canvas(canvas)
            delta = getattr(canvas, "try_apply_selection_delta", None)
            delta_result = (
                delta([], mode=mode, render_context_key=None)
                if callable(delta)
                else {"applied": False, "reason": "delta-api-unavailable"}
            )
            if not delta_result.get("applied"):
                canvas.clear()
                canvas.draw()
            else:
                canvas.draw_idle()
            if update_primary_ui:
                self.chart_stack.stats_strip.update_stats({})
                self.statusBar.showMessage("未选择时间域通道")
            if user_initiated:
                self._warn_action_blocked("请在左侧勾选至少一个通道")
            return
        checked = self.channel_list.get_visible_checked_channels()
        if order is not None:
            checked = order.order_checked(checked)

        # Per-pane plot mode (P2 Task 9 1b): read the layout (subplot/overlay)
        # from the card that owns the TARGET canvas, not always the primary.
        # Outside split this resolves to the primary card's mode, so the
        # non-split path is byte-identical.
        mode = self.chart_stack.plot_mode_for_canvas(canvas)
        # Overlay primary-axis pick (设为左轴): when the chosen (fid, ch) is
        # still checked AND we're in overlay mode, move it to index 0 so the
        # canvas binds it to the LEFT axis (vis[0] → left). If it is no longer
        # checked, drop the stale pick so a hidden channel is never forced
        # onto the left axis. Outside overlay mode the pick is inert (each
        # channel owns its own axis), but we keep it stored for a later toggle.
        if self._overlay_primary is not None:
            pfid, pch = str(self._overlay_primary[0]), str(self._overlay_primary[1])
            primary_is_checked = any(
                str(item[0]) == pfid and str(item[1]) == pch
                for item in all_checked
            )
            if not primary_is_checked:
                self._overlay_primary = None
            elif mode == 'overlay':
                checked = self._checked_with_overlay_primary(checked)
        # Cache invalidation site 7: structural plot-mode change (overlay
        # ↔ subplot) reuses the same (data_id, channel) keys but the line
        # ownership switches between an axes-stack and a single ax with
        # twinx siblings. To keep cached envelopes from rendering on the
        # wrong axes, drop them when the layout changes.
        prev_mode = self._last_plot_mode
        if update_primary_ui:
            if self._last_plot_mode is not None and self._last_plot_mode != mode:
                canvas.invalidate_envelope_cache("plot mode changed")
            self._last_plot_mode = mode
        is_primary = update_primary_ui or user_initiated
        risk = self._estimate_current_time_overlay_risk(mode, checked)
        if is_primary:
            if mode == 'overlay' and risk.level is not PlotRiskLevel.OK:
                self._show_plot_risk(risk)
            else:
                self._clear_plot_risk()
        if (
            risk.level is PlotRiskLevel.DANGER
            and is_primary
            and not self._confirm_overlay_risk(risk)
        ):
            self._restore_previous_time_plot_mode(prev_mode, canvas)
            self.statusBar.showMessage("已取消高风险叠加绘制", 3000)
            return False

        range_enabled = self.inspector.top.range_enabled()
        range_lo, range_hi = self.inspector.top.range_values()
        # Cache invalidation site 6: the range-filter materializes fresh
        # `t[m]`, `sig[m]` arrays whose contents differ from the
        # full-series buffers cached under the same (data_id, channel)
        # key. Whenever the (enabled, lo, hi) tuple flips, drop cached
        # entries so the next refresh re-primes against the current
        # filtered slice.
        cur_range_state = (
            (range_enabled, range_lo, range_hi) if range_enabled else (False,)
        )
        if update_primary_ui:
            if (self._last_range_state is not None
                    and self._last_range_state != cur_range_state):
                canvas.invalidate_envelope_cache("range filter changed")
            self._last_range_state = cur_range_state

        fp = getattr(self.inspector, "filter_panel", None)
        if fp is not None and fp.is_enabled():
            cur_filter_state = (True, tuple(sorted(fp.filter_spec().to_dict().items())))
        else:
            cur_filter_state = (False,)
        if update_primary_ui:
            canvas_key = id(canvas)
            last_filter_state = self._last_filter_state_by_canvas.get(canvas_key)
            if (last_filter_state is not None
                    and last_filter_state != cur_filter_state):
                canvas.invalidate_envelope_cache("filter state changed")
            self._last_filter_state_by_canvas[canvas_key] = cur_filter_state

        applied_x = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())
        render_context_key = (
            (
                applied_x.mode,
                applied_x.resolver,
                applied_x.source_fid,
                applied_x.channel,
            ),
            self._overlay_primary,
            cur_range_state,
            cur_filter_state,
            self._time_axis_label(),
        )

        from ..chart_stack import _STATS_STRIP_ENABLED
        collect_stats = update_primary_ui and _STATS_STRIP_ENABLED
        st = (
            self._build_time_statistics(
                all_checked, range_enabled, range_lo, range_hi,
            )
            if collect_stats
            else {}
        )

        if not checked and not has_record_only:
            self._set_time_plot_diagnostics(canvas)
            count = len(all_checked)
            render_context_key = getattr(
                self, '_last_time_render_context_by_canvas', {}
            ).get(id(canvas), render_context_key)
            delta = getattr(canvas, "try_apply_selection_delta", None)
            delta_result = (
                delta(
                    [],
                    mode=mode,
                    render_context_key=render_context_key,
                )
                if callable(delta)
                else {"applied": False, "reason": "delta-api-unavailable"}
            )
            if delta_result.get("applied"):
                canvas.draw_idle()
            else:
                canvas.show_empty_hint(
                    f"已选择 {count} 个通道，当前均已隐藏"
                )
                canvas.draw()
            if update_primary_ui:
                if collect_stats:
                    self.chart_stack.stats_strip.update_stats(st)
                self.statusBar.showMessage(
                    f"已选择 {count} 个通道，当前均已隐藏"
                )
            return True

        # [perf-probe] 诊断探针，定位后移除。整段绘图计时 + 子计时。
        from ..pg_canvas import _perf_probe as _pp
        if _pp.ENABLED:
            _pp.install_paint_probe(canvas)
            _pp.reset_paint_counter()
            _pp.log(
                f"plot_time 开始: mode={mode} checked={len(checked)} 通道"
            )
        _pp_section = _pp.section("plot_time 一次绘图") if _pp.ENABLED else None
        if _pp_section is not None:
            _pp_section.__enter__()

        progress_token = None
        if update_primary_ui or user_initiated:
            progress_token = self._begin_compute_progress(
                "时间域绘制中",
                total=1000,
            )

        def phase_progress(start, stop, label):
            if progress_token is None:
                return None

            def advance(current, total):
                fraction = max(0.0, min(1.0, current / max(1, total)))
                self._update_compute_progress(
                    int(round(start + (stop - start) * fraction)),
                    1000,
                    label=label,
                    token=progress_token,
                    process_events=True,
                )

            return advance

        try:
            prepare_progress = phase_progress(30, 520, "绘图 · 准备")
            with _pp.timed("_build_time_plot_data 总耗时"):
                result = self._build_time_plot_data(
                    checked, None, range_enabled, range_lo, range_hi,
                    progress_callback=prepare_progress,
                    plot_mode=mode,
                )
            self._set_time_plot_diagnostics(canvas, result)
            data = result.render_rows(mode)
            if not data:
                done_progress = phase_progress(1000, 1000, "绘图 · 无数据")
                if done_progress is not None:
                    done_progress(1, 1)
                attempted = len(result.attempted_channel_keys)
                canvas.show_empty_hint(
                    f"自定义横坐标无法绘制 · 0/{attempted}"
                    if applied_x.mode == CHANNEL_MODE
                    else f"当前时间范围内无可绘制数据 · 0/{attempted}"
                )
                canvas.draw()
                if update_primary_ui:
                    self.chart_stack.stats_strip.update_stats(st)
                    self.statusBar.showMessage(
                        f"绘制: 0/{attempted} 通道"
                    )
                return result

            # Empty string is an explicit, known custom-X unit cohort. Do not
            # collapse it to None, which means "derive from a provider" and
            # could leak the first provider's unrelated unit into the title.
            xlabel = self._time_axis_label(result.x_unit)
            if applied_x.mode == CHANNEL_MODE and applied_x.channel:
                x_identity = (
                    (applied_x.source_fid, applied_x.channel)
                    if applied_x.resolver == EXACT_SOURCE
                    else (None, applied_x.channel)
                )
                x_axis_context = CursorXAxisContext(
                    mode=CHANNEL_MODE,
                    identity=x_identity,
                    label=applied_x.label or applied_x.channel,
                    unit=str(result.x_unit or "").strip(),
                )
            else:
                x_axis_context = CursorXAxisContext(
                    mode=TIME_MODE,
                    identity=None,
                    label="",
                    unit="s",
                )
            setter = getattr(canvas, "set_cursor_x_axis_context", None)
            if callable(setter):
                setter(x_axis_context)
            render_context_key = (
                (
                    applied_x.mode,
                    applied_x.resolver,
                    applied_x.source_fid,
                    applied_x.channel,
                ),
                self._overlay_primary,
                cur_range_state,
                cur_filter_state,
                xlabel,
                result.x_unit,
            )
            contexts = getattr(
                self, '_last_time_render_context_by_canvas', None
            )
            if contexts is not None:
                contexts[id(canvas)] = render_context_key
            canvas_progress = phase_progress(520, 960, "绘图 · 构建")
            has_placeholder = any(
                getattr(slot, "kind", None) == "placeholder"
                for slot in getattr(result, "slots", ())
            )
            delta = getattr(canvas, "try_apply_selection_delta", None)
            if mode == "subplot" and has_placeholder:
                delta_result = {"applied": False, "reason": "placeholder-slots"}
            else:
                delta_result = (
                    delta(
                        data,
                        mode=mode,
                        render_context_key=render_context_key,
                    )
                    if callable(delta)
                    else {"applied": False, "reason": "delta-api-unavailable"}
                )
            if not delta_result.get("applied"):
                rebuild_reason = str(
                    delta_result.get("reason") or "selection-delta-incompatible"
                )
                invalidate = getattr(canvas, "invalidate_envelope_cache", None)
                if callable(invalidate):
                    invalidate(rebuild_reason)
                with _pp.timed("plot_channels(建轴+bind+首次setData) 耗时"):
                    canvas.plot_channels(
                        data,
                        mode,
                        xlabel=xlabel,
                        defer_first_frame=defer_first_frame,
                        progress_callback=canvas_progress,
                        render_context_key=render_context_key,
                        full_rebuild_reason=rebuild_reason,
                        x_axis_context=x_axis_context,
                        defer_axis_finalize=defer_axis_finalize,
                    )
            elif canvas_progress is not None:
                canvas_progress(1, 1)
            finalize_progress = phase_progress(960, 1000, "绘图 · 应用")
            if finalize_progress is not None:
                finalize_progress(1, 1)
            if update_primary_ui:
                self._sync_time_range_inputs_from_visible_xlim()
            # A View restore owns its one final range/tick commit; this is not
            # WWT detection or a native-axis algorithm.
            if not defer_axis_finalize:
                xt, yt = self.inspector.top.tick_density()
                canvas.set_tick_density(xt, yt)
            # [perf-probe] 诊断探针，定位后移除。诊断行 + 强制同步首帧 paint
            # （离屏 settle 后是缓存 blit，需 repaint() 触发 paintEvent hook 记真实首帧）。
            if _pp.ENABLED:
                _pp.log_filter_total()
                _pp.log_canvas_diagnostics(canvas)
                try:
                    # GraphicsView 自身被 hook（见 install_paint_probe）。repaint()
                    # 同步强制首帧光栅；离屏 settle 后的 grab 是缓存 blit，量不到墙。
                    _pp.log("强制 GraphicsView.repaint() 触发首帧光栅")
                    canvas._glw.repaint()
                except Exception as _exc:
                    _pp.log(f"repaint 触发失败(已吞): {_exc!r}")
        finally:
            try:
                if _pp_section is not None:
                    _pp_section.__exit__(*sys.exc_info())
            finally:
                if progress_token is not None:
                    self._finish_compute_progress(token=progress_token)
        # SpanSelector intentionally not enabled — drag-to-select on the
        # chart face was retired (2026-05-27) to prevent accidental triggers.
        # If you need a per-range export tool, re-enable explicitly behind a
        # toolbar button rather than always-on.
        if update_primary_ui:
            if collect_stats:
                self.chart_stack.stats_strip.update_stats(st);
            successful = len(result.successful_channel_keys)
            attempted = len(result.attempted_channel_keys)
            success_files = len({
                fid for fid, _channel in result.successful_channel_keys
            })
            self.statusBar.showMessage(
                f"绘制: {successful}/{attempted} 通道，{success_files} 文件"
            )
        return result

    def _build_time_statistics(
        self, checked, range_enabled, range_lo, range_hi,
    ):
        """Compute acquired-channel stats from every checked channel.

        Eye visibility is a TimeDomain rendering preference, so hidden checked
        channels intentionally remain in this statistics source set.
        """
        stats = {}
        for fid, channel, _color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or channel not in fd.data.columns:
                continue
            signal = fd.data[channel].to_numpy(copy=False)
            if range_enabled:
                time_axis = fd.time_array
                mask = (time_axis >= range_lo) & (time_axis <= range_hi)
                signal = signal[mask]
            if len(signal) == 0:
                continue
            name = fd.get_prefixed_channel(channel)
            unit = fd.channel_units.get(channel, '')
            stats[name] = {
                'min': np.min(signal), 'max': np.max(signal),
                'mean': np.mean(signal),
                'rms': np.sqrt(np.mean(signal ** 2)),
                'std': np.std(signal), 'p2p': np.ptp(signal), 'unit': unit,
            }
        return stats

    def _filter_suffix(self, spec):
        """Short trace-name tag for a filtered overlay, e.g. ``LP 50Hz`` /
        ``BP 100–2000Hz``. The trailing ``Hz)`` is the marker the stats path
        uses to exclude filtered overlays from the stats strip."""
        tag = {"low": "LP", "high": "HP", "band": "BP", "bandstop": "BS"}[spec.kind]
        if spec.kind in ("band", "bandstop"):
            return f"{tag} {spec.cutoff_lo:g}–{spec.cutoff_hi:g}Hz"
        return f"{tag} {spec.cutoff:g}Hz"

    def _build_time_plot_data(self, checked=None, custom_x=None,
                              range_enabled=None, range_lo=0.0, range_hi=0.0,
                              progress_callback=None, *, plot_mode=None):
        """Assemble per-curve TimeDomain rows and source-level diagnostics.

        Pure w.r.t. ``channel_data`` — it never mutates samples. Each checked
        channel yields its ORIGINAL trace (``visible = show_original``) and, when
        a filter is configured and "显示滤波后" is on, a display-layer FILTERED
        overlay (``visible = show_filtered``) computed per-channel at the
        channel's own ``fs`` via the pure-numpy ``signal.filters`` backend. The
        filtered overlay is display-only; it is not written back anywhere.

        Each logical target ``(fid, channel)`` is counted once regardless of a
        filtered companion.  ``progress_callback`` receives
        ``(completed_sample_work, total_sample_work)`` after each channel so a
        large selected source contributes proportionally more than a tiny one.

        ``custom_x`` remains in the call signature only for compatibility with
        older narrow tests/callers. Applied behavior comes exclusively from
        ``_custom_xaxis_spec`` so one source can never leak its X array into a
        different source's payload.
        """
        from ...signal import filters as _filters
        # [perf-probe] 诊断探针，定位后移除。reset 滤波 apply 累计器。
        from ..pg_canvas import _perf_probe as _pp
        _pp.reset_filter_accum()

        if checked is None:
            checked = self.channel_list.get_checked_channels()
        order = getattr(self, "navigator_order", None)
        if order is not None:
            checked = order.order_checked(checked)
        if plot_mode == "overlay":
            checked = self._checked_with_overlay_primary(checked)
        if range_enabled is None:
            range_enabled = self.inspector.top.range_enabled()
            range_lo, range_hi = self.inspector.top.range_values()
        applied_x = getattr(self, '_custom_xaxis_spec', CustomXAxisSpec())

        fp = getattr(self.inspector, "filter_panel", None)
        spec = None
        show_orig, show_filt = True, True
        filt_enabled = False
        if fp is not None and fp.is_enabled():
            spec = fp.filter_spec()
            show_orig, show_filt = fp.show_original(), fp.show_filtered()
            filt_enabled = (spec.cutoff > 0) or (
                spec.cutoff_lo > 0 and spec.cutoff_hi > 0)

        # Track filtered-overlay names so the stats path can exclude them
        # without relying on a fragile name-suffix heuristic.
        self._time_filtered_names = set()

        eff_groups = self.channel_list.checked_axis_groups()
        result = TimePlotBuildResult()
        binding_claimed: set[tuple[str, str]] = set()
        bindings = self._active_time_curve_bindings()
        if bindings:
            from ..time_curve_bindings import bound_time_plot_rows
            from ..time_xaxis import TimePlotIssue as PayloadIssue
            checked_keys = {(fid, ch) for fid, ch, _color in checked}
            checked_colors = {
                (fid, ch): color for fid, ch, color in checked
            }
            bind_result = bound_time_plot_rows(
                bindings,
                getattr(self, "files", {}) or {},
                range_lo=range_lo if range_enabled else None,
                range_hi=range_hi if range_enabled else None,
                checked_channel_keys=checked_keys,
                channel_colors=checked_colors,
                hidden_binding_ids=getattr(
                    self.view_manager.get(self.view_manager.active),
                    "hidden_curve_binding_ids",
                    None,
                ) if getattr(self, "view_manager", None) and self.view_manager.views else None,
            )
            bind_rows, bind_issues, binding_claimed = bind_result
            result.rows.extend(bind_rows)
            for issue in bind_issues:
                result.issues.append(PayloadIssue(
                    code=issue.code,
                    source_fid=str(issue.binding_id or ""),
                    source_label=str(issue.binding_id or ""),
                    target_channel=str(issue.binding_id or ""),
                    x_channel="",
                    detail=issue.detail,
                ))
            for key in bind_result.successful_channel_keys:
                result.successful_channel_keys.add(key)
            for key in binding_claimed:
                if key in checked_keys:
                    result.attempted_channel_keys.add(key)
        channel_work = {}
        for fid, ch, _color in checked:
            if (fid, ch) in binding_claimed:
                continue
            result.attempted_channel_keys.add((fid, ch))
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns:
                continue
            # Range masking and filtering both scale with source samples. A
            # filtered trace has a second full-array pass, hence two units.
            source_samples = max(1, len(fd.data))
            channel_work[(fid, ch)] = source_samples * (2 if filt_enabled else 1)
        total_work = max(1, sum(channel_work.values()))
        completed_work = 0

        def report_progress():
            if callable(progress_callback):
                progress_callback(completed_work, total_work)

        # Unit compatibility is a source fact. Build one representative per
        # source so a file with many selected Y channels cannot outvote other
        # files when choosing the largest normalized-unit cohort.
        incompatible_units = {}
        if applied_x.mode == CHANNEL_MODE:
            representatives = []
            seen_fids = set()
            for fid, ch, _color in checked:
                if fid in seen_fids:
                    continue
                seen_fids.add(fid)
                representatives.append(resolve_custom_xaxis(
                    target_fid=fid,
                    target_channel=ch,
                    files=self.files,
                    spec=applied_x,
                ))
            # Unit voting happens only after each source proves that its X is
            # drawable in the active acquisition-time window. A numerically
            # dominant unit outside the selected range must not suppress the
            # only cohort that can actually render.
            eligible_representatives = []
            for resolved in representatives:
                if not resolved.ready or resolved.x_values is None:
                    continue
                source = self.files.get(resolved.source_fid)
                if source is None:
                    continue
                candidate_x = resolved.x_values
                if range_enabled:
                    time_axis = source.time_array
                    mask = (
                        (time_axis >= range_lo)
                        & (time_axis <= range_hi)
                    )
                    candidate_x = candidate_x[mask]
                if len(candidate_x) == 0:
                    continue
                if not np.isfinite(
                    np.asarray(candidate_x, dtype=float)
                ).any():
                    continue
                eligible_representatives.append(resolved)

            cohorted = apply_unit_cohort(eligible_representatives)
            for resolved in cohorted:
                if resolved.issue_code == 'x_unit_incompatible':
                    incompatible_units[resolved.source_fid] = resolved
            result.x_unit = next((
                resolved.unit for resolved in cohorted
                if resolved.ready
            ), None)

        def append_placeholder(issue):
            result.issues.append(issue)
            result.slots.append(TimePlotSlot(
                key=(str(issue.source_fid), str(issue.target_channel)),
                kind="placeholder",
                issue=issue,
            ))

        report_progress()
        for fid, ch, color in checked:
            if (fid, ch) in binding_claimed:
                continue
            fd = self.channel_list.get_file_data(fid)
            source_label = str(
                getattr(fd, 'short_name', '') or fid
            ) if fd is not None else str(fid)
            if fd is None or ch not in fd.data.columns:
                append_placeholder(TimePlotIssue(
                    code='missing_target_channel',
                    source_fid=str(fid),
                    source_label=source_label,
                    target_channel=str(ch),
                    x_channel=str(applied_x.channel or ''),
                    detail='目标通道已不存在',
                ))
                continue
            source_work = max(1, len(fd.data))
            time_axis = fd.time_array
            sig = fd.data[ch].to_numpy(copy=False)
            if applied_x.mode == CHANNEL_MODE:
                resolved = resolve_custom_xaxis(
                    target_fid=fid,
                    target_channel=ch,
                    files=self.files,
                    spec=applied_x,
                )
                if not resolved.ready:
                    if resolved.issue is not None:
                        append_placeholder(resolved.issue)
                    else:
                        append_placeholder(TimePlotIssue(
                            code='missing_x_channel',
                            source_fid=str(fid),
                            source_label=source_label,
                            target_channel=str(ch),
                            x_channel=str(applied_x.channel or ''),
                            detail='无法解析横坐标',
                        ))
                    completed_work += source_work * (2 if filt_enabled else 1)
                    report_progress()
                    continue
                x_axis = resolved.x_values
            else:
                x_axis = time_axis
            unit = fd.channel_units.get(ch, '')
            name = fd.get_prefixed_channel(ch)
            # Range controls are always in acquisition time, even when the
            # visible X axis is a channel.
            if range_enabled:
                m = (time_axis >= range_lo) & (time_axis <= range_hi)
                x_axis, sig = x_axis[m], sig[m]
            if len(sig) == 0:
                append_placeholder(TimePlotIssue(
                    code='empty_after_time_range',
                    source_fid=str(fid),
                    source_label=source_label,
                    target_channel=str(ch),
                    x_channel=str(applied_x.channel or ''),
                    detail='所选时间范围内没有数据',
                ))
                completed_work += source_work * (2 if filt_enabled else 1)
                report_progress()
                continue

            filtered = None
            gspec = None
            if filt_enabled:
                fs = float(getattr(fd, "fs", 0.0)) or self._estimate_fs(time_axis)
                try:
                    gspec, _msg = _filters.nyquist_guard(spec, fs)
                except ValueError:
                    # band/bandstop with lo >= hi → draw original only.
                    gspec = None
                if gspec is not None:
                    with _pp.filter_apply():
                        filtered = _filters.apply(sig, gspec, fs)

            if applied_x.mode == CHANNEL_MODE:
                finite_x = np.isfinite(np.asarray(x_axis, dtype=float))
                if not finite_x.any():
                    append_placeholder(TimePlotIssue(
                        code='non_finite_x',
                        source_fid=str(fid),
                        source_label=source_label,
                        target_channel=str(ch),
                        x_channel=str(applied_x.channel or ''),
                        detail='所选时间范围内横坐标没有有限数值',
                    ))
                    completed_work += source_work * (2 if filt_enabled else 1)
                    report_progress()
                    continue
                incompatible = incompatible_units.get(str(fid))
                if incompatible is not None:
                    append_placeholder(TimePlotIssue(
                        code='x_unit_incompatible',
                        source_fid=str(fid),
                        source_label=source_label,
                        target_channel=str(ch),
                        x_channel=str(applied_x.channel or ''),
                        detail=incompatible.detail,
                    ))
                    completed_work += source_work * (
                        2 if filt_enabled else 1
                    )
                    report_progress()
                    continue
                # Preserve the original zero-copy buffers when every X point
                # is finite. Besides avoiding an unnecessary allocation, this
                # keeps selection-delta signatures stable across identical
                # replots. Fancy-index only when there is actually work to do.
                if not finite_x.all():
                    x_axis = x_axis[finite_x]
                    sig = sig[finite_x]
                    if filtered is not None:
                        filtered = filtered[finite_x]

            gid = eff_groups.get((fid, ch))
            if gid is not None:
                primary_row = (
                    name, show_orig, x_axis, sig, color, unit, fid,
                    {"axis_group": gid},
                )
            else:
                primary_row = (
                    name, show_orig, x_axis, sig, color, unit, fid
                )
            slot_rows = [primary_row]
            result.rows.append(primary_row)
            result.successful_channel_keys.add((fid, ch))

            completed_work += source_work
            report_progress()

            if filtered is not None and gspec is not None:
                fname = f"{name} ({self._filter_suffix(gspec)})"
                self._time_filtered_names.add(fname)
                # 8th field ``meta``: marks this as a display companion of the
                # source channel ``name`` so the canvas overlays it (dashed) on
                # the SAME axis/row instead of allocating a fresh subplot row.
                # Original 7-tuple rows are unchanged → backward compatible.
                meta = {"companion_of": name, "dash": True}
                companion_row = (
                    fname, show_filt, x_axis, filtered, color, unit, fid, meta
                )
                slot_rows.append(companion_row)
                result.rows.append(companion_row)
                completed_work += source_work
                report_progress()
            elif filt_enabled:
                completed_work += source_work
                report_progress()
            result.slots.append(TimePlotSlot(
                key=(str(fid), str(ch)),
                kind="success",
                rows=slot_rows,
            ))
        completed_work = total_work
        report_progress()
        return result

    def _estimate_fs(self, t):
        t = np.asarray(t, dtype=float)
        if t.size < 2:
            return 0.0
        dt = np.median(np.diff(t))
        return float(1.0 / dt) if dt > 0 else 0.0

    def open_editor(self):
        if not self.files or not self._active or self._active not in self.files:
            self.toast("请先加载文件", "warning")
            return
        from ..drawers.channel_editor_drawer import ChannelEditorDrawer
        # Pass ALL loaded files so the user can switch the edit target inside
        # the drawer. The applied(fid, ...) signal reports whichever file the
        # user actually had selected, so we no longer assume self._active.
        drawer = ChannelEditorDrawer(self, self.files, self._active)
        drawer.applied.connect(self._apply_channel_edits)
        drawer.export_requested.connect(self._do_export_channels)
        # Keep a live handle so toast/status during export (drawer stays open
        # by design — emit before accept) paint on the drawer, not under it.
        self._channel_editor_drawer = drawer
        try:
            drawer.exec_()
        finally:
            self._channel_editor_drawer = None


    def _apply_channel_edits(self, fid, new_channels, removed_channels):
        fd = self.files[fid]
        removed_channels = list(removed_channels or ())
        if removed_channels:
            from .analysis_source_scope import collect_channel_uses

            uses = collect_channel_uses(
                fid,
                removed_channels,
                time_views=self.view_manager.views,
                analysis_managers=self.analysis_managers,
            )
            if uses and not self._confirm_global_channel_delete(uses):
                return
        self._capture_focused_view()
        # Cache invalidation site 3: each touched channel's underlying
        # ndarray identity may have changed (added) or vanished (removed).
        # `fd.get_prefixed_channel(...)` is what plot_channels stashes
        # under self.channel_data, so use that as the cache key.
        # All analysis caches (FFT, FFT-vs-Time, Order) for this fid are
        # stale after a column edit — clear them all via the unified entry
        # point (问题① fix).
        self._invalidate_all_analysis_caches_for_fid(fid)
        for name in list(new_channels.keys()) + list(removed_channels):
            prefixed = fd.get_prefixed_channel(name)
            self.canvas_time.invalidate_envelope_cache(
                "channel edited", data_id=fid, channel=prefixed
            )
            # If the user edited the column currently used as the custom
            # x-axis source, drop its monotonicity cache too.
            self.canvas_time.invalidate_monotonicity_cache(
                custom_xaxis_fid=fid, custom_xaxis_ch=name
            )
        for name, (arr, unit) in new_channels.items():
            fd.data[name] = arr
            fd.channels.append(name)
            fd.channel_units[name] = unit
        for name in removed_channels:
            if name in fd.data.columns:
                fd.data = fd.data.drop(columns=[name])
            if name in fd.channels:
                fd.channels.remove(name)
            fd.channel_units.pop(name, None)
        self._remove_channels_from_all_time_views(fid, removed_channels)
        self._remove_channels_from_all_analysis_views(fid, removed_channels)
        nav_blocked = self.navigator.blockSignals(True)
        list_blocked = self.channel_list.blockSignals(True)
        try:
            self.navigator_order.refresh_channels(fid, fd.get_signal_channels())
            self.navigator.refresh_file(
                fid, fd, channel_order=self.navigator_order.channel_order(fid)
            )
        finally:
            self.channel_list.blockSignals(list_blocked)
            self.navigator.blockSignals(nav_blocked)
        self._refresh_channel_dependent_controls()
        mode = self.chart_stack.current_mode()
        if mode in self.analysis_managers:
            # Channel deletes already scrubbed analysis pane roles; re-project
            # the active analysis canvas so empty panes clear instead of
            # retaining stale curves.
            mgr = self.analysis_managers[mode]
            self._render_analysis_view_from_cache(mode, mgr.get(mgr.active))
        self._status_message(
            f"编辑: +{len(new_channels)} -{len(removed_channels)}"
        )
        self.toast(
            f"通道已更新: 新增 {len(new_channels)} · 删除 {len(removed_channels)}",
            "success",
        )
        self._plot_time_preserving_xlim()

    def _do_export_channels(self, fid, channels, include_time, use_range,
                            fmt="excel"):
        """Channel-editor export entry: ``excel`` / ``wwt`` / ``wwt_compact``."""
        key = str(fmt or "excel").lower()
        if key in ("wwt", "wwt_compact"):
            storage = "compact" if key == "wwt_compact" else "lossless"
            self._do_export_wwt(
                fid, channels, use_range=use_range, storage=storage,
            )
        else:
            self._do_export_excel(
                fid, channels, include_time=include_time, use_range=use_range
            )

    def _do_export_excel(self, fid, channels, include_time, use_range):
        """Write the given channels of file ``fid`` to an Excel file. Invoked
        by the channel-editor's 导出 section (export_requested). Time column and
        time-range filter mirror the former toolbar-export behavior."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        import pandas as pd
        fd = self.files.get(fid)
        requested_channels = channels or []
        valid_channels = [
            ch for ch in requested_channels
            if fd is not None and ch in fd.data.columns
        ]
        if fd is None or not valid_channels:
            self.toast("没有可导出的数据或未勾选通道", "warning")
            return
        fp, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "", "Excel (*.xlsx)")
        if not fp:
            return
        try:
            df = pd.DataFrame()
            if include_time and fd.time_array is not None:
                df['Time'] = fd.time_array
            for ch in valid_channels:
                df[ch] = fd.data[ch].values
            if use_range and fd.time_array is not None:
                lo, hi = self.inspector.top.range_values()
                m = (fd.time_array >= lo) & (fd.time_array <= hi)
                df = df.loc[m].reset_index(drop=True)
            df.to_excel(fp, index=False, engine='openpyxl')
            self._status_message(
                f"导出完成: {Path(fp).name} ({len(df)} 行 × {len(df.columns)} 列)"
            )
            self.toast(
                f"已导出 {Path(fp).name} · {len(df)} 行 × {len(df.columns)} 列",
                "success",
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _do_export_wwt(self, fid, channels, *, use_range, storage="lossless"):
        """Convert selected channels to a WinWert-openable ``.wwt``.

        走 ``io.wwt_export`` 的 clean-room 路径：正文自写（``Zeit`` + N 通道），
        ``storage=lossless`` 为 float64，``compact`` 为 int16 量化；显示尾块由
        捆绑的真实 WinWert 骨架重建并强制时域横坐标。
        """
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        import numpy as np
        from ...io.wwt_export import WwtExportError, export_wwt

        fd = self.files.get(fid)
        requested_channels = channels or []
        valid_channels = [
            ch for ch in requested_channels
            if fd is not None and ch in fd.data.columns
        ]
        if fd is None or not valid_channels:
            self.toast("没有可导出的数据或未勾选通道", "warning")
            return
        if fd.time_array is None or len(fd.time_array) < 2:
            self.toast("当前文件没有可用时间轴，无法导出 WWT", "warning")
            return

        t = np.asarray(fd.time_array, dtype=np.float64)
        series = {
            ch: np.asarray(fd.data[ch].values, dtype=np.float64)
            for ch in valid_channels
        }
        if use_range:
            lo, hi = self.inspector.top.range_values()
            mask = (t >= lo) & (t <= hi)
            t = t[mask]
            series = {ch: arr[mask] for ch, arr in series.items()}
        if len(t) < 2:
            QMessageBox.warning(
                self,
                "无法导出 WWT",
                "选定时间范围内采样点不足，请扩大范围或取消范围限制。",
            )
            return

        fp, _ = QFileDialog.getSaveFileName(
            self, "导出 WinWert WWT", "", "WinWert (*.wwt)"
        )
        if not fp:
            return
        if not str(fp).lower().endswith(".wwt"):
            fp = str(fp) + ".wwt"

        try:
            units = {
                ch: (fd.channel_units.get(ch, "") or "")
                for ch in valid_channels
            }
            title = ""
            comment = "Converted by TraceLab"
            smeta = getattr(fd, "source_metadata", None) or {}
            if isinstance(smeta, dict):
                title = str(smeta.get("title") or "")[:256]
                if smeta.get("comment"):
                    comment = str(smeta.get("comment"))[:256]
            result = export_wwt(
                fp,
                t,
                series,
                units=units,
                title=title,
                comment=comment,
                storage=storage,
            )
            self._status_message(
                f"导出完成: {Path(fp).name} ({result.summary})"
            )
            self.toast(
                f"已导出 {Path(fp).name} · WinWert/TraceLab 可打开 · "
                f"{result.summary}",
                "success",
            )
        except WwtExportError as e:
            QMessageBox.warning(self, "无法导出 WWT", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def open_batch(self):
        from ..drawers.batch import BatchSheet

        existing = self._alive_tool_dialog("_batch_sheet")
        if existing is not None:
            self._raise_tool_dialog(existing)
            return
        # The live Inspector/pane state is the sole authority.  Historical
        # render callbacks may still refresh _last_batch_preset for backward
        # compatibility, but that cache must never overwrite current intent.
        current_preset = self._build_current_batch_preset()
        # T6: a ``current_single`` preset captured before files were
        # closed/swapped will still hold a (fid, channel) tuple whose
        # fid no longer exists in ``self.files`` — forwarding it to the
        # Sheet leads to silent zero-task expansion at run-time. Detect
        # the case here, toast the user, and start the Sheet from a
        # clean slate so they can pick "free config" instead.
        if (current_preset is not None
                and current_preset.source == 'current_single'):
            sig = current_preset.signal
            if sig is None or sig[0] not in self.files:
                self.toast("当前单次预设已失效，请改用自由配置", "warning")
                current_preset = None
        # Batch order analysis retired the fixed-RPM mode that the
        # single-analysis view still offers.  ``_build_current_batch_preset``
        # already strips the retired keys, so the run would otherwise fail
        # per item with a generic "rpm channel is required".  Keep that notice
        # inside the sheet, where the RPM picker is available.  The
        # preset is kept: everything except the RPM source is still valid, so
        # the Sheet opens pre-filled and only the channel is left to pick.
        handoff_notice = ""
        if (current_preset is not None
                and current_preset.method == 'order_time'
                and self._order_view_uses_manual_rpm()):
            handoff_notice = (
                "批处理阶次分析不支持固定 RPM，请在批处理里指定 RPM 通道"
            )
        dlg = BatchSheet(self, self.files, current_preset=current_preset)
        if handoff_notice:
            dlg.set_handoff_notice(handoff_notice)
        self.chart_stack.mark_discovered("batch.export_options")
        # BatchSheet._on_run_clicked is the only live execution path.  The
        # sheet is a non-modal tool window so the Analyzer can keep doing
        # single-file work beside it.
        self._present_tool_dialog(
            dlg, "_batch_sheet", self._on_batch_sheet_destroyed,
        )

    def navigate_to_view(
        self, section: str, view_id: str, *, raise_window: bool = True
    ) -> bool:
        """Switch Analyzer to a source View.

        ``open_source`` keeps ``raise_window=True`` so the Analyzer comes
        forward while the Board stays open. UltraView sync/capture must pass
        ``raise_window=False``: the hidden source still becomes current so
        ``grab()`` can see it, but raising this window would flash the user
        out of the Board and back. Returns False when the View id is missing
        so the caller can arm replacement.
        """
        target = str(view_id)
        if section == "time":
            manager = getattr(self, "view_manager", None)
        else:
            managers = getattr(self, "analysis_managers", None) or {}
            manager = managers.get(section)
        if manager is None:
            return False
        idx = None
        for i, state in enumerate(manager.views):
            if str(getattr(state, "view_id", "")) == target:
                idx = i
                break
        if idx is None:
            return False
        toolbar = getattr(self, "toolbar", None)
        if toolbar is not None:
            toolbar._set_mode(section)

        def _finish_navigation():
            if section == "time":
                self._switch_view(idx)
            else:
                self._on_analysis_switch(section, idx)
            if raise_window:
                self.raise_()
                self.activateWindow()

        QTimer.singleShot(0, _finish_navigation)
        return True

    def open_ultraview(self):
        """Open UltraView as a standalone Board window, not a sixth mode."""
        from ..drawers.ultraview import UltraViewSheet

        existing = self._alive_tool_dialog("_ultraview_sheet")
        if existing is not None:
            self._prepare_ultraview_popup()
            self._raise_tool_dialog(existing)
            self._fit_ultraview_on_open()
            return
        page = getattr(self.chart_stack, "page_ultraview", None)
        stack = getattr(self.chart_stack, "stack", None)
        dlg = UltraViewSheet(self, page, stack)
        self._prepare_ultraview_popup()
        self._present_tool_dialog(
            dlg, "_ultraview_sheet", self._on_ultraview_sheet_destroyed,
        )
        self._fit_ultraview_on_open()

    def open_ultraview_unplaced(self):
        """Open UltraView and focus the active Board's unplaced tray."""
        self.open_ultraview()
        coord = getattr(self, "_ultraview", None)
        opener = getattr(coord, "open_unplaced_tray", None)
        if callable(opener):
            QTimer.singleShot(0, opener)

    def _fit_ultraview_on_open(self) -> None:
        """Every UltraView open parks on 适应, not leftover pan/zoom."""
        stack = getattr(self, "chart_stack", None)
        page = getattr(stack, "page_ultraview", None) if stack is not None else None
        fitter = getattr(page, "fit_on_open", None)
        if callable(fitter):
            fitter()

    def _prepare_ultraview_popup(self) -> None:
        uv = getattr(self, "_ultraview", None)
        if uv is None:
            return
        mode = self.toolbar.current_mode()
        source_modes = ("time", "fft", "fft_time", "frf", "order")
        if mode in source_modes:
            uv.capture_leaving_source(mode)
            uv.note_source_mode(mode)
        refresh = getattr(uv, "refresh_page", None)
        if callable(refresh):
            refresh()

    def _alive_tool_dialog(self, attr: str):
        dlg = getattr(self, attr, None)
        if dlg is None:
            return None
        try:
            from PyQt5 import sip
            if sip.isdeleted(dlg):
                setattr(self, attr, None)
                return None
        except (RuntimeError, TypeError):
            pass
        is_visible = getattr(dlg, "isVisible", None)
        if callable(is_visible):
            try:
                if is_visible():
                    return dlg
            except Exception:
                setattr(self, attr, None)
                return None
            # Hidden/closing: drop the handle only. Do not close() again —
            # a second closeEvent can steal the Board page from a newer
            # sheet. deleteLater stays so a hidden Batch/UltraView dialog
            # does not leak; destroyed uses identity so it cannot wipe a
            # replacement handle.
            deleter = getattr(dlg, "deleteLater", None)
            if callable(deleter):
                try:
                    deleter()
                except Exception:
                    pass
            setattr(self, attr, None)
            return None
        setattr(self, attr, None)
        return None

    def _raise_tool_dialog(self, dlg) -> None:
        present = getattr(dlg, "present", None)
        if callable(present):
            present()
            return
        show = getattr(dlg, "show", None)
        if callable(show):
            show()
        raiser = getattr(dlg, "raise_", None)
        if callable(raiser):
            raiser()
        activate = getattr(dlg, "activateWindow", None)
        if callable(activate):
            activate()

    def _present_tool_dialog(self, dlg, attr: str, on_destroyed) -> None:
        setattr(self, attr, dlg)
        destroyed = getattr(dlg, "destroyed", None)
        if destroyed is not None:
            try:
                destroyed.connect(on_destroyed)
            except (TypeError, RuntimeError):
                pass
        present = getattr(dlg, "present", None)
        if callable(present):
            present()
            return
        # Test doubles historically implemented exec_() only.
        exec_ = getattr(dlg, "exec_", None)
        if callable(exec_):
            exec_()
            return
        self._raise_tool_dialog(dlg)

    def _on_batch_sheet_destroyed(self, *_args) -> None:
        self._forget_tool_dialog_if_current("_batch_sheet")

    def _on_ultraview_sheet_destroyed(self, *_args) -> None:
        self._forget_tool_dialog_if_current("_ultraview_sheet")

    def _forget_tool_dialog_if_current(self, attr: str) -> None:
        current = getattr(self, attr, None)
        if current is None:
            return
        gone = self.sender()
        if gone is not None:
            if current is not gone:
                return
            setattr(self, attr, None)
            return
        try:
            from PyQt5 import sip
            if sip.isdeleted(current):
                setattr(self, attr, None)
        except (RuntimeError, TypeError):
            pass

    def _order_view_uses_manual_rpm(self) -> bool:
        """True when the live order view is driving off a fixed RPM value.

        Batch order analysis no longer accepts one, so ``open_batch`` warns
        about it at hand-off time.  Guarded with ``getattr`` because tests
        substitute lightweight order contexts.
        """
        rpm_mode = getattr(self.inspector.order_ctx, 'rpm_mode', None)
        if not callable(rpm_mode):
            return False
        try:
            return str(rpm_mode()) == 'manual'
        except Exception:
            return False

    def _build_current_batch_preset(self):
        from ...batch import AnalysisPreset
        from ...batch_recipe import normalize_batch_params

        mode = self.toolbar.current_mode()
        if mode == 'time':
            import dataclasses

            checked = self.channel_list.get_checked_channels()
            if not checked:
                return None
            file_ids = tuple(dict.fromkeys(fid for fid, _ch, _color in checked))
            target_signals = tuple(sorted({ch for _fid, ch, _color in checked}))
            params = {}
            if self.inspector.top.range_enabled():
                params['time_range'] = self.inspector.top.range_values()
            fp = getattr(self.inspector, "filter_panel", None)
            if fp is not None:
                params["filter"] = {
                    "enabled": bool(fp.is_enabled()),
                    "spec": fp.filter_spec().to_dict(),
                    "show_original": bool(fp.show_original()),
                    "show_filtered": bool(fp.show_filtered()),
                }
            preset = AnalysisPreset.free_config(
                name="当前时域",
                method="time",
                target_signals=target_signals,
                params=params,
            )
            target_pairs = tuple((fid, ch) for fid, ch, _color in checked)
            return dataclasses.replace(
                preset, file_ids=file_ids, target_pairs=target_pairs,
            )
        if mode == 'fft':
            signal = self.inspector.fft_ctx.current_signal()
            if signal is None:
                return None
            params_getter = getattr(
                self.inspector.fft_ctx,
                'current_params',
                self.inspector.fft_ctx.get_params,
            )
            params = params_getter()
            params['fs'] = self.inspector.fft_ctx.fs()
            if self.inspector.top.range_enabled():
                params['time_range'] = self.inspector.top.range_values()
            return AnalysisPreset.from_current_single(
                name="当前 FFT",
                method="fft",
                signal=signal,
                params=params,
            )
        if mode == 'fft_time':
            signal = self.inspector.fft_time_ctx.current_signal()
            if signal is None:
                return None
            params_getter = getattr(
                self.inspector.fft_time_ctx,
                'current_params',
                self.inspector.fft_time_ctx.get_params,
            )
            params = params_getter()
            params['fs'] = self.inspector.fft_time_ctx.fs()
            if self.inspector.top.range_enabled():
                params['time_range'] = self.inspector.top.range_values()
            params = normalize_batch_params(params, 'fft_time')
            return AnalysisPreset.from_current_single(
                name="当前 FFT vs Time",
                method="fft_time",
                signal=signal,
                params=params,
            )
        if mode == 'order':
            signal = self.inspector.order_ctx.current_signal()
            rpm_signal = self.inspector.order_ctx.current_rpm()
            if signal is None:
                return None
            params_getter = getattr(
                self.inspector.order_ctx,
                'current_params',
                self.inspector.order_ctx.get_params,
            )
            params = params_getter()
            params['fs'] = self.inspector.order_ctx.fs()
            params['rpm_factor'] = self.inspector.order_ctx.rpm_factor()
            if self.inspector.top.range_enabled():
                params['time_range'] = self.inspector.top.range_values()
            # Hand batch only what batch still accepts.  The order view emits
            # ``rpm_mode``/``manual_rpm`` unconditionally, and batch retired
            # both; forwarding them verbatim built a preset that could only
            # fail deep inside the run.  Normalizing here — rather than
            # popping a hard-coded pair — means any future retirement is
            # followed automatically, because ``normalize_batch_params`` is
            # the single definition of what a batch recipe may carry.  It
            # also drops ``time_range``, which batch order discards by design
            # (the matrix must span the full valid time domain) and which the
            # Batch sheet only ever surfaces for the FFT method.
            params = normalize_batch_params(params, 'order_time')
            return AnalysisPreset.from_current_single(
                name="当前时间-阶次",
                method="order_time",
                signal=signal,
                params=params,
                rpm_signal=rpm_signal,
                rpm_channel=rpm_signal[1] if rpm_signal else '',
            )
        return None

    def _remember_batch_preset(self, name, method, signal, params, rpm_signal=None):
        from ...batch import AnalysisPreset

        if signal is None:
            return
        params = dict(params)
        if self.inspector.top.range_enabled():
            params['time_range'] = self.inspector.top.range_values()
        self._last_batch_preset = AnalysisPreset.from_current_single(
            name=name,
            method=method,
            signal=signal,
            params=params,
            rpm_signal=rpm_signal,
            rpm_channel=rpm_signal[1] if rpm_signal else '',
        )

    def _get_sig(self):
        mode = self.toolbar.current_mode()
        if mode == 'fft':
            data = self.inspector.fft_ctx.current_signal()
        else:
            data = self.inspector.order_ctx.current_signal()
        if not data:
            return None, None, None
        fid, ch = data
        if fid not in self.files:
            return None, None, None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None, None, None
        return fd.time_array, fd.data[ch].values, fd.fs

    def _get_rpm(self, n):
        data = self.inspector.order_ctx.current_rpm()
        if not data:
            self.toast("请选择转速信号", "warning")
            return None
        fid, ch = data
        if fid not in self.files:
            return None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None
        factor = self.inspector.order_ctx.rpm_factor()
        rpm = fd.data[ch].values.copy() * factor
        if self.inspector.top.range_enabled() and fd.time_array is not None:
            lo, hi = self.inspector.top.range_values()
            m = (fd.time_array >= lo) & (fd.time_array <= hi)
            rpm = rpm[m]
        if len(rpm) != n:
            self.toast(f"信号与转速长度不匹配 ({n} vs {len(rpm)})", "warning")
            return None
        return rpm

    @staticmethod
    def _fft_auto_xlim(freq, amp):
        """Return display-only FFT fmax from the non-DC energy band."""
        return energy_band_fmax(freq, amp)

    @staticmethod
    def _fft_time_auto_freq_range(result):
        """Return display-only FFT-vs-Time frequency range from energy.

        ``SpectrogramResult.amplitude`` is ``freq_bins x frames``. Max over
        frames is intentionally conservative: intermittent low-frequency
        energy still expands the displayed frequency band enough to show it.
        """
        freq = getattr(result, 'frequencies', None)
        if freq is None:
            freq = getattr(result, 'freq', [])
        amp = np.asarray(getattr(result, 'amplitude', []), dtype=float)
        if amp.ndim >= 2:
            representative = np.nanmax(amp, axis=1)
        else:
            representative = amp
        return (0.0, energy_band_fmax(freq, representative))

    def _check_uniform_or_prompt(self, fd, mode):
        """Pre-flight non-uniform time-axis check before worker dispatch.

        The method name is retained for older call sites/tests, but the
        current UX no longer opens the rebuild popover automatically.
        When an MF4 timestamp axis is too jittered for the spectral
        analyzer, we rebuild it immediately with
        ``fd.suggested_fs_from_time_axis()`` (median-dt estimate), push
        that Fs back into the active contextual panel, clear affected FFT
        vs Time cache entries, and let the compute continue.
        """
        if fd is None or not hasattr(fd, 'is_time_axis_uniform'):
            # Either no file selected, or a duck-typed stand-in (test
            # fakes) that has no axis to validate. Defer to the worker.
            return True
        if fd.is_time_axis_uniform():
            return True

        if hasattr(fd, 'suggested_fs_from_time_axis'):
            suggested = fd.suggested_fs_from_time_axis()
        else:
            suggested = getattr(fd, 'fs', 0.0)
        if not (np.isfinite(suggested) and suggested > 0):
            self.toast("时间轴非均匀，且无法计算有效采样频率。", "warning")
            self.statusBar.showMessage("时间轴非均匀，无法自动重建")
            return False

        if not hasattr(fd, 'rebuild_time_axis'):
            self.toast("时间轴非均匀，当前文件对象不支持自动重建。", "warning")
            self.statusBar.showMessage("时间轴非均匀，无法自动重建")
            return False

        target_fid = None
        for fid, candidate in self.files.items():
            if candidate is fd:
                target_fid = fid
                break

        old_max = fd.time_array[-1] if getattr(fd, 'time_array', None) is not None and len(fd.time_array) else 0.0
        new_fs = float(suggested)
        fd.rebuild_time_axis(new_fs)
        new_max = fd.time_array[-1] if getattr(fd, 'time_array', None) is not None and len(fd.time_array) else 0.0

        if target_fid is not None:
            # Use the unified entry point: non-uniform time-axis auto-rebuild
            # also invalidates FFT and Order analysis caches, not just the
            # legacy LRU (问题① fix).
            self._invalidate_all_analysis_caches_for_fid(target_fid)
        try:
            current_hi = self.inspector.top.spin_end.maximum()
            self.inspector.top.set_range_limits(0, max(current_hi, new_max))
        except Exception:  # noqa: BLE001 - range refresh is best-effort UI state
            pass

        for ctx in (
            self.inspector.fft_ctx,
            self.inspector.fft_time_ctx,
            self.inspector.order_ctx,
        ):
            try:
                sig_data = ctx.current_signal()
            except Exception:  # noqa: BLE001
                sig_data = None
            if target_fid is None or (sig_data is not None and sig_data[0] == target_fid):
                if hasattr(ctx, 'set_fs'):
                    ctx.set_fs(new_fs)

        try:
            if self._restore_progress_token() is None:
                self.plot_time()
        except Exception:  # noqa: BLE001 - plot refresh must not block analysis
            pass

        short_name = getattr(fd, 'short_name', '') or getattr(fd, 'filename', '当前文件')
        self.statusBar.showMessage(
            f"时间轴已自动重建: {short_name} | Fs={new_fs:g} | {old_max:.1f}s → {new_max:.3f}s"
        )
        self.toast(
            f"时间轴非均匀，已按 Fs={new_fs:g} 自动处理。",
            "info",
        )
        return True

    # FFT compute methods (do_fft, _do_fft_single, _fft_compute_arrays, etc.)
    # live in _fft_mixin.FFTMixin — composed into MainWindow via its base list.

    # Order analysis methods (compute, service submission, callbacks, render, etc.)
    # live in _order_mixin.OrderMixin — composed into MainWindow via its base list.

    def closeEvent(self, event):
        """Drain all analysis jobs before the window is destroyed."""
        from PyQt5 import sip

        batch = getattr(self, "_batch_sheet", None)
        if batch is not None:
            try:
                gone = sip.isdeleted(batch)
            except (RuntimeError, TypeError):
                gone = True
            if not gone:
                is_running = getattr(batch, "is_running", None)
                if callable(is_running) and is_running():
                    confirm = getattr(batch, "confirm_stop_and_wait", None)
                    if not callable(confirm) or not confirm(parent=self):
                        event.ignore()
                        return
        for attr in ("_ultraview_sheet", "_batch_sheet"):
            dlg = getattr(self, attr, None)
            if dlg is not None:
                try:
                    if not sip.isdeleted(dlg):
                        dlg.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        uv = getattr(self, "_ultraview", None)
        if uv is not None:
            if not sip.isdeleted(uv):
                uv.shutdown()
                uv.deleteLater()
        abort = getattr(self, "_abort_analysis_restore", None)
        if callable(abort):
            abort()
        # A View switch parked by the render gate is moot once the window is
        # closing; replaying it would drive a full render through a widget tree
        # that is being torn down.
        self._time_render.clear_pending_switch()
        self._analysis_jobs.shutdown()
        super().closeEvent(event)

    # FFT-vs-Time methods (compute, dispatch, callbacks, render) live in
    # _fft_time_mixin.FFTTimeMixin — composed into MainWindow via its base list.

    # ---- FFT vs Time export (Plan Task 9) ----
    def _copy_fft_time_image(self, mode='full'):
        """Copy the FFT vs Time canvas to the system clipboard.

        ``mode='full'`` grabs the whole canvas (spectrogram + slice +
        colorbar). ``mode='main'`` grabs only the spectrogram + colorbar
        region; under headless Qt platforms the canvas falls back to
        the full grab transparently (see PgHeatmapCanvas.grab_main_chart).

        Guards on ``canvas_fft_time.has_result()`` so an empty canvas
        cannot be pushed to the clipboard — a warning toast surfaces
        instead. ``self.statusBar`` is the QStatusBar attribute (NOT
        ``self.statusBar()`` — codebase convention verified in T5).
        """
        if not self.canvas_fft_time.has_result():
            self.toast("尚无 FFT vs Time 结果可导出", "warning")
            return
        if mode == 'main':
            pix = self.canvas_fft_time.grab_main_chart()
            msg = "已复制 FFT vs Time 主图"
        else:
            pix = self.canvas_fft_time.grab_full_view()
            msg = "已复制 FFT vs Time 完整视图"
        QApplication.clipboard().setPixmap(pix)
        self.statusBar.showMessage(msg, 2000)
        self.toast(msg, "success")
