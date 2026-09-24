"""No-load XLSX size advisory; estimates never gate or alter computation.

Use the full source as a conservative upper estimate when preprocessing
trims/downsamples it. No signal arrays or export tables are materialized.
"""
from dataclasses import dataclass
import math

from .signal.adaptive import canonical_spectrogram_frame_count
from .signal.analysis_defaults import DEFAULT_FFT_TIME_OVERLAP, DEFAULT_ORDER_RES


# An advisory threshold, not an Excel limit or a claimed memory prediction.
# A measured 769,500-cell openpyxl export used ~416 MiB process peak RSS.
XLSX_WARN_CELLS = 500_000


@dataclass(frozen=True)
class TableSize:
    rows: int | None
    cells: int | None


def source_size_facts(fd):
    """Read scalar facts from an already loaded source without copying data."""
    from .io.channel_frame import frame_row_count

    axis = fd.time_array
    return {
        'sample_count': frame_row_count(fd.data),
        'sample_rate': fd.fs,
        'time_start': float(axis[0]) if axis is not None and len(axis) else None,
        'time_end': float(axis[-1]) if axis is not None and len(axis) else None,
    }


def estimate_table_size(method, params, facts):
    """Estimate one task's rows/cells; missing/invalid facts remain unknown.

FFT sizing reuses the compute owner's resolver. Spectrogram sizing reuses
the canonical tail-inclusive frame counter. Order is an upper bound before
RPM-dependent window trimming. Slice estimates include the information sheet.
"""
    try:
        n = int(facts['sample_count'])
        if n < 0:
            return TableSize(None, None)
        if n == 0:
            return TableSize(0, 0)
        if method == 'time':
            filt = params.get('filter') or {}
            series = (int(bool(filt.get('show_original', True)))
                      + int(bool(filt.get('show_filtered', True)))) if filt.get('enabled') else 1
            return TableSize(n * series, n * series * 3)
        if method in {'fft', 'fft_time'}:
            from .batch_compute import resolve_effective_nfft

            fs = float(facts['sample_rate'])
            if not math.isfinite(fs) or fs <= 0:
                return TableSize(None, None)
            nfft = resolve_effective_nfft(method, n, fs, params)
            bins = nfft // 2 + 1
            if method == 'fft':
                return TableSize(bins, bins * 2)
            frames = canonical_spectrogram_frame_count(
                n, nfft, params.get('overlap', DEFAULT_FFT_TIME_OVERLAP),
            )
        elif method == 'order_time':
            duration = float(facts['time_end']) - float(facts['time_start'])
            step = float(params.get('time_res', 0.05))
            resolution = float(params.get('order_res', DEFAULT_ORDER_RES))
            max_order = float(params.get('max_order', params.get('max_ord', 20)))
            if not all(math.isfinite(v) for v in (duration, step, resolution, max_order)):
                return TableSize(None, None)
            if duration < 0 or min(step, resolution, max_order) <= 0:
                return TableSize(None, None)
            frames = math.ceil(duration / step) + 1
            bins = max(0, math.ceil(max_order / resolution - 0.5))
        elif method == 'frf':
            from .batch_compute import FRF_EXPORT_COLUMNS
            from .signal.frf import FrfParams, plan_frf_request

            plan = plan_frf_request(n_samples=n, fs=facts['sample_rate'], params=FrfParams(
                t_win_s=params.get('t_win_s', 2.0),
                overlap=params.get('overlap', 0.5),
                nfft_mode=params.get('nfft_mode', 'auto'),
                nfft=params.get('nfft'),
            ))
            bins = plan.nfft // 2 + 1
            return TableSize(bins, bins * len(FRF_EXPORT_COLUMNS))
        else:
            return TableSize(None, None)
        slice_params = params.get('slice') or {}
        if slice_params.get('enabled'):
            picks = min(4, len(set(slice_params.get('positions') or ())))
            if not picks:
                return TableSize(None, None)
            rows = bins if slice_params.get('axis', 'time') == 'time' else frames
            return TableSize(rows + 40, rows * (picks + 1) + 80)
        return TableSize(frames * bins, frames * bins * 3)
    except (KeyError, TypeError, ValueError, OverflowError):
        # A preflight advisory must not invent missing sampling facts. The
        # existing validator/runner owns invalid parameters and error feedback.
        return TableSize(None, None)


def xlsx_size_warning(sizes):
    sizes = tuple(sizes)
    cells = sum(size.cells or 0 for size in sizes)
    unknown = sum(size.cells is None for size in sizes)
    if cells >= XLSX_WARN_CELLS:
        rows = sum(size.rows or 0 for size in sizes)
        text = (f'XLSX 数据量较大：按完整数据估算合计约 {rows:,} 行 / {cells:,} 个单元格。'
                '写入可能耗时较长、占用较多内存，期间取消可能延迟；建议仅导出图片或减少数据量。')
        if unknown:
            text += f'另有 {unknown} 项无法估算。'
        return text
    if unknown:
        return (f'XLSX 有 {unknown} 项暂无法估算大小；完整时域、时频或阶次数据可能很大。'
                '请确认需要数据文件后再运行。')
    return ''
