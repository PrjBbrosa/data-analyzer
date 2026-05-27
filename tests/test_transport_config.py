"""Tests for Stage 8 ``TransportConfig`` and SessionConfig wiring."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


def _selected() -> tuple[SelectedMeasurement, ...]:
    return (SelectedMeasurement(name="EngineSpeed"),)


def test_defaults() -> None:
    tc = TransportConfig()
    assert tc.app_name == "Python"
    assert tc.channel == 0
    assert tc.can_fd is False
    assert tc.bitrate == 500_000
    assert tc.data_bitrate == 2_000_000
    assert tc.sample_point == 75.0
    assert tc.fd_sample_point == 70.0
    assert tc.timeout_s == 1.0
    assert tc.seed_and_key_dll is None


def test_frozen() -> None:
    tc = TransportConfig()
    assert dataclasses.is_dataclass(tc)
    with pytest.raises(dataclasses.FrozenInstanceError):
        tc.channel = 1  # type: ignore[misc]


def test_from_dict_round_trip() -> None:
    src = {
        "app_name": "CANalyzer",
        "channel": 1,
        "can_fd": True,
        "bitrate": 1_000_000,
        "data_bitrate": 4_000_000,
    }
    tc = TransportConfig.from_dict(src)
    assert tc.app_name == "CANalyzer"
    assert tc.can_fd is True
    assert tc.bitrate == 1_000_000
    payload = tc.to_dict()
    for key, value in src.items():
        assert payload[key] == value


def test_from_dict_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        TransportConfig.from_dict({"appname": "CANalyzer"})


def test_from_dict_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="bitrate must be >= 1"):
        TransportConfig.from_dict({"bitrate": 0})


def test_session_config_default_transport(tmp_path: Path) -> None:
    config = SessionConfig(output_mf4=tmp_path / "out.mf4", selected=_selected())

    assert config.transport == TransportConfig()
    assert "transport" not in config.to_dict()


def test_session_config_accepts_custom_transport(tmp_path: Path) -> None:
    transport = TransportConfig(app_name="CANoe", channel=2, can_fd=True)
    config = SessionConfig(
        output_mf4=tmp_path / "out.mf4",
        selected=_selected(),
        transport=transport,
    )

    assert config.transport is transport
    assert "transport" not in config.to_dict()
