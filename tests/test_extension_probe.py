"""Authorized probe child protocol: exit code + JSON, no console dependency."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import pytest

from mf4_analyzer.extensions.contract import ManagerExitCode, ReasonCode
from mf4_analyzer.extensions.locking import write_staging_auth
from mf4_analyzer.extensions.probe import (
    PROBE_ARGV_FLAGS,
    PROBE_REQUEST_FLAG,
    PROBE_RESULT_FLAG,
    ProbeTimeout,
    build_probe_request,
    child_main,
    probe_command,
    run_authorized_probe,
    standin_executable,
    write_result_json,
)
from mf4_analyzer.extensions.runtime import identify_core
from tests.test_extension_transaction import RUNTIME_ID, _write_core


def _staging(app_root: Path, txn: str = "txn-probe") -> Path:
    staging = app_root / "extensions" / ".staging" / txn
    staging.mkdir(parents=True)
    (staging / "media" / "site-packages" / "av").mkdir(parents=True)
    (staging / "media" / "site-packages" / "av" / "__init__.py").write_text("ok\n", encoding="utf-8")
    return staging


def test_probe_flags_are_documented_for_w6_hidden_group():
    assert "--extension-probe-result" in PROBE_ARGV_FLAGS
    assert all(flag.startswith("--extension-probe") for flag in PROBE_ARGV_FLAGS)


def test_child_survives_none_console_streams(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mf4_analyzer.extensions.probe._verify_inherited_grant", lambda *args: None)
    monkeypatch.setattr("mf4_analyzer.extensions.probe.evaluate_staging_probe",
                        lambda request, staging: {"ok": True, "components": request["components"]})
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-1"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id=identify_core(app_root).core_build_id,
        runtime_id=RUNTIME_ID,
        transaction_id="txn-probe",
        components=["media"],
        package_hashes=["aa" * 32],
        staging_relpath=".staging/txn-probe",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    result_path = staging / "result.json"
    write_result_json(request_path, request)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    code = child_main(
        [
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(result_path),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ]
    )
    assert code == ManagerExitCode.SUCCESS
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["components"] == ["media"]


def test_env_skip_is_rejected(tmp_path: Path, monkeypatch):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-2"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id=identify_core(app_root).core_build_id,
        runtime_id=RUNTIME_ID,
        transaction_id="txn-probe",
        components=["media"],
        package_hashes=["aa" * 32],
        staging_relpath=".staging/txn-probe",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    result_path = staging / "result.json"
    write_result_json(request_path, request)
    monkeypatch.setenv("TRACELAB_SKIP_LOCK", "1")
    code = child_main(
        [
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(result_path),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ]
    )
    assert code == ManagerExitCode.VERIFY_OR_PROBE
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["reason_code"] == ReasonCode.VERIFICATION_FAILED


def test_joint_probe_rejects_unverified_package_trees(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mf4_analyzer.extensions.probe._verify_inherited_grant", lambda *args: None)
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-3"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id=identify_core(app_root).core_build_id,
        runtime_id=RUNTIME_ID,
        transaction_id="txn-probe",
        components=["media", "matlab"],
        package_hashes=["aa" * 32, "bb" * 32],
        staging_relpath=".staging/txn-probe",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    result_path = staging / "result.json"
    write_result_json(request_path, request)
    code = child_main(
        [
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(result_path),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ]
    )
    assert code == ManagerExitCode.VERIFY_OR_PROBE
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["reason_code"] == ReasonCode.PROBE_FAILED


def test_result_path_cannot_alias_exe(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    from mf4_analyzer.extensions.probe import ProbeError, assert_result_path_safe

    with pytest.raises(ProbeError) as caught:
        assert_result_path_safe(app_root / "TraceLabAnalyzer.exe", app_root=app_root)
    assert caught.value.exit_code == ManagerExitCode.BAD_ARGS


def test_timeout_reaps_only_the_probe_child(tmp_path: Path):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-4"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id=identify_core(app_root).core_build_id,
        runtime_id=RUNTIME_ID,
        transaction_id="txn-probe",
        components=["media"],
        package_hashes=["aa" * 32],
        staging_relpath=".staging/txn-probe",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    result_path = staging / "result.json"
    write_result_json(request_path, request)
    command = probe_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        request_path=request_path,
        result_path=result_path,
        staging_dir=staging,
        staging_nonce=nonce,
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    import subprocess

    # Ensure the stand-in can import the package.
    assert command[0] == sys.executable
    with pytest.raises(ProbeTimeout):
        run_authorized_probe(command, timeout_seconds=0.3, result_path=result_path, app_root=app_root)
    del env
    del subprocess


def test_real_launcher_routes_probe_flags_to_child_main(tmp_path, monkeypatch):
    """Sibling of the protocol tests: V1.py must dispatch the W5 flag family."""

    import runpy

    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-launcher"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id=identify_core(app_root).core_build_id,
        runtime_id=RUNTIME_ID,
        transaction_id="txn-probe",
        components=["media"],
        package_hashes=["aa" * 32],
        staging_relpath=".staging/txn-probe",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    result_path = staging / "result.json"
    write_result_json(request_path, request)
    routed: list[list[str]] = []

    def trap(argv=None):
        routed.append(list(argv or []))
        return ManagerExitCode.SUCCESS

    monkeypatch.setattr("mf4_analyzer.extensions.probe.child_main", trap)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(result_path),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ],
    )
    launcher = Path(__file__).resolve().parents[1] / "MF4 Data Analyzer V1.py"
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(launcher), run_name="__main__")
    assert stopped.value.code == ManagerExitCode.SUCCESS
    assert routed
    assert PROBE_REQUEST_FLAG in routed[0]
    assert str(request_path) in routed[0]
