"""UI-neutral allocation budgets for one import, including intermediate copies.

These are admission checks, not an OS memory sandbox. Native allocations still
run in a supervised child; available memory is an estimate, never a promise.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import operator
import os
import re
import subprocess
import sys


_MIB = 1024 ** 2
_GIB = 1024 ** 3


class ImportResourceError(ValueError):
    """A declaration or cumulative allocation exceeds this job's budget."""

    def __init__(self, label, requested_bytes, limit_bytes):
        self.label = str(label)
        self.requested_bytes = int(requested_bytes)
        self.limit_bytes = int(limit_bytes)
        super().__init__(
            f"导入资源超过预算：{self.label}，请求 {self.requested_bytes:,}，"
            f"上限 {self.limit_bytes:,}；未截断或补造数据。"
        )


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


class ImportBudget:
    def __init__(self, limits=None):
        self.limits = limits if limits is not None else default_limits()
        self.used_bytes = 0

    def reserve(self, nbytes, *, label):
        nbytes = operator.index(nbytes)
        if nbytes < 0:
            raise ValueError(f"{label}: negative allocation")
        requested = self.used_bytes + nbytes
        if requested > self.limits.max_memory_bytes or nbytes > sys.maxsize:
            raise ImportResourceError(label, requested, self.limits.max_memory_bytes)
        self.used_bytes = requested

    def reserve_array(self, shape, dtype, *, copies=1, label):
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
        self.reserve(elements * dtype.itemsize * copies, label=label)

    def check_channels(self, count, *, label):
        count = operator.index(count)
        if count < 0:
            raise ValueError(f"{label}: negative channel count")
        if count > self.limits.max_channels:
            raise ImportResourceError(label, count, self.limits.max_channels)


_CURRENT_BUDGET = ContextVar("import_allocation_budget", default=None)


def get_import_budget():
    budget = _CURRENT_BUDGET.get()
    return budget if budget is not None else ImportBudget()


@contextmanager
def budget_context(limits=None):
    budget = ImportBudget(limits)
    token = _CURRENT_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _CURRENT_BUDGET.reset(token)
