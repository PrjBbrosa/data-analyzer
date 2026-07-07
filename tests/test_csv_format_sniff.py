"""Layout sniffing for CSVs whose channel-name row is not line 0."""
from pathlib import Path

import pytest

from mf4_analyzer.io.csv_format import CsvLayout, sniff_csv_layout


def _write(tmp_path, name, text, encoding="utf-8"):
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def test_plain_csv_is_trivial_or_none(tmp_path):
    p = _write(tmp_path, "plain.csv", "Time,EngSpd\n0.0,100\n0.1,101\n0.2,102\n")
    layout = sniff_csv_layout(p)
    assert layout is None or layout.is_trivial


def test_winwert_rule_header_on_line_1(tmp_path):
    p = _write(
        tmp_path,
        "ww.csv",
        "WinWert Export V2.1;2023-05-17;;\n"
        "Time;MotSpd;MotTrq\n"
        "0.0;100;1.5\n"
        "0.01;101;1.6\n"
        "0.02;102;1.7\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.known_format == "winwert"
    assert layout.header_row == 1
    assert layout.data_row == 2
    assert layout.sep == ";"


def test_winwert_rule_is_case_insensitive(tmp_path):
    p = _write(
        tmp_path,
        "ww2.csv",
        "Export by WINWERT tool\nTime,Sig\n0.0,1\n0.1,2\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None and layout.known_format == "winwert"
    assert layout.header_row == 1


def test_generic_heuristic_header_on_line_2(tmp_path):
    p = _write(
        tmp_path,
        "banner2.csv",
        "Converted from proprietary format\n"
        "Session 2026-07-06 vehicle=EPS-01\n"
        "Time,SteerTrq,MotSpd\n"
        "0.0,0.1,50\n"
        "0.1,0.2,51\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.header_row == 2
    assert layout.data_row == 3
    assert layout.units_row is None


def test_generic_heuristic_header_on_line_3(tmp_path):
    p = _write(
        tmp_path,
        "banner3.csv",
        "line one banner\nline two banner\nline three banner\n"
        "Time,Sig\n0.0,1\n0.1,2\n0.2,3\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.header_row == 3
    assert layout.data_row == 4


def test_units_row_between_header_and_data(tmp_path):
    p = _write(
        tmp_path,
        "units.csv",
        "Time,MotSpd,MotTrq\n"
        "s,rpm,Nm\n"
        "0.0,100,1.5\n"
        "0.1,101,1.6\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.header_row == 0
    assert layout.units_row == 1
    assert layout.data_row == 2
    assert not layout.is_trivial


def test_decimal_comma_with_semicolon_sep(tmp_path):
    p = _write(
        tmp_path,
        "german.csv",
        "Zeit;Drehzahl\n0,0;100,5\n0,1;101,25\n0,2;102,0\n",
    )
    layout = sniff_csv_layout(p)
    assert layout is not None
    assert layout.sep == ";"
    assert layout.decimal == ","


def test_bom_encoding_detected(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_bytes("Time,Sig\n0.0,1\n0.1,2\n".encode("utf-8-sig"))
    layout = sniff_csv_layout(p)
    if layout is not None:
        assert layout.encoding == "utf-8-sig"


def test_garbage_returns_none(tmp_path):
    p = tmp_path / "garbage.csv"
    p.write_bytes(bytes(range(256)) * 4)
    assert sniff_csv_layout(p) is None


def test_empty_file_returns_none(tmp_path):
    p = _write(tmp_path, "empty.csv", "")
    assert sniff_csv_layout(p) is None
