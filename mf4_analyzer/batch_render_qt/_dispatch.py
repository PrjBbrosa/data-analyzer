"""QApplication lifecycle and synchronous GUI-thread render dispatch."""
from __future__ import annotations

import os
import threading
import traceback
from collections.abc import Callable
from typing import Any

from PyQt5.QtCore import QCoreApplication, QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QApplication


_APP: QApplication | None = None
_DISPATCHER: "_RenderDispatcher | None" = None
_DISPATCH_LOCK = threading.RLock()


def ensure_app() -> QApplication:
    """Return a QWidget-capable app, creating one only on the main thread."""

    global _APP
    instance = QCoreApplication.instance()
    if instance is not None:
        if not isinstance(instance, QApplication):
            raise RuntimeError(
                "Qt batch rendering requires QApplication; an existing "
                "QCoreApplication cannot host QWidget rendering"
            )
        _APP = instance
        return instance
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError(
            "Qt batch renderer cannot create QApplication from a non-main thread; "
            "create QApplication on the GUI thread before starting the worker"
        )
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _APP = QApplication([])
    return _APP


class _RenderDispatcher(QObject):
    request = pyqtSignal(object)

    def __init__(self, app: QApplication):
        super().__init__()
        self._quitting = False
        self.request.connect(self._execute, type=Qt.BlockingQueuedConnection)
        app.aboutToQuit.connect(self._mark_quitting, type=Qt.DirectConnection)

    @property
    def quitting(self) -> bool:
        return self._quitting

    @pyqtSlot()
    def _mark_quitting(self) -> None:
        self._quitting = True

    @pyqtSlot(object)
    def _execute(self, job: dict[str, Any]) -> None:
        if self._quitting:
            job["exception"] = RuntimeError(
                "Qt application is exiting; batch render rejected"
            )
            job["traceback"] = "Qt application emitted aboutToQuit"
            return
        try:
            job["result"] = job["fn"]()
        except BaseException as exc:
            job["exception"] = exc
            job["traceback"] = traceback.format_exc()


def _dispatcher_for(app: QApplication) -> _RenderDispatcher:
    global _DISPATCHER
    with _DISPATCH_LOCK:
        if _DISPATCHER is None:
            dispatcher = _RenderDispatcher(app)
            if dispatcher.thread() is not app.thread():
                dispatcher.moveToThread(app.thread())
            _DISPATCHER = dispatcher
        return _DISPATCHER


def render_on_gui_thread(fn: Callable[[], Any]):
    """Execute ``fn`` on QApplication's thread and return or re-raise."""

    app = ensure_app()
    dispatcher = _dispatcher_for(app)
    if dispatcher.quitting:
        raise RuntimeError("Qt application is exiting; batch render rejected")
    if QThread.currentThread() is app.thread():
        return fn()
    job: dict[str, Any] = {"fn": fn}
    dispatcher.request.emit(job)
    if "exception" in job:
        exc = job["exception"]
        note = "rendered on Qt GUI thread\n" + str(job.get("traceback", ""))
        add_note = getattr(exc, "add_note", None)
        if callable(add_note):
            add_note(note)
        raise exc
    return job.get("result")


__all__ = ["ensure_app", "render_on_gui_thread"]
