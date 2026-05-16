import inspect
import json
import sys

import numpy as np
import pytest

from mf4_analyzer.acquisition.regression import build_snapshot, compare_snapshot
from tests._helpers.mf4_factory import write_single_channel_mf4


def _write_mf4(path, offset=0.0):
    samples = np.array([1.0, 2.0, 3.0, 4.0], dtype=float) + offset
    write_single_channel_mf4(path, name="sig", samples=samples)


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


def test_build_snapshot_raises_when_requested_channel_absent(tmp_path):
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    with pytest.raises(ValueError, match="requested channel not in MF4: missing"):
        build_snapshot(mf4, channels=("missing",))


def test_build_snapshot_silently_excludes_time_when_passed(tmp_path):
    """Even if caller passes 'Time', it must not appear as a tracked channel."""
    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)

    snapshot = build_snapshot(mf4, channels=("sig", "Time"))

    assert "Time" not in snapshot["channels"]
    assert "sig" in snapshot["channels"]


def test_compare_snapshot_reports_new_channel_in_current():
    baseline = {"rows": 4, "duration_s": 0.0, "channels": {"sig": {"mean": 1.0}}}
    current = {
        "rows": 4,
        "duration_s": 0.0,
        "channels": {"sig": {"mean": 1.0}, "extra": {"mean": 9.0}},
    }

    diffs = compare_snapshot(baseline, current, rel_tol=1e-6, abs_tol=1e-6)

    assert any("extra" in d and "new in current" in d for d in diffs)


def test_regression_cli_reports_build_snapshot_value_error(tmp_path, monkeypatch, capsys):
    import scripts.regression as regression_cli

    mf4 = tmp_path / "sample.mf4"
    _write_mf4(mf4)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [
                    {
                        "id": "case",
                        "path": str(mf4),
                        "sets": ["smoke"],
                        "required": False,
                        "expected_channels": ["missing"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "regression.py",
            "smoke",
            "--manifest",
            str(manifest),
            "--snapshot-dir",
            str(tmp_path / "snapshots"),
        ],
    )

    exit_code = regression_cli.main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "case: FAIL" in out
    assert "requested channel not in MF4: missing" in out


def test_compare_snapshot_treats_nan_pair_as_equal():
    baseline = {
        "rows": 4,
        "duration_s": 0.0,
        "channels": {"sig": {"mean": float("nan"), "std": float("nan")}},
    }
    current = {
        "rows": 4,
        "duration_s": 0.0,
        "channels": {"sig": {"mean": float("nan"), "std": float("nan")}},
    }

    diffs = compare_snapshot(baseline, current)

    assert diffs == []


def test_samples_sha256_is_byte_order_stable():
    """Hash must be stable across CPU architectures for little-endian float64."""
    from mf4_analyzer.acquisition.regression import _samples_sha256

    arr = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
    expected = "6bab56d2f81d4b5a2dbf102bf6a6ff7d5211a475fc5f97813f977e8ba714b07d"

    assert _samples_sha256(arr) == expected


def test_samples_sha256_uses_explicit_little_endian():
    """Inspect implementation to guard against the native-byte-order path."""
    from mf4_analyzer.acquisition import regression

    src = inspect.getsource(regression._samples_sha256)
    assert "<f8" in src or "little" in src.lower(), (
        "samples sha256 must specify little-endian explicitly, not rely on host"
    )
