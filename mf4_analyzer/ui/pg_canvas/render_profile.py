"""Compatibility exports for UI-neutral render-profile helpers."""
from mf4_analyzer.render_profile import (  # noqa: F401
    DENSE_DISCRETE_BUCKET_BUDGET,
    DENSE_DISCRETE_INTERACTIVE_BUCKET_BUDGET,
    RenderProfile,
    bucket_width_for,
    classify_render_profile,
    source_revision_for,
)


__all__ = [
    "DENSE_DISCRETE_BUCKET_BUDGET",
    "DENSE_DISCRETE_INTERACTIVE_BUCKET_BUDGET",
    "RenderProfile",
    "bucket_width_for",
    "classify_render_profile",
    "source_revision_for",
]
