"""Settings override tests for Acquisition Cockpit thresholds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_capture.config_store import ConfigSchemaError
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    HwHealth,
    level_can,
    level_hw,
)


@pytest.fixture(autouse=True)
def _isolated_threshold_state(monkeypatch, tmp_path):
    """Keep threshold globals and per-user paths isolated per test."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    thresholds.reset_defaults()
    yield
    thresholds.reset_defaults()


def _full_payload() -> dict[str, object]:
    return {
        "version": 1,
        "thresholds": {
            key: getattr(thresholds, key)
            for key in sorted(thresholds.VALID_THRESHOLD_KEYS)
        },
    }


def test_settings_schema_round_trip(tmp_path):
    path = tmp_path / "nested" / "settings.json"

    thresholds.save_user_settings(_full_payload(), path=path)
    loaded = thresholds.load_user_settings(path=path)

    assert set(loaded) == thresholds.VALID_THRESHOLD_KEYS
    assert loaded["CAN_LOAD_GREEN_MAX_PCT"] == 60.0
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == 1
    assert set(stored["thresholds"]) == thresholds.VALID_THRESHOLD_KEYS


def test_settings_apply_overrides_changes_level_helpers():
    assert level_can(CanHealth(bus_load_pct=15.0)) == "green"

    thresholds.apply_overrides({"CAN_LOAD_GREEN_MAX_PCT": 10.0})

    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 10.0
    assert level_can(CanHealth(bus_load_pct=15.0)) == "yellow"


def test_settings_reject_unknown_threshold_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"version": 1, "thresholds": {"NOT_A_THRESHOLD": 1.0}}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigSchemaError, match="NOT_A_THRESHOLD"):
        thresholds.load_user_settings(path=path)

    with pytest.raises(ConfigSchemaError, match="NOT_A_THRESHOLD"):
        thresholds.apply_overrides({"NOT_A_THRESHOLD": 1.0})


def test_settings_reject_non_numeric_threshold_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "thresholds": {"CAN_LOAD_GREEN_MAX_PCT": "fast"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigSchemaError, match="CAN_LOAD_GREEN_MAX_PCT"):
        thresholds.load_user_settings(path=path)

    with pytest.raises(ConfigSchemaError, match="CAN_LOAD_GREEN_MAX_PCT"):
        thresholds.apply_overrides({"CAN_LOAD_GREEN_MAX_PCT": object()})


def test_default_user_settings_path_uses_monkeypatched_home(tmp_path):
    assert thresholds.default_user_settings_path() == (
        tmp_path / ".acquisition-cockpit" / "settings.json"
    )


def test_acquisition_capture_package_import_applies_user_overrides():
    thresholds.save_user_settings(
        {
            "version": thresholds.SETTINGS_VERSION,
            "thresholds": {"CAN_LOAD_GREEN_MAX_PCT": 11.0},
        }
    )
    thresholds.reset_defaults()

    import importlib
    import mf4_analyzer.acquisition_capture as acquisition_capture

    importlib.reload(acquisition_capture)

    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 11.0


def test_acquisition_capture_package_import_applies_session_config_defaults():
    thresholds.save_user_settings(
        {
            "version": thresholds.SETTINGS_VERSION,
            "thresholds": {
                "DEFAULT_CAN_BITRATE_BPS": 123_456,
                "HEALTH_POLL_INTERVAL_S": 1.25,
                "CONNECTION_TIMEOUT_S": 9.0,
            },
        }
    )
    thresholds.reset_defaults()

    import importlib
    import mf4_analyzer.acquisition_capture as acquisition_capture

    importlib.reload(acquisition_capture)

    config = acquisition_capture.SessionConfig(
        output_mf4=Path("/tmp/capture.mf4"),
        selected=(acquisition_capture.SelectedMeasurement(name="EngineSpeed"),),
    )
    assert config.bitrate_bps == 123_456
    assert config.poll_interval_s == 1.25
    assert config.connection_timeout_s == 9.0


def test_health_level_default_poll_interval_reads_current_threshold():
    thresholds.apply_overrides({"HEALTH_POLL_INTERVAL_S": 5.0})

    snap = HwHealth(
        ok=True,
        driver_version="test",
        channel_count=1,
        last_probe_ts=0.0,
    )

    assert level_hw(snap, now=6.0) == "green"


def test_acquisition_capture_package_import_silent_on_corrupt_settings(tmp_path):
    settings_dir = tmp_path / ".acquisition-cockpit"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_bytes(b"{not json")

    import importlib
    import mf4_analyzer.acquisition_capture as acquisition_capture

    importlib.reload(acquisition_capture)

    # Corrupt settings file is swallowed; defaults retained.
    assert thresholds.CAN_LOAD_GREEN_MAX_PCT == 60.0
