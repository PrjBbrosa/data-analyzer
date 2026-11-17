"""Serial GUI continuations around the Qt-neutral subprocess import broker.

Only the supervisor runs in QThread. Generator steps, dialogs and registration
run on the owning GUI thread. No waiting or event-loop pumping is used here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
from threading import Event
from uuid import uuid4
from weakref import ref

from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QObject, QThread, QTimer, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


def run_import(method, path, **kwargs):
    # Keep optional parser imports out of GUI module initialization.
    from ...io.import_process import run_import as supervised_import
    return supervised_import(method, path, **kwargs)


@dataclass(frozen=True)
class ImportCall:
    method: str
    path: object
    kwargs: dict = field(default_factory=dict)
    phase: str = '读取数据'
    transform: object = None


@dataclass(frozen=True)
class ImportSummary:
    loaded_files: int
    failed_files: int
    skipped_files: int


@dataclass
class ImportRequest:
    request_id: str
    generation: int
    target: object
    factory: object
    cancel_event: Event = field(default_factory=Event)
    workflow: object = None
    on_done: object = None
    progress_callback: object = None
    terminal: bool = False
    path: str = ""
    loaded_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    limits: object = None
    attached_fids: list = field(default_factory=list)


class _Supervisor(QThread):
    progress = pyqtSignal(object)

    def __init__(self, broker, call, request):
        super().__init__()
        self.broker = broker
        self.call = call
        self.request = request
        self.value = None
        self.error = None
        self.limits = request.limits

    def report(self, *args):
        self.progress.emit(args)

    def run(self):
        try:
            if self.limits is None:
                from ...io.import_limits import default_limits
                self.limits = default_limits()
            self.value = self.broker(
                self.call.method, self.call.path, kwargs=self.call.kwargs,
                cancel_check=self.request.cancel_event.is_set,
                progress_callback=self.report, limits=self.limits,
            )
            if self.call.transform is not None and not self.request.cancel_event.is_set():
                self.value = self.call.transform(self.call.path, self.value)
        except Exception as exc:
            # Transport exceptions retain their type/code/stage and traceback.
            logger.exception('Import request=%s path=%s method=%s code=%s stage=%s failed',
                             self.request.request_id, self.call.path, self.call.method,
                             getattr(exc, 'code', 'internal_error'), getattr(exc, 'stage', 'broker'))
            self.error = exc


class _RunRelay(QObject):
    """Retain context explicitly; never inspect a deleted QObject.sender()."""
    def __init__(self, owner, request, thread):
        super().__init__(owner)
        self.owner = owner
        self.request = request
        self.thread = thread

    @pyqtSlot(object)
    def progress(self, args):
        if self.owner.is_valid(self.request) and self.request.progress_callback:
            self.request.progress_callback(*args)

    @pyqtSlot()
    def finished(self):
        owner, request, thread = self.owner, self.request, self.thread
        value, error, call = thread.value, thread.error, thread.call
        request.limits = thread.limits
        thread.value = thread.error = None
        owner._thread = None
        owner._relay = None
        thread.deleteLater()
        self.deleteLater()
        owner._advance(request, value, error, retry_call=call)


class ImportCoordinator(QObject):
    finished = pyqtSignal(str, str, object)
    drained = pyqtSignal()

    def __init__(self, host, *, broker=None):
        # Application ownership keeps the supervisor alive if a parent window
        # destroys its child tab without delivering that child's closeEvent.
        super().__init__(QCoreApplication.instance())
        # The application must not retain the host through this coordinator:
        # close() alone does not delete a Python-owned QWidget, and a strong
        # back-reference would prevent its GC/destruction cleanup indefinitely.
        self._host_ref = ref(host)
        host.destroyed.connect(self._host_destroyed)
        self.broker = broker or run_import
        self.generation = 0
        self.closing = False
        self._queue = deque()
        self._active = None
        self._thread = None
        self._relay = None
        self.failures = deque(maxlen=20)
        self.progress_dialog = None
        self._target_timer = QTimer(self)
        self._target_timer.setInterval(100)
        self._target_timer.timeout.connect(self._check_target)
        self._target_timer.start()

    @pyqtSlot()
    def _host_destroyed(self):
        self._host_ref = None
        self.shutdown()
        if not self.busy:
            self.deleteLater()

    @property
    def host(self):
        host = self._host_ref() if self._host_ref is not None else None
        return host if host is not None and not sip.isdeleted(host) else None

    @property
    def busy(self):
        return self._active is not None or bool(self._queue) or self._thread is not None

    def capture_target(self):
        host = self.host
        if host is None or not hasattr(host, 'chart_stack'):
            return None
        section = host.chart_stack.current_mode()
        if section == 'time':
            resolved = host._focused_time_view_state()
            return ('time', resolved[1].view_id, 0) if resolved else None
        if section in host.analysis_managers:
            focus = host._comparison().focused(section)
            if focus is not None:
                return (section, focus[0], focus[1])
        resolved = host._active_analysis_view_state(section)
        if resolved is None:
            return None
        page = host._analysis_page(section)
        return (section, resolved[2].view_id, page.focused_index() if page else 0)

    def target_state(self, target):
        host = self.host
        if target is None or host is None:
            return None
        section, view_id, pane = target
        manager = (host.view_manager if section == 'time'
                   else host.analysis_managers.get(section))
        if manager is None:
            return None
        for index, state in enumerate(manager.views):
            if state.view_id == view_id:
                if section != 'time' and not 0 <= pane < len(state.panes):
                    return None
                return index, state
        return None

    def is_valid(self, request):
        return (self.host is not None and not self.closing and not request.cancel_event.is_set()
                and request.generation == self.generation
                and (request.target is None or self.target_state(request.target) is not None))

    def _check_target(self):
        if self._active is not None and not self.is_valid(self._active):
            self._active.cancel_event.set()

    def submit(self, factory, *, target=None, on_done=None, progress_callback=None, limits=None):
        if self.closing or self.host is None:
            raise RuntimeError('Import coordinator is closing')
        request = ImportRequest(uuid4().hex, self.generation, target, factory,
                                on_done=on_done, progress_callback=progress_callback, limits=limits)
        self._queue.append(request)
        QTimer.singleShot(0, self._start_next)
        return request.request_id

    def _start_next(self):
        if self._active is not None or self._thread is not None:
            return
        if not self._queue:
            self.drained.emit()
            if self.host is None:
                self.deleteLater()
            return
        request = self._active = self._queue.popleft()
        self._advance(request)

    def _advance(self, request, value=None, error=None, *, retry_call=None):
        if not self.is_valid(request):
            self._finish(request, 'cancelled', None)
            return
        try:
            if error is not None and getattr(error, 'code', '') == 'timeout':
                self.record_failure(request, error, count_file=False)
                limits = self._choose_timeout_retry(request)
                if limits is None:
                    request.cancel_event.set()
                if not self.is_valid(request):
                    self._finish(request, 'cancelled', None)
                    return
                request.limits = limits
                self._start_call(request, retry_call)
                return
            if request.workflow is None:
                request.workflow = request.factory(request)
                call = next(request.workflow)
            elif error is not None:
                call = request.workflow.throw(error)
            else:
                call = request.workflow.send(value)
            if not isinstance(call, ImportCall):
                raise TypeError('Import workflows must yield ImportCall')
            # A modal choice may have processed a session change/cancellation.
            if not self.is_valid(request):
                self._finish(request, 'cancelled', None)
                return
            self._start_call(request, call)
        except StopIteration as done:
            status = 'success'
            if not self.is_valid(request):
                status = 'cancelled'
            elif request.failed_files:
                status = 'partial' if request.loaded_files else 'failed'
            elif request.skipped_files and not request.loaded_files:
                status = 'cancelled'
            summary = ImportSummary(request.loaded_files, request.failed_files,
                                    request.skipped_files)
            self._finish(request, status, done.value if done.value is not None else summary)
        except Exception as exc:
            logger.exception('GUI import continuation failed: %s', request.request_id)
            self.record_failure(request, exc)
            self._finish(request, 'failed', exc)

    def _start_call(self, request, call):
        request.path = str(call.path)
        thread = self._thread = _Supervisor(self.broker, call, request)
        relay = self._relay = _RunRelay(self, request, thread)
        thread.progress.connect(relay.progress)
        thread.finished.connect(relay.finished)
        thread.start()

    def _choose_timeout_retry(self, request):
        """The previous process is already reaped; only an explicit choice retries."""
        from dataclasses import replace
        from PyQt5.QtWidgets import QMessageBox
        from ...ui_kit.message_box_buttons import fit_message_box_buttons_to_text

        current = request.limits.timeout_seconds
        extended = current * 2
        box = QMessageBox(self.host)
        box.setWindowTitle("导入超时")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"本次读取已超过 {current:g} 秒。")
        box.setInformativeText(
            f"可将本次导入限时延长到 {extended:g} 秒，再重试当前文件。"
            "取消不会新增来源。"
        )
        retry = box.addButton("延长并重试", QMessageBox.AcceptRole)
        cancel = box.addButton("取消导入", QMessageBox.RejectRole)
        box.setDefaultButton(cancel)
        fit_message_box_buttons_to_text(box)
        box.exec_()
        accepted = box.clickedButton() is retry
        box.deleteLater()
        return replace(request.limits, timeout_seconds=extended) if accepted else None

    def record_failure(self, request, exc, *, count_file=True):
        from pathlib import Path
        if count_file and getattr(exc, 'code', '') != 'cancelled':
            request.failed_files += 1
        logger.error('Import request=%s path=%s format=%s code=%s stage=%s: %s',
                     request.request_id, request.path, Path(request.path).suffix.lower(),
                     getattr(exc, 'code', 'internal_error'), getattr(exc, 'stage', 'gui'),
                     exc, exc_info=(type(exc), exc, exc.__traceback__))
        self.failures.append({
            'path': request.path,
            'request_id': request.request_id,
            'code': getattr(exc, 'code', 'internal_error'),
            'stage': getattr(exc, 'stage', 'gui'),
            'detail': str(exc),
        })

    def _finish(self, request, status, value):
        if request.terminal:
            return
        request.terminal = True
        try:
            if request.workflow is not None:
                request.workflow.close()
            if request.on_done is not None and self.host is not None:
                request.on_done(status, value)
        except Exception:
            logger.exception('Import cleanup failed: %s', request.request_id)
        finally:
            self._active = None
            self.finished.emit(request.request_id, status, value)
            QTimer.singleShot(0, self._start_next)

    def cancel(self):
        if self._active is not None:
            self._active.cancel_event.set()
        for request in self._queue:
            request.cancel_event.set()

    def invalidate_session(self):
        self.generation += 1
        self.cancel()

    def shutdown(self):
        self.closing = True
        self._target_timer.stop()
        self.invalidate_session()
        return not self.busy
