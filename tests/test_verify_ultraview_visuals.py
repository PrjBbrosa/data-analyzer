"""UltraView visual harness: geometry assertions, contact sheet, default output."""
from __future__ import annotations

import ast
from pathlib import Path

from tools.verify_ultraview_visuals import (
    DEFAULT_OUTPUT,
    REQUIRED_SHOTS,
    _Preview,
    generate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "verify_ultraview_visuals.py"


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
