"""Freeze UltraView public seams after hardening, before Wave 1 file moves.

Copied from HEAD ``f439ba6ad6c799472b49112f2f0c5be26b5e7a1c``.  Do not load
``.state/ultraview-architecture/baseline.json``.  Owner behavior tests stay
in their modules; this file only machine-compares importable names, signal
wiring, and a few live chrome identifiers.

Owner tests (do not duplicate here):

- Projection refresh: ``test_ultraview_page.py``
  ``test_set_preview_and_status_noop_skips_projection``,
  ``test_apply_preview_and_status_projects_once_when_changed``
- Reset compare/library pin: ``test_reset_sheet_session_clears_compare_filter_and_library_pin``
- Move/resize hold planner/present/paint/reproject: ``test_ultraview_feedback_pipeline.py``
- Pointer routing: ``test_ultraview_board_hit_routing.py``
- Capture: ``test_ultraview_capture.py``
- Workspace reset/shutdown timers: ``test_ultraview_lifecycle_subprocess.py``
- Schema 1–5 / sidecar round-trip: ``test_ultraview_project_session.py``,
  ``test_ultraview_preview_sidecar.py``, ``test_ultraview_state.py``
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QToolButton

from mf4_analyzer.ui.chart_stack.ultraview import board_aux_widgets as board_aux_mod
from mf4_analyzer.ui.chart_stack.ultraview import card_widgets as card_widgets_mod
from mf4_analyzer.ui.chart_stack.ultraview import chrome as chrome_mod
from mf4_analyzer.ui.chart_stack.ultraview import free_grid_board as free_grid_board_mod
from mf4_analyzer.ui.chart_stack.ultraview import page as page_mod
from mf4_analyzer.ui.chart_stack.ultraview import template_board as template_board_mod
from mf4_analyzer.ui.chart_stack.ultraview import widgets as widgets_mod
from mf4_analyzer.ui.chart_stack.ultraview import (
    BASE_BOARD_SIZE,
    BOARD_PADDING,
    CARD_FOOTER_HEIGHT,
    CARD_HEADER_HEIGHT,
    MIN_CARD_CHROME_HEIGHT,
    SLOT_GUTTER,
    content_rect,
    slot_rects,
    MAX_PREVIEW_PIXELS,
    MAX_PREVIEW_RAW_EDGE,
    PreviewRecord,
    PreviewStore,
    UltraViewPage,
    BoardGrid,
    CompareRail,
    FocusLayer,
    LibraryRow,
    UnplacedTray,
    UltraViewCard,
    ViewLibraryPanel,
)
from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    BoardIsland,
    BoardPopover,
    CanvasHost,
    CardContextIsland,
    GlobalIsland,
    LayoutPicker,
    NavigationIsland,
    StatusIsland,
    ToolRail,
)
from mf4_analyzer.ui.chart_stack.ultraview.widgets import (
    BoardOverview,
    BoardScrollArea,
    BoardSwitcher,
    BoardToolbar,
    CardViewModel,
    EmptySlotWidget,
    FreeGridBoard,
    FreeGridCard,
    FreeGridMinimap,
    LibraryRowWidget,
    ReplaceHoverController,
    TrayItem,
    UltraViewHintBar,
)
from mf4_analyzer.ui.ultraview_edits import (
    SelectionMutationPlan,
    commit_selection_plan,
    plan_selection_delete,
    plan_selection_nudge,
)
from mf4_analyzer.ui.chart_stack.ultraview.floating_layout import (
    MinimapPlacementFacts,
    place_minimap,
)

from tests.ui.test_ultraview_page import _Harness


UI_ROOT = Path(__file__).resolve().parents[2] / "mf4_analyzer" / "ui"
ULTRAVIEW_ROOT = UI_ROOT / "chart_stack" / "ultraview"
WIDGETS_PATH = ULTRAVIEW_ROOT / "widgets.py"
CHROME_PATH = ULTRAVIEW_ROOT / "chrome.py"
PAGE_PATH = ULTRAVIEW_ROOT / "page.py"
INIT_PATH = ULTRAVIEW_ROOT / "__init__.py"
STATE_PATH = UI_ROOT / "ultraview_state.py"
COORDINATOR_PATH = UI_ROOT / "main_window" / "ultraview_coordinator.py"

# Wave 1 flips this after chrome.py / widgets.py become re-export façades.
WAVE1_FACADE_ACTIVE = False
# Chrome is a façade. widgets.py still owns residual ClassDefs (HintBar /
# Switcher / Toolbar / CompareRail); library/card/template/aux/free-grid moved.
WAVE1_CHROME_FACADE_ACTIVE = True

WAVE1_CHROME_IMPL = (
    "chrome_common.py",
    "canvas_host.py",
    "tool_rail.py",
    "chrome_islands.py",
    "chrome_popovers.py",
)
WAVE1_WIDGET_IMPL = (
    "widgets_common.py",
    "library_widgets.py",
    "card_widgets.py",
    "template_board.py",
    "board_aux_widgets.py",
    "free_grid_board.py",
)

# getattr surface on the widgets façade. Silent additions/removals of the
# re-export list fail until this tuple is updated.
FROZEN_WIDGETS_EXPORTED_CLASSES = (
    "ReplaceHoverController",
    "LibraryRow",
    "CardViewModel",
    "UltraViewHintBar",
    "BoardSwitcher",
    "BoardToolbar",
    "CompareRail",
    "LibraryRowWidget",
    "ViewLibraryPanel",
    "EmptySlotWidget",
    "UltraViewCard",
    "BoardGrid",
    "FreeGridCard",
    "FreeGridBoard",
    "FreeGridMinimap",
    "BoardScrollArea",
    "BoardOverview",
    "TrayItem",
    "UnplacedTray",
    "FocusLayer",
)

# AST ClassDef names not starting with ``_`` that still live in widgets.py.
# Exact match: a later wave that moves a residual class must shrink this tuple.
FROZEN_WIDGETS_PUBLIC_CLASSES = (
    "UltraViewHintBar",
    "BoardSwitcher",
    "BoardToolbar",
    "CompareRail",
)

FROZEN_CHROME_PUBLIC_CLASSES = (
    "CanvasHost",
    "ToolRail",
    "BoardIsland",
    "BoardPopover",
    "GlobalIsland",
    "NavigationIsland",
    "StatusIsland",
    "CardContextIsland",
    "LayoutPicker",
)

FROZEN_PACKAGE_ALL = (
    "BASE_BOARD_SIZE",
    "BOARD_PADDING",
    "CARD_FOOTER_HEIGHT",
    "CARD_HEADER_HEIGHT",
    "MIN_CARD_CHROME_HEIGHT",
    "SLOT_GUTTER",
    "content_rect",
    "slot_rects",
    "MAX_PREVIEW_PIXELS",
    "MAX_PREVIEW_RAW_EDGE",
    "PreviewRecord",
    "PreviewStore",
    "UltraViewPage",
    "BoardGrid",
    "CompareRail",
    "FocusLayer",
    "LibraryRow",
    "UnplacedTray",
    "UltraViewCard",
    "ViewLibraryPanel",
)

FROZEN_PAGE_SIGNALS = (
    "add_ref_requested",
    "replace_slot_requested",
    "swap_slots_requested",
    "place_from_unplaced_requested",
    "place_free_grid_from_unplaced_requested",
    "free_grid_insert_requested",
    "free_grid_replace_requested",
    "move_to_unplaced_requested",
    "remove_ref_requested",
    "open_source_requested",
    "sync_requested",
    "focus_requested",
    "rebind_arm_requested",
    "layout_changed",
    "ratio_nudge_requested",
    "copy_board_requested",
    "copy_card_image_requested",
    "export_png_requested",
    "presentation_toggled",
    "show_titles_toggled",
    "show_sources_toggled",
    "show_card_actions_toggled",
    "rebind_ref_requested",
    "locate_ref_requested",
    "compare_filter_changed",
    "quickref_requested",
    "selection_changed",
    "board_name_changed",
    "feedback_requested",
    "create_board_requested",
    "duplicate_board_requested",
    "rename_board_requested",
    "delete_board_requested",
    "reorder_board_requested",
    "select_board_requested",
    "free_grid_toggled",
    "free_grid_geometry_requested",
    "free_grid_group_geometry_requested",
    "free_grid_preset_requested",
    "free_grid_autofit_requested",
    "organize_free_grid_requested",
    "auto_arrange_requested",
    "free_grid_undo_requested",
    "free_grid_redo_requested",
    "camera_settled",
    "author_create_requested",
    "author_update_requested",
    "author_delete_requested",
    "author_batch_requested",
)

FROZEN_CONNECT_PAGE_SIGNALS = (
    "add_ref_requested",
    "replace_slot_requested",
    "rebind_ref_requested",
    "swap_slots_requested",
    "place_from_unplaced_requested",
    "place_free_grid_from_unplaced_requested",
    "free_grid_insert_requested",
    "free_grid_replace_requested",
    "move_to_unplaced_requested",
    "remove_ref_requested",
    "open_source_requested",
    "sync_requested",
    "focus_requested",
    "layout_changed",
    "ratio_nudge_requested",
    "presentation_toggled",
    "compare_filter_changed",
    "copy_board_requested",
    "copy_card_image_requested",
    "export_png_requested",
    "board_name_changed",
    "create_board_requested",
    "duplicate_board_requested",
    "rename_board_requested",
    "delete_board_requested",
    "reorder_board_requested",
    "select_board_requested",
    "free_grid_toggled",
    "free_grid_geometry_requested",
    "free_grid_group_geometry_requested",
    "free_grid_preset_requested",
    "free_grid_autofit_requested",
    "organize_free_grid_requested",
    "auto_arrange_requested",
    "free_grid_undo_requested",
    "free_grid_redo_requested",
    "author_create_requested",
    "author_update_requested",
    "author_delete_requested",
    "author_batch_requested",
    "show_titles_toggled",
    "show_sources_toggled",
    "show_card_actions_toggled",
    "feedback_requested",
    "camera_settled",
)

FROZEN_COORDINATOR_PUBLIC_METHODS = (
    "is_shutdown",
    "store",
    "note_source_mode",
    "bind_canvas",
    "bound_ref_for",
    "offer_capture_bound_canvas",
    "request_capture",
    "request_visible_section_capture",
    "notify_result_stored",
    "result_generation_for",
    "presentation_payload_for",
    "current_digest_for",
    "set_pinned_from_board",
    "project_source_mode",
    "to_project_payload",
    "restore_project_state",
    "board",
    "workspace",
    "save_preview_sidecar",
    "page",
    "attach",
    "capture_leaving_source",
    "add_from_source_tab",
    "open_source",
    "sync_preview",
    "refresh_page",
    "presentation_revision_for",
    "bump_presentation_revision",
    "copy_board_to_clipboard",
    "copy_card_to_clipboard",
    "choose_and_export_png",
    "export_png_to_path",
    "compose_board_image",
    "shutdown",
    "reset_project_state",
    "clear",
    "schedule_idle_capture",
)

FROZEN_PAGE_LIFECYCLE_METHODS = (
    "reset_sheet_session",
    "showEvent",
    "hideEvent",
    "set_board",
    "set_presentation_active",
)

FROZEN_FEEDBACK_PIPELINE_KEYS = (
    "planner",
    "presents",
    "paints",
    "generation",
    "gesture_id",
    "layout_revision",
)

FROZEN_INTERACTION_FACT_KEYS = (
    "author_geometry_active",
    "gesture_armed",
    "gesture_active",
    "marquee_active",
)

FROZEN_CHROME_OBJECT_NAMES = (
    ("canvas_host", "ultraViewCanvasHost"),
    ("tool_rail", "ultraViewToolRail"),
    ("board_island", "ultraViewBoardIsland"),
    ("board_popover", "ultraViewBoardPopover"),
    ("global_island", "ultraViewGlobalIsland"),
    ("navigation_island", "ultraViewNavigationIsland"),
    ("status_island", "ultraViewStatusIsland"),
    ("card_context_island", "ultraViewCardContextIsland"),
)

LAYOUT_PICKER_OBJECT_NAME = "ultraViewLayoutPopover"

# Production supported surface: coordinator + page imports, plus public
# ClassDefs in ultraview_state.py, plus ``make_ref`` (test/harness identity).
FROZEN_ULTRAVIEW_STATE_IMPORTS = (
    "AnchorTarget",
    "AuthorCommon",
    "AuthorMutationResult",
    "AxisConsistencyFacts",
    "BoardBox",
    "BoardEditEntry",
    "BoardItemKey",
    "BoardPlacementSnapshot",
    "BoardPoint",
    "COMPARE_FILTER_ALL",
    "CardPlacement",
    "ConnectorEndpoint",
    "ConnectorObject",
    "DEFAULT_BOARD_NAME",
    "FreeGridPlacement",
    "FreeGridRectPlan",
    "GridAnchor",
    "GridBounds",
    "GridRect",
    "LAYOUT_MODE_FREE_GRID",
    "LAYOUT_SLOTS",
    "MAX_UI_BOARDS",
    "ObjectPatch",
    "PreviewMeta",
    "SECTION_AXIS_KIND",
    "SOURCE_SECTIONS",
    "STATUS_ORPHANED",
    "STATUS_STALE",
    "ShapeObject",
    "ShapeTextStyle",
    "StickyObject",
    "StrokeObject",
    "TextObject",
    "ULTRAVIEW_PAGE_OBJECT_NAME",
    "UltraViewBoardState",
    "UltraViewRef",
    "UltraViewStateError",
    "UltraViewWorkspaceState",
    "UnknownAuthorObject",
    "active_board",
    "add_ref",
    "all_refs",
    "apply_board_edit_entry",
    "apply_board_placement",
    "apply_free_grid_preset",
    "axis_consistency_facts",
    "best_template_for",
    "board_edit_entry_byte_cost",
    "board_to_payload",
    "capture_board_placement",
    "card_matches_compare_filter",
    "create_board",
    "default_board",
    "default_workspace",
    "delete_board",
    "derive_preview_status",
    "duplicate_board",
    "first_empty_slot",
    "free_grid_default_span",
    "free_grid_placement_for",
    "free_grid_to_template",
    "layout_capacity",
    "layout_slots",
    "make_ref",
    "mark_workspace_mutated",
    "membership_set",
    "move_to_unplaced",
    "normalize_workspace_payload",
    "nudge_ratio",
    "organize_free_grid",
    "parse_ref_payload",
    "place_free_grid_from_unplaced",
    "place_from_unplaced",
    "placed_ref_set",
    "placement_for",
    "presentation_digest",
    "rebind_ref",
    "remove_ref",
    "rename_board",
    "reorder_board",
    "replace_free_grid_ref",
    "replace_slot",
    "set_active_board",
    "set_free_grid_rect",
    "set_free_grid_rects",
    "set_layout",
    "set_presentation_flags",
    "set_workspace_preview_sidecar",
    "set_workspace_show_card_actions",
    "slot_occupant",
    "swap_slots",
    "template_to_free_grid",
    "workspace_to_payload",
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _public_classdefs(path: Path) -> tuple[str, ...]:
    return tuple(
        node.name
        for node in _parse(path).body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    )


def _class_node(path: Path, class_name: str) -> ast.ClassDef:
    for node in _parse(path).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"{class_name} not found in {path.name}")


def _pyqt_signal_names(path: Path, class_name: str) -> tuple[str, ...]:
    names: list[str] = []
    for item in _class_node(path, class_name).body:
        if not isinstance(item, ast.Assign) or not isinstance(item.value, ast.Call):
            continue
        func = item.value.func
        callee = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if callee != "pyqtSignal":
            continue
        for target in item.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return tuple(names)


def _connect_page_signal_names() -> tuple[str, ...]:
    for item in _class_node(COORDINATOR_PATH, "UltraViewCoordinator").body:
        if not isinstance(item, ast.FunctionDef) or item.name != "_connect_page":
            continue
        for stmt in item.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "pairs" for target in stmt.targets):
                continue
            if not isinstance(stmt.value, ast.Tuple):
                raise AssertionError("_connect_page pairs is not a tuple")
            names: list[str] = []
            for elt in stmt.value.elts:
                if not isinstance(elt, ast.Tuple) or not elt.elts:
                    continue
                left = elt.elts[0]
                if isinstance(left, ast.Attribute):
                    names.append(left.attr)
            return tuple(names)
    raise AssertionError("UltraViewCoordinator._connect_page pairs tuple not found")


def _coordinator_public_methods() -> tuple[str, ...]:
    return tuple(
        item.name
        for item in _class_node(COORDINATOR_PATH, "UltraViewCoordinator").body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not item.name.startswith("_")
    )


def _returned_dict_keys(path: Path, class_name: str, method_name: str) -> tuple[str, ...]:
    for item in _class_node(path, class_name).body:
        if not isinstance(item, ast.FunctionDef) or item.name != method_name:
            continue
        for node in item.body:
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                keys: list[str] = []
                for key in node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.append(key.value)
                return tuple(keys)
    raise AssertionError(f"{class_name}.{method_name} dict return not found")


def _imported_ultraview_state_names(*paths: Path) -> set[str]:
    names: set[str] = set()
    for path in paths:
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if not module.endswith("ultraview_state"):
                continue
            for alias in node.names:
                if not alias.name.startswith("_"):
                    names.add(alias.name)
    return names


def test_widgets_public_classes_import_and_match_page_identity():
    imported = (
        ReplaceHoverController,
        LibraryRow,
        CardViewModel,
        UltraViewHintBar,
        BoardSwitcher,
        BoardToolbar,
        CompareRail,
        LibraryRowWidget,
        ViewLibraryPanel,
        EmptySlotWidget,
        UltraViewCard,
        BoardGrid,
        FreeGridCard,
        FreeGridBoard,
        FreeGridMinimap,
        BoardScrollArea,
        BoardOverview,
        TrayItem,
        UnplacedTray,
        FocusLayer,
    )
    assert imported == tuple(getattr(widgets_mod, name) for name in FROZEN_WIDGETS_EXPORTED_CLASSES)
    assert widgets_mod.UltraViewCard is page_mod.UltraViewCard
    assert widgets_mod.UltraViewCard is UltraViewCard
    assert widgets_mod.UltraViewCard is card_widgets_mod.UltraViewCard
    assert widgets_mod.FreeGridCard is card_widgets_mod.FreeGridCard
    assert widgets_mod.BoardGrid is template_board_mod.BoardGrid
    assert widgets_mod.EmptySlotWidget is template_board_mod.EmptySlotWidget
    assert widgets_mod.BoardScrollArea is board_aux_mod.BoardScrollArea
    assert widgets_mod.FreeGridMinimap is board_aux_mod.FreeGridMinimap
    assert widgets_mod.BoardOverview is board_aux_mod.BoardOverview
    assert widgets_mod.FocusLayer is board_aux_mod.FocusLayer
    assert widgets_mod.FreeGridBoard is FreeGridBoard
    assert widgets_mod.FreeGridBoard is free_grid_board_mod.FreeGridBoard


def test_chrome_public_classes_import_and_match_page_identity():
    imported = (
        CanvasHost,
        ToolRail,
        BoardIsland,
        BoardPopover,
        GlobalIsland,
        NavigationIsland,
        StatusIsland,
        CardContextIsland,
        LayoutPicker,
    )
    assert imported == tuple(getattr(chrome_mod, name) for name in FROZEN_CHROME_PUBLIC_CLASSES)
    assert chrome_mod.ToolRail is page_mod.ToolRail
    assert chrome_mod.ToolRail is ToolRail


def test_monkeypatch_seams_remain_module_attributes():
    assert widgets_mod.FreeGridBoard is FreeGridBoard
    assert chrome_mod.ToolRail is ToolRail
    assert hasattr(widgets_mod, "FreeGridBoard")
    assert hasattr(chrome_mod, "ToolRail")


def test_package_all_matches_frozen_exports():
    from mf4_analyzer.ui.chart_stack import ultraview as pkg

    assert tuple(pkg.__all__) == FROZEN_PACKAGE_ALL
    exported = {
        "BASE_BOARD_SIZE": BASE_BOARD_SIZE,
        "BOARD_PADDING": BOARD_PADDING,
        "CARD_FOOTER_HEIGHT": CARD_FOOTER_HEIGHT,
        "CARD_HEADER_HEIGHT": CARD_HEADER_HEIGHT,
        "MIN_CARD_CHROME_HEIGHT": MIN_CARD_CHROME_HEIGHT,
        "SLOT_GUTTER": SLOT_GUTTER,
        "content_rect": content_rect,
        "slot_rects": slot_rects,
        "MAX_PREVIEW_PIXELS": MAX_PREVIEW_PIXELS,
        "MAX_PREVIEW_RAW_EDGE": MAX_PREVIEW_RAW_EDGE,
        "PreviewRecord": PreviewRecord,
        "PreviewStore": PreviewStore,
        "UltraViewPage": UltraViewPage,
        "BoardGrid": BoardGrid,
        "CompareRail": CompareRail,
        "FocusLayer": FocusLayer,
        "LibraryRow": LibraryRow,
        "UnplacedTray": UnplacedTray,
        "UltraViewCard": UltraViewCard,
        "ViewLibraryPanel": ViewLibraryPanel,
    }
    for name in FROZEN_PACKAGE_ALL:
        assert getattr(pkg, name) is exported[name]


def test_ultraview_state_supported_surface_resolves():
    import mf4_analyzer.ui.ultraview_state as state

    missing = [name for name in FROZEN_ULTRAVIEW_STATE_IMPORTS if not hasattr(state, name)]
    assert missing == []
    consumer_imports = _imported_ultraview_state_names(COORDINATOR_PATH, PAGE_PATH)
    unexpected = sorted(consumer_imports - set(FROZEN_ULTRAVIEW_STATE_IMPORTS))
    assert unexpected == []


def test_ultraview_state_reexports_core_model_identity():
    import mf4_analyzer.ui.ultraview_state as state
    from mf4_analyzer.ultraview_core import model

    assert state.UltraViewRef is model.UltraViewRef
    assert state.GridRect is model.GridRect
    assert state.UltraViewBoardState is model.UltraViewBoardState
    assert state.UltraViewWorkspaceState is model.UltraViewWorkspaceState
    assert state.GRID_RESOLUTION == 2
    assert state.GRID_RESOLUTION is model.GRID_RESOLUTION
    assert state.clamp_grid_rect is model.clamp_grid_rect

    from mf4_analyzer.ultraview_core import board_ops

    assert state.add_ref is board_ops.add_ref
    assert state.create_board is board_ops.create_board
    assert state.set_free_grid_rects is board_ops.set_free_grid_rects

    from mf4_analyzer.ultraview_core import author_ops

    assert state.create_author_object is author_ops.create_author_object
    assert state.apply_board_edit_entry is author_ops.apply_board_edit_entry

    from mf4_analyzer.ultraview_core import presentation

    assert state.derive_preview_status is presentation.derive_preview_status
    assert state.axis_consistency_facts is presentation.axis_consistency_facts

    from mf4_analyzer.ultraview_core import serialization

    assert state.normalize_board_payload is serialization.normalize_board_payload
    assert state.presentation_digest is serialization.presentation_digest
    assert state.board_to_payload is serialization.board_to_payload
    assert state.workspace_to_payload is serialization.workspace_to_payload
    assert state.ULTRAVIEW_SCHEMA is serialization.ULTRAVIEW_SCHEMA


def test_hardening_reuse_names_are_the_live_seams():
    assert SelectionMutationPlan.__name__ == "SelectionMutationPlan"
    assert callable(plan_selection_nudge)
    assert callable(plan_selection_delete)
    assert callable(commit_selection_plan)
    assert callable(place_minimap)
    assert MinimapPlacementFacts.__name__ == "MinimapPlacementFacts"


def test_widgets_and_chrome_public_classdefs_are_frozen():
    widgets_classes = _public_classdefs(WIDGETS_PATH)
    chrome_classes = _public_classdefs(CHROME_PATH)
    if WAVE1_FACADE_ACTIVE:
        assert widgets_classes == ()
        assert chrome_classes == ()
        return
    assert widgets_classes == FROZEN_WIDGETS_PUBLIC_CLASSES
    if WAVE1_CHROME_FACADE_ACTIVE:
        assert chrome_classes == ()
        assert tuple(getattr(chrome_mod, name) for name in FROZEN_CHROME_PUBLIC_CLASSES) == (
            CanvasHost,
            ToolRail,
            BoardIsland,
            BoardPopover,
            GlobalIsland,
            NavigationIsland,
            StatusIsland,
            CardContextIsland,
            LayoutPicker,
        )
        return
    assert chrome_classes == FROZEN_CHROME_PUBLIC_CLASSES


@pytest.mark.skipif(
    not WAVE1_FACADE_ACTIVE,
    reason="Wave 1 façade not active; widgets.py/chrome.py still own ClassDefs",
)
def test_wave1_facade_modules_are_reexports_only():
    assert _public_classdefs(WIDGETS_PATH) == ()
    assert _public_classdefs(CHROME_PATH) == ()
    for name in WAVE1_CHROME_IMPL + WAVE1_WIDGET_IMPL:
        path = ULTRAVIEW_ROOT / name
        assert path.is_file(), f"Wave 1 implementation module missing: {name}"
    assert "ToolRail" in _public_classdefs(ULTRAVIEW_ROOT / "tool_rail.py")
    assert widgets_mod.FreeGridBoard is not None
    assert chrome_mod.ToolRail is not None


def test_page_signal_names_are_frozen():
    names = _pyqt_signal_names(PAGE_PATH, "UltraViewPage")
    assert names == FROZEN_PAGE_SIGNALS
    assert len(names) == 49
    for name in names:
        assert hasattr(UltraViewPage, name)


def test_coordinator_connect_page_pairs_are_frozen():
    names = _connect_page_signal_names()
    assert names == FROZEN_CONNECT_PAGE_SIGNALS
    assert len(names) == 45
    page_signals = set(FROZEN_PAGE_SIGNALS)
    unknown = [name for name in names if name not in page_signals]
    assert unknown == []


def test_page_lifecycle_public_methods_exist():
    # Full controller-order ledger skipped: hide/show call private
    # ``_viewport_router``; a true show/hide/reset/Board-switch/presentation
    # sequence would need new production hooks. Owner coverage stays in
    # ``test_reset_sheet_session_clears_compare_filter_and_library_pin`` and
    # ``test_presentation_restores_visible_global_edit_controls``.
    for name in FROZEN_PAGE_LIFECYCLE_METHODS:
        assert hasattr(UltraViewPage, name)


def test_chrome_object_names_focus_and_activation_are_stable(qtbot):
    harness = _Harness(qtbot)
    page = harness.page
    for accessor, object_name in FROZEN_CHROME_OBJECT_NAMES:
        widget = getattr(page, accessor)()
        assert widget.objectName() == object_name
    picker = page.findChild(QFrame, LAYOUT_PICKER_OBJECT_NAME)
    assert picker is not None
    assert isinstance(picker, LayoutPicker)

    host = page.canvas_host()
    island = page.board_island()
    popover = page.board_popover()
    assert host.focusPolicy() == Qt.StrongFocus
    assert island.focusPolicy() == Qt.StrongFocus
    assert popover.focusPolicy() == Qt.NoFocus
    assert str(island.accessibleName()).startswith("当前 Board")
    assert page.status_island().accessibleName()

    display = page.global_island().display_button()
    assert display.isEnabled()
    assert display.focusPolicy() == Qt.TabFocus
    assert display.accessibleName() == "显示标题和来源"

    library = page.tool_rail().findChild(QToolButton, "ultraViewRailLibraryButton")
    assert library is not None
    assert library.isEnabled()
    assert library.focusPolicy() == Qt.TabFocus

    page.hide()
    page.show()
    page.reset_sheet_session()
    assert page.tool_rail().objectName() == "ultraViewToolRail"
    assert page.canvas_host().objectName() == "ultraViewCanvasHost"


def test_feedback_pipeline_count_keys_are_frozen():
    keys = _returned_dict_keys(
        ULTRAVIEW_ROOT / "free_grid_board.py", "FreeGridBoard", "feedback_pipeline_counts"
    )
    assert keys == FROZEN_FEEDBACK_PIPELINE_KEYS


def test_interaction_facts_keys_are_frozen():
    keys = _returned_dict_keys(
        ULTRAVIEW_ROOT / "free_grid_board.py", "FreeGridBoard", "interaction_facts"
    )
    assert keys == FROZEN_INTERACTION_FACT_KEYS


def test_coordinator_public_methods_are_frozen():
    names = _coordinator_public_methods()
    assert names == FROZEN_COORDINATOR_PUBLIC_METHODS
    assert len(names) == 37
    for required in ("shutdown", "reset_project_state", "clear"):
        assert required in names


def test_init_source_still_reexports_package_all():
    tree = _parse(INIT_PATH)
    all_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            all_node = node.value
            break
    assert isinstance(all_node, ast.List)
    names = tuple(
        elt.value
        for elt in all_node.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    )
    assert names == FROZEN_PACKAGE_ALL
