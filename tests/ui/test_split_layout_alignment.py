"""Split-layout alignment contract, characterized on both analysis canvases.

``AnalysisSectionPage`` drives a three-call protocol on every pane it lays out
side by side -- ``prepare_split_layout_alignment`` (release to natural sizes),
``*_layout_metrics`` (measure), ``apply_split_layout_alignment`` (pin to the
cross-pane maxima) -- plus ``reset_split_layout_alignment`` for the single-pane
case. The four methods were near-copies on PgLineCanvas and PgHeatmapCanvas at
0.17-0.64 similarity, i.e. NOT byte-identical, so this file pins what each
canvas actually does before any of it is hoisted into _StackedSplitMixin.

The page calls the two canvases with different keyword names on purpose
(amp_/time_ vs main_/slice_) -- that asymmetry is part of the contract and is
asserted here rather than refactored away.
"""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


@pytest.fixture
def line(qapp):
    c = PgLineCanvas()
    c.resize(640, 480)
    c.plot_spectra(
        [{
            'label': 'f1 · steering torque',
            'color': '#2563eb',
            'freq': np.array([0.0, 1.0, 2.0]),
            'amp': np.array([0.0, 100.0, 0.0]),
            'time': np.linspace(0.0, 1.0, 32),
            'signal': np.zeros(32),
        }],
        xlim=(0.0, 2.0), amp_label='Amplitude', title='FFT',
        y_auto=False, y_min=0.0, y_max=100.0,
    )
    c.show()
    qapp.processEvents()
    yield c
    c.deleteLater()


@pytest.fixture
def heatmap(qapp):
    c = PgHeatmapCanvas(with_slice=True)
    c.resize(640, 480)
    c.plot_or_update_heatmap(
        matrix=np.arange(16, dtype=float).reshape(4, 4),
        x_extent=(0.0, 10.0), y_extent=(0.0, 8.0),
        amplitude_mode='amplitude', z_auto=True,
    )
    c.show()
    qapp.processEvents()
    yield c
    c.deleteLater()


@pytest.fixture(params=['line', 'heatmap'])
def either(request):
    return request.getfixturevalue(request.param)


# --- prepare: title clamp + release -----------------------------------------

@pytest.mark.parametrize('given,expected', [
    (None, None), (200.0, 200.0), (50.0, 80.0), (80.0, 80.0),
])
def test_prepare_clamps_the_title_width_to_a_floor_of_80(
        either, given, expected):
    either.prepare_split_layout_alignment(given)

    assert either._split_title_width == expected


def test_prepare_releases_every_alignment_axis(either, qapp):
    either.apply_split_layout_alignment(left_axis_width=140.0)
    qapp.processEvents()
    released = []
    for axis in either._alignment_left_axes():
        axis.setWidth = (
            lambda v, _a=axis: released.append((_a, v))
        )
    heights = []
    for axis in either._alignment_bottom_axes():
        axis.setHeight = (
            lambda v, _a=axis: heights.append((_a, v))
        )

    either.prepare_split_layout_alignment(None)

    assert released == [(a, None) for a in either._alignment_left_axes()]
    assert heights == [(a, None) for a in either._alignment_bottom_axes()]


# --- apply: pin -------------------------------------------------------------

def test_apply_pins_every_left_axis_to_the_given_width(either, qapp):
    either.apply_split_layout_alignment(left_axis_width=137.0)
    qapp.processEvents()

    widths = [float(a.width()) for a in either._alignment_left_axes()]
    assert widths == [pytest.approx(137.0)] * len(widths)


def test_line_apply_pins_both_bottom_heights(line, qapp):
    line.apply_split_layout_alignment(
        left_axis_width=60.0,
        amp_bottom_axis_height=41.0,
        time_bottom_axis_height=29.0,
    )
    qapp.processEvents()

    assert float(line._plot_amp.getAxis('bottom').height()) == pytest.approx(41.0)
    assert float(line._plot_time.getAxis('bottom').height()) == pytest.approx(29.0)


def test_heatmap_apply_pins_both_bottom_heights(heatmap, qapp):
    heatmap.apply_split_layout_alignment(
        left_axis_width=60.0,
        main_bottom_axis_height=43.0,
        slice_bottom_axis_height=27.0,
    )
    qapp.processEvents()

    assert float(heatmap._plot.getAxis('bottom').height()) == pytest.approx(43.0)
    assert float(
        heatmap._slice_plot.getAxis('bottom').height()) == pytest.approx(27.0)


def test_apply_tolerates_omitted_bottom_heights(either, qapp):
    either.apply_split_layout_alignment(left_axis_width=90.0)
    qapp.processEvents()

    widths = [float(a.width()) for a in either._alignment_left_axes()]
    assert widths == [pytest.approx(90.0)] * len(widths)


def test_heatmap_apply_skips_the_slice_height_without_a_slice_row(qapp):
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)

    c.apply_split_layout_alignment(
        left_axis_width=70.0, slice_bottom_axis_height=25.0)

    assert c._slice_plot is None
    assert float(c._plot.getAxis('left').width()) == pytest.approx(70.0)
    c.deleteLater()


# --- the _split_aligned flag (heatmap only, on purpose) ---------------------

def test_heatmap_tracks_page_driven_alignment_with_a_flag(heatmap):
    heatmap.apply_split_layout_alignment(left_axis_width=60.0)
    assert heatmap._split_aligned is True

    heatmap.reset_split_layout_alignment()
    assert heatmap._split_aligned is False


def test_line_carries_no_such_flag(line):
    """The flag gates the heatmap's slice re-alignment hooks; the line canvas
    has no slice and no _after_split_* overrides, so it never needed one."""
    assert not hasattr(line, '_split_aligned')


# --- unify ------------------------------------------------------------------

def _realized_left_widths(canvas):
    return {round(float(a.width()), 3)
            for a in canvas._alignment_left_axes()}


def test_unify_gives_the_stacked_left_axes_one_width(either, qapp):
    axes = either._alignment_left_axes()
    axes[0].setWidth(180.0)
    axes[1].setWidth(40.0)
    either._activate_graphics_layout()
    qapp.processEvents()
    assert len(_realized_left_widths(either)) == 2, "precondition: axes differ"

    either._unify_stacked_left_axes()
    qapp.processEvents()

    assert len(_realized_left_widths(either)) == 1


def test_unify_never_narrows_an_axis(either, qapp):
    either.apply_split_layout_alignment(left_axis_width=180.0)
    qapp.processEvents()

    either._unify_stacked_left_axes()
    qapp.processEvents()

    for axis in either._alignment_left_axes():
        assert float(axis.width()) >= 180.0


def test_unify_is_a_noop_on_a_heatmap_without_a_slice_row(qapp):
    c = PgHeatmapCanvas(with_slice=False)
    c.resize(640, 480)
    c.show()
    qapp.processEvents()
    before = float(c._plot.getAxis('left').width())

    c._unify_stacked_left_axes()

    assert len(c._alignment_left_axes()) == 1
    assert float(c._plot.getAxis('left').width()) == pytest.approx(before)
    c.deleteLater()


# --- reset ------------------------------------------------------------------

def test_reset_runs_prepare_then_unify(either, monkeypatch):
    order = []
    monkeypatch.setattr(
        type(either), 'prepare_split_layout_alignment',
        lambda self, w: order.append(('prepare', w)))
    monkeypatch.setattr(
        type(either), '_unify_stacked_left_axes',
        lambda self: order.append(('unify',)))

    either.reset_split_layout_alignment()

    assert order == [('prepare', None), ('unify',)]


def test_heatmap_reset_realigns_the_slice_after_unifying(heatmap, monkeypatch):
    order = []
    monkeypatch.setattr(
        type(heatmap), '_unify_stacked_left_axes',
        lambda self: order.append('unify'))
    monkeypatch.setattr(
        type(heatmap), '_align_slice_to_main',
        lambda self: order.append('align'))
    monkeypatch.setattr(
        type(heatmap), '_position_slice_panel',
        lambda self: order.append('panel'))

    heatmap.reset_split_layout_alignment()

    assert order == ['unify', 'align', 'panel']


def test_heatmap_reset_skips_alignment_while_the_slice_is_collapsed(
        heatmap, monkeypatch):
    calls = []
    monkeypatch.setattr(
        type(heatmap), '_unify_stacked_left_axes',
        lambda self: calls.append('unify'))
    monkeypatch.setattr(
        type(heatmap), '_align_slice_to_main',
        lambda self: calls.append('align'))
    heatmap._bottom_collapsed = True

    heatmap.reset_split_layout_alignment()

    assert calls == []


def test_line_reset_unifies_even_while_the_bottom_row_is_collapsed(
        line, monkeypatch):
    """Recorded, not endorsed: the line canvas has no collapse guard on this
    path while the heatmap does. Whether that asymmetry is a bug is not
    decidable from the code, so the fork is preserved and pinned here."""
    calls = []
    monkeypatch.setattr(
        type(line), '_unify_stacked_left_axes',
        lambda self: calls.append('unify'))
    line._bottom_collapsed = True

    line.reset_split_layout_alignment()

    assert calls == ['unify']
