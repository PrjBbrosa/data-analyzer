"""PgLineCanvas: dual-row spectrum canvas tests (offscreen)."""
import numpy as np
import pytest

from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


@pytest.fixture
def canvas(qapp):
    c = PgLineCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _entry(label='f1 · vib', color='#2563eb'):
    freq = np.linspace(0, 500, 256)
    amp = np.exp(-((freq - 120) / 15.0) ** 2)
    return {'label': label, 'color': color, 'freq': freq,
            'amp': amp, 'psd': amp ** 2}


def test_plot_spectra_single_entry(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0),
        amp_label='Amplitude', psd_label='PSD (dB)',
        title='FFT - vib', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1
    assert len(canvas._psd_curves) == 1
    xs, ys = canvas._amp_curves[0].getData()
    assert len(xs) == 256
    (x0, x1), _ = canvas._plot_amp.vb.viewRange()
    assert (x0, x1) == (pytest.approx(0.0), pytest.approx(500.0))


def test_plot_spectra_overlay_n(canvas):
    canvas.plot_spectra(
        [_entry('a', '#2563eb'), _entry('b', '#dc2626'), _entry('c', '#16a34a')],
        xlim=(0.0, 500.0), amp_label='Amplitude', psd_label='PSD',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 3
    # replot replaces, never accumulates
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='A', psd_label='P',
        title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    assert len(canvas._amp_curves) == 1


def test_cursor_readout_values(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        psd_label='PSD', title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    rows = canvas.readout_at(120.0)
    assert len(rows) == 1
    label, freq, amp_val = rows[0][:3]
    assert label == 'f1 · vib'
    assert amp_val == pytest.approx(1.0, abs=0.01)


def test_remark_snaps_to_curve(canvas):
    canvas.plot_spectra(
        [_entry()], xlim=(0.0, 500.0), amp_label='Amplitude',
        psd_label='PSD', title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    canvas.set_remark_enabled(True)
    canvas.add_remark_at('amp', 119.0, 0.5)   # off-curve y → snaps to nearest sample
    assert len(canvas._remarks) == 1
    assert '1' in canvas._remarks[0]['label'].toPlainText()  # snapped peak ≈1
    canvas.clear_remarks()
    assert canvas._remarks == []


def test_set_tick_density_accepts_inspector_counts(canvas):
    # Inspector PersistentTop passes integer tick COUNTS (x spinbox
    # 3-30, y spinbox 3-20; defaults 10/8), NOT pg density factors —
    # same contract as PgHeatmapCanvas.set_tick_density (lesson
    # 2026-06-11-inspector-tick-counts-vs-pg-density-factors).
    canvas.set_tick_density(10, 8)
    for plot in (canvas._plot_amp, canvas._plot_psd):
        assert plot.getAxis('bottom')._tickDensity == pytest.approx(10 / 10.0)
        assert plot.getAxis('left')._tickDensity == pytest.approx(8 / 6.0)


def test_set_tick_density_clamps_at_spinbox_maxima(canvas):
    canvas.set_tick_density(30, 20)
    for plot in (canvas._plot_amp, canvas._plot_psd):
        assert plot.getAxis('bottom')._tickDensity == pytest.approx(3.0)
        assert plot.getAxis('left')._tickDensity == pytest.approx(3.0)
