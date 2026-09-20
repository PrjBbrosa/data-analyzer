"""Time-range intent is configuration; ``plot_time`` is the execution gate.

Walks the 全时段 → 局部视窗 → 指定范围 → 绘图 → 全时段 → 再绘图 chain and
asserts ``channel_data`` time arrays, not just Inspector field values.
"""

import pytest

from tests.ui.test_main_window_smoke import _load_time_window_with_checked


def _plotted_channel_time(canvas, suffix="speed"):
    name = next(name for name in canvas.channel_data if name.endswith(suffix))
    t, _sig, _color, _unit = canvas.channel_data[name]
    return t


def _interior_window(time_array, start_frac=0.25, end_frac=0.45):
    lo = float(time_array.min())
    hi = float(time_array.max())
    span = hi - lo
    assert span > 0.0
    return lo + start_frac * span, lo + end_frac * span


def _assert_full_plotted_time(t, source):
    assert len(t) == len(source)
    assert float(t.min()) == pytest.approx(float(source.min()), abs=1e-6)
    assert float(t.max()) == pytest.approx(float(source.max()), abs=1e-6)


def _assert_window_plotted_time(t, win_lo, win_hi, source):
    assert float(t.min()) >= win_lo - 1e-6
    assert float(t.max()) <= win_hi + 1e-6
    assert len(t) < len(source)
    assert len(t) > 1


def test_time_range_toggle_defers_crop_until_plot_time(qapp, qtbot, loaded_csv):
    """Full source → zoom → arm selected range → plot → full → plot.

    Field values may track the camera the whole time; plotted samples change
    only when ``plot_time`` runs.
    """
    w, fid = _load_time_window_with_checked(qapp, qtbot, loaded_csv, ("speed",))
    source = w.files[fid].time_array
    win_lo, win_hi = _interior_window(source)
    top = w.inspector.top

    top.chk_range.setChecked(False)
    qapp.processEvents()
    assert top.range_enabled() is False
    _assert_full_plotted_time(_plotted_channel_time(w.canvas_time), source)

    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(win_lo, win_hi)
    w.canvas_time._flush_pending_refresh()
    qapp.processEvents()

    rlo, rhi = top.range_values()
    assert top.range_enabled() is False
    assert rlo == pytest.approx(win_lo, abs=1e-6)
    assert rhi == pytest.approx(win_hi, abs=1e-6)
    _assert_full_plotted_time(_plotted_channel_time(w.canvas_time), source)

    top.chk_range.setChecked(True)
    qapp.processEvents()

    assert top.range_enabled() is True
    rlo, rhi = top.range_values()
    assert rlo == pytest.approx(win_lo, abs=1e-6)
    assert rhi == pytest.approx(win_hi, abs=1e-6)
    _assert_full_plotted_time(_plotted_channel_time(w.canvas_time), source)
    nlo, nhi = w.canvas_time._primary_xaxis_ax.get_xlim()
    assert nlo == pytest.approx(win_lo, abs=1e-6)
    assert nhi == pytest.approx(win_hi, abs=1e-6)

    w.plot_time()
    qapp.processEvents()

    cropped = _plotted_channel_time(w.canvas_time)
    _assert_window_plotted_time(cropped, win_lo, win_hi, source)

    top.chk_range.setChecked(False)
    qapp.processEvents()

    assert top.range_enabled() is False
    _assert_window_plotted_time(
        _plotted_channel_time(w.canvas_time), win_lo, win_hi, source
    )

    span = win_hi - win_lo
    tighter_lo = win_lo + 0.2 * span
    tighter_hi = win_hi - 0.2 * span
    primary = w.canvas_time._primary_xaxis_ax
    primary.set_xlim(tighter_lo, tighter_hi)
    w.canvas_time._flush_pending_refresh()
    qapp.processEvents()

    assert top.range_enabled() is False
    rlo, rhi = top.range_values()
    assert rlo == pytest.approx(tighter_lo, abs=1e-6)
    assert rhi == pytest.approx(tighter_hi, abs=1e-6)
    _assert_window_plotted_time(
        _plotted_channel_time(w.canvas_time), win_lo, win_hi, source
    )

    w.plot_time()
    qapp.processEvents()

    _assert_full_plotted_time(_plotted_channel_time(w.canvas_time), source)
