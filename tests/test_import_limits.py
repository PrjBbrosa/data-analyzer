"""Allocation contracts reject bad declarations before touching arrays."""
import pytest

from mf4_analyzer.io.import_limits import (
    ImportBudget, ImportLimits, ImportResourceError, budget_context,
    default_limits, get_import_budget,
)


def test_cumulative_allocation_rejects_before_reserving():
    budget = ImportBudget(ImportLimits(max_memory_bytes=64))
    budget.reserve_array((4,), "float64", label="time")
    budget.reserve(32, label="signal")
    with pytest.raises(ImportResourceError) as caught:
        budget.reserve(1, label="copy")
    assert caught.value.requested_bytes == 65
    assert budget.used_bytes == 64


@pytest.mark.parametrize("shape", [(-1,), (2**63,), (2**32, 2**32)])
def test_bad_shapes_never_reach_allocation(shape):
    with pytest.raises((ValueError, ImportResourceError)):
        ImportBudget(ImportLimits(max_memory_bytes=1024)).reserve_array(
            shape, "float64", label="declared array")


def test_budget_context_restores_even_after_failure():
    with budget_context(ImportLimits(max_memory_bytes=80)) as outer:
        assert get_import_budget() is outer
        with budget_context(ImportLimits(max_memory_bytes=8)) as inner:
            assert get_import_budget() is inner
        assert get_import_budget() is outer
    assert get_import_budget() is not outer


def test_copy_cost_and_channel_limit_are_explicit():
    budget = ImportBudget(ImportLimits(max_memory_bytes=100, max_channels=2))
    with pytest.raises(ImportResourceError):
        budget.reserve_array((8,), "float64", copies=2, label="conversion")
    with pytest.raises(ImportResourceError):
        budget.check_channels(3, label="channels")


def test_default_limits_reserve_parent_memory_and_have_deadline():
    limits = default_limits()
    assert 0 < limits.max_output_bytes <= limits.max_memory_bytes // 2
    assert limits.timeout_seconds > 0
    assert 0 < limits.cancel_grace_seconds <= 2


def test_windows_memory_query_initializes_structure_length(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    from mf4_analyzer.io import import_limits as limits

    def unsupported(_name):
        raise ValueError("not available on Windows")

    def query(pointer):
        status = pointer._obj
        assert status.length == ctypes.sizeof(status)
        status.available_phys = 8 * 1024 ** 3
        return 1

    monkeypatch.setattr(limits.os, "sysconf", unsupported)
    monkeypatch.setattr(limits.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(
        GlobalMemoryStatusEx=query)), raising=False)
    assert limits.default_limits().max_memory_bytes == 2 * 1024 ** 3
