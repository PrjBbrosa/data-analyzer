"""RED contract: TimeDomain Custom X dual-cursor uses X units and major legs.

Current production ``_emit_dual_cursor_html`` always prints ``ΔT`` / ``Hz``
and mixes both physical paths into one ``(x>=A)&(x<=B)`` segment. These
tests assert the NEW contract so they fail on current code.

Customer ``testdoc/`` samples are not required. Arrays come from
``tests/_helpers/wwt_factory.py``.
"""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parents[2]


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _resolve_cursor_x_axis_context_cls():
    for module_name in (
        "mf4_analyzer.ui.pg_canvas.cursor",
        "mf4_analyzer.ui.view_state",
        "mf4_analyzer.ui.time_xaxis",
    ):
        try:
            module = __import__(module_name, fromlist=["CursorXAxisContext"])
        except ImportError:
            continue
        cls = getattr(module, "CursorXAxisContext", None)
        if cls is not None:
            return cls
    return None


def _make_x_axis_context(*, unit, label, identity, mode="channel"):
    cls = _resolve_cursor_x_axis_context_cls()
    if cls is not None:
        try:
            return cls(mode=mode, identity=identity, label=label, unit=unit)
        except TypeError:
            return cls(mode=mode, unit=unit, label=label)
    return SimpleNamespace(mode=mode, identity=identity, label=label, unit=unit)


def _bind_custom_x_context(canvas, ctx):
    """Best-effort wiring onto the intended seam. Missing API is left as RED."""
    signature = inspect.signature(canvas.plot_channels)
    extra = {}
    if "x_axis_context" in signature.parameters:
        extra["x_axis_context"] = ctx
    setter = getattr(canvas, "set_cursor_x_axis_context", None)
    if callable(setter):
        setter(ctx)
    cursor = getattr(canvas, "_cursor", None)
    if cursor is not None:
        cursor_setter = getattr(cursor, "set_x_axis_context", None)
        if callable(cursor_setter):
            cursor_setter(ctx)
        elif hasattr(cursor, "x_axis_context"):
            try:
                cursor.x_axis_context = ctx
            except Exception:
                pass
    return extra


def _plot_custom_x(canvas, rows, *, unit="mm", label=wwt.SFNS_RACK_TRAVEL, identity=None):
    identity = identity or ("f1", wwt.SFNS_RACK_TRAVEL)
    ctx = _make_x_axis_context(unit=unit, label=label, identity=identity)
    extra = _bind_custom_x_context(canvas, ctx)
    canvas.plot_channels(rows, mode="overlay", **extra)
    QCoreApplication.processEvents()
    return ctx


def _emit_dual(canvas, a, b):
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    headers, htmls, rows_seen = [], [], []
    canvas.cursor_info.connect(headers.append)
    canvas.dual_cursor_info.connect(htmls.append)
    canvas.dual_cursor_rows.connect(rows_seen.append)
    canvas._cursor.ax = float(a)
    canvas._cursor.bx = float(b)
    canvas._emit_dual_cursor_html()
    QCoreApplication.processEvents()
    header = headers[-1] if headers else ""
    html = htmls[-1] if htmls else ""
    rows = rows_seen[-1] if rows_seen else []
    return header, html, rows


def _emit_single(canvas, x):
    legacy, structured = [], []
    canvas.cursor_info.connect(legacy.append)
    canvas.single_cursor_rows.connect(structured.append)
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(False)
    canvas._emit_single_cursor_html(float(x))
    QCoreApplication.processEvents()
    return legacy[-1] if legacy else "", structured[-1] if structured else []


def _blob(header, html, rows) -> str:
    return f"{header}\n{html}\n{rows!r}"


def _row_text(rows) -> str:
    parts = []
    for row in rows or ():
        if hasattr(row, "branch") or hasattr(row, "branch_label"):
            parts.append(str(getattr(row, "branch", "") or getattr(row, "branch_label", "")))
            parts.append(str(getattr(row, "status", "") or ""))
            parts.append(str(getattr(row, "label", "") or ""))
        parts.append(str(row))
    return " ".join(parts)


def _force_row(series, *, name, fid, color="#1769e0"):
    return (
        name,
        True,
        np.asarray(series.x, dtype=np.float64),
        np.asarray(series.y, dtype=np.float64),
        color,
        wwt.SFNS_RACK_FORCE_UNIT,
        fid,
    )


def test_custom_x_header_uses_mm_and_delta_x_not_seconds_or_hz(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("noisy")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = _blob(header, html, rows)

    assert wwt.SFNS_RACK_TRAVEL_UNIT in header
    assert "ΔX=" in header or "ΔX" in header
    assert f"A={wwt.SFNS_CURSOR_A:.1f}" in header or "A=" in header
    assert "ΔT" not in blob
    assert "Hz" not in blob
    assert "1/ΔT" not in blob


def test_time_domain_x_header_still_shows_delta_t_and_hz(qapp):
    """Non-regression: time X keeps A/B/ΔT/1/ΔT."""
    canvas = _pg_canvas(qapp)
    t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
    canvas.plot_channels(
        [("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-1")],
        mode="overlay",
    )
    QCoreApplication.processEvents()
    header, _html, _rows = _emit_dual(canvas, 0.20, 0.80)
    assert "ΔT=" in header
    assert "1/ΔT=" in header
    assert "Hz" in header


def test_custom_x_single_emits_rise_then_fall_current_values_only(qapp):
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

    legacy, rows = _emit_single(canvas, 4.0)

    assert "X=4.0 mm" in legacy
    assert len(rows) == 1
    row = rows[0]
    assert row.identity is not None
    assert row.source_label == "fid-a"
    assert row.channel_label == "force"
    assert [branch.label for branch in row.branches] == ["X↑", "X↓"]
    assert [branch.current_value for branch in row.branches] == pytest.approx(
        [40.0, 104.0]
    )
    assert row.current_value is None
    assert row.delta is None
    assert row.min_value is None
    assert row.max_value is None
    assert row.avg_value is None


def test_time_single_legacy_html_stays_compatible_and_adds_structured_value(qapp):
    from mf4_analyzer.ui.plot_helpers import _format_single_cursor_channel_html

    canvas = _pg_canvas(qapp)
    t = np.asarray([0.0, 0.5, 1.0], dtype=np.float64)
    y = np.asarray([1.0, 2.0, 3.0], dtype=np.float64)
    canvas.plot_channels(
        [("[source-a] speed", True, t, y, "#1769e0", "rpm", "fid-a")],
        mode="overlay",
    )
    QCoreApplication.processEvents()

    legacy, rows = _emit_single(canvas, 0.5)

    sep = '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
    expected = sep.join((
        '<span style="color:#111827;">t=0.5000s</span>',
        _format_single_cursor_channel_html(
            "[source-a] speed", 2.0, " rpm", "#1769e0"
        ),
    ))
    assert legacy == expected
    assert len(rows) == 1
    assert rows[0].current_value == pytest.approx(2.0)
    assert rows[0].branches == ()


def test_noisy_single_cycle_emits_exactly_two_x_up_x_down_branches(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("noisy")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = _blob(header, html, rows) + " " + _row_text(rows)

    assert "X↑" in blob
    assert "X↓" in blob
    assert blob.count("X↑") == 1
    assert blob.count("X↓") == 1
    assert "全程" not in blob


def test_same_display_name_from_two_sources_keeps_four_branches(qapp):
    """Composite identity must not merge two Rack Force curves into one pair."""
    canvas = _pg_canvas(qapp)
    first = wwt.sfns_like_hysteresis_arrays("cycle", y_offset=0.0)
    second = wwt.sfns_like_hysteresis_arrays("cycle", y_offset=8.0)
    _plot_custom_x(
        canvas,
        [
            _force_row(first, name=wwt.SFNS_RACK_FORCE, fid="fid-a", color="#ef4444"),
            _force_row(second, name=wwt.SFNS_RACK_FORCE, fid="fid-b", color="#1769e0"),
        ],
        identity=("fid-a", wwt.SFNS_RACK_TRAVEL),
    )
    _header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = html + " " + _row_text(rows)
    assert blob.count("X↑") == 2
    assert blob.count("X↓") == 2


def test_empty_custom_x_interval_does_not_forge_stats(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("cycle")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    header, html, rows = _emit_dual(canvas, -99.0, -90.0)
    blob = _blob(header, html, rows)
    assert "X↑" not in blob
    assert "X↓" not in blob
    assert "区间内无数据" in blob


def test_unidirectional_custom_x_uses_full_path_not_forged_pair(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("unidirectional")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    _header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = html + " " + _row_text(rows)
    assert "全程" in blob
    assert "X↑" not in blob
    assert "X↓" not in blob


def test_two_same_direction_visits_show_diagnostic_not_forged_pair(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("same_direction")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    _header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = html + " " + _row_text(rows)
    assert "X↑" not in blob or "X↓" not in blob
    assert "X↑" not in blob or blob.count("X↑") + blob.count("X↓") != 2
    assert any(
        token in blob
        for token in ("同向", "无法确定", "无法可靠", "诊断")
    ), blob


def test_three_or_more_paths_show_unreliable_diagnostic(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("two_cycles")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    _header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = html + " " + _row_text(rows)
    assert "X↑" not in blob
    assert "X↓" not in blob
    assert "无法可靠区分升程/回程" in blob


def test_nan_gap_is_hard_segment_boundary_not_forged_pair(qapp):
    """NaN is a hard segment boundary; A/B away from the hole may still be a pair.

    The hole sits near x≈0. ``SFNS_CURSOR_A/B = [-60, -45]`` is on the first
    outward stroke *and* the return stroke, so a unique ``X↑/X↓`` pair is
    legitimate and must not splice across the NaN.
    """
    from mf4_analyzer.signal.custom_x_paths import analyze_custom_x_paths

    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("nan_gap")
    nan_idx = int(np.flatnonzero(~np.isfinite(series.x))[0])
    planned = analyze_custom_x_paths(
        series.x, series.y, x_range=(wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B),
    )
    assert planned.unique_pair
    for contrib in (*planned.accepted, *planned.contributions):
        assert np.all(np.isfinite(contrib.x))
        if contrib.indices.size:
            assert not (int(contrib.indices.min()) < nan_idx < int(contrib.indices.max()))

    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    _header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = html + " " + _row_text(rows)
    assert "X↑" in blob
    assert "X↓" in blob

    spanning = analyze_custom_x_paths(series.x, series.y, x_range=(-20.0, 20.0))
    for contrib in (*spanning.accepted, *spanning.contributions):
        if contrib.indices.size:
            assert not (int(contrib.indices.min()) < nan_idx < int(contrib.indices.max()))


def test_custom_x_does_not_sort_interp_a_single_delta_y(qapp, monkeypatch):
    """Custom X must not compress two Y values at one X into a single △."""
    from mf4_analyzer.ui.pg_canvas import cursor as cursor_mod

    calls = []
    real = cursor_mod._interp_cursor_value

    def _wrapped(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(cursor_mod, "_interp_cursor_value", _wrapped)
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("cycle")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    _header, html, rows = _emit_dual(canvas, wwt.SFNS_CURSOR_A, wwt.SFNS_CURSOR_B)
    blob = html + " " + _row_text(rows)
    assert calls == [], (
        "Custom X must not call sort+np.interp single-value ΔY; "
        f"called {len(calls)} times"
    )
    assert "△" not in blob


def test_optional_customer_sfns_custom_x_skip_if_missing():
    sample_dir = _ROOT / "testdoc" / "2024_3_17"
    matches = sorted(sample_dir.glob("SFNS_*.wwt")) if sample_dir.is_dir() else []
    if not matches:
        pytest.skip("customer testdoc/2024_3_17/SFNS_*.wwt missing")
    assert matches[0].is_file()
