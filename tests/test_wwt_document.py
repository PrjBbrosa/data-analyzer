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
    load_wwt_document,
    parse_wwt_document,
)
from mf4_analyzer.io.wwt_format import load_wwt_groups
from mf4_analyzer.io.wwt_formula import WwtFormulaError, evaluate_wwt_formulas
from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parent.parent


def test_channel_xy_with_auxiliaries_roundtrip(tmp_path):
    path = wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")
    doc = parse_wwt_document(path)
    by_name = {record.name: record for record in doc.records}
    assert set(by_name) >= {
        wwt.TIME_NAME, wwt.CHAN_X, wwt.CHAN_Y,
        wwt.LIMIT_HI, wwt.LIMIT_LO, wwt.LINE_X,
    }
    assert by_name[wwt.CHAN_X].declared_n == wwt.CHANNEL_N
    assert by_name[wwt.LIMIT_HI].declared_n == wwt.AUX_N
    assert by_name[wwt.LIMIT_HI].values is not None
    assert by_name[wwt.LIMIT_HI].values.shape == (wwt.AUX_N,)
    assert not by_name[wwt.LIMIT_HI].values.flags.writeable

    assert len(doc.groups) == 1
    channels = list(doc.groups[0]["channels"])
    assert wwt.CHAN_X in channels and wwt.CHAN_Y in channels
    assert wwt.LIMIT_HI not in channels
    assert wwt.LIMIT_LO not in channels
    assert wwt.LINE_X not in channels
    skipped = doc.groups[0]["source_metadata"]["skipped_channels"]
    aux_names = [
        item["name"] if isinstance(item, dict) else item
        for item in doc.groups[0]["source_metadata"].get("wwt_auxiliary_records") or []
    ]
    assert aux_names == [wwt.LIMIT_HI, wwt.LIMIT_LO, wwt.LINE_X]
    assert wwt.LIMIT_HI not in skipped
    assert wwt.LIMIT_LO not in skipped
    assert wwt.LINE_X not in skipped

    assert len(doc.windows) == 1
    window = doc.windows[0]
    assert window.rect_mm == wwt.RECT_WIN_A
    assert window.line_width_mm == wwt.LINE_WIDTH_MM
    x_row = window.curves[0]
    assert x_row.label == f"{wwt.CHAN_X} [{wwt.CHAN_X_UNIT}]"
    assert (x_row.lo, x_row.hi) == (wwt.CHAN_X_LO, wwt.CHAN_X_HI)
    assert x_row.tick_interval == wwt.CHAN_X_TICK
    assert x_row.grid_interval == wwt.CHAN_X_GRID
    chan_y = next(c for c in window.curves if c.record_index == by_name[wwt.CHAN_Y].index)
    assert chan_y.visible is True and chan_y.selected is True
    assert chan_y.x_record_index == by_name[wwt.CHAN_X].index
    assert chan_y.color_rgb == (0, 0, 128)
    for name in (wwt.LIMIT_HI, wwt.LIMIT_LO, wwt.LINE_X):
        curve = next(c for c in window.curves if c.record_index == by_name[name].index)
        assert curve.visible is False

    loaded = load_wwt_groups(path)
    assert [list(g["channels"]) for g in loaded] == [
        list(g["channels"]) for g in doc.groups
    ]
    store = loaded[0]["source_metadata"]["wwt_record_store"]
    assert store is not None
    store_names = [getattr(item, "name", None) for item in store]
    assert wwt.LIMIT_HI in store_names
    assert wwt.LIMIT_HI not in loaded[0]["source_metadata"]["skipped_channels"]


def test_measurement_plus_record_only_tolerance_roundtrip(tmp_path):
    meas_n, tol_n = 120, 8
    path = wwt.measurement_plus_record_only_tolerance(
        meas_n=meas_n, tol_n=tol_n, path=tmp_path / "tol.wwt",
    )
    doc = parse_wwt_document(path)
    by_name = {record.name: record for record in doc.records}
    assert by_name[wwt.MEAS_Y].declared_n == meas_n
    assert by_name[wwt.TOL_Y].declared_n == tol_n
    assert by_name[wwt.LINE_X].declared_n == tol_n
    assert wwt.MEAS_Y in doc.groups[0]["channels"]
    assert wwt.CHAN_X in doc.groups[0]["channels"]
    assert wwt.TOL_Y not in doc.groups[0]["channels"]
    assert wwt.LINE_X not in doc.groups[0]["channels"]

    window = doc.windows[0]
    meas = next(c for c in window.curves if c.record_index == by_name[wwt.MEAS_Y].index)
    tol = next(c for c in window.curves if c.record_index == by_name[wwt.TOL_Y].index)
    assert meas.visible is True and meas.selected is True
    assert meas.x_record_index == by_name[wwt.CHAN_X].index
    assert tol.visible is True and tol.selected is False
    assert tol.x_record_index == by_name[wwt.LINE_X].index
    assert meas.x_record_index != tol.x_record_index


def test_multi_window_overlap_and_formula_roundtrip(tmp_path):
    path = wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    parsed = parse_wwt_document(path)
    assert len(parsed.windows) == wwt.MULTI_WINDOW_COUNT
    assert parsed.windows[1].rect_mm == parsed.windows[2].rect_mm == wwt.RECT_WIN_B
    assert parsed.windows[0].rect_mm == wwt.RECT_WIN_A
    assert parsed.windows[1].rect_mm != parsed.windows[0].rect_mm
    by_name = {record.name: record for record in parsed.records}
    assert by_name[wwt.FORM_Y].tag == "Pars"
    assert by_name[wwt.FORM_Y].formula == wwt.FORMULA
    assert by_name[wwt.FORM_Y].values is None

    win0_y = [c for c in parsed.windows[0].curves if c.visible]
    win1_y = [c for c in parsed.windows[1].curves if c.visible]
    win2_y = [c for c in parsed.windows[2].curves if c.visible]
    assert win0_y[0].record_index == by_name[wwt.CHAN_Y].index
    assert win0_y[0].x_record_index == by_name[wwt.CHAN_X].index
    assert win1_y[0].record_index == by_name[wwt.FORM_Y].index
    assert win1_y[0].x_record_index == by_name[wwt.CHAN_X].index
    assert win2_y[0].record_index == by_name[wwt.TOL_Y].index
    assert win2_y[0].x_record_index == by_name[wwt.LINE_X].index
    assert win2_y[0].x_record_index != win0_y[0].x_record_index

    loaded = load_wwt_document(path)
    form = next(r for r in loaded.document.records if r.name == wwt.FORM_Y)
    chan_y = next(r for r in loaded.document.records if r.name == wwt.CHAN_Y)
    assert form.values is not None
    np.testing.assert_allclose(form.values, np.abs(chan_y.values), rtol=0.0, atol=0.0)
    assert wwt.FORM_Y in loaded.groups[0]["channels"]
    meta = loaded.groups[0]["channel_metadata"][wwt.FORM_Y]
    assert meta["derived"] is True
    assert meta["formula"] == wwt.FORMULA
    assert meta["formula_refs"]


def test_multi_window_trailers_are_strictly_increasing(tmp_path):
    path = wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    offsets = find_trailers(path.read_bytes())
    assert len(offsets) == wwt.MULTI_WINDOW_COUNT
    assert offsets == sorted(offsets)
    assert len(set(offsets)) == wwt.MULTI_WINDOW_COUNT


def test_truncated_display_block_is_diagnosed_without_dropping_groups(tmp_path):
    src = wwt.multi_window_overlap_and_formula()
    offsets = find_trailers(src)
    assert len(offsets) >= 2
    truncated = bytearray(src[: offsets[1] + 40])
    truncated[offsets[1]:offsets[1] + 12] = b"DatenFenste"
    path = tmp_path / "truncated_window.wwt"
    path.write_bytes(truncated)
    doc = parse_wwt_document(path)
    assert doc.groups
    assert len(doc.windows) == 1
    assert any(
        item.startswith("truncated_window:")
        or "display" in item.lower() or "window" in item.lower()
        or "trailer" in item.lower() or "截断" in item
        for item in doc.diagnostics
    )
    assert any(item.startswith("truncated_window:") for item in doc.diagnostics)


def test_load_attaches_one_record_store_to_every_group(tmp_path):
    n = wwt.CHANNEL_N
    records = (
        wwt.WwtRecordSpec("Zeit", "TimeA", "s", n=n, dt=wwt.DT, t0=0.0),
        wwt.WwtRecordSpec(
            "Real", "ChanA", "N", n=n, values=np.linspace(0.0, 1.0, n),
        ),
        wwt.WwtRecordSpec("Zeit", "TimeB", "s", n=n, dt=wwt.DT, t0=1.0),
        wwt.WwtRecordSpec(
            "Real", "ChanB", "N", n=n, values=np.linspace(0.0, 1.0, n),
        ),
        wwt.WwtRecordSpec(
            "Real", wwt.LIMIT_HI, "N", n=wwt.AUX_N,
            values=np.full(wwt.AUX_N, 40.0),
        ),
    )
    path = wwt.write_wwt_file(tmp_path / "groups.wwt", records)
    loaded = load_wwt_document(path)
    assert len(loaded.groups) == 2
    stores = [
        group["source_metadata"]["wwt_record_store"]
        for group in loaded.groups
    ]
    assert stores[0] is stores[1]
    assert stores[0] is loaded.document.records
    aux_names = [
        item["name"] if isinstance(item, dict) else item
        for item in loaded.groups[0]["source_metadata"]["wwt_auxiliary_records"]
    ]
    assert wwt.LIMIT_HI in aux_names
    assert wwt.LIMIT_HI not in loaded.groups[0]["source_metadata"]["skipped_channels"]


def test_optional_customer_wwt_sample_parses_when_present():
    folder = _ROOT / "testdoc" / "WWT"
    samples = sorted(folder.glob("*.wwt")) if folder.is_dir() else []
    if not samples:
        pytest.skip(f"optional customer WWT sample missing: {folder}")
    doc = parse_wwt_document(samples[0])
    assert doc.records and doc.groups


def test_exact_winwert_gap_sentinel_becomes_nan_without_dropping_points(tmp_path):
    path = wwt.record_only_gap_curves(tmp_path / "gap.wwt")
    loaded = load_wwt_document(path)
    records = {record.name: record for record in loaded.document.records}

    y_pos = records[wwt.GAP_Y_POS].values
    y_speed = records[wwt.GAP_Y_SPEED].values
    assert y_pos is not None and y_speed is not None
    assert y_pos.shape == (7,)
    assert y_speed.shape == (7,)
    assert np.isnan(y_pos[2])
    assert np.isnan(y_speed[[2, 5]]).all()
    assert y_pos[3] == -9e299
    assert not y_pos.flags.writeable
    assert not y_speed.flags.writeable

    store = loaded.groups[0]["source_metadata"]["wwt_record_store"]
    assert store[records[wwt.GAP_Y_POS].index].values is y_pos
    assert store[records[wwt.GAP_Y_SPEED].index].values is y_speed


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
