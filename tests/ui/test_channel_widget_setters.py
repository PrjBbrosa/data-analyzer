from PyQt5.QtCore import Qt

from mf4_analyzer.ui.file_navigator import FileNavigator
from mf4_analyzer.ui.widgets import MultiFileChannelWidget


class _FakeFileData:
    data = [0, 1, 2, 3, 4]
    time_array = [0, 1, 2, 3, 4]
    fs = 1.0
    short_name = "fake"

    def get_signal_channels(self):
        return ["rpm", "spd"]

    def get_color_palette(self):
        return ["#111111", "#222222"]


def _checked_pairs(widget):
    return [(fid, channel) for fid, channel, _color in widget.get_checked_channels()]


def test_set_checked_channels_roundtrip(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())

    widget.set_checked_channels([("f1", "spd")])

    assert _checked_pairs(widget) == [("f1", "spd")]
    assert widget._file_items["f1"].checkState(0) == Qt.Unchecked
    assert widget._file_items["f1"].child(0).checkState(0) == Qt.Unchecked
    assert widget._file_items["f1"].child(1).checkState(0) == Qt.Checked


def test_set_checked_channels_is_silent(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    fired = []
    widget.channels_changed.connect(lambda: fired.append(1))

    widget.set_checked_channels([("f1", "rpm")])

    assert fired == []


def test_color_roundtrip_refreshes_swatch_icon(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    channel_item = widget._file_items["f1"].child(0)
    before_key = channel_item.icon(0).cacheKey()

    widget.set_channel_colors({("f1", "rpm"): "#abcdef"})

    assert widget.get_channel_colors()[("f1", "rpm")] == "#abcdef"
    assert channel_item.icon(0).cacheKey() != before_key


def test_set_channel_colors_skips_unknown_channels(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())

    widget.set_channel_colors({
        ("f1", "rpm"): "#abcdef",
        ("missing", "ch"): "#000000",
        ("f1", "missing"): "#111111",
    })

    colors = widget.get_channel_colors()
    assert colors[("f1", "rpm")] == "#abcdef"
    assert ("missing", "ch") not in colors
    assert ("f1", "missing") not in colors


def test_file_navigator_delegates_channel_state(qtbot):
    navigator = FileNavigator()
    qtbot.addWidget(navigator)
    navigator.add_file("f1", _FakeFileData())

    navigator.set_checked_channels([("f1", "rpm")])
    navigator.set_channel_colors({("f1", "spd"): "#123456"})

    assert [(fid, ch) for fid, ch, _color in navigator.get_checked_channels()] == [
        ("f1", "rpm")
    ]
    assert navigator.get_channel_colors()[("f1", "spd")] == "#123456"
