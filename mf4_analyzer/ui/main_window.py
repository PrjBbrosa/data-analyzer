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
from PyQt5.QtCore import Qt, QTimer

from ..io import DataLoader, FileData, HAS_ASAMMDF
from ..signal import FFTAnalyzer, OrderAnalyzer


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
        splitter.setSizes([250, 900, 300])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        splitter.setHandleWidth(3)
        self.navigator.setMinimumWidth(220)
        self.chart_stack.setMinimumWidth(400)
        self.inspector.setMinimumWidth(280)
        root.addWidget(splitter, stretch=1)

        # Convenience aliases pointing to children of ChartStack / Navigator —
        # these are real widgets reachable via the new topology, not shims.
        self.canvas_time = self.chart_stack.canvas_time
        self.canvas_fft = self.chart_stack.canvas_fft
        self.canvas_order = self.chart_stack.canvas_order
        self.channel_list = self.navigator.channel_list

        from PyQt5.QtWidgets import QStatusBar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")

    def _connect(self):
        # --- New-module wiring ---
        self.toolbar.file_add_requested.connect(self.load_files)
        self.toolbar.channel_editor_requested.connect(self.open_editor)
        self.toolbar.export_requested.connect(self.export_excel)
        self.toolbar.mode_changed.connect(self._on_mode_changed)
        self.toolbar.cursor_reset_requested.connect(self._reset_cursors)
        self.toolbar.axis_lock_requested.connect(self._show_axis_lock_popover)

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
        self.inspector.order_rpm_requested.connect(self.do_order_rpm)
        self.inspector.order_track_requested.connect(self.do_order_track)
        self.inspector.xaxis_apply_requested.connect(self._apply_xaxis)
        self.inspector.rebuild_time_requested.connect(self._show_rebuild_popover)
        self.inspector.tick_density_changed.connect(self._update_all_tick_density_pair)
        self.inspector.remark_toggled.connect(self.canvas_fft.set_remark_enabled)
        self.chart_stack.cursor_mode_changed.connect(self._on_cursor_mode_changed)
        self.chart_stack.plot_mode_changed.connect(self._on_plot_mode_changed)
        self.inspector.signal_changed.connect(self._on_inspector_signal_changed)

        # Populate xaxis channel candidates whenever user flips to 'channel' mode.
        self.inspector.top.combo_xaxis.currentIndexChanged.connect(
            lambda i: self._on_xaxis_mode_changed('channel' if i == 1 else 'time')
        )

        # Custom X axis state (unchanged)
        self._custom_xlabel = None
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        self._plot_mode = 'subplot'
        self._axis_lock_widget = None

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
        self._plot_mode = mode
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
        from PyQt5.QtWidgets import QDialog, QMessageBox
        if mode == 'fft':
            sig_data = self.inspector.fft_ctx.current_signal()
        else:
            sig_data = self.inspector.order_ctx.current_signal()
        target_fid = sig_data[0] if sig_data and sig_data[0] in self.files else self._active
        if not target_fid or target_fid not in self.files:
            QMessageBox.warning(self, "提示", "请先选择信号")
            return
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
            for ctx in (self.inspector.fft_ctx, self.inspector.order_ctx):
                sig_data = ctx.current_signal()
                if sig_data is not None and sig_data[0] == target_fid:
                    ctx.set_fs(new_fs)
            self.plot_time()
            self.statusBar.showMessage(
                f"时间轴已重建: {fd.short_name} | Fs={new_fs} | {old_max:.1f}s → {new_max:.3f}s"
            )

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
            for ctx in (self.inspector.fft_ctx, self.inspector.order_ctx):
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
        # Navigator already confirmed; skip the second confirm here
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
                QMessageBox.warning(self, "提示", "请选择横坐标通道")
                return
            fid, ch = data
            if fid not in self.files or ch not in self.files[fid].data.columns:
                QMessageBox.warning(self, "提示", "横坐标通道不存在")
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
                    QMessageBox.warning(
                        self, "提示",
                        "横坐标通道长度与当前绘图通道所在文件不匹配",
                    )
                    return
            self._custom_xaxis_fid = fid
            self._custom_xaxis_ch = ch
            self._custom_xlabel = self.inspector.top.xaxis_label() or ch

        # 重新绘图
        self.plot_time()
        self.statusBar.showMessage(f"横坐标已更新")

    def _reset_cursors(self):
        """Reset both single and dual cursor state on the time-domain canvas."""
        self.canvas_time._ax = self.canvas_time._bx = None
        self.canvas_time._placing = 'A'
        self.canvas_time._refresh = True
        self.canvas_time.draw_idle()
        # Clear the ChartStack-owned cursor pill (no more lbl_cursor/lbl_dual)
        self.chart_stack._cursor_pill.setText("")
        self.chart_stack._cursor_dual_pill.setText("")
        self.chart_stack._cursor_pill.setVisible(False)
        self.chart_stack._cursor_dual_pill.setVisible(False)
        self.statusBar.showMessage("游标已重置")

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
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def close_active(self):
        if self._active: self._close(self._active)

    def _close(self, fid):
        if fid not in self.files: return
        del self.files[fid]
        self.navigator.remove_file(fid)
        self._active = self.navigator._active_fid  # navigator picks fallback
        self._update_info()
        self._reset_plot_state(scope='file')
        self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")

    def close_all(self):
        if not self.files:
            return
        for fid in list(self.files.keys()):
            del self.files[fid]
            self.navigator.remove_file(fid)
        self._active = None
        self._update_info()
        self._reset_plot_state(scope='all')
        self.statusBar.showMessage("已关闭全部")

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
        # Cursor pill (ChartStack owns both)
        self.chart_stack._cursor_pill.setText("")
        self.chart_stack._cursor_pill.setVisible(False)
        self.chart_stack._cursor_dual_pill.setText("")
        self.chart_stack._cursor_dual_pill.setVisible(False)
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
        self.inspector.order_ctx.set_signal_candidates(sig_cands)
        self.inspector.order_ctx.set_rpm_candidates(rpm_cands)

    def _ch_changed(self):
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
        if mode == 'overlay' and len(checked) > 5:
            ans = QMessageBox.question(
                self, "确认",
                f"overlay 下 {len(checked)} 个通道会产生 {len(checked)} 根 Y 轴，右侧可能拥挤。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return

        # 获取自定义横坐标数据
        custom_x = None
        if self._custom_xaxis_fid and self._custom_xaxis_ch:
            if self._custom_xaxis_fid in self.files:
                xfd = self.files[self._custom_xaxis_fid]
                if self._custom_xaxis_ch in xfd.data.columns:
                    custom_x = xfd.data[self._custom_xaxis_ch].values.copy()

        range_enabled = self.inspector.top.range_enabled()
        range_lo, range_hi = self.inspector.top.range_values()

        data = [];
        st = {}
        for fid, ch, color in checked:
            fd = self.channel_list.get_file_data(fid)
            if fd is None or ch not in fd.data.columns: continue

            # 使用自定义横坐标或默认时间轴
            if custom_x is not None and len(custom_x) == len(fd.data):
                t = custom_x.copy()
            else:
                t = fd.time_array.copy()

            sig = fd.data[ch].values.copy()
            unit = fd.channel_units.get(ch, '');
            name = fd.get_prefixed_channel(ch)
            if range_enabled:
                m = (t >= range_lo) & (t <= range_hi)
                t, sig = t[m], sig[m]
            if len(sig) == 0: continue
            data.append((name, True, t, sig, color, unit))
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
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请先加载文件")
            return
        fd = self.files[self._active]
        from .drawers.channel_editor_drawer import ChannelEditorDrawer
        drawer = ChannelEditorDrawer(self, fd)
        drawer.applied.connect(lambda nc, rm: self._apply_channel_edits(self._active, nc, rm))
        drawer.exec_()


    def _apply_channel_edits(self, fid, new_channels, removed_channels):
        fd = self.files[fid]
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
        self.plot_time()

    def export_excel(self):
        if not self.files or not self._active: QMessageBox.warning(self, "提示", "请先加载文件"); return
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
                QMessageBox.information(self, "成功", f"导出: {len(df)} 行 × {len(df.columns)} 列")
            except Exception as e:
                QMessageBox.critical(self, "错误", str(e))

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
            QMessageBox.warning(self, "提示", "请选择转速信号")
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
            QMessageBox.warning(self, "提示", f"长度不匹配 ({n} vs {len(rpm)})")
            return None
        return rpm

    @staticmethod
    def _fft_auto_xlim(freq, amp):
        """自适应计算FFT频率范围，取整到 1/2/5/10/20/50/100... 序列"""
        if len(freq) < 2 or len(amp) < 2:
            return freq[-1] if len(freq) else 100
        # 找到包含99%能量的频率
        cumulative = np.cumsum(amp ** 2)
        total = cumulative[-1]
        if total < 1e-20:
            return freq[-1]
        # 99%能量截止
        idx_99 = np.searchsorted(cumulative, total * 0.99)
        f_cutoff = freq[min(idx_99, len(freq) - 1)]
        # 给一些余量 (1.2x)
        f_cutoff *= 1.2
        # 取整到好看的数值序列: 1, 2, 5, 10, 20, 50, 100, 200, 500 ...
        nice_vals = []
        for exp in range(-1, 7):
            for m in [1, 2, 5]:
                nice_vals.append(m * 10 ** exp)
        nice_vals.sort()
        for nv in nice_vals:
            if nv >= f_cutoff:
                return nv
        return freq[-1]

    def do_fft(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 10: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            sig = sig[m]
        fft_params = self.inspector.fft_ctx.get_params()
        win = fft_params['window']
        nfft = fft_params['nfft']
        overlap = fft_params['overlap']
        fs = self.inspector.fft_ctx.fs()

        try:
            self.statusBar.showMessage('计算FFT...');
            QApplication.processEvents()

            if nfft and overlap > 0:
                # 使用平均FFT (Welch方法)
                freq, amp, psd = FFTAnalyzer.compute_averaged_fft(sig, fs, win, nfft, overlap)
            else:
                freq, amp = FFTAnalyzer.compute_fft(sig, fs, win, nfft)
                _, psd = FFTAnalyzer.compute_psd(sig, fs, win, nfft)

            self.canvas_fft.clear()

            # 自适应频率范围计算
            if fft_params['autoscale']:
                x_max = self._fft_auto_xlim(freq, amp)
            else:
                x_max = fs / 2

            psd_db = 10 * np.log10(psd + 1e-12)

            ax1 = self.canvas_fft.fig.add_subplot(2, 1, 1)
            ax1.plot(freq, amp, '#2563eb', lw=1.0);
            ax1.set_xlabel('Frequency (Hz)');
            ax1.set_ylabel('Amplitude', labelpad=10)
            ax1.set_title(f'FFT - {self.inspector.fft_ctx.combo_sig.currentText()} (窗:{win}, NFFT:{nfft or "auto"})');
            ax1.grid(True, alpha=0.25, ls='--');
            ax1.set_xlim(0, x_max)
            ax2 = self.canvas_fft.fig.add_subplot(2, 1, 2)
            ax2.plot(freq, psd_db, '#dc2626', lw=1.0);
            ax2.set_xlabel('Frequency (Hz)');
            ax2.set_ylabel('PSD (dB)', labelpad=10)
            ax2.set_title('功率谱密度');
            ax2.grid(True, alpha=0.25, ls='--');
            ax2.set_xlim(0, x_max)

            # 存储曲线数据用于remark吸附
            self.canvas_fft.store_line_data(0, freq, amp)
            self.canvas_fft.store_line_data(1, freq, psd_db)

            self.canvas_fft.fig.subplots_adjust(left=0.11, right=0.98, top=0.91, bottom=0.09, hspace=0.42)
            xt, yt = self.inspector.top.tick_density()
            self.canvas_fft.set_tick_density(xt, yt)
            self.canvas_fft.draw();
            pi = np.argmax(amp[1:]) + 1;
            self.statusBar.showMessage(f'FFT峰值: {freq[pi]:.2f} Hz ({amp[pi]:.4f})')
        except Exception as e:
            QMessageBox.critical(self, 'FFT错误', str(e))

    def _order_progress(self, current, total):
        """Order分析进度回调"""
        pct = int(current / total * 100) if total > 0 else 0
        self.inspector.order_ctx.set_progress(f"{pct}%")
        QApplication.processEvents()

    def do_order_time(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            t, sig = t[m], sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.inspector.order_ctx.fs()

        # 获取参数
        op = self.inspector.order_ctx.get_params()
        nfft = op['nfft']
        order_res = op['order_res']
        time_res = op['time_res']
        max_ord = op['max_order']

        try:
            self.statusBar.showMessage('计算时间-阶次谱...');
            self.inspector.order_ctx.set_progress("0%")
            QApplication.processEvents()

            tb, ords, om = OrderAnalyzer.compute_order_spectrum_time_based(
                sig, rpm, t, fs, max_ord, order_res, time_res, nfft, self._order_progress
            )

            self.canvas_order.clear();
            ax = self.canvas_order.fig.add_subplot(1, 1, 1)
            im = ax.pcolormesh(tb, ords, om.T, shading='gouraud', cmap='jet')
            ax.set_xlabel('Time (s)');
            ax.set_ylabel('Order')
            ax.set_title(f'时间-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} (分辨率:{order_res})')
            self.canvas_order.fig.colorbar(im, ax=ax, label='RMS')
            self.canvas_order.fig.tight_layout()
            xt, yt = self.inspector.top.tick_density()
            self.canvas_order.set_tick_density(xt, yt)
            self.canvas_order.draw();
            self.inspector.order_ctx.set_progress("")
            self.statusBar.showMessage(f'完成 | {len(tb)} 时间点 × {len(ords)} 阶次')
        except Exception as e:
            self.inspector.order_ctx.set_progress("")
            QMessageBox.critical(self, '错误', str(e))

    def do_order_rpm(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.inspector.order_ctx.fs()

        # 获取参数
        op = self.inspector.order_ctx.get_params()
        nfft = op['nfft']
        order_res = op['order_res']
        rpm_res = op['rpm_res']
        max_ord = op['max_order']

        try:
            self.statusBar.showMessage('计算转速-阶次谱...');
            self.inspector.order_ctx.set_progress("0%")
            QApplication.processEvents()

            ords, rb, om = OrderAnalyzer.compute_order_spectrum(
                sig, rpm, fs, max_ord, rpm_res, order_res, nfft, self._order_progress
            )

            self.canvas_order.clear();
            ax = self.canvas_order.fig.add_subplot(1, 1, 1)
            im = ax.pcolormesh(ords, rb, om, shading='gouraud', cmap='jet')
            ax.set_xlabel('Order');
            ax.set_ylabel('RPM')
            ax.set_title(f'转速-阶次谱 - {self.inspector.order_ctx.combo_sig.currentText()} (阶次分辨率:{order_res}, RPM分辨率:{rpm_res})')
            self.canvas_order.fig.colorbar(im, ax=ax, label='Amplitude')
            self.canvas_order.fig.tight_layout()
            xt, yt = self.inspector.top.tick_density()
            self.canvas_order.set_tick_density(xt, yt)
            self.canvas_order.draw();
            self.inspector.order_ctx.set_progress("")
            self.statusBar.showMessage(f'转速-阶次谱完成 | {len(rb)} RPM × {len(ords)} 阶次')
        except Exception as e:
            self.inspector.order_ctx.set_progress("")
            QMessageBox.critical(self, '错误', str(e))

    def do_order_track(self):
        t, sig, fs = self._get_sig()
        if sig is None or len(sig) < 100: QMessageBox.warning(self, "提示", "请选择有效信号"); return
        if self.inspector.top.range_enabled() and t is not None:
            lo, hi = self.inspector.top.range_values()
            m = (t >= lo) & (t <= hi)
            sig = sig[m]
        rpm = self._get_rpm(len(sig))
        if rpm is None: return
        fs = self.inspector.order_ctx.fs()
        to = self.inspector.order_ctx.target_order()
        op = self.inspector.order_ctx.get_params()
        nfft = op['nfft']

        try:
            self.statusBar.showMessage(f'跟踪阶次 {to}...');
            QApplication.processEvents()
            rt, oa = OrderAnalyzer.extract_order_track(sig, rpm, fs, to, nfft)
            self.canvas_order.clear()
            ax1 = self.canvas_order.fig.add_subplot(2, 1, 1)
            ax1.plot(rt, oa, '#1f77b4', lw=1);
            ax1.set_xlabel('RPM');
            ax1.set_ylabel('Amplitude', labelpad=10)
            ax1.set_title(f'阶次 {to} 跟踪 - {self.inspector.order_ctx.combo_sig.currentText()}');
            ax1.grid(True, alpha=0.25, ls='--')
            ax2 = self.canvas_order.fig.add_subplot(2, 1, 2)
            ax2.plot(rpm, '#2ca02c', lw=0.5);
            ax2.set_xlabel('Sample');
            ax2.set_ylabel('RPM')
            ax2.set_title('转速曲线');
            ax2.grid(True, alpha=0.25, ls='--')
            self.canvas_order.fig.tight_layout()
            xt, yt = self.inspector.top.tick_density()
            self.canvas_order.set_tick_density(xt, yt)
            self.canvas_order.draw();
            self.statusBar.showMessage(f'阶次 {to} 跟踪完成')
        except Exception as e:
            QMessageBox.critical(self, '错误', str(e))
