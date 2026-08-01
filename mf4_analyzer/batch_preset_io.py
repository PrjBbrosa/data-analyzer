"""JSON serialization for AnalysisPreset (recipe-only, portable).

Excludes runtime selection fields (file_ids, file_paths, signal,
rpm_signal) and the legacy signal_pattern fallback. Output directory
is never persisted — preset is "what to compute", not "where to write".
"""
from __future__ import annotations

import json
from pathlib import Path

from . import db_reference
from .batch import (
    AnalysisPreset,
    BatchOutput,
    BatchRunner,
    _legacy_image_format_warning,
)
from .batch_recipe import normalize_batch_params


SCHEMA_VERSION = 1


class UnsupportedPresetVersion(ValueError):
    """Raised when reading a preset whose schema_version is unknown."""


def _migrate_axis_keys(params: dict) -> dict:
    """Translate legacy 'algorithm' / 'dynamic' / 'amplitude_mode' keys to
    the post-2026-04-28 axis-settings field set. Mutates and returns params.
    Idempotent — safe to call on already-migrated presets."""
    # Drop algorithm key (COT-only after 2026-04-28)
    params.pop('algorithm', None)

    # Translate dynamic → z_auto / z_floor / z_ceiling if not already present
    if 'z_floor' not in params and 'dynamic' in params:
        raw = str(params.pop('dynamic'))
        if raw == 'Auto':
            params['z_auto'] = True
        else:
            try:
                n = float(raw.replace('dB', '').strip())
                params['z_auto'] = False
                params['z_floor'] = -abs(n)
                params['z_ceiling'] = 0.0
            except ValueError:
                params['z_auto'] = True  # malformed → safe default
    else:
        params.pop('dynamic', None)

    return params


def save_preset_to_json(preset: AnalysisPreset, path: str | Path) -> None:
    """Write preset to JSON using the §4.1 serialization whitelist."""
    path = Path(path)
    image_format = str(preset.outputs.image_format or "").strip().lower().lstrip(".")
    if image_format != "png":
        raise ValueError(
            f"unsupported batch image_format: {preset.outputs.image_format!r}"
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "name": preset.name,
        "method": preset.method,
        "target_signals": list(preset.target_signals),
        "target_policy": str(preset.target_policy or "common"),
        "rpm_channel": preset.rpm_channel,
        "params": normalize_batch_params(preset.params, preset.method),
        "outputs": {
            "export_data": bool(preset.outputs.export_data),
            "export_image": bool(preset.outputs.export_image),
            "data_format": str(preset.outputs.data_format),
            "image_format": "png",
            "image_size": str(preset.outputs.image_size),
            "image_width": int(preset.outputs.image_width),
            "image_height": int(preset.outputs.image_height),
            "image_dpi": int(preset.outputs.image_dpi),
            "image_background": str(preset.outputs.image_background),
            "image_line_width": float(preset.outputs.image_line_width),
            "conflict_policy": str(preset.outputs.conflict_policy),
            "write_manifest": bool(preset.outputs.write_manifest),
            "resume_policy": str(preset.outputs.resume_policy),
        },
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_preset_from_json(path: str | Path) -> AnalysisPreset | None:
    """Read preset from JSON. Missing schema_version → v1; unknown → reject.

    Returns ``None`` when the preset's ``method`` is no longer in
    ``BatchRunner.SUPPORTED_METHODS`` — e.g. a legacy ``order_track`` preset
    saved before 2026-04-28. The skip is silent (no exception) so the
    import handler can surface a friendly toast instead of crashing
    ``_run_one``'s ``else: raise`` at run time. Importing
    ``SUPPORTED_METHODS`` from ``batch`` (rather than duplicating the set)
    follows the cross-layer-constant promote rule.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid preset JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("preset JSON must be a JSON object")

    version = raw.get("schema_version")
    if version is None:
        version = 1   # back-compat: pre-versioned hand-written fixture
    if version != SCHEMA_VERSION:
        raise UnsupportedPresetVersion(
            f"preset schema_version={version} not supported "
            f"(this app reads v{SCHEMA_VERSION})"
        )

    # Drop legacy methods no longer supported. order_track was removed
    # 2026-04-28; silently skip presets that still reference it instead of
    # crashing _run_one's `else: raise`.
    method = raw.get("method", "fft")
    if method not in BatchRunner.SUPPORTED_METHODS:
        return None

    outputs_raw = raw.get("outputs") or {}
    requested_image_format = str(
        outputs_raw.get("image_format", "png") or ""
    ).strip().lower().lstrip(".")
    if requested_image_format in {"pdf", "svg"}:
        image_format = "png"
        migration_warnings = (
            _legacy_image_format_warning(requested_image_format),
        )
        migration_provenance = requested_image_format
    elif requested_image_format == "png":
        image_format = "png"
        migration_warnings = ()
        migration_provenance = None
    else:
        raise ValueError(
            f"unsupported preset image_format: {requested_image_format!r}"
        )
    params_dict = dict(raw.get("params") or {})
    _migrate_axis_keys(params_dict)
    # dB-reference-defaults spec §13 S4: a legacy preset's bare
    # ``db_reference`` value (no ``db_reference_mode``) IS the old
    # authoritative display reference -> migrate to Manual, same rule as
    # the View/preset migration (S2/S3). No-op when the key is absent.
    params_dict = normalize_batch_params(
        db_reference.migrate_legacy_reference_params(params_dict), method,
    )
    return AnalysisPreset.free_config(
        name=raw.get("name", ""),
        method=method,
        rpm_channel=raw.get("rpm_channel", ""),
        target_signals=tuple(raw.get("target_signals") or ()),
        target_policy=raw.get("target_policy", "common"),
        params=params_dict,
        outputs=BatchOutput(
            export_data=bool(outputs_raw.get("export_data", True)),
            export_image=bool(outputs_raw.get("export_image", True)),
            data_format=str(outputs_raw.get("data_format", "csv")),
            image_format=image_format,
            image_size=str(outputs_raw.get("image_size", "1920x1080")),
            image_width=int(outputs_raw.get("image_width", 1920)),
            image_height=int(outputs_raw.get("image_height", 1080)),
            image_dpi=int(outputs_raw.get("image_dpi", 144)),
            image_background=str(
                outputs_raw.get("image_background", "white")
            ),
            image_line_width=float(
                outputs_raw.get("image_line_width", 1.5)
            ),
            conflict_policy=str(
                outputs_raw.get("conflict_policy", "auto_number")
            ),
            write_manifest=bool(outputs_raw.get("write_manifest", True)),
            resume_policy=str(outputs_raw.get("resume_policy", "none")),
            requested_image_format=migration_provenance,
            migration_warnings=migration_warnings,
        ),
    )
