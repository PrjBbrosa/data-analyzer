"""Custom-X path-analysis memo on the canvas cursor collaborator."""
from __future__ import annotations

from dataclasses import replace
import inspect
from types import SimpleNamespace

import numpy as np
from PyQt5.QtCore import QCoreApplication

from tests._helpers import wwt_factory as wwt


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
    return extra


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


def _plot_custom_x(canvas, rows, *, unit="mm", label=wwt.SFNS_RACK_TRAVEL, identity=None):
    identity = identity or ("f1", wwt.SFNS_RACK_TRAVEL)
    ctx = _make_x_axis_context(unit=unit, label=label, identity=identity)
    extra = _bind_custom_x_context(canvas, ctx)
    canvas.plot_channels(rows, mode="overlay", **extra)
    QCoreApplication.processEvents()
    return ctx


def _emit_single(canvas, x):
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(False)
    canvas._emit_single_cursor_html(float(x))
    QCoreApplication.processEvents()


def _emit_dual(canvas, x_a, x_b):
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    canvas._cursor._ax = float(x_a)
    canvas._cursor._bx = float(x_b)
    canvas._emit_dual_cursor_html()
    QCoreApplication.processEvents()


def _counting_analyze(monkeypatch):
    import mf4_analyzer.ui.pg_canvas.cursor as cursor_mod

    original = cursor_mod.analyze_custom_x_paths
    calls = []

    def _wrapped(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(cursor_mod, "analyze_custom_x_paths", _wrapped)
    return calls


def _plotted_canvas(qapp):
    canvas = _pg_canvas(qapp)
    series = wwt.sfns_like_hysteresis_arrays("cycle")
    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    return canvas, series


def test_second_sample_on_same_channel_does_not_reanalyze(qapp, monkeypatch):
    canvas, series = _plotted_canvas(qapp)
    calls = _counting_analyze(monkeypatch)
    mid = float(np.mean((series.x[0], series.x[series.x.size // 4])))

    _emit_single(canvas, mid)
    _emit_single(canvas, mid + 1.0)

    assert len(calls) == 1
    assert canvas._cursor._custom_x_path_cache


def test_dual_emit_and_value_toggle_reuse_hot_cache(qapp, monkeypatch):
    canvas, series = _plotted_canvas(qapp)
    calls = _counting_analyze(monkeypatch)
    x_a = float(series.x[series.x.size // 5])
    x_b = float(series.x[series.x.size * 2 // 5])

    _emit_single(canvas, x_a)
    assert len(calls) == 1
    calls.clear()

    _emit_dual(canvas, x_a, x_b)
    options = canvas._cursor.cursor_display_options()
    canvas._cursor.set_cursor_display_options(
        replace(options, show_avg_value=not options.show_avg_value)
    )

    assert calls == []


def test_invalidate_monotonicity_cache_forces_reanalyze(qapp, monkeypatch):
    canvas, series = _plotted_canvas(qapp)
    calls = _counting_analyze(monkeypatch)
    mid = float(series.x[len(series.x) // 4])

    _emit_single(canvas, mid)
    assert len(calls) == 1

    canvas.invalidate_monotonicity_cache()
    assert canvas._cursor._custom_x_path_cache == {}

    _emit_single(canvas, mid)
    assert len(calls) == 2


def test_file_close_style_monotonicity_invalidate_drops_path_memo(qapp, monkeypatch):
    canvas, series = _plotted_canvas(qapp)
    calls = _counting_analyze(monkeypatch)
    mid = float(series.x[len(series.x) // 4])

    _emit_single(canvas, mid)
    assert len(calls) == 1

    canvas.invalidate_monotonicity_cache(custom_xaxis_fid="f1")
    assert canvas._cursor._custom_x_path_cache == {}

    _emit_single(canvas, mid)
    assert len(calls) == 2


def test_range_filter_envelope_invalidate_drops_path_memo(qapp, monkeypatch):
    canvas, series = _plotted_canvas(qapp)
    calls = _counting_analyze(monkeypatch)
    mid = float(series.x[len(series.x) // 4])

    _emit_single(canvas, mid)
    assert len(calls) == 1

    canvas.invalidate_envelope_cache("range filter changed")
    assert canvas._cursor._custom_x_path_cache == {}

    _emit_single(canvas, mid)
    assert len(calls) == 2


def test_plot_channels_rebuild_drops_path_memo(qapp, monkeypatch):
    canvas, series = _plotted_canvas(qapp)
    calls = _counting_analyze(monkeypatch)
    mid = float(series.x[len(series.x) // 4])

    _emit_single(canvas, mid)
    assert len(calls) == 1

    _plot_custom_x(canvas, [_force_row(series, name=wwt.SFNS_RACK_FORCE, fid="f1")])
    assert canvas._cursor._custom_x_path_cache == {}

    _emit_single(canvas, mid)
    assert len(calls) == 2
