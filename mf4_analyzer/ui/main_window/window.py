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
from PyQt5.QtCore import QTimer, QThread, Qt

from ...io import DataLoader, FileData, HAS_ASAMMDF
from ...signal import (
    FFTAnalyzer,
    assess_speed_for_order,
    energy_band_fmax,
    resolve_nfft,
    resolve_order_nfft,
)
from ... import app_meta

from ._sentinel import _INSPECTOR_TIME_RANGE
from ._analysis_mixin import AnalysisMixin
from ._fft_mixin import FFTMixin
from ._order_mixin import OrderMixin
from ._fft_time_mixin import FFTTimeMixin
from ._project_io_mixin import ProjectIOMixin
from ._view_mixin import ViewMixin


class SurfaceStatusBar(QStatusBar):
    """QStatusBar API, displayed as the bottom rounded surface inside the tray."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("surfaceStatusBar")
        self.setContentsMargins(8, 2, 8, 2)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(40)


class MainWindow(
    AnalysisMixin, FFTMixin, OrderMixin, FFTTimeMixin, ProjectIOMixin,
    ViewMixin, QMainWindow,
):
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

        from ..chart_stack import ChartStack
        from ..file_navigator import FileNavigator
        from ..inspector import Inspector
        from ..toolbar import Toolbar
        from .. import view_bridge
        from ..view_state import ViewManager

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
        from ..analysis_cache import AnalysisResultCache
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

        self.statusBar = SurfaceStatusBar(self)
        root.addWidget(self.statusBar)
        self._status_hint_bar = None
        self._install_status_hint_bar(self.chart_stack.current_mode())
        self.chart_stack.mode_changed.connect(self._install_status_hint_bar)
        self.statusBar.showMessage("Ready")
        self._install_update_indicator()

        # Floating toast (constructed lazily on first use; the parent must
        # be the main window so the toast floats above the central canvas).
        from ..widgets import Toast
        self._toast = Toast(self)
        from ..markup import CopyThumbnail
        self._copy_thumbnail = CopyThumbnail(self)
        self._copy_thumbnail.clicked.connect(self._open_markup_editor)
        self._markup_editor = None

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
        # FIRST and the update button SECOND.
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
        self._update_btn.setToolTip("检查更新")
        self._update_btn.clicked.connect(self._open_release_page)

        self.statusBar.addPermanentWidget(self._update_btn)

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

    def _connect(self):
        # --- New-module wiring ---
        self.toolbar.open_requested.connect(self.open_files_or_project)
        self.toolbar.save_project_requested.connect(self.save_project_via_dialog)
        self.toolbar.save_project_as_requested.connect(self.save_project_as_via_dialog)
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
        self.inspector.order_time_requested.connect(self.do_order_time)
        # dB reference is display-only: changing it while in FFT mode should
        # immediately re-render without recompute. Re-evaluate _fft_render_signature
        # (which now includes db_reference) so the stale-check in _enter_fft_mode
        # detects the change and re-draws from cache.
        from PyQt5.QtCore import QTimer as _QTimer
        self.inspector.fft_ctx.spin_db_ref.valueChanged.connect(
            lambda _: _QTimer.singleShot(0, self._enter_fft_mode)
        )
        # Order dB reference is display-only: changing it re-renders from cache
        # (do_order_time hits cache, calls _render_order_on, no worker dispatch).
        self.inspector.order_ctx.spin_db_ref.valueChanged.connect(
            lambda _: _QTimer.singleShot(0, self.do_order_time)
        )
        # FFT-vs-Time dB reference is also display-only.  Changing it should
        # take the normal cache-hit render path (force=False) so the current
        # SpectrogramResult is redrawn with the new render-time reference
        # without scheduling a needless recompute.
        self.inspector.fft_time_ctx.spin_db_ref.valueChanged.connect(
            lambda _: _QTimer.singleShot(0, lambda: self.do_fft_time(force=False))
        )
        self.inspector.gpu_render_toggled.connect(self._on_gpu_render_toggled)
        # GPU 加速是会话级开关：每次启动一律关闭，不跨重启恢复（viewport-GL 累计
        # 过多显示 bug，默认不自动开；需要时本次会话内手动开）。故不再读/写持久化。

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
        self.inspector.top.max_range_requested.connect(
            self._on_time_range_max_requested
        )
        xrange_changed = getattr(self.canvas_time, 'xrange_changed', None)
        if xrange_changed is not None:
            xrange_changed.connect(self._on_time_canvas_xrange_changed)
        self._connect_canvas_range_signals(self.canvas_time)

        # ── Toolbar sidebar toggle buttons ───────────────────────────────────
        from ..side_panels import Ev, PanelState
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
        fft_display_params = self.inspector.fft_ctx.current_params()
        amp_y = fft_display_params.get('amp_y', 'Linear')
        db_reference = float(fft_display_params.get('db_reference', 1.0))
        return (sources, tuple(sorted(params.items())), range_sig, amp_y, db_reference)

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
        knobs are excluded from the cache key)."""
        freq, amp, _psd = result
        p = self.inspector.fft_ctx.current_params()
        amp_y = p.get('amp_y', 'Linear')
        if amp_y == 'dB':
            amp_disp = self._amplitude_to_db(amp, p.get('db_reference', 1.0))
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

    # _on_view_new / _on_view_delete / _on_view_duplicate / _on_view_color /
    # _restore_view_axis_opts / _applied_xaxis_opts / _capture_range_change_into_view /
    # _replot_secondary_preserving_xlim / _replot_canvas_for_view
    # live in _view_mixin.ViewMixin — composed into MainWindow via base list.

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
        mgr = self.analysis_managers['fft']
        state = mgr.get(mgr.active)
        state.panes[pane_idx].time_range = (float(lo), float(hi))
        return True

    def _time_data_extent(self):
        hi = 0.0
        for fd in self.files.values():
            times = getattr(fd, 'time_array', None)
            if times is None or len(times) == 0:
                continue
            try:
                candidate = float(times[-1])
            except Exception:
                continue
            if np.isfinite(candidate):
                hi = max(hi, candidate)
        return 0.0, hi

    def _on_time_range_max_requested(self):
        """「最大」按钮：把时间范围设为整段数据 [0, 全程] 并勾选「使用选定时间
        范围」，再按当前模式重绘/刷新。

        数据范围直接来自已加载文件的 time_array；不要从 spinbox limits
        反推，因为 limits 是 UI 状态，可能暂时滞后。这里特意走
        set_range_from_span（它会 blockSignals 地勾选 chk_range 并按当前模式
        记录 per-mode 勾选状态），从而避开 _on_time_range_enabled_changed
        —— 后者会用画布当前可见 xlim 覆盖 spinbox，正是我们要避免的。
        """
        top = self.inspector.top
        lo, hi = self._time_data_extent()
        if not (hi > lo):          # 还没有数据 / 没有可用的整段范围
            return
        # Keep spinbox limits fresh before setting values; stale/narrow limits
        # would otherwise clamp the data extent back to the old UI maximum.
        top.set_range_limits(lo, hi)
        # 同步填入 [lo, hi] 并（blockSignals 地）勾选，避免可见 xlim 覆盖。
        top.set_range_from_span(lo, hi)
        # 按当前模式应用（与现有处理器的尾部保持一致）。
        canvas = self.chart_stack.focused_canvas()
        idx = self._view_index_for_canvas(canvas)
        if idx is not None and 0 <= idx < len(self.view_manager.views):
            self._capture_range_change_into_view(
                self.view_manager.get(idx), canvas
            )
        mode = self.chart_stack.current_mode()
        if mode == 'time':
            if self.files and self.navigator.get_checked_channels():
                self._replot_canvas_for_view(idx, canvas)
        elif mode == 'fft':
            self._refresh_fft_time_preview(clear_spectrum=False)
        # fft_time / order: 仅做暂存即可，其计算是手动触发的
        # （与拖拽预览路径一致）。

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
        if not data:
            return
        fid, _ch = data
        if fid not in self.files:
            return
        fd = self.files[fid]
        self.inspector.fft_time_ctx.set_fs(fd.fs)

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

    # open_files_or_project / save_project_via_dialog / load_files / load_file
    # live in _project_io_mixin.ProjectIOMixin (composed via the base list).
    # open_acquisition_cockpit stays here (patches main_window.importlib).
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

        from ..chart_stack import _STATS_STRIP_ENABLED
        collect_stats = update_primary_ui and _STATS_STRIP_ENABLED

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

        with _pp.timed("_build_time_plot_data 总耗时"):
            data = self._build_time_plot_data(
                checked, custom_x, range_enabled, range_lo, range_hi,
            )
        st = {}
        if collect_stats:
            # Statistics are computed from the ORIGINAL (post-range-filter)
            # samples only — filtered overlay traces are excluded so the
            # stats strip mirrors the acquired data, never display-layer math.
            for row in data:
                name, _vis, _x, sig, _color, unit = row[:6]
                if name in self._time_filtered_names:
                    continue
                st[name] = {
                    'min': np.min(sig), 'max': np.max(sig),
                    'mean': np.mean(sig), 'rms': np.sqrt(np.mean(sig ** 2)),
                    'std': np.std(sig), 'p2p': np.ptp(sig), 'unit': unit,
                }
        if not data:
            canvas.clear()
            canvas.draw()
            if update_primary_ui:
                self.chart_stack.stats_strip.update_stats({})
            if _pp_section is not None:  # [perf-probe] 关掉提前返回路径的段
                _pp_section.__exit__(None, None, None)
            return

        xlabel = self._custom_xlabel or self.inspector.top.xaxis_label() or 'Time (s)'
        with _pp.timed("plot_channels(建轴+bind+首次setData) 耗时"):
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
        if _pp_section is not None:
            _pp_section.__exit__(None, None, None)
        # SpanSelector intentionally not enabled — drag-to-select on the
        # chart face was retired (2026-05-27) to prevent accidental triggers.
        # If you need a per-range export tool, re-enable explicitly behind a
        # toolbar button rather than always-on.
        if update_primary_ui:
            if collect_stats:
                self.chart_stack.stats_strip.update_stats(st);
            self.statusBar.showMessage(f"绘制: {len(checked)} 通道, {len(set(fid for fid, _, _ in checked))} 文件")

    def _filter_suffix(self, spec):
        """Short trace-name tag for a filtered overlay, e.g. ``LP 50Hz`` /
        ``BP 100–2000Hz``. The trailing ``Hz)`` is the marker the stats path
        uses to exclude filtered overlays from the stats strip."""
        tag = {"low": "LP", "high": "HP", "band": "BP", "bandstop": "BS"}[spec.kind]
        if spec.kind in ("band", "bandstop"):
            return f"{tag} {spec.cutoff_lo:g}–{spec.cutoff_hi:g}Hz"
        return f"{tag} {spec.cutoff:g}Hz"

    def _build_time_plot_data(self, checked=None, custom_x=None,
                              range_enabled=None, range_lo=0.0, range_hi=0.0):
        """Assemble the time-domain plot list
        ``data = [(name, visible, x, sig, color, unit, fid), ...]``.

        Pure w.r.t. ``channel_data`` — it never mutates samples. Each checked
        channel yields its ORIGINAL trace (``visible = show_original``) and, when
        a filter is configured and "显示滤波后" is on, a display-layer FILTERED
        overlay (``visible = show_filtered``) computed per-channel at the
        channel's own ``fs`` via the pure-numpy ``signal.filters`` backend. The
        filtered overlay is display-only; it is not written back anywhere.

        Args default to live UI state so the helper is callable with no args
        for unit tests; ``_plot_time_on_canvas`` passes its already-resolved
        values to avoid recomputing them.
        """
        from ...signal import filters as _filters
        # [perf-probe] 诊断探针，定位后移除。reset 滤波 apply 累计器。
        from ..pg_canvas import _perf_probe as _pp
        _pp.reset_filter_accum()

        if checked is None:
            checked = self.channel_list.get_checked_channels()
        if custom_x is None and self._custom_xaxis_fid and self._custom_xaxis_ch:
            if self._custom_xaxis_fid in self.files:
                xfd = self.files[self._custom_xaxis_fid]
                if self._custom_xaxis_ch in xfd.data.columns:
                    custom_x = xfd.data[self._custom_xaxis_ch].to_numpy(copy=False)
        if range_enabled is None:
            range_enabled = self.inspector.top.range_enabled()
            range_lo, range_hi = self.inspector.top.range_values()

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

        data = []
        for fid, ch, color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns:
                continue
            time_axis = fd.time_array
            # Custom X axis (by reference; the canvas treats arrays as
            # read-only).
            if custom_x is not None and len(custom_x) == len(fd.data):
                x_axis = custom_x
            else:
                x_axis = time_axis
            sig = fd.data[ch].to_numpy(copy=False)
            unit = fd.channel_units.get(ch, '')
            name = fd.get_prefixed_channel(ch)
            # Range controls are always in acquisition time, even when the
            # visible X axis is a channel.
            if range_enabled:
                m = (time_axis >= range_lo) & (time_axis <= range_hi)
                x_axis, sig = x_axis[m], sig[m]
            if len(sig) == 0:
                continue
            data.append((name, show_orig, x_axis, sig, color, unit, fid))

            if filt_enabled:
                fs = float(getattr(fd, "fs", 0.0)) or self._estimate_fs(time_axis)
                try:
                    gspec, _msg = _filters.nyquist_guard(spec, fs)
                except ValueError:
                    # band/bandstop with lo >= hi → draw original only.
                    continue
                with _pp.filter_apply():  # [perf-probe] 累计单次滤波耗时
                    filtered = _filters.apply(sig, gspec, fs)
                fname = f"{name} ({self._filter_suffix(gspec)})"
                self._time_filtered_names.add(fname)
                # 8th field ``meta``: marks this as a display companion of the
                # source channel ``name`` so the canvas overlays it (dashed) on
                # the SAME axis/row instead of allocating a fresh subplot row.
                # Original 7-tuple rows are unchanged → backward compatible.
                meta = {"companion_of": name, "dash": True}
                data.append(
                    (fname, show_filt, x_axis, filtered, color, unit, fid, meta)
                )
        return data

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
        from ..drawers.batch import BatchSheet
        from ...batch import BatchRunner

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
        from ...batch import AnalysisPreset

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

    # Order analysis methods (do_order_time, _dispatch_order_job, _on_order_*, etc.)
    # live in _order_mixin.OrderMixin — composed into MainWindow via its base list.

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

    # FFT-vs-Time methods (do_fft_time, _dispatch_fft_time_job,
    # _fft_time_cache_*, _on_fft_time_*, _render_fft_time*, etc.) live in
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

    # ------------------------------------------------------------------
    # GPU render toggle
    # ------------------------------------------------------------------

    def _on_gpu_render_toggled(self, on: bool):
        # Session-only: no QSettings persistence — GPU always starts OFF on the
        # next launch (see the connect site for rationale).
        self.canvas_time.set_gpu_render(on)
        # pyqtgraph's useOpenGL() SWAPS the viewport widget (setViewport). Curve
        # items built on the PREVIOUS viewport do NOT re-render on the freshly
        # swapped GL viewport — a pan / envelope refresh reuses the same stale
        # items and stays blank; only a full rebuild (plot_channels) paints them
        # (user-confirmed: 开 GPU 后曲线消失，pan 不回来、重新「绘图」才回来). So
        # re-plot here, rebuilding the curves on the new viewport, instead of
        # leaving the chart blank until the user manually re-plots. Gated to the
        # time domain (GPU render only owns the time canvas) and to a loaded
        # file (nothing to draw otherwise); switching back to time re-plots on
        # its own, so an FFT-mode toggle needs no action here.
        if self.files and self.chart_stack.current_mode() == 'time':
            self.plot_time()
