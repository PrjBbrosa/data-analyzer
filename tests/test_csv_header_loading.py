"""load_csv end-to-end with non-first-row headers."""
from pathlib import Path

import pytest

from mf4_analyzer.io.loader import DataLoader

REAL_SAMPLES = sorted(
    (Path(__file__).parent / "fixtures" / "csv_formats").glob("*.csv")
)


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_winwert_second_row_header(tmp_path):
    p = _write(
        tmp_path,
        "ww.csv",
        "WinWert Export V2.1;2023-05-17;;\n"
        "Time;MotSpd;MotTrq\n"
        "0.0;100;1.5\n0.01;101;1.6\n0.02;102;1.7\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "MotSpd", "MotTrq"]
    assert len(df) == 3
    assert float(df["MotSpd"].iloc[0]) == 100.0


def test_header_on_row_3_generic(tmp_path):
    p = _write(
        tmp_path,
        "b3.csv",
        "banner line one\nbanner line two\nbanner line three\n"
        "Time,Sig\n0.0,1\n0.1,2\n0.2,3\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "Sig"]
    assert len(df) == 3


def test_units_row_populates_units_dict(tmp_path):
    p = _write(
        tmp_path,
        "units.csv",
        "Time,MotSpd,MotTrq\ns,rpm,Nm\n0.0,100,1.5\n0.1,101,1.6\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "MotSpd", "MotTrq"]
    assert units == {"Time": "s", "MotSpd": "rpm", "MotTrq": "Nm"}
    assert len(df) == 2


def test_decimal_comma_german_export(tmp_path):
    p = _write(
        tmp_path,
        "de.csv",
        "WinWert Export\nZeit;Drehzahl\n0,0;100,5\n0,1;101,25\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Zeit", "Drehzahl"]
    assert abs(float(df["Drehzahl"].iloc[1]) - 101.25) < 1e-9


def test_bom_plain_csv_clean_first_channel(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("Time,Sig\n0.0,1\n0.1,2\n".encode("utf-8-sig"))
    df, channels, units = DataLoader.load_csv(p)
    assert channels[0] == "Time"


def test_plain_csv_behavior_unchanged(tmp_path):
    p = _write(tmp_path, "plain.csv", "Time,sig\n0,1\n0.1,2\n0.2,3\n")
    df, channels, units = DataLoader.load_csv(p)
    assert channels == ["Time", "sig"]
    assert units == {}
    assert list(df["sig"]) == [1, 2, 3]


def test_garbage_still_raises_valueerror(tmp_path):
    p = tmp_path / "garbage.csv"
    p.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(ValueError, match="Cannot parse CSV"):
        DataLoader.load_csv(p)


def test_time_column_drives_fs_after_detection(tmp_path):
    from mf4_analyzer.io.file_data import FileData

    p = _write(
        tmp_path,
        "ww_fs.csv",
        "winwert banner\nTime,Sig\n0.0,1\n0.1,2\n0.2,3\n0.3,4\n",
    )
    df, channels, units = DataLoader.load_csv(p)
    fd = FileData(str(p), df, channels, units)
    assert abs(fd.fs - 10.0) < 1e-6


@pytest.mark.parametrize("sample", REAL_SAMPLES, ids=lambda p: p.name)
def test_real_samples_load(sample):
    df, channels, units = DataLoader.load_csv(sample)
    assert len(channels) >= 1
    assert len(df) > 0
    assert not all(c.replace(".", "").replace("-", "").isdigit() for c in channels)
