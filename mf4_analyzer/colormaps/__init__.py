"""UI-independent catalog of shipping heatmap colormaps."""
from .registry import (
    ColormapResourceError,
    ColormapSpec,
    DEFAULT_HEATMAP_CMAP,
    FALLBACK_HEATMAP_CMAP,
    SUPPORTED_HEATMAP_COLORMAPS,
    UnknownColormapError,
    get_colormap_spec,
    list_colormap_specs,
    load_rgb_lut,
    validate_colormap_resources,
)

__all__ = [
    "ColormapResourceError", "ColormapSpec", "DEFAULT_HEATMAP_CMAP",
    "FALLBACK_HEATMAP_CMAP", "SUPPORTED_HEATMAP_COLORMAPS", "UnknownColormapError",
    "get_colormap_spec", "list_colormap_specs", "load_rgb_lut", "validate_colormap_resources",
]
