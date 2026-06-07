"""Real-window (cocoa) smoke for P2 Task 9 1a+1b+2.

Loads a CSV, builds two views (speed / torque), enters side-by-side split,
then:

  1) samples the focus-highlight pixels just inside each card edge (3px blue
     frame + light-blue tint) BEFORE and AFTER clicking the secondary card to
     prove the bolder accent paints and moves between panes;
  2) drives the cursor / plot-mode controls while the secondary is focused and
     prints the resulting canvas state to prove the per-pane routing lands on
     the SECONDARY canvas and leaves the primary untouched.

Run on macOS desktop (NOT offscreen):
    .venv/bin/python scripts/per_pane_controls_cocoa_smoke.py
"""
import os
import sys
import tempfile

# Must NOT be offscreen — we want a real rendered border + tint.
os.environ.pop("QT_QPA_PLATFORM", None)

import numpy as np
import pandas as pd
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui_kit import load_stylesheet


def _make_csv():
    t = np.linspace(0, 1.0, 1000)
    df = pd.DataFrame({
        "time": t,
        "speed": 1000 * np.sin(2 * np.pi * 5 * t),
        "torque": 50 + 5 * np.cos(2 * np.pi * 3 * t),
    })
    p = os.path.join(tempfile.gettempdir(), "per_pane_smoke.csv")
    df.to_csv(p, index=False)
    return p


def _set_checked(w, *channels):
    fid = next(iter(w.files))
    w.navigator.set_checked_channels([(fid, ch) for ch in channels])


def _click_card(app, card):
    canvas = card.canvas
    pos = QPoint(canvas.width() // 2, canvas.height() // 2)
    press = QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    app.sendEvent(canvas, press)
    app.processEvents()


def _grab_stack(w, path):
    """Grab the WHOLE chart stack (the composite the user sees) after forcing
    a full re-polish + repaint so the dynamic [focused] QSS rule is current."""
    cs = w.chart_stack
    for card in (cs._time_card, cs._secondary_card):
        if card is None:
            continue
        card.style().unpolish(card)
        card.style().polish(card)
        card.update()
    cs.repaint()
    w.repaint()
    QApplication.processEvents()
    QApplication.processEvents()
    img = cs.grab().toImage()
    img.save(path)
    return img, path


def _edge_sample_in(img, card, stack):
    """Sample the focus frame/tint just inside the card's LEFT edge, scanning a
    SMALL inset block near the toolbar row (NOT the plot interior) so a blue
    channel LINE at vertical-center can't be mistaken for the focus accent.

    Returns the most blue-ish (r,g,b) found. HiDPI 2x + 12px rounded corners =>
    start a few logical px inside the extreme edge; scan a short vertical band
    that overlaps the 3px frame + tint padding ring.

    NOTE: the SAVED PNGs are the authoritative visual evidence (the harness
    reads them); this sampler is a quick numeric cross-check only."""
    dpr = img.devicePixelRatio() or 1.0
    tl = card.mapTo(stack, card.rect().topLeft())
    best = (255, 255, 255)
    best_blueness = -1
    # Scan a band ~6..40 logical px down (frame top edge + tint ring) and
    # ~3..14 logical px in from the left (frame left edge + tint ring).
    for ly in range(6, 40, 2):
        for lx in range(3, 14):
            x = int((tl.x() + lx) * dpr)
            y = int((tl.y() + ly) * dpr)
            if x >= img.width() or y >= img.height():
                continue
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            blueness = b - max(r, g)
            if blueness > best_blueness:
                best_blueness = blueness
                best = (r, g, b)
    return best, best_blueness


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)
    csv = _make_csv()

    w = MainWindow()
    w.resize(1400, 820)
    w.show()
    app.processEvents()
    w.load_file(csv)
    app.processEvents()

    cs = w.chart_stack

    # View 0: speed, overlay, cursor single
    _set_checked(w, "speed")
    cs.set_plot_mode("overlay")
    cs.set_cursor_mode("single")
    w.plot_time()
    w._capture_current_view()

    # View 1: torque, subplot, cursor off
    w._on_view_new()
    app.processEvents()
    _set_checked(w, "torque")
    cs.set_plot_mode("subplot")
    cs.set_cursor_mode("off")
    w.plot_time()
    w._capture_current_view()

    # Back to view 0, split against view 1.
    w._switch_view(0)
    app.processEvents()
    w.view_manager.set_split(1)
    app.processEvents()

    print("split_active:", cs.split_active())

    # ---- highlight verification (BEFORE click: primary focused) ----
    img, _ = _grab_stack(
        w, os.path.join(tempfile.gettempdir(), "per_pane_primary.png")
    )
    p_rgb, p_blue = _edge_sample_in(img, cs._time_card, cs)
    s_rgb, s_blue = _edge_sample_in(img, cs._secondary_card, cs)
    print("BEFORE click  primary edge:", p_rgb, "blueness", p_blue,
          "| secondary edge:", s_rgb, "blueness", s_blue)

    # ---- click secondary: focus + controls move ----
    _click_card(app, cs._secondary_card)
    after_path = os.path.join(tempfile.gettempdir(), "per_pane_secondary.png")
    img2, _ = _grab_stack(w, after_path)
    p_rgb2, p_blue2 = _edge_sample_in(img2, cs._time_card, cs)
    s_rgb2, s_blue2 = _edge_sample_in(img2, cs._secondary_card, cs)
    print("AFTER click   primary edge:", p_rgb2, "blueness", p_blue2,
          "| secondary edge:", s_rgb2, "blueness", s_blue2)
    print("secondary controls enabled:",
          cs._secondary_card.btn_subplot.isEnabled(),
          "| primary controls enabled:",
          cs._time_card.btn_subplot.isEnabled())

    # ---- per-pane cursor routing: drive secondary card cursor -> secondary canvas ----
    prim_cursor_before = (cs.canvas_time._cursor_visible, cs.canvas_time._dual)
    cs._secondary_card.set_cursor_mode("dual")
    app.processEvents()
    print("after secondary 双游标 -> secondary cursor_visible/dual:",
          cs.secondary_canvas()._cursor_visible, cs.secondary_canvas()._dual,
          "| primary unchanged:",
          (cs.canvas_time._cursor_visible, cs.canvas_time._dual) == prim_cursor_before)

    # ---- per-pane plot-mode routing: flip secondary subplot->overlay ----
    _set_checked(w, "speed", "torque")
    w._ch_changed()
    app.processEvents()
    prim_overlay_before = cs.canvas_time._overlay_mode
    cs._secondary_card.set_plot_mode("overlay")
    app.processEvents()
    print("after secondary 叠加 -> secondary overlay_mode:",
          cs.secondary_canvas()._overlay_mode,
          "| primary overlay unchanged:",
          cs.canvas_time._overlay_mode == prim_overlay_before)

    # ---- click back to primary: highlight returns ----
    _click_card(app, cs._time_card)
    back_path = os.path.join(tempfile.gettempdir(), "per_pane_back_to_primary.png")
    img3, _ = _grab_stack(w, back_path)
    p_rgb3, p_blue3 = _edge_sample_in(img3, cs._time_card, cs)
    s_rgb3, s_blue3 = _edge_sample_in(img3, cs._secondary_card, cs)
    print("BACK click    primary edge:", p_rgb3, "blueness", p_blue3,
          "| secondary edge:", s_rgb3, "blueness", s_blue3)

    print("SCREENSHOTS:")
    for p in (
        os.path.join(tempfile.gettempdir(), "per_pane_primary.png"),
        after_path,
        back_path,
    ):
        print(" ", p)
    w.close()


if __name__ == "__main__":
    main()
