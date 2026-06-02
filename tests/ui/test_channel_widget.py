from PyQt5.QtCore import QCoreApplication, Qt

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
