"""Generic analysis compute worker (QObject; move-to-QThread pattern).

Mirrors the contract of the retired ``FFTTimeWorker`` (now the
``do_fft_time`` / ``do_order_time`` job closures) but
takes an opaque ``job`` callable so Order / FFT-vs-Time / future analyses
share one worker class. The job receives the worker itself, so it can
emit ``progress`` and poll ``cancelled()`` as its cancel token.
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal


class AnalysisComputeWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, job):
        """``job(worker) -> result``; raise to land in ``failed``."""
        super().__init__()
        self._job = job
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def cancelled(self) -> bool:
        return self._cancelled

    def run(self):
        try:
            result = self._job(self)
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.finished.emit(result)
