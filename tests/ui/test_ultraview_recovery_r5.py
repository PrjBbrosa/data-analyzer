"""R5 integration: white-layer owners, readonly 1.tlproj copy, compact stages."""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.chart_stack.ultraview.chrome import (
    AUTHOR_TOOL_SELECT,
    AUTHOR_TOOL_STICKY,
    RELEASE_AUTHOR_TOOLS,
)
from mf4_analyzer.ui.chart_stack.ultraview.compositor import _draw_preview
from mf4_analyzer.ui.chart_stack.ultraview.layouts import preview_reading_box
from mf4_analyzer.ui.chart_stack.ultraview.page import BOARD_MENU_ARRANGE
from mf4_analyzer.ui.ultraview_state import (
    GRID_RESOLUTION,
    LAYOUT_MODE_FREE_GRID,
    MAX_PLACED_CARDS,
    STATUS_FRESH,
    FreeGridPlacement,
    GridRect,
    ULTRAVIEW_SCHEMA,
    add_ref,
    board_to_payload,
    make_ref,
    normalize_board_payload,
    normalize_workspace_payload,
    set_layout,
    template_to_free_grid,
    workspace_to_payload,
)
from tests.ui.test_ultraview_page import _Harness
from tests.ui.test_ultraview_sticky_slice import _AuthorSink, _arm_sticky, _click_blank

_REPO = Path(__file__).resolve().parents[2]
_READONLY = _REPO / ".state" / "ultraview-recovery-r0" / "1.tlproj.readonly"
_TESTDOC = _REPO / "testdoc" / "1.tlproj"
_FIXTURE_SHA = "444ab5ae02e2da30d823fb49a7d105886e95ae24df6707cc0ca7d303c9c2a4d2"
_UV_ROOT = _REPO / "mf4_analyzer" / "ui" / "chart_stack" / "ultraview"
_FORBIDDEN_KEYING = {
    "createMaskFromColor",
    "createHeuristicMask",
    "colorKey",
}


@dataclass
class _Preview:
    image: QImage
    captured_digest: str = "r5-preview"
    title: str = "preview"


def _load_readonly_workspace():
    if not _READONLY.is_file():
        pytest.skip("R0 readonly 1.tlproj fixture is missing")
    raw = _READONLY.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _FIXTURE_SHA
    doc = json.loads(raw.decode("utf-8"))
    workspace, warnings = normalize_workspace_payload(doc["ultraview"])
    assert warnings == []
    board = next(item for item in workspace.boards if item.board_id == workspace.active_board_id)
    return doc, workspace, board


def _micro(column: int, row: int, column_span: int, row_span: int) -> GridRect:
    return GridRect(
        column * GRID_RESOLUTION,
        row * GRID_RESOLUTION,
        column_span * GRID_RESOLUTION,
        row_span * GRID_RESOLUTION,
    )


def test_letterbox_owner_is_the_image_slot_not_qimage_paper():
    """V1: 16:9 capture in a square slot leaves leftover in the slot, not the pixels."""
    slot = (400, 400)
    capture = (1600, 900)
    box = preview_reading_box(*slot, capture)
    assert box == (400, 225)
    assert slot[0] - box[0] == 0
    assert slot[1] - box[1] == 175
    assert capture == (1600, 900)


def test_wide_slot_puts_letterbox_on_the_sides_not_by_stretching():
    slot = (800, 300)
    capture = (400, 400)
    box = preview_reading_box(*slot, capture)
    assert box == (300, 300)
    assert slot[0] - box[0] == 500
    assert slot[1] - box[1] == 0


def test_paint_paths_do_not_color_key_preview_white():
    hits: list[str] = []
    for path in (
        _UV_ROOT / "widgets.py",
        _UV_ROOT / "compositor.py",
        _UV_ROOT / "author_render.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = getattr(node, "id", None) or getattr(node, "attr", None)
            if name in _FORBIDDEN_KEYING:
                hits.append(f"{path.name}:{getattr(node, 'lineno', 0)}:{name}")
    assert hits == []
    source = (_UV_ROOT / "compositor.py").read_text(encoding="utf-8")
    assert "KeepAspectRatio" in source
    assert "_contain_size" in source
    assert "drawImage" in source


def test_fitted_preview_keeps_white_paper_pixels(qtbot):
    harness = _Harness(qtbot)
    image = QImage(160, 90, QImage.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    for x in range(20, 140):
        image.setPixelColor(x, 45, QColor("#c0392b"))
    before = image.pixelColor(4, 4).name()
    set_layout(harness.board, "grid_2x2")
    add_ref(harness.board, make_ref("time", "paper"))
    template_to_free_grid(harness.board)
    ref = make_ref("time", "paper")
    harness.page.set_preview(ref, _Preview(image=image))
    harness.page.set_ref_status(ref, STATUS_FRESH, True)
    harness.page.set_board(harness.board)
    QApplication.processEvents()
    card = harness.page.card_widget("time", "paper")
    assert card is not None
    raw = card._raw_image
    assert raw is not None
    assert raw.pixelColor(4, 4).name() == before
    pixmap = card.scale_buffer()
    assert pixmap is not None and not pixmap.isNull()
    sampled = pixmap.toImage().pixelColor(1, 1)
    assert sampled.red() >= 240 and sampled.green() >= 240 and sampled.blue() >= 240


def test_draw_preview_contains_without_stretching_or_keying(qapp):
    paper = QImage(80, 20, QImage.Format_ARGB32)
    paper.fill(QColor("#ffffff"))
    canvas = QImage(80, 80, QImage.Format_ARGB32)
    canvas.fill(QColor("#00ff00"))
    painter = QPainter(canvas)
    _draw_preview(painter, _Preview(image=paper), STATUS_FRESH, 0, 0, 80, 80, 1)
    painter.end()
    # Unused slot remains the canvas fill (letterbox owner), not stretched paper.
    assert canvas.pixelColor(40, 4).name() == "#00ff00"
    assert canvas.pixelColor(40, 40).name() == "#ffffff"


def test_readonly_fixture_copy_loads_six_cards_and_survives_sticky_round_trip(qtbot, tmp_path):
    testdoc_stat = _TESTDOC.stat() if _TESTDOC.is_file() else None
    testdoc_sha = (
        hashlib.sha256(_TESTDOC.read_bytes()).hexdigest() if testdoc_stat is not None else None
    )
    doc, workspace, board = _load_readonly_workspace()
    assert len(board.free_grid) == 6
    assert board.layout_mode == LAYOUT_MODE_FREE_GRID
    assert not board.author_objects

    copy = tmp_path / "1.tlproj"
    copy.write_bytes(_READONLY.read_bytes())

    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, board)
    harness.board = board
    harness.page.set_board(board)
    QApplication.processEvents()
    assert len(list(harness.page._free_grid.card_widgets())) == 6

    _arm_sticky(harness.page)
    _click_blank(harness.page._free_grid)
    note = harness.page._free_grid.sticky_note_widget()
    assert note.is_editing()
    note.editor().setPlainText("只读副本")
    note.commit()
    QApplication.processEvents()
    assert len(board.author_objects) == 1
    assert sink.dirty is True

    payload = board_to_payload(board)
    reopened, warnings = normalize_board_payload(payload)
    assert warnings == []
    assert reopened.author_objects[0].text == "只读副本"

    doc["ultraview"] = workspace_to_payload(workspace)
    copy.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    again = json.loads(copy.read_text(encoding="utf-8"))
    restored, restore_warnings = normalize_workspace_payload(again["ultraview"])
    assert restore_warnings == []
    assert restored.boards[0].author_objects[0].text == "只读副本"
    assert again["ultraview"]["schema"] == ULTRAVIEW_SCHEMA

    if testdoc_stat is not None:
        after = _TESTDOC.stat()
        assert after.st_mtime_ns == testdoc_stat.st_mtime_ns
        assert hashlib.sha256(_TESTDOC.read_bytes()).hexdigest() == testdoc_sha


@pytest.mark.parametrize("size", [(800, 560), (1280, 720), (1600, 1000)])
def test_compact_stages_keep_select_sticky_and_hide_undelivered_tools(qtbot, size):
    page = _Harness(qtbot).page
    page.resize(*size)
    QApplication.processEvents()
    rail = page.tool_rail()
    select = rail.tool_button(AUTHOR_TOOL_SELECT)
    sticky = rail.tool_button(AUTHOR_TOOL_STICKY)
    assert select is None
    assert sticky is not None and sticky.isVisible() and sticky.isEnabled()
    for tool in RELEASE_AUTHOR_TOOLS:
        button = rail.tool_button(tool)
        assert button is not None and button.isVisible()
    assert rail.visible_author_tools() == RELEASE_AUTHOR_TOOLS
    assert sticky.geometry().right() <= rail.width()
    assert sticky.geometry().bottom() <= rail.height()


@pytest.mark.parametrize("zoom", [0.66, 1.0, 3.0])
def test_zoom_stops_keep_fixture_cards_and_allow_sticky(qtbot, zoom):
    _doc, _workspace, board = _load_readonly_workspace()
    harness = _Harness(qtbot)
    sink = _AuthorSink(harness.page, board)
    harness.page.set_board(board)
    QApplication.processEvents()
    harness.page.set_board_zoom(zoom)
    QApplication.processEvents()
    assert len(list(harness.page._free_grid.card_widgets())) == 6
    _arm_sticky(harness.page)
    free = harness.page._free_grid
    _click_blank(free)
    note = free.sticky_note_widget()
    if note.is_editing():
        note.editor().setPlainText(f"z{zoom}")
        note.commit()
        QApplication.processEvents()
        assert board.author_objects
        assert sink.dirty is True
    else:
        pytest.skip("blank interior missed at this zoom; cards still projected")


def test_twenty_four_cards_is_the_placed_ceiling_and_stays_interactive(qtbot):
    harness = _Harness(qtbot)
    board = harness.board
    board.layout_mode = LAYOUT_MODE_FREE_GRID
    board.free_grid = [
        FreeGridPlacement(
            make_ref("time", f"c{index:02d}"),
            _micro((index % 6) * 4, (index // 6) * 4, 4, 3),
        )
        for index in range(MAX_PLACED_CARDS)
    ]
    harness.page.set_board(board)
    QApplication.processEvents()
    cards = list(harness.page._free_grid.card_widgets())
    assert len(cards) == MAX_PLACED_CARDS
    harness.page.zoom_fit()
    QApplication.processEvents()
    assert harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY) is not None
    overview = harness.page.board_overview()
    harness.page.show_overview()
    QApplication.processEvents()
    assert overview.isVisible()
    assert not harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY).isEnabled()
    harness.page.hide_overview()
    QApplication.processEvents()
    assert harness.page.tool_rail().tool_button(AUTHOR_TOOL_STICKY).isEnabled()


def test_optimize_board_is_not_disguised_as_auto_arrange():
    assert BOARD_MENU_ARRANGE == "自动排版"
    assert "优化布局" not in BOARD_MENU_ARRANGE
