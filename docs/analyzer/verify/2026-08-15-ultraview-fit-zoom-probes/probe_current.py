"""UltraView fit / zoom / dismiss probes — spec §1.1 / §2.1 / §3.1.

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
  .venv/bin/python docs/analyzer/verify/2026-08-15-ultraview-fit-zoom-probes/probe_current.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from PyQt5.QtCore import QPoint, Qt  # noqa: E402
from PyQt5.QtTest import QTest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (  # noqa: E402
    fit_rect_for_aspect,
    rect_to_pixels,
    screen_grid_metrics,
)
from mf4_analyzer.ui.ultraview_state import GridRect  # noqa: E402
from tests.ui.test_ultraview_page import _Harness, _prepare_free_grid  # noqa: E402


def _section(title: str) -> None:
    print()
    print(f"== {title} ==")


def _widget_chain(widget) -> str:
    names = []
    current = widget
    while current is not None:
        names.append(current.objectName() or type(current).__name__)
        current = current.parentWidget()
    return " > ".join(names)


def probe_fit() -> None:
    _section("§1 fit_rect_for_aspect (image 1000x800)")
    metrics = screen_grid_metrics([])
    image = (1000, 800)
    for origin in (
        GridRect(0, 0, 4, 6),
        GridRect(0, 0, 10, 3),
        GridRect(0, 0, 6, 4),
        GridRect(0, 0, 2, 2),
    ):
        result = fit_rect_for_aspect(origin, image, metrics)
        ox, oy, ow, oh = rect_to_pixels(origin, metrics)
        rx, ry, rw, rh = rect_to_pixels(result, metrics)
        print(
            f"  origin {origin.column_span}x{origin.row_span} "
            f"({ow}x{oh}px) -> {result.column_span}x{result.row_span} "
            f"({rw}x{rh}px) at ({result.column},{result.row})"
        )


def probe_dismiss(qtbot) -> None:
    _section("§2 blank press vs library")
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a")
    harness.page.set_library_visible(True)
    QApplication.processEvents()
    blank = None
    for x in range(8, max(9, free.width() - 8), 24):
        for y in range(8, max(9, free.height() - 8), 24):
            pos = QPoint(x, y)
            if free._card_at(pos) is None:
                blank = pos
                break
        if blank is not None:
            break
    print(f"  free_grid size={free.width()}x{free.height()} blank={blank}")
    print(f"  library before={harness.page.is_library_visible()}")
    if blank is not None:
        child = free.childAt(blank) or free
        print(f"  hit chain: {_widget_chain(child)}")
        QTest.mouseClick(free, Qt.LeftButton, Qt.NoModifier, blank)
        QApplication.processEvents()
    print(f"  library after inner blank={harness.page.is_library_visible()}")
    harness.page.set_library_visible(True)
    QApplication.processEvents()
    host = harness.page.canvas_host()
    QTest.mouseClick(host, Qt.LeftButton, Qt.NoModifier, QPoint(4, 4))
    QApplication.processEvents()
    print(f"  library after host press={harness.page.is_library_visible()}")


def probe_fit_zoom(qtbot) -> None:
    _section("§3 zoom_fit geometry")
    harness = _Harness(qtbot)
    free, cards = _prepare_free_grid(harness, qtbot, "a", "b", "c", "d")
    size = free.unzoomed_size()
    content = getattr(free, "content_rect_1x", lambda: None)()
    fit = harness.page._content_fit_rect()
    print(f"  unzoomed_size={size.width()}x{size.height()}")
    print(f"  content_rect_1x={content}")
    print(f"  fit_rect={fit.x},{fit.y} {fit.width}x{fit.height}")
    harness.page.zoom_fit()
    QApplication.processEvents()
    origin = harness.page._fit_origin()
    print(f"  zoom_fit zoom={harness.page.board_zoom():.4f} origin={origin}")
    host = harness.page.canvas_host()
    xs, ys = [], []
    for card in cards:
        tl = card.mapTo(host, QPoint(0, 0))
        xs.extend((tl.x(), tl.x() + card.width()))
        ys.extend((tl.y(), tl.y() + card.height()))
    if xs:
        print(
            f"  cards_on_host=({min(xs)},{min(ys)}) "
            f"{max(xs) - min(xs)}x{max(ys) - min(ys)}"
        )


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    class _Bot:
        def addWidget(self, widget):
            return widget

        def wait(self, _ms):
            app.processEvents()

        def waitExposed(self, _widget):
            app.processEvents()

    qtbot = _Bot()
    probe_fit()
    probe_dismiss(qtbot)
    probe_fit_zoom(qtbot)


if __name__ == "__main__":
    main()
