from mf4_analyzer.ui.main_window import MainWindow


def test_main_window_constructs(qapp):
    w = MainWindow()
    assert w.toolbar is not None
    assert w.navigator is not None
    assert w.chart_stack is not None
    assert w.inspector is not None


def test_main_window_has_splitter_with_three_panes(qapp):
    w = MainWindow()
    # The central widget contains a QSplitter with 3 widgets
    from PyQt5.QtWidgets import QSplitter
    splitter = w.findChild(QSplitter)
    assert splitter is not None
    assert splitter.count() == 3


def test_load_csv_flows_through_navigator(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    assert len(w.files) == 1
    assert w.navigator.channel_list.tree.topLevelItemCount() == 1


def test_mode_change_routes_to_chart_stack(qapp, qtbot):
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    w.toolbar.btn_mode_fft.click()
    assert w.chart_stack.current_mode() == 'fft'
    assert w.inspector.contextual_widget_name() == 'fft'


def test_custom_xaxis_length_mismatch_warns(qapp, qtbot, loaded_csv, tmp_path):
    """If user selects a custom X channel whose length != data, warn and abort."""
    import pandas as pd
    import numpy as np
    from PyQt5.QtWidgets import QMessageBox
    from unittest.mock import patch
    from mf4_analyzer.ui.main_window import MainWindow
    # Second csv with different length
    df = pd.DataFrame({"time": np.linspace(0, 1, 500), "pressure": np.random.randn(500)})
    p2 = tmp_path / "shorter.csv"; df.to_csv(p2, index=False)

    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv, str(p2)], "")):
        w.load_files()
    # Pick custom X from file 2's channel while file 1 checked
    w.inspector.top.set_xaxis_mode('channel')
    w._on_xaxis_mode_changed('channel')
    w.inspector.top._combo_xaxis_ch.setCurrentIndex(
        w.inspector.top._combo_xaxis_ch.count() - 1  # last candidate (from file 2)
    )
    qapp.processEvents()
    with patch.object(QMessageBox, 'warning') as warn:
        w._apply_xaxis()
    assert warn.called


def test_file_activation_updates_inspector_fs_and_range(qapp, qtbot, loaded_csv):
    from unittest.mock import patch
    import pytest
    from mf4_analyzer.ui.main_window import MainWindow
    w = MainWindow(); qtbot.addWidget(w)
    with patch('mf4_analyzer.ui.main_window.QFileDialog.getOpenFileNames',
               return_value=([loaded_csv], "")):
        w.load_files()
    fid = next(iter(w.files))
    fd = w.files[fid]
    # activation should have pushed fs + range-limit to inspector
    # (QDoubleSpinBox default decimals=2 rounds fs, so compare with tolerance)
    assert w.inspector.fft_ctx.fs() == pytest.approx(fd.fs, abs=0.01)
    assert w.inspector.order_ctx.fs() == pytest.approx(fd.fs, abs=0.01)
    # range limit upper bound should match time_array tail
    assert w.inspector.top.spin_end.maximum() >= fd.time_array[-1]
