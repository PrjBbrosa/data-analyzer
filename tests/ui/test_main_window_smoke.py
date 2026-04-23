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
