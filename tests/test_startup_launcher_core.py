"""Compile the portable launcher core and check it against the Python contract."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mf4_analyzer.startup_launch_policy import PASSTHROUGH_FLAGS, should_present_native_panel
from mf4_analyzer.startup_visual_contract import tip_index_for_elapsed

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "native" / "startup_launcher"
SOURCES = [
    CORE / "tests" / "test_core.cc",
    CORE / "tip_clock.cc",
    CORE / "json_value.cc",
    CORE / "protocol.cc",
    CORE / "session_machine.cc",
    CORE / "launch_dispatch.cc",
]


def test_native_core_matches_python_tip_and_dispatch(tmp_path):
    compiler = shutil.which("clang++")
    if compiler is None:
        pytest.skip("clang++ is not available for the portable launcher core")
    tips = []
    for initial, elapsed in (
        (0, 0),
        (0, 4999),
        (0, 5000),
        (0, 9999),
        (0, 10000),
        (0, 12000),
        (25, 5000),
        (3, 26000),
    ):
        tips.append(
            {
                "initial": initial,
                "elapsed": elapsed,
                "expect": tip_index_for_elapsed(initial, elapsed),
            }
        )
    panel_inputs = [
        ([], {}),
        (["--help"], {}),
        (["-h"], {}),
        (["data.mf4"], {}),
        ([], {"TRACELAB_STARTUP_SPLASH": "0", "TRACELAB_STARTUP_BACKEND": "native"}),
        ([], {"TRACELAB_STARTUP_BACKEND": "qt"}),
        ([], {"TRACELAB_STARTUP_BACKEND": "none"}),
        ([], {"TRACELAB_STARTUP_BACKEND": "native"}),
        (["--not-a-real-option"], {"TRACELAB_STARTUP_BACKEND": "native"}),
        ([], {"QT_QPA_PLATFORM": "offscreen"}),
        ([], {"TRACELAB_LAYOUT_PROBE": "1"}),
        (["--startup-splash-child", "x"], {}),
        (["file.mf4", "--help"], {}),
    ]
    for flag in PASSTHROUGH_FLAGS:
        panel_inputs.append(([flag], {}))
    panels = []
    for argv, env in panel_inputs:
        panels.append(
            {
                "argv": argv,
                "env": env,
                "expect": should_present_native_panel(list(argv), dict(env)),
            }
        )
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps({"tips": tips, "panels": panels}), encoding="utf-8")
    binary = tmp_path / "launcher_core_test"
    compile_cmd = [
        compiler,
        "-std=c++17",
        "-I",
        str(CORE),
        "-o",
        str(binary),
        *[str(path) for path in SOURCES],
    ]
    compiled = subprocess.run(compile_cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run(
        [str(binary), str(fixture)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    assert "ok" in ran.stdout
