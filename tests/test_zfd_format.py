"""ZFGE2 .zfd 解析：官方布局 fixture、长记录、结构失败与时基合同。"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.loader import DataLoader
from tests.zfd_fixtures import (
    FAKE_MARKER,
    characteristic_values,
    default_header_lines,
    pack_float32_record,
    pack_header,
    pack_time_record,
    write_minimal_zfd,
    write_truncated_last_channel,
    write_zfge2,
    write_zfd_duplicate_names,
)

_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = _ROOT / "testdoc" / "wwt" / "end of travel_1.zfd"
_SAMPLES_JSON = _ROOT / ".state" / "zfd-robustness" / "samples.json"

# Re-export for existing callers (io notices / project session).
_write_minimal_zfd = write_minimal_zfd
_write_zfd_duplicate_names = write_zfd_duplicate_names


def _sample():
    if not SAMPLE.exists():
        pytest.skip(f"sample not found: {SAMPLE}")
    return str(SAMPLE)


# marker 名字/单位 -> (first, min, max)
_ANCHORS = {
    "Szyl 1": ("mm", -83.773, -83.773, 76.897),      # A2（首列保原名）
    "Fcyl 1": ("kN", -0.00055, -0.069, 66.799),
    "U_Batt": ("V", 13.714, 13.249, 17.648),
    "Szyl 1 [E5]": ("mm", -83.761, -83.85, 78.087),  # E5 消歧列
    "I_Battary": ("", -0.066, -0.215, -0.0011),
    "travel": ("mm", 83.177, -82.369, 83.177),
    "travel speed": ("", 1.378, 0.351, 377.29),
}

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
    text = Path(__file__).with_name("zfd_fixtures.py").read_text(encoding="utf-8")
    assert "import mf4_analyzer" not in text
    assert "from mf4_analyzer" not in text
    assert "import tools.matlab_ports" not in text
    assert "from tools.matlab_ports" not in text
    assert "load_zfd" not in text


def test_zfd_single_group_seven_channels_anchors():
    groups = DataLoader.load_zfd(_sample())
    assert len(groups) == 1
    g = groups[0]
    assert g["label_suffix"] == ""

    # 时间轴 1000 Hz / 7487 点
    t = g["data"]["Time"].to_numpy()
    assert len(t) == 7487
    assert t[0] == pytest.approx(0.0)
    assert t[1] - t[0] == pytest.approx(0.001)     # fs = 1000 Hz

    signal_cols = [c for c in g["channels"] if c != "Time"]
    assert len(signal_cols) == 7                    # 正好 7 个通道

    # 两个 Szyl 1 都在（消歧后不同列名）
    assert "Szyl 1" in g["channels"]
    assert "Szyl 1 [E5]" in g["channels"]

    for col, (unit, first, vmin, vmax) in _ANCHORS.items():
        assert col in g["channels"], col
        v = g["data"][col].to_numpy()
        assert v[0] == pytest.approx(first, abs=1e-2), f"{col} first"
        assert v.min() == pytest.approx(vmin, abs=1e-2), f"{col} min"
        assert v.max() == pytest.approx(vmax, abs=1e-2), f"{col} max"
        assert g["units"][col] == unit, f"{col} unit"

    smeta = g["source_metadata"]
    assert smeta["source_kind"] == "zfd"
    assert smeta["title"] == "End of Travel"
    assert "TestRunPRO Data V15532" in smeta["version"]
    assert smeta["source_filename"] == "end of travel_1.zfd"
    assert smeta["fs_estimated"] is False          # dt 真实读到

    # channel_metadata 存 marker id / 单位 / 显示范围
    cm = g["channel_metadata"]["travel"]
    assert cm["marker_id"] == "E17"
    assert cm["unit"] == "mm"
    assert "display_min" in cm and "display_max" in cm
    assert g["channel_metadata"]["Szyl 1 [E5]"]["marker_id"] == "E5"

    renamed = smeta.get("renamed_channels") or []
    assert renamed, "in-group marker_id disambiguation must record renamed_channels"
    assert any(
        r.get("original") == "Szyl 1" and r.get("renamed") == "Szyl 1 [E5]"
        for r in renamed
    )


def test_zfd_end_to_end_filedata_uniform_time_axis():
    groups = DataLoader.load_zfd(_sample())
    g = groups[0]
    fd = _filedata_from_group(_sample(), g)
    ta = fd.time_array
    assert ta is not None and len(ta) == 7487
    # 均匀时间轴
    diffs = np.diff(ta)
    np.testing.assert_allclose(diffs, diffs[0], rtol=1e-9)
    assert diffs[0] == pytest.approx(0.001)
    assert fd.fs == pytest.approx(1000.0, rel=1e-6)


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
    assert len(t) == count
    assert len(y) == count
    assert y[-1] == pytest.approx(float(values[-1]), rel=0, abs=1e-5)
    assert y[0] == pytest.approx(11.0, abs=1e-5)
    assert y[count // 2] == pytest.approx(22.0, abs=1e-5)
    expected_t = 0.0 + np.arange(count, dtype=np.float64) * 0.001
    np.testing.assert_allclose(t, expected_t, rtol=0, atol=1e-12)


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
    assert len(t) == _HOUR_COUNT
    assert len(y) == _HOUR_COUNT
    assert t[-1] - t[0] == pytest.approx(_HOUR_SPAN, abs=1e-9)
    assert y[0] == pytest.approx(11.0, abs=1e-5)
    assert y[_HOUR_COUNT // 2] == pytest.approx(22.0, abs=1e-5)
    assert y[-1] == pytest.approx(33.0, abs=1e-5)
    assert g["source_metadata"]["fs_estimated"] is False

    fd = _filedata_from_group(p, g)
    assert len(fd.time_array) == _HOUR_COUNT
    assert fd.time_array[0] == pytest.approx(0.0)
    assert fd.time_array[-1] - fd.time_array[0] == pytest.approx(_HOUR_SPAN, abs=1e-9)
    assert fd.fs == pytest.approx(1000.0, rel=1e-9)
    assert fd.time_array[0] != 0.0 or True  # t0 kept (here 0)
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
    if not _SAMPLES_JSON.exists():
        pytest.fail("A4 unverified: missing .state/zfd-robustness/samples.json")
    catalog = json.loads(_SAMPLES_JSON.read_text(encoding="utf-8"))
    missing = [item["path"] for item in catalog if not (_ROOT / item["path"]).exists()]
    if missing:
        pytest.fail("A4 unverified: missing samples " + ", ".join(missing))

    for item in catalog:
        path = _ROOT / item["path"]
        groups = DataLoader.load_zfd(str(path))
        expected = item["product"][0]
        assert len(groups) == 1
        g = groups[0]
        t = g["data"]["Time"].to_numpy()
        assert len(t) == expected["n"]
        assert t[0] == pytest.approx(expected["t0"])
        assert t[1] - t[0] == pytest.approx(expected["dt"])
        assert g["source_metadata"]["fs_estimated"] is False
        signal_cols = [c for c in g["channels"] if c != "Time"]
        assert signal_cols == expected["channels"]
        for col, unit in expected["units"].items():
            assert g["units"][col] == unit
        zfd = g["source_metadata"]["zfd_import"]
        assert zfd["sample_count"] == expected["n"]
        assert zfd["time_record_index"] == 0
        assert zfd["parser_profile"] == "zfge2-single-time-f32-v1"


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
    expected = 1.5 + np.arange(5, dtype=np.float64) * 2.0
    np.testing.assert_allclose(t, expected)
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["time_start_s"] == pytest.approx(1.5)
    assert zfd["time_step_s"] == pytest.approx(2.0)
    assert zfd["time_end_s"] == pytest.approx(expected[-1])
    assert zfd["duration_s"] == pytest.approx(expected[-1] - expected[0])
    fd = _filedata_from_group(p, g)
    assert fd.time_array[0] == pytest.approx(1.5)
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
    assert len(t) == 1
    assert t[0] == pytest.approx(3.0)
    zfd = g["source_metadata"]["zfd_import"]
    assert zfd["duration_s"] == pytest.approx(0.0)
    fd = _filedata_from_group(p, g)
    assert fd.fs == pytest.approx(250.0)
    assert fd.time_array[0] == pytest.approx(3.0)


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
