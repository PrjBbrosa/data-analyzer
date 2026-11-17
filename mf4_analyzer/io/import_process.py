"""Supervise complete file parsing outside the application process.

No GUI or parser import occurs here. GUI callers run this synchronous broker
in their coordinator's worker thread; batch callers keep a synchronous API.
"""
from __future__ import annotations

from dataclasses import asdict
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from .import_limits import ImportLimits, ImportResourceError, default_limits


logger = logging.getLogger(__name__)
_SLOT = threading.Semaphore(1)
_CANCEL_CHECK = ContextVar("import_cancel_check", default=None)
IMPORT_METHODS = frozenset({
    "load_mf4", "load_csv", "load_excel", "load_ascii", "load_tdms",
    "load_wwt", "load_wwt_document", "load_zfd", "load_mat", "load_hdf",
    "load_audio_video", "load_blf", "load_blf_dataframe", "read_blf_frames",
    "load_blf_frames", "probe_blf_dbc", "probe_blf_dbc_frames", "probe_mdf",
})


class ImportProcessError(RuntimeError):
    def __init__(self, code, message, *, stage="", detail="", returncode=None):
        self.code = str(code)
        self.stage = str(stage)
        self.detail = str(detail)
        self.returncode = returncode
        super().__init__(str(message))


def source_snapshot(path):
    stat = Path(path).stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def _worker_command(request):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--import-worker-request", str(request)]
    return [sys.executable, "-m", "mf4_analyzer.io.import_worker", str(request)]


def _runtime_identity():
    # Importing the registry is neutral; it does not load any native decoder.
    from .source_adapters import current_extension_runtime
    snapshot = current_extension_runtime()
    if snapshot is None:
        return None
    return {
        "mode": snapshot.mode,
        "app_root": str(snapshot.app_root),
        "components": {key: [value.status, value.package_sha256]
                       for key, value in snapshot.components.items()},
    }


def _read_json(path, max_bytes):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(max_bytes + 1)
    except FileNotFoundError:
        return None
    if len(raw) > max_bytes:
        raise ImportProcessError("internal_error", "导入结果描述超过上限")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ImportProcessError("internal_error", "导入进程返回了无效结果", detail=str(exc)) from exc
    if not isinstance(value, dict):
        raise ImportProcessError("internal_error", "导入结果描述类型无效")
    return value


def _stop_process(proc, root, grace, job=None):
    (root / "cancel").touch()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    if job is not None:
        job.close()
    elif os.name == "nt" and proc.poll() is None:
        # Only the tree rooted at our own Popen handle is terminated.
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW,
                           timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("Unable to stop import process tree %s; killing owned process", proc.pid)
            proc.kill()
    elif os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _kill_owned_group(proc):
    """The leader may have exited while a decoder descendant still holds files."""
    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class _WindowsJob:
    """Own the worker tree even if its leader exits first (Windows 8+).

    No memory-limit claim: the job only owns process lifetime. The child waits
    for admission before loading decoders, closing the spawn/assignment race.
    """

    def __init__(self, proc):
        import ctypes
        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", ctypes.c_uint32), ("min_working", ctypes.c_size_t),
                        ("max_working", ctypes.c_size_t), ("active_limit", ctypes.c_uint32),
                        ("affinity", ctypes.c_size_t), ("priority", ctypes.c_uint32),
                        ("scheduling", ctypes.c_uint32)]
        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", ctypes.c_uint64 * 6),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [("times", ctypes.c_int64 * 4), ("page_faults", ctypes.c_uint32),
                        ("total_processes", ctypes.c_uint32), ("active_processes", ctypes.c_uint32),
                        ("terminated_processes", ctypes.c_uint32)]
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        api.CreateJobObjectW.restype = ctypes.c_void_p
        api.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                               ctypes.c_void_p, ctypes.c_uint32]
        api.SetInformationJobObject.restype = ctypes.c_int
        api.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        api.AssignProcessToJobObject.restype = ctypes.c_int
        api.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        api.TerminateJobObject.restype = ctypes.c_int
        api.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                 ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        api.QueryInformationJobObject.restype = ctypes.c_int
        api.CloseHandle.argtypes = [ctypes.c_void_p]
        api.CloseHandle.restype = ctypes.c_int
        self.api = api
        self.accounting_type = Accounting
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not api.AssignProcessToJobObject(self.handle, int(proc._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            api.CloseHandle(self.handle)
            self.handle = None
            raise

    def close(self):
        if self.handle is not None:
            import ctypes
            # Explicit terminate plus kill-on-close covers cooperative leader
            # exit, parser crash, and normal completion with leftover children.
            if not self.api.TerminateJobObject(self.handle, 1):
                logger.warning("Unable to terminate import job explicitly; closing kill-on-close job")
            deadline = time.monotonic() + 5
            while True:
                info = self.accounting_type()
                if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None):
                    logger.warning("Unable to query import job termination; closing kill-on-close job")
                    break
                if not info.active_processes:
                    break
                if time.monotonic() >= deadline:
                    logger.error("Import job descendants did not exit within cleanup deadline")
                    break
                time.sleep(.01)
            if not self.api.CloseHandle(self.handle):
                logger.error("Unable to close owned import job handle")
            self.handle = None


def _rss_bytes(pid):
    """Best-effort observation, not a hard OS memory limit."""
    if sys.platform.startswith("linux"):
        try:
            values = Path(f"/proc/{pid}/statm").read_text().split()
            return int(values[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "darwin":
        try:
            result = subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(pid)],
                                    capture_output=True, text=True, timeout=1)
            return int(result.stdout.strip()) * 1024 if result.returncode == 0 else None
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    # Windows admission budgets remain active; no false claim of RSS enforcement.
    return None


def _cancelled(cancel_check):
    return cancel_check is not None and bool(cancel_check())


@contextmanager
def import_context(*, cancel_check=None):
    """Scope cancellation across synchronous consumers without persisting it."""
    token = _CANCEL_CHECK.set(cancel_check)
    try:
        yield
    finally:
        _CANCEL_CHECK.reset(token)


def run_import(method, path, *, kwargs=None, cancel_check=None,
               progress_callback=None, limits=None):
    """Parse once in a disposable child and return the loader's original shape."""
    if method not in IMPORT_METHODS:
        raise ValueError(f"unsupported importer operation: {method}")
    if cancel_check is None:
        cancel_check = _CANCEL_CHECK.get()
    limits = limits if limits is not None else default_limits()
    if not isinstance(limits, ImportLimits):
        raise TypeError("limits must be ImportLimits")
    if limits.max_output_bytes > limits.max_memory_bytes // 2:
        raise ValueError("import output budget must be at most half the memory budget")
    admitted_at = time.monotonic()
    while not _SLOT.acquire(timeout=.05):
        if _cancelled(cancel_check):
            raise ImportProcessError("cancelled", "已取消导入")
        if time.monotonic() - admitted_at >= limits.timeout_seconds:
            raise ImportProcessError("timeout", "等待导入资源超过时间预算", stage="等待读取资源")
    try:
        if _cancelled(cancel_check):
            raise ImportProcessError("cancelled", "已取消导入")
        return _run_import(method, path, dict(kwargs or {}), cancel_check,
                           progress_callback, limits, admitted_at)
    finally:
        _SLOT.release()


def _run_import(method, path, kwargs, cancel_check, progress_callback, limits, started):
    from .import_transport import ImportTransportLimitError, read_import_result, write_import_result
    path = Path(path).expanduser().resolve()
    try:
        snapshot = source_snapshot(path)
    except OSError as exc:
        raise ImportProcessError("data_error", f"无法读取文件：{path.name}", detail=str(exc)) from exc
    request_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="tracelab-import-") as temporary:
        root = Path(temporary)
        try:
            write_import_result(kwargs, root / "arguments", request_id=request_id,
                                max_bytes=limits.max_output_bytes)
        except ImportTransportLimitError as exc:
            raise ImportProcessError("resource_limit", str(exc), detail=str(exc)) from exc
        request = {"schema": 1, "request_id": request_id, "method": method,
                   "path": str(path), "snapshot": snapshot,
                   "wait_for_admission": os.name == "nt",
                   "limits": asdict(limits), "runtime": _runtime_identity()}
        request_path = root / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        env = os.environ.copy()
        package_root = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [package_root, env.get("PYTHONPATH")]))
        env["TRACELAB_IMPORT_CHILD"] = "1"
        env["TRACELAB_STARTUP_SPLASH"] = "0"
        options = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
        stage = "启动读取进程"
        last_status = None
        last_memory_check = started
        stderr_path = root / "stderr.log"
        if _cancelled(cancel_check):
            raise ImportProcessError("cancelled", "已取消导入", stage=stage)
        if time.monotonic() - started >= limits.timeout_seconds:
            raise ImportProcessError("timeout", "等待或准备导入超过时间预算", stage=stage)
        with stderr_path.open("wb") as diagnostics:
            try:
                proc = subprocess.Popen(_worker_command(request_path), env=env,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=diagnostics, **options)
            except OSError as exc:
                raise ImportProcessError("dependency_error", "无法启动读取进程", detail=str(exc)) from exc
            job = None
            try:
                if os.name == "nt" and proc.poll() is None:
                    try:
                        job = _WindowsJob(proc)
                    except OSError as exc:
                        if proc.poll() is None:
                            raise ImportProcessError("dependency_error", "无法监督读取进程组", detail=str(exc)) from exc
                    if job is not None:
                        (root / "admitted").touch()
                while proc.poll() is None:
                    if _cancelled(cancel_check):
                        raise ImportProcessError("cancelled", "已取消导入", stage=stage)
                    now = time.monotonic()
                    if now - started > limits.timeout_seconds:
                        raise ImportProcessError("timeout", "文件读取超过时间预算，已停止", stage=stage)
                    status = _read_json(root / "status.json", limits.max_manifest_bytes)
                    if status is not None and status != last_status:
                        if status.get("request_id") != request_id:
                            raise ImportProcessError("internal_error", "读取进程状态身份不匹配")
                        stage = str(status.get("stage") or stage)
                        if progress_callback is not None:
                            progress_callback(float(status.get("fraction", -1)), stage)
                        last_status = status
                    if now - last_memory_check >= .25:
                        last_memory_check = now
                        rss = _rss_bytes(proc.pid)
                        if rss is not None and rss > limits.max_memory_bytes:
                            raise ImportProcessError("resource_limit", "文件读取超过内存预算，已停止", stage=stage,
                                                     detail=f"RSS {rss} > {limits.max_memory_bytes}")
                        if stderr_path.stat().st_size > limits.max_manifest_bytes:
                            raise ImportProcessError("resource_limit", "读取进程诊断输出超过预算", stage=stage)
                    time.sleep(.025)
                proc.wait()
            finally:
                try:
                    if proc.poll() is None:
                        _stop_process(proc, root, limits.cancel_grace_seconds, job)
                finally:
                    if job is not None:
                        job.close()
                    _kill_owned_group(proc)
        if _cancelled(cancel_check):
            raise ImportProcessError("cancelled", "已取消导入", stage=stage)
        outcome = _read_json(root / "outcome.json", limits.max_manifest_bytes)
        if outcome is not None and outcome.get("request_id") != request_id:
            raise ImportProcessError("internal_error", "导入结果身份不匹配", stage=stage)
        if proc.returncode != 0 or outcome is None or outcome.get("state") != "complete":
            with stderr_path.open("rb") as stream:
                stream.seek(max(0, stderr_path.stat().st_size - 8192))
                tail = stream.read(8192).decode("utf-8", errors="replace")
            native_exit = proc.returncode < 0 or "Fatal Python error:" in tail or (
                os.name == "nt" and proc.returncode & 0xC0000000 == 0xC0000000
            )
            code = "native_crash" if native_exit else (outcome or {}).get("code", "internal_error")
            detail = str((outcome or {}).get("detail") or tail)
            message = str((outcome or {}).get("message") or
                          f"读取进程异常结束（退出码 {proc.returncode}），此文件未导入")
            logger.error("Import %s failed: method=%s path=%s code=%s exit=%s stage=%s runtime=%s %s",
                         request_id, method, path, code, proc.returncode, stage,
                         (outcome or {}).get("reader_runtime", request["runtime"]), detail)
            raise ImportProcessError(code, message, stage=stage, detail=detail,
                                     returncode=proc.returncode)
        try:
            current_snapshot = source_snapshot(path)
        except OSError as exc:
            raise ImportProcessError("data_error", "读取期间源文件已不可用", detail=str(exc), stage=stage) from exc
        if current_snapshot != snapshot:
            raise ImportProcessError("data_error", "读取期间源文件发生变化，请重新打开", stage=stage)
        try:
            value = read_import_result(root / "result", request_id=request_id,
                                       max_bytes=limits.max_output_bytes)
        except (ImportResourceError, ImportTransportLimitError) as exc:
            raise ImportProcessError("resource_limit", str(exc), detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise ImportProcessError("internal_error", "读取结果不完整或超过预算", detail=str(exc)) from exc
        if progress_callback is not None:
            progress_callback(1.0, "读取完成")
        return value
