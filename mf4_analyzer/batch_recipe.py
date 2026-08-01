"""Canonical, GUI-free batch recipe normalization and fingerprinting.

This module deliberately does not import :mod:`mf4_analyzer.batch`.  Callers
may therefore use it from ``batch.py``, preset I/O, and the PyQt layer without
creating an import cycle.  ``normalize_analysis_preset`` accepts either a
mapping or any duck-typed object exposing ``AnalysisPreset``-like attributes.

Normalization is intentionally conservative:

* analysis defaults stay absent; stable output-schema defaults are materialized;
* unknown fields survive so a newer recipe can pass through an older UI;
* only fields known to belong to a different method are removed;
* JSON container/scalar representations are made deterministic.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from . import db_reference


SUPPORTED_RECIPE_METHODS = frozenset({"time", "fft", "fft_time", "order_time"})

TIME_RENDER_DEFAULTS = {
    "render_group_by": "none",
    "render_layout": "overlay",
    "x_source": "time",
    "x_channel": "",
    "x_origin": "zero",
}

COMMON_PARAM_FIELDS = frozenset({
    "fs",
    "time_range",
    "time_preprocess",
    "filter",
    "x_auto",
    "x_min",
    "x_max",
    "y_auto",
    "y_min",
    "y_max",
    "z_auto",
    "z_min",
    "z_max",
    "z_floor",
    "z_ceiling",
    "amplitude_mode",
    "weighting",
    "db_reference",
    "db_reference_mode",
    "cmap",
})

METHOD_PARAM_FIELDS = {
    "time": frozenset(TIME_RENDER_DEFAULTS),
    "fft": frozenset({
        "window",
        "nfft",
        "nfft_mode",
        "t_win_s",
        "overlap",
        "avg_mode",
        "avg_overlap",
        "amplitude_definition",
        "amp_y",
    }),
    "fft_time": frozenset({
        "window",
        "nfft",
        "nfft_mode",
        "t_win_s",
        "overlap",
        "remove_mean",
    }),
    "order_time": frozenset({
        "window",
        "nfft",
        "nfft_mode",
        "max_order",
        "order_res",
        "time_res",
        "rpm_mode",
        "manual_rpm",
        "samples_per_rev",
        "rpm_factor",
        # ``rpm_signal`` normally lives on AnalysisPreset, but old/hand-made
        # recipes can carry it inside params.  Mark it as known so a method
        # switch can discard it explicitly instead of treating it as future
        # opaque data.
        "rpm_signal",
        "rpm_channel",
    }),
}

KNOWN_PARAM_FIELDS = COMMON_PARAM_FIELDS | frozenset().union(
    *METHOD_PARAM_FIELDS.values()
)

_FLOAT_PARAM_FIELDS = frozenset({
    "fs",
    "t_win_s",
    "overlap",
    "avg_overlap",
    "x_min",
    "x_max",
    "y_min",
    "y_max",
    "z_min",
    "z_max",
    "z_floor",
    "z_ceiling",
    "db_reference",
    "max_order",
    "order_res",
    "time_res",
    "manual_rpm",
    "rpm_factor",
})
_INT_PARAM_FIELDS = frozenset({"nfft", "samples_per_rev"})
_BOOL_PARAM_FIELDS = frozenset({
    "x_auto",
    "y_auto",
    "z_auto",
    "remove_mean",
})
_NORMALIZED_ENUM_PARAM_FIELDS = frozenset({
    "render_group_by",
    "render_layout",
    "x_source",
    "x_origin",
})

_PRESET_FIELDS = (
    "name",
    "method",
    "source",
    "params",
    "outputs",
    "signal",
    "rpm_signal",
    "signal_pattern",
    "rpm_channel",
    "target_signals",
    "target_pairs",
    "source_ids",
    "source_paths",
    "target_policy",
    "file_ids",
    "file_paths",
)
OUTPUT_DEFAULTS = {
    "export_data": True,
    "export_image": True,
    "data_format": "csv",
    "image_format": "png",
    "image_size": "1920x1080",
    "image_width": 1920,
    "image_height": 1080,
    "image_dpi": 144,
    "image_background": "white",
    "image_line_width": 1.0,
    "conflict_policy": "auto_number",
    "write_manifest": True,
    "resume_policy": "none",
}
_OUTPUT_FIELDS = tuple(OUTPUT_DEFAULTS)

# Only settings that change the requested artifact set or bytes participate in
# the run-recipe fingerprint.  Operational controls may change between a first
# run and a resume/retry without making otherwise identical artifacts stale.
_FINGERPRINT_OUTPUT_FIELDS = (
    "export_data",
    "export_image",
    "data_format",
    "image_format",
    "image_size",
    "image_width",
    "image_height",
    "image_dpi",
    "image_background",
    "image_line_width",
)


def _method_key(method: object) -> str:
    key = str(method or "").strip().lower()
    if key not in SUPPORTED_RECIPE_METHODS:
        raise ValueError(f"unsupported batch method: {method!r}")
    return key


def compatible_param_fields(method: object) -> frozenset[str]:
    """Return the known parameter fields compatible with *method*.

    Unknown fields are not part of this schema, but normalization preserves
    them by design.
    """

    key = _method_key(method)
    return COMMON_PARAM_FIELDS | METHOD_PARAM_FIELDS[key]


def _json_safe(value: Any) -> Any:
    """Return a deterministic JSON-compatible copy of *value*.

    NumPy scalars/arrays are common in analysis state.  Tuples and arrays use
    JSON's single sequence representation (list), making an imported JSON
    recipe equivalent to the in-memory tuple form.  Unsupported opaque values
    fail loudly rather than being fingerprinted through unstable ``repr``.
    """

    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("batch recipe mapping keys must be strings")
            out[key] = _json_safe(item)
        return out
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_json_safe(item) for item in value]
        return sorted(items, key=_canonical_json)
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(
        "batch recipe values must be JSON-compatible; "
        f"got {type(value).__name__}"
    )


def _normalize_known_value(field: str, value: Any) -> Any:
    value = _json_safe(value)
    if field == "amplitude_definition" and isinstance(value, str):
        return value.strip().lower()
    if field in _NORMALIZED_ENUM_PARAM_FIELDS and isinstance(value, str):
        return value.strip().lower()
    if field == "time_range" and isinstance(value, list):
        if len(value) == 2 and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value
        ):
            return [float(value[0]), float(value[1])]
        return value
    if field in _FLOAT_PARAM_FIELDS:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    elif field in _INT_PARAM_FIELDS:
        if isinstance(value, int) and not isinstance(value, bool):
            return int(value)
    elif field in _BOOL_PARAM_FIELDS and isinstance(value, bool):
        return bool(value)
    return value


def normalize_batch_params(params: Mapping[str, Any] | None, method: object) -> dict:
    """Normalize *params* for *method* without introducing defaults.

    Known fields owned by another method are discarded.  Every unknown field
    is retained as a JSON-compatible value so old UI code cannot erase a
    future parameter it does not yet understand.
    """

    method_key = _method_key(method)
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise TypeError("batch params must be a mapping")
    for key in params:
        if not isinstance(key, str):
            raise TypeError("batch recipe mapping keys must be strings")

    migrated = db_reference.migrate_legacy_reference_params(params)
    compatible = compatible_param_fields(method_key)
    normalized: dict[str, Any] = {}
    for field, value in migrated.items():
        if field in KNOWN_PARAM_FIELDS and field not in compatible:
            continue
        normalized[field] = _normalize_known_value(field, value)
    # A source-data window is an FFT-only analysis input.  FFT-vs-Time and
    # order analysis deliberately consume the full valid time domain; keeping
    # a legacy ``time_range`` merely because it is a common historical field
    # would silently crop their matrices in ``batch_preprocess``.
    if method_key in {"fft_time", "order_time"}:
        normalized.pop("time_range", None)
    if method_key == "time":
        # Time-domain output is linear engineering data.  dB reference is a
        # spectral display concern and must neither occupy the compact UI nor
        # leak through an imported legacy recipe.
        normalized.pop("db_reference", None)
        normalized.pop("db_reference_mode", None)
        group_by = normalized.get(
            "render_group_by", TIME_RENDER_DEFAULTS["render_group_by"],
        )
        if group_by == "none":
            normalized.pop("render_layout", None)

        x_source = normalized.get(
            "x_source", TIME_RENDER_DEFAULTS["x_source"],
        )
        if x_source == "channel":
            normalized.pop("x_origin", None)
        else:
            normalized.pop("x_channel", None)

        for field, default in TIME_RENDER_DEFAULTS.items():
            if normalized.get(field) == default:
                normalized.pop(field, None)
    return normalized


def _duck_outputs(outputs: object) -> Any:
    if isinstance(outputs, Mapping):
        supplied = _json_safe(outputs)
        return {**OUTPUT_DEFAULTS, **supplied}
    result = {
        field: getattr(outputs, field, default)
        for field, default in OUTPUT_DEFAULTS.items()
    }
    return _json_safe(result)


def normalize_analysis_preset(preset: Mapping[str, Any] | object) -> dict:
    """Return a canonical mapping for a mapping or AnalysisPreset-like object.

    Mapping input retains unknown top-level fields.  For duck-typed objects,
    the public ``AnalysisPreset`` fields are copied when present.  No import of
    the concrete dataclass is required.
    """

    if isinstance(preset, Mapping):
        raw = dict(preset)
    else:
        raw = {
            field: getattr(preset, field)
            for field in _PRESET_FIELDS
            if hasattr(preset, field)
        }
    if "method" not in raw or not str(raw.get("method") or "").strip():
        raise ValueError("batch analysis preset requires a method")

    method = _method_key(raw["method"])
    normalized: dict[str, Any] = {}
    for field, value in raw.items():
        if field == "method":
            normalized[field] = method
        elif field == "params":
            normalized[field] = normalize_batch_params(value, method)
        elif field == "outputs":
            normalized[field] = _duck_outputs(value)
        else:
            normalized[field] = _json_safe(value)
    return normalized


def _fingerprint_json_safe(value: Any) -> Any:
    """Tag non-finite floats so even an invalid recipe hashes deterministically.

    Validation owns whether NaN/Inf is executable; fingerprinting must not turn
    those values into valid numbers or depend on JSON's non-standard NaN mode.
    """

    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            label = "nan"
        elif value > 0:
            label = "+inf"
        else:
            label = "-inf"
        return {"__nonfinite_float__": label}
    if isinstance(value, dict):
        return {key: _fingerprint_json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_fingerprint_json_safe(item) for item in value]
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _fingerprint_json_safe(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def recipe_fingerprint(
    params: Mapping[str, Any] | None,
    method: object,
    *,
    source_identity: object | None = None,
    group_identity: object | None = None,
    channel_identity: object | None = None,
    outputs: Mapping[str, Any] | object | None = None,
) -> str:
    """Return a stable SHA-256 task/recipe fingerprint.

    Identity fields are optional so the same helper covers both pure recipe
    equality and the Phase-1 task-id contract.  Callers use ``digest[:8]`` for
    human-readable filenames while retaining the full digest in result facts.
    """

    method_key = _method_key(method)
    payload = {
        "method": method_key,
        "params": normalize_batch_params(params, method_key),
    }
    if outputs is not None:
        normalized_outputs = _duck_outputs(outputs)
        payload["outputs"] = {
            field: normalized_outputs[field]
            for field in _FINGERPRINT_OUTPUT_FIELDS
        }
    identities = {
        "source_identity": source_identity,
        "group_identity": group_identity,
        "channel_identity": channel_identity,
    }
    for field, value in identities.items():
        if value is not None:
            payload[field] = _json_safe(value)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "COMMON_PARAM_FIELDS",
    "KNOWN_PARAM_FIELDS",
    "METHOD_PARAM_FIELDS",
    "OUTPUT_DEFAULTS",
    "SUPPORTED_RECIPE_METHODS",
    "TIME_RENDER_DEFAULTS",
    "compatible_param_fields",
    "normalize_analysis_preset",
    "normalize_batch_params",
    "recipe_fingerprint",
]
