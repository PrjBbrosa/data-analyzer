"""HEAD HDF scan-mode time rules, layout rejects, and saved-rate matching."""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.head_hdf import (
    classify_saved_hdf_sampling,
    legacy_simultaneous_dt,
    parse_head_hdf,
)
from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.io.source_adapters import SourceAdapterRegistry, _float_token
from tests._helpers.head_hdf_factory import write_head_hdf


def _channel(name, factor, samples, **extra):
    row = {
        "name": name,
        "factor": factor,
        "quantity": extra.pop("quantity", "acceleration"),
        "unit": extra.pop("unit", "m/s^2"),
        "calibration": 1.0,
        "samples": samples,
    }
    row.update(extra)
    return row


def _write(path, *, channels, n_scans, delta, scan_mode, **kwargs):
    start_of_data = kwargs.pop("start_of_data", 4096)
    return write_head_hdf(
        path,
        channels=channels,
        n_scans=n_scans,
        delta=delta,
        scan_mode=scan_mode,
        start_of_data=start_of_data,
        **kwargs,
    )


def test_simultaneous_dt_ignores_channel_count(tmp_path):
    delta = 1.0 / 24000.0
    n_scans = 8
    one = _write(
        tmp_path / "one.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="simultaneous",
        channels=[_channel("A", 1, np.arange(n_scans, dtype=float))],
    )
    twelve = _write(
        tmp_path / "twelve.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode=" Simultaneous ",
        start_of_data=8192,
        channels=[
            _channel(f"A{i}", 1, np.arange(n_scans, dtype=float) + i)
            for i in range(12)
        ],
    )
    for path in (one, twelve):
        groups = DataLoader.load_hdf(str(path))
        assert len(groups) == 1
        meta = groups[0]["source_metadata"]
        time = groups[0]["data"]["Time"].to_numpy()
        assert meta["sampling_rule"] == "simultaneous"
        assert meta["rule_version"]
        assert meta["dt"] == pytest.approx(delta)
        assert meta["fs"] == pytest.approx(24000.0)
        assert meta["n_samples"] == n_scans
        assert time[1] - time[0] == pytest.approx(delta)
        assert time[-1] == pytest.approx(delta * (n_scans - 1))
        assert meta["n_samples"] * meta["dt"] == pytest.approx(n_scans * delta)
    twelve_meta = DataLoader.load_hdf(str(twelve))[0]["source_metadata"]
    assert twelve_meta["slot_count"] == 12
    assert twelve_meta["fs"] == pytest.approx(24000.0)
    assert twelve_meta["fs"] != pytest.approx(2000.0)


def test_simultaneous_non_unit_factor_does_not_invent_a_rate(tmp_path):
    n_scans = 4
    path = _write(
        tmp_path / "mixed-factor.hdf",
        n_scans=n_scans,
        delta=1e-4,
        scan_mode="simultaneous",
        channels=[
            _channel("Fast", 2, np.arange(n_scans * 2, dtype=float)),
            _channel("Slow", 1, np.arange(n_scans, dtype=float)),
        ],
    )
    with pytest.raises(NotImplementedError, match="simultaneous"):
        parse_head_hdf(path)


def test_synchronised_multiple_keeps_slot_sum_rule_for_mixed_rates(tmp_path):
    n_scans = 10
    factors = (48, 24, 1)
    slot_count = sum(factors)
    delta = 0.001 / slot_count
    path = _write(
        tmp_path / "mix.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="synchronised multiple",
        channels=[
            _channel(f"C{factor}", factor, np.arange(n_scans * factor, dtype=float))
            for factor in factors
        ],
    )
    groups = DataLoader.load_hdf(str(path))
    by_suffix = {group["label_suffix"]: group for group in groups}
    coverage = n_scans * delta * slot_count
    for factor, fs in ((48, 48000.0), (24, 24000.0), (1, 1000.0)):
        group = by_suffix[f"{factor}x"]
        time = group["data"]["Time"].to_numpy()
        assert group["source_metadata"]["fs"] == pytest.approx(fs)
        assert group["source_metadata"]["n_samples"] == n_scans * factor
        assert time[1] - time[0] == pytest.approx(1.0 / fs)
        assert time[-1] == pytest.approx(coverage - 1.0 / fs)


def test_synchronised_multiple_does_not_require_a_unit_factor(tmp_path):
    n_scans = 5
    factors = (48, 24)
    slot_count = sum(factors)
    delta = 0.001 / slot_count
    path = _write(
        tmp_path / "no-slow.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="synchronised multiple",
        channels=[
            _channel("Mic", 48, np.arange(n_scans * 48, dtype=float), quantity="sound pressure", unit="Pa"),
            _channel("Acc", 24, np.arange(n_scans * 24, dtype=float)),
        ],
    )
    groups = DataLoader.load_hdf(str(path))
    rates = sorted(group["source_metadata"]["fs"] for group in groups)
    assert rates == pytest.approx([24000.0, 48000.0])
    assert all(group["source_metadata"]["n_samples"] * group["source_metadata"]["dt"]
               == pytest.approx(n_scans * 0.001) for group in groups)


def test_nonstandard_rate_is_not_snapped(tmp_path):
    delta = 1.0 / 44100.0
    n_scans = 6
    path = _write(
        tmp_path / "cd.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="simultaneous",
        channels=[_channel("Mic", 1, np.arange(n_scans, dtype=float), quantity="sound pressure", unit="Pa")],
    )
    group = DataLoader.load_hdf(str(path))[0]
    assert group["source_metadata"]["fs"] == pytest.approx(44100.0)
    assert group["label_suffix"] == "1x"
    assert group["source_metadata"]["fs"] != pytest.approx(44000.0)
    assert _float_token(group["source_metadata"]["dt"]) == _float_token(delta)


def test_nonzero_and_negative_t0_are_kept(tmp_path):
    delta = 1.0 / 500.0
    n_scans = 4
    path = _write(
        tmp_path / "t0.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="simultaneous",
        first_value=-1.25,
        channels=[_channel("A", 1, np.arange(n_scans, dtype=float))],
    )
    time = DataLoader.load_hdf(str(path))[0]["data"]["Time"].to_numpy()
    np.testing.assert_allclose(time, -1.25 + np.arange(n_scans) * delta)


def test_single_scan_keeps_header_fs_and_t0(tmp_path):
    delta = 1.0 / 12800.0
    path = _write(
        tmp_path / "one-scan.hdf",
        n_scans=1,
        delta=delta,
        scan_mode="simultaneous",
        first_value=3.5,
        channels=[_channel("A", 1, np.array([1.0]))],
    )
    group = DataLoader.load_hdf(str(path))[0]
    fd = FileData(
        str(path), group["data"], group["channels"], group["units"],
        source_metadata=group["source_metadata"],
        channel_metadata=group["channel_metadata"],
        label_suffix=group["label_suffix"],
    )
    assert fd.fs == pytest.approx(12800.0)
    assert fd.fs != pytest.approx(1000.0)
    assert fd.time_array[0] == pytest.approx(3.5)
    assert fd._time_source == "column"


def test_zero_scans_parse_but_do_not_import(tmp_path):
    path = _write(
        tmp_path / "empty.hdf",
        n_scans=0,
        delta=1e-3,
        scan_mode="simultaneous",
        channels=[_channel("A", 1, np.empty(0))],
    )
    parsed = parse_head_hdf(path)
    assert parsed.n_scans == 0
    assert parsed.channels[0].samples.shape == (0,)
    assert parsed.channels[0].fs == pytest.approx(1000.0)
    with pytest.raises(ValueError, match="0 个 scan"):
        DataLoader.load_hdf(str(path))


def test_invalid_delta_and_precision_loss_are_data_errors(tmp_path):
    base = dict(n_scans=4, scan_mode="simultaneous", channels=[
        _channel("A", 1, np.arange(4, dtype=float)),
    ])
    zero = _write(tmp_path / "zero.hdf", delta=0.0, **base)
    with pytest.raises(ValueError, match="delta"):
        parse_head_hdf(zero)
    huge = _write(tmp_path / "huge.hdf", delta=1e-6, first_value=1e16, **base)
    with pytest.raises(ValueError, match="float64"):
        parse_head_hdf(huge)


def test_duplicate_missing_and_unknown_layout_are_explicit(tmp_path):
    path = _write(
        tmp_path / "ok.hdf",
        n_scans=2,
        delta=1e-3,
        scan_mode="synchronised multiple",
        channels=[
            _channel("A", 1, np.arange(2, dtype=float)),
            _channel("B", 1, np.arange(2, dtype=float)),
        ],
    )
    raw = path.read_bytes()
    text = raw[:4096].decode("cp936")
    duplicate = text.replace("ch order:                          1, 2", "ch order:                          1, 1", 1)
    path.write_bytes(duplicate.encode("cp936").ljust(4096, b" ") + raw[4096:])
    with pytest.raises(NotImplementedError, match="重复"):
        parse_head_hdf(path)

    path = _write(
        tmp_path / "mode.hdf",
        n_scans=2,
        delta=1e-3,
        scan_mode="free",
        channels=[_channel("A", 1, np.arange(2, dtype=float))],
    )
    with pytest.raises(NotImplementedError, match="scan mode"):
        parse_head_hdf(path)

    path = _write(
        tmp_path / "release.hdf",
        n_scans=2,
        delta=1e-3,
        scan_mode="simultaneous",
        release="5",
        channels=[_channel("A", 1, np.arange(2, dtype=float))],
    )
    with pytest.raises(NotImplementedError, match="release"):
        parse_head_hdf(path)

    path = _write(
        tmp_path / "unit.hdf",
        n_scans=2,
        delta=1e-3,
        scan_mode="simultaneous",
        absc_unit="ms",
        channels=[_channel("A", 1, np.arange(2, dtype=float))],
    )
    with pytest.raises(NotImplementedError, match="unit"):
        parse_head_hdf(path)


def test_truncated_body_and_unexplained_tail_are_rejected(tmp_path):
    path = _write(
        tmp_path / "body.hdf",
        n_scans=4,
        delta=1e-3,
        scan_mode="simultaneous",
        channels=[_channel("A", 1, np.arange(4, dtype=float))],
    )
    path.write_bytes(path.read_bytes()[:-4])
    with pytest.raises(ValueError, match="截断"):
        parse_head_hdf(path)

    path = _write(
        tmp_path / "tail.hdf",
        n_scans=4,
        delta=1e-3,
        scan_mode="simultaneous",
        channels=[_channel("A", 1, np.arange(4, dtype=float))],
    )
    path.write_bytes(path.read_bytes() + b"\x00EXTRA")
    with pytest.raises(NotImplementedError, match="额外数据"):
        parse_head_hdf(path)


def test_recognized_xml_appendix_is_not_part_of_the_samples(tmp_path):
    path = _write(
        tmp_path / "appendix.hdf",
        n_scans=4,
        delta=1e-3,
        scan_mode="simultaneous",
        channels=[_channel("A", 1, np.arange(4, dtype=float))],
    )
    payload = '<HdfAppendix version="1"><UserDoc /></HdfAppendix>'.encode("utf-16-le")
    tail = f"; xmlAppendix_utf16 {len(payload)} :".encode("ascii") + payload
    path.write_bytes(path.read_bytes() + tail)
    parsed = parse_head_hdf(path)
    np.testing.assert_allclose(parsed.channels[0].samples, np.arange(4, dtype=float))


def test_uint32_slot_is_skipped_without_moving_the_float_group(tmp_path):
    n_scans = 4
    delta = 0.001 / 3
    path = _write(
        tmp_path / "slots.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="synchronised multiple",
        channels=[
            _channel("Mic", 1, np.arange(n_scans, dtype=float)),
            _channel("CAN", 1, np.zeros(n_scans), impl_type="UINT32", quantity="raw", unit=""),
            _channel("Acc", 1, np.arange(n_scans, dtype=float) + 10),
        ],
    )
    groups = DataLoader.load_hdf(str(path))
    assert len(groups) == 1
    group = groups[0]
    assert "CAN" not in group["channels"]
    time = group["data"]["Time"].to_numpy()
    assert time[1] - time[0] == pytest.approx(0.001)
    dropped = group["source_metadata"]["dropped_channels"]
    assert any(item["name"] == "CAN" and "UINT32" in item["reason"] for item in dropped)
    np.testing.assert_allclose(group["data"]["Acc"].to_numpy(), np.arange(n_scans) + 10)


def test_partial_nonfinite_samples_stay_and_are_diagnosed(tmp_path):
    path = _write(
        tmp_path / "finite.hdf",
        n_scans=4,
        delta=1e-3,
        scan_mode="simultaneous",
        channels=[_channel("L", 1, np.zeros(4))],
    )
    bits = np.array([0x7F800001, 0x7FC00000, 0x7F800000, 0xFF800000], dtype="<u4")
    path.write_bytes(path.read_bytes()[:4096] + bits.tobytes())
    with np.errstate(invalid="warn"), pytest.warns(RuntimeWarning, match="invalid value"):
        parsed = parse_head_hdf(path)
    np.testing.assert_array_equal(
        parsed.channels[0].samples, [np.nan, np.nan, np.inf, -np.inf],
    )
    assert any("非有限" in warning for warning in parsed.warnings)


def test_rpm_injection_uses_the_same_rule_and_stays_derived(tmp_path):
    n_scans = 4
    delta = 0.001 / 3
    path = _write(
        tmp_path / "rpm.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="synchronised multiple",
        channels=[
            _channel("Acc", 2, np.arange(n_scans * 2, dtype=float)),
            _channel(
                "SP", 1, np.array([10.0, 20.0, 30.0, 40.0]),
                quantity="speed of rotation", unit="deg/s",
            ),
        ],
    )
    groups = DataLoader.load_hdf(str(path))
    fast = next(group for group in groups if group["label_suffix"] == "2x")
    injected = fast["channel_metadata"]["SP (rpm-injected)"]
    assert injected["injected"] is True
    assert injected["derived"] is True
    assert "sampling_rule" not in injected
    assert fast["data"]["SP (rpm-injected)"].shape == (n_scans * 2,)


def test_simultaneous_group_identity_is_not_the_legacy_scaled_dt(tmp_path):
    delta = 1.0 / 24000.0
    n_scans = 8
    path = _write(
        tmp_path / "id.hdf",
        n_scans=n_scans,
        delta=delta,
        scan_mode="simultaneous",
        channels=[
            _channel("A", 1, np.arange(n_scans, dtype=float)),
            _channel("B", 1, np.arange(n_scans, dtype=float)),
        ],
    )
    loaded = SourceAdapterRegistry.default().adapter_for(path).load_sources(str(path))
    assert len(loaded) == 1
    assert loaded[0].file_data.fs == pytest.approx(24000.0)
    assert _float_token(delta) in loaded[0].group_id
    legacy = legacy_simultaneous_dt(delta, 2, 1)
    assert _float_token(legacy) not in loaded[0].group_id
    assert loaded[0].file_data.get_signal_channels() == ["A", "B"]


def _saved_meta():
    return {
        "sampling_rule": "simultaneous",
        "factor": 1,
        "slot_count": 12,
        "n_scans": 8,
        "n_samples": 8,
        "delta": 1.0 / 24000.0,
        "dt": 1.0 / 24000.0,
        "t0": 0.0,
        "fs": 24000.0,
    }


def test_legacy_simultaneous_rate_matches_only_with_channel_identity():
    meta = _saved_meta()
    channels = {"A": {"raster_factor": 1}, "B": {"raster_factor": 1}}
    saved_fs = 1.0 / legacy_simultaneous_dt(meta["delta"], meta["slot_count"], 1)
    decision = classify_saved_hdf_sampling(
        meta, channels, saved_fs=saved_fs, time_source="column",
        channel_order=["B", "A"],
    )
    assert decision.action == "keep-verified"
    assert "simultaneous" in decision.notice
    assert "未自动缩放" in decision.notice

    mismatched = classify_saved_hdf_sampling(
        meta, channels, saved_fs=saved_fs, time_source="column",
        channel_order=["A"],
    )
    assert mismatched.action == "unproven"

    blocked = classify_saved_hdf_sampling(
        meta, channels, saved_fs=saved_fs, time_source="column",
        channel_order=["A", "B"],
        stored_fingerprint="abc", current_fingerprint="def",
    )
    assert blocked.action == "unproven"

    manual = classify_saved_hdf_sampling(
        meta, channels, saved_fs=800.0, time_source="manual",
        channel_order=["A", "B"],
    )
    assert manual.action == "manual-kept"
    assert "手动采样率" in manual.notice
    assert "未按通道数缩放" in manual.notice

    same = classify_saved_hdf_sampling(
        meta, channels, saved_fs=24000.0, time_source="column",
        channel_order=["A", "B"],
    )
    assert same.action == "apply"
    assert same.notice == ""


def test_other_formats_do_not_use_the_hdf_sampling_hook(tmp_path):
    frame_module = pytest.importorskip("pandas")
    frame = frame_module.DataFrame({"Time": [0.0], "L": [1.0]})
    plain = FileData(str(tmp_path / "plain.csv"), frame, list(frame.columns), {})
    assert plain.fs == pytest.approx(1000.0)
    assert plain.time_array[0] == pytest.approx(0.0)
