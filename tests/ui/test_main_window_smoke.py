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
