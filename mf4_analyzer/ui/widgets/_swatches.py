"""Channel colour swatch rendering shared by the channel tree and its consumers.

``_swatch_pixmap`` resolves ``icon_device_pixel_ratio`` through *this* module's
globals, so tests and dev scripts that need a synthetic screen ratio must patch
``mf4_analyzer.ui.widgets._swatches.icon_device_pixel_ratio``.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

from ...ui_kit.icons import icon_device_pixel_ratio


def _fmt_rate(fs):
    """Format a sample rate in Hz or kHz for display (≥1000 Hz → kHz).

    The branch tests the value *as the Hz branch would print it*, not the raw
    float.  ``fs`` comes from ``1 / median(diff(time))``, so a nominal 1 kHz
    axis lands either side of 1000.0 depending on the sample count: two 1 ms
    groups of one WWT file measured 1000.000000000000796 and
    999.999999999999091, and a bare ``fs >= 1000`` labelled the same rate
    "1.0 kHz" on one and "1000 Hz" on the other -- reading as two different
    rasters.  Rounding first also keeps the branch honest for a genuine
    999.6 Hz, which the Hz branch would render as the four-digit "1000 Hz".
    """
    if round(fs) >= 1000:
        return f"{fs / 1000:.1f} kHz"
    return f"{fs:.0f} Hz"


def _swatch_pixmap(color, size=11, ratio=None):
    """Render the channel color swatch at ``ratio x`` physical resolution and
    tag it with that devicePixelRatio so HiDPI (Retina) screens paint it crisp
    rather than upscaling a 1x bitmap (which produced the jagged edges).

    ``size`` is the logical icon box; the dot fills ``size - 4`` so it reads as
    a compact colour chip aligned with the row text rather than a heavy block.
    """
    if ratio is None:
        ratio = icon_device_pixel_ratio()
    pix = QPixmap(round(size * ratio), round(size * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(QPen(QColor(color), 1))
    p.setBrush(QBrush(QColor(color)))
    # Coordinates stay in LOGICAL units; the painter is scaled by the pixmap's
    # devicePixelRatio automatically.
    p.drawRoundedRect(2, 2, size - 4, size - 4, 3, 3)
    p.end()
    return pix


def _swatch_icon(color, size=11):
    return QIcon(_swatch_pixmap(color, size))