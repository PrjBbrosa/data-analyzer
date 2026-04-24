from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.toolbar import Toolbar


def test_toolbar_constructs(qapp):
    tb = Toolbar()
    assert isinstance(tb, QWidget)


def test_toolbar_mode_changed_emits(qapp, qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.mode_changed, timeout=200) as blocker:
        tb.btn_mode_fft.click()
    assert blocker.args == ['fft']
    assert tb.btn_mode_fft.isChecked()


def test_toolbar_enabled_matrix(qapp):
    tb = Toolbar()
    tb.set_enabled_for_mode('time', has_file=True)
    assert tb.btn_cursor_reset.isEnabled()
    assert tb.btn_axis_lock.isEnabled()
    tb.set_enabled_for_mode('fft', has_file=True)
    assert not tb.btn_cursor_reset.isEnabled()
    assert not tb.btn_axis_lock.isEnabled()
    tb.set_enabled_for_mode('time', has_file=False)
    assert not tb.btn_edit.isEnabled()
