"""Neutral analysis-input preparation.

Same-axis data passes through as a local float copy. Native callers do not
rebuild time by sample index. Explicit uniformization computes new values and
new times. Downsampling uses the frozen zero-phase Butterworth design.
Cross-rate FRF alignment is enabled only for a shared origin and an integer
ratio onto the lower rate. Other ratios and fractional delays stay unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np

from .signal.filters import FilterSpec, apply as apply_filter, nyquist_guard
from .signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE

_ANTIALIAS_ORDER = 8
_ANTIALIAS_CUTOFF_RATIO = 0.9
_ANTIALIAS_STOPBAND_DB = 60.0


POLICY_VERSION = "m4-same-axis-1"
DEFAULT_PREPARE_BYTE_LIMIT = 512 * 1024 * 1024
_RPM_UNITS = frozenset({"", "rpm", "r/min", "1/min", "min^-1", "rev/min"})


@dataclass(frozen=True)
class PreparedSignal:
    status: str
    reason: str
    values: np.ndarray | None
    time: np.ndarray | None
    source_id: str
    physical_id: str
    source_revision: str
    segment: str
    input_count: int
    output_count: int
    requested_range: tuple | None
    effective_range: tuple | None
    source_fs: float | None
    target_fs: float | None
    method: str
    quality: str
    boundary: str
    policy_version: str
    provenance: dict
    original_values_hash: str
    original_time_hash: str
    bytes_charged: int


@dataclass(frozen=True)
class PreparedPair:
    status: str
    reason: str
    left: PreparedSignal | None
    right: PreparedSignal | None
    relationship: str
    alignment_facts: dict
    method: str
    policy_version: str
    bytes_charged: int


class PrepareByteLedger:
    """Byte budget for prepared copies. A refused charge does not increase used."""

    def __init__(self, limit: int):
        self.limit = int(limit)
        self.used = 0

    def charge(self, nbytes: int) -> bool:
        nbytes = int(nbytes)
        if nbytes < 0:
            raise ValueError("prepare byte charge must be >= 0")
        if self.used + nbytes > self.limit:
            return False
        self.used += nbytes
        return True


def array_content_hash(values) -> str:
    array = np.asarray(values)
    return hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()


def preflight_prepare(*, sample_count: int, copies: int = 2, dtype_bytes: int = 8, byte_limit: int):
    """Estimate the float copies a prepare would allocate. Does not allocate."""
    estimated = int(sample_count) * int(copies) * int(dtype_bytes)
    return {
        "admitted": estimated <= int(byte_limit),
        "estimated_bytes": estimated,
    }


def batch_stage_facts(*, pair_alignment=None) -> dict:
    """Native anti-alias sits before the user filter. Legacy batch keeps its own path."""
    return {
        "policy_version": POLICY_VERSION,
        "stage_order": [
            "time_range",
            "finite_policy",
            "scale_offset",
            "remove_mean",
            "antialias_downsample",
            "user_filter",
        ],
        "native_antialias": "explicit_uniform_and_aligned_pair",
        "pair_alignment": None if not pair_alignment else dict(pair_alignment),
    }


def prepare_cache_key(prepared: PreparedSignal, algorithm_params) -> str:
    payload = {
        "algorithm": _plain(algorithm_params),
        "boundary": prepared.boundary,
        "effective_range": _plain(prepared.effective_range),
        "input_count": prepared.input_count,
        "method": prepared.method,
        "output_count": prepared.output_count,
        "physical_id": prepared.physical_id,
        "policy_version": prepared.policy_version,
        "quality": prepared.quality,
        "requested_range": _plain(prepared.requested_range),
        "segment": prepared.segment,
        "source_fs": prepared.source_fs,
        "source_id": prepared.source_id,
        "source_revision": prepared.source_revision,
        "status": prepared.status,
        "target_fs": prepared.target_fs,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def prepare_signal(
    values,
    time,
    *,
    fs=None,
    source_id="",
    physical_id="",
    source_revision="",
    segment="",
    policy="native",
    intent="passthrough",
    value_kind="unspecified",
    target_fs=None,
    origin=None,
    requested_range=None,
    gaps=(),
    invalid=None,
    quality_policy="reject",
    byte_limit=None,
) -> PreparedSignal:
    """Prepare one channel. Inputs are hashed and left unchanged."""
    values_arr = np.asarray(values)
    time_arr = np.asarray(time)
    values_hash = array_content_hash(values_arr)
    time_hash = array_content_hash(time_arr)
    common = dict(
        source_id=str(source_id),
        physical_id=str(physical_id),
        source_revision=str(source_revision),
        segment=str(segment),
        original_values_hash=values_hash,
        original_time_hash=time_hash,
    )
    if values_arr.ndim != 1 or time_arr.ndim != 1:
        return _reject("分析输入必须是一维数组", quality="shape", input_count=0, **common)
    if values_arr.shape[0] != time_arr.shape[0]:
        return _reject(
            "分析值和时间长度不一致，不能按较短的一侧截断",
            quality="shape",
            input_count=int(values_arr.shape[0]),
            **common,
        )
    if policy not in {"native", "legacy"}:
        return _reject("未知分析时间政策", quality="policy", input_count=int(values_arr.shape[0]), **common)
    count = int(values_arr.shape[0])
    if byte_limit is not None:
        decision = preflight_prepare(sample_count=count, byte_limit=int(byte_limit))
        if not decision["admitted"]:
            return _reject(
                "准备副本超过字节预算，未分配分析数组",
                quality="byte_limit",
                input_count=count,
                requested_range=_range_of(time_arr),
                **common,
            )

    source_fs = _optional_fs(fs)
    requested = _as_range(requested_range)
    if requested is None and count:
        requested = _range_of(time_arr)
    elif requested is None:
        requested = None

    if count and requested_range is not None:
        lo, hi = requested
        keep = (time_arr >= lo) & (time_arr <= hi)
        values_arr = values_arr[keep]
        time_arr = time_arr[keep]
        if invalid is not None:
            invalid = np.asarray(invalid, dtype=bool)[keep]

    usable = np.ones(values_arr.shape[0], dtype=bool)
    if values_arr.size:
        usable &= np.isfinite(np.asarray(values_arr, dtype=float))
        usable &= np.isfinite(np.asarray(time_arr, dtype=float))
    if invalid is not None:
        invalid_arr = np.asarray(invalid, dtype=bool).reshape(-1)
        if invalid_arr.shape[0] != values_arr.shape[0]:
            return _reject("失效掩码长度必须与样本一致", quality="invalid", input_count=count, requested_range=requested, **common)
        usable &= ~invalid_arr
    if quality_policy == "longest_finite_segment":
        start, stop = _longest_true_run(usable)
        if stop - start < 2:
            return _reject("没有足够长的连续有效段", quality="nonfinite", input_count=count, requested_range=requested, **common)
        values_arr = values_arr[start:stop]
        time_arr = time_arr[start:stop]
    elif not np.all(usable):
        quality = "invalid" if invalid is not None and np.any(np.asarray(invalid, dtype=bool)) else "nonfinite"
        reason = "样本含失效位，默认不跨失效计算" if quality == "invalid" else "样本含非有限值，默认拒绝计算"
        return _reject(reason, quality=quality, input_count=count, requested_range=requested, **common)
    elif values_arr.shape[0] < 2:
        return _reject("至少需要 2 个有效样本", quality="short", input_count=count, requested_range=requested, **common)

    if intent == "reinterpret_fs":
        return _reinterpret(values_arr, time_arr, source_fs, policy, count, requested, common)
    if intent == "explicit_uniform":
        return _explicit_uniform(
            values_arr, time_arr, source_fs, policy, value_kind, target_fs, origin,
            gaps, count, requested, common,
        )
    if intent != "passthrough":
        return _reject("未知准备意图", quality="intent", input_count=count, requested_range=requested, **common)
    return _passthrough(values_arr, time_arr, source_fs, policy, count, requested, common)


def prepare_pair(
    left_values,
    left_time,
    right_values,
    right_time,
    *,
    left_fs,
    right_fs,
    policy="native",
    align_then_compute=False,
    left_identity="",
    right_identity="",
    source_revision="",
    byte_limit=None,
) -> PreparedPair:
    """Pair two original axes. Equal length is not evidence that they match."""
    left_values_arr = np.asarray(left_values)
    right_values_arr = np.asarray(right_values)
    left_time_arr = np.asarray(left_time, dtype=float)
    right_time_arr = np.asarray(right_time, dtype=float)
    facts = {
        "resampled": False,
        "rejected_proof": "equal_length",
        "align_then_compute": bool(align_then_compute),
    }
    same_count = (
        left_values_arr.ndim == 1
        and right_values_arr.ndim == 1
        and left_values_arr.shape[0] == right_values_arr.shape[0]
        and left_time_arr.shape[0] == left_values_arr.shape[0]
        and right_time_arr.shape[0] == right_values_arr.shape[0]
    )
    if not same_count:
        facts["rejected_proof"] = "length_mismatch"
    left_rate = _optional_fs(left_fs)
    right_rate = _optional_fs(right_fs)
    rates_differ = (
        left_rate is None or right_rate is None
        or not math.isclose(left_rate, right_rate, rel_tol=1e-9, abs_tol=0.0)
    )
    if rates_differ or not _clocks_match(left_time_arr, right_time_arr, left_rate):
        if align_then_compute:
            return _align_uniform_pair(
                left_values_arr, left_time_arr, right_values_arr, right_time_arr,
                left_rate, right_rate, facts, source_revision, byte_limit,
                left_identity, right_identity,
            )
        if rates_differ:
            return _pair(
                "unsupported",
                "异轴对齐未验证，不能计算相位",
                "unsupported",
                "unsupported",
                facts,
            )
        return _pair(
            "rejected",
            "两端原始时间未对齐；相同点数不能当作同步",
            "time_relationship_required",
            "time_relationship_required",
            facts,
        )
    left = prepare_signal(
        left_values_arr, left_time_arr, fs=left_rate, policy="native",
        source_id=str(left_identity), source_revision=source_revision,
        byte_limit=byte_limit,
    )
    right = prepare_signal(
        right_values_arr, right_time_arr, fs=right_rate, policy="native",
        source_id=str(right_identity), source_revision=source_revision,
        byte_limit=byte_limit,
    )
    if left.status != "ready" or right.status != "ready":
        reason = left.reason if left.status != "ready" else right.reason
        return _pair("rejected", reason, "time_relationship_required", "rejected", facts)
    if policy == "legacy" and left.method == "legacy_index_rebuild":
        method = "legacy_index_rebuild"
    else:
        method = "same_axis_passthrough"
    facts["rejected_proof"] = ""
    charged = int(left.bytes_charged) + int(right.bytes_charged)
    return PreparedPair(
        status="ready",
        reason="",
        left=left,
        right=right,
        relationship="same_axis",
        alignment_facts=facts,
        method=method,
        policy_version=POLICY_VERSION,
        bytes_charged=charged,
    )


def prepare_order_speed(
    signal_time,
    rpm_values,
    rpm_time,
    *,
    rpm_factor=1.0,
    rpm_unit="",
    signal_unit="",
    rpm_source=None,
    manual_rpm=None,
    require_full_coverage=True,
    policy="native",
) -> PreparedSignal:
    """Align motor speed onto the signal clock without extending past coverage."""
    signal = np.asarray(signal_time, dtype=float).reshape(-1)
    identity = None if rpm_source is None else tuple(rpm_source)
    common = dict(
        source_id="" if identity is None else str(identity[0]),
        physical_id="" if identity is None else str(identity[1]),
        source_revision="",
        segment="",
        original_values_hash="",
        original_time_hash=array_content_hash(signal) if signal.size else "",
    )
    provenance = {
        "rpm_source": identity,
        "rpm_unit": str(rpm_unit or ""),
        "signal_unit": str(signal_unit or ""),
        "bandwidth_claim": False,
        "resamples_values": False,
    }
    if signal.ndim != 1 or signal.size < 2 or not np.all(np.isfinite(signal)):
        return _reject("目标信号时间轴无效", quality="time", input_count=int(signal.size), provenance=provenance, **common)
    if manual_rpm is not None:
        if not _finite_number(manual_rpm):
            return _reject("手动转速必须是有限数值", quality="unit", input_count=int(signal.size), provenance=provenance, **common)
        values = np.full(signal.size, float(manual_rpm), dtype=np.float64)
        return _ready(
            values, np.array(signal, dtype=np.float64, copy=True),
            method="manual_constant",
            source_fs=None,
            target_fs=None,
            input_count=int(signal.size),
            requested_range=_range_of(signal),
            effective_range=_range_of(signal),
            quality="finite",
            provenance=dict(provenance, value_source="explicit_constant", time_source="signal_axis"),
            **common,
        )
    unit = str(rpm_unit or "").strip().casefold()
    if unit not in _RPM_UNITS:
        return _reject(
            "转速单位未验证，不能换算后对齐",
            quality="unit",
            input_count=int(signal.size),
            provenance=provenance,
            **common,
        )
    if not _finite_number(rpm_factor):
        return _reject("转速倍率必须是有限数值", quality="unit", input_count=int(signal.size), provenance=provenance, **common)
    if rpm_values is None or rpm_time is None:
        return _reject("缺少转速通道", quality="missing", input_count=int(signal.size), provenance=provenance, **common)
    rpm = np.asarray(rpm_values, dtype=float).reshape(-1)
    rpm_axis = np.asarray(rpm_time, dtype=float).reshape(-1)
    common["original_values_hash"] = array_content_hash(rpm)
    if rpm.shape[0] != rpm_axis.shape[0] or rpm.size < 2:
        return _reject("转速和时间长度不一致", quality="shape", input_count=int(signal.size), provenance=provenance, **common)
    if not np.all(np.isfinite(rpm)) or not np.all(np.isfinite(rpm_axis)):
        return _reject("转速或时间含非有限值", quality="nonfinite", input_count=int(signal.size), provenance=provenance, **common)
    if np.any(np.diff(rpm_axis) <= 0) or np.any(np.diff(signal) <= 0):
        return _reject("转速对齐要求两端时间严格递增", quality="time", input_count=int(signal.size), provenance=provenance, **common)
    factor = float(rpm_factor)
    scaled = rpm * factor
    same_clock = rpm.size == signal.size and np.allclose(rpm_axis, signal, rtol=0.0, atol=1e-9)
    if same_clock:
        values = np.array(scaled, dtype=np.float64, copy=True)
        return _ready(
            values, np.array(signal, dtype=np.float64, copy=True),
            method="same_axis_passthrough",
            source_fs=None,
            target_fs=None,
            input_count=int(signal.size),
            requested_range=_range_of(signal),
            effective_range=_range_of(signal),
            quality="finite",
            provenance=dict(provenance, value_source="scale", time_source="original_axis", resamples_values=False),
            **common,
        )
    inside = (signal >= rpm_axis[0]) & (signal <= rpm_axis[-1])
    if require_full_coverage and not bool(np.all(inside)):
        return _reject(
            "信号时间超出转速覆盖，不延长端点",
            quality="coverage",
            input_count=int(signal.size),
            requested_range=_range_of(signal),
            provenance=dict(provenance, value_source="not_extended"),
            **common,
        )
    query = signal if require_full_coverage else signal[inside]
    if query.size < 2:
        return _reject("有效覆盖内不足 2 点", quality="coverage", input_count=int(signal.size), provenance=provenance, **common)
    aligned = np.interp(query, rpm_axis, scaled).astype(np.float64, copy=False)
    return _ready(
        aligned, np.array(query, dtype=np.float64, copy=True),
        method="explicit_linear_uniform",
        source_fs=None,
        target_fs=None,
        input_count=int(signal.size),
        requested_range=_range_of(signal),
        effective_range=_range_of(query),
        quality="finite",
        provenance=dict(
            provenance,
            value_source="linear_interpolation",
            time_source="signal_axis",
            resamples_values=True,
            bandwidth_claim=False,
        ),
        **common,
    )


def prepare_read_series(
    series,
    *,
    policy="native",
    intent="passthrough",
    value_kind="unspecified",
    target_fs=None,
    byte_limit=None,
    requested_range=None,
):
    sampling = getattr(series, "sampling", None)
    fs = None
    if getattr(sampling, "status", None) == "known":
        fs = getattr(sampling, "fs_hz", None)
    gaps = _gaps_from_segments(series.time, getattr(series, "segments", ()) or ())
    if policy == "native" and intent == "passthrough" and len(getattr(series, "segments", ()) or ()) > 1:
        return _reject(
            "native 复位或分段时间轴不能按序号合成一根分析轴",
            quality="gap",
            input_count=int(np.asarray(series.values).shape[0]),
            source_id=str(getattr(series, "source_id", "")),
            physical_id=str(getattr(getattr(series, "physical_key", None), "token", "") or ""),
            source_revision=str(getattr(series, "revision", "")),
            original_values_hash=array_content_hash(series.values),
            original_time_hash=array_content_hash(series.time),
        )
    physical = getattr(series, "physical_key", None)
    return prepare_signal(
        series.values,
        series.time,
        fs=fs,
        source_id=str(getattr(series, "source_id", "")),
        physical_id=str(getattr(physical, "token", "") or physical or ""),
        source_revision=str(getattr(series, "revision", "")),
        policy=policy,
        intent=intent,
        value_kind=value_kind,
        target_fs=target_fs,
        requested_range=requested_range,
        gaps=gaps,
        invalid=getattr(series, "validity", None),
        byte_limit=byte_limit,
    )


def load_native_channel(
    file_data,
    channel,
    time_range=None,
    *,
    byte_limit=DEFAULT_PREPARE_BYTE_LIMIT,
    intent="passthrough",
    target_fs=None,
    value_kind="unspecified",
):
    """Read one native channel and prepare it. Does not call index rebuild."""
    if not getattr(file_data, "is_native", False):
        raise ValueError("load_native_channel 只接受 native 来源")
    from .io.signal_access import SignalAccessError, TimeSpan, read_signal

    span = None
    if time_range is not None:
        span = TimeSpan(float(time_range[0]), float(time_range[1]))
    try:
        series = read_signal(file_data, channel, span=span)
    except SignalAccessError as exc:
        return _reject(str(exc), quality="read")
    return prepare_read_series(
        series,
        policy="native",
        intent=intent,
        value_kind=value_kind,
        target_fs=target_fs,
        byte_limit=byte_limit,
        requested_range=time_range,
    )


def _passthrough(values, time, source_fs, policy, input_count, requested, common):
    time_f = np.asarray(time, dtype=np.float64)
    if not np.all(np.isfinite(time_f)) or np.any(np.diff(time_f) <= 0):
        if policy == "legacy":
            return _legacy_rebuild(values, time_f, source_fs, input_count, requested, common)
        return _reject(
            "native 不按序号重建时间轴；不均匀、复位或缺口需要显式生成均匀分析数据",
            quality="time",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    if source_fs is None:
        return _reject(
            "采样率未知，不能把序号间隔当成采样率",
            quality="fs",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    nominal = 1.0 / float(source_fs)
    jitter = float(np.max(np.abs(np.diff(time_f) - nominal)) / nominal)
    if jitter > DEFAULT_TIME_JITTER_TOLERANCE:
        if policy == "legacy":
            return _legacy_rebuild(values, time_f, source_fs, input_count, requested, common)
        return _reject(
            "native 不按序号重建时间轴；不均匀时间需要显式生成均匀分析数据",
            quality="time",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    copied_values = np.array(values, dtype=np.float64, copy=True)
    copied_time = np.array(time_f, dtype=np.float64, copy=True)
    return _ready(
        copied_values,
        copied_time,
        method="same_axis_passthrough",
        source_fs=float(source_fs),
        target_fs=float(source_fs),
        input_count=input_count,
        requested_range=requested,
        effective_range=_range_of(copied_time),
        quality="finite",
        provenance={
            "value_source": "unchanged_samples",
            "time_source": "original_axis",
            "bandwidth_claim": False,
            "resamples_values": False,
            "policy": policy,
        },
        **common,
    )


def _legacy_rebuild(values, time, source_fs, input_count, requested, common):
    if source_fs is None:
        return _reject("旧政策重建仍需要声明采样率", quality="fs", input_count=input_count, requested_range=requested, **common)
    from .analysis_time_axis import prepare_analysis_time_axis

    try:
        rebuilt, rebuilt_fs, facts = prepare_analysis_time_axis(time, float(source_fs))
    except ValueError as exc:
        return _reject(str(exc), quality="time", input_count=input_count, requested_range=requested, **common)
    copied_values = np.array(values, dtype=np.float64, copy=True)
    return _ready(
        copied_values,
        np.array(rebuilt, dtype=np.float64, copy=True),
        method="legacy_index_rebuild",
        source_fs=float(source_fs),
        target_fs=float(rebuilt_fs),
        input_count=input_count,
        requested_range=requested,
        effective_range=_range_of(rebuilt),
        quality="finite",
        provenance={
            "value_source": "unchanged_samples",
            "time_source": "legacy_index_rebuild",
            "bandwidth_claim": False,
            "resamples_values": False,
            "legacy_facts": facts,
            "policy": "legacy",
        },
        **common,
    )


def _reinterpret(values, time, source_fs, policy, input_count, requested, common):
    if policy != "legacy":
        return _reject(
            "指定 Fs 重解释时间只属于旧来源的派生策略，不会覆盖原轴，也不能当成重采样",
            quality="intent",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    if source_fs is None:
        return _reject("重解释需要明确的 Fs", quality="fs", input_count=input_count, requested_range=requested, **common)
    origin = float(np.asarray(time, dtype=float)[0])
    derived = origin + np.arange(values.shape[0], dtype=np.float64) / float(source_fs)
    copied_values = np.array(values, dtype=np.float64, copy=True)
    return _ready(
        copied_values,
        derived,
        method="fs_reinterpret",
        source_fs=float(source_fs),
        target_fs=float(source_fs),
        input_count=input_count,
        requested_range=requested,
        effective_range=_range_of(derived),
        quality="finite",
        provenance={
            "value_source": "unchanged_samples",
            "time_source": "fs_reinterpret",
            "bandwidth_claim": False,
            "resamples_values": False,
            "policy": "legacy",
        },
        **common,
    )


def frozen_antialias_design() -> dict:
    """Zero-phase FFT Butterworth used before a uniform downsample."""
    return {
        "order": _ANTIALIAS_ORDER,
        "cutoff_ratio": _ANTIALIAS_CUTOFF_RATIO,
        "padding": "odd_reflect",
        "delay_compensation": 0,
        "edge_samples": "min(n-1, max(16, n//10))",
        "stopband_db": _ANTIALIAS_STOPBAND_DB,
    }


def frozen_frf_alignment() -> dict:
    """Supported cross-rate FRF alignment. Other combinations stay unsupported."""
    return {
        "origin": "shared_start",
        "ratio": "integer_lower_fs",
        "fractional_delay": "unsupported",
        "edge_policy": "drop_filter_support",
        "min_input_fs_band": (0.05, 0.30),
    }


def _filter_edge_count(count: int) -> int:
    if count < 2:
        return 0
    return min(count - 1, max(16, count // 10))


def _uniform_declared(time, fs: float) -> bool:
    count = int(np.asarray(time).shape[0])
    if count < 2 or not math.isfinite(fs) or fs <= 0:
        return False
    axis = np.asarray(time, dtype=np.float64)
    if not np.all(np.isfinite(axis)) or np.any(np.diff(axis) <= 0):
        return False
    step = 1.0 / float(fs)
    expected = float(axis[0]) + np.arange(count, dtype=np.float64) * step
    magnitude = max(abs(float(axis[0])), abs(float(axis[-1])), abs(step), 1.0)
    tolerance = (8.0 * np.finfo(np.float64).eps * magnitude) + (
        4.0 * count * np.finfo(np.float64).eps * magnitude
    )
    return bool(np.all(np.abs(axis - expected) <= tolerance))


def _downsample_with_antialias(values, time, source_fs, target_fs, origin, input_count, requested, common):
    count = int(time.shape[0])
    edge = _filter_edge_count(count)
    if edge * 2 >= count - 1:
        return _reject(
            "抗混叠边缘支持长度吃掉了有效段",
            quality="edge",
            input_count=input_count,
            requested_range=requested,
            status="unsupported",
            method="unsupported",
            **common,
        )
    cutoff = 0.5 * float(target_fs) * _ANTIALIAS_CUTOFF_RATIO
    spec, _message = nyquist_guard(
        FilterSpec("low", order=_ANTIALIAS_ORDER, cutoff=cutoff), source_fs,
    )
    filtered = apply_filter(np.asarray(values, dtype=np.float64), spec, source_fs)
    interior_t = np.asarray(time[edge:count - edge], dtype=np.float64)
    interior_y = np.asarray(filtered[edge:count - edge], dtype=np.float64)
    grid = _covered_grid(float(origin), float(interior_t[0]), float(interior_t[-1]), target_fs)
    if grid.size < 2:
        return _reject(
            "抗混叠后目标网格不足 2 点",
            quality="coverage",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    output = np.interp(grid, interior_t, interior_y)
    return _ready(
        np.asarray(output, dtype=np.float64),
        grid,
        method="antialiased_downsample",
        source_fs=source_fs,
        target_fs=float(target_fs),
        input_count=input_count,
        requested_range=requested if requested is not None else _range_of(time),
        effective_range=_range_of(grid),
        quality="finite",
        provenance={
            "value_source": "zero_phase_butterworth",
            "time_source": "origin_plus_k_over_fs",
            "bandwidth_claim": True,
            "resamples_values": True,
            "origin": float(grid[0]),
            "antialias": frozen_antialias_design(),
            "delay_compensation": 0,
        },
        **common,
    )


def _align_uniform_pair(
    left_values, left_time, right_values, right_time,
    left_rate, right_rate, facts, source_revision, byte_limit,
    left_identity, right_identity,
):
    del byte_limit
    facts = dict(facts)
    facts["resampled"] = False
    if (
        left_rate is None or right_rate is None
        or not _uniform_declared(left_time, left_rate)
        or not _uniform_declared(right_time, right_rate)
    ):
        return _pair(
            "unsupported",
            "异轴对齐只接受各自均匀且无缺口的连续量",
            "unsupported",
            "unsupported",
            facts,
        )
    origin_scale = max(abs(float(left_time[0])), abs(float(right_time[0])), 1.0)
    if abs(float(left_time[0]) - float(right_time[0])) > 8.0 * np.finfo(np.float64).eps * origin_scale:
        return _pair(
            "unsupported",
            "两端原点不一致，分数延时未验证，不能对齐",
            "unsupported",
            "unsupported",
            facts,
        )
    target = min(float(left_rate), float(right_rate))
    faster = max(float(left_rate), float(right_rate))
    ratio = faster / target
    nearest = int(round(ratio))
    if nearest < 2 or abs(ratio - nearest) > 1e-6:
        return _pair(
            "unsupported",
            "采样率比率不是大于 1 的整数，未验证的对齐不能计算相位",
            "unsupported",
            "unsupported",
            facts,
        )
    if left_rate >= right_rate:
        fast_values, fast_time, fast_fs = left_values, left_time, left_rate
        slow_values, slow_time = right_values, right_time
        fast_is_left = True
    else:
        fast_values, fast_time, fast_fs = right_values, right_time, right_rate
        slow_values, slow_time = left_values, left_time
        fast_is_left = False
    edge = _filter_edge_count(int(fast_time.shape[0]))
    edge_s = edge / float(fast_fs)
    start = max(float(fast_time[0]), float(slow_time[0])) + edge_s
    stop = min(float(fast_time[-1]), float(slow_time[-1])) - edge_s
    if not stop > start:
        return _pair(
            "unsupported",
            "抗混叠边缘支持长度吃掉了有效段",
            "unsupported",
            "unsupported",
            facts,
        )
    slow_axis = np.asarray(slow_time, dtype=np.float64)
    slow_mask = (slow_axis >= start - 1e-12) & (slow_axis <= stop + 1e-12)
    grid = slow_axis[slow_mask]
    slow_out = np.asarray(slow_values, dtype=np.float64)[slow_mask]
    if grid.size < 2:
        return _pair(
            "unsupported",
            "对齐后的共同网格不足 2 点",
            "unsupported",
            "unsupported",
            facts,
        )
    cutoff = 0.5 * target * _ANTIALIAS_CUTOFF_RATIO
    spec, _message = nyquist_guard(
        FilterSpec("low", order=_ANTIALIAS_ORDER, cutoff=cutoff), fast_fs,
    )
    filtered = apply_filter(np.asarray(fast_values, dtype=np.float64), spec, fast_fs)
    fast_out = np.interp(grid, np.asarray(fast_time, dtype=np.float64), filtered)
    left_out, right_out = (fast_out, slow_out) if fast_is_left else (slow_out, fast_out)
    left_fs_out = target
    common_left = dict(
        source_id=str(left_identity), physical_id="", source_revision=str(source_revision),
        segment="", original_values_hash=array_content_hash(np.asarray(left_values)),
        original_time_hash=array_content_hash(np.asarray(left_time)),
    )
    common_right = dict(
        source_id=str(right_identity), physical_id="", source_revision=str(source_revision),
        segment="", original_values_hash=array_content_hash(np.asarray(right_values)),
        original_time_hash=array_content_hash(np.asarray(right_time)),
    )
    design = frozen_frf_alignment()
    provenance = {
        "value_source": "zero_phase_butterworth" if fast_is_left else "unchanged_samples",
        "time_source": "lower_rate_grid",
        "bandwidth_claim": True,
        "resamples_values": fast_is_left,
        "origin": float(grid[0]),
        "alignment": design,
    }
    left = _ready(
        left_out, np.array(grid, dtype=np.float64, copy=True),
        method="antialiased_lower_fs", source_fs=float(left_rate), target_fs=left_fs_out,
        input_count=int(np.asarray(left_values).shape[0]),
        requested_range=_range_of(left_time), effective_range=_range_of(grid),
        quality="finite", provenance=provenance, **common_left,
    )
    right_provenance = dict(provenance)
    right_provenance["value_source"] = "unchanged_samples" if fast_is_left else "zero_phase_butterworth"
    right_provenance["resamples_values"] = not fast_is_left
    right = _ready(
        right_out, np.array(grid, dtype=np.float64, copy=True),
        method="antialiased_lower_fs", source_fs=float(right_rate), target_fs=target,
        input_count=int(np.asarray(right_values).shape[0]),
        requested_range=_range_of(right_time), effective_range=_range_of(grid),
        quality="finite", provenance=right_provenance, **common_right,
    )
    facts["resampled"] = True
    facts["rejected_proof"] = ""
    facts["target_fs"] = target
    facts["ratio"] = nearest
    charged = int(left.bytes_charged) + int(right.bytes_charged)
    return PreparedPair(
        status="ready",
        reason="",
        left=left,
        right=right,
        relationship="aligned_lower_fs",
        alignment_facts=facts,
        method="antialiased_lower_fs",
        policy_version=POLICY_VERSION,
        bytes_charged=charged,
    )


def _explicit_uniform(values, time, source_fs, policy, value_kind, target_fs, origin, gaps, input_count, requested, common):
    del policy
    if value_kind not in {"continuous", "state"}:
        return _reject(
            "显式均匀化必须选择连续量或状态量，不能从整数推断",
            quality="kind",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    rate = _optional_fs(target_fs)
    if rate is None:
        return _reject("显式均匀化需要明确的目标采样率", quality="fs", input_count=input_count, requested_range=requested, **common)
    time_f = np.asarray(time, dtype=np.float64)
    if np.any(np.diff(time_f) <= 0) or not np.all(np.isfinite(time_f)):
        return _reject("显式均匀化要求严格递增的有限时间", quality="time", input_count=input_count, requested_range=requested, **common)
    if _crosses_gap(time_f, gaps):
        return _reject(
            "已知缺口不跨接，不能为了均匀化把缺口两侧连起来",
            quality="gap",
            input_count=input_count,
            requested_range=requested,
            **common,
        )
    start = float(time_f[0] if origin is None else origin)
    if value_kind == "continuous" and _is_downsample(time_f, source_fs, rate):
        if source_fs is None or not _uniform_declared(time_f, float(source_fs)):
            return _reject(
                "均匀降采样只接受已声明且落在网格上的连续量",
                quality="antialias",
                input_count=input_count,
                requested_range=requested,
                status="unsupported",
                method="unsupported",
                **common,
            )
        return _downsample_with_antialias(
            values, time_f, float(source_fs), rate, start, input_count, requested, common,
        )
    grid = _covered_grid(start, float(time_f[0]), float(time_f[-1]), rate)
    if grid.size < 2:
        return _reject("目标网格在有效覆盖内不足 2 点", quality="coverage", input_count=input_count, requested_range=requested, **common)
    if value_kind == "state":
        output = _zoh(time_f, np.asarray(values, dtype=np.float64), grid)
        method = "explicit_zoh"
        value_source = "zero_order_hold"
    else:
        output = np.interp(grid, time_f, np.asarray(values, dtype=np.float64))
        method = "explicit_linear_uniform"
        value_source = "linear_interpolation"
    return _ready(
        np.asarray(output, dtype=np.float64),
        grid,
        method=method,
        source_fs=source_fs,
        target_fs=rate,
        input_count=input_count,
        requested_range=requested if requested is not None else _range_of(time_f),
        effective_range=_range_of(grid),
        quality="finite",
        provenance={
            "value_source": value_source,
            "time_source": "origin_plus_k_over_fs",
            "bandwidth_claim": False,
            "resamples_values": True,
            "origin": float(grid[0]),
        },
        **common,
    )


def _covered_grid(origin, start, stop, fs):
    first = math.ceil((start - origin) * fs - 1e-9)
    last = math.floor((stop - origin) * fs + 1e-9)
    if last < first:
        return np.array([], dtype=np.float64)
    grid = origin + np.arange(first, last + 1, dtype=np.float64) / float(fs)
    return grid[(grid >= start - 1e-12) & (grid <= stop + 1e-12)]


def _zoh(time, values, grid):
    index = np.searchsorted(time, grid, side="right") - 1
    index = np.clip(index, 0, values.shape[0] - 1)
    return np.asarray(values, dtype=np.float64)[index]


def _is_downsample(time, source_fs, target_fs) -> bool:
    if source_fs is not None and float(target_fs) < float(source_fs) * (1.0 - 1e-12):
        return True
    dt = np.diff(np.asarray(time, dtype=float))
    positive = dt[dt > 0]
    if not positive.size:
        return False
    median_fs = 1.0 / float(np.median(positive))
    return float(target_fs) < median_fs * (1.0 - 1e-6)


def _crosses_gap(time, gaps) -> bool:
    if not gaps:
        return False
    start = float(time[0])
    stop = float(time[-1])
    for gap in gaps:
        if gap is None or len(gap) != 2:
            continue
        lo, hi = float(gap[0]), float(gap[1])
        if hi <= lo:
            continue
        if min(stop, hi) - max(start, lo) > 0.0 and start < hi and stop > lo:
            if start < lo < stop or start < hi < stop:
                return True
    return False


def _gaps_from_segments(time, segments):
    if not segments or len(segments) < 2:
        return ()
    axis = np.asarray(time, dtype=float)
    gaps = []
    ordered = sorted(segments, key=lambda item: int(item.start))
    for prev, nxt in zip(ordered, ordered[1:]):
        left = int(prev.stop) - 1
        right = int(nxt.start)
        if left < 0 or right >= axis.size or right <= left:
            continue
        if np.isfinite(axis[left]) and np.isfinite(axis[right]) and axis[right] > axis[left]:
            gaps.append((float(axis[left]), float(axis[right])))
    return tuple(gaps)


def _clocks_match(left_time, right_time, fs) -> bool:
    if fs is None or left_time.shape != right_time.shape or left_time.size < 2:
        return False
    if not np.all(np.isfinite(left_time)) or not np.all(np.isfinite(right_time)):
        return False
    if np.any(np.diff(left_time) <= 0) or np.any(np.diff(right_time) <= 0):
        return False
    nominal = 1.0 / float(fs)
    tolerance = DEFAULT_TIME_JITTER_TOLERANCE
    for axis in (left_time, right_time):
        jitter = float(np.max(np.abs(np.diff(axis) - nominal)) / nominal)
        if jitter > tolerance:
            return False
    difference = float(np.max(np.abs(left_time - right_time)))
    return difference <= tolerance / float(fs)


def _longest_true_run(mask: np.ndarray):
    best = (0, 0)
    start = None
    for index, flag in enumerate(mask.tolist()):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            if index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    if start is not None and mask.size - start > best[1] - best[0]:
        best = (start, mask.size)
    return best


def _ready(values, time, *, method, source_fs, target_fs, input_count, requested_range, effective_range, quality, provenance, **common):
    charged = int(values.nbytes + time.nbytes)
    return PreparedSignal(
        status="ready",
        reason="",
        values=values,
        time=time,
        input_count=int(input_count),
        output_count=int(values.shape[0]),
        requested_range=requested_range,
        effective_range=effective_range,
        source_fs=source_fs,
        target_fs=target_fs,
        method=method,
        quality=quality,
        boundary="none",
        policy_version=POLICY_VERSION,
        provenance=provenance,
        bytes_charged=charged,
        **common,
    )


def _reject(reason, *, quality, input_count=0, requested_range=None, status="rejected", method="rejected", provenance=None, **common):
    defaults = {
        "source_id": "",
        "physical_id": "",
        "source_revision": "",
        "segment": "",
        "original_values_hash": "",
        "original_time_hash": "",
    }
    defaults.update(common)
    return PreparedSignal(
        status=status,
        reason=reason,
        values=None,
        time=None,
        input_count=int(input_count),
        output_count=0,
        requested_range=requested_range,
        effective_range=None,
        source_fs=None,
        target_fs=None,
        method=method,
        quality=quality,
        boundary="none",
        policy_version=POLICY_VERSION,
        provenance={} if provenance is None else dict(provenance),
        bytes_charged=0,
        **defaults,
    )


def _pair(status, reason, relationship, method, facts) -> PreparedPair:
    return PreparedPair(
        status=status,
        reason=reason,
        left=None,
        right=None,
        relationship=relationship,
        alignment_facts=facts,
        method=method,
        policy_version=POLICY_VERSION,
        bytes_charged=0,
    )


def _optional_fs(value):
    if isinstance(value, (bool, np.bool_)) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def _finite_number(value) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _range_of(time):
    axis = np.asarray(time, dtype=float).reshape(-1)
    if not axis.size:
        return None
    return (float(axis[0]), float(axis[-1]))


def _as_range(value):
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    lo, hi = float(value[0]), float(value[1])
    return (lo, hi)


def _plain(value):
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not math.isfinite(number) else number
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if value is None or isinstance(value, (str, bool)):
        return value
    return str(value)


__all__ = [
    "DEFAULT_PREPARE_BYTE_LIMIT",
    "POLICY_VERSION",
    "PrepareByteLedger",
    "PreparedPair",
    "PreparedSignal",
    "array_content_hash",
    "batch_stage_facts",
    "load_native_channel",
    "preflight_prepare",
    "prepare_cache_key",
    "prepare_order_speed",
    "prepare_pair",
    "prepare_read_series",
    "prepare_signal",
]
