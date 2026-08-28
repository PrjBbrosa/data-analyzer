"""Literal contracts for WWT record catalogs and all DatenFenste2 windows."""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.io import wwt_formula
from mf4_analyzer.io.wwt_display import find_trailers
from mf4_analyzer.io.wwt_document import (
    WwtRecord,
    WwtWindowRectMm,
    load_wwt_document,
    parse_wwt_document,
)
from mf4_analyzer.io.wwt_format import load_wwt_groups
from mf4_analyzer.io.wwt_formula import WwtFormulaError, evaluate_wwt_formulas

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


def test_ucan_pars_formulas_materialize_on_operand_axis():
    loaded = load_wwt_document(_require(UCAN))
    records = {record.index: record for record in loaded.document.records}
    expected = {
        4: -(records[7].values - (-records[13].values)),
        5: -(records[7].values - (-records[15].values)),
        11: np.abs(records[8].values),
        12: records[14].values + records[16].values,
    }
    assert all(records[index].tag == "Pars" for index in expected)
    assert records[4].formula == "-(k7-(-k13))"
    assert records[5].formula == "-(k7-(-k15))"
    assert records[11].formula == "abs(k8)"
    assert records[12].formula == "k14+k16"
    for record_index, values in expected.items():
        got = records[record_index].values
        assert got is not None
        assert got.shape == (15274,)
        np.testing.assert_allclose(got, values, rtol=0.0, atol=0.0)
    assert records[4].declared_n == 50000

    main = next(group for group in loaded.groups if len(group["data"]) == 15274)
    for name, rec_index, formula in (
        ("Diff.Moment A", 4, "-(k7-(-k13))"),
        ("Diff.Moment B", 5, "-(k7-(-k15))"),
        ("Spurstangenkraft", 11, "abs(k8)"),
        ("Motor torque A+B", 12, "k14+k16"),
    ):
        assert name in main["channels"]
        meta = main["channel_metadata"][name]
        assert meta["derived"] is True
        assert meta["record_index"] == rec_index
        assert meta["formula"] == formula
        assert meta["formula_refs"]
    assert main["channels"] == [
        "Time",
        "Diff.Moment A",
        "Diff.Moment B",
        "Wheel input torque",
        "Rack Force",
        "Battary Current",
        "Wheel input angle",
        "Spurstangenkraft",
        "Motor torque A+B",
        "Sensor torque A",
        "Motor torque A",
        "Sensor torque B",
        "Motor torque B",
    ]


def _synthetic_records(*items: WwtRecord) -> tuple[WwtRecord, ...]:
    return items


@pytest.mark.parametrize(("formula", "code"), [
    ("__import__('os')", "unsupported_formula"),
    ("k1.attr", "unsupported_formula"),
    ("k999 + 1", "missing_formula_ref"),
])
def test_formula_rejects_unsafe_or_missing_refs(formula, code):
    records = _synthetic_records(
        WwtRecord(0, "Zeit", 3, "Time", "s", 1.0, 0.0, 0, np.arange(3.0), None),
        WwtRecord(1, "Real", 3, "A", "", 1.0, 0.0, 0, np.ones(3), None),
        WwtRecord(2, "Pars", 3, "Derived", "", 1.0, 0.0, None, None, formula),
    )
    with pytest.raises(WwtFormulaError) as exc:
        evaluate_wwt_formulas(records, strict=True)
    assert exc.value.code == code


def test_formula_cycle_is_rejected():
    records = _synthetic_records(
        WwtRecord(0, "Zeit", 3, "Time", "s", 1.0, 0.0, 0, np.arange(3.0), None),
        WwtRecord(1, "Real", 3, "A", "", 1.0, 0.0, 0, np.ones(3), None),
        WwtRecord(2, "Pars", 3, "A2", "", 1.0, 0.0, None, None, "k3+1"),
        WwtRecord(3, "Pars", 3, "B2", "", 1.0, 0.0, None, None, "k2+1"),
    )
    with pytest.raises(WwtFormulaError) as exc:
        evaluate_wwt_formulas(records, strict=True)
    assert exc.value.code == "formula_cycle"


def test_formula_axis_mismatch_is_rejected():
    records = _synthetic_records(
        WwtRecord(0, "Zeit", 3, "Time", "s", 1.0, 0.0, 0, np.arange(3.0), None),
        WwtRecord(1, "Real", 3, "A", "", 1.0, 0.0, 0, np.ones(3), None),
        WwtRecord(2, "Zeit", 3, "Time2", "s", 1.0, 0.0, 2, np.arange(3.0), None),
        WwtRecord(3, "Real", 3, "B", "", 1.0, 0.0, 2, np.ones(3), None),
        WwtRecord(4, "Pars", 3, "Derived", "", 1.0, 0.0, None, None, "k1+k3"),
    )
    with pytest.raises(WwtFormulaError) as exc:
        evaluate_wwt_formulas(records, strict=True)
    assert exc.value.code == "formula_axis_mismatch"


def test_formula_shape_mismatch_does_not_truncate():
    left = np.arange(3.0)
    right = np.arange(4.0)
    records = _synthetic_records(
        WwtRecord(0, "Zeit", 3, "Time", "s", 1.0, 0.0, 0, np.arange(3.0), None),
        WwtRecord(1, "Real", 3, "A", "", 1.0, 0.0, 0, left, None),
        WwtRecord(2, "Real", 4, "B", "", 1.0, 0.0, 0, right, None),
        WwtRecord(3, "Pars", 3, "Derived", "", 1.0, 0.0, None, None, "k1+k2"),
    )
    with pytest.raises(WwtFormulaError) as exc:
        evaluate_wwt_formulas(records, strict=True)
    assert exc.value.code == "formula_shape_mismatch"
    assert "3" in exc.value.detail and "4" in exc.value.detail
    updated, _ = evaluate_wwt_formulas(records, strict=False)
    assert updated[3].values is None
    np.testing.assert_array_equal(left, np.arange(3.0))
    np.testing.assert_array_equal(right, np.arange(4.0))


def test_formula_no_finite_values_is_rejected():
    records = _synthetic_records(
        WwtRecord(0, "Zeit", 3, "Time", "s", 1.0, 0.0, 0, np.arange(3.0), None),
        WwtRecord(1, "Real", 3, "A", "", 1.0, 0.0, 0, np.zeros(3), None),
        WwtRecord(2, "Pars", 3, "Derived", "", 1.0, 0.0, None, None, "k1/0"),
    )
    with pytest.raises(WwtFormulaError) as exc:
        evaluate_wwt_formulas(records, strict=True)
    assert exc.value.code == "formula_no_finite_values"


def test_wwt_formula_module_never_uses_eval_or_exec():
    tree = ast.parse(Path(wwt_formula.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not ({"eval", "exec", "compile"} & called)
