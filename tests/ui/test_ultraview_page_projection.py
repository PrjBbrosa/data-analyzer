"""Pure UltraView page projection builder (Wave 2 Task 2.1).

Refresh-count ownership stays in ``test_ultraview_page.py``. This module covers
chrome/status/axis construction, template empty-slot maps, live Page parity,
and the import boundary for ``page_projection.py``.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from mf4_analyzer.ui.chart_stack.ultraview.card_widgets import CardViewModel
from mf4_analyzer.ui.chart_stack.ultraview.page_projection import (
    LibraryChromeFacts,
    axis_kind_from_record,
    card_models_for_slots,
    card_view_model,
    chrome_value,
    replacement_armed_for,
    status_for,
    title_for,
    x_unit_and_range_from_record,
)
from mf4_analyzer.ui.ultraview_state import (
    AXIS_KIND_FREQUENCY,
    AXIS_KIND_TIME,
    COMPARE_FILTER_ALL,
    STATUS_MISSING,
    STATUS_ORPHANED,
    STATUS_STALE,
    add_ref,
    make_ref,
)
from tests.ui.test_ultraview_page import FakePreview, _Harness, _image


ULTRAVIEW_ROOT = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "chart_stack"
    / "ultraview"
)
PROJECTION_PATH = ULTRAVIEW_ROOT / "page_projection.py"


def _chrome(**overrides) -> LibraryChromeFacts:
    payload = {
        "section": "time",
        "view_id": "time-1",
        "name": "道路输入",
        "tab_color": "#2d7ff9",
        "source_summary": "time-src",
    }
    payload.update(overrides)
    return LibraryChromeFacts(**payload)


def _record(**overrides) -> SimpleNamespace:
    payload = {
        "title": "旧预览名",
        "tab_color": "#111111",
        "source_summary": "stale-src",
        "axis_kind": AXIS_KIND_TIME,
        "x_unit": "s",
        "x_range": (0.0, 10.0),
        "image": None,
        "captured_digest": "digest-a",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _semantic_fields(model: CardViewModel) -> dict[str, object]:
    return {
        "slot_id": model.slot_id,
        "section": model.section,
        "view_id": model.view_id,
        "title": model.title,
        "tab_color": model.tab_color,
        "status": model.status,
        "source_summary": model.source_summary,
        "axis_kind": model.axis_kind,
        "x_unit": model.x_unit,
        "x_range": model.x_range,
        "selected": model.selected,
        "dimmed": model.dimmed,
        "replacement_armed": model.replacement_armed,
        "show_title": model.show_title,
        "show_source": model.show_source,
        "show_card_actions": model.show_card_actions,
    }


def test_chrome_value_live_prefers_library_then_record_then_default():
    assert chrome_value(True, "lib", "rec", "fallback") == "lib"
    assert chrome_value(True, "", "rec", "fallback") == "rec"
    assert chrome_value(True, "", "", "fallback") == "fallback"


def test_chrome_value_orphan_prefers_record_then_library_then_default():
    assert chrome_value(False, "lib", "rec", "fallback") == "rec"
    assert chrome_value(False, "lib", "", "fallback") == "lib"
    assert chrome_value(False, "", "", "fallback") == "fallback"


def test_title_for_live_vs_orphan_preference():
    ref = make_ref("time", "time-1")
    chrome = _chrome(name="道路输入")
    record = _record(title="旧预览名")
    assert title_for(ref, True, chrome, record) == "道路输入"
    assert title_for(ref, False, chrome, record) == "旧预览名"
    assert title_for(ref, True, None, None) == "time-1"


def test_status_for_explicit_wins_over_derived():
    record = _record(image=object())
    assert status_for(STATUS_STALE, True, record) == STATUS_STALE
    assert status_for(STATUS_ORPHANED, True, record) == STATUS_ORPHANED


def test_status_for_derives_orphaned_missing_and_stale():
    assert status_for(None, False, None) == STATUS_ORPHANED
    assert status_for(None, True, None) == STATUS_MISSING
    # Page always derives with current_digest=None, so a valid image is stale.
    assert status_for(None, True, _record(image=object())) == STATUS_STALE


def test_axis_and_range_from_record():
    assert axis_kind_from_record(None) is None
    assert axis_kind_from_record(_record(axis_kind="")) is None
    assert axis_kind_from_record(_record(axis_kind=AXIS_KIND_FREQUENCY)) == AXIS_KIND_FREQUENCY
    assert x_unit_and_range_from_record(None) == ("", None)
    assert x_unit_and_range_from_record(_record(x_unit="Hz", x_range=[1, 2])) == (
        "Hz",
        (1.0, 2.0),
    )
    assert x_unit_and_range_from_record(_record(x_range=("bad", "data"))) == ("s", None)


def test_compare_filter_dims_non_matching_axis():
    ref = make_ref("time", "time-1")
    matching = card_view_model(
        slot_id="primary",
        ref=ref,
        live=True,
        chrome=_chrome(),
        record=_record(axis_kind=AXIS_KIND_TIME),
        explicit_status=STATUS_STALE,
        selected=False,
        compare_filter=AXIS_KIND_TIME,
        replacement_armed=False,
        show_title=True,
        show_source=True,
        show_card_actions=False,
    )
    dimmed = card_view_model(
        slot_id="primary",
        ref=ref,
        live=True,
        chrome=_chrome(),
        record=_record(axis_kind=AXIS_KIND_TIME),
        explicit_status=STATUS_STALE,
        selected=False,
        compare_filter=AXIS_KIND_FREQUENCY,
        replacement_armed=False,
        show_title=True,
        show_source=True,
        show_card_actions=False,
    )
    assert matching.dimmed is False
    assert dimmed.dimmed is True


def test_replacement_armed_by_ref_or_slot():
    ref = make_ref("time", "time-1")
    other = make_ref("fft", "fft-1")
    assert replacement_armed_for(ref, "primary", ref, None) is True
    assert replacement_armed_for(ref, "primary", None, "primary") is True
    assert replacement_armed_for(ref, "primary", other, "aux_1") is False
    model = card_view_model(
        slot_id="primary",
        ref=ref,
        live=True,
        chrome=_chrome(),
        record=_record(),
        explicit_status=STATUS_STALE,
        selected=True,
        compare_filter=COMPARE_FILTER_ALL,
        replacement_armed=True,
        show_title=True,
        show_source=True,
        show_card_actions=False,
    )
    assert model.replacement_armed is True
    assert model.selected is True


def test_template_slot_map_keeps_empty_slots_none():
    ref = make_ref("time", "time-1")
    models = card_models_for_slots(
        {"primary": ref, "aux_1": None},
        chrome_by_key={("time", "time-1"): _chrome()},
        records={ref: _record()},
        statuses={ref: STATUS_STALE},
        exists={ref: True},
    )
    assert models["aux_1"] is None
    assert models["primary"] is not None
    assert models["primary"].slot_id == "primary"
    assert models["primary"].title == "道路输入"
    assert models["primary"].status == STATUS_STALE


def test_card_view_model_matches_page_card_model(qtbot):
    harness = _Harness(qtbot)
    ref = make_ref("time", "time-1")
    add_ref(harness.board, ref)
    preview = FakePreview(ref=ref, image=_image(), title="旧预览名", tab_color="#111111")
    harness.page.set_preview(ref, preview)
    harness.page.set_ref_status(ref, STATUS_STALE, True)
    harness.page.set_board(harness.board)
    slot_id = f"grid:{ref.section}:{ref.view_id}"
    from_page = harness.page._card_model(ref, slot_id=slot_id)
    built = card_view_model(
        slot_id=slot_id,
        ref=ref,
        live=harness.page._ref_exists.get(ref, True),
        chrome=harness.page._chrome_facts_for(ref),
        record=harness.page._previews.get(ref),
        explicit_status=(
            harness.page._statuses[ref] if ref in harness.page._statuses else None
        ),
        selected=ref in harness.page._interaction.card_selection(),
        compare_filter=harness.page._compare_filter,
        replacement_armed=replacement_armed_for(
            ref,
            slot_id,
            harness.page._replacement_ref,
            harness.page._replacement_slot,
        ),
        show_title=bool(harness.page._board.show_titles),
        show_source=bool(harness.page._board.show_sources),
        show_card_actions=harness.page._show_card_actions,
    )
    assert from_page.title == "道路输入"
    assert from_page.status == STATUS_STALE
    assert from_page.dimmed is False
    assert _semantic_fields(from_page) == _semantic_fields(built)


def test_page_projection_import_boundary():
    source = PROJECTION_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PROJECTION_PATH))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.add(module)
            if module:
                imported.add(module.split(".")[-1])
            for alias in node.names:
                imported.add(alias.name)
    assert "MainWindow" not in imported
    assert "UltraViewPage" not in imported
    assert "page" not in imported
    assert "widgets" not in imported
    assert "coordinator" not in imported
    assert "main_window" not in imported

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        annotations = [node.returns, *node.args.posonlyargs, *node.args.args]
        annotations.extend(node.args.kwonlyargs)
        if node.args.vararg is not None:
            annotations.append(node.args.vararg)
        if node.args.kwarg is not None:
            annotations.append(node.args.kwarg)
        for item in annotations:
            annotation = item if isinstance(item, ast.expr) else getattr(item, "annotation", None)
            if annotation is None:
                continue
            text = ast.unparse(annotation)
            assert "QWidget" not in text
            assert "UltraViewPage" not in text
            assert "MainWindow" not in text
