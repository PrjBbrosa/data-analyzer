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
    # Construction is the empty-session row: 保存 stays off until a file lands.
    # Recent-open caret does not depend on the current session.
    assert tb.btn_add.isEnabled()
    assert tb.btn_open_caret.isEnabled()
    assert not tb.btn_save_project.isEnabled()
    assert not tb.btn_save_caret.isEnabled()
    assert not tb.btn_save_project_as.isEnabled()
    assert tb.btn_batch.isEnabled()
    tb.set_enabled_for_mode('time', has_file=True)
    assert tb.btn_batch.isEnabled()
    assert tb.btn_save_project.isEnabled()
    assert tb.btn_save_caret.isEnabled()
    tb.set_enabled_for_mode('fft', has_file=True)
    assert tb.btn_batch.isEnabled()
    tb.set_enabled_for_mode('time', has_file=False)
    assert not tb.btn_save_project.isEnabled()
    assert not tb.btn_save_caret.isEnabled()
    assert not tb.btn_save_project_as.isEnabled()
    assert tb.btn_batch.isEnabled()


def test_toolbar_batch_requested_emits(qapp, qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    with qtbot.waitSignal(tb.batch_requested, timeout=200):
        tb.btn_batch.click()


def test_toolbar_ultraview_requested_emits(qapp, qtbot):
    """Open intent now comes from the View-rail Dock, not a Toolbar 总览 chip."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    from mf4_analyzer.ui.view_state import ViewManager

    tb = Toolbar()
    qtbot.addWidget(tb)
    assert not hasattr(tb, "btn_mode_ultraview")
    assert not hasattr(tb, "btn_ultraview") or tb.btn_ultraview.isHidden()
    assert not hasattr(tb, "ultraview_requested")

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.attach_view_tabbar(ViewManager())
    with qtbot.waitSignal(cs.open_ultraview_requested, timeout=200):
        cs.ultraview_entry.click()


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
    assert not hasattr(tb, "btn_mode_ultraview")
    assert not hasattr(tb, "btn_ultraview") or tb.btn_ultraview.isHidden()

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
    assert 'Toolbar QPushButton[segment="ultraview"]' not in selector


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
    right_extra = QPushButton("右侧临时功能" * 10, tb._right_widget)
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
    from mf4_analyzer.ui.toolbar import Toolbar, _SAVE_CARET_WIDTH
    tb = Toolbar(); qtbot.addWidget(tb)
    assert tb.btn_add.text() == "打开"
    assert tb.btn_add.objectName() == "toolbarOpenMain"
    assert tb._open_split.objectName() == "toolbarOpenSplit"
    assert tb.btn_open_caret.objectName() == "toolbarOpenCaret"
    assert tb.btn_open_caret.text() == ""
    assert tb.btn_open_caret.width() == _SAVE_CARET_WIDTH
    assert tb.btn_add.property("role") == "primary"
    assert tb.btn_open_caret.property("role") == "primary"
    assert hasattr(tb, "btn_save_project")
    assert tb.btn_save_project.text() == "保存"
    assert hasattr(tb, "btn_save_caret")
    assert tb.btn_save_caret.text() == ""
    assert hasattr(tb, "btn_save_project_as")
    assert tb.btn_save_project_as.text() == "另存为"
    assert tb.btn_save_project_as.parent() is tb._save_menu
    assert not hasattr(tb, "btn_export")
    assert hasattr(tb, "open_requested")
    assert hasattr(tb, "recent_menu_about_to_show")
    assert hasattr(tb, "recent_open_requested")
    assert hasattr(tb, "recent_clear_requested")
    assert hasattr(tb, "save_project_requested")
    assert hasattr(tb, "save_project_as_requested")
    assert not hasattr(tb, "export_requested")


def test_toolbar_open_keeps_primary_entry_cue_and_other_file_actions_are_secondary(qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)

    assert tb.btn_add.property("role") == "primary"
    assert tb.btn_open_caret.property("role") == "primary"
    assert [button.property("role") for button in (
        tb.btn_save_project, tb.btn_save_caret, tb.btn_batch,
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

    assert (
        tb.btn_add.height()
        == tb.btn_open_caret.height()
        == tb.btn_save_project.height()
        == tb.btn_save_caret.height()
        == tb.btn_batch.height()
    )
    assert abs(tb._open_split.height() - tb._save_split.height()) <= 2
    assert abs(tb._save_split.height() - tb.btn_batch.height()) <= 2
    assert tb.btn_save_caret.width() < tb.btn_save_project.width()


def test_toolbar_open_stays_content_sized_and_secondary_file_actions_match(qtbot, qapp):
    from mf4_analyzer.ui.toolbar import _SAVE_CARET_WIDTH
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.resize(1280, 44)
    tb.show()
    qtbot.wait(20)

    assert tb._open_split.width() <= tb.btn_batch.width()
    assert abs(tb._open_split.height() - tb.btn_batch.height()) <= 2
    assert abs(tb._open_split.height() - tb._save_split.height()) <= 2
    assert tb._open_split.width() <= tb._open_split.sizeHint().width() + 1
    assert abs(tb._save_split.width() - tb.btn_batch.width()) <= 1
    assert tb.btn_open_caret.width() == _SAVE_CARET_WIDTH
    assert tb.btn_save_caret.width() == _SAVE_CARET_WIDTH
    assert tb.btn_save_caret.width() < tb.btn_save_project.width()


def test_toolbar_save_split_emits_save_and_save_as(qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.set_enabled_for_mode("time", has_file=True)
    with qtbot.waitSignal(tb.save_project_requested, timeout=200):
        tb.btn_save_project.click()
    with qtbot.waitSignal(tb.save_project_as_requested, timeout=200):
        tb.btn_save_project_as.trigger()


def test_toolbar_save_caret_opens_rounded_save_as_menu(qtbot, qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.set_enabled_for_mode("time", has_file=True)
    tb.show()
    qtbot.waitExposed(tb)
    tb.btn_save_caret.click()
    qapp.processEvents()
    assert tb._save_menu.isVisible()
    assert [action.text() for action in tb._save_menu.actions()] == ["另存为"]
    tb._save_menu.close()


def _mode_buttons(tb):
    return [
        tb.btn_mode_time,
        tb.btn_mode_fft,
        tb.btn_mode_fft_time,
        tb.btn_mode_order,
        tb.btn_mode_frf,
    ]


def test_toolbar_five_modes_go_icon_only_when_narrow_and_restore_labels_when_wide(qtbot, qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    qapp.setStyle("Fusion")
    load_stylesheet(qapp)
    tb = Toolbar()
    qtbot.addWidget(tb)
    buttons = _mode_buttons(tb)

    tb.resize(980, 44)
    tb.show()
    qtbot.wait(30)
    assert tb.is_mode_compact()
    assert all(button.text() == "" for button in buttons)
    geoms = [button.geometry() for button in buttons]
    for left, right in zip(geoms, geoms[1:]):
        assert left.right() <= right.left()
        assert not left.intersects(right)

    tb.resize(1600, 44)
    qtbot.wait(30)
    assert not tb.is_mode_compact()
    assert [button.text() for button in buttons] == [
        "时域", "频谱", "时频", "阶次", "频响",
    ]


def _recent_entry(path, kind, opened_at="2026-09-04T21:32:00"):
    from mf4_analyzer.ui.recent_files import RecentEntry
    return RecentEntry(path=str(path), kind=kind, opened_at=opened_at)


def _recent_popup(tb):
    from mf4_analyzer.ui.widgets.recent_open_popup import RecentOpenPopup

    popups = tb.findChildren(RecentOpenPopup)
    assert len(popups) == 1
    return popups[0]


def test_set_recent_entries_projects_global_mru_into_single_popup(qtbot, tmp_path):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QTableView

    from mf4_analyzer.ui.toolbar import Toolbar

    proj = tmp_path / "p.tlproj"
    present = tmp_path / "run.wwt"
    missing = tmp_path / "gone.mf4"
    proj.write_text("{}", encoding="utf-8")
    present.write_text("x", encoding="utf-8")
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.set_recent_entries((
        _recent_entry(present, "file"),
        _recent_entry(proj, "project"),
        _recent_entry(missing, "file"),
    ))
    popup = _recent_popup(tb)
    names = [match.filename for match in popup._matches]
    assert names == [present.name, proj.name, missing.name]
    assert popup.testAttribute(Qt.WA_TranslucentBackground)
    table = popup.findChild(QTableView, "recentOpenTable")
    assert table is not None
    assert popup.findChild(QWidget, "recentOpenClear").isEnabled()


def test_set_recent_entries_empty_disables_footer(qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.set_recent_entries(())
    popup = _recent_popup(tb)
    assert popup.findChild(QWidget, "recentOpenEmptyTitle").text() == "暂无最近记录"
    assert not popup.findChild(QWidget, "recentOpenClear").isEnabled()


def test_recent_row_click_emits_open_requested(qtbot, tmp_path):
    from PyQt5.QtWidgets import QTableView

    present = tmp_path / "run.wwt"
    present.write_text("x", encoding="utf-8")
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.show()
    qtbot.waitExposed(tb)
    tb.set_recent_entries((_recent_entry(present, "file"),))
    popup = _recent_popup(tb)
    popup.reset_for_show()
    table = popup.findChild(QTableView, "recentOpenTable")
    with qtbot.waitSignal(tb.recent_open_requested, timeout=400) as blocker:
        table.clicked.emit(table.model().index(0, 0))
    assert blocker.args == [str(present)]


def test_recent_footer_emits_clear_requested(qtbot, tmp_path):
    present = tmp_path / "run.wwt"
    present.write_text("x", encoding="utf-8")
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.set_recent_entries((_recent_entry(present, "file"),))
    with qtbot.waitSignal(tb.recent_clear_requested, timeout=200):
        _recent_popup(tb).findChild(QWidget, "recentOpenClear").click()


def test_missing_recent_row_does_not_emit_open(qtbot, tmp_path):
    from PyQt5.QtWidgets import QTableView

    missing = tmp_path / "gone.mf4"
    tb = Toolbar()
    qtbot.addWidget(tb)
    opened = []
    tb.recent_open_requested.connect(opened.append)
    tb.set_recent_entries((_recent_entry(missing, "file"),))
    popup = _recent_popup(tb)
    popup.reset_for_show()
    table = popup.findChild(QTableView, "recentOpenTable")
    table.clicked.emit(table.model().index(0, 0))
    assert opened == []


def test_open_caret_does_not_emit_open_requested(qtbot):
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.show()
    qtbot.waitExposed(tb)
    opened = []
    tb.open_requested.connect(lambda: opened.append("open"))
    tb.btn_open_caret.click()
    assert opened == []
    popup = _recent_popup(tb)
    if popup.isVisible():
        popup.close()


def test_show_recent_popup_is_single_instance_and_refocuses(qtbot, tmp_path):
    present = tmp_path / "run.wwt"
    present.write_text("x", encoding="utf-8")
    tb = Toolbar()
    qtbot.addWidget(tb)
    tb.show()
    qtbot.waitExposed(tb)
    shown = []
    tb.recent_menu_about_to_show.connect(lambda: shown.append("show"))
    tb.set_recent_entries((_recent_entry(present, "file"),))
    tb.show_recent_popup()
    popup = _recent_popup(tb)
    assert popup.isVisible()
    assert shown == ["show"]
    tb.show_recent_popup()
    assert popup.isVisible()
    assert shown == ["show"]
    assert popup._search.hasFocus()
    popup.close()
