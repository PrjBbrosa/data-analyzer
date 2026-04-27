"""Batch analysis presets and GUI-free runner.

Two preset entry points are supported:

* ``from_current_single``: capture the currently selected one-off analysis.
* ``free_config``: describe a reusable rule that selects matching signals.

The runner intentionally depends only on ``FileData`` plus signal modules,
so the PyQt UI can delegate batch work without duplicating numeric logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import numpy as np
import pandas as pd

from .signal.fft import FFTAnalyzer
from .signal.order import OrderAnalysisParams, OrderAnalyzer
from ._chart_kw import CHART_TIGHT_LAYOUT_KW


@dataclass(frozen=True)
class BatchOutput:
    export_data: bool = True
    export_image: bool = True
    data_format: str = 'csv'


@dataclass
class AnalysisPreset:
    name: str
    method: str
    source: str
    params: dict = field(default_factory=dict)
    outputs: BatchOutput = field(default_factory=BatchOutput)
    signal: tuple | None = None
    rpm_signal: tuple | None = None
    signal_pattern: str = ''
    rpm_channel: str = ''

    @classmethod
    def from_current_single(cls, name, method, signal, params=None, outputs=None, rpm_channel='', rpm_signal=None):
        return cls(
            name=str(name or 'current analysis'),
            method=str(method),
            source='current_single',
            signal=tuple(signal) if signal is not None else None,
            rpm_signal=tuple(rpm_signal) if rpm_signal is not None else None,
            rpm_channel=str(rpm_channel or ''),
            params=dict(params or {}),
            outputs=outputs or BatchOutput(),
        )

    @classmethod
    def free_config(cls, name, method, signal_pattern='', rpm_channel='', params=None, outputs=None):
        return cls(
            name=str(name or 'custom batch'),
            method=str(method),
            source='free_config',
            signal_pattern=str(signal_pattern or ''),
            rpm_channel=str(rpm_channel or ''),
            params=dict(params or {}),
            outputs=outputs or BatchOutput(),
        )


@dataclass
class BatchItemResult:
    method: str
    file_id: object
    file_name: str
    signal: str
    status: str
    data_path: str | None = None
    image_path: str | None = None
    message: str = ''


@dataclass
class BatchRunResult:
    status: str
    items: list[BatchItemResult] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)


class BatchRunner:
    SUPPORTED_METHODS = {'fft', 'order_time', 'order_track'}

    def __init__(self, files):
        self.files = files

    def run(self, preset, output_dir, progress_callback=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        items = []
        blocked = []
        tasks = list(self._expand_tasks(preset))
        if not tasks:
            return BatchRunResult(
                status='blocked',
                blocked=['no matching batch tasks'],
            )

        for index, task in enumerate(tasks, start=1):
            fid, fd, signal_name = task
            try:
                item = self._run_one(preset, fid, fd, signal_name, output_dir)
            except Exception as exc:
                item = BatchItemResult(
                    method=preset.method,
                    file_id=fid,
                    file_name=fd.filename,
                    signal=signal_name,
                    status='blocked',
                    message=str(exc),
                )
                blocked.append(f"{fd.filename}:{signal_name}: {exc}")
            items.append(item)
            if progress_callback:
                progress_callback(index, len(tasks))

        if blocked and len(blocked) == len(items):
            status = 'blocked'
        elif blocked:
            status = 'partial'
        else:
            status = 'done'
        return BatchRunResult(status=status, items=items, blocked=blocked)

    def _expand_tasks(self, preset):
        if preset.method not in self.SUPPORTED_METHODS:
            return
        if preset.source == 'current_single':
            if preset.signal is None:
                return
            fid, ch = preset.signal
            fd = self.files.get(fid)
            if fd is not None and ch in fd.data.columns:
                yield fid, fd, ch
            return

        pattern = preset.signal_pattern.strip()
        for fid, fd in self.files.items():
            for ch in fd.get_signal_channels():
                if preset.method.startswith('order') and ch == preset.rpm_channel:
                    continue
                if self._matches(ch, pattern):
                    yield fid, fd, ch

    @staticmethod
    def _matches(channel, pattern):
        """通道名匹配规则：

        - 空 pattern → 匹配所有通道
        - pattern 大小写不敏感地包含在 channel 中（substring） → 匹配
        - 否则按 pattern 当正则解析（IGNORECASE，re.search 半匹配） → 匹配

        **注意：** substring 优先级高于 regex。所以包含正则元字符
        （如 ``motor.speed``）的字面量信号名会先按 substring 匹配；
        若 substring 未命中，``.`` 才被解释为"任意字符"，可能产生
        意料之外的命中（如匹配到 ``motorXspeed``）。需要严格字面量
        匹配的调用方应自行做 `re.escape(pattern)`。
        """
        if not pattern:
            return True
        channel_l = channel.lower()
        pattern_l = pattern.lower()
        if pattern_l in channel_l:
            return True
        try:
            return re.search(pattern, channel, flags=re.IGNORECASE) is not None
        except re.error:
            return False

    def _run_one(self, preset, fid, fd, signal_name, output_dir):
        sig = fd.data[signal_name].to_numpy(dtype=float, copy=False)
        time = fd.time_array
        fs = float(preset.params.get('fs') or fd.fs)
        method = preset.method
        stem = _safe_stem(f"{fd.short_name}_{signal_name}_{method}")

        if method == 'fft':
            sig, time, _ = self._apply_time_range(sig, time, preset.params)
            df = self._compute_fft_dataframe(sig, fs, preset.params)
            image_payload = ('fft', df)
        else:
            rpm = self._rpm_values(fd, preset)
            sig, time, rpm = self._apply_time_range(sig, time, preset.params, rpm=rpm)
            if method == 'order_time':
                df = self._compute_order_time_dataframe(sig, rpm, time, fs, preset.params)
                image_payload = ('order_time', df)
            elif method == 'order_track':
                df = self._compute_order_track_dataframe(sig, rpm, fs, preset.params)
                image_payload = ('order_track', df)
            else:  # pragma: no cover - guarded by _expand_tasks
                raise ValueError(f"unsupported method: {method}")

        data_path = None
        image_path = None
        if preset.outputs.export_data:
            data_path = self._write_dataframe(df, output_dir / f"{stem}.{preset.outputs.data_format}")
        if preset.outputs.export_image:
            image_path = self._write_image(image_payload, output_dir / f"{stem}.png")

        return BatchItemResult(
            method=method,
            file_id=fid,
            file_name=fd.filename,
            signal=signal_name,
            status='done',
            data_path=str(data_path) if data_path else None,
            image_path=str(image_path) if image_path else None,
        )

    @staticmethod
    def _apply_time_range(sig, time, params, rpm=None):
        time_range = params.get('time_range')
        if not time_range or time is None:
            return sig, time, rpm
        lo, hi = time_range
        mask = (time >= float(lo)) & (time <= float(hi))
        sig = sig[mask]
        time = time[mask]
        if rpm is not None:
            rpm = rpm[mask]
        return sig, time, rpm

    @staticmethod
    def _compute_fft_dataframe(sig, fs, params):
        nfft_raw = params.get('nfft')
        if isinstance(nfft_raw, str):
            nfft = None if nfft_raw.strip() in ('', '自动', 'auto') else int(nfft_raw)
        elif nfft_raw is None or nfft_raw <= 0:
            nfft = None
        else:
            nfft = int(nfft_raw)
        freq, amp = FFTAnalyzer.compute_fft(
            sig,
            fs,
            win=params.get('window', params.get('win', 'hanning')),
            nfft=nfft,
        )
        return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})

    @staticmethod
    def _order_params(fs, params):
        return OrderAnalysisParams(
            fs=fs,
            nfft=int(params.get('nfft', 1024)),
            window=params.get('window', 'hanning'),
            max_order=float(params.get('max_order', params.get('max_ord', 20))),
            order_res=float(params.get('order_res', 0.1)),
            time_res=float(params.get('time_res', 0.05)),
            target_order=float(params.get('target_order', params.get('target', 1.0))),
        )

    @classmethod
    def _compute_order_time_dataframe(cls, sig, rpm, time, fs, params):
        result = OrderAnalyzer.compute_time_order_result(
            sig,
            rpm,
            time,
            cls._order_params(fs, params),
        )
        return _matrix_to_long_dataframe(
            result.times,
            result.orders,
            result.amplitude,
            x_name='time_s',
            y_name='order',
        )

    @classmethod
    def _compute_order_track_dataframe(cls, sig, rpm, fs, params):
        result = OrderAnalyzer.extract_order_track_result(
            sig,
            rpm,
            cls._order_params(fs, params),
        )
        return pd.DataFrame({'rpm': result.rpm, 'amplitude': result.amplitude})

    def _rpm_values(self, fd, preset):
        if preset.rpm_signal is not None:
            rpm_fid, rpm_ch = preset.rpm_signal
            rpm_fd = self.files.get(rpm_fid)
            if rpm_fd is None or rpm_ch not in rpm_fd.data.columns:
                raise ValueError("rpm signal is missing for order batch analysis")
            factor = float(preset.params.get('rpm_factor', 1.0))
            rpm = rpm_fd.data[rpm_ch].to_numpy(dtype=float, copy=False) * factor
            if len(rpm) != len(fd.data):
                raise ValueError(f"signal and rpm length mismatch: {len(fd.data)} vs {len(rpm)}")
            return rpm
        rpm_channel = preset.rpm_channel
        if not rpm_channel:
            rpm_channel = _guess_rpm_channel(fd)
        if not rpm_channel or rpm_channel not in fd.data.columns:
            raise ValueError("rpm channel is required for order batch analysis")
        factor = float(preset.params.get('rpm_factor', 1.0))
        return fd.data[rpm_channel].to_numpy(dtype=float, copy=False) * factor

    @staticmethod
    def _write_dataframe(df, path):
        path = Path(path)
        fmt = path.suffix.lower()
        if fmt == '.xlsx':
            df.to_excel(path, index=False, engine='openpyxl')
        else:
            if fmt != '.csv':
                path = path.with_suffix('.csv')
            df.to_csv(path, index=False)
        return path

    @staticmethod
    def _write_image(payload, path):
        kind, df = payload
        from matplotlib.figure import Figure

        fig = Figure(figsize=(8, 4.5), dpi=140)
        try:
            ax = fig.subplots()
            if kind == 'fft':
                ax.plot(df['frequency_hz'], df['amplitude'], lw=1.0)
                ax.set_xlabel('Frequency (Hz)')
                ax.set_ylabel('Amplitude')
            elif kind == 'order_track':
                ax.plot(df['rpm'], df['amplitude'], lw=1.0)
                ax.set_xlabel('RPM')
                ax.set_ylabel('Amplitude')
            else:
                pivot = df.pivot(index=df.columns[1], columns=df.columns[0], values='amplitude')
                im = ax.imshow(
                    pivot.to_numpy(),
                    aspect='auto',
                    origin='lower',
                    extent=[
                        float(pivot.columns.min()),
                        float(pivot.columns.max()),
                        float(pivot.index.min()),
                        float(pivot.index.max()),
                    ],
                    interpolation='bilinear',
                    cmap='turbo',
                )
                ax.set_xlabel(df.columns[0])
                ax.set_ylabel(df.columns[1])
                fig.colorbar(im, ax=ax, label='Amplitude')
            ax.grid(True, alpha=0.25, ls='--')
            fig.tight_layout(**CHART_TIGHT_LAYOUT_KW)
            fig.savefig(path)
        finally:
            fig.clear()
        return path


def _guess_rpm_channel(fd):
    for ch in fd.get_signal_channels():
        low = ch.lower()
        if 'rpm' in low or 'speed' in low or 'tach' in low:
            return ch
    return ''


def _safe_stem(text):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('._')
    return cleaned or 'batch_result'


def _matrix_to_long_dataframe(x_values, y_values, matrix, x_name, y_name):
    x_values = np.asarray(x_values, dtype=float)
    y_values = np.asarray(y_values, dtype=float)
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (len(x_values), len(y_values)):
        raise ValueError(
            f"matrix shape {matrix.shape} does not match "
            f"({len(x_values)}, {len(y_values)})"
        )
    xs = np.repeat(x_values, len(y_values))
    ys = np.tile(y_values, len(x_values))
    return pd.DataFrame({x_name: xs, y_name: ys, 'amplitude': matrix.reshape(-1)})
