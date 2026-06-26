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

from .signal import resolve_nfft
from .signal.fft import FFTAnalyzer


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

    Extension-based dispatch keeps batch parity with the GUI loader.
    Returns FileData. Idx -1 marks "not registered with main_window".
    """
    from mf4_analyzer.io import DataLoader, FileData
    from mf4_analyzer.io.loader import AUDIO_VIDEO_EXTS

    ext = Path(path).suffix.lower()
    if ext in AUDIO_VIDEO_EXTS:
        data, chs, units, fs, smeta = DataLoader.load_audio_video(path)
        return FileData(path, data, chs, units, idx=-1, fs=fs,
                        source_metadata=smeta)
    if ext == '.csv':
        data, chs, units = DataLoader.load_csv(path)
    elif ext in ('.xls', '.xlsx'):
        data, chs, units = DataLoader.load_excel(path)
    else:
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
        prev_disk_key = None  # last disk-path key resident in _disk_cache (for eviction)

        for index, (file_key, signal_name) in enumerate(tasks, start=1):
            # File-major ordering → evict the previous disk file when we move on
            # to a different file key.  This keeps peak _disk_cache resident ≤ 1.
            if prev_disk_key is not None and file_key != prev_disk_key:
                self._disk_cache.pop(prev_disk_key, None)
                prev_disk_key = None

            if cancel_token is not None and cancel_token.is_set():
                cancelled = True
                # Emit task_cancelled for this and all remaining tasks
                for j in range(index, total + 1):
                    key_j, sig_j = tasks[j - 1]
                    if key_j in self.files:
                        fname_j = getattr(self.files[key_j], 'filename', str(key_j))
                    elif key_j in self._disk_cache:
                        cached = self._disk_cache[key_j]
                        fname_j = (cached.path if isinstance(cached, _LoadFailure)
                                   else getattr(cached, 'filename', str(key_j)))
                    else:
                        fname_j = str(key_j)
                    if on_event:
                        on_event(BatchProgressEvent(
                            kind='task_cancelled',
                            task_index=j, total=total,
                            file_name=fname_j, signal=sig_j,
                            method=preset.method,
                        ))
                break

            # Resolve the file (lazy load if disk path, live lookup if registered fid)
            fid, fd_or_fail = self._resolve_task_file(file_key)

            # Track which disk key is currently resident so we can evict later
            if file_key not in self.files:
                prev_disk_key = file_key

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

        # Evict any trailing disk file after the loop completes
        if prev_disk_key is not None:
            self._disk_cache.pop(prev_disk_key, None)

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

    def _resolve_task_file(self, file_key):
        """Resolve a deferred task ``file_key`` to ``(fid, fd_or_failure)``.

        Registered fid → live ``FileData`` directly from ``self.files``.
        Disk path → loaded via ``self._loader``, cached in ``self._disk_cache``
        (value is either ``FileData`` or ``_LoadFailure``).
        """
        fd = self.files.get(file_key)
        if fd is not None:
            return file_key, fd
        if file_key in self._disk_cache:
            return file_key, self._disk_cache[file_key]
        try:
            fd = self._loader(file_key)
        except Exception as exc:  # noqa: BLE001
            fd = _LoadFailure(str(file_key), str(exc))
        self._disk_cache[file_key] = fd
        return file_key, fd

    def _any_target_could_match(self, file_keys, target_signals):
        """Return True if any task in the cartesian product might succeed.

        Already-loaded files are checked against their real columns; disk
        paths (not yet loaded) and unknown keys are assumed possibly-matching
        (verified per-task inside ``run()``).  This preserves the existing
        "all-loaded + none-match → blocked" semantic while avoiding eager loads.
        """
        for key in file_keys:
            fd = self.files.get(key)
            if fd is None:
                # Disk path or unknown — assume it could match; run() verifies.
                return True
            if any(ch in fd.data.columns for ch in target_signals):
                return True
        return False

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
                yield fid, ch
            return
        if preset.target_signals:
            # Lazy path: enumerate the full cartesian product of
            # (file_keys × target_signals) WITHOUT loading any disk files.
            # Disk loading is deferred to run() via _resolve_task_file().
            file_keys = list(preset.file_ids) + list(preset.file_paths)
            if not file_keys:
                # Legacy fallback: use all already-loaded files.
                file_keys = list(self.files.keys())
            if not self._any_target_could_match(file_keys, preset.target_signals):
                return  # all-loaded & none match → run() returns blocked (preserved)
            for key in file_keys:
                for ch in preset.target_signals:
                    yield key, ch
            return
        # Pattern fallback (legacy / test path): eager load to enumerate channels.
        # UI never produces pattern mode (always uses target_signals via free_config).
        files_iter = list(self._resolve_files(preset))
        pattern = preset.signal_pattern.strip()
        for fid, fd in files_iter:
            if isinstance(fd, _LoadFailure):
                continue
            for ch in fd.get_signal_channels():
                if preset.method.startswith('order') and ch == preset.rpm_channel:
                    continue
                if self._matches(ch, pattern):
                    yield fid, ch

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

        spectro = None
        fft_df = None
        if method == 'fft':
            sig, time, _ = self._apply_time_range(sig, time, preset.params)
            fft_df = self._compute_fft_dataframe(sig, fs, preset.params)
            image_payload = ('fft', fft_df)
        elif method == 'fft_time':
            sig, time, _ = self._apply_time_range(sig, time, preset.params)
            spectro = self._compute_fft_time_spectro(
                sig, time, fs, preset.params, channel_name=signal_name,
            )
            image_payload = ('fft_time', spectro)
        else:
            rpm = self._rpm_values(fd, preset)
            sig, time, rpm = self._apply_time_range(sig, time, preset.params, rpm=rpm)
            if method == 'order_time':
                spectro = self._compute_order_time_spectro(sig, rpm, time, fs, preset.params)
                image_payload = ('order_time', spectro)
            else:  # pragma: no cover - guarded by _expand_tasks
                raise ValueError(f"unsupported method: {method}")

        data_path = None
        image_path = None
        if preset.outputs.export_data:
            # Build long-table dataframe only when the caller needs it (export_data=True).
            # Image-only export skips this allocation entirely (lesson 2026-04-26).
            if fft_df is not None:
                export_df = fft_df
            else:
                export_df = spectro.to_long_dataframe()
            data_path = self._write_dataframe(
                export_df, output_dir / f"{stem}.{preset.outputs.data_format}")
        if preset.outputs.export_image:
            image_path = self._write_image(
                image_payload,
                output_dir / f"{stem}.png",
                params=preset.params,
            )

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
    def _suggest_fs_from_time_axis(time, fallback_fs):
        arr = np.asarray(time, dtype=float)
        if arr.size < 2:
            return float(fallback_fs)
        dt = np.diff(arr)
        positive = dt[dt > 0]
        if positive.size == 0:
            return float(fallback_fs)
        median_dt = float(np.median(positive))
        if not np.isfinite(median_dt) or median_dt <= 0:
            return float(fallback_fs)
        return 1.0 / median_dt

    @classmethod
    def _uniform_time_axis_for_spectrogram(cls, time, fs, length):
        """Return a spectrogram-safe time axis and matching Fs.

        Batch FFT-vs-Time mirrors the single-file UX: jittered MF4
        timestamps are rebuilt to ``arange(n) / suggested_fs`` using the
        median-dt estimate instead of failing every task with the raw
        ``non-uniform time axis`` validator error.
        """
        fs = float(fs)
        if time is None:
            return np.arange(int(length), dtype=float) / fs, fs
        time_arr = np.asarray(time, dtype=float)
        if time_arr.size < 2:
            return time_arr, fs

        from .signal.spectrogram import (
            DEFAULT_TIME_JITTER_TOLERANCE,
            SpectrogramAnalyzer,
        )

        try:
            SpectrogramAnalyzer._validate_time_axis(
                time_arr, fs, DEFAULT_TIME_JITTER_TOLERANCE,
            )
            return time_arr, fs
        except ValueError as exc:
            if 'non-uniform time axis' not in str(exc):
                raise

        suggested = cls._suggest_fs_from_time_axis(time_arr, fs)
        if not (np.isfinite(suggested) and suggested > 0):
            suggested = fs
        return np.arange(len(time_arr), dtype=float) / float(suggested), float(suggested)

    @staticmethod
    def _compute_fft_dataframe(sig, fs, params):
        nfft = BatchRunner._resolve_fft_nfft(len(sig), fs, params)
        win = params.get('window', params.get('win', 'hanning'))
        weighting = str(params.get('weighting', 'None'))
        avg_mode = str(params.get('avg_mode', '单帧'))
        avg_overlap = BatchRunner._avg_overlap_fraction(params)
        if avg_mode == '线性平均':
            freq, amp, _psd = FFTAnalyzer.compute_averaged_fft(
                sig, fs, win, int(nfft), avg_overlap, weighting=weighting,
            )
            return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})
        if avg_mode == '峰值保持':
            freq, amp = FFTAnalyzer.compute_peak_hold_fft(
                sig, fs, win=win, nfft=int(nfft), overlap=avg_overlap,
                weighting=weighting,
            )
            return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})
        freq, amp = FFTAnalyzer.compute_fft(
            sig,
            fs,
            win=win,
            nfft=nfft,
            weighting=weighting,
        )
        return pd.DataFrame({'frequency_hz': freq, 'amplitude': amp})

    @staticmethod
    def _avg_overlap_fraction(params):
        try:
            value = float(params.get('avg_overlap', 50))
        except (TypeError, ValueError):
            value = 50.0
        if value > 1.0:
            value /= 100.0
        return max(0.0, min(0.95, value))

    @staticmethod
    def _resolve_fft_nfft(n_samples, fs, params):
        nfft_raw = params.get('nfft')
        avg_mode = str(params.get('avg_mode', '单帧'))
        if isinstance(nfft_raw, str):
            nfft = None if nfft_raw.strip() in ('', '自动', 'auto') else int(nfft_raw)
        elif nfft_raw is None or nfft_raw <= 0:
            nfft = None
        else:
            nfft = int(nfft_raw)
        if nfft is None and avg_mode in {'线性平均', '峰值保持'}:
            t_win_s = float(params.get('t_win_s', 1.5))
            return int(resolve_nfft(
                float(fs), int(n_samples), t_win_s,
                BatchRunner._avg_overlap_fraction(params),
            ))
        return nfft

    @classmethod
    def _compute_order_time_spectro(cls, sig, rpm, time, fs, params) -> "_Spectro2D":
        """Compute time-order spectrogram via COT and return a ``_Spectro2D``.

        ``matrix`` is x-major ``(len(times), len(orders))`` so that
        ``to_long_dataframe()`` round-trips through ``_matrix_to_long_dataframe``
        without any transpose. The transpose needed for ``imshow`` (rows=y) is
        applied in ``_write_image``.
        """
        from .signal.order_cot import COTOrderAnalyzer, COTParams

        # Defensive: COT requires strictly monotonic t. Even microsecond
        # jitter in MF4 timestamps would raise ValueError. If not strict,
        # rebuild a uniform fallback from len + fs.
        time_arr = np.asarray(time, dtype=float)
        if len(time_arr) < 2 or np.any(np.diff(time_arr) <= 0):
            time_arr = np.arange(len(time_arr), dtype=float) / float(fs)

        cot_params = COTParams(
            samples_per_rev=int(params.get('samples_per_rev', 256)),
            nfft=int(params.get('nfft', 1024)),
            window=str(params.get('window', 'hanning')),
            max_order=float(params.get('max_order', params.get('max_ord', 20))),
            order_res=float(params.get('order_res', 0.1)),
            time_res=float(params.get('time_res', 0.05)),
            fs=float(fs),
            weighting=str(params.get('weighting', 'None')),
        )
        result = COTOrderAnalyzer.compute(sig, rpm, time_arr, cot_params)
        return _Spectro2D(
            x=np.asarray(result.times, dtype=float),
            y=np.asarray(result.orders, dtype=float),
            matrix=np.asarray(result.amplitude, dtype=float),
            x_name='time_s',
            y_name='order',
        )

    @classmethod
    def _compute_order_time_dataframe(cls, sig, rpm, time, fs, params):
        """Thin wrapper — delegates to ``_compute_order_time_spectro``.

        As of 2026-04-28 the legacy frequency-domain path
        (``OrderAnalyzer`` time-order result builder) is no longer invoked
        here; COT handles all RPM regimes (sweep, coast-down, steady-state)
        without smearing. ``samples_per_rev`` defaults to 256 when absent from
        preset params; the COT pipeline requires ``time`` to be strictly
        monotonically increasing.
        """
        return cls._compute_order_time_spectro(sig, rpm, time, fs, params).to_long_dataframe()

    @classmethod
    def _compute_fft_time_spectro(cls, sig, time, fs, params, *,
                                  channel_name='') -> "_Spectro2D":
        """Compute one-sided FFT-vs-time spectrogram and return a ``_Spectro2D``.

        ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
        ``(freq_bins, frames)``. ``_Spectro2D.matrix`` is x-major
        ``(len(times), len(frequencies))``, so we store ``amplitude.T``
        (``(frames, freq_bins)``). The exported dataframe stays in linear
        amplitude — the dB conversion is a display-only choice in
        ``_write_image``.
        """
        from .signal.spectrogram import SpectrogramAnalyzer, SpectrogramParams
        time, fs = cls._uniform_time_axis_for_spectrogram(time, fs, len(sig))
        sp = SpectrogramParams(
            fs=float(fs),
            nfft=int(params.get('nfft', 1024)),
            window=str(params.get('window', 'hanning')),
            overlap=float(params.get('overlap', 0.5)),
            remove_mean=bool(params.get('remove_mean', True)),
            weighting=str(params.get('weighting', 'None')),
        )
        result = SpectrogramAnalyzer.compute(
            signal=sig, time=time, params=sp,
            channel_name=channel_name or 'signal',
        )
        return _Spectro2D(
            x=np.asarray(result.times, dtype=float),
            y=np.asarray(result.frequencies, dtype=float),
            matrix=np.asarray(result.amplitude.T, dtype=float),
            x_name='time_s',
            y_name='frequency_hz',
        )

    @classmethod
    def _compute_fft_time_dataframe(cls, sig, time, fs, params, *, channel_name=''):
        """Thin wrapper — delegates to ``_compute_fft_time_spectro``.

        ``SpectrogramAnalyzer.compute`` returns ``amplitude`` with shape
        ``(freq_bins, frames)``. ``_matrix_to_long_dataframe`` requires
        ``matrix.shape == (len(x_values), len(y_values))`` (x-major), so we
        transpose to ``(frames, freq_bins)`` before flattening. The exported
        dataframe stays in linear amplitude — the dB conversion is a
        display-only choice in ``_write_image``.
        """
        return cls._compute_fft_time_spectro(
            sig, time, fs, params, channel_name=channel_name,
        ).to_long_dataframe()

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
    def _ensure_qapp():
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    @staticmethod
    def _extract_matrix(data):
        if isinstance(data, _Spectro2D):
            spectro = data
            matrix = np.asarray(spectro.matrix, dtype=float).T
            return (
                matrix,
                (float(spectro.x.min()), float(spectro.x.max())),
                (float(spectro.y.min()), float(spectro.y.max())),
                spectro.x_name,
                spectro.y_name,
            )

        df = data
        pivot = df.pivot(index=df.columns[1], columns=df.columns[0], values='amplitude')
        return (
            pivot.to_numpy(dtype=float),
            (float(pivot.columns.min()), float(pivot.columns.max())),
            (float(pivot.index.min()), float(pivot.index.max())),
            df.columns[0],
            df.columns[1],
        )

    @staticmethod
    def _build_export_scene(payload, params=None):
        kind, data = payload
        params = params or {}
        x_auto = bool(params.get('x_auto', True))
        x_min = float(params.get('x_min', 0.0))
        x_max = float(params.get('x_max', 0.0))
        y_auto = bool(params.get('y_auto', True))
        y_min = float(params.get('y_min', 0.0))
        y_max = float(params.get('y_max', 0.0))
        z_auto = bool(params.get('z_auto', True))
        z_floor = float(params.get('z_floor', -80.0))
        z_ceiling = float(params.get('z_ceiling', 0.0))
        default_amp_mode = 'amplitude_db' if kind == 'fft_time' else 'amplitude'
        amp_mode = str(params.get('amplitude_mode', default_amp_mode)).lower()
        amp_y = str(params.get('amp_y', '')).lower()
        render_db = 'db' in amp_mode or amp_y == 'db'
        db_reference = float(params.get('db_reference', 1.0) or 1.0)
        if db_reference <= 0:
            db_reference = 1.0

        BatchRunner._ensure_qapp()
        import pyqtgraph as pg
        from PyQt5.QtCore import QRectF

        widget = pg.GraphicsLayoutWidget()
        widget.resize(1120, 630)
        plot = widget.addPlot()
        plot.showGrid(x=True, y=True, alpha=0.25)
        info = {
            "plot_item": plot,
            "image_item": None,
            "levels": None,
            "matrix": None,
            "x_range": None,
            "y_range": None,
            "colorbar_label": None,
            "colormap_name": None,
        }

        if kind == 'fft':
            df = data
            x = df['frequency_hz'].to_numpy()
            y = df['amplitude'].to_numpy()
            if render_db:
                from .signal.spectrogram import SpectrogramAnalyzer as _SA

                y = _SA.amplitude_to_db(y, reference=max(db_reference, 1e-12))
                y_label = 'Amplitude (dB)'
            else:
                y_label = 'Amplitude'
            plot.plot(x, y, pen='w')
            plot.setLabel('bottom', 'Frequency (Hz)')
            plot.setLabel('left', y_label)
            if not x_auto and x_max > x_min:
                plot.setXRange(x_min, x_max, padding=0)
                info["x_range"] = (x_min, x_max)
            if not y_auto and y_max > y_min:
                plot.setYRange(y_min, y_max, padding=0)
                info["y_range"] = (y_min, y_max)
            info["line_y"] = y
            info["y_label"] = y_label
            return widget, info

        matrix, x_extent, y_extent, x_label, y_label = BatchRunner._extract_matrix(data)
        if render_db:
            # Display-only dB choice; exported data stays linear.
            from .signal.spectrogram import SpectrogramAnalyzer as _SA

            matrix = _SA.amplitude_to_db(matrix, reference=max(db_reference, 1e-12))
            cbar_label = 'Amplitude (dB)'
        else:
            cbar_label = 'Amplitude'

        display_levels = _finite_matrix_bounds(matrix)
        levels = None
        if not z_auto:
            levels = (z_floor, z_ceiling)
            display_levels = levels

        image_item = pg.ImageItem()
        image_item.setOpts(axisOrder='row-major')
        image_item.setImage(matrix, autoLevels=False)
        image_item.setRect(QRectF(
            x_extent[0],
            y_extent[0],
            x_extent[1] - x_extent[0],
            y_extent[1] - y_extent[0],
        ))
        colormap = pg.colormap.get("turbo")
        image_item.setColorMap(colormap)
        image_item.setLevels(display_levels)
        plot.addItem(image_item)
        plot.setLabel('bottom', x_label)
        plot.setLabel('left', y_label)
        x_view = x_extent if x_extent[1] > x_extent[0] else (x_extent[0], x_extent[0] + 1.0)
        y_view = y_extent if y_extent[1] > y_extent[0] else (y_extent[0], y_extent[0] + 1.0)
        plot.setXRange(*x_view, padding=0)
        plot.setYRange(*y_view, padding=0)

        colorbar = pg.ColorBarItem(
            values=display_levels,
            colorMap=colormap,
            label=cbar_label,
            interactive=False,
            colorMapMenu=False,
        )
        colorbar.setImageItem(image_item, insert_in=plot)

        if not x_auto and x_max > x_min:
            plot.setXRange(x_min, x_max, padding=0)
            info["x_range"] = (x_min, x_max)
        if not y_auto and y_max > y_min:
            plot.setYRange(y_min, y_max, padding=0)
            info["y_range"] = (y_min, y_max)

        info.update({
            "image_item": image_item,
            "levels": levels,
            "matrix": matrix,
            "colorbar_label": cbar_label,
            "colormap_name": "turbo",
        })
        return widget, info

    @staticmethod
    def _export_png(widget, path):
        path = Path(path)
        BatchRunner._ensure_qapp()
        from PyQt5.QtWidgets import QApplication
        from pyqtgraph.exporters import ImageExporter

        widget.show()
        QApplication.processEvents()
        exporter = ImageExporter(widget.scene())
        exporter.parameters()['width'] = 1120
        exporter.export(str(path))
        widget.close()
        return path

    @staticmethod
    def _write_image(payload, path, params=None):
        widget, _info = BatchRunner._build_export_scene(payload, params)
        return BatchRunner._export_png(widget, path)


def _finite_matrix_bounds(matrix):
    values = np.asarray(matrix, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo = float(finite.min())
    hi = float(finite.max())
    if hi <= lo:
        hi = lo + 1.0
    return (lo, hi)


def _guess_rpm_channel(fd):
    for ch in fd.get_signal_channels():
        low = ch.lower()
        if 'rpm' in low or 'speed' in low or 'tach' in low:
            return ch
    return ''


def _safe_stem(text):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', text).strip('._')
    return cleaned or 'batch_result'


@dataclass(frozen=True)
class _Spectro2D:
    """2-D analysis result kept matrix-first to avoid a long→wide pivot
    round-trip on export. ``matrix`` is x-major: shape (len(x), len(y))."""
    x: np.ndarray
    y: np.ndarray
    matrix: np.ndarray
    x_name: str
    y_name: str

    def to_long_dataframe(self) -> pd.DataFrame:
        return _matrix_to_long_dataframe(
            self.x, self.y, self.matrix, self.x_name, self.y_name)


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
