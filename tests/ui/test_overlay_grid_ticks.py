"""Overlay graticule, tick pinning, and vertical wheel behavior tests.

Pure helper tests stay Qt-free; canvas-level tests use the shared qapp fixture.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from PyQt5.QtCore import QPointF, Qt

from mf4_analyzer.ui import pg_canvases as pgc
from mf4_analyzer.ui.pg_canvases import _fmt_tick, _frame_to_nice, _nice_per_div


_NICE = pgc._NICE_STEP_MANTISSAS


def _mantissa(v):
    exp = math.floor(math.log10(v))
    return v / (10.0 ** exp)


class TestFmtTick:
    """A graticule tick that is zero-but-for-float-residue must read ``0`` —
    not ``1.78e-15`` (2026-06-25 sci-notation zero-label fix). The residue
    comes from wheel-pan tick accumulation (``lo - step*per_div + k*per_div``)
    where the zero-crossing division no longer lands on an exact 0.0."""

    @pytest.mark.parametrize("residue", [
        1.78e-15,                      # the value from the user's screenshot
        -3.55e-16,
        1.1102230246251565e-16,
        -2.220446049250313e-16,
        5e-10,
    ])
    def test_near_zero_residue_reads_zero(self, residue):
        assert _fmt_tick(residue) == "0"

    def test_exact_zero_and_normal_values_unchanged(self):
        assert _fmt_tick(0.0) == "0"
        assert _fmt_tick(5.0) == "5"
        assert _fmt_tick(-1.2) == "-1.2"
        assert _fmt_tick(1.2) == "1.2"

    def test_genuine_small_and_large_values_keep_sci_notation(self):
        # A real tick >= 1e-9 must NOT be flattened to 0; big values still sci.
        assert _fmt_tick(5e-5) == "5.00e-05"
        assert _fmt_tick(1.5e7) == "1.50e+07"

    def test_wheel_pan_zero_division_label_is_zero(self):
        # Reproduce the real trigger end-to-end: snap to a clean grid, then do
        # one plain-wheel vertical pan (overlay_axes.py:1357). The zero-crossing
        # division accumulates float residue; its LABEL must still be "0".
        n = 10
        per_div = 0.1
        step = 1
        lo = -5 * per_div                       # snapped clean lower bound
        bottom = lo - step * per_div            # plain-wheel pan
        ticks = [bottom + k * per_div for k in range(n + 1)]
        labels = [_fmt_tick(v) for v in ticks]
        zero_like = [lab for v, lab in zip(ticks, labels) if abs(v) < 1e-9]
        assert zero_like, "this fixture must contain a zero-crossing division"
        assert all(lab == "0" for lab in zero_like)
        assert not any("e-" in lab for lab in labels)


class TestNicePerDiv:
    @pytest.mark.parametrize("raw, expected", [
        (1.0, 1.0),
        (1.013, 1.2),
        (1.35, 1.5),
        (2.01, 2.5),
        (8.01, 10.0),
        (0.013, 0.015),
        (130.0, 150.0),
    ])
    def test_returns_smallest_nice_ge_raw(self, raw, expected):
        got = _nice_per_div(raw)
        assert got == pytest.approx(expected, rel=1e-9)
        assert got >= raw - 1e-9

    def test_mantissa_always_in_nice_set(self):
        for raw in (0.07, 0.7, 3.3, 17.0, 410.0, 0.0009):
            got = _nice_per_div(raw)
            assert any(abs(_mantissa(got) - m) < 1e-6 for m in _NICE + [1.0])

    def test_nonpositive_and_nonfinite_return_none(self):
        assert _nice_per_div(0.0) is None
        assert _nice_per_div(-2.0) is None
        assert _nice_per_div(float("nan")) is None
        assert _nice_per_div(float("inf")) is None


class TestFrameToNice:
    @pytest.mark.parametrize("lo, hi, n", [
        (0.317, 8.42, 8),
        (-5.0, 5.0, 8),
        (-12.3, -1.1, 6),
        (0.0, 0.0, 8),
        (1e3, 1.0008e3, 10),
        (-0.0008, 0.0009, 8),
    ])
    def test_contains_and_nice(self, lo, hi, n):
        bottom, top, ticks = _frame_to_nice(lo, hi, n)
        assert bottom <= min(lo, hi) + 1e-9
        assert top >= max(lo, hi) - 1e-9
        assert len(ticks) == n + 1
        per_div = ticks[1] - ticks[0]
        for value in ticks:
            ratio = value / per_div
            assert abs(ratio - round(ratio)) < 1e-6
        diffs = np.diff(ticks)
        assert np.allclose(diffs, diffs[0], rtol=1e-9)

    def test_concrete_example_matches_spec(self):
        bottom, top, ticks = _frame_to_nice(0.317, 8.42, 8)
        assert bottom == pytest.approx(0.0)
        assert top == pytest.approx(9.6)
        assert ticks == pytest.approx([
            0,
            1.2,
            2.4,
            3.6,
            4.8,
            6.0,
            7.2,
            8.4,
            9.6,
        ])

    def test_framed_window_is_idempotent(self):
        first = _frame_to_nice(-2.0, 2.0, 8)
        second = _frame_to_nice(first[0], first[1], 8)
        assert second == pytest.approx(first)


class TestOverlayDivisions:
    def _overlay(self, qapp, n_ch=2, npts=200):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, npts)
        rows = []
        for i in range(n_ch):
            sig = (i + 1) * np.sin(2 * np.pi * (i + 1) * t) + 0.3 * i
            rows.append((f"ch{i}", True, t, sig, "#1769e0", "u", f"fid-{i}"))
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    def test_default_divisions_is_10(self, qapp):
        canvas = self._overlay(qapp)
        assert canvas._overlay_axes.divisions == 10
        assert len(canvas._overlay_axes.grid_lines) == 10 - 1

    def test_set_tick_density_drives_divisions_and_gridlines(self, qapp):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, 12)
        assert canvas._overlay_axes.divisions == 12
        assert len(canvas._overlay_axes.grid_lines) == 12 - 1

    def test_density_clamped_to_3_20(self, qapp):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, 99)
        assert canvas._overlay_axes.divisions == 20
        canvas.set_tick_density(10, 1)
        assert canvas._overlay_axes.divisions == 3


class TestRepinTicks:
    def _overlay(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t) + 1.0, "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    def test_each_channel_ticks_align_to_divisions(self, qapp):
        canvas = self._overlay(qapp)
        canvas._repin_overlay_channel_ticks()
        n = canvas._overlay_axes.divisions
        for handle in canvas.axes_list:
            lo, hi = handle.get_ylim()
            span = hi - lo
            assert span > 0
            axis = handle.y_axis_item()
            major = axis._tickLevels[0]
            fracs = sorted(((value - lo) / span) for value, _label in major)
            expected = [k / n for k in range(n + 1)]
            assert fracs == pytest.approx(expected, abs=1e-6)

    def test_tick_values_are_nice_multiples(self, qapp):
        canvas = self._overlay(qapp)
        canvas._repin_overlay_channel_ticks()
        for handle in canvas.axes_list:
            axis = handle.y_axis_item()
            major = axis._tickLevels[0]
            vals = sorted(value for value, _label in major)
            per_div = vals[1] - vals[0]
            for value in vals:
                ratio = value / per_div
                assert abs(ratio - round(ratio)) < 1e-6


def _overlay_scene_pos_at_fraction(canvas, frac):
    view_box = canvas._x_master_handle.view_box
    rect = view_box.sceneBoundingRect()
    return QPointF(
        float(rect.center().x()),
        float(rect.bottom()) - float(frac) * float(rect.height()),
    )


def _assert_cursor_anchor_preserved(before, after, frac):
    before_anchor = before[0] + frac * (before[1] - before[0])
    after_anchor = after[0] + frac * (after[1] - after[0])
    assert after_anchor == pytest.approx(before_anchor, rel=1e-10, abs=1e-10)


class TestOverlayWheel:
    def _overlay(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.5 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    @pytest.mark.parametrize("divisions", [3, 10, 20])
    @pytest.mark.parametrize("frac", [0.15, 0.50, 0.85])
    def test_shift_wheel_preserves_cursor_anchor(
        self, qapp, divisions, frac,
    ):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, divisions)
        initial_ranges = [(-2.5, 2.5), (-120.0, 280.0)]
        for handle, limits in zip(canvas.axes_list, initial_ranges):
            handle.set_ylim(*limits)
        scene_pos = _overlay_scene_pos_at_fraction(canvas, frac)
        before = [handle.get_ylim() for handle in canvas.axes_list]

        assert canvas._handle_wheel_dispatch(
            delta=120.0,
            modifiers=Qt.ShiftModifier,
            x_pos=0.5,
            y_pos=0.0,
            view_box=canvas._x_master_handle.view_box,
            scene_pos=scene_pos,
            axis=None,
        ) is True

        after = [handle.get_ylim() for handle in canvas.axes_list]
        for old_limits, new_limits in zip(before, after):
            _assert_cursor_anchor_preserved(old_limits, new_limits, frac)

    @pytest.mark.parametrize("divisions", [3, 10, 20])
    @pytest.mark.parametrize("frac", [0.15, 0.50, 0.85])
    def test_shift_wheel_round_trip_restores_ranges_and_projects_ticks(
        self, qapp, divisions, frac,
    ):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, divisions)
        # Per-division values are exactly 1 and 40, both members of the nice-step
        # sequence. This isolates reversibility of adjacent nice levels from the
        # separate first-notch normalization of an arbitrary external range.
        initial_ranges = [
            (-0.5 * divisions, 0.5 * divisions),
            (-20.0 * divisions, 20.0 * divisions),
        ]
        for handle, limits in zip(canvas.axes_list, initial_ranges):
            handle.set_ylim(*limits)
        initial_x = canvas._x_master_handle.get_xlim()
        scene_pos = _overlay_scene_pos_at_fraction(canvas, frac)
        previous_ranges = [handle.get_ylim() for handle in canvas.axes_list]

        for delta in [120.0] * 4 + [-120.0] * 4:
            assert canvas._handle_wheel_dispatch(
                delta=delta,
                modifiers=Qt.ShiftModifier,
                x_pos=0.5,
                y_pos=0.0,
                view_box=canvas._x_master_handle.view_box,
                scene_pos=scene_pos,
                axis=None,
            ) is True
            for old_limits, handle in zip(previous_ranges, canvas.axes_list):
                new_limits = handle.get_ylim()
                _assert_cursor_anchor_preserved(old_limits, new_limits, frac)
                major = handle.y_axis_item()._tickLevels[0]
                tick_values = [value for value, _label in major]
                assert len(tick_values) == divisions + 1
                assert tick_values[0] == pytest.approx(new_limits[0])
                assert tick_values[-1] == pytest.approx(new_limits[1])
                tick_step = (new_limits[1] - new_limits[0]) / divisions
                assert np.diff(tick_values) == pytest.approx(
                    [tick_step] * divisions
                )
            previous_ranges = [handle.get_ylim() for handle in canvas.axes_list]

        for handle, initial_limits in zip(canvas.axes_list, initial_ranges):
            assert handle.get_ylim() == pytest.approx(initial_limits)
        assert canvas._x_master_handle.get_xlim() == pytest.approx(initial_x)

    def test_real_viewport_shift_wheel_round_trip_does_not_drift(self, qapp):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QWheelEvent
        from PyQt5.QtWidgets import QApplication

        canvas = self._overlay(qapp)
        canvas.resize(900, 500)
        canvas.show()
        qapp.processEvents()
        frac = 0.85
        initial_ranges = [(-2.5, 2.5), (-120.0, 280.0)]
        for handle, limits in zip(canvas.axes_list, initial_ranges):
            handle.set_ylim(*limits)
        initial_x = canvas._x_master_handle.get_xlim()
        scene_pos = _overlay_scene_pos_at_fraction(canvas, frac)
        pos = QPointF(canvas._glw.mapFromScene(scene_pos))
        global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
        delivered_scene_pos = canvas._glw.mapToScene(pos.toPoint())
        delivered_frac = canvas._overlay_axes._overlay_cursor_y_fraction(
            delivered_scene_pos,
            canvas._x_master_handle.view_box,
        )
        previous_ranges = [handle.get_ylim() for handle in canvas.axes_list]

        for delta in [120, 120, -120, -120]:
            event = QWheelEvent(
                pos,
                global_pos,
                QPoint(),
                QPoint(0, delta),
                Qt.NoButton,
                Qt.ShiftModifier,
                Qt.ScrollUpdate,
                False,
            )
            assert QApplication.sendEvent(canvas._glw.viewport(), event)
            assert event.isAccepted()
            qapp.processEvents()
            current_ranges = [handle.get_ylim() for handle in canvas.axes_list]
            for old_limits, new_limits in zip(previous_ranges, current_ranges):
                old_span = old_limits[1] - old_limits[0]
                new_span = new_limits[1] - new_limits[0]
                if delta > 0:
                    assert new_span < old_span
                else:
                    assert new_span > old_span
                _assert_cursor_anchor_preserved(
                    old_limits, new_limits, delivered_frac
                )
            previous_ranges = current_ranges

        for handle, initial_limits in zip(canvas.axes_list, initial_ranges):
            assert handle.get_ylim() == pytest.approx(initial_limits)
        assert canvas._x_master_handle.get_xlim() == pytest.approx(initial_x)

    def test_no_selection_shift_wheel_zooms_all_keeps_xmaster_locked(self, qapp):
        # New design (user request): overlay Y zooms ALL channels together like
        # the shared X — no pre-selection required, no overlay_y_needs_selection.
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel(None)
        emitted = []
        canvas.overlay_y_needs_selection.connect(lambda: emitted.append(1))
        xm = canvas._x_master_handle
        before_x = xm.get_xlim()
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        y0_before = ax0.get_ylim()
        y1_before = ax1.get_ylim()

        consumed = canvas._handle_wheel_dispatch(
            delta=120.0,
            modifiers=Qt.ShiftModifier,
            x_pos=0.5,
            y_pos=0.5,
        )

        assert consumed is True
        assert ax0.get_ylim() != pytest.approx(y0_before)
        assert ax1.get_ylim() != pytest.approx(y1_before)
        # The curveless X-master keeps its locked [0,1] Y and unchanged X.
        assert xm.get_ylim() == pytest.approx((0.0, 1.0))
        assert xm.get_xlim() == pytest.approx(before_x)
        assert emitted == []

    def test_shift_wheel_zooms_all_channels_together(self, qapp):
        canvas = self._overlay(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        y0_before = ax0.get_ylim()
        y1_before = ax1.get_ylim()
        x_before = canvas._x_master_handle.get_xlim()
        span0_before = y0_before[1] - y0_before[0]
        span1_before = y1_before[1] - y1_before[0]

        canvas._handle_wheel_dispatch(
            delta=120.0,
            modifiers=Qt.ShiftModifier,
            x_pos=0.5,
            y_pos=1.0,
        )

        # Both channels shrink (zoom in) together.
        assert (ax0.get_ylim()[1] - ax0.get_ylim()[0]) < span0_before
        assert (ax1.get_ylim()[1] - ax1.get_ylim()[0]) < span1_before
        assert canvas._x_master_handle.get_xlim() == pytest.approx(x_before)

    @pytest.mark.parametrize("divisions", range(3, 21))
    def test_shift_wheel_zoom_out_strictly_expands_at_every_density(
        self, qapp, divisions,
    ):
        """A negative Shift-wheel step must never be snapped back to the
        current overlay range, including the sparse Y densities 3 through 6.
        """
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, divisions)
        for handle in canvas.axes_list:
            handle.set_ylim(0.0, float(divisions))

        for step_index in range(8):
            before = [hi - lo for lo, hi in (
                handle.get_ylim() for handle in canvas.axes_list
            )]
            expected_spans = [
                divisions * pgc._adjacent_nice_step(span / divisions, 1)
                for span in before
            ]

            assert canvas._handle_wheel_dispatch(
                delta=-120.0,
                modifiers=Qt.ShiftModifier,
                x_pos=0.5,
                y_pos=0.5,
            ) is True

            after = [hi - lo for lo, hi in (
                handle.get_ylim() for handle in canvas.axes_list
            )]
            for channel_index, (old_span, new_span, expected_span) in enumerate(
                zip(before, after, expected_spans)
            ):
                assert new_span > old_span, (
                    f"n={divisions}, step={step_index}, channel={channel_index}: "
                    f"zoom-out must expand {old_span}, got {new_span}"
                )
                assert new_span == pytest.approx(expected_span), (
                    f"n={divisions}, step={step_index}, channel={channel_index}: "
                    "zoom-out must keep the selected adjacent nice step"
                )

    @pytest.mark.parametrize("divisions", range(3, 21))
    def test_shift_wheel_zoom_in_strictly_contracts_at_every_density(
        self, qapp, divisions,
    ):
        canvas = self._overlay(qapp)
        canvas.set_tick_density(10, divisions)
        for handle in canvas.axes_list:
            handle.set_ylim(0.0, float(divisions))

        for step_index in range(8):
            before = [hi - lo for lo, hi in (
                handle.get_ylim() for handle in canvas.axes_list
            )]
            expected_spans = [
                divisions * pgc._adjacent_nice_step(span / divisions, -1)
                for span in before
            ]

            assert canvas._handle_wheel_dispatch(
                delta=120.0,
                modifiers=Qt.ShiftModifier,
                x_pos=0.5,
                y_pos=0.5,
            ) is True

            after = [hi - lo for lo, hi in (
                handle.get_ylim() for handle in canvas.axes_list
            )]
            for channel_index, (old_span, new_span, expected_span) in enumerate(
                zip(before, after, expected_spans)
            ):
                assert new_span < old_span, (
                    f"n={divisions}, step={step_index}, channel={channel_index}: "
                    f"zoom-in must contract {old_span}, got {new_span}"
                )
                assert new_span == pytest.approx(expected_span), (
                    f"n={divisions}, step={step_index}, channel={channel_index}: "
                    "zoom-in must keep the selected adjacent nice step"
                )

    def test_axis_gutter_shift_wheel_zooms_only_that_channel(self, qapp):
        # Wheel over ONE channel's own Y-axis gutter (pyqtgraph forwards it as
        # axis=1) → scroll/zoom ONLY that channel; the others are untouched.
        canvas = self._overlay(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        y0_before = ax0.get_ylim()
        y1_before = ax1.get_ylim()

        canvas._handle_wheel_dispatch(
            delta=120.0, modifiers=Qt.ShiftModifier, x_pos=0.5, y_pos=1.0,
            view_box=ax0.view_box, axis=1,
        )

        assert ax0.get_ylim() != pytest.approx(y0_before), "ch0 axis must zoom"
        assert ax1.get_ylim() == pytest.approx(y1_before), (
            "axis-gutter wheel must NOT touch other channels"
        )

    def test_axis_gutter_plain_wheel_pans_only_that_channel(self, qapp):
        canvas = self._overlay(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        y0_before = ax0.get_ylim()
        y1_before = ax1.get_ylim()

        canvas._handle_wheel_dispatch(
            delta=120.0, modifiers=Qt.NoModifier, x_pos=0.5, y_pos=0.5,
            view_box=ax1.view_box, axis=1,
        )

        assert ax1.get_ylim() != pytest.approx(y1_before), "ch1 axis must pan"
        assert ax0.get_ylim() == pytest.approx(y0_before), (
            "axis-gutter wheel must NOT touch other channels"
        )

    def test_selection_plain_wheel_pans_one_division(self, qapp):
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel("ch0")
        ax0 = canvas._channel_lines["ch0"][0]
        lo0, hi0 = ax0.get_ylim()
        per_div = (hi0 - lo0) / canvas._overlay_axes.divisions

        canvas._handle_wheel_dispatch(
            delta=120.0,
            modifiers=Qt.NoModifier,
            x_pos=0.5,
            y_pos=0.5,
        )

        lo1, hi1 = ax0.get_ylim()
        # Wheel-up (delta>0) pans the view DOWN by one division — Windows-
        # traditional direction (negated vs the wheel ``step``).
        assert (lo1 - lo0) == pytest.approx(-per_div, rel=1e-6)
        assert (hi1 - hi0) == pytest.approx(-per_div, rel=1e-6)

    def test_ctrl_wheel_still_zooms_x(self, qapp):
        canvas = self._overlay(qapp)
        canvas.select_overlay_channel(None)
        xm = canvas._x_master_handle
        x_before = xm.get_xlim()

        canvas._handle_wheel_dispatch(
            delta=120.0,
            modifiers=Qt.ControlModifier,
            x_pos=0.5,
            y_pos=0.5,
        )

        assert xm.get_xlim() != pytest.approx(x_before)


class TestDragSnap:
    def _overlay_selected(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        canvas.select_overlay_channel("ch0")
        return canvas

    def test_release_reframes_to_nice(self, qapp):
        canvas = self._overlay_selected(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax0.set_ylim(-1.731, 2.169)

        canvas._snap_overlay_channel_to_grid(ax0)

        lo, hi = ax0.get_ylim()
        n = canvas._overlay_axes.divisions
        per_div = (hi - lo) / n
        assert abs(lo / per_div - round(lo / per_div)) < 1e-6
        assert abs(hi / per_div - round(hi / per_div)) < 1e-6
        major = ax0.y_axis_item()._tickLevels[0]
        assert [value for value, _label in major] == pytest.approx([
            lo + k * per_div for k in range(n + 1)
        ])


class _FakeBox:
    """Minimal MouseDragEvent stand-in for the box-zoom override.

    Only ``button()``, ``isStart()``, and ``isFinish()`` are read by
    ``_ModifierWheelViewBox.mouseDragEvent`` once super() is stubbed out.
    """

    def __init__(self, button, *, start=False, finish=False):
        self._button = button
        self._start = start
        self._finish = finish

    def button(self):
        return self._button

    def isStart(self):
        return self._start

    def isFinish(self):
        return self._finish


class TestOverlayBoxZoom:
    """Box-zoom (RectMode rubber band) in overlay must zoom shared X +
    the selected channel's Y, keep the X-master Y locked to [0, 1] so the
    graticule never collapses (2026-06-06 grid-redraw-after-zoom fix)."""

    def _overlay(self, qapp, select="ch0"):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.5 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        if select is not None:
            canvas.select_overlay_channel(select)
        return canvas

    def test_box_zoom_zooms_all_channels(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QPointF, QRectF

        canvas = self._overlay(qapp, select="ch0")
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        ax0.set_ylim(0.0, 100.0)
        QCoreApplication.processEvents()
        lo1_before, hi1_before = ax1.get_ylim()
        span1_before = hi1_before - lo1_before
        n_lines_before = len(canvas._overlay_axes.grid_lines)

        xm = canvas._x_master_handle.view_box
        # Simulate the rubber-band finish exactly like pyqtgraph does: a
        # rect spanning a sub-region of both X and the [0, 1] graticule Y.
        xm.showAxRect(QRectF(QPointF(0.2, 0.3), QPointF(0.6, 0.7)))
        QCoreApplication.processEvents()
        # Sanity: showAxRect did pull the X-master Y off [0, 1] (the bug).
        assert xm.viewRange()[1] != pytest.approx((0.0, 1.0))

        canvas._apply_overlay_box_zoom_y()
        QCoreApplication.processEvents()

        # X-master Y is re-locked → graticule lines all back in view.
        assert xm.viewRange()[1] == pytest.approx((0.0, 1.0), abs=1e-6)
        assert len(canvas._overlay_axes.grid_lines) == n_lines_before
        # X stayed zoomed (handler must not touch shared X).
        assert xm.viewRange()[0] != pytest.approx((0.0, 1.0))
        # ch0 zoomed into the box sub-range (~[30, 70]).
        lo0, hi0 = ax0.get_ylim()
        assert lo0 >= 0.0 - 1e-6 and hi0 <= 100.0 + 1e-6
        assert (hi0 - lo0) < 100.0 * 0.9
        assert lo0 < 35.0 and hi0 > 65.0
        # EVERY channel zooms by the same screen fraction now — not only the
        # selected one. ch1 must have narrowed too.
        lo1, hi1 = ax1.get_ylim()
        assert (hi1 - lo1) < span1_before * 0.9

    def test_box_zoom_no_selection_zooms_all_channels(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QPointF, QRectF

        canvas = self._overlay(qapp, select=None)
        canvas.select_overlay_channel(None)
        ax0 = canvas._channel_lines["ch0"][0]
        ax1 = canvas._channel_lines["ch1"][0]
        ax0.set_ylim(0.0, 100.0)
        QCoreApplication.processEvents()
        span0_before = ax0.get_ylim()[1] - ax0.get_ylim()[0]
        span1_before = ax1.get_ylim()[1] - ax1.get_ylim()[0]

        xm = canvas._x_master_handle.view_box
        xm.showAxRect(QRectF(QPointF(0.2, 0.3), QPointF(0.6, 0.7)))
        canvas._apply_overlay_box_zoom_y()
        QCoreApplication.processEvents()

        # No channel selected, yet box-zoom Y now applies to ALL channels.
        assert xm.viewRange()[1] == pytest.approx((0.0, 1.0), abs=1e-6)
        assert (ax0.get_ylim()[1] - ax0.get_ylim()[0]) < span0_before * 0.9
        assert (ax1.get_ylim()[1] - ax1.get_ylim()[0]) < span1_before * 0.9

    def test_box_zoom_override_calls_y_handler_only_on_xmaster_finish(
        self, qapp, monkeypatch,
    ):
        import pyqtgraph as pg

        canvas = self._overlay(qapp, select="ch0")
        xm_vb = canvas._x_master_handle.view_box
        xm_vb.setMouseMode(pg.ViewBox.RectMode)
        monkeypatch.setattr(
            pg.ViewBox, "mouseDragEvent",
            lambda self, ev, axis=None: None,
        )
        calls = []
        monkeypatch.setattr(
            canvas, "_apply_overlay_box_zoom_y", lambda: calls.append(1),
        )

        xm_vb.mouseDragEvent(_FakeBox(Qt.LeftButton, finish=True), axis=None)
        assert calls == [1], "RectMode finish on X-master must apply box-zoom Y"

        calls.clear()
        xm_vb.mouseDragEvent(_FakeBox(Qt.LeftButton, start=True), axis=None)
        assert calls == [], "drag start (non-finish) must not apply box-zoom Y"

        calls.clear()
        aux_vb = canvas._overlay_axes.aux_viewboxes[0]
        aux_vb.setMouseMode(pg.ViewBox.RectMode)
        aux_vb.mouseDragEvent(_FakeBox(Qt.LeftButton, finish=True), axis=None)
        assert calls == [], "box-zoom Y handler must fire only for the X-master"


class TestAnimatedSnap:
    """Drag-release snap should glide to the nice graticule (animated),
    not jump instantly (2026-06-06 release-snap smoothing)."""

    def _sel(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        canvas.select_overlay_channel("ch0")
        return canvas

    def test_release_with_anim_disabled_snaps_immediately(self, qapp):
        from unittest.mock import MagicMock

        canvas = self._sel(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax0.set_ylim(-1.731, 2.169)
        canvas._overlay_axes.snap_anim_ms = 0
        canvas._overlay_axes.dragging = True
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        canvas._handle_overlay_mouse_release(MagicMock())

        lo, hi = ax0.get_ylim()
        n = canvas._overlay_axes.divisions
        per_div = (hi - lo) / n
        assert abs(lo / per_div - round(lo / per_div)) < 1e-6
        assert abs(hi / per_div - round(hi / per_div)) < 1e-6

    def test_release_with_anim_does_not_jump_instantly(self, qapp):
        from unittest.mock import MagicMock

        canvas = self._sel(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax0.set_ylim(-1.731, 2.169)
        canvas._overlay_axes.snap_anim_ms = 150
        canvas._overlay_axes.dragging = True
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        canvas._handle_overlay_mouse_release(MagicMock())

        # The curve is still where the user dropped it; the snap glides in.
        assert ax0.get_ylim() == pytest.approx((-1.731, 2.169), abs=0.06)
        assert canvas._overlay_axes.snap_anim is not None

    def test_release_anim_pins_final_labels_without_flicker(self, qapp):
        """During the glide the axis labels must already be the final
        snapped values and stay constant — no per-frame recompute that
        flickers ugly intermediate numbers (2026-06-06 no-tick-flicker)."""
        from unittest.mock import MagicMock
        from PyQt5.QtCore import QCoreApplication

        canvas = self._sel(qapp)
        ax0 = canvas._channel_lines["ch0"][0]
        ax0.set_ylim(-0.474, 5.526)  # off-grid dragged window, span 6.0
        canvas._overlay_axes.snap_anim_ms = 150
        canvas._overlay_axes.dragging = True
        canvas._begin_overlay_y_drag_at(start_y_px=100.0)
        canvas._handle_overlay_mouse_release(MagicMock())

        n = canvas._overlay_axes.divisions
        per_div = 6.0 / n
        bottom = round(-0.474 / per_div) * per_div
        expected = [bottom + k * per_div for k in range(n + 1)]

        def tick_values():
            return [v for v, _label in ax0.y_axis_item()._tickLevels[0]]

        # Immediately after release: labels are already the final integers.
        assert tick_values() == pytest.approx(expected)
        # The curve, however, has NOT snapped yet — it glides in.
        assert ax0.get_ylim() == pytest.approx((-0.474, 5.526), abs=1e-6)

        # Mid-glide: labels stay constant (no flicker), curve has moved.
        canvas._overlay_axes.snap_anim.setCurrentTime(75)
        QCoreApplication.processEvents()
        assert tick_values() == pytest.approx(expected)
        assert ax0.get_ylim() != pytest.approx((-0.474, 5.526), abs=1e-6)


class TestFitYToVisibleOverlay:
    """fit_y_to_visible_x must reframe overlay ticks back onto graticules."""

    def _overlay(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        rows = [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t) + 1.0, "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.4 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        return canvas

    def test_fit_y_to_visible_x_keeps_overlay_ticks_on_grid(self, qapp):
        canvas = self._overlay(qapp)
        canvas.fit_y_to_visible_x()
        n = canvas._overlay_axes.divisions
        for handle in canvas.axes_list:
            lo, hi = handle.get_ylim()
            span = hi - lo
            assert span > 0
            axis = handle.y_axis_item()
            major = axis._tickLevels[0]
            fracs = sorted(((value - lo) / span) for value, _label in major)
            expected = [k / n for k in range(n + 1)]
            assert fracs == pytest.approx(expected, abs=1e-6)

    def test_fit_y_to_visible_x_subplot_does_not_reframe(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 256)
        sig0 = 3.1 * np.sin(2 * np.pi * t)
        sig1 = 1.7 * np.cos(2 * np.pi * 2 * t)
        rows = [
            ("ch0", True, t, sig0, "#1769e0", "V", "fid-0"),
            ("ch1", True, t, sig1, "#e07b17", "A", "fid-1"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        canvas.fit_y_to_visible_x()
        handle = canvas.axes_list[0]
        lo, hi = handle.get_ylim()
        data_lo, data_hi = float(sig0.min()), float(sig0.max())
        pad = (data_hi - data_lo) * 0.05
        assert lo == pytest.approx(data_lo - pad, rel=1e-3)
        assert hi == pytest.approx(data_hi + pad, rel=1e-3)


class TestOverlaySwitchGeometry:
    """Overlay aux ViewBoxes must sync after layout-affecting build work."""

    def _rows(self):
        t = np.linspace(0.0, 1.0, 256)
        return [
            ("ch0", True, t, 2.0 * np.sin(2 * np.pi * t), "#1769e0", "V", "fid-0"),
            ("ch1", True, t, 0.5 * np.cos(2 * np.pi * 3 * t), "#e07b17", "A", "fid-1"),
            ("ch2", True, t, 1.2 * np.sin(2 * np.pi * 5 * t), "#17a07b", "Nm", "fid-2"),
        ]

    def _assert_aux_match_xmaster(self, canvas, tol=1.0):
        xm = canvas._x_master_handle.view_box.sceneBoundingRect()
        assert canvas._overlay_axes.aux_viewboxes, "overlay must build aux ViewBoxes"
        assert xm.width() > 1.0 and xm.height() > 1.0, "X-master rect must be settled"
        for aux in canvas._overlay_axes.aux_viewboxes:
            r = aux.sceneBoundingRect()
            assert abs(r.x() - xm.x()) <= tol
            assert abs(r.y() - xm.y()) <= tol
            assert abs(r.width() - xm.width()) <= tol
            assert abs(r.height() - xm.height()) <= tol

    def test_overlay_build_syncs_aux_after_tick_density_layout_work(self, qapp):
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        density_applied = {"value": False}
        sync_calls = []

        tick_density = canvas._tick_density_controller
        original_density = tick_density._apply_tick_density_to_all_axes
        original_sync = canvas._sync_overlay_aux_viewboxes

        def mark_density_applied():
            density_applied["value"] = True
            return original_density()

        def record_sync_order():
            sync_calls.append(density_applied["value"])
            return original_sync()

        tick_density._apply_tick_density_to_all_axes = mark_density_applied
        canvas._sync_overlay_aux_viewboxes = record_sync_order

        canvas.plot_channels(self._rows(), mode="overlay")

        assert sync_calls == [True], (
            "overlay build must sync aux exactly once, after tick-density/axis "
            "geometry work"
        )

    def test_switch_subplot_to_overlay_aux_matches_xmaster_after_build(self, qapp):
        from PyQt5.QtCore import QCoreApplication
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        rows = self._rows()
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()

        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()

        self._assert_aux_match_xmaster(canvas)

    def test_resize_settled_resyncs_aux_geometry(self, qapp):
        from PyQt5.QtCore import QCoreApplication, QRectF
        from tests.ui.test_pg_timedomain_canvas import _pg_canvas

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(self._rows(), mode="overlay")
        QCoreApplication.processEvents()

        canvas._disconnect_overlay_view_sync()
        for aux in canvas._overlay_axes.aux_viewboxes:
            aux.setGeometry(QRectF(0.0, 0.0, 5.0, 5.0))

        canvas._on_resize_settled()
        self._assert_aux_match_xmaster(canvas)
