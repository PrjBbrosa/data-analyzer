"""Literal contracts for WWT record catalogs and all DatenFenste2 windows."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io.wwt_display import find_trailers
from mf4_analyzer.io.wwt_document import (
    WwtWindowRectMm,
    parse_wwt_document,
)
from mf4_analyzer.io.wwt_format import load_wwt_groups

_ROOT = Path(__file__).resolve().parent.parent
UCAN = _ROOT / "testdoc" / "WWT" / "UCAN-b6_P779_0007.wwt"
SFNS = _ROOT / "testdoc" / "WWT" / "SFNS_10_P779_0007.wwt"
YP = _ROOT / "testdoc" / "WWT" / "YP_SS_P779_0007.wwt"


def _require(path: Path) -> Path:
    if not path.is_file():
        pytest.fail(f"required sample missing: {path}")
    return path


def test_ucan_record_catalog_and_all_display_windows():
    doc = parse_wwt_document(_require(UCAN))
    assert len(doc.records) == 21
    assert [record.index for record in doc.records] == list(range(21))
    assert len(doc.windows) == 7
    assert [window.rect_mm for window in doc.windows] == [
        WwtWindowRectMm(25.0, 65.0, 100.0, 60.0),
        WwtWindowRectMm(41.0, 138.2, 90.0, 60.0),
        WwtWindowRectMm(147.5, 62.5, 50.0, 60.0),
        WwtWindowRectMm(215.5, 62.5, 50.0, 60.0),
        WwtWindowRectMm(147.5, 138.0, 50.0, 60.0),
        WwtWindowRectMm(214.5, 138.0, 50.0, 60.0),
        WwtWindowRectMm(214.5, 138.0, 50.0, 60.0),
    ]
    assert [window.line_width_mm for window in doc.windows] == [0.2] * 7

    names = [record.name for record in doc.records]
    assert names[0] == "Time"
    assert names[4] == "Diff.Moment A"
    assert names[5] == "Diff.Moment B"
    assert names[11] == "Spurstangenkraft"
    assert names[12] == "Motor torque A+B"
    assert names[17] == "Wheel input torque Symmetry"
    assert names[20] == "Wheel input torque Hysteresis"

    assert doc.records[0].tag == "Zeit"
    assert doc.records[0].declared_n == 1988
    assert doc.records[4].tag == "Pars"
    assert doc.records[4].declared_n == 50000
    assert doc.records[4].formula == "-(k7-(-k13))"
    assert doc.records[4].values is None
    assert doc.records[5].formula == "-(k7-(-k15))"
    assert doc.records[11].formula == "abs(k8)"
    assert doc.records[12].formula == "k14+k16"
    assert doc.records[7].declared_n == 15274
    assert doc.records[7].values is not None
    assert doc.records[7].values.shape == (15274,)
    assert not doc.records[7].values.flags.writeable
    assert doc.records[17].declared_n == 72
    assert doc.records[17].values is not None
    assert doc.records[17].values.shape == (72,)
    assert doc.records[19].declared_n == 151
    assert doc.records[19].values is not None
    assert doc.records[19].values.shape == (151,)


def test_ucan_find_trailers_are_strictly_increasing_6114_apart():
    data = _require(UCAN).read_bytes()
    offsets = find_trailers(data)
    assert len(offsets) == 7
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == 7
    diffs = [b - a for a, b in zip(offsets, offsets[1:])]
    assert diffs == [6114] * 6


def test_sfns_and_yp_keep_one_display_window_and_existing_groups():
    sfns = parse_wwt_document(_require(SFNS))
    assert len(sfns.windows) == 1
    assert sfns.windows[0].line_width_mm == 0.2
    x_row = sfns.windows[0].curves[0]
    assert x_row.label.startswith("Rack travel")
    assert (x_row.lo, x_row.hi) == (-100.0, 100.0)
    assert x_row.tick_interval == 10.0
    force = next(c for c in sfns.windows[0].curves if "Rack Force" in c.label)
    assert force.visible is True
    assert (force.lo, force.hi) == (-1500.0, 1500.0)
    assert force.tick_interval == 500.0
    assert force.grid_interval == 100.0
    assert force.color_rgb == (0, 0, 128)

    yp = parse_wwt_document(_require(YP))
    assert len(yp.windows) == 1
    x_row = yp.windows[0].curves[0]
    assert "Steering Angle" in x_row.label
    assert (x_row.lo, x_row.hi) == (-720.0, 720.0)
    assert x_row.tick_interval == 120.0
    assert x_row.grid_interval == 60.0
    by_label = {c.label: c for c in yp.windows[0].curves}
    assert by_label["Tol_oben [mm]"].visible is True
    assert by_label["Tol_oben [mm]"].selected is False
    assert by_label["Tol_oben [mm]"].color_rgb == (255, 0, 0)
    assert by_label["Tol_oben [mm]"].x_record_index == 3
    druck = by_label["Druckstückspiel [mm]"]
    assert druck.visible is True and druck.selected is True
    assert druck.color_rgb == (0, 0, 128)
    assert (druck.lo, druck.hi) == (0.0, 0.2)
    assert druck.tick_interval == 0.05
    assert druck.grid_interval == 0.01

    loaded = load_wwt_groups(SFNS)
    assert [list(g["channels"]) for g in loaded] == [
        list(g["channels"]) for g in sfns.groups
    ]


def test_truncated_display_block_is_diagnosed_without_dropping_groups(tmp_path):
    src = _require(UCAN).read_bytes()
    offsets = find_trailers(src)
    assert len(offsets) >= 2
    truncated = bytearray(src[: offsets[1] + 40])
    truncated[offsets[1]:offsets[1] + 12] = b"DatenFenste"
    path = tmp_path / "truncated_window.wwt"
    path.write_bytes(truncated)
    doc = parse_wwt_document(path)
    assert doc.groups
    assert len(doc.windows) == 1
    assert any("display" in item.lower() or "window" in item.lower()
               or "trailer" in item.lower() or "截断" in item
               for item in doc.diagnostics)
