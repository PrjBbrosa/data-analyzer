"""Regression: recoloring a curve must sync the LEFT channel-list swatch.

User bug (2026-07-09): in overlay mode, editing a curve's color via the
图表选项 dialog updated the on-canvas curve/axis but the little color dot
(swatch) in the left channel list stayed the OLD palette color. Root cause:
the recolor path (``ChartOptionsDialog._apply_appearance`` →
``sync_line_axis_color`` → ``canvas._sync_pg_channel_color``) only wrote the
canvas-internal ``channel_data`` + in-plot labels; it never wrote back to the
navigator's ``_colors`` — which is ALSO the color source-of-truth for time
replot and FFT/order analysis. So the swatch never changed AND a later replot
could snap the color back to the palette default.

Fix: the time canvas emits ``channel_color_changed(fid, display_name, color)``
from ``_sync_pg_channel_color``; the main window maps the display name back to
the raw ``(fid, ch)`` and calls ``navigator.set_channel_colors`` so the swatch,
time replot, and FFT all share one color truth.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key


def _make_file(stem: str, *, amp: float, idx: int) -> FileData:
    n = 1_500
    t = np.linspace(0.0, 1.0, n, dtype=np.float64)
    sig = amp * np.sin(2 * np.pi * 5 * t)
    df = pd.DataFrame({"time": t, "sig": sig})
    return FileData(f"{stem}.csv", df, ["time", "sig"], {"sig": "u"}, idx=idx)


def _row_for(fd: FileData, ch: str, fid: str, *, visible: bool):
    sig = fd.data[ch].to_numpy(copy=False).astype(float, copy=False)
    color = fd.get_color_palette()[0]
    return (
        fd.get_prefixed_channel(ch),
        visible,
        fd.time_array,
        sig,
        color,
        fd.channel_units.get(ch, ""),
        fid,
    )


def test_canvas_emits_channel_color_changed_on_recolor(qapp):
    """The real recolor entry point (``sync_line_axis_color``) makes the time
    canvas emit ``channel_color_changed`` carrying the ORIGINAL fid + display
    name + new color."""
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    fd = _make_file("motor", amp=1000.0, idx=0)
    display_name = fd.get_prefixed_channel("sig")
    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels([_row_for(fd, "sig", "fid-A", visible=True)], mode="overlay")
    QCoreApplication.processEvents()

    received: list[tuple] = []
    canvas.channel_color_changed.connect(lambda *a: received.append(a))

    ck = _view_state_channel_key("fid-A", display_name)
    handle, line = canvas._channel_lines.get(ck)

    new_color = "#123456"
    handle.sync_line_axis_color(line, new_color)  # the real dialog path
    QCoreApplication.processEvents()

    assert received, "recolor did not emit channel_color_changed"
    data_id, disp, color = received[-1]
    assert str(data_id) == "fid-A"
    assert disp == display_name
    assert color == new_color


def test_recolor_updates_navigator_swatch_and_color_source(qapp, loaded_csv, qtbot):
    """End-to-end: recolor on the live time canvas updates the navigator's
    per-channel color (which drives the swatch icon AND time/FFT replot)."""
    from mf4_analyzer.ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(loaded_csv)
    fid = next(iter(win.files))

    win.toolbar._set_mode("time")
    win.navigator.set_checked_channels([(fid, "speed")])
    win.plot_time()
    QCoreApplication.processEvents()

    fd = win.files[fid]
    display_name = fd.get_prefixed_channel("speed")
    ck = _view_state_channel_key(fid, display_name)
    handle, line = win.canvas_time._channel_lines.get(ck)

    new_color = "#123456"
    handle.sync_line_axis_color(line, new_color)
    QCoreApplication.processEvents()

    colors = win.navigator.get_channel_colors()
    assert colors.get((fid, "speed")) == new_color, (
        "navigator color (swatch + replot/FFT source) did not follow the recolor"
    )

    # 验真机渲染 (CLAUDE.md): the actual swatch PIXMAP must be repainted in the
    # new color, not just the backing dict. Read the rendered icon's center
    # pixel for the 'speed' leaf.
    from PyQt5.QtGui import QColor

    tree = win.navigator.channel_list.tree

    def _find_leaf(item):
        data = item.data(0, 0x0100)  # Qt.UserRole
        if data and data[0] == "channel" and data[2] == "speed":
            return item
        for i in range(item.childCount()):
            hit = _find_leaf(item.child(i))
            if hit is not None:
                return hit
        return None

    leaf = None
    for i in range(tree.topLevelItemCount()):
        leaf = _find_leaf(tree.topLevelItem(i))
        if leaf is not None:
            break
    assert leaf is not None, "could not locate the 'speed' channel leaf"

    icon = leaf.icon(0)
    assert not icon.isNull(), "channel leaf has no swatch icon"
    img = icon.pixmap(22, 22).toImage()
    center = QColor(img.pixel(img.width() // 2, img.height() // 2))
    assert center.name() == new_color, (
        f"rendered swatch pixel is {center.name()!r}, expected {new_color!r}"
    )
