import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.batch import BatchOutput
from mf4_analyzer.io import FileData
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet


def large_sheet(qtbot, tmp_path):
    data = pd.DataFrame({'Time': np.arange(200000) / 1000, 'sig': np.ones(200000)})
    fd = FileData(tmp_path / 'large.csv', data, list(data), {})
    sheet = BatchSheet(None, files={'source': fd})
    qtbot.addWidget(sheet)
    sheet.apply_files(('source',), ())
    sheet.apply_signals(('sig',))
    sheet.show()
    return sheet


@pytest.mark.parametrize('method', ['time', 'fft', 'fft_time', 'order_time', 'frf'])
def test_each_method_defaults_to_no_data_export(qtbot, method):
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_method(method)
    assert not sheet.export_data()
    assert sheet._output_panel._xlsx_warning.isHidden()


def test_large_xlsx_warning_updates_before_run_and_clears(qtbot, tmp_path):
    sheet = large_sheet(qtbot, tmp_path)
    panel = sheet._output_panel
    assert not panel._chk_data.isChecked()
    panel._chk_data.setChecked(True)
    qtbot.waitUntil(lambda: not panel._xlsx_warning.isHidden())
    assert '600,000' in panel._xlsx_warning.text()
    assert not sheet._running
    assert sheet.is_runnable()  # advisory only
    # A small segmented spectrum does not inherit the full-record warning.
    sheet.apply_method('fft')
    sheet.apply_params({'nfft': 1024, 'avg_mode': '线性平均'})
    qtbot.waitUntil(panel._xlsx_warning.isHidden)
    sheet.apply_method('time')
    qtbot.waitUntil(lambda: not panel._xlsx_warning.isHidden())
    panel._chk_data.setChecked(False)
    qtbot.waitUntil(panel._xlsx_warning.isHidden)


def test_reopen_does_not_silently_restore_data_opt_in(qtbot, tmp_path):
    from tests.ui.test_batch_smoke import _prefs_store
    from mf4_analyzer.ui.batch_settings import BatchPanelPrefs

    store = _prefs_store(tmp_path)
    store.save(BatchPanelPrefs(outputs={'export_data': True}))
    sheet = BatchSheet(None, files={}, prefs_store=store)
    qtbot.addWidget(sheet)
    assert not sheet.export_data()
    sheet.apply_outputs(BatchOutput(export_data=True))
    assert sheet.export_data()  # explicitly loaded intent remains supported


def test_disk_probe_size_facts_warn_without_loading_again(qtbot, tmp_path, monkeypatch):
    from mf4_analyzer.io.source_adapters import SourceDescriptor, SourceAdapterRegistry

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    path = str(tmp_path / 'split.hdf')
    fl._set_row_state(path, 'probing')
    fl._on_probe_finished(path, (SourceDescriptor(
        'fast', path, 'fast-group', 'fast', ('sig',), {}, 24000,
        {'sample_count': 1188000, 'sample_rate': 24000,
         'time_start': 0., 'time_end': 49.499},
    ), SourceDescriptor(
        'slow', path, 'slow-group', 'slow', ('rpm',), {}, 1000,
        {'sample_count': 49500, 'sample_rate': 1000,
         'time_start': 0., 'time_end': 49.499},
    )))
    def no_load(*args, **kwargs):
        pytest.fail('size advisory must consume cached probe facts')
    monkeypatch.setattr(SourceAdapterRegistry, 'load_sources', no_load)
    sheet._input_panel.apply_target_policy('available_per_source')
    sheet.apply_signals(('sig',))
    sheet.apply_outputs(BatchOutput(export_data=True))
    sheet._recompute_pipeline_status()
    assert '3,564,000' in sheet._output_panel._xlsx_warning.text()
    assert '无法估算' not in sheet._output_panel._xlsx_warning.text()
