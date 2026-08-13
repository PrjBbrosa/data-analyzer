"""UVL-A21: MainWindow close must not tear down a live Batch runner.

Abort / Qt fatal errors from callbacks into deleted widgets are not
catchable with ``pytest.raises``. This child process is the exit-path
guard; it uses a hold-thread rather than a full ``BatchRunner`` so CI
cannot hang on DSP/render work.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_THIS = Path(__file__).resolve()


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(_REPO_ROOT)
    tmp = Path("/tmp")
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    env["TMPDIR"] = str(tmp)
    env["MPLCONFIGDIR"] = str(tmp)
    return env


def test_mainwindow_close_after_confirmed_batch_stop_exits_clean():
    result = subprocess.run(
        [sys.executable, str(_THIS), "confirmed-stop"],
        cwd=str(_REPO_ROOT),
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout


def _child_confirmed_stop() -> None:
    import threading

    from PyQt5.QtCore import QCoreApplication, QEvent, QThread
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from mf4_analyzer.ui.drawers.batch import sheet as sheet_module
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    from mf4_analyzer.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])

    class _HoldThread(QThread):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._release = threading.Event()
            self.run_started = threading.Event()

        def request_cancel(self):
            self._release.set()

        def run(self):
            self.run_started.set()
            self._release.wait(timeout=30)

    win = MainWindow()
    sheet = BatchSheet(win, files={})
    win._batch_sheet = sheet

    thread = _HoldThread(sheet)
    sheet._running = True
    sheet._runner_thread = thread
    thread.finished.connect(sheet._on_thread_finished)
    thread.start()
    if not thread.run_started.wait(timeout=5):
        raise SystemExit("hold thread never started")

    sheet_module.QMessageBox.question = (
        lambda *_a, **_k: QMessageBox.Yes
    )

    accepted = win.close()
    if not accepted:
        raise SystemExit("closeEvent ignored after confirmed stop")
    from PyQt5 import sip
    if not sip.isdeleted(sheet) and sheet.is_running():
        raise SystemExit("runner still marked running after close")

    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()
    print("ok")
    app.quit()


if __name__ == "__main__":
    _mode = sys.argv[1]
    if _mode == "confirmed-stop":
        _child_confirmed_stop()
    else:
        raise SystemExit(f"unknown mode {_mode!r}")
