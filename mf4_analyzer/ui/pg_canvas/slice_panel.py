"""The heatmap canvas's 1D slice strip and its X/Y direction toggle.

Split out of ``heatmap_canvas.py``, where roughly 400 lines of slice behaviour
sat interleaved with the 2D map's own render, colorbar and remark paths, each
consumer guarded on ``self._slice_curve is not None``. Every "slice" change
landed in the canvas's largest file.

``PgHeatmapCanvas`` still owns the state and still exposes every slice method
it always did -- those are one-line delegates to ``self._slice`` now. What
lives here is the behaviour:

* ``_SliceDirToggle`` -- the two-segment 按X/按Y switch in the info panel;
* ``_SliceStrip`` -- seeding, direction, index clamping, curve + marker
  rendering, drag-to-reslice, the readout text, and the geometry that keeps
  the strip's right edge aligned with the map above it.

``_SliceStrip`` is a ``_CanvasBackref``, so ``self._slice_x_idx``,
``self._matrix_disp``, ``self._time_index_for(...)`` and ``self.slice_picked``
all still mean the CANVAS's -- reads and writes forward. That is deliberate:
tests and ``ui/main_window/_order_mixin.py`` read ``canvas._slice_*`` directly,
and keeping the fields there let this code move without a single body edit.

dB-domain amplitude bounds are NOT re-implemented here: ``_slice_amp_bounds``
and ``_SLICE_MAX_SPAN_DB`` live in the neutral ``qt_analysis_shared`` layer and
reach this module via ``analysis_axes``.
"""
from __future__ import annotations

import logging

import numpy as np
import pyqtgraph as pg
from PyQt5 import sip
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QPushButton, QWidget

from mf4_analyzer.render_profile import envelope_ink_dev_px
from mf4_analyzer.signal.display_ranges import line_amplitude_limits, visible_line_values

from mf4_analyzer.ui._axis_handle import (
    PG_AXIS_NEUTRAL_COLOR,
    PG_AXIS_NEUTRAL_WIDTH,
)
from mf4_analyzer.ui.pg_canvas._backref import _CanvasBackref
from mf4_analyzer.ui.pg_canvas.analysis_axes import (
    _hide_plot_title,
)
from mf4_analyzer.ui.pg_canvas.quality import (
    _BACKSTOP_BLACKLIST_MAX,
    _BACKSTOP_EPOCH_PROPERTY,
    _BACKSTOP_FIRST_AA_MS,
    _BACKSTOP_STEADY_AA_MS,
    _BACKSTOP_STEADY_EMA_ALPHA,
)
from mf4_analyzer.ui.pg_canvas.quality_backstop import AaFrameLatch


logger = logging.getLogger(__name__)


class _SliceDirToggle(QWidget):
    """Two-segment X/Y slice-direction switch overlaid on the slice view's
    top-right corner. ``direction_changed`` emits 'x' or 'y'.

    'x' = fix a position on the X axis (a time) → slice shows amplitude vs the
    Y axis (frequency / order). 'y' = fix a position on the Y axis → slice
    shows amplitude vs time. The two button labels are supplied by the owner so
    FFT-vs-Time reads 「按时间 / 按频率」 and Order reads 「按时间 / 按阶次」.
    """

    direction_changed = pyqtSignal(str)

    def __init__(self, x_label, y_label, parent=None):
        super().__init__(parent)
        self.setObjectName("sliceDirToggle")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self._btn_x = QPushButton(x_label, self)
        self._btn_y = QPushButton(y_label, self)
        for b, d in ((self._btn_x, 'x'), (self._btn_y, 'y')):
            b.setCheckable(True)
            b.setProperty("role", "slice-seg")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, _d=d: self.set_direction(_d))
            box.addWidget(b, 1)  # split the panel width evenly
        self._dir = 'x'
        self._sync_buttons()

    def direction(self):
        return self._dir

    def set_direction(self, d, *, emit=True):
        d = 'y' if d == 'y' else 'x'
        if d == self._dir:
            self._sync_buttons()
            return
        self._dir = d
        self._sync_buttons()
        if emit:
            self.direction_changed.emit(d)

    def _sync_buttons(self):
        self._btn_x.setChecked(self._dir == 'x')
        self._btn_y.setChecked(self._dir == 'y')


class _SliceStrip(_CanvasBackref):
    """The heatmap's 1D slice strip: direction, index, curve, marker,
    info panel and the geometry that keeps it aligned to the map above.

    Every ``_slice_*`` field stays on the CANVAS -- ``_CanvasBackref``
    forwards reads and writes -- because tests and ``ui/main_window`` read
    ``canvas._slice_plot`` / ``._slice_dir`` / ``._slice_x_idx`` directly.
    The same forwarding is what lets these method bodies stay byte-for-byte
    what they were on ``PgHeatmapCanvas``: ``self._matrix_disp``,
    ``self._time_index_for(...)``, ``self.slice_picked`` and the rest still
    resolve to the canvas.

    Slice AA settlement state (discrete timer, latch, ink cache, pending
    flag) is owned here. ``_slice_aa_on`` and ``_slice_aa_idle_timer`` stay
    on the canvas: tests and the 150 ms interaction path already read them
    there. ``_aa_backstop_armed`` also stays on the canvas because the
    resident paint timer reads that bare attribute on every frame.
    """

    # New settlement state must be listed here. An undeclared ``self.X =``
    # becomes write-through and fails test_pg_canvas_backref_invariants.
    _owned_names = frozenset({
        "_slice_aa_block_reason",
        "_slice_aa_latch",
        "_slice_backstop_timer",
        "_slice_discrete_aa_timer",
        "_slice_discrete_quality_deferred",
        "_slice_discrete_quality_hold",
        "_slice_discrete_settle_pending",
        "_slice_ink_allowed",
        "_slice_ink_dev_px",
        "_slice_ink_seeded",
    })

    def __init__(self, canvas):
        super().__init__(canvas)
        # Separate from the 150 ms idle timer. QTimer.start(int) permanently
        # rewrites interval, so a 0 ms settle must not reuse that timer.
        self._slice_discrete_aa_timer = QTimer(canvas)
        self._slice_discrete_aa_timer.setSingleShot(True)
        self._slice_discrete_aa_timer.setInterval(0)
        self._slice_discrete_quality_hold = None
        self._slice_discrete_quality_deferred = False
        self._slice_discrete_aa_timer.timeout.connect(
            self.try_enable_idle_quality)
        self._slice_backstop_timer = QTimer(canvas)
        self._slice_backstop_timer.setSingleShot(True)
        self._slice_backstop_timer.setInterval(0)
        self._slice_backstop_timer.timeout.connect(
            self._on_slice_backstop_timeout)
        self._slice_aa_latch = self._new_slice_aa_latch()
        self._slice_ink_allowed = False
        self._slice_ink_seeded = False
        self._slice_ink_dev_px = None
        self._slice_discrete_settle_pending = False
        self._slice_aa_block_reason = None
        canvas.destroyed.connect(self._on_slice_canvas_destroyed)

    def _new_slice_aa_latch(self) -> AaFrameLatch:
        # Ceilings are borrowed, not a slice calibration. Spec 2026-09-23 §5:
        # 借用 ``_BACKSTOP_FIRST_AA_MS`` / ``_BACKSTOP_STEADY_AA_MS``，待标定.
        return AaFrameLatch(
            _BACKSTOP_FIRST_AA_MS,
            _BACKSTOP_STEADY_AA_MS,
            _BACKSTOP_STEADY_EMA_ALPHA,
            _BACKSTOP_BLACKLIST_MAX,
        )

    def _slice_canvas_alive(self) -> bool:
        try:
            return not sip.isdeleted(self._c)
        except RuntimeError:
            return False

    def _slice_timer_alive(self, timer):
        """Return ``timer`` when it and the canvas still exist in C++."""
        if timer is None or not self._slice_canvas_alive():
            return None
        try:
            if sip.isdeleted(timer):
                return None
        except RuntimeError:
            return None
        return timer

    def _stop_slice_timer(self, timer) -> None:
        alive = self._slice_timer_alive(timer)
        if alive is None:
            return
        try:
            alive.stop()
        except RuntimeError:
            return

    def _apply_slice_curve_aa_state(self) -> None:
        if self._slice_curve is None:
            return
        self._set_curve_aa(self._slice_curve, self._slice_aa_on)
        try:
            self._glw.update()
        except RuntimeError:
            return

    def _reset_slice_quality_for_rebuild(self) -> None:
        """Drop slice AA for a heatmap rebuild and arm the discrete settle.

        The call itself must not paint an AA frame. The 0 ms timer decides
        on the next event-loop turn, after ``_seed_slice`` has installed the
        new samples. Interaction keeps using ``_slice_aa_idle_timer``.
        """
        self._stop_slice_timer(self._slice_aa_idle_timer)
        self._close_slice_backstop_session()
        self._slice_ink_seeded = False
        self._slice_ink_allowed = False
        self._slice_ink_dev_px = None
        self._slice_aa_block_reason = None
        self._slice_aa_on = False
        if self._slice_curve is None:
            self._slice_discrete_settle_pending = False
            self._stop_slice_timer(self._slice_discrete_aa_timer)
            return
        self._apply_slice_curve_aa_state()
        self._arm_slice_discrete_aa()

    def _arm_slice_discrete_aa(self) -> None:
        """Arm one 0 ms settle against the samples now on the slice curve."""
        self._stop_slice_timer(self._slice_aa_idle_timer)
        self._close_slice_backstop_session()
        self._slice_ink_seeded = False
        self._slice_ink_allowed = False
        self._slice_ink_dev_px = None
        self._slice_aa_block_reason = None
        self._slice_aa_on = False
        if self._slice_curve is None:
            self._slice_discrete_settle_pending = False
            self._stop_slice_timer(self._slice_discrete_aa_timer)
            return
        self._apply_slice_curve_aa_state()
        timer = self._slice_timer_alive(self._slice_discrete_aa_timer)
        if timer is None:
            self._slice_discrete_settle_pending = False
            self._slice_discrete_quality_deferred = False
            return
        self._slice_discrete_settle_pending = True
        if self._slice_discrete_quality_hold is not None:
            self._stop_slice_timer(timer)
            self._slice_discrete_quality_deferred = True
            return
        self._slice_discrete_quality_deferred = False
        timer.start()

    def hold_discrete_quality(self, token) -> None:
        """Defer the slice's 0 ms AA settle for a page-transition token."""
        self._slice_discrete_quality_hold = token
        timer = self._slice_timer_alive(self._slice_discrete_aa_timer)
        if timer is not None and timer.isActive():
            self._stop_slice_timer(timer)
            self._slice_discrete_quality_deferred = True

    def release_discrete_quality(self, token) -> None:
        """Arm one deferred slice settle after the matching transition."""
        if self._slice_discrete_quality_hold != token:
            return
        self._slice_discrete_quality_hold = None
        deferred = self._slice_discrete_quality_deferred
        self._slice_discrete_quality_deferred = False
        if not deferred or self._slice_curve is None:
            self._slice_discrete_settle_pending = False
            return
        timer = self._slice_timer_alive(self._slice_discrete_aa_timer)
        if timer is None:
            self._slice_discrete_settle_pending = False
            return
        self._slice_discrete_settle_pending = True
        timer.start()

    def release_slice_quality_state(self) -> None:
        """Drop latch, pending settle, and timers. Used by canvas clear."""
        self._stop_slice_timer(self._slice_aa_idle_timer)
        self._stop_slice_timer(self._slice_discrete_aa_timer)
        self._stop_slice_timer(self._slice_backstop_timer)
        self._slice_discrete_settle_pending = False
        self._slice_discrete_quality_deferred = False
        self._close_slice_backstop_session()
        self._slice_aa_latch = self._new_slice_aa_latch()
        self._slice_ink_seeded = False
        self._slice_ink_allowed = False
        self._slice_ink_dev_px = None
        self._slice_aa_block_reason = None
        self._slice_aa_on = False
        if self._slice_curve is not None:
            self._apply_slice_curve_aa_state()

    def _on_slice_canvas_destroyed(self, *_args) -> None:
        """Stop settle timers and forget measured sessions with the canvas."""
        self._slice_discrete_settle_pending = False
        self._stop_slice_timer(self._slice_discrete_aa_timer)
        self._stop_slice_timer(self._slice_backstop_timer)
        self._slice_aa_latch.close()
        self._slice_aa_latch.blacklist.clear()
        self._slice_aa_latch.memo.clear()
        if not self._slice_canvas_alive():
            return
        self._c._aa_backstop_armed = False

    def disable_interactive_quality(self) -> None:
        """Drop slice-curve AA while the user is actively moving the view."""
        self._stop_slice_timer(self._slice_aa_idle_timer)
        self._stop_slice_timer(self._slice_discrete_aa_timer)
        self._slice_discrete_settle_pending = False
        self._slice_discrete_quality_deferred = False
        self._close_slice_backstop_session()
        if self._slice_curve is None or not self._slice_aa_on:
            return
        self._slice_aa_on = False
        self._apply_slice_curve_aa_state()

    def schedule_idle_quality(self) -> None:
        """Restore slice-curve AA after the 150 ms interaction quiet window."""
        if self._slice_curve is None:
            return
        timer = self._slice_timer_alive(self._slice_aa_idle_timer)
        if timer is None:
            return
        # No argument: start(int) would permanently replace the 150 ms interval.
        timer.start()

    def try_enable_idle_quality(self) -> None:
        """Shared gate for the 0 ms discrete settle and the 150 ms idle timer."""
        if not self._slice_canvas_alive():
            return
        if self._slice_curve is None or self._slice_aa_on:
            self._stop_slice_timer(self._slice_discrete_aa_timer)
            self._stop_slice_timer(self._slice_aa_idle_timer)
            self._slice_discrete_settle_pending = False
            return
        try:
            buttons_down = QApplication.mouseButtons() != Qt.NoButton
        except RuntimeError:
            logger.warning(
                "slice idle-quality mouse query failed", exc_info=True)
            buttons_down = False
        if buttons_down:
            self._stop_slice_timer(self._slice_discrete_aa_timer)
            self._slice_discrete_settle_pending = False
            self.schedule_idle_quality()
            return
        self._stop_slice_timer(self._slice_discrete_aa_timer)
        self._stop_slice_timer(self._slice_aa_idle_timer)
        self._slice_discrete_settle_pending = False
        signature = self._slice_view_signature()
        if self._slice_aa_latch.blocked(signature):
            self._slice_aa_block_reason = "aa-backstop"
            return
        if not self._slice_ink_allowed_now():
            return
        self._slice_aa_block_reason = None
        self._slice_aa_on = True
        # Arm before the update. _apply_slice_curve_aa_state repaints, and a
        # synchronous paint has to land inside this session or the backstop
        # never sees the frame it just paid for.
        if signature is not None:
            self._open_slice_backstop_session(signature)
        self._apply_slice_curve_aa_state()

    def _borrowed_spectrum_ink_band(self):
        """Spectrum-row admission band, borrowed until the slice is calibrated.

        Spec 2026-09-23 §5: 借用 ``_SPECTRUM_INK_AA_ON/OFF``，待标定.
        The numbers stay on the spectrum row; this is a reference.
        """
        from mf4_analyzer.ui.pg_canvas.line_canvas import (
            _SPECTRUM_INK_AA_OFF,
            _SPECTRUM_INK_AA_ON,
        )
        return _SPECTRUM_INK_AA_ON, _SPECTRUM_INK_AA_OFF

    def _measure_slice_ink(self):
        """Device-pixel ink of the slice curve, or ``None`` when unknown.

        Unknown is not zero: a missing row height must not read as a free
        curve and turn AA on.
        """
        curve = self._slice_curve
        plot = self._slice_plot
        if curve is None or plot is None:
            return None
        try:
            _x_data, y_data = curve.getData()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
        if y_data is None:
            return None
        try:
            view_box = plot.vb
            view_box.updateAutoRange()
            y_range = view_box.viewRange()[1]
            y_span = abs(float(y_range[1]) - float(y_range[0]))
            row_height_px = float(view_box.sceneBoundingRect().height())
            dpr = float(self._glw.devicePixelRatioF())
        except (AttributeError, IndexError, RuntimeError, TypeError,
                ValueError):
            return None
        if not np.isfinite(row_height_px) or row_height_px <= 0.0:
            return None
        if not np.isfinite(dpr) or dpr <= 0.0:
            return None
        return envelope_ink_dev_px(
            y_data, y_span=y_span, row_height_px=row_height_px, dpr=dpr)

    def _slice_ink_allowed_now(self) -> bool:
        """Hysteresis ink leg. Band borrowed from the spectrum row."""
        total = self._measure_slice_ink()
        if total is None:
            self._slice_aa_block_reason = "unknown-ink"
            return False
        self._slice_ink_dev_px = float(total)
        on_ink, off_ink = self._borrowed_spectrum_ink_band()
        if not self._slice_ink_seeded:
            self._slice_ink_allowed = total <= off_ink
            self._slice_ink_seeded = True
        elif total <= on_ink:
            self._slice_ink_allowed = True
        elif total > off_ink:
            self._slice_ink_allowed = False
        if not self._slice_ink_allowed:
            self._slice_aa_block_reason = "high-ink"
            return False
        return True

    def _slice_view_signature(self):
        """Identity of this slice's AA cost, or ``None`` when geometry is unknown."""
        plot = self._slice_plot
        curve = self._slice_curve
        if plot is None or curve is None:
            return None
        try:
            from mf4_analyzer.ui.pg_canvas.renderer import _quantize_y_span_key

            view_box = plot.vb
            y_range = view_box.viewRange()[1]
            y_span = abs(float(y_range[1]) - float(y_range[0]))
            rect = view_box.sceneBoundingRect()
            _x_data, y_data = curve.getData()
            n_points = 0 if y_data is None else int(len(y_data))
            return (
                "slice",
                str(self._slice_dir),
                int(self._slice_x_idx),
                int(self._slice_y_idx),
                n_points,
                _quantize_y_span_key(y_span),
                int(rect.height()),
                int(rect.width()),
            )
        except (AttributeError, IndexError, RuntimeError, TypeError,
                ValueError):
            return None

    def _open_slice_backstop_session(self, signature) -> None:
        self._slice_aa_latch.open(signature)
        self._c._aa_backstop_armed = True

    def _close_slice_backstop_session(self) -> None:
        armed = bool(self._c._aa_backstop_armed)
        session_open = bool(self._slice_aa_latch.session_open)
        if not armed and not session_open:
            return
        self._c._aa_backstop_armed = False
        self._slice_aa_latch.close()

    def _note_slice_aa_frame(self, frame_ms) -> None:
        """Feed one measured AA frame. Called from the canvas paint timer."""
        if not self._slice_canvas_alive() or not self._c._aa_backstop_armed:
            return
        trip = self._slice_aa_latch.note_frame(frame_ms)
        if trip is not None:
            self._trip_slice_backstop(trip[0], trip[1])

    def _trip_slice_backstop(self, reason, measured_ms) -> None:
        """Disarm now; drop AA on the next turn so paint is not mutated."""
        self._c._aa_backstop_armed = False
        self._slice_aa_latch.reason = (str(reason), float(measured_ms))
        timer = self._slice_timer_alive(self._slice_backstop_timer)
        if timer is None:
            logger.warning(
                "slice AA backstop tripped (%s, %.1f ms) but its timer is "
                "gone; antialiasing stays on for this session",
                reason, float(measured_ms),
            )
            return
        try:
            timer.setProperty(
                _BACKSTOP_EPOCH_PROPERTY, int(self._slice_aa_latch.epoch))
            timer.start()
        except RuntimeError:
            logger.warning(
                "slice AA backstop trip could not be queued", exc_info=True)

    def _on_slice_backstop_timeout(self) -> None:
        """Drop AA only for the epoch that measured the unaffordable frame."""
        timer = self._slice_timer_alive(self._slice_backstop_timer)
        if timer is None:
            return
        try:
            epoch = int(timer.property(_BACKSTOP_EPOCH_PROPERTY))
        except (RuntimeError, TypeError, ValueError):
            return
        if epoch != int(self._slice_aa_latch.epoch):
            return
        self._slice_aa_block_reason = "aa-backstop"
        self.disable_interactive_quality()

    def _slice_settle_pending(self) -> bool:
        if self._slice_discrete_settle_pending:
            return True
        for timer in (
            self._slice_discrete_aa_timer,
            self._slice_aa_idle_timer,
        ):
            alive = self._slice_timer_alive(timer)
            if alive is None:
                continue
            try:
                if alive.isActive():
                    return True
            except RuntimeError:
                continue
        return False

    def slice_quality_status(self) -> dict:
        """Observable slice AA state, same vocabulary as the chart quality dot.

        ``preview`` / ``red`` with ``block_reason`` is the existing "受限"
        indication: ink over the borrowed band, or a measured frame that
        tripped the backstop. A refusal is never a silent AA-off.
        """
        curve = self._slice_curve
        if curve is None:
            return {
                "state": "idle",
                "tooltip": "无切片曲线",
                "block_reason": "no-curve",
            }
        try:
            actual_on = bool(curve.opts.get("antialias", False))
        except (AttributeError, RuntimeError, TypeError):
            actual_on = False
        if self._slice_aa_on and actual_on:
            return {"state": "green", "tooltip": "精细显示"}
        if self._slice_settle_pending():
            return {"state": "yellow", "tooltip": "正在细化：等待空闲刷新"}
        reason = self._slice_aa_block_reason
        if reason == "aa-backstop" or (
            self._slice_aa_latch.blacklist
            and self._slice_aa_latch.blocked(self._slice_view_signature())
        ):
            return {
                "state": "red",
                "block_reason": "aa-backstop",
                "tooltip": "绘制异常：实测帧超时",
            }
        if reason == "high-ink" or (
            self._slice_ink_seeded and not self._slice_ink_allowed
        ):
            return {
                "state": "preview",
                "block_reason": "high-ink",
                "tooltip": (
                    "流畅预览：切片曲线填满绘图区，绘制量超预算"
                    "（已按墨迹预算关闭抗锯齿）"
                ),
            }
        if reason == "unknown-ink":
            return {
                "state": "red",
                "block_reason": "unknown-ink",
                "tooltip": "绘制异常：绘制量无法测量",
            }
        return {"state": "red", "tooltip": "绘制异常：抗锯齿未激活"}

    def _slice_coords(self):
        """Return (x_coords, y_coords) for the displayed matrix, falling back
        to a regular grid derived from the extents when no explicit arrays were
        supplied (parity with how the image is drawn across the extents)."""
        m = self._matrix_disp
        if m is None or self._extents is None:
            return None, None
        nrows, ncols = m.shape[0], m.shape[1]
        x0, x1, y0, y1 = self._extents
        xc = self._x_coords
        if xc is None or len(xc) != ncols:
            xc = np.linspace(float(x0), float(x1), ncols)
        yc = self._y_coords
        if yc is None or len(yc) != nrows:
            yc = np.linspace(float(y0), float(y1), nrows)
        return xc, yc

    def _seed_slice(self):
        """Position the slice and render it.

        On the FIRST render (no prior position) the slice lands at the matrix
        centre. On a RE-render it maps the previous cursor position back by
        COORDINATE value (time / frequency) to the nearest index, so changing
        an inspector knob and re-rendering does not snap the slice to the
        middle — it stays where the user put it (parity with a colorbar drag
        leaving the matrix intact)."""
        m = self._matrix_disp
        if m is None or self._slice_curve is None:
            return
        nrows, ncols = m.shape[0], m.shape[1]
        xc, yc = self._slice_coords()
        if self._slice_x_val is not None and xc is not None and len(xc):
            self._slice_x_idx = int(np.argmin(np.abs(np.asarray(xc) - self._slice_x_val)))
        else:
            self._slice_x_idx = ncols // 2
        if self._slice_y_val is not None and yc is not None and len(yc):
            self._slice_y_idx = int(np.argmin(np.abs(np.asarray(yc) - self._slice_y_val)))
        else:
            self._slice_y_idx = nrows // 2
        self._apply_slice()
        # Re-arm after the samples are on the curve. plot_or_update_heatmap
        # arms once before this seed; a processEvents in between would
        # otherwise settle the previous (or empty) curve.
        self._arm_slice_discrete_aa()

    def set_slice_direction(self, direction: str) -> None:
        """Switch the slice between 'x' (fix time → amp vs Y) and 'y' (fix
        frequency/order → amp vs time). Re-renders the slice + flips the marker."""
        direction = 'y' if direction == 'y' else 'x'
        self._slice_dir = direction
        if self._slice_toggle is not None:
            self._slice_toggle.set_direction(direction, emit=False)
        if self._matrix_disp is None:
            if not self.isVisible():
                return
            self._apply_default_axis_labels()
            return
        self._apply_slice()

    def select_time_index(self, idx: int) -> None:
        """Back-compat entry point: place an X slice (fixed time) at frame
        ``idx``. Preserved for the FFT-vs-Time auto-seed + tests."""
        if self._matrix_disp is None or self._slice_curve is None:
            return
        ncols = self._matrix_disp.shape[1]
        self._slice_dir = 'x'
        self._slice_x_idx = int(np.clip(idx, 0, max(0, ncols - 1)))
        if self._slice_toggle is not None:
            self._slice_toggle.set_direction('x', emit=False)
        self._apply_slice()

    @staticmethod
    def _slice_visible_mask(coords, lo: float, hi: float):
        """Keep visible centers and adjacent endpoints of crossing segments."""
        arr = np.asarray(coords, dtype=float)
        finite = np.isfinite(arr)
        lo, hi = sorted((float(lo), float(hi)))
        mask = finite & (arr >= lo) & (arr <= hi)
        adjacent = finite[:-1] & finite[1:]
        for boundary in (lo, hi):
            crossing = adjacent & (((arr[:-1] < boundary) & (arr[1:] > boundary))
                                   | ((arr[:-1] > boundary) & (arr[1:] < boundary)))
            indices = np.flatnonzero(crossing)
            mask[indices] = True
            mask[indices + 1] = True
        selected = np.flatnonzero(mask)
        if selected.size:
            # Keep intervening NaN coordinates as drawing breaks. Removing
            # them would connect physically disconnected finite samples.
            mask[selected[0]:selected[-1] + 1] = True
        return mask

    def _set_slice_x_range(self, lo: float, hi: float, values) -> None:
        if self._slice_plot is None:
            return
        lo, hi = sorted((float(lo), float(hi)))
        if hi > lo:
            self._slice_plot.setXRange(lo, hi, padding=0)
            return
        arr = np.asarray(values, dtype=float)
        finite = arr[np.isfinite(arr)]
        if finite.size:
            center = float(finite[0])
            pad = max(abs(center) * 0.01, 0.5)
            self._slice_plot.setXRange(center - pad, center + pad, padding=0)

    def _slice_axis_range(self, panel_range, view_axis: str, coords):
        """Follow the applied main viewport, including zoom and Home."""
        vr = self._main_view_range(view_axis)
        if vr is not None:
            return vr
        if panel_range is not None:
            return tuple(sorted(map(float, panel_range)))
        arr = np.asarray(coords, dtype=float)
        finite = arr[np.isfinite(arr)]
        return (float(finite.min()), float(finite.max())) if finite.size else (0., 1.)

    def _apply_slice_amp_range(self, values) -> None:
        """Set the slice's amplitude (vertical) axis.

        Manual z (``_panel_amp_range`` set) clamps the amplitude axis to
        ``[z_floor, z_ceiling]`` — the same window as the colorbar so the
        slice and image share one amplitude caliber. Auto z
        (``_panel_amp_range is None``) enables pyqtgraph auto-fit on the
        already freq/time-range-clipped curve data."""
        if self._slice_plot is None:
            return
        vb = self._slice_plot.vb
        rng = self._panel_amp_range
        if rng is not None:
            lo, hi = sorted((float(rng[0]), float(rng[1])))
            if hi > lo:
                vb.enableAutoRange(axis=vb.YAxis, enable=False)
                self._slice_plot.setYRange(lo, hi, padding=0)
                return
        bounds = line_amplitude_limits(values, amplitude_mode=self._amplitude_mode)
        # Explicit empty view: never inherit a previous curve's range.
        lo, hi = bounds if bounds is not None else (0., 1.)
        vb.enableAutoRange(axis=vb.YAxis, enable=False)
        self._slice_plot.setYRange(lo, hi, padding=0)

    def _raw_slice_arrays(self):
        xc, yc = self._slice_coords()
        if self._slice_dir == 'y':
            idx = self._slice_y_idx
            return xc, self._matrix_disp[idx, :], self._matrix_amp_valid[idx, :]
        idx = self._slice_x_idx
        return yc, self._matrix_disp[:, idx], self._matrix_amp_valid[:, idx]

    def fit_y_to_visible_x(self) -> None:
        """Fit the raw slice in the visible window, independently of color Z."""
        if self._slice_plot is None or self._matrix_disp is None:
            return
        xs, ys, valid = self._raw_slice_arrays()
        xlim = self._slice_plot.vb.viewRange()[0]
        values = visible_line_values(xs, ys, xlim, valid_mask=valid)
        bounds = line_amplitude_limits(values, amplitude_mode=self._amplitude_mode)
        self.disable_interactive_quality()
        self._slice_plot.vb.enableAutoRange(axis=self._slice_plot.vb.YAxis, enable=False)
        self._slice_plot.setYRange(*(bounds or (0., 1.)), padding=0)
        self.schedule_idle_quality()

    def _apply_slice(self, *, refresh_chrome: bool = True) -> None:
        """Render the slice curve + marker for the current direction/index."""
        m = self._matrix_disp
        if m is None or self._slice_curve is None:
            return
        xc, yc = self._slice_coords()
        if xc is None or m.size == 0:
            self._slice_curve.clear()
            self._apply_slice_amp_range([])
            return
        nrows, ncols = m.shape[0], m.shape[1]
        if self._slice_dir == 'y':
            # Fix a Y position (frequency / order) → curve = amplitude vs time.
            # Horizontal axis is TIME → panel x_* range (when manual).
            idx = int(np.clip(self._slice_y_idx, 0, max(0, nrows - 1)))
            self._slice_y_idx = idx
            self._slice_y_val = float(yc[idx])
            lo, hi = self._slice_axis_range(self._panel_time_range, 'x', xc)
            mask = self._slice_visible_mask(xc, lo, hi)
            self._slice_curve.setData(xc[mask], m[idx, :][mask])
            self._set_slice_x_range(lo, hi, xc[mask])
            self._apply_slice_amp_range(visible_line_values(
                xc, m[idx, :], (lo, hi), valid_mask=self._matrix_amp_valid[idx, :]))
            if refresh_chrome:
                self._slice_plot.setLabel('bottom', self._x_label or 'Time (s)')
                self._slice_marker_updating = True
                try:
                    self._slice_marker.setAngle(0)
                    self._slice_marker.setValue(float(yc[idx]))
                finally:
                    self._slice_marker_updating = False
            fixed_val, fixed_lbl = float(yc[idx]), self._y_label
        else:
            # Fix a time → curve = amplitude vs Y (frequency / order).
            # Horizontal axis is FREQUENCY/ORDER → panel freq_range (when manual).
            idx = int(np.clip(self._slice_x_idx, 0, max(0, ncols - 1)))
            self._slice_x_idx = idx
            self._slice_x_val = float(xc[idx])
            lo, hi = self._slice_axis_range(self._panel_freq_range, 'y', yc)
            mask = self._slice_visible_mask(yc, lo, hi)
            self._slice_curve.setData(yc[mask], m[:, idx][mask])
            self._set_slice_x_range(lo, hi, yc[mask])
            self._apply_slice_amp_range(visible_line_values(
                yc, m[:, idx], (lo, hi), valid_mask=self._matrix_amp_valid[:, idx]))
            if refresh_chrome:
                self._slice_plot.setLabel('bottom', self._y_label or 'Frequency (Hz)')
                self._slice_marker_updating = True
                try:
                    self._slice_marker.setAngle(90)
                    self._slice_marker.setValue(float(xc[idx]))
                finally:
                    self._slice_marker_updating = False
            fixed_val, fixed_lbl = float(xc[idx]), self._x_label
        self._apply_slice_curve_aa_state()
        if not refresh_chrome:
            return
        amp_label = self._current_amplitude_axis_label()
        self._slice_plot.setLabel('left', amp_label)
        _hide_plot_title(self._slice_plot)
        self._slice_marker.setVisible(True)
        self._update_slice_hint(fixed_lbl, fixed_val)
        if self._slice_panel is not None and self._slice_panel.isHidden():
            self._slice_panel.show()
        self._align_slice_to_main()
        self._position_slice_panel()
        self.layout_geometry_changed.emit()

    def _on_slice_marker_dragged(self, *_args) -> None:
        """Marker drag → snap to the nearest index along the active axis and
        re-slice live."""
        if self._slice_marker_updating:
            # Programmatic InfiniteLine.setValue inside _apply_slice emits
            # sigPositionChanged. Treating that as a drag stops the discrete
            # 0 ms settle and leaves a cheap slice AA-off at rest.
            return
        if self._matrix_disp is None or self._slice_curve is None:
            return
        xc, yc = self._slice_coords()
        if xc is None:
            return
        try:
            pos = float(self._slice_marker.value())
        except Exception:
            return
        self.disable_interactive_quality()
        if self._slice_dir == 'y':
            self._slice_y_idx = int(np.argmin(np.abs(yc - pos)))
        else:
            self._slice_x_idx = int(np.argmin(np.abs(xc - pos)))
        self._apply_slice()
        self.schedule_idle_quality()

    def _update_slice_hint(self, label: str, value: float) -> None:
        if self._slice_hint is None:
            return
        prefix, unit = self._short_axis_label(label)
        unit_part = f' {unit}' if unit else ''
        # At most 2 decimals, trailing zeros trimmed (3.00 -> 3, 4.0336 -> 4.03).
        vtxt = f'{round(float(value), 2):.2f}'.rstrip('0').rstrip('.')
        if vtxt in ('', '-0'):
            vtxt = '0'
        # Single centred line: 'Prefix = <value> unit', value emphasised.
        self._slice_hint.setText(
            f'<span style="color:#8a94a6;">{prefix} = </span>'
            f'<span style="font-size:14px;font-weight:800;color:#1f3b63;">'
            f'{vtxt}</span>'
            f'<span style="color:#8a94a6;">{unit_part}</span>'
        )

    def _select_slice_at(self, x: float, y: float) -> None:
        """Position the slice at a clicked map point, respecting direction and
        the data extents (a click on the colorbar/padding is ignored)."""
        if (self._matrix_disp is None or self._slice_curve is None
                or self._extents is None):
            self.slice_hint_requested.emit("先点计算生成谱图")
            return
        x0, x1, y0, y1 = self._extents
        if self._slice_dir == 'y':
            if not (y0 <= y <= y1):
                self.slice_hint_requested.emit("点击位置超出谱图范围")
                return
            self._slice_y_idx = self._freq_index_for(y)
            self._apply_slice()
            self.slice_picked.emit()
        else:
            if not (x0 <= x <= x1):
                self.slice_hint_requested.emit("点击位置超出谱图范围")
                return
            self._slice_x_idx = self._time_index_for(x)
            self._apply_slice()
            self.slice_picked.emit()

    def set_slice_button_labels(self, x_label: str, y_label: str) -> None:
        """Set the X/Y toggle segment captions (Order uses 按阶次 for Y)."""
        self._slice_x_btn_label = x_label
        self._slice_y_btn_label = y_label
        if self._slice_toggle is not None:
            self._slice_toggle._btn_x.setText(x_label)
            self._slice_toggle._btn_y.setText(y_label)

    def _align_slice_to_main(self) -> None:
        """Pull the slice plot's right edge in to match the heatmap's, so the
        time axis lines up vertically (the heatmap's right edge is inset by the
        colorbar). Single-pane; split alignment handles the multi-pane case."""
        if self._slice_plot is None:
            return
        try:
            self._set_slice_right_spacer(None)
            self._activate_graphics_layout()
            main_r = float(self._plot.vb.sceneBoundingRect().right())
            slice_r = float(self._slice_plot.vb.sceneBoundingRect().right())
        except Exception:
            return
        reserve = slice_r - main_r
        self._set_slice_right_spacer(
            reserve if reserve > 1.0 else PG_AXIS_NEUTRAL_WIDTH)
        self._activate_graphics_layout()

    def _position_slice_panel(self) -> None:
        """Pin the slice info panel into the colorbar column (right of the
        aligned slice plot, below the colorbar)."""
        if getattr(self, '_bottom_collapsed', False):
            if self._slice_panel is not None:
                self._slice_panel.hide()
            return
        if self._slice_panel is None or self._slice_plot is None:
            return
        try:
            srect = self._slice_plot.vb.sceneBoundingRect()
        except Exception:
            return
        cbar_left = None
        if self._cbar is not None:
            try:
                cbar_left = float(self._cbar.sceneBoundingRect().left())
            except Exception:
                cbar_left = None
        if cbar_left is not None and cbar_left > srect.right():
            x = int(cbar_left) - 2
        else:
            x = int(srect.right()) + 6
        margin = 4
        y = int(srect.top())
        w = max(70, int(self.width() - x - margin))
        h = max(40, int(srect.height()))
        self._slice_panel.setGeometry(x, y, w, h)
        # Clamp the centred toggle to the available content width so it never
        # clips on a very narrow column (margins are 6 each side).
        if self._slice_toggle is not None:
            self._slice_toggle.setFixedWidth(
                min(self._slice_toggle_w, max(52, w - 12)))
        self._slice_panel.show()
        self._slice_panel.raise_()

    def _set_slice_right_spacer(self, width: float | None) -> None:
        if self._slice_plot is None:
            return
        axis = self._slice_plot.getAxis('right')
        frame_pen = pg.mkPen(
            color=PG_AXIS_NEUTRAL_COLOR, width=PG_AXIS_NEUTRAL_WIDTH)
        transparent = pg.mkPen((0, 0, 0, 0))
        if width is None:
            # _align_slice_to_main 在测量 colorbar 内缩量之前会先调用本分支做一次
            # 瞬时复位——此时把右轴从测量中移除，保持 reserve 计算干净，不画边框。
            try:
                self._slice_plot.showAxis('right', False)
                axis.setWidth(None)
            except Exception:
                pass
            return
        try:
            self._slice_plot.showAxis('right', True)
            # 在 slice viewbox 的右缘画一条可见边框线，使下方图右侧闭合（与热力图右
            # 边框对齐）。刻度文字保持隐藏；width>0 时仍预留 colorbar 列的间距。
            axis.setPen(frame_pen)
            axis.setTextPen(transparent)
            axis.setStyle(showValues=False, tickLength=0)
            axis.setWidth(float(width) if width > 0 else 1.0)
        except Exception:
            pass


__all__ = ["_SliceDirToggle", "_SliceStrip"]
