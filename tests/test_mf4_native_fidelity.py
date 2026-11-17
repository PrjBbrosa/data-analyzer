"""M0 contracts for native MF4 sampling.

These tests freeze the reviewed byte ledger, the current shared-axis losses,
and the numerical oracles. Pointwise native reads go through
``DataLoader.load_mf4_native``. F08 and F09 check the frozen filter and the
integer-ratio alignment, including a stopband measurement.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

# Review ledger. Literals are the acceptance values; the shared-axis term is
# read back from the production reserver rather than recomputed here.
LEDGER_MEMORY = 498_988_944
LEDGER_OUTPUT = 249_494_472
LEDGER_RECORD = 36_601_314
LEDGER_CATALOG = 2_197_504
LEDGER_SHARED = 599_941_344
LEDGER_REQUESTED = 638_740_162
LEDGER_CYCLES = 471_652
LEDGER_DATA_CHANNELS = 52
# Historical probe of one accident file. Not a product limit.
SAMPLE_SPECIFIC_COUNTS = {"numeric_scalars": 967, "single_point": 915, "excluded": 22}

_DIGEST_PREFIX = b"mf4-native-m0-v1\n"


def content_digest(name, timestamps, samples, invalidation=None) -> str:
    """Stable identity of a human oracle. Independent of the MF4 header clock."""
    hasher = hashlib.sha256()
    hasher.update(_DIGEST_PREFIX)
    hasher.update(str(name).encode())
    hasher.update(b"\n")
    hasher.update(np.asarray(timestamps, dtype="<f8").tobytes())
    hasher.update(b"\n")
    array = np.asarray(samples)
    hasher.update(array.dtype.str.encode())
    hasher.update(b"\n")
    hasher.update(array.tobytes())
    hasher.update(b"\n")
    if invalidation is None:
        hasher.update(b"-")
    else:
        hasher.update(np.asarray(invalidation, dtype=np.uint8).tobytes())
    return hasher.hexdigest()


def _f64(values):
    return np.asarray(values, dtype="<f8")


ORACLES = {
    "grid": {
        "timestamps": _f64([0.0, 0.25, 0.5, 0.75, 1.0]),
        "samples": _f64([1.0, 1.0, 1.0, 1.0, 1.0]),
        "unit": "Nm",
        "digest": "3d03d6e94dbc219ac89b899ea40445361e580e1d3a5dbbc18f1cff98731e1ecf",
        "expect": "参考轴。丢峰反例看 burst，不把这条常值轴当成被丢掉的测量",
    },
    "burst": {
        "timestamps": _f64([0.10, 0.11, 0.12]),
        "samples": _f64([0.0, 100.0, 0.0]),
        "unit": "Nm",
        "digest": "e6a65362a356d116a41770f4c650e5c7858b431102e668256e62e1203a340b66",
        "expect": "公共轴投影后峰 100 消失；native 必须能取回 (0.11 s, 100)",
    },
    "fast": {
        "timestamps": _f64([0.0, 0.25, 0.5, 0.75, 1.0]),
        "samples": _f64([0.0, 1.0, 2.0, 3.0, 4.0]),
        "unit": "Nm",
        "digest": None,
    },
    "slow": {
        "timestamps": _f64([0.0, 5.0, 10.0]),
        "samples": _f64([10.0, 20.0, 30.0]),
        "unit": "Nm",
        "digest": "4f871d33c92d77dabba8857e509e1c5fddfe115dd18b10ceb9a22fcbff10da9f",
        "expect": "t=5 与 t=10 的样本留在原通道；当前公共轴截到参考轴末端",
    },
    "far": {
        "timestamps": _f64([20.0, 21.0, 22.0]),
        "samples": _f64([1.0, 2.0, 3.0]),
        "unit": "Nm",
        "digest": "e22f27677ff576d1ce5412fceaf8d891e435c6b4b36e5e2fabaa711d66127052",
        "expect": "与参考轴无重叠也要保留；当前原因是 no-time-overlap",
    },
    "multi": {
        "timestamps": _f64([0.0, 1.0, 2.0]),
        "samples": _f64([1.0, 2.0, 3.0]),
        "unit": "Nm",
        "digest": None,
    },
    "dot": {
        "timestamps": _f64([1.0]),
        "samples": _f64([9.0]),
        "unit": "Nm",
        "digest": "63a1ba11614390e49f513a81922081b69f8651bc3af631d0b2af51e85731911b",
        "expect": "受支持单点。当前公共轴会丢，native 应恢复，Fs 为 unknown。不为了维持 52 路信号而排除",
    },
    "anchor": {
        "timestamps": _f64([0.0, 1.0, 2.0]),
        "samples": _f64([0.0, 0.0, 0.0]),
        "unit": "Nm",
        "digest": None,
    },
    "other": {
        "timestamps": _f64([0.0, 1.0, 3.0]),
        "samples": _f64([0.0, 0.0, 30.0]),
        "unit": "Nm",
        "digest": "ab44e09227b68613618321d0b76cf4070bc6966002d407a6495afdcb8af68bb0",
        "expect": "点数相同不是同步。原时间 3 s 处的 30 必须留下，不能插值成 2 s 处的 15",
    },
    "dup_axis": {
        "timestamps": _f64([0.0, 1.0, 2.0, 3.0]),
        "samples": _f64([0.0, 0.0, 0.0, 0.0]),
        "unit": "s",
        "digest": None,
    },
    "dup": {
        "timestamps": _f64([0.0, 1.0, 1.0, 2.0]),
        "samples": _f64([1.0, 2.0, 9.0, 4.0]),
        "unit": "Nm",
        "digest": "57ab7dee0112105b625ca67b8fc28109811fdfff51b998431b3a4a3c95fa3e7e",
        "expect": "重复时间两笔都保留，按记录序号区分。当前公共轴只留最后一笔 9",
    },
    "reset": {
        "timestamps": _f64([0.0, 2.0, 1.0]),
        "samples": _f64([1.0, 2.0, 3.0]),
        "unit": "Nm",
        "digest": "629c5b8163b7b2b46525b7bde22914d9d704d33e6ef806ec93ddaaee04764e80",
        "expect": "时间回退保持记录顺序，不排序拼接。当前整文件被拒绝",
    },
    "flagged": {
        "timestamps": _f64([0.0, 0.1, 0.2, 0.3]),
        "samples": _f64([10.0, 20.0, 30.0, 40.0]),
        "invalidation": np.array([0, 1, 0, 1], dtype=np.uint8),
        "unit": "Nm",
        "digest": "0665eaaf82313af7cc7c2ba0b8ca1caf7d3bf76cf163614075f95b0207bb1c6d",
        "expect": "失效样本留在原序号。掩码以原始 get 的返回数组为准",
    },
    "wide": {
        "timestamps": _f64([0.0, 1.0, 2.0]),
        "samples": np.array([1, 2**53 + 3, 5], dtype="<i8"),
        "unit": "count",
        "digest": "8e4058662f06728b8a7c8b601790139f1a2da487d77c585742a4d619664d3836",
        "expect": "超过 2^53 的整数不能先经 float64。中间样本必须仍是 2**53+3",
    },
}


def _check_digest(name):
    spec = ORACLES[name]
    if spec["digest"] is None:
        return
    got = content_digest(
        name, spec["timestamps"], spec["samples"], spec.get("invalidation"),
    )
    assert got == spec["digest"]


def _write_groups(path, groups):
    from asammdf import MDF, Signal

    mdf = MDF(version="4.10")
    for group in groups:
        signals = []
        for name in group:
            spec = ORACLES[name]
            kwargs = {}
            if "invalidation" in spec:
                kwargs["invalidation_bits"] = spec["invalidation"]
            signals.append(Signal(
                samples=np.asarray(spec["samples"]),
                timestamps=np.asarray(spec["timestamps"], dtype=float),
                name=name,
                unit=spec["unit"],
                **kwargs,
            ))
        mdf.append(signals)
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def _load(path):
    from mf4_analyzer.io.loader import DataLoader

    frame, channels, _units = DataLoader.load_mf4(str(path))
    return frame, channels


def _skipped(frame):
    return frame.attrs["source_metadata"]["skipped_channels"]


def _native_series(path, channel, *, representation="physical"):
    """Planned M1 entry. A missing function is the unimplemented contract."""
    try:
        from mf4_analyzer.io.loader import DataLoader
        from mf4_analyzer.io.signal_access import read_signal
    except ImportError as exc:
        pytest.fail(f"native 取数未实现，不能用公共轴结果代替: {exc}")
    load = getattr(DataLoader, "load_mf4_native", None)
    if not callable(load):
        pytest.fail("DataLoader.load_mf4_native 未实现")
    loaded = load(str(path))
    source = loaded[0] if isinstance(loaded, tuple) else loaded
    series = read_signal(source, channel, representation=representation)
    if not hasattr(series, "time") or not hasattr(series, "values"):
        pytest.fail("SignalSeries 没有 time/values")
    return series


def _assert_native_samples(path, channel, *, representation="physical"):
    spec = ORACLES[channel]
    series = _native_series(path, channel, representation=representation)
    assert np.array_equal(np.asarray(series.time, dtype=float), np.asarray(spec["timestamps"], dtype=float))
    assert np.array_equal(np.asarray(series.values), np.asarray(spec["samples"]))
    return series


# --- ledger and current shared-axis facts ---------------------------------


def test_reviewed_ledger_refuses_at_the_injected_budget():
    """Anonymous stand-in for the review table. Production code charges the shared axis."""
    from types import SimpleNamespace

    from asammdf.blocks import v4_constants as c

    from mf4_analyzer.io.import_limits import ImportBudget, ImportLimits, ImportResourceError
    from mf4_analyzer.io.mdf_reader import _reserve_shared_output

    output_cap = LEDGER_MEMORY // 2
    assert output_cap == LEDGER_OUTPUT
    assert output_cap <= LEDGER_OUTPUT
    limits = ImportLimits(max_memory_bytes=LEDGER_MEMORY, max_output_bytes=output_cap)
    untouched = ImportLimits()
    assert untouched.max_memory_bytes == 512 * 1024**2
    assert untouched.max_output_bytes == 256 * 1024**2
    assert untouched.max_channels == 100_000
    assert untouched.max_channels > LEDGER_DATA_CHANNELS
    assert untouched.max_channels > SAMPLE_SPECIFIC_COUNTS["numeric_scalars"]

    def channel(*, master):
        return SimpleNamespace(
            data_type=0,
            channel_type=c.CHANNEL_TYPE_MASTER if master else 0,
            sync_type=c.SYNC_TYPE_TIME if master else 0,
        )

    group = SimpleNamespace(
        channels=[channel(master=True), *[channel(master=False) for _ in range(LEDGER_DATA_CHANNELS)]],
        channel_dependencies=[None] * (LEDGER_DATA_CHANNELS + 1),
        channel_group=SimpleNamespace(cycles_nr=LEDGER_CYCLES),
    )
    budget = ImportBudget(limits)
    budget.reserve(LEDGER_RECORD, label="MDF record buffers")
    budget.reserve(LEDGER_CATALOG, label="MDF channel metadata/array expansion")
    with pytest.raises(ImportResourceError) as caught:
        _reserve_shared_output(SimpleNamespace(groups=[group]), budget)
    error = caught.value
    assert budget.used_bytes == LEDGER_RECORD + LEDGER_CATALOG
    assert error.requested_bytes == LEDGER_REQUESTED
    assert error.limit_bytes == LEDGER_MEMORY
    assert error.resource_kind == "memory_estimate"
    assert error.unit == "bytes"
    assert error.phase == "mdf_shared_axis"
    assert [item.amount for item in error.components] == [
        LEDGER_RECORD, LEDGER_CATALOG, LEDGER_SHARED,
    ]
    assert sum(item.amount for item in error.components) == LEDGER_REQUESTED
    assert limits.max_output_bytes <= LEDGER_OUTPUT


def test_oracle_content_hashes_match_the_human_arrays():
    for name, spec in ORACLES.items():
        if spec["digest"] is None:
            continue
        _check_digest(name)
        assert "expect" in spec


def test_public_axis_drops_the_interior_peak(tmp_path):
    _check_digest("burst")
    path = _write_groups(tmp_path / "peak.mf4", [("grid",), ("burst",)])
    frame, channels = _load(path)
    assert "burst" in channels
    assert float(np.max(np.abs(frame["burst"].to_numpy(dtype=float)))) == pytest.approx(0.0)
    assert 0.11 not in set(np.round(frame["Time"].to_numpy(dtype=float), 2))


def test_public_axis_drops_samples_past_the_reference(tmp_path):
    _check_digest("slow")
    path = _write_groups(tmp_path / "long.mf4", [("fast",), ("slow",)])
    frame, channels = _load(path)
    assert "slow" in channels
    assert float(frame["Time"].max()) == pytest.approx(1.0)
    assert not np.any(np.isclose(frame["Time"].to_numpy(dtype=float), 10.0))


def test_public_axis_skips_a_nonoverlapping_channel(tmp_path):
    _check_digest("far")
    path = _write_groups(tmp_path / "apart.mf4", [("fast",), ("far",)])
    frame, channels = _load(path)
    assert "far" not in channels
    assert {"name": "far", "reason": "no-time-overlap"} in _skipped(frame)


def test_public_axis_drops_a_supported_single_point(tmp_path):
    """The ledger's 52 channels are a shared-axis count, not a reason to drop dots."""
    _check_digest("dot")
    path = _write_groups(tmp_path / "dots.mf4", [("multi",), ("dot",)])
    frame, channels = _load(path)
    assert "dot" not in channels
    assert {"name": "dot", "reason": "single-sample"} in _skipped(frame)
    assert LEDGER_DATA_CHANNELS != 1


def test_equal_length_clocks_are_interpolated(tmp_path):
    _check_digest("other")
    path = _write_groups(tmp_path / "shift.mf4", [("anchor",), ("other",)])
    frame, channels = _load(path)
    assert "other" in channels
    row = frame.loc[np.isclose(frame["Time"], 2.0)].iloc[0]
    assert row["other"] == pytest.approx(15.0)
    assert not np.any(np.isclose(frame["Time"].to_numpy(dtype=float), 3.0))


def test_public_axis_keeps_only_the_last_duplicate(tmp_path):
    _check_digest("dup")
    path = _write_groups(tmp_path / "dup.mf4", [("dup_axis",), ("dup",)])
    frame, _channels = _load(path)
    row = frame.loc[np.isclose(frame["Time"], 1.0)].iloc[0]
    assert row["dup"] == pytest.approx(9.0)
    assert not np.any(np.isclose(frame["dup"].to_numpy(dtype=float), 2.0))


def test_public_axis_rejects_a_clock_reset(tmp_path):
    _check_digest("reset")
    path = _write_groups(tmp_path / "reset.mf4", [("reset",)])
    with pytest.raises(ValueError, match="reset"):
        _load(path)


def test_invalidation_semantics_come_from_the_raw_api(tmp_path):
    """Do not infer the mask from the parameter name ``ignore_invalidation_bits``."""
    from asammdf import MDF
    from asammdf.blocks import v4_constants as c

    _check_digest("flagged")
    path = _write_groups(tmp_path / "flags.mf4", [("flagged",)])
    with MDF(str(path)) as src:
        signal = src.groups[0].channels[1]
        present = c.FLAG_CN_INVALIDATION_PRESENT
        named = c.FLAG_INVALIDATION_BIT_VALID
        assert present == named and present != 0
        assert signal.flags & present == present
        dropped = src.get(group=0, index=1, raw=True, ignore_invalidation_bits=False)
        kept = src.get(group=0, index=1, raw=True, ignore_invalidation_bits=True)
        dropped_only = src.get(
            group=0, index=1, raw=True, samples_only=True, ignore_invalidation_bits=False,
        )
        kept_only = src.get(
            group=0, index=1, raw=True, samples_only=True, ignore_invalidation_bits=True,
        )
    assert int(dropped.flags) == 0
    assert int(kept.flags) == 0
    assert np.allclose(dropped.samples, [10.0, 30.0])
    assert np.allclose(dropped.timestamps, [0.0, 0.2])
    assert dropped.invalidation_bits is None
    assert np.allclose(dropped_only[0], [10.0, 30.0])
    assert dropped_only[1] is None
    assert np.allclose(kept.samples, [10.0, 20.0, 30.0, 40.0])
    assert np.allclose(kept.timestamps, [0.0, 0.1, 0.2, 0.3])
    assert np.array_equal(np.asarray(kept.invalidation_bits), [False, True, False, True])
    assert np.array_equal(np.asarray(kept_only[1]), [False, True, False, True])
    frame, _channels = _load(path)
    assert not np.any(np.isclose(frame["flagged"].to_numpy(dtype=float), 20.0))
    assert not np.any(np.isclose(frame["flagged"].to_numpy(dtype=float), 40.0))


def test_shared_axis_cannot_keep_an_integer_past_the_mantissa(tmp_path):
    from asammdf import MDF

    _check_digest("wide")
    path = _write_groups(tmp_path / "wide.mf4", [("wide",)])
    with MDF(str(path)) as src:
        raw = src.get("wide", raw=True, ignore_invalidation_bits=True)
    assert raw.samples.dtype.kind == "i"
    assert int(raw.samples[1]) == 2**53 + 3
    frame, _channels = _load(path)
    loaded = frame["wide"].to_numpy(dtype=float)[1]
    assert loaded == pytest.approx(9007199254740996.0)
    assert int(loaded) != 2**53 + 3


def test_same_axis_control_is_unchanged(tmp_path):
    from asammdf import MDF, Signal

    count = 32
    timestamps = np.arange(count, dtype=float) / 32.0
    mdf = MDF(version="4.10")
    signals = []
    for index in range(4):
        signals.append(Signal(
            samples=np.full(count, index + 1.0),
            timestamps=timestamps,
            name=f"ch{index}",
            unit="Nm",
        ))
    mdf.append(signals)
    path = tmp_path / "same.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    frame, channels = _load(path)
    assert channels[0] == "Time"
    for index in range(4):
        assert frame[f"ch{index}"].tolist() == pytest.approx([index + 1.0] * count)


def test_multi_rate_short_channels_are_stretched(tmp_path):
    from asammdf import MDF, Signal

    mdf = MDF(version="4.10")
    long_t = np.arange(32, dtype=float) / 32.0
    mdf.append([Signal(np.zeros(32), long_t, name="long", unit="Nm")])
    for index in range(3):
        short_t = np.linspace(0.0, 0.5, 4)
        mdf.append([Signal(np.full(4, index + 1.0), short_t, name=f"short{index}", unit="Nm")])
    path = tmp_path / "rates.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    frame, channels = _load(path)
    assert len(frame) == 32
    assert all(f"short{index}" in channels for index in range(3))
    assert len(frame) != 4


def test_dense_single_points_are_all_skipped(tmp_path):
    from asammdf import MDF, Signal

    mdf = MDF(version="4.10")
    timestamps = np.arange(16, dtype=float)
    mdf.append([Signal(np.arange(16, dtype=float), timestamps, name="wave", unit="Nm")])
    for index in range(8):
        mdf.append([Signal(
            np.array([100.0 + index]),
            np.array([float(index)]),
            name=f"dot{index}",
            unit="Nm",
        )])
    path = tmp_path / "dense.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    frame, channels = _load(path)
    skipped = {item["name"] for item in _skipped(frame)}
    for index in range(8):
        assert f"dot{index}" not in channels
        assert f"dot{index}" in skipped
    assert "wave" in channels


def test_existing_fft_core_meets_the_frozen_sine_gate():
    from mf4_analyzer.signal.fft import one_sided_amplitude

    fs = 1024.0
    count = 1024
    tone = 32.0
    time = np.arange(count) / fs
    samples = np.sin(2.0 * np.pi * tone * time)
    freq, amp = one_sided_amplitude(samples, fs, win="hanning", remove_mean=True)
    again_freq, again_amp = one_sided_amplitude(samples, fs, win="hanning", remove_mean=True)
    np.testing.assert_array_equal(freq, again_freq)
    np.testing.assert_array_equal(amp, again_amp)
    peak = int(np.argmax(amp))
    bin_hz = fs / count
    assert abs(freq[peak] - tone) <= bin_hz
    assert abs(amp[peak] - 1.0) / 1.0 <= 0.01


def test_existing_frf_core_meets_the_frozen_band_gate():
    from mf4_analyzer.signal.frf import FrfParams, compute_frf

    fs = 1000.0
    count = 8000
    tones = (50.0, 80.0, 120.0, 180.0, 250.0, 300.0)
    gain = 2.0
    delay = 4
    time = np.arange(count) / fs
    stimulus = np.sum([np.sin(2.0 * np.pi * tone * time) for tone in tones], axis=0)
    response = gain * np.roll(stimulus, delay)
    low = 0.05 * fs
    high = 0.30 * fs
    assert all(low <= tone <= high for tone in tones)
    for estimator in ("h1", "h2"):
        params = FrfParams(
            estimator=estimator,
            t_win_s=1.0,
            overlap=0.0,
            window="hanning",
            detrend="none",
            periodic_window=True,
        )
        result = compute_frf(
            stimulus, response, fs=fs, params=params, input_time=time, output_time=time,
        )
        for tone in tones:
            index = int(np.argmin(np.abs(result.frequencies - tone)))
            transfer = result.transfer[index]
            gain_error = abs(20.0 * np.log10(np.abs(transfer)) - 20.0 * np.log10(gain))
            phase = np.degrees(np.angle(transfer))
            expected = -360.0 * tone * delay / fs
            phase_error = abs((phase - expected + 180.0) % 360.0 - 180.0)
            assert result.coherence[index] >= 0.99
            assert gain_error <= 0.1
            assert phase_error <= 1.0


def test_standard_plot_load_budget_is_not_allocated():
    samples = 1_188_000
    curves = 6
    shared_time_bytes = (curves + 1) * samples * 8
    assert shared_time_bytes == 66_528_000
    assert samples > 0 and curves == 6


# --- unimplemented native pointwise contracts ------------------------------


def test_native_recovers_interior_peak(tmp_path):
    path = _write_groups(tmp_path / "peak.mf4", [("grid",), ("burst",)])
    _assert_native_samples(path, "burst")


def test_native_keeps_long_range_samples(tmp_path):
    path = _write_groups(tmp_path / "long.mf4", [("fast",), ("slow",)])
    _assert_native_samples(path, "slow")


def test_native_keeps_nonoverlapping_channel(tmp_path):
    path = _write_groups(tmp_path / "apart.mf4", [("fast",), ("far",)])
    _assert_native_samples(path, "far")


def test_native_keeps_multi_rate_lengths(tmp_path):
    from asammdf import MDF, Signal

    mdf = MDF(version="4.10")
    long_t = np.arange(32, dtype=float) / 32.0
    mdf.append([Signal(np.zeros(32), long_t, name="long", unit="Nm")])
    short_t = np.linspace(0.0, 0.5, 4)
    mdf.append([Signal(np.ones(4), short_t, name="short0", unit="Nm")])
    path = tmp_path / "rates.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    series = _native_series(path, "short0")
    assert np.asarray(series.values).shape == (4,)
    assert np.allclose(np.asarray(series.time, dtype=float), short_t)
    assert np.allclose(np.asarray(series.values, dtype=float), 1.0)


def test_native_keeps_every_dense_single_point(tmp_path):
    from asammdf import MDF, Signal

    mdf = MDF(version="4.10")
    timestamps = np.arange(16, dtype=float)
    mdf.append([Signal(np.arange(16, dtype=float), timestamps, name="wave", unit="Nm")])
    for index in range(8):
        mdf.append([Signal(
            np.array([100.0 + index]),
            np.array([float(index)]),
            name=f"dot{index}",
            unit="Nm",
        )])
    path = tmp_path / "dense.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    for index in range(8):
        series = _native_series(path, f"dot{index}")
        assert np.asarray(series.values).shape == (1,)
        assert float(np.asarray(series.values, dtype=float)[0]) == pytest.approx(100.0 + index)
        assert series.sampling.state == "unknown"


def test_native_keeps_single_point_with_unknown_fs(tmp_path):
    path = _write_groups(tmp_path / "dots.mf4", [("multi",), ("dot",)])
    series = _assert_native_samples(path, "dot")
    assert series.sampling.state == "unknown"
    assert series.sampling.fs is None


def test_native_equal_length_is_not_synchrony(tmp_path):
    path = _write_groups(tmp_path / "shift.mf4", [("anchor",), ("other",)])
    _assert_native_samples(path, "other")


def test_native_keeps_duplicate_timestamps(tmp_path):
    path = _write_groups(tmp_path / "dup.mf4", [("dup_axis",), ("dup",)])
    _assert_native_samples(path, "dup")


def test_native_keeps_clock_reset_order(tmp_path):
    path = _write_groups(tmp_path / "reset.mf4", [("reset",)])
    _assert_native_samples(path, "reset")


def test_native_keeps_invalidation_positions(tmp_path):
    path = _write_groups(tmp_path / "flags.mf4", [("flagged",)])
    series = _assert_native_samples(path, "flagged")
    assert np.array_equal(
        np.asarray(series.invalidation_bits).astype(bool),
        [False, True, False, True],
    )


def test_native_keeps_int64_above_the_mantissa(tmp_path):
    path = _write_groups(tmp_path / "wide.mf4", [("wide",)])
    series = _native_series(path, "wide", representation="raw")
    assert int(np.asarray(series.values)[1]) == 2**53 + 3


def test_native_uniform_fft_uses_original_samples(tmp_path):
    from asammdf import MDF, Signal

    from mf4_analyzer.signal.fft import one_sided_amplitude

    fs = 1024.0
    count = 1024
    tone = 32.0
    time = np.arange(count) / fs
    samples = np.sin(2.0 * np.pi * tone * time)
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=samples, timestamps=time, name="sine", unit="Nm")])
    path = tmp_path / "sine.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    series = _native_series(path, "sine")
    native = np.asarray(series.values, dtype=float)
    np.testing.assert_allclose(native, samples)
    core_freq, core_amp = one_sided_amplitude(samples, fs, win="hanning", remove_mean=True)
    native_freq, native_amp = one_sided_amplitude(native, fs, win="hanning", remove_mean=True)
    np.testing.assert_array_equal(native_freq, core_freq)
    np.testing.assert_array_equal(native_amp, core_amp)
    peak = int(np.argmax(core_amp))
    assert abs(core_freq[peak] - tone) <= fs / count


def test_native_antialias_suppresses_a_stopband_tone():
    from mf4_analyzer.analysis_signal_prepare import (
        frozen_antialias_design, prepare_signal,
    )

    design = frozen_antialias_design()
    required = {"order", "cutoff_ratio", "padding", "delay_compensation", "edge_samples"}
    assert not required.difference(design)
    assert float(design["stopband_db"]) >= 60.0
    source_fs = 4000.0
    time = np.arange(4000) / source_fs
    tone = np.sin(2.0 * np.pi * 1500.0 * time)
    prepared = prepare_signal(
        tone, time, fs=source_fs, policy="native", intent="explicit_uniform",
        value_kind="continuous", target_fs=500.0, origin=0.0,
    )
    assert prepared.status == "ready"
    stop_rms = float(np.sqrt(np.mean(np.square(prepared.values))))
    source_rms = float(np.sqrt(np.mean(np.square(tone))))
    assert 20.0 * np.log10(stop_rms / source_rms) <= -60.0


def test_native_cross_rate_alignment_keeps_an_inband_gain():
    from mf4_analyzer.analysis_signal_prepare import (
        frozen_frf_alignment, prepare_pair,
    )
    from mf4_analyzer.signal.frf import FrfParams, compute_frf

    design = frozen_frf_alignment()
    required = {"origin", "ratio", "fractional_delay", "edge_policy", "min_input_fs_band"}
    assert not required.difference(design)
    assert design["min_input_fs_band"] == (0.05, 0.30)
    assert design["fractional_delay"] == "unsupported"
    left_fs = 2000.0
    right_fs = 1000.0
    left_time = np.arange(4000) / left_fs
    right_time = np.arange(2000) / right_fs
    tone = 80.0
    stimulus = np.sin(2.0 * np.pi * tone * left_time)
    response = 2.0 * np.sin(2.0 * np.pi * tone * right_time)
    prepared = prepare_pair(
        stimulus, left_time, response, right_time,
        left_fs=left_fs, right_fs=right_fs, policy="native",
        align_then_compute=True,
    )
    assert prepared.status == "ready"
    params = FrfParams(
        estimator="h1", t_win_s=0.5, overlap=0.0, nfft_mode="auto",
        window="hanning", periodic_window=True, detrend="none",
    )
    result = compute_frf(
        prepared.left.values, prepared.right.values, fs=right_fs, params=params,
        input_time=prepared.left.time, output_time=prepared.right.time,
    )
    band = (result.coherence >= 0.99) & (result.frequencies >= 50.0) & (result.frequencies <= 120.0)
    assert np.any(band)
    gain_db = 20.0 * np.log10(np.abs(result.transfer[band]))
    phase = np.angle(result.transfer[band], deg=True)
    assert np.max(np.abs(gain_db - 20.0 * np.log10(2.0))) <= 0.1
    assert np.max(np.abs(phase)) <= 1.0
