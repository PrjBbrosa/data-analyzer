"""Contract schemas, reason codes, SemVer, and runtime_id isolation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mf4_analyzer.app_meta import APP_VERSION
from mf4_analyzer.extensions.contract import (
    DISCOVERY_SCHEMA_V1,
    ExtensionError,
    MANAGER_EXIT_CODES,
    ManagerExitCode,
    PRODUCT_ID,
    REASON_CODES,
    ReasonCode,
    SemVer,
    compare_semver,
    compute_runtime_id,
    dumps_json,
    exit_code_for_reason,
    generate_discovery_envelope,
    generate_package_manifest,
    parse_active_state,
    parse_core_files,
    parse_discovery_envelope,
    parse_manager_status_v1,
    parse_package_manifest,
    parse_transaction_log,
    sha256_hex,
    validate_relative_ref,
)
from mf4_analyzer.extensions.runtime_recipe import (
    RUNTIME_EXCLUDED_FIELDS,
    RUNTIME_RECIPE,
    assert_recipe_json_matches_embedded,
    load_runtime_recipe,
)
from mf4_analyzer.extensions.state import bind_core_identity, core_build_id_for_files


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "extensions"

_RUNTIME_KWARGS = dict(
    python_implementation="CPython",
    python_version="3.11.9",
    python_abi="cp311",
    arch="win-amd64",
    numpy_version="1.26.4",
    numpy_abi="cp311",
    core_shared_libraries=("python", "numpy"),
)


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_reason_codes_are_the_frozen_set_ui_must_match():
    assert REASON_CODES == {
        "COMPONENT_MISSING",
        "COMPONENT_INCOMPATIBLE",
        "COMPONENT_CORRUPT",
        "MANAGER_TOO_OLD",
        "PROTOCOL_UNSUPPORTED",
        "NO_COMPATIBLE_PACKAGE",
        "CORE_INCONSISTENT",
        "APP_RUNNING",
        "UNSUPPORTED_FILESYSTEM",
        "VERIFICATION_FAILED",
        "PROBE_FAILED",
        "TRANSACTION_RECOVERY_REQUIRED",
    }
    chinese = ExtensionError(ReasonCode.MANAGER_TOO_OLD, "扩展管理器过旧，请更新")
    assert chinese.reason_code == "MANAGER_TOO_OLD"
    assert chinese.reason_code != str(chinese)


def test_manager_exit_codes_match_spec():
    assert ManagerExitCode.SUCCESS == 0
    assert ManagerExitCode.BAD_ARGS == 2
    assert ManagerExitCode.CANCELLED == 3
    assert ManagerExitCode.TARGET_OR_COMPAT == 10
    assert ManagerExitCode.MANAGER_OR_PROTOCOL_TOO_OLD == 11
    assert ManagerExitCode.NETWORK_OR_METADATA == 12
    assert ManagerExitCode.BUSY_FS_OR_PERM == 13
    assert ManagerExitCode.VERIFY_OR_PROBE == 14
    assert ManagerExitCode.RECOVERY_REQUIRED == 15
    assert MANAGER_EXIT_CODES == {0, 2, 3, 10, 11, 12, 13, 14, 15}
    assert exit_code_for_reason(ReasonCode.CORE_INCONSISTENT) == 10
    assert exit_code_for_reason(ReasonCode.MANAGER_TOO_OLD) == 11
    assert exit_code_for_reason(ReasonCode.PROTOCOL_UNSUPPORTED) == 11
    assert exit_code_for_reason(ReasonCode.VERIFICATION_FAILED) == 14
    assert exit_code_for_reason(ReasonCode.PROBE_FAILED) == 14
    assert exit_code_for_reason(ReasonCode.TRANSACTION_RECOVERY_REQUIRED) == 15


def test_semver_is_not_dictionary_or_lexicographic_order():
    assert "1.10.0" < "1.2.0"
    assert "10.0.0" < "9.0.0"
    assert compare_semver("1.10.0", "1.2.0") == 1
    assert compare_semver("10.0.0", "9.0.0") == 1
    assert compare_semver("1.0.0", "1.0.0") == 0
    assert SemVer.parse("1.0.0-alpha") < SemVer.parse("1.0.0")
    with pytest.raises(ExtensionError) as info:
        SemVer.parse(APP_VERSION)
    assert info.value.reason_code == ReasonCode.PROTOCOL_UNSUPPORTED
    with pytest.raises(ExtensionError):
        SemVer.parse("1.02.0")


def test_runtime_id_ignores_app_version_source_hash_and_build_time():
    baseline = compute_runtime_id(**_RUNTIME_KWARGS)
    shifted = compute_runtime_id(
        **_RUNTIME_KWARGS,
        app_version="v9.9.9",
        source_hash="abc123",
        build_timestamp="2026-09-21T00:00:00Z",
        exe_sha256="f" * 64,
        core_build_id="cb1-changed",
    )
    assert baseline == shifted
    assert baseline.startswith("rt1-")
    for field in RUNTIME_EXCLUDED_FIELDS:
        assert field in load_runtime_recipe()["excluded_fields"]


def test_runtime_id_changes_when_python_numpy_or_arch_changes():
    baseline = compute_runtime_id(**_RUNTIME_KWARGS)
    python_changed = compute_runtime_id(**{**_RUNTIME_KWARGS, "python_version": "3.11.8"})
    numpy_changed = compute_runtime_id(**{**_RUNTIME_KWARGS, "numpy_version": "1.26.5"})
    arch_changed = compute_runtime_id(**{**_RUNTIME_KWARGS, "arch": "win-arm64"})
    assert python_changed != baseline
    assert numpy_changed != baseline
    assert arch_changed != baseline


def test_published_runtime_recipe_matches_embedded_copy():
    assert_recipe_json_matches_embedded()
    assert RUNTIME_RECIPE["match_policy"] == "exact"
    assert RUNTIME_RECIPE["loader_contract_version"] == 1


def test_valid_core_fixture_uses_exe_name_from_json_not_tracelab_exe():
    envelope = parse_discovery_envelope(_load("core-valid.json"))
    files = parse_core_files(_load("core-files-valid.json"))
    identity = bind_core_identity(envelope, files)

    assert envelope.discovery_schema == DISCOVERY_SCHEMA_V1
    assert envelope.product_id == PRODUCT_ID
    assert envelope.exe_relpath == "TraceLabAnalyzer.exe"
    assert envelope.exe_relpath != "TraceLab.exe"
    assert identity.exe_relpath == envelope.exe_relpath
    assert identity.core_build_id == core_build_id_for_files(files)

    generated = generate_discovery_envelope(
        exe_relpath="Custom Analyzer.exe",
        core_build_id=identity.core_build_id,
        runtime_id=envelope.runtime_id,
        component_capabilities={"media": "1", "matlab": "1"},
        min_manager_version="1.0.0",
        manager_download_page=envelope.manager_download_page,
    )
    text = dumps_json(generated)
    assert "Custom Analyzer.exe" in text
    assert "TraceLab.exe" not in text
    assert generated["app_version"] == APP_VERSION


def test_core_and_package_fixtures_cover_missing_and_unknown_major():
    with pytest.raises(ExtensionError) as missing_core:
        parse_discovery_envelope(_load("core-missing-fields.json"))
    assert missing_core.value.reason_code == ReasonCode.PROTOCOL_UNSUPPORTED

    with pytest.raises(ExtensionError) as missing_pkg:
        parse_package_manifest(_load("package-missing-fields.json"))
    assert missing_pkg.value.reason_code == ReasonCode.PROTOCOL_UNSUPPORTED

    with pytest.raises(ExtensionError) as unknown_major:
        parse_package_manifest(_load("package-unknown-major.json"))
    assert unknown_major.value.reason_code == ReasonCode.PROTOCOL_UNSUPPORTED


def test_unknown_required_feature_is_rejected_optional_fields_are_ignored():
    with pytest.raises(ExtensionError) as info:
        parse_package_manifest(_load("package-unknown-required-feature.json"))
    assert info.value.reason_code == ReasonCode.PROTOCOL_UNSUPPORTED
    assert "teleport_v9" in str(info.value)

    package = parse_package_manifest(_load("package-optional-fields.json"))
    assert package.component == "media"
    assert package.extras["blurb"] == "音视频支持"
    assert "homepage" in package.extras


def test_active_json_rejects_absolute_paths_and_parent_escape():
    state = parse_active_state(_load("active-valid.json"))
    assert state.generation == 4
    selection = next(state.iter_selections())
    assert not selection.package_relpath.startswith("/")
    assert ".." not in selection.package_relpath.split("/")

    with pytest.raises(ExtensionError) as absolute:
        parse_active_state(_load("active-absolute-path.json"))
    assert absolute.value.reason_code == ReasonCode.VERIFICATION_FAILED

    with pytest.raises(ExtensionError) as parent:
        parse_active_state(_load("active-parent-escape.json"))
    assert parent.value.reason_code == ReasonCode.VERIFICATION_FAILED

    with pytest.raises(ExtensionError):
        validate_relative_ref("/tmp/outside")
    with pytest.raises(ExtensionError):
        validate_relative_ref(r"C:\TraceLab\store")

    with pytest.raises(ExtensionError) as staging:
        parse_active_state(
            {
                "schema": 1,
                "generation": 1,
                "by_runtime": {
                    "rt1-0123456789abcdef0123456789abcdef": {
                        "media": {
                            "package_relpath": ".STAGING/txn-1",
                            "package_sha256": "d" * 64,
                        }
                    }
                },
            }
        )
    assert staging.value.reason_code == ReasonCode.VERIFICATION_FAILED

    with pytest.raises(ExtensionError) as cache:
        parse_active_state(
            {
                "schema": 1,
                "generation": 1,
                "by_runtime": {
                    "rt1-0123456789abcdef0123456789abcdef": {
                        "media": {
                            "package_relpath": "CACHE/downloads/pkg",
                            "package_sha256": "d" * 64,
                        }
                    }
                },
            }
        )
    assert cache.value.reason_code == ReasonCode.VERIFICATION_FAILED

    with pytest.raises(ExtensionError) as wrong_component:
        parse_active_state(
            {
                "schema": 1,
                "generation": 1,
                "by_runtime": {
                    "rt1-0123456789abcdef0123456789abcdef": {
                        "media": {
                            "package_relpath": (
                                "store/rt1-0123456789abcdef0123456789abcdef/matlab/"
                                + ("d" * 64)
                            ),
                            "package_sha256": "d" * 64,
                        }
                    }
                },
            }
        )
    assert wrong_component.value.reason_code == ReasonCode.VERIFICATION_FAILED

    with pytest.raises(ExtensionError):
        validate_relative_ref("NUL/payload")
    with pytest.raises(ExtensionError):
        validate_relative_ref("payload.txt:hidden")


def test_transaction_and_manager_status_fixtures():
    log = parse_transaction_log(_load("transaction-valid.json"))
    assert log.stage == "prepared"
    assert log.transaction_id == "txn-test-001"

    status = parse_manager_status_v1(_load("manager-status-v1.json"))
    assert status.latest_manager_version != status.minimum_supported_manager_version
    assert status.latest_manager_version != APP_VERSION
    assert status.minimum_supported_manager_version != APP_VERSION
    assert SemVer.parse(status.latest_manager_version) > SemVer.parse(
        status.minimum_supported_manager_version
    )


def test_package_revision_is_increasing_int_content_hash_is_identity():
    payload = json.loads(_load("package-valid.json"))
    first = parse_package_manifest(payload)
    payload["package_revision"] = 4
    second = parse_package_manifest(payload)
    assert second.package_revision > first.package_revision
    assert first.content_identity == second.content_identity
    assert first.files_digest == second.files_digest


def test_oversized_manifest_is_rejected():
    huge = json.dumps({"discovery_schema": 1, "pad": "x" * (70 * 1024)})
    with pytest.raises(ExtensionError) as info:
        parse_discovery_envelope(huge)
    assert info.value.reason_code == ReasonCode.VERIFICATION_FAILED


def test_generate_package_manifest_round_trip():
    payload = generate_package_manifest(
        component="matlab",
        package_revision=1,
        runtime_id="rt1-0123456789abcdef0123456789abcdef",
        component_api="1",
        min_manager_version="1.0.0",
        python_tag="cp311",
        platform_tag="win_amd64",
        module_roots=["site-packages/scipy"],
        dll_directories=["native/scipy"],
        dependency_ownership={"scipy": "matlab", "h5py": "matlab"},
        files=[
            {
                "relpath": "site-packages/scipy/__init__.py",
                "size": 32,
                "sha256": "e" * 64,
            }
        ],
        max_extract_bytes=4096,
        probe_type="matlab_mat_v73_v1",
    )
    parsed = parse_package_manifest(payload)
    assert parsed.component == "matlab"
    assert sha256_hex(json.dumps(payload).encode("utf-8"))


def test_unknown_reason_code_cannot_be_constructed():
    with pytest.raises(ValueError, match="unknown reason_code"):
        ExtensionError("PLEASE_UPDATE_INSTALLER")
