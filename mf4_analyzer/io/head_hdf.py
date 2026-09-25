"""Parser for HEAD acoustics datafile format v4 (.hdf) time-data files.

Phase-1 time rules (``HEAD_HDF_TIME_RULE_VERSION``):

* ``simultaneous`` and every declared factor is 1: ``dt = delta``,
  ``N = n_scans``. Channel count is not part of ``dt``. Any other factor
  mix is unsupported until an official basis exists.
* ``synchronised multiple``: ``dt = delta * slot_count / factor``,
  ``N = n_scans * factor``. ``slot_count`` includes skipped UINT32 slots.
  This is the existing compatibility rule, not a licence to apply it to
  other scan modes.

Missing header values stay missing. Case and surrounding whitespace may
be normalized; they are never replaced with a guessed default.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

_SIG = b"HEAD acoustics datafile format"
HEAD_HDF_TIME_RULE_VERSION = "head-hdf-time-1"
_HEADER_PROBE = 65536
_MAX_HEADER = 16 * 1024 * 1024
_MAX_TRAILER = 1024 * 1024
_SLOT_BYTES = 4
_TIME_NAMES = frozenset({
    "time", "t", "zeit", "timestamp", "time_s", "time(s)", "t(s)",
})
_APPENDIX = re.compile(br"; xmlAppendix_utf16 (\d+) :")
_RATE_REL_TOL = 1e-8
_AXIS_REL_TOL = 1e-6


def sniff_head_hdf(path) -> bool:
    with open(path, "rb") as fh:
        return _SIG in fh.read(4096)


@dataclass
class HeadChannel:
    name: str
    factor: int
    quantity: str = ""
    unit: str = ""
    calibration: float = 1.0
    db_reference: str = ""
    ext_name: str = ""
    moniker: str = ""
    physical_channel_nbr: int = -1
    impl_type: str = ""
    equalization: str = ""
    emphasis: str = ""
    samples: np.ndarray | None = None
    definition_index: int = 0
    skip_reason: str = ""
    dt: float | None = None
    fs: float | None = None
    t0: float | None = None
    n_samples: int = 0


@dataclass
class HeadHdfFile:
    version: int
    release: str
    byte_order: str
    kind: str
    scan_mode: str
    code_page: str
    start_of_data: int
    n_scans: int
    delta: float
    first_value: float
    recording_date: str
    timezone: str
    channels: list = field(default_factory=list)
    ch_order: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    sampling_rule: str = ""
    rule_version: str = ""
    slot_count: int = 0
    idx_order: str = ""
    data_org: str = ""


@dataclass(frozen=True)
class SavedHdfSamplingDecision:
    """How a saved project rate relates to a reloaded HEAD HDF time base.

    ``apply`` keeps the historical restore path. ``keep-verified`` and
    ``unproven`` leave the file time axis in place. ``manual-kept`` tells
    the caller to restore an explicit user rate without rescaling it.
    """

    action: str
    notice: str = ""


# HEAD 给每个 CAN 导入通道的 ext 名追加的来源标记，形如 ``(CAN.Sig.14)``。
# 它是采集端的槽位编号，不是信号名的一部分——工程师认的是 ``Com_TAS_Torque``。
_EXT_SOURCE_TAG = re.compile(r"\s*\((?:CAN|LIN|FlexRay)\.Sig\.\d+\)\s*$")


def full_channel_name(ch: HeadChannel) -> str:
    """通道的完整名（丢失信息的 ``name str`` 的替代）。

    HEAD 的 ``name str`` 字段硬截断到 16 字符：实测一个真实文件里 19 个 CAN
    通道全部踩线，其中 4 个塌成同一个 ``Com_Motor_Torque``（真名分别以
    ``_DV`` / ``_PV`` / ``_VT`` 结尾或无后缀），2 个塌成 ``Com_RPS_SpeedFil``。
    ``;#ext name str`` 行保留完整名（``Com_Motor_Torque_DV (CAN.Sig.2)``），
    剥掉来源标记后既是全名又天然互不相同。

    没有 ext 行的通道（麦克风、加速度计等非 CAN 通道）退回 ``name str``——
    它们的名字本来就短，没被截断。
    """
    ext = (ch.ext_name or "").strip()
    if not ext:
        return ch.name
    stripped = _EXT_SOURCE_TAG.sub("", ext).strip()
    return stripped or ext


def _kv(line: str):
    """Split 'key: value' (also ';#key: value'); return (key, value) or None."""
    m = re.match(r"^;?#?\s*([^:]+?):\s*(.*)$", line)
    if not m:
        return None
    return m.group(1).strip().lower(), m.group(2).strip()


def _norm(value) -> str | None:
    """Case-fold and collapse whitespace. Blank stays missing, not a default."""
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    return text.casefold()


def _require_text(value, label: str) -> str:
    text = _norm(value)
    if text is None:
        raise NotImplementedError(f"HEAD .hdf 缺少 {label}，不能补默认值")
    return text


def _parse_ch_order(s: str):
    """Parse ``ch order``. A bare token is the file's factor-1 syntax, not a guess."""
    out = []
    seen = set()
    for t in re.split(r"[,\s]+", s.strip()):
        if not t:
            continue
        if t.count("*") > 1:
            raise ValueError(f"HEAD .hdf ch order 项无法解析: {t!r}")
        if "*" in t:
            raw_factor, raw_ch = t.split("*")
            try:
                factor = int(raw_factor)
                channel = int(raw_ch)
            except ValueError as exc:
                raise ValueError(f"HEAD .hdf ch order 项无法解析: {t!r}") from exc
        else:
            try:
                channel = int(t)
            except ValueError as exc:
                raise ValueError(f"HEAD .hdf ch order 项无法解析: {t!r}") from exc
            factor = 1
        if factor < 1 or channel < 1:
            raise ValueError(
                f"HEAD .hdf ch order 需要正整数 factor 与通道号，得到 {t!r}"
            )
        if channel in seen:
            raise NotImplementedError(
                f"HEAD .hdf 重复的 ch order 引用 {channel} 暂不支持"
            )
        seen.add(channel)
        out.append((channel, factor))
    if not out:
        raise ValueError("HEAD .hdf ch order 没有通道引用")
    return out


def _rates_close(left: float, right: float) -> bool:
    if not math.isfinite(left) or not math.isfinite(right):
        return False
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) <= _RATE_REL_TOL * scale


def legacy_simultaneous_dt(delta: float, slot_count: int, factor: int) -> float:
    """Old unconditional formula ``delta * slot_count / factor``.

    It is the known wrong result for ``simultaneous`` files. Sampling axes
    must not be built from it.
    """
    if factor < 1 or slot_count < 1:
        raise ValueError("legacy simultaneous dt 需要正的 factor 与槽数")
    if not math.isfinite(delta) or delta <= 0:
        raise ValueError("legacy simultaneous dt 需要有限正 delta")
    return float(delta) * float(slot_count) / float(factor)


def build_time_axis(t0: float, dt: float, n: int) -> np.ndarray:
    """Return ``t0 + k*dt``. Raise if float64 cannot represent that axis.

    The last step is checked directly. A collapsed spacing is a precision
    error, not something ``median(diff)`` may paper over.
    """
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)):
        raise ValueError(f"样本数不是整数: {n!r}")
    count = int(n)
    if count < 0:
        raise ValueError(f"样本数不能为负: {count}")
    if not math.isfinite(t0):
        raise ValueError("时间起点不是有限值")
    if not math.isfinite(dt) or dt <= 0:
        raise ValueError("采样间隔必须是有限正数")
    if count == 0:
        return np.empty(0, dtype=np.float64)
    if count == 1:
        return np.array([t0], dtype=np.float64)
    axis = np.asarray(t0, dtype=np.float64) + np.arange(count, dtype=np.float64) * dt
    if axis.shape != (count,) or not np.isfinite(axis).all():
        raise ValueError("时间轴含非有限值，无法按声明的 dt 生成")
    diffs = np.diff(axis)
    if not np.isfinite(diffs).all() or np.any(diffs <= 0):
        raise ValueError("float64 无法分辨该时间起点与采样间隔下的相邻样本")
    rel = float(np.max(np.abs(diffs - dt) / dt))
    if rel > _AXIS_REL_TOL:
        raise ValueError("时间轴间隔与声明的 dt 不一致，不能用差分中位数掩盖")
    return axis


def _signal_names(channel_metadata) -> set[str]:
    names: set[str] = set()
    if not isinstance(channel_metadata, Mapping):
        return names
    for name, facts in channel_metadata.items():
        text = str(name).strip()
        if not text or text.casefold() in _TIME_NAMES:
            continue
        if isinstance(facts, Mapping) and (facts.get("injected") or facts.get("derived")):
            continue
        names.add(text)
    return names


def _ordered_names(channel_order: Sequence) -> set[str]:
    names: set[str] = set()
    for name in channel_order or ():
        text = str(name).strip()
        if not text or text.casefold() in _TIME_NAMES:
            continue
        names.add(text)
    return names


def _fingerprint_conflict(stored, current) -> bool:
    if stored in (None, "") or current in (None, ""):
        return False
    return str(stored).strip().lower() != str(current).strip().lower()


def _legacy_simultaneous_rate_matches(
    source_metadata: Mapping,
    channel_metadata,
    saved_fs: float,
    channel_order: Sequence,
    *,
    stored_fingerprint,
    current_fingerprint,
) -> bool:
    if _norm(source_metadata.get("sampling_rule")) != "simultaneous":
        return False
    if _fingerprint_conflict(stored_fingerprint, current_fingerprint):
        return False
    try:
        factor = int(source_metadata.get("factor"))
        slot_count = int(source_metadata.get("slot_count"))
        n_scans = int(source_metadata.get("n_scans"))
        n_samples = int(source_metadata.get("n_samples"))
        delta = float(source_metadata.get("delta"))
        t0 = float(source_metadata.get("t0"))
        dt = float(source_metadata.get("dt"))
    except (TypeError, ValueError):
        return False
    if factor != 1 or slot_count < 2 or n_samples != n_scans or n_scans < 1:
        return False
    if not math.isfinite(t0) or not math.isfinite(delta) or delta <= 0:
        return False
    if not _rates_close(dt, delta):
        return False
    legacy_dt = legacy_simultaneous_dt(delta, slot_count, factor)
    if _rates_close(legacy_dt, dt):
        return False
    if not _rates_close(saved_fs, 1.0 / legacy_dt):
        return False
    live = _signal_names(channel_metadata)
    saved = _ordered_names(channel_order)
    return bool(live) and live == saved


def classify_saved_hdf_sampling(
    source_metadata,
    channel_metadata=None,
    *,
    saved_fs,
    time_source,
    channel_order: Sequence = (),
    stored_fingerprint=None,
    current_fingerprint=None,
) -> SavedHdfSamplingDecision | None:
    """Classify a saved project rate against one reloaded HDF group.

    Returns ``None`` when the source has no verified HDF sampling rule, so
    other formats keep the historical restore path. A match to the known
    simultaneous bug requires the reloaded header, the saved rate, and the
    same signal-name set. Display labels are not consulted. A fingerprint
    is checked only when both sides have one.
    """
    if not isinstance(source_metadata, Mapping) or not source_metadata.get("sampling_rule"):
        return None
    try:
        dt = float(source_metadata.get("dt"))
        saved = float(saved_fs)
    except (TypeError, ValueError):
        return SavedHdfSamplingDecision(
            "unproven",
            "HEAD HDF 工程采样率无法读取。已保留文件时间轴，选区和游标未自动缩放。",
        )
    if not math.isfinite(dt) or dt <= 0 or not math.isfinite(saved) or saved <= 0:
        return SavedHdfSamplingDecision(
            "unproven",
            "HEAD HDF 工程采样率与文件采样间隔无法比较。已保留文件时间轴，未自动缩放。",
        )
    verified = 1.0 / dt
    source = str(time_source or "")
    if source == "manual":
        notice = ""
        if not _rates_close(saved, verified):
            notice = (
                f"HEAD HDF 文件采样率约为 {verified:.6g} Hz。"
                f"已保留手动采样率 {saved:.6g} Hz，未按通道数缩放。"
                "选区、游标和标注未自动缩放，请重新确认。"
            )
        return SavedHdfSamplingDecision("manual-kept", notice)
    if source == "auto":
        if _rates_close(saved, verified):
            return SavedHdfSamplingDecision("apply")
        return SavedHdfSamplingDecision(
            "keep-verified",
            f"HEAD HDF 已保留文件头采样率 {verified:.6g} Hz，未回落到工程里保存的默认采样率。",
        )
    if source != "column":
        return SavedHdfSamplingDecision("apply")
    if _rates_close(saved, verified):
        return SavedHdfSamplingDecision("apply")
    if _legacy_simultaneous_rate_matches(
        source_metadata,
        channel_metadata,
        saved,
        channel_order,
        stored_fingerprint=stored_fingerprint,
        current_fingerprint=current_fingerprint,
    ):
        return SavedHdfSamplingDecision(
            "keep-verified",
            (
                "HEAD HDF 时间基准已按 simultaneous 规则更正"
                f"（采样率由约 {saved:.6g} Hz 改为约 {verified:.6g} Hz）。"
                "选区、游标和标注未自动缩放，请重新确认。工程文件未改写。"
            ),
        )
    return SavedHdfSamplingDecision(
        "unproven",
        (
            f"HEAD HDF 工程采样率约 {saved:.6g} Hz 与文件时间轴约 {verified:.6g} Hz 不一致，"
            "也无法按已知的旧公式确认。已保留文件时间轴，未按通道数缩放，"
            "选区和游标未自动修改。"
        ),
    )


def _recognized_trailer(tail: bytes) -> bool:
    if not tail:
        return True
    match = _APPENDIX.match(tail)
    if match is None:
        return False
    declared = int(match.group(1))
    return declared == len(tail) - match.end()


def _read_bounded_header(path: Path):
    file_size = path.stat().st_size
    with path.open("rb") as handle:
        probe = handle.read(min(file_size, _HEADER_PROBE))
        match = re.search(br"(?m)^start of data:\s*(\d+)", probe)
        if match is None and file_size > len(probe):
            handle.seek(0)
            probe = handle.read(min(file_size, _MAX_HEADER))
            match = re.search(br"(?m)^start of data:\s*(\d+)", probe)
        if match is None:
            raise ValueError("missing 'start of data' header field")
        try:
            start = int(match.group(1))
        except ValueError as exc:
            raise ValueError("start of data 不是整数") from exc
        if start < 0 or start > file_size:
            raise ValueError(
                f"start of data {start} 超出文件范围（文件 {file_size} 字节）"
            )
        if start > _MAX_HEADER:
            raise ValueError(
                f"start of data {start} 超过支持的头部上限 {_MAX_HEADER}"
            )
        if start <= len(probe):
            header = probe[:start]
        else:
            handle.seek(0)
            header = handle.read(start)
            if len(header) != start:
                raise ValueError("HEAD .hdf 头部短于 start of data")
    return header, start, file_size


def _assign_sampling(channels, *, rule: str, delta: float, t0: float, n_scans: int, slot_count: int):
    checked = set()
    for channel in channels:
        factor = channel.factor
        if rule == "simultaneous":
            if factor != 1:
                raise NotImplementedError(
                    "HEAD .hdf simultaneous 目前只支持全部 factor=1，"
                    f"通道 {channel.definition_index} 的 factor={factor}"
                )
            dt = delta
            n_samples = n_scans
        elif rule == "synchronised-multiple":
            dt = delta * slot_count / factor
            n_samples = n_scans * factor
        else:
            raise NotImplementedError(f"unsupported sampling rule: {rule!r}")
        if not math.isfinite(dt) or dt <= 0:
            raise ValueError(f"通道 {channel.definition_index} 的 dt 不是有限正数")
        key = (dt, n_samples)
        if key not in checked:
            build_time_axis(t0, dt, n_samples)
            checked.add(key)
        channel.dt = dt
        channel.fs = 1.0 / dt
        channel.t0 = t0
        channel.n_samples = n_samples


def _demux(path: Path, start: int, nbytes: int, channels, ch_order, n_scans: int, slot_count: int, warnings: list):
    if n_scans == 0 or nbytes == 0:
        for channel in channels:
            if channel.impl_type == "FLOAT32":
                channel.samples = np.empty(0, dtype=np.float64)
            else:
                channel.samples = None
        return
    with path.open("rb") as handle:
        handle.seek(start)
        payload = handle.read(nbytes)
    if len(payload) != nbytes:
        raise ValueError(
            f"HEAD .hdf 数据块被截断：需要 {nbytes} 字节，读到 {len(payload)} 字节"
        )
    matrix = np.frombuffer(payload, dtype="<f4").reshape(n_scans, slot_count)
    offsets = {}
    column = 0
    for channel_index, factor in ch_order:
        offsets[channel_index] = (column, factor)
        column += factor
    by_index = {channel.definition_index: channel for channel in channels}
    for channel_index, factor in ch_order:
        channel = by_index[channel_index]
        start_col, width = offsets[channel_index]
        if channel.impl_type != "FLOAT32":
            channel.samples = None
            channel.skip_reason = f"non-FLOAT32: {channel.impl_type}"
            continue
        block = matrix[:, start_col:start_col + width].astype(np.float64).reshape(-1)
        if block.size != channel.n_samples:
            raise ValueError(
                f"通道 {channel_index} 样本数 {block.size} 与声明的 {channel.n_samples} 不一致"
            )
        channel.samples = block
        if block.size and not np.isfinite(block).all() and not np.isnan(block).all():
            label = full_channel_name(channel) or channel.name or str(channel_index)
            warnings.append(f"通道 {label} 含非有限样本，已原样保留")


def parse_head_hdf(path) -> HeadHdfFile:
    path = Path(path)
    header, start, file_size = _read_bounded_header(path)
    text = header.decode("cp936", errors="replace")
    lines = text.splitlines()

    top = {}
    abscissa = {}
    channels: list[HeadChannel] = []
    by_index: dict[int, HeadChannel] = {}
    cur = None
    section = "top"
    abscissa_count = 0
    for line in lines:
        kv = _kv(line)
        if kv is None:
            continue
        key, val = kv
        if key == "abscissa definition":
            section = "abscissa"
            abscissa_count += 1
            abscissa = {}
            continue
        if key == "channel definition":
            section = "channel"
            try:
                index = int(val)
            except ValueError as exc:
                raise ValueError(f"channel definition 不是整数: {val!r}") from exc
            if index < 1:
                raise ValueError(f"channel definition 超出范围: {index}")
            if index in by_index:
                raise ValueError(f"重复的 channel definition: {index}")
            cur = HeadChannel(name="", factor=0, definition_index=index)
            by_index[index] = cur
            channels.append(cur)
            continue
        if section == "channel" and cur is not None:
            if key == "name str":
                cur.name = val
            elif key == "ext name str":
                cur.ext_name = val
            elif key == "physical quantity":
                cur.quantity = val
            elif key == "physical unit":
                cur.unit = val
            elif key == "calibration":
                cur.calibration = float(val) if val else 1.0
            elif key == "db reference":
                cur.db_reference = val
            elif key == "moniker":
                cur.moniker = val
            elif key == "physical channel nbr":
                cur.physical_channel_nbr = int(val) if val else -1
            elif key == "implementation type":
                cur.impl_type = val.strip()
            elif key == "equalization":
                cur.equalization = val
            elif key == "emphasis":
                cur.emphasis = val
        elif section == "abscissa":
            abscissa[key] = val
        else:
            top[key] = val

    if abscissa_count != 1:
        raise NotImplementedError(
            f"HEAD .hdf 目前只支持单一横轴，得到 {abscissa_count} 个 abscissa definition"
        )
    version_text = _require_text(top.get("version"), "version")
    try:
        version = int(version_text)
    except ValueError as exc:
        raise ValueError(f"HEAD .hdf version 不是整数: {top.get('version')!r}") from exc
    if version != 4:
        raise NotImplementedError(f"unsupported version: {top.get('version')!r}")
    release = _require_text(top.get("release"), "release")
    if release != "6":
        raise NotImplementedError(f"unsupported release: {top.get('release')!r}")
    byte_order = _require_text(top.get("byte order"), "byte order")
    if byte_order != "intel":
        raise NotImplementedError(f"unsupported byte order: {top.get('byte order')!r}")
    kind = _require_text(top.get("kind"), "kind")
    if kind != "time data":
        raise NotImplementedError(f"unsupported kind: {top.get('kind')!r}")
    code_page = _require_text(top.get("code page"), "code page")
    if code_page != "936":
        raise NotImplementedError(f"unsupported code page: {top.get('code page')!r}")
    scan_mode = _require_text(top.get("scan mode"), "scan mode")
    if scan_mode == "simultaneous":
        rule = "simultaneous"
    elif scan_mode == "synchronised multiple":
        rule = "synchronised-multiple"
    else:
        raise NotImplementedError(f"unsupported scan mode: {top.get('scan mode')!r}")
    idx_order = _require_text(top.get("idx order"), "idx order")
    if idx_order != "1":
        raise NotImplementedError(f"unsupported idx order: {top.get('idx order')!r}")
    data_org = _require_text(top.get("data org"), "data org")
    if data_org != "a1b1 a2b2":
        raise NotImplementedError(f"unsupported data org: {top.get('data org')!r}")
    extra_fields = _norm(top.get("nbr of extra fields"))
    if extra_fields not in (None, "0"):
        raise NotImplementedError(
            f"unsupported nbr of extra fields: {top.get('nbr of extra fields')!r}"
        )
    subchannels = _norm(top.get("nbr of subchannel"))
    if subchannels not in (None, "0"):
        raise NotImplementedError(
            f"unsupported nbr of subchannel: {top.get('nbr of subchannel')!r}"
        )
    attributes = _norm(top.get("channel attributes"))
    if attributes not in (None, "private"):
        raise NotImplementedError(
            f"unsupported channel attributes: {top.get('channel attributes')!r}"
        )
    declared_channels = _norm(top.get("nbr of channel"))
    if declared_channels is not None:
        try:
            declared_count = int(declared_channels)
        except ValueError as exc:
            raise ValueError(
                f"nbr of channel 不是整数: {top.get('nbr of channel')!r}"
            ) from exc
        if declared_count != len(channels):
            raise ValueError(
                f"nbr of channel {declared_count} 与 channel definition 数 {len(channels)} 不一致"
            )
    declared_abscissa = _norm(top.get("nbr of abscissa"))
    if declared_abscissa not in (None, "1"):
        raise NotImplementedError(
            f"unsupported nbr of abscissa: {top.get('nbr of abscissa')!r}"
        )

    if _norm(abscissa.get("physical quantity")) != "time":
        raise NotImplementedError(
            f"unsupported abscissa quantity: {abscissa.get('physical quantity')!r}"
        )
    if _norm(abscissa.get("physical unit")) != "s":
        raise NotImplementedError(
            f"unsupported abscissa unit: {abscissa.get('physical unit')!r}"
        )
    if _norm(abscissa.get("absc sort")) != "calc":
        raise NotImplementedError(
            f"unsupported absc sort: {abscissa.get('absc sort')!r}"
        )
    if _norm(abscissa.get("distribution func")) != "linear":
        raise NotImplementedError(
            f"unsupported distribution func: {abscissa.get('distribution func')!r}"
        )
    if _norm(abscissa.get("first value")) is None:
        raise ValueError("HEAD .hdf 缺少 first value，不能把时间起点当成 0")
    if _norm(abscissa.get("delta value")) is None:
        raise ValueError("HEAD .hdf 缺少 delta value")
    if _norm(abscissa.get("nbr of scans")) is None:
        raise ValueError("HEAD .hdf 头部缺失 'nbr of scans' 行")
    try:
        t0 = float(abscissa.get("first value"))
        delta = float(abscissa.get("delta value"))
    except ValueError as exc:
        raise ValueError("HEAD .hdf 横轴 first value / delta value 不是数字") from exc
    if not math.isfinite(t0):
        raise ValueError("HEAD .hdf first value 不是有限值")
    if not math.isfinite(delta) or delta <= 0:
        raise ValueError("HEAD .hdf delta value 必须是有限正数")
    try:
        n_scans = int(str(abscissa.get("nbr of scans")).strip())
    except ValueError as exc:
        raise ValueError(
            f"nbr of scans 不是整数: {abscissa.get('nbr of scans')!r}"
        ) from exc
    if n_scans < 0:
        raise ValueError(f"nbr of scans 不能为负: {n_scans}")

    ch_order_raw = top.get("ch order")
    if _norm(ch_order_raw) is None:
        raise ValueError("HEAD .hdf 头部缺失 'ch order' 行")
    ch_order = _parse_ch_order(str(ch_order_raw))
    defined = set(by_index)
    referenced = {channel_index for channel_index, _factor in ch_order}
    if referenced - defined:
        missing = sorted(referenced - defined)
        raise ValueError(f"HEAD .hdf ch order 引用了未定义通道: {missing}")
    if defined - referenced:
        missing = sorted(defined - referenced)
        raise ValueError(
            "HEAD .hdf ch order 没有覆盖每个数据通道，缺失 factor 不再按 1 估算: "
            f"{missing}"
        )
    for channel_index, factor in ch_order:
        by_index[channel_index].factor = factor

    for channel in channels:
        impl = _norm(channel.impl_type)
        if impl is None:
            raise NotImplementedError(
                f"通道 {channel.definition_index} 缺少 implementation type，不能假定为 FLOAT32"
            )
        if impl == "float32":
            channel.impl_type = "FLOAT32"
        elif impl == "uint32":
            channel.impl_type = "UINT32"
            channel.skip_reason = "non-FLOAT32: UINT32"
        else:
            raise NotImplementedError(
                "HEAD .hdf 有未确认宽度的存储类型，拒绝整段布局: "
                f"通道 {channel.definition_index} implementation type {channel.impl_type!r}"
            )

    slot_count = sum(factor for _channel, factor in ch_order)
    if slot_count < 1:
        raise ValueError("HEAD .hdf 没有数据槽")
    if rule == "simultaneous" and any(factor != 1 for _channel, factor in ch_order):
        raise NotImplementedError(
            "HEAD .hdf simultaneous 目前只支持全部 factor=1；"
            "其他 factor 组合在有官方依据前不生成采样率"
        )
    _assign_sampling(
        channels,
        rule=rule,
        delta=delta,
        t0=t0,
        n_scans=n_scans,
        slot_count=slot_count,
    )

    nbytes = n_scans * slot_count * _SLOT_BYTES
    available = file_size - start
    if available < nbytes:
        raise ValueError(
            f"HEAD .hdf 数据块被截断：需要 {nbytes} 字节，"
            f"start of data 之后只有 {available} 字节"
        )
    trailer_size = available - nbytes
    if trailer_size > _MAX_TRAILER:
        raise NotImplementedError(
            f"HEAD .hdf 有无法解释的尾部数据 {trailer_size} 字节"
        )
    if trailer_size:
        with path.open("rb") as handle:
            handle.seek(start + nbytes)
            trailer = handle.read(trailer_size)
        if not _recognized_trailer(trailer):
            raise NotImplementedError(
                "HEAD .hdf 数据块之后有无法解释的额外数据，不能忽略"
            )

    warnings: list[str] = []
    _demux(path, start, nbytes, channels, ch_order, n_scans, slot_count, warnings)

    return HeadHdfFile(
        version=version,
        release=str(top.get("release", "")).strip(),
        byte_order=str(top.get("byte order", "")).strip(),
        kind=str(top.get("kind", "")).strip(),
        scan_mode=str(top.get("scan mode", "")).strip(),
        code_page=str(top.get("code page", "")).strip(),
        start_of_data=start,
        n_scans=n_scans,
        delta=delta,
        first_value=t0,
        recording_date=top.get("date of recording", ""),
        timezone=top.get("timezone", ""),
        channels=channels,
        ch_order=ch_order,
        warnings=warnings,
        sampling_rule=rule,
        rule_version=HEAD_HDF_TIME_RULE_VERSION,
        slot_count=slot_count,
        idx_order=str(top.get("idx order", "")).strip(),
        data_org=str(top.get("data org", "")).strip(),
    )
