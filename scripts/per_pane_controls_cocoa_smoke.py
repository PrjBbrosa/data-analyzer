"""Real-window (cocoa) smoke for P2 Task 9 1a+1b+2.

Loads a CSV, builds two views (speed / torque), enters side-by-side split,
then:

  1) samples the focused card's real 3px top accent strip BEFORE and AFTER
     clicking the secondary card to prove the visible cue moves between panes;
  2) drives the visible shared cursor / plot-mode controls while the secondary
     is focused and checks the production routing contract: cursor state
     applies to both visible panes, while a plot-mode change re-lays out only
     the focused secondary pane.

Run on macOS desktop (NOT offscreen):
    .venv/bin/python scripts/per_pane_controls_cocoa_smoke.py
"""
import os
import sys
import tempfile

# Must NOT be offscreen — we want the real rendered focus marker.
os.environ.pop("QT_QPA_PLATFORM", None)

import numpy as np
import pandas as pd
from PyQt5.QtCore import QEvent, QEventLoop, QPoint, QTimer, Qt
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
    _pump(app)


def _pump(_app, milliseconds=20):
    """Run a bounded native Cocoa turn instead of an unbounded processEvents.

    The smoke drives a real foreground application without calling its normal
    ``app.exec_()``. On Cocoa, a bare ``processEvents()`` can enter the native
    run loop until another user event arrives after a cursor-mode transition.
    A single-shot nested turn services paint and queued signals but guarantees
    this release probe returns to the shell.
    """
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec_()


def _close_window(app, window):
    """Dispose the top-level widget while a live Cocoa turn still exists.

    This harness deliberately runs without ``app.exec_()``.  Letting its
    Python wrappers reach interpreter finalization while their QObject tree is
    still pending deletion can make SIP's atexit cleanup dereference already
    reclaimed Cocoa state.  This is test-harness teardown, not a product
    shortcut: it mirrors Qt's normal deferred-delete delivery before the
    process returns to Python.
    """
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    _pump(app)


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
    _pump(QApplication.instance())
    _pump(QApplication.instance())
    img = cs.grab().toImage()
    img.save(path)
    return img, path


def _focus_marker_sample(img, card, stack):
    """Sample the center pixel of a visible card's real focus marker.

    Focus is intentionally an overlay strip, not a QSS border: the full-bleed
    pyqtgraph canvas paints over a card border. Sampling the marker's own
    center avoids confusing an ordinary chart line or rounded corner with the
    focus cue. ``None`` means the marker is correctly hidden.
    """
    bar = card._focus_bar
    if bar.isHidden():
        return None
    dpr = img.devicePixelRatio() or 1.0
    top_left = bar.mapTo(stack, bar.rect().topLeft())
    x = int((top_left.x() + bar.width() // 2) * dpr)
    y = int((top_left.y() + bar.height() // 2) * dpr)
    if not (0 <= x < img.width() and 0 <= y < img.height()):
        raise AssertionError(f"focus marker pixel out of image bounds: {(x, y)}")
    color = img.pixelColor(x, y)
    return color.red(), color.green(), color.blue()


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)
    csv = _make_csv()

    w = MainWindow()
    w.resize(1400, 820)
    w.show()
    _pump(app)
    w.load_file(csv)
    _pump(app)
    fid = next(iter(w.files))

    cs = w.chart_stack

    # View 0: speed, overlay, cursor single
    _set_checked(w, "speed")
    cs.set_plot_mode("overlay")
    cs.set_cursor_mode("single")
    w.plot_time()
    w._capture_current_view()

    # View 1: torque, subplot, cursor off
    w._on_view_new()
    _pump(app)
    # A new View deliberately starts with an empty file scope. Attach the
    # source before selecting torque so this foreground probe exercises a real
    # second canvas rather than accepting an empty comparison pane.
    w._attach_files_to_focused_view([fid])
    _set_checked(w, "torque")
    cs.set_plot_mode("subplot")
    cs.set_cursor_mode("off")
    w.plot_time()
    w._capture_current_view()

    # Back to view 0, split against view 1.
    w._switch_view(0)
    _pump(app)
    w.view_manager.set_split(1)
    _pump(app)

    print("split_active:", cs.split_active())

    # ---- highlight verification (BEFORE click: primary focused) ----
    img, _ = _grab_stack(
        w, os.path.join(tempfile.gettempdir(), "per_pane_primary.png")
    )
    p_rgb = _focus_marker_sample(img, cs._time_card, cs)
    s_rgb = _focus_marker_sample(img, cs._secondary_card, cs)
    _require(p_rgb is not None and s_rgb is None,
             f"initial focus marker state was primary={p_rgb}, secondary={s_rgb}")
    print("BEFORE click  primary marker:", p_rgb,
          "| secondary marker hidden:", s_rgb is None)

    # ---- click secondary: focus + controls move ----
    _click_card(app, cs._secondary_card)
    after_path = os.path.join(tempfile.gettempdir(), "per_pane_secondary.png")
    img2, _ = _grab_stack(w, after_path)
    p_rgb2 = _focus_marker_sample(img2, cs._time_card, cs)
    s_rgb2 = _focus_marker_sample(img2, cs._secondary_card, cs)
    _require(p_rgb2 is None and s_rgb2 is not None,
             f"secondary focus marker did not move: primary={p_rgb2}, secondary={s_rgb2}")
    print("AFTER click   primary marker hidden:", p_rgb2 is None,
          "| secondary marker:", s_rgb2)

    # ---- visible shared cursor routing: both split panes update ----
    prim_cursor_before = (cs.canvas_time._cursor.visible, cs.canvas_time._cursor.dual)
    cs._time_card.set_cursor_mode("dual")
    _pump(app)
    secondary_cursor = (
        cs.secondary_canvas()._cursor.visible,
        cs.secondary_canvas()._cursor.dual,
    )
    primary_cursor = (cs.canvas_time._cursor.visible, cs.canvas_time._cursor.dual)
    _require(secondary_cursor == (True, True) and primary_cursor == (True, True),
             "shared dual-cursor control did not update both split panes")
    print("after focused-secondary 双游标 -> primary/secondary:",
          primary_cursor, secondary_cursor, "| primary before:", prim_cursor_before)

    # ---- per-pane plot-mode routing: flip secondary subplot->overlay ----
    _set_checked(w, "speed", "torque")
    w._ch_changed()
    _pump(app)
    prim_overlay_before = cs.canvas_time._overlay_mode
    print("before focused-secondary 叠加 -> shared/secondary modes:",
          cs._time_card.plot_mode(), cs._secondary_card.plot_mode(),
          "| canvas modes:", prim_overlay_before,
          cs.secondary_canvas()._overlay_mode)
    cs._time_card.set_plot_mode("overlay")
    _pump(app)
    secondary_overlay = cs.secondary_canvas()._overlay_mode
    primary_overlay_unchanged = cs.canvas_time._overlay_mode == prim_overlay_before
    _require(secondary_overlay and primary_overlay_unchanged,
             "focused-secondary overlay routing failed: "
             f"shared={cs._time_card.plot_mode()}, "
             f"secondary={cs._secondary_card.plot_mode()}, "
             f"primary_canvas={cs.canvas_time._overlay_mode}, "
             f"secondary_canvas={secondary_overlay}")
    print("after secondary 叠加 -> secondary overlay_mode:",
          secondary_overlay, "| primary overlay unchanged:", primary_overlay_unchanged)

    # ---- click back to primary: highlight returns ----
    _click_card(app, cs._time_card)
    back_path = os.path.join(tempfile.gettempdir(), "per_pane_back_to_primary.png")
    img3, _ = _grab_stack(w, back_path)
    p_rgb3 = _focus_marker_sample(img3, cs._time_card, cs)
    s_rgb3 = _focus_marker_sample(img3, cs._secondary_card, cs)
    _require(p_rgb3 is not None and s_rgb3 is None,
             f"focus marker did not return to primary: primary={p_rgb3}, secondary={s_rgb3}")
    print("BACK click    primary marker:", p_rgb3,
          "| secondary marker hidden:", s_rgb3 is None)

    print("SCREENSHOTS:")
    for p in (
        os.path.join(tempfile.gettempdir(), "per_pane_primary.png"),
        after_path,
        back_path,
    ):
        print(" ", p)
    _close_window(app, w)


if __name__ == "__main__":
    main()
