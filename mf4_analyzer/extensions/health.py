"""Target-child health evidence bound to core build and exact selected hashes."""
from __future__ import annotations

from dataclasses import replace
import json
import logging
from pathlib import Path
import tempfile
import uuid

from .contract import ReasonCode
from .probe import (PROBE_REQUEST_FLAG, PROBE_RESULT_FLAG, ProbeError, ProbeTimeout,
                    build_probe_request, run_authorized_probe)
from .runtime import (STATUS_CORRUPT, STATUS_READY, content_identity_bytes,
                      planned_search_path, write_json_atomic)


def probe_installed(snapshot, names, *, runner=run_authorized_probe, executable=None):
    core = snapshot.core
    request = build_probe_request(
        core_build_id=core.core_build_id, runtime_id=core.runtime_id,
        transaction_id=uuid.uuid4().hex, components=names,
        package_hashes=[snapshot.availability(name).package_sha256 for name in names],
        staging_relpath="", staging_nonce="",
    )
    request.update(mode="installed", app_root=str(snapshot.app_root))
    command = list(executable or [str(snapshot.app_root / core.exe_relpath)])
    with tempfile.TemporaryDirectory(prefix="tracelab-health-") as directory:
        request_path, result_path = Path(directory) / "request.json", Path(directory) / "result.json"
        write_json_atomic(request_path, request)
        command += [PROBE_REQUEST_FLAG, str(request_path), PROBE_RESULT_FLAG, str(result_path)]
        return runner(command, timeout_seconds=45, result_path=result_path, app_root=snapshot.app_root)


def ensure_runtime_health(snapshot, *, runner=run_authorized_probe):
    """Call only after file verification and with the application's shared lease."""
    names = sorted(name for name, item in snapshot.components.items() if item.status == STATUS_READY)
    if not names:
        return snapshot
    key = {"core_build_id": snapshot.core.core_build_id,
           "packages": {name: snapshot.availability(name).package_sha256 for name in names}}
    cache = snapshot.app_root / "extensions" / "health" / (content_identity_bytes(key) + ".json")
    try:
        cached = json.loads(cache.read_bytes())
    except (OSError, ValueError):
        cached = None
    if isinstance(cached, dict) and cached.get("key") == key and cached.get("native_reads") is True:
        return snapshot
    try:
        payload = probe_installed(snapshot, names, runner=runner)
    except (ProbeError, ProbeTimeout, OSError) as exc:
        logging.getLogger(__name__).error("Extension health failed: %s", exc)
        failed = names
        if len(names) > 1:
            failed = []
            for name in names:
                try:
                    probe_installed(snapshot, [name], runner=runner)
                except (ProbeError, ProbeTimeout, OSError):
                    failed.append(name)
            if not failed:  # each works alone but their combined native load fails
                failed = names
        components = dict(snapshot.components)
        for name in failed:
            components[name] = replace(components[name], status=STATUS_CORRUPT,
                                       reason_code=ReasonCode.PROBE_FAILED)
        snapshot.components = components
        snapshot.planned = planned_search_path(snapshot.app_root, components)
        return snapshot
    if not payload.get("native_reads"):
        raise ProbeError(ReasonCode.PROBE_FAILED, "native evidence missing")
    try:
        write_json_atomic(cache, {"key": key, "native_reads": True, "probe": payload})
    except OSError as exc:
        logging.getLogger(__name__).warning("Could not cache extension health: %s", exc)
    return snapshot
