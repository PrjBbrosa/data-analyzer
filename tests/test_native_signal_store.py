"""M1 native store: immutable axes, identity, revision, and lifecycle ledger.

These tests build stores in memory. They do not call ``load_mf4`` or
``load_mf4_native`` and do not claim a file import is finished.
"""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.io.import_limits import ImportBudget, ImportLimits
from mf4_analyzer.io.native_signal_store import (
    AxisSpec,
    ChannelSpec,
    NativeContractError,
    NativeSignalStore,
    SourceClosedError,
)


def _time_axis(axis_id, clock, values, **kwargs):
    return AxisSpec(
        axis_id=axis_id,
        clock_source=clock,
        kind="time",
        unit="s",
        values=np.asarray(values, dtype=np.float64),
        **kwargs,
    )


def _channel(group, index, name, axis_id, raw, **kwargs):
    return ChannelSpec(
        group=group,
        index=index,
        original_name=name,
        axis_id=axis_id,
        raw=np.asarray(raw),
        **kwargs,
    )


def _store(axes, channels, source_id="mdf:test-root"):
    return NativeSignalStore.build(source_id, axes, channels)


def test_channels_keep_their_own_lengths_and_no_shared_table():
    short = _time_axis("slow", "clk-slow", [0.0, 1.0, 2.0])
    long = _time_axis("fast", "clk-fast", np.arange(8) / 10.0)
    store = _store(
        (short, long),
        (
            _channel(0, 1, "torque", "slow", [1, 2, 3], unit="Nm"),
            _channel(1, 1, "speed", "fast", np.arange(8), unit="rpm"),
        ),
    )
    assert store.channel("torque").sample_count == 3
    assert store.channel("speed").sample_count == 8
    arrays = store.owned_arrays()
    assert arrays
    assert all(array.ndim == 1 for array in arrays)
    assert not any(getattr(array, "shape", ())[:1] == (8,) and array.ndim == 2 for array in arrays)
    assert store.axis("slow").clock_source == "clk-slow"
    assert store.axis("fast").clock_source == "clk-fast"
    assert store.axis("slow").axis_id != store.axis("fast").axis_id


def test_equal_clocks_share_only_when_the_same_buffer_is_given():
    shared = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    shared.setflags(write=False)
    store = _store(
        (
            AxisSpec("a", "device-a", "time", "s", shared),
            AxisSpec("b", "device-b", "time", "s", shared),
        ),
        (
            _channel(0, 1, "left", "a", [1.0, 2.0, 3.0]),
            _channel(1, 1, "right", "b", [4.0, 5.0, 6.0]),
        ),
    )
    assert np.shares_memory(store.axis("a").values, store.axis("b").values)
    assert store.axis("a").clock_source == "device-a"
    assert store.axis("b").clock_source == "device-b"
    assert store.axis("a").axis_id != store.axis("b").axis_id

    separate = _store(
        (
            _time_axis("a", "device-a", [0.0, 0.1, 0.2]),
            _time_axis("b", "device-b", [0.0, 0.1, 0.2]),
        ),
        (
            _channel(0, 1, "left", "a", [1.0, 2.0, 3.0]),
            _channel(1, 1, "right", "b", [4.0, 5.0, 6.0]),
        ),
    )
    assert not np.shares_memory(separate.axis("a").values, separate.axis("b").values)
    assert separate.axis("a").clock_source != separate.axis("b").clock_source


def test_time_measurement_uses_the_existing_public_name_map():
    axis = _time_axis("master", "ecu-clock", [0.0, 0.1, 0.2, 0.3])
    store = _store(
        (axis,),
        (
            _channel(0, 1, "Time", "master", [10, 20, 30, 40], unit="Nm"),
            _channel(1, 2, "Time", "master", [1, 2, 3, 4], unit="V"),
            _channel(0, 3, "sig", "master", [4, 3, 2, 1], unit="V"),
        ),
    )
    assert store.public_names() == ("Time [0:1]", "Time [1:2]", "sig")
    assert store.channel("Time [0:1]").raw.tolist() == [10, 20, 30, 40]
    assert store.channel("Time [1:2]").unit == "V"
    with pytest.raises(NativeContractError, match="Time"):
        store.channel("Time")
    with pytest.raises(NativeContractError, match="time"):
        store.channel("time")
    assert not np.array_equal(store.axis("master").values, store.channel("Time [0:1]").raw)
    assert store.channel("Time [0:1]").physical_key.token != "Time [0:1]"
    assert store.channel("Time [0:1]").physical_key.group == 0
    assert store.channel("Time [0:1]").physical_key.index == 1


def test_raw_int64_above_float_mantissa_stays_int64_and_readonly():
    raw = np.array([2**53 + 3, -(2**53)], dtype=np.int64)
    store = _store(
        (_time_axis("t", "clk", [0.0, 1.0]),),
        (_channel(0, 1, "counter", "t", raw),),
    )
    stored = store.channel("counter").raw
    physical = store.channel("counter").physical
    assert stored.dtype == np.int64
    assert physical.dtype == np.int64
    assert int(stored[0]) == 2**53 + 3
    assert stored is physical
    assert stored.flags.writeable is False
    with pytest.raises(ValueError):
        stored[0] = 0
    caller = np.array([2**53 + 3, -(2**53)], dtype=np.int64)
    caller[0] = 1
    assert int(stored[0]) == 2**53 + 3


def test_revision_follows_content_not_wrapper_identity():
    def build(sample):
        return _store(
            (_time_axis("t", "clk", [0.0, 0.5]),),
            (_channel(0, 1, "sig", "t", [sample, 2.0]),),
        )

    first = build(1.0)
    second = build(1.0)
    changed = build(1.5)
    assert first.revision == second.revision
    assert first.revision != changed.revision
    assert str(id(first.axis("t").values)) not in first.revision
    derived = first.with_derived_channel(
        original_name="filtered",
        group=9,
        index=0,
        axis_id="t",
        raw=np.array([3.0, 4.0]),
        unit="Nm",
    )
    assert derived.revision != first.revision
    assert "filtered" not in first.public_names()
    assert derived.axis("t").values is first.axis("t").values
    assert not np.shares_memory(derived.channel("filtered").raw, first.channel("sig").raw)


def test_derived_values_are_independent_of_the_caller_buffer():
    store = _store(
        (_time_axis("t", "clk", [0.0, 1.0, 2.0]),),
        (_channel(0, 1, "sig", "t", [1.0, 1.0, 1.0]),),
    )
    caller = np.array([8.0, 8.0, 8.0])
    derived = store.with_derived_channel(
        original_name="offset",
        group=9,
        index=1,
        axis_id="t",
        raw=caller,
    )
    caller[0] = -1.0
    assert derived.channel("offset").raw.tolist() == [8.0, 8.0, 8.0]
    assert store.channel("sig").raw.tolist() == [1.0, 1.0, 1.0]
    with pytest.raises(ValueError):
        derived.channel("offset").raw[0] = 0.0


def test_duplicate_physical_occurrence_is_rejected():
    axis = _time_axis("t", "clk", [0.0, 1.0])
    with pytest.raises(NativeContractError, match="occurrence"):
        _store(
            (axis,),
            (
                _channel(0, 1, "sig", "t", [1.0, 2.0]),
                _channel(0, 1, "sig-alias", "t", [3.0, 4.0]),
            ),
        )


def test_length_mismatch_is_not_truncated():
    with pytest.raises(NativeContractError, match="3"):
        _store(
            (_time_axis("t", "clk", [0.0, 1.0, 2.0]),),
            (_channel(0, 1, "sig", "t", [1.0, 2.0]),),
        )


def test_parent_coordinates_stay_on_the_physical_key():
    store = _store(
        (_time_axis("t", "clk", [0.0, 1.0]),),
        (
            _channel(
                0, 4, "elem", "t", [5, 6],
                parent=("vector",), coordinates=(1,),
            ),
        ),
    )
    key = store.channel("elem").physical_key
    assert key.parent == ("vector",)
    assert key.coordinates == (1,)
    assert store.public_names() == ("elem",)


def test_close_drops_access_without_touching_samples():
    store = _store(
        (_time_axis("t", "clk", [0.0, 1.0]),),
        (_channel(0, 1, "sig", "t", [1.0, 2.0]),),
    )
    revision = store.revision
    store.close()
    assert store.closed is True
    assert store.revision == revision
    with pytest.raises(SourceClosedError):
        store.channel("sig")
    store.close()


def test_decimal_rates_are_uniform_and_real_jitter_is_not():
    original = np.arange(100, dtype=np.float64) / 100.0
    seen = original.copy()
    for rate in (10.0, 100.0, 1000.0, 1024.0):
        stamps = np.arange(100, dtype=np.float64) / rate
        store = _store(
            (_time_axis("t", "clk", stamps),),
            (_channel(0, 1, "sig", "t", np.arange(100.0)),),
        )
        sampling = store.axis("t").sampling
        assert sampling.status == "known"
        assert sampling.basis == "uniform_timestamps"
        assert sampling.fs_hz == pytest.approx(rate)
        shifted = 12.5 + stamps
        shifted_store = _store(
            (_time_axis("t", "clk", shifted),),
            (_channel(0, 1, "sig", "t", np.arange(100.0)),),
        )
        assert shifted_store.axis("t").sampling.status == "known"
        assert shifted_store.axis("t").sampling.fs_hz == pytest.approx(rate)
    jitter = seen.copy()
    jitter[40] += 1e-6
    noisy = _store(
        (_time_axis("t", "clk", jitter),),
        (_channel(0, 1, "sig", "t", np.arange(100.0)),),
    )
    assert noisy.axis("t").sampling.status == "unknown"
    assert noisy.axis("t").sampling.basis == "not_strictly_uniform"
    np.testing.assert_array_equal(noisy.axis("t").values, jitter)
    declared = _store(
        (_time_axis("t", "clk", np.arange(32) / 1024.0, fs_status="known", fs_hz=100.0),),
        (_channel(0, 1, "sig", "t", np.arange(32.0)),),
    )
    assert declared.axis("t").sampling.status == "unknown"
    assert declared.axis("t").sampling.basis == "declared_conflict"
    np.testing.assert_array_equal(original, seen)


def test_sampling_status_is_known_estimated_or_unknown():
    uniform = _store(
        (_time_axis("t", "clk", [0.0, 0.1, 0.2]),),
        (_channel(0, 1, "sig", "t", [1.0, 2.0, 3.0]),),
    )
    assert uniform.axis("t").sampling.status == "known"
    assert uniform.axis("t").sampling.fs_hz == pytest.approx(10.0)

    single = _store(
        (_time_axis("t", "clk", [1.25]),),
        (_channel(0, 1, "sig", "t", [7.0]),),
    )
    assert single.axis("t").sampling.status == "unknown"
    assert single.axis("t").sampling.fs_hz is None

    empty = _store(
        (_time_axis("t", "clk", np.array([], dtype=np.float64)),),
        (_channel(0, 1, "sig", "t", np.array([], dtype=np.float64)),),
    )
    assert empty.axis("t").sampling.status == "unknown"
    assert empty.channel("sig").sample_count == 0

    estimated = _store(
        (_time_axis(
            "t", "clk", [0.0, 0.001, 0.002],
            fs_status="estimated", fs_hz=1000.0,
        ),),
        (_channel(0, 1, "sig", "t", [1.0, 2.0, 3.0]),),
    )
    assert estimated.axis("t").sampling.status == "estimated"
    assert estimated.axis("t").sampling.fs_hz == pytest.approx(1000.0)

    angle = _store(
        (AxisSpec("a", "encoder", "angle", "deg", np.array([0.0, 10.0, 20.0])),),
        (_channel(0, 1, "sig", "a", [1.0, 2.0, 3.0]),),
    )
    assert angle.axis("a").sampling.status == "unknown"
    assert angle.axis("a").sampling.fs_hz is None
    assert angle.axis("a").kind == "angle"


def test_reset_and_duplicate_segments_keep_record_order():
    store = _store(
        (_time_axis("t", "clk", [0.0, 0.0, 1.0, 0.5]),),
        (_channel(0, 1, "sig", "t", [10, 20, 30, 40]),),
    )
    segments = store.axis("t").segments
    assert [(item.start, item.stop) for item in segments] == [(0, 3), (3, 4)]
    assert segments[0].has_duplicate_time is True
    assert store.channel("sig").raw.tolist() == [10, 20, 30, 40]


def test_lifecycle_reports_four_kinds_without_changing_used_bytes():
    time = np.arange(4, dtype=np.float64) * 0.1
    raw_a = np.array([1, 2, 3, 4], dtype=np.int64)
    raw_b = np.array([1.5, 2.5, 3.5, 4.5], dtype=np.float64)
    physical_b = np.array([10.0, 20.0, 30.0, 40.0], dtype=np.float64)
    validity = np.array([True, False, True, True])
    store = _store(
        (_time_axis("t", "clk", time),),
        (
            _channel(0, 1, "counter", "t", raw_a),
            _channel(
                0, 2, "torque", "t", raw_b,
                physical=physical_b, conversion="library", validity=validity,
            ),
        ),
    )
    ledger = store.byte_ledger()
    assert set(ledger) == {"raw", "time", "physical", "validity"}
    assert ledger["time"] == time.nbytes
    assert ledger["raw"] == raw_a.nbytes + raw_b.nbytes
    assert ledger["physical"] == physical_b.nbytes
    assert ledger["validity"] == validity.nbytes

    budget = ImportBudget(ImportLimits(max_memory_bytes=100))
    budget.reserve(40, label="seed")
    tokens = store.report_lifecycle(budget)
    assert budget.used_bytes == 40
    assert len(tokens) == 4
    snapshot = budget.lifecycle_snapshot()
    assert [item.kind for item in snapshot] == ["raw", "time", "physical", "validity"]
    assert [item.nbytes for item in snapshot] == [
        ledger["raw"], ledger["time"], ledger["physical"], ledger["validity"],
    ]
    for token in tokens:
        budget.release_lifecycle(token)
    assert budget.used_bytes == 40
    assert all(item.released for item in budget.lifecycle_snapshot())
    with pytest.raises(Exception) as caught:
        budget.reserve(80, label="more")
    assert caught.value.requested_bytes == 120
    assert budget.used_bytes == 40
    budget.reserve(5, label="after")
    assert budget.used_bytes == 45


def test_build_segments_preserves_order_across_fast_path_blocks():
    from mf4_analyzer.io.native_signal_store import SegmentFact, build_segments

    axis = (np.arange(131080, dtype=np.uint64) + np.uint64(2**63))[::2]
    assert build_segments(axis) == (SegmentFact(0, 0, len(axis), True, False, False),)
    axis[65536] = axis[65535]
    assert build_segments(axis) == (SegmentFact(0, 0, len(axis), True, True, False),)
    axis[65536] -= np.uint64(1)
    assert build_segments(axis) == (
        SegmentFact(0, 0, 65536, True, False, False),
        SegmentFact(1, 65536, len(axis), True, False, False),
    )
    assert build_segments(np.array([np.inf, np.nan, 2.0, 3.0, -np.inf])) == (
        SegmentFact(0, 0, 1, False, False, True),
        SegmentFact(1, 1, 2, False, False, True),
        SegmentFact(2, 2, 4, True, False, False),
        SegmentFact(3, 4, 5, False, False, True),
    )
