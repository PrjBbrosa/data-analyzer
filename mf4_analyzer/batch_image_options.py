"""Lightweight, GUI-free batch image option contract."""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real


SUPPORTED_IMAGE_FORMATS = frozenset({"png", "svg", "pdf"})
SUPPORTED_IMAGE_BACKGROUNDS = frozenset({"white", "transparent", "dark"})
MIN_IMAGE_DIMENSION_PX = 320
MAX_IMAGE_DIMENSION_PX = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MIN_IMAGE_DPI = 36
MAX_IMAGE_DPI = 1_200
MIN_IMAGE_LINE_WIDTH = 0.5
MAX_IMAGE_LINE_WIDTH = 4.0


@dataclass(frozen=True)
class BatchRenderOptions:
    """Immutable image geometry and encoding options.

    Pixel geometry and DPI are intentionally independent. Pixel geometry is
    authoritative for raster output; DPI controls raster metadata and the
    physical page size of vector output.
    """

    width_px: int = 1920
    height_px: int = 1080
    dpi: int = 144
    format: str = "png"
    background: str = "white"
    line_width: float = 1.0

    def __post_init__(self) -> None:
        for name in ("width_px", "height_px", "dpi"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise TypeError(f"{name} must be an integer")
            object.__setattr__(self, name, int(value))
        if not MIN_IMAGE_DIMENSION_PX <= self.width_px <= MAX_IMAGE_DIMENSION_PX:
            raise ValueError(
                f"width_px must be between {MIN_IMAGE_DIMENSION_PX} and "
                f"{MAX_IMAGE_DIMENSION_PX}"
            )
        if not MIN_IMAGE_DIMENSION_PX <= self.height_px <= MAX_IMAGE_DIMENSION_PX:
            raise ValueError(
                f"height_px must be between {MIN_IMAGE_DIMENSION_PX} and "
                f"{MAX_IMAGE_DIMENSION_PX}"
            )
        if self.width_px * self.height_px > MAX_IMAGE_PIXELS:
            raise ValueError(
                f"image pixels must not exceed {MAX_IMAGE_PIXELS:,}"
            )
        if not MIN_IMAGE_DPI <= self.dpi <= MAX_IMAGE_DPI:
            raise ValueError(
                f"dpi must be between {MIN_IMAGE_DPI} and {MAX_IMAGE_DPI}"
            )
        image_format = str(self.format).strip().lower()
        if image_format not in SUPPORTED_IMAGE_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_FORMATS))
            raise ValueError(f"format must be one of: {supported}")
        object.__setattr__(self, "format", image_format)

        background = str(self.background).strip().lower()
        if background not in SUPPORTED_IMAGE_BACKGROUNDS:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_BACKGROUNDS))
            raise ValueError(f"background must be one of: {supported}")
        object.__setattr__(self, "background", background)

        line_width = self.line_width
        if isinstance(line_width, bool) or not isinstance(line_width, Real):
            raise TypeError("line_width must be a real number")
        line_width = float(line_width)
        if not math.isfinite(line_width):
            raise ValueError("line_width must be finite")
        if not MIN_IMAGE_LINE_WIDTH <= line_width <= MAX_IMAGE_LINE_WIDTH:
            raise ValueError(
                f"line_width must be between {MIN_IMAGE_LINE_WIDTH:g} and "
                f"{MAX_IMAGE_LINE_WIDTH:g}"
            )
        object.__setattr__(self, "line_width", line_width)


__all__ = [
    "BatchRenderOptions",
    "MAX_IMAGE_DIMENSION_PX",
    "MAX_IMAGE_DPI",
    "MAX_IMAGE_PIXELS",
    "MAX_IMAGE_LINE_WIDTH",
    "MIN_IMAGE_DIMENSION_PX",
    "MIN_IMAGE_DPI",
    "MIN_IMAGE_LINE_WIDTH",
    "SUPPORTED_IMAGE_BACKGROUNDS",
    "SUPPORTED_IMAGE_FORMATS",
]
