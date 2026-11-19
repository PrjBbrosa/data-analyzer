"""Serial GUI continuations around the Qt-neutral subprocess import broker.

Only the supervisor runs in QThread. Generator steps, dialogs and registration
run on the owning GUI thread. No waiting or event-loop pumping is used here.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from functools import partial
import logging
import os
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import uuid4
from weakref import ref

from PyQt5 import sip
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtCore import QCoreApplication, QObject, QThread, QTimer, pyqtSignal, pyqtSlot

from ...ui_kit.import_progress_dialog import (
    KIND_CANCELLED,
    KIND_CANCELLING,
    KIND_FAILED,
    KIND_HANDOFF,
    KIND_PARTIAL,
    KIND_READING,
    KIND_STAGE,
    KIND_SUCCESS,
    KIND_WAITING,
    KIND_WAITING_USER,
    build_import_progress_snapshot,
)

logger = logging.getLogger(__name__)


def run_import(method, path, **kwargs):
    # Keep optional parser imports out of GUI module initialization.
    from ...io.import_process import run_import as supervised_import
    return supervised_import(method, path, **kwargs)


_default_broker = run_import


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
    source_snapshot: object = None
    source_path: str = ""
    worker_request_id: str = ""
    explicit_native: bool = False


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
                start = monotonic()
                self.value = self.call.transform(self.call.path, self.value)
                if os.environ.get("TRACELAB_IMPORT_TIMINGS") == "1":
                    logger.info("Import timing gui_request=%s prepare_file_data_ms=%.1f",
                                self.request.request_id, (monotonic() - start) * 1000)
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
        self._last_call = None
        self.failures = deque(maxlen=20)
        self.progress_dialog = None
        self.progress_log = []
        self._progress = None
        self._target_timer = QTimer(self)
        self._target_timer.setInterval(100)
        self._target_timer.timeout.connect(self._check_target)
        self._target_timer.start()
        # One timer for the active import. Elapsed text is not a second progress policy.
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._on_progress_tick)
        self._progress_show_timer = QTimer(self)
        self._progress_show_timer.setSingleShot(True)
        self._progress_show_timer.setInterval(250)
        self._progress_show_timer.timeout.connect(self._show_progress_dialog)
        self._prewarm = None
        self._prewarm_timer = QTimer(self)
        self._prewarm_timer.setSingleShot(True)
        self._prewarm_timer.setInterval(750)
        self._prewarm_timer.timeout.connect(self._start_prewarm)

    def enable_prewarm(self):
        if (self.broker is not _default_broker or self.closing
                or self._prewarm is not None
                or QGuiApplication.platformName() in {"offscreen", "minimal"}):
            return
        from ...io.import_process import MdfImportPrewarm
        self._prewarm = MdfImportPrewarm()
        self._prewarm_timer.start()

    def _start_prewarm(self):
        host = self.host
        if (self._prewarm is not None and host is not None and host.isVisible()
                and not self.closing and not self.busy):
            self._prewarm.start()


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
        return (self._active is not None or bool(self._queue) or self._thread is not None
                or (self.closing and self._prewarm is not None and self._prewarm.running))

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
        if self.closing and not self.busy:
            self._target_timer.stop()
            self._start_next()
            return
        if self._active is not None and not self.is_valid(self._active):
            self._active.cancel_event.set()

    def submit(self, factory, *, target=None, on_done=None, progress_callback=None,
               limits=None, explicit_native=False):
        if self.closing or self.host is None:
            raise RuntimeError('Import coordinator is closing')
        request = ImportRequest(
            uuid4().hex, self.generation, target, factory,
            on_done=on_done, progress_callback=progress_callback, limits=limits,
            explicit_native=bool(explicit_native),
        )
        self._queue.append(request)
        QTimer.singleShot(0, self._start_next)
        return request.request_id

    def _start_next(self):
        if self._active is not None or self._thread is not None:
            return
        if not self._queue:
            if self.busy:
                return
            if self.closing:
                self._target_timer.stop()
            elif self._prewarm is not None and not self._prewarm.running:
                self._prewarm_timer.start()
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
            if error is not None and getattr(error, 'code', '') == 'resource_limit':
                from ...io.import_limits import ACTION_RECHECK_RETRY

                action = self._present_resource_dialog(request, error)
                if not self.is_valid(request):
                    self._finish(request, 'cancelled', None)
                    return
                if action == ACTION_RECHECK_RETRY and self.accept_resource_recheck(request, retry_call):
                    self.resume_after_user_wait(request)
                    self._start_call(request, retry_call)
                    return
                self.resume_after_user_wait(request)
                try:
                    error.resource_dialog_presented = True
                except (AttributeError, TypeError):
                    pass
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
        if self._thread is not None:
            logger.error(
                'Import request=%s refused a new worker before the previous one was reaped',
                request.request_id,
            )
            return
        request.path = str(call.path)
        request.source_path = str(call.path)
        request.source_snapshot = self._capture_source_snapshot(call.path)
        request.worker_request_id = uuid4().hex
        self._last_call = call
        self.note_call_started(request, call)
        broker = self.broker
        if broker is _default_broker:
            broker = partial(broker, diagnostic_id=request.request_id)
        if self._prewarm is not None:
            if (call.method in {"load_mf4", "load_mf4_native"}
                    and not getattr(self.host, "_restoring_project", False)):
                broker = partial(broker, prewarm=self._prewarm)
            else:
                self._prewarm.discard()
        thread = self._thread = _Supervisor(broker, call, request)
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
        self.note_user_wait(request, "等待确认是否延长并重试")
        box.exec_()
        accepted = box.clickedButton() is retry
        box.deleteLater()
        if accepted:
            self.resume_after_user_wait(request)
        return replace(request.limits, timeout_seconds=extended) if accepted else None

    def record_failure(self, request, exc, *, count_file=True):
        if count_file and getattr(exc, 'code', '') != 'cancelled':
            request.failed_files += 1
        logger.error('Import request=%s path=%s format=%s code=%s stage=%s: %s',
                     request.request_id, request.path, Path(request.path).suffix.lower(),
                     getattr(exc, 'code', 'internal_error'), getattr(exc, 'stage', 'gui'),
                     exc, exc_info=(type(exc), exc, exc.__traceback__))
        entry = {
            'path': request.path,
            'request_id': request.request_id,
            'code': getattr(exc, 'code', 'internal_error'),
            'stage': getattr(exc, 'stage', 'gui'),
            'detail': str(exc),
        }
        if entry['code'] == 'resource_limit':
            from ...io.import_limits import resource_user_text
            entry['user_text'] = resource_user_text(exc)
        self.failures.append(entry)

    def _capture_source_snapshot(self, path):
        from ...io.import_process import source_snapshot

        try:
            return tuple(source_snapshot(path))
        except OSError:
            return None

    def accept_resource_recheck(self, request, call) -> bool:
        """One explicit recheck. The fresh ``default_limits()`` object is the budget."""
        if self._thread is not None or call is None:
            return False
        if not self.is_valid(request):
            return False
        if request.target is not None and self.target_state(request.target) is None:
            return False
        if request.source_path and str(call.path) != str(request.source_path):
            return False
        current = self._capture_source_snapshot(call.path)
        if current is None or current != request.source_snapshot:
            return False
        from ...io.import_limits import default_limits

        request.limits = default_limits()
        return True

    def _present_resource_dialog(self, request, error):
        from ...io.import_limits import (
            ACTION_CLOSE,
            resource_action_ids,
            resource_technical_detail,
            resource_user_text,
        )
        from ...ui_kit.message_dialog import build_import_resource_dialog

        self.note_user_wait(request, "等待处理导入错误")
        dialog = build_import_resource_dialog(
            self.host,
            text=resource_user_text(error),
            detail=resource_technical_detail(
                error,
                stage=getattr(error, "stage", "") or "",
                detail=getattr(error, "detail", "") or "",
                request_id=getattr(error, "request_id", "") or request.worker_request_id,
            ),
            action_ids=resource_action_ids(error),
        )
        dialog.exec_()
        result = dialog.message_result
        action = ACTION_CLOSE if result is None or not result.action_id else result.action_id
        dialog.deleteLater()
        return action

    def _finish(self, request, status, value):
        if request.terminal:
            return
        request.terminal = True
        try:
            # The generator's finally already ran on the success path. Publish
            # the one terminal snapshot while the dialog and status token still
            # exist, then dismiss. Dismiss blocks signals so close is not cancel.
            self.publish_terminal(request, status)
        except Exception:
            logger.exception('Import progress terminal failed: %s', request.request_id)
        try:
            self.dismiss_progress(request)
            if request.workflow is not None:
                request.workflow.close()
            if request.on_done is not None and self.host is not None:
                request.on_done(status, value)
        except Exception:
            logger.exception('Import cleanup failed: %s', request.request_id)
        finally:
            self.dismiss_progress(request)
            # Retry/continuation has settled and the supervisor has drained.
            # A completed call may hold a bound window method and CAN frames;
            # diagnostic history must retain only the bounded facts above.
            self._last_call = None
            request.workflow = None
            request.factory = None
            request.on_done = None
            request.progress_callback = None
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
        if self._prewarm is not None:
            self._prewarm.discard()

    def shutdown(self):
        self.closing = True
        self._prewarm_timer.stop()
        if self._prewarm is not None:
            self._prewarm.close()
        self._progress_timer.stop()
        self._progress_show_timer.stop()
        self.invalidate_session()
        if not self.busy:
            self._target_timer.stop()
            return True
        return False

    @property
    def current_progress(self):
        session = self._progress
        return None if session is None else session.last

    def progress_owned(self, request) -> bool:
        session = self._progress
        return session is not None and session.request_id == request.request_id

    def open_progress(
        self, request, dialog, *, status_sink=None, finish_status=None,
        title, file_count, path="", phase="读取数据",
    ):
        """Own the elapsed timer and the one snapshot for this request."""
        if self._progress is not None and self._progress.request_id != request.request_id:
            self.dismiss_progress()
        external = request.progress_callback
        request.progress_callback = partial(self._on_broker_progress, request)
        name = Path(str(path)).name if path else ""
        self._progress = _ProgressSession(
            request_id=request.request_id,
            status_sink=status_sink,
            finish_status=finish_status,
            external=external,
            started=monotonic(),
            title=str(title or "导入文件"),
            index=1 if file_count else 0,
            total=max(0, int(file_count)),
            path=str(path or ""),
            file_name=name,
            phase=str(phase or "读取数据"),
            kind=KIND_WAITING,
            stage_fraction=None,
            message="",
            loaded=0,
            failed=0,
            terminal_sent=False,
            last=None,
        )
        self.progress_dialog = dialog
        self._push_current()
        self._progress_timer.start()
        self._progress_show_timer.start()

    def _show_progress_dialog(self):
        session = self._progress
        request = self._active
        dialog = self.progress_dialog
        if (session is not None and not session.terminal_sent
                and request is not None and self.is_valid(request)
                and request.request_id == session.request_id
                and dialog is not None and not sip.isdeleted(dialog)
                and not dialog.isVisible()):
            self._progress_show_timer.stop()
            dialog.show()

    def note_handoff(self, request, phase):
        session = self._editable(request)
        if session is not None:
            session.phase = phase
            session.kind = KIND_HANDOFF
            session.stage_fraction = None
            session.message = ""
            self._push_current()

    def note_file(self, request, *, index, total, path, phase):
        session = self._editable(request)
        if session is None:
            return
        session.index = int(index)
        session.total = int(total)
        session.path = str(path)
        session.file_name = Path(str(path)).name or session.file_name
        session.phase = str(phase or session.phase or "读取数据")
        session.kind = KIND_WAITING
        session.stage_fraction = None
        session.message = ""
        self._push_current()

    def note_call_started(self, request, call):
        session = self._editable(request)
        if session is None or session.kind == KIND_WAITING_USER:
            return
        session.path = str(call.path)
        session.file_name = Path(str(call.path)).name or session.file_name
        session.phase = str(getattr(call, "phase", "") or session.phase or "读取数据")
        session.kind = KIND_READING
        session.stage_fraction = None
        self._push_current()

    def note_user_wait(self, request, message, *, show_progress=True):
        session = self._editable(request)
        if session is None:
            return
        session.kind = KIND_WAITING_USER
        session.message = str(message or "等待处理")
        session.stage_fraction = None
        self._push_current()
        if show_progress:
            self._show_progress_dialog()

    def resume_after_user_wait(self, request):
        session = self._editable(request)
        if session is None or session.kind != KIND_WAITING_USER:
            return
        session.kind = KIND_READING
        session.message = ""
        session.stage_fraction = None
        self._push_current()

    def on_progress_cancel(self):
        session = self._progress
        if session is not None and not session.terminal_sent and session.kind != KIND_CANCELLING:
            session.kind = KIND_CANCELLING
            session.message = ""
            session.stage_fraction = None
            self._push_current()
        self.cancel()

    def publish_terminal(self, request, status):
        session = self._progress
        if session is None or session.request_id != request.request_id or session.terminal_sent:
            return
        session.terminal_sent = True
        self._progress_timer.stop()
        self._progress_show_timer.stop()
        session.kind = {
            "success": KIND_SUCCESS,
            "partial": KIND_PARTIAL,
            "failed": KIND_FAILED,
            "cancelled": KIND_CANCELLED,
        }.get(status, KIND_FAILED)
        session.loaded = int(request.loaded_files)
        session.failed = int(request.failed_files)
        session.stage_fraction = 1.0 if session.kind == KIND_SUCCESS else None
        session.message = ""
        self._push_current()

    def dismiss_progress(self, request=None):
        session = self._progress
        if session is None:
            return
        if request is not None and session.request_id != request.request_id:
            return
        self._progress_timer.stop()
        self._progress_show_timer.stop()
        dialog = self.progress_dialog
        finish = session.finish_status
        self._progress = None
        self.progress_dialog = None
        if dialog is not None:
            try:
                if not sip.isdeleted(dialog):
                    dialog.dismiss()
            except RuntimeError:
                pass
        if finish is not None and self.host is not None:
            finish()

    def _editable(self, request):
        session = self._progress
        if session is None or session.terminal_sent or session.request_id != request.request_id:
            return None
        if session.kind == KIND_CANCELLING:
            return None
        return session

    def _on_broker_progress(self, request, fraction, phase):
        session = self._progress
        if session is None or session.terminal_sent or session.request_id != request.request_id:
            return
        if session.kind in (KIND_CANCELLING, KIND_WAITING_USER):
            external = session.external
            if external is not None:
                external(fraction, phase)
            return
        try:
            value = float(fraction)
        except (TypeError, ValueError):
            value = -1.0
        if value != value:
            value = -1.0
        session.phase = str(phase or session.phase or "读取数据")
        if value < 0:
            session.kind = KIND_READING
            session.stage_fraction = None
        elif value >= 1.0:
            # Broker 1.0 is the read/handoff boundary, not a committed import.
            session.kind = KIND_HANDOFF
            session.stage_fraction = None
        else:
            session.kind = KIND_STAGE
            session.stage_fraction = value
        self._push_current()
        if session.external is not None:
            session.external(fraction, phase)

    def _on_progress_tick(self):
        session = self._progress
        if session is None or session.terminal_sent:
            self._progress_timer.stop()
            return
        self._push_current()

    def _push_current(self):
        session = self._progress
        if session is None:
            return
        snapshot = build_import_progress_snapshot(
            kind=session.kind,
            title=session.title,
            file_name=session.file_name or "导入文件",
            full_path=session.path,
            index=session.index,
            total=session.total,
            phase=session.phase,
            elapsed_s=max(0.0, monotonic() - session.started),
            stage_fraction=session.stage_fraction,
            loaded=session.loaded,
            failed=session.failed,
            message=session.message,
        )
        previous = session.last
        session.last = snapshot
        if _progress_snapshot_changed(previous, snapshot):
            self.progress_log.append(snapshot)
            if len(self.progress_log) > 200:
                del self.progress_log[:-200]
        dialog = self.progress_dialog
        if dialog is not None:
            try:
                if sip.isdeleted(dialog):
                    self.progress_dialog = None
                else:
                    dialog.apply_snapshot(snapshot)
            except RuntimeError:
                self.progress_dialog = None
        if session.status_sink is not None and self.host is not None:
            session.status_sink(snapshot)


def _progress_snapshot_changed(previous, snapshot) -> bool:
    if previous is None:
        return True
    return (
        previous.kind != snapshot.kind
        or previous.phase != snapshot.phase
        or previous.index != snapshot.index
        or previous.bar_current != snapshot.bar_current
        or previous.bar_total != snapshot.bar_total
        or previous.indeterminate != snapshot.indeterminate
        or         previous.terminal != snapshot.terminal
        or previous.file_name != snapshot.file_name
    )


@dataclass
class _ProgressSession:
    request_id: str
    status_sink: object
    finish_status: object
    external: object
    started: float
    title: str
    index: int
    total: int
    path: str
    file_name: str
    phase: str
    kind: str
    stage_fraction: object
    message: str
    loaded: int
    failed: int
    terminal_sent: bool
    last: object
