"""Visual verification for the HiDPI color-swatch / View-tab-dot fix.

Authoritative method: put the OLD (pre-fix, 1x) icon and the shipped NEW icon
into REAL on-screen widgets (a QTreeWidget row and a QTabBar tab) on the live
Retina display, grab the native 2x device pixels Qt actually painted, auto-crop
the orange dot from each, magnify with NEAREST-neighbour so the painted pixels
are visible, and stack OLD-vs-NEW side by side into one PNG.

This routes through the exact paint path the user sees: Qt upscales the OLD 1x
pixmap to fill the icon slot on a 2x screen (smeared/jagged), while the NEW
pixmap is tagged with the device pixel ratio and painted 1:1 (crisp).

Run on macOS desktop (NOT offscreen):
    PYTHONPATH=. .venv/bin/python scripts/color_swatch_hidpi_smoke.py
"""
import os
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)  # must be the real cocoa platform

from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QBrush, QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QTabBar,
    QTreeWidget,
    QTreeWidgetItem,
)

from mf4_analyzer.ui.widgets import _swatch_pixmap
from mf4_analyzer.ui.view_tabbar import _tab_color_pixmap
from mf4_analyzer.ui.markup.editor import MarkupEditor

ORANGE = "#ff7f0e"


# --- OLD (pre-fix) implementations, reproduced verbatim for comparison -------
def _old_editor_color_pixmap(hex_color):
    pix = QPixmap(18, 18)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor("#d0d7e2"), 1))
    p.setBrush(QBrush(QColor(hex_color)))
    p.drawEllipse(QRectF(3, 3, 12, 12))
    p.end()
    return pix

def _old_swatch_pixmap(color, size=14):
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor(color), 1))
    p.setBrush(QBrush(QColor(color)))
    p.drawRoundedRect(2, 2, size - 4, size - 4, 3, 3)
    p.end()
    return pix


def _old_tab_pixmap(hex_color, size=12):
    color = QColor(hex_color)
    if not color.isValid():
        color = QColor("#2d7ff9")
    pix = QPixmap(QSize(size, size))
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(color.darker(115), 1))
    p.setBrush(color)
    p.drawRoundedRect(1, 3, 10, 6, 2, 2)
    p.end()
    return pix


def _is_orange(qrgb):
    a = (qrgb >> 24) & 0xFF
    r = (qrgb >> 16) & 0xFF
    g = (qrgb >> 8) & 0xFF
    b = qrgb & 0xFF
    return a > 30 and r > 140 and g < r - 20 and b < 130


def _orange_mask(img):
    pts = []
    for y in range(img.height()):
        for x in range(img.width()):
            if _is_orange(img.pixel(x, y)):
                pts.append((x, y))
    return pts


def _bands(values, gap=3):
    """Group sorted distinct ints into runs separated by >= gap blanks."""
    vals = sorted(set(values))
    bands = []
    if not vals:
        return bands
    start = prev = vals[0]
    for v in vals[1:]:
        if v - prev > gap:
            bands.append((start, prev))
            start = v
        prev = v
    bands.append((start, prev))
    return bands


def _bbox_of(pts):
    xs = [x for x, _ in pts]; ys = [y for _, y in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _split_blobs(img, axis):
    """Return per-blob bboxes. axis='y' splits stacked rows (tree),
    axis='x' splits side-by-side columns (tab bar)."""
    pts = _orange_mask(img)
    if not pts:
        return []
    coord = 1 if axis == "y" else 0
    bands = _bands([p[coord] for p in pts])
    out = []
    for lo, hi in bands:
        blob = [p for p in pts if lo <= p[coord] <= hi]
        if blob:
            out.append(_bbox_of(blob))
    return out


def _crop_pad(img, bbox, pad):
    xmin, ymin, xmax, ymax = bbox
    x = max(0, xmin - pad); y = max(0, ymin - pad)
    w = min(img.width(), xmax + pad + 1) - x
    h = min(img.height(), ymax + pad + 1) - y
    return img.copy(x, y, w, h)


def _magnify(img, scale):
    return img.scaled(img.width() * scale, img.height() * scale,
                      Qt.IgnoreAspectRatio, Qt.FastTransformation)


def _grab_pair_in_tree(app, old_icon, new_icon, icon_px):
    """Put OLD icon (row 1) and NEW icon (row 2) in a QTreeWidget, grab the
    native pixels and auto-crop the orange dot from each. Returns (old, new)."""
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(False)
    tree.setIconSize(QSize(icon_px, icon_px))
    tree.setStyleSheet("QTreeWidget{background:#ffffff;border:0;}")
    a = QTreeWidgetItem(["  OLD"]); a.setIcon(0, old_icon)
    b = QTreeWidgetItem(["  NEW"]); b.setIcon(0, new_icon)
    tree.addTopLevelItem(a)
    tree.addTopLevelItem(b)
    tree.resize(260, 80)
    tree.show()
    app.processEvents(); app.processEvents()
    img = tree.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    img.setDevicePixelRatio(1.0)
    blobs = _split_blobs(img, "y")
    tree.close()
    if len(blobs) < 2:
        return None, None
    return _crop_pad(img, blobs[0], 3), _crop_pad(img, blobs[1], 3)


def _grab_tree_dots(app):
    """Two QTreeWidget rows: OLD icon, NEW icon. Returns (old_img, new_img)."""
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(False)
    tree.setIconSize(QSize(14, 14))
    tree.setStyleSheet("QTreeWidget{background:#ffffff;border:0;}")
    old_item = QTreeWidgetItem(["  channel A (OLD)"])
    old_item.setIcon(0, QIcon(_old_swatch_pixmap(ORANGE, 14)))
    new_item = QTreeWidgetItem(["  channel B (NEW)"])
    new_item.setIcon(0, QIcon(_swatch_pixmap(ORANGE, 14)))
    tree.addTopLevelItem(old_item)
    tree.addTopLevelItem(new_item)
    tree.resize(260, 80)
    tree.show()
    app.processEvents(); app.processEvents()
    img = tree.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    img.setDevicePixelRatio(1.0)
    blobs = _split_blobs(img, "y")  # OLD row above NEW row
    tree.close()
    if len(blobs) < 2:
        return None, None
    return _crop_pad(img, blobs[0], 3), _crop_pad(img, blobs[1], 3)


def _grab_tab_dots(app):
    """A QTabBar with OLD-icon and NEW-icon tabs. Returns (old_img, new_img)."""
    bar = QTabBar()
    bar.setStyleSheet("QTabBar{background:#ffffff;} QTabBar::tab{background:#ffffff;padding:6px 14px;}")
    bar.addTab(QIcon(_old_tab_pixmap(ORANGE, 12)), "OLD")
    bar.addTab(QIcon(_tab_color_pixmap(ORANGE)), "NEW")
    bar.setIconSize(QSize(12, 12))
    bar.resize(220, 44)
    bar.show()
    app.processEvents(); app.processEvents()
    img = bar.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    img.setDevicePixelRatio(1.0)
    blobs = _split_blobs(img, "x")  # OLD tab left of NEW tab
    bar.close()
    if len(blobs) < 2:
        return None, None
    return _crop_pad(img, blobs[0], 3), _crop_pad(img, blobs[1], 3)


def _compose(pairs, dpr, out_path):
    mag = 14
    label_h = 22
    pad = 20
    col_w = max(max(o.width(), n.width()) for _, o, n in pairs) * mag
    cell_w = col_w + pad
    header_h = 36
    row_h = label_h + max(max(o.height(), n.height()) for _, o, n in pairs) * mag + pad
    left = 150
    width = pad + left + 2 * cell_w
    height = header_h + len(pairs) * row_h + pad
    canvas = QPixmap(width, height)
    canvas.fill(QColor("#ffffff"))
    p = QPainter(canvas)
    p.setPen(QColor("#111111"))
    f = p.font(); f.setPointSize(13); f.setBold(True); p.setFont(f)
    p.drawText(pad + left, 0, col_w, header_h, Qt.AlignCenter,
               f"OLD  (1x, upscaled by Qt @ dpr={dpr:g})")
    p.drawText(pad + left + cell_w, 0, col_w, header_h, Qt.AlignCenter,
               "NEW  (rendered at dpr)")
    y = header_h
    for title, old_img, new_img in pairs:
        f.setBold(False); f.setPointSize(11); p.setFont(f)
        p.setPen(QColor("#333333"))
        p.drawText(8, y, left - 8, row_h, Qt.AlignLeft | Qt.AlignVCenter, title)
        ox = pad + left
        for col, im in ((0, old_img), (1, new_img)):
            if im is None:
                continue
            xx = ox + col * cell_w
            p.drawImage(xx, y + label_h, _magnify(im, mag))
            p.setPen(QPen(QColor("#cccccc"), 1))
            p.drawRect(xx - 1, y + label_h - 1, im.width() * mag + 1, im.height() * mag + 1)
        y += row_h
    p.end()
    canvas.save(out_path)
    return out_path


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    dpr = app.devicePixelRatio()
    print("live devicePixelRatio:", dpr)
    # The unambiguous proof: OLD source is 1x (Qt MUST upscale it to fill the
    # icon slot on this 2x screen -> soft/jagged); NEW source is rendered at the
    # device ratio and painted 1:1 (crisp).
    s_old, s_new = _old_swatch_pixmap(ORANGE, 14), _swatch_pixmap(ORANGE, 14)
    t_old, t_new = _old_tab_pixmap(ORANGE, 12), _tab_color_pixmap(ORANGE)
    print(f"channel swatch source: OLD {s_old.width()}px@{s_old.devicePixelRatioF():g}  "
          f"->  NEW {s_new.width()}px@{s_new.devicePixelRatioF():g}")
    print(f"View-tab dot   source: OLD {t_old.width()}px@{t_old.devicePixelRatioF():g}  "
          f"->  NEW {t_new.width()}px@{t_new.devicePixelRatioF():g}")

    so, sn = _grab_tree_dots(app)
    to, tn = _grab_tab_dots(app)
    # markup editor color dot (shipped MarkupEditor._color_icon vs the old 1x)
    eo, en = _grab_pair_in_tree(
        app,
        QIcon(_old_editor_color_pixmap(ORANGE)),
        MarkupEditor._color_icon(MarkupEditor, QColor(ORANGE)),
        18,
    )
    pairs = [
        ("channel\nlist dot", so, sn),
        ("View-tab\ndot", to, tn),
        ("markup editor\ncolor dot", eo, en),
    ]
    for title, o, n in pairs:
        if o is None or n is None:
            print(f"[{title.replace(chr(10), ' ')!r}] crop failed:", o is None, n is None)
    out = os.path.join(tempfile.gettempdir(), "color_swatch_hidpi_compare.png")
    _compose(pairs, dpr, out)
    print("SCREENSHOT:", out)


if __name__ == "__main__":
    main()
