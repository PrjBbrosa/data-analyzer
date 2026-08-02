"""QThread wrapping BatchRunner.run with cross-thread event forwarding.

Wraps ``run()`` in ``try/except`` so unexpected exceptions become a
``status='blocked'`` result. Unlock in ``BatchSheet`` is bound to the
Qt-emitted ``QThread.finished`` signal — never to ``finished_with_result``
— so the dialog can never get stuck locked.
"""
from __future__ import annotations

import threading

from PyQt5.QtCore import QThread, pyqtSignal

from ....batch import BatchRunResult


class BatchRunnerThread(QThread):
    progress = pyqtSignal(object)              # BatchProgressEvent
    finished_with_result = pyqtSignal(object)  # BatchRunResult

    def __init__(
        self,
        runner,
        preset,
        output_dir,
        parent=None,
        *,
        resume_manifest=None,
        retry_failed_manifest=None,
    ):
        super().__init__(parent)
        self._runner = runner
        self._preset = preset
        self._output_dir = output_dir
        self._resume_manifest = resume_manifest
        self._retry_failed_manifest = retry_failed_manifest
        self._cancel_token = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_token.set()

    def run(self) -> None:
        try:
            result = self._runner.run(
                self._preset,
                self._output_dir,
                on_event=self.progress.emit,
                cancel_token=self._cancel_token,
                resume_manifest=self._resume_manifest,
                retry_failed_manifest=self._retry_failed_manifest,
            )
        except Exception as exc:  # noqa: BLE001
            # Convert unexpected exception to a blocked result so the UI
            # gets a deterministic value via finished_with_result, and
            # QThread.finished still fires for unlock.
            result = BatchRunResult(
                status='blocked',
                blocked=[f"runner crashed: {exc}"],
            )
        self.finished_with_result.emit(result)


class BatchPreviewThread(QThread):
    """Render one representative group without sharing BatchSheet run state."""

    finished_with_result = pyqtSignal(object)  # BatchPreviewResult

    def __init__(self, runner, preset, group_id, temp_dir, parent=None):
        super().__init__(parent)
        self._runner = runner
        self._preset = preset
        self._group_id = str(group_id)
        self._temp_dir = temp_dir
        self._cancel_token = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_token.set()

    def run(self) -> None:
        try:
            result = self._runner.preview_group(
                self._preset,
                self._group_id,
                self._temp_dir,
                cancel_token=self._cancel_token,
            )
        except Exception as exc:  # noqa: BLE001
            from ....batch import BatchPreviewResult
            result = BatchPreviewResult(
                image_path=None,
                group_id=self._group_id,
                display_name='',
                loaded_source_count=0,
                message=f'preview crashed: {exc}',
            )
        self.finished_with_result.emit(result)
