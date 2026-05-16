"""Tests for ``SessionConfig`` / ``SelectedMeasurement`` / ``SessionSummary``.

Pins:
- ``SessionConfig`` rejects bad suffixes, empty selection, bad duration.
- default thresholds (bitrate, ring capacity) match ``thresholds`` module.
- ``SessionSummary.write_sidecar`` writes valid UTF-8 JSON next to the MF4.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.session import (
    SESSION_SUMMARY_VERSION,
    SelectedMeasurement,
    SessionConfig,
    SessionSummary,
)


def _three_signals() -> tuple[SelectedMeasurement, ...]:
    return (
        SelectedMeasurement(name="EngSpdAvg", unit="rpm"),
        SelectedMeasurement(name="EngTrqAct", unit="Nm"),
        SelectedMeasurement(name="VehSpeedRaw", unit="km/h"),
    )


def test_session_config_accepts_minimum(tmp_path):
    config = SessionConfig(
        output_mf4=tmp_path / "out.mf4",
        selected=_three_signals(),
    )
    # Defaults pulled from thresholds module — pin them explicitly so a
    # silent change in thresholds.py surfaces here.
    assert config.bitrate_bps == thresholds.DEFAULT_CAN_BITRATE_BPS
    assert config.ring_capacity == thresholds.DEFAULT_RING_CAPACITY
    assert config.poll_interval_s == thresholds.HEALTH_POLL_INTERVAL_S
    assert config.connection_timeout_s == thresholds.CONNECTION_TIMEOUT_S
    assert config.backend == "fake"
    assert config.duration_s is None


def test_session_config_rejects_non_mf4_suffix(tmp_path):
    with pytest.raises(ValueError, match=".mf4 suffix"):
        SessionConfig(
            output_mf4=tmp_path / "out.csv",
            selected=_three_signals(),
        )


def test_session_config_rejects_empty_selection(tmp_path):
    with pytest.raises(ValueError, match="at least one measurement"):
        SessionConfig(output_mf4=tmp_path / "out.mf4", selected=())


def test_session_config_rejects_non_positive_duration(tmp_path):
    with pytest.raises(ValueError, match="duration_s"):
        SessionConfig(
            output_mf4=tmp_path / "out.mf4",
            selected=_three_signals(),
            duration_s=0,
        )


def test_session_config_rejects_unknown_backend(tmp_path):
    with pytest.raises(ValueError, match="unknown backend"):
        SessionConfig(
            output_mf4=tmp_path / "out.mf4",
            selected=_three_signals(),
            backend="usb-can",
        )


def test_session_config_accepts_string_path(tmp_path):
    # User-passed strings must be coerced to Path.
    config = SessionConfig(
        output_mf4=str(tmp_path / "out.mf4"),
        selected=_three_signals(),
    )
    assert isinstance(config.output_mf4, Path)


def test_session_config_selected_names(tmp_path):
    config = SessionConfig(
        output_mf4=tmp_path / "out.mf4",
        selected=_three_signals(),
    )
    assert config.selected_names == ("EngSpdAvg", "EngTrqAct", "VehSpeedRaw")


def test_session_config_to_dict_round_trip_keys(tmp_path):
    config = SessionConfig(
        output_mf4=tmp_path / "out.mf4",
        selected=_three_signals(),
        duration_s=10.0,
    )
    payload = config.to_dict()
    assert set(payload) == {
        "output_mf4",
        "selected",
        "duration_s",
        "bitrate_bps",
        "ring_capacity",
        "segment_seconds",
        "backend",
        "poll_interval_s",
        "connection_timeout_s",
    }
    assert payload["selected"][0]["name"] == "EngSpdAvg"


# Spec §Persistence Contract: this is the EXACT field set. No extras,
# no omissions. Kept as a module-level constant so the in-memory and
# on-disk exact-key tests share the same source of truth.
EXPECTED_SIDECAR_KEYS: tuple[str, ...] = (
    "version",
    "duration_s",
    "rx_count",
    "write_count",
    "queue_overflow_count",
    "bus_error_count",
    "dropped_frames",
    "max_queue_depth",
    "segments",
    "output_mf4",
    "auto_stop",
    "warnings",
)


def test_session_summary_default_shape_matches_spec():
    summary = SessionSummary()
    payload = summary.to_dict()
    # Exact equality — spec §Persistence Contract pins the field set.
    assert set(payload) == set(EXPECTED_SIDECAR_KEYS)
    assert payload["version"] == SESSION_SUMMARY_VERSION


def test_session_summary_exact_key_set(tmp_path):
    """Spec §Persistence Contract: sidecar JSON has EXACTLY these keys.

    Asserts on the on-disk artifact (not just ``to_dict()``) because
    that is the contract Stage 5 / external tooling reads. A regression
    that re-adds ``problems`` would fail loudly here.
    """
    summary = SessionSummary(
        duration_s=2.0,
        rx_count=10,
        write_count=10,
        output_mf4=str(tmp_path / "out.mf4"),
        warnings=["ring buffer hit 90% for 3s"],
    )
    sidecar = summary.write_sidecar(tmp_path / "out.mf4")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert set(payload) == set(EXPECTED_SIDECAR_KEYS), (
        f"sidecar shape drift: extra={set(payload) - set(EXPECTED_SIDECAR_KEYS)} "
        f"missing={set(EXPECTED_SIDECAR_KEYS) - set(payload)}"
    )


def test_session_summary_write_sidecar_uses_utf8(tmp_path):
    """The sidecar must round-trip Chinese strings verbatim."""
    summary = SessionSummary(
        duration_s=1.23,
        rx_count=100,
        warnings=["连接超时", "drop oldest"],
        output_mf4=str(tmp_path / "out.mf4"),
    )
    sidecar = summary.write_sidecar(tmp_path / "out.mf4")
    # Basename-scoped: ``out.mf4`` -> ``out.session_summary.json``
    # (spec §Persistence Contract).
    assert sidecar == tmp_path / "out.session_summary.json"
    # Read back using explicit UTF-8 — locale defaults on Windows
    # (cp936/cp1252) would corrupt the Chinese warning otherwise.
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["warnings"][0] == "连接超时"
    assert payload["duration_s"] == 1.23
    assert payload["rx_count"] == 100
