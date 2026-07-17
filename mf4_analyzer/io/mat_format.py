"""Reader for MATLAB ``.mat`` measurement files.

产出与 wwt/hdf 同形状的 groups。策略通用（不 hardcode 单个文件）：把所有可
ravel 成 1 维的数值变量当候选序列，按名字挑时间轴、按长度分组。v7.3（HDF5）
文件 ``scipy.io.loadmat`` 会抛 ``NotImplementedError``，回退用 h5py 读。
"""
from __future__ import annotations
import re
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

# 时间变量名（去掉矩阵列后缀后按小写匹配）
_TIME_NAMES = {"t", "time", "zeit", "timestamp", "time_s", "time(s)", "t(s)"}
_MIN_LEN = 2


def _detect_version(fp) -> str:
    """best-effort 读 .mat 版本：v4→'v4'、v5→'v5'、v7.3→'v7.3'。私有 API 变动
    时静默降级为空串。"""
    try:
        from scipy.io.matlab._miobase import get_matfile_version
    except Exception:
        return ""
    try:
        with open(fp, "rb") as fh:
            major, _minor = get_matfile_version(fh)
    except Exception:
        return ""
    return {0: "v4", 1: "v5", 2: "v7.3"}.get(major, f"v{major}")


def _as_numeric_1d_candidates(name, arr):
    """把一个变量摊平成候选列 [(colname, 1d array), ...]；非数值/形状不合返回
    ([], is_matrix_split=False)。矩阵 (N,M>1) 按列拆成 ``<var>_c{j}``。"""
    arr = np.asarray(arr)
    if arr.dtype.kind not in "iucfb" or arr.dtype.kind == "c":
        # 整型/浮点/布尔算数值；复数不画，跳过
        return [], False
    arr = arr.astype(np.float64, copy=False)

    if arr.ndim == 1:
        return ([(name, arr)] if arr.size >= _MIN_LEN else []), False
    if arr.ndim == 2:
        r, c = arr.shape
        if min(r, c) == 1 and max(r, c) >= _MIN_LEN:      # 行/列向量
            return [(name, arr.ravel())], False
        if r >= _MIN_LEN and c > 1:                        # 真矩阵，按列拆
            return [(f"{name}_c{j}", arr[:, j]) for j in range(c)], True
    return [], False


def _collect_scipy(raw):
    """从 scipy.loadmat 结果收集候选序列，返回 (series, skipped, lone_matrix)。"""
    series = []
    skipped = []
    matrix_vars = 0
    vector_vars = 0
    for name, val in raw.items():
        if name.startswith("__") and name.endswith("__"):
            continue
        cols, is_matrix = _as_numeric_1d_candidates(name, val)
        if not cols:
            skipped.append(name)
            continue
        series.extend(cols)
        if is_matrix:
            matrix_vars += 1
        else:
            vector_vars += 1
    lone_matrix = matrix_vars == 1 and vector_vars == 0
    return series, skipped, lone_matrix


def _collect_h5py(fp):
    """v7.3（HDF5）回退。遍历数据集，转置 MATLAB 的列主序。"""
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "该 .mat 是 v7.3(HDF5) 格式，需要 h5py 才能读取，请安装 h5py") from exc

    series = []
    skipped = []
    matrix_vars = 0
    vector_vars = 0
    with h5py.File(fp, "r") as hf:
        for name, obj in hf.items():
            if name.startswith("#"):
                continue
            if not isinstance(obj, h5py.Dataset):
                skipped.append(name)
                continue
            data = np.asarray(obj)
            if data.dtype.kind not in "iufb":     # 非数值（含 HDF5 对象引用）
                skipped.append(name)
                continue
            # h5py 读出的是 MATLAB 列主序的转置：(M, N) 对应 MATLAB 的 (N, M)
            if data.ndim == 2:
                data = data.T
            cols, is_matrix = _as_numeric_1d_candidates(name, data)
            if not cols:
                skipped.append(name)
                continue
            series.extend(cols)
            if is_matrix:
                matrix_vars += 1
            else:
                vector_vars += 1
    lone_matrix = matrix_vars == 1 and vector_vars == 0
    return series, skipped, lone_matrix


def _is_monotonic(arr):
    return arr.size >= 2 and np.all(np.diff(arr) > 0)


def load_mat_groups(fp):
    """解析 .mat，返回与 ``DataLoader.load_hdf`` 同形状的 groups 列表。"""
    name = Path(fp).name
    try:
        from scipy.io import loadmat
    except ImportError as exc:
        raise ImportError("需要 scipy 才能读取 .mat 文件，请安装 scipy") from exc

    mat_version = _detect_version(fp)
    try:
        raw = loadmat(fp, squeeze_me=True, struct_as_record=False)
        series, skipped, lone_matrix = _collect_scipy(raw)
    except NotImplementedError:
        # v7.3 HDF5：loadmat 拒读，回退 h5py（h5py 缺失时的 ImportError 直接透传）
        series, skipped, lone_matrix = _collect_h5py(fp)
        mat_version = mat_version or "v7.3"
    except Exception as exc:
        # scipy 对非 .mat 内容会抛各种内部错（ValueError/IndexError 等）→
        # 归一为中文提示（本 try 内不产出自定义异常，广捕安全）
        raise ValueError(
            f"无法读取 .mat 文件（可能不是有效的 MATLAB 文件）: {name}") from exc

    if not series:
        raise ValueError(f"MAT: 未找到任何数值型时序变量: {name}")

    # 时间列识别：按名字（去矩阵列后缀）匹配；否则孤立矩阵首列单调 → 时间
    time_cols = set()
    for col, arr in series:
        base = re.sub(r"_c\d+$", "", col)
        if base.lower() in _TIME_NAMES:
            time_cols.add(col)
    if not time_cols and lone_matrix and _is_monotonic(series[0][1]):
        time_cols.add(series[0][0])

    # 按长度分组（长度相同 → 共享时间轴归一组）
    by_len = OrderedDict()
    for col, arr in series:
        by_len.setdefault(arr.size, []).append((col, arr))

    smeta_base = {
        "source_kind": "mat", "mat_version": mat_version,
        "source_filename": name, "skipped_vars": skipped,
    }

    # 组顺序：通道最多的长度在前（主组），其余按出现顺序
    def _chan_count(length):
        return sum(1 for col, _ in by_len[length] if col not in time_cols)

    lengths = sorted(by_len, key=lambda L: (-_chan_count(L),
                                            list(by_len).index(L)))

    groups = []
    for length in lengths:
        members = by_len[length]
        time_members = [m for m in members if m[0] in time_cols]
        chan_members = [m for m in members if m[0] not in time_cols]
        # 该长度没有可当通道的序列（只有时间轴）→ 不产组
        if not chan_members:
            continue

        frame = {}
        units = {}
        cmeta = {}
        dt = None
        if time_members:
            _tname, tvals = time_members[0]
            tvals = np.asarray(tvals, dtype=np.float64)
            frame["Time"] = tvals
            if tvals.size > 1:
                d = np.median(np.diff(tvals))
                if d > 0:
                    dt = float(d)
            # 多余的时间变量（罕见）降级为普通通道
            chan_members = time_members[1:] + chan_members

        for col, arr in chan_members:
            name_col = col
            if name_col in frame:
                name_col = f"{col} [{length}]"
                while name_col in frame:
                    name_col = f"{name_col}_"
            frame[name_col] = np.asarray(arr, dtype=np.float64)
            units[name_col] = ""     # .mat 通常无单位，不猜
            cmeta[name_col] = {"mat_variable": col, "unit": ""}

        groups.append({
            "data": pd.DataFrame(frame), "channels": list(frame.keys()),
            "units": units, "channel_metadata": cmeta,
            "source_metadata": dict(smeta_base),
            "_length": length, "_dt": dt,
        })

    if not groups:
        raise ValueError(f"MAT: 没有可导入的时序通道: {name}")

    for g in groups:
        length = g.pop("_length")
        dt = g.pop("_dt")
        if len(groups) == 1:
            g["label_suffix"] = ""
        elif dt and dt > 0:
            g["label_suffix"] = f"{1.0 / dt:.0f}Hz·{length}"
        else:
            g["label_suffix"] = f"{length}pts"
    return groups
