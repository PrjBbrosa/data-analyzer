"""Shared CSV/Excel/ASCII numeric preparation without implicit data repair."""
from __future__ import annotations

import numpy as np

from .ascii_format import _TIME_NAMES
from .import_diagnostics import make_import_issue, set_import_diagnostics

_SECOND_SCALES = {"s": 1., "sec": 1., "second": 1., "seconds": 1.,
                  "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "μs": 1e-6, "ns": 1e-9}


def prepare_numeric_table(frame, *, source_kind, source_filename, units=None,
                          source_rows=None, sampling_rate=None, generate_time=True,
                          decimal="."):
    """Keep row alignment and signal gaps; require trustworthy timing evidence.

    ``sampling_rate`` is supplied only by explicit user intent or verified
    format metadata. It never replaces an existing (possibly invalid) time
    column. Fixed-width ASCII may keep its original columns and return that
    verified rate separately with ``generate_time=False``.
    """
    import pandas as pd

    if frame.empty:
        raise ValueError("没有可导入的数值通道")
    columns = list(frame.columns)
    time_column = next((col for col in columns
                        if str(col).strip().casefold() in _TIME_NAMES), None)
    def numeric_column(series):
        if series.dtype.kind in {"M", "m", "c"}:
            # Calendar/timedelta storage ticks and complex values are not
            # measured real values. Never strip their semantics by casting.
            return pd.Series(np.nan, index=series.index)
        # pandas leaves an entire decimal-comma column as text when even one
        # sample is invalid. Normalize only strings before numeric conversion.
        if decimal == ",":
            series = series.map(lambda value: value.replace(",", ".") if isinstance(value, str) else value)
        return pd.to_numeric(series, errors="coerce")

    numeric = frame.apply(numeric_column)
    metadata = {"source_kind": source_kind, "source_filename": str(source_filename)}
    issues = []
    units = dict(units or {})
    if time_column is not None:
        time = numeric[time_column].to_numpy(dtype=np.float64)
        raw_unit = str(units.get(time_column, "")).strip()
        if raw_unit:
            unit = raw_unit.strip("[]").casefold()
            if unit not in _SECOND_SCALES:
                raise ValueError(f"时间列 {time_column} 的单位 {raw_unit!r} 不受支持，不能按秒解释")
            scale = _SECOND_SCALES[unit]
            metadata["original_time_unit"] = raw_unit
            units[time_column] = "s"
            if scale != 1.:
                time = time * scale
                numeric[time_column] = time
                issues.append(make_import_issue(
                    "time_unit_converted", f"时间列 {time_column} 已从 {raw_unit} 转换为秒",
                    action="unit_converted", channel=str(time_column), original_unit=raw_unit,
                    output_unit="s", scale=scale,
                ))
        if not np.isfinite(time).all():
            raise ValueError(f"时间列 {time_column} 含缺失或无效数值，无法确定时间轴")
        if time.size > 1 and not np.all(np.diff(time) > 0):
            raise ValueError(f"时间列 {time_column} 必须严格递增，不能自动修复重复或回退时间")
        metadata["time_column"] = str(time_column)
        metadata["time_axis_origin"] = "column"
        # One timestamp cannot establish a sampling interval. Preserve it for
        # viewing; analysis must reject the unknown rate rather than use 1 kHz.
        with np.errstate(over="ignore", divide="ignore"):
            rate = float(1.0 / np.median(np.diff(time))) if time.size > 1 else None
        if rate is not None and (not np.isfinite(rate) or rate <= 0):
            raise ValueError(f"时间列 {time_column} 的采样间隔无法表示")
        metadata["verified_sample_rate"] = rate
    else:
        try:
            rate = float(sampling_rate)
        except (TypeError, ValueError):
            raise ValueError("无法确定时间轴：文件没有时间列或明确的采样率 (sampling rate)") from None
        if not np.isfinite(rate) or rate <= 0:
            raise ValueError("无法确定时间轴：采样率必须是有限正数 (sampling rate)")
        with np.errstate(over="ignore", divide="ignore"):
            last_time = np.float64(len(numeric) - 1) / rate
        if not np.isfinite(last_time):
            raise ValueError("无法确定时间轴：指定采样率生成的时间超出可表示范围")
        metadata["verified_sample_rate"] = rate
        metadata["time_axis_origin"] = "explicit_sampling_rate" if generate_time else "format_sampling_rate"
        if generate_time:
            time_column = "Time"
            numeric.insert(0, time_column, np.arange(len(numeric), dtype=np.float64) / rate)
            metadata["time_column"] = time_column

    rows = list(source_rows) if source_rows is not None else list(range(2, len(frame) + 2))
    if len(rows) != len(frame):
        raise ValueError("表格行号与数据长度不一致，无法可靠导入")
    skipped = []
    kept = []
    for column_index, col in enumerate(columns):
        if col == time_column:
            kept.append(col)
            continue
        values = numeric[col].to_numpy(dtype=np.float64)
        finite = np.isfinite(values)
        count = int(np.count_nonzero(~finite))
        if not finite.any():
            skipped.append({"name": str(col), "reason": "no-finite-samples", "column_index": column_index})
            issues.append(make_import_issue(
                "unusable_channel", f"通道 {col} 无有效数值，已跳过", severity="partial", action="skipped",
                channel=str(col), column_index=column_index, sample_count=int(values.size),
            ))
            continue
        kept.append(col)
        if count:
            indices = np.flatnonzero(~finite)
            issues.append(make_import_issue(
                "nonfinite_samples", f"通道 {col} 含 {count} 个无效样本，已保留缺口", severity="partial",
                action="gap_preserved", channel=str(col), column_index=column_index,
                sample_count=count, source_rows=[int(rows[i]) for i in indices[:20]],
            ))
    signal_count = sum(col != time_column for col in kept)
    if not signal_count:
        raise ValueError("没有可导入的数值通道")
    if time_column is not None and time_column not in kept:
        kept.insert(0, time_column)
    data = numeric.loc[:, kept].copy()
    metadata["skipped_channels"] = skipped
    set_import_diagnostics(
        metadata, issues, imported_channels=signal_count,
        declared_channels=sum(col != time_column for col in columns),
        skipped_channels=len(skipped), sample_count=len(data),
    )
    data.attrs["source_metadata"] = metadata
    kept_units = {col: unit for col, unit in (units or {}).items() if col in kept}
    return data, list(data.columns), kept_units
