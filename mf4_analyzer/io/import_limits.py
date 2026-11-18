"""UI-neutral allocation budgets for one import, including intermediate copies.

These are admission checks, not an OS memory sandbox. Native allocations still
run in a supervised child; available memory is an estimate, never a promise.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import errno
import math
import operator
import os
import re
import subprocess
import sys


_MIB = 1024 ** 2
_GIB = 1024 ** 3
# Historical analysis-prepare ceiling. Do not raise it here.
_ANALYSIS_REQUEST_CEILING = 512 * _MIB
_MAX_PHASE = 120
_MAX_BASIS = 80
_MAX_LABEL = 240
_MAX_COMPONENT_NAME = 200
_MAX_COMPONENTS = 32
_MAX_KIND = 64
_MAX_QUANTITY = 2**63 - 1
MAX_RESOURCE_DETAIL_CHARS = 16_000
MAX_RESOURCE_MESSAGE_CHARS = 4_000

# Wire values are a closed set. Unknown kinds keep their original wording.
RESOURCE_KINDS = frozenset({
    "memory_estimate",
    "worker_memory",
    "output_transfer",
    "temp_disk",
    "channel_count",
    "file_count",
    "memory_error",
    "diagnostic_output",
})
_KIND_UNITS = {
    "memory_estimate": "bytes",
    "worker_memory": "bytes",
    "output_transfer": "bytes",
    "temp_disk": "bytes",
    "memory_error": "bytes",
    "diagnostic_output": "bytes",
    "channel_count": "count",
    "file_count": "count",
}
RESOURCE_UNITS = frozenset({"bytes", "count"})
ACTION_CLOSE = "close"
ACTION_TOGGLE_DETAILS = "toggle_details"
ACTION_COPY_DIAGNOSTICS = "copy_diagnostics"
ACTION_RECHECK_RETRY = "recheck_retry"
_BASE_ACTIONS = (ACTION_CLOSE, ACTION_TOGGLE_DETAILS, ACTION_COPY_DIAGNOSTICS)
ESTIMATE_UNAVAILABLE = "未提供估算"


@dataclass(frozen=True)
class ImportResourceComponent:
    name: str
    amount: int
    unit: str


@dataclass(frozen=True)
class ImportResourceFacts:
    """Parsed resource failure. Numbers stay None when the envelope did not prove them."""

    resource_kind: str
    unit: str
    requested: int | None
    limit: int | None
    phase: str
    estimate_basis: str
    components: tuple[ImportResourceComponent, ...] = ()
    label: str = ""
    recheck_allowed: bool = False
    supported: bool = False
    numbers_available: bool = False


def _bounded_text(value, limit):
    if type(value) is not str:
        return ""
    cleaned = "".join(char for char in value if char >= " " or char == "\t")
    return cleaned[:limit]


def _quantity(value):
    """Accept only a non-negative int. Bools, floats and digit strings are not numbers."""
    if type(value) is not int or value < 0 or value > _MAX_QUANTITY:
        return None
    return value


def _component_items(components):
    if not components:
        return ()
    items = []
    for entry in components:
        if isinstance(entry, ImportResourceComponent):
            items.append(entry)
            continue
        if isinstance(entry, dict):
            name, amount, unit = entry.get("name"), entry.get("amount"), entry.get("unit")
        else:
            try:
                name, amount, unit = entry
            except (TypeError, ValueError):
                raise TypeError("resource component must be a name/amount/unit triple") from None
        if type(unit) is not str or unit not in RESOURCE_UNITS:
            raise ValueError("resource component unit is not bytes or count")
        parsed = _quantity(amount if type(amount) is int else int(amount))
        if parsed is None or type(name) is not str or not name:
            raise ValueError("resource component amount must be a non-negative integer")
        items.append(ImportResourceComponent(name[:_MAX_COMPONENT_NAME], parsed, unit))
    return tuple(items)


class ImportResourceError(ValueError):
    """A declaration or cumulative allocation exceeds this job's budget.

    Positional ``requested_bytes`` / ``limit_bytes`` remain the legacy byte
    admission call. Counts and other dimensions are keyword-only and never
    alias those two attributes.
    """

    def __init__(self, label, requested_bytes=None, limit_bytes=None, *,
                 resource_kind=None, unit=None, requested=None, limit=None,
                 phase="", estimate_basis="", components=None):
        self.label = str(label)
        structured = any(value is not None for value in (
            resource_kind, unit, requested, limit, components))
        if not structured and not phase and not estimate_basis:
            if requested_bytes is None or limit_bytes is None:
                raise TypeError("ImportResourceError requires requested_bytes and limit_bytes")
            resource_kind = "memory_estimate"
            unit = "bytes"
            requested = requested_bytes
            limit = limit_bytes
        else:
            if (requested is None and requested_bytes is not None
                    and unit in (None, "bytes")
                    and resource_kind in (None, "memory_estimate")):
                requested = requested_bytes
            if (limit is None and limit_bytes is not None
                    and unit in (None, "bytes")
                    and resource_kind in (None, "memory_estimate")):
                limit = limit_bytes
            if resource_kind is None:
                resource_kind = "memory_estimate"
            if unit is None:
                unit = _KIND_UNITS.get(resource_kind, "bytes")
        self.resource_kind = str(resource_kind)
        self.unit = str(unit)
        self.requested = None if requested is None else int(requested)
        self.limit = None if limit is None else int(limit)
        self.phase = str(phase)
        self.estimate_basis = str(estimate_basis)
        self.components = _component_items(components)
        if self.unit == "bytes":
            self.requested_bytes = None if self.requested is None else int(self.requested)
            self.limit_bytes = None if self.limit is None else int(self.limit)
        else:
            self.requested_bytes = None
            self.limit_bytes = None
        if self.requested is None or self.limit is None:
            message = f"导入资源超过预算：{self.label}；{ESTIMATE_UNAVAILABLE}；未截断或补造数据。"
        else:
            message = (
                f"导入资源超过预算：{self.label}，请求 {self.requested:,}，"
                f"上限 {self.limit:,}；未截断或补造数据。"
            )
        super().__init__(message)

    def to_envelope(self):
        payload = {
            "schema": 1,
            "resource_kind": self.resource_kind,
            "unit": self.unit,
            "phase": self.phase,
            "estimate_basis": self.estimate_basis,
            "label": self.label,
        }
        if self.requested is not None:
            payload["requested"] = int(self.requested)
        if self.limit is not None:
            payload["limit"] = int(self.limit)
        if self.components:
            payload["components"] = [
                {"name": item.name, "amount": int(item.amount), "unit": item.unit}
                for item in self.components
            ]
        return payload


@dataclass(frozen=True)
class ImportLimits:
    max_memory_bytes: int = 512 * _MIB
    max_output_bytes: int = 256 * _MIB
    max_channels: int = 100_000
    max_manifest_bytes: int = 8 * _MIB
    timeout_seconds: float = 1800.0
    cancel_grace_seconds: float = 2.0

    def __post_init__(self):
        for name in ("max_memory_bytes", "max_output_bytes", "max_channels",
                     "max_manifest_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("timeout_seconds", "cancel_grace_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


def _available_memory_bytes():
    try:
        return int(os.sysconf("SC_AVPHYS_PAGES")) * int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, AttributeError):
        pass
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/vm_stat"], capture_output=True, text=True,
                timeout=1, check=True,
            )
            page = re.search(r"page size of (\d+) bytes", result.stdout)
            counts = re.findall(r"Pages (?:free|inactive):\s+(\d+)\.", result.stdout)
            if page and len(counts) == 2:
                return int(page.group(1)) * sum(map(int, counts))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    if sys.platform == "win32":
        import ctypes
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_phys", "available_phys", "total_page", "available_page",
                    "total_virtual", "available_virtual", "extended_virtual")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.available_phys)
    return None


def default_limits():
    available = _available_memory_bytes()
    memory = min(2 * _GIB, max(2, available // 4)) if available else 512 * _MIB
    return ImportLimits(max_memory_bytes=memory, max_output_bytes=memory // 2)


@dataclass(frozen=True)
class AnalysisRequestHold:
    """One prepare request. Releasing it does not change import ``used_bytes``."""

    token: int
    nbytes: int
    label: str
    released: bool


@dataclass(frozen=True)
class LifecycleRecord:
    """A live native buffer note. It is not part of the cumulative admission."""

    token: int
    kind: str
    nbytes: int
    label: str
    released: bool


_LIFECYCLE_KINDS = frozenset({"raw", "time", "physical", "validity"})


class ImportBudget:
    def __init__(self, limits=None):
        self.limits = limits if limits is not None else default_limits()
        self.used_bytes = 0
        self._components = []
        self._lifecycle = []
        self._analysis_requests = []
        self._analysis_outstanding = 0

    def reserve(self, nbytes, *, label, phase="admission",
                estimate_basis="cumulative_admission"):
        nbytes = operator.index(nbytes)
        if nbytes < 0:
            raise ValueError(f"{label}: negative allocation")
        requested = self.used_bytes + nbytes
        if requested > self.limits.max_memory_bytes or nbytes > sys.maxsize:
            raise ImportResourceError(
                label, requested, self.limits.max_memory_bytes,
                resource_kind="memory_estimate", unit="bytes",
                phase=phase, estimate_basis=estimate_basis,
                components=(*self._components, (label, int(nbytes), "bytes")),
            )
        self.used_bytes = requested
        self._components.append((label, int(nbytes), "bytes"))

    def reserve_array(self, shape, dtype, *, copies=1, label, phase="admission",
                      estimate_basis="cumulative_admission"):
        import numpy as np
        dtype = np.dtype(dtype)
        if dtype.hasobject:
            raise ValueError(f"{label}: object arrays have no bounded numeric size")
        copies = operator.index(copies)
        if copies <= 0:
            raise ValueError(f"{label}: copies must be positive")
        elements = 1
        for size in shape:
            size = operator.index(size)
            if size < 0 or size > sys.maxsize:
                raise ValueError(f"{label}: invalid array shape")
            elements *= size
        self.reserve(elements * dtype.itemsize * copies, label=label,
                     phase=phase, estimate_basis=estimate_basis)

    def record_lifecycle(self, nbytes, *, kind, label):
        """Note one live native buffer.

        ``used_bytes`` stays the monotonic admission total. Releasing a note
        does not give that admission back and does not change ``reserve``.
        """
        if type(kind) is not str or kind not in _LIFECYCLE_KINDS:
            raise ValueError("lifecycle kind must be raw, time, physical, or validity")
        nbytes = operator.index(nbytes)
        if nbytes < 0:
            raise ValueError(f"{label}: negative lifecycle size")
        token = len(self._lifecycle)
        self._lifecycle.append(LifecycleRecord(
            token, kind, int(nbytes), str(label), False,
        ))
        return token

    def release_lifecycle(self, token):
        """Mark one live note released. ``used_bytes`` is left unchanged."""
        token = operator.index(token)
        current = self._lifecycle[token]
        if current.released:
            return
        self._lifecycle[token] = LifecycleRecord(
            current.token, current.kind, current.nbytes, current.label, True,
        )

    def lifecycle_snapshot(self):
        return tuple(self._lifecycle)

    def analysis_request_outstanding(self):
        """Bytes held by prepare requests. Independent of monotonic ``used_bytes``."""
        return int(self._analysis_outstanding)

    def open_analysis_request(self, nbytes, *, label):
        """Hold one prepare peak against this owner's memory cap.

        The hold is not an import admission and does not change ``used_bytes``.
        Live sources, bound results, the prepare cache and sibling tasks are
        not included; those remain the unfinished application ledger.
        """
        nbytes = operator.index(nbytes)
        if nbytes < 0:
            raise ValueError(f"{label}: negative analysis request")
        requested = self._analysis_outstanding + nbytes
        if requested > self.limits.max_memory_bytes or nbytes > sys.maxsize:
            raise ImportResourceError(
                label, requested, self.limits.max_memory_bytes,
                resource_kind="memory_estimate", unit="bytes",
                phase="analysis_request", estimate_basis="request_peak",
                components=((str(label), int(nbytes), "bytes"),),
            )
        token = len(self._analysis_requests)
        self._analysis_requests.append(AnalysisRequestHold(
            token, int(nbytes), str(label), False,
        ))
        self._analysis_outstanding = requested
        return token

    def release_analysis_request(self, token):
        """Return one prepare hold. A second release is a no-op.

        ``used_bytes`` stays where import admission left it.
        """
        token = operator.index(token)
        current = self._analysis_requests[token]
        if current.released:
            return
        self._analysis_outstanding -= current.nbytes
        self._analysis_requests[token] = AnalysisRequestHold(
            current.token, current.nbytes, current.label, True,
        )

    def check_channels(self, count, *, label, phase="admission",
                       estimate_basis="declared_count"):
        count = operator.index(count)
        if count < 0:
            raise ValueError(f"{label}: negative channel count")
        if count > self.limits.max_channels:
            raise ImportResourceError(
                label, resource_kind="channel_count", unit="count",
                requested=count, limit=self.limits.max_channels,
                phase=phase, estimate_basis=estimate_basis,
                components=((label, count, "count"),),
            )


_CURRENT_BUDGET = ContextVar("import_allocation_budget", default=None)


def get_import_budget():
    budget = _CURRENT_BUDGET.get()
    return budget if budget is not None else ImportBudget()


def active_import_budget():
    """Budget installed by ``budget_context``, or None.

    Unlike ``get_import_budget``, this does not create a throwaway ledger and
    does not query available memory.
    """
    return _CURRENT_BUDGET.get()


def analysis_request_byte_limit(budget=None) -> int:
    """Effective byte ceiling for one analysis prepare request.

    Uses the active owner's memory cap when a budget is installed, and never
    exceeds the historical 512 MiB prepare ceiling. ``used_bytes`` is not read.
    This is not the application peak: live sources, bound results, the byte
    LRU and concurrent tasks are still uncharged.
    """
    if budget is None:
        budget = _CURRENT_BUDGET.get()
    if budget is None:
        return _ANALYSIS_REQUEST_CEILING
    cap = operator.index(budget.limits.max_memory_bytes)
    if cap <= 0:
        raise ValueError("analysis request limit must be positive")
    if cap < _ANALYSIS_REQUEST_CEILING:
        return int(cap)
    return _ANALYSIS_REQUEST_CEILING


@contextmanager
def budget_context(limits=None):
    budget = ImportBudget(limits)
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)


def _unknown_facts(*, kind="unknown", phase="", estimate_basis="", label=""):
    return ImportResourceFacts(
        resource_kind=kind,
        unit="",
        requested=None,
        limit=None,
        phase=phase,
        estimate_basis=estimate_basis,
        components=(),
        label=label,
        recheck_allowed=False,
        supported=False,
        numbers_available=False,
    )


def _parsed_components(raw):
    if not isinstance(raw, list):
        return ()
    items = []
    for entry in raw:
        if len(items) >= _MAX_COMPONENTS:
            break
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        amount = _quantity(entry.get("amount"))
        unit = entry.get("unit")
        if type(name) is not str or not name or amount is None or unit not in RESOURCE_UNITS:
            continue
        items.append(ImportResourceComponent(_bounded_text(name, _MAX_COMPONENT_NAME), amount, unit))
    return tuple(items)


def parse_resource_envelope(payload):
    """Validate one bounded JSON object. Hostile or legacy payloads never raise."""
    if not isinstance(payload, dict):
        return _unknown_facts()
    if payload.get("schema", 1) != 1:
        return _unknown_facts()
    phase = _bounded_text(payload.get("phase", ""), _MAX_PHASE)
    basis = _bounded_text(payload.get("estimate_basis", ""), _MAX_BASIS)
    label = _bounded_text(payload.get("label", ""), _MAX_LABEL)
    kind_raw = payload.get("resource_kind")
    if type(kind_raw) is not str or not kind_raw or len(kind_raw) > _MAX_KIND or kind_raw not in RESOURCE_KINDS:
        token = kind_raw if type(kind_raw) is str and kind_raw.isidentifier() and len(kind_raw) <= _MAX_KIND else "unknown"
        return _unknown_facts(kind=token, phase=phase, estimate_basis=basis, label=label)
    expected_unit = _KIND_UNITS[kind_raw]
    unit_ok = payload.get("unit", expected_unit) == expected_unit
    requested = None
    limit = None
    if unit_ok:
        if "requested" in payload and payload.get("requested") is not None:
            requested = _quantity(payload.get("requested"))
        if "limit" in payload and payload.get("limit") is not None:
            limit = _quantity(payload.get("limit"))
    numbers_available = requested is not None and limit is not None
    return ImportResourceFacts(
        resource_kind=kind_raw,
        unit=expected_unit if unit_ok else "",
        requested=requested,
        limit=limit,
        phase=phase,
        estimate_basis=basis,
        components=_parsed_components(payload.get("components")),
        label=label,
        recheck_allowed=kind_raw == "memory_estimate" and unit_ok,
        supported=True,
        numbers_available=numbers_available,
    )


def _bare_envelope(kind, unit, basis, *, phase, label):
    return {
        "schema": 1,
        "resource_kind": kind,
        "unit": unit,
        "phase": _bounded_text(phase, _MAX_PHASE),
        "estimate_basis": basis,
        "label": label,
    }


def envelope_for_known_resource(exc, *, phase=""):
    """Structured facts for exceptions that already carry them. Never invents sizes."""
    if isinstance(exc, ImportResourceError):
        payload = exc.to_envelope()
        if phase and not payload.get("phase"):
            payload["phase"] = _bounded_text(phase, _MAX_PHASE)
        return payload
    if isinstance(exc, MemoryError):
        return _bare_envelope("memory_error", "bytes", "memory_error",
                              phase=phase or "runtime", label="MemoryError")
    quota = getattr(errno, "EDQUOT", None)
    if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, quota if quota is not None else -1):
        basis = "os_edquot" if quota is not None and exc.errno == quota else "os_enospc"
        return _bare_envelope("temp_disk", "bytes", basis, phase=phase or "storage", label="temp_disk")
    return None


def output_transfer_envelope(*, phase, label="output_transfer"):
    return _bare_envelope("output_transfer", "bytes", "transport_limit",
                          phase=phase or "transfer", label=label)


def worker_memory_envelope(*, requested, limit, phase):
    return {
        "schema": 1,
        "resource_kind": "worker_memory",
        "unit": "bytes",
        "requested": int(requested),
        "limit": int(limit),
        "phase": _bounded_text(phase, _MAX_PHASE),
        "estimate_basis": "worker_rss",
        "label": "worker_rss",
    }


def diagnostic_output_envelope(*, requested, limit, phase):
    return {
        "schema": 1,
        "resource_kind": "diagnostic_output",
        "unit": "bytes",
        "requested": int(requested),
        "limit": int(limit),
        "phase": _bounded_text(phase, _MAX_PHASE),
        "estimate_basis": "diagnostic_bytes",
        "label": "diagnostic_output",
    }


def clamp_resource_detail(detail):
    text = "" if detail is None else str(detail)
    if len(text) <= MAX_RESOURCE_DETAIL_CHARS:
        return text, False
    return text[-MAX_RESOURCE_DETAIL_CHARS:], True


def _coerce(error, *, message=None, stage=None, detail=None, request_id=None):
    if isinstance(error, ImportResourceFacts):
        return (error, message or "", stage or error.phase, detail or "", request_id or "")
    if isinstance(error, ImportResourceError):
        facts = parse_resource_envelope(error.to_envelope())
        return (
            facts,
            str(error) if message is None else message,
            error.phase if stage is None else stage,
            "" if detail is None else detail,
            "" if request_id is None else request_id,
        )
    if isinstance(error, dict):
        facts = parse_resource_envelope(error)
        return (facts, message or "", stage or facts.phase, detail or "", request_id or "")
    code = getattr(error, "code", None)
    if code is None and not hasattr(error, "resource"):
        raise TypeError(f"unsupported resource error value: {type(error).__name__}")
    if code not in (None, "resource_limit"):
        return (
            None,
            str(error) if message is None else message,
            getattr(error, "stage", "") if stage is None else stage,
            getattr(error, "detail", "") if detail is None else detail,
            getattr(error, "request_id", "") if request_id is None else request_id,
        )
    facts = getattr(error, "resource", None)
    if not isinstance(facts, ImportResourceFacts):
        facts = _unknown_facts()
    return (
        facts,
        str(error) if message is None else message,
        (getattr(error, "stage", "") or facts.phase) if stage is None else stage,
        getattr(error, "detail", "") if detail is None else detail,
        getattr(error, "request_id", "") if request_id is None else request_id,
    )


def _approx_mib(nbytes):
    rounded = (int(nbytes) + _MIB // 2) // _MIB
    if nbytes > 0 and rounded == 0:
        return "不足 1 MiB"
    return f"约{rounded} MiB"


def _user_body(facts, original):
    if not facts.supported:
        lines = [f"本次未导入此文件。{ESTIMATE_UNAVAILABLE}。"]
        if original:
            lines.append(original)
        return "\n".join(lines)
    kind = facts.resource_kind
    if kind == "memory_estimate" and facts.numbers_available:
        return (
            f"本次未导入此文件。预计导入资源需求{_approx_mib(facts.requested)}，"
            f"当前预算{_approx_mib(facts.limit)}。\n"
            "可关闭不需要的来源或其他占用内存的程序，再重新检查。重新检查后仍可能无法导入。"
        )
    if kind == "memory_estimate":
        return (
            f"本次未导入此文件。{ESTIMATE_UNAVAILABLE}。\n"
            "可关闭不需要的来源或其他占用内存的程序，再重新检查。重新检查后仍可能无法导入。"
        )
    if kind == "worker_memory" and facts.numbers_available:
        return (
            f"本次未导入此文件。读取进程监测到内存{_approx_mib(facts.requested)}，"
            f"当前预算{_approx_mib(facts.limit)}。这是运行中的监测结果。"
        )
    if kind == "worker_memory":
        return f"本次未导入此文件。读取进程内存超过预算。{ESTIMATE_UNAVAILABLE}。"
    if kind == "memory_error":
        return f"本次未导入此文件。读取进程报告内存不足。{ESTIMATE_UNAVAILABLE}。"
    if kind == "output_transfer" and facts.numbers_available:
        return (
            f"本次未导入此文件。读取结果传输量{_approx_mib(facts.requested)}，"
            f"输出上限{_approx_mib(facts.limit)}。"
        )
    if kind == "output_transfer":
        return f"本次未导入此文件。读取结果的传输量超过输出上限。{ESTIMATE_UNAVAILABLE}。"
    if kind == "temp_disk":
        if facts.numbers_available:
            text = (
                f"本次未导入此文件。临时磁盘空间不足，需求{_approx_mib(facts.requested)}，"
                f"可用上限{_approx_mib(facts.limit)}。这不是内存预算不足。"
            )
        else:
            text = (
                f"本次未导入此文件。临时磁盘空间不足，无法完成读取结果写入。"
                f"{ESTIMATE_UNAVAILABLE}。这不是内存预算不足。"
            )
        if original:
            text += "\n" + original
        return text
    if kind == "channel_count" and facts.numbers_available:
        return (
            f"本次未导入此文件。通道数量为 {facts.requested:,}，"
            f"当前上限为 {facts.limit:,}。"
        )
    if kind == "channel_count":
        return f"本次未导入此文件。通道数量超过上限。{ESTIMATE_UNAVAILABLE}。"
    if kind == "file_count" and facts.numbers_available:
        return (
            f"本次未导入此文件。文件数量为 {facts.requested:,}，"
            f"当前上限为 {facts.limit:,}。"
        )
    if kind == "file_count":
        return f"本次未导入此文件。文件数量超过上限。{ESTIMATE_UNAVAILABLE}。"
    if kind == "diagnostic_output" and facts.numbers_available:
        return (
            f"本次未导入此文件。诊断输出{_approx_mib(facts.requested)}，"
            f"上限{_approx_mib(facts.limit)}。"
        )
    if kind == "diagnostic_output":
        return f"本次未导入此文件。读取进程的诊断输出超过上限。{ESTIMATE_UNAVAILABLE}。"
    return f"本次未导入此文件。{ESTIMATE_UNAVAILABLE}。"


def resource_user_text(error, *, message=None):
    """Ordinary copy. Quantities come from structured fields, never from prose."""
    facts, original, _stage, _detail, _request_id = _coerce(error, message=message)
    if facts is None:
        return original
    return _user_body(facts, original)


def resource_technical_detail(error, *, message=None, stage=None, detail=None, request_id=None):
    """Exact quantities, breakdown, phase and log locator for the copy action."""
    facts, original, stage_value, detail_value, request = _coerce(
        error, message=message, stage=stage, detail=detail, request_id=request_id)
    if facts is None:
        lines = ["本次失败不是资源预算拒绝。"]
        if original:
            lines.append(f"原始说明：{original}")
        if detail_value:
            lines.append(detail_value)
        return "\n".join(lines)
    lines = [
        f"阶段：{facts.phase or stage_value or '未提供'}",
        f"资源类型：{facts.resource_kind}",
        f"单位：{facts.unit or '未提供'}",
    ]
    if facts.supported and facts.numbers_available:
        lines.append(f"估算请求：{facts.requested:,} {facts.unit}")
        lines.append(f"上限：{facts.limit:,} {facts.unit}")
        lines.append("估算请求供核对。进程是否持有这些字节，要以运行监测为准。")
    else:
        lines.append(f"估算：{ESTIMATE_UNAVAILABLE}")
    if facts.label:
        lines.append(f"技术标签：{facts.label}")
    if facts.estimate_basis:
        lines.append(f"估算依据：{facts.estimate_basis}")
    for item in facts.components:
        lines.append(f"分项：{item.name} = {item.amount:,} {item.unit}")
    if request:
        lines.append(f"日志定位：request_id={request}")
    else:
        lines.append("日志定位：应用日志中的 Import 失败记录")
    if stage_value and stage_value != facts.phase:
        lines.append(f"经纪阶段：{stage_value}")
    if original:
        lines.append(f"原始说明：{original}")
    if detail_value:
        lines.append("原始详情：")
        lines.append(detail_value)
    return "\n".join(lines)


def resource_action_ids(error):
    """Stable action ids. Chinese button labels are not part of this contract."""
    facts, *_rest = _coerce(error)
    if facts is None:
        return ()
    actions = list(_BASE_ACTIONS)
    if facts.recheck_allowed:
        actions.append(ACTION_RECHECK_RETRY)
    return tuple(actions)


def resource_recheck_allowed(error):
    """Pure mark for a later UI. Only a memory-estimate refusal may be rechecked."""
    facts, *_rest = _coerce(error)
    return bool(facts and facts.recheck_allowed)
