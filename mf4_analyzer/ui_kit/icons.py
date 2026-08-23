"""Precision Light QIcon factories drawn programmatically via QPainter.

No external image assets. Icons render at 2x DPR for sharpness and keep
the PyQt app independent from web/icon-font packages.
"""
from contextlib import contextmanager
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QFont, QPainterPath
from PyQt5.QtWidgets import QApplication


def icon_device_pixel_ratio() -> float:
    """Device pixel ratio to render programmatically-drawn icons at.

    Returns the running QApplication's ratio (2.0 on a Retina screen), or 1.0
    when there is no application yet / on a standard-DPI screen. A pixmap built
    at ``round(size * ratio)`` physical pixels and tagged via
    ``setDevicePixelRatio(ratio)`` paints crisp on HiDPI, instead of letting Qt
    upscale a 1x bitmap at paint time (which smears the antialiased edge into
    the jagged dots seen on Retina).
    """
    app = QApplication.instance()
    ratio = app.devicePixelRatio() if app is not None else 1.0
    return ratio if ratio and ratio >= 1.0 else 1.0


BLUE = QColor('#1769E0')
GRAY = QColor('#475569')
MUTED = QColor('#64748B')
RED = QColor('#DC2626')
GREEN = QColor('#059669')
AMBER = QColor('#D97706')
CHEVRON = QColor('#7B8798')
LASER_DOT_COLOR = QColor('#E6364D')
LASER_DOT_CORE_DIAMETER = 8.0
LASER_DOT_HALO_DIAMETER = 20.0
LASER_DOT_OPTION = "B"


def paint_laser_glow(
    painter,
    center,
    *,
    core_diameter=LASER_DOT_CORE_DIAMETER,
    halo_diameter=LASER_DOT_HALO_DIAMETER,
    color=None,
):
    """Draw option-B glowing disc. Core/halo stay in the same 8/20 ratio."""
    fill = QColor(color or LASER_DOT_COLOR)
    core_r = max(0.5, float(core_diameter) / 2.0)
    halo_r = max(core_r, float(halo_diameter) / 2.0)
    painter.save()
    painter.setPen(Qt.NoPen)
    outer = QColor(fill)
    outer.setAlpha(55)
    painter.setBrush(outer)
    painter.drawEllipse(center, halo_r, halo_r)
    mid = QColor(fill)
    mid.setAlpha(115)
    mid_r = (halo_r + core_r) * 0.5
    painter.setBrush(mid)
    painter.drawEllipse(center, mid_r, mid_r)
    painter.setBrush(fill)
    painter.drawEllipse(center, core_r, core_r)
    highlight = QColor(255, 255, 255, 210)
    painter.setBrush(highlight)
    painter.drawEllipse(
        QPointF(center.x() - core_r * 0.28, center.y() - core_r * 0.28),
        core_r * 0.32,
        core_r * 0.32,
    )
    painter.restore()


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


# UltraView's icon-only rails have two deliberately supported icon targets:
# 20px in compact mode and 24px on the desktop.  A single 20px QIcon source
# is otherwise upscaled by Qt at the desktop target, which softens the small
# QPainter strokes on both Retina and 100%-scale displays.  Keep this helper
# narrow: the rest of the app retains its established 20px icon contract.
_ULTRAVIEW_ICON_LOGICAL_SIZES = (20, 24, 28)
_ULTRAVIEW_ICON_DESIGN_SIZE = 20.0


@contextmanager
def _ultraview_painting(logical_size):
    ratio = max(float(icon_device_pixel_ratio()), 2.0)
    physical_size = max(1, int(round(logical_size * ratio)))
    pix = QPixmap(physical_size, physical_size)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    # The individual glyphs stay authored in the familiar 20-unit grid while
    # each target gets a freshly rasterised, correctly proportioned path.
    scale = float(logical_size) / _ULTRAVIEW_ICON_DESIGN_SIZE
    painter.scale(scale, scale)
    try:
        yield pix, painter
    finally:
        painter.end()


def _ultraview_icon(draw):
    icon = QIcon()
    for logical_size in _ULTRAVIEW_ICON_LOGICAL_SIZES:
        with _ultraview_painting(logical_size) as (pix, painter):
            draw(painter)
        icon.addPixmap(pix, QIcon.Normal, QIcon.Off)
    return icon


def _ultraview_line_icon(draw, color=GRAY, pen_width=1.85):
    def paint(painter):
        painter.setPen(_pen(color, pen_width))
        painter.setBrush(Qt.NoBrush)
        draw(painter)

    return _ultraview_icon(paint)


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


def _line_edit_action_icon(draw, *, logical=16, color=MUTED, filled=False):
    """Crisp square icon sized for QLineEdit leading/trailing actions.

    Hard-coding the shared ``_canvas(20)`` path left empty margin that made
    glyphs look coarse and sit optically low inside the 32px search track.
    This helper paints into a tight ``logical`` box at >=2× DPR so Windows
    100–150% scaling stays sharp.
    """
    ratio = max(float(icon_device_pixel_ratio()), 2.0)
    physical = max(1, int(round(logical * ratio)))
    pix = QPixmap(physical, physical)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    try:
        if filled:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
        else:
            painter.setPen(_pen(color, 1.55))
            painter.setBrush(Qt.NoBrush)
        draw(painter, float(logical))
    finally:
        painter.end()
    return QIcon(pix)


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
    def search(cls, color=None):
        """Leading magnifier for shared SearchField — stroke AA, not font glyph."""
        stroke = color or MUTED

        def draw(p, size):
            # Optically center the lens; handle stays inside the square.
            lens = size * 0.58
            inset = (size - lens) * 0.38
            p.drawEllipse(QRectF(inset, inset, lens, lens))
            p.drawLine(
                QPointF(inset + lens * 0.72, inset + lens * 0.72),
                QPointF(size - size * 0.14, size - size * 0.14),
            )

        return _line_edit_action_icon(draw, color=stroke)

    @classmethod
    def clear_field(cls, color=None):
        """Trailing clear affordance: soft disc + crisp X (replaces Qt stock)."""
        fill = color or MUTED

        def draw(p, size):
            margin = size * 0.12
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(fill))
            p.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
            p.setPen(_pen(QColor("#ffffff"), 1.45))
            p.setBrush(Qt.NoBrush)
            pad = size * 0.34
            p.drawLine(QPointF(pad, pad), QPointF(size - pad, size - pad))
            p.drawLine(QPointF(size - pad, pad), QPointF(pad, size - pad))

        return _line_edit_action_icon(draw, color=fill, filled=True)

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
    def eye_open(cls):
        """Visible-channel glyph for the TimeDomain channel tree."""
        with _painting() as (pix, p):
            p.setPen(_pen(BLUE, 1.45))
            p.setBrush(Qt.NoBrush)
            eye = QPainterPath()
            eye.moveTo(3, 10)
            eye.cubicTo(6, 5, 14, 5, 17, 10)
            eye.cubicTo(14, 15, 6, 15, 3, 10)
            eye.closeSubpath()
            p.drawPath(eye)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(BLUE))
            p.drawEllipse(QRectF(8, 8, 4, 4))
        return QIcon(pix)

    @classmethod
    def eye_closed(cls):
        """Hidden-channel glyph: quiet eye contour with an explicit slash."""
        with _painting() as (pix, p):
            p.setPen(_pen(MUTED, 1.45))
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(4, 5, 12, 10), 200 * 16, 140 * 16)
            p.drawLine(QPointF(4, 4), QPointF(16, 16))
        return QIcon(pix)

    @classmethod
    def export(cls, color=None):
        def draw(p):
            p.drawLine(QPointF(10, 3), QPointF(10, 12))
            p.drawLine(QPointF(6, 8), QPointF(10, 12))
            p.drawLine(QPointF(14, 8), QPointF(10, 12))
            p.drawRoundedRect(QRectF(4, 14, 12, 4), 1.5, 1.5)
        return _line_icon(draw, color or GRAY)

    @classmethod
    def expand_focus(cls, color=None):
        """Four corner brackets for UltraView temporary-focus / expand."""
        stroke = color or BLUE

        def draw(p, size):
            p.setPen(_pen(stroke, 2.05))
            pad = size * 0.16
            arm = size * 0.32
            corners = (
                (pad, pad, pad + arm, pad, pad, pad + arm),
                (size - pad, pad, size - pad - arm, pad, size - pad, pad + arm),
                (pad, size - pad, pad + arm, size - pad, pad, size - pad - arm),
                (
                    size - pad,
                    size - pad,
                    size - pad - arm,
                    size - pad,
                    size - pad,
                    size - pad - arm,
                ),
            )
            for x, y, x_h, y_h, x_v, y_v in corners:
                p.drawLine(QPointF(x, y), QPointF(x_h, y_h))
                p.drawLine(QPointF(x, y), QPointF(x_v, y_v))

        return _line_edit_action_icon(draw, logical=16, color=stroke)

    @classmethod
    def batch(cls):
        """Task-queue glyph for batch processing."""
        with _painting() as (pix, p):
            p.setPen(_pen(GRAY, 1.45))
            p.setBrush(Qt.NoBrush)
            for y in (5, 10, 15):
                p.drawRoundedRect(QRectF(3, y - 1.6, 3.2, 3.2), 0.9, 0.9)
                p.drawLine(QPointF(8, y), QPointF(13.5, y))

            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(GRAY))
            play = QPainterPath()
            play.moveTo(15, 6.2)
            play.lineTo(18, 10)
            play.lineTo(15, 13.8)
            play.closeSubpath()
            p.drawPath(play)
        return QIcon(pix)

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
    def mode_frf(cls):
        """Input -> transfer block -> output, legible at toolbar size."""
        with _painting() as (pix, p):
            p.setPen(_pen(BLUE, 1.35))
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(2.5, 10), QPointF(6.0, 10))
            p.drawRoundedRect(QRectF(6.0, 5.5, 7.5, 9.0), 1.4, 1.4)
            font = QFont()
            font.setPointSizeF(6.0)
            font.setBold(True)
            p.setFont(font)
            p.drawText(QRectF(6.0, 5.5, 7.5, 9.0), Qt.AlignCenter, "H")
            p.drawLine(QPointF(13.5, 10), QPointF(17.5, 10))
            p.drawLine(QPointF(15.4, 7.9), QPointF(17.5, 10))
            p.drawLine(QPointF(15.4, 12.1), QPointF(17.5, 10))
        return QIcon(pix)

    @classmethod
    def mode_order(cls):
        def draw(p):
            for x in (4, 10, 16):
                for y in (4, 10, 16):
                    p.drawRect(QRectF(x, y, 3, 3))
        return _line_icon(draw, BLUE)

    @classmethod
    def mode_fft_time(cls):
        """Time-frequency glyph: stacked horizontal bands (frequency rows
        across time) — distinguishes from mode_fft (vertical bars) and
        mode_order (3x3 grid)."""
        def draw(p):
            # bottom axes (time x · freq y)
            p.drawLine(QPointF(3, 17), QPointF(17, 17))
            p.drawLine(QPointF(3, 3), QPointF(3, 17))
            # three horizontal bands at increasing intensity (drawn as dashes)
            p.drawLine(QPointF(5, 14), QPointF(16, 14))
            p.drawLine(QPointF(5, 10), QPointF(13, 10))
            p.drawLine(QPointF(5, 6), QPointF(15, 6))
        return _line_icon(draw, BLUE)

    @classmethod
    def mode_ultraview(cls):
        """Board of preview cards: 2×3 tiles, distinct from mode_order's 3×3."""
        def draw(p):
            for x in (3, 11):
                for y in (3, 9, 15):
                    p.drawRoundedRect(QRectF(x, y, 6, 4), 0.8, 0.8)
        return _line_icon(draw, BLUE)

    # UltraView narrow-rail actions.  These deliberately remain programmatic
    # line icons rather than Unicode/emoji glyphs: the rail is icon-only and
    # must stay visually stable across the macOS and Windows fallback fonts.

    @classmethod
    def ultraview_library(cls, color=None):
        """Stacked preview rows for opening the UltraView View library."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(3.2, 3.0, 13.6, 14.0), 2.0, 2.0)
            for y, width in ((6.4, 7.0), (10.0, 8.8), (13.6, 5.4)):
                p.drawLine(QPointF(6.0, y), QPointF(6.0 + width, y))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            for y in (6.4, 10.0, 13.6):
                p.drawEllipse(QPointF(4.8, y), 0.9, 0.9)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_pin(cls, color=None):
        """Tack used to keep the View library open while clicking the board."""
        c = color or GRAY

        def draw(p):
            p.drawEllipse(QRectF(6.6, 3.0, 6.8, 6.8))
            p.drawLine(QPointF(10.0, 9.8), QPointF(10.0, 16.8))
            p.drawLine(QPointF(7.2, 7.4), QPointF(12.8, 7.4))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_layout(cls, color=None):
        """Unequal board cells for template/free-grid layout selection."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(2.8, 3.0, 14.4, 14.0), 1.8, 1.8)
            p.drawLine(QPointF(10.0, 3.5), QPointF(10.0, 16.5))
            p.drawLine(QPointF(10.5, 8.0), QPointF(16.7, 8.0))
            p.drawLine(QPointF(10.5, 12.2), QPointF(16.7, 12.2))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_free_grid(cls, color=None):
        """Even 3-by-4 cells standing in for the 12-column free grid."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(2.8, 3.0, 14.4, 14.0), 1.8, 1.8)
            for i in (1, 2, 3):
                x = 2.8 + 14.4 * i / 4.0
                p.drawLine(QPointF(x, 3.5), QPointF(x, 16.5))
            for j in (1, 2):
                y = 3.0 + 14.0 * j / 3.0
                p.drawLine(QPointF(3.3, y), QPointF(16.7, y))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_filter(cls, color=None):
        """Funnel glyph for the transient compare/filter popover."""
        c = color or GRAY

        def draw(p):
            path = QPainterPath()
            path.moveTo(3.5, 4.0)
            path.lineTo(16.5, 4.0)
            path.lineTo(11.5, 9.6)
            path.lineTo(11.5, 15.8)
            path.lineTo(8.5, 17.0)
            path.lineTo(8.5, 9.6)
            path.closeSubpath()
            p.drawPath(path)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_unplaced(cls, color=None):
        """Card descending into a tray for the unplaced-card panel."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(4.0, 3.0, 12.0, 7.3), 1.4, 1.4)
            p.drawLine(QPointF(10.0, 10.8), QPointF(10.0, 14.2))
            p.drawLine(QPointF(7.8, 12.4), QPointF(10.0, 14.6))
            p.drawLine(QPointF(12.2, 12.4), QPointF(10.0, 14.6))
            p.drawLine(QPointF(4.0, 17.0), QPointF(16.0, 17.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_author_sticky(cls, color=None):
        """Outline sticky note with a folded corner; not a solid square."""
        c = color or GRAY

        def draw(p):
            note = QPainterPath()
            note.moveTo(3.5, 3.5)
            note.lineTo(16.5, 3.5)
            note.lineTo(16.5, 12.0)
            note.lineTo(12.0, 16.5)
            note.lineTo(3.5, 16.5)
            note.closeSubpath()
            p.drawPath(note)
            p.drawLine(QPointF(12.0, 16.5), QPointF(12.0, 12.0))
            p.drawLine(QPointF(12.0, 12.0), QPointF(16.5, 12.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_author_text(cls, color=None):
        """Compact sans-serif T; not a serif capital A."""
        c = color or GRAY

        def draw(p):
            p.drawLine(QPointF(3.6, 3.8), QPointF(16.4, 3.8))
            p.drawLine(QPointF(10.0, 3.8), QPointF(10.0, 16.4))
            p.drawLine(QPointF(3.6, 3.8), QPointF(3.6, 6.2))
            p.drawLine(QPointF(16.4, 3.8), QPointF(16.4, 6.2))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_author_shapes(cls, color=None):
        """Outline square, circle, and triangle sharing one stroke."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(3.5, 9.0, 6.8, 7.0), 0.9, 0.9)
            p.drawEllipse(QRectF(10.0, 3.5, 6.5, 6.5))
            tri = QPainterPath()
            tri.moveTo(13.3, 10.4)
            tri.lineTo(16.5, 16.5)
            tri.lineTo(10.2, 16.5)
            tri.closeSubpath()
            p.drawPath(tri)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_author_draw(cls, color=None):
        """Canonical outline pen. Rail glyph does not follow the subtool."""
        c = color or GRAY

        def draw(p):
            shaft = QPainterPath()
            shaft.moveTo(5.0, 14.6)
            shaft.lineTo(13.6, 5.5)
            shaft.lineTo(15.8, 7.7)
            shaft.lineTo(7.2, 16.8)
            shaft.closeSubpath()
            p.drawPath(shaft)
            p.drawLine(QPointF(12.7, 4.7), QPointF(15.1, 7.1))
            nib = QPainterPath()
            nib.moveTo(5.0, 14.6)
            nib.lineTo(3.6, 16.6)
            nib.lineTo(7.2, 16.8)
            p.drawPath(nib)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_draw_pen(cls, color=None):
        """Draw-popover pen: enlarged nib, shaft, and baseline stroke."""
        c = color or GRAY

        def draw(p):
            p.setPen(_pen(c, 1.9))
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(12.4, 4.2), QPointF(6.6, 12.4))
            p.drawLine(QPointF(15.6, 6.5), QPointF(9.8, 14.7))
            p.drawLine(QPointF(12.4, 4.2), QPointF(15.6, 6.5))
            p.drawLine(QPointF(9.0, 9.0), QPointF(12.7, 11.7))
            nib = QPainterPath()
            nib.moveTo(6.6, 12.4)
            nib.lineTo(4.8, 15.7)
            nib.lineTo(9.8, 14.7)
            nib.closeSubpath()
            p.drawPath(nib)
            p.drawLine(QPointF(7.1, 13.5), QPointF(4.8, 15.7))
            p.drawLine(QPointF(4.5, 16.4), QPointF(16.0, 16.4))

        return _ultraview_icon(draw)

    @classmethod
    def ultraview_draw_highlighter(cls, color=None):
        """Draw-popover highlighter: enlarged chisel and a thick mark."""
        c = color or GRAY

        def draw(p):
            p.setPen(_pen(c, 1.9))
            p.setBrush(Qt.NoBrush)
            barrel = QPainterPath()
            barrel.moveTo(7.6, 3.8)
            barrel.lineTo(14.0, 3.8)
            barrel.lineTo(13.5, 11.1)
            barrel.lineTo(7.1, 11.1)
            barrel.closeSubpath()
            p.drawPath(barrel)
            p.drawLine(QPointF(7.6, 5.5), QPointF(13.9, 5.5))
            chisel = QPainterPath()
            chisel.moveTo(5.8, 11.1)
            chisel.lineTo(14.8, 11.1)
            chisel.lineTo(15.4, 13.8)
            chisel.lineTo(5.2, 13.8)
            chisel.closeSubpath()
            p.drawPath(chisel)
            p.setPen(_pen(c, 3.0))
            p.drawLine(QPointF(4.2, 16.5), QPointF(16.0, 16.5))

        return _ultraview_icon(draw)

    @classmethod
    def ultraview_draw_eraser(cls, color=None):
        """Draw-popover eraser: enlarged tilted rubber with a divider band."""
        c = color or GRAY

        def draw(p):
            p.setPen(_pen(c, 1.9))
            p.setBrush(Qt.NoBrush)
            body = QPainterPath()
            body.moveTo(3.8, 12.0)
            body.lineTo(10.2, 4.2)
            body.lineTo(16.2, 7.4)
            body.lineTo(9.8, 15.2)
            body.closeSubpath()
            p.drawPath(body)
            p.drawLine(QPointF(6.4, 13.4), QPointF(12.8, 5.8))

        return _ultraview_icon(draw)

    @classmethod
    def ultraview_draw_lasso(cls, color=None):
        """Draw-popover lasso: enlarged dashed loop with a visible tail."""
        c = color or GRAY

        def draw(p):
            p.setBrush(Qt.NoBrush)
            loop = QPainterPath()
            loop.moveTo(7.8, 9.0)
            loop.cubicTo(4.6, 6.1, 7.4, 3.8, 11.2, 4.2)
            loop.cubicTo(15.2, 4.7, 16.0, 9.1, 14.2, 12.2)
            loop.cubicTo(12.3, 15.7, 7.2, 16.0, 5.4, 13.1)
            loop.cubicTo(4.2, 11.1, 5.0, 9.8, 7.8, 9.0)
            dash = _pen(c, 1.9)
            dash.setCapStyle(Qt.FlatCap)
            dash.setStyle(Qt.CustomDashLine)
            dash.setDashPattern([1.25, 1.2])
            p.setPen(dash)
            p.drawPath(loop)
            p.setPen(_pen(c, 1.9))
            p.drawLine(QPointF(7.8, 9.0), QPointF(16.1, 16.5))
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(4.8, 10.5), 1.0, 1.0)

        return _ultraview_icon(draw)

    @classmethod
    def ultraview_author_select(cls, color=None):
        """B2 pointer: a larger, optically centred outline cursor."""
        c = color or GRAY

        def draw(p):
            path = QPainterPath()
            path.moveTo(4.2, 3.2)
            path.lineTo(4.2, 16.8)
            path.lineTo(7.8, 13.7)
            path.lineTo(11.2, 17.0)
            path.lineTo(13.0, 15.4)
            path.lineTo(9.8, 12.0)
            path.lineTo(16.4, 12.0)
            path.closeSubpath()
            p.drawPath(path)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_author_laser(cls, color=None):
        """Option B glowing disc. Same 8/20 core/halo ratio as the real cursor."""
        del color
        # 20px design grid, 2px inset: halo 16, core 6.4 (= 16 * 8/20).
        halo = 16.0
        core = halo * (LASER_DOT_CORE_DIAMETER / LASER_DOT_HALO_DIAMETER)

        def draw(p):
            paint_laser_glow(
                p,
                QPointF(10.0, 10.0),
                core_diameter=core,
                halo_diameter=halo,
                color=LASER_DOT_COLOR,
            )

        return _ultraview_icon(draw)

    @classmethod
    def ultraview_author_connector(cls, color=None):
        """Outline arrow used only when Connector is constructed on a test rail."""
        c = color or GRAY

        def draw(p):
            p.drawLine(QPointF(3.6, 10.0), QPointF(14.4, 10.0))
            head = QPainterPath()
            head.moveTo(16.4, 10.0)
            head.lineTo(12.2, 7.0)
            head.lineTo(12.2, 13.0)
            head.closeSubpath()
            p.drawPath(head)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_display(cls, color=None):
        """Eye with metadata lines for title/source display options."""
        c = color or GRAY

        def draw(p):
            eye = QPainterPath()
            eye.moveTo(2.8, 7.3)
            eye.cubicTo(5.8, 3.4, 11.4, 3.4, 14.4, 7.3)
            eye.cubicTo(11.4, 11.2, 5.8, 11.2, 2.8, 7.3)
            eye.closeSubpath()
            p.drawPath(eye)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(8.6, 7.3), 1.55, 1.55)
            p.setPen(_pen(c, 1.55))
            p.drawLine(QPointF(4.0, 14.0), QPointF(16.0, 14.0))
            p.drawLine(QPointF(4.0, 17.0), QPointF(12.2, 17.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_presentation(cls, color=None):
        """Projection screen with play mark for presentation mode."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(3.0, 3.0, 14.0, 10.5), 1.6, 1.6)
            p.drawLine(QPointF(10.0, 13.5), QPointF(10.0, 16.8))
            p.drawLine(QPointF(6.8, 16.8), QPointF(13.2, 16.8))
            play = QPainterPath()
            play.moveTo(8.4, 6.4)
            play.lineTo(12.2, 8.25)
            play.lineTo(8.4, 10.1)
            play.closeSubpath()
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawPath(play)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_overview(cls, color=None):
        """Nine compact cells for whole-board overview/minimap navigation."""
        c = color or GRAY

        def draw(p):
            for x in (3.0, 8.3, 13.6):
                for y in (3.0, 8.3, 13.6):
                    p.drawRoundedRect(QRectF(x, y, 3.4, 3.4), 0.65, 0.65)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_fit(cls, color=None):
        """Inward brackets for fitting the complete board into the viewport."""
        c = color or GRAY

        def draw(p):
            p.drawLine(QPointF(3.0, 7.4), QPointF(3.0, 3.0))
            p.drawLine(QPointF(3.0, 3.0), QPointF(7.4, 3.0))
            p.drawLine(QPointF(17.0, 7.4), QPointF(17.0, 3.0))
            p.drawLine(QPointF(17.0, 3.0), QPointF(12.6, 3.0))
            p.drawLine(QPointF(3.0, 12.6), QPointF(3.0, 17.0))
            p.drawLine(QPointF(3.0, 17.0), QPointF(7.4, 17.0))
            p.drawLine(QPointF(17.0, 12.6), QPointF(17.0, 17.0))
            p.drawLine(QPointF(17.0, 17.0), QPointF(12.6, 17.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_fit_to_image(cls, color=None):
        """Card frame collapsing onto an inner preview rectangle."""
        c = color or GRAY

        def draw(p):
            p.drawRect(QRectF(3.0, 3.5, 14.0, 13.0))
            p.drawRect(QRectF(5.5, 6.5, 9.0, 7.0))
            p.drawLine(QPointF(7.5, 10.0), QPointF(12.5, 10.0))
            p.drawLine(QPointF(10.0, 7.5), QPointF(10.0, 12.5))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_reset_zoom(cls, color=None):
        """Return-to-baseline target, used for UltraView's 100% control."""
        c = color or GRAY

        def draw(p):
            p.drawEllipse(QRectF(3.5, 3.5, 13.0, 13.0))
            p.drawLine(QPointF(10.0, 7.0), QPointF(10.0, 13.0))
            p.drawLine(QPointF(7.0, 10.0), QPointF(13.0, 10.0))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(10.0, 10.0), 1.1, 1.1)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_zoom_out(cls, color=None):
        """Magnifier-minus for reducing the board viewport scale."""
        c = color or GRAY

        def draw(p):
            p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
            p.drawLine(QPointF(10.6, 10.6), QPointF(16.8, 16.8))
            p.drawLine(QPointF(5.8, 8.0), QPointF(10.2, 8.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_zoom_in(cls, color=None):
        """Magnifier-plus for increasing the board viewport scale."""
        c = color or GRAY

        def draw(p):
            p.drawEllipse(QRectF(3.0, 3.0, 10.0, 10.0))
            p.drawLine(QPointF(10.6, 10.6), QPointF(16.8, 16.8))
            p.drawLine(QPointF(5.8, 8.0), QPointF(10.2, 8.0))
            p.drawLine(QPointF(8.0, 5.8), QPointF(8.0, 10.2))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_help(cls, color=None):
        """Question-mark-in-circle help affordance, drawn without a font glyph."""
        c = color or GRAY

        def draw(p):
            p.setPen(_pen(c, 1.55))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
            question = QPainterPath()
            question.moveTo(7.2, 7.3)
            question.cubicTo(7.3, 5.2, 10.4, 4.9, 11.8, 6.5)
            question.cubicTo(13.1, 8.2, 11.7, 9.5, 10.2, 10.4)
            question.cubicTo(9.2, 11.0, 9.1, 11.8, 9.1, 12.4)
            p.drawPath(question)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(9.1, 14.6), 0.9, 0.9)

        return _ultraview_icon(draw)

    @classmethod
    def ultraview_add(cls, color=None):
        """Plain plus for creating a Board; not the add-file document glyph."""
        c = color or GRAY

        def draw(p):
            p.drawLine(QPointF(10.0, 3.5), QPointF(10.0, 16.5))
            p.drawLine(QPointF(3.5, 10.0), QPointF(16.5, 10.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_open_source(cls, color=None):
        """Open the source View from a selected UltraView card."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(3.0, 5.5, 11.0, 11.0), 1.6, 1.6)
            p.drawLine(QPointF(10.0, 10.0), QPointF(17.0, 3.0))
            p.drawLine(QPointF(12.4, 3.0), QPointF(17.0, 3.0))
            p.drawLine(QPointF(17.0, 3.0), QPointF(17.0, 7.6))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_remove_from_board(cls, color=None):
        """Minus-from-board: drop this card from the current Board only."""
        c = color or GRAY

        def draw(p):
            p.drawRoundedRect(QRectF(3.0, 5.5, 11.0, 11.0), 1.6, 1.6)
            p.drawLine(QPointF(10.2, 10.0), QPointF(17.0, 10.0))

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_sync(cls, color=None):
        """Recapture the live source View into this UltraView card."""
        c = color or BLUE

        def draw(p):
            p.drawArc(QRectF(3.0, 3.0, 14.0, 14.0), 50 * 16, 260 * 16)
            p.setBrush(QBrush(c))
            p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(14.2, 2.2)
            path.lineTo(17.4, 5.6)
            path.lineTo(12.0, 6.2)
            path.closeSubpath()
            p.drawPath(path)

        return _ultraview_line_icon(draw, c)

    @classmethod
    def ultraview_move_to_tray(cls, color=None):
        """Compact card-to-tray action for the card context island."""
        return cls.ultraview_unplaced(color)

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
    def menu(cls, color=None):
        def draw(p):
            for y in (6, 10, 14):
                p.drawPoint(QPointF(10, y))
        icon = _line_icon(draw, color or GRAY)
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

    @classmethod
    def annotate(cls, color=None):
        """Label + leader-line annotation icon.

        Geometry in 0..20 viewport:
          data-point circle at (3, 15) r=1.8
          leader line from (4.5, 13.5) to (10, 7.5)
          label rect (10, 3) × 8×8
          two text-lines inside the label rect
        """
        c = color or GRAY
        def draw(p):
            p.setPen(_pen(c, 1.45))
            p.setBrush(Qt.NoBrush)
            # data-point circle
            p.drawEllipse(QPointF(3, 15), 1.8, 1.8)
            # leader line
            p.drawLine(QPointF(4.5, 13.5), QPointF(10, 7.5))
            # label rectangle
            p.drawRoundedRect(QRectF(10, 3, 8, 8), 1.2, 1.2)
            # two short text lines inside
            p.drawLine(QPointF(12, 6), QPointF(16, 6))
            p.drawLine(QPointF(12, 8.5), QPointF(15, 8.5))
        return _line_icon(draw, c)

    @classmethod
    def cloud_download(cls):
        """Cloud outline + down arrow — 'get the latest version'."""
        def draw(p):
            cloud = QPainterPath()
            cloud.moveTo(6.0, 13.0)
            cloud.cubicTo(2.6, 13.0, 2.6, 8.6, 6.3, 8.4)
            cloud.cubicTo(6.7, 4.7, 12.4, 4.4, 13.2, 8.1)
            cloud.cubicTo(16.6, 7.9, 16.9, 12.7, 13.8, 13.0)
            cloud.lineTo(6.0, 13.0)
            p.drawPath(cloud)
            p.drawLine(QPointF(10.0, 9.5), QPointF(10.0, 16.8))
            p.drawLine(QPointF(7.4, 14.0), QPointF(10.0, 16.8))
            p.drawLine(QPointF(12.6, 14.0), QPointF(10.0, 16.8))
        return _line_icon(draw, GRAY)

    @classmethod
    def panel_left(cls):
        """Sidebar-left icon: outer rect + left panel divider + left fill."""
        with _painting() as (pix, p):
            pen = _pen(QColor("#64748b"), 1.4)
            p.setPen(pen)
            # outer rect
            p.drawRoundedRect(QRectF(2, 2, 16, 16), 2, 2)
            # vertical divider at x=7
            p.drawLine(QPointF(7, 2), QPointF(7, 18))
            # left panel fill
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(100, 116, 139, 60)))
            p.drawRect(QRectF(2, 2, 5, 16))
        return QIcon(pix)

    @classmethod
    def panel_right(cls):
        """Sidebar-right icon: outer rect + right panel divider + right fill."""
        with _painting() as (pix, p):
            pen = _pen(QColor("#64748b"), 1.4)
            p.setPen(pen)
            p.drawRoundedRect(QRectF(2, 2, 16, 16), 2, 2)
            p.drawLine(QPointF(13, 2), QPointF(13, 18))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(100, 116, 139, 60)))
            p.drawRect(QRectF(13, 2, 5, 16))
        return QIcon(pix)

    @classmethod
    def chevron_down(cls, color=None):
        """Two-stroke V opening downwards — 'expand this popup'.

        Drawn rather than typed: the ``"⌄"`` glyph rasterizes unevenly across
        the fallback fonts Qt picks for it. The stroke width matches the other
        line icons so the chevron sits at the same visual weight as the rest of
        the icon set. Callers control the rendered size via ``setIconSize``;
        the default ``#7b8798`` is the resting arrow color of the batch signal
        picker, with ``#354254`` passed in on hover.
        """
        def draw(p):
            p.drawLine(QPointF(5, 8), QPointF(10, 13))
            p.drawLine(QPointF(10, 13), QPointF(15, 8))
        return _line_icon(draw, color or CHEVRON)

    @classmethod
    def chevron_right(cls, color=None):
        """:meth:`chevron_down` rotated -90° — 'this section is collapsed'.

        Same stroke and same bounding box as its sibling so a disclosure
        control can swap between the two without the glyph shifting weight.
        """
        def draw(p):
            p.drawLine(QPointF(8, 5), QPointF(13, 10))
            p.drawLine(QPointF(13, 10), QPointF(8, 15))
        return _line_icon(draw, color or CHEVRON)

    @classmethod
    def chevron_up(cls, color=None):
        """Mirror of :meth:`chevron_down` — 'collapse this popup'."""

        def draw(p):
            p.drawLine(QPointF(5, 12), QPointF(10, 7))
            p.drawLine(QPointF(10, 7), QPointF(15, 12))
        return _line_icon(draw, color or CHEVRON)

    @classmethod
    def save_disk(cls):
        """Floppy-disk 'save' glyph (distinct from the export tray-arrow)."""
        def draw(p):
            body = QPainterPath()
            body.moveTo(4, 4)
            body.lineTo(13.5, 4)
            body.lineTo(16, 6.5)
            body.lineTo(16, 16)
            body.lineTo(4, 16)
            body.closeSubpath()
            p.drawPath(body)
            # top shutter slot
            p.drawRect(QRectF(7.5, 4, 4, 3))
            # bottom label panel
            p.drawRect(QRectF(6.5, 10.5, 7, 5.5))
        return _line_icon(draw, GRAY)


# =============================================================================
# QSS subcontrol-arrow icon cache (scheme B: qtawesome -> PNG -> QSS image:url)
# =============================================================================
#
# QSpinBox / QDoubleSpinBox / QComboBox subcontrols (::up-button /
# ::down-button / ::drop-down) render no platform-default glyph once any
# QSS rule customizes them. We supply our own arrows by rendering
# mdi6.menu-up / mdi6.menu-down via qtawesome to per-state PNG files,
# then referencing them from style.qss via ``image: url("...")``.
#
# The cache lives in ~/.mf4-analyzer-cache/icons/ so it persists across
# runs. Filenames embed an icon-name + color + pixel-size + qtawesome-
# version hash so a qtawesome upgrade or palette change forces
# regeneration without manual cleanup.
#
# Color palette (matches Precision Light):
#   rest      #475569   (slate-600 — visible at rest, low contrast)
#   hover     #1769e0   (interaction blue — primary accent)
#   press     #1349a8   (interaction blue darkened)
#   disabled  #cbd5e1   (slate-300 — greyed out)
#
# The QSS template in style.qss uses placeholders like
# ``{{ICON_SPIN_UP_REST}}`` that ``ensure_icon_cache`` substitutes at
# stylesheet-load time (see mf4_analyzer/ui_kit/stylesheet.py).

# Each entry: (placeholder_key, qtawesome_icon_name, color_hex)
_ARROW_SPECS = (
    # Spin box up arrow
    ("ICON_SPIN_UP_REST",     "mdi6.menu-up",   "#475569"),
    ("ICON_SPIN_UP_HOVER",    "mdi6.menu-up",   "#1769e0"),
    ("ICON_SPIN_UP_PRESS",    "mdi6.menu-up",   "#1349a8"),
    ("ICON_SPIN_UP_DISABLED", "mdi6.menu-up",   "#cbd5e1"),
    # Spin box down arrow
    ("ICON_SPIN_DOWN_REST",     "mdi6.menu-down", "#475569"),
    ("ICON_SPIN_DOWN_HOVER",    "mdi6.menu-down", "#1769e0"),
    ("ICON_SPIN_DOWN_PRESS",    "mdi6.menu-down", "#1349a8"),
    ("ICON_SPIN_DOWN_DISABLED", "mdi6.menu-down", "#cbd5e1"),
    # Combo drop-down arrow (separate filenames so QSS can wire them
    # independently if we ever want a different combo glyph; today they
    # share mdi6.menu-down so the cached PNGs are byte-identical to spin
    # down's PNGs but live under their own filename hash).
    ("ICON_COMBO_DOWN_REST",     "mdi6.menu-down", "#475569"),
    ("ICON_COMBO_DOWN_HOVER",    "mdi6.menu-down", "#1769e0"),
    ("ICON_COMBO_DOWN_PRESS",    "mdi6.menu-down", "#1349a8"),
    ("ICON_COMBO_DOWN_DISABLED", "mdi6.menu-down", "#cbd5e1"),
    # Checkbox indicator glyphs
    ("ICON_CHECKBOX_CHECKED",          "mdi6.check", "#ffffff"),
    ("ICON_CHECKBOX_CHECKED_DISABLED", "mdi6.check", "#94a3b8"),
)

# Logical (CSS pixel) icon size. The actual rendered PNG is scaled up by
# devicePixelRatio so the QSS ``image:`` rule still resolves to a crisp
# 12-logical-px glyph on HiDPI screens.
_LOGICAL_ARROW_PX = 12


def _icon_cache_dir():
    """Return (and create if missing) the per-user icon cache directory."""
    from pathlib import Path
    out = Path.home() / ".mf4-analyzer-cache" / "icons"
    out.mkdir(parents=True, exist_ok=True)
    return out


def ensure_icon_cache():
    """Generate per-state subcontrol arrow PNGs and return placeholder map.

    Returns a dict mapping QSS placeholder keys (e.g. ``"ICON_SPIN_UP_REST"``)
    to absolute filesystem paths of the corresponding cached PNG files. The
    paths are forward-slash normalized; QSS ``image: url("...")`` on Windows
    rejects backslashes silently, so callers feeding these into a stylesheet
    can use the path verbatim.

    Behavior:

    * Cache directory is ``~/.mf4-analyzer-cache/icons/``. PNG filenames
      embed (icon_name, color_hex, pixel_size, qtawesome.__version__) so a
      qtawesome upgrade or palette change automatically re-generates without
      manual invalidation.
    * Existing non-empty PNGs are reused (skip path).
    * Renders at ``devicePixelRatio * _LOGICAL_ARROW_PX`` and calls
      ``setDevicePixelRatio`` on the saved pixmap so HiDPI screens get crisp
      output without QSS having to know about scale factors.
    * Logs one debug line after a regeneration pass with timing and count.

    **Ordering constraint**: must be called AFTER ``QApplication`` has been
    constructed. qtawesome lazy-loads its icon font and emits
    ``UserWarning: You need to have a running QApplication`` if invoked
    pre-app; the rendered pixmap also depends on the screen's
    devicePixelRatio which is only known once QApplication exists.
    """
    import time
    from pathlib import Path

    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        # Fail loud — wiring this before QApplication is a programmer error.
        raise RuntimeError(
            "ensure_icon_cache() requires an existing QApplication; call "
            "after QApplication(sys.argv).",
        )

    # Lazy-import qtawesome so module-level imports of icons.py do not pay
    # the qtawesome font-load cost when only the QPainter Icons class is
    # used (the existing usage path).
    import qtawesome as qta

    try:
        qta_version = qta.__version__
    except AttributeError:
        # Defensive: fall back to a stable string so cache filenames are
        # still deterministic even if qtawesome stops exposing __version__.
        qta_version = "unknown"

    ratio = app.devicePixelRatio() or 1.0
    if ratio < 1.0:
        ratio = 1.0
    size_px = int(round(_LOGICAL_ARROW_PX * ratio))

    out_dir = _icon_cache_dir()
    paths = {}
    generated = 0
    t0 = time.perf_counter()

    for placeholder, icon_name, color in _ARROW_SPECS:
        color_slug = color.lstrip("#").lower()
        # Cache key uses qtawesome version so an upgrade invalidates
        # automatically. Including the icon_name lets future palette
        # variants (e.g. mdi6.chevron-up) co-exist in the same dir.
        filename = (
            f"{icon_name.replace('.', '_')}_"
            f"{color_slug}_{size_px}_qta{qta_version}.png"
        )
        out_path = out_dir / filename

        if not (out_path.exists() and out_path.stat().st_size > 0):
            pix = qta.icon(icon_name, color=color).pixmap(size_px, size_px)
            pix.setDevicePixelRatio(ratio)
            pix.save(str(out_path), "PNG")
            generated += 1

        # Forward-slash normalize for QSS image:url consumption on Windows.
        paths[placeholder] = str(out_path).replace("\\", "/")

    if generated:
        elapsed = time.perf_counter() - t0
        # Use stderr-style print rather than logging so it shows up in the
        # console even before any logging.basicConfig has run.
        print(
            f"[mf4_analyzer.ui_kit.icons] generated {generated}/"
            f"{len(_ARROW_SPECS)} subcontrol-arrow PNGs in {elapsed:.2f}s "
            f"(cache: {out_dir})",
        )

    return paths


def render_qss_template(template_text, icon_paths):
    """Substitute ``{{KEY}}`` placeholders in a QSS string with icon paths.

    Parameters
    ----------
    template_text : str
        Raw QSS source that may contain ``{{ICON_*}}`` placeholders.
    icon_paths : dict[str, str]
        Mapping from placeholder key (without braces) to absolute icon
        path. Use the return value of :func:`ensure_icon_cache`.

    Returns
    -------
    str
        Stylesheet with all known placeholders replaced. Unknown
        placeholders are left untouched (Qt will silently drop ``image:``
        rules pointing to nonexistent files; this is preferable to a hard
        failure when adding new placeholders incrementally).
    """
    out = template_text
    for key, path in icon_paths.items():
        out = out.replace("{{" + key + "}}", path)
    return out
