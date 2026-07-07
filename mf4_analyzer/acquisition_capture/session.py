"""Session data model for the Acquisition Cockpit capture core.

These dataclasses are pure data: no Qt, no IO. They are imported by the CLI,
the controller, and the (future) Cockpit UI. JSON serialization is provided
for ``SessionSummary`` so the sidecar file (``<basename>.session_summary.json``)
matches the schema pinned in
``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Persistence Contract.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig

SESSION_SUMMARY_VERSION = 1


@dataclass(frozen=True)
class SelectedMeasurement:
    """One A2L measurement chosen for capture.

    ``name`` is the A2L measurement name **verbatim** — this is the
    load-bearing channel-naming contract (spec §Recorder Backend). The
    Mf4Writer MUST use ``name`` as the MF4 channel name with no prefix or
    suffix; review ``expected_channels`` round-trips depend on it.

    ``event`` is the DAQ event name (e.g. ``event_10ms``) or ``None`` for
    A2Ls that lack ``IF_DATA XCP DAQ_EVENT`` nodes.

    ``event_rate_hz`` and ``payload_bytes`` are used by the preflight
    estimators (Stage 3). They default to safe placeholders so fake/replay
    capture can run without an A2L attached.
    """

    name: str
    unit: str = ""
    event: str | None = None
    event_rate_hz: float = 100.0
    payload_bytes: int = 4
    address_hex: str | None = None


@dataclass(frozen=True)
class SessionConfig:
    """Parameters frozen at the moment ``CaptureController.start()`` runs.

    The controller copies this into ``SessionSummary`` so the sidecar file
    records exactly what was captured, not what the UI looked like later.
    """

    output_mf4: Path
    selected: tuple[SelectedMeasurement, ...]
    duration_s: float | None = None
    bitrate_bps: int = field(
        default_factory=lambda: thresholds.DEFAULT_CAN_BITRATE_BPS
    )
    ring_capacity: int = thresholds.DEFAULT_RING_CAPACITY
    segment_seconds: float | None = None
    backend: str = "fake"   # one of {"fake", "replay", "vector"}
    poll_interval_s: float = field(
        default_factory=lambda: thresholds.HEALTH_POLL_INTERVAL_S
    )
    connection_timeout_s: float = field(
        default_factory=lambda: thresholds.CONNECTION_TIMEOUT_S
    )
    transport: TransportConfig = field(default_factory=TransportConfig)

    def __post_init__(self) -> None:
        # Hard validation: output path must point at a writable directory
        # and the suffix must be ``.mf4`` — Cockpit will not silently write
        # to a missing folder or to a wrong-suffix path.
        if not isinstance(self.output_mf4, Path):
            object.__setattr__(self, "output_mf4", Path(self.output_mf4))
        if self.output_mf4.suffix.lower() != ".mf4":
            raise ValueError(
                f"output_mf4 must have a .mf4 suffix, got {self.output_mf4!s}"
            )
        if not self.selected:
            raise ValueError("SessionConfig.selected must contain at least one measurement")
        if self.duration_s is not None and self.duration_s <= 0:
            raise ValueError(f"duration_s must be positive, got {self.duration_s}")
        if self.ring_capacity <= 0:
            raise ValueError(f"ring_capacity must be positive, got {self.ring_capacity}")
        if self.backend not in {"fake", "replay", "vector"}:
            raise ValueError(f"unknown backend {self.backend!r}")

    @property
    def selected_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.selected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_mf4": str(self.output_mf4),
            "selected": [asdict(m) for m in self.selected],
            "duration_s": self.duration_s,
            "bitrate_bps": self.bitrate_bps,
            "ring_capacity": self.ring_capacity,
            "segment_seconds": self.segment_seconds,
            "backend": self.backend,
            "poll_interval_s": self.poll_interval_s,
            "connection_timeout_s": self.connection_timeout_s,
        }


@dataclass
class SessionSummary:
    """Capture-side sidecar emitted next to the finalized MF4.

    Schema pinned by spec §Persistence Contract — see that section for
    the canonical example. Field order follows the spec table.
    """

    duration_s: float = 0.0
    rx_count: int = 0
    write_count: int = 0
    queue_overflow_count: int = 0
    bus_error_count: int = 0
    dropped_frames: int = 0
    max_queue_depth: int = 0
    segments: list[dict[str, float]] = field(default_factory=list)
    output_mf4: str = ""
    auto_stop: bool = False
    warnings: list[str] = field(default_factory=list)
    version: int = SESSION_SUMMARY_VERSION

    def to_dict(self) -> dict[str, Any]:
        # Field ordering matters for human readability of the sidecar.
        # Field set is EXACT per spec §Persistence Contract — diagnostic
        # strings that the legacy ``problems[]`` list used to carry are
        # folded into ``warnings[]`` (same semantics, single field).
        return {
            "version": self.version,
            "duration_s": float(self.duration_s),
            "rx_count": int(self.rx_count),
            "write_count": int(self.write_count),
            "queue_overflow_count": int(self.queue_overflow_count),
            "bus_error_count": int(self.bus_error_count),
            "dropped_frames": int(self.dropped_frames),
            "max_queue_depth": int(self.max_queue_depth),
            "segments": list(self.segments),
            "output_mf4": self.output_mf4,
            "auto_stop": bool(self.auto_stop),
            "warnings": list(self.warnings),
        }

    def write_sidecar(self, mf4_path: Path) -> Path:
        """Write ``<basename>.session_summary.json`` next to the given MF4.

        Filename is basename-scoped (``foo.mf4`` →
        ``foo.session_summary.json``) per spec §Persistence Contract so
        multiple captures in the same directory never collide on
        diagnostics.

        ``encoding='utf-8'`` is explicit because the warnings text
        frequently carries Chinese (e.g. ``连接超时``); locale-codec
        defaults on Windows would corrupt it. See
        ``docs/lessons-learned/signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md``.
        """
        sidecar = Path(mf4_path).with_suffix(".session_summary.json")
        sidecar.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return sidecar
