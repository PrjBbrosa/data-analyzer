"""Request-anchored scalar heatmap windows: no GUI or matrix history."""
import copy
import math

import pytest

from mf4_analyzer.heatmap_color_policy import (
    normalize_heatmap_color_basis,
    resolve_heatmap_color_policy,
)


def resolve(**changes):
    args = dict(params={"z_auto": False, "z_floor": -80.0, "z_ceiling": 0.0},
                source=("f1", "signal"), amplitude_mode="amplitude_db",
                reference=1.0, unit="N", quantity="force")
    args.update(changes)
    return resolve_heatmap_color_policy(**args)


@pytest.mark.parametrize("reference,delta", [(10**1.5, -30), (10**-1.5, 30), (1e6, -120)])
def test_reference_shift_is_anchored_and_reversible(reference, delta):
    anchor = resolve().basis
    snapshot = copy.deepcopy(anchor)
    for _ in range(20):
        result = resolve(basis=anchor, reference=reference)
        assert (result.z_floor, result.z_ceiling) == pytest.approx((-80 + delta, delta))
        assert result.basis == anchor
    original = resolve(basis=result.basis, reference=1)
    assert (original.z_floor, original.z_ceiling) == (-80, 0)
    assert anchor == snapshot


def test_reference_ratio_cannot_overflow_before_logarithm():
    anchor = resolve(reference=1e300).basis
    result = resolve(basis=anchor, reference=1e-300)
    assert (result.z_floor, result.z_ceiling) == pytest.approx((11920, 12000))


@pytest.mark.parametrize("reference", [False, True, 0, -1, math.nan, math.inf, "1", [], None])
def test_invalid_reference_rejected(reference):
    with pytest.raises(ValueError, match="reference"):
        resolve(reference=reference)


@pytest.mark.parametrize("lo,hi", [(0, 0), (1, 0), (math.nan, 0), (0, math.inf), (False, 1), ([], 1)])
def test_invalid_manual_window_rejected(lo, hi):
    with pytest.raises(ValueError, match="range"):
        resolve(params={"z_auto": False, "z_floor": lo, "z_ceiling": hi})


def test_shift_that_collapses_double_precision_is_rejected():
    with pytest.raises(ValueError, match="range"):
        resolve(params={"z_auto": False, "z_floor": 0., "z_ceiling": 1e-100},
                basis=resolve().basis, reference=1e300)


@pytest.mark.parametrize("changes", [dict(source=("f2", "signal")), dict(unit="Pa"),
                                       dict(quantity="pressure"), dict(appearance={"z_auto": False, "z_min": -80, "z_max": 0})])
def test_context_change_reanchors_without_cross_source_shift(changes):
    result = resolve(basis=resolve().basis, reference=10, **changes)
    assert (result.z_floor, result.z_ceiling) == (-80, 0)
    assert result.basis["reference"] == 10


def test_reference_provenance_label_does_not_reanchor():
    result = resolve(basis=resolve(reference_source="metadata").basis,
                     reference=10, reference_source="catalog")
    assert (result.z_floor, result.z_ceiling) == (-100, -20)


@pytest.mark.parametrize("changes", [dict(source=None), dict(source=("", "signal")),
                                       dict(reference_source="fallback"),
                                       dict(amplitude_mode="linear"),
                                       dict(params={"z_auto": True, "z_floor": -80, "z_ceiling": 0})])
def test_nonanchorable_policy_clears_basis(changes):
    result = resolve(basis=resolve().basis, **changes)
    assert result.basis is None
    assert (result.z_floor, result.z_ceiling) == (-80, 0)


def test_only_valid_z_appearance_overrides_default():
    for appearance in ({"title": "Example"}, {"z_auto": False, "z_min": 10, "z_max": 0}):
        assert resolve(appearance=appearance).policy_owner == "view_default"
    result = resolve(appearance={"z_auto": False, "z_min": -20, "z_max": 10})
    assert result.policy_owner == "pane_override"
    assert (result.z_floor, result.z_ceiling) == (-20, 10)
    assert resolve(appearance={"z_auto": True}).z_auto is True


def test_basis_normalization_isolated_and_rejects_bad_fields():
    basis = resolve().basis
    normalized = normalize_heatmap_color_basis(basis)
    normalized["source"][0] = "other"
    assert basis["source"] == ["f1", "signal"]
    for key, value in (("version", True), ("source", ["f1"]), ("reference", False),
                       ("policy_owner", "canvas"), ("amplitude_mode", "linear"), ("unit", [])):
        assert normalize_heatmap_color_basis(dict(basis, **{key: value})) is None
