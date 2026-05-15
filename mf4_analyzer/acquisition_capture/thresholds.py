"""Single source of truth for all numeric thresholds in the Acquisition Cockpit.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§Threshold Contract.

UI and capture code MUST import constants from this module — never inline a
literal threshold elsewhere. A future Settings dialog will load/save through
this module; until that exists, the module is the single source.
"""

from __future__ import annotations

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
