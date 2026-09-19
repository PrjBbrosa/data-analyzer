import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QTreeWidgetItem

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


# Every test attaches "f1" after add_file: rows of an unattached file are inert
# (get_checked_channels filters by _attached_file_ids, _is_item_attached gates
# check propagation), mirroring a TimeDomain View that has not been given the
# file yet. Without the attach these tests assert against an always-empty tree.


def test_set_checked_channels_roundtrip(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])

    widget.set_checked_channels([("f1", "spd")])

    assert _checked_pairs(widget) == [("f1", "spd")]
    assert widget._file_items["f1"].checkState(0) == Qt.Unchecked
    assert widget._file_items["f1"].child(0).checkState(0) == Qt.Unchecked
    assert widget._file_items["f1"].child(1).checkState(0) == Qt.Checked


def test_set_checked_channels_is_silent(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])
    fired = []
    widget.channels_changed.connect(lambda: fired.append(1))

    widget.set_checked_channels([("f1", "rpm")])

    assert fired == []


def test_set_hidden_channels_keeps_only_checked_known_channels(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])
    widget.set_checked_channels([("f1", "rpm")])

    widget.set_hidden_channels([
        ("f1", "rpm"),
        ("f1", "spd"),
        ("missing", "rpm"),
    ])

    assert widget.get_hidden_channels() == [("f1", "rpm")]
    assert widget.get_visible_checked_channels() == []


def test_unchecking_channel_clears_hidden_state(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])
    item = widget._file_items["f1"].child(0)
    widget.set_checked_channels([("f1", "rpm")])
    widget.set_hidden_channels([("f1", "rpm")])

    item.setCheckState(0, Qt.Unchecked)

    assert widget.get_hidden_channels() == []
    assert item.icon(2).isNull()


def test_set_channel_visible_rejects_unchecked_or_unknown_rows(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])

    assert widget.set_channel_visible("f1", "rpm", False) is False
    assert widget.set_channel_visible("missing", "rpm", False) is False
    assert widget.get_hidden_channels() == []


def test_color_roundtrip_refreshes_swatch_icon(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])
    channel_item = widget._file_items["f1"].child(0)
    before_key = channel_item.icon(0).cacheKey()

    widget.set_channel_colors({("f1", "rpm"): "#abcdef"})

    assert widget.get_channel_colors()[("f1", "rpm")] == "#abcdef"
    assert channel_item.icon(0).cacheKey() != before_key


def test_set_channel_colors_skips_unknown_channels(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])

    widget.set_channel_colors({
        ("f1", "rpm"): "#abcdef",
        ("missing", "ch"): "#000000",
        ("f1", "missing"): "#111111",
    })

    colors = widget.get_channel_colors()
    assert colors[("f1", "rpm")] == "#abcdef"
    assert ("missing", "ch") not in colors
    assert ("f1", "missing") not in colors


def test_restore_channel_color_overrides_does_not_keep_previous_view(qtbot):
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])
    widget.set_channel_colors({
        ("f1", "rpm"): "#ff0000",
        ("f1", "spd"): "#00ff00",
    })

    widget.restore_channel_color_overrides({("f1", "rpm"): "#0000ff"})

    colors = widget.get_channel_colors()
    assert colors[("f1", "rpm")] == "#0000ff"
    assert colors[("f1", "spd")] == "#222222"
    assert widget.get_channel_color_overrides() == {("f1", "rpm"): "#0000ff"}


def test_file_navigator_delegates_channel_state(qtbot):
    navigator = FileNavigator()
    qtbot.addWidget(navigator)
    navigator.add_file("f1", _FakeFileData())
    navigator.set_attached_file_ids(["f1"])

    navigator.set_checked_channels([("f1", "rpm")])
    navigator.set_channel_colors({("f1", "spd"): "#123456"})

    assert [(fid, ch) for fid, ch, _color in navigator.get_checked_channels()] == [
        ("f1", "rpm")
    ]
    assert navigator.get_channel_colors()[("f1", "spd")] == "#123456"


def test_file_navigator_invalidate_channel_filter_context_is_silent(qtbot):
    navigator = FileNavigator()
    qtbot.addWidget(navigator)
    navigator.add_file("f1", _FakeFileData())
    navigator.set_attached_file_ids(["f1"])
    navigator.set_checked_channels([("f1", "rpm")])
    navigator.channel_list.search.setText("rpm")
    fired = []
    navigator.channels_changed.connect(lambda: fired.append(1))
    navigator.visibility_changed.connect(lambda *_args: fired.append(2))
    generation = navigator.channel_list._filter_generation

    navigator.invalidate_channel_filter_context()

    assert navigator.channel_list._filter_snapshot is None
    assert navigator.channel_list._filter_generation == generation + 1
    assert navigator.channel_list.search.text() == "rpm"
    assert _checked_pairs(navigator) == [("f1", "rpm")]
    assert fired == []


def test_same_projection_skips_all_item_writes_including_record_rows(qtbot, monkeypatch):
    """Replaying one complete View projection must leave Qt item data alone."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    record_rows = [{
        "binding_id": "record-1",
        "owner_fid": "f1",
        "record_index": 3,
        "name": "raw", "unit": "Nm", "color": "#abcdef", "visible": True,
    }]
    with widget.channel_projection_batch():
        widget.set_attached_file_ids(["f1"])
        widget.set_channel_colors({("f1", "rpm"): "#123456"})
        widget.set_checked_channels([("f1", "rpm")])
        widget.set_hidden_channels([("f1", "rpm")])
        widget.set_record_curve_rows("view-1", record_rows)

    calls = []
    for name in (
        "setCheckState", "setHidden", "setIcon", "setText", "setToolTip", "setData",
    ):
        original = getattr(QTreeWidgetItem, name)

        def _counted(item, *args, _name=name, _original=original):
            calls.append(_name)
            return _original(item, *args)

        monkeypatch.setattr(QTreeWidgetItem, name, _counted)

    with widget.channel_projection_batch():
        widget.set_attached_file_ids(["f1"])
        widget.set_channel_colors({("f1", "rpm"): "#123456"})
        widget.set_checked_channels([("f1", "rpm")])
        widget.set_hidden_channels([("f1", "rpm")])
        widget.set_record_curve_rows("view-1", record_rows)

    assert calls == []


def test_nested_projection_batch_settles_once_after_exception(qtbot, monkeypatch):
    """An exception does not strand a nested projection or replay its settle."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.add_file("f1", _FakeFileData())
    widget.set_attached_file_ids(["f1"])
    settled = []
    monkeypatch.setattr(
        widget, "_apply_filters", lambda *args, **kwargs: settled.append("filter"),
    )
    monkeypatch.setattr(
        widget, "_refresh_visibility_icons",
        lambda: settled.append("visibility"),
    )
    monkeypatch.setattr(
        widget, "_sync_empty_state", lambda: settled.append("empty"),
    )
    monkeypatch.setattr(
        widget, "_update_config_context", lambda: settled.append("context"),
    )

    with pytest.raises(RuntimeError, match="projection failure"):
        with widget.channel_projection_batch():
            widget.set_checked_channels([("f1", "rpm")])
            with widget.channel_projection_batch():
                widget.set_hidden_channels([("f1", "rpm")])
                raise RuntimeError("projection failure")

    assert settled == ["visibility", "filter", "empty"]


def test_tree_rebuild_does_not_preserve_a_stale_projection_noop(qtbot):
    """A rebuilt row receives the same View facts instead of a cached no-op."""
    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    data = _FakeFileData()
    widget.add_file("f1", data)
    with widget.channel_projection_batch():
        widget.set_attached_file_ids(["f1"])
        widget.set_channel_colors({("f1", "rpm"): "#abcdef"})
        widget.set_checked_channels([("f1", "rpm")])

    old_item = widget._file_items["f1"].child(0)
    widget._remove_file_tree_item("f1")
    widget.add_file("f1", data)
    rebuilt_item = widget._file_items["f1"].child(0)
    assert rebuilt_item is not old_item

    with widget.channel_projection_batch():
        widget.set_attached_file_ids(["f1"])
        widget.set_channel_colors({("f1", "rpm"): "#abcdef"})
        widget.set_checked_channels([("f1", "rpm")])

    assert rebuilt_item.checkState(0) == Qt.Checked
    assert widget.get_channel_colors()[("f1", "rpm")] == "#abcdef"
