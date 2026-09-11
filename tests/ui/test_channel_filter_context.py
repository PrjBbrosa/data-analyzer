"""Channel-tree search empty states and same-context expand/scroll restore."""
import inspect

from PyQt5.QtCore import QCoreApplication, QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from mf4_analyzer.ui.file_navigator import FileNavigator
from mf4_analyzer.ui.main_window._analysis_mixin import AnalysisMixin
from mf4_analyzer.ui.main_window._view_mixin import ViewMixin
from mf4_analyzer.ui.widgets import MultiFileChannelWidget
from tests._helpers.wwt_record_tree import make_record_row
from tests.ui.test_channel_widget import (
    _FakeFileData,
    _MultiChannelFileData,
    _ReplaceableFileData,
    _WwtGroupedFileData,
    _add_attached_file,
)


def _flush(widget):
    QCoreApplication.processEvents()
    timer = getattr(widget, "_filter_restore_timer", None)
    if timer is not None and timer.isActive():
        timer.stop()
        widget._flush_filter_restore()
    QCoreApplication.processEvents()


def _filter_empty_title(widget):
    title = widget.findChild(QLabel, "channelFilterEmptyTitle")
    assert title is not None, "filter empty title is missing"
    return title.text()


def _filter_empty_clear(widget):
    button = widget.findChild(QPushButton, "channelFilterEmptyClear")
    assert button is not None, "清除筛选 button is missing"
    assert button.text() == "清除筛选"
    return button


def _is_no_attachment_page(widget):
    return widget._tree_stack.currentWidget() is widget.empty_state


def _is_filter_empty_page(widget):
    page = getattr(widget, "_filter_empty", None)
    return page is not None and widget._tree_stack.currentWidget() is page


def test_collapse_search_keep_typing_clear_restores_collapse_without_data_signals(
    qapp, qtbot,
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    QCoreApplication.processEvents()

    changed = []
    widget.channels_changed.connect(lambda: changed.append("channels"))
    widget.visibility_changed.connect(
        lambda *_args: changed.append("visibility")
    )

    widget.search.setText("t")
    widget.search.setText("tas")
    QCoreApplication.processEvents()
    assert file_item.isExpanded()
    assert widget._filter_snapshot is not None

    widget.search.clear()
    _flush(widget)

    assert not file_item.isExpanded()
    assert changed == []
    assert widget._filter_snapshot is None


def test_duplicate_channel_names_restore_by_userrole_identity(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 320)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    _add_attached_file(widget, "file-b", _MultiChannelFileData())
    left = widget._file_items["file-a"]
    right = widget._file_items["file-b"]
    left.setExpanded(False)
    right.setExpanded(True)
    QCoreApplication.processEvents()

    widget.search.setText("speed")
    QCoreApplication.processEvents()
    snapshot = widget._filter_snapshot
    assert snapshot is not None
    identities = [ident for ident, _expanded in snapshot["expanded"]]
    assert all(isinstance(ident, tuple) for ident in identities)
    assert ("channel", "file-a", "speed") in identities
    assert ("channel", "file-b", "speed") in identities
    assert "speed" not in identities
    assert left is not widget._tree_item_for_data(("file", "file-b"))

    widget.search.clear()
    _flush(widget)
    assert not left.isExpanded()
    assert right.isExpanded()


def test_keyword_and_selected_only_share_one_snapshot(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    file_item.child(2).setCheckState(0, Qt.Checked)
    QCoreApplication.processEvents()

    widget.search.setText("t")
    first = widget._filter_snapshot
    widget.btn_selected_only.setChecked(True)
    widget.search.setText("torque")
    QCoreApplication.processEvents()
    assert widget._filter_snapshot is first
    assert file_item.child(0).isHidden()
    assert not file_item.child(2).isHidden()

    widget.btn_selected_only.setChecked(False)
    widget.search.clear()
    _flush(widget)
    assert not file_item.isExpanded()
    assert file_item.child(2).checkState(0) == Qt.Checked


def test_wwt_record_group_tag_match_keeps_container_not_empty_tree(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.set_record_curve_rows("view-1", [
        make_record_row(name="TolY", binding_id="b-tol"),
    ])
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    widget.search.setText("原始记录 (")
    QCoreApplication.processEvents()
    assert not _is_filter_empty_page(widget)
    assert widget._tree_stack.currentWidget() is widget.tree
    assert widget._filter_match_records == 0
    assert widget._filter_kept_record_groups >= 1

    widget.search.setText("no-such-channel")
    QCoreApplication.processEvents()
    assert _is_filter_empty_page(widget)
    assert _filter_empty_title(widget) == "没有匹配的通道"
    assert not _is_no_attachment_page(widget)


def test_delete_source_while_filtering_invalidates_snapshot(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 320)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    _add_attached_file(widget, "file-b", _FakeFileData())
    left = widget._file_items["file-a"]
    right = widget._file_items["file-b"]
    left.setExpanded(False)
    right.setExpanded(False)
    QCoreApplication.processEvents()

    widget.search.setText("speed")
    assert widget._filter_snapshot is not None
    generation = widget._filter_generation
    widget.remove_file("file-a")
    QCoreApplication.processEvents()
    assert widget._filter_generation == generation + 1
    assert widget._filter_snapshot is None
    assert widget.search.text() == "speed"

    widget.search.clear()
    _flush(widget)
    remaining = widget._file_items["file-b"]
    assert remaining.isExpanded()


def test_same_files_different_view_does_not_restore_old_tree_position(
    qapp, qtbot,
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    QCoreApplication.processEvents()

    widget.search.setText("tas")
    QCoreApplication.processEvents()
    assert file_item.isExpanded()
    widget.invalidate_filter_context()
    assert widget._filter_snapshot is None
    assert widget.search.text() == "tas"

    widget.search.clear()
    _flush(widget)
    assert file_item.isExpanded()

    widget.search.setText("tas")
    widget.search.clear()
    _flush(widget)
    assert file_item.isExpanded()


def test_rapid_clear_then_search_again_ignores_stale_restore(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    QCoreApplication.processEvents()

    widget.search.setText("tas")
    widget.search.clear()
    assert widget._filter_restore_pending
    widget.search.setText("tas")
    assert file_item.isExpanded()
    QCoreApplication.processEvents()
    assert file_item.isExpanded()

    widget.search.clear()
    _flush(widget)
    assert not file_item.isExpanded()


def test_manual_expand_during_filter_is_ephemeral(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(True)
    QCoreApplication.processEvents()

    widget.search.setText("tas")
    file_item.setExpanded(False)
    widget.search.clear()
    _flush(widget)
    assert file_item.isExpanded()


def test_search_clear_keeps_selected_only_filter_empty_clear_drops_both(
    qapp, qtbot,
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    file_item.child(0).setCheckState(0, Qt.Checked)
    QCoreApplication.processEvents()

    widget.search.setText("zzz")
    widget.btn_selected_only.setChecked(True)
    QCoreApplication.processEvents()
    assert _is_filter_empty_page(widget)
    assert _filter_empty_title(widget) == "没有匹配的通道"

    widget.search.clear()
    QCoreApplication.processEvents()
    assert widget.btn_selected_only.isChecked()
    assert widget.search.text() == ""
    assert not _is_filter_empty_page(widget)
    assert not file_item.child(0).isHidden()
    assert file_item.child(1).isHidden()
    assert file_item.isExpanded()

    file_item.child(0).setCheckState(0, Qt.Unchecked)
    QCoreApplication.processEvents()
    assert _is_filter_empty_page(widget)
    assert _filter_empty_title(widget) == "尚未勾选通道"

    _filter_empty_clear(widget).click()
    _flush(widget)
    assert widget.search.text() == ""
    assert not widget.btn_selected_only.isChecked()
    assert not _is_filter_empty_page(widget)
    assert not file_item.isExpanded()
    assert file_item.child(0).checkState(0) == Qt.Unchecked


def test_three_empty_states_are_mutually_exclusive(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)

    widget.search.setText("speed")
    widget.btn_selected_only.setChecked(True)
    QCoreApplication.processEvents()
    assert _is_no_attachment_page(widget)
    assert "尚未加入文件" in widget.empty_state.text()
    assert not _is_filter_empty_page(widget)
    assert widget.search.isVisible()
    assert widget.btn_all.isVisible()
    assert widget.config_bar.isVisible()
    widget.search.clear()
    widget.btn_selected_only.setChecked(False)

    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.btn_selected_only.setChecked(True)
    QCoreApplication.processEvents()
    assert _is_filter_empty_page(widget)
    assert _filter_empty_title(widget) == "尚未勾选通道"
    assert not _is_no_attachment_page(widget)
    assert widget.search.isEnabled()
    assert widget.btn_selected_only.isEnabled()
    assert widget.config_bar.isVisible()

    widget.btn_selected_only.setChecked(False)
    widget._file_items["file-a"].child(0).setCheckState(0, Qt.Checked)
    widget.search.setText("no-such-channel")
    QCoreApplication.processEvents()
    assert _is_filter_empty_page(widget)
    assert _filter_empty_title(widget) == "没有匹配的通道"
    assert "尚未勾选通道" not in _filter_empty_title(widget)
    assert "尚未加入文件" not in _filter_empty_title(widget)
    assert not _is_no_attachment_page(widget)


def test_esc_clears_keyword_but_does_not_swallow_parent_when_empty(qapp, qtbot):
    host = QWidget()
    host.escapes = []

    def _key_press(event):
        if event.key() == Qt.Key_Escape:
            host.escapes.append(event.key())
        QWidget.keyPressEvent(host, event)

    host.keyPressEvent = _key_press
    qtbot.addWidget(host)
    widget = MultiFileChannelWidget(host)
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    host.show()
    widget.show()
    qtbot.waitExposed(widget)
    widget.search.setFocus(Qt.OtherFocusReason)
    widget.search.setText("tas")
    QCoreApplication.processEvents()

    assert widget.search.receivers(widget.search.escape_requested) == 0
    qtbot.keyClick(widget.search, Qt.Key_Escape)
    QCoreApplication.processEvents()
    assert widget.search.text() == ""
    assert widget.search.hasFocus()
    assert host.escapes == []

    empty_event = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    QApplication.sendEvent(widget.search, empty_event)
    assert not empty_event.isAccepted()
    host.escapes.clear()
    qtbot.keyClick(widget.search, Qt.Key_Escape)
    QCoreApplication.processEvents()
    assert host.escapes == [Qt.Key_Escape]


def test_select_all_stays_visible_only_and_clear_all_still_clears_hidden(
    qapp, qtbot,
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    file_item.child(2).setCheckState(0, Qt.Checked)
    widget.search.setText("tas")
    QCoreApplication.processEvents()

    widget.btn_all.click()
    QCoreApplication.processEvents()
    checked = {row[1] for row in widget.get_checked_channels()}
    assert "Rte_TAS_mTorsionBarTorque_xds16" in checked
    assert "speed" not in checked
    assert "torque" in checked

    widget.search.clear()
    widget.btn_none.click()
    QCoreApplication.processEvents()
    assert widget.get_checked_channels() == []


def test_scroll_restore_uses_identity_anchor_and_numeric_fallback(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 220)
    widget.show()
    qtbot.waitExposed(widget)
    names = [f"ch_{index:02d}" for index in range(40)]
    _add_attached_file(widget, "file-a", _ReplaceableFileData(names))
    file_item = widget._file_items["file-a"]
    file_item.setExpanded(True)
    QCoreApplication.processEvents()
    bar = widget.tree.verticalScrollBar()
    bar.setValue(bar.maximum())
    saved = bar.value()
    assert saved > 0

    widget.search.setText("ch_00")
    QCoreApplication.processEvents()
    widget.search.clear()
    _flush(widget)
    assert bar.value() == saved


def test_invalidate_does_not_emit_or_change_search_and_checks(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.set_checked_channels([("file-a", "speed")])
    widget.set_hidden_channels([("file-a", "speed")])
    widget.search.setText("speed")
    widget.btn_selected_only.setChecked(True)
    fired = []
    widget.channels_changed.connect(lambda: fired.append("c"))
    widget.visibility_changed.connect(lambda *_args: fired.append("v"))

    widget.invalidate_filter_context()

    assert widget.search.text() == "speed"
    assert widget.btn_selected_only.isChecked()
    assert [row[:2] for row in widget.get_checked_channels()] == [
        ("file-a", "speed")
    ]
    assert widget.get_hidden_channels() == [("file-a", "speed")]
    assert fired == []
    assert widget._filter_snapshot is None
    assert not widget._filter_restore_pending


class _NavigatorFileData(_FakeFileData):
    time_array = [1, 2, 3]
    fs = 1.0
    short_name = "fake"


def test_file_navigator_forwards_invalidate_channel_filter_context(qtbot):
    navigator = FileNavigator()
    qtbot.addWidget(navigator)
    navigator.add_file("f1", _NavigatorFileData())
    navigator.set_attached_file_ids(["f1"])
    navigator.channel_list.search.setText("rpm")
    assert navigator.channel_list._filter_snapshot is not None
    generation = navigator.channel_list._filter_generation

    navigator.invalidate_channel_filter_context()

    assert navigator.channel_list._filter_snapshot is None
    assert navigator.channel_list._filter_generation == generation + 1
    assert navigator.channel_list.search.text() == "rpm"


def test_projection_entry_points_invalidate_before_applying_state():
    view_src = inspect.getsource(ViewMixin._project_view_controls)
    analysis_src = inspect.getsource(AnalysisMixin._project_analysis_attachments)
    view_idx = view_src.find("invalidate_channel_filter_context")
    analysis_idx = analysis_src.find("invalidate_channel_filter_context")
    assert view_idx != -1
    assert analysis_idx != -1
    assert view_idx < view_src.find("apply_controls_from_state")
    assert analysis_idx < analysis_src.find("set_attached_file_ids")
    assert "self._filter_snapshot" not in view_src
    assert "self._filter_snapshot" not in analysis_src
