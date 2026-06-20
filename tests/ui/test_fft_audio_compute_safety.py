import numpy as np


def test_fft_canvas_envelopes_large_spectrum_curves_for_responsive_compute(
    qapp, qtbot
):
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    canvas = PgLineCanvas()
    qtbot.addWidget(canvas)

    n_freq = 386_048
    n_time = 772_096
    freq = np.linspace(0.0, 22_050.0, n_freq, dtype=float)
    amp = np.abs(np.sin(np.linspace(0.0, 250.0, n_freq, dtype=float)))
    time = np.linspace(0.0, 17.5, n_time, dtype=float)
    signal = np.sin(np.linspace(0.0, 800.0, n_time, dtype=float))

    canvas.plot_spectra(
        [
            {
                "label": "L",
                "color": "#2563eb",
                "freq": freq,
                "amp": amp,
                "time": time,
                "signal": signal,
            }
        ],
        xlim=(0.0, 22_050.0),
        amp_label="Amplitude",
        title="FFT - L",
    )

    plotted_freq, _plotted_amp = canvas._amp_curves[0].getData()

    assert len(canvas._entries[0]["freq"]) == n_freq
    assert len(plotted_freq) < 20_000
