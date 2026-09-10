"""Preset baseline snapshots and comparable-value diffs.

Qt-free owner for classification, alias normalization, axis conflicts,
target resolution, and old-project baseline inference. PresetBar and hover
cards consume this; they must not copy a second compare.
"""
from __future__ import annotations

import copy
import logging
import math
from dataclasses import dataclass
from typing import Any, Mapping

from ...db_reference import migrate_legacy_reference_params

logger = logging.getLogger(__name__)

PRESET_KINDS = frozenset({"fft", "fft_time", "order", "frf"})
# Nested baseline write version. Outer AnalysisViewState schema stays 9.
PRESET_BASELINE_VERSION = 2
PRESET_BASELINE_SUPPORTED_VERSIONS = frozenset({1, 2})
PRESET_SLOTS = (1, 2, 3, 4)

PRESET_SOURCE_UNKNOWN_NOTE = "来源版本未知"
PRESET_SOURCE_UPDATED_NOTE = "基准快照，槽位已更新"
PRESET_SOURCE_UNAVAILABLE_NOTE = "原基准已不可用"

_PRESET_MATCH_REL_TOL = 1e-9
_PRESET_MATCH_ABS_TOL = 1e-9

_AXIS_IDS = ("x", "y", "z")
_AXIS_KEYS = {
    "x": ("x_auto", "x_min", "x_max"),
    "y": ("y_auto", "y_min", "y_max"),
    "z": ("z_auto", "z_floor", "z_ceiling"),
}
_AXES_FOR_KIND = {
    "fft": ("x", "y"),
    "fft_time": ("x", "y", "z"),
    "order": ("x", "y", "z"),
    "frf": (),
}
_AMPLITUDE_AXIS = {"fft": "y", "fft_time": "z", "order": "z", "frf": None}

_PARAM_KEYS = {
    "fft": frozenset({
        "window", "nfft", "nfft_mode", "t_win_s", "overlap",
        "avg_mode", "avg_overlap", "amp_y", "db_reference_mode", "db_reference",
    }),
    "fft_time": frozenset({
        "window", "nfft", "nfft_mode", "t_win_s", "overlap",
        "amplitude_mode", "db_reference_mode", "db_reference",
    }),
    "order": frozenset({
        "max_order", "order_res", "time_res", "window", "nfft", "nfft_mode",
        "amplitude_mode", "samples_per_rev", "rpm_factor", "rpm_mode",
        "manual_rpm", "db_reference_mode", "db_reference",
    }),
    "frf": frozenset({
        "estimator", "window", "t_win_s", "overlap", "nfft_mode", "nfft",
        "magnitude_scale", "frequency_scale", "phase_mode",
        "coherence_threshold", "fade_low_coherence",
    }),
}

_IGNORE_KEYS = frozenset({
    "remark", "cmap", "remove_mean", "nfft_effective", "nfft_preview",
    "fs", "signal", "weighting", "periodic_window", "detrend",
})
_ALIAS_KEYS = frozenset({
    "autoscale", "freq_auto", "freq_min", "freq_max", "dynamic",
})
_CANONICAL_AXIS_KEYS = frozenset(
    key for keys in _AXIS_KEYS.values() for key in keys
)

_AUTO_NFFT_LABELS = frozenset({"自动", "auto"})


@dataclass(frozen=True)
class PresetDiff:
    params_differ: bool
    axes_differ: bool
    param_keys: tuple[str, ...] = ()
    axis_keys: tuple[str, ...] = ()
    unknown_keys: tuple[str, ...] = ()


def values_match(left, right) -> bool:
    """Same band as ``_helpers.preset_value_matches`` (1e-9; bool is not int)."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        return math.isclose(
            float(left), float(right),
            rel_tol=_PRESET_MATCH_REL_TOL, abs_tol=_PRESET_MATCH_ABS_TOL,
        )
    return left == right


def _as_mapping(params) -> dict[str, Any]:
    if isinstance(params, Mapping):
        return dict(params)
    return {}


def _parse_dynamic(raw) -> dict[str, Any] | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.lower() == "auto":
        return {"z_auto": True}
    try:
        span = abs(float(text.lower().replace("db", "").strip()))
    except ValueError:
        return None
    return {"z_auto": False, "z_floor": -span, "z_ceiling": 0.0}


def _nfft_is_auto(params: Mapping[str, Any]) -> bool:
    mode = params.get("nfft_mode")
    if mode is not None and str(mode).strip() != "":
        return str(mode).strip().lower() == "auto"
    nfft = params.get("nfft")
    if nfft is None:
        return True
    if isinstance(nfft, str):
        token = nfft.strip()
        if token in _AUTO_NFFT_LABELS or token.startswith("自动"):
            return True
    return False


def _unknown_keys(kind: str, params: Mapping[str, Any]) -> tuple[str, ...]:
    allowed = (
        _PARAM_KEYS.get(kind, frozenset())
        | _CANONICAL_AXIS_KEYS
        | _IGNORE_KEYS
        | _ALIAS_KEYS
    )
    found = []
    for key in params:
        if key not in allowed:
            found.append(str(key))
    return tuple(found)


def normalize_preset_params(kind, params) -> dict[str, Any]:
    """Return canonical comparable intent for ``kind``.

    Drops ignored keys, maps retired axis aliases once, and keeps only
    effective auto/manual axis and NFFT / dB-reference intent.
    """
    kind = str(kind)
    raw = _as_mapping(params)
    out: dict[str, Any] = {}

    if "x_auto" in raw:
        out["x_auto"] = bool(raw["x_auto"])
    elif "autoscale" in raw:
        out["x_auto"] = bool(raw["autoscale"])
    if "x_min" in raw:
        out["x_min"] = raw["x_min"]
    if "x_max" in raw:
        out["x_max"] = raw["x_max"]

    if "y_auto" in raw:
        out["y_auto"] = bool(raw["y_auto"])
    elif "freq_auto" in raw:
        out["y_auto"] = bool(raw["freq_auto"])
    if "y_min" in raw:
        out["y_min"] = raw["y_min"]
    elif "freq_min" in raw:
        out["y_min"] = raw["freq_min"]
    if "y_max" in raw:
        out["y_max"] = raw["y_max"]
    elif "freq_max" in raw:
        out["y_max"] = raw["freq_max"]

    z_from_dynamic = _parse_dynamic(raw["dynamic"]) if "dynamic" in raw else None
    if "z_auto" in raw:
        out["z_auto"] = bool(raw["z_auto"])
    elif z_from_dynamic is not None and "z_auto" in z_from_dynamic:
        out["z_auto"] = z_from_dynamic["z_auto"]
    if "z_floor" in raw:
        out["z_floor"] = raw["z_floor"]
    elif z_from_dynamic is not None and "z_floor" in z_from_dynamic:
        out["z_floor"] = z_from_dynamic["z_floor"]
    if "z_ceiling" in raw:
        out["z_ceiling"] = raw["z_ceiling"]
    elif z_from_dynamic is not None and "z_ceiling" in z_from_dynamic:
        out["z_ceiling"] = z_from_dynamic["z_ceiling"]

    allowed_axes = _AXES_FOR_KIND.get(kind, ())
    for axis in _AXIS_IDS:
        auto_key, min_key, max_key = _AXIS_KEYS[axis]
        if axis not in allowed_axes:
            out.pop(auto_key, None)
            out.pop(min_key, None)
            out.pop(max_key, None)
            continue
        if auto_key not in out:
            out.pop(min_key, None)
            out.pop(max_key, None)
            continue
        if bool(out[auto_key]):
            out.pop(min_key, None)
            out.pop(max_key, None)

    param_allow = _PARAM_KEYS.get(kind, frozenset())
    for key, value in raw.items():
        if key in _IGNORE_KEYS or key in _ALIAS_KEYS or key in _CANONICAL_AXIS_KEYS:
            continue
        if key in param_allow:
            out[key] = value

    if "nfft" in out or "nfft_mode" in raw or "nfft" in raw:
        if _nfft_is_auto(raw):
            if "nfft_mode" in param_allow:
                out["nfft_mode"] = "auto"
            out.pop("nfft", None)
        else:
            if kind == "frf":
                out["nfft_mode"] = "manual"
            elif "nfft_mode" in param_allow:
                out["nfft_mode"] = "fixed"
            if "nfft" in raw and raw["nfft"] is not None:
                out["nfft"] = raw["nfft"]

    mode = out.get("db_reference_mode", raw.get("db_reference_mode"))
    if mode is None and "db_reference" in raw:
        mode = "manual"
        out["db_reference_mode"] = "manual"
    if mode is not None:
        out["db_reference_mode"] = mode
        if str(mode).strip().lower() == "auto":
            out.pop("db_reference", None)
        elif "db_reference" in raw:
            out["db_reference"] = raw["db_reference"]

    return out


def _collect_unknown(kind, *blobs) -> tuple[str, ...]:
    keys = []
    seen = set()
    for blob in blobs:
        for key in _unknown_keys(kind, _as_mapping(blob)):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    if keys:
        logger.warning(
            "preset comparable-field map missing keys %s for kind %s",
            keys, kind,
        )
    return tuple(keys)


def diff_preset_state(kind, baseline_params, current_params, *, owned_only=False) -> PresetDiff:
    """Compare two collect_preset-shaped dicts after normalization."""
    kind = str(kind)
    unknown = _collect_unknown(kind, baseline_params, current_params)
    left = normalize_preset_params(kind, baseline_params)
    right = normalize_preset_params(kind, current_params)
    param_allow = _PARAM_KEYS.get(kind, frozenset())
    axis_allow = set()
    for axis in _AXES_FOR_KIND.get(kind, ()):
        axis_allow.update(_AXIS_KEYS[axis])

    if owned_only:
        keys = tuple(left)
    else:
        keys = tuple(dict.fromkeys((*left, *right)))

    param_diffs = []
    axis_diffs = []
    for key in keys:
        if key not in left or key not in right or not values_match(left[key], right[key]):
            if key in axis_allow:
                axis_diffs.append(key)
            elif key in param_allow:
                param_diffs.append(key)
            else:
                param_diffs.append(key)

    raw_left = _as_mapping(baseline_params)
    raw_right = _as_mapping(current_params)
    unknown_mismatches = []
    seen_unknown = set()
    for key in unknown:
        if key in seen_unknown:
            continue
        seen_unknown.add(key)
        if (
            key not in raw_left
            or key not in raw_right
            or not values_match(raw_left.get(key), raw_right.get(key))
        ):
            unknown_mismatches.append(key)

    axes_differ = bool(axis_diffs) if _AXES_FOR_KIND.get(kind) else False
    params_differ = bool(param_diffs) or bool(unknown_mismatches)
    return PresetDiff(
        params_differ=params_differ,
        axes_differ=axes_differ,
        param_keys=tuple(param_diffs),
        axis_keys=tuple(axis_diffs),
        unknown_keys=unknown,
    )


def build_preset_baseline(
    kind, slot, display_name, collect_params, *, source_payload=None,
) -> dict[str, Any]:
    """Build a baseline. ``source_payload`` makes a v2 load snapshot.

    Inference and programmatic tests that did not observe a load omit
    ``source_payload`` and stay on v1 (source unknown). An empty ``{}``
    collect is still returned here; callers must not treat it as a
    successful commit.
    """
    params = copy.deepcopy(_as_mapping(collect_params))
    payload = {
        "kind": str(kind),
        "slot": int(slot),
        "display_name": str(display_name),
        "params": params,
    }
    if source_payload is None:
        payload["version"] = 1
        return payload
    payload["version"] = PRESET_BASELINE_VERSION
    payload["source_payload"] = copy.deepcopy(_as_mapping(source_payload))
    return payload


def validate_preset_baseline(baseline, *, expected_kind=None) -> dict[str, Any] | None:
    if not isinstance(baseline, Mapping):
        return None
    version = baseline.get("version")
    kind = baseline.get("kind")
    slot = baseline.get("slot")
    display_name = baseline.get("display_name")
    params = baseline.get("params")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in PRESET_BASELINE_SUPPORTED_VERSIONS
    ):
        return None
    if not isinstance(kind, str) or not kind:
        return None
    if expected_kind is not None:
        if kind != expected_kind:
            return None
    elif kind not in PRESET_KINDS:
        return None
    if not isinstance(slot, int) or isinstance(slot, bool) or slot not in PRESET_SLOTS:
        return None
    if not isinstance(display_name, str):
        return None
    if not isinstance(params, dict) or not params:
        return None
    if version == 1:
        # Historical snapshot. Do not invent source_payload from a live slot.
        return {
            "version": 1,
            "kind": kind,
            "slot": slot,
            "display_name": display_name,
            "params": copy.deepcopy(params),
        }
    source_payload = baseline.get("source_payload")
    if not isinstance(source_payload, dict) or not source_payload:
        return None
    return {
        "version": 2,
        "kind": kind,
        "slot": slot,
        "display_name": display_name,
        "params": copy.deepcopy(params),
        "source_payload": copy.deepcopy(source_payload),
    }


def _complete_match(kind, payload, current) -> bool:
    if not payload:
        return False
    unknown = _collect_unknown(kind, payload, current)
    if unknown:
        return False
    left = normalize_preset_params(kind, payload)
    right = normalize_preset_params(kind, current)
    if not left or not right:
        return False
    if set(left) != set(right):
        return False
    return all(values_match(left[key], right[key]) for key in left)


def infer_preset_baseline(
    kind, current_params, slot_payloads, slot_names=None,
) -> dict[str, Any] | None:
    """Infer a baseline only when a slot's normalized comparable set is complete."""
    kind = str(kind)
    names = slot_names or {}
    payloads = slot_payloads or {}
    for slot in PRESET_SLOTS:
        payload = payloads.get(slot)
        if not isinstance(payload, Mapping) or not payload:
            continue
        if _complete_match(kind, payload, current_params):
            name = names.get(slot, f"配置 {slot}")
            return build_preset_baseline(kind, slot, name, current_params)
    return None


def _axis_effective(norm: Mapping[str, Any], axis: str):
    auto_key, min_key, max_key = _AXIS_KEYS[axis]
    if auto_key not in norm:
        return None
    if bool(norm[auto_key]):
        return ("auto",)
    if min_key not in norm or max_key not in norm:
        return ("manual", None, None)
    return ("manual", norm[min_key], norm[max_key])


def _axis_in_payload(kind, params, axis: str) -> bool:
    raw = _as_mapping(params)
    auto_key, min_key, max_key = _AXIS_KEYS[axis]
    aliases = {
        "x": ("autoscale",),
        "y": ("freq_auto", "freq_min", "freq_max"),
        "z": ("dynamic",),
    }
    if auto_key in raw or min_key in raw or max_key in raw:
        return True
    return any(key in raw for key in aliases.get(axis, ()))


def manual_axis_conflicts(kind, current, target) -> list[str]:
    """Axes that are currently manual and that applying ``target`` would change."""
    kind = str(kind)
    cur = normalize_preset_params(kind, current)
    tgt = normalize_preset_params(kind, target)
    conflicts = []
    for axis in _AXES_FOR_KIND.get(kind, ()):
        current_eff = _axis_effective(cur, axis)
        if current_eff is None or current_eff[0] != "manual":
            continue
        if not _axis_in_payload(kind, target, axis):
            continue
        target_eff = _axis_effective(tgt, axis)
        if target_eff is None:
            continue
        if target_eff[0] == "auto" or not values_match(current_eff, target_eff):
            conflicts.append(axis)
    return conflicts


def _db_ref_intent(norm: Mapping[str, Any]):
    mode = norm.get("db_reference_mode")
    if mode is None:
        return None
    if str(mode).strip().lower() == "auto":
        return ("auto",)
    return ("manual", norm.get("db_reference"))


def incompatible_amplitude_axes(kind, current, target) -> list[str]:
    kind = str(kind)
    axis = _AMPLITUDE_AXIS.get(kind)
    if axis is None:
        return []
    cur = normalize_preset_params(kind, current)
    tgt = normalize_preset_params(kind, target)
    changed = False
    if kind == "fft":
        if "amp_y" in tgt and "amp_y" in cur and not values_match(cur.get("amp_y"), tgt.get("amp_y")):
            changed = True
    else:
        if (
            "amplitude_mode" in tgt
            and "amplitude_mode" in cur
            and not values_match(cur.get("amplitude_mode"), tgt.get("amplitude_mode"))
        ):
            changed = True
    cur_ref = _db_ref_intent(cur)
    tgt_ref = _db_ref_intent(tgt)
    if cur_ref is not None and tgt_ref is not None and not values_match(cur_ref, tgt_ref):
        changed = True
    return [axis] if changed else []


def _write_axis(out: dict[str, Any], axis: str, *, auto: bool, lo=None, hi=None) -> None:
    auto_key, min_key, max_key = _AXIS_KEYS[axis]
    out[auto_key] = bool(auto)
    if axis == "x":
        out["autoscale"] = bool(auto)
    if axis == "y":
        out["freq_auto"] = bool(auto)
    if axis == "z":
        out["dynamic"] = "Auto" if auto else (
            f"{int(round(abs(float(lo))))} dB" if lo is not None else out.get("dynamic", "Auto")
        )
    if auto:
        return
    if lo is not None:
        out[min_key] = lo
        if axis == "y":
            out["freq_min"] = lo
    if hi is not None:
        out[max_key] = hi
        if axis == "y":
            out["freq_max"] = hi


def apply_keep_ranges(kind, current, target) -> dict[str, Any]:
    """Merge compatible current manual axes onto ``target``; auto-reset incompatible."""
    kind = str(kind)
    out = dict(_as_mapping(target))
    cur = normalize_preset_params(kind, current)
    incompat = set(incompatible_amplitude_axes(kind, current, target))
    for axis in _AXES_FOR_KIND.get(kind, ()):
        if axis in incompat:
            _write_axis(out, axis, auto=True)
            continue
        current_eff = _axis_effective(cur, axis)
        if current_eff is None or current_eff[0] != "manual":
            continue
        _, lo, hi = current_eff
        _write_axis(out, axis, auto=False, lo=lo, hi=hi)
    return out


def apply_preset_ranges(kind, current, target) -> dict[str, Any]:
    """Apply target ranges, but never keep old-unit amplitude numbers."""
    out = dict(_as_mapping(target))
    for axis in incompatible_amplitude_axes(kind, current, target):
        _write_axis(out, axis, auto=True)
    return out


def comparable_params_match(kind, left, right) -> bool:
    """True when normalized target/current comparison surfaces agree."""
    diff = diff_preset_state(kind, left, right)
    return not diff.params_differ and not diff.axes_differ


def source_payloads_match(kind, left, right) -> bool:
    """Compare slot patches with the same normalization used for diffs."""
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    if not left or not right:
        return False
    return comparable_params_match(kind, left, right)


def baseline_source_status(
    baseline,
    *,
    slot_available=True,
    current_payload=None,
    current_name="",
    kind=None,
) -> str:
    """Explain whether a restored baseline still matches the live slot."""
    if not isinstance(baseline, Mapping):
        return ""
    if not slot_available:
        return PRESET_SOURCE_UNAVAILABLE_NOTE
    version = baseline.get("version")
    source = baseline.get("source_payload")
    if version != 2 or not isinstance(source, Mapping) or not source:
        return PRESET_SOURCE_UNKNOWN_NOTE
    cmp_kind = kind or baseline.get("kind")
    if not source_payloads_match(cmp_kind, source, current_payload):
        return PRESET_SOURCE_UPDATED_NOTE
    if str(current_name) != str(baseline.get("display_name", "")):
        return PRESET_SOURCE_UPDATED_NOTE
    return ""


def _overlap_collect_value(kind: str, raw_value):
    """Map a patch overlap onto the kind's ``_collect_preset`` shape."""
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return raw_value
    if kind == "frf":
        percent = value * 100.0 if value <= 1.0 else value
        return float(round(percent)) / 100.0
    # FFT / FFT-vs-Time ``_apply_preset`` write the percent spin via int().
    return int(value)


def _amplitude_mode_collect(value) -> str:
    # Matches FFT-vs-Time / Order ``_apply_preset`` ('dB' in val).
    return "Amplitude dB" if "dB" in str(value) else "Amplitude"


def _apply_nfft_patch(kind: str, out: dict[str, Any], raw: Mapping[str, Any]) -> None:
    if "nfft" not in raw and "nfft_mode" not in raw:
        return
    if _nfft_is_auto(raw):
        if kind == "frf":
            out["nfft_mode"] = "auto"
            out["nfft"] = None
            return
        out["nfft_mode"] = "auto"
        out["nfft"] = "自动"
        return
    if kind == "frf":
        if "nfft_mode" in raw:
            out["nfft_mode"] = "manual"
            if raw.get("nfft") is not None:
                out["nfft"] = int(raw["nfft"])
            return
        if raw.get("nfft") is not None and str(out.get("nfft_mode")) == "manual":
            out["nfft"] = int(raw["nfft"])
        return
    out["nfft_mode"] = "fixed"
    if raw.get("nfft") is not None:
        out["nfft"] = str(raw["nfft"])


def _apply_db_patch(out: dict[str, Any], raw: Mapping[str, Any]) -> None:
    if "db_reference" not in raw and "db_reference_mode" not in raw:
        return
    migrated = migrate_legacy_reference_params(dict(raw))
    if "db_reference_mode" in migrated:
        out["db_reference_mode"] = migrated["db_reference_mode"]
    if "db_reference" in migrated and str(out.get("db_reference_mode", "")).lower() != "auto":
        out["db_reference"] = migrated["db_reference"]


def _apply_axis_patch(kind: str, out: dict[str, Any], raw: Mapping[str, Any]) -> None:
    if kind == "frf":
        return
    if "x_auto" in raw:
        out["x_auto"] = bool(raw["x_auto"])
    elif "autoscale" in raw:
        out["x_auto"] = bool(raw["autoscale"])
    if "x_min" in raw:
        out["x_min"] = raw["x_min"]
    if "x_max" in raw:
        out["x_max"] = raw["x_max"]

    if "y_auto" in raw:
        out["y_auto"] = bool(raw["y_auto"])
    elif "freq_auto" in raw:
        out["y_auto"] = bool(raw["freq_auto"])
    if "y_min" in raw:
        out["y_min"] = raw["y_min"]
    elif "freq_min" in raw:
        out["y_min"] = raw["freq_min"]
    if "y_max" in raw:
        out["y_max"] = raw["y_max"]
    elif "freq_max" in raw:
        out["y_max"] = raw["freq_max"]

    if "dynamic" in raw and "z_floor" not in raw:
        parsed = _parse_dynamic(raw["dynamic"])
        if parsed:
            out.update(parsed)
    if "z_auto" in raw:
        out["z_auto"] = bool(raw["z_auto"])
    if "z_floor" in raw:
        out["z_floor"] = raw["z_floor"]
    if "z_ceiling" in raw:
        out["z_ceiling"] = raw["z_ceiling"]

    allowed = set(_AXES_FOR_KIND.get(kind, ()))
    for axis in _AXIS_IDS:
        if axis in allowed:
            continue
        auto_key, min_key, max_key = _AXIS_KEYS[axis]
        out.pop(auto_key, None)
        out.pop(min_key, None)
        out.pop(max_key, None)


def _sync_collect_aliases(kind: str, out: dict[str, Any]) -> None:
    if kind == "fft" and "x_auto" in out:
        out["autoscale"] = bool(out["x_auto"])
    if kind != "fft_time":
        return
    if "y_auto" in out:
        out["freq_auto"] = bool(out["y_auto"])
    if "y_min" in out:
        out["freq_min"] = out["y_min"]
    if "y_max" in out:
        out["freq_max"] = out["y_max"]
    if "z_auto" in out and bool(out["z_auto"]):
        out["dynamic"] = "Auto"
        return
    if "z_floor" in out:
        try:
            span = abs(float(out["z_floor"]))
        except (TypeError, ValueError):
            return
        out["dynamic"] = f"{int(round(span))} dB"


def _apply_frf_enum(out: dict[str, Any], raw: Mapping[str, Any], key: str) -> None:
    if key in raw:
        out[key] = str(raw[key]).lower()


def resolve_preset_target(kind, before, patch) -> dict[str, Any]:
    """Resolve a slot patch onto ``before`` using apply-then-collect semantics.

    ``before`` is the current ``_collect_preset`` surface. Missing RPM / dB /
    axis / unit fields inherit from ``before``. This is not ``dict.update()``
    and must not be obtained by applying the live panel twice.
    """
    kind = str(kind)
    base = _as_mapping(before)
    raw = _as_mapping(patch)
    if not base and not raw:
        return {}
    out = dict(base)
    param_allow = _PARAM_KEYS.get(kind, frozenset())

    _apply_nfft_patch(kind, out, raw)
    if "overlap" in raw:
        out["overlap"] = _overlap_collect_value(kind, raw["overlap"])
    _apply_db_patch(out, raw)
    _apply_axis_patch(kind, out, raw)

    skip = {
        "nfft", "nfft_mode", "overlap",
        "db_reference", "db_reference_mode",
        *_CANONICAL_AXIS_KEYS, *_ALIAS_KEYS,
    }
    for key, value in raw.items():
        if key == "remark":
            out["remark"] = bool(value)
            continue
        if key in skip or key in _IGNORE_KEYS:
            continue
        if key == "amplitude_mode":
            out["amplitude_mode"] = _amplitude_mode_collect(value)
            continue
        if kind == "frf" and key in {
            "estimator", "window", "magnitude_scale",
            "frequency_scale", "phase_mode",
        }:
            _apply_frf_enum(out, raw, key)
            continue
        if key in param_allow:
            out[key] = value

    _sync_collect_aliases(kind, out)
    return out

