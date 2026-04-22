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

    def get_signal_channels(self):
        return [c for c in self.channels if
                c.lower() not in ('time', 't', 'zeit', 'timestamp', 'time_s', 'time(s)', 't(s)')]

    def get_prefixed_channel(self, ch):
        return f"[{self.short_name}] {ch}"

    def get_color_palette(self):
        return FILE_PALETTES[self.file_index % len(FILE_PALETTES)]
