"""Canvas-side situational signals that feed the nudge surface.

The detection logic (amplitude disparity, clip-flat-top, dead colour window)
lives as pure helpers so the *logic* is unit-tested here; the perceptual
thresholds themselves still need on-device tuning against real data.
"""
import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.canvas import (
    TimeDomainCanvasPG,
    _looks_clipped,
    _subsampled_ptp,
)
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import (
    PgHeatmapCanvas,
    _colorbar_is_dead,
)


# ---- pure helpers --------------------------------------------------------

def test_subsampled_ptp_handles_empty_and_nan():
    assert _subsampled_ptp(np.array([])) is None
    assert _subsampled_ptp(np.array([np.nan, np.inf])) is None
    assert _subsampled_ptp(np.array([1.0, 5.0, 3.0])) == pytest.approx(4.0)


def test_looks_clipped_flags_flat_top_not_clean_sine():
    t = np.linspace(0, 20, 8000)
    clean = np.sin(t)
    clipped = np.clip(np.sin(t) * 2.0, -0.5, 0.5)  # saturates flat at ±0.5
    assert _looks_clipped(clean) is False
    assert _looks_clipped(clipped) is True
    assert _looks_clipped(np.full(8000, 3.0)) is False  # constant ≠ clipped


def test_colorbar_is_dead_logic():
    m = np.linspace(-60.0, 0.0, 400).reshape(20, 20)
    assert _colorbar_is_dead(m, -60.0, 0.0) is False   # full contrast window
    assert _colorbar_is_dead(m, 50.0, 60.0) is True    # window far off the data
    assert _colorbar_is_dead(m, 5.0, 5.0) is True      # degenerate (lo == hi)


# ---- time-domain canvas integration --------------------------------------

def _rows(specs):
    """specs: list of (unit, sig[, axis_group]) → plot_channels rows."""
    t = np.linspace(0.0, 10.0, 5000, dtype=np.float64)
    rows = []
    for i, spec in enumerate(specs):
        unit, sig = spec[0], spec[1]
        row = [f"ch{i}", True, t, sig, "#1769e0", unit, f"fid-{i}"]
        if len(spec) > 2 and spec[2] is not None:
            row.append({"axis_group": spec[2]})
        rows.append(tuple(row))
    return rows


def test_time_canvas_reports_count_and_same_unit(qapp, qtbot):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0, 10, 5000)
    canvas.plot_channels(_rows([("rpm", np.sin(t))] * 4), mode="overlay")
    sig = canvas.nudge_signals()
    assert sig["channel_count"] == 4
    assert sig["same_unit"] is True
    assert sig["has_axis_group"] is False


def test_time_canvas_same_unit_false_for_mixed(qapp, qtbot):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0, 10, 5000)
    canvas.plot_channels(
        _rows([("rpm", np.sin(t)), ("Nm", np.cos(t)), ("rpm", np.sin(t))]),
        mode="overlay",
    )
    assert canvas.nudge_signals()["same_unit"] is False


def test_time_canvas_has_axis_group_when_grouped(qapp, qtbot):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0, 10, 5000)
    canvas.plot_channels(
        _rows([("rpm", np.sin(t), 1), ("rpm", np.cos(t), 1)]),
        mode="overlay",
    )
    assert canvas.nudge_signals()["has_axis_group"] is True


def test_time_canvas_amp_disparate_detects_dwarfed_curve(qapp, qtbot):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0, 10, 5000)
    canvas.plot_channels(
        _rows([("V", np.sin(t) * 0.01), ("V", np.sin(t) * 100.0)]),
        mode="overlay",
    )
    assert canvas.nudge_signals()["amp_disparate"] is True


def test_time_canvas_calm_when_similar_amplitudes(qapp, qtbot):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0, 10, 5000)
    canvas.plot_channels(
        _rows([("V", np.sin(t)), ("V", np.cos(t))]), mode="overlay"
    )
    sig = canvas.nudge_signals()
    assert sig["amp_disparate"] is False
    assert sig["clipped"] is False


# ---- heatmap canvas integration ------------------------------------------

def test_heatmap_nudge_signals_track_colour_window(qapp, qtbot):
    canvas = PgHeatmapCanvas()
    qtbot.addWidget(canvas)
    m = np.linspace(-60.0, 0.0, 400).reshape(20, 20)
    canvas.plot_or_update_heatmap(m, (0.0, 1.0), (0.0, 1.0), z_auto=True)
    assert canvas.nudge_signals()["colorbar_dead"] is False

    # Shove the window far above the data → nothing visible → dead.
    canvas._img.setLevels((50.0, 60.0))
    assert canvas.nudge_signals()["colorbar_dead"] is True
