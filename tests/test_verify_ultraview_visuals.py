"""UltraView visual harness: geometry assertions, contact sheet, default output."""
from __future__ import annotations

import ast
import contextlib
import json
from pathlib import Path

import pytest

from tools.verify_ultraview_visuals import (
    DEFAULT_OUTPUT,
    HOST_COORD_SPACE,
    MANIFEST_SCHEMA_VERSION,
    REQUIRED_SHOTS,
    GeometryError,
    _facts_intersect,
    _fact_contained_by,
    _hidden_host_rect,
    _library_constants,
    _library_errors,
    _minimap_selection_facts,
    _Preview,
    _selection_chrome_errors,
    _setup_selected_bottom_right_scene,
    assert_geometry,
    generate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "verify_ultraview_visuals.py"


def _library_manifest(
    *,
    section: dict | None = None,
    width: int | None = None,
    mode_controls_visible: bool = False,
    compact_host_visible: bool = False,
) -> dict:
    """Synthetic slice for the one-path, grouped library contract."""
    constants = _library_constants()
    panel = {
        "x": 68,
        "y": 64,
        "w": constants["LIBRARY_DEFAULT_WIDTH"] if width is None else width,
        "h": 560,
        "visible": True,
    }
    return {
        "library_constants": constants,
        "geometry": {
            "library_groups_1280": {
                "library": {
                    "panel": dict(panel),
                    "browse_mode": constants["LIBRARY_MODE_GROUPS"],
                    "sections": {
                        "time": section
                        or {"height": 215, "min_hint": 215, "visible": True}
                    },
                    "mode_controls_visible": mode_controls_visible,
                    "compact_host_visible": compact_host_visible,
                }
            },
        },
    }


def _matching(errors: list[str], needle: str) -> list[str]:
    return [error for error in errors if needle in error]


def test_default_output_is_gitignored_state_dir():
    assert DEFAULT_OUTPUT.parts[-2:] == (".state", "ultraview-p0")
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".state/" in gitignore


def test_harness_does_not_import_main_window():
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "main_window" not in alias.name
                assert alias.name != "mf4_analyzer.ui.main_window"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "main_window" not in node.module
            assert node.module != "mf4_analyzer.ui"


def test_ultraview_visual_harness_geometry_and_contact_sheet(qapp, tmp_path):
    manifest = generate(tmp_path)
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    for name in REQUIRED_SHOTS:
        info = manifest["shots"][name]
        path = tmp_path / info["path"]
        assert path.is_file(), name
        assert path.stat().st_size > 100, name
        assert info["width"] >= 10 and info["height"] >= 10
    contact = tmp_path / manifest["contact_sheet"]
    assert contact.is_file()
    assert contact.stat().st_size > 1000
    assert (tmp_path / "manifest.json").is_file()
    statuses = {
        card["status"]
        for card in manifest["geometry"]["four_status_1440"]["cards"]
        if not card.get("empty")
    }
    assert {"fresh", "stale", "missing", "orphaned"} <= statuses
    assert manifest["geometry"]["toolbar_1100"]["overlap_pairs"] == []
    assert manifest["geometry"]["show_flags_1440"]["show_titles"] is False
    assert manifest["geometry"]["presentation_1280"]["library_visible"] is False
    mini = manifest["geometry"]["selected_bottom_right_with_minimap"]["minimap_selection"]
    assert mini["space"] == HOST_COORD_SPACE
    assert mini["target"]["visible"] is True
    assert mini["minimap"]["visible"] is True
    assert _facts_intersect(mini["target"], mini["stage"])
    assert not _facts_intersect(mini["minimap"], mini["target"])
    picker = manifest["geometry"]["selected_shape_format_picker"]["format_picker"]
    assert picker["space"] == HOST_COORD_SPACE
    assert picker["picker"]["visible"] is True
    assert picker["target"]["visible"] is True
    assert picker["toolbar"]["visible"] is True
    assert _facts_intersect(picker["target"], picker["stage"])
    assert not _facts_intersect(picker["picker"], picker["target"])


def test_required_shots_cover_the_single_grouped_library_path():
    assert "library_groups_1280" in REQUIRED_SHOTS
    assert "boards_1280" in REQUIRED_SHOTS
    assert "library_overview_1280" not in REQUIRED_SHOTS
    assert "library_overview_stale_1280" not in REQUIRED_SHOTS


def test_required_shots_cover_pointer_minimap_and_laser_facts():
    assert "pointer_popup_800" in REQUIRED_SHOTS
    assert "pointer_popup_1280" in REQUIRED_SHOTS
    assert "selected_bottom_right_with_minimap" in REQUIRED_SHOTS
    assert "selected_shape_format_picker" in REQUIRED_SHOTS
    assert "laser_cursor" in REQUIRED_SHOTS


def test_library_contract_accepts_the_single_grouped_path():
    errors = _library_errors(_library_manifest())
    assert _matching(errors, "is clipped") == []
    assert _matching(errors, "browse-mode control") == []
    assert _matching(errors, "compact catalog") == []


def test_library_contract_catches_wrong_width_clipped_section_and_removed_controls():
    assert _matching(_library_errors(_library_manifest(width=470)), "library width=470")
    clipped = _library_manifest(
        section={"height": 164, "min_hint": 215, "visible": True}
    )
    assert _matching(_library_errors(clipped), "'time' is clipped")
    assert _matching(
        _library_errors(_library_manifest(mode_controls_visible=True)),
        "browse-mode control",
    )
    assert _matching(
        _library_errors(_library_manifest(compact_host_visible=True)),
        "compact catalog host",
    )


def test_library_shot_records_the_single_grouped_path(qapp, tmp_path):
    with contextlib.suppress(GeometryError):
        generate(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    name = "library_groups_1280"
    assert (tmp_path / manifest["shots"][name]["path"]).is_file(), name
    facts = manifest["geometry"][name]["library"]
    assert facts["panel"]["visible"] is True
    assert facts["panel"]["w"] == _library_constants()["LIBRARY_DEFAULT_WIDTH"]
    assert facts["panel"]["h"] > 0
    assert facts["browse_mode"] == "groups"
    assert set(facts["sections"]) == {"time", "fft", "fft_time", "frf", "order"}
    assert facts["section_order"] == ["time", "fft", "fft_time", "frf", "order"]
    assert all(section_facts["min_hint"] > 0 for section_facts in facts["sections"].values())
    assert facts["row_heights"]
    assert facts["mode_controls_visible"] is False
    assert facts["compact_host_visible"] is False


def test_lod_zoom_matrix_exposes_type_and_hides_title_only_preview(qapp, qtbot):
    """Offscreen state/geometry only — not a Cocoa visual pass."""
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
    from mf4_analyzer.ui.chart_stack.ultraview.widgets import LibraryRow
    from mf4_analyzer.ui.ultraview_state import (
        STATUS_MISSING,
        add_ref,
        default_board,
        make_ref,
    )
    from mf4_analyzer.ui_kit import load_stylesheet
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtWidgets import QToolButton

    load_stylesheet(qapp)
    page = UltraViewPage()
    qtbot.addWidget(page)
    board = default_board()
    ref = make_ref("time", "View 1")
    add_ref(board, ref)
    page.set_library_rows(
        [
            LibraryRow(
                section="time",
                view_id="View 1",
                name="View 1",
                tab_color="#2d7ff9",
                status=STATUS_MISSING,
                on_board=True,
                source_summary="time-src",
            )
        ]
    )
    image = QImage(48, 32, QImage.Format_ARGB32)
    image.fill(QColor("#2d7ff9"))
    page.set_preview(
        ref,
        _Preview(ref=ref, image=image, title="View 1", captured_digest="keep"),
    )
    page.set_board(board)
    page.show()
    for width, height in ((800, 560), (1280, 800), (1440, 900)):
        page.resize(width, height)
        qtbot.wait(10)
        card = page.card_widget("time", "View 1")
        assert card is not None
        for zoom, expect_preview in ((1.0, True), (0.55, True), (0.35, False)):
            page.set_board_zoom(zoom)
            qtbot.wait(10)
            chip = card.findChild(QToolButton, "ultraViewCardTypeChip")
            assert chip is not None and chip.isVisible()
            assert "时域" in (chip.text() + chip.toolTip() + chip.accessibleName())
            if expect_preview:
                assert card._image.isVisible() and card._image.height() > 0
            else:
                assert not card._image.isVisible() or card._image.height() == 0
            assert card._title.full_text() == "View 1"
            assert getattr(page._previews[ref], "captured_digest", None) == "keep"


def _on_stage_host_rect(*, x: int, y: int, w: int, h: int, visible: bool = True) -> dict:
    return {
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "visible": visible,
        "space": HOST_COORD_SPACE,
    }


def _valid_chrome_facts(**overrides) -> dict:
    stage = _on_stage_host_rect(x=0, y=0, w=1600, h=900)
    target = _on_stage_host_rect(x=200, y=180, w=240, h=160)
    handles = _on_stage_host_rect(x=182, y=162, w=276, h=196)
    toolbar = _on_stage_host_rect(x=220, y=120, w=200, h=48)
    picker = _on_stage_host_rect(x=220, y=360, w=160, h=120)
    trigger = _on_stage_host_rect(x=220, y=340, w=40, h=14)
    minimap = _on_stage_host_rect(x=1420, y=728, w=168, h=112)
    facts = {
        "space": HOST_COORD_SPACE,
        "stage": stage,
        "target": target,
        "selection_bounds": dict(target),
        "handles": handles,
        "toolbar": toolbar,
        "picker": picker,
        "trigger": trigger,
        "minimap": minimap,
    }
    facts.update(overrides)
    return facts


def _shot_stub_manifest(*, minimap=None, picker=None, schema_version=MANIFEST_SCHEMA_VERSION):
    return {
        "schema_version": schema_version,
        "shots": {name: {"width": 20, "height": 20} for name in REQUIRED_SHOTS},
        "contact_sheet": "contact-sheet.png",
        "geometry": {
            "selected_bottom_right_with_minimap": {
                "minimap_selection": minimap,
            },
            "selected_shape_format_picker": {
                "format_picker": picker,
            },
        },
    }


def test_missing_schema_version_fails_closed():
    missing = _shot_stub_manifest()
    del missing["schema_version"]
    with pytest.raises(GeometryError) as exc:
        assert_geometry(missing)
    assert "schema_version" in str(exc.value)
    with pytest.raises(GeometryError) as exc:
        assert_geometry(_shot_stub_manifest(schema_version=None))
    assert "schema_version" in str(exc.value)


def test_wrong_schema_version_fails_closed():
    with pytest.raises(GeometryError) as exc:
        assert_geometry(_shot_stub_manifest(schema_version=1))
    assert "schema_version" in str(exc.value)


def test_vacuous_minimap_manifest_without_target_visibility_fails():
    old = {
        "minimap": {"x": 1420, "y": 728, "w": 168, "h": 112, "visible": True},
        "selection_bounds": {"x": -930, "y": -7114, "w": 819, "h": 460},
        "handles": {"x": -948, "y": -7132, "w": 855, "h": 496},
        "toolbar_visible": False,
        "clear_of_selection_chrome": True,
    }
    errors = _selection_chrome_errors(
        "selected_bottom_right_with_minimap", old, require_minimap=True
    )
    assert errors
    assert any("target" in error or "missing" in error for error in errors)
    with pytest.raises(GeometryError) as exc:
        assert_geometry(_shot_stub_manifest(minimap=old, picker=_valid_chrome_facts()))
    assert "selected_bottom_right_with_minimap" in str(exc.value)


def test_offstage_target_facts_fail_even_when_minimap_is_clear():
    facts = _valid_chrome_facts(
        target=_on_stage_host_rect(x=-930, y=-7114, w=819, h=460),
        selection_bounds=_on_stage_host_rect(x=-930, y=-7114, w=819, h=460),
        handles=_on_stage_host_rect(x=-948, y=-7132, w=855, h=496),
        toolbar=_hidden_host_rect(),
        picker=_hidden_host_rect(),
        clear_of_selection_chrome=True,
        folded=False,
        intersects_handles=False,
        intersects_toolbar=False,
    )
    errors = _selection_chrome_errors(
        "selected_bottom_right_with_minimap", facts, require_minimap=True
    )
    assert any("does not intersect stage" in error for error in errors)


def test_inconsistent_coordinate_space_fails():
    facts = _valid_chrome_facts(
        target=_on_stage_host_rect(x=200, y=180, w=240, h=160),
    )
    facts["target"] = {**facts["target"], "space": "page"}
    errors = _selection_chrome_errors(
        "selected_bottom_right_with_minimap", facts, require_minimap=True
    )
    assert any("host coordinates" in error for error in errors)


def test_format_picker_requires_visible_target_and_rejects_overlap():
    overlapping = _valid_chrome_facts(
        picker=_on_stage_host_rect(x=210, y=190, w=160, h=120),
        picker_visible=True,
    )
    errors = _selection_chrome_errors(
        "selected_shape_format_picker",
        overlapping,
        require_picker=True,
        require_toolbar=True,
    )
    assert any("overlaps" in error for error in errors)

    hidden_target = _valid_chrome_facts(target=_hidden_host_rect(), picker_visible=True)
    errors = _selection_chrome_errors(
        "selected_shape_format_picker",
        hidden_target,
        require_picker=True,
        require_toolbar=True,
    )
    assert any("target is not visible" in error for error in errors)


def test_required_chrome_must_stay_on_stage_and_picker_must_anchor():
    picker_offstage = _valid_chrome_facts(
        picker=_on_stage_host_rect(x=2000, y=2000, w=160, h=120),
    )
    errors = _selection_chrome_errors(
        "selected_shape_format_picker",
        picker_offstage,
        require_picker=True,
        require_toolbar=True,
    )
    assert any("picker is not contained by stage" in error for error in errors)

    minimap_offstage = _valid_chrome_facts(
        picker=_hidden_host_rect(),
        minimap=_on_stage_host_rect(x=2000, y=2000, w=168, h=112),
    )
    errors = _selection_chrome_errors(
        "selected_bottom_right_with_minimap",
        minimap_offstage,
        require_minimap=True,
    )
    assert any("minimap is not contained by stage" in error for error in errors)

    picker_unanchored = _valid_chrome_facts(
        picker=_on_stage_host_rect(x=800, y=600, w=160, h=120),
    )
    errors = _selection_chrome_errors(
        "selected_shape_format_picker",
        picker_unanchored,
        require_picker=True,
        require_toolbar=True,
    )
    assert any("not anchored" in error for error in errors)


def test_valid_required_chrome_is_contained_by_stage():
    facts = _valid_chrome_facts()
    assert _fact_contained_by(facts["picker"], facts["stage"])
    assert _fact_contained_by(facts["minimap"], facts["stage"])


def test_scrolling_selected_object_off_stage_fails_assert_geometry(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
    from mf4_analyzer.ui_kit import load_stylesheet

    load_stylesheet(qapp)
    page = UltraViewPage()
    qtbot.addWidget(page)
    _setup_selected_bottom_right_scene(qapp, page, scroll_off_stage=True)
    facts = _minimap_selection_facts(page)
    assert not _facts_intersect(facts.get("target"), facts.get("stage"))
    errors = _selection_chrome_errors(
        "selected_bottom_right_with_minimap", facts, require_minimap=True
    )
    assert errors
    assert any(
        "intersect" in error or "visible" in error or "missing" in error
        for error in errors
    )
    with pytest.raises(GeometryError) as exc:
        assert_geometry(
            _shot_stub_manifest(minimap=facts, picker=_valid_chrome_facts())
        )
    assert "selected_bottom_right_with_minimap" in str(exc.value)
