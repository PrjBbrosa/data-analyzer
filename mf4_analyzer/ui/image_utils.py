"""Shared GUI-thread image helpers.

Callers must already be on the Qt GUI thread. This module only normalizes
device-pixel-ratio and pixel format; size rejection and memory budgets belong
to the owner that stores the image (PreviewStore for UltraView).
"""
from __future__ import annotations

from PyQt5.QtGui import QImage, QPixmap

_STORE_IMAGE_FORMAT = QImage.Format_ARGB32_Premultiplied


def pixmap_as_device_pixel_image(pixmap) -> QImage | None:
    """Return a DPR=1.0 raw-pixel ``QImage``, or ``None`` if *pixmap* is missing.

    Accepts ``QPixmap`` or ``QImage``. Raw ``width()`` / ``height()`` are
    preserved; only the device-pixel-ratio metadata is forced to 1.0 and the
    buffer is converted to a predictable 32-bit format. Small sizes are not
    rejected here.
    """
    if pixmap is None:
        return None
    if isinstance(pixmap, QPixmap):
        if pixmap.isNull():
            return None
        image = pixmap.toImage()
    elif isinstance(pixmap, QImage):
        if pixmap.isNull():
            return None
        image = pixmap
    else:
        return None
    if image.isNull():
        return None
    converted = image.convertToFormat(_STORE_IMAGE_FORMAT)
    if converted.isNull():
        return None
    converted.setDevicePixelRatio(1.0)
    return converted


def pixmap_as_device_pixels(pixmap) -> QPixmap | None:
    """Compatibility wrapper so existing ``QPixmap`` call sites stay ``QPixmap``."""
    image = pixmap_as_device_pixel_image(pixmap)
    if image is None:
        return None
    out = QPixmap.fromImage(image)
    if out.isNull():
        return None
    out.setDevicePixelRatio(1.0)
    return out
