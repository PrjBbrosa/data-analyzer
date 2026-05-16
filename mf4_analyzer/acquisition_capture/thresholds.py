"""Single source of truth for all numeric thresholds in the Acquisition Cockpit.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Threshold Contract.

UI and capture code MUST import constants from this module — never inline a
literal threshold elsewhere. A future Settings dialog will load/save through
this module; until that exists, the module is the single source.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mf4_analyzer.acquisition_capture.config_store import ConfigSchemaError

# ---------------------------------------------------------------------------
# Record-readiness bands (spec §Threshold Contract, table 1).
# ---------------------------------------------------------------------------

# CAN bus load (percent of bitrate).
CAN_LOAD_GREEN_MAX_PCT = 60.0
CAN_LOAD_YELLOW_MAX_PCT = 80.0  # >= triggers red

# DAQ slot per event (percent of event capacity).
DAQ_SLOT_GREEN_MAX_PCT = 75.0
DAQ_SLOT_YELLOW_MAX_PCT = 95.0  # 100% triggers red

# Disk remaining (bytes).
DISK_FREE_GREEN_MIN_BYTES = 5 * 1024 ** 3        # > 5 GB
DISK_FREE_YELLOW_MIN_BYTES = 1 * 1024 ** 3       # 1-5 GB
# < 1 GB -> red

# Estimated record duration (seconds).
RECORD_DURATION_GREEN_MIN_S = 4 * 3600           # > 4 h
RECORD_DURATION_YELLOW_MIN_S = 30 * 60           # 30 min .. 4 h
# < 30 min -> red

# Total sample events per second.
SAMPLE_EVENTS_GREEN_MAX_PER_S = 30_000.0
SAMPLE_EVENTS_YELLOW_MAX_PER_S = 80_000.0
# > 80 k -> red

# ---------------------------------------------------------------------------
# Recording-quality bands (spec §Threshold Contract, table 2).
# ---------------------------------------------------------------------------

# Ring buffer watermarks (percent of capacity).
RING_BUFFER_GREEN_MAX_PCT = 50.0
RING_BUFFER_YELLOW_LOW_MAX_PCT = 70.0
RING_BUFFER_RED_MAX_PCT = 85.0
RING_BUFFER_RED_DROP_MAX_PCT = 95.0
# >= 95% for RING_BUFFER_AUTO_STOP_SUSTAIN_S => auto-stop
RING_BUFFER_AUTO_STOP_SUSTAIN_S = 5.0

# Dropped-frames escalation.
DROPPED_FRAMES_YELLOW_MAX_PER_WINDOW = 10
DROPPED_FRAMES_RED_PER_10S = 10
DROPPED_FRAMES_PROMPT_TOTAL = 100  # asks "continue?" but never force-stops

# Disk auto-stop (live capture, bytes).
DISK_FREE_AUTO_STOP_BYTES = 100 * 1024 * 1024  # 100 MB

# ---------------------------------------------------------------------------
# Health-aggregator polling (spec §Health Snapshot Model Contract).
# ---------------------------------------------------------------------------

HEALTH_POLL_INTERVAL_S = 0.5
# Stale-snapshot rule: HwHealth.last_probe_ts older than 2 * poll_interval ⇒ off.
HEALTH_STALE_FACTOR = 2.0

# RecHealth.last_rx_age_s thresholds.
REC_LAST_RX_YELLOW_MIN_S = 1.0
REC_LAST_RX_RED_MIN_S = 2.0

# XCP timeout escalation.
XCP_YELLOW_TIMEOUTS = 1   # 1..2 timeouts ⇒ yellow
XCP_RED_TIMEOUTS = 3      # >= 3 ⇒ red

# ---------------------------------------------------------------------------
# Connection / session defaults (spec §State Machine Contract).
# ---------------------------------------------------------------------------

CONNECTION_TIMEOUT_S = 3.0
DEFAULT_CAN_BITRATE_BPS = 500_000

# UI draw cap (spec §Center Pane).
LIVE_FPS_NORMAL = 30
LIVE_FPS_DEGRADED = 10

# Default ring-buffer capacity (samples). Tunable; deliberately conservative
# so the watermark transitions are exercisable in the MVP CLI without
# overwhelming /tmp on macOS.
DEFAULT_RING_CAPACITY = 4096


SETTINGS_VERSION = 1

_EDITABLE_THRESHOLD_KEYS = (
    "CAN_LOAD_GREEN_MAX_PCT",
    "CAN_LOAD_YELLOW_MAX_PCT",
    "DAQ_SLOT_GREEN_MAX_PCT",
    "DAQ_SLOT_YELLOW_MAX_PCT",
    "DISK_FREE_GREEN_MIN_BYTES",
    "DISK_FREE_YELLOW_MIN_BYTES",
    "RECORD_DURATION_GREEN_MIN_S",
    "RECORD_DURATION_YELLOW_MIN_S",
    "SAMPLE_EVENTS_GREEN_MAX_PER_S",
    "SAMPLE_EVENTS_YELLOW_MAX_PER_S",
    "RING_BUFFER_GREEN_MAX_PCT",
    "RING_BUFFER_YELLOW_LOW_MAX_PCT",
    "RING_BUFFER_RED_MAX_PCT",
    "RING_BUFFER_RED_DROP_MAX_PCT",
    "RING_BUFFER_AUTO_STOP_SUSTAIN_S",
    "DROPPED_FRAMES_YELLOW_MAX_PER_WINDOW",
    "DROPPED_FRAMES_RED_PER_10S",
    "DROPPED_FRAMES_PROMPT_TOTAL",
    "DISK_FREE_AUTO_STOP_BYTES",
    "HEALTH_POLL_INTERVAL_S",
    "REC_LAST_RX_YELLOW_MIN_S",
    "REC_LAST_RX_RED_MIN_S",
    "XCP_YELLOW_TIMEOUTS",
    "XCP_RED_TIMEOUTS",
    "CONNECTION_TIMEOUT_S",
    "DEFAULT_CAN_BITRATE_BPS",
)

_DEFAULT_THRESHOLDS = MappingProxyType(
    {key: globals()[key] for key in _EDITABLE_THRESHOLD_KEYS}
)

VALID_THRESHOLD_KEYS = frozenset(_DEFAULT_THRESHOLDS)


def default_user_settings_path() -> Path:
    """Return the per-user Cockpit settings path."""
    return Path.home() / ".acquisition-cockpit" / "settings.json"


def load_user_settings(path: Path | None = None) -> dict[str, float | int]:
    """Load threshold overrides from ``settings.json``.

    Missing files mean "no overrides". Schema or type errors raise
    ``ConfigSchemaError`` so callers can distinguish corrupt settings
    from the normal first-run path.
    """
    p = Path(path) if path is not None else default_user_settings_path()
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigSchemaError(f"{p}: invalid JSON: {exc}") from exc
    return _validate_settings_payload(payload, label=str(p))


def save_user_settings(payload: Mapping[str, Any], path: Path | None = None) -> None:
    """Validate and write a settings payload using explicit UTF-8 IO."""
    p = Path(path) if path is not None else default_user_settings_path()
    overrides = _validate_settings_payload(payload, label=str(p))
    normalized = {
        "version": SETTINGS_VERSION,
        "thresholds": dict(sorted(overrides.items())),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_overrides(overrides: Mapping[str, float | int]) -> None:
    """Apply validated threshold overrides to this module's constants."""
    validated = _validate_threshold_mapping(overrides, label="threshold overrides")
    for key, value in validated.items():
        globals()[key] = value


def reset_defaults() -> None:
    """Restore threshold constants from the immutable module-load snapshot."""
    for key, value in _DEFAULT_THRESHOLDS.items():
        globals()[key] = value


def _validate_settings_payload(
    payload: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, float | int]:
    if not isinstance(payload, Mapping):
        raise ConfigSchemaError(f"{label}: settings payload must be a mapping")

    extra = set(payload.keys()) - {"version", "thresholds"}
    if extra:
        raise ConfigSchemaError(
            f"{label}: unknown top-level key(s) {sorted(extra)!r}"
        )

    version = payload.get("version")
    if version != SETTINGS_VERSION:
        raise ConfigSchemaError(
            f"{label}: version must be {SETTINGS_VERSION}, got {version!r}"
        )

    raw_thresholds = payload.get("thresholds", {})
    if raw_thresholds is None:
        raw_thresholds = {}
    if not isinstance(raw_thresholds, Mapping):
        raise ConfigSchemaError(f"{label}: thresholds must be a mapping")
    return _validate_threshold_mapping(raw_thresholds, label=label)


def _validate_threshold_mapping(
    values: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, float | int]:
    if not isinstance(values, Mapping):
        raise ConfigSchemaError(f"{label}: threshold overrides must be a mapping")

    unknown = set(values.keys()) - VALID_THRESHOLD_KEYS
    if unknown:
        raise ConfigSchemaError(
            f"{label}: unknown threshold key(s) {sorted(unknown)!r}; "
            f"allowed keys are {sorted(VALID_THRESHOLD_KEYS)!r}"
        )

    validated: dict[str, float | int] = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigSchemaError(
                f"{label}: threshold {key!r} must be numeric, got {value!r}"
            )
        validated[str(key)] = value
    return validated
