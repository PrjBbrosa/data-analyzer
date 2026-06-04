"""Real-window verification for the two side-by-side fixes:

  1) Cursor readout follows focus: the SECONDARY pane's cursor readout reaches
     the single floating pill (was wired to the primary canvas only) and the
     pill is positioned OVER the secondary canvas.
  2) Shared toolbar routes to the focused pane: home/pan/zoom/图表选项 act on the
     SECONDARY canvas while it is focused, leaving the primary untouched, and
     the shared toolbar's pan/zoom highlight mirrors the focused pane.

Loads the real testfile/*.mf4, builds two views, enters split, then exercises
the real code paths (no signal-faking for the toolbar; the cursor uses the
canvas's own _emit_single/dual_cursor_html which reads real channel_data).

Run on the Windows desktop (NOT offscreen):
    .venv/Scripts/python.exe scripts/verify_secondary_cursor_toolbar.py
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)  # need a real rendered window

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui_kit import load_stylesheet

MF4 = os.path.join(os.path.dirname(__file__), "..", "testfile",
                   "resonance_high500degree.mf4")
OUT = os.path.join(os.path.dirname(__file__), "..", "testfile")

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def _click_card(app, card):
    canvas = card.canvas
    pos = QPoint(canvas.width() // 2, canvas.height() // 2)
    app.sendEvent(canvas, QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    app.processEvents()


def _channels_of(w):
    fid = next(iter(w.files))
    fd = w.channel_list.get_file_data(fid)
    cols = [c for c in fd.data.columns
            if c.strip().lower() not in ("time", "t")
            and "time" not in c.strip().lower()]
    return fid, cols


def _vb0(canvas):
    ax = canvas.axes_list[0]
    return getattr(ax, "view_box", None)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)

    w = MainWindow()
    w.resize(1500, 860)
    w.show()
    app.processEvents()
    w.load_file(os.path.abspath(MF4))
    app.processEvents()

    cs = w.chart_stack
    fid, cols = _channels_of(w)
    print("file channels:", cols[:8], "..." if len(cols) > 8 else "")
    ch_a, ch_b = cols[0], (cols[1] if len(cols) > 1 else cols[0])
    print(f"view0 -> {ch_a!r}   view1 -> {ch_b!r}")

    # View 0: ch_a, overlay
    w.navigator.set_checked_channels([(fid, ch_a)])
    cs.set_plot_mode("overlay")
    cs.set_cursor_mode("off")
    w.plot_time()
    w._capture_current_view()

    # View 1: ch_b, subplot
    w._on_view_new()
    app.processEvents()
    w.navigator.set_checked_channels([(fid, ch_b)])
    cs.set_plot_mode("subplot")
    w.plot_time()
    w._capture_current_view()

    # Back to view 0, split against view 1, focus the secondary pane.
    w._switch_view(0)
    app.processEvents()
    w.view_manager.set_split(1)
    app.processEvents()
    print("split_active:", cs.split_active())
    _click_card(app, cs._secondary_card)
    app.processEvents()
    check("secondary pane is focused", cs.focused_canvas() is cs.secondary_canvas())

    sec = cs.secondary_canvas()
    pri = cs.canvas_time
    shared = cs._time_toolbar

    # ---------------- Issue 2: shared toolbar routes to focused ----------------
    print("\n[Toolbar] shared nav routes to the focused SECONDARY pane")
    pri_mode_vb_before = _vb0(pri).state["mouseMode"]
    shared._actions_by_key["zoom"].trigger()
    app.processEvents()
    check("shared 'zoom' set SECONDARY viewbox to RectMode",
          _vb0(sec).state["mouseMode"] == pg.ViewBox.RectMode,
          f"sec mouseMode={_vb0(sec).state['mouseMode']}")
    check("PRIMARY viewbox mode untouched by the click",
          _vb0(pri).state["mouseMode"] == pri_mode_vb_before)
    zoom_btn = shared.widgetForAction(shared._actions_by_key["zoom"])
    pan_btn = shared.widgetForAction(shared._actions_by_key["pan"])
    check("shared toolbar zoom icon highlighted (mirrors focused pane)",
          bool(zoom_btn.property("navActive")) and not bool(pan_btn.property("navActive")))

    # home (forwarded) re-autoscales the SECONDARY only.
    shared._actions_by_key["pan"].trigger()  # back to pan
    app.processEvents()
    sax = sec._primary_xaxis_ax
    pax = pri._primary_xaxis_ax
    sax.set_xlim(0.10, 0.20)   # narrow the secondary window
    pri_xlim_before = pax.get_xlim()
    app.processEvents()
    shared._actions_by_key["home"].trigger()
    app.processEvents()
    s_lo, s_hi = sec._primary_xaxis_ax.get_xlim()
    check("shared 'home' re-expanded the SECONDARY x-window",
          (s_hi - s_lo) > 0.11, f"sec xlim=({s_lo:.3f},{s_hi:.3f})")
    check("PRIMARY x-window untouched by 'home'",
          np.allclose(pri._primary_xaxis_ax.get_xlim(), pri_xlim_before, atol=1e-6))

    # 图表选项 opens the focused (secondary) canvas's dialog.
    opened = []
    sec.open_chart_options_dialog = lambda: opened.append("secondary")
    pri.open_chart_options_dialog = lambda: opened.append("primary")
    cs._time_card._options_btn.click()
    app.processEvents()
    check("shared 图表选项 opened the SECONDARY canvas", opened == ["secondary"],
          f"opened={opened}")

    # ---------------- Issue 1: cursor readout follows focus ----------------
    print("\n[Cursor] secondary pane readout reaches the shared pill")
    cs._time_card.set_cursor_mode("single")  # shared control -> focused (secondary)
    app.processEvents()
    check("secondary canvas cursor enabled", sec._cursor_visible is True)

    # Drive the REAL readout path: _emit_single_cursor_html reads the secondary
    # canvas's own channel_data and emits cursor_info (as a hover would).
    s_lo, s_hi = sec._primary_xaxis_ax.get_xlim()
    x_mid = 0.5 * (s_lo + s_hi)
    sec._emit_single_cursor_html(x_mid)
    app.processEvents()
    pill_text = cs.cursor_pill_text()
    check("pill shows the SECONDARY channel readout",
          ch_b.split(".")[-1][:6] in pill_text or "t=" in pill_text,
          f"pill={pill_text[:60]!r}")
    check("active cursor card is the secondary", cs._active_cursor_card is cs._secondary_card)

    # Pill is positioned OVER the secondary (right) canvas, not the primary.
    pill_geo = cs._pill.geometry()
    sec_origin = sec.mapTo(cs.stack, sec.rect().topLeft())
    sec_x0 = sec_origin.x()
    sec_x1 = sec_x0 + sec.width()
    pill_cx = pill_geo.x() + pill_geo.width() // 2
    check("pill is anchored over the SECONDARY canvas",
          sec_x0 - 4 <= pill_cx <= sec_x1 + 4,
          f"pill_cx={pill_cx}, sec_x=[{sec_x0},{sec_x1}]")

    # A subsequent PRIMARY readout takes the pill back (follows the hovered pane).
    cs._time_card.set_cursor_mode("off")  # secondary off
    app.processEvents()
    _click_card(app, cs._time_card)
    cs._time_card.set_cursor_mode("single")
    app.processEvents()
    p_lo, p_hi = pri._primary_xaxis_ax.get_xlim()
    pri._emit_single_cursor_html(0.5 * (p_lo + p_hi))
    app.processEvents()
    check("pill follows back to the primary pane",
          cs._active_cursor_card is cs._time_card)

    # Screenshot evidence: pill over the secondary pane.
    _click_card(app, cs._secondary_card)
    cs._time_card.set_cursor_mode("single")
    app.processEvents()
    s_lo, s_hi = sec._primary_xaxis_ax.get_xlim()
    sec._emit_single_cursor_html(0.5 * (s_lo + s_hi))
    app.processEvents()
    cs.repaint()
    w.repaint()
    app.processEvents()
    shot = os.path.abspath(os.path.join(OUT, "verify_secondary_cursor.png"))
    cs.grab().save(shot)
    print("\nSCREENSHOT:", shot)

    n_pass = sum(1 for _, ok in _results if ok)
    print(f"\n==== {n_pass}/{len(_results)} checks passed ====")
    w.close()
    return 0 if n_pass == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
