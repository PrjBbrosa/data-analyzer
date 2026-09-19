"""Side-effect-free cursor evaluate facts vs live emit (pinned-cursor Task 1)."""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayChannel,
    CursorExtremaFact,
    FrequencyCursorChannel,
    FrfCursorPoint,
    FrfCursorSample,
    PinnedCursorSample,
)
from tests.ui.test_custom_x_cursor_contract import (
    _emit_dual,
    _emit_single,
    _force_row,
    _pg_canvas,
    _plot_custom_x,
)
from tests.ui.test_frf_canvas import _result
from tests.ui.test_pg_line_canvas import _entry
from tests._helpers import wwt_factory as wwt


REPO_ROOT = Path(__file__).resolve().parents[2]


def _watch(source, *signal_names):
    buckets = {}
    for name in signal_names:
        bucket = []
        getattr(source, name).connect(bucket.append)
        buckets[name] = bucket
    return buckets


def _line_state(items):
    state = []
    for item in items or ():
        try:
            state.append((float(item.value()), bool(item.isVisible())))
        except Exception:
            state.append(None)
    return tuple(state)


def _time_cursor_state(canvas):
    cursor = canvas._cursor
    return {
        "ax": cursor._ax,
        "bx": cursor._bx,
        "placing": cursor._placing,
        "last_t": cursor._last_t,
        "placement": canvas.snapshot_cursor_placement(),
        "lines": _line_state(cursor._cursor_line_items),
        "a_lines": _line_state(cursor._cursor_a_items),
        "b_lines": _line_state(cursor._cursor_b_items),
    }


def _fft_cursor_state(canvas):
    return {
        "a": canvas._cursor_a_frequency,
        "b": canvas._cursor_b_frequency,
        "placement": canvas.snapshot_cursor_placement(),
        "lines": _line_state(canvas._cursor_lines),
        "a_lines": _line_state(canvas._cursor_a_lines),
        "b_lines": _line_state(canvas._cursor_b_lines),
    }


def _frf_cursor_state(canvas):
    return {
        "a": canvas._cursor_a_frequency,
        "b": canvas._cursor_b_frequency,
        "placement": canvas.snapshot_cursor_placement(),
        "lines": _line_state(canvas._cursor_lines),
        "a_lines": _line_state(canvas._cursor_a_lines),
        "b_lines": _line_state(canvas._cursor_b_lines),
    }


def _assert_optional_close(actual, expected):
    if expected is None:
        assert actual is None
        return
    expected_f = float(expected)
    if not np.isfinite(expected_f):
        assert actual is None or not np.isfinite(float(actual))
        return
    assert actual == pytest.approx(expected_f)


def _assert_dual_matches_live(channels, rows):
    assert len(channels) == len(rows)
    for channel, row in zip(channels, rows):
        assert channel.identity == row.identity
        _assert_optional_close(channel.delta, row.delta)
        _assert_optional_close(channel.min_value, row.min_value)
        _assert_optional_close(channel.max_value, row.max_value)
        _assert_optional_close(channel.avg_value, row.avg)
        assert str(channel.diagnostic or "") == str(getattr(row, "status", "") or "")
        live_branches = tuple(getattr(row, "branches", ()) or ())
        assert len(channel.branches) == len(live_branches)
        for branch, raw in zip(channel.branches, live_branches):
            assert branch.label == raw.branch_label
            _assert_optional_close(branch.min_value, raw.min_value)
            _assert_optional_close(branch.max_value, raw.max_value)
            _assert_optional_close(branch.avg_value, raw.avg)
            _assert_optional_close(branch.delta_value, raw.delta)


def _plot_time_ramp(canvas):
    t = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    y = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    canvas.plot_channels(
        [("[source-a] speed", True, t, y, "#1769e0", "rpm", "fid-a")],
        mode="overlay",
    )
    QCoreApplication.processEvents()


def _fft_canvas(qapp):
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas()
    canvas.resize(640, 480)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _frf_canvas(qtbot):
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas

    canvas = PgFrfCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(900, 700)
    canvas.show()
    qtbot.wait(20)
    return canvas


def test_cursor_display_model_stays_qt_free():
    src = REPO_ROOT / "mf4_analyzer" / "ui" / "cursor_display_model.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert all("Qt" not in name and "PyQt" not in name for name in imported)
    for cls in (
        FrfCursorPoint, FrfCursorSample, PinnedCursorSample, CursorExtremaFact,
    ):
        assert cls.__dataclass_params__.frozen is True


def test_pinned_cursor_sample_is_immutable():
    sample = PinnedCursorSample(
        domain="time",
        mode="single",
        x=0.5,
        channels=(),
        data_revision=1,
    )
    with pytest.raises(FrozenInstanceError):
        sample.x = 1.0
    with pytest.raises(FrozenInstanceError):
        sample.frf_sample = FrfCursorSample(frequency_hz=1.0)


def test_time_single_evaluate_matches_live_t_half_value(qapp):
    canvas = _pg_canvas(qapp)
    _plot_time_ramp(canvas)
    before = _time_cursor_state(canvas)
    signals = _watch(
        canvas, "cursor_info", "single_cursor_rows",
        "dual_cursor_rows", "dual_cursor_info",
    )

    evaluated = canvas.evaluate_single_cursor(0.5)

    assert signals["cursor_info"] == []
    assert signals["single_cursor_rows"] == []
    assert signals["dual_cursor_rows"] == []
    assert _time_cursor_state(canvas) == before
    assert _line_state(canvas._cursor._cursor_line_items) == before["lines"]

    _legacy, rows = _emit_single(canvas, 0.5)
    assert evaluated == tuple(rows)
    assert len(evaluated) == 1
    assert evaluated[0].current_value == pytest.approx(2.0)
    assert evaluated[0].branches == ()
    assert isinstance(evaluated[0], CursorDisplayChannel)


def test_custom_x_single_evaluate_matches_rise_then_fall_at_four(qapp):
    canvas = _pg_canvas(qapp)
    x = np.concatenate((
        np.linspace(0.0, 10.0, 51),
        np.linspace(10.0, 0.0, 51)[1:],
    ))
    y = np.concatenate((10.0 * x[:51], 100.0 + x[51:]))
    _plot_custom_x(
        canvas,
        [("[source-a] force", True, x, y, "#1769e0", "N", "fid-a")],
        unit="mm",
        label="travel",
        identity=("fid-a", "travel"),
    )
    before = _time_cursor_state(canvas)
    signals = _watch(canvas, "cursor_info", "single_cursor_rows")

    evaluated = canvas.evaluate_single_cursor(4.0)

    assert signals["cursor_info"] == []
    assert signals["single_cursor_rows"] == []
    assert _time_cursor_state(canvas) == before
    _legacy, rows = _emit_single(canvas, 4.0)
    assert evaluated == tuple(rows)
    row = evaluated[0]
    assert [branch.label for branch in row.branches] == ["X↑", "X↓"]
    assert [branch.current_value for branch in row.branches] == pytest.approx(
        [40.0, 104.0]
    )
    assert row.current_value is None
    assert row.delta is None
    assert row.min_value is None
    assert row.max_value is None
    assert row.avg_value is None


def test_custom_x_evaluate_does_not_forge_empty_diagnostics(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("cycle")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])

    dual = canvas.evaluate_dual_cursor(-99.0, -90.0)
    assert dual
    for channel in dual:
        assert channel.diagnostic
        assert "区间内无数据" in channel.diagnostic
        assert channel.min_value is None
        assert channel.max_value is None
        assert channel.avg_value is None
        assert channel.delta is None
        assert channel.branches == ()
        assert 0.0 not in (
            channel.min_value, channel.max_value, channel.avg_value, channel.delta,
        )

    single = canvas.evaluate_single_cursor(-99.0)
    assert single
    for channel in single:
        assert channel.diagnostic
        if channel.current_value is not None:
            assert channel.current_value != 0
        assert all(
            branch.current_value is None or branch.current_value != 0
            for branch in channel.branches
        )

    _header, _html, live_rows = _emit_dual(canvas, -99.0, -90.0)
    _assert_dual_matches_live(dual, live_rows)


def test_time_dual_evaluate_a_equals_b_and_a_greater_than_b(qapp):
    canvas = _pg_canvas(qapp)
    _plot_time_ramp(canvas)

    equal = canvas.evaluate_dual_cursor(0.5, 0.5)
    assert equal
    assert equal[0].delta == pytest.approx(0.0)
    assert np.isfinite(equal[0].delta)
    assert equal[0].min_value == pytest.approx(2.0)
    assert equal[0].max_value == pytest.approx(2.0)

    reversed_ab = canvas.evaluate_dual_cursor(1.0, 0.0)
    assert reversed_ab[0].delta == pytest.approx(-2.0)
    assert reversed_ab[0].min_value == pytest.approx(1.0)
    assert reversed_ab[0].max_value == pytest.approx(3.0)

    before = _time_cursor_state(canvas)
    _header, _html, live_equal = _emit_dual(canvas, 0.5, 0.5)
    _assert_dual_matches_live(equal, live_equal)
    canvas._cursor.ax = before["ax"]
    canvas._cursor.bx = before["bx"]

    _header, _html, live_rev = _emit_dual(canvas, 1.0, 0.0)
    _assert_dual_matches_live(reversed_ab, live_rev)
    assert live_rev[0].delta == pytest.approx(-2.0)


def test_custom_x_dual_evaluate_keeps_signed_delta_and_does_not_swap(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("cycle")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    a, b = wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B
    forward = canvas.evaluate_dual_cursor(a, b)
    backward = canvas.evaluate_dual_cursor(b, a)
    assert forward and backward
    _header, _html, live_forward = _emit_dual(canvas, a, b)
    _assert_dual_matches_live(forward, live_forward)
    _header, _html, live_backward = _emit_dual(canvas, b, a)
    _assert_dual_matches_live(backward, live_backward)
    for left, right in zip(forward, backward):
        for lb, rb in zip(left.branches, right.branches):
            if lb.delta_value is None or rb.delta_value is None:
                continue
            assert lb.delta_value == pytest.approx(-rb.delta_value)


def test_time_evaluate_does_not_emit_or_move_lines(qapp):
    canvas = _pg_canvas(qapp)
    _plot_time_ramp(canvas)
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    canvas._cursor.ax = 0.25
    canvas._cursor.bx = 0.75
    canvas._emit_dual_cursor_html()
    QCoreApplication.processEvents()
    before = _time_cursor_state(canvas)
    signals = _watch(
        canvas, "cursor_info", "single_cursor_rows",
        "dual_cursor_rows", "dual_cursor_info",
    )

    canvas.evaluate_single_cursor(0.5)
    canvas.evaluate_dual_cursor(0.1, 0.9)
    canvas._cursor.evaluate_dual_cursor_sample(0.1, 0.9)

    assert all(not bucket for bucket in signals.values())
    assert _time_cursor_state(canvas) == before


def test_time_evaluate_missing_and_nonfinite_are_empty_not_zero(qapp):
    canvas = _pg_canvas(qapp)
    canvas.plot_channels(
        [("empty", True, np.asarray([]), np.asarray([]), "#1769e0", "", "fid-a")],
        mode="overlay",
    )
    QCoreApplication.processEvents()
    assert canvas.evaluate_single_cursor(0.5) == ()
    assert canvas.evaluate_single_cursor(float("nan")) == ()
    assert canvas.evaluate_dual_cursor(0.0, float("inf")) == ()
    assert canvas._cursor.evaluate_single_cursor_sample(float("nan")) is None


def test_time_dual_sample_carries_revision_and_extrema(qapp):
    canvas = _pg_canvas(qapp)
    _plot_time_ramp(canvas)
    revision = canvas._cursor._cursor_data_revision
    sample = canvas._cursor.evaluate_dual_cursor_sample(0.0, 1.0)
    assert sample is not None
    assert sample.data_revision == revision
    assert sample.domain == "time"
    assert sample.mode == "dual"
    assert sample.ax == pytest.approx(0.0)
    assert sample.bx == pytest.approx(1.0)
    assert sample.extrema
    assert isinstance(sample.extrema[0], CursorExtremaFact)
    with pytest.raises(FrozenInstanceError):
        sample.ax = 3.0


def test_fft_evaluate_first_curve_snap_and_per_curve_grid(qapp):
    canvas = _fft_canvas(qapp)
    e1 = {
        "label": "force",
        "channel": "force",
        "fid": "fid-a",
        "color": "#2563eb",
        "freq": np.array([0.0, 10.0, 20.0], dtype=float),
        "amp": np.array([1.0, 2.0, 3.0], dtype=float),
        "time": np.linspace(0.0, 1.0, 8),
        "signal": np.zeros(8),
    }
    e2 = {
        "label": "force",
        "channel": "force",
        "fid": "fid-b",
        "color": "#dc2626",
        "freq": np.array([0.0, 12.0, 24.0], dtype=float),
        "amp": np.array([4.0, 5.0, 6.0], dtype=float),
        "time": np.linspace(0.0, 1.0, 8),
        "signal": np.zeros(8),
    }
    canvas.plot_spectra(
        [e1, e2], xlim=(0.0, 30.0), amp_label="Amplitude", title="FFT",
    )
    before = _fft_cursor_state(canvas)
    signals = _watch(
        canvas, "cursor_info", "frequency_cursor_channels",
        "frequency_cursor_rows", "dual_cursor_info",
    )

    result = canvas.evaluate_frequency_cursor(11.0)

    assert result is not None
    snapped, channels = result
    assert snapped == pytest.approx(10.0)
    assert [channel.identity for channel in channels] == [
        ("fid-a", "force"),
        ("fid-b", "force"),
    ]
    assert channels[0].value == pytest.approx(2.0)
    assert channels[1].value == pytest.approx(5.0)
    assert channels[0].delta_to_primary is None
    assert channels[1].delta_to_primary == pytest.approx(3.0)
    assert signals["cursor_info"] == []
    assert signals["frequency_cursor_channels"] == []
    assert _fft_cursor_state(canvas) == before

    live = []
    canvas.frequency_cursor_channels.connect(live.append)
    canvas.set_cursor_frequency(11.0)
    assert tuple(live[-1]) == channels


def test_fft_dual_evaluate_delta_vs_primary_and_incomplete_b(qapp):
    canvas = _fft_canvas(qapp)
    e1, e2 = _entry("a", "#2563eb"), _entry("b", "#dc2626")
    e1 = dict(e1, fid="fid-a", channel="a")
    e2 = dict(e2, amp=e2["amp"] * 0.5, signal=e2["signal"] * 0.5, fid="fid-b", channel="b")
    canvas.plot_spectra(
        [e1, e2], xlim=(0.0, 500.0), amp_label="Amplitude", title="FFT",
    )
    before = _fft_cursor_state(canvas)
    assert canvas.evaluate_dual_frequency_cursor(100.0, None) is None
    assert canvas._cursor_a_frequency is None
    assert _fft_cursor_state(canvas) == before

    evaluated = canvas.evaluate_dual_frequency_cursor(100.0, 200.0)
    assert evaluated is not None
    a_hz, b_hz, channels = evaluated
    assert np.isfinite(a_hz) and np.isfinite(b_hz)
    assert len(channels) == 2
    for channel in channels:
        assert channel.delta_ab == pytest.approx(channel.b_value - channel.a_value)
        assert isinstance(channel, FrequencyCursorChannel)
    assert channels[0].identity != channels[1].identity
    assert _fft_cursor_state(canvas) == before

    live = []
    canvas.frequency_cursor_channels.connect(live.append)
    canvas.set_dual_cursor_frequencies(100.0, 200.0)
    assert tuple(live[-1]) == channels

    reversed_eval = canvas.evaluate_dual_frequency_cursor(200.0, 100.0)
    assert reversed_eval is not None
    _a, _b, reversed_channels = reversed_eval
    assert reversed_channels[0].delta_ab == pytest.approx(-channels[0].delta_ab)

    sample = canvas.evaluate_frequency_cursor_sample(120.0)
    assert sample is not None
    assert sample.binding_generation == canvas._spectrum_display_generation
    assert sample.data_revision == canvas._spectrum_display_revision
    with pytest.raises(FrozenInstanceError):
        sample.x = 0.0


def test_fft_evaluate_nonfinite_and_empty_are_none(qapp):
    canvas = _fft_canvas(qapp)
    assert canvas.evaluate_frequency_cursor(120.0) is None
    assert canvas.evaluate_frequency_cursor(float("nan")) is None
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label="Amplitude", title="FFT",
    )
    assert canvas.evaluate_frequency_cursor(float("inf")) is None
    assert canvas.evaluate_dual_frequency_cursor(100.0, float("nan")) is None


def test_frf_evaluate_linear_matches_live_and_keeps_hz(qtbot):
    canvas = _frf_canvas(qtbot)
    canvas.set_result(
        _result(),
        {"frequency_scale": "linear", "magnitude_scale": "linear", "phase_mode": "wrapped"},
        {},
    )
    before = _frf_cursor_state(canvas)
    signals = _watch(canvas, "cursor_info", "dual_cursor_info")

    sample = canvas.evaluate_frequency_cursor(1.1)

    assert sample is not None
    idx = canvas._nearest_frequency_index(1.1)
    assert sample.frequency_hz == pytest.approx(float(canvas._draw_frequencies[idx]))
    assert sample.frequency_hz == pytest.approx(1.0)
    assert sample.magnitude == pytest.approx(2.0)
    assert sample.phase_deg == pytest.approx(0.0)
    assert sample.coherence == pytest.approx(0.95)
    assert signals["cursor_info"] == []
    assert _frf_cursor_state(canvas) == before

    live = []
    canvas.cursor_info.connect(live.append)
    readout = canvas.set_cursor_frequency(1.1)
    assert "f=1" in readout
    assert live[-1] == readout
    assert sample.frequency_hz == pytest.approx(1.0)


def test_frf_evaluate_log_keeps_hz_and_does_not_write_line_value(qtbot):
    canvas = _frf_canvas(qtbot)
    result = _result()
    result.frequencies = np.array([0.0, 1.0, 10.0, 100.0, 1000.0])
    canvas.set_result(result, {"frequency_scale": "log"}, {})
    before_values = tuple(line.value() for line in canvas._cursor_lines)
    before_visible = tuple(line.isVisible() for line in canvas._cursor_lines)

    sample = canvas.evaluate_frequency_cursor(10.0)

    assert sample is not None
    assert sample.frequency_hz == pytest.approx(10.0)
    assert tuple(line.value() for line in canvas._cursor_lines) == before_values
    assert tuple(line.isVisible() for line in canvas._cursor_lines) == before_visible
    canvas.set_cursor_frequency(10.0)
    assert all(line.value() == pytest.approx(1.0) for line in canvas._cursor_lines)


def test_frf_dual_evaluate_is_all_or_nothing_signed_delta(qtbot):
    canvas = _frf_canvas(qtbot)
    canvas.set_result(
        _result(),
        {"frequency_scale": "linear", "magnitude_scale": "linear"},
        {},
    )
    before = _frf_cursor_state(canvas)
    assert canvas.evaluate_dual_frequency_cursor(1.1, None) is None
    assert canvas._cursor_a_frequency is None
    assert _frf_cursor_state(canvas) == before

    sample = canvas.evaluate_dual_frequency_cursor(1.1, 3.8)
    assert sample is not None
    assert sample.a is not None and sample.b is not None
    assert sample.a.frequency_hz == pytest.approx(1.0)
    assert sample.b.frequency_hz == pytest.approx(4.0)
    assert sample.delta_frequency_hz == pytest.approx(3.0)
    assert sample.delta_magnitude == pytest.approx(
        sample.b.magnitude - sample.a.magnitude
    )
    assert sample.delta_phase_deg == pytest.approx(
        sample.b.phase_deg - sample.a.phase_deg
    )
    assert sample.delta_coherence == pytest.approx(
        sample.b.coherence - sample.a.coherence
    )
    assert _frf_cursor_state(canvas) == before

    reversed_sample = canvas.evaluate_dual_frequency_cursor(3.8, 1.1)
    assert reversed_sample.delta_frequency_hz == pytest.approx(
        -sample.delta_frequency_hz
    )
    assert reversed_sample.delta_magnitude == pytest.approx(-sample.delta_magnitude)

    live_primary, live_detail = [], []
    canvas.cursor_info.connect(live_primary.append)
    canvas.dual_cursor_info.connect(live_detail.append)
    text = canvas.set_dual_cursor_frequencies(1.1, 3.8)
    assert "A=1 Hz" in text and "B=4 Hz" in text and "Δf=+3 Hz" in text
    assert "Δ|H|=" in live_detail[-1]


def test_frf_evaluate_nonfinite_is_empty_not_zero(qtbot):
    canvas = _frf_canvas(qtbot)
    canvas.set_result(
        _result(),
        {"frequency_scale": "linear", "magnitude_scale": "linear"},
        {},
    )
    sample = canvas.evaluate_frequency_cursor(2.0)
    assert sample is not None
    assert sample.frequency_hz == pytest.approx(2.0)
    assert sample.magnitude is None
    assert sample.phase_deg is None
    assert sample.coherence is None
    assert sample.magnitude != 0
    assert canvas.evaluate_frequency_cursor(float("nan")) is None
    empty = _frf_canvas(qtbot)
    assert empty.evaluate_frequency_cursor(1.0) is None
    assert empty.evaluate_dual_frequency_cursor(1.0, 2.0) is None
