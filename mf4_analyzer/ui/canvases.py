"""Matplotlib canvases: TimeDomainCanvas and PlotCanvas."""
import time as _time
import numpy as np

from PyQt5.QtWidgets import QDialog
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from matplotlib.ticker import MaxNLocator
from matplotlib.patches import Rectangle

from .dialogs import AxisEditDialog

CHART_FACE = '#ffffff'
AXIS_TEXT = '#475569'
AXIS_LINE = '#cbd5e1'
GRID_LINE = '#d7dee8'
PRIMARY = '#1769e0'
DANGER = '#dc2626'


def _apply_axes_style(ax, grid=True):
    ax.set_facecolor(CHART_FACE)
    ax.tick_params(axis='both', colors=AXIS_TEXT, labelsize=8)
    ax.xaxis.label.set_color(AXIS_TEXT)
    ax.yaxis.label.set_color(AXIS_TEXT)
    ax.title.set_color('#111827')
    for spine in ax.spines.values():
        spine.set_color(AXIS_LINE)
        spine.set_linewidth(0.8)
    if grid:
        ax.grid(True, color=GRID_LINE, alpha=0.78, ls='--', lw=0.7)


def _compact_axis_label(name, unit='', max_chars=22):
    text = str(name)
    if len(text) > max_chars:
        text = text[:max_chars - 3] + '...'
    return f"{text} ({unit})" if unit else text


def _set_series_ylabel(ax, label, color, labelpad=10):
    ax.set_ylabel(label, fontsize=8, color=color, labelpad=labelpad)
    ax.yaxis.label.set_clip_on(False)


class TimeDomainCanvas(FigureCanvas):
    MAX_PTS = 8000
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    span_selected = pyqtSignal(float, float)

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(10, 6), dpi=100, facecolor=CHART_FACE)
        super().__init__(self.fig)
        self.setParent(parent)
        self.axes_list = [];
        self._overlay_mode = False
        self.lines = {};
        self.channel_data = {}
        self.span_selector = None
        self._cursor_visible = False;
        self._bg = None;
        self._cursor_artists = [];
        self._last_t = 0;
        self._refresh = True
        self._dual = False;
        self._ax = None;
        self._bx = None;
        self._placing = 'A'
        self._a_artists = [];
        self._b_artists = []
        self.mpl_connect('motion_notify_event', self._on_move)
        self.mpl_connect('scroll_event', self._on_scroll)
        self.mpl_connect('draw_event', lambda e: setattr(self, '_refresh', True))
        self.mpl_connect('button_press_event', self._on_click)
        self.setFocusPolicy(Qt.StrongFocus)
        self._axis_lock = None     # None | 'x' | 'y'
        self._rb_start = None      # (x, y) at press
        self._rb_ax = None
        self._rb_patch = None
        self.mpl_connect('button_release_event', self._on_release)
        self.mpl_connect('key_press_event', self._on_key)

    def clear(self):
        # Drop any in-flight rubber-band refs before fig.clear discards the axes.
        self._rb_patch = None
        self._rb_start = None
        self._rb_ax = None
        self.fig.clear();
        self.axes_list = [];
        self.lines = {};
        self.channel_data = {}
        self._cursor_artists = [];
        self._a_artists = [];
        self._b_artists = [];
        self._bg = None;
        self._refresh = True
        self._ax = None;
        self._bx = None

    def full_reset(self):
        """Clear figure AND all cursor/dual-cursor/background/axis-lock state.
        Use this on file close; use clear() for redraws within a session."""
        if self._rb_patch is not None:
            try: self._rb_patch.remove()
            except Exception: pass
        self._rb_patch = None
        self._rb_start = None
        self._rb_ax = None
        self._axis_lock = None
        self.clear()
        self._bg = None
        self._cursor_artists = []
        self._a_artists = []
        self._b_artists = []
        self._ax = None
        self._bx = None
        self._placing = 'A'
        self._cursor_visible = False
        self._dual = False
        self.span_selector = None
        self._last_t = 0
        self.draw_idle()

    def plot_channels(self, ch_list, mode='overlay', xlabel='Time (s)'):
        self.clear()
        vis = [(n, t, s, c, u) for n, v, t, s, c, u in ch_list if v]
        self._overlay_mode = mode == 'overlay' and len(vis) >= 2
        if not vis: self.draw(); return
        if mode == 'subplot' and len(vis) > 1:
            n = len(vis); first = None
            for i, (name, t, sig, color, unit) in enumerate(vis):
                ax = self.fig.add_subplot(n, 1, i + 1, sharex=first) if i > 0 else self.fig.add_subplot(n, 1, 1)
                if i == 0: first = ax
                self.axes_list.append(ax)
                _apply_axes_style(ax)
                td, sd = self._ds(t, sig)
                ax.plot(td, sd, color=color, lw=1.05)
                self.channel_data[name] = (t, sig, color, unit)
                label = _compact_axis_label(name, unit, max_chars=20)
                _set_series_ylabel(ax, label, color, labelpad=12)
                ax.tick_params(axis='y', colors=color, labelsize=7)
                ax.spines['left'].set_color(color); ax.spines['left'].set_linewidth(2)
                if i < n - 1:
                    ax.tick_params(axis='x', labelbottom=False)
                else:
                    ax.set_xlabel(xlabel, fontsize=9, color=AXIS_TEXT)
            self.fig.subplots_adjust(hspace=0.08, left=0.17, right=0.96, top=0.96, bottom=0.08)
        elif mode == 'overlay' and len(vis) >= 2:
            # Per-channel twin-Y axes
            ax0 = self.fig.add_subplot(1, 1, 1); self.axes_list.append(ax0)
            _apply_axes_style(ax0)
            for i in range(1, len(vis)):
                tw = ax0.twinx(); self.axes_list.append(tw)
                _apply_axes_style(tw, grid=False)
                tw.spines['left'].set_visible(False)
                tw.spines['top'].set_visible(False)
                tw.spines['bottom'].set_visible(False)
                if i >= 2:
                    tw.spines['right'].set_position(('outward', 60 * (i - 1)))
            for ax, (name, t, sig, color, unit) in zip(self.axes_list, vis):
                td, sd = self._ds(t, sig)
                ax.plot(td, sd, color=color, lw=1.05)
                self.channel_data[name] = (t, sig, color, unit)
                label = _compact_axis_label(name, unit, max_chars=18)
                _set_series_ylabel(ax, label, color, labelpad=12)
                ax.tick_params(axis='y', colors=color, labelsize=7)
                side = 'left' if ax is ax0 else 'right'
                ax.spines[side].set_color(color); ax.spines[side].set_linewidth(1.5)
            ax0.set_xlabel(xlabel, fontsize=9, color=AXIS_TEXT)
            right = max(0.93 - 0.065 * max(0, len(vis) - 2), 0.58)
            self.fig.subplots_adjust(left=0.15, right=right, top=0.96, bottom=0.09)
        else:
            # single channel
            ax = self.fig.add_subplot(1, 1, 1); self.axes_list.append(ax)
            _apply_axes_style(ax)
            name, t, sig, color, unit = vis[0]
            td, sd = self._ds(t, sig)
            ax.plot(td, sd, color=color, lw=1.05)
            self.channel_data[name] = (t, sig, color, unit)
            label = _compact_axis_label(name, unit, max_chars=24)
            _set_series_ylabel(ax, label, color, labelpad=12)
            ax.tick_params(axis='y', colors=color, labelsize=7)
            ax.set_xlabel(xlabel, fontsize=9, color=AXIS_TEXT)
            self.fig.subplots_adjust(left=0.17, right=0.96, top=0.95, bottom=0.11)
        for ax in self.axes_list:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=10, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=3))
        self.draw(); self._refresh = True

    def _ds(self, t, sig):
        n = len(sig)
        if n <= self.MAX_PTS: return t, sig
        bs = n // (self.MAX_PTS // 2)
        if bs < 2: return t, sig
        idx = []
        for s in range(0, n, bs):
            e = min(s + bs, n);
            c = sig[s:e]
            idx.extend([s + np.argmin(c), s + np.argmax(c)])
        idx = np.unique(np.clip(idx, 0, n - 1))
        return t[idx], sig[idx]

    def set_tick_density(self, x, y):
        for ax in self.axes_list:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=x, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=y, min_n_ticks=3))
        self._refresh = True;
        self.draw_idle()

    def enable_span_selector(self, cb):
        if self.axes_list:
            def _onselect(xmin, xmax):
                self.span_selected.emit(float(xmin), float(xmax))
                cb(xmin, xmax)
            self.span_selector = SpanSelector(self.axes_list[-1], _onselect, 'horizontal', useblit=True, interactive=True,
                                              props=dict(alpha=0.16, facecolor=PRIMARY))

    def set_cursor_visible(self, v):
        self._cursor_visible = v
        if not v:
            for a in self._cursor_artists + self._a_artists + self._b_artists: a.set_visible(False)
            self.draw_idle()

    def set_dual_cursor_mode(self, en):
        self._dual = en
        if not en:
            self._ax = self._bx = None;
            self._placing = 'A'
            for a in self._a_artists + self._b_artists: a.set_visible(False)
            self._a_artists.clear();
            self._b_artists.clear()
            self._refresh = True;
            self.draw_idle()

    def _ensure_artists(self):
        if self._cursor_artists: return
        for ax in self.axes_list:
            self._cursor_artists.append(
                ax.axvline(x=0, color=DANGER, lw=0.8, ls='--', alpha=0.75, animated=True, visible=False))
        self._refresh = True

    def _ensure_dual(self):
        if not self._a_artists:
            for ax in self.axes_list: self._a_artists.append(
                ax.axvline(x=0, color='#00BFFF', lw=1.5, alpha=0.9, animated=True, visible=False))
        if not self._b_artists:
            for ax in self.axes_list: self._b_artists.append(
                ax.axvline(x=0, color='#FF6347', lw=1.5, alpha=0.9, animated=True, visible=False))
        self._refresh = True

    def _refresh_bg(self):
        for a in self._cursor_artists + self._a_artists + self._b_artists: a.set_visible(False)
        self.fig.canvas.draw()
        self._bg = self.fig.canvas.copy_from_bbox(self.fig.bbox)
        self._refresh = False

    def _on_click(self, e):
        # Axis-lock mode short-circuits dual-cursor and initiates rubber-band
        if self._axis_lock is not None and e.button == 1 and e.inaxes is not None \
                and e.xdata is not None and e.ydata is not None:
            self._rb_start = (e.xdata, e.ydata)
            self._rb_ax = e.inaxes
            xlo, xhi = e.inaxes.get_xlim()
            ylo, yhi = e.inaxes.get_ylim()
            if self._axis_lock == 'x':
                self._rb_patch = Rectangle((e.xdata, ylo), 0, yhi - ylo,
                                           facecolor=PRIMARY, alpha=0.16, edgecolor=PRIMARY, lw=0.8)
            else:
                self._rb_patch = Rectangle((xlo, e.ydata), xhi - xlo, 0,
                                           facecolor=PRIMARY, alpha=0.16, edgecolor=PRIMARY, lw=0.8)
            e.inaxes.add_patch(self._rb_patch)
            self.draw_idle()
            return
        if not self._dual or not self._cursor_visible or e.inaxes is None or e.xdata is None or e.button != 1:
            return
        if self._placing == 'A':
            self._ax = e.xdata; self._placing = 'B'
        else:
            self._bx = e.xdata; self._placing = 'A'
        self._update_dual()

    def _on_move(self, e):
        # Rubber-band update has priority
        if self._rb_start is not None and self._rb_patch is not None and e.inaxes is self._rb_ax \
                and e.xdata is not None and e.ydata is not None:
            x0, y0 = self._rb_start
            if self._axis_lock == 'x':
                self._rb_patch.set_x(min(x0, e.xdata))
                self._rb_patch.set_width(abs(e.xdata - x0))
            else:
                self._rb_patch.set_y(min(y0, e.ydata))
                self._rb_patch.set_height(abs(e.ydata - y0))
            self.draw_idle()
            return
        if not self._cursor_visible or e.inaxes is None or e.xdata is None: return
        now = _time.monotonic() * 1000
        if now - self._last_t < 33: return
        self._last_t = now
        if self._dual:
            self._update_dual(hover=e.xdata)
        else:
            self._update_single(e.xdata)

    def _update_single(self, x):
        self._ensure_artists()
        if self._refresh or not self._bg: self._refresh_bg()
        self.fig.canvas.restore_region(self._bg)
        for i, vl in enumerate(self._cursor_artists):
            if i < len(self.axes_list): vl.set_xdata([x, x]); vl.set_visible(True); self.axes_list[i].draw_artist(vl)
        info = [f"t={x:.4f}s"]
        for ch, (tf, sf, _, u) in self.channel_data.items():
            if len(tf):
                idx = min(np.searchsorted(tf, x), len(sf) - 1)
                unit_s = f" {u}" if u else ""
                info.append(f"{ch[:18]}={sf[idx]:.4g}{unit_s}")
        self.fig.canvas.blit(self.fig.bbox)
        self.cursor_info.emit("  │  ".join(info))

    def _update_dual(self, hover=None):
        self._ensure_dual()
        if self._refresh or not self._bg: self._refresh_bg()
        self.fig.canvas.restore_region(self._bg)
        info, dual = [], []
        if self._ax is not None:
            for i, vl in enumerate(self._a_artists):
                if i < len(self.axes_list): vl.set_xdata([self._ax] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
            info.append(f"A={self._ax:.4f}s")
        if self._bx is not None:
            for i, vl in enumerate(self._b_artists):
                if i < len(self.axes_list): vl.set_xdata([self._bx] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
            info.append(f"B={self._bx:.4f}s")
        if self._ax is not None and self._bx is not None:
            dx = self._bx - self._ax;
            info.append(f"ΔT={dx:.4f}s")
            if abs(dx) > 1e-12: info.append(f"1/ΔT={1 / abs(dx):.2f}Hz")
            xlo, xhi = min(self._ax, self._bx), max(self._ax, self._bx)
            for ch, (tf, sf, _, u) in self.channel_data.items():
                if not len(tf): continue
                m = (tf >= xlo) & (tf <= xhi); seg = sf[m]
                if not len(seg): continue
                unit_s = f" {u}" if u else ""
                dual.append(
                    f"{ch[:20]}:Min={np.min(seg):.4g}{unit_s} Max={np.max(seg):.4g}{unit_s} "
                    f"Avg={np.mean(seg):.4g}{unit_s} RMS={np.sqrt(np.mean(seg ** 2)):.4g}{unit_s}"
                )
        if hover is not None:
            self._ensure_artists()
            for i, vl in enumerate(self._cursor_artists):
                if i < len(self.axes_list): vl.set_xdata([hover] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
        self.fig.canvas.blit(self.fig.bbox)
        self.cursor_info.emit("  │  ".join(info) if info else "Click A")
        self.dual_cursor_info.emit("\n".join(dual) if dual else "")

    def _on_scroll(self, e):
        if e.inaxes is None: return
        ax = e.inaxes;
        step = e.step;
        key = e.key or '';
        f = 0.85 if step > 0 else 1 / 0.85
        if 'control' in key:
            lo, hi = ax.get_xlim(); c = e.xdata or (lo + hi) / 2; ax.set_xlim(c - (c - lo) * f, c + (hi - c) * f)
        elif 'shift' in key:
            lo, hi = ax.get_ylim(); c = e.ydata or (lo + hi) / 2; ax.set_ylim(c - (c - lo) * f, c + (hi - c) * f)
        else:
            lo, hi = ax.get_ylim(); d = (hi - lo) * 0.1 * step; ax.set_ylim(lo + d, hi + d)
        self._refresh = True;
        self.draw_idle()

    def set_axis_lock(self, mode):
        """mode in {'x', 'y', 'none'}."""
        self._axis_lock = None if mode == 'none' else mode
        if self.span_selector is not None:
            self.span_selector.set_active(self._axis_lock is None)
        self._cancel_rb()

    def _cancel_rb(self):
        if self._rb_patch is not None:
            try: self._rb_patch.remove()
            except Exception: pass
        self._rb_patch = None
        self._rb_start = None
        self._rb_ax = None
        self.draw_idle()

    def _on_release(self, e):
        if self._axis_lock is None or self._rb_start is None or self._rb_ax is None:
            return
        if e.inaxes is not self._rb_ax or e.xdata is None or e.ydata is None:
            self._cancel_rb(); return
        x0, y0 = self._rb_start
        x1, y1 = e.xdata, e.ydata
        ax = self._rb_ax
        if self._axis_lock == 'x' and abs(x1 - x0) > 1e-9:
            ax.set_xlim(min(x0, x1), max(x0, x1))
        elif self._axis_lock == 'y' and abs(y1 - y0) > 1e-9:
            ax.set_ylim(min(y0, y1), max(y0, y1))
        self._refresh = True
        self._cancel_rb()

    def _on_key(self, e):
        if e.key == 'escape':
            self._cancel_rb()

    def get_statistics(self, time_range=None):
        stats = {}
        for ch, (t, sig, _, unit) in self.channel_data.items():
            s = sig[(t >= time_range[0]) & (t <= time_range[1])] if time_range else sig
            if len(s): stats[ch] = {'min': np.min(s), 'max': np.max(s), 'mean': np.mean(s),
                                    'rms': np.sqrt(np.mean(s ** 2)), 'std': np.std(s), 'p2p': np.ptp(s), 'unit': unit}
        return stats


class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(20, 12), dpi=100, facecolor=CHART_FACE);
        super().__init__(self.fig);
        self.setParent(parent)
        self.mpl_connect('scroll_event', self._on_scroll)
        self.mpl_connect('button_press_event', self._on_click)
        self.setFocusPolicy(Qt.StrongFocus)
        self._remarks = []  # [(ax_index, x, y, annotation_artist, dot_artist)]
        self._line_data = {}  # {ax_index: (xdata, ydata)} for snapping
        self._remark_enabled = False
        self._last_scroll_t = 0  # 滚轮节流
        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(lambda: self.draw_idle())

    def clear(self):
        self._remarks = []
        self._line_data = {}
        self.fig.clear()
        self.fig.set_facecolor(CHART_FACE)

    def full_reset(self):
        """Clear figure AND remarks/stored-line-data."""
        self.clear()
        self._remark_enabled = False
        self.draw_idle()

    def set_remark_enabled(self, enabled):
        self._remark_enabled = enabled

    def store_line_data(self, ax_index, xdata, ydata):
        """存储曲线数据用于remark吸附"""
        self._line_data[ax_index] = (np.array(xdata), np.array(ydata))

    def _snap_to_curve(self, ax_index, x_click):
        """将点击位置吸附到最近的曲线数据点"""
        if ax_index not in self._line_data:
            return None, None
        xd, yd = self._line_data[ax_index]
        if len(xd) == 0:
            return None, None
        idx = np.argmin(np.abs(xd - x_click))
        return float(xd[idx]), float(yd[idx])

    def _add_remark(self, ax, ax_index, x, y):
        """在指定位置添加remark标注"""
        # 格式化标签
        if abs(x) >= 1000:
            x_str = f"{x:.1f}"
        elif abs(x) >= 1:
            x_str = f"{x:.2f}"
        else:
            x_str = f"{x:.4f}"
        if abs(y) >= 1000:
            y_str = f"{y:.1f}"
        elif abs(y) >= 0.01:
            y_str = f"{y:.4f}"
        else:
            y_str = f"{y:.2e}"

        ann = ax.annotate(
            f"({x_str}, {y_str})",
            xy=(x, y), xytext=(15, 15),
            textcoords='offset points',
            fontsize=8, color='#111827',
            bbox=dict(boxstyle='round,pad=0.35', facecolor='#ffffff', edgecolor='#94a3b8', alpha=0.95),
            arrowprops=dict(arrowstyle='->', color='#64748b', lw=1),
            zorder=100
        )
        # 标记点
        dot, = ax.plot(x, y, 'o', color=DANGER, markersize=5, zorder=101)
        self._remarks.append((ax_index, x, y, ann, dot))
        self.draw_idle()

    def _remove_remark_at(self, ax_index, x_click, y_click):
        """删除最近的remark"""
        if not self._remarks:
            return
        ax = self.fig.axes[ax_index] if ax_index < len(self.fig.axes) else None
        if ax is None:
            return
        # 查找最近的remark (按像素距离)
        best_idx, best_dist = -1, float('inf')
        for i, (ai, rx, ry, ann, dot) in enumerate(self._remarks):
            if ai != ax_index:
                continue
            # 转换为显示坐标计算距离
            try:
                disp = ax.transData.transform((rx, ry))
                click_disp = ax.transData.transform((x_click, y_click))
                dist = np.sqrt((disp[0] - click_disp[0])**2 + (disp[1] - click_disp[1])**2)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            except:
                pass
        if best_idx >= 0 and best_dist < 50:  # 50像素内
            _, _, _, ann, dot = self._remarks.pop(best_idx)
            ann.remove()
            dot.remove()
            self.draw_idle()

    def _find_axis_for_dblclick(self, e):
        """根据双击像素位置判断应编辑哪个axes的哪个轴。
        检测范围包括axes外部的刻度标签区域（更符合用户直觉）。
        返回 (ax, 'x'|'y') 或 (None, None)。
        """
        px, py = e.x, e.y
        MARGIN = 45  # 像素：axes外部可点击的边距（覆盖刻度数字区域）
        best = (None, None)
        best_dist = float('inf')
        for ax in self.fig.axes:
            bbox = ax.get_window_extent()
            # --- X轴区域：axes下方 MARGIN 像素范围内，水平方向在axes范围内 ---
            if bbox.x0 - 10 <= px <= bbox.x1 + 10:
                if bbox.y0 - MARGIN <= py <= bbox.y0 + 20:
                    dist = abs(py - bbox.y0)
                    if dist < best_dist:
                        best = (ax, 'x')
                        best_dist = dist
            # --- Y轴区域：axes左侧 MARGIN 像素范围内，垂直方向在axes范围内 ---
            if bbox.y0 - 10 <= py <= bbox.y1 + 10:
                if bbox.x0 - MARGIN <= px <= bbox.x0 + 20:
                    dist = abs(px - bbox.x0)
                    if dist < best_dist:
                        best = (ax, 'y')
                        best_dist = dist
                # --- 右侧Y轴（colorbar等）：axes右侧 MARGIN 像素范围内 ---
                if bbox.x1 - 20 <= px <= bbox.x1 + MARGIN:
                    dist = abs(px - bbox.x1)
                    if dist < best_dist:
                        best = (ax, 'y')
                        best_dist = dist
        return best

    def _on_click(self, e):
        # 双击编辑坐标轴 — 优先处理，不要求点击在axes内部
        if e.button == 1 and e.dblclick:
            ax, axis = self._find_axis_for_dblclick(e)
            if ax is not None:
                self._edit_axis(ax, axis)
                return

        if e.inaxes is None or e.xdata is None:
            return
        # 找到点击的是哪个axes
        ax_index = -1
        for i, ax in enumerate(self.fig.axes):
            if e.inaxes == ax:
                ax_index = i
                break
        if ax_index < 0:
            return

        if e.button == 3:  # 右键删除remark
            self._remove_remark_at(ax_index, e.xdata, e.ydata)
            return

        if e.button == 1 and not e.dblclick and self._remark_enabled:
            # 左键单击添加remark (吸附到曲线)
            x, y = self._snap_to_curve(ax_index, e.xdata)
            if x is not None:
                self._add_remark(e.inaxes, ax_index, x, y)

    def _edit_axis(self, ax, axis):
        """弹出坐标轴编辑对话框"""
        dlg = AxisEditDialog(self.parent(), ax, axis)
        if dlg.exec_() == QDialog.Accepted:
            vmin, vmax, label, auto = dlg.get_values()
            if axis == 'x':
                if auto:
                    ax.autoscale(axis='x')
                else:
                    ax.set_xlim(vmin, vmax)
                if label:
                    ax.set_xlabel(label)
            else:
                if auto:
                    ax.autoscale(axis='y')
                else:
                    ax.set_ylim(vmin, vmax)
                if label:
                    ax.set_ylabel(label)
            self.draw_idle()

    def set_tick_density(self, x, y):
        for ax in self.fig.axes:
            _apply_axes_style(ax)
            ax.xaxis.set_major_locator(MaxNLocator(nbins=x, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=y, min_n_ticks=3))
        self.draw_idle()

    def _on_scroll(self, e):
        if e.inaxes is None: return
        ax = e.inaxes;
        step = e.step;
        key = e.key or '';
        f = 0.85 if step > 0 else 1 / 0.85
        if 'control' in key:
            lo, hi = ax.get_xlim(); c = e.xdata or (lo + hi) / 2; ax.set_xlim(c - (c - lo) * f, c + (hi - c) * f)
        elif 'shift' in key:
            lo, hi = ax.get_ylim(); c = e.ydata or (lo + hi) / 2; ax.set_ylim(c - (c - lo) * f, c + (hi - c) * f)
        else:
            lo, hi = ax.get_ylim(); d = (hi - lo) * 0.1 * step; ax.set_ylim(lo + d, hi + d)
        # 节流：快速滚动时延迟重绘，避免pcolormesh等重量级图形卡顿
        now = _time.monotonic() * 1000
        if now - self._last_scroll_t < 50:
            # 滚动太快，延迟重绘
            self._scroll_timer.start(60)
        else:
            self.draw_idle()
        self._last_scroll_t = now
