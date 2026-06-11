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
        # Order (COT) worker thread (M5). Same QObject + QThread pattern
        # as the FFT-vs-Time pair above; refs set in ``do_order_time``,
        # cleared in ``_on_order_thread_done``.
        self._order_thread = None
        self._order_worker = None
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
            sc.activated.connect(lambda bound=idx: self._switch_view(bound))
            self._view_shortcuts.append(sc)

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
        old_xt = top.spin_xt.blockSignals(True)
        old_yt = top.spin_yt.blockSignals(True)
        try:
            top.spin_xt.setValue(int(xt))
            top.spin_yt.setValue(int(yt))
        finally:
            top.spin_yt.blockSignals(old_yt)
            top.spin_xt.blockSignals(old_xt)

    def _on_mode_changed(self, mode):
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

    def _on_time_range_enabled_changed(self, enabled):
        canvas = self.chart_stack.focused_canvas()
        if enabled:
            xlim = None
            get_xlim = getattr(canvas, 'get_visible_xlim', None)
            if callable(get_xlim):
                xlim = get_xlim()
            self._sync_time_range_inputs_from_visible_xlim(xlim)
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self._view_bridge.capture_controls_into(
                self.view_manager.get(idx), self, canvas
            )
        if self.files and self.navigator.get_checked_channels():
            self._replot_canvas_for_view(idx, canvas)

    def _on_annotation_enabled_changed(self, mode, enabled):
        if mode == 'fft':
            chk = self.inspector.fft_ctx.chk_remark
            if chk.isChecked() != bool(enabled):
                chk.blockSignals(True)
                chk.setChecked(bool(enabled))
                chk.blockSignals(False)

    def _update_all_tick_density_pair(self, xt, yt):
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
        self.canvas_fft.set_tick_density(xt, yt)
        self.canvas_order.set_tick_density(xt, yt)

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
            "所有支持的文件 (*.mf4 *.csv *.xlsx *.xls *.tlproj);;"
            "项目 (*.tlproj);;数据文件 (*.mf4 *.csv *.xlsx *.xls)",
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
        fps, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "All (*.mf4 *.csv *.xlsx *.xls)")
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
            if ext == '.mf4':
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

        self._active = fid_map.get(doc.active_file)
        # Route the mode through the toolbar's programmatic setter (not
        # chart_stack.set_mode directly): _set_mode checks the matching
        # segment button AND emits mode_changed -> _on_mode_changed, which
        # syncs chart_stack + inspector + toolbar enabled-state together.
        # Calling chart_stack.set_mode alone leaves the toolbar segment and
        # the inspector panel stuck on the previous mode (desync on reopen of
        # a project saved in FFT / Order / FFT-vs-Time).
        self.toolbar._set_mode(doc.current_mode)

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

    def do_fft(self):
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
            sig = sig[m]
        fft_params = self.inspector.fft_ctx.current_params()
        win = fft_params['window']
        nfft = fft_params['nfft']
        overlap = fft_params['overlap']
        fs = self.inspector.fft_ctx.fs()
        # Wave 2 / SP2 / Task 2.2: Welch averaging + peak-hold dispatch.
        # Default '单帧' preserves the legacy compute_fft path so existing
        # presets and snapshots stay backward-compatible.
        avg_mode = fft_params.get('avg_mode', '单帧')
        overlap_pct = int(fft_params.get('avg_overlap', 50))
        avg_overlap = max(0.0, min(0.95, overlap_pct / 100.0))

        try:
            self.statusBar.showMessage('计算FFT...');
            QApplication.processEvents()

            if avg_mode == '线性平均':
                freq, amp, psd = FFTAnalyzer.compute_averaged_fft(
                    sig, fs, win, nfft or 1024, avg_overlap,
                )
            elif avg_mode == '峰值保持':
                freq, amp = FFTAnalyzer.compute_peak_hold_fft(
                    sig, fs, win=win, nfft=nfft or 1024, overlap=avg_overlap,
                )
                psd = amp ** 2
            else:
                # 单帧 — single-frame snapshot (legacy default).
                freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
                _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft)

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
            psd_y = fft_params.get('psd_y', 'dB')
            if amp_y == 'dB':
                amp_disp = 20 * np.log10(
                    np.clip(amp, 1e-12, None) / max(amp.max(), 1e-12)
                )
            else:
                amp_disp = amp
            if psd_y == 'dB':
                psd_disp = 10 * np.log10(psd + 1e-12)
            else:
                psd_disp = psd

            sig_label = self.inspector.fft_ctx.combo_sig.currentText()
            entry = {
                'label': sig_label,
                'color': '#2563eb',
                'freq': freq,
                'amp': amp_disp,
                'psd': psd_disp,
            }
            self.canvas_fft.plot_spectra(
                [entry],
                xlim=xlim,
                amp_label='Amplitude (dB)' if amp_y == 'dB' else 'Amplitude',
                psd_label='PSD (dB)' if psd_y == 'dB' else 'PSD',
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

    def do_order_time(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100:
            self.toast("请选择有效信号", "warning")
            return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t, sig = t[m], sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None:
            return
        fs = self.inspector.order_ctx.fs()
        # Wave 2 (2026-04-28 plan): COT is the only tracking algorithm.
        # The frequency-domain branch has been deleted alongside
        # combo_algorithm. Since M5 the compute runs on a worker QThread
        # (see below); results land in ``_on_order_finished``.
        order_params = self.inspector.order_ctx.current_params()
        op = self.inspector.order_ctx.get_params()
        from ..signal.order_cot import COTOrderAnalyzer, COTParams
        # Audit fix R6/C7: COTOrderAnalyzer.compute requires a strictly
        # monotonic ``t``; real MF4 column timestamps can carry
        # microsecond jitter that trips ``np.diff(t) <= 0`` on the GUI
        # thread. Mirror the batch fallback (Wave 1, Step 1.3): when the
        # timestamp array is degenerate, synthesise a uniform grid from
        # the inspector-supplied fs.
        t_arr = np.asarray(t, dtype=float)
        if len(t_arr) < 2 or np.any(np.diff(t_arr) <= 0):
            t_arr = np.arange(len(t_arr), dtype=float) / float(fs)
        # M5: COT moved off the GUI thread (AnalysisComputeWorker +
        # QThread, same pattern as do_fft_time). Re-entry guard mirrors
        # the FFT-vs-Time one; the COT compute polls ``worker.cancelled``
        # once per frame (cancel_token), so closeEvent's cancel() lands
        # cross-platform — terminate() is only a Windows backstop (see
        # pyqt-ui/2026-06-11-qthread-terminate-noop-on-gil-bound-macos).
        if getattr(self, '_order_thread', None) is not None and self._order_thread.isRunning():
            self.statusBar.showMessage("正在计算…")
            return
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
            return
        self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
        self.inspector.order_ctx.set_progress("计算中...")

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
        return

    def _render_order_time(self, result):
        title = (
            f"时间-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} "
            f"(分辨率:{result.params.order_res})"
        )
        # Wave 3 / Task 3.2: pull HEAD-parity display knobs from the
        # OrderContextual. Inspector exposes amplitude_mode ∈
        # {'Amplitude dB', 'Amplitude'} and dynamic ∈
        # {'30 dB', '50 dB', '80 dB', 'Auto'}; canvas expects the
        # internal token 'amplitude_db' / 'amplitude' for the first.
        ctx = self.inspector.order_ctx
        order_params = ctx.current_params() if hasattr(ctx, 'current_params') else {}
        amp_mode_token = (
            'amplitude_db'
            if order_params.get('amplitude_mode', 'Amplitude dB') == 'Amplitude dB'
            else 'amplitude'
        )
        # `result.amplitude` is (frames, orders) → transpose so imshow
        # gets (rows=Y_orders, cols=X_times); x_extent=times, y_extent=orders.
        self.canvas_order.plot_or_update_heatmap(
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
        )
        xt, yt = self.inspector.top.tick_density()
        self.canvas_order.set_tick_density(xt, yt)
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
        self.inspector.order_ctx.set_progress("")
        self._render_order_time(result)

    def _on_order_failed(self, message):
        self.inspector.order_ctx.set_progress("")
        QMessageBox.critical(self, "错误", str(message))

    def _on_order_thread_done(self):
        self._order_thread = None
        self._order_worker = None

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
        if not data:
            return None, None, None, None, None
        fid, ch = data
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
        """Compute and render the FFT-vs-Time spectrogram on a worker.

        ``force=True`` bypasses the LRU cache; ``force=False`` consults
        the cache first. Cache hits stay synchronous (no thread).
        Cache misses dispatch an :class:`AnalysisComputeWorker` (running
        the spectrogram compute job) on a ``QThread``;
        results land in :meth:`_on_fft_time_finished`, errors in
        :meth:`_on_fft_time_failed`. There is no synchronous fallback.

        Re-entry while a worker is still running is dropped with a
        ``正在计算…`` status message (Plan Task 7 Phase 1: ignore, do
        not queue). On compute failure the OLD chart stays visible —
        the failed handler does NOT call ``canvas_fft_time.clear()``.
        """
        from ..signal import SpectrogramParams
        # Re-entry guard: a previous compute is still on the thread.
        # Phase 1 ignores the click rather than queuing.
        if (
            self._fft_time_thread is not None
            and self._fft_time_thread.isRunning()
        ):
            self.statusBar.showMessage("正在计算…")
            return
        fid, ch, t, sig, fd = self._get_fft_time_signal()
        if sig is None or len(sig) < 2:
            self.toast("请选择有效信号", "warning")
            return
        # Pre-flight uniformity gate (T2, 2026-04-26): if the time axis
        # is non-uniform we route through the rebuild popover BEFORE
        # dispatching the worker. This collapses the old "worker raises
        # -> failed handler reopens popover -> deferred retry" path
        # (which had a latent retry-flag lifecycle bug, H4 in T1
        # diagnosis) into a single synchronous gate.
        if not self._check_uniform_or_prompt(fd, 'fft_time'):
            return
        # The popover Accept branch rebuilt ``fd.time_array`` to
        # ``arange(n)/fs`` and cleared the per-fid cache; refresh the
        # locals we captured pre-popover.
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
        cached = None if force else self._fft_time_cache_get(key)
        if cached is not None:
            # Cache hit stays on the main thread — no worker needed.
            self._render_fft_time(cached, p)
            self.statusBar.showMessage(
                "使用缓存结果 · "
                f"{cached.metadata.get('frames', 0)} frames · NFFT {p['nfft']}"
            )
            return
        # SpectrogramParams is the cache key on the analyzer side; build
        # it from compute-relevant fields only (matches our
        # _fft_time_cache_key contract).
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
        # Stash everything the finished handler needs to cache + render.
        # ``_render_fft_time`` re-reads display options from ``p`` so we
        # pass it through; ``key`` is the cache slot the result belongs
        # in. (T2 2026-04-26: ``force`` no longer needs to be stashed --
        # the prior non-uniform auto-retry path that consumed it has
        # been replaced by the synchronous ``_check_uniform_or_prompt``
        # pre-flight at the top of this method.)
        self._fft_time_pending = {
            'cache_key': key,
            'render_params': p,
        }
        from .analysis_worker import AnalysisComputeWorker

        def job(worker, _sig=sig, _t=t, _params=params, _ch=ch, _unit=unit):
            from ..signal import SpectrogramAnalyzer
            return SpectrogramAnalyzer.compute(
                _sig, _t, _params, channel_name=_ch, unit=_unit,
                progress_callback=worker.progress.emit,
                cancel_token=worker.cancelled,
            )

        worker = AnalysisComputeWorker(job)
        thread = QThread(self)
        worker.moveToThread(thread)
        # Standard QThread cleanup chain. The order matters:
        #   started -> run        : entry point lives on the worker thread
        #   finished/failed -> quit: stops the event loop on the worker thread
        #   finished -> handler   : runs on the MAIN thread (default
        #                           connection type AutoConnection across
        #                           threads = QueuedConnection)
        #   thread.finished -> deleteLater (worker, thread)
        #   thread.finished -> _on_fft_time_thread_done : clears refs
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(self._on_fft_time_finished)
        worker.failed.connect(self._on_fft_time_failed)
        # Optional progress wiring — Phase 1 has no progress dialog,
        # but the signal is hot so future tasks (T8 export, T9 progress
        # bar) can subscribe without retrofitting.
        worker.progress.connect(self._on_fft_time_progress)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_fft_time_thread_done)
        self._fft_time_thread = thread
        self._fft_time_worker = worker
        self.statusBar.showMessage("正在计算…")
        thread.start()

    def _render_fft_time(self, result, p):
        """Apply display-only options and draw on the canvas.

        Display fields are NOT part of the cache key; this is the sole
        place they are read.
        """
        freq_range = self._normalize_freq_range(p)
        # Wave 5: legacy ``dynamic: str`` is gone; we forward the explicit
        # z_auto / z_floor / z_ceiling triplet that FFTTimeContextual now
        # emits, plus y_auto / y_min / y_max for the manual Y override
        # (precedes freq_range on the canvas). amplitude_mode is already
        # the canvas's lowercase token ('amplitude_db' / 'amplitude') in
        # FFTTimeContextual.get_params, so no translation needed.
        self.canvas_fft_time.plot_result(
            result,
            amplitude_mode=p['amplitude_mode'],
            cmap=p['cmap'],
            z_auto=bool(p.get('z_auto', False)),
            z_floor=float(p.get('z_floor', -80.0)),
            z_ceiling=float(p.get('z_ceiling', 0.0)),
            freq_range=freq_range,
            x_auto=bool(p.get('x_auto', True)),
            x_min=float(p.get('x_min', 0.0)),
            x_max=float(p.get('x_max', 0.0)),
            y_auto=bool(p.get('y_auto', True)),
            y_min=float(p.get('y_min', 0.0)),
            y_max=float(p.get('y_max', 0.0)),
        )

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
        if key is not None:
            self._fft_time_cache_put(key, result)
        if p is not None:
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
        """Worker thread emitted ``finished`` — clear refs.

        Both ``worker`` and ``thread`` are scheduled for deleteLater
        before this slot fires (per the connect order in
        :meth:`do_fft_time`); we just drop the local references so the
        re-entry guard in ``do_fft_time`` lets the next compute through.
        """
        self._fft_time_thread = None
        self._fft_time_worker = None

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
