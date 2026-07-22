from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QMessageBox, QPushButton

from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui.widgets import MultiFileChannelWidget


class _FakeFileData:
    data = [1, 2, 3]

    def get_signal_channels(self):
        return ["speed"]

    def get_color_palette(self):
        return ["#1769e0"]


class _MultiChannelFileData:
    data = [1, 2, 3]

    def get_signal_channels(self):
        return ["speed", "Rte_TAS_mTorsionBarTorque_xds16", "torque"]

    def get_color_palette(self):
        return ["#1769e0", "#8b5cf6", "#f43f5e"]


def _add_attached_file(widget, fid, file_data):
    """Mirror the production View contract for channel-widget tests."""
    widget.add_file(fid, file_data)
    widget.set_attached_file_ids([*widget.get_attached_file_ids(), fid])


def test_channel_context_menu_uses_translucent_rounded_shell(qapp, qtbot, monkeypatch):
    captured = []

    def fake_exec(menu, *_args, **_kwargs):
        captured.append(menu)
        return None

    monkeypatch.setattr("mf4_analyzer.ui.widgets.QMenu.exec_", fake_exec)

    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(320, 240)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _FakeFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    channel_item = widget._file_items["file-a"].child(0)
    widget.tree.scrollToItem(channel_item)
    QCoreApplication.processEvents()
    pos = widget.tree.visualItemRect(channel_item).center()
    assert widget.tree.itemAt(pos) is channel_item
    widget._on_context_menu(pos)

    assert captured, "right-clicking a channel row should create the channel menu"
    menu = captured[-1]
    assert menu.objectName() == "channelContextMenu"
    assert menu.testAttribute(Qt.WA_TranslucentBackground), (
        "rounded channel QMenu needs a transparent shell, otherwise the radius "
        "shows a rectangular backing"
    )
    flags = menu.windowFlags()
    assert bool(flags & Qt.NoDropShadowWindowHint), (
        "macOS rounded QMenu must disable the native rectangular shadow"
    )
    assert bool(flags & Qt.FramelessWindowHint), (
        "rounded QMenu needs a frameless window so square platform corners do not show"
    )


def test_channel_action_buttons_use_two_char_chinese(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    labels = {b.text() for b in widget.findChildren(QPushButton)}
    # The compact channel actions use two-character Chinese labels.
    assert {"全选", "全不", "已选"} <= labels
    assert "反选" not in labels
    # 编辑通道 moved down from the top toolbar onto the channel-action row.
    assert "编辑通道" in labels


def test_channel_tree_has_compact_time_visibility_column(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)

    assert widget.tree.columnCount() == 3
    assert widget.tree.headerItem().text(2) == "显示"
    assert widget.tree.header().sectionSize(2) == 42


def test_time_visibility_icons_are_distinct(qapp):
    opened = Icons.eye_open()
    closed = Icons.eye_closed()

    assert not opened.isNull()
    assert not closed.isNull()
    assert opened.cacheKey() != closed.cacheKey()


def test_checked_channel_eye_toggles_without_unchecking(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    item = widget._file_items["file-a"].child(0)

    assert item.icon(2).isNull()
    item.setCheckState(0, Qt.Checked)
    assert not item.icon(2).isNull()
    assert item.toolTip(2) == "点击隐藏此通道（仅影响时域图）"

    fired = []
    widget.visibility_changed.connect(lambda *args: fired.append(args))
    widget._on_item_clicked(item, 2)

    assert item.checkState(0) == Qt.Checked
    assert widget.get_hidden_channels() == [("file-a", "speed")]
    assert widget.get_visible_checked_channels() == []
    assert item.toolTip(2) == "点击显示此通道（仅影响时域图）"
    assert fired == [("file-a", "speed", False)]

    widget._on_item_clicked(item, 2)

    assert widget.get_hidden_channels() == []
    assert [row[:2] for row in widget.get_visible_checked_channels()] == [
        ("file-a", "speed")
    ]
    assert fired[-1] == ("file-a", "speed", True)


def test_eye_click_never_propagates_to_other_selected_rows(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    file_item = widget._file_items["file-a"]
    first = file_item.child(0)
    second = file_item.child(1)
    widget.set_checked_channels([
        ("file-a", "speed"),
        ("file-a", "Rte_TAS_mTorsionBarTorque_xds16"),
    ])
    first.setSelected(True)
    second.setSelected(True)

    widget._on_item_clicked(first, 2)

    assert widget.get_hidden_channels() == [("file-a", "speed")]
    assert not second.icon(2).isNull()


def test_time_visibility_column_hides_outside_time_mode(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)

    widget.set_time_visibility_available(False)
    assert widget.tree.isColumnHidden(2)

    widget.set_time_visibility_available(True)
    assert not widget.tree.isColumnHidden(2)


def test_channel_search_expands_parent_to_show_matches(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    QCoreApplication.processEvents()

    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    widget.search.setText("tas")
    QCoreApplication.processEvents()

    assert not file_item.isHidden()
    assert file_item.isExpanded()
    visible = [
        (file_item.child(i).text(0), not file_item.child(i).isHidden())
        for i in range(file_item.childCount())
    ]
    assert visible == [
        ("speed", False),
        ("Rte_TAS_mTorsionBarTorque_xds16", True),
        ("torque", False),
    ]


def test_selected_filter_button_only_shows_checked_channels(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    QCoreApplication.processEvents()

    file_item = widget._file_items["file-a"]
    file_item.setExpanded(False)
    file_item.child(1).setCheckState(0, Qt.Checked)
    QCoreApplication.processEvents()

    selected_button = next(
        button for button in widget.findChildren(QPushButton)
        if button.text() == "已选"
    )
    selected_button.click()
    QCoreApplication.processEvents()

    assert selected_button.isChecked()
    assert not file_item.isHidden()
    assert file_item.isExpanded()
    visible = [
        (file_item.child(i).text(0), not file_item.child(i).isHidden())
        for i in range(file_item.childCount())
    ]
    assert visible == [
        ("speed", False),
        ("Rte_TAS_mTorsionBarTorque_xds16", True),
        ("torque", False),
    ]


def _left_click(tree, pos):
    """Synthesize a left-button press at viewport ``pos`` and dispatch it to
    the tree so the custom mousePressEvent tolerance logic runs."""
    ev = QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    tree.mousePressEvent(ev)


def test_checkbox_hit_tolerance_band_toggles_but_name_does_not(qapp, qtbot):
    """Clicking just LEFT of the checkbox (inside the ~6px tolerance band)
    must toggle the channel's check state; clicking on the channel-name
    text must NOT toggle it (selection / 设为左轴 territory)."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _FakeFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    tree = widget.tree
    channel_item = widget._file_items["file-a"].child(0)
    tree.scrollToItem(channel_item)
    QCoreApplication.processEvents()

    index = tree.indexFromItem(channel_item, 0)
    hit = tree._check_hit_rect(channel_item, index)
    assert hit is not None

    assert channel_item.checkState(0) == Qt.Unchecked

    # A point just inside the LEFT edge of the tolerance band (left of the
    # actual indicator box) must still toggle.
    band_pos = QPoint(hit.left() + 1, hit.center().y())
    _left_click(tree, band_pos)
    QCoreApplication.processEvents()
    assert channel_item.checkState(0) == Qt.Checked, (
        "click inside the widened tolerance band should toggle the checkbox"
    )

    # A point on the channel-name text (well right of the band) must NOT
    # toggle — that area is for selection / right-click 设为左轴.
    row = tree.visualItemRect(channel_item)
    name_pos = QPoint(row.right() - 8, row.center().y())
    assert not hit.contains(name_pos)
    _left_click(tree, name_pos)
    QCoreApplication.processEvents()
    assert channel_item.checkState(0) == Qt.Checked, (
        "clicking the channel name must leave the check state unchanged"
    )


def test_checkbox_double_click_event_is_consumed_after_row_selection(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _FakeFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    tree = widget.tree
    channel_item = widget._file_items["file-a"].child(0)
    tree.scrollToItem(channel_item)
    QCoreApplication.processEvents()

    row = tree.visualItemRect(channel_item)
    name_pos = row.center()
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, name_pos)
    QCoreApplication.processEvents()
    assert tree.currentItem() is channel_item

    index = tree.indexFromItem(channel_item, 0)
    hit = tree._check_hit_rect(channel_item, index)
    assert hit is not None
    assert channel_item.checkState(0) == Qt.Unchecked

    double_clicked = []
    tree.itemDoubleClicked.connect(
        lambda item, column: double_clicked.append((item, column))
    )

    QTest.mouseDClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, hit.center())
    QCoreApplication.processEvents()

    assert channel_item.checkState(0) == Qt.Checked
    assert double_clicked == []


def test_selected_channel_checkbox_center_click_toggles_once(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _FakeFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    tree = widget.tree
    channel_item = widget._file_items["file-a"].child(0)
    tree.scrollToItem(channel_item)
    QCoreApplication.processEvents()

    row = tree.visualItemRect(channel_item)
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, row.center())
    QCoreApplication.processEvents()
    assert tree.currentItem() is channel_item

    hit = tree._check_hit_rect(channel_item, tree.indexFromItem(channel_item, 0))
    assert hit is not None
    assert channel_item.checkState(0) == Qt.Unchecked

    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, hit.center())
    QCoreApplication.processEvents()

    assert channel_item.checkState(0) == Qt.Checked


def test_checkbox_click_batches_selected_channel_rows_after_confirmation(
    qapp, qtbot, monkeypatch
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    tree = widget.tree
    file_item = widget._file_items["file-a"]
    first = file_item.child(0)
    second = file_item.child(1)
    tree.clearSelection()
    first.setSelected(True)
    second.setSelected(True)
    QCoreApplication.processEvents()

    fired = []
    widget.channels_changed.connect(lambda: fired.append(1))
    monkeypatch.setattr(
        widget, "_confirm_selected_channel_checks", lambda *_args: True
    )
    hit = tree._check_hit_rect(first, tree.indexFromItem(first, 0))
    assert hit is not None

    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, hit.center())
    QCoreApplication.processEvents()

    assert first.checkState(0) == Qt.Checked
    assert second.checkState(0) == Qt.Checked
    assert file_item.child(2).checkState(0) == Qt.Unchecked
    assert fired == [1]


def test_checkbox_batch_cancel_keeps_states_and_emits_nothing(
    qapp, qtbot, monkeypatch
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    tree = widget.tree
    file_item = widget._file_items["file-a"]
    first = file_item.child(0)
    second = file_item.child(1)
    tree.clearSelection()
    first.setSelected(True)
    second.setSelected(True)
    monkeypatch.setattr(
        widget, "_confirm_selected_channel_checks", lambda *_args: False
    )
    fired = []
    widget.channels_changed.connect(lambda: fired.append(1))

    hit = tree._check_hit_rect(first, tree.indexFromItem(first, 0))
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, hit.center())
    QCoreApplication.processEvents()

    assert first.checkState(0) == Qt.Unchecked
    assert second.checkState(0) == Qt.Unchecked
    assert fired == []


def test_checkbox_batch_check_confirmation_reopens_hidden_members(
    qapp, qtbot, monkeypatch
):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    tree = widget.tree
    file_item = widget._file_items["file-a"]
    first = file_item.child(0)
    second = file_item.child(1)
    second.setCheckState(0, Qt.Checked)
    widget.set_channel_visible(
        "file-a", "Rte_TAS_mTorsionBarTorque_xds16", False, emit=False
    )
    tree.clearSelection()
    first.setSelected(True)
    second.setSelected(True)
    monkeypatch.setattr(
        widget, "_confirm_selected_channel_checks", lambda *_args: True
    )

    hit = tree._check_hit_rect(first, tree.indexFromItem(first, 0))
    QTest.mouseClick(tree.viewport(), Qt.LeftButton, Qt.NoModifier, hit.center())
    QCoreApplication.processEvents()

    assert first.checkState(0) == Qt.Checked
    assert second.checkState(0) == Qt.Checked
    assert widget.get_hidden_channels() == []


def test_batch_confirmation_copy_and_default_cancel(qapp, qtbot, monkeypatch):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    boxes = []
    titles = []
    original_set_window_title = QMessageBox.setWindowTitle

    def capture_window_title(box, title):
        titles.append(title)
        original_set_window_title(box, title)

    monkeypatch.setattr(QMessageBox, "setWindowTitle", capture_window_title)
    monkeypatch.setattr(
        QMessageBox, "exec_", lambda box: boxes.append(box) or 0
    )

    assert widget._confirm_selected_channel_checks(5, Qt.Checked) is False
    check_box = boxes[-1]
    assert titles[-1] == "批量操作确认"
    assert check_box.text() == "当前选中了 5 个通道，是否将它们全部勾选并显示？"
    assert {button.text() for button in check_box.buttons()} == {
        "全部勾选并显示", "取消操作"
    }
    assert check_box.defaultButton().text() == "取消操作"

    assert widget._confirm_selected_channel_checks(5, Qt.Unchecked) is False
    uncheck_box = boxes[-1]
    assert uncheck_box.text() == (
        "当前选中了 5 个通道，是否将它们全部取消勾选并从当前视图移除？"
    )
    assert {button.text() for button in uncheck_box.buttons()} == {
        "全部取消勾选", "取消操作"
    }
    assert uncheck_box.defaultButton().text() == "取消操作"


def test_edit_channels_button_enables_with_file_and_emits(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    # Disabled until a file is loaded — editing channels needs a file.
    assert not widget.btn_edit.isEnabled()

    _add_attached_file(widget, "file-a", _FakeFileData())
    assert widget.btn_edit.isEnabled()

    with qtbot.waitSignal(widget.channel_editor_requested, timeout=200):
        widget.btn_edit.click()

    widget.remove_file("file-a")
    assert not widget.btn_edit.isEnabled()
