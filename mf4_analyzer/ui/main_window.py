"""MainWindow: top-level QMainWindow assembling the application UI."""
# Phase 2 complete: no legacy shims remain. The 3-pane topology
# (Toolbar + FileNavigator + ChartStack + Inspector) is the only owner
# of state; MainWindow is a router between them.

import importlib

import numpy as np
from pathlib import Path
from collections import OrderedDict

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QColorDialog,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)
from PyQt5.QtCore import QTimer, QThread

from ..io import DataLoader, FileData, HAS_ASAMMDF
from ..signal import FFTAnalyzer
from .. import app_meta


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(app_meta.WINDOW_TITLE)
        self.setGeometry(100, 100, 1450, 850);
        # Spec §9 minimum window size: 1100 × 640.
        self.setMinimumSize(1100, 640)
        self.files = OrderedDict();
        self._fc = 0;
        self._active = None
        self._project_path = None
        # FFT vs Time LRU cache (Plan Task 6). Keys are produced by
        # ``_fft_time_cache_key`` from compute-relevant fields ONLY —
        # display options (amplitude_mode, cmap, dynamic, freq_*) do
        # not participate, so toggling them re-renders without
        # recomputing. Capacity 12 = enough to hold a typical
        # diagnostic / amplitude / high-frequency preset sweep.
        # Invalidation lives in T7 (file-load / close / channel-edit /
        # custom-x / rebuild paths); no clear() calls in this task.
        self._fft_time_cache = OrderedDict()
        self._fft_time_cache_capacity = 12
        # FFT vs Time worker thread (Plan Task 7). Both refs are set
        # in ``do_fft_time`` when a compute is enqueued and cleared in
        # ``_on_fft_time_thread_done`` when the QThread reports
        # ``finished``. Re-entry guard in ``do_fft_time`` consults
        # ``_fft_time_thread.isRunning()``.
        self._fft_time_thread = None
        self._fft_time_worker = None
        # V7b: split-heatmap sequential compute queue. ``do_fft_time``
        # builds a list of cache-miss ``(pane_idx, fid, ch)`` jobs (focused
        # pane first); each job runs on the SAME single worker/thread above,
        # one at a time, so a 2-pane compare computes both panes without
        # spawning concurrent threads. ``_fft_time_pending`` carries the
        # current job's render target; the queue drives the next dispatch
        # from ``_on_fft_time_thread_done``.
        self._fft_time_queue = []
        # Order (COT) worker thread (M5). Same QObject + QThread pattern
        # as the FFT-vs-Time pair above; refs set in ``do_order_time``,
        # cleared in ``_on_order_thread_done``.
        self._order_thread = None
        self._order_worker = None
        # V7b: Order split-heatmap sequential compute queue (mirrors the
        # FFT-vs-Time queue above). Jobs are ``(pane_idx, fid, ch, rpm_source)``.
        self._order_queue = []
        self._last_batch_preset = None
        self._acquisition_cockpit_window = None
        self._init_ui();
        self._connect()

    def _init_ui(self):
        from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget
        from PyQt5.QtCore import Qt

        from .chart_stack import ChartStack
        from .file_navigator import FileNavigator
        from .inspector import Inspector
        from .toolbar import Toolbar
        from . import view_bridge
        from .view_state import ViewManager

        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = Toolbar(self)
        root.addWidget(self.toolbar)

        from PyQt5.QtWidgets import QHBoxLayout
        from .side_panels import Side, SidePanelStrip, PeekOverlay, SidePanelController

        splitter = QSplitter(Qt.Horizontal, self)
        self.splitter = splitter
        self.navigator = FileNavigator(self)
        self.chart_stack = ChartStack(self)
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
        self.channel_list = self.navigator.channel_list
        self.view_manager = ViewManager(self)
        self._view_bridge = view_bridge
        self.view_tabbar = self.chart_stack.attach_view_tabbar(self.view_manager)
        self._primary_view_idx = self.view_manager.active
        self._secondary_view_idx = None
        self._focused_view_idx = self.view_manager.active

        # V7 Step 2: per-section analysis view managers (owned by ChartStack so
        # the per-section ViewTabBar can dereference a real manager at
        # construction) + per-section LRU result caches (owned here).
        from .analysis_cache import AnalysisResultCache
        self.analysis_managers = self.chart_stack.analysis_managers
        self.analysis_caches = {
            'fft': AnalysisResultCache(32),
            'fft_time': AnalysisResultCache(12),
            'order': AnalysisResultCache(12),
        }
        # Re-entrancy guard: while a view switch is applying state to the UI,
        # suppress the inspector signal handlers that would otherwise capture
        # the half-applied controls back into the outgoing view.
        self._applying_analysis_view = False
        # Post-load auto-recompute queue. A saved project carries each analysis
        # view's compute params + signal sources but NOT the numeric results
        # (recompute-on-open, per the user's choice). open_project seeds this
        # with every (section, view_idx) that has sources; the first time such a
        # view is rendered we recompute it instead of showing the empty
        # "click 计算" state, then drop it from the set.
        self._analysis_restore_pending = set()
        # Identity of the inputs behind the last fft-canvas render. Re-entering
        # fft mode with the same signature reuses the retained stacked-page
        # canvas instead of wiping + rebuilding it (keeps the computed spectrum
        # alive across section round-trips and skips the preview rebuild cost).
        self._fft_last_render_sig = None

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self._status_hint_bar = None
        self._install_status_hint_bar(self.chart_stack.current_mode())
        self.chart_stack.mode_changed.connect(self._install_status_hint_bar)
        self.statusBar.showMessage("Ready")
        self._install_update_indicator()

        # Floating toast (constructed lazily on first use; the parent must
        # be the main window so the toast floats above the central canvas).
        from .widgets import Toast
        self._toast = Toast(self)
        from .markup import CopyThumbnail
        self._copy_thumbnail = CopyThumbnail(self)
        self._copy_thumbnail.clicked.connect(self._open_markup_editor)
        self._markup_editor = None

    def _install_update_indicator(self):
        """Far-right status-bar update affordance: a cloud-download icon
        (no text, hover '检查更新') + the app version, linking to the release
        page."""
        from PyQt5.QtCore import Qt, QSize
        from PyQt5.QtWidgets import QToolButton
        from ..ui_kit.icons import Icons
        from .. import app_meta

        self._update_btn = QToolButton(self)
        self._update_btn.setIcon(Icons.cloud_download())
        self._update_btn.setIconSize(QSize(18, 18))
        self._update_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._update_btn.setText(app_meta.APP_VERSION)
        self._update_btn.setAutoRaise(True)
        self._update_btn.setCursor(Qt.PointingHandCursor)
        self._update_btn.setToolTip("检查更新")
        self._update_btn.setStyleSheet(
            "QToolButton { padding: 2px 6px; }"
        )
        self._update_btn.clicked.connect(self._open_release_page)

        self.statusBar.addPermanentWidget(self._update_btn)

    def _open_release_page(self):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        from .. import app_meta
        QDesktopServices.openUrl(QUrl(app_meta.RELEASE_URL))

    def _install_status_hint_bar(self, mode=None):
        """Keep exactly one mode hint bar in the global status line."""
        mode = mode or self.chart_stack.current_mode()
        target = self.chart_stack.hint_bar_for_mode(mode)
        current = getattr(self, "_status_hint_bar", None)
        if current is target and target.parentWidget() is self.statusBar:
            target.show()
            return
        if current is not None:
            self.statusBar.removeWidget(current)
            current.hide()
            current.setParent(None)
        self._status_hint_bar = self.chart_stack.take_hint_bar(mode, self.statusBar)
        self.statusBar.insertPermanentWidget(0, self._status_hint_bar, 1)
        self._status_hint_bar.show()

    # ---- public toast helper ----
    def toast(self, msg, level='info'):
        """Show a transient acknowledgement toast at the bottom of the window."""
        if not msg:
            return
        self._toast.show_message(msg, level=level)

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
        from .markup import MarkupEditor
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

    def _connect(self):
        # --- New-module wiring ---
        self.toolbar.open_requested.connect(self.open_files_or_project)
        self.toolbar.save_project_requested.connect(self.save_project_via_dialog)
        self.toolbar.batch_requested.connect(self.open_batch)
        self.toolbar.acquisition_cockpit_requested.connect(self.open_acquisition_cockpit)
        self.toolbar.mode_changed.connect(self._on_mode_changed)
        self.chart_stack.image_captured.connect(
            lambda pix: self._publish_copied_pixmap(pix)
        )
        self.inspector.preset_acknowledged.connect(
            lambda level, msg: self.toast(msg, level)
        )

        self.navigator.channels_changed.connect(self._ch_changed)
        self.navigator.channel_editor_requested.connect(self.open_editor)
        self.navigator.file_activated.connect(self._on_file_activated)
        self.navigator.file_close_requested.connect(self._on_file_close_requested)
        self.navigator.close_all_requested.connect(self._on_close_all_requested)
        self.navigator.primary_channel_requested.connect(
            self._on_primary_channel_requested
        )
        self.navigator.channel_context_menu_requested.connect(
            lambda: self.chart_stack.mark_discovered("channel.right_click")
        )

        # Canvas cursor signals are owned by ChartStack; MainWindow doesn't
        # need to subscribe (ChartStack updates the pill itself).

        # Inspector signals wire up in Phase 2 when real sections land. In
        # Phase 1, these are no-ops but must exist so Task 2.x edits are
        # minimal additions rather than rewrites.
        self.inspector.plot_time_requested.connect(self.plot_time)
        self.inspector.fft_requested.connect(self.do_fft)
        self.inspector.order_time_requested.connect(self.do_order_time)
        self.inspector.xaxis_apply_requested.connect(self._apply_xaxis)
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
        self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)
        self.chart_stack.focus_changed.connect(self._on_chart_focus_changed)
        self.chart_stack.home_triggered.connect(
            lambda: self._hint_focused_pane("复位")
        )
        # P2 Task 9 1b: the secondary (compare) pane's own 分屏/叠加 control
        # asks for a layout replot of just that canvas, X-window preserved.
        self.chart_stack.set_secondary_replot_callback(
            self._replot_secondary_preserving_xlim
        )
        self.inspector.signal_changed.connect(self._on_inspector_signal_changed)
        self.view_tabbar.switch_requested.connect(self._switch_view)
        self.view_tabbar.new_requested.connect(self._on_view_new)
        self.view_tabbar.delete_requested.connect(self._on_view_delete)
        self.view_tabbar.duplicate_requested.connect(self._on_view_duplicate)
        self.view_tabbar.rename_requested.connect(self.view_manager.rename)
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
            bar.rename_requested.connect(mgr.rename)
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
            if sec != 'fft':
                page.pane_canvas(0).levels_changed.connect(
                    lambda lo, hi, s=sec: self._on_analysis_levels_dragged(
                        s, 0, lo, hi))
            else:
                self._connect_fft_preview_range_signal(page.pane_canvas(0), 0)

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
        # Hover readout: surface PgHeatmapCanvas.cursor_info in the
        # status bar (reviewer Important #1; design §6.4 mouse-move
        # readout). Pattern matches canvas_time.cursor_info → ChartStack
        # CursorPill — the pill is gated to time mode, so the spectrogram
        # canvas reuses the status bar instead of cloning the pill.
        self.canvas_fft_time.cursor_info.connect(
            self._on_fft_time_cursor_info
        )

        # Populate xaxis channel candidates whenever user flips to 'channel' mode.
        self.inspector.top.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._on_xaxis_mode_changed('channel' if i == 1 else 'time')
        )

        # Custom X axis state (unchanged)
        self._custom_xlabel = None
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        # Phase 1 item 4: track range-filter and plot-mode state across
        # plot_time() calls so we can fire the appropriate envelope-cache
        # invalidation when either changes (the cache is keyed on raw
        # (data_id, channel, xlim, pixel_width) and does NOT know whether
        # the source arrays were range-filtered or which plot layout was
        # active when the entry was inserted).
        self._last_range_state = None   # (enabled, lo, hi) or None
        self._last_plot_mode = None     # 'overlay' / 'subplot' / None
        # Overlay primary-axis pick: (fid, ch) chosen via the channel
        # right-click 设为左轴 menu. When set AND still checked AND in overlay
        # mode, plot_time reorders the checked list so this channel is index 0
        # (bound to the left axis). Cleared/ignored otherwise.
        self._overlay_primary = None
        self.inspector.top.chk_range.toggled.connect(
            self._on_time_range_enabled_changed
        )
        xrange_changed = getattr(self.canvas_time, 'xrange_changed', None)
        if xrange_changed is not None:
            xrange_changed.connect(self._on_time_canvas_xrange_changed)
        self._connect_canvas_range_signals(self.canvas_time)

        # ── Toolbar sidebar toggle buttons ───────────────────────────────────
        from .side_panels import Ev, PanelState
        self.toolbar.nav_panel_toggled.connect(
            lambda: self._panel_ctrl_left._dispatch(Ev.CLICK)
        )
        self.toolbar.inspector_panel_toggled.connect(
            lambda: self._panel_ctrl_right._dispatch(Ev.CLICK)
        )
        # Sync checked state when panel state changes (includes drag-collapse).
        self._panel_ctrl_left.state_changed.connect(
            lambda s: self.toolbar.set_nav_open(s == PanelState.PINNED)
        )
        self._panel_ctrl_right.state_changed.connect(
            lambda s: self.toolbar.set_inspector_open(s == PanelState.PINNED)
        )

    def _connect_canvas_range_signals(self, canvas):
        visible_range_changed = getattr(canvas, 'visible_range_changed', None)
        if visible_range_changed is not None:
            visible_range_changed.connect(
                lambda c=canvas: self._capture_canvas_ranges_for_bound_view(c)
            )

    def _ensure_secondary_range_signal_connected(self):
        canvas = self.chart_stack.secondary_canvas()
        if canvas is None or getattr(canvas, '_view_range_connected', False):
            return
        self._connect_canvas_range_signals(canvas)
        xrange_changed = getattr(canvas, 'xrange_changed', None)
        if xrange_changed is not None:
            xrange_changed.connect(self._on_secondary_canvas_xrange_changed)
        canvas._view_range_connected = True

    def _capture_current_view(self):
        self._capture_focused_view()

    def _sync_pane_bindings_from_manager(self):
        active = self.view_manager.active
        partner = self.view_manager.split_with
        self._primary_view_idx = active
        self._secondary_view_idx = partner
        if partner is None:
            self._focused_view_idx = active
        elif self._focused_view_idx not in (active, partner):
            self._focused_view_idx = active

    def _view_index_for_canvas(self, canvas):
        if canvas is self.canvas_time:
            return self._primary_view_idx
        secondary = self.chart_stack.secondary_canvas()
        if secondary is not None and canvas is secondary:
            return self._secondary_view_idx
        return None

    def _canvas_for_view_index(self, idx):
        if idx == self._primary_view_idx:
            return self.canvas_time
        if idx == self._secondary_view_idx:
            return self.chart_stack.secondary_canvas()
        return None

    def _capture_canvas_ranges_for_bound_view(self, canvas):
        if getattr(self, '_applying_view', False):
            return
        idx = self._view_index_for_canvas(canvas)
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        self._view_bridge.capture_canvas_ranges_into(self.view_manager.get(idx), canvas)

    def _capture_focused_view(self):
        idx = self._focused_view_idx
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        canvas = self._canvas_for_view_index(idx) or self.canvas_time
        state = self.view_manager.get(idx)
        self._view_bridge.capture_controls_into(state, self, canvas)
        self._view_bridge.capture_canvas_ranges_into(state, canvas)

    def _project_view_controls(self, idx):
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return
        canvas = self._canvas_for_view_index(idx) or self.canvas_time
        old_applying_view = getattr(self, '_applying_view', False)
        self._applying_view = True
        try:
            self._view_bridge.apply_controls_from_state(
                self.view_manager.get(idx), self, canvas
            )
        finally:
            self._applying_view = old_applying_view

    def _sync_focus_accent(self):
        idx = self._focused_view_idx
        color = None
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            color = self.view_manager.get(idx).tab_color
        setter = getattr(self.chart_stack, 'set_focus_accent', None)
        if callable(setter):
            setter(color)

    def _hint_focused_pane(self, action_label):
        if not self.chart_stack.split_active():
            return False
        idx = self._focused_view_idx
        if idx is None or not (0 <= idx < len(self.view_manager.views)):
            return False
        role = "主栏" if idx == self._primary_view_idx else "副栏"
        name = self.view_manager.get(idx).name
        self.toast(f"{action_label} 作用于 {role} · {name} · 点另一栏可改", "info")
        return True

    def _install_view_shortcuts(self):
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        from PyQt5.QtCore import Qt
        self._view_shortcuts = []
        for i in range(6):
            sc = QShortcut(QKeySequence(f"Alt+{i + 1}"), self)
            sc.setContext(Qt.ApplicationShortcut)
            idx = i
            sc.activated.connect(
                lambda bound=idx: self._switch_view_for_active_section(bound))
            self._view_shortcuts.append(sc)

    def _switch_view_for_active_section(self, idx):
        """Alt+i: switch the view of whatever section is currently shown.

        The time section keeps the cross-view pairing path (``_switch_view``);
        analysis sections (fft/fft_time/order) route to their own manager via
        ``_on_analysis_switch``. Both already guard idx range + no-op on no
        change, so out-of-range Alt keys are safe.
        """
        mode = self.chart_stack.current_mode()
        if mode in ('fft', 'fft_time', 'order'):
            self._on_analysis_switch(mode, idx)
        else:
            self._switch_view(idx)

    def _switch_view(self, idx):
        if idx == self.view_manager.active:
            return
        if not (0 <= idx < len(self.view_manager.views)):
            return
        self._capture_focused_view()
        self.view_manager.set_active(idx)

    def _apply_active_view(self, idx):
        if not (0 <= idx < len(self.view_manager.views)):
            return
        self._sync_pane_bindings_from_manager()
        partner = self.view_manager.split_with
        if partner is None:
            self.chart_stack.exit_split()
        else:
            self.chart_stack.enter_split()
            self._ensure_secondary_range_signal_connected()
        self._focused_view_idx = idx
        self._sync_focus_accent()
        if self.files and self.chart_stack.current_mode() == 'time':
            self._render_view_to_canvas(idx, self.canvas_time, update_primary_ui=True)
            if partner is not None:
                self._render_view_to_canvas(
                    partner,
                    self.chart_stack.secondary_canvas(),
                    update_primary_ui=False,
                )
        else:
            self._project_view_controls(idx)

    def _on_view_split(self, other_idx):
        self._capture_focused_view()
        self._sync_pane_bindings_from_manager()
        if other_idx is None:
            self.chart_stack.exit_split()
            self._secondary_view_idx = None
            self._focused_view_idx = self.view_manager.active
            self._sync_focus_accent()
            if self.files and self.chart_stack.current_mode() == 'time':
                self._render_view_to_canvas(
                    self.view_manager.active,
                    self.canvas_time,
                    update_primary_ui=True,
                )
            else:
                self._project_view_controls(self.view_manager.active)
            return
        if not (0 <= other_idx < len(self.view_manager.views)):
            self.chart_stack.exit_split()
            return

        self.chart_stack.enter_split()
        self._ensure_secondary_range_signal_connected()
        self._focused_view_idx = self.view_manager.active
        self._sync_focus_accent()
        if self.files and self.chart_stack.current_mode() == 'time':
            self._render_view_to_canvas(
                self.view_manager.active, self.canvas_time, update_primary_ui=True
            )
            self._render_view_to_canvas(
                other_idx, self.chart_stack.secondary_canvas(), update_primary_ui=False
            )
        else:
            self._project_view_controls(self.view_manager.active)

    def _on_view_clear_split(self, idx):
        self._capture_focused_view()
        self.view_manager.clear_split_for(idx)

    def _render_view_to_canvas(self, idx, canvas, *, update_primary_ui):
        if canvas is None:
            return
        if not (0 <= idx < len(self.view_manager.views)):
            return
        state = self.view_manager.get(idx)

        # Snapshot/restore is only for off-screen secondary renders in split
        # mode. Primary view switches must show the target view's cursor state,
        # not the previous view's last readout.
        cursor_pill_snapshot = (
            self.chart_stack.cursor_pill_snapshot()
            if not update_primary_ui
            else None
        )
        restore_idx = self._focused_view_idx
        old_applying_view = getattr(self, '_applying_view', False)
        self._applying_view = True
        try:
            self._view_bridge.apply_controls_from_state(state, self, canvas)
            if update_primary_ui and state.cursor_mode == 'off':
                self.chart_stack.clear_cursor_pill()
            self._plot_time_on_canvas(
                canvas,
                update_primary_ui=update_primary_ui,
                defer_first_frame=(state.xlim is not None),
            )
            canvas.restore_visible_xlim(state.xlim)
            canvas.restore_visible_ylims(state.ylims)
            tick_opts = (state.axis_opts or {}).get('tick_density') or {}
            canvas.set_tick_density(
                int(tick_opts.get('x', 10)),
                int(tick_opts.get('y', 6)),
            )
        finally:
            self._applying_view = old_applying_view
            if restore_idx is not None:
                self._project_view_controls(restore_idx)
            if cursor_pill_snapshot is not None:
                self.chart_stack.restore_cursor_pill_snapshot(cursor_pill_snapshot)

    # ==================================================================
    # V7: per-section analysis view routing (Steps 2-4)
    # ==================================================================
    def _analysis_ctx(self, section):
        return {
            'fft': self.inspector.fft_ctx,
            'fft_time': self.inspector.fft_time_ctx,
            'order': self.inspector.order_ctx,
        }[section]

    def _analysis_page(self, section):
        return {
            'fft': self.chart_stack.page_fft,
            'fft_time': self.chart_stack.page_fft_time,
            'order': self.chart_stack.page_order,
        }[section]

    # -- tab-bar intent handlers (capture outgoing view first) ----------
    def _on_analysis_switch(self, section, idx):
        mgr = self.analysis_managers[section]
        if idx == mgr.active:
            return
        self._capture_active_analysis_view(section)
        mgr.set_active(idx)

    def _on_analysis_new(self, section):
        self._capture_active_analysis_view(section)
        self.analysis_managers[section].new_view()

    def _on_analysis_delete(self, section, idx):
        self._capture_active_analysis_view(section)
        self.analysis_managers[section].delete_view(idx)

    def _on_analysis_duplicate(self, section, idx):
        self._capture_active_analysis_view(section)
        self.analysis_managers[section].duplicate(idx)

    def _on_analysis_color(self, section, idx):
        mgr = self.analysis_managers[section]
        if not (0 <= idx < len(mgr.views)):
            return
        from PyQt5.QtGui import QColor
        current = QColor(mgr.get(idx).tab_color)
        color = QColorDialog.getColor(current, self, "选择标签颜色")
        if color.isValid():
            mgr.set_color(idx, color.name())

    def _on_analysis_split(self, section, on):
        """split_requested / clear_split_requested → add / remove pane 2 of the
        ACTIVE view of this section."""
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        page = self._analysis_page(section)
        if on:
            if state.add_pane():
                page.enter_split()
                self._connect_new_pane(section, page)
        else:
            state.remove_second_pane()
            page.exit_split()

    def _connect_new_pane(self, section, page):
        """Wire copy/annotation relays for a freshly split pane card so the
        compare pane behaves like pane 0."""
        if page.pane_count() < 2:
            return
        self.chart_stack._connect_analysis_card_signals(page._cards[1])
        if section == 'fft':
            self._connect_fft_preview_range_signal(page.pane_canvas(1), 1)
        # V8: pane 1's colorbar-drag → inspector Z echo (heatmap sections).
        # Guarded against double-wiring across repeated splits via a marker on
        # the canvas (enter_split builds a fresh card each time, so a stale
        # connection on a destroyed canvas is never reused — but a duplicate
        # connect on the same long-lived canvas would double-fire).
        if section != 'fft':
            canvas = page.pane_canvas(1)
            if not getattr(canvas, '_levels_echo_wired', False):
                canvas.levels_changed.connect(
                    lambda lo, hi: self._on_analysis_levels_dragged(
                        section, 1, lo, hi))
                canvas._levels_echo_wired = True

    def _connect_fft_preview_range_signal(self, canvas, pane_idx):
        signal = getattr(canvas, 'time_preview_range_changed', None)
        if signal is None or getattr(canvas, '_fft_preview_range_wired', False):
            return
        signal.connect(
            lambda lo, hi, idx=pane_idx: self._on_fft_preview_range_changed(
                idx, lo, hi))
        canvas._fft_preview_range_wired = True

    # -- view-switch pipeline (capture → switch → apply → render) -------
    def _capture_active_analysis_view(self, section, *, capture_sources=True):
        from .analysis_view_bridge import capture_params_to_state
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        capture_params_to_state(self._analysis_ctx(section), state)
        if capture_sources:
            self._capture_analysis_sources(section, state)

    def _on_analysis_view_switched(self, section, idx):
        """manager.active_changed → apply the new view's structure, params and
        sources, then render whatever the cache already holds (never compute)."""
        from .analysis_view_bridge import apply_params_from_state
        mgr = self.analysis_managers[section]
        if not (0 <= idx < len(mgr.views)):
            return
        state = mgr.get(idx)
        page = self._analysis_page(section)
        self._applying_analysis_view = True
        try:
            # 1. Align the pane structure to the view (1 or 2 panes).
            if len(state.panes) == 2 and page.pane_count() == 1:
                page.enter_split()
                self._connect_new_pane(section, page)
            elif len(state.panes) == 1 and page.pane_count() == 2:
                page.exit_split()
            # 2. Compare options (state is the source of truth; enter_split
            #    above may have emitted a non-edge link_toggled — we ignore
            #    that signal entirely and drive set_linked from state here).
            #    V8 closes the loop: set_levels_locked is now also state-driven,
            #    and the toggle buttons are re-seeded from state.compare (under
            #    _applying_analysis_view, so the resulting button edges do not
            #    write back onto the state we just read).
            x_linked = bool(state.compare.get('x_linked', True))
            levels_locked = bool(state.compare.get('levels_locked', True))
            page.set_linked(x_linked)
            page.set_levels_locked(levels_locked)
            page.sync_compare_buttons(
                x_linked=x_linked, levels_locked=levels_locked)
            # 3. Params + focused-pane source echo.
            apply_params_from_state(self._analysis_ctx(section), state)
            self._apply_analysis_sources(section, state)
        finally:
            self._applying_analysis_view = False
        # 4. Render from cache only (spec §4: switching never auto-computes).
        self._render_analysis_view_from_cache(section, state)

    def _on_analysis_focus_changed(self, section, idx):
        """A pane click changed the focused pane: capture the source selection
        into the PREVIOUS focused pane, then echo the now-focused pane's
        source back into the inspector / navigator."""
        if self._applying_analysis_view:
            return
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        page = self._analysis_page(section)
        old_idx = min(page.previous_focused_index(), len(state.panes) - 1)
        self._capture_analysis_sources(section, state, pane_idx=old_idx)
        self._apply_analysis_sources(section, state)

    def _on_analysis_compare_toggled(self, section, key, on):
        """A page compare toggle (联动缩放 / 锁定色阶) flipped → persist it onto
        the active view's ``state.compare`` so a later view switch reads it
        back (V8 write-back loop: toggle → state → _on_analysis_view_switched
        reads state to drive set_linked / set_levels_locked)."""
        if self._applying_analysis_view:
            return
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        state.compare[key] = bool(on)

    def _on_analysis_levels_dragged(self, section, pane_idx, lo, hi):
        """User dragged a heatmap colorbar → echo (lo, hi) into the inspector
        Z controls (manual range). Only the FOCUSED pane's drag drives the
        inspector, since the inspector mirrors the focused pane. fft (line
        section) has no colorbar so it never reaches here.

        The two-pane *canvas* sync under a level lock is handled entirely
        inside the page (_on_locked_levels_changed); this path is strictly
        canvas → inspector, so the two never fight: the page mutates the
        sibling canvas's levels, MainWindow mutates the inspector spinboxes.
        apply_params here is an existing inspector API called with corrected
        args — no algorithm/loader is touched."""
        if self._applying_analysis_view:
            return
        page = self._analysis_page(section)
        if pane_idx != page.focused_index():
            return
        ctx = self._analysis_ctx(section)
        ctx.apply_params({
            'z_auto': False,
            'z_floor': float(lo),
            'z_ceiling': float(hi),
        })

    # -- source routing (Step 4) ----------------------------------------
    def _capture_analysis_sources(self, section, state, pane_idx=None):
        page = self._analysis_page(section)
        if pane_idx is None:
            pane_idx = page.focused_index()
        idx = min(int(pane_idx), len(state.panes) - 1)
        pane = state.panes[idx]
        if section == 'fft':
            checked = self.navigator.get_checked_channels()
            pane.sources = [(fid, ch) for fid, ch, _color in checked]
            self._sync_fft_source_summary(checked)
        else:
            ctx = self._analysis_ctx(section)
            sig = ctx.current_signal()
            pane.sources = [tuple(sig)] if sig else []
            if section == 'order':
                rpm = ctx.current_rpm()
                pane.rpm_source = tuple(rpm) if rpm else None

    def _analysis_channel_color_map(self):
        colors = {}
        getter = getattr(self.navigator, 'get_channel_colors', None)
        if callable(getter):
            for key, color in getter().items():
                try:
                    fid, ch = key[:2]
                except (TypeError, ValueError):
                    continue
                colors[(fid, ch)] = color
        for row in self.navigator.get_checked_channels():
            try:
                fid, ch, color = row[:3]
            except (TypeError, ValueError):
                continue
            colors[(fid, ch)] = color
        return colors

    def _apply_analysis_sources(self, section, state):
        page = self._analysis_page(section)
        idx = min(page.focused_index(), len(state.panes) - 1)
        pane = state.panes[idx]
        if section == 'fft':
            self.navigator.set_checked_channels(list(pane.sources))
            self._sync_fft_source_summary()
        else:
            ctx = self._analysis_ctx(section)
            if pane.sources:
                self._echo_combo_signal(ctx.combo_sig, pane.sources[0])
            if section == 'order' and pane.rpm_source is not None:
                self._echo_combo_signal(ctx.combo_rpm, pane.rpm_source)

    @staticmethod
    def _echo_combo_signal(combo, key):
        """Select ``key`` (a (fid, ch) tuple) in a SearchableComboBox by its
        userData, tolerating list/tuple shape drift."""
        if key is None:
            return
        target = tuple(key)
        for i in range(combo.count()):
            data = combo.itemData(i)
            if data is not None and tuple(data) == target:
                combo.setCurrentIndex(i)
                return

    # -- cache-backed render on switch (Step 3) -------------------------
    def _analysis_compute_params(self, section):
        """Compute-relevant params (cache-key inputs) for the active inspector
        state of ``section``. Display-only knobs are excluded so toggling them
        does not invalidate the cache."""
        ctx = self._analysis_ctx(section)
        p = ctx.get_params()
        if section == 'fft':
            # Compute inputs for FFT spectra are window / nfft / averaging mode
            # + averaging overlap (see _fft_compute_arrays). The plain
            # ``overlap`` knob feeds only batch presets, NOT the spectrum
            # compute, so it is excluded from the key (and its get/apply
            # fraction-vs-percent asymmetry would make the key unstable).
            cp = ctx.current_params()
            return {
                'window': p.get('window'),
                'nfft': p.get('nfft'),
                'avg_mode': cp.get('avg_mode', '单帧'),
                'avg_overlap': cp.get('avg_overlap', 50),
            }
        if section == 'fft_time':
            return {
                'fs': p.get('fs'),
                'nfft': p.get('nfft'),
                'window': p.get('window'),
                'overlap': p.get('overlap'),
                'remove_mean': p.get('remove_mean'),
                'db_reference': p.get('db_reference', 1.0),
            }
        # order: COT params + rpm_source must both be in the key (changing the
        # RPM channel must NOT hit an old result).
        return {
            'nfft': p.get('nfft'),
            'max_order': p.get('max_order'),
            'order_res': p.get('order_res'),
            'time_res': p.get('time_res'),
            'samples_per_rev': ctx.current_params().get('samples_per_rev'),
        }

    def _analysis_cache_key(self, section, fid, ch, rpm_source=None):
        cache = self.analysis_caches[section]
        params = dict(self._analysis_compute_params(section))
        if section == 'order':
            params['rpm_source'] = (
                list(rpm_source) if rpm_source else None
            )
        return cache.make_key(fid, ch, params)

    def _recompute_analysis_section(self, section):
        """Dispatch the active view's compute for ``section`` (used by the
        post-load auto-recompute path). Reuses the same entry points as the
        计算 buttons, so caching / rendering / split-pane handling are shared.

        Runs deferred (QTimer.singleShot) from the restore path; guard the whole
        dispatch so a compute failure can never bubble out of the event-loop
        callback and tear down the freshly opened project."""
        try:
            if section == 'fft':
                self.do_fft()
            elif section == 'order':
                self.do_order_time()
            elif section == 'fft_time':
                self.do_fft_time()
        except Exception:
            pass

    def _render_analysis_view_from_cache(self, section, state):
        """Render each pane from cached results; panes whose sources are not all
        cached show an empty state and a 'click 计算' status hint.

        Normally never computes (spec §4). The one exception is the post-load
        auto-recompute: when this (section, view) was queued by open_project
        and still has sources, recompute it once so the saved params + sources
        repopulate the chart, then fall back to the normal cache-render path on
        every subsequent call."""
        mgr = self.analysis_managers.get(section)
        if mgr is not None:
            restore_key = (section, mgr.active)
            if restore_key in self._analysis_restore_pending:
                self._analysis_restore_pending.discard(restore_key)
                if any(p.sources for p in state.panes):
                    # Defer the recompute to the next event-loop turn instead of
                    # running it inline. open_project drives this for all three
                    # sections mid-restore; a synchronous compute could pop a
                    # blocking QMessageBox (FFT/order compute error) that would
                    # interrupt the half-finished open. Deferring lets the window
                    # finish opening first, so any error surfaces cleanly after.
                    QTimer.singleShot(
                        0, lambda s=section: self._recompute_analysis_section(s))
                    return
        page = self._analysis_page(section)
        any_missing = False
        for pane_idx in range(page.pane_count()):
            if pane_idx >= len(state.panes):
                break
            pane = state.panes[pane_idx]
            canvas = page.pane_canvas(pane_idx)
            cache = self.analysis_caches[section]
            if section == 'fft':
                entries = []
                colors = self._analysis_channel_color_map()
                for fid, ch in pane.sources:
                    key = self._analysis_cache_key(section, fid, ch)
                    result = cache.get(key)
                    if result is None:
                        any_missing = True
                        continue
                    entries.append(self._fft_entry_from_cache(
                        result, fid, ch, colors.get((fid, ch))))
                if entries:
                    self._plot_fft_entries(entries, canvas)
                else:
                    # No cached curves (empty sources, or all sources missing
                    # from the cache) -> empty canvas state.
                    self._clear_analysis_canvas(canvas)
            else:
                if not pane.sources:
                    self._clear_analysis_canvas(canvas)
                    continue
                fid, ch = pane.sources[0]
                key = self._analysis_cache_key(
                    section, fid, ch,
                    rpm_source=pane.rpm_source if section == 'order' else None)
                result = cache.get(key)
                if result is None:
                    any_missing = True
                    self._clear_analysis_canvas(canvas)
                else:
                    self._render_cached_heatmap(section, canvas, result)
        if any_missing:
            self.statusBar.showMessage("参数/源已就绪，点击计算")

    def _clear_analysis_canvas(self, canvas):
        if hasattr(canvas, 'full_reset'):
            try:
                canvas.full_reset()
            except Exception:
                pass

    # -- render glue (shared by cache-switch and compute paths) ---------
    def _file_display_name(self, fid):
        fd = self.files.get(fid)
        if fd is None:
            return str(fid)
        return getattr(fd, 'short_name', None) or str(fid)

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

    def _fft_trace_for_source(self, fid, ch):
        fd = self.files.get(fid)
        if fd is None or ch not in fd.data.columns:
            return None, None
        t = np.asarray(fd.time_array, dtype=float)
        sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            mask = (t >= lo) & (t <= hi)
            t = t[mask]
            sig = sig[mask]
        return t, sig

    def _fft_time_preview_entries(self, checked=None):
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
            t, sig = self._fft_trace_for_source(fid, ch)
            if t is None or sig is None or len(sig) == 0:
                continue
            entries.append({
                'label': f"{self._file_display_name(fid)} · {ch}",
                'color': color or '#2563eb',
                'time': t,
                'signal': sig,
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

    def _fft_render_signature(self):
        """Identity of everything the fft-canvas render depends on that can
        change while another section is showing. Two fft-mode entries with the
        same signature show identical content, so the retained stacked-page
        canvas may be reused untouched (no spectrum wipe, no preview rebuild).

        Only fft *inputs* go in here: the navigator selection (shared across
        sections), the compute params (cache-key inputs), the time-range
        filter (drives the preview), and the dB/linear display toggle. The
        remaining fft knobs live in the fft-only inspector that is hidden in
        other sections, so they cannot drift while away."""
        sources = tuple(
            (str(row[0]), str(row[1]))
            for row in self.navigator.get_checked_channels()
            if len(row) >= 2
        )
        params = self._analysis_compute_params('fft')
        range_sig = None
        if self.inspector.top.range_enabled():
            try:
                range_sig = tuple(
                    float(v) for v in self.inspector.top.range_values())
            except Exception:
                range_sig = None
        amp_y = self.inspector.fft_ctx.current_params().get('amp_y', 'Linear')
        return (sources, tuple(sorted(params.items())), range_sig, amp_y)

    def _fft_any_source_cached(self, state):
        cache = self.analysis_caches['fft']
        for pane in state.panes:
            for fid, ch in pane.sources:
                if cache.get(self._analysis_cache_key('fft', fid, ch)) is not None:
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
        cached."""
        if self.chart_stack.current_mode() != 'fft' or not self.files:
            return
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        # Mirror do_fft / the view-switch path: pull the (possibly changed)
        # navigator selection into the active view so the cache lookup and the
        # signature reflect what is actually selected right now.
        self._capture_active_analysis_view('fft')
        signature = self._fft_render_signature()
        if signature == self._fft_last_render_sig:
            return
        self._fft_last_render_sig = signature
        if self._fft_any_source_cached(state):
            self._render_analysis_view_from_cache('fft', state)
        else:
            self._refresh_fft_time_preview()

    def _fft_entry_from_cache(self, result, fid, ch, color):
        """Build a plot_spectra entry from a cached FFT result.

        ``result`` is the raw compute tuple ``(freq, amp, psd)`` (linear). The
        dB/linear display transform is applied here from the CURRENT inspector
        axis toggle, so toggling dB re-renders without recompute (display-only
        knobs are excluded from the cache key)."""
        freq, amp, _psd = result
        p = self.inspector.fft_ctx.current_params()
        amp_y = p.get('amp_y', 'Linear')
        if amp_y == 'dB':
            amp_disp = 20 * np.log10(
                np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12))
        else:
            amp_disp = amp
        label = f"{self._file_display_name(fid)} · {ch}"
        t, sig = self._fft_trace_for_source(fid, ch)
        return {
            'label': label,
            'color': color or '#2563eb',
            'freq': freq,
            'amp': amp_disp,
            'time': [] if t is None else t,
            'signal': [] if sig is None else sig,
        }

    def _plot_fft_entries(self, entries, canvas=None):
        """Render a pane's FFT overlay entries with axis labels/limits pulled
        from the current inspector state."""
        if canvas is None:
            canvas = self.canvas_fft
        if not entries:
            return
        p = self.inspector.fft_ctx.current_params()
        amp_y = p.get('amp_y', 'Linear')
        x_auto = bool(p.get('x_auto', p.get('autoscale', True)))
        x_min = float(p.get('x_min', 0.0))
        x_max = float(p.get('x_max', 0.0))
        if x_auto:
            freq0 = entries[0]['freq']
            amp0 = entries[0]['amp']
            xlim = (0.0, self._fft_auto_xlim(freq0, amp0))
        elif x_max > x_min:
            xlim = (x_min, x_max)
        else:
            xlim = (0.0, self.inspector.fft_ctx.fs() / 2)
        canvas.plot_spectra(
            entries,
            xlim=xlim,
            amp_label='Amplitude (dB)' if amp_y == 'dB' else 'Amplitude',
            title=f'FFT · {len(entries)} 条曲线',
            y_auto=bool(p.get('y_auto', True)),
            y_min=float(p.get('y_min', 0.0)),
            y_max=float(p.get('y_max', 0.0)),
        )
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)

    def _render_cached_heatmap(self, section, canvas, result):
        """Render a cached heatmap result on ``canvas`` using the current
        section inspector's display options."""
        if section == 'fft_time':
            p = self.inspector.fft_time_ctx.get_params()
            self._render_fft_time_on(canvas, result, p)
        else:
            self._render_order_on(canvas, result)

    def _on_view_new(self):
        self._capture_current_view()
        self.view_manager.new_view()

    def _on_view_delete(self, idx):
        self._capture_current_view()
        self.view_manager.delete_view(idx)

    def _on_view_duplicate(self, idx):
        self._capture_current_view()
        self.view_manager.duplicate(idx)

    def _on_view_color(self, idx):
        if not (0 <= idx < len(self.view_manager.views)):
            return
        from PyQt5.QtGui import QColor

        current = QColor(self.view_manager.get(idx).tab_color)
        color = QColorDialog.getColor(current, self, "选择标签颜色")
        if color.isValid():
            self.view_manager.set_color(idx, color.name())
            if idx == self._focused_view_idx:
                self._sync_focus_accent()

    def _restore_view_axis_opts(self, axis_opts):
        axis_opts = axis_opts or {}
        top = self.inspector.top

        range_opts = axis_opts.get('range_filter') or {}
        range_enabled = bool(range_opts.get('enabled', False))
        range_start = range_opts.get('start', top.spin_start.value())
        range_end = range_opts.get('end', top.spin_end.value())
        old_chk = top.chk_range.blockSignals(True)
        try:
            top.chk_range.setChecked(range_enabled)
        finally:
            top.chk_range.blockSignals(old_chk)
        top.set_range_values(range_start, range_end)
        update_range_rows = getattr(top, '_update_range_rows_visible', None)
        if callable(update_range_rows):
            update_range_rows(range_enabled)

        x_opts = axis_opts.get('x_axis') or {}
        requested_mode = x_opts.get('mode') or 'time'
        label = x_opts.get('label') or ''
        target_fid = x_opts.get('fid')
        target_channel = x_opts.get('channel')

        use_channel = (
            requested_mode == 'channel'
            and target_fid is not None
            and target_channel is not None
        )
        if use_channel:
            self._refresh_xaxis_candidates()
            combo = top._combo_xaxis_ch
            match_idx = -1
            for i in range(combo.count()):
                if combo.itemData(i) == (target_fid, target_channel):
                    match_idx = i
                    break
            use_channel = match_idx >= 0

        old_mode = top.combo_xaxis.blockSignals(True)
        old_combo = top._combo_xaxis_ch.blockSignals(True)
        old_label = top.edit_xlabel.blockSignals(True)
        _le = top._combo_xaxis_ch.lineEdit()
        _old_le = _le.blockSignals(True) if _le is not None else False
        try:
            if use_channel:
                self._custom_xaxis_fid = target_fid
                self._custom_xaxis_ch = target_channel
                self._custom_xlabel = label or target_channel
                top.set_xaxis_mode('channel')
                top._combo_xaxis_ch.setEnabled(True)
                top._combo_xaxis_ch.setCurrentIndex(match_idx)
                top.edit_xlabel.setText(label or '')
            else:
                self._custom_xaxis_fid = None
                self._custom_xaxis_ch = None
                self._custom_xlabel = label or None
                top.set_xaxis_mode('time')
                top._combo_xaxis_ch.setEnabled(False)
                _safe_label = label if (label and label != 'Time (s)') else ''
                top.edit_xlabel.setText(_safe_label if requested_mode == 'time' else '')
        finally:
            top.edit_xlabel.blockSignals(old_label)
            top._combo_xaxis_ch.blockSignals(old_combo)
            top.combo_xaxis.blockSignals(old_mode)
            if _le is not None:
                _le.blockSignals(_old_le)
        update_xaxis_row = getattr(top, '_update_xaxis_channel_row_visible', None)
        if callable(update_xaxis_row):
            update_xaxis_row(top.combo_xaxis.currentIndex())

        tick_opts = axis_opts.get('tick_density') or {}
        xt = tick_opts.get('x', 10)
        yt = tick_opts.get('y', 6)
        self._set_tick_density_controls_silent(xt, yt)

    def _applied_xaxis_opts(self):
        custom_active = (
            self._custom_xaxis_fid is not None
            and self._custom_xaxis_ch is not None
        )
        if custom_active:
            return {
                "mode": "channel",
                "fid": self._custom_xaxis_fid,
                "channel": self._custom_xaxis_ch,
                "label": self._custom_xlabel or self._custom_xaxis_ch,
            }
        return {
            "mode": "time",
            "fid": None,
            "channel": None,
            "label": self._custom_xlabel or "",
        }

    def _capture_range_change_into_view(self, state, canvas):
        prev_axis_opts = state.axis_opts or {}
        prev_x_axis = prev_axis_opts.get('x_axis') or self._applied_xaxis_opts()
        self._view_bridge.capture_controls_into(state, self, canvas)
        axis_opts = dict(state.axis_opts or {})
        axis_opts['x_axis'] = prev_x_axis
        state.axis_opts = axis_opts

    def _snapshot_xaxis_controls(self):
        top = self.inspector.top
        return {
            "mode": top.xaxis_mode(),
            "channel_data": top._combo_xaxis_ch.currentData(),
            "label": top.xaxis_label(),
            "auto_label": getattr(top, "_xlabel_auto_from_channel", False),
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

    def _on_mode_changed(self, mode):
        old_mode = self.chart_stack.current_mode()
        if (
            old_mode != mode
            and not getattr(self, '_opening_project', False)
        ):
            if old_mode == 'time':
                self._capture_focused_view()
            elif old_mode in self.analysis_managers:
                self._capture_active_analysis_view(old_mode)
        self.chart_stack.set_mode(mode)
        self.inspector.set_mode(mode)
        self.toolbar.set_enabled_for_mode(mode, has_file=bool(self.files))
        # §6.2 auto re-plot on entering time mode with checked channels.
        # Defer by one tick: QStackedWidget has not yet laid out the newly
        # visible canvas, and drawing now paints onto a backing store that is
        # discarded when the layout pass fires (observed regression: plot
        # blanks after fft → time toggle).
        if mode == 'time' and self.files and self.navigator.get_checked_channels():
            QTimer.singleShot(0, self._plot_time_preserving_xlim)
        elif mode == 'fft' and self.files:
            QTimer.singleShot(0, self._enter_fft_mode)

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

    def _replot_secondary_preserving_xlim(self):
        """Replot the secondary (compare) canvas after its own plot-mode flip
        (P2 Task 9 1b), preserving that pane's visible X window.

        The secondary holds a compare-view snapshot; its 分屏/叠加 control only
        changes the LAYOUT of that pane, so we redraw the secondary canvas
        in-place (with ``update_primary_ui=False`` so the primary stats strip /
        bookkeeping stay untouched) and re-apply the secondary's X window. No
        secondary canvas (split inactive) → no-op. X preservation follows the
        TimeDomain state-preservation lesson: keep the visible window when the
        new layout's extent still overlaps it."""
        canvas = self.chart_stack.secondary_canvas()
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            state = self.view_manager.get(idx)
            self._view_bridge.capture_controls_into(state, self, canvas)
        self._replot_canvas_for_view(idx, canvas)

    def _replot_canvas_for_view(self, idx, canvas):
        if idx is None or canvas is None:
            return
        cur_xlim = self._safe_capture_xlim_for(canvas)
        try:
            self._render_view_to_canvas(
                idx,
                canvas,
                update_primary_ui=(canvas is self.canvas_time),
            )
        finally:
            if cur_xlim is not None:
                self._safe_restore_xlim_for(canvas, cur_xlim)
            self._capture_canvas_ranges_for_bound_view(canvas)

    def _on_primary_channel_requested(self, fid, ch):
        """User picked 设为左轴 on a channel. Make it the overlay primary
        (left-axis) channel and replot preserving the current x-window.

        Only meaningful in overlay mode; in subplot/single each channel has
        its own axis so there is no single "left" to assign. We still store
        the pick so it applies if the user later switches to overlay, but the
        replot only reorders when overlay is active (plot_time guards that).
        """
        self._overlay_primary = (fid, ch)
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
        # Skip restoration if the captured window has zero or
        # degenerate overlap with the new axis' autoscale window — that
        # means the underlying data extent is no longer compatible
        # (channel set changed, file closed, etc.). Use <= / >= so a
        # single tangent point (zero-length intersection) also falls
        # back to autoscale instead of locking onto a one-pixel slice.
        if new_hi <= cur_lo or new_lo >= cur_hi:
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

    def _on_time_canvas_xrange_changed(self, lo, hi):
        # In split mode: skip update when focus is on the secondary canvas so
        # the inspector shows the focused pane's range, not the primary's.
        if (self.chart_stack.split_active()
                and self.chart_stack.focused_canvas() is not self.canvas_time):
            return
        self._sync_time_range_inputs_from_visible_xlim((lo, hi))

    def _on_secondary_canvas_xrange_changed(self, lo, hi):
        if self.chart_stack.focused_canvas() is self.chart_stack.secondary_canvas():
            self._sync_time_range_inputs_from_visible_xlim((lo, hi))

    def _sync_time_range_inputs_from_visible_xlim(self, xlim=None):
        if getattr(self, '_applying_view', False):
            return False
        # Inspector range values are in acquisition time. If a custom channel
        # is the visible X axis, that viewport is in channel units and must not
        # overwrite the time-range controls.
        if self._custom_xaxis_fid is not None and self._custom_xaxis_ch is not None:
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
        if self.chart_stack.current_mode() != 'fft':
            return False
        page = self.chart_stack.page_fft
        if pane_idx != page.focused_index():
            return False
        if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
            return False
        self.inspector.top.set_range_from_span(lo, hi)
        return True

    def _on_time_range_enabled_changed(self, enabled):
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
        from .drawers.rebuild_time_popover import RebuildTimePopover
        pop = RebuildTimePopover(self, fd.filename, fd.fs)
        pop.show_at(anchor)
        if pop.exec_() == QDialog.Accepted:
            new_fs = pop.new_fs()
            old_max = fd.time_array[-1] if len(fd.time_array) else 0
            fd.rebuild_time_axis(new_fs)
            new_max = fd.time_array[-1] if len(fd.time_array) else 0
            current_hi = self.inspector.top.spin_end.maximum()
            self.inspector.top.set_range_limits(0, max(current_hi, new_max))
            # FFT vs Time cache: rebuilding the time axis changes both
            # ``time_range`` and the per-frame timing of cached
            # SpectrogramResults for this fid. Targeted clear so other
            # files' cached entries are preserved.
            self._fft_time_cache_clear_for_fid(target_fid)
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

    def _on_inspector_signal_changed(self, mode, data):
        """Fs auto-sync per §6.3: spin_fs reflects selected signal's source file Fs."""
        if not data:
            return
        fid, _ch = data
        if fid not in self.files:
            return
        fs = self.files[fid].fs
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
        ``fft_time_ctx`` route. Reviewer Important #2 hand-off."""
        if not data:
            return
        fid, _ch = data
        if fid not in self.files:
            return
        self.inspector.fft_time_ctx.set_fs(self.files[fid].fs)

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

    def _on_file_close_requested(self, fid):
        self._close(fid)

    def _on_close_all_requested(self):
        # Navigator already confirmed; skip the second confirm here.
        # FFT vs Time cache wipe is also performed inside ``close_all``;
        # mirroring it here keeps the invariant local to the dispatcher
        # so future refactors that bypass ``close_all`` (e.g. a partial
        # close-all flow) still tear the cache down.
        self._fft_time_cache.clear()
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
        cands = []
        for fid, fd in self.files.items():
            px = f"[{fd.short_name}] "
            for ch in fd.channels:
                cands.append((px + ch, (fid, ch)))
        return cands

    def _refresh_xaxis_candidates(self):
        self.inspector.top.set_xaxis_candidates(self._build_xaxis_candidates())

    def _validate_custom_xaxis_source(self):
        if self._custom_xaxis_fid is None or self._custom_xaxis_ch is None:
            return
        fd = self.files.get(self._custom_xaxis_fid)
        if fd is not None and self._custom_xaxis_ch in fd.data.columns:
            return
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        self._custom_xlabel = None
        self.inspector.top.set_xaxis_mode('time')

    def _refresh_channel_dependent_controls(self):
        self._validate_custom_xaxis_source()
        self._update_combos()
        if self.inspector.top.xaxis_mode() == 'channel':
            self._refresh_xaxis_candidates()

    def _apply_xaxis(self):
        """应用横坐标设置"""
        canvas = self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(canvas)
        mode = self.inspector.top.xaxis_mode()
        if mode == 'time':
            self._custom_xlabel = self.inspector.top.xaxis_label() or None
            self._custom_xaxis_fid = None
            self._custom_xaxis_ch = None
        else:
            data = self.inspector.top.xaxis_channel_data()
            if not data:
                self.toast("请选择横坐标通道", "warning")
                return
            fid, ch = data
            if fid not in self.files or ch not in self.files[fid].data.columns:
                self.toast("横坐标通道不存在", "warning")
                return
            # §6.1 validation: length must match every file whose channels are
            # currently checked for plotting (not every loaded file).
            xlen = len(self.files[fid].data)
            checked = self.navigator.get_checked_channels()  # [(fid, ch, color), ...]
            plotted_fids = {cfid for cfid, _, _ in checked}
            if not plotted_fids:
                plotted_fids = {fid}
            for cfid in plotted_fids:
                if cfid in self.files and len(self.files[cfid].data) != xlen:
                    self.toast("横坐标通道长度与当前绘图通道不一致", "warning")
                    return
            self._custom_xaxis_fid = fid
            self._custom_xaxis_ch = ch
            _raw = self.inspector.top.xaxis_label()
            self._custom_xlabel = (_raw if _raw and _raw != 'Time (s)' else None) or ch

        # Cache invalidation site 5: the t-array bound to every plotted
        # channel just changed (time-axis ↔ custom-channel x-axis), so
        # every (data_id, channel, xlim, pixel_width) entry is now stale.
        # Monotonicity cache is also re-keyed by the new fid/ch pair, so
        # wipe it to be safe.
        invalidate_envelope = getattr(canvas, 'invalidate_envelope_cache', None)
        if callable(invalidate_envelope):
            invalidate_envelope("custom-x changed")
        invalidate_mono = getattr(canvas, 'invalidate_monotonicity_cache', None)
        if callable(invalidate_mono):
            invalidate_mono()
        # FFT vs Time cache: keep the existing conservative invalidation
        # when the shared top controls change plot semantics. Time range
        # itself remains tied to FileData.time_array.
        self._fft_time_cache.clear()
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self._view_bridge.capture_controls_into(
                self.view_manager.get(idx), self, canvas
            )
        if self.files and self.chart_stack.current_mode() == 'time':
            self._replot_canvas_for_view(idx, canvas)
        else:
            self.plot_time()
        self.statusBar.showMessage(f"横坐标已更新")
        if not self._hint_focused_pane("坐标设置"):
            self.toast("横坐标已更新", "success")

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
            self.canvas_time._refresh = True
            self.canvas_time.draw_idle()
        self.chart_stack.clear_cursor_pill()
        self.statusBar.showMessage("游标已重置")
        self.toast("游标已重置", "info")

    def open_files_or_project(self):
        """统一打开入口：文件对话框同时接受数据文件和 .tlproj。
        数据文件追加；单个项目替换（有文件时先确认）；项目+文件先开项目再追加；≥2个项目拒绝。"""
        from pathlib import Path
        fps, _ = QFileDialog.getOpenFileNames(
            self, "打开", "",
            "所有支持的文件 (*.mf4 *.mdf *.csv *.xlsx *.xls *.tlproj);;"
            "项目 (*.tlproj);;数据文件 (*.mf4 *.mdf *.csv *.xlsx *.xls)",
        )
        if not fps:
            return
        projects = [p for p in fps if Path(p).suffix.lower() == ".tlproj"]
        data_files = [p for p in fps if Path(p).suffix.lower() != ".tlproj"]

        if len(projects) >= 2:
            QMessageBox.warning(self, "无法打开", "一次只能打开一个项目（.tlproj）。")
            return

        if projects:
            if self.files:
                resp = QMessageBox.question(
                    self, "打开项目",
                    f"打开项目将关闭当前 {len(self.files)} 个文件，是否继续？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    return
            self.open_project(projects[0])
            for fp in data_files:
                self._load_one(fp)
            return

        for fp in data_files:
            self._load_one(fp)

    def save_project_via_dialog(self):
        """保存项目 handler: overwrite the current .tlproj if one is open,
        otherwise prompt Save-As."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog
        if self._project_path is not None:
            self.save_project(self._project_path)
            return
        fp, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "TraceLab 项目 (*.tlproj)")
        if not fp:
            return
        if not fp.lower().endswith(".tlproj"):
            fp = fp + ".tlproj"
        self.save_project(Path(fp))

    def load_files(self):
        fps, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "All (*.mf4 *.mdf *.csv *.xlsx *.xls)")
        for fp in fps: self._load_one(fp)

    def load_file(self, path) -> None:
        """Public Analyzer handoff for single-file loads.

        Stage 5 of the Acquisition Cockpit plan
        (``docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md``)
        wires Cockpit's review modal to this method. Spec §Architecture
        Contract / Analyzer Handoff pins the contract:

        - Public method, accepts ``str | Path``.
        - Thin wrapper around the existing private ``_load_one(fp)`` flow.
        - Cockpit MUST NOT call ``_load_one`` directly.

        This is the only Analyzer-side modification authorized by the
        plan; ``_load_one``'s body stays unchanged.
        """
        self._load_one(str(path))

    def open_acquisition_cockpit(self) -> None:
        cockpit_module = importlib.import_module(
            "mf4_analyzer.acquisition_ui.main_window"
        )
        CockpitMainWindow = cockpit_module.CockpitMainWindow

        for window in QApplication.topLevelWidgets():
            if isinstance(window, CockpitMainWindow):
                if not window.isVisible():
                    window.show()
                window.raise_()
                window.activateWindow()
                return

        cockpit = CockpitMainWindow()
        self._acquisition_cockpit_window = cockpit
        cockpit.show()

    def _load_one(self, fp):
        try:
            self.statusBar.showMessage(f"加载: {fp}");
            QApplication.processEvents()
            p = Path(fp);
            ext = p.suffix.lower()
            if ext in ('.mf4', '.mdf'):
                if not HAS_ASAMMDF: QMessageBox.critical(self, "错误", "asammdf 未安装"); return
                data, chs, units = DataLoader.load_mf4(fp)
            elif ext in ('.xlsx', '.xls'):
                data, chs, units = DataLoader.load_excel(fp)
            else:
                data, chs, units = DataLoader.load_csv(fp)
            fid = f"f{self._fc}";
            self._fc += 1
            fd = FileData(fp, data, chs, units, len(self.files));
            self.files[fid] = fd
            self.navigator.add_file(fid, fd)
            # Cache invalidation site 1: a new file's data_id is now in
            # play. Drop everything — channel selections will redraw.
            self.canvas_time.invalidate_envelope_cache("file loaded")
            self.canvas_time.invalidate_monotonicity_cache()
            # FFT vs Time cache: scrub any stale entries that share this
            # freshly minted fid (defensive; fid is monotonic per-session
            # but the helper is cheap and keeps the invariant tight).
            self._fft_time_cache_clear_for_fid(fid)
            self._refresh_channel_dependent_controls()
            if fd.time_array is not None and len(fd.time_array):
                current_hi = self.inspector.top.spin_end.maximum()
                new_hi = max(current_hi, fd.time_array[-1])
                self.inspector.top.set_range_limits(0, new_hi)
                if len(self.files) == 1:
                    self.inspector.top.spin_end.setValue(fd.time_array[-1])
            # User-request 2026-05-20: do NOT auto-select channel[0] on file
            # load. The canvas opens empty; the user picks the channel(s)
            # they want explicitly. Any previously-checked channels on
            # *other* loaded files remain checked and visible — their fids
            # are unaffected by the freshly minted ``fid`` above.
            self._update_info()
            self.statusBar.showMessage(f"✅ 已加载: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
            self.toast(f"已加载 {p.name} · {len(data)} 行", "success")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _close(self, fid):
        if fid not in self.files: return
        name = self.files[fid].short_name
        # Cache invalidation site 2: drop entries for this file before
        # we discard the FileData — capture fid so the per-data_id filter
        # can match. Same for the monotonicity cache (custom-x source
        # may also be this file).
        self.canvas_time.invalidate_envelope_cache(
            "file closed", data_id=fid
        )
        self.canvas_time.invalidate_monotonicity_cache(custom_xaxis_fid=fid)
        # FFT vs Time cache: per-file targeted clear — the source ndarray
        # is about to be released, so any cached SpectrogramResult keyed
        # under this fid is now strictly stale.
        self._fft_time_cache_clear_for_fid(fid)
        # Per-section analysis caches (V7) are keyed on (fid, ch, params).
        # _fft_time_cache and analysis_caches['fft_time'] are double-written
        # on compute, so both must be torn down for this fid here — otherwise
        # reopening a file that reuses the same fid would hit a stale result.
        for cache in self.analysis_caches.values():
            cache.invalidate_fid(fid)
        del self.files[fid]
        self.navigator.remove_file(fid)
        self._active = self.navigator._active_fid  # navigator picks fallback
        self._update_info()
        self._reset_plot_state(scope='file')
        self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")
        self.toast(f"已关闭 {name}", "info")

    def save_project(self, path):
        """Serialize the current session (open files + all Views) to a
        reference-only ``.tlproj`` JSON file. No UI entry point yet — this is
        the callable used by tests and a future menu/button."""
        from pathlib import Path
        from . import project_io as pio
        path = Path(path)

        self._capture_focused_view()
        # Flush each analysis section's live UI state into its active view so
        # the last (uncommitted) inspector edit / source / compare toggle is
        # serialized rather than lost.
        current_mode = self.chart_stack.current_mode()
        for sec in self.analysis_managers:
            self._capture_active_analysis_view(
                sec, capture_sources=(sec == current_mode))

        file_refs = []
        for fid, fd in self.files.items():
            abs_p = str(Path(fd.filepath).resolve())
            file_refs.append(pio.ProjectFileRef(
                fid=fid,
                path_abs=abs_p,
                path_rel=pio.make_relative(abs_p, path),
                fs=float(fd.fs),
                time_source=fd._time_source,
            ))

        vm = {
            "active": int(self.view_manager.active),
            "split_pairs": {
                str(host): int(src)
                for host, src in self.view_manager._split_pairs.items()
            },
        }
        doc = pio.ProjectDocument(
            active_file=self._active,
            current_mode=self.chart_stack.current_mode(),
            files=file_refs,
            views=[v.to_dict() for v in self.view_manager.views],
            view_manager=vm,
            analysis_views={
                sec: {
                    "active": mgr.active,
                    "views": [v.to_dict() for v in mgr.views],
                }
                for sec, mgr in self.analysis_managers.items()
            },
        )
        pio.save_project_to_json(doc, path)
        self._project_path = path
        self.statusBar.showMessage(f"已保存项目: {path.name}")

    def open_project(self, path):
        """Restore a session from a ``.tlproj`` file: re-read referenced source
        files (skipping missing ones), reinstall saved Views with fids remapped
        to freshly minted ids, and select the saved active file / mode."""
        from pathlib import Path
        from PyQt5.QtWidgets import QMessageBox
        from . import project_io as pio
        from .view_state import ViewState
        path = Path(path)

        doc = pio.load_project_from_json(path)
        self.close_all()
        # Fresh restore: clear any stale auto-recompute queue from a prior open.
        self._analysis_restore_pending = set()

        fid_map = {}
        missing = []
        for ref in doc.files:
            resolved = pio.resolve_file_path(ref, path)
            if resolved is None:
                missing.append(ref.path_abs)
                continue
            before = len(self.files)
            self._load_one(str(resolved))
            if len(self.files) <= before:
                missing.append(ref.path_abs)
                continue
            new_fid = next(reversed(self.files))
            fid_map[ref.fid] = new_fid
            fd = self.files[new_fid]
            fd.fs = float(ref.fs)
            if ref.time_source in ("generated", "manual"):
                fd.rebuild_time_axis(float(ref.fs))

        remapped = pio.remap_view_fids(doc.views, fid_map)
        states = [ViewState.from_dict(v) for v in remapped]
        if not states:
            states = [self.view_manager._make(0)]
        self.view_manager.views = states
        self.view_manager._split_pairs = {
            int(host): int(src)
            for host, src in (doc.view_manager.get("split_pairs") or {}).items()
            if 0 <= int(host) < len(states) and 0 <= int(src) < len(states)
        }
        active_idx = int(doc.view_manager.get("active", 0))
        self.view_manager.active = max(0, min(active_idx, len(states) - 1))
        self.view_manager._set_active_split_from_pairs()
        self.view_manager.views_changed.emit()

        # Restore each analysis section's view list (fids remapped to the
        # freshly minted ids). An old project without analysis_views yields an
        # empty remapped dict -> every section keeps its default single view.
        from .project_io import remap_analysis_view_fids
        from .analysis_view_state import AnalysisViewState
        remapped = remap_analysis_view_fids(doc.analysis_views, fid_map)
        for sec, mgr in self.analysis_managers.items():
            block = remapped.get(sec)
            if not block or not block.get("views"):
                continue
            mgr.views = [AnalysisViewState.from_dict(v) for v in block["views"]]
            mgr.active = min(int(block.get("active", 0)), len(mgr.views) - 1)
            # Queue every source-bearing view for auto-recompute (recompute-on-
            # open): the project stored params + sources but not the numeric
            # results. The active view recomputes immediately via the emit
            # below; the rest recompute lazily the first time they're shown.
            for i, v in enumerate(mgr.views):
                if any(p.sources for p in v.panes):
                    self._analysis_restore_pending.add((sec, i))
            mgr.views_changed.emit()
            # active_changed drives _on_analysis_view_switched: it applies the
            # restored structure/params/sources, then _render_analysis_view_from
            # _cache recomputes this view (queued above) so the chart repopulates.
            mgr.active_changed.emit(mgr.active)

        self._active = fid_map.get(doc.active_file)
        # Route the mode through the toolbar's programmatic setter (not
        # chart_stack.set_mode directly): _set_mode checks the matching
        # segment button AND emits mode_changed -> _on_mode_changed, which
        # syncs chart_stack + inspector + toolbar enabled-state together.
        # Calling chart_stack.set_mode alone leaves the toolbar segment and
        # the inspector panel stuck on the previous mode (desync on reopen of
        # a project saved in FFT / Order / FFT-vs-Time).
        self._opening_project = True
        try:
            self.toolbar._set_mode(doc.current_mode)
        finally:
            self._opening_project = False

        if missing:
            QMessageBox.warning(
                self, "部分文件缺失",
                "以下文件找不到，已跳过：\n" + "\n".join(missing),
            )

        # The project's files/views are loaded by this point, so the document
        # is "open" regardless of whether the final view render succeeds —
        # record the path BEFORE the render guard so a render hiccup doesn't
        # leave 保存项目 prompting Save-As for an already-open project.
        self._project_path = path

        try:
            self._apply_active_view(self.view_manager.active)
        except Exception:
            self.statusBar.showMessage(f"已打开项目: {path.name}（渲染恢复失败）")
            return

        self.statusBar.showMessage(f"已打开项目: {path.name}")

    def close_all(self):
        if not self.files:
            return
        n = len(self.files)
        # Cache invalidation site 2 (close-all variant): wipe everything.
        self.canvas_time.invalidate_envelope_cache("all files closed")
        self.canvas_time.invalidate_monotonicity_cache()
        # FFT vs Time cache: every entry is keyed against a now-dead fid.
        self._fft_time_cache.clear()
        # Per-section analysis caches: every entry is now stale (close-all
        # variant of the per-fid invalidate in ``_close``).
        for cache in self.analysis_caches.values():
            cache.clear()
        for fid in list(self.files.keys()):
            del self.files[fid]
            self.navigator.remove_file(fid)
        self._active = None
        self._update_info()
        self._reset_plot_state(scope='all')
        self.statusBar.showMessage("已关闭全部")
        self.toast(f"已关闭全部 {n} 个文件", "info")

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

    def _update_combos(self):
        sig_cands = []
        rpm_cands = []
        for fid, fd in self.files.items():
            px = f"[{fd.short_name}] "
            for ch in fd.get_signal_channels():
                sig_cands.append((px + ch, (fid, ch)))
                rpm_cands.append((px + ch, (fid, ch)))
        self.inspector.fft_ctx.set_signal_candidates(sig_cands)
        self.inspector.fft_time_ctx.set_signal_candidates(sig_cands)
        self.inspector.order_ctx.set_signal_candidates(sig_cands)
        self.inspector.order_ctx.set_rpm_candidates(rpm_cands)
        self._sync_fft_source_summary()

    def _on_chart_focus_changed(self, secondary_focused):
        if not self.chart_stack.split_active():
            return
        self._capture_focused_view()
        self.view_tabbar.set_split_focus(secondary_focused)
        if secondary_focused:
            self._focused_view_idx = self._secondary_view_idx
            which = "对比"
        else:
            self._focused_view_idx = self._primary_view_idx
            which = "主"
        if self._focused_view_idx is not None:
            self._sync_focus_accent()
            self._project_view_controls(self._focused_view_idx)
        self.statusBar.showMessage(f"聚焦{which}视图：通道勾选将作用于此栏", 2000)

    def _ch_changed(self):
        # Cache invalidation site 4: the visible channel set changed, so
        # the Line2D map plot_channels rebuilds will not match the cache
        # entries from the prior selection. Drop the focused canvas's cache;
        # the next plot_time() will re-prime as needed. (Outside split the
        # focused canvas IS self.canvas_time, so this is unchanged.)
        focused = self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(focused)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self._view_bridge.capture_controls_into(
                self.view_manager.get(idx), self, focused
            )
        invalidate = getattr(focused, 'invalidate_envelope_cache', None)
        if callable(invalidate):
            invalidate("selection changed")
        if self.chart_stack.current_mode() == 'fft':
            self._sync_fft_source_summary()
            # Channel-checkbox selection changed: keep the already-computed
            # spectrum on screen but mark it stale (dim + "结果已过期" marker).
            # Do NOT auto-recompute — the user re-clicks 计算 to refresh.
            self._refresh_fft_time_preview(clear_spectrum=False)
        if self.files and self.chart_stack.current_mode() == 'time':
            self._replot_canvas_for_view(idx, focused)

    def _restore_checked_channels(self, checked):
        self.channel_list.set_checked_channels(checked)

    def plot_time(self):
        # Route channel-check replots to the focused time card. Outside
        # side-by-side compare, focused_canvas() is the primary self.canvas_time
        # so this is byte-identical to the old behaviour; while split is active
        # and the secondary card is focused, the replot lands on the secondary
        # canvas instead. update_primary_ui stays gated on whether the focused
        # canvas IS the primary, so the stats strip / status bar / cache
        # bookkeeping only fire for the primary pane.
        focused = self.chart_stack.focused_canvas()
        self._plot_time_on_canvas(
            focused, update_primary_ui=(focused is self.canvas_time)
        )

    def _plot_time_on_canvas(self, canvas, update_primary_ui=True, defer_first_frame=False):
        if not self.files:
            canvas.clear()
            canvas.draw()
            if update_primary_ui:
                self.chart_stack.stats_strip.update_stats({})
            return
        checked = self.channel_list.get_checked_channels()
        if not checked:
            canvas.clear()
            canvas.draw()
            if update_primary_ui:
                self.chart_stack.stats_strip.update_stats({})
            return

        # Per-pane plot mode (P2 Task 9 1b): read the layout (subplot/overlay)
        # from the card that owns the TARGET canvas, not always the primary.
        # Outside split this resolves to the primary card's mode, so the
        # non-split path is byte-identical.
        mode = self.chart_stack.plot_mode_for_canvas(canvas)
        if not update_primary_ui:
            invalidate = getattr(canvas, 'invalidate_envelope_cache', None)
            if callable(invalidate):
                invalidate("compare view changed")
        # Overlay primary-axis pick (设为左轴): when the chosen (fid, ch) is
        # still checked AND we're in overlay mode, move it to index 0 so the
        # canvas binds it to the LEFT axis (vis[0] → left). If it is no longer
        # checked, drop the stale pick so a hidden channel is never forced
        # onto the left axis. Outside overlay mode the pick is inert (each
        # channel owns its own axis), but we keep it stored for a later toggle.
        if self._overlay_primary is not None:
            pfid, pch = self._overlay_primary
            primary_idx = next(
                (i for i, (cfid, cch, _color) in enumerate(checked)
                 if cfid == pfid and cch == pch),
                None,
            )
            if primary_idx is None:
                self._overlay_primary = None
            elif mode == 'overlay' and primary_idx != 0:
                checked.insert(0, checked.pop(primary_idx))
        # Cache invalidation site 7: structural plot-mode change (overlay
        # ↔ subplot) reuses the same (data_id, channel) keys but the line
        # ownership switches between an axes-stack and a single ax with
        # twinx siblings. To keep cached envelopes from rendering on the
        # wrong axes, drop them when the layout changes.
        if update_primary_ui:
            if self._last_plot_mode is not None and self._last_plot_mode != mode:
                canvas.invalidate_envelope_cache("plot mode changed")
            self._last_plot_mode = mode
        if update_primary_ui and mode == 'overlay' and len(checked) > 5:
            ans = QMessageBox.question(
                self, "确认",
                f"overlay 下 {len(checked)} 个通道会产生 {len(checked)} 根 Y 轴，右侧可能拥挤。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        # 获取自定义横坐标数据。
        # Phase 1 item 3: avoid `.values.copy()` — `to_numpy(copy=False)`
        # returns the underlying buffer when pandas can; for object /
        # extension dtypes it may still copy, which is acceptable.
        # Consumers (TimeDomainCanvas, statistics) treat these arrays as
        # read-only. The downstream range-filter mask makes a fresh
        # array via fancy indexing, so no caller mutates `custom_x`.
        custom_x = None
        if self._custom_xaxis_fid and self._custom_xaxis_ch:
            if self._custom_xaxis_fid in self.files:
                xfd = self.files[self._custom_xaxis_fid]
                if self._custom_xaxis_ch in xfd.data.columns:
                    custom_x = xfd.data[self._custom_xaxis_ch].to_numpy(copy=False)

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

        from .chart_stack import _STATS_STRIP_ENABLED
        collect_stats = update_primary_ui and _STATS_STRIP_ENABLED

        data = [];
        st = {}
        for fid, ch, color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns: continue

            time_axis = fd.time_array
            # 使用自定义横坐标或默认时间轴 — by reference; the canvas
            # treats these arrays as read-only.
            if custom_x is not None and len(custom_x) == len(fd.data):
                x_axis = custom_x
            else:
                x_axis = time_axis

            sig = fd.data[ch].to_numpy(copy=False)
            unit = fd.channel_units.get(ch, '');
            name = fd.get_prefixed_channel(ch)
            # Only allocate filtered arrays when the user actually asked
            # for range filtering. The range controls are always in
            # acquisition time, even when the visible X axis is a channel.
            if range_enabled:
                m = (time_axis >= range_lo) & (time_axis <= range_hi)
                x_axis, sig = x_axis[m], sig[m]
            if len(sig) == 0: continue
            # Statistics are computed from the (post-range-filter)
            # original samples — never from envelope output.
            data.append((name, True, x_axis, sig, color, unit, fid))
            if collect_stats:
                st[name] = {'min': np.min(sig), 'max': np.max(sig), 'mean': np.mean(sig), 'rms': np.sqrt(np.mean(sig ** 2)),
                            'std': np.std(sig), 'p2p': np.ptp(sig), 'unit': unit}
        if not data:
            canvas.clear()
            canvas.draw()
            if update_primary_ui:
                self.chart_stack.stats_strip.update_stats({})
            return

        xlabel = self._custom_xlabel or self.inspector.top.xaxis_label() or 'Time (s)'
        canvas.plot_channels(
            data,
            mode,
            xlabel=xlabel,
            defer_first_frame=defer_first_frame,
        )
        if update_primary_ui:
            self._sync_time_range_inputs_from_visible_xlim()
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)
        # SpanSelector intentionally not enabled — drag-to-select on the
        # chart face was retired (2026-05-27) to prevent accidental triggers.
        # If you need a per-range export tool, re-enable explicitly behind a
        # toolbar button rather than always-on.
        if update_primary_ui:
            if collect_stats:
                self.chart_stack.stats_strip.update_stats(st);
            self.statusBar.showMessage(f"绘制: {len(checked)} 通道, {len(set(fid for fid, _, _ in checked))} 文件")

    def open_editor(self):
        if not self.files or not self._active or self._active not in self.files:
            self.toast("请先加载文件", "warning")
            return
        from .drawers.channel_editor_drawer import ChannelEditorDrawer
        # Pass ALL loaded files so the user can switch the edit target inside
        # the drawer. The applied(fid, ...) signal reports whichever file the
        # user actually had selected, so we no longer assume self._active.
        drawer = ChannelEditorDrawer(self, self.files, self._active)
        drawer.applied.connect(self._apply_channel_edits)
        drawer.export_requested.connect(self._do_export_excel)
        drawer.exec_()


    def _apply_channel_edits(self, fid, new_channels, removed_channels):
        fd = self.files[fid]
        checked_before = {
            (cfid, ch)
            for cfid, ch, _color in self.channel_list.get_checked_channels()
        }
        # Cache invalidation site 3: each touched channel's underlying
        # ndarray identity may have changed (added) or vanished (removed).
        # `fd.get_prefixed_channel(...)` is what plot_channels stashes
        # under self.channel_data, so use that as the cache key.
        # FFT vs Time cache: any cached SpectrogramResult keyed under
        # this fid was computed against pre-edit columns; targeted clear.
        self._fft_time_cache_clear_for_fid(fid)
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
        nav_blocked = self.navigator.blockSignals(True)
        list_blocked = self.channel_list.blockSignals(True)
        try:
            self.navigator.remove_file(fid)
            self.navigator.add_file(fid, fd)
        finally:
            self.channel_list.blockSignals(list_blocked)
            self.navigator.blockSignals(nav_blocked)
        self._restore_checked_channels(checked_before)
        self._refresh_channel_dependent_controls()
        self.statusBar.showMessage(
            f"编辑: +{len(new_channels)} -{len(removed_channels)}"
        )
        self.toast(
            f"通道已更新: 新增 {len(new_channels)} · 删除 {len(removed_channels)}",
            "success",
        )
        self._plot_time_preserving_xlim()

    def _do_export_excel(self, fid, channels, include_time, use_range):
        """Write the given channels of file ``fid`` to an Excel file. Invoked
        by the channel-editor's 导出 section (export_requested). Time column and
        time-range filter mirror the former toolbar-export behavior."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        import pandas as pd
        fd = self.files.get(fid)
        if fd is None or not channels:
            return
        fp, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "", "Excel (*.xlsx)")
        if not fp:
            return
        try:
            df = pd.DataFrame()
            if include_time and fd.time_array is not None:
                df['Time'] = fd.time_array
            for ch in channels:
                if ch in fd.data.columns:
                    df[ch] = fd.data[ch].values
            if use_range and fd.time_array is not None:
                lo, hi = self.inspector.top.range_values()
                m = (fd.time_array >= lo) & (fd.time_array <= hi)
                df = df.loc[m].reset_index(drop=True)
            df.to_excel(fp, index=False, engine='openpyxl')
            self.statusBar.showMessage(
                f"导出完成: {Path(fp).name} ({len(df)} 行 × {len(df.columns)} 列)"
            )
            self.toast(
                f"已导出 {Path(fp).name} · {len(df)} 行 × {len(df.columns)} 列",
                "success",
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def open_batch(self):
        from .drawers.batch import BatchSheet
        from ..batch import BatchRunner

        current_preset = self._last_batch_preset or self._build_current_batch_preset()
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
        dlg = BatchSheet(self, self.files, current_preset=current_preset)
        if dlg.exec_() != QDialog.Accepted:
            return
        preset = dlg.get_preset()
        output_dir = dlg.output_dir()
        if not output_dir:
            self.toast("请选择输出目录", "warning")
            return
        try:
            self.statusBar.showMessage("批处理运行中...")
            QApplication.processEvents()
            result = BatchRunner(self.files).run(preset, output_dir)
        except Exception as e:
            QMessageBox.critical(self, "批处理错误", str(e))
            return
        done = sum(1 for item in result.items if item.status == 'done')
        if result.status == 'done':
            msg = f"批处理完成 · {done} 项"
            self.toast(msg, "success")
        elif result.status == 'partial':
            msg = f"批处理部分完成 · {done}/{len(result.items)} 项"
            self.toast(msg, "warning")
        else:
            msg = "批处理未执行"
            self.toast(msg, "warning")
        self.statusBar.showMessage(f"{msg} · {output_dir}")
        if result.blocked:
            QMessageBox.warning(self, "批处理提示", "\n".join(result.blocked[:8]))

    def _build_current_batch_preset(self):
        from ..batch import AnalysisPreset

        mode = self.toolbar.current_mode()
        if mode == 'fft':
            signal = self.inspector.fft_ctx.current_signal()
            if signal is None:
                return None
            params = self.inspector.fft_ctx.get_params()
            params['fs'] = self.inspector.fft_ctx.fs()
            if self.inspector.top.range_enabled():
                params['time_range'] = self.inspector.top.range_values()
            return AnalysisPreset.from_current_single(
                name="当前 FFT",
                method="fft",
                signal=signal,
                params=params,
            )
        if mode == 'order':
            signal = self.inspector.order_ctx.current_signal()
            rpm_signal = self.inspector.order_ctx.current_rpm()
            if signal is None:
                return None
            params = self.inspector.order_ctx.get_params()
            params['fs'] = self.inspector.order_ctx.fs()
            params['rpm_factor'] = self.inspector.order_ctx.rpm_factor()
            if self.inspector.top.range_enabled():
                params['time_range'] = self.inspector.top.range_values()
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
        from ..batch import AnalysisPreset

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
        """自适应计算 FFT 频率范围。

        策略：忽略 DC 分量，找到「最高的有意义峰位」——即幅值仍达到全频段
        峰值 1% 以上的最高频率点；再取 1.3x 余量并向上取整到
        1/2/5/10/20/50/100… 美观刻度。该算法相比单纯的累计能量法对
        包含直流偏置或低频主导分量的信号更鲁棒。
        """
        if len(freq) < 2 or len(amp) < 2:
            return freq[-1] if len(freq) else 100

        amp = np.asarray(amp, dtype=float)
        # 跳过 DC：从 index 1 起；若分辨率极低也至少保留 1 个点
        body = amp[1:] if len(amp) > 1 else amp
        peak = float(np.max(body)) if len(body) else 0.0
        if peak <= 0 or not np.isfinite(peak):
            return freq[-1]

        # 「最高有意义谱线」：amp >= 1% 峰值的最大频率索引（含 DC 偏移 +1）
        threshold = peak * 0.01
        meaningful = np.where(body >= threshold)[0]
        if len(meaningful) == 0:
            return freq[-1]
        idx = int(meaningful[-1]) + 1
        f_cutoff = float(freq[min(idx, len(freq) - 1)])
        # 再加 1.3x 余量，避免恰好压在最右一根谱线上
        f_cutoff *= 1.3
        # 与最大可达频率取小，防止超过 Nyquist
        f_cutoff = min(f_cutoff, float(freq[-1]))

        nice_vals = []
        for exp in range(-1, 7):
            for m in [1, 2, 5]:
                nice_vals.append(m * 10 ** exp)
        nice_vals.sort()
        for nv in nice_vals:
            if nv >= f_cutoff:
                return nv
        return freq[-1]

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
            self._fft_time_cache_clear_for_fid(target_fid)
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

    def _fft_compute_arrays(self, sig, fs, fft_params):
        """Run the FFT compute branch (Welch avg / peak-hold / single-frame)
        on a single signal, returning raw display-independent ``(freq, amp,
        psd)``. Algorithm calls are byte-identical to the legacy do_fft."""
        win = fft_params['window']
        nfft = fft_params['nfft']
        avg_mode = fft_params.get('avg_mode', '单帧')
        overlap_pct = int(fft_params.get('avg_overlap', 50))
        avg_overlap = max(0.0, min(0.95, overlap_pct / 100.0))
        if avg_mode == '线性平均':
            freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win, nfft or 1024, avg_overlap)
        elif avg_mode == '峰值保持':
            freq, amp = FFTAnalyzer.compute_peak_hold_fft(
                sig, fs, win=win, nfft=nfft or 1024, overlap=avg_overlap)
            psd = amp ** 2
        else:
            freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
            _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft)
        return freq, amp, psd

    def _fft_fetch_signal(self, fid, ch):
        """Fetch + range-gate a single FFT source's signal. Returns
        ``(sig, fs)`` or ``(None, None)`` when unavailable."""
        fd = self.files.get(fid)
        if fd is None or ch not in fd.data.columns:
            return None, None
        sig = fd.data[ch].values
        t = fd.time_array
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            sig = sig[m]
        return sig, fd.fs

    def do_fft(self):
        """Compute the ACTIVE FFT view: every source of every pane.

        Compute semantics (spec §4): the button computes the whole active
        view. Each pane overlays N curves (its sources); each source is cached
        on a (fid, ch, compute-params) key so re-render / view-switch is free.

        Back-compat: when the focused pane has no navigator-checked sources
        (or they are not fetchable), fall back to the legacy single-signal
        ``_get_sig()`` path so the existing single-signal UX + tests are
        unchanged.
        """
        self._capture_active_analysis_view('fft')
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        page = self.chart_stack.page_fft
        fft_params = self.inspector.fft_ctx.current_params()
        cache = self.analysis_caches['fft']
        colors = self._analysis_channel_color_map()

        any_rendered = False
        any_multi = False
        for pane_idx in range(page.pane_count()):
            if pane_idx >= len(state.panes):
                break
            sources = state.panes[pane_idx].sources
            if not sources:
                continue
            any_multi = True
            entries = []
            for fid, ch in sources:
                key = self._analysis_cache_key('fft', fid, ch)
                result = cache.get(key)
                if result is None:
                    sig, fs = self._fft_fetch_signal(fid, ch)
                    if sig is None or len(sig) < 10:
                        continue
                    fd = self.files.get(fid)
                    if not self._check_uniform_or_prompt(fd, 'fft'):
                        continue
                    sig, fs = self._fft_fetch_signal(fid, ch)
                    if sig is None or len(sig) < 10:
                        continue
                    try:
                        result = self._fft_compute_arrays(
                            sig, self.inspector.fft_ctx.fs(), fft_params)
                    except Exception as e:
                        QMessageBox.critical(self, 'FFT错误', str(e))
                        continue
                    cache.put(key, result)
                entries.append(self._fft_entry_from_cache(
                    result, fid, ch, colors.get((fid, ch))))
            if entries:
                self._plot_fft_entries(entries, page.pane_canvas(pane_idx))
                any_rendered = True

        if any_multi:
            if any_rendered:
                self.statusBar.showMessage('FFT 完成')
                self.toast('FFT 完成', 'success')
            return
        # ---- legacy single-signal fallback (no navigator-checked sources) ----
        self._do_fft_single()

    def _do_fft_single(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10:
            self.toast("请选择有效信号", "warning"); return
        # Pre-flight: route non-uniform axes through the rebuild popover
        # BEFORE running the FFT. ``compute_fft`` itself does not consume
        # ``t`` (it samples by index + fs), so the FFT path used to
        # silently produce garbage from a jittered axis -- this gate
        # makes the FFT vs Time pre-flight (H1 root cause) consistent
        # across all spectral entry points (H3 mitigation).
        mode = self.toolbar.current_mode()
        ctx_mode = 'fft' if mode == 'fft' else 'order'
        sig_data = (
            self.inspector.fft_ctx.current_signal()
            if ctx_mode == 'fft'
            else self.inspector.order_ctx.current_signal()
        )
        fid = sig_data[0] if sig_data else None
        fd = self.files.get(fid) if fid else None
        if not self._check_uniform_or_prompt(fd, ctx_mode):
            return
        # Re-fetch t/sig: the popover Accept branch rebuilt
        # ``fd.time_array`` to ``arange(n)/fs``, so the local ``t`` we
        # captured before the popover is now stale.
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10:
            self.toast("请选择有效信号", "warning"); return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m]
            sig = sig[m]
        fft_params = self.inspector.fft_ctx.current_params()
        win = fft_params['window']
        nfft = fft_params['nfft']
        overlap = fft_params['overlap']
        fs = self.inspector.fft_ctx.fs()

        try:
            self.statusBar.showMessage('计算FFT...');
            QApplication.processEvents()

            freq, amp, _psd = self._fft_compute_arrays(sig, fs, fft_params)

            x_auto = bool(fft_params.get('x_auto', fft_params.get('autoscale', True)))
            x_min = float(fft_params.get('x_min', 0.0))
            x_max = float(fft_params.get('x_max', 0.0))
            if x_auto:
                xlim = (0.0, self._fft_auto_xlim(freq, amp))
            elif x_max > x_min:
                xlim = (x_min, x_max)
            else:
                xlim = (0.0, fs / 2)
            y_auto = bool(fft_params.get('y_auto', True))
            y_min = float(fft_params.get('y_min', 0.0))
            y_max = float(fft_params.get('y_max', 0.0))

            # Wave 2 / SP2 / Task 2.3: per-subplot Linear/dB toggle.
            amp_y = fft_params.get('amp_y', 'Linear')
            if amp_y == 'dB':
                amp_disp = 20 * np.log10(
                    np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12)
                )
            else:
                amp_disp = amp

            sig_label = self.inspector.fft_ctx.combo_sig.currentText()
            entry = {
                'label': sig_label,
                'color': '#2563eb',
                'freq': freq,
                'amp': amp_disp,
                'time': t,
                'signal': sig,
            }
            self.canvas_fft.plot_spectra(
                [entry],
                xlim=xlim,
                amp_label='Amplitude (dB)' if amp_y == 'dB' else 'Amplitude',
                title=f'FFT - {sig_label} (窗:{win}, NFFT:{nfft or "auto"})',
                y_auto=y_auto, y_min=y_min, y_max=y_max,
            )
            xt, yt = self.inspector.top.tick_density()
            self.canvas_fft.set_tick_density(xt, yt)
            self._remember_batch_preset(
                "当前 FFT",
                "fft",
                self.inspector.fft_ctx.current_signal(),
                {
                    'fs': fs,
                    'window': win,
                    'nfft': nfft,
                    'overlap': overlap,
                },
            )
            pi = np.argmax(amp[1:]) + 1;
            self.statusBar.showMessage(f'FFT峰值: {freq[pi]:.2f} Hz ({amp[pi]:.4f})')
            self.toast(f"FFT 完成 · 峰值 {freq[pi]:.2f} Hz", "success")
        except Exception as e:
            QMessageBox.critical(self, 'FFT错误', str(e))

    # ------------------------------------------------------------------
    # Order analysis (COT on a worker QThread, M5)
    # ------------------------------------------------------------------
    # ``do_order_time`` gathers signal/rpm/params on the GUI thread,
    # then runs ``COTOrderAnalyzer.compute`` on an
    # ``AnalysisComputeWorker`` + QThread (same lifecycle wiring as
    # ``do_fft_time``); ``_on_order_finished`` renders the result.

    def _order_sig_for(self, source):
        """Fetch + range-gate an explicit Order signal source ``(fid, ch)``.
        Returns ``(t, sig)`` or ``(None, None)``. V7b: the split queue must
        fetch a NON-focused pane's source, not the inspector selection."""
        if not source:
            return None, None
        fid, ch = source
        if fid not in self.files:
            return None, None
        fd = self.files[fid]
        if ch not in fd.data.columns:
            return None, None
        t = fd.time_array
        sig = fd.data[ch].values
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m] if t is not None else None
            sig = sig[m]
        return t, sig

    def _order_rpm_for(self, rpm_source, n):
        """Fetch + range-gate + scale an explicit Order RPM source. ``n`` is
        the signal length the rpm must match. Returns the scaled rpm array or
        ``None`` (caller skips the pane). The scale factor is the current
        inspector ``rpm_factor`` — shared across panes like the COT params."""
        if not rpm_source:
            return None
        fid, ch = rpm_source
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
            return None
        return rpm

    def do_order_time(self):
        """Compute the WHOLE active Order view — every pane (V7b).

        Each pane carries one signal source ``(fid, ch)`` plus its own
        ``rpm_source``. For every pane we build the analysis cache key and
        either render a cache HIT onto that pane's canvas immediately, or
        enqueue a ``(pane_idx, fid, ch, rpm_source)`` job. The focused pane
        is enqueued first. Miss jobs run sequentially on ONE shared worker
        QThread; :meth:`_on_order_thread_done` pumps the next. A single
        (non-split) pane yields one job, identical to the V7 path.

        Re-entry while a worker is running drops the whole new request with
        ``正在计算…``. A pane whose source/rpm is unfetchable is skipped
        without aborting the queue.
        """
        # V7 Step 5: capture the active Order view (params + per-pane sources +
        # rpm_source) so a later view switch renders from analysis_caches.
        self._capture_active_analysis_view('order')
        # Re-entry guard: a previous compute / queue is still running.
        if getattr(self, '_order_thread', None) is not None and self._order_thread.isRunning():
            self.statusBar.showMessage("正在计算…")
            return
        mgr = self.analysis_managers['order']
        state = mgr.get(mgr.active)
        page = self._analysis_page('order')
        cache = self.analysis_caches['order']

        focus = page.focused_index()
        pane_order = sorted(
            range(min(page.pane_count(), len(state.panes))),
            key=lambda i: (i != focus, i),
        )
        queue = []
        any_source = False
        for pane_idx in pane_order:
            sources = state.panes[pane_idx].sources
            if not sources:
                continue
            any_source = True
            fid, ch = sources[0]
            rpm_source = state.panes[pane_idx].rpm_source
            analysis_key = self._analysis_cache_key(
                'order', fid, ch,
                rpm_source=tuple(rpm_source) if rpm_source else None)
            cached = cache.get(analysis_key)
            if cached is not None:
                cache.put(analysis_key, cached)
                self._render_order_on(page.pane_canvas(pane_idx), cached)
            else:
                queue.append((pane_idx, fid, ch, rpm_source))

        if not queue:
            if not any_source:
                # No captured pane source → legacy inspector-selection path so
                # the standalone-signal UX + existing tests are unchanged.
                self._do_order_time_single()
                return
            self.statusBar.showMessage("使用缓存结果")
            return

        self._order_queue = queue
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")
        self._start_next_order_job()

    def _do_order_time_single(self):
        """Legacy single-source Order path: compute the inspector's selected
        signal/rpm onto the primary canvas. Kept for the standalone-signal UX
        and the pre-V7b tests."""
        sig_data = self.inspector.order_ctx.current_signal()
        rpm_data = self.inspector.order_ctx.current_rpm()
        if not sig_data:
            self.toast("请选择有效信号", "warning")
            return
        page = self._analysis_page('order')
        self._order_queue = []
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")
        if not self._dispatch_order_job(
                page.focused_index(), sig_data[0], sig_data[1],
                tuple(rpm_data) if rpm_data else None):
            self.inspector.order_ctx.set_progress("")

    def _start_next_order_job(self):
        """Dispatch the head Order job, skipping unfetchable sources."""
        while self._order_queue:
            pane_idx, fid, ch, rpm_source = self._order_queue.pop(0)
            if self._dispatch_order_job(pane_idx, fid, ch, rpm_source):
                return
        # Queue drained.
        self.inspector.order_ctx.set_progress("")

    def _dispatch_order_job(self, pane_idx, fid, ch, rpm_source):
        """Fetch the ``(fid, ch)`` signal + ``rpm_source`` rpm, then start the
        shared COT worker, rendering onto ``page.pane_canvas(pane_idx)``.
        Returns True if a worker started, False if the source was skipped."""
        from ..signal.order_cot import COTOrderAnalyzer, COTParams
        t, sig = self._order_sig_for((fid, ch))
        if sig is None or len(sig) < 100:
            return False
        rpm = self._order_rpm_for(rpm_source, len(sig))
        if rpm is None:
            return False
        fs = self.inspector.order_ctx.fs()
        order_params = self.inspector.order_ctx.current_params()
        op = self.inspector.order_ctx.get_params()
        # Audit fix R6/C7: COT requires strictly monotonic ``t``; synthesise a
        # uniform grid from the inspector fs when the timestamps are degenerate.
        t_arr = np.asarray(t, dtype=float) if t is not None else np.array([])
        if len(t_arr) < 2 or np.any(np.diff(t_arr) <= 0):
            t_arr = np.arange(len(sig), dtype=float) / float(fs)
        try:
            p = COTParams(
                samples_per_rev=int(order_params.get('samples_per_rev', 256)),
                nfft=int(op['nfft']),
                window=op.get('window', 'hanning'),
                max_order=float(op['max_order']),
                order_res=float(op['order_res']),
                time_res=float(op['time_res']),
                fs=fs,
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
            return False
        # Stash the analysis cache key + render target for this job.
        self._order_analysis_key = self._analysis_cache_key(
            'order', fid, ch,
            rpm_source=tuple(rpm_source) if rpm_source else None)
        self._order_render_pane = pane_idx

        from .analysis_worker import AnalysisComputeWorker

        def job(worker, _sig=sig, _rpm=rpm, _t=t_arr, _p=p):
            return COTOrderAnalyzer.compute(_sig, _rpm, _t, _p,
                                            cancel_token=worker.cancelled)

        worker = AnalysisComputeWorker(job)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_order_finished)
        worker.failed.connect(self._on_order_failed)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_order_thread_done)
        self._order_thread = thread
        self._order_worker = worker
        thread.start()
        return True

    def _render_order_on(self, canvas, result):
        """Multi-pane variant: draw an Order COT ``result`` on an arbitrary
        order heatmap canvas using the current OrderContextual display knobs.
        Pure canvas draw — no preset/status side-effects (those stay in
        ``_render_order_time``)."""
        title = (
            f"时间-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} "
            f"(分辨率:{result.params.order_res})"
        )
        ctx = self.inspector.order_ctx
        order_params = ctx.current_params() if hasattr(ctx, 'current_params') else {}
        amp_mode_token = (
            'amplitude_db'
            if order_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB'
            else 'amplitude'
        )
        # Pin the amplitude mode so the slice's amplitude-axis label reads
        # 'Amplitude (dB)' vs 'Amplitude' correctly (Order renders through
        # plot_or_update_heatmap, which does not set it like plot_result does).
        canvas._amplitude_mode = amp_mode_token
        canvas.plot_or_update_heatmap(
            matrix=result.amplitude.T,
            x_extent=(float(result.times[0]), float(result.times[-1])),
            y_extent=(float(result.orders[0]), float(result.orders[-1])),
            x_label='Time (s)',
            y_label='Order',
            title=title,
            cmap='turbo',
            interp='bilinear',
            cbar_label='Amplitude',
            amplitude_mode=amp_mode_token,
            z_auto=bool(order_params.get('z_auto', False)),
            z_floor=float(order_params.get('z_floor', -30.0)),
            z_ceiling=float(order_params.get('z_ceiling', 0.0)),
            x_auto=bool(order_params.get('x_auto', True)),
            x_min=float(order_params.get('x_min', 0.0)),
            x_max=float(order_params.get('x_max', 0.0)),
            y_auto=bool(order_params.get('y_auto', True)),
            y_min=float(order_params.get('y_min', 0.0)),
            y_max=float(order_params.get('y_max', 0.0)),
            x_coords=result.times, y_coords=result.orders,
        )
        # Seed the order slice (default 按阶次 / Y is most useful, but keep the
        # current direction if the user already switched it).
        if getattr(canvas, '_slice_curve', None) is not None:
            canvas._seed_slice()
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)

    def _render_order_time(self, result):
        # Wave 3 / Task 3.2: pull HEAD-parity display knobs from the
        # OrderContextual. Inspector exposes amplitude_mode ∈
        # {'Amplitude dB', 'Amplitude'} and dynamic ∈
        # {'30 dB', '50 dB', '80 dB', 'Auto'}; canvas expects the
        # internal token 'amplitude_db' / 'amplitude' for the first.
        # `result.amplitude` is (frames, orders) → transpose so imshow
        # gets (rows=Y_orders, cols=X_times); x_extent=times, y_extent=orders.
        self._render_order_on(self.canvas_order, result)
        self._remember_batch_preset(
            "当前时间-阶次", "order_time",
            self.inspector.order_ctx.current_signal(),
            {
                'fs': result.params.fs,
                'nfft': result.params.nfft,
                'max_order': result.params.max_order,
                'order_res': result.params.order_res,
                'time_res': result.params.time_res,
                'rpm_factor': self.inspector.order_ctx.rpm_factor(),
            },
            rpm_signal=self.inspector.order_ctx.current_rpm(),
        )
        self.statusBar.showMessage(
            f'完成 | {len(result.times)} 时间点 × {len(result.orders)} 阶次'
        )
        self.toast(
            f"时间-阶次谱完成 · {len(result.times)} × {len(result.orders)}",
            "success",
        )

    def _on_order_finished(self, result):
        analysis_key = getattr(self, '_order_analysis_key', None)
        if analysis_key is not None:
            self.analysis_caches['order'].put(analysis_key, result)
        # V7b: render onto the SPECIFIC pane this job was computed for.
        # ``_render_order_time`` (preset + status + toast side-effects) runs
        # only for the primary pane (0); compare panes get a pure canvas draw.
        page = self._analysis_page('order')
        pane_idx = getattr(self, '_order_render_pane', 0)
        if pane_idx == 0:
            self._render_order_time(result)
        elif pane_idx < page.pane_count():
            self._render_order_on(page.pane_canvas(pane_idx), result)
        else:
            self._render_order_time(result)
        # Clear the in-progress label only when no more jobs are queued; the
        # thread-done pump re-sets it for the next job otherwise.
        if not self._order_queue:
            self.inspector.order_ctx.set_progress("")

    def _on_order_failed(self, message):
        # A single pane's failure must not abort the queue; the wired
        # ``failed -> thread.quit -> _on_order_thread_done`` pump advances to
        # the next job. Surface the error but keep going.
        #
        # V8 minor: use the non-modal ``toast`` (symmetric with
        # ``_on_fft_time_failed``) instead of ``QMessageBox.critical``. A
        # modal exec() raised mid-queue spins a nested event loop that can
        # re-enter the compute pump (and hangs under offscreen Qt with no
        # user to click OK — lesson qmessagebox-static-warning-hangs-offscreen).
        msg = str(message)
        self.toast(msg, "error")
        self.statusBar.showMessage(f"阶次分析错误: {msg}")
        if not self._order_queue:
            self.inspector.order_ctx.set_progress("")

    def _on_order_thread_done(self):
        self._order_thread = None
        self._order_worker = None
        if self._order_queue:
            self._start_next_order_job()

    def closeEvent(self, event):
        """Stop the FFT-vs-Time worker before the window is destroyed.

        ``_fft_time_thread + _fft_time_worker`` is a ``QObject + QThread``
        pair (an :class:`AnalysisComputeWorker` running the spectrogram
        job; see :meth:`do_fft_time`). The worker has ``cancel()`` (flips
        the flag its ``cancelled()`` token returns, which the analyzer
        polls per frame); the thread is what owns ``isRunning()``. The
        wired ``thread.finished -> deleteLater`` chain handles cleanup —
        we just need to give it time to run via ``quit() + wait()``.
        """
        # V7b: drop any pending split-queue jobs FIRST so the cooperative
        # ``quit()+wait()`` drain below — which fires ``_on_*_thread_done``
        # via the wired ``thread.finished`` — does not pump a NEW worker job
        # onto a window that is being destroyed.
        self._fft_time_queue = []
        self._order_queue = []
        fft_thread = getattr(self, '_fft_time_thread', None)
        fft_worker = getattr(self, '_fft_time_worker', None)
        if fft_thread is not None and fft_thread.isRunning():
            if fft_worker is not None and hasattr(fft_worker, 'cancel'):
                fft_worker.cancel()
            # cancel is cooperative; the analyzer returns at the next
            # poll, then the wired ``finished/failed -> thread.quit``
            # connection drains the worker thread's event loop. We
            # quit() defensively in case the worker is between polls.
            fft_thread.quit()
            if not fft_thread.wait(2000):
                fft_thread.terminate()
                fft_thread.wait(500)

        # Order (COT) worker: same drain. The COT job now polls
        # ``cancelled()`` per frame (``do_order_time`` passes
        # ``cancel_token=worker.cancelled`` into ``COTOrderAnalyzer.compute``),
        # so cancel() takes effect within a frame and the cooperative
        # ``quit() + wait(2000)`` is the normal exit path. The terminate()
        # fallback is only a GIL-thread / Windows backstop: on macOS
        # ``terminate()`` never lands on a GIL-held numpy worker (see
        # pyqt-ui/2026-06-11-qthread-terminate-noop-on-gil-bound-macos),
        # but it still guards a Qt5 qFatal crash if a non-cooperative
        # compute ever outlives wait(2000) at destruction.
        order_thread = getattr(self, '_order_thread', None)
        order_worker = getattr(self, '_order_worker', None)
        if order_thread is not None and order_thread.isRunning():
            if order_worker is not None:
                order_worker.cancel()
            order_thread.quit()
            if not order_thread.wait(2000):
                order_thread.terminate()
                order_thread.wait(500)

        super().closeEvent(event)

    # ------------------------------------------------------------------
    # FFT vs Time (synchronous compute path, Plan Task 6)
    # ------------------------------------------------------------------
    # The cache lives on this MainWindow instance (per session).
    # Invalidation hooks belong to T7 (file load/close/edit + custom-x +
    # rebuild); this task adds get/put helpers and the consumer side.
    # Per ``signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface``
    # the cache is read on the per-button-click hot path inside
    # ``do_fft_time`` — that is the SOLE consumer; no other code path
    # bypasses ``_fft_time_cache_get``.
    # Per ``pyqt-ui/2026-04-25-cache-invalidation-event-conditional`` we
    # do NOT need a last-state diff at the entry of ``do_fft_time`` —
    # this method is button-triggered (Inspector emits
    # ``fft_time_requested``), not handler-replayed via
    # ``QTimer.singleShot`` re-entry.

    def _fft_time_cache_key(self, params):
        """Build the LRU cache key from compute-relevant fields ONLY.

        Display options (``amplitude_mode``, ``cmap``, ``dynamic``,
        ``freq_auto``, ``freq_min``, ``freq_max``) are deliberately
        absent so toggling them re-renders without recomputing.
        """
        return (
            params.get('fid'),
            params.get('channel'),
            tuple(params.get('time_range') or (None, None)),
            float(params.get('fs')),
            int(params.get('nfft')),
            str(params.get('window')),
            float(params.get('overlap')),
            bool(params.get('remove_mean')),
            float(params.get('db_reference', 1.0)),
        )

    def _fft_time_cache_get(self, key):
        if key not in self._fft_time_cache:
            return None
        # LRU: pop and reinsert so the most-recently-used entry is at
        # the OrderedDict tail.
        value = self._fft_time_cache.pop(key)
        self._fft_time_cache[key] = value
        return value

    def _fft_time_cache_put(self, key, result):
        if key in self._fft_time_cache:
            self._fft_time_cache.pop(key)
        self._fft_time_cache[key] = result
        while len(self._fft_time_cache) > self._fft_time_cache_capacity:
            # popitem(last=False) is the LRU eviction (oldest first).
            self._fft_time_cache.popitem(last=False)

    def _fft_time_cache_clear_for_fid(self, fid):
        """Drop every cache entry keyed under ``fid``.

        Used by per-file invalidation hooks (file load, single-file
        close, time-axis rebuild, custom-x change) so a freshly
        modified file does not see stale results from a prior open.
        Cache key shape (per ``_fft_time_cache_key``):
        ``(fid, channel, time_range_tuple, fs, nfft, window, overlap,
        remove_mean, db_reference)`` — ``key[0]`` is the fid.
        """
        keys = [k for k in self._fft_time_cache if k[0] == fid]
        for k in keys:
            self._fft_time_cache.pop(k, None)

    def _get_fft_time_signal(self):
        """Resolve the (fid, channel, time, signal, file_data) tuple
        for the currently-selected fft_time signal.

        Adapts to this repo's ``FileData`` API: ``fd.data`` is the
        DataFrame (NOT ``fd.df``), ``fd.time_array`` is the time axis,
        ``fd.channel_units`` carries unit strings (NOT ``fd.units``).
        Returns ``(None,) * 5`` when no usable selection exists so
        ``do_fft_time`` can surface a single warning and bail.
        """
        data = self.inspector.fft_time_ctx.current_signal()
        return self._fft_time_signal_for(data)

    def _fft_time_signal_for(self, source):
        """Resolve the (fid, channel, time, signal, file_data) tuple for an
        explicit ``(fid, ch)`` source. V7b: the split-heatmap queue needs to
        fetch a NON-focused pane's source directly, not the inspector's
        current selection. Returns ``(None,) * 5`` when the source is
        unavailable so the queue can skip that job without aborting the rest.
        """
        if not source:
            return None, None, None, None, None
        fid, ch = source
        if fid not in self.files:
            return None, None, None, None, None
        fd = self.files[fid]
        if not hasattr(fd, 'data') or ch not in fd.data.columns:
            return None, None, None, None, None
        t = np.asarray(fd.time_array, dtype=float)
        sig = np.asarray(fd.data[ch].to_numpy(copy=False), dtype=float)
        return fid, ch, t, sig, fd

    @staticmethod
    def _normalize_freq_range(p):
        """Translate the panel's ``freq_*`` fields into the canvas's
        ``freq_range`` tuple, with a clamp against contradictory
        ``freq_max <= freq_min`` input.

        Returns ``None`` to mean "auto" (canvas falls back to Nyquist).
        Reviewer Important #3: when a user toggles auto off and leaves
        ``freq_max == 0`` while raising ``freq_min``, the panel emits
        ``(lo>0, hi=0)``; the canvas's silent fallback is correct but
        confusing. We force ``hi=0`` (auto) whenever ``hi <= lo`` AND
        ``hi > 0``, and treat the entire pair as auto so the canvas
        reuses its existing fallback rather than receiving the bogus
        pair. Documented in
        ``docs/superpowers/reports/2026-04-25-fft-vs-time-T5-mainwindow-sync-compute.md``.
        """
        if p.get('freq_auto', True):
            return None
        lo = float(p.get('freq_min', 0.0))
        hi = float(p.get('freq_max', 0.0))
        # If freq_max is 0 it already means "auto / use Nyquist" per
        # FFTTimeContextual contract — pass the (lo, 0) pair through.
        # If freq_max > 0 but <= freq_min, the user input is
        # contradictory; force auto so the canvas does not silently
        # invert or collapse the range.
        if hi > 0 and hi <= lo:
            return None
        return (lo, hi)

    def do_fft_time(self, force=False):
        """Compute and render the FFT-vs-Time spectrogram(s) for the active view.

        V7b: computes the WHOLE active view — every pane, not just the
        focused one. Each pane carries one heatmap source ``(fid, ch)``.
        For every pane we build the analysis cache key and either:
          * cache HIT  → render that result on the pane's own canvas
            immediately (synchronous, no thread); or
          * cache MISS → enqueue a ``(pane_idx, fid, ch)`` job.
        The focused pane is enqueued first so the user's primary chart
        appears first. The miss jobs run sequentially on ONE shared worker
        QThread (no concurrent threads): :meth:`_start_next_fft_time_job`
        dispatches the head job, :meth:`_on_fft_time_finished` caches +
        renders onto ``page.pane_canvas(job_pane_idx)``, then
        :meth:`_on_fft_time_thread_done` drives the next job. A single
        pane (non-split) view yields exactly one job, so behaviour is
        identical to the V7 focused-single-pane path.

        ``force=True`` bypasses the LRU cache. Re-entry while a worker is
        still running is dropped with a ``正在计算…`` status message
        (the whole new request is discarded; we do not interleave a new
        view's jobs into a running queue). On compute failure the OLD
        chart for that pane stays visible — the failed handler does NOT
        clear the canvas — and the next queued job still runs.
        """
        # V7 Step 5: capture the active view's params + per-pane sources so a
        # later view switch renders from analysis_caches.
        self._capture_active_analysis_view('fft_time')
        # Re-entry guard: a previous compute / queue is still on the thread.
        # We drop the whole new request rather than interleaving jobs.
        if (
            self._fft_time_thread is not None
            and self._fft_time_thread.isRunning()
        ):
            self.statusBar.showMessage("正在计算…")
            return
        mgr = self.analysis_managers['fft_time']
        state = mgr.get(mgr.active)
        page = self._analysis_page('fft_time')
        p = self.inspector.fft_time_ctx.get_params()
        cache = self.analysis_caches['fft_time']

        # Build the job list: focused pane first so its chart appears first.
        focus = page.focused_index()
        pane_order = sorted(
            range(min(page.pane_count(), len(state.panes))),
            key=lambda i: (i != focus, i),
        )
        queue = []
        any_source = False
        for pane_idx in pane_order:
            sources = state.panes[pane_idx].sources
            if not sources:
                continue
            any_source = True
            fid, ch = sources[0]
            analysis_key = self._analysis_cache_key('fft_time', fid, ch)
            cached = None if force else cache.get(analysis_key)
            if cached is not None:
                # Cache hit → render on THIS pane's canvas immediately
                # (touch the LRU so it stays warm) — no worker needed.
                cache.put(analysis_key, cached)
                self._render_fft_time_on(page.pane_canvas(pane_idx), cached, p)
            else:
                queue.append((pane_idx, fid, ch))

        if not queue:
            if not any_source:
                # No pane has a source selected → legacy single-source path
                # so the standalone-signal UX + existing tests are unchanged.
                self._do_fft_time_single(force=force)
                return
            self.statusBar.showMessage(
                "使用缓存结果 · NFFT %s" % p.get('nfft'))
            return

        self._fft_time_queue = queue
        self._start_next_fft_time_job()

    def _do_fft_time_single(self, force=False):
        """Legacy single-source FFT-vs-Time path: compute the inspector's
        currently-selected signal onto the primary canvas. Kept so a view
        whose panes have no captured source (e.g. a brand-new heatmap view
        before the navigator/inspector echo wires a source) still computes
        the inspector selection, matching pre-V7b behaviour and tests.

        Fetches via :meth:`_get_fft_time_signal` (the inspector-selection
        getter, which standalone-signal tests monkeypatch) rather than the
        per-pane ``_fft_time_signal_for`` used by the split queue.
        """
        from ..signal import SpectrogramParams
        self._fft_time_queue = []
        page = self._analysis_page('fft_time')
        pane_idx = page.focused_index()
        fid, ch, t, sig, fd = self._get_fft_time_signal()
        if sig is None or len(sig) < 2:
            self.toast("请选择有效信号", "warning")
            return
        # Pre-flight uniformity gate (T2, 2026-04-26): rebuild a non-uniform
        # time axis BEFORE dispatching the worker.
        if not self._check_uniform_or_prompt(fd, 'fft_time'):
            return
        # The rebuild may have rewritten ``fd.time_array``; re-fetch.
        fid, ch, t, sig, fd = self._get_fft_time_signal()
        if sig is None or len(sig) < 2:
            self.toast("请选择有效信号", "warning")
            return
        p = self.inspector.fft_time_ctx.get_params()
        if self.inspector.top.range_enabled():
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m]; sig = sig[m]
            if len(sig) < 2:
                self.toast("当前范围内样本不足", "warning")
                return
            time_range = (float(lo), float(hi))
        else:
            time_range = (float(t[0]), float(t[-1]))
        key_params = dict(p, fid=fid, channel=ch, time_range=time_range)
        key = self._fft_time_cache_key(key_params)
        analysis_key = self._analysis_cache_key('fft_time', fid, ch)
        cached = None if force else self._fft_time_cache_get(key)
        if cached is None and not force:
            cached = self.analysis_caches['fft_time'].get(analysis_key)
        if cached is not None:
            # Cache hit stays on the main thread — no worker needed.
            self.analysis_caches['fft_time'].put(analysis_key, cached)
            self._render_fft_time(cached, p)
            self.statusBar.showMessage(
                "使用缓存结果 · "
                f"{cached.metadata.get('frames', 0)} frames · NFFT {p['nfft']}"
            )
            return
        params = SpectrogramParams(
            fs=float(p['fs']),
            nfft=int(p['nfft']),
            window=str(p['window']),
            overlap=float(p['overlap']),
            remove_mean=bool(p['remove_mean']),
            db_reference=float(p.get('db_reference', 1.0)),
        )
        unit = ''
        if fd is not None and hasattr(fd, 'channel_units'):
            unit = fd.channel_units.get(ch, '') or ''
        self._fft_time_pending = {
            'cache_key': key,
            'render_params': p,
            'analysis_key': analysis_key,
            'pane_idx': pane_idx,
        }

        def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
            from ..signal import SpectrogramAnalyzer
            return SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        self._start_fft_time_worker(job)

    def _start_next_fft_time_job(self):
        """Dispatch the head job of the FFT-vs-Time queue, skipping jobs whose
        source has become unfetchable. Stops (queue empty) when none remain."""
        page = self._analysis_page('fft_time')
        while self._fft_time_queue:
            pane_idx, fid, ch = self._fft_time_queue.pop(0)
            if self._dispatch_fft_time_job(pane_idx, fid, ch):
                return
        # Queue drained.
        self.statusBar.showMessage("FFT vs Time 完成")

    def _dispatch_fft_time_job(self, pane_idx, fid, ch, force=False):
        """Fetch + range-gate the ``(fid, ch)`` source, then start the shared
        worker for it, rendering onto ``page.pane_canvas(pane_idx)`` when done.
        Returns True if a worker was started, False if the source was skipped
        (caller advances to the next queued job)."""
        from ..signal import SpectrogramParams
        fid, ch, t, sig, fd = self._fft_time_signal_for((fid, ch))
        if sig is None or len(sig) < 2:
            return False
        # Pre-flight uniformity gate (T2, 2026-04-26): rebuild a non-uniform
        # time axis BEFORE dispatching the worker. Best-effort per pane —
        # a failed rebuild skips this job, not the whole queue.
        if not self._check_uniform_or_prompt(fd, 'fft_time'):
            return False
        # The rebuild may have rewritten ``fd.time_array``; re-fetch.
        fid, ch, t, sig, fd = self._fft_time_signal_for((fid, ch))
        if sig is None or len(sig) < 2:
            return False
        p = self.inspector.fft_time_ctx.get_params()
        if self.inspector.top.range_enabled():
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t = t[m]; sig = sig[m]
            if len(sig) < 2:
                return False
            time_range = (float(lo), float(hi))
        else:
            time_range = (float(t[0]), float(t[-1]))
        key_params = dict(p, fid=fid, channel=ch, time_range=time_range)
        key = self._fft_time_cache_key(key_params)
        analysis_key = self._analysis_cache_key('fft_time', fid, ch)
        # SpectrogramParams is the cache key on the analyzer side; build
        # it from compute-relevant fields only.
        params = SpectrogramParams(
            fs=float(p['fs']),
            nfft=int(p['nfft']),
            window=str(p['window']),
            overlap=float(p['overlap']),
            remove_mean=bool(p['remove_mean']),
            db_reference=float(p.get('db_reference', 1.0)),
        )
        unit = ''
        if fd is not None and hasattr(fd, 'channel_units'):
            unit = fd.channel_units.get(ch, '') or ''
        # Stash everything the finished handler needs to cache + render the
        # RIGHT pane. ``pane_idx`` is the load-bearing field: the finished
        # handler renders onto ``page.pane_canvas(pane_idx)``, never pane 0.
        self._fft_time_pending = {
            'cache_key': key,
            'render_params': p,
            'analysis_key': analysis_key,
            'pane_idx': pane_idx,
        }

        def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
            from ..signal import SpectrogramAnalyzer
            return SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        self._start_fft_time_worker(job)
        return True

    def _start_fft_time_worker(self, job):
        """Wire + start the shared FFT-vs-Time worker/QThread for ``job``.
        The caller has already populated ``self._fft_time_pending`` (incl. the
        render ``pane_idx``)."""
        from .analysis_worker import AnalysisComputeWorker
        worker = AnalysisComputeWorker(job)
        thread = QThread(self)
        worker.moveToThread(thread)
        # Standard QThread cleanup chain. The order matters:
        #   started -> run        : entry point lives on the worker thread
        #   finished/failed -> quit: stops the event loop on the worker thread
        #   finished -> handler   : runs on the MAIN thread (AutoConnection
        #                           across threads = QueuedConnection)
        #   thread.finished -> deleteLater (worker, thread)
        #   thread.finished -> _on_fft_time_thread_done : clears refs + pumps
        #                       the next queued job
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_fft_time_finished)
        worker.failed.connect(self._on_fft_time_failed)
        worker.progress.connect(self._on_fft_time_progress)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_fft_time_thread_done)
        self._fft_time_thread = thread
        self._fft_time_worker = worker
        self.statusBar.showMessage("正在计算…")
        thread.start()

    def _render_fft_time(self, result, p):
        """Apply display-only options and draw on the primary canvas.

        Display fields are NOT part of the cache key; this is the sole
        place they are read.
        """
        self._render_fft_time_on(self.canvas_fft_time, result, p)

    def _render_fft_time_on(self, canvas, result, p):
        """Multi-pane variant: render ``result`` on an arbitrary FFT-vs-Time
        heatmap canvas with display options from ``p``."""
        freq_range = self._normalize_freq_range(p)
        # Wave 5: legacy ``dynamic: str`` is gone; we forward the explicit
        # z_auto / z_floor / z_ceiling triplet that FFTTimeContextual now
        # emits, plus y_auto / y_min / y_max for the manual Y override
        # (precedes freq_range on the canvas). amplitude_mode is already
        # the canvas's lowercase token ('amplitude_db' / 'amplitude') in
        # FFTTimeContextual.get_params, so no translation needed.
        canvas.plot_result(
            result,
            amplitude_mode=p['amplitude_mode'],
            cmap=p['cmap'],
            z_auto=bool(p.get('z_auto', False)),
            z_floor=float(p.get('z_floor', -80.0)),
            z_ceiling=float(p.get('z_ceiling', 0.0)),
            freq_range=freq_range,
            interp='bilinear',
            x_auto=bool(p.get('x_auto', True)),
            x_min=float(p.get('x_min', 0.0)),
            x_max=float(p.get('x_max', 0.0)),
            y_auto=bool(p.get('y_auto', True)),
            y_min=float(p.get('y_min', 0.0)),
            y_max=float(p.get('y_max', 0.0)),
        )
        xt, yt = self.inspector.top.tick_density()
        canvas.set_tick_density(xt, yt)

    def _on_fft_time_cursor_info(self, text):
        """Surface PgHeatmapCanvas hover readout in the status bar.

        Empty text (cursor outside the heatmap scene or before a result
        is plotted) restores the active-file summary so the bar does not
        remain blank. Reviewer Important #1.
        """
        if text:
            self.statusBar.showMessage(text)
        else:
            # Restore default status when the cursor leaves the plot.
            self._update_info()

    # ---- FFT vs Time worker callbacks (Plan Task 7) ----
    def _on_fft_time_finished(self, result):
        """Worker reported success — cache + render on the main thread.

        Runs on the main thread (Qt cross-thread signals default to
        ``QueuedConnection``), so it is safe to touch the LRU cache and
        the pyqtgraph canvas here.
        """
        pending = getattr(self, '_fft_time_pending', None) or {}
        key = pending.get('cache_key')
        p = pending.get('render_params')
        analysis_key = pending.get('analysis_key')
        pane_idx = pending.get('pane_idx')
        if key is not None:
            self._fft_time_cache_put(key, result)
        if analysis_key is not None:
            self.analysis_caches['fft_time'].put(analysis_key, result)
        if p is not None:
            # V7b: render onto the SPECIFIC pane this job was computed for,
            # never the focused pane / pane 0. ``pane_idx`` falls back to the
            # primary canvas only when the queue never set it (legacy path).
            page = self._analysis_page('fft_time')
            if pane_idx is not None and pane_idx < page.pane_count():
                self._render_fft_time_on(page.pane_canvas(pane_idx), result, p)
            else:
                self._render_fft_time(result, p)
        self.statusBar.showMessage(
            f"FFT vs Time 完成 · {result.metadata.get('frames', 0)} frames"
        )

    def _on_fft_time_failed(self, message):
        """Worker reported failure — keep the previous chart on screen.

        Mirrors the synchronous T5 error pattern: ``toast(error)`` plus
        a status-bar message; the canvas is NEVER cleared so the user
        keeps the last-known-good chart while debugging the input.

        Cancel is also routed here (the analyzer raises
        ``RuntimeError('spectrogram computation cancelled')`` when
        ``cancel_token`` returns truthy) — the message string itself
        carries the distinction, no separate signal needed.

        T2 (2026-04-26) removed the in-handler auto-rebuild + retry
        branch that previously handled ``non-uniform time axis``
        errors. Non-uniform inputs are now caught synchronously by
        :meth:`_check_uniform_or_prompt` BEFORE worker dispatch (see
        ``do_fft_time``). The handler's earlier ``_fft_time_retry_pending``
        flag had a latent lifecycle bug (cleared in the deferred
        ``_retry``'s ``finally`` before the next worker could fail);
        deleting the retry path eliminates that risk and simplifies the
        contract: every worker failure now surfaces verbatim. If the
        worker still raises ``non-uniform time axis`` (e.g. a future
        regression or a genuinely racy axis mutation), the message
        surfaces as a normal error toast and the user can click
        重建时间轴 manually.
        """
        msg = str(message)
        self.toast(msg, "error")
        self.statusBar.showMessage(f"FFT vs Time 错误: {message}")

    def _on_fft_time_progress(self, current, total):
        """Optional per-frame progress hook.

        Phase 1 has no progress dialog — this exists so future tasks
        (T8 export, T9 progress bar) can subscribe without rewiring.
        Signature mirrors the analyzer's ``progress_callback`` contract.
        """
        # Intentionally no UI updates in Phase 1. A status-bar update
        # here would compete with ``正在计算…`` and the cursor readout,
        # which is more user-visible noise than value.
        pass

    def _on_fft_time_thread_done(self):
        """Worker thread emitted ``finished`` — clear refs, then pump the
        next queued job.

        Both ``worker`` and ``thread`` are scheduled for deleteLater
        before this slot fires (per the connect order in
        :meth:`_dispatch_fft_time_job`); we drop the local references so the
        re-entry guard in :meth:`do_fft_time` lets the next compute through,
        then dispatch the next job in the split queue (V7b). The refs MUST be
        cleared before :meth:`_start_next_fft_time_job` so the new job's
        ``thread.isRunning()`` re-entry guard does not see the just-finished
        thread.
        """
        self._fft_time_thread = None
        self._fft_time_worker = None
        if self._fft_time_queue:
            self._start_next_fft_time_job()

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
