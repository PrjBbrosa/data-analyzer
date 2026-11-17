"""Hidden, non-GUI parser child. A completed result is published exactly once."""
from __future__ import annotations

import faulthandler
import errno
import inspect
import json
from pathlib import Path
import sys
import time
import traceback

from .import_limits import (
    MAX_RESOURCE_DETAIL_CHARS, MAX_RESOURCE_MESSAGE_CHARS, ImportLimits,
    ImportResourceError, budget_context, envelope_for_known_resource,
    output_transfer_envelope,
)
from .import_process import IMPORT_METHODS, _read_json, _runtime_identity, source_snapshot


class _Cancelled(Exception):
    pass


def _is_reader_data_error(exc, method):
    """Only known parser-domain failures; never import a decoder for diagnosis."""
    if isinstance(exc, (ValueError, OSError, EOFError)):
        return True
    origin = exc.__traceback__
    while origin is not None and origin.tb_next is not None:
        origin = origin.tb_next
    frame = origin.tb_frame if origin is not None else None
    origin_module = frame.f_globals.get("__name__") if frame is not None else None
    zip_module = sys.modules.get("zipfile")
    bad_zip = getattr(zip_module, "BadZipFile", None)
    if (method == "load_excel" and bad_zip is not None
            and isinstance(exc, bad_zip) and origin_module == "zipfile"):
        return True
    struct_module = sys.modules.get("struct")
    struct_error = getattr(struct_module, "error", None)
    if (method in {"load_blf", "load_blf_dataframe", "read_blf_frames", "probe_blf_dbc"}
            and struct_error is not None and isinstance(exc, struct_error)
            and origin_module == "can.io.blf"
            and frame.f_code.co_qualname.startswith("BLFReader.")):
        # Only the reader's own unpack failure is a malformed input. A struct
        # error in our code or a callback still exposes a programming failure.
        return True
    module = sys.modules.get("asammdf.blocks.utils")
    mdf_error = getattr(module, "MdfException", None)
    if mdf_error is not None and isinstance(exc, mdf_error):
        return True
    adapters = sys.modules.get("mf4_analyzer.io.source_adapters")
    unavailable = getattr(adapters, "SourceUnavailableError", None)
    return bool(unavailable is not None and isinstance(exc, unavailable)
                and exc.__cause__ is not None and _is_reader_data_error(exc.__cause__, method))


def _reader_runtime():
    """Report already-loaded decoders only; diagnostics never import another one."""
    facts = {"python": sys.version.split()[0], "executable": sys.executable}
    for name in ("asammdf", "numpy", "scipy", "h5py", "av", "nptdms", "pandas"):
        module = sys.modules.get(name)
        if module is not None:
            facts[name] = {"version": str(getattr(module, "__version__", "unknown")),
                           "path": str(getattr(module, "__file__", "unknown"))}
    return facts


def _publish(path, payload):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _dispatch(method, path, kwargs, progress):
    from .loader import DataLoader
    if method == "probe_mdf":
        from .source_adapters import SourceAdapterRegistry, _probe_mdf
        adapter = SourceAdapterRegistry.default().adapter_for(path)
        return _probe_mdf(str(path), adapter)
    function = getattr(DataLoader, method)
    params = inspect.signature(function).parameters
    if "progress_callback" in params:
        kwargs["progress_callback"] = progress
    if method in {"load_blf_frames", "probe_blf_dbc_frames"}:
        if "frames" not in kwargs:
            raise ValueError("CAN frames missing from import request")
        return function(kwargs.pop("frames"), **kwargs)
    return function(str(path), **kwargs)


def main(request_path):
    request_path = Path(request_path)
    if request_path.is_symlink() or request_path.parent.is_symlink():
        return 2
    request_path = request_path.resolve()
    root = request_path.parent
    # The broker creates a private directory; the worker only writes fixed
    # children, never an arbitrary output path supplied in JSON.
    if request_path.name != "request.json" or not root.name.startswith("tracelab-import-"):
        return 2
    try:
        request = _read_json(request_path, 1024 * 1024)
    except (OSError, RuntimeError):
        return 2
    if request is None or request.get("schema") != 1:
        return 2
    request_id = request.get("request_id")
    if (not isinstance(request_id, str) or len(request_id) != 32
            or any(char not in "0123456789abcdef" for char in request_id)):
        return 2
    if request.get("method") not in IMPORT_METHODS:
        return 2
    try:
        limits = ImportLimits(**request["limits"])
        path = Path(request["path"])
    except (KeyError, TypeError, ValueError):
        return 2
    if any((root / name).is_symlink() for name in
           ("status.json", "status.tmp", "outcome.json", "outcome.tmp", "arguments", "result")):
        return 2
    if path.resolve().is_relative_to(root):
        return 2
    outcome = {"request_id": request_id, "state": "failed"}
    last_progress = [0.0]

    def progress(current=0, total=0, phase="读取数据"):
        if (root / "cancel").exists():
            raise _Cancelled()
        now = time.monotonic()
        if now - last_progress[0] < .1:
            return
        last_progress[0] = now
        fraction = min(.99, max(0.0, float(current) / total)) if total else -1.0
        _publish(root / "status.json", {"request_id": request_id,
                 "stage": str(phase), "fraction": fraction})

    from .import_transport import ImportTransportLimitError, read_import_result, write_import_result
    diagnostics = None
    operation = "initialization"
    try:
        diagnostics = (root / "stderr.log").open("ab") if sys.stderr is None else None
        faulthandler.enable(file=diagnostics if diagnostics is not None else sys.stderr)
        if request.get("wait_for_admission"):
            deadline = time.monotonic() + limits.timeout_seconds
            while not (root / "admitted").exists():
                if (root / "cancel").exists():
                    raise _Cancelled()
                if time.monotonic() >= deadline:
                    raise TimeoutError("读取进程未获监督授权")
                time.sleep(.01)
        progress(phase="初始化读取器")
        # Bootstrap remains Qt-free and retains modular DLL/search-path leases.
        from mf4_analyzer.app import bootstrap_extension_runtime
        runtime = request.get("runtime")
        if runtime is None:
            bootstrap_extension_runtime()
        else:
            bootstrap_extension_runtime(app_root=Path(runtime["app_root"]),
                                        use_extensions=runtime["mode"] == "modular")
            if _runtime_identity() != runtime:
                raise ImportError("读取进程的依赖组件与主程序不一致")
        operation = "source"
        if source_snapshot(path) != request["snapshot"]:
            raise ValueError("读取开始前源文件发生变化")
        operation = "arguments"
        kwargs = read_import_result(root / "arguments", request_id=request_id,
                                    max_bytes=limits.max_output_bytes)
        if not isinstance(kwargs, dict):
            raise ValueError("invalid importer arguments")
        with budget_context(limits):
            progress(phase="读取数据")
            operation = "parse"
            result = _dispatch(request["method"], path, kwargs, progress)
            if (root / "cancel").exists():
                raise _Cancelled()
            operation = "source"
            if source_snapshot(path) != request["snapshot"]:
                raise ValueError("读取期间源文件发生变化")
            progress(phase="交接读取结果")
            operation = "transfer"
            write_import_result(result, root / "result", request_id=request_id,
                                max_bytes=limits.max_output_bytes)
        outcome["state"] = "complete"
        code = 0
    except _Cancelled:
        outcome.update(code="cancelled", message="已取消导入", detail="")
        code = 1
    except Exception as exc:
        # This is the process boundary, not a per-channel recovery blanket.
        # Unexpected failures remain internal_error with their full traceback.
        envelope = None
        if isinstance(exc, ImportResourceError):
            kind = "resource_limit"
            envelope = envelope_for_known_resource(exc, phase=operation)
        elif isinstance(exc, ImportTransportLimitError):
            kind = "resource_limit"
            envelope = output_transfer_envelope(phase=operation or "transfer")
        elif isinstance(exc, MemoryError):
            kind = "resource_limit"
            envelope = envelope_for_known_resource(exc, phase=operation)
        elif isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
            kind = "resource_limit"
            envelope = envelope_for_known_resource(exc, phase=operation)
        elif isinstance(exc, ImportError):
            kind = "dependency_error"
        elif isinstance(exc, TimeoutError):
            kind = "timeout"
        elif operation in {"parse", "source"} and _is_reader_data_error(exc, request["method"]):
            kind = "data_error"
        else:
            kind = "internal_error"
        detail = traceback.format_exc()
        if len(detail) > MAX_RESOURCE_DETAIL_CHARS:
            detail = detail[-MAX_RESOURCE_DETAIL_CHARS:]
        outcome.update(code=kind, message=str(exc)[:MAX_RESOURCE_MESSAGE_CHARS], detail=detail)
        if kind == "resource_limit" and envelope is not None:
            outcome["resource"] = envelope
        code = 1
    outcome["reader_runtime"] = _reader_runtime()
    try:
        _publish(root / "outcome.json", outcome)
        return code
    finally:
        if diagnostics is not None:
            faulthandler.disable()
            diagnostics.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
