"""Preview the channel-list color dot at several sizes in the REAL widget.

Builds an actual MultiFileChannelWidget with a few coloured channels, renders it
on the live Retina display at candidate swatch sizes, grabs the native pixels
and stacks them side by side so the dot-vs-text proportion can be judged.

Run on macOS desktop (NOT offscreen):
    PYTHONPATH=. .venv/bin/python scripts/channel_dot_size_preview.py
"""
import os
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)

from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

import mf4_analyzer.ui.widgets.channel_tree as channel_tree_mod
from mf4_analyzer.ui.widgets import MultiFileChannelWidget
from mf4_analyzer.ui_kit import load_stylesheet

PALETTE = ["#2d7ff9", "#10b981", "#ef4444", "#f97316",
           "#06b6d4", "#8b5cf6", "#e11d48"]


class _FakeFile:
    short_name = "taiyaok"
    data = [0, 1, 2, 3, 4]
    time_array = [0, 1, 2, 3, 4]
    fs = 1.0

    def get_signal_channels(self):
        return [f"chan_{i}" for i in range(len(PALETTE))]

    def get_color_palette(self):
        return list(PALETTE)


def _render_at(app, size):
    # Pin the swatch size for this render.  The rebind has to land on
    # ``channel_tree`` -- that is the module whose globals MultiFileChannelWidget
    # resolves ``_swatch_icon`` through; rebinding the ``ui.widgets`` re-export
    # would silently paint the default size instead.
    orig = channel_tree_mod._swatch_icon
    channel_tree_mod._swatch_icon = lambda color, _s=size: orig(color, _s)
    try:
        w = MultiFileChannelWidget()
        w.add_file("f1", _FakeFile())
        # check a couple so the rows show the checked + dot state like the user's
        w.set_checked_channels([("f1", "chan_3"), ("f1", "chan_4")])
        w.resize(240, 300)
        w.show()
        app.processEvents(); app.processEvents()
        # expand the file node so channel rows (with dots) are visible
        w.tree.expandAll()
        app.processEvents(); app.processEvents()
        img = w.tree.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        img.setDevicePixelRatio(1.0)
        w.close()
        return img
    finally:
        channel_tree_mod._swatch_icon = orig


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    load_stylesheet(app)
    sizes = [14, 12, 11, 10]
    imgs = [(s, _render_at(app, s)) for s in sizes]

    pad = 16
    label_h = 26
    cell_w = max(im.width() for _, im in imgs)
    cell_h = max(im.height() for _, im in imgs)
    width = pad + len(imgs) * (cell_w + pad)
    height = label_h + cell_h + 2 * pad
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#ffffff"))
    p = QPainter(canvas)
    f = p.font(); f.setPointSize(12); f.setBold(True); p.setFont(f)
    x = pad
    for s, im in imgs:
        p.setPen(QColor("#111111"))
        tag = "size=%d (current)" % s if s == 14 else "size=%d" % s
        p.drawText(x, 0, cell_w, label_h, Qt.AlignCenter, tag)
        p.drawImage(x, label_h + pad, im)
        x += cell_w + pad
    p.end()
    out = os.path.join(tempfile.gettempdir(), "channel_dot_size_preview.png")
    canvas.save(out)
    print("SCREENSHOT:", out)


if __name__ == "__main__":
    main()
