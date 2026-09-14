"""Retained FFT reveal: real Qt paints, state preservation and cancellation."""
import numpy as np
import pytest
from PyQt5.QtWidgets import QWidget
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


@pytest.fixture
def canvas(qtbot):
    owner = QWidget()
    qtbot.addWidget(owner)
    c = PgLineCanvas(owner)
    c.resize(800, 600)
    owner.resize(820, 620)
    owner.show()
    c.show()
    x = np.linspace(0, 100, 129)
    c.plot_spectra([dict(label='a', fid='f', channel='a', freq=x,
                        amp=np.sin(x) + 2, color='#2563eb')],
                   xlim=(0, 100), amp_label='Amplitude', title='FFT')
    qtbot.waitUntil(lambda: not c._aa_settle_pending())
    yield c


def test_fft_retained_reveal_keeps_curves_ranges_and_history(canvas, qtbot):
    c = canvas
    c._plot_amp.setXRange(20, 70, padding=0)
    c.flush_pending_spectrum_display()
    curves = tuple(c._amp_curves)
    ranges = c.capture_xy_viewport()
    data = c.readout_at(30)
    callbacks = []
    c._replot_callbacks.append(lambda: callbacks.append(True))
    c.hide()
    c.begin_section_reveal()
    assert c.capture_quality_settled() is False
    c.show()
    qtbot.waitUntil(c.capture_quality_settled)
    assert tuple(c._amp_curves) == curves
    assert c.capture_xy_viewport() == ranges
    assert c.readout_at(30) == data
    assert not callbacks
    assert c._aa_idle_timer.interval() == 150


@pytest.mark.parametrize('high_ink', [False, True])
def test_fft_reveal_quality_settles_after_real_paint(canvas, qtbot, monkeypatch, high_ink):
    c = canvas
    monkeypatch.setattr(c, '_spectrum_ink_total', lambda: 1e9 if high_ink else 1.0)
    c.hide()
    c.begin_section_reveal()
    c._enable_idle_quality()
    assert not c._aa_on
    assert not c._discrete_aa_timer.isActive()
    c.show()
    qtbot.waitUntil(c.capture_quality_settled)
    assert c._section_reveal_painted_generation == c._section_reveal_generation
    assert bool(c._amp_curves[0].opts['antialias']) is not high_ink


def test_fft_reveal_cancel_and_replace(canvas):
    c = canvas
    c.begin_section_reveal()
    token = c._section_reveal_paint_token()
    c.hide()
    assert not c._aa_settle_pending()
    c.begin_section_reveal()
    c._section_reveal_painted(token)
    assert c._section_reveal_waiting
    c.full_reset()
    assert not c._section_reveal_waiting
    assert not c._discrete_aa_timer.isActive()


def test_fft_explicit_grab_settles_retained_reveal(canvas):
    c = canvas
    c.begin_section_reveal()
    pixmap = c.grab_pixmap(scale=1)
    assert not pixmap.isNull()
    assert c.capture_quality_settled()
    assert c._section_reveal_painted_generation == c._section_reveal_generation
    assert c._amp_curves[0].opts['antialias']


def test_hide_without_reveal_keeps_existing_idle_lifecycle(canvas):
    c = canvas
    c.disable_interactive_quality()
    c.schedule_idle_quality()
    c.hide()
    assert c._aa_idle_timer.isActive()
    assert not c._section_reveal_waiting
