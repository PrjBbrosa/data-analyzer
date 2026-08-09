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
    assert tb.btn_save_project.isEnabled()
    tb.set_enabled_for_mode('fft', has_file=True)
    assert tb.btn_batch.isEnabled()
    tb.set_enabled_for_mode('time', has_file=False)
    assert not tb.btn_save_project.isEnabled()
    assert tb.btn_batch.isEnabled()


def test_toolbar_batch_requested_emits(qapp, qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.batch_requested, timeout=200):
        tb.btn_batch.click()


def test_toolbar_batch_icon_is_distinct_from_export(qapp, qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)

    assert not tb.btn_batch.icon().isNull()
    assert tb.btn_batch.icon().cacheKey() != tb.btn_add.icon().cacheKey()


def test_toolbar_exposes_fft_time_mode(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar

    tb = Toolbar()
    qtbot.addWidget(tb)
    seen = []
    tb.mode_changed.connect(seen.append)
    tb.btn_mode_fft_time.click()

    assert tb.current_mode() == 'fft_time'
    assert seen[-1] == 'fft_time'
    assert tb.btn_mode_fft_time.text() == '时频'


def test_toolbar_exposes_five_exact_mode_names_and_keys(qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)

    buttons = [
        tb.btn_mode_time,
        tb.btn_mode_fft,
        tb.btn_mode_fft_time,
        tb.btn_mode_frf,
        tb.btn_mode_order,
    ]
    assert [button.text() for button in buttons] == [
        "时域", "频谱", "时频", "频响", "阶次",
    ]
    assert [button.property("segment") for button in buttons] == [
        "time", "fft", "fft_time", "frf", "order",
    ]
    assert "FFT" in tb.btn_mode_fft.toolTip()
    assert "FRF" in tb.btn_mode_frf.toolTip()

    seen = []
    tb.mode_changed.connect(seen.append)
    tb.btn_mode_frf.click()
    assert tb.current_mode() == "frf"
    assert seen == ["frf"]
    assert tb.btn_mode_frf.isChecked()
    assert sum(button.isChecked() for button in buttons) == 1


def test_toolbar_frf_unselected_uses_the_same_segment_style_as_other_modes():
    from pathlib import Path

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    selector = qss[qss.index('Toolbar QPushButton[segment="time"]'):qss.index('Toolbar QPushButton[segment]:hover')]
    assert 'Toolbar QPushButton[segment="frf"]' in selector



def test_toolbar_open_save_split_and_no_export(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar(); qtbot.addWidget(tb)
    assert tb.btn_add.text() == "打开"
    assert hasattr(tb, "btn_save_project")
    assert tb.btn_save_project.text() == "保存"
    assert hasattr(tb, "btn_save_project_as")
    assert tb.btn_save_project_as.text() == "另存为"
    assert not hasattr(tb, "btn_export")
    assert hasattr(tb, "open_requested")
    assert hasattr(tb, "save_project_requested")
    assert hasattr(tb, "save_project_as_requested")
    assert not hasattr(tb, "export_requested")
