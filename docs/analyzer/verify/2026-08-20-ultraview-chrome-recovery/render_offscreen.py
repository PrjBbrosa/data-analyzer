"""Offscreen structure shots for the 2026-08-20 chrome recovery. Not Cocoa."""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import QPoint, QSettings, Qt
from PyQt5.QtGui import QColor, QImage
from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    ShapeObject,
    StickyObject,
    add_ref,
    default_board,
    make_ref,
    set_layout,
    template_to_free_grid,
)
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet
from tests.ui.test_ultraview_page import FakePreview, LibraryRow, _image


def _isolate_settings(tmp: Path) -> None:
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp))


def _page(size: tuple[int, int]) -> UltraViewPage:
    page = UltraViewPage()
    page.resize(*size)
    page.show()
    board = default_board()
    set_layout(board, "grid_2x2")
    add_ref(board, make_ref("time", "shot-0"))
    template_to_free_grid(board)
    page.set_library_rows(
        [
            LibraryRow(
                section="time",
                view_id="shot-0",
                name="道路输入",
                source_summary="扭矩",
                tab_color="#3D79EF",
            )
        ]
    )
    page.set_board(board)
    ref = make_ref("time", "shot-0")
    page.set_preview(ref, FakePreview(ref=ref, image=_image(320, 180), axis_kind="time"))
    QApplication.processEvents()
    return page


def main() -> None:
    out = Path(__file__).resolve().parent
    tmp = out / ".qsettings"
    tmp.mkdir(exist_ok=True)
    _isolate_settings(tmp)
    app = QApplication.instance() or QApplication([])
    load_stylesheet(app)

    page = _page((1280, 720))
    card = page.card_widget("time", "shot-0")
    assert card is not None
    from PyQt5.QtTest import QTest

    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    page._refresh_author_toolbar()
    QApplication.processEvents()
    page.grab().save(str(out / "selected-card-toolbar.png"))

    shape = ShapeObject(
        "shape-shot",
        "shape",
        box=BoardBox(8.0, 8.0, 5.0, 4.0),
        shape="rectangle",
        text="形状",
    )
    page._board.author_objects = [shape]
    page.set_board(page._board)
    QApplication.processEvents()
    page.interaction().select_only_author("shape-shot")
    page._free_grid.sync_selection_projection()
    page._refresh_author_toolbar()
    QApplication.processEvents()
    page.grab().save(str(out / "selected-shape-toolbar.png"))

    page.interaction().clear_selection()
    page._refresh_author_toolbar()
    QApplication.processEvents()
    page.tool_rail().set_creation_enabled(True)
    page._show_sticky_popover()
    QApplication.processEvents()
    page._sticky_popover.grab().save(str(out / "sticky-flyout.png"))

    compact = _page((800, 560))
    card = compact.card_widget("time", "shot-0")
    QTest.mouseClick(card, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    compact._refresh_author_toolbar()
    QApplication.processEvents()
    compact.grab().save(str(out / "compact-800x560.png"))
    print("wrote", out)


if __name__ == "__main__":
    main()
