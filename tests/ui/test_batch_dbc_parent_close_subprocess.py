"""The last window must not exit before the DBC broker reaps its worker."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='POSIX owned-process group probe')


def _child(mode, out):
    import importlib
    import resource
    import time
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from PyQt5.QtCore import QSettings, QTimer
    from PyQt5.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.IniFormat)
    for scope in (QSettings.UserScope, QSettings.SystemScope):
        QSettings.setPath(QSettings.IniFormat, scope, str(out / 'settings'))

    def settings(*args, **kwargs):
        return QSettings(str(out / 'settings.ini'), QSettings.IniFormat)

    for name in ('inspector_sections', 'inspector_sections._helpers',
                 'inspector_sections.collapsible', 'inspector_sections.presets',
                 'inspector_sections.persistent_top', 'batch_settings'):
        module = importlib.import_module('mf4_analyzer.ui.' + name)
        for symbol in ('_preset_settings', '_default_settings'):
            if hasattr(module, symbol):
                setattr(module, symbol, settings)
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.main_window.project_dirty import DirtyGuardResult
    from mf4_analyzer.io import import_process

    started_at = time.monotonic()

    def record(event, **values):
        with (out / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(event=event, elapsed=time.monotonic()-started_at, **values)) + '\n')

    app = QApplication([])
    assert app.quitOnLastWindowClosed()
    window = MainWindow()
    window.confirm_leave_unsaved_project = lambda: DirtyGuardResult.PROCEED_DISCARDED
    window.show()
    window.open_batch()
    sheet = window._batch_sheet
    owner = sheet._dbc_imports
    owner.finished.connect(lambda *args: record('finished', status=args[1]))
    owner.drained.connect(lambda: record('drained'))
    app.aboutToQuit.connect(lambda: record('aboutToQuit', busy=owner.busy))

    def close_main():
        record('close_requested', busy=owner.busy)
        accepted = window.close()
        record('close_returned', accepted=accepted, busy=owner.busy)

    if mode == 'idle':
        QTimer.singleShot(100, close_main)
    else:
        path = out / 'source.blf'
        path.write_bytes(b'BLF')
        pid_path = out / 'worker.pid'
        worker = out / 'worker.py'
        worker.write_text('import os,time\nfrom pathlib import Path\n'
                          + 'Path(' + repr(str(pid_path)) + ').write_text(str(os.getpid()))\n'
                          + 'time.sleep(60)\n')
        # Real broker process ownership, cancellation grace and reap. Only the
        # disposable worker is replaced to make the close race deterministic.
        import_process._worker_command = lambda _request: [sys.executable, str(worker)]
        sheet._add_disk_paths_with_blf_context([str(path)])
        poll = QTimer(window)
        poll.setInterval(20)

        def worker_started():
            if not pid_path.exists():
                return
            poll.stop()
            record('worker_started', pid=int(pid_path.read_text()))
            if mode == 'cancelled_close':
                owner.cancel()
            elif mode == 'sheet_close_then_parent':
                sheet.close()
            elif mode == 'sheet_reject_then_parent':
                sheet.reject()
            QTimer.singleShot(100 if mode != 'active_close' else 0, close_main)
        poll.timeout.connect(worker_started)
        poll.start()

    def deadline():
        record('deadline')
        app.exit(91)
    QTimer.singleShot(8000, deadline)
    code = app.exec_()
    record('exec_returned', code=code, busy=owner.busy,
           thread_running=bool(owner._thread and owner._thread.isRunning()))
    return code


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.mark.parametrize('mode', [
    'idle', 'active_close', 'cancelled_close',
    'sheet_close_then_parent', 'sheet_reject_then_parent',
])
def test_dbc_parent_close_exits_only_after_worker_reaped(tmp_path, mode):
    env = dict(os.environ, TMPDIR='/tmp', MPLCONFIGDIR='/tmp',
               QT_QPA_PLATFORM='offscreen', PYTHONPATH=str(ROOT))
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), '--child', mode, str(tmp_path)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=12,
        )
        (tmp_path / 'stderr.log').write_text(result.stderr)
        assert result.returncode == 0, result.stderr
        events = [json.loads(line) for line in (tmp_path / 'events.jsonl').read_text().splitlines()]
        assert not any(row['event'] == 'deadline' for row in events)
        last = events[-1]
        assert last['event'] == 'exec_returned'
        assert not last['busy'] and not last['thread_running']
        if mode != 'idle':
            names = [row['event'] for row in events]
            assert names.index('finished') < names.index('drained') < names.index('aboutToQuit')
            assert [row['status'] for row in events if row['event'] == 'finished'] == ['cancelled']
            assert not _pid_alive(int((tmp_path / 'worker.pid').read_text()))
    finally:
        # A failing pre-fix subprocess must not leave its private sleeper alive.
        pid_path = tmp_path / 'worker.pid'
        if pid_path.exists():
            pid = int(pid_path.read_text())
            if _pid_alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == '__main__':
    sys.exit(_child(sys.argv[2], Path(sys.argv[3])))
