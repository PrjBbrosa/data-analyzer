import numpy as np
from asammdf import MDF, Signal

from mf4_analyzer.acquisition.regression import build_snapshot, compare_snapshot


def _write_mf4(path, offset=0.0):
    t = np.array([0.0, 0.01, 0.02, 0.03], dtype=float)
    y = np.array([1.0, 2.0, 3.0, 4.0], dtype=float) + offset
    mdf = MDF(version="4.10")
    mdf.append([Signal(samples=y, timestamps=t, name="sig", unit="V")])
    mdf.save(str(path), overwrite=True)
    mdf.close()


def test_build_snapshot_contains_stable_metrics(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    snapshot = build_snapshot(mf4, channels=("sig",))

    assert snapshot["rows"] == 4
    metrics = snapshot["channels"]["sig"]
    assert metrics["mean"] == 2.5
    assert metrics["max"] == 4.0
    assert metrics["len"] == 4
    assert metrics["finite_count"] == 4
    assert metrics["first_sample"] == 1.0
    assert metrics["last_sample"] == 4.0
    assert isinstance(metrics["samples_sha256"], str) and len(metrics["samples_sha256"]) == 64


def test_compare_snapshot_accepts_small_difference():
    baseline = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {
            "sig": {
                "mean": 2.5,
                "std": 1.1180339887,
                "min": 1.0,
                "max": 4.0,
                "len": 4,
                "finite_count": 4,
                "first_sample": 1.0,
                "last_sample": 4.0,
                "samples_sha256": "a" * 64,
            }
        },
    }
    current = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {
            "sig": {
                "mean": 2.50001,
                "std": 1.1180339887,
                "min": 1.0,
                "max": 4.0,
                "len": 4,
                "finite_count": 4,
                "first_sample": 1.0,
                "last_sample": 4.0,
                "samples_sha256": "a" * 64,
            }
        },
    }

    diffs = compare_snapshot(baseline, current, rel_tol=1e-3, abs_tol=1e-3)

    assert diffs == []


def test_compare_snapshot_reports_metric_drift():
    baseline = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {"sig": {"mean": 2.5}},
    }
    current = {
        "rows": 4,
        "duration_s": 0.03,
        "channels": {"sig": {"mean": 3.0}},
    }

    diffs = compare_snapshot(baseline, current, rel_tol=1e-6, abs_tol=1e-6)

    assert diffs == ["sig.mean drift: baseline=2.5 current=3.0"]


def test_compare_snapshot_reports_samples_hash_drift():
    baseline = {"rows": 4, "channels": {"sig": {"samples_sha256": "a" * 64}}}
    current = {"rows": 4, "channels": {"sig": {"samples_sha256": "b" * 64}}}

    diffs = compare_snapshot(baseline, current)

    assert any("samples_sha256" in diff for diff in diffs)
