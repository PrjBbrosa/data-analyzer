"""Bounded expression jobs; workers never retain a dialog or touch Qt widgets."""
from __future__ import annotations

import logging

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, Qt, pyqtSignal, pyqtSlot

from ...signal.expression import ExpressionError, check_channel_expression


def _evaluate(request):
    token, expr, time, channels = request
    try:
        return token, check_channel_expression(expr, time, channels), None
    except Exception as exc:
        # Worker boundary: deliver failures to the GUI receiver, which routes
        # expected input errors to the tip and unexpected errors to the hook.
        if not isinstance(exc, (ExpressionError, MemoryError)):
            logging.getLogger(__name__).exception("Expression check failed (request %s)", token)
        return token, None, exc


class _Signals(QObject):
    done = pyqtSignal(int, object, object)


class _Job(QRunnable):
    def __init__(self, request):
        super().__init__()
        self.request = request
        self.signals = _Signals()
        # Even if the editor is destroyed mid-job, retire the GUI-affine
        # signal object on its own thread after emitting the outcome.
        self.signals.done.connect(self.signals.deleteLater, Qt.QueuedConnection)

    def run(self):
        self.signals.done.emit(*_evaluate(self.request))


class ExpressionCheckRunner(QObject):
    """At most one running trial and one replaceable pending request per editor."""

    completed = pyqtSignal(int, object, object)
    # Small requests keep the existing immediate create behavior. The cap is
    # an execution scheduling choice, never a data sampling/validation limit.
    INLINE_SAMPLES = 20_000

    def __init__(self, parent):
        super().__init__(parent)
        self._job = None
        self._pending = None
        self._latest_token = None

    def invalidate(self):
        self._latest_token = None
        self._pending = None

    def submit(self, token, expr, time, channels):
        request = (token, expr, time, channels)
        self._latest_token = token
        if self._job is not None:
            self._pending = request
        else:
            self._start(request)

    def _start(self, request):
        if request[2].size <= self.INLINE_SAMPLES:
            self._finished(*_evaluate(request))
            return
        self._job = _Job(request)
        self._job.signals.done.connect(self._finished, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(self._job)

    @pyqtSlot(int, object, object)
    def _finished(self, token, result, error):
        self._job = None
        if token == self._latest_token:
            self.completed.emit(token, result, error)
        pending, self._pending = self._pending, None
        if pending is not None:
            self._start(pending)
