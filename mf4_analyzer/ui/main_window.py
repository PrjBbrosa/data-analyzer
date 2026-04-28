"""MainWindow: top-level QMainWindow assembling the application UI."""
# Phase 2 complete: no legacy shims remain. The 3-pane topology
# (Toolbar + FileNavigator + ChartStack + Inspector) is the only owner
# of state; MainWindow is a router between them.

import numpy as np
import pandas as pd
from pathlib import Path
from collections import OrderedDict

from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt, QTimer, QObject, QThread, pyqtSignal

from ..io import DataLoader, FileData, HAS_ASAMMDF
from ..signal import FFTAnalyzer, OrderAnalyzer
from .canvases import CHART_TIGHT_LAYOUT_KW


class FFTTimeWorker(QObject):
    """Run :class:`SpectrogramAnalyzer.compute` on a worker QThread.

    Plan Task 7. The worker is a plain ``QObject`` (NOT a QThread
    subclass); the canonical Qt pattern is to instantiate the worker on
    the main thread, ``moveToThread(thread)``, and connect
    ``thread.started`` to ``worker.run``. ``finished``/``failed`` both
    quit the thread; the cleanup chain
    (``thread.finished -> worker.deleteLater`` /
    ``thread.deleteLater``) keeps the QThread from leaking.

    The analyzer's ``compute()`` polls ``cancel_token`` at the top of
    every frame (see ``signal/spectrogram.py``); flipping
    ``self._cancelled`` via :meth:`cancel` is the only way to stop a
    running compute mid-loop.
    """

    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, sig, t, params, channel_name, unit):
        super().__init__()
        self.sig = sig
        self.t = t
        self.params = params
        self.channel_name = channel_name
        self.unit = unit
        self._cancelled = False

    def cancel(self):
        """Flip the cancel flag; ``compute`` polls it at every frame."""
        self._cancelled = True

    def run(self):
        from ..signal import SpectrogramAnalyzer
        try:
            result = SpectrogramAnalyzer.compute(
                self.sig,
                self.t,
                self.params,
                channel_name=self.channel_name,
                unit=self.unit,
                progress_callback=self.progress.emit,
                cancel_token=lambda: self._cancelled,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)


class OrderWorker(QThread):
    """Run :meth:`OrderAnalyzer.compute_*` on a worker QThread.

    Plan Task 5 / spec §4.3. Three signals all carry ``generation``;
    :class:`MainWindow` uses a generation-token pattern (independent of
    whether ``cancel()`` ran in time) to decide whether a queued
    ``result_ready`` belongs to the most-recent dispatch or a stale one.

    Unlike :class:`FFTTimeWorker` (a ``QObject`` moved onto a separate
    ``QThread``), this is a ``QThread`` subclass: cleanup is simpler,
    ``cancel()/wait()/terminate()`` all live on the same instance, and
    no ``moveToThread`` plumbing is needed. ``OrderAnalyzer`` polls
    ``cancel_token`` per chunk so cancellation is cooperative.
    """

    result_ready = pyqtSignal(object, str, int)   # (result, kind, generation)
    failed = pyqtSignal(str, int)                  # (message, generation)
    progress = pyqtSignal(int, int, int)           # (current, total, generation)

    def __init__(self, kind, sig, rpm, t, params, generation, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._sig = sig
        self._rpm = rpm
        self._t = t
        self._params = params
        self._generation = int(generation)
        self._cancelled = False

    def cancel(self):
        """Flip the cancel flag; ``OrderAnalyzer`` polls it per chunk."""
        self._cancelled = True

    def run(self):
        from ..signal import OrderAnalyzer
        gen = self._generation
        try:
            cb_progress = lambda i, n: self.progress.emit(i, n, gen)
            cb_cancel = lambda: self._cancelled
            if self._kind == 'time':
                r = OrderAnalyzer.compute_time_order_result(
                    self._sig, self._rpm, self._t, self._params,
                    progress_callback=cb_progress, cancel_token=cb_cancel,
                )
            else:
                raise ValueError(f"unknown kind: {self._kind}")
            if self._cancelled:
                # Cancel landed after compute returned but before emit;
                # let MainWindow's generation check drop any leftover.
                return
            self.result_ready.emit(r, self._kind, gen)
        except RuntimeError as e:
            # OrderAnalyzer raises RuntimeError("...cancelled...") when
            # the cancel_token returns truthy; treat that as silent exit.
            if 'cancel' in str(e).lower():
                return
            self.failed.emit(str(e), gen)
        except Exception as e:
            self.failed.emit(str(e), gen)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MF4/CSV/Excel 数据分析工具 v5.0 - 多文件支持")
        self.setGeometry(100, 100, 1450, 850);
        # Spec §9 minimum window size: 1100 × 640.
        self.setMinimumSize(1100, 640)
        self.files = OrderedDict();
        self._fc = 0;
        self._active = None
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
        # Order worker (Plan Task 5). ``_order_worker`` is the live
        # :class:`OrderWorker` (a QThread subclass) or None;
        # ``_order_generation`` is a monotonically-increasing token used
        # by :meth:`_dispatch_order_worker` so stale signals from a
        # cancelled-but-still-emitting worker can be discarded by
        # comparing ``generation`` in the slots.
        self._order_worker = None
        self._order_generation = 0
        self._last_batch_preset = None
        self._init_ui();
        self._connect()

    def _init_ui(self):
        from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget
        from PyQt5.QtCore import Qt

        from .chart_stack import ChartStack
        from .file_navigator import FileNavigator
        from .inspector import Inspector
        from .toolbar import Toolbar

        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.toolbar = Toolbar(self)
        root.addWidget(self.toolbar)

        splitter = QSplitter(Qt.Horizontal, self)
        self.navigator = FileNavigator(self)
        self.chart_stack = ChartStack(self)
        self.inspector = Inspector(self)
        splitter.addWidget(self.navigator)
        splitter.addWidget(self.chart_stack)
        splitter.addWidget(self.inspector)
        # 2026-04-26 R3 紧凑化 fix-5: align the inspector splitter slot with
        # the fixed visible Inspector width (360). The 60px bump from 300→360
        # prevents a visible gap on first launch where the splitter would
        # otherwise hand the inspector less width than its content needs.
        splitter.setSizes([250, 900, 360])
        # 2026-04-26 inspector 右侧空白二次修复:
        # Without explicit stretch factors, QSplitter distributes window-resize
        # growth proportionally across panes by current size. That gives the
        # inspector pane more "slot" width than its setMaximumWidth(376), and
        # the surplus inside the slot reads as a visible empty column. Pin the
        # chart stack as the only stretchy pane; navigator and inspector keep
        # their initial sizes regardless of window width.
        splitter.setStretchFactor(0, 0)  # navigator: no stretch
        splitter.setStretchFactor(1, 1)  # chart_stack: absorbs all extra width
        splitter.setStretchFactor(2, 0)  # inspector: no stretch
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        splitter.setHandleWidth(3)
        self.navigator.setMinimumWidth(220)
        self.chart_stack.setMinimumWidth(400)
        self.inspector.setMinimumWidth(self.inspector.maximumWidth())
        root.addWidget(splitter, stretch=1)

        # Convenience aliases pointing to children of ChartStack / Navigator —
        # these are real widgets reachable via the new topology, not shims.
        self.canvas_time = self.chart_stack.canvas_time
        self.canvas_fft = self.chart_stack.canvas_fft
        self.canvas_order = self.chart_stack.canvas_order
        self.canvas_fft_time = self.chart_stack.canvas_fft_time
        self.channel_list = self.navigator.channel_list

        from PyQt5.QtWidgets import QStatusBar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")

        # Floating toast (constructed lazily on first use; the parent must
        # be the main window so the toast floats above the central canvas).
        from .widgets import Toast
        self._toast = Toast(self)

    # ---- public toast helper ----
    def toast(self, msg, level='info'):
        """Show a transient acknowledgement toast at the bottom of the window."""
        if not msg:
            return
        self._toast.show_message(msg, level=level)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, '_toast') and self._toast.isVisible():
            self._toast._reposition()

    def _connect(self):
        # --- New-module wiring ---
        self.toolbar.file_add_requested.connect(self.load_files)
        self.toolbar.channel_editor_requested.connect(self.open_editor)
        self.toolbar.export_requested.connect(self.export_excel)
        self.toolbar.batch_requested.connect(self.open_batch)
        self.toolbar.mode_changed.connect(self._on_mode_changed)
        self.chart_stack.image_copied.connect(
            lambda msg: (self.statusBar.showMessage(msg, 2000),
                         self.toast(msg, 'success'))
        )
        self.inspector.preset_acknowledged.connect(
            lambda level, msg: self.toast(msg, level)
        )

        self.navigator.channels_changed.connect(self._ch_changed)
        self.navigator.file_activated.connect(self._on_file_activated)
        self.navigator.file_close_requested.connect(self._on_file_close_requested)
        self.navigator.close_all_requested.connect(self._on_close_all_requested)

        # Canvas cursor signals are owned by ChartStack; MainWindow doesn't
        # need to subscribe (ChartStack updates the pill itself).

        # Inspector signals wire up in Phase 2 when real sections land. In
        # Phase 1, these are no-ops but must exist so Task 2.x edits are
        # minimal additions rather than rewrites.
        self.inspector.plot_time_requested.connect(self.plot_time)
        self.inspector.fft_requested.connect(self.do_fft)
        self.inspector.order_time_requested.connect(self.do_order_time)
        # T6: Inspector publishes a cancel intent without knowing about
        # the worker; MainWindow translates it into ``OrderWorker.cancel``.
        self.inspector.order_ctx.cancel_requested.connect(
            self._cancel_order_compute
        )
        self.inspector.xaxis_apply_requested.connect(self._apply_xaxis)
        self.inspector.rebuild_time_requested.connect(self._show_rebuild_popover)
        self.inspector.tick_density_changed.connect(self._update_all_tick_density_pair)
        self.inspector.remark_toggled.connect(self.canvas_fft.set_remark_enabled)
        self.chart_stack.cursor_mode_changed.connect(self._on_cursor_mode_changed)
        self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)
        self.inspector.signal_changed.connect(self._on_inspector_signal_changed)

        # FFT vs Time wiring (Plan Task 6 + Task 9 export).
        # The Inspector relays compute / force / export buttons.
        self.inspector.fft_time_requested.connect(
            lambda: self.do_fft_time(force=False)
        )
        self.inspector.fft_time_force_requested.connect(
            lambda: self.do_fft_time(force=True)
        )
        # Export buttons → clipboard pixmap (Plan Task 9).
        self.inspector.fft_time_export_full_requested.connect(
            lambda: self._copy_fft_time_image(mode='full')
        )
        self.inspector.fft_time_export_main_requested.connect(
            lambda: self._copy_fft_time_image(mode='main')
        )
        # Fs auto-sync for fft_time_ctx — mirrors what
        # _on_inspector_signal_changed does for fft / order via the
        # original Inspector.signal_changed channel. Routed through the
        # T6 reviewer Important #2 relay so the panel's Fs spinbox
        # tracks the selected signal's source-file Fs.
        self.inspector.fft_time_signal_changed.connect(
            self._on_fft_time_signal_changed
        )
        # Hover readout: surface SpectrogramCanvas.cursor_info in the
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
        self._axis_lock_widget = None
        # Phase 1 item 4: track range-filter and plot-mode state across
        # plot_time() calls so we can fire the appropriate envelope-cache
        # invalidation when either changes (the cache is keyed on raw
        # (data_id, channel, xlim, pixel_width) and does NOT know whether
        # the source arrays were range-filtered or which plot layout was
        # active when the entry was inserted).
        self._last_range_state = None   # (enabled, lo, hi) or None
        self._last_plot_mode = None     # 'overlay' / 'subplot' / None

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
            QTimer.singleShot(0, self.plot_time)

    def _on_cursor_mode_changed(self, mode):
        self.canvas_time.set_cursor_visible(mode != 'off')
        self.canvas_time.set_dual_cursor_mode(mode == 'dual')

    def _on_plot_mode_changed(self, mode):
        self.plot_time()

    def _update_all_tick_density_pair(self, xt, yt):
        self.canvas_time.set_tick_density(xt, yt)
        from matplotlib.ticker import MaxNLocator
        for ax in self.canvas_fft.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_fft.draw_idle()
        for ax in self.canvas_order.fig.axes:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=xt, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=yt, min_n_ticks=3))
        self.canvas_order.draw_idle()

    def _show_axis_lock_popover(self, anchor):
        from .drawers.axis_lock_popover import AxisLockPopover
        current = self.canvas_time._axis_lock or 'none'
        pop = AxisLockPopover(self, current=current)
        pop.lock_changed.connect(self.canvas_time.set_axis_lock)
        pop.show_at(anchor)

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
                self.inspector.top.set_range_limits(0, fd.time_array[-1])
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
            cands = []
            for fid, fd in self.files.items():
                px = f"[{fd.short_name}] "
                for ch in fd.channels:
                    cands.append((px + ch, (fid, ch)))
            self.inspector.top.set_xaxis_candidates(cands)

    def _apply_xaxis(self):
        """应用横坐标设置"""
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
            self._custom_xlabel = self.inspector.top.xaxis_label() or ch

        # Cache invalidation site 5: the t-array bound to every plotted
        # channel just changed (time-axis ↔ custom-channel x-axis), so
        # every (data_id, channel, xlim, pixel_width) entry is now stale.
        # Monotonicity cache is also re-keyed by the new fid/ch pair, so
        # wipe it to be safe.
        self.canvas_time.invalidate_envelope_cache("custom-x changed")
        self.canvas_time.invalidate_monotonicity_cache()
        # FFT vs Time cache: custom-x semantics shift the time_range
        # interpretation for every fid that the user might subsequently
        # compute against; wholesale clear is safe at capacity 12 and
        # matches T5's recommendation in the cache-invalidation handoff.
        self._fft_time_cache.clear()
        # 重新绘图
        self.plot_time()
        self.statusBar.showMessage(f"横坐标已更新")
        self.toast("横坐标已更新", "success")

    def _reset_cursors(self):
        """Reset both single and dual cursor state on the time-domain canvas."""
        self.canvas_time._ax = self.canvas_time._bx = None
        self.canvas_time._placing = 'A'
        self.canvas_time._refresh = True
        self.canvas_time.draw_idle()
        self.chart_stack.clear_cursor_pill()
        self.statusBar.showMessage("游标已重置")
        self.toast("游标已重置", "info")

    def load_files(self):
        fps, _ = QFileDialog.getOpenFileNames(self, "选择文件", "", "All (*.mf4 *.csv *.xlsx *.xls)")
        for fp in fps: self._load_one(fp)

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
            self._update_combos()
            if fd.time_array is not None and len(fd.time_array):
                current_hi = self.inspector.top.spin_end.maximum()
                new_hi = max(current_hi, fd.time_array[-1])
                self.inspector.top.set_range_limits(0, new_hi)
                if len(self.files) == 1:
                    self.inspector.top.spin_end.setValue(fd.time_array[-1])
            self.channel_list.check_first_channel(fid)
            QTimer.singleShot(100, self.plot_time)
            self._update_info()
            self.statusBar.showMessage(f"✅ 已加载: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
            self.toast(f"已加载 {p.name} · {len(data)} 行", "success")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def close_active(self):
        if self._active: self._close(self._active)

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
        # Invalidate custom X axis pointer if source gone
        if self._custom_xaxis_fid is not None and self._custom_xaxis_fid not in self.files:
            self._custom_xaxis_fid = None
            self._custom_xaxis_ch = None
            self._custom_xlabel = None
            self.inspector.top.set_xaxis_mode('time')
        # Refill candidates if still in channel mode
        if self.inspector.top.xaxis_mode() == 'channel':
            self._on_xaxis_mode_changed('channel')
        self._update_combos()
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

    def _ch_changed(self):
        # Cache invalidation site 4: the visible channel set changed, so
        # the Line2D map plot_channels rebuilds will not match the cache
        # entries from the prior selection. Drop everything; the next
        # plot_time() will re-prime as needed.
        self.canvas_time.invalidate_envelope_cache("selection changed")
        if self.files and self.chart_stack.current_mode() == 'time':
            self.plot_time()

    def _on_span(self, xmin, xmax):
        self.inspector.top.set_range_from_span(xmin, xmax)
        st = self.canvas_time.get_statistics(time_range=(xmin, xmax))
        self.chart_stack.stats_strip.update_stats(st or {})

    def plot_time(self):
        if not self.files: self.canvas_time.clear(); self.canvas_time.draw(); self.chart_stack.stats_strip.update_stats({}); return
        checked = self.channel_list.get_checked_channels()
        if not checked: self.canvas_time.clear(); self.canvas_time.draw(); self.chart_stack.stats_strip.update_stats({}); return

        mode = self.chart_stack.plot_mode()
        # Cache invalidation site 7: structural plot-mode change (overlay
        # ↔ subplot) reuses the same (data_id, channel) keys but the line
        # ownership switches between an axes-stack and a single ax with
        # twinx siblings. To keep cached envelopes from rendering on the
        # wrong axes, drop them when the layout changes.
        if self._last_plot_mode is not None and self._last_plot_mode != mode:
            self.canvas_time.invalidate_envelope_cache("plot mode changed")
        self._last_plot_mode = mode
        if mode == 'overlay' and len(checked) > 5:
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
        if (self._last_range_state is not None
                and self._last_range_state != cur_range_state):
            self.canvas_time.invalidate_envelope_cache("range filter changed")
        self._last_range_state = cur_range_state

        data = [];
        st = {}
        for fid, ch, color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns: continue

            # 使用自定义横坐标或默认时间轴 — by reference; the canvas
            # treats these arrays as read-only.
            if custom_x is not None and len(custom_x) == len(fd.data):
                t = custom_x
            else:
                t = fd.time_array

            sig = fd.data[ch].to_numpy(copy=False)
            unit = fd.channel_units.get(ch, '');
            name = fd.get_prefixed_channel(ch)
            # Only allocate filtered arrays when the user actually asked
            # for range filtering — otherwise pass the originals through.
            if range_enabled:
                m = (t >= range_lo) & (t <= range_hi)
                t, sig = t[m], sig[m]
            if len(sig) == 0: continue
            # Statistics are computed from the (post-range-filter)
            # original samples — never from envelope output.
            data.append((name, True, t, sig, color, unit, fid))
            st[name] = {'min': np.min(sig), 'max': np.max(sig), 'mean': np.mean(sig), 'rms': np.sqrt(np.mean(sig ** 2)),
                        'std': np.std(sig), 'p2p': np.ptp(sig), 'unit': unit}
        if not data: self.canvas_time.clear(); self.canvas_time.draw(); self.chart_stack.stats_strip.update_stats({}); return

        xlabel = self._custom_xlabel or self.inspector.top.xaxis_label() or 'Time (s)'
        self.canvas_time.plot_channels(data, mode, xlabel=xlabel)
        xt, yt = self.inspector.top.tick_density()
        self.canvas_time.set_tick_density(xt, yt)
        self.canvas_time.enable_span_selector(self._on_span);
        self.chart_stack.stats_strip.update_stats(st);
        self.statusBar.showMessage(f"绘制: {len(checked)} 通道, {len(set(fid for fid, _, _ in checked))} 文件")

    def open_editor(self):
        if not self.files or not self._active or self._active not in self.files:
            self.toast("请先加载文件", "warning")
            return
        fd = self.files[self._active]
        from .drawers.channel_editor_drawer import ChannelEditorDrawer
        drawer = ChannelEditorDrawer(self, fd)
        drawer.applied.connect(lambda nc, rm: self._apply_channel_edits(self._active, nc, rm))
        drawer.exec_()


    def _apply_channel_edits(self, fid, new_channels, removed_channels):
        fd = self.files[fid]
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
        self.navigator.remove_file(fid)
        self.navigator.add_file(fid, fd)
        self._update_combos()
        self.statusBar.showMessage(
            f"编辑: +{len(new_channels)} -{len(removed_channels)}"
        )
        self.toast(
            f"通道已更新: 新增 {len(new_channels)} · 删除 {len(removed_channels)}",
            "success",
        )
        self.plot_time()

    def export_excel(self):
        if not self.files or not self._active:
            self.toast("请先加载文件", "warning"); return
        fd = self.files[self._active];
        chs = fd.get_signal_channels()
        if not chs: return
        from .drawers.export_sheet import ExportSheet
        dlg = ExportSheet(self, chs)
        if dlg.exec_() == QDialog.Accepted:
            sel = dlg.get_selected()
            if not sel: return
            fp, _ = QFileDialog.getSaveFileName(self, "保存", "", "Excel (*.xlsx)")
            if not fp: return
            try:
                df = pd.DataFrame()
                if dlg.chk_time.isChecked() and fd.time_array is not None: df['Time'] = fd.time_array
                for ch in sel:
                    if ch in fd.data.columns: df[ch] = fd.data[ch].values
                if dlg.chk_range.isChecked() and fd.time_array is not None:
                    lo, hi = self.inspector.top.range_values()
                    m = (fd.time_array >= lo) & (fd.time_array <= hi);
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
        if not self.files:
            self.toast("请先加载文件", "warning")
            return
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
        """Pre-flight non-uniform time-axis check, run BEFORE worker dispatch.

        Returns ``True`` when ``fd.time_array`` is uniform-enough for
        ``SpectrogramAnalyzer._validate_time_axis`` to accept, OR when
        the user accepted the rebuild popover (in which case
        ``fd.time_array`` is now ``arange(n)/fs`` -- guaranteed
        uniform). Returns ``False`` when the axis is non-uniform AND
        the user dismissed the popover; the caller must abort.

        ``mode`` selects the popover anchor (``'fft'`` -> the standard
        FFT contextual's ``btn_rebuild``; ``'fft_time'`` -> the FFT vs
        Time contextual's ``btn_rebuild``; ``'order'`` -> the order
        contextual's ``btn_rebuild``).

        T2 (2026-04-26): collapses the prior worker -> failed -> popover
        -> retry round-trip into a single synchronous gate. This also
        eliminates the H4 latent bug in ``_fft_time_retry_pending``
        lifecycle (the flag was cleared in ``_retry``'s ``finally``
        before the worker could ever fail again). See
        ``docs/superpowers/reports/2026-04-26-nonuniform-fft-T2-fix.md``.
        """
        if fd is None or not hasattr(fd, 'is_time_axis_uniform'):
            # Either no file selected, or a duck-typed stand-in (test
            # fakes) that has no axis to validate. Defer to the worker.
            return True
        if fd.is_time_axis_uniform():
            return True
        # Seed the popover's spin_fs with the median-dt estimate so the
        # user only has to confirm rather than retype Fs from scratch.
        if hasattr(fd, 'suggested_fs_from_time_axis'):
            suggested = fd.suggested_fs_from_time_axis()
            if np.isfinite(suggested) and suggested > 0:
                fd.fs = float(suggested)
        if mode == 'fft':
            anchor = self.inspector.fft_ctx.btn_rebuild
        elif mode == 'fft_time':
            anchor = self.inspector.fft_time_ctx.btn_rebuild
        else:
            anchor = self.inspector.order_ctx.btn_rebuild
        self.toast(
            "时间轴非均匀，无法直接做时频分析。"
            "已为你打开“重建时间轴”，请确认 Fs 后重试。",
            "warning",
        )
        self.statusBar.showMessage("时间轴非均匀，请重建后重试")
        return self._show_rebuild_popover(anchor, mode=mode)

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

            self.canvas_fft.clear()

            # 自适应频率范围计算
            if fft_params['autoscale']:
                x_max = self._fft_auto_xlim(freq, amp)
            else:
                x_max = fs / 2

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

            ax1 = self.canvas_fft.fig.add_subplot(2, 1, 1)
            ax1.plot(freq, amp_disp, '#2563eb', lw=1.0);
            ax1.set_xlabel('Frequency (Hz)');
            ax1.set_ylabel(
                'Amplitude (dB)' if amp_y == 'dB' else 'Amplitude',
                labelpad=10,
            )
            ax1.set_title(f'FFT - {self.inspector.fft_ctx.combo_sig.currentText()} (窗:{win}, NFFT:{nfft or "auto"})');
            ax1.grid(True, alpha=0.25, ls='--');
            ax1.set_xlim(0, x_max)
            ax2 = self.canvas_fft.fig.add_subplot(2, 1, 2)
            ax2.plot(freq, psd_disp, '#dc2626', lw=1.0);
            ax2.set_xlabel('Frequency (Hz)');
            ax2.set_ylabel(
                'PSD (dB)' if psd_y == 'dB' else 'PSD',
                labelpad=10,
            )
            ax2.set_title('功率谱密度');
            ax2.grid(True, alpha=0.25, ls='--');
            ax2.set_xlim(0, x_max)

            # 存储曲线数据用于remark吸附
            self.canvas_fft.store_line_data(0, freq, amp_disp)
            self.canvas_fft.store_line_data(1, freq, psd_disp)

            self.canvas_fft.fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
            xt, yt = self.inspector.top.tick_density()
            self.canvas_fft.set_tick_density(xt, yt)
            self.canvas_fft.draw();
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
    # Order analysis (Plan Task 5: dispatch on OrderWorker QThread)
    # ------------------------------------------------------------------
    # The synchronous `_order_progress + QApplication.processEvents()`
    # path was deleted in T5; progress is now signalled via
    # `OrderWorker.progress` and consumed by `_on_order_progress`. Slot
    # methods compare the carried `generation` against
    # `self._order_generation` so a stale worker that has been
    # cancelled-but-not-yet-stopped cannot mutate UI on the main thread.
    # See spec §4.3 and lessons:
    #   - pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md
    #   - pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md
    #   - pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md

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
        # Wave 4 / Task 4.2: pull current_params (extends get_params with
        # algorithm + samples_per_rev) and branch on algorithm. Default
        # 'frequency' keeps the existing async OrderWorker dispatch path
        # so progress/cancel/generation tracking are untouched. The 'cot'
        # branch runs COTOrderAnalyzer synchronously on the GUI thread —
        # acceptable for v1 wiring; an async COT worker is out of scope.
        order_params = self.inspector.order_ctx.current_params()
        algorithm = order_params.get('algorithm', 'frequency')
        op = self.inspector.order_ctx.get_params()
        if algorithm == 'cot':
            from ..signal.order_cot import COTOrderAnalyzer, COTParams
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
                self.statusBar.showMessage('计算时间-阶次谱 (COT)...')
                self.inspector.order_ctx.set_progress("计算中...")
                result = COTOrderAnalyzer.compute(sig, rpm, t, p)
            except Exception as e:
                self.inspector.order_ctx.set_progress("")
                QMessageBox.critical(self, "错误", str(e))
                return
            self.inspector.order_ctx.set_progress("")
            self._render_order_time(result)
            return

        from ..signal.order import OrderAnalysisParams
        params = OrderAnalysisParams(
            fs=fs,
            nfft=int(op['nfft']),
            window=op.get('window', 'hanning'),
            max_order=float(op['max_order']),
            order_res=float(op['order_res']),
            time_res=float(op['time_res']),
        )
        self._dispatch_order_worker('time', sig, rpm, t, params,
                                     status_msg='计算时间-阶次谱...')

    def _cancel_order_compute(self):
        """Slot for ``OrderContextual.cancel_requested``.

        Cancellation is cooperative: ``OrderWorker.cancel`` flips a flag
        that ``compute_*`` polls between batches, so the worker thread
        keeps running until the next checkpoint. We update the status
        bar + clear the progress label immediately so the user gets
        feedback even before the worker actually exits. The button
        itself is disabled by ``_on_order_result`` / ``_on_order_failed``
        once the worker emits its terminal signal — disabling it here
        would make the UI lie if the worker manages to finish before
        the cancel flag is sampled.
        """
        worker = getattr(self, '_order_worker', None)
        if worker is not None and worker.isRunning():
            worker.cancel()
            self.statusBar.showMessage('阶次计算已取消')
            self.inspector.order_ctx.set_progress("")

    def _dispatch_order_worker(self, kind, sig, rpm, t, params, *, status_msg):
        """Spin up an :class:`OrderWorker`, cancelling any predecessor.

        Increments ``_order_generation`` first so signals from a worker
        we are about to abort can be discarded by the slots'
        generation-equality check, even if the queued slot fires after
        ``cancel()`` (cancel is cooperative, not instantaneous).
        """
        # 1. Bump generation token; the new worker carries it forward
        #    and the slots compare against this value.
        self._order_generation = getattr(self, '_order_generation', 0) + 1
        gen = self._order_generation

        # 2. Cancel + disconnect the previous worker if still running.
        old = getattr(self, '_order_worker', None)
        if old is not None and old.isRunning():
            try:
                old.result_ready.disconnect()
                old.failed.disconnect()
                old.progress.disconnect()
            except TypeError:
                pass
            old.cancel()
            if not old.wait(2000):
                # wait timed out — escalate to terminate; give 500 ms
                # for the OS to actually reap the thread.
                old.terminate()
                old.wait(500)

        # 3. Build the new worker and wire signals.
        worker = OrderWorker(kind, sig, rpm, t, params,
                              generation=gen, parent=self)
        worker.progress.connect(self._on_order_progress)
        worker.result_ready.connect(self._on_order_result)
        worker.failed.connect(self._on_order_failed)
        self._order_worker = worker
        self.statusBar.showMessage(status_msg)
        self.inspector.order_ctx.set_progress("0%")
        # T6: btn_cancel is now part of OrderContextual unconditionally,
        # so call setEnabled directly without a defensive getattr.
        self.inspector.order_ctx.btn_cancel.setEnabled(True)
        worker.start()

    def _on_order_progress(self, current, total, generation):
        if generation != getattr(self, '_order_generation', -1):
            return  # stale; drop
        if total > 0:
            self.inspector.order_ctx.set_progress(
                f"{int(current / total * 100)}%"
            )

    def _on_order_failed(self, msg, generation):
        if generation != getattr(self, '_order_generation', -1):
            return  # stale; drop
        self.inspector.order_ctx.set_progress("")
        self.inspector.order_ctx.btn_cancel.setEnabled(False)
        QMessageBox.critical(self, "错误", msg)

    def _on_order_result(self, result, kind, generation):
        if generation != getattr(self, '_order_generation', -1):
            return  # stale; drop
        self.inspector.order_ctx.set_progress("")
        self.inspector.order_ctx.btn_cancel.setEnabled(False)
        if kind == 'time':
            self._render_order_time(result)

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
            dynamic=order_params.get('dynamic', '30 dB'),
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

    def closeEvent(self, event):
        """Stop every running worker before the window is destroyed.

        Two distinct lifecycles to handle (spec §4.3):

        1. ``_order_worker`` — a :class:`OrderWorker` (QThread subclass)
           with built-in ``cancel() + isRunning()``. Cancel, wait, and
           on timeout escalate to ``terminate()``.

        2. ``_fft_time_thread + _fft_time_worker`` — a
           ``QObject + QThread`` pair (see :class:`FFTTimeWorker` /
           :meth:`do_fft_time` near ``main_window.py:1469-1495``). The
           worker has ``cancel()`` (sets a flag the analyzer polls per
           frame); the thread is what owns ``isRunning()``. The wired
           ``thread.finished -> deleteLater`` chain handles cleanup —
           we just need to give it time to run via ``quit() + wait()``.
        """
        # 1. order worker (QThread subclass)
        order_worker = getattr(self, '_order_worker', None)
        if order_worker is not None and order_worker.isRunning():
            try:
                order_worker.result_ready.disconnect()
                order_worker.failed.disconnect()
                order_worker.progress.disconnect()
            except (TypeError, AttributeError):
                pass
            order_worker.cancel()
            if not order_worker.wait(2000):
                order_worker.terminate()
                order_worker.wait(500)

        # 2. FFT-vs-Time (QObject worker + QThread)
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
        Cache misses dispatch :class:`FFTTimeWorker` on a ``QThread``;
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
        worker = FFTTimeWorker(sig, t, params, channel_name=ch, unit=unit)
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
        self.canvas_fft_time.plot_result(
            result,
            amplitude_mode=p['amplitude_mode'],
            cmap=p['cmap'],
            dynamic=p['dynamic'],
            freq_range=freq_range,
        )

    def _on_fft_time_cursor_info(self, text):
        """Surface SpectrogramCanvas hover readout in the status bar.

        Empty text (cursor outside ``_ax_spec`` or before a result is
        plotted) restores the active-file summary so the bar does not
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
        the matplotlib canvas here.
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
        the full grab transparently (see SpectrogramCanvas.grab_main_chart).

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
