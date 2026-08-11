"""任意来源 → WinWert ``.wwt`` 的产品入口。

两条路，语义相同、代价不同：

``cleanroom``（默认）
    自己写正文（``Zeit`` + N×``Real`` float64）+ 把真实显示尾块的曲线表按目标
    通道重建。**点数原生保留、通道数不限、零量化误差**。依据：用户用 WinWert
    自己把 ``.mat`` 导成 ``.wwt``，其正文正是这个形状，且与 :mod:`wwt_writer`
    的记录头逐字节一致。

``template``
    把序列重采样进真实骨架的测量槽位（:mod:`wwt_inplace`）。受模板槽位数与
    点数约束，量化槽位要重新标定，好处是骨架逐字节来自真机文件。

两条路都强制**时域显示**（每条曲线的 X 引用清 0）并清掉模板继承的页脚文本，
详见 :mod:`wwt_display`。设计与实测台账：
``docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md``。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from ..app_meta import asset_path
from . import wwt_display as _disp
from .wwt_inplace import WwtInplaceError, convert_to_wwt
from .wwt_writer import MIN_TIMESERIES_SAMPLES, infer_zeit_params, write_wwt

_TRAILER_ASSET = ("wwt", "winwert_display_trailer.bin")

MODE_CLEANROOM = "cleanroom"
MODE_TEMPLATE = "template"
_MODES = (MODE_CLEANROOM, MODE_TEMPLATE)


class WwtExportError(ValueError):
    """导出无法完成（时间轴不合法、缺资源、模板装不下等）。"""


@dataclass(frozen=True)
class WwtExportResult:
    """导出结果摘要，供 UI 拼提示语。"""

    path: Path
    mode: str
    channel_count: int
    sample_count: int
    resampled: bool
    quantized: bool

    @property
    def summary(self) -> str:
        bits = [f"{self.channel_count} 通道", f"{self.sample_count} 点"]
        if self.resampled:
            bits.append("已重采样")
        if self.quantized:
            bits.append("量化写入")
        return " · ".join(bits)


def default_display_trailer_path() -> Path:
    """捆绑的真实 WinWert 显示尾块（clean-room 导出用）。"""
    return asset_path(*_TRAILER_ASSET)


def _load_display_trailer(path=None) -> bytes:
    p = Path(path) if path else default_display_trailer_path()
    if not p.is_file():
        raise WwtExportError(
            f"缺少 WinWert 显示尾块资源: {p}。"
            "请确认 assets/wwt/ 已随安装包分发。"
        )
    data = p.read_bytes()
    if not data.startswith(_disp.TRAILER_PREFIX):
        raise WwtExportError(f"显示尾块资源不是 DatenFenste 块: {p}")
    return data


def _as_items(channels) -> list[tuple[str, np.ndarray]]:
    items = list(channels.items()) if hasattr(channels, "items") else list(channels)
    if not items:
        raise WwtExportError("至少需要勾选一条通道才能导出 WWT")
    return [(str(name), np.asarray(values, dtype=np.float64))
            for name, values in items]


def _label(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def _finite_range(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    lo = float(np.min(finite))
    hi = float(np.max(finite))
    return (lo, hi + 1.0) if lo == hi else (lo, hi)


def _ensure_equidistant(
    time: np.ndarray,
    items: list[tuple[str, np.ndarray]],
) -> tuple[np.ndarray, list[tuple[str, np.ndarray]], bool]:
    """Return equidistant ``(t, items, resampled)`` suitable for WWT Zeit.

    WWT stores Zeit as ``t0 + k·dt``. Irregular source axes (common in MF4 /
    event-driven logs) are linearly resampled onto ``linspace(t0, t1, n)``
    while keeping the original sample count, so WinWert still sees a valid
    equidistant file without asking the user to rebuild the time base first.
    """
    t = np.asarray(time, dtype=np.float64)
    if t.ndim != 1 or t.size < 2:
        raise WwtExportError("时间轴至少需要 2 个采样点才能导出 WWT")
    if not np.all(np.isfinite(t)):
        raise WwtExportError("时间轴含有非有限值，无法导出 WWT")
    for name, values in items:
        if values.shape != t.shape:
            raise WwtExportError(
                f"通道 {name!r} 长度 {values.size} 与时间轴 {t.size} 不一致"
            )
    try:
        infer_zeit_params(t)
        return t, items, False
    except ValueError:
        pass

    n = int(t.size)
    order = np.argsort(t, kind="mergesort")
    t_sorted = t[order]
    # Drop exact duplicate timestamps so np.interp stays well-defined.
    uniq = np.concatenate([[True], np.diff(t_sorted) > 0.0])
    t_sorted = t_sorted[uniq]
    if t_sorted.size < 2:
        raise WwtExportError(
            "时间轴有效递增采样不足，无法重采样为等间隔 Zeit"
        )
    t0 = float(t_sorted[0])
    t1 = float(t_sorted[-1])
    if not (t1 > t0):
        raise WwtExportError("时间轴无效，无法重采样为等间隔 Zeit")
    t_eq = np.linspace(t0, t1, n, dtype=np.float64)
    out_items: list[tuple[str, np.ndarray]] = []
    for name, values in items:
        y_sorted = np.asarray(values, dtype=np.float64)[order][uniq]
        out_items.append((name, np.interp(t_eq, t_sorted, y_sorted)))
    return t_eq, out_items, True


def export_cleanroom(
    out_path,
    time: np.ndarray,
    channels: Mapping[str, np.ndarray] | Sequence[tuple[str, np.ndarray]],
    *,
    units: Mapping[str, str] | None = None,
    title: str = "",
    comment: str = "Converted by TraceLab",
    annotations: Sequence[str] | None = (),
    trailer_path=None,
) -> WwtExportResult:
    """自写正文 + 重建显示尾块：原生点数、任意通道数、float64 无量化。

    源时间轴若非等间隔，会自动重采样到等间隔网格（保留点数与起止时刻）。
    """
    items = _as_items(channels)
    units = dict(units or {})
    t, items, resampled = _ensure_equidistant(np.asarray(time, dtype=np.float64), items)
    try:
        t0, _dt, n = infer_zeit_params(t)
    except ValueError as exc:  # 重采样后仍失败才是硬错误
        raise WwtExportError(str(exc)) from exc
    if n < MIN_TIMESERIES_SAMPLES:
        raise WwtExportError(
            f"WWT 需要至少 {MIN_TIMESERIES_SAMPLES} 个采样点（当前 {n}），"
            "更短的块会被当成曲线定义而不是时域测量。"
        )

    spec = [
        (_label(name, units.get(name, "")), *_finite_range(values))
        for name, values in items
    ]
    trailer = _disp.rebuild_display_trailer(
        _load_display_trailer(trailer_path), spec, t0, float(t[-1]),
    )
    # 模板尾块继承的页脚会把别人的台架 / 试验规范 / 操作员印在导出图上。
    trailer = _disp.set_display_text(
        trailer, title=title, comment=comment,
        annotations=annotations, editor="TraceLab",
    )
    path = write_wwt(
        out_path, t, items, units=units, title=title, comment=comment,
        source_filename=Path(out_path).name, trailer=trailer,
    )
    return WwtExportResult(
        path=path, mode=MODE_CLEANROOM, channel_count=len(items),
        sample_count=n, resampled=resampled, quantized=False,
    )


def export_wwt(
    out_path,
    time: np.ndarray,
    channels: Mapping[str, np.ndarray] | Sequence[tuple[str, np.ndarray]],
    *,
    units: Mapping[str, str] | None = None,
    title: str = "",
    comment: str = "Converted by TraceLab",
    mode: str = MODE_CLEANROOM,
    template_path=None,
    trailer_path=None,
    annotations: Sequence[str] | None = (),
) -> WwtExportResult:
    """把时序导出成 WinWert 与 TraceLab 都能打开的 ``.wwt``。

    源时间轴不必事先等间隔：clean-room 路径会自动重采样到等间隔 Zeit。
    """
    if mode not in _MODES:
        raise WwtExportError(f"未知的 WWT 导出模式: {mode!r}（可选 {_MODES}）")
    if mode == MODE_CLEANROOM:
        return export_cleanroom(
            out_path, time, channels, units=units, title=title,
            comment=comment, annotations=annotations, trailer_path=trailer_path,
        )
    try:
        result = convert_to_wwt(
            out_path, time, channels, units=units, title=title,
            comment=comment, template_path=template_path,
        )
    except WwtInplaceError as exc:
        raise WwtExportError(str(exc)) from exc
    return WwtExportResult(
        path=result.path, mode=MODE_TEMPLATE,
        channel_count=result.channel_count, sample_count=result.template_n,
        resampled=result.resampled, quantized=True,
    )
