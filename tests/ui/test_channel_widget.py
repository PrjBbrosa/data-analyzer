import json
from pathlib import Path

from PyQt5.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, Qt
from PyQt5.QtGui import QColor, QDragLeaveEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton

from mf4_analyzer.ui.channel_drag import (
    INTERNAL_CHANNEL_MIME,
    decode_channel_drag,
    encode_channel_drag,
)

from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit.icons import Icons
from mf4_analyzer.ui.widgets import INTERNAL_FILE_FIDS_MIME, MultiFileChannelWidget


def test_channel_tree_selected_rows_render_approved_windows_highlight(qapp, qtbot):
    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        widget = MultiFileChannelWidget()
        qtbot.addWidget(widget)
        widget.resize(520, 360)
        _add_attached_file(widget, "file-a", _MultiChannelFileData())
        widget.show()
        qtbot.waitExposed(widget)

        item = widget._file_items["file-a"].child(0)
        widget.tree.setCurrentItem(item)
        item.setSelected(True)
        qapp.processEvents()

        row = widget.tree.visualItemRect(item)
        image = widget.tree.viewport().grab().toImage()
        expected = QColor("#b7d3f2")
        body_x = widget.tree.columnViewportPosition(2) + 4

        body_color = image.pixelColor(body_x, row.center().y())
        branch_color = image.pixelColor(2, row.center().y())

        assert body_color == expected, (
            f"selected row body rendered {body_color.name()}, expected {expected.name()}"
        )
        assert branch_color == expected, (
            "selected row branch gutter rendered "
            f"{branch_color.name()}, expected {expected.name()}"
        )
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


def test_selected_file_parent_keeps_a_visible_expander(qapp, qtbot):
    """The selected-row tint must not swallow a clickable parent chevron."""
    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        widget = MultiFileChannelWidget()
        qtbot.addWidget(widget)
        widget.resize(520, 360)
        _add_attached_file(widget, "file-a", _MultiChannelFileData())
        widget.show()
        qtbot.waitExposed(widget)

        parent = widget._file_items["file-a"]
        widget.tree.setCurrentItem(parent)
        parent.setSelected(True)
        qapp.processEvents()

        row = widget.tree.visualItemRect(parent)
        image = widget.tree.viewport().grab().toImage()
        gutter_left = widget.tree.columnViewportPosition(0)
        gutter_right = row.left() - 1
        dark_pixels = [
            image.pixelColor(x, y)
            for y in range(row.top() + 4, row.bottom() - 3)
            for x in range(gutter_left + 2, gutter_right)
            if image.pixelColor(x, y).lightness() < 175
        ]

        assert dark_pixels, "selected file row lost its expand/collapse chevron"
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


def test_selected_file_parent_selection_is_a_continuous_bar(qapp, qtbot):
    """Expander slot and display-column action share one rectangular fill.

    Per-cell ``::item:selected`` / ``::branch:selected`` radius used to paint
    a circle around the chevron and a pill around the red x, with the tree
    background showing at the square slot corners.
    """
    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        widget = MultiFileChannelWidget()
        qtbot.addWidget(widget)
        widget.resize(520, 360)
        _add_attached_file(widget, "file-a", _MultiChannelFileData())
        widget.show()
        qtbot.waitExposed(widget)

        parent = widget._file_items["file-a"]
        widget.tree.setCurrentItem(parent)
        parent.setSelected(True)
        widget._on_item_entered(parent, 2)
        qapp.processEvents()

        expected = QColor("#b7d3f2")
        tree = widget.tree
        image = tree.viewport().grab().toImage()
        row = tree.visualItemRect(parent)
        display = tree.visualRect(tree.indexFromItem(parent, 2))
        pts = tree.visualRect(tree.indexFromItem(parent, 1))
        gutter_right = row.left()

        def _assert_fill(x, y, where):
            color = image.pixelColor(x, y)
            assert color == expected, (
                f"{where} at ({x},{y}) rendered {color.name()}, "
                f"expected {expected.name()}"
            )

        _assert_fill(2, row.top() + 1, "branch slot top-left")
        _assert_fill(2, row.bottom() - 1, "branch slot bottom-left")
        _assert_fill(gutter_right - 2, row.top() + 1, "branch slot top-right")
        _assert_fill(gutter_right - 2, row.bottom() - 1, "branch slot bottom-right")
        _assert_fill(display.left() + 1, display.top() + 1, "display top-left")
        _assert_fill(display.right() - 1, display.top() + 1, "display top-right")
        _assert_fill(display.left() + 1, display.bottom() - 1, "display bottom-left")
        _assert_fill(display.right() - 1, display.bottom() - 1, "display bottom-right")
        _assert_fill(pts.right() - 2, row.center().y(), "pts near display seam")
        _assert_fill(display.left() + 2, row.center().y(), "display near pts seam")
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


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


class _GroupedFileData(_MultiChannelFileData):
    def __init__(self, fs, label_suffix):
        self.data = list(range(100))
        self.fs = fs
        self.filepath = Path("/tmp/260417-ripple-PK2C.mf4")
        self.label_suffix = label_suffix


class _WwtGroupedFileData:
    def __init__(self, zeit, channels, channel_metadata=None):
        self.data = list(range(100))
        self.fs = 1000.0
        self.filepath = Path("/tmp/same-physical.wwt")
        self.label_suffix = "1.0 kHz"
        self.source_metadata = {
            "source_kind": "wwt",
            "zeit_record_indices": (zeit,),
        }
        self.channel_metadata = channel_metadata or {}
        self._channels = list(channels)

    def get_signal_channels(self):
        return list(self._channels)

    def get_color_palette(self):
        return ["#1769e0"] * max(1, len(self._channels))


class _ReplaceableFileData:
    data = [1, 2, 3]

    def __init__(self, channels):
        self._channels = list(channels)

    def get_signal_channels(self):
        return list(self._channels)

    def get_color_palette(self):
        return ["#1769e0", "#8b5cf6", "#f43f5e", "#f59e0b"]


def _add_attached_file(widget, fid, file_data):
    """Mirror the production View contract for channel-widget tests."""
    widget.add_file(fid, file_data)
    widget.set_attached_file_ids([*widget.get_attached_file_ids(), fid])


def test_nested_parent_checkbox_geometry_stays_aligned_when_selected(qapp, qtbot):
    """Selected raster rows keep the sibling box and hit band in one slot."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(520, 360)
    _add_attached_file(widget, "f0", _GroupedFileData(1188000, "24.0 kHz"))
    _add_attached_file(widget, "f1", _GroupedFileData(49500, "1.0 kHz"))
    widget.show()
    qtbot.waitExposed(widget)
    widget.tree.expandAll()

    selected = widget._raster_items["f0"]
    sibling = widget._raster_items["f1"]
    widget.tree.setCurrentItem(selected)
    selected.setSelected(True)
    qapp.processEvents()

    delegate = widget.tree.itemDelegate()
    selected_box = delegate.parent_geometry(
        widget.tree.visualItemRect(selected)
    )[0]
    sibling_box = delegate.parent_geometry(
        widget.tree.visualItemRect(sibling)
    )[0]
    assert selected_box.left() == sibling_box.left()
    assert selected_box.width() == sibling_box.width()

    hit = widget.tree._check_hit_rect(
        selected, widget.tree.indexFromItem(selected, 0)
    )
    assert hit.contains(selected_box.center())
    assert not hit.contains(
        QPoint(selected_box.right() + widget.tree.HIT_PAD + 2,
               selected_box.center().y())
    )

    QTest.mouseClick(
        widget.tree.viewport(), Qt.LeftButton, Qt.NoModifier,
        selected_box.center(),
    )
    qapp.processEvents()
    assert selected.checkState(0) == Qt.Checked


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


def test_projection_role_updates_header_and_checkable_flags(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "f0", _MultiChannelFileData())
    channel = widget._file_items["f0"].child(0)
    assert channel is not None
    assert channel.flags() & Qt.ItemIsUserCheckable

    widget.set_projection_role("fft_sources")
    assert widget.tree.headerItem().text(2) == "来源"
    assert channel.flags() & Qt.ItemIsUserCheckable

    widget.set_projection_role("analysis_candidates")
    assert widget.tree.headerItem().text(2) == "移出"
    assert not (channel.flags() & Qt.ItemIsUserCheckable)
    file_item = widget._file_items["f0"]
    assert not (file_item.flags() & Qt.ItemIsUserCheckable)

    widget.set_projection_role("time")
    assert widget.tree.headerItem().text(2) == "显示"
    assert channel.flags() & Qt.ItemIsUserCheckable
    assert file_item.flags() & Qt.ItemIsUserCheckable


def test_set_projection_role_repeat_call_skips_replay_but_role_change_still_replays(
    qapp, qtbot, monkeypatch,
):
    """A same-role call is a no-op early-return; a real role change still
    replays icons/chrome/empty-state in full."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "f0", _MultiChannelFileData())

    widget.set_projection_role("fft_sources")

    calls = []
    monkeypatch.setattr(
        widget, "_refresh_visibility_icons", lambda: calls.append("icons")
    )
    monkeypatch.setattr(
        widget, "_sync_projection_chrome", lambda: calls.append("chrome")
    )
    monkeypatch.setattr(
        widget, "_sync_empty_state", lambda: calls.append("empty")
    )

    # Redundant call: (role, checks_editable, visibility_available) is
    # unchanged, so this must hit the early-return path.
    widget.set_projection_role("fft_sources")
    assert calls == []

    # A genuine role change must still do the full replay.
    widget.set_projection_role("analysis_candidates")
    assert calls == ["icons", "chrome", "empty"]


def test_projection_role_repeat_call_then_rebuilt_rows_stay_non_checkable(
    qapp, qtbot,
):
    """Guard against a stale early-return cache: a redundant same-role call
    must not let later-added/rebuilt rows slip past analysis_candidates'
    non-checkable chrome. ``add_file`` always calls ``_sync_projection_chrome``
    directly after building new rows and must not be shadowed by the cache
    ``set_projection_role`` keeps for its own no-op short-circuit."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "f0", _MultiChannelFileData())

    widget.set_projection_role("analysis_candidates")
    # Redundant call with the same role: expected to early-return internally.
    widget.set_projection_role("analysis_candidates")

    channel = widget._file_items["f0"].child(0)
    assert not (channel.flags() & Qt.ItemIsUserCheckable)

    # New rows always start checkable; add_file's own explicit chrome sync
    # must still flip them non-checkable despite the cached "no change"
    # signature on set_projection_role.
    _add_attached_file(widget, "f1", _MultiChannelFileData())
    new_channel = widget._file_items["f1"].child(0)
    new_file_item = widget._file_items["f1"]
    assert not (new_channel.flags() & Qt.ItemIsUserCheckable)
    assert not (new_file_item.flags() & Qt.ItemIsUserCheckable)


def test_set_projection_role_repeat_call_keeps_empty_state_text_stable(
    qapp, qtbot,
):
    """A no-op early-return must not leave the empty-state copy stale."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.set_empty_state_context(section_label="频域", view_name="View 2")

    widget.set_projection_role("fft_sources")
    text_before = widget.empty_state.text()
    assert "频域 · View 2" in text_before

    widget.set_projection_role("fft_sources")
    assert widget.empty_state.text() == text_before


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


def test_time_visibility_toggle_hides_channel_eyes_but_not_file_remove(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.set_checked_channels([("file-a", "speed")])
    file_item = widget._file_items["file-a"]
    channel = file_item.child(0)

    widget.set_time_visibility_available(False)
    assert not widget.tree.isColumnHidden(2)
    assert channel.icon(2).isNull()

    widget.set_time_visibility_available(True)
    assert not widget.tree.isColumnHidden(2)
    assert not channel.icon(2).isNull()


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


def _left_drag(tree, start, end):
    """Drag across tree rows with the left button held."""
    viewport = tree.viewport()
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    QCoreApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton, Qt.NoModifier
        ),
    )
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)


def test_channel_tree_left_drag_does_not_extend_selection(qapp, qtbot, monkeypatch):
    """A row drag must not accidentally turn single selection into a range."""
    class _FakeDrag:
        def __init__(self, parent):
            pass

        def setMimeData(self, mime):
            pass

        def setPixmap(self, pix):
            pass

        def exec_(self, *args, **kwargs):
            return Qt.IgnoreAction

    monkeypatch.setattr("mf4_analyzer.ui.widgets.channel_tree.QDrag", _FakeDrag)
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
    third = file_item.child(2)
    tree.scrollToItem(third)
    QCoreApplication.processEvents()

    _left_drag(
        tree,
        tree.visualItemRect(first).center(),
        tree.visualItemRect(third).center(),
    )
    QCoreApplication.processEvents()

    assert tree.selectedItems() == [first]

    QTest.mouseClick(
        tree.viewport(), Qt.LeftButton, Qt.NoModifier,
        tree.visualItemRect(first).center(),
    )
    QTest.mouseClick(
        tree.viewport(), Qt.LeftButton, Qt.ControlModifier,
        tree.visualItemRect(third).center(),
    )
    assert tree.selectedItems() == [first, third]

    tree.clearSelection()
    QTest.mouseClick(
        tree.viewport(), Qt.LeftButton, Qt.NoModifier,
        tree.visualItemRect(first).center(),
    )
    QTest.mouseClick(
        tree.viewport(), Qt.LeftButton, Qt.ShiftModifier,
        tree.visualItemRect(third).center(),
    )
    assert tree.selectedItems() == [first, second, third]


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


def test_refresh_file_preserves_view_attachment_and_tree_interactions(qapp, qtbot):
    """Refreshing an edited source is not equivalent to detaching it."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _ReplaceableFileData(["speed", "torque"]))
    widget.set_checked_channels([("file-a", "speed"), ("file-a", "torque")])
    widget.set_hidden_channels([("file-a", "speed")])
    widget.set_channel_colors({("file-a", "speed"): "#abcdef"})
    widget.merge_axis_group([("file-a", "speed"), ("file-a", "torque")])

    old_file_item = widget._file_items["file-a"]
    speed = old_file_item.child(0)
    speed.setSelected(True)
    widget.tree.setCurrentItem(speed)
    old_file_item.setExpanded(False)

    widget.refresh_file(
        "file-a", _ReplaceableFileData(["speed", "torque", "d_dt_speed"])
    )

    assert widget.get_attached_file_ids() == ["file-a"]
    assert [row[:2] for row in widget.get_checked_channels()] == [
        ("file-a", "speed"), ("file-a", "torque"),
    ]
    assert widget.get_hidden_channels() == [("file-a", "speed")]
    assert widget.get_channel_colors()[("file-a", "speed")] == "#abcdef"
    assert widget.axis_group_for("file-a", "speed") == 1
    assert widget.axis_group_for("file-a", "torque") == 1

    refreshed = widget._file_items["file-a"]
    assert not refreshed.isExpanded()
    assert widget.tree.currentItem().data(0, Qt.UserRole) == (
        "channel", "file-a", "speed"
    )
    assert [refreshed.child(i).text(0) for i in range(refreshed.childCount())] == [
        "speed", "torque", "d_dt_speed",
    ]


class _LongNameFileData:
    """Names shaped like the HEAD CAN channels: long, distinguished by suffix."""
    data = [1, 2, 3]
    channel_units = {
        "Com_Motor_Torque_DV": "Nm",
        "Com_Motor_Torque_PV": "Nm",
        "Com_Motor_Torque_VT": "",
    }

    def get_signal_channels(self):
        return list(self.channel_units)

    def get_color_palette(self):
        return ["#1769e0", "#8b5cf6", "#f43f5e"]


def test_channel_rows_carry_full_name_tooltip(qapp, qtbot):
    """An elided name must stay readable somewhere — column 0 had no tooltip.

    The Channel column is narrow at the default dock width (real render: ~42 px
    of text room once indentation, checkbox and swatch are subtracted), so
    20-character measurement names are always elided there. Rows only had
    tooltips on the eye column, leaving the name itself unreadable.
    """
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _LongNameFileData())

    parent = widget._file_items["file-a"]
    tips = {
        parent.child(i).text(0): parent.child(i).toolTip(0)
        for i in range(parent.childCount())
    }
    assert tips["Com_Motor_Torque_DV"] == "Com_Motor_Torque_DV [Nm]"
    assert tips["Com_Motor_Torque_PV"] == "Com_Motor_Torque_PV [Nm]"
    # No unit recorded -> bare name, not a dangling "[]"
    assert tips["Com_Motor_Torque_VT"] == "Com_Motor_Torque_VT"


def test_channel_names_elide_in_the_middle_to_keep_the_suffix(qapp, qtbot):
    """ElideRight ate the only part that distinguishes these channels.

    ``Com_Motor_Torque_DV`` / ``_PV`` / ``_VT`` share a 16-character prefix.
    Tail elision renders all three as the same ``Com_Motor_Torq…`` row; middle
    elision keeps both ends, so the suffix survives at any column width.
    """
    from PyQt5.QtGui import QFontMetrics
    from mf4_analyzer.ui.widgets.channel_tree import _ChannelLeafDelegate

    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _LongNameFileData())
    delegate = widget.tree.itemDelegate()
    assert isinstance(delegate, _ChannelLeafDelegate)

    fm = QFontMetrics(widget.tree.font())
    names = list(_LongNameFileData.channel_units)
    width = fm.horizontalAdvance(names[0]) * 2 // 3   # forces elision

    tail = {fm.elidedText(n, Qt.ElideRight, width) for n in names}
    middle = {fm.elidedText(n, Qt.ElideMiddle, width) for n in names}
    assert len(tail) == 1, "tail elision collapses the three into one label"
    assert len(middle) == 3, "middle elision keeps them distinguishable"
    for name, shown in zip(names, (fm.elidedText(n, Qt.ElideMiddle, width)
                                   for n in names)):
        assert shown.endswith(name[-2:])


def test_delegate_paints_channel_names_with_middle_elision(qapp, qtbot):
    """Guard the delegate's own elide mode, not just QFontMetrics behaviour."""
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QStyleOptionViewItem

    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _LongNameFileData())
    delegate = widget.tree.itemDelegate()

    captured = []
    original = delegate._paint_text

    def spy(painter, rect, text, color, alignment, option, elide=Qt.ElideRight):
        captured.append((str(text), elide))
        return original(painter, rect, text, color, alignment, option, elide)

    delegate._paint_text = spy
    widget.resize(240, 300)
    widget.show()
    qtbot.waitExposed(widget)
    widget.tree.expandAll()
    qapp.processEvents()
    widget.tree.viewport().grab()

    name_paints = [
        (text, elide) for text, elide in captured
        if text in _LongNameFileData.channel_units
    ]
    assert name_paints, "channel names were never painted by the delegate"
    assert all(elide == Qt.ElideMiddle for _text, elide in name_paints)


def _channel_mime(fid, channel):
    mime = QMimeData()
    mime.setData(INTERNAL_CHANNEL_MIME, encode_channel_drag(fid, channel))
    return mime


def _file_mime(fids):
    mime = QMimeData()
    mime.setData(INTERNAL_FILE_FIDS_MIME, json.dumps(list(fids)).encode("utf-8"))
    return mime


class _FakeChannelDrag:
    last_mime = None
    parents = []

    def __init__(self, parent):
        type(self).parents.append(parent)

    def setMimeData(self, mime):
        type(self).last_mime = mime

    def setPixmap(self, pix):
        pass

    def exec_(self, *args, **kwargs):
        return Qt.CopyAction


def test_encode_decode_channel_drag_roundtrip():
    raw = encode_channel_drag("f0", "MotorTorque")
    assert decode_channel_drag(raw) == ("f0", "MotorTorque")
    assert decode_channel_drag(b"not-json") is None
    assert decode_channel_drag(b'{"version":2,"kind":"channel","fid":"f0","channel":"x"}') is None


def test_channel_body_drag_encodes_composite_mime(qapp, qtbot, monkeypatch):
    _FakeChannelDrag.last_mime = None
    _FakeChannelDrag.parents = []
    monkeypatch.setattr("mf4_analyzer.ui.widgets.channel_tree.QDrag", _FakeChannelDrag)
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    tree = widget.tree
    item = widget._file_items["file-a"].child(0)
    pos = tree.visualItemRect(item).center()
    tree.mousePressEvent(
        QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    )
    far = QPoint(pos.x(), pos.y() + QApplication.startDragDistance() + 8)
    tree.mouseMoveEvent(
        QMouseEvent(QEvent.MouseMove, far, Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    )

    assert _FakeChannelDrag.last_mime is not None
    assert decode_channel_drag(bytes(_FakeChannelDrag.last_mime.data(INTERNAL_CHANNEL_MIME))) == (
        "file-a",
        "speed",
    )
    assert _FakeChannelDrag.parents == [widget.window()]


def test_checkbox_does_not_start_tree_drag(qapp, qtbot, monkeypatch):
    _FakeChannelDrag.last_mime = None
    monkeypatch.setattr("mf4_analyzer.ui.widgets.channel_tree.QDrag", _FakeChannelDrag)
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    tree = widget.tree
    parent = widget._file_items["file-a"]
    channel = parent.child(0)
    index = tree.indexFromItem(channel, 0)
    hit = tree._check_hit_rect(channel, index)
    tree.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress,
            hit.center(),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    tree.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove,
            QPoint(hit.center().x(), hit.center().y() + QApplication.startDragDistance() + 8),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert _FakeChannelDrag.last_mime is None


def test_file_root_drag_encodes_file_mime(qapp, qtbot, monkeypatch):
    _FakeChannelDrag.last_mime = None
    _FakeChannelDrag.parents = []
    monkeypatch.setattr("mf4_analyzer.ui.widgets.channel_tree.QDrag", _FakeChannelDrag)
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    tree = widget.tree
    parent = widget._file_items["file-a"]
    row = tree.visualItemRect(parent)
    hit = tree._check_hit_rect(parent, tree.indexFromItem(parent, 0))
    pos = QPoint(hit.right() + 12, row.center().y())
    tree.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress,
            pos,
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    tree.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove,
            pos + QPoint(0, QApplication.startDragDistance() + 8),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert _FakeChannelDrag.last_mime is not None
    assert json.loads(
        bytes(_FakeChannelDrag.last_mime.data(INTERNAL_FILE_FIDS_MIME)).decode("utf-8")
    ) == ["file-a"]
    assert _FakeChannelDrag.parents == [widget.window()]


def test_file_root_drag_is_time_tree_only(qapp, qtbot, monkeypatch):
    _FakeChannelDrag.last_mime = None
    monkeypatch.setattr("mf4_analyzer.ui.widgets.channel_tree.QDrag", _FakeChannelDrag)
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.set_projection_role("fft_sources")
    widget.tree.expandAll()
    qapp.processEvents()

    tree = widget.tree
    parent = widget._file_items["file-a"]
    row = tree.visualItemRect(parent)
    hit = tree._check_hit_rect(parent, tree.indexFromItem(parent, 0))
    pos = QPoint(hit.right() + 12, row.center().y())
    tree.mousePressEvent(
        QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    )
    tree.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove,
            pos + QPoint(0, QApplication.startDragDistance() + 8),
            Qt.NoButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )

    assert _FakeChannelDrag.last_mime is None


def test_file_root_drop_emits_tree_file_order_request(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 320)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    _add_attached_file(widget, "file-b", _FakeFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    target = widget._file_items["file-b"]
    target_row = widget.tree.visualItemRect(target)
    pos = target_row.bottomLeft() - QPoint(-8, 2)
    mime = _file_mime(["file-a"])
    event = QDropEvent(
        pos, Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    captured = []
    widget.file_tree_order_requested.connect(
        lambda source, target, placement: captured.append(
            (source, target, placement)
        )
    )

    with qtbot.assertNotEmitted(widget.files_attach_requested):
        assert widget.eventFilter(widget.tree.viewport(), event) is True

    assert event.isAccepted()
    assert event.dropAction() == Qt.MoveAction
    assert captured == [("file-a", "file-b", "after")]


def test_file_root_drag_move_shows_and_clears_tree_insert_line(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 320)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    _add_attached_file(widget, "file-b", _FakeFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    target = widget._file_items["file-b"]
    target_row = widget.tree.visualItemRect(target)
    mime = _file_mime(["file-a"])
    move = QDragMoveEvent(
        target_row.bottomLeft() - QPoint(-8, 2),
        Qt.MoveAction | Qt.CopyAction,
        mime,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    move._mime_ref = mime

    assert widget.eventFilter(widget.tree.viewport(), move) is True
    assert move.isAccepted()
    assert move.dropAction() == Qt.MoveAction
    assert widget._file_tree_insert_line.isVisible()

    assert widget.eventFilter(widget.tree.viewport(), QDragLeaveEvent()) is True
    assert not widget._file_tree_insert_line.isVisible()


def test_short_channel_move_is_still_a_click(qapp, qtbot, monkeypatch):
    _FakeChannelDrag.last_mime = None
    monkeypatch.setattr("mf4_analyzer.ui.widgets.channel_tree.QDrag", _FakeChannelDrag)
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    qapp.processEvents()
    tree = widget.tree
    item = widget._file_items["file-a"].child(0)
    pos = tree.visualItemRect(item).center()
    tree.mousePressEvent(
        QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    )
    tree.mouseMoveEvent(
        QMouseEvent(QEvent.MouseMove, pos + QPoint(1, 1), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    )
    assert _FakeChannelDrag.last_mime is None


def test_same_fid_channel_drop_emits_order_request(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 280)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    parent = widget._file_items["file-a"]
    target = parent.child(0)
    pos = widget.tree.visualItemRect(target).topLeft() + QPoint(8, 2)
    mime = _channel_mime("file-a", "torque")
    event = QDropEvent(pos, Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    event._mime_ref = mime
    captured = []
    widget.channel_order_requested.connect(
        lambda fid, channel, target_ch, placement: captured.append(
            (fid, channel, target_ch, placement)
        )
    )
    widget._handle_channel_drop(event)
    assert event.dropAction() == Qt.MoveAction
    assert captured == [("file-a", "torque", "speed", "before")]


def test_cross_fid_and_search_channel_drop_have_no_side_effects(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(360, 320)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    _add_attached_file(widget, "file-b", _FakeFileData())
    widget.tree.expandAll()
    qapp.processEvents()

    target = widget._file_items["file-a"].child(0)
    pos = widget.tree.visualItemRect(target).center()
    with qtbot.assertNotEmitted(widget.channel_order_requested):
        mime = _channel_mime("file-b", "speed")
        event = QDropEvent(pos, Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event._mime_ref = mime
        widget._handle_channel_drop(event)
        assert not event.isAccepted()

        widget.search.setText("speed")
        mime = _channel_mime("file-a", "torque")
        event = QDropEvent(pos, Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event._mime_ref = mime
        widget._handle_channel_drop(event)
        assert not event.isAccepted()

        widget.search.clear()
        widget.set_projection_role("analysis_candidates")
        event = QDropEvent(pos, Qt.MoveAction | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        event._mime_ref = mime
        widget._handle_channel_drop(event)
        assert not event.isAccepted()


def test_project_channel_order_matches_checked_order(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _MultiChannelFileData())
    widget.set_checked_channels(
        [("file-a", "speed"), ("file-a", "torque"), ("file-a", "Rte_TAS_mTorsionBarTorque_xds16")]
    )
    widget.project_channel_order(
        "file-a", ["torque", "speed", "Rte_TAS_mTorsionBarTorque_xds16"]
    )
    assert [row[:2] for row in widget.get_checked_channels()] == [
        ("file-a", "torque"),
        ("file-a", "speed"),
        ("file-a", "Rte_TAS_mTorsionBarTorque_xds16"),
    ]


def test_refresh_file_keeps_saved_order_and_appends_new(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    _add_attached_file(widget, "file-a", _ReplaceableFileData(["speed", "torque"]))
    widget.set_checked_channels([("file-a", "speed"), ("file-a", "torque")])
    widget.refresh_file(
        "file-a",
        _ReplaceableFileData(["speed", "torque", "power"]),
        channel_order=("torque", "speed", "power"),
    )
    parent = widget._file_items["file-a"]
    assert [parent.child(idx).text(0) for idx in range(parent.childCount())] == [
        "torque",
        "speed",
        "power",
    ]


def test_grouped_source_raster_tooltip_accepts_dataframe():
    """HDF/CSV FileData.data is a DataFrame; ``value or []`` is ambiguous."""
    import pandas as pd

    from mf4_analyzer.ui.widgets.channel_tree import grouped_source_raster_tooltip

    class _HdfFile:
        data = pd.DataFrame({"Accel": [0.0, 1.0, 2.0]})
        source_metadata = {"source_kind": "hdf"}

    assert grouped_source_raster_tooltip(_HdfFile()) == "3 行"


def test_wwt_grouped_sources_use_zeit_labels_and_search_hits_pars(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(520, 360)
    widget.show()
    qtbot.waitExposed(widget)
    _add_attached_file(
        widget,
        "f0",
        _WwtGroupedFileData(
            0,
            ["ChanY", "SumAB"],
            {"SumAB": {"derived": True}},
        ),
    )
    _add_attached_file(
        widget,
        "f1",
        _WwtGroupedFileData(2, ["RackForce"]),
    )
    widget.tree.expandAll()
    QCoreApplication.processEvents()
    assert widget._raster_items["f0"].text(0) == "1.0 kHz · Zeit 0"
    assert widget._raster_items["f1"].text(0) == "1.0 kHz · Zeit 2"
    tip = widget._raster_items["f0"].toolTip(0)
    assert "Zeit 记录: 0" in tip
    assert "已注入 Pars 公式通道: 1" in tip
    widget.search.setText("sum")
    QCoreApplication.processEvents()
    raster = widget._raster_items["f0"]
    visible = [
        (raster.child(i).text(0), not raster.child(i).isHidden())
        for i in range(raster.childCount())
    ]
    assert visible == [("ChanY", False), ("SumAB", True)]
    assert ("f0", "SumAB") in widget._colors
