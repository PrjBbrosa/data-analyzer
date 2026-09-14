"""Spectrum peak-trace coverage cache (plan T3 / §3.3)."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import pyqtgraph as pg

from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.pg_canvas.spectrum_display import (
    OVERSCAN_FRACTION,
    SpectrumCurveIndex,
    SpectrumDisplayRequest,
    build_spectrum_trace_cache,
    clip_overscan_cover,
    plan_spectrum_display,
)


@pytest.fixture
def canvas(qapp):
    c = PgLineCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _entry(label='f1 · vib', color='#2563eb', n=501, fmax=500.0):
    freq = np.linspace(0.0, fmax, n)
    amp = np.exp(-((freq - 120.0) / 15.0) ** 2)
    time = np.linspace(0.0, 1.0, 64)
    signal = np.sin(2.0 * np.pi * 12.0 * time)
    return {
        'label': label,
        'color': color,
        'freq': freq,
        'amp': amp,
        'time': time,
        'signal': signal,
    }


def _plot_fft(canvas, entry=None, xlim=(0.0, 500.0), **kwargs):
    if entry is None:
        entry = _entry()
    canvas.plot_spectra(
        [entry], xlim=xlim, amp_label=kwargs.get('amp_label', 'Amplitude'),
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    return entry


def _amp_setdata_log(canvas, monkeypatch):
    calls = []
    orig = pg.PlotDataItem.setData

    def wrapped(self, *args, **kwargs):
        if self in canvas._amp_curves:
            calls.append((args, kwargs))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(pg.PlotDataItem, 'setData', wrapped)
    return calls


def _curve(first, last, fully, breaks=()):
    return SpectrumCurveIndex(first, last, fully, breaks)


def _request(*, revision=1, ident=('a',), lo=0.0, hi=500.0, width=400,
             curves=None, data_lo=0.0, data_hi=500.0):
    if curves is None:
        curves = (_curve(0, 500, True),)
    return SpectrumDisplayRequest(
        revision, ident, lo, hi, width, curves, data_lo, data_hi,
    )


def _cache_for(request, cover_curves=None):
    plan = plan_spectrum_display(request, None)
    curves = cover_curves if cover_curves is not None else request.curves
    return build_spectrum_trace_cache(request, plan, curves)


def test_plan_full_coverage_pan_hits_without_exact_xlim():
    first = _request(lo=0.0, hi=500.0)
    cache = _cache_for(first)
    pan = _request(lo=-40.0, hi=540.0)
    plan = plan_spectrum_display(pan, cache)
    assert plan.reuse is True
    assert plan.reason == 'hit'


def test_plan_index_stable_slices_hit_when_xlim_floats_differ():
    curves = (_curve(99, 201, False),)
    first = _request(lo=100.0, hi=200.0, curves=curves)
    cache = replace(
        _cache_for(first, cover_curves=curves),
        fully_covered=False,
    )
    pan = _request(lo=100.25, hi=200.25, curves=curves)
    plan = plan_spectrum_display(pan, cache)
    assert plan.reuse is True


def test_plan_zoom_in_density_misses():
    first = _request(lo=0.0, hi=500.0, width=400)
    cache = _cache_for(first)
    zoom = _request(lo=100.0, hi=200.0, width=400, curves=(_curve(100, 200, False),))
    plan = plan_spectrum_display(zoom, cache)
    assert plan.reuse is False
    assert plan.reason == 'density'


def test_plan_pixel_width_up_density_misses():
    first = _request(lo=0.0, hi=500.0, width=400)
    cache = _cache_for(first)
    wider = _request(lo=0.0, hi=500.0, width=800)
    plan = plan_spectrum_display(wider, cache)
    assert plan.reuse is False
    assert plan.reason == 'density'


def test_plan_overscan_contains_then_past_buffer_misses():
    assert OVERSCAN_FRACTION == 0.5
    target = _request(lo=100.0, hi=200.0, curves=(_curve(99, 201, False),))
    plan = plan_spectrum_display(target, None)
    cover_lo, cover_hi = clip_overscan_cover(100.0, 200.0, 0.0, 500.0)
    assert (cover_lo, cover_hi) == (50.0, 250.0)
    assert plan.cover_lo == 50.0 and plan.cover_hi == 250.0
    assert plan.bucket_width == 800
    cache = build_spectrum_trace_cache(
        target, plan, (_curve(49, 251, False),),
    )
    inside = _request(lo=110.0, hi=210.0, curves=(_curve(109, 211, False),))
    assert plan_spectrum_display(inside, cache).reuse is True
    past = _request(lo=200.0, hi=300.0, curves=(_curve(199, 301, False),))
    miss = plan_spectrum_display(past, cache)
    assert miss.reuse is False
    assert miss.reason == 'coverage'


def test_plan_revision_or_identity_misses():
    first = _request(revision=1, ident=('a',))
    cache = _cache_for(first)
    assert plan_spectrum_display(
        _request(revision=2, ident=('a',)), cache,
    ).reason == 'revision'
    assert plan_spectrum_display(
        _request(revision=1, ident=('b',)), cache,
    ).reason == 'revision'


def test_plan_nan_break_missing_from_cache_misses():
    cached = (_curve(0, 20, True, (5,)),)
    needed = (_curve(0, 20, True, (5, 12)),)
    first = _request(curves=cached)
    cache = _cache_for(first, cover_curves=cached)
    miss = plan_spectrum_display(_request(curves=needed), cache)
    assert miss.reuse is False
    assert miss.reason == 'coverage'


def test_full_coverage_pan_does_not_setdata_after_first_draw(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas)
    qapp.processEvents()
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(-40.0, 540.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls == []


def test_index_stable_pan_without_crossings_skips_setdata(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    freq = np.arange(0.0, 501.0)
    entry = _entry(n=freq.size)
    entry['freq'] = freq
    entry['amp'] = np.ones_like(freq)
    _plot_fft(canvas, entry=entry)
    canvas._plot_amp.setXRange(-10.0, 400.0, padding=0)
    canvas._refresh_spectrum_display()
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(-20.0, 400.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls == []


def test_crossing_only_xlim_keeps_trace_and_updates_raw_y(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    entry = _entry(n=3)
    entry['freq'] = np.array([0.0, 10.0, 20.0])
    entry['amp'] = np.array([0.0, 100.0, 0.0])
    _plot_fft(canvas, entry=entry, xlim=(5.0, 15.0))
    y_before = tuple(canvas._plot_amp.vb.viewRange()[1])
    x_before, _y_before = canvas._amp_curves[0].getData()
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(2.0, 18.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls == []
    x_after, _y_after = canvas._amp_curves[0].getData()
    np.testing.assert_array_equal(np.asarray(x_after), np.asarray(x_before))
    y_after = tuple(canvas._plot_amp.vb.viewRange()[1])
    assert y_after[0] == pytest.approx(16.0)
    assert y_after[1] == pytest.approx(104.0)
    assert y_before != y_after


def test_zoom_in_rebuilds_when_density_is_insufficient(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas, entry=_entry(n=10001, fmax=1000.0), xlim=(0.0, 1000.0))
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(100.0, 200.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls, 'zoom-in must rebuild a denser peak trace'


def test_overscan_hit_inside_buffer_and_rebuild_past_it(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas, entry=_entry(n=10001, fmax=1000.0), xlim=(0.0, 1000.0))
    canvas._plot_amp.setXRange(100.0, 200.0, padding=0)
    canvas._refresh_spectrum_display()
    cache = canvas._spectrum_trace_cache
    assert cache is not None
    assert cache.cover_lo == pytest.approx(50.0)
    assert cache.cover_hi == pytest.approx(250.0)
    assert cache.bucket_width == 800
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(110.0, 210.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls == []
    canvas._plot_amp.setXRange(200.0, 300.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls, 'panning past the overscan buffer must rebuild'


def test_nan_frequency_break_survives_hit_and_rebuild(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    entry = _entry(n=4)
    entry['freq'] = np.array([0.0, np.nan, 10.0, 20.0])
    entry['amp'] = np.array([1.0, 2.0, 3.0, 4.0])
    _plot_fft(canvas, entry=entry, xlim=(0.0, 20.0))

    def _has_nan_break():
        x, y = canvas._amp_curves[0].getData()
        return bool(np.isnan(np.asarray(x)).any() or np.isnan(np.asarray(y)).any())

    assert _has_nan_break()
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(-4.0, 24.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls == []
    assert _has_nan_break()
    canvas._plot_amp.setXRange(0.0, 8.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls, 'zoom-in should rebuild'
    assert _has_nan_break()


def test_full_coverage_pan_keeps_deep_valley_in_auto_y(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    freq = np.linspace(0.0, 500.0, 501)
    amp = np.full_like(freq, -110.0)
    amp[(freq >= 80.0) & (freq <= 220.0)] = -24.0
    amp[np.argmin(np.abs(freq - 140.0))] = -12.0
    entry = _entry()
    entry['freq'] = freq
    entry['amp'] = amp
    _plot_fft(canvas, entry=entry, xlim=(0.0, 300.0), amp_label='Amplitude (dB)')
    _x, (y0, y1) = canvas._plot_amp.vb.viewRange()
    assert y0 == pytest.approx(-114.9)
    assert y1 >= -12.0
    calls = _amp_setdata_log(canvas, monkeypatch)
    canvas._plot_amp.setXRange(-20.0, 320.0, padding=0)
    canvas._refresh_spectrum_display()
    assert calls == []
    _x, (y0, y1) = canvas._plot_amp.vb.viewRange()
    assert y0 == pytest.approx(-114.9)
    assert y1 >= -12.0


def test_resize_home_replot_and_clear_invalidate(
        canvas, qapp, monkeypatch):
    width = [400]
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: width[0])
    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas, entry=_entry(n=10001, fmax=1000.0), xlim=(0.0, 1000.0))
    first_cache = canvas._spectrum_trace_cache
    assert first_cache is not None

    calls = _amp_setdata_log(canvas, monkeypatch)
    width[0] = 1000
    canvas._plot_amp.vb.sigResized.emit(canvas._plot_amp.vb)
    assert calls, 'wider plot rect must rebuild'

    canvas._plot_amp.setXRange(100.0, 200.0, padding=0)
    canvas._refresh_spectrum_display()
    calls.clear()
    canvas.reset_view_to_data_extents()
    assert calls, 'Home must drop the coverage cache and rebuild'

    calls.clear()
    _plot_fft(canvas, entry=_entry(label='next', n=256))
    assert canvas._spectrum_trace_cache is not None
    assert canvas._spectrum_trace_cache.revision != first_cache.revision
    assert calls, 'new plot_spectra must rebuild traces'

    canvas.full_reset()
    assert canvas._spectrum_trace_cache is None
    assert canvas._amp_curves == []


def test_aa_gate_sees_real_post_buffer_drawn_points(
        canvas, qapp, monkeypatch):
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas, entry=_entry(n=10001, fmax=1000.0), xlim=(0.0, 1000.0))
    canvas._plot_amp.setXRange(100.0, 200.0, padding=0)
    canvas._refresh_spectrum_display()
    x, _y = canvas._amp_curves[0].getData()
    total = canvas._spectrum_drawn_point_total()
    assert total == len(x)
    assert total >= 400
