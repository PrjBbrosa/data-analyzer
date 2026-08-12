"""GUI-free contract for the batch report's tick density and text size.

These three values ride in the recipe ``params`` next to ``x_min``/``x_max``
rather than in :class:`~mf4_analyzer.batch_image_options.BatchRenderOptions`:
they are presentation choices the user makes beside the axis ranges, they
round-trip through the same preset JSON, and ``params`` already reaches
``render_batch_image`` untouched.

Parsing is deliberately forgiving — a preset written by a newer UI, or a
hand-edited recipe, must never abort a run over a text-size number. Values
outside the supported span are clamped to it; non-numeric or non-finite values
fall back to the default.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from numbers import Real


# Same pair as the interactive 「密」preset; `ui.chart_defaults` imports these
# rather than declaring a second (20, 15). Saved recipes that already store
# an explicit tick_density keep that value.
DEFAULT_TICK_DENSITY_X = 20
DEFAULT_TICK_DENSITY_Y = 15
DEFAULT_FONT_SCALE = 1.0

MIN_TICK_DENSITY_X = 3
MAX_TICK_DENSITY_X = 40
MIN_TICK_DENSITY_Y = 3
MAX_TICK_DENSITY_Y = 20
MIN_FONT_SCALE = 0.6
MAX_FONT_SCALE = 2.5

#: ``(label, x, y)`` triples shared by the batch panel's density presets.
TICK_DENSITY_PRESETS = (
    ("疏", 8, 6),
    ("标准", DEFAULT_TICK_DENSITY_X, DEFAULT_TICK_DENSITY_Y),
    ("密", 24, 16),
)


def _clamp_int(value, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Real):
        return default
    number = float(value)
    if not math.isfinite(number):
        return default
    return int(max(low, min(high, round(number))))


def _clamp_float(value, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        return default
    number = float(value)
    if not math.isfinite(number):
        return default
    return float(max(low, min(high, number)))


@dataclass(frozen=True)
class RenderStyle:
    """Resolved tick density and text scale for one rendered report page."""

    tick_density_x: int = DEFAULT_TICK_DENSITY_X
    tick_density_y: int = DEFAULT_TICK_DENSITY_Y
    font_scale: float = DEFAULT_FONT_SCALE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tick_density_x",
            _clamp_int(
                self.tick_density_x,
                MIN_TICK_DENSITY_X,
                MAX_TICK_DENSITY_X,
                DEFAULT_TICK_DENSITY_X,
            ),
        )
        object.__setattr__(
            self,
            "tick_density_y",
            _clamp_int(
                self.tick_density_y,
                MIN_TICK_DENSITY_Y,
                MAX_TICK_DENSITY_Y,
                DEFAULT_TICK_DENSITY_Y,
            ),
        )
        object.__setattr__(
            self,
            "font_scale",
            _clamp_float(
                self.font_scale, MIN_FONT_SCALE, MAX_FONT_SCALE, DEFAULT_FONT_SCALE
            ),
        )

    def as_params(self) -> dict:
        return {
            "tick_density_x": int(self.tick_density_x),
            "tick_density_y": int(self.tick_density_y),
            "font_scale": float(self.font_scale),
        }

    @property
    def is_default(self) -> bool:
        return self == RenderStyle()


def render_style_from_params(params: Mapping | None) -> RenderStyle:
    """Resolve the render style a recipe asks for, defaults filled in."""
    values = dict(params or {})
    return RenderStyle(
        tick_density_x=values.get("tick_density_x", DEFAULT_TICK_DENSITY_X),
        tick_density_y=values.get("tick_density_y", DEFAULT_TICK_DENSITY_Y),
        font_scale=values.get("font_scale", DEFAULT_FONT_SCALE),
    )


__all__ = [
    "DEFAULT_FONT_SCALE",
    "DEFAULT_TICK_DENSITY_X",
    "DEFAULT_TICK_DENSITY_Y",
    "MAX_FONT_SCALE",
    "MAX_TICK_DENSITY_X",
    "MAX_TICK_DENSITY_Y",
    "MIN_FONT_SCALE",
    "MIN_TICK_DENSITY_X",
    "MIN_TICK_DENSITY_Y",
    "TICK_DENSITY_PRESETS",
    "RenderStyle",
    "render_style_from_params",
]
