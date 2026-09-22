from pathlib import Path
import json
import sys

import pytest

from mf4_analyzer.extensions.contract import (
    generate_core_files,
    generate_discovery_envelope,
    generate_package_manifest,
    sha256_hex,
)
from mf4_analyzer.frozen_evidence_paths import UnsafeEvidencePath


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from verify_extension_installation import (  # noqa: E402
    is_frozen_executable_claim,
    main as verify_main,
    reject_evidence_target,
    verify,
)


def _write(path: Path, data: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    return path


def _core_and_package(tmp_path: Path) -> tuple[Path, Path]:
    digest = sha256_hex(b"exe")
    files = generate_core_files(
        [{"relpath": "TraceLabAnalyzer.exe", "size": 3, "sha256": digest}]
    )
    from mf4_analyzer.extensions.contract import parse_core_files
    from mf4_analyzer.extensions.state import core_build_id_for_files

    parsed = parse_core_files(files)
    envelope = generate_discovery_envelope(
        exe_relpath="TraceLabAnalyzer.exe",
        core_build_id=core_build_id_for_files(parsed),
        runtime_id="rt1-0123456789abcdef0123456789abcdef",
        component_capabilities={"media": "1", "matlab": "1"},
        min_manager_version="1.0.0",
        manager_download_page="https://example.invalid/tracelab/extension-manager",
        app_version="v8.3.1",
        exe_sha256=digest,
        core_files_digest=parsed.digest,
    )
    core_json = _write(tmp_path / "core.json", json.dumps(envelope, indent=2) + "\n")
    _write(tmp_path / "core-files.json", json.dumps(files, indent=2) + "\n")
    package = generate_package_manifest(
        component="media",
        package_revision=1,
        runtime_id=envelope["runtime_id"],
        component_api="1",
        min_manager_version="1.0.0",
        python_tag="cp311",
        platform_tag="win_amd64",
        module_roots=["site-packages/av"],
        dll_directories=[],
        dependency_ownership={"av": "media"},
        files=[
            {
                "relpath": "site-packages/av/__init__.py",
                "size": 4,
                "sha256": sha256_hex(b"data"),
            }
        ],
        max_extract_bytes=4096,
        probe_type="media_wav_mp4_v1",
        required_features=[
            "store_layout_v1",
            "native_probe_v1",
            "file_manifest_sha256",
        ],
    )
    package_json = _write(tmp_path / "package.json", json.dumps(package, indent=2) + "\n")
    return core_json, package_json


def test_evidence_alias_of_exe_is_rejected_before_work(tmp_path):
    exe = _write(tmp_path / "probe.exe", b"not-frozen")
    with pytest.raises(UnsafeEvidencePath):
        reject_evidence_target(exe, exe=exe)
    code, payload = verify(
        mode="combination-contract",
        exe=exe,
        core_json=tmp_path / "core.json",
        evidence_json=exe,
    )
    assert code == 2
    assert payload["ok"] is False
    assert exe.read_bytes() == b"not-frozen"


def test_cli_rejects_exe_alias_as_usage_error(tmp_path):
    exe = _write(tmp_path / "probe.exe", b"not-frozen")
    with pytest.raises(SystemExit):
        verify_main(
            ["--mode", "base-expected-missing", "--exe", str(exe), "--evidence-json", str(exe)]
        )
    assert exe.read_bytes() == b"not-frozen"


def test_combination_contract_expected_missing_without_package(tmp_path):
    core_json, package_json = _core_and_package(tmp_path)
    del package_json
    evidence = tmp_path / "evidence.json"
    code, payload = verify(
        mode="combination-contract",
        core_json=core_json,
        app_root=tmp_path,
        expect_missing=True,
        evidence_json=evidence,
    )
    assert code == 0
    assert payload["ok"] is True
    assert payload["reason_code"] == "COMPONENT_MISSING"
    assert payload["wav_ok"] is False
    assert payload["mp4_ok"] is False
    assert payload["frozen_media_read"] is False


def test_combination_contract_installed_package_is_load_compatible(tmp_path):
    core_json, package_json = _core_and_package(tmp_path)
    code, payload = verify(
        mode="combination-contract",
        core_json=core_json,
        package_json=package_json,
        expect_missing=False,
    )
    assert code == 0
    assert payload["ok"] is True
    assert payload["allowed"] is True
    assert payload["wav_ok"] is False


def test_fallback_contract_keeps_remaining_and_marks_removed_missing(tmp_path):
    core_json, package_json = _core_and_package(tmp_path)
    code, payload = verify(
        mode="fallback-contract",
        core_json=core_json,
        remaining_package_json=package_json,
        removed_component="matlab",
    )
    assert code == 0
    assert payload["ok"] is True
    assert payload["remaining"]["allowed"] is True
    assert payload["missing"]["reason_code"] == "COMPONENT_MISSING"
    assert payload["wav_ok"] is False


def test_placeholder_exe_does_not_claim_wav_mp4_success(tmp_path):
    exe = _write(tmp_path / "TraceLabAnalyzer.exe", b"fake")
    assert is_frozen_executable_claim(exe) is False
    code, payload = verify(mode="installed-available", exe=exe)
    assert code == 2
    assert payload["ok"] is False
    assert payload["wav_ok"] is False
    assert payload["mp4_ok"] is False
    assert "refusing to claim" in payload["note"]


def test_mz_header_still_does_not_invent_a_successful_read(tmp_path):
    exe = _write(tmp_path / "TraceLabAnalyzer.exe", b"MZ" + (b"\x00" * 80))
    assert is_frozen_executable_claim(exe) is True
    code, payload = verify(mode="base-expected-missing", exe=exe)
    assert code == 14
    assert payload["ok"] is False
    assert payload["wav_ok"] is False
    assert payload["frozen_media_read"] is False


def test_legal_evidence_json_is_written_for_source_contract(tmp_path):
    core_json, _package_json = _core_and_package(tmp_path)
    evidence = tmp_path / "out" / "evidence.json"
    code = verify_main(
        [
            "--mode",
            "combination-contract",
            "--core-json",
            str(core_json),
            "--expect-missing",
            "--evidence-json",
            str(evidence),
            "--app-root",
            str(tmp_path),
        ]
    )
    assert code == 0
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["wav_ok"] is False
