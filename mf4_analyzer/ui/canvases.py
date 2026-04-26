"""Matplotlib canvases: TimeDomainCanvas and PlotCanvas."""
import time as _time
from collections import OrderedDict

import numpy as np

import matplotlib as _mpl
from PyQt5.QtWidgets import QDialog
from PyQt5.QtCore import Qt, pyqtSignal, QTimer

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
from matplotlib.ticker import MaxNLocator
from matplotlib.patches import Rectangle

from .dialogs import AxisEditDialog

# ----------------------------------------------------------------------
# Phase 1 item 5: free Matplotlib rcParams wins.
#
# Apply once at module import — these are global to the matplotlib
# backend so they don't need to be re-set per-canvas (and we MUST NOT
# re-set them per replot or per draw, which would burn CPU on every
# plot_channels call). Values per the time-domain plot performance
# spec; thresholds are conservative enough to leave the visual output
# unchanged at typical canvas sizes.
# ----------------------------------------------------------------------
_mpl.rcParams['path.simplify'] = True
_mpl.rcParams['path.simplify_threshold'] = 0.8
_mpl.rcParams['agg.path.chunksize'] = 10000

CHART_FACE = '#ffffff'
AXIS_TEXT = '#475569'
AXIS_LINE = '#cbd5e1'
GRID_LINE = '#d7dee8'
PRIMARY = '#1769e0'
DANGER = '#dc2626'


def _is_monotonic_array(t):
    """Return True iff ``t`` is non-decreasing. Empty / single-sample → True."""
    if t is None:
        return True
    arr = np.asarray(t)
    if arr.size < 2:
        return True
    # np.all(np.diff(t) >= 0) allocates diff but matches the spec's contract.
    return bool(np.all(np.diff(arr) >= 0))


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


def _split_prefixed_label(text):
    """Return (prefix, rest) for labels shaped like '[filename] channel'.
    Returns (None, text) when the pattern doesn't match."""
    if text.startswith('[') and ']' in text:
        i = text.index(']')
        rest = text[i + 1:].lstrip()
        if rest:
            return text[:i + 1], rest
    return None, text


def _compact_axis_label(name, unit='', max_chars=22):
    """Channel-name only — units are now drawn separately above the axis."""
    text = str(name)
    if len(text) <= max_chars:
        return text
    prefix, rest = _split_prefixed_label(text)
    if prefix is not None:
        return f"{prefix}\n{rest}"
    return text[:max_chars - 3] + '...'


def _set_series_ylabel(ax, label, color, labelpad=10, unit='', side='left'):
    ax.set_ylabel(label, fontsize=8, color=color, labelpad=labelpad)
    ax.yaxis.label.set_clip_on(False)
    if unit:
        # Horizontal unit chip at the very top of the spine (above tick labels).
        x_anchor = 0.0 if side == 'left' else 1.0
        ha = 'left' if side == 'left' else 'right'
        ax.text(
            x_anchor, 1.012, unit,
            transform=ax.transAxes,
            ha=ha, va='bottom',
            fontsize=8, color=color, fontweight='600',
            clip_on=False,
        )


def _format_dual_html(rows):
    """rows: list of (channel_name, mn, mx, avg, rms, unit_suffix, color).
    Channel name is rendered on its own line (file prefix + name split when
    the source matches '[file] channel'); stats follow as a 4-column row.
    Channel name and numeric cells are tinted with the channel's plot color."""
    from html import escape
    parts = ['<table cellspacing="0" cellpadding="0" '
             'style="font-size:11px; color:#111827;">']
    for i, row in enumerate(rows):
        if len(row) >= 7:
            ch, mn, mx, avg, rms, u, color = row[:7]
        else:
            ch, mn, mx, avg, rms, u = row[:6]
            color = '#111827'
        prefix, rest = _split_prefixed_label(ch)
        if prefix is not None:
            name_html = (f'<span style="color:#64748b;">{escape(prefix)}</span>'
                         f'<br/><b style="color:{color};">{escape(rest)}</b>')
        else:
            name_html = f'<b style="color:{color};">{escape(ch)}</b>'
        top_pad = '8px' if i > 0 else '0'
        parts.append(
            f'<tr><td colspan="4" style="padding-top:{top_pad}; padding-bottom:2px;">'
            f'{name_html}</td></tr>'
        )
        cell = (f'padding:1px 8px 1px 0; color:{color}; font-family:'
                '\'SF Mono\',Menlo,Consolas,monospace;')
        lab = 'padding:1px 4px 1px 0; color:#94a3b8;'
        parts.append(
            f'<tr>'
            f'<td style="{lab}">Min</td>'
            f'<td style="{cell}" align="right">{mn:.4g}{escape(u)}</td>'
            f'<td style="{lab}; padding-left:8px;">Max</td>'
            f'<td style="{cell}" align="right">{mx:.4g}{escape(u)}</td>'
            f'</tr>'
            f'<tr>'
            f'<td style="{lab}">Avg</td>'
            f'<td style="{cell}" align="right">{avg:.4g}{escape(u)}</td>'
            f'<td style="{lab}; padding-left:8px;">RMS</td>'
            f'<td style="{cell}" align="right">{rms:.4g}{escape(u)}</td>'
            f'</tr>'
        )
    parts.append('</table>')
    return ''.join(parts)


# ----------------------------------------------------------------------
# Module-level envelope helper (spec §6.4 / plan T4 step 3).
#
# Pure function version of the viewport-aware min/max envelope reducer
# previously embedded in ``TimeDomainCanvas._envelope``. Lives at module
# scope so non-canvas callers (e.g. ``order_track`` lower-half RPM line)
# can reuse the exact same downsampling without instantiating a canvas.
#
# ``TimeDomainCanvas._envelope`` is now a thin wrapper that forwards
# here. The wrapper keeps its required-``xlim`` signature; the
# ``xlim=None`` (full-range) contract belongs to ``build_envelope`` only,
# per spec §6.4 — this prevents the canvas method's compatibility
# surface from growing.
# ----------------------------------------------------------------------

# Default cap mirrors ``TimeDomainCanvas.MAX_PTS = 8000``. Forward
# referencing the class attribute is impossible because this helper must
# be defined before the class; the constant is duplicated here and kept
# in sync deliberately.
_BUILD_ENVELOPE_LEGACY_MAX_PTS = 8000


def _ds_legacy_pure(t, sig, max_pts=_BUILD_ENVELOPE_LEGACY_MAX_PTS):
    """Module-level twin of :meth:`TimeDomainCanvas._ds_legacy`.

    Verbatim algorithm; ``self.MAX_PTS`` is replaced with the parameter
    ``max_pts`` defaulting to the same 8000 the canvas uses.
    """
    n = len(sig)
    if n <= max_pts:
        return t, sig
    bs = n // (max_pts // 2)
    if bs < 2:
        return t, sig
    idx = []
    for s in range(0, n, bs):
        e = min(s + bs, n)
        c = sig[s:e]
        idx.extend([s + np.argmin(c), s + np.argmax(c)])
    idx = np.unique(np.clip(idx, 0, n - 1))
    return t[idx], sig[idx]


def build_envelope(t, sig, *, xlim, pixel_width, is_monotonic=None):
    """Pure function version of the viewport-aware min/max envelope.

    Parameters
    ----------
    t, sig : np.ndarray
        Same length 1-D arrays. ``t`` should be monotonic for the fast
        path; non-monotonic input falls back to the legacy full-series
        reducer (:func:`_ds_legacy_pure`).
    xlim : tuple(float, float) | None
        Visible x-axis range ``(x0, x1)``. ``None`` means **full range**
        and is equivalent to ``(float(t[0]), float(t[-1]))`` — this is
        the entry used by ``order_track``'s lower-half RPM line which
        does not own a viewport. Empty ``t`` with ``xlim=None`` returns
        the inputs untouched.
    pixel_width : int
        Approximate pixel width of the visible axes — sets the target
        bucket count.
    is_monotonic : Optional[bool]
        Precomputed monotonicity flag. ``None`` means "scan to verify"
        (safety net for ad-hoc callers / tests).

    Returns
    -------
    (t_out, sig_out) : tuple of np.ndarray
        Time-ordered (min, max) sample pairs per pixel bucket. Small
        visible spans are returned unchanged. NaN buckets emit a single
        NaN break to preserve polyline discontinuities.
    """
    # xlim=None → full-range fallback (spec §6.4). Empty input is
    # special-cased to avoid IndexError on ``t[0]`` / ``t[-1]``.
    if xlim is None:
        if len(t) == 0:
            return np.asarray(t, dtype=float), np.asarray(sig, dtype=float)
        xlim = (float(t[0]), float(t[-1]))

    t = np.asarray(t)
    sig = np.asarray(sig)
    n_total = len(sig)
    if n_total == 0:
        return t, sig
    if pixel_width is None or pixel_width < 1:
        pixel_width = 1

    # Non-monotonic x → legacy full-series reduction. searchsorted is
    # invalid here; trust the precomputed flag when supplied, else scan.
    if n_total >= 2:
        if is_monotonic is None:
            is_monotonic = _is_monotonic_array(t)
        if not is_monotonic:
            return _ds_legacy_pure(t, sig)

    x0, x1 = float(xlim[0]), float(xlim[1])
    if x1 < x0:
        x0, x1 = x1, x0
    # Visible window via searchsorted (monotonic t).
    i0 = int(np.searchsorted(t, x0, side='left'))
    i1 = int(np.searchsorted(t, x1, side='right'))
    if i1 <= i0:
        return t[i0:i0], sig[i0:i0]

    t_vis = t[i0:i1]
    s_vis = sig[i0:i1]
    n_vis = len(s_vis)

    # Small-visible shortcut: don't bother bucketing.
    if n_vis <= 2 * pixel_width:
        return t_vis, s_vis

    # Bucket count: ~one bucket per pixel.
    n_buckets = int(pixel_width)
    bs = max(1, n_vis // n_buckets)
    n_buckets = max(1, n_vis // bs)

    out_t = np.empty(2 * n_buckets, dtype=t_vis.dtype)
    out_s = np.empty(2 * n_buckets, dtype=np.result_type(s_vis.dtype,
                                                          np.float64))
    out_count = 0

    for b in range(n_buckets):
        s_start = b * bs
        # Last bucket absorbs the remainder so no samples are dropped.
        s_end = n_vis if b == n_buckets - 1 else s_start + bs
        seg = s_vis[s_start:s_end]
        if seg.size == 0:
            continue
        nan_mask = np.isnan(seg) if np.issubdtype(seg.dtype,
                                                    np.floating) else None
        if nan_mask is not None and nan_mask.all():
            mid_idx = s_start + seg.size // 2
            out_t[out_count] = t_vis[mid_idx]
            out_s[out_count] = np.nan
            out_count += 1
            continue
        if nan_mask is not None and nan_mask.any():
            rel_lo = int(np.nanargmin(seg))
            rel_hi = int(np.nanargmax(seg))
        else:
            rel_lo = int(np.argmin(seg))
            rel_hi = int(np.argmax(seg))
        lo_idx = s_start + rel_lo
        hi_idx = s_start + rel_hi
        # Emit min/max in TIME ORDER so the line traversal is monotonic.
        if lo_idx <= hi_idx:
            out_t[out_count] = t_vis[lo_idx]
            out_s[out_count] = s_vis[lo_idx]
            out_count += 1
            if hi_idx != lo_idx:
                out_t[out_count] = t_vis[hi_idx]
                out_s[out_count] = s_vis[hi_idx]
                out_count += 1
        else:
            out_t[out_count] = t_vis[hi_idx]
            out_s[out_count] = s_vis[hi_idx]
            out_count += 1
            out_t[out_count] = t_vis[lo_idx]
            out_s[out_count] = s_vis[lo_idx]
            out_count += 1

    return out_t[:out_count], out_s[:out_count]


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
        # data_id parallel dict: {channel_name: data_id}. Kept separate
        # from channel_data so the cursor/dual-cursor/get_statistics
        # readers (which expect a 4-tuple value) don't change shape.
        self._channel_data_id = {}
        # Per-channel Line2D references so the viewport-refresh path can
        # call set_data() in-place without rebuilding axes.
        self._channel_lines = {}
        # Per-channel monotonicity flag, populated once per plot_channels
        # build (Phase 1 item 6 follow-up F-1). _refresh_visible_data
        # reads this dict and passes the cached boolean into
        # _envelope_cached / _envelope so the hot path does not re-run
        # _is_monotonic_array on every viewport change.
        self._channel_is_monotonic = {}
        self.span_selector = None
        # ----- viewport refresh wiring (Phase 1 items 2 + 5) -----
        # The "primary" axis is the one whose xlim_changed we listen to.
        # In subplot mode the axes share x via sharex, so a single
        # connection suffices; in overlay mode all twinx siblings share
        # the same x, so we listen on axes_list[0].
        self._primary_xaxis_ax = None
        self._xlim_cid = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(40)  # ~25 FPS coalesce window
        self._refresh_timer.timeout.connect(self._refresh_visible_data)
        self._refresh_pending = False
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
        # --- viewport-aware envelope caches (Phase 1 items 4 + 6) ----
        # LRU cache keyed by (data_id, channel_name, quantized_xlim, pixel_width).
        self._envelope_cache_capacity = 64
        self._envelope_cache = OrderedDict()
        self._envelope_cache_hits = 0
        self._envelope_cache_misses = 0
        # Monotonicity cache keyed by (custom_xaxis_fid, custom_xaxis_ch).
        self._monotonicity_cache = {}
        self._monotonicity_cache_hits = 0
        self._monotonicity_cache_misses = 0
        # Mouse-press flag for hover short-circuit during active drag.
        self._mouse_button_pressed = False
        self.mpl_connect('button_press_event', self._track_mouse_press)
        self.mpl_connect('button_release_event', self._track_mouse_release)

    def clear(self):
        # Drop any in-flight rubber-band refs before fig.clear discards the axes.
        self._rb_patch = None
        self._rb_start = None
        self._rb_ax = None
        # Disconnect the xlim_changed callback before the axis it was
        # attached to is destroyed by fig.clear() — otherwise stale
        # callbacks accumulate on rebuild and fire against dangling axes.
        self._disconnect_xlim_listener()
        # Also cancel any pending refresh tied to the soon-to-be-gone axes.
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        self._refresh_pending = False
        self.fig.clear();
        self.axes_list = [];
        self.lines = {};
        self.channel_data = {}
        self._channel_data_id = {}
        self._channel_lines = {}
        self._channel_is_monotonic = {}
        self._primary_xaxis_ax = None
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
        """Build the figure for ``ch_list``.

        ``ch_list`` is a list of tuples shaped either as
        ``(name, visible, t, sig, color, unit)`` (legacy) or
        ``(name, visible, t, sig, color, unit, data_id)`` (preferred —
        the optional trailing ``data_id`` lets the viewport refresh path
        key the envelope cache per-source-file).
        """
        self.clear()
        vis = []
        for row in ch_list:
            visible = row[1]
            if not visible:
                continue
            if len(row) >= 7:
                name, _, t, sig, color, unit, data_id = row[:7]
            else:
                name, _, t, sig, color, unit = row[:6]
                data_id = None
            vis.append((name, t, sig, color, unit, data_id))
        self._overlay_mode = mode == 'overlay' and len(vis) >= 2
        if not vis: self.draw(); return
        if mode == 'subplot' and len(vis) > 1:
            n = len(vis); first = None
            for i, (name, t, sig, color, unit, data_id) in enumerate(vis):
                ax = self.fig.add_subplot(n, 1, i + 1, sharex=first) if i > 0 else self.fig.add_subplot(n, 1, 1)
                if i == 0: first = ax
                self.axes_list.append(ax)
                _apply_axes_style(ax)
                td, sd = self._ds(t, sig)
                line, = ax.plot(td, sd, color=color, lw=1.05)
                self.channel_data[name] = (t, sig, color, unit)
                self._channel_data_id[name] = data_id
                self._channel_lines[name] = (ax, line)
                # F-1: cache monotonicity once per build so the refresh
                # path does not re-scan np.diff(t) on every xlim change.
                self._channel_is_monotonic[name] = _is_monotonic_array(t)
                label = _compact_axis_label(name, unit, max_chars=20)
                _set_series_ylabel(ax, label, color, labelpad=12, unit=unit, side='left')
                ax.tick_params(axis='y', colors=color, labelsize=7)
                ax.spines['left'].set_color(color); ax.spines['left'].set_linewidth(2)
                if i < n - 1:
                    ax.tick_params(axis='x', labelbottom=False)
                else:
                    ax.set_xlabel(xlabel, fontsize=9, color=AXIS_TEXT)
            self.fig.tight_layout()
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
            for ax, (name, t, sig, color, unit, data_id) in zip(self.axes_list, vis):
                td, sd = self._ds(t, sig)
                line, = ax.plot(td, sd, color=color, lw=1.05)
                self.channel_data[name] = (t, sig, color, unit)
                self._channel_data_id[name] = data_id
                self._channel_lines[name] = (ax, line)
                # F-1: cache monotonicity once per build (see subplot branch).
                self._channel_is_monotonic[name] = _is_monotonic_array(t)
                label = _compact_axis_label(name, unit, max_chars=18)
                side = 'left' if ax is ax0 else 'right'
                _set_series_ylabel(ax, label, color, labelpad=12, unit=unit, side=side)
                ax.tick_params(axis='y', colors=color, labelsize=7)
                ax.spines[side].set_color(color); ax.spines[side].set_linewidth(1.5)
            ax0.set_xlabel(xlabel, fontsize=9, color=AXIS_TEXT)
            # Overlay keeps the right-hand margin adjustment because multiple twinx
            # spines require space; tight_layout cannot reason about twinx stacks.
            # Use tight_layout first to fix left/top/bottom, then carve the right.
            self.fig.tight_layout()
            right = max(0.93 - 0.065 * max(0, len(vis) - 2), 0.58)
            self.fig.subplots_adjust(right=right)
        else:
            # single channel
            ax = self.fig.add_subplot(1, 1, 1); self.axes_list.append(ax)
            _apply_axes_style(ax)
            name, t, sig, color, unit, data_id = vis[0]
            td, sd = self._ds(t, sig)
            line, = ax.plot(td, sd, color=color, lw=1.05)
            self.channel_data[name] = (t, sig, color, unit)
            self._channel_data_id[name] = data_id
            self._channel_lines[name] = (ax, line)
            # F-1: cache monotonicity once per build (see subplot branch).
            self._channel_is_monotonic[name] = _is_monotonic_array(t)
            label = _compact_axis_label(name, unit, max_chars=24)
            _set_series_ylabel(ax, label, color, labelpad=12, unit=unit, side='left')
            ax.tick_params(axis='y', colors=color, labelsize=7)
            ax.set_xlabel(xlabel, fontsize=9, color=AXIS_TEXT)
            self.fig.tight_layout()
        for ax in self.axes_list:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=10, min_n_ticks=3))
            ax.yaxis.set_major_locator(MaxNLocator(nbins=6, min_n_ticks=3))
        # ----- Phase 1 item 2: hook xlim_changed for viewport refresh -----
        # Connect ONCE on the primary x-axis. In subplot mode all axes
        # share x via sharex so listening on axes_list[0] is sufficient;
        # in overlay mode all twinx siblings share the same x, so the
        # primary axis is again axes_list[0].
        if self.axes_list:
            self._primary_xaxis_ax = self.axes_list[0]
            self._connect_xlim_listener(self._primary_xaxis_ax)
        self.draw(); self._refresh = True

    def _ds(self, t, sig, xlim=None, pixel_width=None):
        """Downsample for display.

        Backwards-compatible: when ``xlim`` and ``pixel_width`` are both
        supplied AND ``t`` is monotonic, delegate to the viewport-aware
        :meth:`_envelope`. Otherwise fall back to the legacy fixed-size
        full-series min/max reduction capped by :attr:`MAX_PTS`.

        Statistics callers MUST NOT pass through this method — see
        :meth:`get_statistics`.
        """
        if xlim is not None and pixel_width is not None:
            return self._envelope(t, sig, xlim=xlim, pixel_width=pixel_width)
        return self._ds_legacy(t, sig)

    def _ds_legacy(self, t, sig):
        """Original fixed-size full-series min/max reducer.

        Kept as the non-monotonic fallback path for custom x-axis data.
        """
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

    # ----------------------------------------------------------------
    # viewport-aware envelope (Phase 1 item 1)
    # ----------------------------------------------------------------

    def _envelope(self, t, sig, xlim, pixel_width, *, is_monotonic=None):
        """Thin wrapper around :func:`build_envelope` (spec §6.4).

        ``xlim`` stays required here on purpose — the ``xlim=None``
        full-range contract belongs to the module-level helper only and
        must not propagate to this method, otherwise ``TimeDomainCanvas``
        callers gain a compatibility surface they never asked for.
        """
        if xlim is None:
            raise TypeError(
                "TimeDomainCanvas._envelope requires an explicit xlim tuple; "
                "use build_envelope(...) for the full-range (xlim=None) contract."
            )
        return build_envelope(
            t, sig,
            xlim=xlim, pixel_width=pixel_width,
            is_monotonic=is_monotonic,
        )

    # ----------------------------------------------------------------
    # Envelope LRU cache (Phase 1 item 4)
    # ----------------------------------------------------------------

    def _envelope_cached(self, t, sig, xlim, *, data_id, channel_name,
                         pixel_width, is_monotonic=None):
        """Cache-front for :meth:`_envelope`.

        Cache key: ``(data_id, channel_name, quantized_xlim, pixel_width)``
        where ``quantized_xlim`` snaps to the bucket width (~one screen
        pixel) so sub-pixel jitter during pan still hits the same entry.

        ``is_monotonic`` is forwarded to :meth:`_envelope` on cache
        misses (F-1 follow-up). It does NOT participate in the cache key:
        the result for a given ``(data_id, channel_name, xlim,
        pixel_width)`` is deterministic regardless of which path the
        miss took, so partitioning entries by the flag would only add
        misses without changing outputs.

        Returned arrays are shared with the LRU cache; callers must
        treat them as read-only.
        """
        if pixel_width is None or pixel_width < 1:
            pixel_width = 1
        x0, x1 = float(xlim[0]), float(xlim[1])
        if x1 < x0:
            x0, x1 = x1, x0
        span = x1 - x0
        # Quantize to one bucket-width (i.e. ~1 pixel). This is roughly
        # 1/pixel_width of the view span, well within the 0.5%-1% target
        # for typical canvas widths (>=200 px). Guard against zero span.
        q = (span / pixel_width) if span > 0 else 1.0
        if q <= 0:
            q = 1.0
        qx0 = int(round(x0 / q))
        qx1 = int(round(x1 / q))
        key = (data_id, channel_name, qx0, qx1, int(pixel_width))
        cache = self._envelope_cache
        if key in cache:
            cache.move_to_end(key)
            self._envelope_cache_hits += 1
            return cache[key]
        self._envelope_cache_misses += 1
        result = self._envelope(t, sig, xlim=(x0, x1), pixel_width=pixel_width,
                                 is_monotonic=is_monotonic)
        cache[key] = result
        # LRU eviction.
        while len(cache) > self._envelope_cache_capacity:
            cache.popitem(last=False)
        return result

    def invalidate_envelope_cache(self, reason: str, *, data_id=None,
                                   channel=None):
        """Invalidate envelope cache entries.

        With no filters, drops everything (file load/close, plot mode
        change). With ``data_id`` and/or ``channel`` set, drops only
        matching entries (channel-edit / per-file invalidation).
        """
        if data_id is None and channel is None:
            self._envelope_cache.clear()
            return
        keys_to_drop = []
        for k in self._envelope_cache:
            k_data_id, k_channel = k[0], k[1]
            if data_id is not None and k_data_id != data_id:
                continue
            if channel is not None and k_channel != channel:
                continue
            keys_to_drop.append(k)
        for k in keys_to_drop:
            self._envelope_cache.pop(k, None)

    # ----------------------------------------------------------------
    # Monotonicity cache for custom x-axis arrays (Phase 1 item 6)
    # ----------------------------------------------------------------

    def _is_monotonic(self, t, custom_xaxis_fid=None, custom_xaxis_ch=None):
        """Return whether ``t`` is non-decreasing.

        When ``(custom_xaxis_fid, custom_xaxis_ch)`` is provided, the
        result is cached and reused on subsequent calls until invalidated
        via :meth:`invalidate_monotonicity_cache`.
        """
        key = (custom_xaxis_fid, custom_xaxis_ch)
        if key != (None, None):
            cached = self._monotonicity_cache.get(key)
            if cached is not None:
                self._monotonicity_cache_hits += 1
                return cached
        self._monotonicity_cache_misses += 1
        result = _is_monotonic_array(np.asarray(t))
        if key != (None, None):
            self._monotonicity_cache[key] = result
        return result

    # ----------------------------------------------------------------
    # Viewport refresh wiring (Phase 1 item 2)
    # ----------------------------------------------------------------

    def _connect_xlim_listener(self, ax):
        """Attach an xlim_changed callback to ``ax`` (single connection)."""
        # Defensive: drop any prior connection so structural rebuilds
        # don't pile up callbacks against dangling axes.
        self._disconnect_xlim_listener()
        self._xlim_cid = ax.callbacks.connect('xlim_changed',
                                              self._on_xlim_changed)

    def _disconnect_xlim_listener(self):
        """Disconnect the xlim_changed callback if one is live."""
        if self._xlim_cid is not None and self._primary_xaxis_ax is not None:
            try:
                self._primary_xaxis_ax.callbacks.disconnect(self._xlim_cid)
            except Exception:
                pass
        self._xlim_cid = None

    def _on_xlim_changed(self, _ax):
        """Coalesce rapid xlim updates into a single refresh."""
        # If a refresh is already pending, do not start another timer —
        # the existing timer's tick will pick up the latest xlim.
        if self._refresh_pending:
            return
        self._refresh_pending = True
        # Single-shot timer; 40 ms ≈ 25 Hz coalesce window.
        self._refresh_timer.start()

    def _flush_pending_refresh(self):
        """Drain any pending refresh immediately (end-of-pan/zoom)."""
        if not self._refresh_pending:
            return
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
        # Run synchronously so the final post-release frame uses
        # full-detail envelope output instead of waiting another 40 ms.
        self._refresh_visible_data()

    def _refresh_visible_data(self):
        """Recompute envelope output for the current xlim and update lines.

        Called via the QTimer started in :meth:`_on_xlim_changed` and
        immediately on mouse-release. Does NOT clear axes, rebuild lines,
        re-create the SpanSelector, call ``tight_layout()``, or rewire
        tick density — only ``Line2D.set_data`` followed by
        ``draw_idle()``.
        """
        # Always clear the pending flag at the start; if a new xlim_changed
        # arrives while we're computing, it can schedule a fresh refresh.
        self._refresh_pending = False
        if not self._channel_lines or self._primary_xaxis_ax is None:
            return
        try:
            xlim = self._primary_xaxis_ax.get_xlim()
        except Exception:
            return
        # Pixel width strategy:
        #   - Subplot mode: every axes shares the same x-extent, so the
        #     primary axis bbox width is the canonical pixel count.
        #   - Overlay mode: twinx siblings literally share the primary
        #     axis's x bbox, so the same primary-axis bbox width applies.
        # In both cases the primary axis bbox width is what we want.
        try:
            pixel_width = int(max(1, self._primary_xaxis_ax.bbox.width))
        except Exception:
            pixel_width = int(max(1, self.fig.bbox.width))
        any_changed = False
        for name, (ax, line) in self._channel_lines.items():
            entry = self.channel_data.get(name)
            if entry is None:
                continue
            t, sig, _color, _unit = entry
            data_id = self._channel_data_id.get(name)
            if data_id is None:
                # No stable cache key — fall back to the legacy reducer
                # so non-monotonic / unkeyed streams still render.
                td, sd = self._ds_legacy(t, sig)
            else:
                # F-1: pass the precomputed monotonicity flag so
                # _envelope skips the per-call np.diff(t) scan. The
                # dict is populated in plot_channels and cleared in
                # invalidate_monotonicity_cache; if a caller manages
                # to land here without populating it (e.g. external
                # mutation of channel_data), `is_monotonic=None` lets
                # _envelope fall back to the uncached scan as a safety
                # net rather than silently mis-classifying the array.
                is_monotonic = self._channel_is_monotonic.get(name)
                td, sd = self._envelope_cached(
                    t, sig, xlim,
                    data_id=data_id,
                    channel_name=name,
                    pixel_width=pixel_width,
                    is_monotonic=is_monotonic,
                )
            line.set_data(td, sd)
            any_changed = True
        if any_changed:
            # Cursor blit-cache assumes the static background; the line
            # data underneath has changed so the cache must be rebuilt
            # before the next cursor frame.
            self._refresh = True
            self.draw_idle()

    def invalidate_monotonicity_cache(self, custom_xaxis_fid=None,
                                       custom_xaxis_ch=None):
        """Drop monotonicity-cache entries.

        With no filters, clear everything. Otherwise drop entries that
        match the supplied filter components (None acts as a wildcard).

        F-1 follow-up: also clears the per-channel ``_channel_is_monotonic``
        dict. The dict is keyed by display channel name (e.g.
        ``"[A] sig1"``) which does not align with ``(fid, ch)`` filters,
        and every main_window invalidation site is followed by a
        ``plot_time()`` that rebuilds the dict via ``plot_channels``.
        Conservative full-clear here keeps the cache coherent and is a
        no-op cost (the rebuild repopulates immediately).
        """
        # Per-channel monotonicity flag — always full-cleared so the
        # next refresh either recomputes (if it lands before
        # plot_channels) or sees a freshly populated dict (after
        # plot_channels rebuilds).
        self._channel_is_monotonic.clear()
        if custom_xaxis_fid is None and custom_xaxis_ch is None:
            self._monotonicity_cache.clear()
            return
        to_drop = []
        for (fid, ch) in self._monotonicity_cache:
            if custom_xaxis_fid is not None and fid != custom_xaxis_fid:
                continue
            if custom_xaxis_ch is not None and ch != custom_xaxis_ch:
                continue
            to_drop.append((fid, ch))
        for k in to_drop:
            self._monotonicity_cache.pop(k, None)

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

    def _track_mouse_press(self, e):
        self._mouse_button_pressed = True

    def _track_mouse_release(self, e):
        self._mouse_button_pressed = False

    def _on_click(self, e):
        # Double-click on axis label region → open AxisEditDialog (priority over
        # dual-cursor / rubber-band logic). Routes to all 4 canvases via the
        # _axis_interaction helper.
        if e.button == 1 and e.dblclick:
            from ._axis_interaction import find_axis_for_dblclick, edit_axis_dialog
            ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
            if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
                self.draw_idle()
            return
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
        # Hover affordance for axis-edit dblclick. Only short-circuit during
        # active drag (mouse button currently held); pan/zoom modes themselves
        # do NOT short-circuit because the default UI state is pan-active and
        # we still want the hover hint to fire when the user is just looking.
        if not self._mouse_button_pressed:
            from ._axis_interaction import find_axis_for_dblclick
            from PyQt5.QtCore import Qt
            ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
            if ax is not None:
                self.setCursor(Qt.PointingHandCursor)
                self.setToolTip("双击编辑坐标轴")
            else:
                self.unsetCursor()
                self.setToolTip("")
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
        from html import escape
        sep = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>')
        parts = [f'<span style="color:#111827;">t={x:.4f}s</span>']
        for ch, (tf, sf, color, u) in self.channel_data.items():
            if len(tf):
                idx = min(np.searchsorted(tf, x), len(sf) - 1)
                unit_s = f" {u}" if u else ""
                name = ch[:18]
                parts.append(
                    f'<span style="color:{color};">'
                    f'{escape(name)}=<b>{sf[idx]:.4g}{escape(unit_s)}</b>'
                    f'</span>'
                )
        self.fig.canvas.blit(self.fig.bbox)
        self.cursor_info.emit(sep.join(parts))

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
            for ch, (tf, sf, color, u) in self.channel_data.items():
                if not len(tf): continue
                m = (tf >= xlo) & (tf <= xhi); seg = sf[m]
                if not len(seg): continue
                u_suffix = f" {u}" if u else ""
                dual.append((
                    ch,
                    float(np.min(seg)),
                    float(np.max(seg)),
                    float(np.mean(seg)),
                    float(np.sqrt(np.mean(seg ** 2))),
                    u_suffix,
                    color,
                ))
        if hover is not None:
            self._ensure_artists()
            for i, vl in enumerate(self._cursor_artists):
                if i < len(self.axes_list): vl.set_xdata([hover] * 2); vl.set_visible(True); self.axes_list[
                    i].draw_artist(vl)
        self.fig.canvas.blit(self.fig.bbox)
        if info:
            primary_html = ('<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
                            .join(f'<span style="color:#111827;">{p}</span>' for p in info))
        else:
            primary_html = "Click A"
        self.cursor_info.emit(primary_html)
        self.dual_cursor_info.emit(_format_dual_html(dual) if dual else "")

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
        # End-of-pan/zoom flush (Phase 1 item 2). Must run AFTER any
        # rubber-band ``set_xlim``/``set_ylim`` so that the freshly
        # scheduled xlim_changed debounce is also drained — otherwise
        # the post-zoom envelope frame is held back behind the 40 ms
        # timer (B-1). The try/finally guarantees both the rubber-band
        # branch and every early-return path (no axis lock, missing
        # press anchor, off-axis release) end with no pending QTimer.
        try:
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
        finally:
            self._flush_pending_refresh()

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


class SpectrogramCanvas(FigureCanvas):
    """FFT vs Time spectrogram canvas (Task 5 — full body).

    Renders a 2D time-frequency intensity plot in the upper axis with a
    1D frequency-slice plot underneath. Click on the spectrogram to
    select a time frame; the slice updates accordingly. Hover emits a
    cursor readout via :pyattr:`cursor_info`.

    The dB conversion cache (``_db_cache``) is canvas-local and keyed
    by ``(id(result), db_reference)`` so it is implicitly invalidated
    whenever a fresh ``SpectrogramResult`` is plotted. Per
    ``signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface``
    the cache is read on the hot path of ``plot_result`` (initial
    render) and ``_plot_slice`` / ``_on_motion`` (interaction).

    Matplotlib mouse events are connected via figure-level
    ``mpl_connect`` rather than ``Axes.callbacks`` per
    ``pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle``. The cids
    are tracked and explicitly disconnected on ``full_reset`` for
    defense-in-depth, even though figure-level connections survive
    ``fig.clear()``.
    """

    cursor_info = pyqtSignal(str)

    def __init__(self, parent=None):
        self.fig = Figure(figsize=(12, 8), dpi=100, facecolor=CHART_FACE)
        super().__init__(self.fig)
        self.setParent(parent)
        self._result = None
        self._selected_index = None
        self._amplitude_mode = 'amplitude_db'
        self._cmap = 'turbo'
        self._dynamic = '80 dB'
        self._freq_range = None
        self._db_cache = None  # (cache_key, ndarray); cache_key=(id(result), db_reference)
        # Axes / artist handles set by plot_result.
        self._ax_spec = None
        self._ax_slice = None
        self._colorbar = None
        self._cursor_line = None
        # Track figure-level mpl_connect cids so full_reset can drop them.
        # Figure-level cids survive fig.clear() (axes-level Axes.callbacks
        # do not — see lessons-learned), but tracking is cheap and lets
        # full_reset wipe them deterministically per T2's flagged note.
        self._cid_click = self.mpl_connect('button_press_event', self._on_click)
        self._cid_motion = self.mpl_connect('motion_notify_event', self._on_motion)
        # Mouse-press tracking is used by _on_motion to short-circuit the
        # axis-edit hover affordance during an active drag (e.g. while
        # the user is clicking-and-dragging in the spectrogram axis).
        self._mouse_button_pressed = False
        self.mpl_connect('button_press_event', self._track_mouse_press)
        self.mpl_connect('button_release_event', self._track_mouse_release)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def clear(self):
        self._result = None
        self._selected_index = None
        self._db_cache = None
        self._ax_spec = None
        self._ax_slice = None
        self._colorbar = None
        self._cursor_line = None
        self.fig.clear()
        self.fig.set_facecolor(CHART_FACE)

    def _disconnect_mpl_handlers(self):
        """Drop figure-level mpl cids so a re-init doesn't double-fire.

        Figure-level connections survive ``fig.clear()`` (only
        ``Axes.callbacks`` are at risk per the lessons-learned doc),
        but T2's hand-off explicitly asked us to disconnect on
        ``full_reset`` so a future code path that recreates the
        canvas cannot leak handlers. Defensive try/except in case the
        canvas's callback registry has already been torn down.
        """
        for cid_attr in ('_cid_click', '_cid_motion'):
            cid = getattr(self, cid_attr, None)
            if cid is not None:
                try:
                    self.mpl_disconnect(cid)
                except Exception:
                    pass
            setattr(self, cid_attr, None)

    def full_reset(self):
        self._disconnect_mpl_handlers()
        self.clear()
        # Re-arm the handlers so the canvas remains interactive after a
        # full reset (matches the original __init__ contract).
        self._cid_click = self.mpl_connect('button_press_event', self._on_click)
        self._cid_motion = self.mpl_connect('motion_notify_event', self._on_motion)
        self.draw_idle()

    def selected_index(self):
        return self._selected_index

    def has_result(self):
        return self._result is not None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def plot_result(self, result, amplitude_mode='amplitude_db', cmap='turbo',
                    dynamic='80 dB', freq_range=None):
        """Render ``result`` as a spectrogram with a frequency-slice strip.

        Parameters
        ----------
        result : SpectrogramResult
            The compute output. ``result.amplitude`` is shape
            ``(freq_bins, frames)``.
        amplitude_mode : {'amplitude', 'amplitude_db'}
            Whether to display linear amplitude or dB.
        cmap : str
            Matplotlib colormap name for the 2D image.
        dynamic : {'Auto', '60 dB', '80 dB'}
            Color-limit policy. Only meaningful in ``amplitude_db`` mode.
        freq_range : tuple(float, float) or None
            ``(lo, hi)`` Hz. ``hi <= 0`` or ``hi <= lo`` falls back to
            the Nyquist bin (``frequencies[-1]``).
        """
        self.clear()
        self._result = result
        self._amplitude_mode = amplitude_mode
        self._cmap = cmap
        self._dynamic = dynamic
        self._freq_range = freq_range
        self._selected_index = 0

        gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.28)
        self._ax_spec = self.fig.add_subplot(gs[0, 0])
        self._ax_slice = self.fig.add_subplot(gs[1, 0])

        z = self._display_matrix(result, amplitude_mode)
        extent = [
            float(result.times[0]),
            float(result.times[-1]),
            float(result.frequencies[0]),
            float(result.frequencies[-1]),
        ]
        vmin, vmax = self._color_limits(z, amplitude_mode, dynamic)
        im = self._ax_spec.imshow(
            z,
            origin='lower',
            aspect='auto',
            extent=extent,
            cmap=cmap,
            interpolation='nearest',
            vmin=vmin,
            vmax=vmax,
        )
        self._colorbar = self.fig.colorbar(im, ax=self._ax_spec, pad=0.01)
        self._ax_spec.set_xlabel('Time (s)')
        self._ax_spec.set_ylabel('Frequency (Hz)')
        if freq_range is not None:
            lo, hi = freq_range
            if hi <= 0 or hi <= lo:
                hi = float(result.frequencies[-1])
            self._ax_spec.set_ylim(lo, hi)
        # White vertical cursor line at the currently selected frame.
        x0 = float(result.times[0])
        self._cursor_line = self._ax_spec.axvline(x0, color='#ffffff', lw=1.2)
        self._plot_slice()
        # tight_layout warns "Axes that are not compatible with
        # tight_layout" because of the colorbar — suppress the user
        # warning, the resulting layout is still acceptable.
        import warnings as _warnings
        with _warnings.catch_warnings():
            _warnings.simplefilter('ignore', UserWarning)
            try:
                self.fig.tight_layout()
            except Exception:
                pass
        self.draw_idle()

    def _color_limits(self, z, amplitude_mode, dynamic):
        """Choose (vmin, vmax) for ``imshow`` based on amplitude mode and policy.

        Linear amplitude or 'Auto' dB → ``(nanmin, nanmax)``.
        '80 dB' / '60 dB' (only in dB mode) → ``(zmax - N, zmax)``.
        """
        zmax = float(np.nanmax(z))
        if amplitude_mode == 'amplitude_db':
            if dynamic == '80 dB':
                return zmax - 80.0, zmax
            if dynamic == '60 dB':
                return zmax - 60.0, zmax
            # 'Auto' (or any other label) → let the data dictate.
            return float(np.nanmin(z)), zmax
        # Linear amplitude.
        return float(np.nanmin(z)), zmax

    def _display_matrix(self, result, amplitude_mode):
        """Return the matrix to render. dB conversion is memoized per result.

        Cache key is ``(id(result), db_reference)`` so a re-render with
        the same result reuses the converted array, but a new
        ``SpectrogramResult`` (different ``id``) or a different
        ``db_reference`` invalidates implicitly.
        """
        if amplitude_mode == 'amplitude_db':
            ref = float(result.params.db_reference)
            cache_key = (id(result), ref)
            if self._db_cache is None or self._db_cache[0] != cache_key:
                from mf4_analyzer.signal.spectrogram import SpectrogramAnalyzer
                db = SpectrogramAnalyzer.amplitude_to_db(
                    result.amplitude, ref
                ).astype(np.float32, copy=False)
                self._db_cache = (cache_key, db)
            return self._db_cache[1]
        return result.amplitude

    def _plot_slice(self):
        """Redraw the lower 1D frequency-slice axis at ``_selected_index``."""
        if self._ax_slice is None:
            return
        self._ax_slice.clear()
        if self._result is None or self._selected_index is None:
            return
        z = self._display_matrix(self._result, self._amplitude_mode)
        # z has shape (freq_bins, frames); slice along time axis.
        idx = max(0, min(int(self._selected_index), z.shape[1] - 1))
        y = z[:, idx]
        self._ax_slice.plot(self._result.frequencies, y, color=PRIMARY, lw=1.0)
        self._ax_slice.set_xlabel('Frequency (Hz)')
        self._ax_slice.set_ylabel(
            'Amplitude dB' if self._amplitude_mode == 'amplitude_db' else 'Amplitude'
        )
        self._ax_slice.grid(True, color=GRID_LINE, alpha=0.78, ls='--', lw=0.7)
        if self._freq_range is not None:
            lo, hi = self._freq_range
            if hi <= 0 or hi <= lo:
                hi = float(self._result.frequencies[-1])
            self._ax_slice.set_xlim(lo, hi)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def select_time_index(self, idx):
        """Programmatic selection. Clamps to ``[0, frames-1]``."""
        if self._result is None:
            return
        n_frames = len(self._result.times)
        if n_frames == 0:
            return
        idx = max(0, min(int(idx), n_frames - 1))
        self._selected_index = idx
        if self._cursor_line is not None:
            x = float(self._result.times[idx])
            self._cursor_line.set_xdata([x, x])
        self._plot_slice()
        self.draw_idle()

    def _track_mouse_press(self, e):
        self._mouse_button_pressed = True

    def _track_mouse_release(self, e):
        self._mouse_button_pressed = False

    def _on_click(self, event):
        # Double-click on any axis (main spec OR slice) → open AxisEditDialog
        if event.button == 1 and event.dblclick:
            from ._axis_interaction import find_axis_for_dblclick, edit_axis_dialog
            ax, axis = find_axis_for_dblclick(self.fig, event.x, event.y, 45)
            if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
                self.draw_idle()
            return
        if self._result is None or event.inaxes is not self._ax_spec:
            return
        if event.xdata is None:
            return
        idx = int(np.argmin(np.abs(self._result.times - event.xdata)))
        self.select_time_index(idx)

    def _on_motion(self, event):
        # Axis hover affordance — fires regardless of toolbar mode, only
        # short-circuits during active drag (mouse button currently held).
        if not self._mouse_button_pressed:
            from ._axis_interaction import find_axis_for_dblclick
            from PyQt5.QtCore import Qt
            ax, axis = find_axis_for_dblclick(self.fig, event.x, event.y, 45)
            if ax is not None:
                self.setCursor(Qt.PointingHandCursor)
                self.setToolTip("双击编辑坐标轴")
            else:
                self.unsetCursor()
                self.setToolTip("")
        if self._result is None or event.inaxes is not self._ax_spec:
            # Clear the readout pill when the pointer leaves the
            # spectrogram axis (or before a result has been plotted).
            self.cursor_info.emit('')
            return
        if event.xdata is None or event.ydata is None:
            return
        t_idx = int(np.argmin(np.abs(self._result.times - event.xdata)))
        f_idx = int(np.argmin(np.abs(self._result.frequencies - event.ydata)))
        z = self._display_matrix(self._result, self._amplitude_mode)
        # Defensive bounds — argmin can never index out of range, but a
        # zero-shape matrix would; bail silently in that pathological case.
        if z.shape[0] == 0 or z.shape[1] == 0:
            return
        val = float(z[f_idx, t_idx])
        unit = 'dB' if self._amplitude_mode == 'amplitude_db' else (self._result.unit or '')
        msg = (
            f"t={self._result.times[t_idx]:.4g} s · "
            f"f={self._result.frequencies[f_idx]:.4g} Hz · "
            f"{val:.4g} {unit}"
        ).rstrip()
        self.cursor_info.emit(msg)

    # ------------------------------------------------------------------
    # Export (Plan Task 9 / T8 — clipboard pixmaps)
    # ------------------------------------------------------------------
    def grab_full_view(self):
        """Return a ``QPixmap`` of the entire canvas (spectrogram + slice).

        Phase-1 export contract used by ``MainWindow._copy_fft_time_image``
        with ``mode='full'``. Whether or not a result has been plotted,
        this returns the current canvas pixmap; the MainWindow caller
        guards on :meth:`has_result` before invoking, so a blank pixmap
        cannot reach the clipboard.
        """
        return self.grab()

    def grab_main_chart(self):
        """Return a ``QPixmap`` of the spectrogram-image region only.

        Crops to the bounding box of ``_ax_spec`` plus its colorbar so
        the lower frequency-slice strip is excluded. If the bounding box
        is unavailable (no result plotted, layout not yet realized, or
        an exception during transform conversion), falls back to
        :meth:`grab_full_view` so the export button never returns a null
        pixmap when ``has_result()`` is True.

        Phase-1 caveat: under pytest-qt headless / offscreen Qt
        platforms the figure layout has not actually rendered to a
        backing store, so ``ax.bbox`` may report stale or zero-size
        coordinates. The full-canvas fallback is the safe default; the
        validation report (T10) flags the headless limitation for
        the user.
        """
        # Defensive: no axis, no result, no layout → fall through.
        if self._result is None or self._ax_spec is None:
            return self.grab_full_view()
        try:
            # Build a Qt-pixel rect that encloses the spectrogram axis
            # and its colorbar (right-pad). matplotlib reports bboxes
            # in figure-pixel coords with origin at bottom-left; Qt's
            # rect coords have origin at top-left, so we flip y.
            from PyQt5.QtCore import QRect
            ax_bbox = self._ax_spec.get_tightbbox(self.fig.canvas.get_renderer())
            if self._colorbar is not None:
                cb_bbox = self._colorbar.ax.get_tightbbox(self.fig.canvas.get_renderer())
                # Union the two bboxes manually so we don't miss the
                # colorbar tick labels on the right edge.
                x0 = min(ax_bbox.x0, cb_bbox.x0)
                y0 = min(ax_bbox.y0, cb_bbox.y0)
                x1 = max(ax_bbox.x1, cb_bbox.x1)
                y1 = max(ax_bbox.y1, cb_bbox.y1)
            else:
                x0, y0, x1, y1 = ax_bbox.x0, ax_bbox.y0, ax_bbox.x1, ax_bbox.y1
            fig_h = self.fig.bbox.height
            # Clamp to the canvas's device pixel rect; an out-of-range
            # crop returns a null pixmap.
            dpr = self.devicePixelRatioF() if hasattr(self, 'devicePixelRatioF') else 1.0
            qx = int(max(0, x0 / dpr))
            qy = int(max(0, (fig_h - y1) / dpr))
            qw = int(max(1, (x1 - x0) / dpr))
            qh = int(max(1, (y1 - y0) / dpr))
            # Sanity: a degenerate rect (offscreen / unrealized layout)
            # should fall back rather than yield a null/stripe pixmap.
            if qw < 10 or qh < 10:
                return self.grab_full_view()
            rect = QRect(qx, qy, qw, qh)
            pix = self.grab(rect)
            if pix.isNull():
                return self.grab_full_view()
            return pix
        except Exception:
            # Any layout/transform glitch → safe fallback.
            return self.grab_full_view()


class PlotCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(20, 12), dpi=100, facecolor=CHART_FACE);
        super().__init__(self.fig);
        self.setParent(parent)
        self.mpl_connect('scroll_event', self._on_scroll)
        self.mpl_connect('button_press_event', self._on_click)
        # Hover affordance for axis-edit dblclick — track press/release so
        # we can suppress the hover cursor swap while a drag is in flight.
        self._mouse_button_pressed = False
        self.mpl_connect('button_press_event', self._track_mouse_press)
        self.mpl_connect('button_release_event', self._track_mouse_release)
        self.mpl_connect('motion_notify_event', self._on_axis_hover)
        self.setFocusPolicy(Qt.StrongFocus)
        self._remarks = []  # [(ax_index, x, y, annotation_artist, dot_artist)]
        self._line_data = {}  # {ax_index: (xdata, ydata)} for snapping
        self._remark_enabled = False
        self._last_scroll_t = 0  # 滚轮节流
        self._scroll_timer = QTimer()
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(lambda: self.draw_idle())
        # Heatmap reuse handles (spec §6.2 / plan T4 step 7).
        # ``plot_or_update_heatmap`` populates these; ``clear()`` resets
        # them. Init here so the first call's ``getattr(..., None)`` is
        # not the only thing keeping the compat-check honest — the
        # matplotlib-axes-callbacks-lifecycle lesson applies: stale
        # handles after a structural rebuild silently bypass the
        # 4-clause check otherwise.
        self._heatmap_ax = None
        self._heatmap_im = None
        self._heatmap_cbar = None

    def clear(self):
        self._remarks = []
        self._line_data = {}
        # Reset heatmap handles BEFORE fig.clear() so any caller racing
        # against a partially-cleared figure sees a consistent "no
        # heatmap" state. fig.clear() destroys the underlying axes; if
        # we leave the handles dangling, the next plot_or_update_heatmap
        # may pass clauses 1-3 of the compat check (handles not None,
        # in fig.axes if Python still holds the ref) yet operate on a
        # dead artist.
        self._heatmap_ax = None
        self._heatmap_im = None
        self._heatmap_cbar = None
        self.fig.clear()
        self.fig.set_facecolor(CHART_FACE)

    def plot_or_update_heatmap(self, *, matrix, x_extent, y_extent,
                                x_label, y_label, title,
                                cmap='turbo', interp='bilinear',
                                vmin=None, vmax=None,
                                cbar_label='Amplitude'):
        """Render a 2-D heatmap; on a compatible second call reuse the
        existing axes / image / colorbar via ``set_data`` instead of
        rebuilding (spec §4.2 / §6.2).

        ``matrix`` is shape ``(N_y, N_x)`` matching ``imshow`` row/col
        layout. ``x_extent`` / ``y_extent`` are ``(min, max)``.

        Compatibility judgement (all 4 must hold to take the
        ``set_data`` fast path; otherwise fall back to ``clear()`` +
        rebuild):

        1. Three handles all non-``None``;
        2. heatmap axes still member of ``fig.axes`` (rules out
           accidental destruction by external code paths);
        3. ``len(fig.axes) == 2`` — heatmap + its colorbar exactly,
           rules out the 2-subplot ``order_track`` layout;
        4. existing image's array shape equals the new matrix shape —
           ``AxesImage.set_data`` accepts shape changes but downstream
           extent/clim wiring becomes brittle; we conservatively rebuild
           in that case.

        Non-uniform-grid warning: ``imshow`` requires a uniform grid on
        both axes. If a future caller introduces logarithmic RPM bins
        etc., do NOT call this method — fall back to ``pcolormesh`` or a
        dedicated canvas.
        """
        m = np.asarray(matrix, dtype=float)
        if vmin is None:
            vmin = float(np.nanmin(m))
        if vmax is None:
            vmax = float(np.nanmax(m))

        existing_ax = getattr(self, '_heatmap_ax', None)
        existing_im = getattr(self, '_heatmap_im', None)
        existing_cbar = getattr(self, '_heatmap_cbar', None)
        compatible = (
            existing_ax is not None
            and existing_im is not None
            and existing_cbar is not None
            and existing_ax in self.fig.axes
            and len(self.fig.axes) == 2
            and existing_im.get_array().shape == m.shape
        )
        if compatible:
            existing_im.set_data(m)
            existing_im.set_extent([x_extent[0], x_extent[1],
                                    y_extent[0], y_extent[1]])
            existing_im.set_cmap(cmap)
            existing_im.set_interpolation(interp)
            existing_im.set_clim(vmin, vmax)
            existing_ax.set_xlim(x_extent)
            existing_ax.set_ylim(y_extent)
            existing_ax.set_xlabel(x_label)
            existing_ax.set_ylabel(y_label)
            existing_ax.set_title(title)
            existing_cbar.update_normal(existing_im)
            existing_cbar.set_label(cbar_label)
            self.draw_idle()
            return

        # Incompatible / first call → rebuild from scratch.
        self.clear()
        ax = self.fig.add_subplot(1, 1, 1)
        im = ax.imshow(
            m, origin='lower', aspect='auto',
            extent=[x_extent[0], x_extent[1], y_extent[0], y_extent[1]],
            cmap=cmap, interpolation=interp,
            vmin=vmin, vmax=vmax,
        )
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        ax.set_title(title)
        cbar = self.fig.colorbar(im, ax=ax, label=cbar_label)
        try:
            self.fig.tight_layout()
        except Exception:
            pass
        self._heatmap_ax = ax
        self._heatmap_im = im
        self._heatmap_cbar = cbar
        self.draw_idle()

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

    def _track_mouse_press(self, e):
        self._mouse_button_pressed = True

    def _track_mouse_release(self, e):
        self._mouse_button_pressed = False

    def _on_axis_hover(self, e):
        # Hover affordance for axis-edit dblclick. Skip during active drag
        # so the cursor/tooltip don't flicker while the user manipulates
        # remarks or pans. Routes through the shared _axis_interaction
        # helper for parity with TimeDomainCanvas / SpectrogramCanvas /
        # OrderTrackCanvas.
        if self._mouse_button_pressed:
            return
        from ._axis_interaction import find_axis_for_dblclick
        ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
        if ax is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("双击编辑坐标轴")
        else:
            self.unsetCursor()
            self.setToolTip("")

    def _on_click(self, e):
        # 双击编辑坐标轴 — 优先处理，不要求点击在axes内部
        if e.button == 1 and e.dblclick:
            from ._axis_interaction import find_axis_for_dblclick, edit_axis_dialog
            ax, axis = find_axis_for_dblclick(self.fig, e.x, e.y, 45)
            if ax is not None and edit_axis_dialog(self.parent(), ax, axis):
                self.draw_idle()
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
