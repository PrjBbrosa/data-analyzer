"""The requested range, not the entire imported source, owns gap validation."""
import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.signal.fft import FFTAnalyzer
from mf4_analyzer.ui.main_window import MainWindow


def test_imported_gap_can_be_avoided_by_gui_time_range(qapp):
    window = MainWindow()
    try:
        time = np.arange(1024) / 1024
        values = np.sin(2 * np.pi * 32 * time)
        values[900] = np.nan
        data = pd.DataFrame({"Time": time, "A": values})
        source = FileData("gap.csv", data, list(data.columns), {})
        window.files[0] = source
        good, fs = window._fft_fetch_signal(0, "A", time_range=(0, .5))
        _freq, amplitude = FFTAnalyzer.compute_fft(good, fs)
        assert np.isfinite(amplitude).all()
        all_samples, fs = window._fft_fetch_signal(0, "A", time_range=None)
        with pytest.raises(ValueError, match="non-finite"):
            FFTAnalyzer.compute_fft(all_samples, fs)
        assert np.isnan(source.data["A"].iloc[900])
        assert len(source.data) == 1024
    finally:
        window.close()
        window.deleteLater()
