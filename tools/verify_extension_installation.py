"""Verify modular extension combinations without claiming frozen success.

Parameter checks and evidence-path alias rejection run without a frozen EXE.
WAV/MP4/MAT read success is only allowed when a frozen child actually reports
it.  Missing a frozen executable is not a media-import pass.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mf4_analyzer.extensions.contract import (  # noqa: E402
    ReasonCode,
    dumps_json,
    evaluate_load_compatibility,
    parse_discovery_envelope,
    parse_package_manifest,
)
from mf4_analyzer.frozen_evidence_paths import (  # noqa: E402
    UnsafeEvidencePath,
    canonical_path,
    reject_aliased_evidence,
)


_EVIDENCE_MESSAGE = (
    "evidence JSON must not alias the frozen executable, core.json, "
    "core-files.json, active.json, or an input fixture"
)
MODES = (
    "combination-contract",
    "fallback-contract",
    "base-expected-missing",
    "installed-available",
)


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_json(payload), encoding="utf-8")


def _best_effort_write(stream, text: str) -> None:
    if stream is None:
        return
    try:
        stream.write(text)
    except Exception:
        return


def planned_protected_files(
    *,
    exe: Path | None,
    app_root: Path | None,
    extra: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    protected: list[Path] = []
    if exe is not None:
        protected.append(canonical_path(exe))
    if app_root is not None:
        root = canonical_path(app_root)
        protected.extend(root.glob("*.exe"))
        protected.extend(
            (
                root / "core.json",
                root / "core-files.json",
                root / "extensions" / "active.json",
                root / "installer.exe",
            )
        )
    protected.extend(canonical_path(path) for path in extra)
    return tuple(protected)


def reject_evidence_target(
    evidence_json: Path | None,
    *,
    exe: Path | None = None,
    app_root: Path | None = None,
    extra: tuple[Path, ...] = (),
) -> None:
    if evidence_json is None:
        return
    reject_aliased_evidence(
        canonical_path(evidence_json),
        planned_protected_files(exe=exe, app_root=app_root, extra=extra),
        message=_EVIDENCE_MESSAGE,
    )


def combination_contract(
    *,
    core_json: Path,
    package_json: Path | None,
    expect_missing: bool,
) -> dict[str, Any]:
    core = parse_discovery_envelope(core_json.read_bytes())
    package = (
        parse_package_manifest(package_json.read_bytes())
        if package_json is not None
        else None
    )
    decision = evaluate_load_compatibility(
        core=core,
        package=package,
        files_verified=package is not None,
        installer_available=False,
    )
    if expect_missing:
        ok = (
            not decision.allowed
            and decision.reason_code == ReasonCode.COMPONENT_MISSING
        )
        expected = ReasonCode.COMPONENT_MISSING
    else:
        ok = decision.allowed
        expected = None
    return {
        "ok": ok,
        "mode": "combination-contract" if package_json is None or expect_missing else "installed-contract",
        "allowed": decision.allowed,
        "reason_code": decision.reason_code,
        "expected_reason_code": expected,
        "frozen_media_read": False,
        "wav_ok": False,
        "mp4_ok": False,
        "mat_ok": False,
        "note": (
            "source combination contract only; this is not a frozen "
            "WAV/MP4/MAT read"
        ),
    }


def fallback_contract(
    *,
    core_json: Path,
    remaining_package_json: Path,
    removed_component: str,
) -> dict[str, Any]:
    remaining = combination_contract(
        core_json=core_json,
        package_json=remaining_package_json,
        expect_missing=False,
    )
    missing = combination_contract(
        core_json=core_json,
        package_json=None,
        expect_missing=True,
    )
    ok = remaining["ok"] is True and missing["ok"] is True
    return {
        "ok": ok,
        "mode": "fallback-contract",
        "removed_component": removed_component,
        "remaining": remaining,
        "missing": missing,
        "frozen_media_read": False,
        "wav_ok": False,
        "mp4_ok": False,
        "mat_ok": False,
        "note": (
            "uninstall fallback is a source contract; remaining component "
            "stays load-compatible and the removed one is COMPONENT_MISSING"
        ),
    }


def refuse_unfrozen_media_success(mode: str) -> dict[str, Any]:
    return {
        "ok": False,
        "mode": mode,
        "reason_code": "NO_FROZEN_EXECUTABLE",
        "frozen_media_read": False,
        "wav_ok": False,
        "mp4_ok": False,
        "mat_ok": False,
        "note": (
            "refusing to claim WAV/MP4/MAT success without a frozen "
            "Windows executable that actually performed the read"
        ),
    }


def is_frozen_executable_claim(exe: Path) -> bool:
    """A placeholder file is not a frozen TraceLab EXE."""
    if not exe.is_file():
        return False
    if exe.stat().st_size < 64:
        return False
    # PE MZ header is required before any media-success claim.
    try:
        with exe.open("rb") as stream:
            header = stream.read(2)
    except OSError:
        return False
    return header == b"MZ"


def verify(
    *,
    mode: str,
    exe: Path | None = None,
    app_root: Path | None = None,
    core_json: Path | None = None,
    package_json: Path | None = None,
    remaining_package_json: Path | None = None,
    removed_component: str = "",
    expect_missing: bool = False,
    evidence_json: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    extra: list[Path] = []
    if core_json is not None:
        extra.append(core_json)
    if package_json is not None:
        extra.append(package_json)
    if remaining_package_json is not None:
        extra.append(remaining_package_json)
    try:
        reject_evidence_target(
            evidence_json,
            exe=exe,
            app_root=app_root,
            extra=tuple(extra),
        )
    except UnsafeEvidencePath as exc:
        payload = {"ok": False, "error": str(exc), "mode": mode, "wav_ok": False, "mp4_ok": False}
        return 2, payload

    if mode in {"base-expected-missing", "installed-available"}:
        if exe is None or not is_frozen_executable_claim(exe):
            payload = refuse_unfrozen_media_success(mode)
            return 2, payload

    if mode == "combination-contract":
        if core_json is None:
            return 2, {"ok": False, "error": "--core-json is required", "mode": mode}
        payload = combination_contract(
            core_json=core_json,
            package_json=package_json,
            expect_missing=expect_missing or package_json is None,
        )
        return (0 if payload["ok"] else 10), payload

    if mode == "fallback-contract":
        if core_json is None or remaining_package_json is None:
            return 2, {
                "ok": False,
                "error": "fallback-contract requires --core-json and --remaining-package-json",
                "mode": mode,
            }
        payload = fallback_contract(
            core_json=core_json,
            remaining_package_json=remaining_package_json,
            removed_component=removed_component or "removed",
        )
        return (0 if payload["ok"] else 10), payload

    if mode in {"base-expected-missing", "installed-available"}:
        return verify_frozen(mode=mode, exe=exe, app_root=app_root or exe.parent)

    return 2, {"ok": False, "error": f"unknown mode {mode!r}", "mode": mode}


def verify_frozen(*, mode: str, exe: Path, app_root: Path):
    from mf4_analyzer.extensions.runtime import load_runtime, STATUS_READY, STATUS_NOT_INSTALLED
    from mf4_analyzer.extensions.health import probe_installed
    from mf4_analyzer.extensions.probe import (build_probe_request, run_authorized_probe,
        PROBE_REQUEST_FLAG, PROBE_RESULT_FLAG, ProbeError, ProbeTimeout)
    from mf4_analyzer.extensions.contract import ExtensionError

    snapshot = None
    payload = {"ok": False, "mode": mode, "frozen_media_read": False,
               "wav_ok": False, "mp4_ok": False, "mat_ok": False}
    try:
        snapshot = load_runtime(app_root, frozen=True, use_extensions=True)
        if canonical_path(exe) != canonical_path(app_root / snapshot.core.exe_relpath):
            raise ExtensionError(ReasonCode.CORE_INCONSISTENT, "EXE does not match target core")
        if mode == "installed-available":
            names = sorted(name for name, item in snapshot.components.items() if item.status == STATUS_READY)
            if not names:
                raise ExtensionError(ReasonCode.COMPONENT_MISSING, "no ready components to verify")
            result = probe_installed(snapshot, names, executable=[str(exe)])
        else:
            names = sorted(snapshot.components)
            request = build_probe_request(core_build_id=snapshot.core.core_build_id,
                runtime_id=snapshot.core.runtime_id, transaction_id="availability", components=names,
                package_hashes=[snapshot.availability(name).package_sha256 for name in names],
                staging_relpath="", staging_nonce="")
            request.update(mode="availability", app_root=str(app_root.resolve()))
            with tempfile.TemporaryDirectory(prefix="tracelab-verify-") as directory:
                request_path, result_path = Path(directory)/"request.json", Path(directory)/"result.json"
                write_json(request_path, request)
                result = run_authorized_probe([str(exe), PROBE_REQUEST_FLAG, str(request_path),
                    PROBE_RESULT_FLAG, str(result_path)], timeout_seconds=45,
                    result_path=result_path, app_root=app_root)
            if any(result.get("availability", {}).get(name, {}).get("status") != STATUS_NOT_INSTALLED for name in names):
                raise ExtensionError(ReasonCode.VERIFICATION_FAILED, "base has unexpected component state")
        if result.get("frozen") is not True:
            raise ExtensionError(ReasonCode.PROBE_FAILED, "child is not frozen")
        files = {entry["name"] for entry in result.get("files", [])}
        payload.update(ok=True, probe=result, wav_ok="sample.wav" in files, mp4_ok="sample.mp4" in files,
                       mat_ok={"legacy.mat", "sample-v73.mat"}.issubset(files),
                       frozen_media_read={"sample.wav", "sample.mp4"}.issubset(files))
        return 0, payload
    except (ExtensionError, ProbeError, ProbeTimeout, OSError, ValueError) as exc:
        payload.update(reason_code=getattr(exc, "reason_code", ReasonCode.PROBE_FAILED), error=str(exc))
        return 14, payload
    finally:
        if snapshot is not None and snapshot.lease is not None:
            snapshot.lease.release()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--core-json", type=Path)
    parser.add_argument("--package-json", type=Path)
    parser.add_argument("--remaining-package-json", type=Path)
    parser.add_argument("--removed-component", default="")
    parser.add_argument("--expect-missing", action="store_true")
    parser.add_argument("--evidence-json", type=Path)
    args = parser.parse_args(argv)

    if args.mode in {"base-expected-missing", "installed-available"} and args.exe is None:
        parser.error(f"{args.mode} requires --exe")

    try:
        reject_evidence_target(
            args.evidence_json,
            exe=args.exe,
            app_root=args.app_root,
            extra=tuple(
                path
                for path in (args.core_json, args.package_json, args.remaining_package_json)
                if path is not None
            ),
        )
    except UnsafeEvidencePath as exc:
        parser.error(str(exc))

    code, payload = verify(
        mode=args.mode,
        exe=args.exe,
        app_root=args.app_root,
        core_json=args.core_json,
        package_json=args.package_json,
        remaining_package_json=args.remaining_package_json,
        removed_component=args.removed_component,
        expect_missing=args.expect_missing,
        evidence_json=args.evidence_json,
    )
    if args.evidence_json is not None and code != 2:
        write_json(args.evidence_json, payload)
    elif args.evidence_json is not None and code == 2 and "error" in payload:
        # Alias rejection must not write over the protected file.
        pass
    if payload.get("ok") is True:
        _best_effort_write(sys.stdout, dumps_json(payload))
    else:
        _best_effort_write(sys.stderr, dumps_json(payload))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
