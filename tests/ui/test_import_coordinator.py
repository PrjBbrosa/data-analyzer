"""GUI import tasks keep the event loop live and retire before window teardown."""
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
