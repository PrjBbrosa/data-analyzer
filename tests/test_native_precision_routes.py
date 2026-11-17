"""Native precision failure reaches real Batch items without losing safe spans."""
import numpy as np
import pytest
from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.io.native_signal_store import AxisSpec, ChannelSpec, NativeSignalStore


def precision_file():
    raw = np.arange(256, dtype=np.int64)
    raw[0] = 2**53+3
    store = NativeSignalStore.build('precision', [AxisSpec('t', 'clock', 'time', 's', np.arange(256.)/128)],
        [ChannelSpec(0, 1, 'wide', 't', raw)])
    return FileData.from_native_store('/data/wide.mf4', store)


@pytest.mark.parametrize('method', ['time', 'fft', 'fft_time'])
def test_native_batch_precision_item_and_selected_range(tmp_path, method):
    fd = precision_file()
    runner = BatchRunner({'f': fd})
    params = {'fs': 128., 'nfft': 32, 'nperseg': 32}
    preset = AnalysisPreset.from_current_single(name='precision', method=method,
        signal=('f', 'wide'), params=params, outputs=BatchOutput(export_data=True, export_image=False))
    result = runner.run(preset, tmp_path / 'refused')
    assert len(result.items) == 1
    assert result.items[0].status == 'failed'
    assert 'float64' in result.items[0].message
    preset.params['time_range'] = [.5, 1.5]
    accepted = runner.run(preset, tmp_path / 'accepted')
    assert len(accepted.items) == 1
    if method == 'fft_time':
        # This existing Batch policy intentionally ignores source-data ranges.
        assert accepted.items[0].status == 'failed'
        assert 'float64' in accepted.items[0].message
    else:
        assert accepted.items[0].status == 'done', accepted.items[0].message
    assert int(fd.native_store.channel('wide').raw[0]) == 2**53+3
