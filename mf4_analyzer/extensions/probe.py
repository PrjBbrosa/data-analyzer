"""Authorized extension probe child protocol.

Truth is carried by exit code + a dedicated JSON result file.  Windowed
executables may expose ``sys.stdout`` / ``sys.stderr`` as ``None``; this
module must not depend on console streams. The launcher dispatches this child
before GUI/importer startup. A request digest is delivered through an inherited
pipe; only the target interpreter performs native reads.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Mapping, Sequence

from mf4_analyzer.extensions.contract import (
    ExtensionError,
    ManagerExitCode,
    ReasonCode,
    dumps_json,
)
from mf4_analyzer.extensions.locking import extensions_root, verify_staging_auth
from mf4_analyzer.frozen_evidence_paths import UnsafeEvidencePath, reject_aliased_evidence


PROBE_SCHEMA = 1
PROBE_RESULT_FLAG = "--extension-probe-result"
PROBE_REQUEST_FLAG = "--extension-probe-request"
PROBE_STAGING_FLAG = "--extension-probe-staging"
PROBE_STAGING_NONCE_FLAG = "--extension-probe-staging-nonce"
PROBE_STAGING_HANDLE_FLAG = "--extension-probe-staging-handle"

# Shared with the mutually exclusive, allow_abbrev=False launcher group.
PROBE_ARGV_FLAGS = (
    PROBE_RESULT_FLAG,
    PROBE_REQUEST_FLAG,
    PROBE_STAGING_FLAG,
    PROBE_STAGING_NONCE_FLAG,
    PROBE_STAGING_HANDLE_FLAG,
)

KNOWN_PROBE_TYPES = frozenset({"media_wav_mp4_v1", "matlab_mat_v73_v1", "joint_v1"})
COMPONENT_PROBE_TYPES = {
    "media": "media_wav_mp4_v1",
    "matlab": "matlab_mat_v73_v1",
}

_SKIP_ENV_NAMES = (
    "TRACELAB_SKIP_LOCK",
    "TRACELAB_TRUST_STAGING",
    "TRACELAB_SKIP_PROBE",
)


class ProbeTimeout(Exception):
    """The authorized child exceeded its timeout and was reaped."""


class ProbeError(Exception):
    def __init__(self, reason_code: str, message: str = "", exit_code: int = ManagerExitCode.VERIFY_OR_PROBE) -> None:
        self.reason_code = reason_code
        self.exit_code = exit_code
        super().__init__(message or reason_code)


def _write_text_line(stream: object | None, message: str) -> None:
    writer = getattr(stream, "write", None)
    if not callable(writer):
        return
    try:
        writer(message + "\n")
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()
    except (OSError, ValueError):
        return


def build_probe_request(
    *,
    core_build_id: str,
    runtime_id: str,
    transaction_id: str,
    components: Sequence[str],
    package_hashes: Sequence[str],
    staging_relpath: str,
    staging_nonce: str,
    probe_types: Sequence[str] | None = None,
) -> dict[str, Any]:
    names = tuple(str(item) for item in components)
    types = tuple(probe_types) if probe_types is not None else tuple(
        COMPONENT_PROBE_TYPES[name] for name in names
    )
    if len(names) > 1:
        types = types + ("joint_v1",) if "joint_v1" not in types else types
    return {
        "schema": PROBE_SCHEMA,
        "core_build_id": core_build_id,
        "runtime_id": runtime_id,
        "transaction_id": transaction_id,
        "components": list(names),
        "package_hashes": list(package_hashes),
        "probe_types": list(types),
        "staging_relpath": staging_relpath,
        "staging_nonce": staging_nonce,
    }


def probe_command(
    executable: str | Path | Sequence[str],
    *,
    request_path: Path,
    result_path: Path,
    staging_dir: Path,
    staging_nonce: str,
    staging_handle: int | None = None,
) -> list[str]:
    if isinstance(executable, (str, Path)):
        command = [os.fspath(executable)]
    else:
        command = [os.fspath(item) for item in executable]
    command.extend(
        [
            PROBE_REQUEST_FLAG,
            os.fspath(request_path),
            PROBE_RESULT_FLAG,
            os.fspath(result_path),
            PROBE_STAGING_FLAG,
            os.fspath(staging_dir),
            PROBE_STAGING_NONCE_FLAG,
            staging_nonce,
        ]
    )
    if staging_handle is not None:
        command.extend([PROBE_STAGING_HANDLE_FLAG, str(int(staging_handle))])
    return command


def _protected_result_targets(app_root: Path | None, extra: Sequence[Path] = ()) -> tuple[Path, ...]:
    protected = list(extra)
    if app_root is not None:
        root = Path(app_root)
        protected.extend(
            [
                root / "TraceLabAnalyzer.exe",
                root / "core.json",
                root / "core-files.json",
                root / "installer.exe",
                extensions_root(root) / "active.json",
            ]
        )
        exe_candidates = list(root.glob("*.exe"))
        protected.extend(exe_candidates)
    return tuple(protected)


def assert_result_path_safe(
    result_path: Path,
    *,
    app_root: Path | None = None,
    extra_protected: Sequence[Path] = (),
) -> Path:
    target = Path(result_path).expanduser()
    try:
        reject_aliased_evidence(
            target,
            _protected_result_targets(app_root, extra_protected),
            message="probe result path aliases a protected input",
        )
    except UnsafeEvidencePath as exc:
        raise ProbeError(ReasonCode.VERIFICATION_FAILED, str(exc), ManagerExitCode.BAD_ARGS) from exc
    return target


def write_result_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dumps_json(dict(payload)).encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def parse_request(payload: Mapping[str, Any] | str | bytes) -> dict[str, Any]:
    if isinstance(payload, (str, bytes)):
        data = json.loads(payload)
    else:
        data = dict(payload)
    if not isinstance(data, dict) or int(data.get("schema") or 0) != PROBE_SCHEMA:
        raise ProbeError(ReasonCode.PROTOCOL_UNSUPPORTED, "unsupported probe request schema", ManagerExitCode.BAD_ARGS)
    components = data.get("components") or []
    if not isinstance(components, list) or not components:
        raise ProbeError(ReasonCode.PROTOCOL_UNSUPPORTED, "probe request components missing", ManagerExitCode.BAD_ARGS)
    types = data.get("probe_types") or []
    if not isinstance(types, list) or any(item not in KNOWN_PROBE_TYPES for item in types):
        raise ProbeError(ReasonCode.PROTOCOL_UNSUPPORTED, "unknown probe_type", ManagerExitCode.BAD_ARGS)
    return data


def _expected_marker(component: str) -> str:
    if component == "media":
        return "site-packages/av/__init__.py"
    if component == "matlab":
        return "site-packages/h5py/__init__.py"
    raise ProbeError(ReasonCode.COMPONENT_INCOMPATIBLE, f"unknown component {component}")


def evaluate_staging_probe(request: Mapping[str, Any], staging_dir: Path) -> dict[str, Any]:
    """Run real native reads; a directory or import marker is never success."""
    from .native_probe import run_native_reads
    from .state import resolve_inside

    try:
        roots = request.get("package_roots")
        if roots:
            extensions = Path(staging_dir).resolve().parents[1]
            packages = {name: resolve_inside(extensions, roots[name]) for name in request["components"]}
        else:
            packages = {name: Path(staging_dir) / name for name in request["components"]}
        payload = run_native_reads(packages)
    except Exception as exc:
        # Child boundary: retain the actual exception, never turn it into success.
        payload = {"ok": False, "reason_code": ReasonCode.PROBE_FAILED,
                   "detail": f"{type(exc).__name__}: {exc}"}
    payload.update({key: request.get(key) for key in
                    ("core_build_id", "runtime_id", "components", "package_hashes", "probe_types")})
    return payload


def _verify_inherited_grant(handle: int | None, request_bytes: bytes) -> None:
    if handle is None:
        raise ProbeError(ReasonCode.VERIFICATION_FAILED, "missing inherited probe authorization")
    if os.name == "nt":
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    else:
        fd = handle
    with os.fdopen(fd, "rb") as reader:
        grant = reader.read(65)
    if grant != hashlib.sha256(request_bytes).hexdigest().encode("ascii"):
        raise ProbeError(ReasonCode.VERIFICATION_FAILED, "probe request differs from inherited authorization")


@contextmanager
def _authorized_child_args(command: Sequence[str]):
    """Pass just one read handle/FD; no environment variable bypass."""
    args = list(command)
    request_path = Path(args[args.index(PROBE_REQUEST_FLAG) + 1])
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, hashlib.sha256(request_path.read_bytes()).hexdigest().encode("ascii"))
    finally:
        os.close(write_fd)
    try:
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            import msvcrt
            handle = msvcrt.get_osfhandle(read_fd)
            os.set_handle_inheritable(handle, True)
            startup = subprocess.STARTUPINFO()
            startup.lpAttributeList = {"handle_list": [handle]}
            kwargs.update(startupinfo=startup, close_fds=True)
        else:
            handle = read_fd
            kwargs.update(pass_fds=(read_fd,), start_new_session=True)
        args.extend([PROBE_STAGING_HANDLE_FLAG, str(handle)])
        yield args, kwargs
    finally:
        os.close(read_fd)


class _ProbeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ProbeError(ReasonCode.PROTOCOL_UNSUPPORTED, message, ManagerExitCode.BAD_ARGS)


def child_main(argv: Sequence[str] | None = None) -> int:
    """Windowed-safe child entry.  Exit code + JSON are authoritative."""

    parser = _ProbeParser(add_help=False, allow_abbrev=False)
    parser.add_argument(PROBE_REQUEST_FLAG, dest="request_path", required=True)
    parser.add_argument(PROBE_RESULT_FLAG, dest="result_path", required=True)
    parser.add_argument(PROBE_STAGING_FLAG, dest="staging_dir")
    parser.add_argument(PROBE_STAGING_NONCE_FLAG, dest="staging_nonce")
    parser.add_argument(PROBE_STAGING_HANDLE_FLAG, dest="staging_handle", type=int, default=None)
    try:
        args, extra = parser.parse_known_args(list(argv) if argv is not None else sys.argv[1:])
    except ProbeError:
        return ManagerExitCode.BAD_ARGS
    if extra:
        _write_text_line(sys.stderr, "unexpected probe arguments")
        return ManagerExitCode.BAD_ARGS
    result_path = Path(args.result_path)
    safe_result = False
    try:
        request_bytes = Path(args.request_path).read_bytes()
        request = parse_request(request_bytes)
        app_root = Path(request.get("app_root") or
                        Path(args.staging_dir).resolve().parents[2])
        assert_result_path_safe(result_path, app_root=app_root,
                                extra_protected=(Path(args.request_path),))
        if result_path.exists():
            raise ProbeError(ReasonCode.VERIFICATION_FAILED, "result already exists", ManagerExitCode.BAD_ARGS)
        safe_result = True
        _verify_inherited_grant(args.staging_handle, request_bytes)
        for name in _SKIP_ENV_NAMES:
            if os.environ.get(name):
                raise ProbeError(ReasonCode.VERIFICATION_FAILED, f"{name} is not a valid probe authorization")
        from .runtime import identify_core, verify_core_files
        core = identify_core(app_root)
        verify_core_files(app_root, core)
        if (request["core_build_id"], request["runtime_id"]) != (core.core_build_id, core.runtime_id):
            raise ProbeError(ReasonCode.CORE_INCONSISTENT, "probe target core changed")
        if getattr(sys, "frozen", False) and Path(sys.executable).resolve() != (app_root / core.exe_relpath).resolve():
            raise ProbeError(ReasonCode.CORE_INCONSISTENT, "probe is not running in the target executable")
        if request.get("mode") in {"installed", "availability"}:
            from .runtime import load_runtime, STATUS_READY
            from .state import resolve_inside
            from .native_probe import run_native_reads
            snapshot = load_runtime(app_root, frozen=True, use_extensions=True)
            try:
                names = request["components"]
                available = [snapshot.availability(name) for name in names]
                if request.get("mode") == "availability":
                    payload = {"ok": True, "native_reads": False,
                               "frozen": bool(getattr(sys, "frozen", False)),
                               "availability": {item.component: {"status": item.status, "reason_code": item.reason_code}
                                                for item in available}}
                else:
                    if any(item.status != STATUS_READY for item in available):
                        raise ProbeError(ReasonCode.PROBE_FAILED, "installed selection unavailable")
                    if [item.package_sha256 for item in available] != request["package_hashes"]:
                        raise ProbeError(ReasonCode.PROBE_FAILED, "installed selection changed")
                    payload = run_native_reads({item.component: resolve_inside(extensions_root(app_root), item.package_relpath)
                                                for item in available})
                payload.update({key: request.get(key) for key in
                                ("core_build_id", "runtime_id", "components", "package_hashes", "probe_types")})
            finally:
                if snapshot.lease is not None:
                    snapshot.lease.release()
        else:
            staging = verify_staging_auth(
                Path(args.staging_dir), args.staging_nonce,
                extensions_root_path=extensions_root(app_root),
                transaction_id=request["transaction_id"],
            )
            payload = evaluate_staging_probe(request, staging)
        payload["schema"] = PROBE_SCHEMA
        write_result_json(result_path, payload)
        if payload.get("ok"):
            return ManagerExitCode.SUCCESS
        return ManagerExitCode.VERIFY_OR_PROBE
    except ProbeError as exc:
        if not safe_result or exc.exit_code == ManagerExitCode.BAD_ARGS:
            return exc.exit_code
        try:
            write_result_json(
                result_path,
                {"ok": False, "reason_code": exc.reason_code, "detail": str(exc), "schema": PROBE_SCHEMA},
            )
        except OSError:
            pass
        return exc.exit_code
    except ExtensionError as exc:
        if not safe_result:
            return ManagerExitCode.VERIFY_OR_PROBE
        try:
            write_result_json(
                result_path,
                {"ok": False, "reason_code": exc.reason_code, "detail": str(exc), "schema": PROBE_SCHEMA},
            )
        except OSError:
            pass
        return ManagerExitCode.VERIFY_OR_PROBE
    except Exception as exc:
        # Programming errors stay visible; they are not network failures.
        if not safe_result:
            return ManagerExitCode.VERIFY_OR_PROBE
        try:
            write_result_json(
                result_path,
                {
                    "ok": False,
                    "reason_code": ReasonCode.PROBE_FAILED,
                    "detail": f"{type(exc).__name__}: {exc}",
                    "schema": PROBE_SCHEMA,
                },
            )
        except OSError:
            pass
        return ManagerExitCode.VERIFY_OR_PROBE


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    """Reap only the probe child we spawned.  Never target user TraceLab."""

    if proc.poll() is not None:
        return
    if os.name == "nt":
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            return


def run_authorized_probe(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    result_path: Path,
    app_root: Path | None = None,
    extra_protected: Sequence[Path] = (),
) -> dict[str, Any]:
    """Launch the authorized child, reap on timeout, read the result JSON."""

    assert_result_path_safe(result_path, app_root=app_root, extra_protected=extra_protected)
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    Path(result_path).unlink(missing_ok=True)
    with _authorized_child_args(command) as (args, authorization):
        proc = subprocess.Popen(args, **kwargs, **authorization)
    try:
        proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _kill_process_tree(proc)
        proc.wait(timeout=5)
        raise ProbeTimeout(f"probe child exceeded {timeout_seconds}s and was reaped") from exc
    if not Path(result_path).is_file():
        raise ProbeError(
            ReasonCode.PROBE_FAILED,
            f"probe child exit {proc.returncode} produced no result JSON",
        )
    payload = json.loads(Path(result_path).read_bytes().decode("utf-8"))
    if proc.returncode != ManagerExitCode.SUCCESS or not payload.get("ok"):
        raise ProbeError(
            str(payload.get("reason_code") or ReasonCode.PROBE_FAILED),
            str(payload.get("detail") or "probe failed"),
        )
    request = parse_request(Path(command[list(command).index(PROBE_REQUEST_FLAG) + 1]).read_bytes())
    for key in ("core_build_id", "runtime_id", "components", "package_hashes"):
        if payload.get(key) != request[key]:
            raise ProbeError(ReasonCode.PROBE_FAILED, f"probe result does not bind {key}")
    if request.get("mode") != "availability" and not payload.get("native_reads"):
        raise ProbeError(ReasonCode.PROBE_FAILED, "probe result has no native read evidence")
    return payload


def standin_executable() -> list[str]:
    """Explicit source-test entry; executes the same real native protocol."""

    return [sys.executable, "-m", "mf4_analyzer.extensions.probe"]


def main() -> int:
    return child_main()


if __name__ == "__main__":
    sys.exit(main())
