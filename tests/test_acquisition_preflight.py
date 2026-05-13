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
