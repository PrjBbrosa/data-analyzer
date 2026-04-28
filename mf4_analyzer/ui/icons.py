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
# stylesheet-load time (see mf4_analyzer/app.py).

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
            f"[mf4_analyzer.ui.icons] generated {generated}/"
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
