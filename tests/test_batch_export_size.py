import numpy as np

from mf4_analyzer.batch_export_size import estimate_table_size, xlsx_size_warning


def facts(n=10000, fs=1000):
    return {'sample_count': n, 'sample_rate': fs,
            'time_start': 0., 'time_end': (n - 1) / fs}


def test_time_counts_both_filter_series_and_large_workbook_warning():
    size = estimate_table_size('time', {'filter': {
        'enabled': True, 'show_original': True, 'show_filtered': True,
    }}, facts(100000))
    assert (size.rows, size.cells) == (200000, 600000)
    assert 'XLSX' in xlsx_size_warning([size])
    assert not xlsx_size_warning([estimate_table_size('time', {}, facts(10))])


def test_spectrogram_estimate_matches_real_complete_frames_including_tail():
    from mf4_analyzer.batch_compute import compute_fft_time_spectro
    params = {'nfft': 256, 'overlap': 0.5}
    time = np.arange(1000) / 1000
    result = compute_fft_time_spectro(np.sin(time), time, 1000, params)
    size = estimate_table_size('fft_time', params, facts(1000))
    assert size.rows == result.matrix.size
    assert size.cells == result.matrix.size * 3


def test_slice_estimate_does_not_charge_full_heatmap_matrix():
    params = {'nfft': 1024, 'overlap': 0.75}
    full = estimate_table_size('fft_time', params, facts(1200000, 24000))
    sliced = estimate_table_size('fft_time', dict(params, slice={
        'enabled': True, 'axis': 'time', 'positions': [1, 2],
    }), facts(1200000, 24000))
    assert xlsx_size_warning([full])
    assert not xlsx_size_warning([sliced])
    assert sliced.cells < 2000


def test_unknown_size_is_not_silently_treated_as_small():
    size = estimate_table_size('fft_time', {'nfft': 'auto'}, {})
    assert size.rows is None
    assert '无法估算' in xlsx_size_warning([size])


def test_order_time_uses_time_grid_upper_bound():
    size = estimate_table_size('order_time', {
        'time_res': 0.05, 'order_res': 0.1, 'max_order': 20,
    }, facts(50000, 1000))
    assert size.rows == 1001 * 200
    assert xlsx_size_warning([size])


def test_multiple_small_tables_aggregate_and_zero_is_empty():
    size = estimate_table_size('time', {}, facts(100000))
    assert not xlsx_size_warning([size])
    assert xlsx_size_warning([size, size])
    assert not xlsx_size_warning([])
    assert estimate_table_size('time', {}, facts(0)).cells == 0


def test_frf_estimate_uses_the_actual_window_not_record_length():
    from mf4_analyzer.batch_compute import FRF_EXPORT_COLUMNS

    size = estimate_table_size('frf', {'t_win_s': 2.0}, facts(1200000, 24000))
    assert size.rows == 24001
    assert size.cells == 24001 * len(FRF_EXPORT_COLUMNS)


def test_fft_auto_size_uses_single_frame_record_or_segmented_resolver():
    single = estimate_table_size('fft', {'nfft': 'auto'}, facts(1200000, 24000))
    averaged = estimate_table_size('fft', {
        'nfft': 'auto', 'avg_mode': '线性平均', 't_win_s': .02,
    }, facts(1200000, 24000))
    assert single.rows == 600001
    assert averaged.rows < single.rows
    assert xlsx_size_warning([single])
    assert not xlsx_size_warning([averaged])
