"""Stroke disclosure chevron shared by inspector section headers.

Qt's native ``QToolButton`` arrow is a filled triangle. On macOS that
glyph is heavy and picks up the accent color while the button is
checked. Analysis sections already paint this hairline chevron; the
time-domain chart-settings handle must use the same pixmap.
"""
from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

_CHEVRON_COLOR = QColor("#475569")
_LOGICAL = 12


def inspector_chevron_icon(host, degrees):
    """Right-pointing chevron, rotated clockwise up to 90° (down)."""
    dpr = max(1.0, float(host.devicePixelRatioF()))
    side = max(_LOGICAL, int(round(_LOGICAL * dpr)))
    pixmap = QPixmap(side, side)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.translate(_LOGICAL / 2.0, _LOGICAL / 2.0)
    painter.rotate(max(0.0, min(90.0, float(degrees))))
    pen = QPen(_CHEVRON_COLOR, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPolyline(
        QPolygonF(
            (
                QPointF(-1.5, -2.7),
                QPointF(1.2, 0.0),
                QPointF(-1.5, 2.7),
            )
        )
    )
    painter.end()
    return QIcon(pixmap)
