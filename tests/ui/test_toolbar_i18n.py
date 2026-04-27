import pytest


_LIVE_REFS = []  # module-level pin so test-local objects survive past the helper return


def _build_toolbar(qtbot):
    from PyQt5.QtWidgets import QWidget
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import (
        FigureCanvasQTAgg as FigureCanvas,
        NavigationToolbar2QT as NavigationToolbar,
    )
    parent = QWidget()
    qtbot.addWidget(parent)
    fig = Figure()
    canvas = FigureCanvas(fig)
    canvas.setParent(parent)
    toolbar = NavigationToolbar(canvas, parent)
    # NavigationToolbar2QT holds only weak refs to canvas/parent on some
    # matplotlib versions; pin the python wrappers so the C++ objects
    # don't get destroyed when this helper returns.
    _LIVE_REFS.append((parent, fig, canvas, toolbar))
    return toolbar


def test_pan_zoom_save_have_chinese_tooltips(qtbot):
    from mf4_analyzer.ui._toolbar_i18n import apply_chinese_toolbar_labels
    toolbar = _build_toolbar(qtbot)
    apply_chinese_toolbar_labels(toolbar)
    found = {act.data(): act.toolTip() for act in toolbar.actions() if act.data()}
    assert '平移' in found.get('pan', '')
    assert '缩放' in found.get('zoom', '')
    assert '保存' in found.get('save', '')
    assert '重置' in found.get('home', '')


def test_back_forward_retained_with_chinese_tooltips(qtbot):
    """Back and Forward are now restored per user request (2026-04-27).
    They must be present and carry Chinese tooltips."""
    from mf4_analyzer.ui._toolbar_i18n import apply_chinese_toolbar_labels
    toolbar = _build_toolbar(qtbot)
    apply_chinese_toolbar_labels(toolbar)
    found = {act.data(): act.toolTip() for act in toolbar.actions() if act.data()}
    assert 'back' in found, "Back (上一视图) action must be retained"
    assert 'forward' in found, "Forward (下一视图) action must be retained"
    assert '上一视图' in found.get('back', '')
    assert '下一视图' in found.get('forward', '')


def test_act_data_preserved_for_find_action(qtbot):
    from mf4_analyzer.ui._toolbar_i18n import apply_chinese_toolbar_labels
    toolbar = _build_toolbar(qtbot)
    apply_chinese_toolbar_labels(toolbar)
    save_acts = [act for act in toolbar.actions() if act.data() == 'save']
    assert len(save_acts) == 1
