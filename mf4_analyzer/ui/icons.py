"""macOS-style QIcon factories. All icons drawn programmatically via QPainter.
No external image assets. Icons render at 2x DPR for Retina sharpness."""
from contextlib import contextmanager
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QPainterPath

BLUE = QColor('#007AFF')
GRAY = QColor('#48484A')
RED = QColor('#FF3B30')
GREEN = QColor('#34C759')  # reserved; matches #success in style.qss


def _canvas(size=20):
    pix = QPixmap(size * 2, size * 2)
    pix.setDevicePixelRatio(2.0)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    return pix, p


@contextmanager
def _painting(size=20):
    pix, p = _canvas(size)
    try:
        yield pix, p
    finally:
        p.end()


def _pen(color, w=1.5):
    pen = QPen(color, w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _padlock(p, color):
    """Draw a small padlock at ~(4..16, 6..16). Shared body for lock_x/lock_y."""
    p.setPen(_pen(color, 1.4))
    p.setBrush(Qt.NoBrush)
    # shackle (top U)
    p.drawArc(QRectF(6, 3, 8, 8), 0 * 16, 180 * 16)
    # body (rounded rect)
    p.setBrush(QBrush(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(4, 8, 12, 9), 1.5, 1.5)


def _axis_letter(p, letter, color=None):
    """Overlay a single letter on the lock body."""
    if color is None:
        color = QColor(255, 255, 255)
    f = QFont()
    f.setPointSizeF(6.5)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QPen(color))
    p.drawText(QRectF(4, 8, 12, 9), Qt.AlignCenter, letter)


class Icons:
    @classmethod
    def lock_x(cls):
        with _painting() as (pix, p):
            _padlock(p, BLUE)
            _axis_letter(p, 'X')
        return QIcon(pix)

    @classmethod
    def lock_y(cls):
        with _painting() as (pix, p):
            _padlock(p, BLUE)
            _axis_letter(p, 'Y')
        return QIcon(pix)

    @classmethod
    def add_file(cls):
        with _painting() as (pix, p):
            # circle outline
            p.setPen(_pen(BLUE, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(3, 3, 14, 14))
            # plus
            p.drawLine(QPointF(10, 6), QPointF(10, 14))
            p.drawLine(QPointF(6, 10), QPointF(14, 10))
        return QIcon(pix)

    @classmethod
    def close_file(cls):
        with _painting() as (pix, p):
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(RED))
            p.drawRoundedRect(QRectF(3, 3, 14, 14), 4, 4)
            p.setPen(_pen(QColor(255, 255, 255), 1.8))
            p.drawLine(QPointF(7, 7), QPointF(13, 13))
            p.drawLine(QPointF(13, 7), QPointF(7, 13))
        return QIcon(pix)

    @classmethod
    def close_all(cls):
        with _painting() as (pix, p):
            p.setPen(Qt.NoPen)
            # two stacked red squares
            p.setBrush(QBrush(QColor(255, 59, 48, 110)))
            p.drawRoundedRect(QRectF(1, 5, 13, 13), 3, 3)
            p.setBrush(QBrush(RED))
            p.drawRoundedRect(QRectF(6, 2, 13, 13), 3, 3)
            p.setPen(_pen(QColor(255, 255, 255), 1.6))
            p.drawLine(QPointF(10, 6), QPointF(15, 11))
            p.drawLine(QPointF(15, 6), QPointF(10, 11))
        return QIcon(pix)

    @classmethod
    def plot(cls):
        with _painting() as (pix, p):
            p.setPen(_pen(BLUE, 1.6))
            path = QPainterPath()
            path.moveTo(3, 15)
            path.lineTo(7, 9)
            path.lineTo(11, 12)
            path.lineTo(17, 4)
            p.drawPath(path)
            # axis baseline
            p.setPen(_pen(GRAY, 1.0))
            p.drawLine(QPointF(3, 17), QPointF(17, 17))
            p.drawLine(QPointF(3, 17), QPointF(3, 4))
        return QIcon(pix)

    @classmethod
    def rebuild_time(cls):
        with _painting() as (pix, p):
            p.setPen(_pen(BLUE, 1.5))
            p.setBrush(Qt.NoBrush)
            # circular arrow
            p.drawArc(QRectF(3, 3, 14, 14), 30 * 16, 270 * 16)
            # arrowhead
            path = QPainterPath()
            path.moveTo(14, 2)
            path.lineTo(17, 5)
            path.lineTo(12, 6)
            path.closeSubpath()
            p.setBrush(QBrush(BLUE))
            p.setPen(Qt.NoPen)
            p.drawPath(path)
            # clock hand
            p.setPen(_pen(BLUE, 1.3))
            p.drawLine(QPointF(10, 10), QPointF(10, 6))
            p.drawLine(QPointF(10, 10), QPointF(13, 10))
        return QIcon(pix)
