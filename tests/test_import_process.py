"""Real supervised children fail without killing or blocking their caller."""
from dataclasses import replace
from pathlib import Path
import runpy
import subprocess
import sys
import time
from types import ModuleType

import pytest

from mf4_analyzer.io.import_limits import default_limits
from mf4_analyzer.io.import_process import ImportProcessError, run_import


def _csv(tmp_path):
    path = tmp_path / "测量 data.csv"
    path.write_text("Time,signal\n0,1\n0.1,2\n0.2,3\n")
    return path


def test_real_csv_round_trip_and_source_unchanged(tmp_path):
    path = _csv(tmp_path)
    before = path.read_bytes()
    frame, channels, units = run_import("load_csv", path)
    assert frame["signal"].tolist() == [1, 2, 3]
    assert frame["Time"].tolist() == [0, .1, .2]
    assert path.read_bytes() == before


@pytest.mark.parametrize("script,code", [
    ("import os; os._exit(17)", "internal_error"),
    ("import faulthandler, os; faulthandler.enable(); os.abort()", "native_crash"),
    ("pass", "internal_error"),
])
def test_child_failure_then_next_file_works(tmp_path, monkeypatch, script, code):
    import mf4_analyzer.io.import_process as process
    path = _csv(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(process, "_worker_command", lambda request: [sys.executable, "-c", script])
        with pytest.raises(ImportProcessError) as caught:
            run_import("load_csv", path)
        assert caught.value.code == code
    assert run_import("load_csv", path)[0]["signal"].tolist() == [1, 2, 3]


def test_deadline_reaps_unresponsive_child(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_process as process
    monkeypatch.setattr(process, "_worker_command", lambda request: [
        sys.executable, "-c", "import time; time.sleep(60)"])
    limits = replace(default_limits(), timeout_seconds=.2, cancel_grace_seconds=.1)
    started = time.monotonic()
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", _csv(tmp_path), limits=limits)
    assert caught.value.code == "timeout"
    assert time.monotonic() - started < 3


def test_cancelled_before_spawn(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_process as process
    def forbidden(_request):
        pytest.fail("cancelled request spawned")
    monkeypatch.setattr(process, "_worker_command", forbidden)
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", _csv(tmp_path), cancel_check=lambda: True)
    assert caught.value.code == "cancelled"


def test_custom_output_budget_must_leave_detached_copy_headroom(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_process as process
    def forbidden(_request):
        pytest.fail("inconsistent transport budget spawned a worker")
    monkeypatch.setattr(process, "_worker_command", forbidden)
    limits = replace(default_limits(), max_memory_bytes=1024, max_output_bytes=1024)
    with pytest.raises(ValueError, match="output.*half"):
        run_import("load_csv", _csv(tmp_path), limits=limits)


def test_invalid_csv_has_data_failure(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"broken")
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", path)
    assert caught.value.code == "data_error"
    assert caught.value.detail


@pytest.mark.parametrize("method", ["load_mf4", "probe_mdf"])
def test_invalid_mdf_is_data_error_not_programming_error(tmp_path, method):
    path = tmp_path / "bad.mf4"
    path.write_bytes(b"not an MDF file" * 8)
    with pytest.raises(ImportProcessError) as caught:
        run_import(method, path)
    assert caught.value.code == "data_error"
    assert "MdfException" in caught.value.detail


def test_queued_request_deadline_does_not_wait_forever(tmp_path, monkeypatch):
    import threading
    from mf4_analyzer.io import import_process as process
    occupied = threading.Semaphore(0)
    monkeypatch.setattr(process, "_SLOT", occupied)
    # Safety release bounds the red test; admission must time out before it.
    timer = threading.Timer(.5, occupied.release)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ImportProcessError) as caught:
            run_import("load_csv", _csv(tmp_path),
                       limits=replace(default_limits(), timeout_seconds=.1))
        assert caught.value.code == "timeout"
        assert time.monotonic() - started < .45
    finally:
        timer.cancel()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group integration")
def test_cancellation_reaps_descendant_after_leader_cooperates(tmp_path, monkeypatch):
    import os
    import signal
    from mf4_analyzer.io import import_process as process
    pid_path = tmp_path / "descendant.pid"
    script = '''
import subprocess, sys, time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
Path(sys.argv[2]).write_text(str(child.pid))
while not Path(sys.argv[1]).with_name('cancel').exists(): time.sleep(.01)
'''
    monkeypatch.setattr(process, "_worker_command", lambda request: [
        sys.executable, "-c", script, str(request), str(pid_path)])
    try:
        with pytest.raises(ImportProcessError) as caught:
            run_import("load_csv", _csv(tmp_path), cancel_check=pid_path.exists,
                       limits=replace(default_limits(), cancel_grace_seconds=.2))
        assert caught.value.code == "cancelled"
        pid = int(pid_path.read_text())
        # A reaped/orphan zombie has stopped and cannot retain file handles.
        for _ in range(50):
            state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                                   capture_output=True, text=True).stdout.strip()
            if not state or state.startswith("Z"):
                break
            time.sleep(.01)
        assert not state or state.startswith("Z"), f"orphan still alive: {pid} {state}"
    finally:
        if pid_path.exists():
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_active_cancel_reaps_and_removes_private_directory(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_process as process
    requests = []
    def command(request):
        requests.append(request)
        return [sys.executable, "-c", "import time; time.sleep(60)"]
    monkeypatch.setattr(process, "_worker_command", command)
    started = time.monotonic()
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", _csv(tmp_path),
                   limits=replace(default_limits(), cancel_grace_seconds=.1),
                   cancel_check=lambda: time.monotonic() - started > .2)
    assert caught.value.code == "cancelled"
    assert requests and not requests[0].parent.exists()
    assert time.monotonic() - started < 3


def test_changed_source_is_never_returned(tmp_path, monkeypatch):
    import mf4_analyzer.io.import_process as process
    real_command = process._worker_command
    path = _csv(tmp_path)
    def command(request):
        path.write_text("Time,signal\n0,99\n1,98\n")
        return real_command(request)
    monkeypatch.setattr(process, "_worker_command", command)
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", path)
    assert caught.value.code == "data_error"
    assert "变化" in str(caught.value)


def test_output_budget_is_classified_as_resource_limit(tmp_path):
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", _csv(tmp_path),
                   limits=replace(default_limits(), max_output_bytes=1000))
    assert caught.value.code == "resource_limit"


@pytest.mark.parametrize("exception,code", [("TypeError", "internal_error"),
    ("RuntimeError", "internal_error"), ("ImportError", "dependency_error"),
    ("MemoryError", "resource_limit")])
def test_worker_preserves_exception_taxonomy_and_cleans(tmp_path, monkeypatch, exception, code):
    from mf4_analyzer.io import import_process as process
    requests = []

    def command(request):
        requests.append(request)
        script = f'''\nimport sys
from mf4_analyzer.io import import_worker as worker
def broken(*args, **kwargs): raise {exception}("injected parser failure")
worker._dispatch = broken
raise SystemExit(worker.main(sys.argv[1]))
'''
        return [sys.executable, "-c", script, str(request)]

    monkeypatch.setattr(process, "_worker_command", command)
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", _csv(tmp_path))
    assert caught.value.code == code
    assert exception in caught.value.detail
    assert not requests[0].parent.exists()


@pytest.mark.parametrize("method,statement", [
    ("load_blf", "struct.unpack('<I', b'')"),
    ("load_blf_frames", "struct.unpack('<I', b'')"),
    ("load_csv", "zipfile.ZipFile(io.BytesIO(b'not a zip'))"),
    ("load_excel", "raise zipfile.BadZipFile('programming injection outside zip reader')"),
])
def test_parser_exception_types_outside_known_reader_remain_internal(tmp_path, monkeypatch, method, statement):
    from mf4_analyzer.io import import_process as process
    script = f'''
import io, struct, sys, zipfile
from mf4_analyzer.io import import_worker as worker
def broken(*args, **kwargs):
    {statement}
worker._dispatch = broken
raise SystemExit(worker.main(sys.argv[1]))
'''
    monkeypatch.setattr(process, "_worker_command", lambda request: [sys.executable, "-c", script, str(request)])
    with pytest.raises(ImportProcessError) as caught:
        run_import(method, _csv(tmp_path))
    assert caught.value.code == "internal_error"
    assert "Traceback" in caught.value.detail


def test_windowed_child_without_stderr_keeps_fatal_diagnostics(tmp_path, monkeypatch):
    from mf4_analyzer.io import import_process as process
    script = '''
import os, sys
from mf4_analyzer.io import import_worker as worker
sys.stderr = None
def abort(*args, **kwargs): os.abort()
worker._dispatch = abort
raise SystemExit(worker.main(sys.argv[1]))
'''
    monkeypatch.setattr(process, "_worker_command", lambda request: [sys.executable, "-c", script, str(request)])
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", _csv(tmp_path))
    assert caught.value.code == "native_crash"
    assert "Fatal Python error" in caught.value.detail


def test_windows_job_uses_pointer_sized_handles_and_owns_descendants(monkeypatch):
    import ctypes
    from types import SimpleNamespace
    from mf4_analyzer.io.import_process import _WindowsJob
    calls = []

    def function(name, fn):
        def call(*args):
            calls.append(name)
            return fn(*args)
        return call

    def set_info(handle, kind, pointer, size):
        assert handle == 2 ** 40
        assert kind == 9 and pointer._obj.basic.flags == 0x2000
        assert size == ctypes.sizeof(pointer._obj)
        return 1

    api = SimpleNamespace(
        CreateJobObjectW=function("create", lambda *args: 2 ** 40),
        SetInformationJobObject=function("limits", set_info),
        AssignProcessToJobObject=function("assign", lambda job, process: int(process == 2 ** 41)),
        TerminateJobObject=function("terminate", lambda *args: 1),
        QueryInformationJobObject=function("query", lambda *args: 1),
        CloseHandle=function("close", lambda *args: 1),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: api, raising=False)
    job = _WindowsJob(SimpleNamespace(_handle=2 ** 41))
    assert api.CreateJobObjectW.restype is ctypes.c_void_p
    assert api.AssignProcessToJobObject.argtypes == [ctypes.c_void_p, ctypes.c_void_p]
    job.close()
    job.close()
    assert calls == ["create", "limits", "assign", "terminate", "query", "close"]


@pytest.mark.parametrize("error,code", [("errno.ENOSPC", "resource_limit"),
                                       ("errno.EACCES", "internal_error")])
def test_result_storage_failure_is_not_bad_source(tmp_path, monkeypatch, error, code):
    from mf4_analyzer.io import import_process as process
    script = f'''
import errno, sys
from mf4_analyzer.io import import_worker as worker, import_transport as transport
def fail(*args, **kwargs): raise OSError({error}, 'injected result storage failure')
transport.write_import_result = fail
raise SystemExit(worker.main(sys.argv[1]))
'''
    monkeypatch.setattr(process, "_worker_command", lambda request: [sys.executable, "-c", script, str(request)])
    path = _csv(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ImportProcessError) as caught:
        run_import("load_csv", path)
    assert caught.value.code == code
    assert path.read_bytes() == before


def test_broker_and_worker_import_without_qt_or_native_decoders():
    script = """
import sys
import mf4_analyzer.io.import_process
import mf4_analyzer.io.import_worker
assert not any(n.startswith(('PyQt', 'pyqtgraph', 'asammdf', 'av', 'scipy', 'h5py')) for n in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_hidden_entry_routes_before_gui(tmp_path, monkeypatch):
    calls = []
    worker = ModuleType("mf4_analyzer.io.import_worker")
    worker.main = lambda path: calls.append(path) or 7
    monkeypatch.setitem(sys.modules, worker.__name__, worker)
    request = tmp_path / "request.json"
    monkeypatch.setattr(sys, "argv", ["TraceLab.exe", "--import-worker-request", str(request)])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(Path(__file__).parents[1] / "MF4 Data Analyzer V1.py"), run_name="__main__")
    assert caught.value.code == 7
    assert calls == [request]


@pytest.mark.parametrize("arguments", [
    ["--import-worker-req", "request.json"],
    ["--import-worker-request", "request.json", "--importer-runtime-smoke"],
    ["--import-worker-request", "request.json", "--startup-splash-child"],
])
def test_hidden_entry_rejects_ambiguous_modes(arguments, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["TraceLab.exe", *arguments])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(Path(__file__).parents[1] / "MF4 Data Analyzer V1.py"), run_name="__main__")
    assert caught.value.code == 2
