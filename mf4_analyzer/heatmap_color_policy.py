"""GUI-neutral heatmap color intent and deterministic dB projection.

The saved window belongs to its request reference, never to the previously
painted canvas. This module neither inspects matrices nor mutates its inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Any, Mapping


class HeatmapColorPolicyError(ValueError):
    """Invalid user/persisted scalar policy; render errors are not this type."""


def _finite_scalar(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _source(value: Any) -> list[str] | None:
    if (not isinstance(value, (tuple, list)) or len(value) != 2
            or not all(isinstance(part, str) and part for part in value)):
        return None
    return list(value)


def normalize_heatmap_color_basis(value: Any) -> dict[str, Any] | None:
    """Validate and copy persisted intent; diagnostics belong to deserialization."""
    if not isinstance(value, Mapping):
        return None
    reference = _finite_scalar(value.get("reference"))
    source = _source(value.get("source"))
    if (type(value.get("version")) is not int or value["version"] != 1
            or value.get("policy_owner") not in ("view_default", "pane_override")
            or value.get("amplitude_mode") != "amplitude_db"
            or source is None or reference is None or reference <= 0
            or not isinstance(value.get("unit"), str)
            or not isinstance(value.get("quantity"), str)):
        return None
    return {
        "version": 1, "policy_owner": value["policy_owner"], "source": source,
        "amplitude_mode": "amplitude_db", "reference": reference,
        "unit": value["unit"], "quantity": value["quantity"],
    }


def _range(lo: Any, hi: Any) -> tuple[float, float]:
    low, high = _finite_scalar(lo), _finite_scalar(hi)
    if low is None or high is None or low >= high:
        raise HeatmapColorPolicyError("heatmap color range must be finite scalars with low < high")
    return low, high


@dataclass(frozen=True)
class HeatmapColorPolicy:
    z_auto: bool
    z_floor: float
    z_ceiling: float
    basis: dict[str, Any] | None
    policy_owner: str


def resolve_heatmap_color_policy(
    *, params: Mapping[str, Any], appearance: Mapping[str, Any] | None = None,
    basis: Mapping[str, Any] | None = None, source: Any,
    amplitude_mode: str, reference: Any, unit: str = "", quantity: str = "",
    reference_source: str = "",
) -> HeatmapColorPolicy:
    """Return effective scalar levels and a proposed anchor for successful paint.

    Callers supply section defaults in ``params``. ``appearance`` is the pane's
    heatmap role, and only a valid explicit Z policy overrides the View request.
    Auto levels remain the renderer's responsibility. Missing source or a
    resolver fallback cannot establish physical history; their numeric request
    stays unchanged. Invalid manual requests/references raise ``ValueError`` so
    the owning transaction can retain its last valid presentation explicitly.
    """
    z_auto = bool(params.get("z_auto", True))
    lo, hi = params["z_floor"], params["z_ceiling"]
    owner = "view_default"
    if isinstance(appearance, Mapping) and type(appearance.get("z_auto")) is bool:
        if appearance["z_auto"]:
            z_auto, owner = True, "pane_override"
        else:
            try:
                candidate = _range(appearance.get("z_min"), appearance.get("z_max"))
            except ValueError:
                pass  # Invalid partial overrides follow the View's valid policy.
            else:
                z_auto, owner = False, "pane_override"
                lo, hi = candidate
    lo, hi = _range(lo, hi)
    if z_auto or amplitude_mode != "amplitude_db":
        return HeatmapColorPolicy(z_auto, lo, hi, None, owner)
    identity = _source(source)
    if identity is None or reference_source == "fallback":
        return HeatmapColorPolicy(False, lo, hi, None, owner)
    current = _finite_scalar(reference)
    if current is None or current <= 0:
        raise HeatmapColorPolicyError("heatmap dB reference must be a positive finite scalar")
    if not isinstance(unit, str) or not isinstance(quantity, str):
        raise HeatmapColorPolicyError("heatmap physical unit and quantity must be canonical strings")
    context = dict(version=1, policy_owner=owner, source=identity,
                   amplitude_mode=amplitude_mode, unit=unit, quantity=quantity)
    anchor = normalize_heatmap_color_basis(basis)
    if anchor is None or any(anchor[key] != value for key, value in context.items()):
        anchor = dict(context, reference=current)
    delta = 20.0 * (math.log10(anchor["reference"]) - math.log10(current))
    lo, hi = _range(lo + delta, hi + delta)
    return HeatmapColorPolicy(False, lo, hi, anchor, owner)
