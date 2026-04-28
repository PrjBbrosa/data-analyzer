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
from typing import Callable, Literal
import re
import threading

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
    # NEW (configuration; free_config only)
    target_signals: tuple = ()
    # NEW (run-time selection; free_config only; injected via dataclasses.replace)
    file_ids: tuple = ()
    file_paths: tuple = ()

    @classmethod
    def from_current_single(cls, name, method, signal, params=None,
                            outputs=None, rpm_channel='', rpm_signal=None,
                            target_signals=None, file_ids=None, file_paths=None):
        if target_signals:
            raise ValueError(
                "target_signals is a free_config-only field; "
                "use AnalysisPreset.free_config instead"
            )
        if file_ids or file_paths:
            raise ValueError(
                "file_ids / file_paths are run-time selection fields; "
                "inject via dataclasses.replace, not from_current_single"
            )
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
    def free_config(cls, name, method, signal_pattern='', rpm_channel='',
                    params=None, outputs=None, target_signals=None,
                    file_ids=None, file_paths=None):
        if file_ids:
            raise ValueError(
                "file_ids is a run-time selection field; "
                "inject via dataclasses.replace after free_config()"
            )
        if file_paths:
            raise ValueError(
                "file_paths is a run-time selection field; "
                "inject via dataclasses.replace after free_config()"
            )
        return cls(
            name=str(name or 'custom batch'),
            method=str(method),
            source='free_config',
            signal_pattern=str(signal_pattern or ''),
            rpm_channel=str(rpm_channel or ''),
            target_signals=tuple(target_signals or ()),
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


@dataclass
class BatchProgressEvent:
    kind: Literal[
        'task_started', 'task_done', 'task_failed',
        'task_cancelled', 'run_finished',
    ]
    task_index: int | None = None
    total: int | None = None
    file_name: str | None = None
    signal: str | None = None
    method: str | None = None
    error: str | None = None        # task_failed only
    final_status: str | None = None  # run_finished only


@dataclass
class _LoadFailure:
    """Sentinel returned by ``BatchRunner._resolve_files`` when a disk path
    cannot be loaded. ``_expand_tasks`` still yields tasks for it; ``run``
    converts each to a ``task_failed`` event with the cached error.
    """
    path: str
    error: str


def _default_loader(path):
    """Default disk loader for ``BatchRunner.file_paths`` resolution.

    Returns FileData. Idx -1 marks "not registered with main_window".
    """
    from mf4_analyzer.io import DataLoader, FileData
    data, chs, units = DataLoader.load_mf4(path)
    return FileData(path, data, chs, units, idx=-1)


class BatchRunner:
    SUPPORTED_METHODS = {'fft', 'order_time', 'fft_time'}

    def __init__(self, files, loader: Callable | None = None):
        self.files = files
        self._loader = loader or _default_loader
        self._disk_cache: dict[str, object] = {}

    def run(self, preset, output_dir,
            progress_callback: Callable[[int, int], None] | None = None,
            *,
            on_event: Callable[[BatchProgressEvent], None] | None = None,
            cancel_token: threading.Event | None = None) -> BatchRunResult:
        output_dir = Path(output_dir)
        # Output-dir create — fail-fast if impossible
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            err = f"cannot create output dir: {exc}"
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished',
                    final_status='blocked',
                ))
            return BatchRunResult(status='blocked', blocked=[err])

        tasks = list(self._expand_tasks(preset))
        if not tasks:
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished', final_status='blocked',
                ))
            return BatchRunResult(
                status='blocked', blocked=['no matching batch tasks'],
            )

        items: list[BatchItemResult] = []
        blocked: list[str] = []
        cancelled = False
        total = len(tasks)

        for index, task in enumerate(tasks, start=1):
            fid, fd_or_fail, signal_name = task
            if cancel_token is not None and cancel_token.is_set():
                cancelled = True
                # Emit task_cancelled for this and all remaining
                for j in range(index, total + 1):
                    fid_j, fd_j, sig_j = tasks[j - 1]
                    fname = (fd_j.path if isinstance(fd_j, _LoadFailure)
                             else getattr(fd_j, 'filename', str(fid_j)))
                    if on_event:
                        on_event(BatchProgressEvent(
                            kind='task_cancelled',
                            task_index=j, total=total,
                            file_name=fname, signal=sig_j,
                            method=preset.method,
                        ))
                break

            # Determine file_name for events (works for _LoadFailure too)
            if isinstance(fd_or_fail, _LoadFailure):
                fname = fd_or_fail.path
            else:
                fname = getattr(fd_or_fail, 'filename', str(fid))

            if on_event:
                on_event(BatchProgressEvent(
                    kind='task_started',
                    task_index=index, total=total,
                    file_name=fname, signal=signal_name, method=preset.method,
                ))
            try:
                if isinstance(fd_or_fail, _LoadFailure):
                    raise IOError(fd_or_fail.error)
                if signal_name not in fd_or_fail.data.columns:
                    raise ValueError(f"missing signal: {signal_name}")
                item = self._run_one(preset, fid, fd_or_fail,
                                     signal_name, output_dir)
                items.append(item)
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_done',
                        task_index=index, total=total,
                        file_name=fname, signal=signal_name,
                        method=preset.method,
                    ))
                # progress_callback fires ONLY on task_done (legacy contract
                # was "called once per completed task"). Failed tasks do NOT
                # bump it — see spec §4.4 / §8.
                if progress_callback:
                    progress_callback(index, total)
            except Exception as exc:
                items.append(BatchItemResult(
                    method=preset.method, file_id=fid,
                    file_name=fname, signal=signal_name,
                    status='blocked', message=str(exc),
                ))
                blocked.append(f"{fname}:{signal_name}: {exc}")
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_failed',
                        task_index=index, total=total,
                        file_name=fname, signal=signal_name,
                        method=preset.method, error=str(exc),
                    ))

        if cancelled:
            status = 'cancelled'
        elif blocked and len(blocked) == len(items):
            status = 'blocked'
        elif blocked:
            status = 'partial'
        else:
            status = 'done'

        if on_event:
            on_event(BatchProgressEvent(
                kind='run_finished', final_status=status,
            ))
        return BatchRunResult(status=status, items=items, blocked=blocked)

    def _resolve_files(self, preset):
        """Yield (fid, FileData) pairs for the preset.

        For free_config: file_ids resolved via self.files; file_paths
        lazy-loaded via self._loader, cached on this BatchRunner instance.
        For current_single: yield (signal[0], self.files[signal[0]]).
        """
        if preset.source == 'current_single':
            if preset.signal is None:
                return
            fid = preset.signal[0]
            fd = self.files.get(fid)
            if fd is not None:
                yield fid, fd
            return
        # free_config
        # Legacy compatibility: when neither file_ids nor file_paths is set
        # (pre-Wave-2 free_config call sites that relied on signal_pattern
        # selecting from all loaded files), fall back to all registered files.
        # New call sites that explicitly inject file_ids / file_paths via
        # dataclasses.replace are unaffected.
        if not preset.file_ids and not preset.file_paths:
            for fid, fd in self.files.items():
                yield fid, fd
            return
        for fid in preset.file_ids:
            fd = self.files.get(fid)
            if fd is not None:
                yield fid, fd
        for path in preset.file_paths:
            if path in self._disk_cache:
                yield path, self._disk_cache[path]
                continue
            try:
                fd = self._loader(path)
            except Exception as exc:
                # signal back via a sentinel that _expand_tasks/run can detect
                fail = _LoadFailure(path, str(exc))
                self._disk_cache[path] = fail
                yield path, fail
                continue
            self._disk_cache[path] = fd
            yield path, fd

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
        files_iter = list(self._resolve_files(preset))
        if preset.target_signals:
            # Phase 1: will phase 2 yield ANY task at all?
            # _LoadFailure entries DO count — phase 2 yields them so run() can
            # surface task_failed rows (per spec §3.2 / §7: disk-load failures
            # become per-task failure, not a blanket blocked status).
            has_any_yield = False
            for fid, fd in files_iter:
                if isinstance(fd, _LoadFailure):
                    has_any_yield = True
                    break
                for ch in preset.target_signals:
                    if ch in fd.data.columns:
                        has_any_yield = True
                        break
                if has_any_yield:
                    break
            if not has_any_yield:
                return  # → run() blocked path (UI rule § 7 normally pre-empts this)
            # Phase 2: yield full cartesian product (load failures and missing
            # signals surface as task_failed via run() try/except).
            for fid, fd in files_iter:
                for ch in preset.target_signals:
                    yield fid, fd, ch
            return
        # Pattern fallback (existing behavior unchanged for tests)
        pattern = preset.signal_pattern.strip()
        for fid, fd in files_iter:
            if isinstance(fd, _LoadFailure):
                continue
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
        elif method == 'fft_time':
            sig, time, _ = self._apply_time_range(sig, time, preset.params)
            df = self._compute_fft_time_dataframe(
                sig, time, fs, preset.params, channel_name=signal_name,
            )
            image_payload = ('fft_time', df)
        else:
            rpm = self._rpm_values(fd, preset)
            sig, time, rpm = self._apply_time_range(sig, time, preset.params, rpm=rpm)
            if method == 'order_time':
                df = self._compute_order_time_dataframe(sig, rpm, time, fs, preset.params)
                image_payload = ('order_time', df)
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
    def _compute_fft_time_dataframe(cls, sig, time, fs, params, *, channel_name=''):
        """Compute one-sided FFT-vs-time spectrogram and emit long format.

        ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
        ``(freq_bins, frames)``. ``_matrix_to_long_dataframe`` requires
        ``matrix.shape == (len(x_values), len(y_values))`` (x-major), so we
        transpose to ``(frames, freq_bins)`` before flattening. The exported
        dataframe stays in linear amplitude — the dB conversion is a
        display-only choice in ``_write_image``.
        """
        from .signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
        sp = SpectrogramParams(
            fs=float(fs),
            nfft=int(params.get('nfft', 1024)),
            window=str(params.get('window', 'hanning')),
            overlap=float(params.get('overlap', 0.5)),
            remove_mean=bool(params.get('remove_mean', True)),
            db_reference=float(params.get('db_reference', 1.0)),
        )
        result = SpectrogramAnalyzer.compute(
            signal=sig, time=time, params=sp,
            channel_name=channel_name or 'signal',
        )
        return _matrix_to_long_dataframe(
            result.times,           # x
            result.frequencies,     # y
            result.amplitude.T,     # (freq_bins, frames) -> (frames, freq_bins)
            x_name='time_s',
            y_name='frequency_hz',
        )

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
            else:
                pivot = df.pivot(
                    index=df.columns[1], columns=df.columns[0], values='amplitude'
                )
                matrix = pivot.to_numpy()
                if kind == 'fft_time':
                    # Render in dB for readability (display-only choice; the
                    # exported CSV/H5 stays linear amplitude). Mirrors
                    # SpectrogramAnalyzer.amplitude_to_db: floor at tiny so
                    # log(0) does not appear.
                    eps = np.finfo(float).tiny
                    matrix = 20.0 * np.log10(np.maximum(matrix, eps))
                    cbar_label = 'Amplitude (dB)'
                else:
                    cbar_label = 'Amplitude'
                im = ax.imshow(
                    matrix,
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
                fig.colorbar(im, ax=ax, label=cbar_label)
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
