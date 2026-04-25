"""Precision Light QIcon factories drawn programmatically via QPainter.

No external image assets. Icons render at 2x DPR for sharpness and keep
the PyQt app independent from web/icon-font packages.
"""
from contextlib import contextmanager
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QPainterPath

BLUE = QColor('#1769E0')
GRAY = QColor('#475569')
MUTED = QColor('#64748B')
RED = QColor('#DC2626')
GREEN = QColor('#059669')
AMBER = QColor('#D97706')


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


def _line_icon(draw, color=GRAY, size=20):
    with _painting(size) as (pix, p):
        p.setPen(_pen(color, 1.7))
        p.setBrush(Qt.NoBrush)
        draw(p)
    return QIcon(pix)


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
    def add_file(cls, color=None):
        def draw(p):
            p.drawRoundedRect(QRectF(4, 3, 10, 14), 2, 2)
            p.drawLine(QPointF(7, 7), QPointF(11, 7))
            p.drawLine(QPointF(7, 10), QPointF(11, 10))
            p.drawLine(QPointF(15, 10), QPointF(19, 10))
            p.drawLine(QPointF(17, 8), QPointF(17, 12))
        return _line_icon(draw, color or BLUE)

    @classmethod
    def file(cls):
        def draw(p):
            p.drawRoundedRect(QRectF(5, 3, 11, 14), 2, 2)
            p.drawLine(QPointF(8, 7), QPointF(13, 7))
            p.drawLine(QPointF(8, 10), QPointF(13, 10))
            p.drawLine(QPointF(8, 13), QPointF(11, 13))
        return _line_icon(draw, MUTED)

    @classmethod
    def edit_channels(cls):
        def draw(p):
            p.drawLine(QPointF(4, 6), QPointF(11, 6))
            p.drawLine(QPointF(15, 6), QPointF(18, 6))
            p.drawEllipse(QRectF(11, 4, 4, 4))
            p.drawLine(QPointF(4, 14), QPointF(7, 14))
            p.drawLine(QPointF(11, 14), QPointF(18, 14))
            p.drawEllipse(QRectF(7, 12, 4, 4))
        return _line_icon(draw, GRAY)

    @classmethod
    def export(cls):
        def draw(p):
            p.drawLine(QPointF(10, 3), QPointF(10, 12))
            p.drawLine(QPointF(6, 8), QPointF(10, 12))
            p.drawLine(QPointF(14, 8), QPointF(10, 12))
            p.drawRoundedRect(QRectF(4, 14, 12, 4), 1.5, 1.5)
        return _line_icon(draw, GRAY)

    @classmethod
    def mode_time(cls):
        def draw(p):
            path = QPainterPath()
            path.moveTo(3, 10)
            path.cubicTo(5, 3, 8, 17, 10, 10)
            path.cubicTo(12, 3, 15, 17, 17, 10)
            p.drawPath(path)
        return _line_icon(draw, BLUE)

    @classmethod
    def mode_fft(cls):
        def draw(p):
            p.drawLine(QPointF(4, 17), QPointF(16, 17))
            p.drawLine(QPointF(5, 17), QPointF(5, 8))
            p.drawLine(QPointF(9, 17), QPointF(9, 4))
            p.drawLine(QPointF(13, 17), QPointF(13, 11))
            p.drawLine(QPointF(17, 17), QPointF(17, 6))
        return _line_icon(draw, BLUE)

    @classmethod
    def mode_order(cls):
        def draw(p):
            for x in (4, 10, 16):
                for y in (4, 10, 16):
                    p.drawRect(QRectF(x, y, 3, 3))
        return _line_icon(draw, BLUE)

    @classmethod
    def cursor_reset(cls):
        def draw(p):
            p.drawLine(QPointF(10, 3), QPointF(10, 7))
            p.drawLine(QPointF(10, 13), QPointF(10, 17))
            p.drawLine(QPointF(3, 10), QPointF(7, 10))
            p.drawLine(QPointF(13, 10), QPointF(17, 10))
            p.drawEllipse(QRectF(6, 6, 8, 8))
        return _line_icon(draw, GRAY)

    @classmethod
    def axis_lock(cls):
        with _painting() as (pix, p):
            _padlock(p, GRAY)
        return QIcon(pix)

    @classmethod
    def copy_image(cls):
        """Two stacked rounded rectangles + small mountain glyph — 'copy chart
        as image' action."""
        with _painting() as (pix, p):
            # back card
            p.setPen(_pen(MUTED, 1.3))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(2.5, 2.5, 11, 11), 1.6, 1.6)
            # front card filled white
            p.setPen(_pen(BLUE, 1.4))
            p.setBrush(QBrush(QColor(255, 255, 255)))
            p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 1.6, 1.6)
            # tiny mountain inside front card
            p.setPen(_pen(BLUE, 1.3))
            path = QPainterPath()
            path.moveTo(8, 15.5)
            path.lineTo(10.5, 12)
            path.lineTo(12, 13.5)
            path.lineTo(14, 11)
            path.lineTo(16, 15.5)
            p.drawPath(path)
            # sun dot
            p.setBrush(QBrush(BLUE))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(14.5, 9), 0.9, 0.9)
        return QIcon(pix)

    @classmethod
    def menu(cls):
        def draw(p):
            for y in (6, 10, 14):
                p.drawPoint(QPointF(10, y))
        icon = _line_icon(draw, GRAY)
        return icon

    @classmethod
    def close_file(cls):
        def draw(p):
            p.drawLine(QPointF(6, 6), QPointF(14, 14))
            p.drawLine(QPointF(14, 6), QPointF(6, 14))
        return _line_icon(draw, RED)

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
