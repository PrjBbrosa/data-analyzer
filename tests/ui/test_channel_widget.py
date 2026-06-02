from PyQt5.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QPushButton

from mf4_analyzer.ui.widgets import MultiFileChannelWidget


class _FakeFileData:
    data = [1, 2, 3]

    def get_signal_channels(self):
        return ["speed"]

    def get_color_palette(self):
        return ["#1769e0"]


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
    widget.add_file("file-a", _FakeFileData())
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
    # All / None / Inv were localised to two-character Chinese labels.
    assert {"全选", "全不", "反选"} <= labels
    # 编辑通道 moved down from the top toolbar onto the channel-action row.
    assert "编辑通道" in labels


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
    widget.add_file("file-a", _FakeFileData())
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


def test_edit_channels_button_enables_with_file_and_emits(qapp, qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    # Disabled until a file is loaded — editing channels needs a file.
    assert not widget.btn_edit.isEnabled()

    widget.add_file("file-a", _FakeFileData())
    assert widget.btn_edit.isEnabled()

    with qtbot.waitSignal(widget.channel_editor_requested, timeout=200):
        widget.btn_edit.click()

    widget.remove_file("file-a")
    assert not widget.btn_edit.isEnabled()
