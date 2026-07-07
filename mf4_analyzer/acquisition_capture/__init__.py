"""Acquisition Cockpit capture core.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``.
Stage 0 gap note: ``docs/analyzer/acquisition/reports/2026-05-15-cockpit-stage0-gap-note.md``.

This package is intentionally Qt-free so capture behavior can run on
macOS without a display. The Cockpit Qt window in
``mf4_analyzer/acquisition_ui/`` imports from here, not the other way
around.

Public API (stable for the Cockpit and CLI):

- ``SessionConfig``, ``SelectedMeasurement``, ``SessionSummary`` — session data
- ``CaptureController`` — start/stop/flush orchestrator
- ``RingBuffer``, ``WatermarkLevel`` — backpressure model
- ``Mf4Writer`` — buffered-chunks-then-finalize writer
- ``RecorderBackend``, ``FakeRecorderBackend``, ``ReplayRecorderBackend``,
  ``VectorXcpRecorderBackend`` — backends
- Health: ``HwHealth``, ``CanHealth``, ``XcpHealth``, ``DaqHealth``,
  ``RecHealth``, ``HealthAggregator``, ``HealthSnapshot``,
  plus the ``level_*`` helpers.
- ``thresholds`` module — single source of all numeric thresholds.

Adjacent package ``mf4_analyzer.acquisition`` (note: no ``_capture`` suffix)
is the post-record validation program (manifest / preflight / regression /
signals). Do NOT confuse the two — Stage 0 gap note pins this distinction.
"""

from __future__ import annotations

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.backends import (
    BackendStatus,
    FakeRecorderBackend,
    RecorderBackend,
    ReplayRecorderBackend,
    VectorXcpRecorderBackend,
)
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    ChannelHealth,
    DaqHealth,
    HealthAggregator,
    HealthSnapshot,
    HwHealth,
    RecHealth,
    XcpHealth,
    level_can,
    level_channel,
    level_daq,
    level_hw,
    level_rec,
    level_xcp,
    probe_hw_macos_stub,
)
from mf4_analyzer.acquisition_capture.ring_buffer import (
    RingBuffer,
    Signal,
    WatermarkLevel,
)
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
    SessionSummary,
)
from mf4_analyzer.acquisition_capture.writer import Mf4Writer, Mf4WriterError

# RecorderHealth is the spec alias for RecHealth (see plan §Core types).
RecorderHealth = RecHealth

__all__ = [
    "thresholds",
    # Session
    "SelectedMeasurement",
    "SessionConfig",
    "SessionSummary",
    # Controller
    "CaptureController",
    # Ring buffer
    "RingBuffer",
    "Signal",
    "WatermarkLevel",
    # Writer
    "Mf4Writer",
    "Mf4WriterError",
    # Backends
    "BackendStatus",
    "RecorderBackend",
    "FakeRecorderBackend",
    "ReplayRecorderBackend",
    "VectorXcpRecorderBackend",
    # Health
    "ChannelHealth",
    "HwHealth",
    "CanHealth",
    "XcpHealth",
    "DaqHealth",
    "RecHealth",
    "RecorderHealth",
    "HealthAggregator",
    "HealthSnapshot",
    "level_hw",
    "level_can",
    "level_channel",
    "level_xcp",
    "level_daq",
    "level_rec",
    "probe_hw_macos_stub",
]


def _autoload_user_threshold_overrides() -> None:
    """Apply user threshold overrides at package import.

    Best-effort: any failure (missing file, IO error, schema error, decode
    error) falls back to defaults silently. ``KeyboardInterrupt`` and
    ``SystemExit`` are NOT caught.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        overrides = thresholds.load_user_settings()
        if overrides:
            thresholds.apply_overrides(overrides)
    except Exception as exc:  # noqa: BLE001 - silent fallback per spec
        log.warning("could not auto-load user threshold overrides: %s", exc)


_autoload_user_threshold_overrides()
