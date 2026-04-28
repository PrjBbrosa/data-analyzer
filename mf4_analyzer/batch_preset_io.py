"""JSON serialization for AnalysisPreset (recipe-only, portable).

Excludes runtime selection fields (file_ids, file_paths, signal,
rpm_signal) and the legacy signal_pattern fallback. Output directory
is never persisted — preset is "what to compute", not "where to write".
"""
from __future__ import annotations

import json
from pathlib import Path

from .batch import AnalysisPreset, BatchOutput, BatchRunner


SCHEMA_VERSION = 1


class UnsupportedPresetVersion(ValueError):
    """Raised when reading a preset whose schema_version is unknown."""


def save_preset_to_json(preset: AnalysisPreset, path: str | Path) -> None:
    """Write preset to JSON using the §4.1 serialization whitelist."""
    path = Path(path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "name": preset.name,
        "method": preset.method,
        "target_signals": list(preset.target_signals),
        "rpm_channel": preset.rpm_channel,
        "params": dict(preset.params),
        "outputs": {
            "export_data": bool(preset.outputs.export_data),
            "export_image": bool(preset.outputs.export_image),
            "data_format": str(preset.outputs.data_format),
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
    return AnalysisPreset.free_config(
        name=raw.get("name", ""),
        method=method,
        rpm_channel=raw.get("rpm_channel", ""),
        target_signals=tuple(raw.get("target_signals") or ()),
        params=dict(raw.get("params") or {}),
        outputs=BatchOutput(
            export_data=bool(outputs_raw.get("export_data", True)),
            export_image=bool(outputs_raw.get("export_image", True)),
            data_format=str(outputs_raw.get("data_format", "csv")),
        ),
    )
