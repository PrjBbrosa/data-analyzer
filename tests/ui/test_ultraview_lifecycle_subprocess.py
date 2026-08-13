"""UltraView teardown must not abort the process (UV-R01).

Abort / Qt fatal errors are not catchable with ``pytest.raises``. These
cases spawn a fresh interpreter so a non-zero child exit is the failure.
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
    tmp = _REPO_ROOT / ".tmp-pytest"
    tmp.mkdir(exist_ok=True)
    env["TMP"] = str(tmp)
    env["TEMP"] = str(tmp)
    env["TMPDIR"] = str(tmp)
    env["MPLCONFIGDIR"] = str(tmp)
    return env


def _run_child(mode: str, loops: int = 1, *, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_THIS), mode, str(loops)],
        cwd=str(_REPO_ROOT),
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_preview_store_parent_destroy_exits_clean():
    result = _run_child("store-destroy")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout


def test_preview_store_parent_destroy_loop_exits_clean():
    result = _run_child("store-destroy", loops=10)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout


def test_mainwindow_construct_close_loop_exits_clean():
    result = _run_child("window-loop", loops=10, timeout=300)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout


def test_shutdown_twice_in_child_exits_clean():
    result = _run_child("shutdown-twice")
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ok" in result.stdout


def _child_store_destroy(loops: int) -> None:
    import gc

    from PyQt5.QtCore import QCoreApplication, QEvent
    from PyQt5.QtGui import QColor, QImage
    from PyQt5.QtWidgets import QApplication, QWidget

    from mf4_analyzer.ui.chart_stack.ultraview.preview_store import PreviewStore
    from mf4_analyzer.ui.ultraview_state import PreviewMeta, make_ref

    app = QApplication.instance() or QApplication([])
    for _ in range(loops):
        parent = QWidget()
        store = PreviewStore(parent=parent)
        ref = make_ref("time", "v1")
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(QColor("#336699"))
        store.publish(
            ref,
            image,
            digest="d",
            meta=PreviewMeta(ref=ref, title="loop", source_summary="x"),
        )
        # Owner did not call clear(); parent teardown must still be process-safe.
        parent.deleteLater()
        parent = None
        store = None
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
        gc.collect()
    print("ok")
    app.quit()


def _child_window_loop(loops: int) -> None:
    import gc

    from PyQt5.QtCore import QCoreApplication, QEvent
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    for _ in range(loops):
        win = MainWindow()
        win.show()
        QCoreApplication.processEvents()
        win.close()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
        del win
        gc.collect()
    print("ok")
    app.quit()


def _child_shutdown_twice(_loops: int) -> None:
    from PyQt5.QtCore import QCoreApplication, QEvent
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    uv = win._ultraview
    uv.shutdown()
    uv.shutdown()
    win.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()
    print("ok")
    app.quit()


if __name__ == "__main__":
    _mode = sys.argv[1]
    _loops = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    if _mode == "store-destroy":
        _child_store_destroy(_loops)
    elif _mode == "window-loop":
        _child_window_loop(_loops)
    elif _mode == "shutdown-twice":
        _child_shutdown_twice(_loops)
    else:
        raise SystemExit(f"unknown mode {_mode!r}")
