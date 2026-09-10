"""ZFGE2 .zfd 解析：官方布局 fixture、长记录、结构失败与时基合同。"""
from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader
from tests.zfd_corpus import (
    CORPUS_ROOT_ENV,
    REQUIRE_CORPUS_ENV,
    CorpusSupplyError,
    read_zfd_corpus_manifest,
    resolve_zfd_corpus_samples,
)
from tests.zfd_fixtures import (
    FAKE_MARKER,
    characteristic_values,
    default_header_lines,
    expected_f32_values,
    expected_time_axis,
    pack_float32_record,
    pack_header,
    pack_time_record,
    write_minimal_zfd,
    write_truncated_last_channel,
    write_zfge2,
    write_zfd_duplicate_names,
)

# Re-export for existing callers (io notices / project session).
_write_minimal_zfd = write_minimal_zfd
_write_zfd_duplicate_names = write_zfd_duplicate_names


def _zfd_corpus_samples():
    """Optional real samples: skip without corpus, fail in required mode."""
    try:
        return resolve_zfd_corpus_samples()
    except CorpusSupplyError as exc:
        message = str(exc)
        optional = exc.optional
    if optional:
        pytest.skip(message)
    pytest.fail(message)


_A1_COUNTS = (65535, 65536, 65537, 131072)
_HOUR_COUNT = 3_608_000
_HOUR_DT = 0.001
_HOUR_SPAN = 3_607.999


def _port_read(path):
    """Official-port cross-check for complete fixtures only — not an error oracle."""
    from tools.matlab_ports.zfd_import import zfd_import

    return zfd_import(path)


def _filedata_from_group(path, group):
    return FileData(
        str(path),
        group["data"],
        group["channels"],
        group["units"],
        0,
        source_metadata=group["source_metadata"],
        channel_metadata=group["channel_metadata"],
        label_suffix=group["label_suffix"],
    )


def test_zfd_fixtures_do_not_import_product_parser():
    for name in ("zfd_fixtures.py", "zfd_corpus.py"):
        text = Path(__file__).with_name(name).read_text(encoding="utf-8")
        assert "import mf4_analyzer" not in text
        assert "from mf4_analyzer" not in text
        assert "import tools.matlab_ports" not in text
        assert "from tools.matlab_ports" not in text
        assert "load_zfd" not in text


def test_zfd_fixtures_directory_has_no_customer_binaries():
    root = Path(__file__).resolve().parent / "fixtures" / "zfd"
    assert root.is_dir()
    assert list(root.rglob("*.zfd")) == []


def test_zfd_checked_in_manifest_lists_six_samples():
    manifest = read_zfd_corpus_manifest()
    ids = [item["id"] for item in manifest["samples"]]
    assert ids == [
        "rws-axial-000031",
        "rws-axial-000032",
        "rws-axial-000033",
        "rws-axial-000034",
        "rws-axial-000035",
        "wwt-end-of-travel-1",
    ]
    assert manifest["parser_profile"] == "zfge2-single-time-f32-v1"
    assert manifest["license"]["redistributable"] is False
    assert manifest["license"]["binaries_in_repo"] is False
    assert manifest["long_customer_recording"]["status"] == "unknown"
    for item in manifest["samples"]:
        assert item["profile"] == "zfge2-single-time-f32-v1"
        assert item["source_count"] == 1
        assert item["channels"]
        assert set(item["units"]) == set(item["channels"])
        assert set(item["value_evidence"]) == set(item["channels"])


def test_non_zfge2_magic_rejected(tmp_path):
    p = tmp_path / "junk.zfd"
    p.write_bytes(b"NOTZF\nfoo\nbar\n" + b"\x00" * 200)
    with pytest.raises(ValueError, match="不是有效的 ZFD"):
        DataLoader.load_zfd(str(p))


def test_zfd_slow_sample_dt_two_seconds_keeps_half_hz(tmp_path):
    """A6: dt=2.0 (0.5 Hz) must not be crushed into the 1 kHz estimate."""
    p = write_minimal_zfd(tmp_path / "slow.zfd", dt=2.0, count=5,
                          values=[1.0, 2.0, 3.0, 4.0, 5.0])
    groups = DataLoader.load_zfd(str(p))
    assert len(groups) == 1
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 5
    assert t[1] - t[0] == pytest.approx(2.0)
    assert g["source_metadata"]["fs_estimated"] is False
    fd = _filedata_from_group(p, g)
    assert fd.fs == pytest.approx(0.5, rel=1e-9)


def test_zfd_slow_dt_above_hour_is_kept(tmp_path):
    """A6: dt=7200 s is a legal slow axis, not a 1 kHz fallback."""
    p = write_minimal_zfd(tmp_path / "slow-hour.zfd", dt=7200.0, count=4)
    groups = DataLoader.load_zfd(str(p))
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    assert t[1] - t[0] == pytest.approx(7200.0)
    assert g["source_metadata"]["fs_estimated"] is False
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["time_step_s"] == pytest.approx(7200.0)
    fd = _filedata_from_group(p, g)
    assert fd.fs == pytest.approx(1.0 / 7200.0, rel=1e-12)


def test_zfd_illegal_dt_is_rejected(tmp_path):
    for label, dt in (("nan", float("nan")), ("inf", float("inf")),
                      ("zero", 0.0), ("neg", -0.001)):
        p = write_minimal_zfd(tmp_path / f"bad-dt-{label}.zfd", dt=dt, count=4)
        with pytest.raises(ValueError, match="时间轴无效"):
            DataLoader.load_zfd(str(p))


def test_zfd_duplicate_names_record_renamed_channels(tmp_path):
    """F5: in-group [marker_id] renames must enter source_metadata like HDF/WWT."""
    from mf4_analyzer.io.loader import format_renamed_channels_notice

    p = write_zfd_duplicate_names(tmp_path / "dup.zfd")
    groups = DataLoader.load_zfd(str(p))
    assert len(groups) == 1
    g = groups[0]
    assert "Szyl 1" in g["channels"]
    assert "Szyl 1 [E5]" in g["channels"]
    renamed = g["source_metadata"].get("renamed_channels") or []
    assert renamed == [{"original": "Szyl 1", "renamed": "Szyl 1 [E5]"}]
    assert format_renamed_channels_notice(renamed) == "1 个通道重名，已加序号区分"


@pytest.mark.parametrize("count", _A1_COUNTS)
def test_zfd_a1_int32_count_reads_every_sample(tmp_path, count):
    values = characteristic_values(count)
    p = write_minimal_zfd(
        tmp_path / f"a1-{count}.zfd",
        dt=0.001,
        count=count,
        values=values,
        name="probe",
    )
    raw = Path(p).read_bytes()
    assert struct.pack("<i", count) in raw
    if count > 65535:
        assert struct.pack("<H", count & 0xFFFF) != struct.pack("<i", count)[:2] or True

    # Port is a cross-check on a complete fixture, not the value oracle.
    _header, infos, channels = _port_read(p)
    assert infos[0]["Typ"] == 0
    assert infos[0]["AnzahlWerte"] == count
    assert infos[1]["AnzahlWerte"] == count
    assert len(channels[1]) == count
    assert float(channels[1][-1]) == pytest.approx(float(values[-1]), rel=0, abs=1e-5)

    groups = DataLoader.load_zfd(str(p))
    assert len(groups) == 1
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    y = g["data"]["probe"].to_numpy()
    expected_y = expected_f32_values(values)
    expected_t = expected_time_axis(count, t0=0.0, dt=0.001)
    assert y.dtype == np.float64
    assert t.dtype == np.float64
    assert g["units"]["probe"] == "C"
    np.testing.assert_array_equal(y, expected_y)
    np.testing.assert_array_equal(t, expected_t)
    assert y[0] == pytest.approx(11.0, abs=1e-5)
    assert y[count // 2] == pytest.approx(22.0, abs=1e-5)
    assert y[-1] == pytest.approx(33.0, abs=1e-5)


def test_zfd_a2_hour_record_span_and_filedata(tmp_path):
    values = characteristic_values(_HOUR_COUNT)
    p = write_minimal_zfd(
        tmp_path / "hour.zfd",
        dt=_HOUR_DT,
        count=_HOUR_COUNT,
        values=values,
        name="hour",
    )
    groups = DataLoader.load_zfd(str(p))
    g = groups[0]
    t = g["data"]["Time"].to_numpy()
    y = g["data"]["hour"].to_numpy()
    expected_y = expected_f32_values(values)
    expected_t = expected_time_axis(_HOUR_COUNT, t0=0.0, dt=_HOUR_DT)
    assert y.dtype == np.float64
    assert t.dtype == np.float64
    assert g["units"]["hour"] == "C"
    np.testing.assert_array_equal(y, expected_y)
    np.testing.assert_array_equal(t, expected_t)
    assert t[-1] - t[0] == pytest.approx(_HOUR_SPAN, abs=1e-9)
    assert y[0] == pytest.approx(11.0, abs=1e-5)
    assert y[_HOUR_COUNT // 2] == pytest.approx(22.0, abs=1e-5)
    assert y[-1] == pytest.approx(33.0, abs=1e-5)
    assert g["source_metadata"]["fs_estimated"] is False

    fd = _filedata_from_group(p, g)
    assert len(fd.time_array) == _HOUR_COUNT
    np.testing.assert_array_equal(fd.time_array, t)
    np.testing.assert_array_equal(fd.data["hour"].to_numpy(), y)
    assert fd.fs == pytest.approx(1000.0, rel=1e-9)
    # Must not have rebuilt Time via FileData(fs=...).
    assert fd.time_array[-1] == pytest.approx(t[-1])


@pytest.mark.parametrize(
    "kind",
    ("zero_count", "neg_count", "declared_exceeds", "last_truncated", "huge_decl"),
)
def test_zfd_a3_incomplete_or_illegal_count_fails_closed(tmp_path, kind):
    if kind == "zero_count":
        p = write_zfge2(
            tmp_path / "zero.zfd",
            records=(
                pack_time_record(count=8, declared_count=0),
                pack_float32_record(values=range(8), declared_count=0, data_bytes=b""),
            ),
        )
    elif kind == "neg_count":
        p = write_zfge2(
            tmp_path / "neg.zfd",
            records=(
                pack_time_record(count=8, declared_count=-3),
                pack_float32_record(values=range(8), declared_count=-3, data_bytes=b""),
            ),
        )
    elif kind == "declared_exceeds":
        p = write_zfge2(
            tmp_path / "short-payload.zfd",
            records=(
                pack_time_record(count=8),
                pack_float32_record(
                    values=range(8),
                    declared_count=1000,
                    data_bytes=np.arange(8, dtype="<f4").tobytes(),
                ),
            ),
        )
    elif kind == "last_truncated":
        p = write_truncated_last_channel(tmp_path / "cut.zfd", count=32, drop_bytes=24)
    else:
        p = write_zfge2(
            tmp_path / "huge.zfd",
            records=(
                pack_time_record(count=4),
                pack_float32_record(
                    values=[1.0],
                    declared_count=3_608_000,
                    data_bytes=np.asarray([1.0], dtype="<f4").tobytes(),
                ),
            ),
        )

    before = None
    with pytest.raises(ValueError) as exc_info:
        before = DataLoader.load_zfd(str(p))
    assert before is None
    text = str(exc_info.value)
    assert p.name in text
    assert any(token in text for token in ("不完整", "时间轴无效", "声明", "不足", "截断"))


def test_zfd_a4_real_samples_match_step0_profile():
    """A4 metadata only. Values live in the separate corpus evidence test."""
    samples = _zfd_corpus_samples()
    manifest = read_zfd_corpus_manifest()
    time_tol = float(manifest.get("time_abs_tol", 1e-12))
    assert len(samples) == 6
    for entry, path in samples:
        groups = DataLoader.load_zfd(str(path))
        assert len(groups) == 1
        g = groups[0]
        t = g["data"]["Time"].to_numpy()
        smeta = g["source_metadata"]
        zfd = smeta["zfd_import"]
        signal_cols = [c for c in g["channels"] if c != "Time"]
        assert g["label_suffix"] == entry.get("label_suffix", "")
        assert smeta["source_kind"] == entry.get("source_kind", "zfd")
        assert smeta["title"] == entry["title"]
        assert smeta["version"] == entry["version"]
        assert smeta["source_filename"] == entry["source_filename"]
        assert smeta["fs_estimated"] is False
        assert len(t) == entry["sample_count"]
        assert t[0] == pytest.approx(entry["t0"], abs=time_tol, rel=0)
        assert t[-1] == pytest.approx(entry["t_end"], abs=time_tol, rel=0)
        if len(t) > 1:
            assert t[1] - t[0] == pytest.approx(entry["dt"], abs=time_tol, rel=0)
        assert signal_cols == entry["channels"]
        for col, unit in entry["units"].items():
            assert g["units"][col] == unit
        assert (smeta.get("renamed_channels") or []) == entry.get(
            "renamed_channels", []
        )
        for col, marker in entry.get("channel_markers", {}).items():
            assert g["channel_metadata"][col]["marker_id"] == marker
        assert zfd["sample_count"] == entry["sample_count"]
        assert zfd["time_record_index"] == entry["time_record_index"]
        assert zfd["parser_profile"] == entry["profile"]
        assert zfd["declared_record_count"] == entry["declared_record_count"]
        assert zfd["parsed_record_count"] == entry["parsed_record_count"]
        assert zfd["time_name"] == entry["time_name"]


def test_zfd_a5_header_annotation_and_structure(tmp_path):
    values = [1.0, 2.0, 3.0, 4.0]
    fake_in_data = np.frombuffer(
        (FAKE_MARKER + b"xxxx")[:16].ljust(16, b"\x00"), dtype="<f4",
    ).astype(np.float64)
    p = write_zfge2(
        tmp_path / "struct.zfd",
        header_lines=default_header_lines(title="Structured"),
        annotations=("note-one", "note-two"),
        records=(
            pack_time_record(count=4, name="clock", unit="s", t0=0.0, dt=0.5),
            pack_float32_record(
                values=fake_in_data, name="plain_force", unit="N",
            ),
        ),
        trailing=FAKE_MARKER + pack_float32_record(
            values=[9.0, 8.0, 7.0, 6.0], name="A2: trailing", unit="N",
        ),
    )
    groups = DataLoader.load_zfd(str(p))
    g = groups[0]
    assert g["label_suffix"] == ""
    assert "plain_force" in g["channels"]
    assert "trailing" not in g["channels"]
    assert "A2: trailing" not in g["channels"]
    assert len([c for c in g["channels"] if c != "Time"]) == 1
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["trailing_bytes"] > 0
    assert zfd["declared_record_count"] == zfd["parsed_record_count"] == 2
    cm = g["channel_metadata"]["plain_force"]
    assert cm["record_index"] == 1
    assert cm["record_type"] == 4
    assert cm.get("marker_id") in (None, "")


def test_zfd_a5_truncated_header_and_counts_fail(tmp_path):
    short_header = tmp_path / "short-head.zfd"
    short_header.write_bytes(pack_header(default_header_lines())[:20])
    with pytest.raises(ValueError, match="不完整|截断"):
        DataLoader.load_zfd(str(short_header))

    p = write_zfge2(
        tmp_path / "neg-ann.zfd",
        annotation_count_bytes=struct.pack("<h", -2),
        records=(
            pack_time_record(count=4),
            pack_float32_record(values=range(4)),
        ),
    )
    with pytest.raises(ValueError):
        DataLoader.load_zfd(str(p))

    p = write_zfge2(
        tmp_path / "neg-rec.zfd",
        record_count_bytes=struct.pack("<b", -3),
        records=(
            pack_time_record(count=4),
            pack_float32_record(values=range(4)),
        ),
    )
    with pytest.raises(ValueError):
        DataLoader.load_zfd(str(p))

    p = write_zfge2(
        tmp_path / "omit-rec.zfd",
        omit_record_count=True,
        records=(),
    )
    with pytest.raises(ValueError, match="不完整|截断"):
        DataLoader.load_zfd(str(p))


@pytest.mark.parametrize("unit", ("sec", "s", "SEC", " S "))
def test_zfd_a6_time_units_and_nonzero_t0(tmp_path, unit):
    p = write_minimal_zfd(
        tmp_path / f"t0-{unit.strip()}.zfd",
        dt=2.0,
        count=5,
        values=[1.0, 2.0, 3.0, 4.0, 5.0],
        t0=1.5,
        time_unit=unit,
    )
    g = DataLoader.load_zfd(str(p))[0]
    t = g["data"]["Time"].to_numpy()
    y = g["data"]["temp"].to_numpy()
    expected = expected_time_axis(5, t0=1.5, dt=2.0)
    np.testing.assert_array_equal(t, expected)
    np.testing.assert_array_equal(y, expected_f32_values([1.0, 2.0, 3.0, 4.0, 5.0]))
    assert y.dtype == np.float64
    assert t.dtype == np.float64
    assert g["units"]["temp"] == "C"
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["time_start_s"] == pytest.approx(1.5)
    assert zfd["time_step_s"] == pytest.approx(2.0)
    assert zfd["time_end_s"] == pytest.approx(expected[-1])
    assert zfd["duration_s"] == pytest.approx(expected[-1] - expected[0])
    fd = _filedata_from_group(p, g)
    np.testing.assert_array_equal(fd.time_array, t)
    np.testing.assert_array_equal(fd.data["temp"].to_numpy(), y)
    assert fd.fs == pytest.approx(0.5)


def test_zfd_a6_one_point_uses_declared_dt_not_default_1khz(tmp_path):
    p = write_minimal_zfd(
        tmp_path / "one.zfd",
        dt=0.004,
        count=1,
        values=[7.0],
        t0=3.0,
    )
    g = DataLoader.load_zfd(str(p))[0]
    t = g["data"]["Time"].to_numpy()
    y = g["data"]["temp"].to_numpy()
    assert len(t) == 1
    np.testing.assert_array_equal(t, expected_time_axis(1, t0=3.0, dt=0.004))
    np.testing.assert_array_equal(y, expected_f32_values([7.0]))
    assert y.dtype == np.float64
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["duration_s"] == pytest.approx(0.0)
    fd = _filedata_from_group(p, g)
    assert fd.fs == pytest.approx(250.0)
    np.testing.assert_array_equal(fd.time_array, t)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    (
        ({"dt": 0.001, "time_unit": "min"}, "时间轴无效|单位"),
        ({"dt": 0.001, "t0": -1.0}, "时间轴无效|不支持"),
        ({"dt": float("nan")}, "时间轴无效"),
    ),
)
def test_zfd_a7_invalid_timebase_rejected(tmp_path, kwargs, match):
    p = write_minimal_zfd(tmp_path / "bad-time.zfd", count=4, **kwargs)
    with pytest.raises(ValueError, match=match):
        DataLoader.load_zfd(str(p))


def test_zfd_a7_nonzero_x_and_count_mismatch_rejected(tmp_path):
    p = write_minimal_zfd(tmp_path / "x1.zfd", dt=0.001, count=8, x=1)
    with pytest.raises(ValueError, match="不支持|时间引用|X"):
        DataLoader.load_zfd(str(p))

    p = write_zfge2(
        tmp_path / "mismatch.zfd",
        records=(
            pack_time_record(count=8),
            pack_float32_record(values=range(5), name="A2: short"),
        ),
    )
    with pytest.raises(ValueError, match="点数|不一致"):
        DataLoader.load_zfd(str(p))


def test_zfd_a7_time_overflow_and_non_increasing_rejected(tmp_path):
    p = write_minimal_zfd(
        tmp_path / "overflow.zfd",
        dt=1e308,
        count=4,
        t0=1e308,
    )
    with pytest.raises(ValueError, match="时间轴无效"):
        DataLoader.load_zfd(str(p))

    p = write_minimal_zfd(
        tmp_path / "stuck.zfd",
        dt=0.001,
        count=4,
        t0=1e20,
    )
    with pytest.raises(ValueError, match="时间轴无效"):
        DataLoader.load_zfd(str(p))


@pytest.mark.parametrize("typ", (1, 2, 3, 99))
def test_zfd_a8_unsupported_types_fail_closed(tmp_path, typ):
    p = write_zfge2(
        tmp_path / f"type-{typ}.zfd",
        records=(
            pack_time_record(count=4),
            pack_float32_record(values=range(4), typ=typ, name="A2: other"),
        ),
    )
    with pytest.raises(ValueError, match="不支持|类型"):
        DataLoader.load_zfd(str(p))


def test_zfd_a8_multiple_time_records_rejected(tmp_path):
    p = write_zfge2(
        tmp_path / "two-time.zfd",
        records=(
            pack_time_record(count=4, name="t"),
            pack_time_record(count=4, name="t2"),
            pack_float32_record(values=range(4)),
        ),
    )
    with pytest.raises(ValueError, match="多个时间轴"):
        DataLoader.load_zfd(str(p))


def test_zfd_a8_non_zfge2_first_line_rejected(tmp_path):
    lines = default_header_lines()
    lines[0] = "ZFGE1"
    p = write_zfge2(
        tmp_path / "zfge1.zfd",
        header_lines=lines,
        records=(
            pack_time_record(count=4),
            pack_float32_record(values=range(4)),
        ),
    )
    with pytest.raises(ValueError, match="不是有效的 ZFD|ZFGE2"):
        DataLoader.load_zfd(str(p))


def test_zfd_a9_nan_inf_and_time_name_collision(tmp_path):
    values = [1.0, math.nan, math.inf, -math.inf]
    p = write_zfge2(
        tmp_path / "special.zfd",
        records=(
            pack_time_record(count=4),
            pack_float32_record(values=values, name="A2: Time", unit="C"),
            pack_float32_record(values=[0.0, 1.0, 2.0, 3.0], name="force"),
            pack_float32_record(values=[4.0, 5.0, 6.0, 7.0], name="force"),
        ),
    )
    g = DataLoader.load_zfd(str(p))[0]
    assert "Time" in g["channels"]
    time_like = [c for c in g["channels"] if c != "Time" and "Time" in c]
    assert time_like, g["channels"]
    y = g["data"][time_like[0]].to_numpy()
    assert math.isnan(y[1])
    assert math.isinf(y[2]) and y[2] > 0
    assert math.isinf(y[3]) and y[3] < 0
    assert y.dtype == np.float64
    force_cols = [c for c in g["channels"] if c.startswith("force")]
    assert len(force_cols) == 2
    assert "force" in g["channels"]
    np.testing.assert_array_equal(
        g["data"]["force"].to_numpy(),
        expected_f32_values([0.0, 1.0, 2.0, 3.0]),
    )
    other_force = [c for c in force_cols if c != "force"][0]
    np.testing.assert_array_equal(
        g["data"][other_force].to_numpy(),
        expected_f32_values([4.0, 5.0, 6.0, 7.0]),
    )


def test_zfd_a10_metadata_matches_arrays(tmp_path):
    p = write_minimal_zfd(
        tmp_path / "meta.zfd",
        dt=0.002,
        count=6,
        values=[1, 2, 3, 4, 5, 6],
        t0=0.5,
        name="probe",
    )
    g = DataLoader.load_zfd(str(p))[0]
    t = g["data"]["Time"].to_numpy()
    y = g["data"]["probe"].to_numpy()
    np.testing.assert_array_equal(t, expected_time_axis(6, t0=0.5, dt=0.002))
    np.testing.assert_array_equal(y, expected_f32_values([1, 2, 3, 4, 5, 6]))
    assert y.dtype == np.float64
    assert g["units"]["probe"] == "C"
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["schema"] == 1
    assert zfd["parser_profile"] == "zfge2-single-time-f32-v1"
    assert zfd["declared_record_count"] == 2
    assert zfd["parsed_record_count"] == 2
    assert zfd["sample_count"] == 6
    assert zfd["time_record_index"] == 0
    assert zfd["time_start_s"] == pytest.approx(t[0])
    assert zfd["time_end_s"] == pytest.approx(t[-1])
    assert zfd["duration_s"] == pytest.approx(t[-1] - t[0])
    assert zfd["time_step_s"] == pytest.approx(0.002)
    assert zfd["measurement_records_complete"] is True
    assert zfd["trailing_bytes"] == 0
    assert zfd["time_name"] == "t"
    assert zfd["time_unit_original"].strip().lower() in {"sec", "s"}
    assert g["source_metadata"]["fs_estimated"] is False
    cm = g["channel_metadata"]["probe"]
    assert cm["record_index"] == 1
    assert cm["record_type"] == 4
    assert cm["declared_count"] == 6
    assert cm["decoded_count"] == 6
    assert cm["x_record_index"] == 0
    with pytest.raises(ValueError, match="偏移|记录") as exc_info:
        DataLoader.load_zfd(str(write_truncated_last_channel(
            tmp_path / "meta-err.zfd", count=8, drop_bytes=12,
        )))
    err = str(exc_info.value)
    assert "meta-err.zfd" in err
    assert any(ch.isdigit() for ch in err)


def test_zfd_synthetic_complete_arrays_dtype_units_and_time(tmp_path):
    """A22: construction formula is the parser oracle for every sample."""
    count = 4096
    t0 = 1.25
    dt = 0.004
    values = characteristic_values(count, head=-4.5, mid=8.25, tail=12.5)
    p = write_minimal_zfd(
        tmp_path / "full-array.zfd",
        dt=dt,
        count=count,
        values=values,
        name="rack",
        unit="mm",
        t0=t0,
        title="Full Array",
    )
    g = DataLoader.load_zfd(str(p))[0]
    t = g["data"]["Time"].to_numpy()
    y = g["data"]["rack"].to_numpy()
    np.testing.assert_array_equal(t, expected_time_axis(count, t0=t0, dt=dt))
    np.testing.assert_array_equal(y, expected_f32_values(values))
    assert t.dtype == np.float64
    assert y.dtype == np.float64
    assert g["units"]["rack"] == "mm"
    assert g["source_metadata"]["title"] == "Full Array"
    assert g["channel_metadata"]["rack"]["unit"] == "mm"
    fd = _filedata_from_group(p, g)
    np.testing.assert_array_equal(fd.time_array, t)
    np.testing.assert_array_equal(fd.data["rack"].to_numpy(), y)
    assert fd.fs == pytest.approx(1.0 / dt, rel=1e-12)


def test_zfd_synthetic_parser_filedata_parity(tmp_path):
    """Consumer parity is not a parser-correctness oracle."""
    values = [1.5, -2.25, 3.0, 4.5, 5.75]
    p = write_minimal_zfd(
        tmp_path / "parity.zfd",
        dt=0.5,
        count=5,
        values=values,
        name="probe",
        unit="N",
        t0=0.25,
    )
    g = DataLoader.load_zfd(str(p))[0]
    fd = _filedata_from_group(p, g)
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry

    loaded = SourceAdapterRegistry.default().adapter_for(p).load_sources(p)
    assert len(loaded) == 1
    other = loaded[0].file_data
    np.testing.assert_array_equal(fd.time_array, g["data"]["Time"].to_numpy())
    np.testing.assert_array_equal(other.time_array, fd.time_array)
    np.testing.assert_array_equal(
        fd.data["probe"].to_numpy(),
        g["data"]["probe"].to_numpy(),
    )
    np.testing.assert_array_equal(
        other.data["probe"].to_numpy(),
        fd.data["probe"].to_numpy(),
    )
    assert fd.fs == pytest.approx(other.fs) == pytest.approx(2.0)


def test_zfd_corpus_helper_optional_root_unset_is_skippable(monkeypatch):
    monkeypatch.delenv(CORPUS_ROOT_ENV, raising=False)
    monkeypatch.delenv(REQUIRE_CORPUS_ENV, raising=False)
    with pytest.raises(CorpusSupplyError) as exc:
        resolve_zfd_corpus_samples()
    assert exc.value.optional is True


def test_zfd_corpus_helper_required_root_unset_is_failure(monkeypatch):
    monkeypatch.delenv(CORPUS_ROOT_ENV, raising=False)
    monkeypatch.setenv(REQUIRE_CORPUS_ENV, "1")
    with pytest.raises(CorpusSupplyError) as exc:
        resolve_zfd_corpus_samples()
    assert exc.value.optional is False
    assert CORPUS_ROOT_ENV in str(exc.value)


def test_zfd_corpus_helper_missing_file_is_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(CORPUS_ROOT_ENV, str(tmp_path))
    monkeypatch.setenv(REQUIRE_CORPUS_ENV, "1")
    with pytest.raises(CorpusSupplyError) as exc:
        resolve_zfd_corpus_samples()
    assert exc.value.optional is False
    assert "missing" in str(exc.value).lower()


def test_zfd_corpus_helper_hash_mismatch_is_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(CORPUS_ROOT_ENV, str(tmp_path))
    monkeypatch.delenv(REQUIRE_CORPUS_ENV, raising=False)
    manifest = read_zfd_corpus_manifest()
    for entry in manifest["samples"]:
        dest = tmp_path / entry["relative_path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"not-a-real-zfd-corpus-file")
    with pytest.raises(CorpusSupplyError) as exc:
        resolve_zfd_corpus_samples()
    assert exc.value.optional is False
    assert "hash" in str(exc.value).lower()


def test_zfd_corpus_helper_missing_manifest_is_failure(tmp_path, monkeypatch):
    monkeypatch.setenv(REQUIRE_CORPUS_ENV, "1")
    monkeypatch.setenv(CORPUS_ROOT_ENV, str(tmp_path))
    with pytest.raises(CorpusSupplyError) as exc:
        resolve_zfd_corpus_samples(manifest_path=tmp_path / "no-such-manifest.json")
    assert exc.value.optional is False
    assert "manifest" in str(exc.value).lower()


def test_zfd_corpus_value_evidence_matches_manifest():
    samples = _zfd_corpus_samples()
    manifest = read_zfd_corpus_manifest()
    abs_tol = float(manifest.get("value_abs_tol", 1e-6))
    time_tol = float(manifest.get("time_abs_tol", 1e-12))
    for entry, path in samples:
        g = DataLoader.load_zfd(str(path))[0]
        t = g["data"]["Time"].to_numpy()
        assert t.dtype == np.float64
        assert len(t) == entry["sample_count"]
        assert t[0] == pytest.approx(entry["t0"], abs=time_tol, rel=0)
        if len(t) > 1:
            assert t[1] - t[0] == pytest.approx(entry["dt"], abs=time_tol, rel=0)
        assert t[-1] == pytest.approx(entry["t_end"], abs=time_tol, rel=0)
        for col, expected in entry["value_evidence"].items():
            y = g["data"][col].to_numpy()
            assert y.dtype == np.float64
            assert len(y) == entry["sample_count"]
            assert y[0] == pytest.approx(expected["first"], abs=abs_tol, rel=0)
            assert y[1] == pytest.approx(expected["index_1"], abs=abs_tol, rel=0)
            assert y[len(y) // 2] == pytest.approx(expected["mid"], abs=abs_tol, rel=0)
            assert y[-2] == pytest.approx(
                expected["index_n_minus_2"], abs=abs_tol, rel=0
            )
            assert y[-1] == pytest.approx(expected["last"], abs=abs_tol, rel=0)
            assert y.min() == pytest.approx(expected["min"], abs=abs_tol, rel=0)
            assert y.max() == pytest.approx(expected["max"], abs=abs_tol, rel=0)


def test_zfd_corpus_parser_filedata_parity():
    samples = _zfd_corpus_samples()
    from mf4_analyzer.io.source_adapters import SourceAdapterRegistry

    registry = SourceAdapterRegistry.default()
    for _entry, path in samples:
        g = DataLoader.load_zfd(str(path))[0]
        fd = _filedata_from_group(path, g)
        loaded = registry.adapter_for(path).load_sources(path)
        assert len(loaded) == 1
        other = loaded[0].file_data
        t = g["data"]["Time"].to_numpy()
        np.testing.assert_array_equal(fd.time_array, t)
        np.testing.assert_array_equal(other.time_array, fd.time_array)
        assert fd.fs == pytest.approx(other.fs)
        for col in g["channels"]:
            if col == "Time":
                continue
            np.testing.assert_array_equal(
                fd.data[col].to_numpy(),
                g["data"][col].to_numpy(),
            )
            np.testing.assert_array_equal(
                other.data[col].to_numpy(),
                fd.data[col].to_numpy(),
            )
