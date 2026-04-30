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
    assert tb.btn_batch.isEnabled()
    assert tb.btn_edit.isEnabled()
    assert tb.btn_export.isEnabled()
    tb.set_enabled_for_mode('fft', has_file=True)
    assert tb.btn_batch.isEnabled()
    tb.set_enabled_for_mode('time', has_file=False)
    assert not tb.btn_edit.isEnabled()
    assert not tb.btn_export.isEnabled()
    assert tb.btn_batch.isEnabled()


def test_toolbar_batch_requested_emits(qapp, qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.batch_requested, timeout=200):
        tb.btn_batch.click()


def test_toolbar_exposes_fft_time_mode(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar

    tb = Toolbar()
    qtbot.addWidget(tb)
    seen = []
    tb.mode_changed.connect(seen.append)
    tb.btn_mode_fft_time.click()

    assert tb.current_mode() == 'fft_time'
    assert seen[-1] == 'fft_time'
    assert tb.btn_mode_fft_time.text() == 'FFT vs Time'
