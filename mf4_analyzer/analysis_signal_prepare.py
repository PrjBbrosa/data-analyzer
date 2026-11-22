"""Neutral analysis-input preparation.

Same-axis data passes through as a local float copy. Native callers do not
rebuild time by sample index. Explicit uniformization computes new values and
new times. Downsampling uses the frozen zero-phase Chebyshev II design.
Cross-rate FRF alignment is enabled only for a shared origin and an integer
ratio onto the lower rate. Other ratios and fractional delays stay unsupported.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import sys

import numpy as np

from .signal.numeric_precision import integers_exact_in_float64
from .signal.spectrogram import DEFAULT_TIME_JITTER_TOLERANCE

# Zero-phase Chebyshev type II. sosfiltfilt applies the design twice, so each
# pass is specified at half the product ripple and stopband. The product
# contract stays passband [0, 0.30 Ft] within 0.1 dB and stopband
# [0.50 Ft, source Nyquist) at least 60 dB down. Each pass uses 0.049 dB
# rather than a literal half of 0.1: the equiripple endpoint plus float64
# lands a few ULPs over 0.1 when the single pass is exactly 0.05.
_ANTIALIAS_PASSBAND_RATIO = 0.30
_ANTIALIAS_STOPBAND_RATIO = 0.50
_ANTIALIAS_PASSBAND_DB = 0.1
_ANTIALIAS_STOPBAND_DB = 60.0
_ANTIALIAS_GPASS_DB = 0.049
_ANTIALIAS_GSTOP_DB = 30.0
_PRECISION_POLICY = "m4-same-axis-2"


POLICY_VERSION = "m4-antialias-3"
_CLOCK_POLICY = "shared-origin-halo-1"
DEFAULT_PREPARE_BYTE_LIMIT = 512 * 1024 * 1024
_FLOAT_BYTES = 8
_RPM_UNITS = frozenset({"", "rpm", "r/min", "1/min", "min^-1", "rev/min"})
_BYTE_LIMIT_REASON = (
    "准备副本超过字节预算，未分配分析数组。"
    "请缩小时间范围或减少同时准备的通道；不会截断点数，也不会静默降采样。"
)
_CANCEL_REASON = "准备已取消，未保留本请求的分析数组。"
_PREPARE_INTENTS = frozenset({"passthrough", "explicit_uniform", "reinterpret_fs"})


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
    peak_bytes: int = 0


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
    peak_bytes: int = 0


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


@dataclass(frozen=True)
class PrepareCostPlan:
    """Scalar admission plan. ``result_bytes`` is not the overlapping peak.

    ``bytes_charged`` on a finished signal stays the retained result size.
    ``peak_bytes`` is the overlapping allocation this request must admit.
    Resident inputs are listed once and are not added on top of new copies.
    """

    output_count: int
    resident_input_bytes: int
    new_input_copy_bytes: int
    quality_index_bytes: int
    hash_bytes: int
    grid_output_bytes: int
    filter_workspace_bytes: int
    peak_bytes: int
    result_bytes: int
    quality: str = ""
    reason: str = ""

    def as_components(self) -> dict:
        return {
            "resident_input_bytes": int(self.resident_input_bytes),
            "new_input_copy_bytes": int(self.new_input_copy_bytes),
            "quality_index_bytes": int(self.quality_index_bytes),
            "hash_bytes": int(self.hash_bytes),
            "grid_output_bytes": int(self.grid_output_bytes),
            "filter_workspace_bytes": int(self.filter_workspace_bytes),
            "peak_bytes": int(self.peak_bytes),
            "result_bytes": int(self.result_bytes),
        }


def _buffer_resident_bytes(arrays) -> int:
    """Count each existing allocation once. Views collapse to their base."""
    seen = {}
    for array in arrays:
        arr = np.asarray(array)
        base = arr
        while isinstance(getattr(base, "base", None), np.ndarray):
            base = base.base
        seen[id(base)] = int(base.nbytes)
    return int(sum(seen.values()))


def _hash_workspace_bytes(array) -> int:
    """Peak bytes of one content hash: tobytes, plus a contiguous copy when needed.

    The two arrays of a signal are hashed one after another, so callers take
    the max rather than the sum. This does not hash.
    """
    arr = np.asarray(array)
    nbytes = int(arr.nbytes)
    if nbytes <= 0:
        return 0
    if arr.flags.c_contiguous:
        return nbytes
    return nbytes * 2


def _quality_index_bytes(count: int) -> int:
    """Bool masks that overlap: usable, finite values, finite time."""
    if count <= 0:
        return 0
    return int(count) * 3


def _covered_count(origin, start, stop, fs):
    """Point count of ``_covered_grid`` without allocating the grid.

    Returns None when the count is non-finite or cannot be an array length.
    """
    try:
        origin = float(origin)
        start = float(start)
        stop = float(stop)
        fs = float(fs)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(origin) or not math.isfinite(start) or not math.isfinite(stop):
        return None
    if not math.isfinite(fs) or fs <= 0.0:
        return None
    try:
        span_start = (start - origin) * fs
        span_stop = (stop - origin) * fs
    except OverflowError:
        return None
    if not math.isfinite(span_start) or not math.isfinite(span_stop):
        return None
    first = math.ceil(span_start - 1e-9)
    last = math.floor(span_stop + 1e-9)
    if last < first:
        return 0
    count = last - first + 1
    if count < 0 or count > sys.maxsize or count > sys.maxsize // _FLOAT_BYTES:
        return None
    return int(count)


def _filter_workspace_bytes(count, source_fs, target_fs):
    """Padded filtfilt workspace. Designs the SOS only; does not filter samples."""
    sos = _antialias_sos(source_fs, target_fs)
    sections = int(np.asarray(sos).shape[0])
    pad = 3 * (2 * sections + 1)
    extended = int(count) + 2 * pad
    if extended < 0 or extended > sys.maxsize // (_FLOAT_BYTES * 2):
        return None
    return _FLOAT_BYTES * extended * 2


def _downsample_planned(count, source_fs, target_fs, start, stop) -> bool:
    if source_fs is not None and float(target_fs) < float(source_fs) * (1.0 - 1e-12):
        return True
    if count < 2 or not math.isfinite(start) or not math.isfinite(stop) or stop <= start:
        return False
    median_fs = (count - 1) / (stop - start)
    return float(target_fs) < median_fs * (1.0 - 1e-6)


def _cost_plan(
    *,
    output_count,
    resident,
    new_copy,
    quality_bytes,
    hash_bytes,
    grid_bytes,
    filter_bytes,
    peak,
    result,
    quality="",
    reason="",
) -> PrepareCostPlan:
    return PrepareCostPlan(
        output_count=int(output_count),
        resident_input_bytes=int(resident),
        new_input_copy_bytes=int(new_copy),
        quality_index_bytes=int(quality_bytes),
        hash_bytes=int(hash_bytes),
        grid_output_bytes=int(grid_bytes),
        filter_workspace_bytes=int(filter_bytes),
        peak_bytes=int(peak),
        result_bytes=int(result),
        quality=quality,
        reason=reason,
    )


def _refused_plan(resident, *, quality, reason, output_count=0) -> PrepareCostPlan:
    return _cost_plan(
        output_count=output_count, resident=resident, new_copy=0, quality_bytes=0,
        hash_bytes=0, grid_bytes=0, filter_bytes=0, peak=0, result=0,
        quality=quality, reason=reason,
    )


def _passthrough_plan(values, time) -> PrepareCostPlan:
    """Two retained float64 copies. Temps that die first do not raise the peak."""
    count = int(values.shape[0])
    resident = _buffer_resident_bytes((values, time))
    new_copy = count * _FLOAT_BYTES
    quality_bytes = _quality_index_bytes(count)
    hash_bytes = max(_hash_workspace_bytes(values), _hash_workspace_bytes(time))
    grid_bytes = count * _FLOAT_BYTES * 2
    peak = max(hash_bytes, quality_bytes, grid_bytes)
    return _cost_plan(
        output_count=count, resident=resident, new_copy=new_copy,
        quality_bytes=quality_bytes, hash_bytes=hash_bytes, grid_bytes=grid_bytes,
        filter_bytes=0, peak=peak, result=grid_bytes,
    )


def _explicit_plan(values, time, *, source_fs, value_kind, target_fs, origin) -> PrepareCostPlan:
    resident = _buffer_resident_bytes((values, time))
    count = int(values.shape[0])
    if value_kind not in {"continuous", "state"}:
        return _refused_plan(
            resident, quality="kind",
            reason="显式均匀化必须选择连续量或状态量，不能从整数推断",
        )
    rate = _optional_fs(target_fs)
    if rate is None:
        return _refused_plan(
            resident, quality="fs",
            reason="显式均匀化需要明确的目标采样率",
        )
    try:
        start = float(time[0])
        stop = float(time[-1])
    except (TypeError, ValueError, OverflowError):
        return _refused_plan(resident, quality="time", reason="显式均匀化要求严格递增的有限时间")
    if not math.isfinite(start) or not math.isfinite(stop):
        return _refused_plan(resident, quality="time", reason="显式均匀化要求严格递增的有限时间")
    origin_value = start if origin is None else origin
    try:
        origin_value = float(origin_value)
    except (TypeError, ValueError, OverflowError):
        return _refused_plan(resident, quality="time", reason="显式均匀化要求严格递增的有限时间")
    output_count = _covered_count(origin_value, start, stop, rate)
    if output_count is None:
        return _refused_plan(
            resident, quality="unrepresentable",
            reason="目标点数无法表示，未分配分析网格。请缩小时间范围或降低目标采样率。",
        )
    source = _optional_fs(source_fs)
    filter_bytes = 0
    if value_kind == "continuous" and _downsample_planned(count, source, rate, start, stop):
        if source is None:
            filter_bytes = 0
        else:
            try:
                workspace = _filter_workspace_bytes(count, source, rate)
            except ValueError:
                workspace = 0
            if workspace is None:
                return _refused_plan(
                    resident, quality="unrepresentable",
                    reason="目标点数无法表示，未分配分析网格。请缩小时间范围或降低目标采样率。",
                )
            filter_bytes = int(workspace)
    grid_bytes = output_count * _FLOAT_BYTES * 2
    new_copy = 0 if values.dtype == np.dtype(np.float64) else count * _FLOAT_BYTES
    quality_bytes = _quality_index_bytes(count)
    hash_bytes = max(_hash_workspace_bytes(values), _hash_workspace_bytes(time))
    retained = grid_bytes
    overlapping_input = new_copy + retained
    peak = max(hash_bytes, quality_bytes, filter_bytes, retained, overlapping_input)
    return _cost_plan(
        output_count=output_count, resident=resident, new_copy=new_copy,
        quality_bytes=quality_bytes, hash_bytes=hash_bytes, grid_bytes=grid_bytes,
        filter_bytes=filter_bytes, peak=peak, result=retained,
    )


def plan_prepare_cost(
    values,
    time,
    *,
    fs=None,
    intent="passthrough",
    value_kind="unspecified",
    target_fs=None,
    origin=None,
) -> PrepareCostPlan:
    """Plan one signal from shape, dtype, rate and endpoints. Does not hash or allocate a grid."""
    values_arr = np.asarray(values)
    time_arr = np.asarray(time)
    if values_arr.ndim != 1 or time_arr.ndim != 1 or values_arr.shape[0] != time_arr.shape[0]:
        return _refused_plan(0, quality="shape", reason="分析输入必须是一维数组")
    if intent == "explicit_uniform":
        return _explicit_plan(
            values_arr, time_arr, source_fs=fs, value_kind=value_kind,
            target_fs=target_fs, origin=origin,
        )
    return _passthrough_plan(values_arr, time_arr)


def _combine_signal_plans(left: PrepareCostPlan, right: PrepareCostPlan, arrays) -> PrepareCostPlan:
    """One request. Both retained results overlap; sequential temps do not."""
    resident = _buffer_resident_bytes(arrays)
    new_copy = int(left.new_input_copy_bytes) + int(right.new_input_copy_bytes)
    quality_bytes = max(int(left.quality_index_bytes), int(right.quality_index_bytes))
    hash_bytes = max(int(left.hash_bytes), int(right.hash_bytes))
    grid_bytes = int(left.grid_output_bytes) + int(right.grid_output_bytes)
    filter_bytes = max(int(left.filter_workspace_bytes), int(right.filter_workspace_bytes))
    right_phase = max(
        int(right.hash_bytes), int(right.quality_index_bytes),
        int(right.filter_workspace_bytes), int(right.grid_output_bytes),
    )
    peak = max(
        grid_bytes,
        int(left.grid_output_bytes) + right_phase,
        int(left.peak_bytes),
        int(right.peak_bytes),
    )
    return _cost_plan(
        output_count=int(left.output_count) + int(right.output_count),
        resident=resident, new_copy=new_copy, quality_bytes=quality_bytes,
        hash_bytes=hash_bytes, grid_bytes=grid_bytes, filter_bytes=filter_bytes,
        peak=peak, result=int(left.result_bytes) + int(right.result_bytes),
    )


def plan_pair_cost(
    left_values,
    left_time,
    right_values,
    right_time,
    *,
    left_fs,
    right_fs,
    align_then_compute=False,
) -> PrepareCostPlan:
    """Plan one pair. Same-axis peaks add; a cross-rate pair uses one shared upper bound."""
    left_values_arr = np.asarray(left_values)
    right_values_arr = np.asarray(right_values)
    left_time_arr = np.asarray(left_time)
    right_time_arr = np.asarray(right_time)
    arrays = (left_values_arr, left_time_arr, right_values_arr, right_time_arr)
    if (
        left_values_arr.ndim != 1 or right_values_arr.ndim != 1
        or left_time_arr.ndim != 1 or right_time_arr.ndim != 1
    ):
        return _refused_plan(0, quality="shape", reason="分析输入必须是一维数组")
    left_rate = _optional_fs(left_fs)
    right_rate = _optional_fs(right_fs)
    rates_close = (
        left_rate is not None and right_rate is not None
        and math.isclose(left_rate, right_rate, rel_tol=1e-9, abs_tol=0.0)
    )
    if rates_close and _clocks_match(np.asarray(left_time_arr, dtype=float), np.asarray(right_time_arr, dtype=float), left_rate):
        left_plan = _passthrough_plan(left_values_arr, left_time_arr)
        right_plan = _passthrough_plan(right_values_arr, right_time_arr)
        return _combine_signal_plans(left_plan, right_plan, arrays)
    if not align_then_compute or left_rate is None or right_rate is None:
        return _refused_plan(
            _buffer_resident_bytes(arrays), quality="fs",
            reason="异轴对齐未验证，不能计算相位",
        )
    fast_count = int(left_values_arr.shape[0] if left_rate >= right_rate else right_values_arr.shape[0])
    slow_count = int(right_values_arr.shape[0] if left_rate >= right_rate else left_values_arr.shape[0])
    try:
        sections = int(np.asarray(_antialias_sos(max(left_rate, right_rate), min(left_rate, right_rate))).shape[0])
    except ValueError:
        return _refused_plan(
            _buffer_resident_bytes(arrays), quality="antialias",
            reason="抗混叠归一化频带不可设计",
        )
    return _align_cost_plan(
        fast_count, slow_count, sections, _buffer_resident_bytes(arrays),
    )


def _align_cost_plan(fast_count, slow_count, sections, resident) -> PrepareCostPlan:
    """Same terms as ``_align_admission_bytes``. Hash and masks sit in the ``*6`` term."""
    needed = _align_admission_bytes(fast_count, slow_count, sections)
    pad = 3 * (2 * int(sections) + 1)
    samples = int(fast_count) + int(slow_count)
    workspace = int(fast_count) + 2 * pad
    copy_bytes = 8 * samples * 6
    filter_bytes = 8 * workspace * 4
    grid_bytes = 8 * int(slow_count) * 4
    return _cost_plan(
        output_count=int(slow_count),
        resident=int(resident),
        new_copy=copy_bytes,
        quality_bytes=0,
        hash_bytes=0,
        grid_bytes=grid_bytes,
        filter_bytes=filter_bytes,
        peak=int(needed),
        result=0,
        quality="",
        reason="",
    )


def _passthrough_count_plan(count: int) -> PrepareCostPlan:
    """Contiguous float64 passthrough peak from a sample count. Does not allocate."""
    count = int(count)
    new_copy = count * _FLOAT_BYTES
    quality_bytes = _quality_index_bytes(count)
    hash_bytes = count * _FLOAT_BYTES
    grid_bytes = count * _FLOAT_BYTES * 2
    peak = max(hash_bytes, quality_bytes, grid_bytes)
    return _cost_plan(
        output_count=count, resident=0, new_copy=new_copy,
        quality_bytes=quality_bytes, hash_bytes=hash_bytes, grid_bytes=grid_bytes,
        filter_bytes=0, peak=peak, result=grid_bytes,
    )


def _open_request(budget, nbytes, label):
    """Return ``(token, blocked)``. A missing budget does not allocate a ledger."""
    if budget is None or int(nbytes) <= 0:
        return None, False
    from .io.import_limits import ImportResourceError

    try:
        return budget.open_analysis_request(int(nbytes), label=label), False
    except ImportResourceError:
        return None, True


def _release_request(budget, token):
    if budget is None or token is None:
        return
    budget.release_analysis_request(token)


def _endpoint_range(time_arr):
    if getattr(time_arr, "shape", ()) == () or int(time_arr.shape[0]) == 0:
        return None
    try:
        start = float(time_arr[0])
        stop = float(time_arr[-1])
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(start) or not math.isfinite(stop):
        return None
    return (start, stop)


def _identity_kwargs(source_id, physical_id, source_revision, segment):
    return dict(
        source_id=str(source_id),
        physical_id=str(physical_id),
        source_revision=str(source_revision),
        segment=str(segment),
    )


def _one_sample_is_finite(values_arr, time_arr) -> bool:
    try:
        return math.isfinite(float(values_arr[0])) and math.isfinite(float(time_arr[0]))
    except (TypeError, ValueError, OverflowError):
        return False


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
    resource_budget=None,
    cancel_check=None,
) -> PreparedSignal:
    """Prepare one channel. Hash and growing copies happen only after admission."""
    values_arr = np.asarray(values)
    time_arr = np.asarray(time)
    identity = _identity_kwargs(source_id, physical_id, source_revision, segment)
    if values_arr.ndim != 1 or time_arr.ndim != 1:
        return _reject("分析输入必须是一维数组", quality="shape", input_count=0, **identity)
    if values_arr.shape[0] != time_arr.shape[0]:
        return _reject(
            "分析值和时间长度不一致，不能按较短的一侧截断",
            quality="shape",
            input_count=int(values_arr.shape[0]),
            **identity,
        )
    if policy not in {"native", "legacy"}:
        return _reject("未知分析时间政策", quality="policy", input_count=int(values_arr.shape[0]), **identity)
    if policy == "native" and values_arr.dtype.kind not in "biuf":
        return _reject("native 分析只接受实数值数组", quality="dtype", input_count=len(values_arr), **identity)
    if intent not in _PREPARE_INTENTS:
        return _reject("未知准备意图", quality="intent", input_count=int(values_arr.shape[0]), **identity)
    count = int(values_arr.shape[0])
    if invalid is not None and np.asarray(invalid).shape != values_arr.shape:
        return _reject("失效掩码形状必须与样本一致", quality="invalid", input_count=count, **identity)
    if count == 0 or (count == 1 and _one_sample_is_finite(values_arr, time_arr)):
        return _reject("至少需要 2 个有效样本", quality="short", input_count=count, **identity)
    if count == 1:
        return _reject("样本含非有限值，默认拒绝计算", quality="nonfinite", input_count=count, **identity)

    plan = plan_prepare_cost(
        values_arr, time_arr, fs=fs, intent=intent, value_kind=value_kind,
        target_fs=target_fs, origin=origin,
    )
    if plan.quality in {"fs", "unrepresentable", "kind", "time"} and plan.reason:
        return _reject(plan.reason, quality=plan.quality, input_count=count, **identity)
    if intent == "passthrough" and _optional_fs(fs) is None:
        reason = (
            "旧政策重建仍需要声明采样率"
            if policy == "legacy"
            else "采样率未知，不能把序号间隔当成采样率"
        )
        return _reject(reason, quality="fs", input_count=count, **identity)
    if intent == "reinterpret_fs" and _optional_fs(fs) is None:
        return _reject("重解释需要明确的 Fs", quality="fs", input_count=count, **identity)
    if byte_limit is not None and int(plan.peak_bytes) > int(byte_limit):
        return _reject(
            _BYTE_LIMIT_REASON,
            quality="byte_limit",
            input_count=count,
            requested_range=_endpoint_range(time_arr),
            **identity,
        )
    token, blocked = _open_request(resource_budget, plan.peak_bytes, "prepare_signal")
    if blocked:
        return _reject(
            _BYTE_LIMIT_REASON,
            quality="byte_limit",
            input_count=count,
            requested_range=_endpoint_range(time_arr),
            **identity,
        )
    try:
        if cancel_check is not None and cancel_check():
            return _reject(
                _CANCEL_REASON, quality="cancelled", status="cancelled",
                input_count=count, **identity,
            )
        values_hash = array_content_hash(values_arr)
        time_hash = array_content_hash(time_arr)
        common = dict(
            source_id=str(source_id),
            physical_id=str(physical_id),
            source_revision=str(source_revision),
            segment=str(segment),
            original_values_hash=values_hash,
            original_time_hash=time_hash,
            peak_bytes=int(plan.peak_bytes),
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
            usable &= np.isfinite(values_arr if policy == "native" else np.asarray(values_arr, dtype=float))
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

        if policy == "native" and not integers_exact_in_float64(values_arr):
            return _reject(
                "整数样本不能精确表示为 float64；未启动计算，请缩小范围或选择可精确表示的通道",
                quality="integer_precision", input_count=count, requested_range=requested, **common,
            )

        if intent == "reinterpret_fs":
            return _reinterpret(values_arr, time_arr, source_fs, policy, count, requested, common)
        if intent == "explicit_uniform":
            return _explicit_uniform(
                values_arr, time_arr, source_fs, policy, value_kind, target_fs, origin,
                gaps, count, requested, common,
            )
        return _passthrough(values_arr, time_arr, source_fs, policy, count, requested, common)
    finally:
        _release_request(resource_budget, token)


@dataclass(frozen=True)
class _NativeClock:
    origin: float
    fs: float
    count: int
    index_base: int
    axis_id: str
    revision: str
    source_id: str
    physical_id: str
    segment: str
    unit: str
    uniform: bool
    reason: str


def _empty_clock(reason: str) -> _NativeClock:
    return _NativeClock(
        0.0, 0.0, 0, 0, "", "", "", "", "", "", False, reason,
    )


def _clock_from_parts(time, sampling, segments, *, revision, source_id, physical_id, axis_id, unit) -> _NativeClock:
    """One scalar origin and a declared rate. Does not copy the axis or the values."""
    facts = tuple(segments or ())
    fs = None
    if getattr(sampling, "status", None) == "known":
        fs = _optional_fs(getattr(sampling, "fs_hz", None))
    if len(facts) != 1:
        return _empty_clock("native 复位或分段时间轴不能按同一时钟对齐")
    segment = facts[0]
    if (
        not getattr(segment, "monotonic", False)
        or getattr(segment, "has_duplicate_time", False)
        or getattr(segment, "has_nonfinite_time", False)
    ):
        return _empty_clock("所选时钟含重复、复位或非有限时间，不能对齐")
    if fs is None:
        return _empty_clock("采样率未知，不能把序号间隔当成采样率")
    start = int(segment.start)
    stop = int(segment.stop)
    count = stop - start
    if count < 2:
        return _empty_clock("至少需要 2 个有效样本")
    try:
        origin = float(time[start])
    except (TypeError, ValueError, IndexError, OverflowError):
        return _empty_clock("原始时钟原点不可读")
    if not math.isfinite(origin):
        return _empty_clock("原始时钟原点不是有限值")
    return _NativeClock(
        origin=origin,
        fs=float(fs),
        count=count,
        index_base=start,
        axis_id=str(axis_id or ""),
        revision=str(revision or ""),
        source_id=str(source_id or ""),
        physical_id=str(physical_id or ""),
        segment=str(getattr(segment, "index", 0)),
        unit=str(unit or ""),
        uniform=True,
        reason="",
    )


def _native_clock(file_data, channel) -> _NativeClock:
    if not getattr(file_data, "is_native", False):
        return _empty_clock("load_native_channel 只接受 native 来源")
    logical = getattr(file_data, "logical_channels", None) or {}
    if channel in logical:
        record = logical[channel]
        physical = record.get("physical_key")
        token = getattr(physical, "token", "") or ""
        return _clock_from_parts(
            record["time"], record["sampling"], record.get("segments") or (),
            revision=record.get("revision"),
            source_id=record.get("source_id"),
            physical_id=token or physical or "",
            axis_id=record.get("axis_id"),
            unit=record.get("unit"),
        )
    store = getattr(file_data, "native_store", None)
    if store is None:
        return _empty_clock("native 来源没有可描述的时钟")
    from .io.native_signal_store import NativeContractError

    try:
        record = store.channel(channel)
        axis = store.axis(record.axis_id)
    except (NativeContractError, TypeError, KeyError, AttributeError) as exc:
        return _empty_clock(str(exc))
    token = getattr(record.physical_key, "token", "") or ""
    return _clock_from_parts(
        axis.values, axis.sampling, axis.segments,
        revision=store.revision,
        source_id=store.source_id,
        physical_id=token,
        axis_id=axis.axis_id,
        unit=record.unit,
    )


def _shared_origin(left: float, right: float) -> bool:
    scale = max(abs(float(left)), abs(float(right)), 1.0)
    return abs(float(left) - float(right)) <= 8.0 * np.finfo(np.float64).eps * scale


def _index_span(origin, fs, count, start, stop):
    """Inclusive indices of the declared grid inside ``[start, stop]``, or None."""
    if _covered_count(origin, start, stop, fs) is None:
        return None
    try:
        first = math.ceil((float(start) - float(origin)) * float(fs) - 1e-9)
        last = math.floor((float(stop) - float(origin)) * float(fs) + 1e-9)
    except (OverflowError, ValueError):
        return None
    if last < first:
        return None
    first = max(0, int(first))
    last = min(int(count) - 1, int(last))
    if last < first:
        return None
    return first, last


def _halo_samples(request_count: int, support: int) -> int:
    """Fast samples outside the request that keep the filter edge off the request."""
    halo = max(int(support), 16)
    request_count = max(0, int(request_count))
    for _ in range(64):
        window = request_count + 2 * halo
        if window < 2:
            return halo
        edge = min(window - 1, max(int(support), 16, window // 10))
        if edge <= halo:
            return halo
        halo = int(edge)
    return halo


def _cache_policy(left: _NativeClock, right: _NativeClock) -> str:
    payload = {
        "clock": _CLOCK_POLICY,
        "policy": "native",
        "input_revision": left.revision,
        "output_revision": right.revision,
        "input_axis": left.axis_id,
        "output_axis": right.axis_id,
        "input_segment": left.segment,
        "output_segment": right.segment,
        "input_physical": left.physical_id,
        "output_physical": right.physical_id,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _coverage_bounds(origin, fs, count, request):
    end = float(origin) + (int(count) - 1) / float(fs)
    if request is None:
        return float(origin), end
    try:
        start = float(request[0])
        stop = float(request[1])
    except (TypeError, ValueError, IndexError):
        return None
    if not math.isfinite(start) or not math.isfinite(stop) or start > stop:
        return None
    return max(float(origin), start), min(end, stop)


def frf_coverage_hint(start, stop, requested_range):
    if stop <= start:
        return "两通道缺少共同时间段，请选择同时记录的输入和输出。"
    if requested_range is None:
        return "共同时间段内样本不足，请选择重叠时间更长的通道。"
    return f"选区内共同样本不足，请在 {start} 至 {stop} 秒内重新选取时段。"


def _native_coverage_hint(left, right, request):
    left_start, left_stop = _coverage_bounds(left.origin, left.fs, left.count, None)
    right_start, right_stop = _coverage_bounds(right.origin, right.fs, right.count, None)
    return frf_coverage_hint(max(left_start, right_start), min(left_stop, right_stop), request)


def _plan_same_axis(left: _NativeClock, right: _NativeClock, request):
    left_bounds = _coverage_bounds(left.origin, left.fs, left.count, request)
    right_bounds = _coverage_bounds(right.origin, right.fs, right.count, request)
    if left_bounds is None or right_bounds is None:
        return None, "时间范围必须是有限且 start <= stop"
    start = max(left_bounds[0], right_bounds[0])
    stop = min(left_bounds[1], right_bounds[1])
    if not stop > start:
        return None, _native_coverage_hint(left, right, request)
    left_span = _index_span(left.origin, left.fs, left.count, start, stop)
    right_span = _index_span(right.origin, right.fs, right.count, start, stop)
    if left_span is None or right_span is None:
        return None, _native_coverage_hint(left, right, request)
    first = max(left_span[0], right_span[0])
    last = min(left_span[1], right_span[1])
    if last - first < 1:
        return None, _native_coverage_hint(left, right, request)
    effective = (
        float(left.origin) + first / float(left.fs),
        float(left.origin) + last / float(left.fs),
    )
    return {
        "first": first,
        "last": last,
        "count": last - first + 1,
        "effective": effective,
        "target_fs": float(left.fs),
    }, ""


def _plan_cross_rate(left: _NativeClock, right: _NativeClock, request):
    if left.fs >= right.fs:
        fast, slow, fast_is_left = left, right, True
    else:
        fast, slow, fast_is_left = right, left, False
    ratio = float(fast.fs) / float(slow.fs)
    nearest = int(round(ratio))
    if nearest < 2 or abs(ratio - nearest) > 1e-6:
        return None, "采样率比率不是大于 1 的整数，未验证的对齐不能计算相位"
    try:
        sections = int(np.asarray(_antialias_sos(fast.fs, slow.fs)).shape[0])
    except ValueError as exc:
        return None, str(exc)
    support = 3 * (2 * sections + 1)
    fast_bounds = _coverage_bounds(fast.origin, fast.fs, fast.count, request)
    slow_bounds = _coverage_bounds(slow.origin, slow.fs, slow.count, request)
    if fast_bounds is None or slow_bounds is None:
        return None, "时间范围必须是有限且 start <= stop"
    start = max(fast_bounds[0], slow_bounds[0])
    stop = min(fast_bounds[1], slow_bounds[1])
    if not stop > start:
        return None, _native_coverage_hint(left, right, request)
    fast_span = _index_span(fast.origin, fast.fs, fast.count, start, stop)
    slow_span = _index_span(slow.origin, slow.fs, slow.count, start, stop)
    if fast_span is None or slow_span is None:
        return None, _native_coverage_hint(left, right, request)
    request_count = fast_span[1] - fast_span[0] + 1
    if request_count < 2:
        return None, _native_coverage_hint(left, right, request)
    wanted = _halo_samples(request_count, support)
    left_halo = min(wanted, fast_span[0])
    right_halo = min(wanted, fast.count - 1 - fast_span[1])
    window_first = fast_span[0] - left_halo
    window_last = fast_span[1] + right_halo
    window_count = window_last - window_first + 1
    edge = min(window_count - 1, max(support, 16, window_count // 10))
    if edge * 2 >= window_count - 1:
        return None, "抗混叠边缘支持长度吃掉了有效段"
    valid_start = float(fast.origin) + (window_first + edge) / float(fast.fs)
    valid_stop = float(fast.origin) + (window_last - edge) / float(fast.fs)
    out_start = max(start, valid_start)
    out_stop = min(stop, valid_stop)
    slow_out = _index_span(slow.origin, slow.fs, slow.count, out_start, out_stop)
    if slow_out is None or slow_out[1] - slow_out[0] < 1:
        return None, "抗混叠边缘支持长度吃掉了有效段"
    effective = (
        float(slow.origin) + slow_out[0] / float(slow.fs),
        float(slow.origin) + slow_out[1] / float(slow.fs),
    )
    return {
        "fast": fast,
        "slow": slow,
        "fast_is_left": fast_is_left,
        "ratio": nearest,
        "sections": sections,
        "target_fs": float(slow.fs),
        "window_first": window_first,
        "window_last": window_last,
        "slow_first": slow_out[0],
        "slow_last": slow_out[1],
        "effective": effective,
        "edge": edge,
    }, ""


def _planned_signal(
    clock: _NativeClock, *, method, source_fs, target_fs, output_count,
    requested, effective, quality, provenance, peak,
) -> PreparedSignal:
    return PreparedSignal(
        status="ready",
        reason="",
        values=None,
        time=None,
        source_id=clock.physical_id or clock.axis_id,
        physical_id=clock.physical_id,
        source_revision=clock.revision,
        segment=clock.segment,
        input_count=int(clock.count),
        output_count=int(output_count),
        requested_range=requested,
        effective_range=effective,
        source_fs=float(source_fs),
        target_fs=float(target_fs),
        method=method,
        quality=quality,
        boundary="none",
        policy_version=POLICY_VERSION,
        provenance=provenance,
        original_values_hash="",
        original_time_hash="",
        bytes_charged=0,
        peak_bytes=int(peak),
    )


def _clock_facts(left: _NativeClock, right: _NativeClock, *, method, target_fs, effective, requested, ratio, resampled, quality) -> dict:
    return {
        "resampled": bool(resampled),
        "rejected_proof": "",
        "align_then_compute": ratio is not None or resampled,
        "policy": "native",
        "method": method,
        "target_fs": float(target_fs),
        "ratio": ratio,
        "origin": float(left.origin),
        "requested_range": None if requested is None else (float(requested[0]), float(requested[1])),
        "effective_range": (float(effective[0]), float(effective[1])),
        "quality": quality,
        "clock_policy": _CLOCK_POLICY,
        "cache_policy": _cache_policy(left, right),
        "input_revision": left.revision,
        "output_revision": right.revision,
        "input_axis_id": left.axis_id,
        "output_axis_id": right.axis_id,
        "input_segment": left.segment,
        "output_segment": right.segment,
        "input_physical_id": left.physical_id,
        "output_physical_id": right.physical_id,
    }


def prepare_native_frf_pair(
    input_fd,
    input_channel,
    output_fd,
    output_channel,
    *,
    requested_range=None,
    align_then_compute=False,
    materialize=True,
    byte_limit=None,
    resource_budget=None,
    cancel_check=None,
    left_identity="",
    right_identity="",
) -> PreparedPair:
    """Describe or materialize one native FRF pair from the original clocks.

    ``materialize=False`` reads shape, sampling, segment and revision only.
    It does not hash, copy values, build a resample grid, or filter.
    Sample quality stays ``pending_verification`` until a materialized job.
    """
    left = _native_clock(input_fd, input_channel)
    right = _native_clock(output_fd, output_channel)
    facts = {
        "resampled": False,
        "rejected_proof": "clock",
        "align_then_compute": bool(align_then_compute),
        "policy": "native",
        "clock_policy": _CLOCK_POLICY,
    }
    if not left.uniform or not right.uniform:
        return _pair(
            "unsupported",
            left.reason or right.reason or "时钟关系未验证，不能对齐",
            "unsupported",
            "unsupported",
            facts,
        )
    if left.source_id != right.source_id:
        return _pair(
            "unsupported",
            "输入和输出必须来自同一个逻辑来源",
            "unsupported",
            "unsupported",
            facts,
        )
    if not _shared_origin(left.origin, right.origin):
        return _pair(
            "unsupported",
            "两端原点不一致，分数延时未验证，不能对齐",
            "unsupported",
            "unsupported",
            facts,
        )
    rates_differ = not math.isclose(left.fs, right.fs, rel_tol=1e-9, abs_tol=0.0)
    if rates_differ and not align_then_compute:
        return _pair(
            "unsupported",
            "异轴对齐未验证，不能计算相位",
            "unsupported",
            "unsupported",
            facts,
        )
    cross = None
    same = None
    if rates_differ:
        cross, reason = _plan_cross_rate(left, right, requested_range)
        if cross is None:
            return _pair("unsupported", reason, "unsupported", "unsupported", facts)
        cost = _align_cost_plan(
            cross["window_last"] - cross["window_first"] + 1,
            cross["slow_last"] - cross["slow_first"] + 1,
            cross["sections"],
            0,
        )
        method = "antialiased_lower_fs"
        target_fs = cross["target_fs"]
        effective = cross["effective"]
        output_count = cross["slow_last"] - cross["slow_first"] + 1
        ratio = cross["ratio"]
    else:
        same, reason = _plan_same_axis(left, right, requested_range)
        if same is None:
            return _pair("rejected", reason, "time_relationship_required", "rejected", facts)
        cost = _combine_signal_plans(
            _passthrough_count_plan(same["count"]),
            _passthrough_count_plan(same["count"]),
            (),
        )
        method = "same_axis_passthrough"
        target_fs = same["target_fs"]
        effective = same["effective"]
        output_count = same["count"]
        ratio = None
    if byte_limit is not None and int(cost.peak_bytes) > int(byte_limit):
        return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    # Same-axis materialization lets prepare_pair own the single reservation.
    # A description, and a cross-rate job, hold it here and do not open again.
    owns_budget = not (materialize and same is not None)
    token = None
    if owns_budget:
        token, blocked = _open_request(resource_budget, cost.peak_bytes, "prepare_native_frf_pair")
        if blocked:
            return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    try:
        if cancel_check is not None and cancel_check():
            return _pair("cancelled", _CANCEL_REASON, "cancelled", "cancelled", facts)
        requested = None if requested_range is None else (float(requested_range[0]), float(requested_range[1]))
        if not materialize:
            quality = "pending_verification"
            described = _clock_facts(
                left, right, method=method, target_fs=target_fs, effective=effective,
                requested=requested, ratio=ratio, resampled=rates_differ, quality=quality,
            )
            described["align_then_compute"] = bool(align_then_compute)
            provenance = {
                "value_source": "not_materialized",
                "time_source": "declared_origin_fs",
                "bandwidth_claim": False,
                "resamples_values": bool(rates_differ),
                "origin": float(left.origin),
                "quality": quality,
                "clock_policy": _CLOCK_POLICY,
            }
            built_left = _planned_signal(
                left, method=method, source_fs=left.fs, target_fs=target_fs,
                output_count=output_count, requested=requested, effective=effective,
                quality=quality, provenance=provenance, peak=cost.peak_bytes,
            )
            built_right = _planned_signal(
                right, method=method, source_fs=right.fs, target_fs=target_fs,
                output_count=output_count, requested=requested, effective=effective,
                quality=quality, provenance=dict(provenance), peak=cost.peak_bytes,
            )
            if left_identity:
                built_left = replace(built_left, source_id=str(left_identity))
            if right_identity:
                built_right = replace(built_right, source_id=str(right_identity))
            return PreparedPair(
                status="ready",
                reason="",
                left=built_left,
                right=built_right,
                relationship="aligned_lower_fs" if rates_differ else "same_axis",
                alignment_facts=described,
                method=method,
                policy_version=POLICY_VERSION,
                bytes_charged=0,
                peak_bytes=int(cost.peak_bytes),
            )
        if same is not None:
            return _materialize_same_axis(
                input_fd, input_channel, output_fd, output_channel,
                left, right, same, requested, byte_limit, resource_budget,
                cancel_check, left_identity, right_identity, align_then_compute,
                cost.peak_bytes,
            )
        return _materialize_cross_rate(
            input_fd, input_channel, output_fd, output_channel,
            left, right, cross, requested, left_identity, right_identity,
            align_then_compute, cost.peak_bytes,
        )
    finally:
        if owns_budget:
            _release_request(resource_budget, token)


def _read_index(file_data, channel, start, stop):
    from .io.signal_access import IndexSpan, SignalAccessError, read_signal

    try:
        return read_signal(file_data, channel, span=IndexSpan(int(start), int(stop))), None
    except (SignalAccessError, TypeError, ValueError) as exc:
        return None, str(exc)


def _materialize_same_axis(
    input_fd, input_channel, output_fd, output_channel,
    left, right, plan, requested, byte_limit, resource_budget,
    cancel_check, left_identity, right_identity, align_then_compute, peak,
):
    left_series, left_error = _read_index(
        input_fd, input_channel,
        left.index_base + plan["first"], left.index_base + plan["last"] + 1,
    )
    right_series, right_error = _read_index(
        output_fd, output_channel,
        right.index_base + plan["first"], right.index_base + plan["last"] + 1,
    )
    if left_series is None or right_series is None:
        return _pair(
            "rejected", left_error or right_error or "native 分析输入不可用",
            "time_relationship_required", "rejected",
            {"resampled": False, "align_then_compute": bool(align_then_compute), "policy": "native"},
        )
    pair = prepare_pair(
        left_series.values, left_series.time, right_series.values, right_series.time,
        left_fs=left.fs, right_fs=right.fs, policy="native",
        align_then_compute=False,
        left_identity=left_identity or input_channel,
        right_identity=right_identity or output_channel,
        source_revision=left.revision,
        byte_limit=byte_limit,
        resource_budget=resource_budget,
        cancel_check=cancel_check,
        materialize=True,
    )
    if pair.status != "ready" or pair.left is None or pair.right is None:
        return pair
    facts = _clock_facts(
        left, right, method=pair.method, target_fs=float(pair.left.target_fs),
        effective=plan["effective"], requested=requested, ratio=None,
        resampled=False, quality="finite",
    )
    facts["align_then_compute"] = bool(align_then_compute)
    return replace(
        pair,
        alignment_facts=facts,
        peak_bytes=int(peak),
        left=replace(
            pair.left,
            source_revision=left.revision,
            physical_id=left.physical_id,
            segment=left.segment,
            requested_range=requested if requested is not None else pair.left.requested_range,
            effective_range=plan["effective"],
        ),
        right=replace(
            pair.right,
            source_revision=right.revision,
            physical_id=right.physical_id,
            segment=right.segment,
            requested_range=requested if requested is not None else pair.right.requested_range,
            effective_range=plan["effective"],
        ),
    )


def _materialize_cross_rate(
    input_fd, input_channel, output_fd, output_channel,
    left, right, plan, requested, left_identity, right_identity,
    align_then_compute, peak,
):
    fast_fd, fast_channel, fast_clock = (
        (input_fd, input_channel, left) if plan["fast_is_left"] else (output_fd, output_channel, right)
    )
    slow_fd, slow_channel, slow_clock = (
        (output_fd, output_channel, right) if plan["fast_is_left"] else (input_fd, input_channel, left)
    )
    facts = _clock_facts(
        left, right, method="antialiased_lower_fs", target_fs=plan["target_fs"],
        effective=plan["effective"], requested=requested, ratio=plan["ratio"],
        resampled=True, quality="finite",
    )
    facts["align_then_compute"] = bool(align_then_compute)
    fast, fast_error = _read_index(
        fast_fd, fast_channel,
        fast_clock.index_base + plan["window_first"],
        fast_clock.index_base + plan["window_last"] + 1,
    )
    slow, slow_error = _read_index(
        slow_fd, slow_channel,
        slow_clock.index_base + plan["slow_first"],
        slow_clock.index_base + plan["slow_last"] + 1,
    )
    if fast is None or slow is None:
        return _pair("rejected", fast_error or slow_error or "native 分析输入不可用", "unsupported", "unsupported", facts)
    fast_values = np.asarray(fast.values)
    slow_values = np.asarray(slow.values)
    fast_time = np.asarray(fast.time)
    slow_time = np.asarray(slow.time)
    if not integers_exact_in_float64(fast_values) or not integers_exact_in_float64(slow_values):
        return _pair(
            "rejected", "整数样本不能精确表示为 float64，未启动对齐计算",
            "integer_precision", "rejected", facts,
        )
    if (
        not _uniform_declared(fast_time, fast_clock.fs)
        or not _uniform_declared(slow_time, slow_clock.fs)
    ):
        return _pair(
            "unsupported",
            "异轴对齐只接受各自均匀且无缺口的连续量",
            "unsupported",
            "unsupported",
            facts,
        )
    if not np.all(np.isfinite(fast_values)) or not np.all(np.isfinite(slow_values)):
        return _pair(
            "rejected",
            "对齐段或抗混叠支持内含失效或非有限值，不能计算",
            "nonfinite",
            "rejected",
            facts,
        )
    filtered = _apply_antialias(fast_values, fast_clock.fs, plan["target_fs"])
    fast_out = np.interp(np.asarray(slow_time, dtype=np.float64), np.asarray(fast_time, dtype=np.float64), filtered)
    slow_out = np.asarray(slow_values, dtype=np.float64)
    grid = np.asarray(slow_time, dtype=np.float64)
    if plan["fast_is_left"]:
        left_values, right_values = fast_out, slow_out
    else:
        left_values, right_values = slow_out, fast_out
    design = frozen_frf_alignment()
    provenance = {
        "value_source": "zero_phase_chebyshev2" if plan["fast_is_left"] else "unchanged_samples",
        "time_source": "lower_rate_grid",
        "bandwidth_claim": True,
        "resamples_values": plan["fast_is_left"],
        "origin": float(left.origin),
        "alignment": design,
        "delay_compensation": 0,
        "precision_policy": _PRECISION_POLICY,
        "clock_policy": _CLOCK_POLICY,
        "read_start": int(fast_clock.index_base + plan["window_first"]),
        "read_stop": int(fast_clock.index_base + plan["window_last"] + 1),
        "output_start": int(slow_clock.index_base + plan["slow_first"]),
        "output_stop": int(slow_clock.index_base + plan["slow_last"] + 1),
    }

    def _side(values, clock, source_fs, resampled, value_source, source_values, source_time):
        copied_values = np.asarray(values, dtype=np.float64)
        copied_time = np.array(grid, dtype=np.float64, copy=True)
        side_provenance = dict(provenance)
        side_provenance["value_source"] = value_source
        side_provenance["resamples_values"] = resampled
        return _ready(
            copied_values, copied_time,
            method="antialiased_lower_fs",
            source_fs=float(source_fs),
            target_fs=float(plan["target_fs"]),
            input_count=int(clock.count),
            requested_range=requested if requested is not None else _range_of(copied_time),
            effective_range=plan["effective"],
            quality="finite",
            provenance=side_provenance,
            source_id=str(left_identity if clock is left else right_identity),
            physical_id=clock.physical_id,
            source_revision=clock.revision,
            segment=clock.segment,
            original_values_hash=array_content_hash(source_values),
            original_time_hash=array_content_hash(source_time),
            peak_bytes=int(peak),
        )

    if plan["fast_is_left"]:
        left_source, left_source_time = fast_values, fast_time
        right_source, right_source_time = slow_values, slow_time
    else:
        left_source, left_source_time = slow_values, slow_time
        right_source, right_source_time = fast_values, fast_time
    built_left = _side(
        left_values, left, left.fs, plan["fast_is_left"],
        "zero_phase_chebyshev2" if plan["fast_is_left"] else "unchanged_samples",
        left_source, left_source_time,
    )
    built_right = _side(
        right_values, right, right.fs, not plan["fast_is_left"],
        "unchanged_samples" if plan["fast_is_left"] else "zero_phase_chebyshev2",
        right_source, right_source_time,
    )
    charged = int(built_left.bytes_charged) + int(built_right.bytes_charged)
    return PreparedPair(
        status="ready",
        reason="",
        left=built_left,
        right=built_right,
        relationship="aligned_lower_fs",
        alignment_facts=facts,
        method="antialiased_lower_fs",
        policy_version=POLICY_VERSION,
        bytes_charged=charged,
        peak_bytes=int(peak),
    )


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
    materialize=True,
    resource_budget=None,
    cancel_check=None,
) -> PreparedPair:
    """Pair two original axes. Equal length is not evidence that they match.

    One ``byte_limit`` covers both sides, their outputs and the temps that
    are alive together. Each side must not be given that full limit again.
    """
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
                left_identity, right_identity, materialize=materialize,
                resource_budget=resource_budget, cancel_check=cancel_check,
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
    left_plan = _passthrough_plan(left_values_arr, left_time_arr)
    right_plan = _passthrough_plan(right_values_arr, right_time_arr)
    pair_plan = _combine_signal_plans(
        left_plan, right_plan,
        (left_values_arr, left_time_arr, right_values_arr, right_time_arr),
    )
    if byte_limit is not None and int(pair_plan.peak_bytes) > int(byte_limit):
        return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    token, blocked = _open_request(resource_budget, pair_plan.peak_bytes, "prepare_pair")
    if blocked:
        return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    # Each side is admitted against its own peak, never the whole request limit.
    left_limit = None if byte_limit is None else int(left_plan.peak_bytes)
    right_limit = None if byte_limit is None else int(right_plan.peak_bytes)
    try:
        if cancel_check is not None and cancel_check():
            return _pair("cancelled", _CANCEL_REASON, "cancelled", "cancelled", facts)
        left = prepare_signal(
            left_values_arr, left_time_arr, fs=left_rate, policy="native",
            source_id=str(left_identity), source_revision=source_revision,
            byte_limit=left_limit, cancel_check=cancel_check,
        )
        right = prepare_signal(
            right_values_arr, right_time_arr, fs=right_rate, policy="native",
            source_id=str(right_identity), source_revision=source_revision,
            byte_limit=right_limit, cancel_check=cancel_check,
        )
        if left.status == "cancelled" or right.status == "cancelled":
            return _pair("cancelled", _CANCEL_REASON, "cancelled", "cancelled", facts)
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
            peak_bytes=int(pair_plan.peak_bytes),
        )
    finally:
        _release_request(resource_budget, token)


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
    invalid=None,
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
    if policy == "native" and not integers_exact_in_float64(np.asarray(rpm_values)):
        return _reject("转速整数样本不能精确表示为 float64，未启动计算",
                       quality="integer_precision", input_count=int(signal.size), **common)
    rpm = np.asarray(rpm_values, dtype=float).reshape(-1)
    rpm_axis = np.asarray(rpm_time, dtype=float).reshape(-1)
    common["original_values_hash"] = array_content_hash(rpm)
    if rpm.shape[0] != rpm_axis.shape[0] or rpm.size < 2:
        return _reject("转速和时间长度不一致", quality="shape", input_count=int(signal.size), provenance=provenance, **common)
    invalid_mask = None
    if invalid is not None:
        invalid_mask = np.asarray(invalid, dtype=bool).reshape(-1)
        if invalid_mask.shape[0] != rpm.shape[0]:
            return _reject(
                "转速失效掩码长度必须与样本一致",
                quality="invalid", input_count=int(signal.size), provenance=provenance, **common,
            )
    if not np.all(np.isfinite(rpm_axis)):
        return _reject("转速或时间含非有限值", quality="nonfinite", input_count=int(signal.size), provenance=provenance, **common)
    if np.any(np.diff(rpm_axis) <= 0) or np.any(np.diff(signal) <= 0):
        return _reject("转速对齐要求两端时间严格递增", quality="time", input_count=int(signal.size), provenance=provenance, **common)
    factor = float(rpm_factor)
    scaled = rpm * factor

    def _speed_support_is_bad(query_axis):
        lo = float(np.asarray(query_axis, dtype=float)[0])
        hi = float(np.asarray(query_axis, dtype=float)[-1])
        covered = np.flatnonzero((rpm_axis >= lo) & (rpm_axis <= hi))
        if covered.size:
            left = max(0, int(covered[0]) - 1)
            right = min(int(rpm.size), int(covered[-1]) + 2)
        else:
            left, right = 0, int(rpm.size)
        flagged = invalid_mask is not None and bool(np.any(invalid_mask[left:right]))
        nonfinite = not bool(np.all(np.isfinite(rpm[left:right])))
        return flagged, nonfinite

    same_clock = rpm.size == signal.size and np.allclose(rpm_axis, signal, rtol=0.0, atol=1e-9)
    if same_clock:
        flagged, nonfinite = _speed_support_is_bad(signal)
        if flagged or nonfinite:
            return _reject(
                "转速样本含失效或非有限值，不能计算",
                quality="invalid" if flagged else "nonfinite",
                input_count=int(signal.size),
                provenance=provenance,
                **common,
            )
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
    flagged, nonfinite = _speed_support_is_bad(query)
    if flagged or nonfinite:
        return _reject(
            "转速样本含失效或非有限值，不能计算",
            quality="invalid" if flagged else "nonfinite",
            input_count=int(signal.size),
            provenance=provenance,
            **common,
        )
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


_TIME_FILTER_MIN_SAMPLES = 4
_TIME_FILTER_HALO_SAMPLES = 0
_TIME_FILTER_SHRINK = "请缩小到有效段或选择有效段。"


def time_filter_halo_samples(sample_count=None) -> int:
    """Source samples ``signal.filters.apply`` reads outside the array it is given.

    ``apply`` builds an odd-reflection pad of ``min(n - 1, max(16, n // 10))``
    from that array's own edges. The pad is not taken from neighboring source
    records, so the external halo is zero for every length.
    """
    return _TIME_FILTER_HALO_SAMPLES


def _filter_shrink(detail: str) -> str:
    text = str(detail).rstrip("。")
    return f"{text}。{_TIME_FILTER_SHRINK}"


def _filter_segments(time_arr, segments):
    facts = tuple(segments or ())
    if facts:
        return facts
    from .io.native_signal_store import build_segments

    return tuple(build_segments(time_arr))


def _time_filter_bounds(time_arr, requested_range, segments):
    """One contiguous read window, or a quality code. Does not allocate an index grid."""
    facts = _filter_segments(time_arr, segments)
    if requested_range is None:
        if len(facts) != 1:
            return None, "gap"
        fact = facts[0]
        if getattr(fact, "has_nonfinite_time", False):
            return None, "nonfinite"
        if not getattr(fact, "monotonic", True):
            return None, "time"
        return (int(fact.start), int(fact.stop)), None
    try:
        lo = float(requested_range[0])
        hi = float(requested_range[1])
    except (TypeError, ValueError, IndexError):
        return None, "time"
    if not math.isfinite(lo) or not math.isfinite(hi) or lo > hi:
        return None, "time"
    hits = []
    for fact in facts:
        if getattr(fact, "has_nonfinite_time", False) or not getattr(fact, "monotonic", True):
            continue
        start = int(fact.start)
        stop = int(fact.stop)
        if stop <= start:
            continue
        part = time_arr[start:stop]
        left = int(np.searchsorted(part, lo, side="left"))
        right = int(np.searchsorted(part, hi, side="right"))
        if right > left:
            hits.append((start + left, start + right))
    if len(hits) > 1:
        return None, "gap"
    if not hits:
        return (0, 0), None
    return hits[0], None


def _filter_interval_provenance(start, stop):
    return {
        "read_start": int(start),
        "read_stop": int(stop),
        "output_start": int(start),
        "output_stop": int(stop),
        "halo_samples": time_filter_halo_samples(stop - start),
        "halo_rule": "filters.apply 只对给定数组做奇反射填充，不读取选区外的源样本",
        "value_source": "unchanged_samples",
        "time_source": "acquisition_clock",
        "resamples_values": False,
        "drops_invalid": False,
    }


def prepare_time_filter_input(
    values,
    time,
    *,
    fs=None,
    invalid=None,
    segments=(),
    requested_range=None,
    source_id="",
    physical_id="",
    source_revision="",
    segment="",
    byte_limit=None,
    resource_budget=None,
    cancel_check=None,
) -> PreparedSignal:
    """Admit one time-filter window. Does not call the user filter.

    The read interval and the output interval are the same contiguous record
    span. Samples outside that span, and outside the zero-sample external
    halo, do not participate. Invalid, non-finite, reset, or unprovable-clock
    samples inside the span reject the whole request: nothing is zeroed,
    interpolated, or deleted and joined.
    """
    values_arr = np.asarray(values)
    time_arr = np.asarray(time)
    identity = _identity_kwargs(source_id, physical_id, source_revision, segment)
    if values_arr.ndim != 1 or time_arr.ndim != 1:
        return _reject("分析输入必须是一维数组", quality="shape", input_count=0, **identity)
    count = int(values_arr.shape[0])
    if time_arr.shape[0] != count:
        return _reject(
            "分析值和时间长度不一致，不能按较短的一侧截断",
            quality="shape",
            input_count=count,
            **identity,
        )
    if values_arr.dtype.kind not in "biuf":
        return _reject(
            "复杂数或分类通道不能滤波",
            quality="dtype",
            input_count=count,
            **identity,
        )
    if count == 0:
        return _reject(
            "至少需要 4 个样本才启动滤波",
            quality="short",
            input_count=0,
            **identity,
        )
    if invalid is not None and np.asarray(invalid).shape != values_arr.shape:
        return _reject(
            "失效掩码形状必须与样本一致",
            quality="invalid",
            input_count=count,
            **identity,
        )
    source_fs = _optional_fs(fs)
    if source_fs is None:
        return _reject(
            "采样率未知，不能把序号间隔当成采样率",
            quality="fs",
            input_count=count,
            **identity,
        )
    bounds, bounds_quality = _time_filter_bounds(time_arr, requested_range, segments)
    requested = _as_range(requested_range)
    if requested is None and count:
        requested = _range_of(time_arr)
    if bounds is None:
        if bounds_quality == "gap":
            reason = _filter_shrink("所选区间跨过时间间隙，不能删点拼接后滤波")
        elif bounds_quality == "nonfinite":
            reason = _filter_shrink("所选区间含非有限时间或数值，不能滤波")
        else:
            reason = _filter_shrink("所选区间含重复、复位或无法证明的均匀时钟，不能滤波")
        return _reject(
            reason,
            quality=bounds_quality or "time",
            input_count=count,
            requested_range=requested,
            provenance=_filter_interval_provenance(0, 0),
            **identity,
        )
    start, stop = bounds
    window_count = int(stop) - int(start)
    provenance = _filter_interval_provenance(start, stop)
    if window_count < _TIME_FILTER_MIN_SAMPLES:
        return _reject(
            "至少需要 4 个样本才启动滤波",
            quality="short",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    window_values = values_arr[start:stop]
    window_time = time_arr[start:stop]
    plan = plan_prepare_cost(window_values, window_time, fs=source_fs, intent="passthrough")
    if plan.quality in {"fs", "unrepresentable", "kind", "time", "shape"} and plan.reason:
        return _reject(
            plan.reason,
            quality=plan.quality,
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    if byte_limit is not None and int(plan.peak_bytes) > int(byte_limit):
        return _reject(
            _BYTE_LIMIT_REASON,
            quality="byte_limit",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    if invalid is not None and np.any(np.asarray(invalid, dtype=bool)[start:stop]):
        return _reject(
            _filter_shrink("所选区间含失效样本，不能跨失效滤波"),
            quality="invalid",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    if window_values.dtype.kind == "f" and not np.all(np.isfinite(window_values)):
        return _reject(
            _filter_shrink("所选区间含非有限时间或数值，不能滤波"),
            quality="nonfinite",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    time_f = np.asarray(window_time, dtype=np.float64)
    if (
        not np.all(np.isfinite(time_f))
        or time_f.shape[0] < 2
        or np.any(np.diff(time_f) <= 0)
    ):
        return _reject(
            _filter_shrink("所选区间含重复、复位或无法证明的均匀时钟，不能滤波"),
            quality="time",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    nominal = 1.0 / float(source_fs)
    jitter = float(np.max(np.abs(np.diff(time_f) - nominal)) / nominal)
    if jitter > DEFAULT_TIME_JITTER_TOLERANCE:
        return _reject(
            _filter_shrink("所选区间含重复、复位或无法证明的均匀时钟，不能滤波"),
            quality="time",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    if not integers_exact_in_float64(window_values):
        return _reject(
            "整数样本不能精确表示为 float64；未启动计算，请缩小范围或选择可精确表示的通道",
            quality="integer_precision",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    token, blocked = _open_request(resource_budget, plan.peak_bytes, "prepare_time_filter_input")
    if blocked:
        return _reject(
            _BYTE_LIMIT_REASON,
            quality="byte_limit",
            input_count=count,
            requested_range=requested,
            provenance=provenance,
            **identity,
        )
    try:
        if cancel_check is not None and cancel_check():
            return _reject(
                _CANCEL_REASON,
                quality="cancelled",
                status="cancelled",
                input_count=count,
                requested_range=requested,
                provenance=provenance,
                **identity,
            )
        values_hash = array_content_hash(window_values)
        time_hash = array_content_hash(window_time)
        copied_values = np.array(window_values, dtype=np.float64, copy=True)
        copied_time = np.array(time_f, dtype=np.float64, copy=True)
        return _ready(
            copied_values,
            copied_time,
            method="time_filter_window",
            source_fs=float(source_fs),
            target_fs=float(source_fs),
            input_count=count,
            requested_range=requested,
            effective_range=_range_of(copied_time),
            quality="finite",
            provenance=provenance,
            source_id=str(source_id),
            physical_id=str(physical_id),
            source_revision=str(source_revision),
            segment=str(segment),
            original_values_hash=values_hash,
            original_time_hash=time_hash,
            peak_bytes=int(plan.peak_bytes),
        )
    finally:
        _release_request(resource_budget, token)


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
            "compute_dtype": "float64",
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
            "compute_dtype": "float64",
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
            "compute_dtype": "float64",
            "time_source": "fs_reinterpret",
            "bandwidth_claim": False,
            "resamples_values": False,
            "policy": "legacy",
        },
        **common,
    )


def frozen_antialias_design() -> dict:
    """Zero-phase Chebyshev II used before a uniform downsample.

    The mask is not the user-filter Butterworth. ``sosfiltfilt`` applies the
    section twice. Each pass uses half the stopband and a passband ripple
    just inside half of 0.1 dB, so the product stays inside the contract.
    """
    return {
        "kind": "cheby2_zero_phase",
        "ftype": "cheby2",
        "passband_end_ratio": _ANTIALIAS_PASSBAND_RATIO,
        "stopband_start_ratio": _ANTIALIAS_STOPBAND_RATIO,
        "passband_db": _ANTIALIAS_PASSBAND_DB,
        "stopband_db": _ANTIALIAS_STOPBAND_DB,
        "gpass_per_pass_db": _ANTIALIAS_GPASS_DB,
        "gstop_per_pass_db": _ANTIALIAS_GSTOP_DB,
        "padding": "odd",
        "delay_compensation": 0,
        "edge_samples": "filtfilt_pad",
        "application": "sosfiltfilt",
        "precision_policy": _PRECISION_POLICY,
    }


def _antialias_sos(source_fs, target_fs):
    """Design the single-pass SOS. Does not allocate signal workspace."""
    from scipy.signal import iirdesign

    source = float(source_fs)
    target = float(target_fs)
    nyquist = 0.5 * source
    wp = (_ANTIALIAS_PASSBAND_RATIO * target) / nyquist
    ws = (_ANTIALIAS_STOPBAND_RATIO * target) / nyquist
    if not (0.0 < wp < ws < 1.0):
        raise ValueError("抗混叠归一化频带不可设计")
    return iirdesign(
        wp, ws, _ANTIALIAS_GPASS_DB, _ANTIALIAS_GSTOP_DB,
        analog=False, ftype="cheby2", output="sos",
    )


def _apply_antialias(values, source_fs, target_fs):
    """Zero-phase anti-alias. Call only after admission."""
    from scipy.signal import sosfiltfilt

    sos = _antialias_sos(source_fs, target_fs)
    return np.asarray(
        sosfiltfilt(sos, np.asarray(values, dtype=np.float64), padtype="odd"),
        dtype=np.float64,
    )


def _antialias_edge_count(count: int, source_fs, target_fs) -> int:
    if count < 2:
        return 0
    sections = int(np.asarray(_antialias_sos(source_fs, target_fs)).shape[0])
    support = 3 * (2 * sections + 1)
    return min(count - 1, max(support, 16, count // 10))


def _align_admission_bytes(fast_count: int, slow_count: int, sections: int) -> int:
    """Bytes of hash copies, masks, filter pad, grids and both outputs."""
    pad = 3 * (2 * int(sections) + 1)
    samples = int(fast_count) + int(slow_count)
    workspace = int(fast_count) + 2 * pad
    return 8 * (samples * 6 + workspace * 4 + int(slow_count) * 4)


def align_companion_clock(signal_time, values, companion_time, *, name="自定义横坐标"):
    """Put a companion on the signal clock, or reject a relationship that is not covered.

    Equal length is not evidence that the clocks match. Samples outside the
    companion coverage are not filled from the endpoint.
    """
    signal = np.asarray(signal_time, dtype=np.float64).reshape(-1)
    companion = np.asarray(values, dtype=np.float64).reshape(-1)
    clock = np.asarray(companion_time, dtype=np.float64).reshape(-1)
    if companion.shape[0] != clock.shape[0]:
        raise ValueError(f"{name} 的值和时间长度不一致")
    if signal.size < 2 or clock.size < 2:
        raise ValueError(f"{name} 至少需要 2 个采样点")
    if (
        not np.all(np.isfinite(signal))
        or not np.all(np.isfinite(clock))
        or not np.all(np.isfinite(companion))
    ):
        raise ValueError(f"{name} 含失效或非有限值，不能对齐")
    if np.any(np.diff(signal) <= 0) or np.any(np.diff(clock) <= 0):
        raise ValueError(f"{name} 要求时间严格递增")
    if companion.shape[0] == signal.size and np.allclose(clock, signal, rtol=0.0, atol=1e-9):
        return np.array(companion, dtype=np.float64, copy=True)
    if float(signal[-1]) < float(clock[0]) or float(signal[0]) > float(clock[-1]):
        raise ValueError(f"{name} 时钟与信号不重叠，不能当作同一采样")
    if np.any(signal < float(clock[0])) or np.any(signal > float(clock[-1])):
        raise ValueError(f"{name} 时钟未覆盖信号时间，不延长端点")
    return np.interp(signal, clock, companion).astype(np.float64, copy=False)


def frozen_frf_alignment() -> dict:
    """Supported cross-rate FRF alignment. Other combinations stay unsupported."""
    return {
        "origin": "shared_start",
        "ratio": "integer_lower_fs",
        "fractional_delay": "unsupported",
        "edge_policy": "drop_filter_support",
        "min_input_fs_band": (0.05, 0.30),
    }


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
    try:
        edge = _antialias_edge_count(count, source_fs, target_fs)
    except ValueError as exc:
        return _reject(
            str(exc),
            quality="antialias",
            input_count=input_count,
            requested_range=requested,
            status="unsupported",
            method="unsupported",
            **common,
        )
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
    filtered = _apply_antialias(values, source_fs, target_fs)
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
            "value_source": "zero_phase_chebyshev2",
            "time_source": "origin_plus_k_over_fs",
            "bandwidth_claim": True,
            "resamples_values": True,
            "origin": float(grid[0]),
            "antialias": frozen_antialias_design(),
            "delay_compensation": 0,
        },
        **common,
    )


def _described_signal(
    time, *, method, source_fs, target_fs, input_count, requested_range,
    quality, provenance, **common,
):
    grid = np.asarray(time, dtype=np.float64)
    return PreparedSignal(
        status="ready",
        reason="",
        values=None,
        time=grid,
        input_count=int(input_count),
        output_count=int(grid.shape[0]),
        requested_range=requested_range,
        effective_range=_range_of(grid),
        source_fs=source_fs,
        target_fs=target_fs,
        method=method,
        quality=quality,
        boundary="none",
        policy_version=POLICY_VERSION,
        provenance=provenance,
        bytes_charged=0,
        **common,
    )


def _describe_array_alignment(
    left_rate, right_rate, facts, source_revision, left_identity, right_identity,
    fast_is_left, target, nearest, needed, start, stop, fast_time, slow_time,
):
    """Scalar description of an in-memory alignment. No value copy, hash, grid or filter."""
    del fast_time
    slow = np.asarray(slow_time)
    origin = float(slow[0])
    count = int(slow.shape[0])
    span = _index_span(origin, float(target), count, float(start) - 1e-12, float(stop) + 1e-12)
    if span is None or span[1] - span[0] < 1:
        return _pair(
            "unsupported", "对齐后的共同网格不足 2 点",
            "unsupported", "unsupported", facts,
        )
    effective = (
        origin + span[0] / float(target),
        origin + span[1] / float(target),
    )
    output_count = span[1] - span[0] + 1
    facts = dict(facts)
    facts["resampled"] = True
    facts["rejected_proof"] = ""
    facts["target_fs"] = float(target)
    facts["ratio"] = int(nearest)
    facts["quality"] = "pending_verification"
    provenance = {
        "value_source": "not_materialized",
        "time_source": "declared_origin_fs",
        "bandwidth_claim": False,
        "resamples_values": True,
        "origin": origin,
        "quality": "pending_verification",
        "clock_policy": _CLOCK_POLICY,
    }

    def _one(identity, source_fs, resampled):
        side = dict(provenance)
        side["resamples_values"] = bool(resampled)
        return PreparedSignal(
            status="ready",
            reason="",
            values=None,
            time=None,
            source_id=str(identity),
            physical_id="",
            source_revision=str(source_revision),
            segment="",
            input_count=count,
            output_count=output_count,
            requested_range=None,
            effective_range=effective,
            source_fs=float(source_fs),
            target_fs=float(target),
            method="antialiased_lower_fs",
            quality="pending_verification",
            boundary="none",
            policy_version=POLICY_VERSION,
            provenance=side,
            original_values_hash="",
            original_time_hash="",
            bytes_charged=0,
            peak_bytes=int(needed),
        )

    left = _one(left_identity, left_rate, fast_is_left)
    right = _one(right_identity, right_rate, not fast_is_left)
    return PreparedPair(
        status="ready",
        reason="",
        left=left,
        right=right,
        relationship="aligned_lower_fs",
        alignment_facts=facts,
        method="antialiased_lower_fs",
        policy_version=POLICY_VERSION,
        bytes_charged=0,
        peak_bytes=int(needed),
    )


def _align_uniform_pair(
    left_values, left_time, right_values, right_time,
    left_rate, right_rate, facts, source_revision, byte_limit,
    left_identity, right_identity, *, materialize=True,
    resource_budget=None, cancel_check=None,
):
    facts = dict(facts)
    facts["resampled"] = False
    if (
        byte_limit is not None
        and left_rate is not None and right_rate is not None
        and np.asarray(left_values).ndim == 1 and np.asarray(right_values).ndim == 1
    ):
        fast_count = int(
            np.asarray(left_values).shape[0] if left_rate >= right_rate else np.asarray(right_values).shape[0]
        )
        slow_count = int(
            np.asarray(right_values).shape[0] if left_rate >= right_rate else np.asarray(left_values).shape[0]
        )
        try:
            early_sections = int(np.asarray(_antialias_sos(
                max(float(left_rate), float(right_rate)),
                min(float(left_rate), float(right_rate)),
            )).shape[0])
            early_needed = _align_admission_bytes(fast_count, slow_count, early_sections)
        except ValueError:
            early_needed = None
        if early_needed is not None and early_needed > int(byte_limit):
            return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    if materialize and (
        not integers_exact_in_float64(left_values) or not integers_exact_in_float64(right_values)
    ):
        return _pair(
            "rejected", "整数样本不能精确表示为 float64，未启动对齐计算",
            "integer_precision", "rejected", facts,
        )
    if materialize and (
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
    if not materialize and (left_rate is None or right_rate is None):
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
    fast_axis = np.asarray(fast_time, dtype=np.float64)
    slow_axis = np.asarray(slow_time, dtype=np.float64)
    try:
        edge = _antialias_edge_count(int(fast_axis.shape[0]), fast_fs, target)
        sections = int(np.asarray(_antialias_sos(fast_fs, target)).shape[0])
    except ValueError as exc:
        return _pair("unsupported", str(exc), "unsupported", "unsupported", facts)
    edge_s = edge / float(fast_fs)
    start = max(float(fast_axis[0]), float(slow_axis[0])) + edge_s
    stop = min(float(fast_axis[-1]), float(slow_axis[-1])) - edge_s
    if not stop > start:
        return _pair(
            "unsupported",
            "抗混叠边缘支持长度吃掉了有效段",
            "unsupported",
            "unsupported",
            facts,
        )
    needed = _align_admission_bytes(
        int(fast_axis.shape[0]), int(slow_axis.shape[0]), sections,
    )
    if byte_limit is not None and needed > int(byte_limit):
        return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    token, blocked = _open_request(resource_budget, needed, "prepare_pair_align")
    if blocked:
        return _pair("rejected", _BYTE_LIMIT_REASON, "byte_limit", "rejected", facts)
    try:
        if cancel_check is not None and cancel_check():
            return _pair("cancelled", _CANCEL_REASON, "cancelled", "cancelled", facts)
        if not materialize:
            return _describe_array_alignment(
                left_rate, right_rate, facts, source_revision, left_identity, right_identity,
                fast_is_left, target, nearest, needed, start, stop, fast_time, slow_time,
            )
        return _align_after_admission(
            left_values, left_time, right_values, right_time,
            left_rate, right_rate, facts, source_revision, left_identity, right_identity,
            fast_values, fast_time, slow_values, slow_time, fast_is_left, fast_fs,
            target, nearest, needed, start, stop, edge_s, fast_axis, slow_axis,
            materialize=materialize,
        )
    finally:
        _release_request(resource_budget, token)


def _align_after_admission(
    left_values, left_time, right_values, right_time,
    left_rate, right_rate, facts, source_revision, left_identity, right_identity,
    fast_values, fast_time, slow_values, slow_time, fast_is_left, fast_fs,
    target, nearest, needed, start, stop, edge_s, fast_axis, slow_axis,
    *, materialize,
):
    """Masks, hash, filter and outputs. The caller has already admitted ``needed``."""
    slow_mask = (slow_axis >= start - 1e-12) & (slow_axis <= stop + 1e-12)
    fast_mask = (fast_axis >= start - edge_s - 1e-12) & (fast_axis <= stop + edge_s + 1e-12)
    grid = slow_axis[slow_mask]
    slow_out = np.asarray(slow_values, dtype=np.float64)[slow_mask]
    fast_window = np.asarray(fast_values, dtype=np.float64)[fast_mask]
    fast_window_time = fast_axis[fast_mask]
    if grid.size < 2 or fast_window.size < 2:
        return _pair(
            "unsupported",
            "对齐后的共同网格不足 2 点",
            "unsupported",
            "unsupported",
            facts,
        )
    if not np.all(np.isfinite(slow_out)) or not np.all(np.isfinite(fast_window)):
        return _pair(
            "rejected",
            "对齐段或抗混叠支持内含失效或非有限值，不能计算",
            "nonfinite",
            "rejected",
            facts,
        )
    if materialize:
        filtered = _apply_antialias(fast_window, fast_fs, target)
        fast_out = np.interp(grid, fast_window_time, filtered)
    else:
        fast_out = None
    left_out, right_out = (fast_out, slow_out) if fast_is_left else (slow_out, fast_out)
    left_fs_out = target
    hash_inputs = bool(materialize)
    common_left = dict(
        source_id=str(left_identity), physical_id="", source_revision=str(source_revision),
        segment="",
        original_values_hash=array_content_hash(np.asarray(left_values)) if hash_inputs else "",
        original_time_hash=array_content_hash(np.asarray(left_time)) if hash_inputs else "",
    )
    common_right = dict(
        source_id=str(right_identity), physical_id="", source_revision=str(source_revision),
        segment="",
        original_values_hash=array_content_hash(np.asarray(right_values)) if hash_inputs else "",
        original_time_hash=array_content_hash(np.asarray(right_time)) if hash_inputs else "",
    )
    design = frozen_frf_alignment()
    provenance = {
        "value_source": "zero_phase_chebyshev2" if fast_is_left else "unchanged_samples",
        "time_source": "lower_rate_grid",
        "bandwidth_claim": True,
        "resamples_values": fast_is_left,
        "origin": float(grid[0]),
        "alignment": design,
        "delay_compensation": 0,
        "precision_policy": _PRECISION_POLICY,
    }
    grid_copy = np.array(grid, dtype=np.float64, copy=True)
    if materialize:
        left = _ready(
            left_out, grid_copy,
            method="antialiased_lower_fs", source_fs=float(left_rate), target_fs=left_fs_out,
            input_count=int(np.asarray(left_values).shape[0]),
            requested_range=_range_of(left_time), effective_range=_range_of(grid),
            quality="finite", provenance=provenance, **common_left,
        )
        right_provenance = dict(provenance)
        right_provenance["value_source"] = "unchanged_samples" if fast_is_left else "zero_phase_chebyshev2"
        right_provenance["resamples_values"] = not fast_is_left
        right = _ready(
            right_out, np.array(grid, dtype=np.float64, copy=True),
            method="antialiased_lower_fs", source_fs=float(right_rate), target_fs=target,
            input_count=int(np.asarray(right_values).shape[0]),
            requested_range=_range_of(right_time), effective_range=_range_of(grid),
            quality="finite", provenance=right_provenance, **common_right,
        )
    else:
        left = _described_signal(
            grid_copy, method="antialiased_lower_fs", source_fs=float(left_rate),
            target_fs=left_fs_out, input_count=int(np.asarray(left_values).shape[0]),
            requested_range=_range_of(left_time), quality="finite",
            provenance=provenance, **common_left,
        )
        right_provenance = dict(provenance)
        right_provenance["value_source"] = "unchanged_samples" if fast_is_left else "zero_phase_chebyshev2"
        right_provenance["resamples_values"] = not fast_is_left
        right = _described_signal(
            np.array(grid, dtype=np.float64, copy=True),
            method="antialiased_lower_fs", source_fs=float(right_rate), target_fs=target,
            input_count=int(np.asarray(right_values).shape[0]),
            requested_range=_range_of(right_time), quality="finite",
            provenance=right_provenance, **common_right,
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
        peak_bytes=int(needed),
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
    peak = common.pop("peak_bytes", charged)
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
        peak_bytes=int(peak),
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
    common.pop("peak_bytes", None)
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
        peak_bytes=0,
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
    "align_companion_clock",
    "array_content_hash",
    "batch_stage_facts",
    "load_native_channel",
    "plan_pair_cost",
    "plan_prepare_cost",
    "preflight_prepare",
    "prepare_cache_key",
    "PrepareCostPlan",
    "prepare_native_frf_pair",
    "prepare_order_speed",
    "prepare_pair",
    "prepare_read_series",
    "prepare_signal",
]
