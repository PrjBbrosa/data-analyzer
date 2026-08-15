"""Real-machine (Cocoa) render acceptance for the View-switch re-entrancy fix.

Offscreen cannot be a visual acceptance (CLAUDE.md Gotchas), so this drives a
REAL window, performs the reported gesture, grabs the canvas, and measures ink.

Two sides, both automated, same process, same data:

  guard-off : `_restore_view_xlim` reverted to the historical verbatim restore
              (what shipped) -> reproduces "图没了"
  guard-on  : the shipped fix

Each side prints visible-point counts, the ink ratio of the grabbed pixmap and
its md5, and writes a PNG.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window._view_mixin import ViewMixin

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
OUT.mkdir(parents=True, exist_ok=True)


def _csv(path, *, duration, points, columns):
    t = np.linspace(0.0, float(duration), points)
    frame = {"time": t}
    frame.update({name: fn(t) for name, fn in columns.items()})
    pd.DataFrame(frame).to_csv(path, index=False)
    return str(path)


# --- the three shipped-bug behaviours, restored verbatim for the A side ----
def _verbatim_restore(self, canvas, xlim):
    """Pre-fix: restore whatever was saved, fits the data or not."""
    if xlim is not None:
        canvas.restore_visible_xlim(xlim)


def _no_gate(self):
    """Pre-fix: no gate at all -> no scope, no switch deferral, no busy flag."""
    return None


def _unguarded_capture(self):
    """Pre-fix `_capture_focused_view`: captures whatever is on screen."""
    if self.chart_stack.current_mode() != 'time':
        return
    idx = self._focused_view_idx
    if idx is None or not (0 <= idx < len(self.view_manager.views)):
        return
    canvas = self._canvas_for_view_index(idx) or self.canvas_time
    state = self.view_manager.get(idx)
    self._view_bridge.capture_controls_into(state, self, canvas)
    self._view_bridge.capture_canvas_ranges_into(state, canvas)


def _ink_ratio_and_hash(pixmap):
    image = pixmap.toImage().convertToFormat(4)  # QImage.Format_RGB32
    width, height = image.width(), image.height()
    ptr = image.bits()
    ptr.setsize(image.sizeInBytes())
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(height, image.bytesPerLine() // 4, 4)
    arr = arr[:, :width, :3]
    # Chart face is near-white; count anything meaningfully darker as ink, and
    # ignore the axis frame/gridlines by requiring saturation OR real darkness.
    darkness = 255 - arr.min(axis=2)
    saturation = arr.max(axis=2).astype(np.int16) - arr.min(axis=2).astype(np.int16)
    ink = (darkness > 60) & (saturation > 25)      # coloured curve pixels only
    return float(ink.mean()), hashlib.md5(arr.tobytes()).hexdigest()[:12]


def run_side(app, label, *, guarded):
    if guarded:
        ViewMixin._restore_view_xlim = _SHIPPED["restore"]
        ViewMixin._time_render_gate = _SHIPPED["gate"]
        ViewMixin._capture_focused_view = _SHIPPED["capture"]
    else:
        ViewMixin._restore_view_xlim = _verbatim_restore
        ViewMixin._time_render_gate = _no_gate
        ViewMixin._capture_focused_view = _unguarded_capture

    tmp = Path(os.environ.get("TMPDIR", "/tmp"))
    long_csv = _csv(tmp / "probe_long.csv", duration=260.0, points=26000,
                    columns={"steer_torque": lambda t: np.sin(t)})
    short_csv = _csv(tmp / "probe_short.csv", duration=49.5, points=99000,
                     columns={"L": lambda t: 0.4 * np.sin(50 * t),
                              "R": lambda t: 0.4 * np.cos(50 * t)})

    win = MainWindow()
    win.resize(1500, 860)
    win.show()
    app.processEvents()
    win.load_file(long_csv)
    win.load_file(short_csv)
    app.processEvents()
    long_fid, short_fid = list(win.files)

    # View 1: the long recording, zoomed to 118.41-125.03 s (the screenshot).
    win.navigator.set_checked_channels([(long_fid, "steer_torque")])
    app.processEvents()
    win.plot_time()
    app.processEvents()
    win.canvas_time.restore_visible_xlim((118.41, 125.032))
    app.processEvents()
    win._capture_focused_view()

    # View 2: the 49.5 s wideband file (L/R), full range.
    win._on_view_new()
    app.processEvents()
    win._attach_files_to_focused_view([short_fid])
    app.processEvents()
    win.navigator.set_checked_channels([(short_fid, "L"), (short_fid, "R")])
    app.processEvents()
    win.plot_time()
    app.processEvents()
    win._capture_focused_view()

    # View 3: back on the long recording.
    win._on_view_new()
    app.processEvents()
    win._attach_files_to_focused_view([long_fid])
    app.processEvents()
    win.navigator.set_checked_channels([(long_fid, "steer_torque")])
    app.processEvents()
    win.plot_time()
    app.processEvents()
    win._capture_focused_view()

    win._switch_view(0)
    app.processEvents()

    # The reported gesture: 切来切去 — clicks landing while a render is running.
    QTimer.singleShot(0, lambda: win._switch_view(2))
    QTimer.singleShot(0, lambda: win._switch_view(1))
    win._switch_view(1)
    for _ in range(6):
        app.processEvents()

    canvas = win.canvas_time
    points = []
    for _ck, name, (_h, line) in canvas._channel_lines.composite_items():
        pdi = getattr(line, "plot_data_item", None)
        if pdi is None or not pdi.isVisible():
            continue
        x, _y = pdi.getData()
        points.append((str(name).split("] ")[-1], 0 if x is None else len(x)))
    pixmap = canvas.grab_pixmap(scale=1.0)
    ratio, digest = _ink_ratio_and_hash(pixmap)
    png = OUT / f"{label}.png"
    pixmap.save(str(png))

    states = [
        (f"View{i + 1}", sorted(ch for _f, ch in st.checked),
         None if st.xlim is None else tuple(round(v, 2) for v in st.xlim))
        for i, st in enumerate(win.view_manager.views)
    ]
    for row in states:
        print(f"    {label} state {row}")
    print(
        f"[{label}] active=View{win.view_manager.active + 1} "
        f"xlim={tuple(round(v, 3) for v in canvas.get_visible_xlim())} "
        f"visible={sorted(points)} ink={ratio:.4%} md5={digest} -> {png.name}"
    )
    win.close()
    app.processEvents()
    return ratio, points


_SHIPPED = {
    "restore": ViewMixin._restore_view_xlim,
    "gate": ViewMixin._time_render_gate,
    "capture": ViewMixin._capture_focused_view,
}

if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    off_ratio, off_points = run_side(app, "guard-off-shipped-bug", guarded=False)
    on_ratio, on_points = run_side(app, "guard-on-fixed", guarded=True)
    print()
    print(f"guard-off ink {off_ratio:.4%} | guard-on ink {on_ratio:.4%}")
    blank_before = all(n < 2 for _n, n in off_points) if off_points else True
    drawn_after = bool(on_points) and all(n >= 2 for _n, n in on_points)
    print(f"blank before fix: {blank_before} | curves after fix: {drawn_after}")
    sys.exit(0 if (blank_before and drawn_after and on_ratio > off_ratio) else 1)
