"""FFT-vs-Time automatic time-axis recovery regression tests.

The analysis always derives a local uniform axis from valid timestamp data.
No file data or user-selected sampling-rate override is mutated or retained.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# --- Fixture: a duck-typed FileData stand-in that fails the predicate ---


class _NonUniformFakeFD:
    """Duck-typed source with jittered timestamps for local analysis repair."""

    def __init__(self, n: int = 64, nominal_fs: float = 100.0):
        self.fs = float(nominal_fs)
        # Build the same "alternating jitter" axis as the recovery test
        # so the predicate has a real reason to reject.
        nominal_dt = 1.0 / self.fs
        bumps = np.zeros(n, dtype=float)
        bumps[1::2] = 2.4 * nominal_dt
        t_uniform = np.arange(n, dtype=float) / self.fs
        self.time_array = np.cumsum(
            np.concatenate(([0.0], np.diff(t_uniform) + bumps[1:]))
        )
        # Signal: 20 Hz tone sampled on a uniform clock (same model as
        # the recovery fixture -- ADC stable, timestamps jittered).
        sig = np.sin(2.0 * np.pi * 20.0 * (np.arange(n, dtype=float) / self.fs))
        self.data = pd.DataFrame({'ch': sig.astype(float)})
        self.channels = ['ch']
        self.channel_units = {'ch': 'V'}
        self.filename = 'synthetic.mf4'
        self.short_name = 'syn'
        self.file_index = 0
    def get_color_palette(self):
        # MainWindow.activate path may read this; return the same shape
        # FILE_PALETTES entries do (a list of color hex strings).
        return ['#2563eb']


def _wire_fake_file(win, monkeypatch, fake_fd):
    """Inject the fake fd so do_fft_time can resolve a signal without
    having to load a real file (the signal-layer recovery test already
    covers the FileData path; here we exercise the UI plumbing).
    """
    fid = 'fX'
    monkeypatch.setattr(
        win, '_get_fft_time_signal',
        lambda: (
            fid,
            'ch',
            np.asarray(fake_fd.time_array, dtype=float),
            np.asarray(fake_fd.data['ch'].to_numpy(), dtype=float),
            fake_fd,
        ),
    )
    p = dict(
        fid=fid, channel='ch', fs=fake_fd.fs, nfft=8, window='hanning',
        overlap=0.5, remove_mean=True, db_reference=1.0,
        amplitude_mode='amplitude', cmap='turbo', dynamic='80 dB',
        freq_auto=True, freq_min=0.0, freq_max=0.0,
    )
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'get_params',
                        lambda: dict(p, fs=fake_fd.fs))
    monkeypatch.setattr(win.inspector.fft_time_ctx, 'compute_params',
                        lambda: dict(p, fs=fake_fd.fs))
    monkeypatch.setattr(win.inspector.top, 'range_enabled', lambda: False)
    win.files[fid] = fake_fd
    win._active = fid
    return fid, p


def test_full_flow_nonuniform_axis_reconstructs_locally(qtbot, monkeypatch):
    """A non-uniform axis is reconstructed locally and computed."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    _wire_fake_file(win, monkeypatch, fake_fd)


    toasts = []
    monkeypatch.setattr(
        win, 'toast',
        lambda msg, level='info': toasts.append((msg, level)),
    )

    win.do_fft_time(force=False)
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running('fft_time'), timeout=10000
    )

    assert len(win.analysis_caches['fft_time']._store) == 1
    # No error toast (the pre-flight emitted a warning, not an error).
    assert not any(level == 'error' for _msg, level in toasts)


def test_full_flow_no_dispatch_when_signal_already_uniform(qtbot, monkeypatch):
    """A uniform axis dispatches normally and populates the cache."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    # Supply a physically uniform timestamp sequence.
    fake_fd.time_array = np.arange(len(fake_fd.time_array), dtype=float) / fake_fd.fs
    _wire_fake_file(win, monkeypatch, fake_fd)

    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    win.do_fft_time(force=True)
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running('fft_time'), timeout=10000
    )

    # The worker ran and cached the uniform-axis analysis.
    assert len(win.analysis_caches['fft_time']._store) == 1


def test_auto_rebuild_uses_median_time_spacing_without_mutating_source(qtbot, monkeypatch):
    """Automatic recovery uses median spacing without mutating the source."""
    import numpy as np
    from mf4_analyzer.signal import spectrogram as spectrogram_mod
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)

    fake_fd = _NonUniformFakeFD()
    fake_fd.fs = 100.0
    _wire_fake_file(win, monkeypatch, fake_fd)
    good = SpectrogramResult(
        times=np.linspace(0.0, 1.0, 4),
        frequencies=np.linspace(0.0, 50.0, 3),
        amplitude=np.ones((3, 4), dtype=np.float32),
        params=SpectrogramParams(fs=250.0, nfft=8),
        channel_name='ch',
        metadata={'frames': 4, 'hop': 4, 'freq_bins': 3},
    )
    seen = {}

    def fake_compute(signal, time, params, **kw):
        seen['fs'] = params.fs
        seen['dt'] = float(np.median(np.diff(time)))
        return good

    monkeypatch.setattr(
        spectrogram_mod.SpectrogramAnalyzer,
        'compute',
        staticmethod(fake_compute),
    )
    monkeypatch.setattr(win, 'toast', lambda *a, **kw: None)

    win.do_fft_time(force=True)
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running('fft_time'), timeout=10000
    )

    expected_fs = 1.0 / np.median(np.diff(fake_fd.time_array))
    assert fake_fd.fs == 100.0
    assert seen['fs'] == pytest.approx(expected_fs)
    assert seen['dt'] == pytest.approx(1.0 / expected_fs)
