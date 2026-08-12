"""WWT 量化标定：物理值 ↔ 整型/浮点存储。

``int1`` / ``Long`` 槽位存的是 raw，物理值 = ``raw × a + c``。导出或模板写入
前按本次数据量程重算 ``(a, c)``，避免沿用模板原标定导致静默截断。
"""
from __future__ import annotations

import numpy as np

from .wwt_format import _TAG_DTYPES


def fit_scale(tag: str, lo: float | None, hi: float | None) -> tuple[float, float]:
    """给量化槽位标定 ``(scale, offset)``，使 ``[lo, hi]`` 铺满存储类型量程。

    浮点标签（``Real`` / ``Floa``）与 ``Zeit`` 返回 ``(1.0, 0.0)``。
    """
    dtype = _TAG_DTYPES.get(tag)
    if dtype is None or dtype.kind == "f":
        return 1.0, 0.0
    limit = 32767.0 if dtype.itemsize == 2 else 2147483647.0
    if lo is None or hi is None or not np.isfinite(lo) or not np.isfinite(hi):
        return 1.0, 0.0
    center = (hi + lo) / 2.0
    half = (hi - lo) / 2.0
    if half <= 0.0:
        return 1.0, center
    # 留一点余量，rint 后不会因为浮点误差顶出量程。
    return half / (limit - 1.0), center


def physical_to_raw(
    values: np.ndarray,
    tag: str,
    *,
    scale: float,
    offset: float,
    n: int | None = None,
) -> bytes:
    """Encode physical samples into the on-disk payload for ``tag``."""
    dtype = _TAG_DTYPES.get(tag)
    if dtype is None:
        raise ValueError(f"标签 {tag!r} 没有可写入的数据区")
    phys = np.asarray(values, dtype=np.float64)
    if n is not None and phys.shape != (n,):
        raise ValueError(f"通道长度 {phys.size} 与预期 {n} 不一致")
    a = 1.0 if scale == 0.0 else float(scale)
    c = float(offset)
    raw = (phys - c) / a
    if dtype == np.dtype("<i2"):
        raw = np.clip(np.rint(raw), -32768, 32767).astype("<i2")
    elif dtype == np.dtype("<i4"):
        raw = np.clip(np.rint(raw), -2147483648, 2147483647).astype("<i4")
    elif dtype == np.dtype("<f4"):
        raw = raw.astype("<f4")
    else:
        raw = raw.astype("<f8")
    return np.ascontiguousarray(raw).tobytes()
