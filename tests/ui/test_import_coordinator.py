"""GUI import tasks keep the event loop live and retire before window teardown."""
from pathlib import Path
from threading import Event
from time import monotonic

import pytest
from PyQt5.QtCore import QThread, QTimer
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.main_window.import_coordinator import ImportCall, ImportCoordinator


def test_slow_broker_keeps_gui_live_and_commits_on_gui_thread(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    release = Event()
    entered = Event()
    seen = []

    def broker(method, path, **kwargs):
        entered.set()
        assert release.wait(2)
        return 42

    owner = ImportCoordinator(host, broker=broker)
    ticks = []
    timer = QTimer(host)
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(monotonic()))
    timer.start()

    def workflow(request):
        value = yield ImportCall('load_csv', 'x.csv')
        seen.append((value, QThread.currentThread() is host.thread()))

    owner.submit(workflow)
    qtbot.waitUntil(entered.is_set)
    qtbot.waitUntil(lambda: len(ticks) >= 5)
    assert seen == []
    release.set()
    qtbot.waitUntil(lambda: not owner.busy)
    assert seen == [(42, True)]
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < .5


@pytest.mark.parametrize('operation', ['cancel', 'invalidate_session', 'shutdown'])
def test_cancel_and_late_completion_are_single_terminal(qtbot, operation):
    host = QWidget()
    qtbot.addWidget(host)
    entered = Event()
    release = Event()
    commits = []
    terminals = []

    def broker(method, path, *, cancel_check, **kwargs):
        entered.set()
        assert release.wait(2)
        assert cancel_check()
        return 'late result'

    owner = ImportCoordinator(host, broker=broker)
    owner.finished.connect(lambda *args: terminals.append(args))

    def workflow(request):
        commits.append((yield ImportCall('load_csv', 'x.csv')))

    owner.submit(workflow)
    qtbot.waitUntil(entered.is_set)
    getattr(owner, operation)()
    release.set()
    qtbot.waitUntil(lambda: not owner.busy)
    assert commits == []
    assert len(terminals) == 1
    assert terminals[0][1] == 'cancelled'


def test_error_is_thrown_into_workflow_then_next_file_runs(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    calls = []
    seen = []

    def broker(method, path, **kwargs):
        calls.append(path)
        if path == 'bad':
            raise RuntimeError('native crash')
        return 'good'

    owner = ImportCoordinator(host, broker=broker)

    def workflow(request):
        try:
            yield ImportCall('load_csv', 'bad')
        except RuntimeError as exc:
            seen.append(str(exc))
        seen.append((yield ImportCall('load_csv', 'good')))

    owner.submit(workflow)
    qtbot.waitUntil(lambda: not owner.busy)
    assert calls == ['bad', 'good']
    assert seen == ['native crash', 'good']


def _csv_result():
    import pandas as pd
    return pd.DataFrame({'Time': [0., .1, .2], 'sig': [1., 2., 3.]}), ['Time', 'sig'], {'sig': 'V'}


def _main_window(qtbot, monkeypatch, broker):
    from mf4_analyzer.ui.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    window._imports.broker = broker
    errors = []
    monkeypatch.setattr(window, '_show_async_import_error', errors.append)
    monkeypatch.setattr(window, 'toast', lambda *a, **k: None)
    return window, errors


def test_ordinary_open_returns_before_commit_and_retains_target(qtbot, monkeypatch, tmp_path):
    entered, release = Event(), Event()

    def broker(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    original = window.view_manager.get(0)
    path = tmp_path / 'slow.csv'
    path.write_text('Time,sig\n0,1\n.1,2\n')
    window._open_data_paths([path])
    assert window.files == {}
    qtbot.waitUntil(entered.is_set)
    window.view_manager.new_view()
    window.view_manager.set_active(1)
    release.set()
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert not errors
    assert len(window.files) == 1
    assert original.attached_file_ids == list(window.files)
    assert not window.view_manager.get(1).attached_file_ids


@pytest.mark.parametrize('failure', ['construct', 'navigator'])
def test_multigroup_failure_rolls_back_only_request(qtbot, monkeypatch, failure):
    entered, release = Event(), Event()

    def broker(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        data, channels, units = _csv_result()
        return [dict(data=data.copy(), channels=channels, units=units,
                     source_metadata={}, channel_metadata={}, label_suffix=str(i)) for i in range(2)]

    window, errors = _main_window(qtbot, monkeypatch, broker)
    existing = window._register_file_data('existing.csv', *_csv_result())
    original_fids = list(window.files)
    construct = window._prepare_file_data
    add = window.navigator.add_file
    count = [0]

    def failing(*args, **kwargs):
        count[0] += 1
        if count[0] == 2:
            raise ValueError('injected second group failure')
        return (construct if failure == 'construct' else add)(*args, **kwargs)

    monkeypatch.setattr(window if failure == 'construct' else window.navigator,
                        '_prepare_file_data' if failure == 'construct' else 'add_file', failing)
    window._load_one('multi.mat')
    qtbot.waitUntil(entered.is_set)
    existing.fs = 321.0  # user edit made while the new import was pending
    release.set()
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert len(errors) == 1
    assert list(window.files) == original_fids
    assert existing.fs == 321.0
    assert list(window.navigator_order.file_fids()) == original_fids
    assert window.navigator.file_list_count() == 1


def test_deleted_target_discards_result(qtbot, monkeypatch):
    entered, release = Event(), Event()

    def broker(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    window._load_one('slow.csv')
    qtbot.waitUntil(entered.is_set)
    # Replace the sole view, as when its tab is removed/reset.
    window.view_manager.views = [window.view_manager._make(0)]
    release.set()
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert not window.files
    assert not errors


def test_project_restore_waits_for_sources_and_manual_rate(qtbot, monkeypatch, tmp_path):
    from mf4_analyzer.io.loader import DataLoader
    calls = []

    def broker(method, path, *, kwargs, **unused):
        calls.append((method, kwargs))
        return getattr(DataLoader, method)(path, **kwargs)

    source, errors = _main_window(qtbot, monkeypatch, broker)
    path = tmp_path / 'no_time.csv'
    path.write_text('sig\n1\n2\n3\n')
    source._load_one(path, sampling_rate=50.)
    qtbot.waitUntil(lambda: not source._imports.busy)
    project = tmp_path / 'saved.tlproj'
    source.save_project(project)
    restored, errors = _main_window(qtbot, monkeypatch, broker)
    restored.open_project(project)
    assert not restored.files
    qtbot.waitUntil(lambda: not restored._imports.busy)
    assert not errors
    assert len(restored.files) == 1
    assert next(iter(restored.files.values())).fs == 50.
    assert calls[-1] == ('load_csv', {'sampling_rate': 50.})
    assert not restored._restoring_project


def test_window_close_cancels_and_defers_teardown(qtbot, monkeypatch):
    entered, release = Event(), Event()

    def broker(*args, cancel_check, **kwargs):
        entered.set()
        assert release.wait(2)
        assert cancel_check()
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    window._load_one('slow.csv')
    qtbot.waitUntil(entered.is_set)
    window.close()
    assert window._imports.closing
    assert window._imports.busy
    release.set()
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert not window.files
    assert not errors


def test_broker_cancelled_stops_batch_without_success(qtbot, monkeypatch):
    from mf4_analyzer.io.import_process import ImportProcessError
    calls, notices, terminals = [], [], []

    def broker(method, path, **kwargs):
        calls.append(str(path))
        raise ImportProcessError('cancelled', 'cancelled by broker', stage='读取')

    window, errors = _main_window(qtbot, monkeypatch, broker)
    monkeypatch.setattr(window, 'toast', lambda *args: notices.append(args))
    window._imports.finished.connect(lambda *args: terminals.append(args))
    window._open_data_paths(['cancel.csv', 'never.csv'])
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert calls == ['cancel.csv']
    assert not window.files
    assert not errors
    assert not any(level == 'success' for _, level in notices)
    assert len(terminals) == 1 and terminals[0][1] == 'cancelled'


def test_destroyed_parent_reaps_supervisor_without_touching_widgets(qtbot):
    from PyQt5 import sip
    host = QWidget()
    entered, release = Event(), Event()
    commits = []

    def broker(method, path, *, cancel_check, **kwargs):
        entered.set()
        assert release.wait(2)
        assert cancel_check()
        return 42

    owner = ImportCoordinator(host, broker=broker)
    terminals = []
    owner.finished.connect(lambda *args: terminals.append(args))

    def workflow(request):
        commits.append((yield ImportCall('load_csv', 'x.csv')))

    owner.submit(workflow)
    qtbot.waitUntil(entered.is_set)
    sip.delete(host)
    release.set()
    qtbot.waitUntil(lambda: len(terminals) == 1)
    assert commits == []
    assert terminals[0][1] == 'cancelled'


def test_real_broker_csv_failure_then_success(qtbot, monkeypatch, tmp_path):
    from mf4_analyzer.ui.main_window.import_coordinator import run_import
    window, errors = _main_window(qtbot, monkeypatch, run_import)
    path = tmp_path / 'real.csv'
    path.write_text('Time,sig\n0,1\n.1,2\n.2,3\n')
    ticks = []
    timer = QTimer(window)
    timer.setInterval(100)
    timer.timeout.connect(lambda: ticks.append(monotonic()))
    timer.start()
    window._open_data_paths([tmp_path / 'missing.csv', path])
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=20000)
    assert len(errors) == 1
    assert len(window.files) == 1
    fd = next(iter(window.files.values()))
    assert fd.data['sig'].tolist() == [1., 2., 3.]
    assert len(ticks) >= 2
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < .5


def test_project_switch_invalidates_old_import(qtbot, monkeypatch, tmp_path):
    entered, release = Event(), Event()

    def broker(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    project = tmp_path / 'empty.tlproj'
    window.save_project(project)
    window._load_one('old-session.csv')
    qtbot.waitUntil(entered.is_set)
    window.open_project(project)
    release.set()
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert not window.files
    assert not errors
    assert window._project_path == project
    assert not window._restoring_project


def test_cancelled_restore_drops_previous_save_target(qtbot, monkeypatch, tmp_path):
    path = tmp_path / 'source.csv'
    path.write_text('Time,sig\n0,1\n.1,2\n')
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **k: _csv_result())
    window._load_one(path)
    qtbot.waitUntil(lambda: not window._imports.busy)
    project = tmp_path / 'previous.tlproj'
    window.save_project(project)
    entered, release = Event(), Event()

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return _csv_result()

    window._imports.broker = slow
    window.open_project(project)
    qtbot.waitUntil(entered.is_set)
    assert window._imports.progress_dialog is not None
    window._imports.cancel()
    release.set()
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert window._project_path is None
    assert not window._restoring_project
    assert not window.files
    assert not errors


@pytest.mark.parametrize('paths, expected, counts', [
    (['bad.csv'], 'failed', (0, 1)),
    (['bad.csv', 'good.csv'], 'partial', (1, 1)),
    (['good.csv'], 'success', (1, 0)),
])
def test_file_failures_define_task_terminal_state(qtbot, monkeypatch, paths, expected, counts):
    def broker(method, path, **kwargs):
        if path == 'bad.csv':
            raise ValueError('broken source')
        data, channels, units = _csv_result()
        # A successfully loaded source's warnings do not mean a failed task.
        data.attrs['source_metadata'] = {'warnings': ['source warning']}
        return data, channels, units

    window, errors = _main_window(qtbot, monkeypatch, broker)
    terminals, notices = [], []
    window._imports.finished.connect(lambda *args: terminals.append(args))
    monkeypatch.setattr(window, 'toast', lambda *args: notices.append(args))
    window._open_data_paths(paths)
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert len(terminals) == 1
    _, state, summary = terminals[0]
    assert state == expected
    assert (summary.loaded_files, summary.failed_files) == counts
    assert len(errors) == counts[1]
    if state != 'success':
        assert not any(level == 'success' for _, level in notices)


def test_cancel_button_is_visible_and_clickable_during_slow_import(qtbot, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QPushButton
    entered = Event()

    def broker(*args, cancel_check, **kwargs):
        entered.set()
        deadline = monotonic() + 3
        while not cancel_check() and monotonic() < deadline:
            Event().wait(.01)
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    window.show()
    window._load_one('slow.csv')
    try:
        qtbot.waitUntil(entered.is_set)
        qtbot.wait(800)
        dialog = window._imports.progress_dialog
        button = next(b for b in dialog.findChildren(QPushButton) if b.text() == '取消导入')
        assert dialog.isVisible()
        assert button.isVisible()
        started = monotonic()
        qtbot.mouseClick(button, Qt.LeftButton)
        qtbot.waitUntil(lambda: not window._imports.busy, timeout=3000)
        assert monotonic() - started < 3
        assert not window.files
        assert not errors
    finally:
        window._imports.cancel()
        qtbot.waitUntil(lambda: not window._imports.busy, timeout=4000)


import json
import numpy as np
import pandas as pd


def test_activation_failure_rolls_back_all_groups(qtbot, monkeypatch):
    groups = [dict(data=pd.DataFrame({'Time': np.arange(3 + i) * .1, 'sig': np.arange(3 + i)}),
                   channels=['Time', 'sig'], units={}, source_metadata={}, channel_metadata={},
                   label_suffix=str(i)) for i in range(2)]
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **k: groups)
    terminals = []
    window._imports.finished.connect(lambda *args: terminals.append(args))
    activate = window._on_file_activated

    def fail(fid):
        raise RuntimeError('review injected activation failure')

    monkeypatch.setattr(window, '_on_file_activated', fail)
    window._load_one('two.mat')
    qtbot.waitUntil(lambda: not window._imports.busy)
    monkeypatch.setattr(window, '_on_file_activated', activate)
    observed = dict(terminal=terminals[0][1], files=list(window.files),
                    navigator=window.navigator.file_list_count(), errors=len(errors))
    print('ACTIVATION ' + json.dumps(observed))
    assert observed['terminal'] == 'failed'
    assert observed['files'] == []
    assert observed['errors'] == 1


def test_cancel_in_wwt_prompt_leaves_no_source_or_layout(qtbot, monkeypatch, tmp_path):
    from tests._helpers import wwt_factory as wwt
    from mf4_analyzer.io.loader import DataLoader

    path = wwt.channel_xy_with_auxiliaries(tmp_path / 'layout.wwt')
    loaded = DataLoader.load_wwt_document(path)
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **k: loaded)
    initial = [state.view_id for state in window.view_manager.views]
    terminals, recent = [], []
    window._imports.finished.connect(lambda *args: terminals.append(args))
    monkeypatch.setattr(window._recent_files, 'record_file', recent.append)

    def cancel_during_modal(*args):
        window._imports.cancel()
        return True

    monkeypatch.setattr(window._wwt_import, '_ask_layout', cancel_during_modal)
    window._load_one(path)
    qtbot.waitUntil(lambda: not window._imports.busy)
    observed = dict(terminal=terminals[0][1], before=initial,
                    after=[state.view_id for state in window.view_manager.views],
                    files=list(window.files), recent=recent, errors=len(errors))
    print('WWT_CANCEL ' + json.dumps(observed))
    assert observed['terminal'] == 'cancelled'
    assert observed['after'] == observed['before']
    assert observed['recent'] == []
    assert observed['files'] == []
    assert not errors


def test_filedata_full_time_scan_runs_off_gui_thread(qtbot, monkeypatch):
    axis = np.arange(50_000.) * .01
    result = (pd.DataFrame({'Time': axis, 'sig': axis}), ['Time', 'sig'], {})
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **k: result)
    original = np.median
    observed = []

    def median(values, *args, **kwargs):
        if np.size(values) == 49_999:
            observed.append(QThread.currentThread() is window.thread())
        return original(values, *args, **kwargs)

    monkeypatch.setattr(np, 'median', median)
    window._load_one('samples.csv')
    qtbot.waitUntil(lambda: not window._imports.busy)
    print('FILEDATA_SCAN ' + json.dumps(dict(gui_thread=observed, samples=len(axis), errors=len(errors))))
    assert observed and not any(observed)


def test_failed_restore_drops_previous_project_save_target(qtbot, monkeypatch, tmp_path):
    path = tmp_path / 'source.csv'
    path.write_text('Time,sig\n0,1\n.1,2\n.2,3\n')
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **k: _csv_result())
    window._load_one(path)
    qtbot.waitUntil(lambda: not window._imports.busy)
    previous = tmp_path / 'previous.tlproj'
    incoming = tmp_path / 'incoming.tlproj'
    window.save_project(previous)
    incoming.write_bytes(previous.read_bytes())
    old_fids = list(window.files)
    terminals = []
    window._imports.finished.connect(lambda *args: terminals.append(args))

    def fail(*args, **kwargs):
        raise RuntimeError('review injected restore projection failure')

    monkeypatch.setattr(window, '_open_project_restoring', fail)
    window.open_project(incoming)
    qtbot.waitUntil(lambda: not window._imports.busy)
    observed = dict(terminal=terminals[0][1], old_fids=old_fids, files=list(window.files),
                    save_target=str(window._project_path), incoming=str(incoming),
                    restoring=window._restoring_project, errors=len(errors))
    print('RESTORE_FAILURE ' + json.dumps(observed))
    assert observed['terminal'] == 'failed'
    assert observed['files'] != observed['old_fids']
    assert window._project_path is None


@pytest.mark.parametrize('retry', [False, True])
def test_timeout_requires_explicit_extension_choice(qtbot, monkeypatch, retry):
    from mf4_analyzer.io.import_process import ImportProcessError
    from PyQt5.QtWidgets import QMessageBox
    calls, decisions, terminals = [], [], []

    def broker(method, path, *, limits, **kwargs):
        calls.append((str(path), limits.timeout_seconds))
        if len(calls) == 1:
            raise ImportProcessError('timeout', 'timed out', stage='读取')
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    window._imports.finished.connect(lambda *args: terminals.append(args))

    def choose(box):
        decisions.append((box.text(), box.informativeText()))
        snap = window._imports.current_progress
        assert snap is not None and snap.kind == 'waiting_user'
        assert snap.indeterminate is False
        assert '等待确认是否延长并重试' in snap.headline
        assert '剩余' not in snap.headline
        dialog = window._imports.progress_dialog
        assert dialog is not None and dialog.isVisible()
        assert dialog.progress_bar.minimum() != dialog.progress_bar.maximum()
        assert dialog.progress_bar.value() != dialog.progress_bar.maximum()
        text = '延长并重试' if retry else '取消导入'
        next(button for button in box.buttons() if button.text() == text).click()
        return 0

    monkeypatch.setattr(QMessageBox, 'exec_', choose)
    window._load_one('slow.csv')
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert len(decisions) == 1
    assert '1800' in decisions[0][0] and '3600' in decisions[0][1]
    assert calls == ([('slow.csv', 1800.), ('slow.csv', 3600.)] if retry else [('slow.csv', 1800.)])
    assert len(window.files) == int(retry)
    assert not errors
    assert len(terminals) == 1
    assert terminals[0][1] == ('success' if retry else 'cancelled')


def test_broker_completion_is_not_import_success_when_registration_fails(qtbot, monkeypatch):
    def broker(method, path, *, progress_callback=None, **kwargs):
        if progress_callback is not None:
            progress_callback(0.4, '读取通道')
            progress_callback(1.0, '读取完成')
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    updates = []

    def capture(current, total, label=None, token=None, **kwargs):
        updates.append((current, total, label))

    monkeypatch.setattr(window, '_update_compute_progress', capture)

    def fail(_fid):
        raise RuntimeError('register failed')

    monkeypatch.setattr(window, '_on_file_activated', fail)
    window._load_one('register-fail.csv')
    qtbot.waitUntil(lambda: not window._imports.busy)
    log = list(window._imports.progress_log)
    kinds = [item.kind for item in log]
    assert 'stage' in kinds
    assert 'handoff' in kinds
    assert 'waiting_user' in kinds
    assert 'success' not in kinds
    assert kinds[-1] == 'failed'
    stage = next(item for item in log if item.kind == 'stage')
    assert '当前阶段 40%' in stage.headline
    assert stage.indeterminate is False
    assert stage.bar_current == 400 and stage.bar_total == 1000
    handoff = next(item for item in log if item.kind == 'handoff')
    assert handoff.indeterminate is True
    assert handoff.bar_total == 0
    assert '读取完成' in handoff.headline
    assert '导入成功' not in handoff.headline
    assert '100%' not in handoff.headline
    failed = log[-1]
    assert failed.terminal is True
    assert failed.bar_current != failed.bar_total
    assert '导入成功' not in failed.headline
    assert '100%' not in failed.headline
    assert not window.files
    assert errors
    for item in log:
        assert (item.bar_current, item.bar_total, item.status_label) in updates


def test_success_close_does_not_cancel_the_queued_import(qtbot, monkeypatch, tmp_path):
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **k: _csv_result())
    first = tmp_path / 'first.csv'
    second = tmp_path / 'second.csv'
    first.write_text('Time,sig\n0,1\n.1,2\n')
    second.write_text('Time,sig\n0,3\n.1,4\n')
    window._load_one(first)
    window._load_one(second)
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert not errors
    assert len(window.files) == 2
    successes = [item for item in window._imports.progress_log if item.kind == 'success']
    assert len(successes) == 2
    assert all(item.terminal and item.bar_current == item.bar_total == 1000 for item in successes)


def test_cancel_stays_up_until_reap_and_the_next_import_is_not_cancelled(qtbot, monkeypatch, tmp_path):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QPushButton

    entered = Event()
    release = Event()
    mode = {'slow': True}

    def broker(*args, cancel_check, **kwargs):
        if mode['slow']:
            entered.set()
            while not cancel_check():
                Event().wait(0.01)
            assert release.wait(2)
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    window.show()
    try:
        window._load_one('slow.csv')
        qtbot.waitUntil(entered.is_set)
        dialog = window._imports.progress_dialog
        qtbot.waitUntil(dialog.isVisible)
        button = next(item for item in dialog.findChildren(QPushButton) if item.text() == '取消导入')
        qtbot.mouseClick(button, Qt.LeftButton)
        snap = window._imports.current_progress
        assert dialog.isVisible()
        assert snap is not None and snap.kind == 'cancelling'
        assert snap.headline == '正在取消…'
        assert not dialog.cancel_button.isEnabled()
        assert '正在取消' in dialog.phase_label.text()
        release.set()
        qtbot.waitUntil(lambda: not window._imports.busy, timeout=4000)
        assert not window.files
        assert not errors
        mode['slow'] = False
        path = tmp_path / 'next.csv'
        path.write_text('Time,sig\n0,1\n.1,2\n')
        window._load_one(path)
        qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
        assert len(window.files) == 1
        assert not errors
    finally:
        release.set()
        window._imports.cancel()
        qtbot.waitUntil(lambda: not window._imports.busy, timeout=4000)


def test_can_candidate_after_auto_probe_budget_is_selectable(qtbot, monkeypatch, tmp_path):
    from types import SimpleNamespace
    sets = [[str(tmp_path / f'{i}.dbc')] for i in range(4)]
    probed = []

    def broker(method, path, *, kwargs, **unused):
        if method == 'read_blf_frames':
            return [(0., 1, b'\x00')]
        if method == 'probe_blf_dbc_frames':
            probed.append(kwargs['dbc_paths'])
            return SimpleNamespace(is_match=True, strength='strong')
        assert method == 'load_blf_frames'
        assert kwargs['dbc_paths'] == sets[3]
        return _csv_result()

    window, errors = _main_window(qtbot, monkeypatch, broker)
    monkeypatch.setattr(window, '_candidate_blf_dbc_paths', lambda path: sets)
    selected = []

    def choose(path, candidates):
        selected.extend(candidates)
        return sets[3]

    monkeypatch.setattr(window, '_ask_multiple_blf_dbc_candidates', choose)
    window._load_one(tmp_path / 'sample.blf')
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert len(selected) == 4
    assert probed == sets
    assert len(window.files) == 1 and not errors


def test_wwt_blank_replacement_keeps_request_valid_during_view_signals(qtbot, monkeypatch, tmp_path):
    from tests._helpers import wwt_factory as wwt
    from mf4_analyzer.io.loader import DataLoader

    batch = wwt.batch_choice_set(tmp_path, n_display=3, include_no_display=False)

    def broker(method, path, **kwargs):
        return DataLoader.load_wwt_document(path)

    window, errors = _main_window(qtbot, monkeypatch, broker)
    asked, terminals = [], []
    monkeypatch.setattr(window._wwt_import, '_ask_layout', lambda *args: asked.append(1) or True)
    # Model the target watchdog firing during View publication (render slots
    # may process GUI events). Accepted replacement must already own its target.
    window.view_manager.views_changed.connect(window._imports._check_target)
    window._imports.finished.connect(lambda *args: terminals.append(args))
    window._open_data_paths([str(path) for path in batch.ordered_paths])
    qtbot.waitUntil(lambda: not window._imports.busy)
    assert not errors
    assert terminals[0][1] == 'success'
    assert len(asked) == 3
    assert len(window.view_manager.views) == 3


def _drain_lifecycle_deletes():
    import gc
    from PyQt5.QtCore import QCoreApplication, QEvent
    for _ in range(3):
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QCoreApplication.processEvents()
    gc.collect()


@pytest.mark.parametrize('shutdown', [False, True], ids=['close_only', 'shutdown'])
def test_idle_host_close_gc_releases_application_owned_coordinator(qapp, shutdown):
    import weakref
    from PyQt5 import sip

    _drain_lifecycle_deletes()
    baseline = len(qapp.findChildren(ImportCoordinator))
    hosts, owners = [], []
    try:
        for _ in range(20):
            # Deliberately no qtbot.addWidget/deleteLater: production callers
            # and several UI tests rely on close plus GC for Python-owned hosts.
            host = QWidget()
            owner = ImportCoordinator(host)
            host._imports = owner
            hosts.append(weakref.ref(host))
            owners.append(weakref.ref(owner))
            host.close()
            if shutdown:
                assert owner.shutdown()
            del host, owner
        _drain_lifecycle_deletes()
        assert all(ref() is None for ref in hosts)
        assert all(ref() is None for ref in owners)
        assert len(qapp.findChildren(ImportCoordinator)) == baseline
    finally:
        # Ensure the intentionally RED old implementation cannot leak into
        # other tests. This runs only after the lifecycle assertions above.
        for ref in hosts:
            if ref() is not None and not sip.isdeleted(ref()):
                ref().deleteLater()
        _drain_lifecycle_deletes()


@pytest.mark.parametrize('deletion', ['close_gc', 'delete_qobject'])
def test_active_host_deletion_retains_supervisor_until_cancelled_drain(qapp, qtbot, deletion):
    import weakref
    from PyQt5 import sip

    host = QWidget()
    host_ref = weakref.ref(host)
    entered, release = Event(), Event()
    commits, callbacks, progress, terminals = [], [], [], []

    def broker(method, path, *, cancel_check, progress_callback, **kwargs):
        entered.set()
        assert release.wait(3)
        assert cancel_check()
        progress_callback(1.0, 'late progress')
        return 'late value'

    owner = ImportCoordinator(host, broker=broker)
    host._imports = owner
    owner.finished.connect(lambda *args: terminals.append(args))

    def workflow(request):
        commits.append((yield ImportCall('load_csv', 'x.csv')))

    owner.submit(workflow, on_done=lambda *args: callbacks.append(args),
                 progress_callback=lambda *args: progress.append(args))
    try:
        qtbot.waitUntil(entered.is_set)
        thread_ref = weakref.ref(owner._thread)
        if deletion == 'close_gc':
            host.close()
        else:
            sip.delete(host)
        del host
        _drain_lifecycle_deletes()
        assert host_ref() is None
        assert owner.host is None
        assert owner.closing
        assert owner.parent() is qapp
        assert not sip.isdeleted(owner)
        assert thread_ref() is not None and thread_ref().isRunning()
        release.set()
        qtbot.waitUntil(lambda: sip.isdeleted(owner))
        _drain_lifecycle_deletes()
        assert len(terminals) == 1
        assert terminals[0][1] == 'cancelled'
        assert commits == callbacks == progress == []
        assert thread_ref() is None
    finally:
        if host_ref() is not None and not sip.isdeleted(host_ref()):
            host_ref().deleteLater()
        _drain_lifecycle_deletes()
        release.set()
        qtbot.waitUntil(lambda: sip.isdeleted(owner) or not owner.busy)


_SHARED_AXIS = "MDF shared-axis conversion/alignment/frame"


def _resource_exc(kind, *, requested=None, limit=None, unit="bytes"):
    from mf4_analyzer.io.import_limits import parse_resource_envelope
    from mf4_analyzer.io.import_process import ImportProcessError

    payload = {
        "schema": 1,
        "resource_kind": kind,
        "unit": unit,
        "phase": "admission",
        "estimate_basis": "test",
        "label": _SHARED_AXIS,
    }
    if requested is not None:
        payload["requested"] = int(requested)
        payload["limit"] = int(limit)
        payload["components"] = [{
            "name": _SHARED_AXIS, "amount": int(requested), "unit": unit,
        }]
    return ImportProcessError(
        "resource_limit",
        "导入资源超过预算",
        stage="admission",
        detail="worker detail",
        resource=parse_resource_envelope(payload),
        request_id="req-fixed-1",
    )


def _csv_file(path):
    path.write_text("Time,sig\n0,1\n.1,2\n.2,3\n")
    return path


def _patch_message_boxes(monkeypatch, on_resource):
    from PyQt5.QtWidgets import QMessageBox
    from mf4_analyzer.ui_kit.message_dialog import AppMessageDialog

    shown, critical = [], []

    def drive(self):
        self._captured_text = self._text_label.text()
        shown.append(self)
        on_resource(self)
        if self.message_result is None:
            self.button("close").click()
        return 0

    monkeypatch.setattr(AppMessageDialog, "exec_", drive)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: critical.append(args))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "exec_", lambda self: 0)
    return shown, critical


def _window_for_broker(qtbot, monkeypatch, broker):
    from mf4_analyzer.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._imports.broker = broker
    toasts, recent = [], []
    monkeypatch.setattr(window, "toast", lambda *args, **kwargs: toasts.append(args))
    original = window._recent_files.record_file

    def spy(path, *args, **kwargs):
        recent.append(str(path))
        return original(path)

    monkeypatch.setattr(window._recent_files, "record_file", spy)
    return window, toasts, recent


def _action_ids(dialog):
    return [
        button.property("appMessageActionId")
        for button in dialog._buttons.values()
    ]


@pytest.mark.parametrize(
    ("kind", "unit", "requested", "limit", "needle", "recheck", "forbid"),
    [
        ("memory_estimate", "bytes", 638_976_000, 498_988_944, "约609 MiB", True, "638,976,000"),
        ("temp_disk", "bytes", 10 * 1024 * 1024, 1024 * 1024, "这不是内存预算不足", False, None),
        ("channel_count", "count", 120_000, 100_000, "通道数量为 120,000", False, "MiB"),
        ("not_a_real_kind", "bytes", None, None, "未提供估算", False, "MiB"),
    ],
)
def test_resource_failure_dialog_uses_structured_copy(
    qtbot, monkeypatch, tmp_path, kind, unit, requested, limit, needle, recheck, forbid,
):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.io.import_limits import (
        resource_action_ids, resource_technical_detail, resource_user_text,
    )

    exc = _resource_exc(kind, requested=requested, limit=limit, unit=unit)
    path = _csv_file(tmp_path / "sample.csv")
    calls = []

    def broker(method, file_path, **kwargs):
        calls.append(str(file_path))
        raise exc

    captured = {}

    def on_resource(dialog):
        snap = window._imports.current_progress
        progress = window._imports.progress_dialog
        captured["snap"] = snap
        captured["text"] = dialog._text_label.text()
        captured["actions"] = _action_ids(dialog)
        captured["plain"] = dialog._text_label.textFormat() == Qt.PlainText
        captured["detail_hidden"] = dialog._detailed_label.isHidden()
        dialog.button("copy_diagnostics").click()
        captured["clipboard"] = QApplication.clipboard().text()
        dialog.button("toggle_details").click()
        captured["detail"] = dialog._detailed_label.text()
        captured["detail_open"] = not dialog._detailed_label.isHidden()
        captured["toggle_id"] = dialog.button("toggle_details").property("appMessageActionId")
        assert progress is not None and progress.isVisible()
        assert progress.progress_bar.minimum() != progress.progress_bar.maximum()
        assert snap is not None and snap.kind == "waiting_user" and snap.indeterminate is False
        assert "等待处理导入错误" in snap.headline

    shown, critical = _patch_message_boxes(monkeypatch, on_resource)
    window, toasts, recent = _window_for_broker(qtbot, monkeypatch, broker)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert len(shown) == 1 and not critical
    assert captured["plain"] is True
    assert captured["detail_hidden"] is True and captured["detail_open"] is True
    assert captured["toggle_id"] == "toggle_details"
    assert captured["text"] == resource_user_text(exc)
    assert needle in captured["text"]
    assert "shared-axis" not in captured["text"]
    assert set(captured["actions"]) == set(resource_action_ids(exc))
    assert ("recheck_retry" in captured["actions"]) is recheck
    if forbid:
        assert forbid not in captured["text"]
    assert captured["detail"] == resource_technical_detail(
        exc, stage=exc.stage, detail=exc.detail, request_id=exc.request_id,
    )
    assert _SHARED_AXIS in captured["detail"]
    assert "req-fixed-1" in captured["clipboard"]
    if requested is not None:
        assert f"{int(requested):,}" in captured["clipboard"]
        assert f"{int(requested):,}" in captured["detail"]
    else:
        assert "未提供估算" in captured["clipboard"]
    assert calls == [str(path)]
    assert not window.files
    assert str(path) not in recent
    assert not any(len(item) > 1 and item[1] == "success" for item in toasts)


def test_recheck_uses_new_default_limits_for_the_failed_file_only(
    qtbot, monkeypatch, tmp_path,
):
    from mf4_analyzer.io.import_limits import ImportLimits

    good = _csv_file(tmp_path / "good.csv")
    bad = _csv_file(tmp_path / "bad.csv")
    exc = _resource_exc(
        "memory_estimate", requested=638_976_000, limit=498_988_944,
    )
    first = ImportLimits(max_memory_bytes=300_000_000, max_output_bytes=150_000_000)
    second = ImportLimits(max_memory_bytes=200_000_000, max_output_bytes=100_000_000)
    produced, seen, ids, parsed = [], [], [], []

    def fake_default():
        value = second if produced else first
        produced.append(value)
        return value

    monkeypatch.setattr(
        "mf4_analyzer.io.import_limits.default_limits", fake_default,
    )

    def forbid_parent_parse(*args, **kwargs):
        parsed.append(args)
        raise AssertionError("parent parsed MF4 during recheck")

    monkeypatch.setattr(
        "mf4_analyzer.io.loader.DataLoader.load_mf4", forbid_parent_parse,
    )

    bad_attempts = []

    def broker(method, file_path, **kwargs):
        seen.append(kwargs.get("limits"))
        active = window._imports._active
        ids.append(getattr(active, "worker_request_id", ""))
        if Path(str(file_path)).name == bad.name:
            bad_attempts.append(1)
            if len(bad_attempts) == 1:
                raise exc
        return _csv_result()

    held = {}

    def on_resource(dialog):
        held["fids"] = list(window.files)
        held["recent"] = list(recent)
        held["old_limits"] = window._imports._active.limits
        button = dialog.button("recheck_retry")
        assert button.property("appMessageActionId") == "recheck_retry"
        button.setText("关闭")
        button.click()

    _patch_message_boxes(monkeypatch, on_resource)
    window, toasts, recent = _window_for_broker(qtbot, monkeypatch, broker)
    window._open_data_paths([str(good), str(bad)])
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert produced == [first, second]
    assert seen == [first, first, second]
    assert seen[2] is second and seen[2] is not held["old_limits"]
    assert second.max_memory_bytes < first.max_memory_bytes
    assert seen[2].max_output_bytes == second.max_output_bytes
    assert ids[2] and ids[2] != ids[1]
    assert held["fids"] and all(fid in window.files for fid in held["fids"])
    assert len(window.files) == len(held["fids"]) + 1
    assert recent.count(str(good)) == 1 and recent.count(str(bad)) == 1
    assert str(bad) not in held["recent"]
    assert not parsed


def test_close_does_not_retry_or_reregister_successful_files(
    qtbot, monkeypatch, tmp_path,
):
    first = _csv_file(tmp_path / "a.csv")
    failed = _csv_file(tmp_path / "bad.csv")
    third = _csv_file(tmp_path / "c.csv")
    exc = _resource_exc("memory_estimate", requested=638_976_000, limit=498_988_944)
    names = []

    def broker(method, file_path, **kwargs):
        names.append(Path(str(file_path)).name)
        if Path(str(file_path)).name == failed.name:
            raise exc
        return _csv_result()

    captured = {}

    def on_close(dialog):
        captured["actions"] = _action_ids(dialog)

    shown, critical = _patch_message_boxes(monkeypatch, on_close)
    window, toasts, recent = _window_for_broker(qtbot, monkeypatch, broker)
    window._open_data_paths([str(first), str(failed), str(third)])
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert len(shown) == 1 and not critical
    assert "recheck_retry" in captured["actions"]
    assert names == ["a.csv", "bad.csv", "c.csv"]
    assert len(window.files) == 2
    loaded = {fd.filename for fd in window.files.values()}
    assert loaded == {"a.csv", "c.csv"}
    assert str(failed) not in recent
    assert not any(len(item) > 1 and item[1] == "success" and "bad.csv" in item[0] for item in toasts)


def test_recheck_refuses_a_changed_source_or_a_missing_target(
    qtbot, monkeypatch, tmp_path,
):
    path = _csv_file(tmp_path / "moving.csv")
    exc = _resource_exc("memory_estimate", requested=638_976_000, limit=498_988_944)
    calls = []

    def broker(method, file_path, **kwargs):
        calls.append(str(file_path))
        raise exc

    captured = {}

    def change_source(dialog):
        captured["actions"] = _action_ids(dialog)
        path.write_text("Time,sig\n0,1\n.1,2\n.2,3\n.3,4\n")
        dialog.button("recheck_retry").click()

    shown, _critical = _patch_message_boxes(monkeypatch, change_source)
    window, _toasts, _recent = _window_for_broker(qtbot, monkeypatch, broker)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert len(shown) == 1 and "recheck_retry" in captured["actions"]
    assert calls == [str(path)]
    assert not window.files

    target = _csv_file(tmp_path / "target.csv")
    calls.clear()
    shown.clear()

    def drop_target(dialog):
        window.view_manager.views = [window.view_manager._make(0)]
        dialog.button("recheck_retry").click()

    shown, _critical = _patch_message_boxes(monkeypatch, drop_target)
    window, _toasts, _recent = _window_for_broker(qtbot, monkeypatch, broker)
    window._load_one(str(target))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert len(shown) == 1
    assert calls == [str(target)]
    assert not window.files


def test_recheck_does_not_start_while_the_worker_is_alive(qtbot, tmp_path):
    path = _csv_file(tmp_path / "busy.csv")
    entered, release = Event(), Event()
    calls = []

    def broker(method, file_path, **kwargs):
        calls.append(str(file_path))
        entered.set()
        assert release.wait(2)
        return _csv_result()

    host = QWidget()
    qtbot.addWidget(host)
    owner = ImportCoordinator(host, broker=broker)

    def workflow(request):
        yield ImportCall("load_csv", str(path))

    owner.submit(workflow)
    qtbot.waitUntil(entered.is_set)
    try:
        assert owner._thread is not None
        assert owner.accept_resource_recheck(owner._active, owner._last_call) is False
        assert calls == [str(path)]
    finally:
        release.set()
    qtbot.waitUntil(lambda: not owner.busy, timeout=15000)


def test_timeout_extension_does_not_offer_resource_recheck(qtbot, monkeypatch, tmp_path):
    from mf4_analyzer.io.import_limits import default_limits
    from mf4_analyzer.io.import_process import ImportProcessError
    from mf4_analyzer.ui_kit import message_dialog
    from PyQt5.QtWidgets import QMessageBox

    path = _csv_file(tmp_path / "slow.csv")
    probes = {"defaults": 0, "resource_dialogs": 0}
    real_default = default_limits

    def counting_default():
        probes["defaults"] += 1
        return real_default()

    def refuse_resource_dialog(*args, **kwargs):
        probes["resource_dialogs"] += 1
        raise AssertionError("timeout dialog must not become a resource recheck")

    monkeypatch.setattr("mf4_analyzer.io.import_limits.default_limits", counting_default)
    monkeypatch.setattr(
        message_dialog, "build_import_resource_dialog", refuse_resource_dialog, raising=False,
    )
    calls = []

    def broker(method, file_path, **kwargs):
        limits = kwargs.get("limits")
        calls.append(None if limits is None else (
            limits.max_memory_bytes, limits.max_output_bytes, limits.timeout_seconds,
        ))
        if len(calls) == 1:
            raise ImportProcessError("timeout", "timed out", stage="读取")
        return _csv_result()

    window, _toasts, _recent = _window_for_broker(qtbot, monkeypatch, broker)

    def choose(box):
        labels = [button.text() for button in box.buttons()]
        ids = [button.property("appMessageActionId") for button in box.buttons()]
        assert "延长并重试" in labels and "取消导入" in labels
        assert "recheck_retry" not in ids
        assert "重新检查并重试" not in labels
        next(button for button in box.buttons() if button.text() == "延长并重试").click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec_", choose)
    window._load_one(str(path))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert probes["resource_dialogs"] == 0
    assert len(calls) == 2
    assert calls[0][0] == calls[1][0] and calls[0][1] == calls[1][1]
    assert calls[1][2] == calls[0][2] * 2
    assert probes["defaults"] == 1


def test_project_restore_and_batch_dbc_use_the_resource_dialog(
    qtbot, monkeypatch, tmp_path,
):
    from mf4_analyzer.io.import_limits import resource_user_text

    exc = _resource_exc("memory_estimate", requested=638_976_000, limit=498_988_944)
    source = _csv_file(tmp_path / "restore.csv")
    state = {"fail": False}
    calls = []

    def broker(method, file_path, **kwargs):
        calls.append(Path(str(file_path)).name)
        if state["fail"]:
            raise exc
        return _csv_result()

    shown, critical = _patch_message_boxes(monkeypatch, lambda dialog: None)
    window, _toasts, _recent = _window_for_broker(qtbot, monkeypatch, broker)
    window._load_one(str(source))
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    project = tmp_path / "restore.tlproj"
    assert window.save_project(project)
    state["fail"] = True
    before = len(calls)
    window.open_project(project)
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert len(shown) == 1 and not critical
    assert shown[0]._captured_text == resource_user_text(exc)
    assert "shared-axis" not in shown[0]._captured_text
    assert calls[before:] == ["restore.csv"]
    assert not window.files

    blf = tmp_path / "batch.blf"
    blf.write_bytes(b"not-a-real-blf")
    calls.clear()
    resolved = []

    def batch_broker(method, file_path, **kwargs):
        calls.append(method)
        raise exc

    window._imports.broker = batch_broker
    window.resolve_blf_dbc_paths_for_batch_async(
        [blf], coordinator=window._imports, on_resolved=resolved.append,
    )
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert calls == ["read_blf_frames"]
    assert len(shown) == 2
    assert shown[-1]._captured_text == resource_user_text(exc)
    assert not critical
    assert resolved == []


@pytest.mark.parametrize('outcome', ['success', 'error', 'cancel', 'invalidate_session'])
def test_completed_call_releases_bound_transform_and_large_kwargs(qapp, qtbot, monkeypatch, outcome):
    import weakref
    import numpy as np
    from PyQt5 import sip

    # A synchronous diagnostic handler, like production. pytest's capturing
    # handlers retain traceback frames (and their arrays) until test teardown.
    import io
    import logging
    sink = io.StringIO()
    diagnostic = logging.Logger("import-lifetime-test")
    diagnostic.addHandler(logging.StreamHandler(sink))
    monkeypatch.setattr("mf4_analyzer.ui.main_window.import_coordinator.logger", diagnostic)

    class Host(QWidget):
        def transform(self, path, result):
            return result

    host = Host()
    payload = np.arange(1024.)
    host_ref, payload_ref = weakref.ref(host), weakref.ref(payload)
    entered, release = Event(), Event()
    terminals = []

    def broker(method, path, **kwargs):
        entered.set()
        assert release.wait(3)
        if outcome == 'error':
            raise ValueError('bad data')
        return 1

    def workflow(request, transform=host.transform, frames=payload):
        yield ImportCall('load_can', 'frames', kwargs={'frames': frames}, transform=transform)

    owner = ImportCoordinator(host, broker=broker)
    owner.finished.connect(lambda request_id, status, value: terminals.append(status))
    owner.submit(workflow)
    del workflow, payload
    try:
        qtbot.waitUntil(entered.is_set)
        if outcome in ('cancel', 'invalidate_session'):
            getattr(owner, outcome)()
        release.set()
        qtbot.waitUntil(lambda: not owner.busy)
        _drain_lifecycle_deletes()
        assert payload_ref() is None
        if outcome == "error":
            assert "bad data" in sink.getvalue()
            assert owner.failures[-1]["detail"] == "bad data"
        assert len(terminals) == 1
        # The next request still runs, independently of retired call cleanup.
        def next_workflow(request):
            yield ImportCall('load_csv', 'next')
        owner.submit(next_workflow)
        qtbot.waitUntil(lambda: not owner.busy)
        assert len(terminals) == 2
        owner.shutdown()
        host.close()
        del host
        _drain_lifecycle_deletes()
        assert host_ref() is None
    finally:
        release.set()
        if host_ref() is not None and not sip.isdeleted(host_ref()):
            host_ref().deleteLater()
        _drain_lifecycle_deletes()


def test_fast_import_finishes_before_progress_dialog_show(qtbot, monkeypatch):
    from mf4_analyzer.ui_kit.import_progress_dialog import ImportProgressDialog

    shown = []
    original_show = ImportProgressDialog.show

    def show(dialog):
        shown.append(dialog)
        return original_show(dialog)

    monkeypatch.setattr(ImportProgressDialog, "show", show)
    window, errors = _main_window(qtbot, monkeypatch, lambda *a, **kw: _csv_result())
    # Control the display deadline independently of CI load.
    window._imports._progress_show_timer.setInterval(60_000)
    window._load_one("fast.csv")
    qtbot.waitUntil(lambda: bool(window.files) and not window._imports.busy)
    assert window._imports.current_progress is None
    assert not window._imports._progress_show_timer.isActive()
    assert not shown
    assert not errors
