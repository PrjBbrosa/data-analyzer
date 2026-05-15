"""Tests for the ``python -m mf4_analyzer.acquisition_capture`` CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mf4_analyzer.io.loader import DataLoader


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env_python = sys.executable  # use the same interpreter pytest is running on
    cmd = [env_python, "-m", "mf4_analyzer.acquisition_capture", *args]
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_cli_fake_backend_exits_zero_and_writes_mf4(tmp_path: Path):
    """The plan §Exit criteria smoke command must work end-to-end."""
    out = tmp_path / "cap.mf4"
    result = _run_cli([
        "--backend", "fake",
        "--duration", "2",
        "--output", str(out),
        "--signals", "EngSpdAvg,EngTrqAct,VehSpeedRaw",
    ])
    assert result.returncode == 0, (
        f"CLI exited {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    # MF4 finalized and loadable.
    assert out.exists()
    df, channels, units = DataLoader.load_mf4(str(out))
    assert {"EngSpdAvg", "EngTrqAct", "VehSpeedRaw"} <= set(channels)
    # Basename-scoped sidecar present and parseable.
    # Spec §Persistence Contract: ``<basename>.session_summary.json``.
    sidecar = tmp_path / "cap.session_summary.json"
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    required_keys = {
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
    }
    # Exact equality — spec §Persistence Contract pins this set.
    assert set(payload) == required_keys, (
        f"sidecar shape drift: extra={set(payload) - required_keys} "
        f"missing={required_keys - set(payload)}"
    )
    assert payload["output_mf4"] == str(out)
    assert payload["duration_s"] > 0


def test_cli_rejects_non_mf4_suffix(tmp_path: Path):
    out = tmp_path / "wrong.csv"
    result = _run_cli([
        "--backend", "fake",
        "--duration", "1",
        "--output", str(out),
    ])
    assert result.returncode != 0
    assert ".mf4 suffix" in (result.stderr + result.stdout)


def test_cli_replay_backend_works(tmp_path: Path):
    out = tmp_path / "replay.mf4"
    result = _run_cli([
        "--backend", "replay",
        "--duration", "1",
        "--output", str(out),
        "--signals", "A,B,C",
    ])
    assert result.returncode == 0, result.stderr
    assert out.exists()
    df, channels, _ = DataLoader.load_mf4(str(out))
    assert {"A", "B", "C"} <= set(channels)


def test_cli_help_lists_required_flags():
    result = _run_cli(["--help"])
    assert result.returncode == 0
    out = result.stdout
    for flag in ("--backend", "--duration", "--output", "--signals", "--segment"):
        assert flag in out
