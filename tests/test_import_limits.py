"""Allocation contracts reject bad declarations before touching arrays."""
import errno

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


SCREENSHOT_REQUESTED = 638_740_162
SCREENSHOT_LIMIT = 498_988_944
BAIT_MESSAGE = "导入资源超过预算：bait，请求 638,740,162，上限 498,988,944"


def _limits_api():
    from mf4_analyzer.io import import_limits as limits
    return limits


def test_legacy_positional_call_keeps_byte_fields_and_message():
    error = ImportResourceError("copy", 65, 64)
    assert error.requested_bytes == 65
    assert error.limit_bytes == 64
    assert "copy" in str(error)
    assert "65" in str(error)
    limits = _limits_api()
    assert error.resource_kind == "memory_estimate"
    assert error.unit == "bytes"
    assert error.requested == 65
    assert error.limit == 64
    assert limits.resource_recheck_allowed(error) is True


def test_channel_count_is_not_reported_as_mib():
    limits = _limits_api()
    budget = ImportBudget(ImportLimits(max_memory_bytes=10**9, max_channels=2))
    with pytest.raises(ImportResourceError) as caught:
        budget.check_channels(3, label="channels")
    error = caught.value
    assert error.resource_kind == "channel_count"
    assert error.unit == "count"
    assert error.requested == 3
    assert error.limit == 2
    assert error.requested_bytes is None
    assert error.limit_bytes is None
    text = limits.resource_user_text(error)
    assert "MiB" not in text
    assert "通道" in text
    assert "3" in text and "2" in text
    assert "recheck_retry" not in limits.resource_action_ids(error)
    assert "释放" not in text


def test_memory_estimate_copy_uses_structured_fields_not_the_label():
    limits = _limits_api()
    error = ImportResourceError(
        "MDF shared-axis conversion/alignment/frame",
        1,
        2,
        resource_kind="memory_estimate",
        unit="bytes",
        requested=SCREENSHOT_REQUESTED,
        limit=SCREENSHOT_LIMIT,
        phase="mdf_shared_axis",
        estimate_basis="cumulative_admission",
        components=(
            ("record-buffer", 36_601_314, "bytes"),
            ("channel-catalog", 2_197_504, "bytes"),
            ("shared-axis", 599_941_344, "bytes"),
        ),
    )
    assert "请求 1" in str(error) or "638,740,162" in str(error)
    text = limits.resource_user_text(error)
    assert text == (
        "本次未导入此文件。预计导入资源需求约609 MiB，当前预算约476 MiB。\n"
        "可关闭不需要的来源或其他占用内存的程序，再重新检查。重新检查后仍可能无法导入。"
    )
    assert "MDF shared-axis conversion/alignment/frame" not in text
    assert "shared-axis" not in text
    assert "alignment" not in text
    assert "已分配" not in text
    assert "释放" not in text
    assert "139,751,218" not in text
    assert "139751218" not in text
    detail = limits.resource_technical_detail(error, request_id="abc123")
    assert "638,740,162" in detail
    assert "498,988,944" in detail
    assert "36,601,314" in detail
    assert "2,197,504" in detail
    assert "599,941,344" in detail
    assert "mdf_shared_axis" in detail
    assert "cumulative_admission" in detail
    assert "MDF shared-axis conversion/alignment/frame" in detail
    assert "abc123" in detail
    assert "日志定位" in detail
    assert limits.resource_action_ids(error) == (
        "close", "toggle_details", "copy_diagnostics", "recheck_retry",
    )
    assert all(action.isascii() for action in limits.resource_action_ids(error))


def test_user_text_ignores_contradictory_numbers_in_the_message():
    limits = _limits_api()
    facts = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "memory_estimate",
        "unit": "bytes",
        "requested": SCREENSHOT_REQUESTED,
        "limit": SCREENSHOT_LIMIT,
    })
    text = limits.resource_user_text(facts, message="请求 1，上限 2")
    assert "约609 MiB" in text
    assert "约476 MiB" in text
    assert "请求 1" not in text


@pytest.mark.parametrize("payload", [
    None,
    "resource_limit",
    5,
    ["memory_estimate"],
    True,
    {"schema": 1},
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes"},
    {"resource_kind": "memory_estimate", "unit": "bytes", "requested": None, "limit": None},
])
def test_missing_resource_fields_say_estimate_unavailable(payload):
    limits = _limits_api()
    facts = limits.parse_resource_envelope(payload)
    assert facts.requested is None
    assert facts.limit is None
    assert facts.numbers_available is False
    text = limits.resource_user_text(facts, message=BAIT_MESSAGE)
    assert "未提供估算" in text
    assert "609" not in text
    assert "476" not in text
    assert "MiB" not in text
    assert facts.recheck_allowed is False or facts.resource_kind == "memory_estimate"


@pytest.mark.parametrize("payload", [
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": -1, "limit": SCREENSHOT_LIMIT},
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": True, "limit": SCREENSHOT_LIMIT},
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": "638740162", "limit": "498988944"},
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": 1.5, "limit": SCREENSHOT_LIMIT},
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": 10**30, "limit": SCREENSHOT_LIMIT},
    {"schema": 1, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": SCREENSHOT_REQUESTED, "limit": -5},
    {"schema": 99, "resource_kind": "memory_estimate", "unit": "bytes",
     "requested": SCREENSHOT_REQUESTED, "limit": SCREENSHOT_LIMIT},
])
def test_bad_resource_fields_do_not_invent_amounts(payload):
    limits = _limits_api()
    facts = limits.parse_resource_envelope(payload)
    assert facts.numbers_available is False
    assert facts.requested is None or facts.limit is None or facts.supported is False
    text = limits.resource_user_text(facts, message=BAIT_MESSAGE)
    assert "未提供估算" in text
    assert "609" not in text
    assert "476" not in text
    assert "MiB" not in text


def test_unsupported_kind_keeps_original_wording_and_drops_recheck():
    limits = _limits_api()
    facts = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "gpu_memory",
        "unit": "bytes",
        "requested": SCREENSHOT_REQUESTED,
        "limit": SCREENSHOT_LIMIT,
        "recheck_allowed": True,
        "please_free_ram": True,
    })
    assert facts.supported is False
    assert facts.recheck_allowed is False
    assert facts.numbers_available is False
    text = limits.resource_user_text(facts, message="原始说明：控制器拒绝了这一次写入")
    assert "未提供估算" in text
    assert "控制器拒绝了这一次写入" in text
    assert "约609" not in text
    assert "MiB" not in text
    assert "预计导入资源需求" not in text
    assert "recheck_retry" not in limits.resource_action_ids(facts)
    detail = limits.resource_technical_detail(facts, message="原始说明：控制器拒绝了这一次写入")
    assert "gpu_memory" in detail
    assert "控制器拒绝了这一次写入" in detail
    assert "日志定位" in detail


def test_disk_copy_is_not_the_memory_estimate_copy():
    limits = _limits_api()
    memory = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "memory_estimate",
        "unit": "bytes",
        "requested": SCREENSHOT_REQUESTED,
        "limit": SCREENSHOT_LIMIT,
        "phase": "admission",
        "estimate_basis": "cumulative_admission",
    })
    disk = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "temp_disk",
        "unit": "bytes",
        "phase": "storage",
        "estimate_basis": "os_enospc",
        "recheck_allowed": True,
    })
    memory_text = limits.resource_user_text(memory)
    disk_text = limits.resource_user_text(disk, message="No space left on device")
    assert "预计导入资源需求" in memory_text
    assert "磁盘" in disk_text
    assert "预计导入资源需求" not in disk_text
    assert "磁盘" not in memory_text
    assert "MiB" not in disk_text
    assert "未提供估算" in disk_text
    assert "No space left on device" in disk_text or "No space left on device" in limits.resource_technical_detail(disk, message="No space left on device")
    assert limits.resource_recheck_allowed(memory) is True
    assert limits.resource_recheck_allowed(disk) is False
    assert limits.resource_action_ids(disk) == ("close", "toggle_details", "copy_diagnostics")


def test_file_count_and_worker_memory_stay_in_their_own_units():
    limits = _limits_api()
    files = limits.parse_resource_envelope({
        "schema": 1, "resource_kind": "file_count", "unit": "count",
        "requested": 12, "limit": 8,
    })
    text = limits.resource_user_text(files)
    assert "MiB" not in text
    assert "文件" in text
    assert "12" in text and "8" in text
    assert "recheck_retry" not in limits.resource_action_ids(files)
    watched = limits.parse_resource_envelope({
        "schema": 1, "resource_kind": "worker_memory", "unit": "bytes",
        "requested": 600 * 1024 * 1024, "limit": SCREENSHOT_LIMIT,
        "estimate_basis": "worker_rss", "phase": "读取数据",
    })
    watched_text = limits.resource_user_text(watched)
    assert "监测" in watched_text
    assert "预计导入资源需求" not in watched_text
    assert "释放" not in watched_text
    assert "recheck_retry" not in limits.resource_action_ids(watched)
    output = limits.parse_resource_envelope({
        "schema": 1, "resource_kind": "output_transfer", "unit": "bytes",
        "phase": "transfer", "estimate_basis": "transport_limit",
    })
    output_text = limits.resource_user_text(output)
    assert "未提供估算" in output_text
    assert "MiB" not in output_text
    assert "预计导入资源需求" not in output_text
    assert "传输" in output_text or "输出" in output_text


def test_mismatched_unit_is_not_compared_or_shown_as_mib():
    limits = _limits_api()
    facts = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "channel_count",
        "unit": "bytes",
        "requested": 3_000_000,
        "limit": 2,
    })
    assert facts.numbers_available is False
    text = limits.resource_user_text(facts, message=BAIT_MESSAGE)
    assert "MiB" not in text
    assert "未提供估算" in text
    assert "609" not in text
    matched = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "channel_count",
        "unit": "count",
        "requested": 3_000_000,
        "limit": 2,
    })
    assert matched.numbers_available is True
    matched_text = limits.resource_user_text(matched)
    assert "MiB" not in matched_text
    assert "3,000,000" in matched_text
    assert "通道" in matched_text


def test_bad_components_and_overlong_fields_are_bounded():
    limits = _limits_api()
    facts = limits.parse_resource_envelope({
        "schema": 1,
        "resource_kind": "memory_estimate",
        "unit": "bytes",
        "requested": SCREENSHOT_REQUESTED,
        "limit": SCREENSHOT_LIMIT,
        "phase": "p" * 5000,
        "estimate_basis": "b" * 5000,
        "label": "L" * 5000,
        "components": (
            [{"name": "n" * 5000, "amount": 1, "unit": "bytes"}] * 40
            + [{"name": "bad", "amount": -1, "unit": "bytes"},
               {"name": "string", "amount": "12", "unit": "bytes"},
               "nope"]
        ),
    })
    assert facts.numbers_available is True
    assert len(facts.phase) <= 120
    assert len(facts.estimate_basis) <= 80
    assert len(facts.label) <= 240
    assert 0 < len(facts.components) <= 32
    assert all(len(item.name) <= 200 and item.amount >= 0 for item in facts.components)
    assert all(item.name != "bad" and item.name != "string" for item in facts.components)
    text = limits.resource_user_text(facts)
    assert "约609 MiB" in text
    assert "L" * 241 not in text


def test_memory_error_helper_does_not_invent_bytes():
    limits = _limits_api()
    envelope = limits.envelope_for_known_resource(MemoryError("injected parser failure"))
    assert envelope["resource_kind"] == "memory_error"
    assert "requested" not in envelope
    assert "limit" not in envelope
    facts = limits.parse_resource_envelope(envelope)
    text = limits.resource_user_text(facts, message="injected parser failure")
    assert "未提供估算" in text
    assert "MiB" not in text
    assert facts.requested is None
    assert facts.limit is None
    assert facts.recheck_allowed is False
    disk = limits.envelope_for_known_resource(OSError(errno.ENOSPC, "No space left on device"))
    assert disk["resource_kind"] == "temp_disk"
    assert "requested" not in disk
    assert "limit" not in disk


def test_timeout_is_not_the_memory_recheck_action():
    limits = _limits_api()
    from mf4_analyzer.io.import_process import ImportProcessError
    error = ImportProcessError("timeout", "等待导入资源超过时间预算", stage="等待读取资源")
    assert limits.resource_action_ids(error) == ()
    assert limits.resource_recheck_allowed(error) is False
    assert "recheck_retry" not in limits.resource_action_ids(error)
    assert "延长" not in "".join(limits.resource_action_ids(error))


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
