import json

import numpy as np
from asammdf import MDF, Signal

from mf4_analyzer.acquisition.preflight import analyze_mf4


def _write_mf4(path, name="sig", unit="V"):
    t = np.array([0.0, 0.01, 0.02, 0.03], dtype=float)
    y = np.array([1.0, 2.0, 3.0, 4.0], dtype=float)
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name=name, unit=unit)])
    mdf.save(str(path), overwrite=True)
    mdf.close()


def test_analyze_mf4_reports_ok_for_valid_file(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="vehicle_speed", unit="km/h")

    result = analyze_mf4(mf4, expected_channels=("vehicle_speed",))

    assert result.ok
    assert result.rows == 4
    assert "vehicle_speed" in result.channels
    assert result.missing_channels == ()
    assert abs(result.duration_s - 0.03) < 1e-12
    assert result.units["vehicle_speed"] == "km/h"


def test_analyze_mf4_flags_missing_expected_channel(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="actual")

    result = analyze_mf4(mf4, expected_channels=("missing",))

    assert not result.ok
    assert result.missing_channels == ("missing",)


def test_analyze_mf4_reports_problem_when_file_missing(tmp_path):
    result = analyze_mf4(tmp_path / "absent.mf4")

    assert not result.ok
    assert "file does not exist" in result.problems


def test_analyze_mf4_without_signal_config_keeps_legacy_behavior(tmp_path):
    """Module A contract: without signal_config_root/vehicle, expected_channels
    are interpreted as raw channel names and missing_channels reports raw names.
    """
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="actual")

    result = analyze_mf4(mf4, expected_channels=("missing",))

    assert not result.ok
    assert result.missing_channels == ("missing",)
    assert result.resolved_signals == {}


def test_analyze_mf4_reports_resolved_standard_signals(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="raw_speed", unit="km/h")
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {"vehicle": "CAR", "aliases": {"vehicle_speed": ["raw_speed"]}}
        ),
        encoding="utf-8",
    )

    result = analyze_mf4(
        mf4,
        expected_channels=("vehicle_speed",),
        signal_config_root=root,
        vehicle="CAR",
    )

    assert result.ok
    assert result.resolved_signals == {"vehicle_speed": "raw_speed"}
    assert result.missing_channels == ()
    payload = json.loads(result.to_json())
    assert payload["resolved_signals"] == {"vehicle_speed": "raw_speed"}


def test_analyze_mf4_reports_unresolved_standard_signal_as_missing(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4, name="something_else")
    root = tmp_path / "signals"
    vehicles = root / "vehicles"
    vehicles.mkdir(parents=True)
    (vehicles / "CAR.json").write_text(
        json.dumps(
            {"vehicle": "CAR", "aliases": {"vehicle_speed": ["raw_speed"]}}
        ),
        encoding="utf-8",
    )

    result = analyze_mf4(
        mf4,
        expected_channels=("vehicle_speed",),
        signal_config_root=root,
        vehicle="CAR",
    )

    assert not result.ok
    # Standard name passes through unchanged when no alias matches.
    assert result.missing_channels == ("vehicle_speed",)
    assert result.resolved_signals == {}


def test_analyze_mf4_reports_loader_failure_as_problem(tmp_path):
    """A corrupt/empty MF4 must produce ok=False with a loader-failure problem,
    not raise an exception out of analyze_mf4.
    """
    bogus = tmp_path / "bogus.mf4"
    bogus.write_bytes(b"")

    result = analyze_mf4(bogus)

    assert not result.ok
    assert any("loader failed" in p for p in result.problems)


def test_analyze_mf4_skips_sha256_when_not_requested(tmp_path, monkeypatch):
    """Hashing a multi-GB MF4 is expensive; do it only when expected_sha256 is set."""
    from mf4_analyzer.acquisition import preflight as preflight_module

    calls = {"count": 0}

    def fake_sha(_path):
        calls["count"] += 1
        return "0" * 64

    monkeypatch.setattr(preflight_module, "sha256_file", fake_sha)

    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    analyze_mf4(mf4)
    assert calls["count"] == 0, "sha256_file must not be called without expected_sha256"

    analyze_mf4(mf4, expected_sha256="ignored")
    assert calls["count"] == 1, "sha256_file must be called once when verification requested"
