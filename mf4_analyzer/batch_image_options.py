"""Lightweight, GUI-free batch image option contract."""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral


SUPPORTED_IMAGE_FORMATS = frozenset({"png", "svg", "pdf"})
MIN_IMAGE_DIMENSION_PX = 320
MAX_IMAGE_DIMENSION_PX = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MIN_IMAGE_DPI = 36
MAX_IMAGE_DPI = 1_200


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


__all__ = [
    "BatchRenderOptions",
    "MAX_IMAGE_DIMENSION_PX",
    "MAX_IMAGE_DPI",
    "MAX_IMAGE_PIXELS",
    "MIN_IMAGE_DIMENSION_PX",
    "MIN_IMAGE_DPI",
    "SUPPORTED_IMAGE_FORMATS",
]
