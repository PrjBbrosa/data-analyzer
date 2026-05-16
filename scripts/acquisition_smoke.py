#!/usr/bin/env python3
"""Run the offline acquisition validation smoke suite.

Stages:
1. Unit + synthetic tests under tests/ (must exist; failure exits 1).
2. Optional local MF4 dataset smoke (skipped cleanly if manifest absent).

Cross-platform: works on macOS, Linux, Windows.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
UNIT_TESTS = [
    "tests/test_acquisition_manifest.py",
    "tests/test_acquisition_preflight.py",
    "tests/test_acquisition_regression.py",
    "tests/test_acquisition_signals.py",
    "tests/test_acquisition_smoke.py",
    "tests/synthetic",
]


def _python_executable() -> list[str]:
    env_python = os.environ.get("PYTHON")
    if env_python:
        return [env_python]
    venv = REPO_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    if venv.exists():
        return [str(venv)]
    return [sys.executable]


def _run(cmd: list[str], *, env: dict[str, str]) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=REPO_ROOT, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquisition smoke runner.")
    parser.add_argument(
        "--manifest",
        default="data/manifest.local.json",
        help="Local manifest to drive the smoke regression set.",
    )
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="Run only unit + synthetic; do not touch any MF4 dataset.",
    )
    args = parser.parse_args()

    python = _python_executable()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)

    rc = _run(python + ["-m", "pytest", *UNIT_TESTS, "-v"], env=env)
    if rc != 0:
        return 1

    if args.skip_regression:
        return 0

    manifest_path = REPO_ROOT / args.manifest
    if not manifest_path.exists():
        print(f"{manifest_path} not found; skipped local MF4 smoke dataset")
        return 0

    rc = _run(
        python
        + [
            "scripts/regression.py",
            "smoke",
            "--manifest",
            str(manifest_path),
        ],
        env=env,
    )
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
