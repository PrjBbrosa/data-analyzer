import json
from pathlib import Path

from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

from mf4_analyzer.ui.file_navigator import FileNavigator, _FileRow


def test_file_navigator_constructs(qapp):
    nav = FileNavigator()
    assert nav.channel_list is not None


def test_file_navigator_signals_exist(qapp):
    nav = FileNavigator()
    assert hasattr(nav, 'file_activated')
    assert hasattr(nav, 'file_close_requested')
    assert hasattr(nav, 'close_all_requested')
    assert hasattr(nav, 'channels_changed')
    assert hasattr(nav, 'visibility_changed')


class FakeFd:
    def __init__(self, filename="sample.csv", short_name="sample", rows=100, fs=1000.0, duration=5.0, filepath=None, label_suffix=""):
        self.filename = filename
        self.short_name = short_name
        self.filepath = Path(filepath) if filepath is not None else None
        self.label_suffix = label_suffix
        self.fs = fs
        self._rows = rows
        self._dur = duration
    @property
    def data(self):
        class _L:
            def __init__(self, n): self._n = n
            def __len__(self): return self._n
        return _L(self._rows)
    @property
    def time_array(self):
        import numpy as np
        return np.linspace(0, self._dur, self._rows)
    def get_signal_channels(self): return ["speed", "torque"]
    def get_color_palette(self): return ["#1f77b4", "#ff7f0e"]
    @property
    def channel_units(self): return {}


def _add_attached(nav, fid, fd):
    nav.add_file(fid, fd)
    nav.set_attached_file_ids([*nav.get_attached_file_ids(), fid])


def test_file_row_added(qapp):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    assert nav.file_list_count() == 1


def test_channel_visibility_delegates_and_signal_bubbles(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    nav.set_checked_channels([("f0", "speed")])

    nav.set_hidden_channels([("f0", "speed")])

    assert nav.get_hidden_channels() == [("f0", "speed")]
    assert nav.get_visible_checked_channels() == []
    with qtbot.waitSignal(nav.visibility_changed, timeout=200) as blocker:
        assert nav.set_channel_visible("f0", "speed", True)
    assert blocker.args == ["f0", "speed", True]


def test_time_visibility_toggle_keeps_file_remove_column_available(qapp):
    nav = FileNavigator()
    _add_attached(nav, "f0", FakeFd())
    tree = nav.channel_list.tree
    parent = nav.channel_list._file_items["f0"]
    channel = parent.child(0)
    nav.set_checked_channels([("f0", "speed")])

    nav.set_time_visibility_available(False)
    assert not tree.isColumnHidden(2)
    assert channel.icon(2).isNull()

    nav.set_time_visibility_available(True)
    assert not tree.isColumnHidden(2)
    assert not channel.icon(2).isNull()


def test_channel_tree_file_parent_uses_full_filename_stem(qapp):
    nav = FileNavigator()
    full = "PK2C_VehSpd_0_TAS_0123456789abcdef.csv"
    nav.add_file("f0", FakeFd(filename=full, short_name="PK2C_VehSpd_0_TAS"))

    item = nav.channel_list._file_items["f0"]

    assert item.text(0) == "PK2C_VehSpd_0_TAS_0123456789abcdef"
    assert item.toolTip(0) == full


def test_file_row_close_emits(qapp, qtbot):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    with qtbot.waitSignal(nav.file_close_requested, timeout=200) as blocker:
        nav._request_close("f0")
    assert blocker.args == ["f0"]


def test_file_row_click_emits_activated(qapp, qtbot):
    nav = FileNavigator()
    # Initial add_file auto-activates f0 (emits). Add a second file so that
    # switching back to f0 produces an observable signal.
    nav.add_file("f0", FakeFd(short_name="one"))
    nav.add_file("f1", FakeFd(short_name="two"))
    with qtbot.waitSignal(nav.file_activated, timeout=200) as blocker:
        nav._activate("f0")
    assert blocker.args == ["f0"]


from unittest.mock import patch
from PyQt5.QtCore import Qt


def test_channel_search_filters(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    # "speed" matches channel named "speed"; "xyz" matches nothing
    nav.channel_list.search.setText("xyz")
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).isHidden()
    nav.channel_list.search.setText("speed")
    visible = [not fi.child(i).isHidden() for i in range(fi.childCount())]
    assert any(visible)


def test_channel_all_button_checks(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    nav.channel_list._all()
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).checkState(0) == Qt.Checked


def test_channel_none_button_clears(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    nav.channel_list._all()
    nav.channel_list._none()
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).checkState(0) == Qt.Unchecked


def test_channel_selected_button_filters_to_checked(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    fi = nav.channel_list._file_items["f0"]
    fi.child(0).setCheckState(0, Qt.Checked)
    nav.channel_list.btn_selected_only.click()
    assert nav.channel_list.btn_selected_only.isChecked()
    assert not fi.child(0).isHidden()
    assert fi.child(1).isHidden()


def test_selected_channel_keeps_the_same_checkbox_origin(qapp, qtbot):
    """Channel-leaf controls keep one anchor in selected and normal rows."""
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    nav.resize(520, 420)
    nav.show()
    qapp.processEvents()

    tree = nav.channel_list.tree
    parent = nav.channel_list._file_items["f0"]
    selected = parent.child(0)
    normal = parent.child(1)
    tree.setCurrentItem(selected)
    selected.setSelected(True)
    qapp.processEvents()

    selected_index = tree.indexFromItem(selected, 0)
    normal_index = tree.indexFromItem(normal, 0)
    delegate = tree.itemDelegate()
    selected_check, selected_swatch, selected_text = delegate.channel_geometry(
        tree.visualRect(selected_index)
    )
    normal_check, normal_swatch, normal_text = delegate.channel_geometry(
        tree.visualRect(normal_index)
    )

    # These anchors used to be delegated to the macOS native tree style,
    # which shifted only the selected checkbox.  Keep all three column-0
    # primitives explicitly invariant now.
    assert selected_check.x() == normal_check.x()
    assert selected_swatch.x() == normal_swatch.x()
    assert selected_text.x() == normal_text.x()
    assert tree._check_hit_rect(selected, selected_index).left() == (
        selected_check.left() - tree.HIT_PAD
    )

    selected_eye_index = tree.indexFromItem(selected, 2)
    normal_eye_index = tree.indexFromItem(normal, 2)
    assert delegate._is_channel(selected_eye_index)
    selected_eye = delegate.eye_geometry(tree.visualRect(selected_eye_index))
    normal_eye = delegate.eye_geometry(tree.visualRect(normal_eye_index))
    assert selected_eye.center().x() == tree.visualRect(selected_eye_index).center().x()
    assert normal_eye.center().x() == tree.visualRect(normal_eye_index).center().x()

    # The visual anchor and click anchor must be the same rect; a delegate
    # fix must not make the manually painted checkbox decorative only.
    qtbot.mouseClick(tree.viewport(), Qt.LeftButton, pos=selected_check.center())
    qapp.processEvents()
    assert selected.checkState(0) == Qt.Checked


def test_file_detach_icon_is_centered_in_display_column(qapp, qtbot):
    """The file-row close icon shares the display-column center with eyes."""
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    nav.resize(520, 420)
    nav.show()
    qapp.processEvents()

    channel_list = nav.channel_list
    tree = channel_list.tree
    parent = channel_list._file_items["f0"]
    channel_list._on_item_entered(parent, 2)
    qapp.processEvents()

    cell = tree.visualRect(tree.indexFromItem(parent, 2))
    image = tree.viewport().grab().toImage()
    red_x = []
    for y in range(cell.top(), cell.bottom() + 1):
        for x in range(cell.left(), cell.right() + 1):
            pixel = image.pixelColor(x, y)
            if pixel.red() >= 180 and pixel.green() <= 120 and pixel.blue() <= 120:
                red_x.append(x)

    assert red_x, "file detach icon did not render"
    painted_center_x = (min(red_x) + max(red_x)) / 2.0
    assert abs(painted_center_x - cell.center().x()) <= 1.0


def test_navigator_tool_buttons_outer_size_compact(qapp):
    """fix-4 — file-navigator close + kebab buttons must shrink their
    outer chrome to <=24px on both axes (icon size kept at 16px)."""
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    row = nav._rows["f0"]
    # Close button on a file row.
    assert row._btn_close.maximumWidth() <= 24, (
        f"_btn_close maxWidth={row._btn_close.maximumWidth()} > 24"
    )
    assert row._btn_close.maximumHeight() <= 24, (
        f"_btn_close maxHeight={row._btn_close.maximumHeight()} > 24"
    )
    # Kebab button in the file-area header.
    assert nav._btn_kebab.maximumWidth() <= 24, (
        f"_btn_kebab maxWidth={nav._btn_kebab.maximumWidth()} > 24"
    )
    assert nav._btn_kebab.maximumHeight() <= 24, (
        f"_btn_kebab maxHeight={nav._btn_kebab.maximumHeight()} > 24"
    )


def test_channel_over_threshold_warns(qapp, qtbot, monkeypatch):
    # Craft a FakeFd with many channels to trigger the >8 warn.
    class WideFd(FakeFd):
        def get_signal_channels(self):
            return [f"ch{i}" for i in range(20)]
        def get_color_palette(self):
            return ["#000"] * 20
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", WideFd())
    with patch('mf4_analyzer.ui.widgets.QMessageBox.question',
               return_value=False) as q:
        nav.channel_list._all()
    assert q.called


def test_channel_tree_projects_only_attached_files(qapp):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd(short_name="one"))
    nav.add_file("f1", FakeFd(short_name="two"))

    nav.set_attached_file_ids(["f1"])

    assert nav.get_attached_file_ids() == ["f1"]
    assert nav.channel_list._file_items["f0"].isHidden()
    assert not nav.channel_list._file_items["f1"].isHidden()


def test_explicit_empty_attachment_shows_real_empty_state(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    nav.show()

    nav.set_attached_file_ids([])

    assert nav.channel_list.empty_state.isVisible()
    assert not nav.channel_list.search.isEnabled()
    assert not nav.channel_list.btn_selected_only.isEnabled()
    assert not nav.channel_list.config_bar.btn_apply.isEnabled()


def test_attachment_projection_does_not_emit_channel_change(qapp, qtbot):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())

    with qtbot.assertNotEmitted(nav.channels_changed):
        nav.set_attached_file_ids(["f0"])


def test_group_projection_hides_source_when_no_raster_is_attached(qapp):
    nav = FileNavigator()
    source = "C:/data/grouped.hdf"
    nav.add_file(
        "f0",
        FakeFd(filepath=source, label_suffix="1 kHz", fs=1000.0),
    )
    nav.add_file(
        "f1",
        FakeFd(filepath=source, label_suffix="2 kHz", fs=2000.0),
    )

    nav.set_attached_file_ids(["f1"])

    parent = nav.channel_list._source_items[str(Path(source))]
    assert not parent.isHidden()
    assert nav.channel_list._raster_items["f0"].isHidden()
    assert not nav.channel_list._raster_items["f1"].isHidden()
    nav.set_attached_file_ids([])
    assert parent.isHidden()


def test_detach_parent_bubbles_all_attached_group_fids_once(qapp, qtbot):
    nav = FileNavigator()
    source = "C:/data/grouped.hdf"
    nav.add_file("f0", FakeFd(filepath=source, label_suffix="1 kHz"))
    nav.add_file("f1", FakeFd(filepath=source, label_suffix="2 kHz"))
    nav.set_attached_file_ids(["f0", "f1"])
    parent = nav.channel_list._source_items[str(Path(source))]

    with qtbot.waitSignal(nav.files_detach_requested, timeout=200) as emitted:
        nav.channel_list._on_item_clicked(parent, 2)

    assert emitted.args == [("f0", "f1"), parent.text(0)]


def test_group_parent_checkbox_changes_only_attached_rasters(qapp):
    nav = FileNavigator()
    source = "C:/data/grouped.hdf"
    nav.add_file("f0", FakeFd(filepath=source, label_suffix="1 kHz"))
    nav.add_file("f1", FakeFd(filepath=source, label_suffix="2 kHz"))
    nav.set_attached_file_ids(["f1"])
    parent = nav.channel_list._source_items[str(Path(source))]

    parent.setCheckState(0, Qt.Checked)

    assert all(
        nav.channel_list._raster_items["f0"].child(idx).checkState(0)
        == Qt.Unchecked
        for idx in range(nav.channel_list._raster_items["f0"].childCount())
    )
    assert all(
        nav.channel_list._raster_items["f1"].child(idx).checkState(0)
        == Qt.Checked
        for idx in range(nav.channel_list._raster_items["f1"].childCount())
    )


def test_parent_detach_hover_does_not_clear_checked_channels(qapp, qtbot):
    nav = FileNavigator()
    source = "C:/data/grouped.hdf"
    nav.add_file("f0", FakeFd(filepath=source, label_suffix="1 kHz"))
    nav.set_attached_file_ids(["f0"])
    nav.set_checked_channels([("f0", "speed")])
    parent = nav.channel_list._source_items[str(Path(source))]

    with qtbot.assertNotEmitted(nav.channels_changed):
        nav.channel_list._on_item_entered(parent, 2)

    assert [(fid, channel) for fid, channel, _color in nav.get_checked_channels()] == [
        ("f0", "speed")
    ]


def test_file_row_drag_payload_contains_every_group_fid(qapp):
    row = _FileRow("f0", FakeFd())
    row.add_fid("f1", FakeFd())

    mime = row._build_drag_mime()

    assert json.loads(bytes(mime.data(row.MIME_TYPE))) == ["f0", "f1"]


def test_auto_attach_toggle_is_compact_and_emits(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)

    assert nav.btn_auto_attach.maximumWidth() <= 24
    assert nav.auto_attach_enabled() is True
    enabled_icon_key = nav.btn_auto_attach.icon().cacheKey()
    with qtbot.waitSignal(nav.auto_attach_changed, timeout=200) as emitted:
        nav.btn_auto_attach.click()

    assert emitted.args == [False]
    assert nav.auto_attach_enabled() is False
    assert nav.btn_auto_attach.icon().cacheKey() != enabled_icon_key


def test_internal_file_drop_emits_known_fids_once(qapp, qtbot):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    nav.add_file("f1", FakeFd())
    assert nav.channel_list.acceptDrops()

    mime = QMimeData()
    mime.setData(
        _FileRow.MIME_TYPE,
        json.dumps(["f0", "f1", "f0", "missing"]).encode("utf-8"),
    )
    drag_event = QDragEnterEvent(
        QPoint(4, 4), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    nav.channel_list.dragEnterEvent(drag_event)

    assert drag_event.isAccepted()
    assert nav.channel_list.property("dropActive") is True

    event = QDropEvent(
        QPointF(4, 4), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )

    with qtbot.waitSignal(nav.files_attach_requested, timeout=200) as emitted:
        nav.channel_list.dropEvent(event)

    assert emitted.args == [("f0", "f1")]
    assert event.isAccepted()
    assert nav.channel_list.property("dropActive") is False


def test_malformed_internal_file_drop_is_ignored(qapp, qtbot):
    nav = FileNavigator()
    mime = QMimeData()
    mime.setData(_FileRow.MIME_TYPE, b"not-json")
    event = QDropEvent(
        QPointF(4, 4), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )

    with qtbot.assertNotEmitted(nav.files_attach_requested):
        nav.channel_list.dropEvent(event)

    assert not event.isAccepted()
