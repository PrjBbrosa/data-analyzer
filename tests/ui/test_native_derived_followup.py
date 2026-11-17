"""Native recipes retain time and remain usable through the editor and replay."""
import numpy as np
import pytest
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore
from mf4_analyzer.io.signal_access import read_signal, TimeSpan, SignalAccessError
from mf4_analyzer.io.channel_edit_log import replay
from mf4_analyzer.signal.channel_recipe import make_single
from mf4_analyzer.ui.dialogs import ChannelEditorDialog


def native_file(time=None, validity=None):
    t = np.arange(8.) / 4 if time is None else np.asarray(time, dtype=float)
    store = NativeSignalStore.build('derived-test', [AxisSpec('t', 'clock', 'time', 's', t)],
        [ChannelSpec(0, 1, 'raw', 't', -4*t, validity=validity)])
    return FileData.from_native_store('/data/test.mf4', store)


def test_native_editor_chain_and_replay(qtbot, monkeypatch):
    fd = native_file()
    dlg = ChannelEditorDialog(None, {'f': fd}, 'f')
    qtbot.addWidget(dlg)
    errors = []
    monkeypatch.setattr('mf4_analyzer.ui.dialogs.channel_editor.QMessageBox.critical', lambda *a: errors.append(a))
    dlg.combo_src.setCurrentText('raw')
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    dlg.combo_src.setCurrentText('abs_raw')
    dlg.combo_op.setCurrentIndex(0)
    dlg._create_single()
    assert not errors
    np.testing.assert_allclose(dlg.new_channels['d_dt_abs_raw'][0], 4.)
    results = replay(fd, dlg._edit_log.to_json())
    assert all(r.applied for r in results)
    np.testing.assert_allclose(read_signal(fd, 'd_dt_abs_raw').values, 4.)
    again = native_file()
    assert all(r.applied for r in replay(again, dlg._edit_log.to_json()))
    np.testing.assert_array_equal(read_signal(again, 'd_dt_abs_raw').values, read_signal(fd, 'd_dt_abs_raw').values)


def test_applied_derived_read_halo_hidden_and_raw_unchanged():
    fd = native_file()
    original = fd.native_store.channel('raw').raw.tobytes()
    entries = [make_single('positive', '', 'abs', 'raw', None),
               make_single('rate', '', 'derivative', 'positive', None)]
    assert all(r.applied for r in replay(fd, entries))
    series = read_signal(fd, 'rate', TimeSpan(.5, 1.), neighbor_halo=1)
    np.testing.assert_array_equal(series.time, [.25, .5, .75, 1., 1.25])
    np.testing.assert_allclose(series.values, 4.)
    assert not series.values.flags.writeable
    assert series.revision != fd.native_store.revision
    assert series.physical_key != fd.native_store.channel('raw').physical_key
    replay(fd, [{'op': 'remove', 'names': ['raw', 'positive']}])
    for name in ['raw', 'positive']:
        with pytest.raises(SignalAccessError):
            read_signal(fd, name)
    assert fd.native_store.channel('raw').raw.tobytes() == original


@pytest.mark.parametrize('time', [np.arange(8.)/4, np.array([0., .25, .6, 1., 1.2, 1.7, 2.5, 3.])])
def test_nonuniform_three_level_recipe_preserves_time_and_quality(time):
    fd = native_file(time)
    entries = [make_single('positive', '', 'abs', 'raw', None),
               make_single('rate', '', 'derivative', 'positive', None),
               make_single('area', '', 'integral', 'rate', None)]
    assert all(r.applied for r in replay(fd, entries))
    np.testing.assert_allclose(read_signal(fd, 'area').values, 4*time, atol=1e-13)
    invalid = np.zeros(8, dtype=bool)
    invalid[3] = True
    flagged = native_file(validity=invalid)
    result = replay(flagged, entries)
    assert result[0].applied and not result[1].applied and not result[2].applied
    series = read_signal(flagged, 'positive')
    assert series.validity[3] and np.isnan(series.values[3])
    assert '缺口' in result[1].reason


def test_editor_exports_only_selected_staged_derived(qtbot, monkeypatch, tmp_path):
    import csv
    from PyQt5.QtWidgets import QMessageBox
    fd = native_file()
    dlg = ChannelEditorDialog(None, {'f': fd}, 'f')
    qtbot.addWidget(dlg)
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    target = tmp_path / 'selected.csv'
    monkeypatch.setattr('mf4_analyzer.ui.dialogs.channel_editor.QFileDialog.getSaveFileName', lambda *a: (str(target), ''))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: None)
    def pick_long(box):
        box.buttons()[0].click()
        return 0
    monkeypatch.setattr(QMessageBox, 'exec_', pick_long)
    dlg._export_native_channels(['abs_raw'])
    rows = list(csv.DictReader(target.read_text().splitlines()))
    assert {r['channel'] for r in rows} == {'abs_raw'}
    assert [float(r['value']) for r in rows] == list(np.arange(8.))
    assert [float(r['time']) for r in rows] == list(np.arange(8.)/4)
    assert 'abs_raw' not in fd.get_signal_channels()


def test_native_gui_precision_reasons_and_ready_derived_plot(qapp, qtbot):
    from types import SimpleNamespace
    from mf4_analyzer.ui.main_window._fft_mixin import FFTMixin
    from mf4_analyzer.ui.main_window._order_mixin import OrderMixin
    from mf4_analyzer.ui.time_curve_bindings import native_plot_rows
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    from mf4_analyzer.analysis_signal_prepare import load_native_channel
    from tests.test_native_precision_routes import precision_file
    fd = precision_file()
    host = SimpleNamespace(files={'f': fd})
    for fetch in [FFTMixin._fft_fetch_signal, OrderMixin._order_sig_for]:
        rejected = []
        args = (host, 'f', 'wide') if fetch is FFTMixin._fft_fetch_signal else (host, ('f', 'wide'))
        result = fetch(*args, time_range=None, rejections=rejected)
        assert result == (None, None)
        assert len(rejected) == 1 and 'float64' in rejected[0]
    derived = native_file()
    assert replay(derived, [make_single('positive', '', 'abs', 'raw', None)])[0].applied
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(640, 360)
    canvas.show()
    canvas.plot_channels(native_plot_rows(derived, ['positive'], fid='derived'), mode='single')
    qapp.processEvents()
    reading = canvas._cursor.evaluate_single_cursor(.75)
    assert reading[0].current_value == 3.
    assert reading[0].content_revision == read_signal(derived, 'positive').revision
    prepared = load_native_channel(derived, 'positive')
    assert prepared.status == 'ready'
    np.testing.assert_array_equal(prepared.time, np.arange(8.)/4)


def test_native_delete_recreate_keeps_physical_identity_hidden():
    from mf4_analyzer.io.signal_access import channel_in_source, known_sampling_hz
    fd = native_file()
    original_key = fd.native_store.channel('raw').physical_key
    assert replay(fd, [make_single('copy', '', 'abs', 'raw', None)])[0].applied
    replay(fd, [{'op': 'remove', 'names': ['raw']}])
    assert replay(fd, [make_single('raw', '', 'scale', 'copy', 2.)])[0].applied
    assert channel_in_source(fd, 'raw')
    assert known_sampling_hz(fd, 'raw') == 4.
    with pytest.raises(SignalAccessError):
        read_signal(fd, original_key)
    np.testing.assert_array_equal(read_signal(fd, 'raw').values, 2*np.arange(8.))


def test_native_precision_blocks_fft_dispatch_and_order_job(qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from tests.test_native_precision_routes import precision_file
    window = MainWindow()
    qtbot.addWidget(window)
    window.files['f'] = precision_file()
    window._analysis_page('fft').ensure_ready()
    state = window.analysis_managers['fft'].get(window.analysis_managers['fft'].active)
    state.panes[0].sources = [('f', 'wide')]
    monkeypatch.setattr(window, '_capture_active_analysis_view', lambda section: None)
    outcomes = []
    def feedback(outcome, **kwargs):
        outcomes.append(outcome)
        return True
    def forbidden(*args, **kwargs):
        pytest.fail('rejected integer input started computation')
    monkeypatch.setattr(window, '_emit_compute_feedback', feedback)
    monkeypatch.setattr(window, '_fft_compute_arrays', forbidden)
    monkeypatch.setattr(window, '_begin_compute_progress', forbidden)
    window.do_fft()
    assert len(outcomes) == 1
    assert len(outcomes[0].skipped) == 1 and 'float64' in outcomes[0].skipped[0]
    messages = []
    monkeypatch.setattr(window, 'toast', lambda text, *args: messages.append(text))
    assert window._build_order_job(0, 'f', 'wide', None) is None
    assert len(messages) == 1 and 'float64' in messages[0]


@pytest.mark.parametrize('count', [0, 1])
def test_native_short_recipes_keep_length_and_reject_derivative(count):
    fd = native_file(np.arange(count, dtype=float))
    results = replay(fd, [make_single('abs', '', 'abs', 'raw', None),
                          make_single('derivative', '', 'derivative', 'abs', None)])
    assert results[0].applied
    assert read_signal(fd, 'abs').values.shape == (count,)
    assert not results[1].applied


def test_editor_cancel_releases_staged_values(qtbot):
    import gc
    import weakref
    fd = native_file()
    dlg = ChannelEditorDialog(None, {'f': fd}, 'f')
    qtbot.addWidget(dlg)
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    values = weakref.ref(dlg.new_channels['abs_raw'][0])
    dlg.reject()
    gc.collect()
    assert values() is None
    assert fd.get_signal_channels() == ['raw']


def test_derived_budget_refuses_before_recipe_allocation(monkeypatch):
    from mf4_analyzer.io.channel_edit_log import evaluate_native_channel
    from mf4_analyzer.signal.channel_recipe import RecipeError
    monkeypatch.setattr('mf4_analyzer.analysis_signal_prepare.DEFAULT_PREPARE_BYTE_LIMIT', 1)
    def forbidden(*args):
        pytest.fail('recipe allocated before admission')
    monkeypatch.setattr('mf4_analyzer.io.channel_edit_log.evaluate_derive', forbidden)
    with pytest.raises(RecipeError, match='byte_limit'):
        evaluate_native_channel(native_file(), make_single('abs', '', 'abs', 'raw', None))


def test_native_editor_apply_through_main_window_and_save_recipe(qtbot, monkeypatch, tmp_path):
    import json
    from asammdf import MDF, Signal
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.analysis_signal_prepare import load_native_channel
    time = np.arange(64.)/4
    with MDF(version='4.10') as mdf:
        mdf.append([Signal(-4*time, time, name='raw')])
        path = mdf.save(tmp_path/'source.mf4', overwrite=True)
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(window, 'toast', lambda *a: None)
    window.request_explicit_native_import(path)
    qtbot.waitUntil(lambda: not window._imports.busy, timeout=15000)
    assert len(window.files) == 1
    fid, fd = next(iter(window.files.items()))
    dlg = ChannelEditorDialog(window, window.files, fid)
    qtbot.addWidget(dlg)
    dlg.combo_src.setCurrentText('raw')
    dlg.combo_op.setCurrentIndex(5)
    dlg._create_single()
    dlg.combo_src.setCurrentText('abs_raw')
    dlg.combo_op.setCurrentIndex(0)
    dlg._create_single()
    window._apply_channel_edits(fid, dlg.new_channels, dlg.removed_channels, dlg._edit_log.entries)
    assert 'd_dt_abs_raw' in fd.get_signal_channels()
    window.navigator.set_checked_channels([(fid, 'd_dt_abs_raw')])
    window.plot_time()
    prepared = load_native_channel(fd, 'd_dt_abs_raw')
    assert prepared.status == 'ready'
    np.testing.assert_allclose(prepared.values, 4.)
    project = tmp_path/'recipe.tlproj'
    assert window.save_project(project)
    payload = json.loads(project.read_text())
    assert payload['schema_version'] == 6
    assert [e['name'] for e in payload['files'][0]['channel_edits']] == ['abs_raw', 'd_dt_abs_raw']
    assert '"values"' not in project.read_text()


@pytest.mark.parametrize('corruption', [
    {'values': np.arange(9.)},
    {'values': np.arange(8.).reshape(2, 4)},
    {'validity': np.zeros(7, dtype=bool)},
])
def test_staged_native_shape_is_rejected_without_truncation(corruption):
    from mf4_analyzer.io.channel_edit_log import evaluate_native_channel
    from mf4_analyzer.io.signal_access import read_logical_channel
    fd = native_file()
    record = evaluate_native_channel(fd, make_single('abs', '', 'abs', 'raw', None))
    corrupt = dict(record, **corruption)
    with pytest.raises(SignalAccessError, match='长度|形状'):
        read_logical_channel(corrupt)
