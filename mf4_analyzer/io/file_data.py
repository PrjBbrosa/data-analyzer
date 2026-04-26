"""FileData: per-file in-memory channel container."""
import numpy as np
from pathlib import Path

from .._palette import FILE_PALETTES


class FileData:
    def __init__(self, fp, df, chs, units, idx=0):
        self.filepath = Path(fp)
        self.filename = self.filepath.name
        self.short_name = self.filepath.stem[:18]
        self.data = df
        self.channels = chs
        self.channel_units = units
        self.file_index = idx
        self.time_array = None
        self.fs = 1000.0
        self._time_source = 'auto'  # 'auto', 'column', 'generated'

        # 尝试从列名识别时间列
        for ch in chs:
            if ch.lower() in ('time', 't', 'zeit', 'timestamp', 'time_s', 'time(s)', 't(s)'):
                self.time_array = df[ch].values.astype(float)
                if len(self.time_array) > 1:
                    dt = np.median(np.diff(self.time_array))
                    if dt > 0:
                        self.fs = 1.0 / dt
                        self._time_source = 'column'
                break

        # 如果没有时间列，根据采样率生成
        if self.time_array is None:
            self.time_array = np.arange(len(df), dtype=float) / self.fs
            self._time_source = 'generated'

    def rebuild_time_axis(self, fs):
        """根据新的采样率重建时间轴"""
        self.fs = fs
        n = len(self.data)
        self.time_array = np.arange(n, dtype=float) / fs
        self._time_source = 'manual'

    def is_time_axis_uniform(self, tolerance=None):
        """Pre-flight predicate matching SpectrogramAnalyzer._validate_time_axis.

        Returns ``True`` iff the analyzer's compute step would NOT raise
        ``non-uniform time axis: ...`` for the current ``time_array`` at
        the current ``self.fs``. The decision rule mirrors
        :func:`mf4_analyzer.signal.spectrogram.SpectrogramAnalyzer._validate_time_axis`
        exactly:

          * length < 2  -> ``True`` (degenerate, defer to caller's
            ``len(sig) < 2`` guard).
          * any ``dt <= 0`` -> ``False`` (non-monotonic, the extreme
            non-uniform case).
          * ``max|dt - 1/fs| / (1/fs) > tolerance`` -> ``False``.
          * otherwise ``True`` (the analyzer would accept).

        ``tolerance`` defaults to
        :data:`mf4_analyzer.signal.spectrogram.DEFAULT_TIME_JITTER_TOLERANCE`
        (the analyzer's own kwarg default). Do NOT hardcode a different
        threshold here -- the whole point of this predicate is that the
        UI pre-flight and the worker's validator agree.

        Used by ``MainWindow.do_fft`` and ``MainWindow.do_fft_time`` to
        route non-uniform inputs through ``_show_rebuild_popover``
        BEFORE dispatching the FFT worker, eliminating the
        worker-failed -> popover -> retry round-trip (lesson 2026-04-26
        non-uniform fft pre-flight).
        """
        if tolerance is None:
            # Imported here to avoid a hard dep at import-time / cycle risk.
            from ..signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE
            tolerance = DEFAULT_TIME_JITTER_TOLERANCE
        t = self.time_array
        if t is None:
            return True
        arr = np.asarray(t, dtype=float)
        if arr.ndim != 1 or arr.size < 2:
            return True
        fs = float(self.fs)
        if not np.isfinite(fs) or fs <= 0:
            # No nominal_dt is meaningful; defer rebuild to the caller.
            return False
        nominal_dt = 1.0 / fs
        dt = np.diff(arr)
        if np.any(dt <= 0):
            return False
        relative_jitter = float(np.max(np.abs(dt - nominal_dt)) / nominal_dt)
        return relative_jitter <= float(tolerance)

    def suggested_fs_from_time_axis(self):
        """Best-effort Fs estimate from the existing ``time_array``.

        Returns the median dt's reciprocal when the axis has at least 2
        samples and a positive median dt; otherwise falls back to the
        current ``self.fs``. The caller (rebuild popover) uses this as
        the seed value, so the user only has to confirm rather than
        retype Fs from scratch when the axis is non-uniform but has a
        clear central tendency.

        The median (not mean) is used because non-uniform MF4 timestamp
        streams typically have rare large gaps that would otherwise pull
        a mean estimate off the true sampling rate.
        """
        t = self.time_array
        if t is None:
            return float(self.fs)
        arr = np.asarray(t, dtype=float)
        if arr.size < 2:
            return float(self.fs)
        dt = np.diff(arr)
        # Drop non-positive gaps so a non-monotonic axis still yields a
        # sensible estimate from the well-ordered majority.
        positive = dt[dt > 0]
        if positive.size == 0:
            return float(self.fs)
        median_dt = float(np.median(positive))
        if not np.isfinite(median_dt) or median_dt <= 0:
            return float(self.fs)
        return 1.0 / median_dt

    def get_signal_channels(self):
        return [c for c in self.channels if
                c.lower() not in ('time', 't', 'zeit', 'timestamp', 'time_s', 'time(s)', 't(s)')]

    def get_prefixed_channel(self, ch):
        return f"[{self.short_name}] {ch}"

    def get_color_palette(self):
        return FILE_PALETTES[self.file_index % len(FILE_PALETTES)]
