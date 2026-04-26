"""Geometry-clipping tests for ``RebuildTimePopover.show_at``.

The popover used to call ``self.move(anchor.mapToGlobal(...))`` without any
screen-edge clipping, so when the anchor sat near the right/bottom edge of
the screen (FFT vs Time inspector lives in the right pane), the popover
would render partially or fully off the visible display. The fix clips the
target rect inside ``QScreen.availableGeometry`` and flips the popover
above the anchor when below would overflow. These tests run under
``QT_QPA_PLATFORM=offscreen``; per
``docs/lessons-learned/pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md``
the offscreen platform exposes valid screen geometry, so geometry assertions
are reliable in headless CI.
"""
from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QMainWindow, QPushButton

from mf4_analyzer.ui.drawers.rebuild_time_popover import (
    GAP,
    MARGIN,
    RebuildTimePopover,
)


def _avail():
    return QGuiApplication.primaryScreen().availableGeometry()


def _build_window_with_anchor(qtbot, anchor_offset_in_window):
    """Place a QMainWindow flush with the right/bottom edge of the screen
    and put a QPushButton inside at the given offset."""
    avail = _avail()
    win = QMainWindow()
    win.resize(300, 200)
    # Anchor near right edge of the screen — same shape as the FFT vs Time
    # inspector "重建时间轴" button.
    win.move(
        avail.right() - win.width() + 1,
        avail.bottom() - win.height() + 1,
    )
    btn = QPushButton("rebuild", win)
    btn.resize(80, 24)
    btn.move(*anchor_offset_in_window)
    win.setCentralWidget(QPushButton("filler"))
    btn.setParent(win)
    btn.show()
    win.show()
    qtbot.addWidget(win)
    qtbot.waitExposed(win)
    qtbot.waitExposed(btn)
    return win, btn


def test_popover_clamped_inside_right_edge(qapp, qtbot):
    """Anchor at the right edge: popover must NOT extend past availableGeometry.right()."""
    avail = _avail()
    # Put the anchor button against the inner right edge of the window so
    # its bottomLeft is < MARGIN from the screen's right edge.
    win, btn = _build_window_with_anchor(qtbot, (220, 10))
    pop = RebuildTimePopover(parent=win, target_filename="x.mf4", current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show_at(btn)
    qtbot.waitExposed(pop)

    fg = pop.frameGeometry()
    assert fg.right() <= avail.right() - MARGIN + 1, (
        f"popover right={fg.right()} must stay inside avail.right()={avail.right()} - MARGIN"
    )
    assert fg.left() >= avail.left() + MARGIN - 1, (
        f"popover left={fg.left()} must stay inside avail.left()={avail.left()} + MARGIN"
    )


def test_popover_clamped_inside_bottom_edge_flips_above(qapp, qtbot):
    """Anchor at the bottom edge: popover should flip above the anchor."""
    avail = _avail()
    # Anchor very near the bottom of the window, which itself is near the
    # bottom of the screen. Below-anchor placement would overflow.
    win, btn = _build_window_with_anchor(qtbot, (10, 170))
    pop = RebuildTimePopover(parent=win, target_filename="x.mf4", current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show_at(btn)
    qtbot.waitExposed(pop)

    fg = pop.frameGeometry()
    anchor_top_global_y = btn.mapToGlobal(btn.rect().topLeft()).y()

    assert fg.bottom() <= avail.bottom() - MARGIN + 1, (
        f"popover bottom={fg.bottom()} must stay inside avail.bottom()={avail.bottom()} - MARGIN"
    )
    assert fg.top() >= avail.top() + MARGIN - 1, (
        f"popover top={fg.top()} must stay inside avail.top()={avail.top()} + MARGIN"
    )
    # If the popover fits above the anchor, it should have flipped to sit
    # above (top edge no greater than anchor top - GAP).
    if pop.height() + GAP <= anchor_top_global_y - (avail.top() + MARGIN):
        assert fg.top() <= anchor_top_global_y - GAP + 1, (
            "popover should flip above the anchor when below would overflow"
        )


def test_popover_clamped_inside_corner(qapp, qtbot):
    """Anchor at the bottom-right corner: popover must stay fully on-screen."""
    avail = _avail()
    win, btn = _build_window_with_anchor(qtbot, (220, 170))
    pop = RebuildTimePopover(parent=win, target_filename="x.mf4", current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show_at(btn)
    qtbot.waitExposed(pop)

    fg = pop.frameGeometry()
    # Allow a 1px slack for frame-vs-geometry rounding under offscreen.
    assert fg.right() <= avail.right() - MARGIN + 1
    assert fg.left() >= avail.left() + MARGIN - 1
    assert fg.bottom() <= avail.bottom() - MARGIN + 1
    assert fg.top() >= avail.top() + MARGIN - 1


def test_popover_uses_anchor_bottom_when_room_available(qapp, qtbot):
    """Sanity: when there is room, popover should still be just below the anchor.

    Backwards-compat with ``test_rebuild_time_popover_anchors_below_widget``
    in ``test_drawers.py`` — the geometry-clipping logic must be a no-op
    when the natural anchor.bottomLeft position fits on screen.
    """
    avail = _avail()
    # Place the anchor near the top-left of the screen with plenty of room.
    win = QMainWindow()
    win.resize(200, 150)
    win.move(avail.left() + 50, avail.top() + 50)
    btn = QPushButton("rebuild", win)
    btn.resize(80, 24)
    btn.move(20, 20)
    btn.show()
    win.show()
    qtbot.addWidget(win)
    qtbot.waitExposed(win)
    qtbot.waitExposed(btn)

    pop = RebuildTimePopover(parent=win, target_filename="x.mf4", current_fs=1000.0)
    qtbot.addWidget(pop)
    pop.show_at(btn)
    qtbot.waitExposed(pop)

    expected = btn.mapToGlobal(btn.rect().bottomLeft())
    actual = pop.pos()
    assert abs(actual.x() - expected.x()) <= 2
    assert abs(actual.y() - expected.y()) <= 2
