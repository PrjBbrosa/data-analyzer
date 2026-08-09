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
        tb.btn_mode_order,
        tb.btn_mode_frf,
    ]
    assert [button.text() for button in buttons] == [
        "时域", "频谱", "时频", "阶次", "频响",
    ]
    assert [button.property("segment") for button in buttons] == [
        "time", "fft", "fft_time", "order", "frf",
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


def test_toolbar_mode_zone_keeps_symmetric_divider_gaps_and_fixed_height(qtbot, qapp):
    """The analysis-mode cluster is a centered zone, not hand-placed chrome."""
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.resize(1440, 44)
    tb.show()
    qtbot.wait(20)

    left_divider, right_divider = tb._mode_zone_dividers
    segment = tb._mode_segment
    left_gap = segment.x() - (left_divider.x() + left_divider.width())
    right_gap = right_divider.x() - (segment.x() + segment.width())

    assert tb.height() == 44
    assert left_gap == right_gap
    assert left_divider.height() == right_divider.height() == 16
    assert abs(tb._mode_zone.geometry().center().x() - tb.rect().center().x()) <= 1
    assert tb._mode_active_dots["time"].isVisible()
    assert not tb._mode_active_dots["fft"].isVisible()

    tb.btn_mode_fft.click()
    assert not tb._mode_active_dots["time"].isVisible()
    assert tb._mode_active_dots["fft"].isVisible()


def test_toolbar_mode_zone_recenters_when_top_actions_change(qtbot, qapp):
    """Future additions on either side must rebalance the mirrored hosts."""
    from PyQt5.QtWidgets import QPushButton

    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.resize(1440, 44)
    tb.show()
    qtbot.wait(20)

    extra = QPushButton("临时功能", tb._left_widget)
    tb._left_layout.addWidget(extra)
    qtbot.wait(30)

    expected_width = max(
        tb._left_layout.sizeHint().width(),
        tb._right_layout.sizeHint().width(),
        1,
    )
    assert tb._left_widget.width() == tb._right_widget.width() == expected_width
    assert abs(tb._mode_zone.geometry().center().x() - tb.rect().center().x()) <= 1

    tb._left_layout.removeWidget(extra)
    extra.deleteLater()
    qtbot.wait(30)
    assert abs(tb._mode_zone.geometry().center().x() - tb.rect().center().x()) <= 1

    # Deliberately exceed the normal left group: this proves a future right
    # action can grow the mirror width instead of shifting the center zone.
    right_extra = QPushButton("右侧临时功能" * 5, tb._right_widget)
    tb._right_layout.addWidget(right_extra)
    qtbot.wait(30)

    expected_width = max(
        tb._left_layout.sizeHint().width(),
        tb._right_layout.sizeHint().width(),
        1,
    )
    assert expected_width > tb._left_layout.sizeHint().width()
    assert tb._left_widget.width() == tb._right_widget.width() == expected_width
    assert abs(tb._mode_zone.geometry().center().x() - tb.rect().center().x()) <= 1

    tb._right_layout.removeWidget(right_extra)
    right_extra.deleteLater()
    qtbot.wait(30)
    assert abs(tb._mode_zone.geometry().center().x() - tb.rect().center().x()) <= 1



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


def test_toolbar_open_keeps_primary_entry_cue_and_other_file_actions_are_secondary(qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)

    assert tb.btn_add.property("role") == "primary"
    assert [button.property("role") for button in (
        tb.btn_save_project, tb.btn_save_project_as, tb.btn_batch,
    )] == ["secondary"] * 3


def test_toolbar_primary_open_matches_secondary_file_action_height(qtbot, qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.resize(720, 44)
    tb.show()
    qtbot.wait(20)

    assert tb.btn_add.height() == tb.btn_save_project.height() == tb.btn_batch.height()
