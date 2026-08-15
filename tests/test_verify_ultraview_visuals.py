"""UltraView visual harness: geometry assertions, contact sheet, default output."""
from __future__ import annotations

import ast
import contextlib
import json
from pathlib import Path

from tools.verify_ultraview_visuals import (
    DEFAULT_OUTPUT,
    REQUIRED_SHOTS,
    GeometryError,
    _library_constants,
    _library_errors,
    _Preview,
    generate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "verify_ultraview_visuals.py"


def _library_manifest(
    *,
    overview_panel: dict | None = None,
    section: dict | None = None,
    catalog_height: int | None = None,
    stale_catalog_height: int | None = None,
) -> dict:
    """Synthetic manifest slice exercising the library contract in isolation.

    Built from the live constants so the fixture cannot drift away from the
    product; the callers below vary one fact at a time.
    """
    constants = _library_constants()
    panel = {"x": 68, "y": 64, "w": 470, "h": 560, "visible": True}
    card = catalog_height
    if card is None:
        card = constants["LIBRARY_CATALOG_HEIGHT"]
    stale_card = card if stale_catalog_height is None else stale_catalog_height
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
                    "catalog_cards": {"time": card},
                }
            },
            "library_overview_stale_1280": {
                "library": {
                    "panel": dict(panel),
                    "browse_mode": constants["LIBRARY_MODE_COMPACT"],
                    "sections": {},
                    "catalog_cards": {"time": stale_card},
                }
            },
            "library_overview_1280": {
                "library": {
                    "panel": dict(overview_panel or panel),
                    "browse_mode": constants["LIBRARY_MODE_COMPACT"],
                    "sections": {},
                    "catalog_cards": {"time": card},
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


def test_required_shots_cover_both_library_browse_modes():
    assert "library_groups_1280" in REQUIRED_SHOTS
    assert "library_overview_1280" in REQUIRED_SHOTS
    # The stale frame is a separate required shot, not a nicety: it is the only
    # state that still has spare height for the catalog cards to balloon into.
    assert "library_overview_stale_1280" in REQUIRED_SHOTS


def test_library_contract_accepts_a_panel_that_does_not_move():
    errors = _library_errors(_library_manifest())
    assert _matching(errors, "panel rect changed") == []
    assert _matching(errors, "is clipped") == []
    assert _matching(errors, "catalog card") == []


def test_library_contract_catches_a_panel_rect_that_jumps():
    """The load-bearing assertion: only panel *content* changed between shots."""
    manifest = _library_manifest(
        overview_panel={"x": 68, "y": 147, "w": 470, "h": 356, "visible": True}
    )
    assert _matching(_library_errors(manifest), "panel rect changed")


def test_library_contract_catches_a_clipped_section_and_a_ballooned_card():
    clipped = _library_manifest(
        section={"height": 164, "min_hint": 215, "visible": True}
    )
    assert _matching(_library_errors(clipped), "'time' is clipped")
    ballooned = _library_manifest(catalog_height=80)
    assert _matching(_library_errors(ballooned), "catalog card 'time' height=80")


def test_library_contract_catches_a_balloon_only_the_stale_frame_shows():
    """A build can render 40px cards after a reflow and 100px before it.

    Checking only the re-laid-out shot is what let this harness call such a
    build healthy, so the stale shot carries its own assertion.
    """
    manifest = _library_manifest(stale_catalog_height=100)
    errors = _library_errors(manifest)
    assert _matching(errors, "library_overview_stale_1280 catalog card 'time' height=100")
    assert _matching(errors, "library_overview_1280 catalog card") == []


def test_library_shots_record_the_anti_jump_facts(qapp, tmp_path):
    """Facts layer: the manifest carries the library geometry either way.

    ``generate`` writes manifest.json before it runs ``assert_geometry``, so the
    facts are read off disk rather than off the return value — enforcing the
    contract stays the job of the geometry test above, and this one keeps
    working while the product is still red.
    """
    with contextlib.suppress(GeometryError):
        generate(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for name in (
        "library_groups_1280",
        "library_overview_stale_1280",
        "library_overview_1280",
    ):
        assert (tmp_path / manifest["shots"][name]["path"]).is_file(), name
        facts = manifest["geometry"][name]["library"]
        assert facts["panel"]["visible"] is True, name
        assert facts["panel"]["w"] > 0 and facts["panel"]["h"] > 0, name
        assert set(facts["sections"]) == {"time", "fft", "fft_time", "frf", "order"}
        for section_facts in facts["sections"].values():
            assert section_facts["min_hint"] > 0
        assert facts["catalog_cards"]
        assert facts["row_heights"]
        assert facts["mode_tab_widths"] == [
            facts["mode_tabs"]["groups"]["w"],
            facts["mode_tabs"]["compact"]["w"],
        ]
    groups = manifest["geometry"]["library_groups_1280"]["library"]
    overview = manifest["geometry"]["library_overview_1280"]["library"]
    assert groups["browse_mode"] != overview["browse_mode"]


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
