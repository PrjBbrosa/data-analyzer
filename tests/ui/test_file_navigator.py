import json
from pathlib import Path

from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt5.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PyQt5.QtWidgets import QToolButton

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
    assert hasattr(nav, 'file_order_requested')


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


def test_group_close_emits_all_fids_once(qapp, qtbot):
    nav = FileNavigator()
    source = "C:/data/grouped.hdf"
    nav.add_file("f0", FakeFd(filepath=source, label_suffix="1 kHz"))
    nav.add_file("f1", FakeFd(filepath=source, label_suffix="2 kHz"))
    rows_key = nav._fid_to_key["f0"]
    with qtbot.waitSignal(nav.file_group_close_requested, timeout=200) as blocker:
        nav._request_close_group(rows_key)
    assert set(blocker.args[0]) == {"f0", "f1"}
    with qtbot.assertNotEmitted(nav.file_close_requested):
        nav._request_close_group(rows_key)


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
    from mf4_analyzer.ui_kit import load_stylesheet

    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        nav = FileNavigator()
        qtbot.addWidget(nav)
        _add_attached(nav, "f0", FakeFd())
        nav.resize(520, 420)
        nav.show()
        qtbot.waitExposed(nav)
        tree = nav.channel_list.tree
        tree.expandAll()
        qapp.processEvents()

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
        assert selected_check.width() == normal_check.width() == 18
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

        # Painted checkbox borders must share the same left edge — geometry
        # helpers alone previously stayed green while macOS QSS still nudged
        # the visible box on the selected row. Unselected AA borders sit on
        # white and read lighter than selected ones on the blue tint.
        image = tree.viewport().grab().toImage()

        def _checkbox_border_left(check_rect):
            xs = []
            for y in range(check_rect.top(), check_rect.bottom() + 1):
                for x in range(check_rect.left() - 1, check_rect.right() + 2):
                    pixel = image.pixelColor(x, y)
                    if pixel.lightness() < 235 and pixel.lightness() > 160:
                        xs.append(x)
            assert xs, "checkbox border missing in rendered viewport"
            return min(xs)

        assert _checkbox_border_left(selected_check) == _checkbox_border_left(
            normal_check
        )

        # The visual anchor and click anchor must be the same rect; a delegate
        # fix must not make the manually painted checkbox decorative only.
        qtbot.mouseClick(tree.viewport(), Qt.LeftButton, pos=selected_check.center())
        qapp.processEvents()
        assert selected.checkState(0) == Qt.Checked
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


def test_pts_column_stays_right_anchored_when_selection_changes(qapp, qtbot):
    """Pts numbers must not jump sideways when a neighbouring row is selected."""
    from mf4_analyzer.ui_kit import load_stylesheet
    from PyQt5.QtWidgets import QHeaderView

    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        nav = FileNavigator()
        qtbot.addWidget(nav)
        _add_attached(nav, "f0", FakeFd())
        nav.resize(520, 420)
        nav.show()
        qtbot.waitExposed(nav)
        channel_list = nav.channel_list
        tree = channel_list.tree
        tree.expandAll()
        qapp.processEvents()

        header = tree.header()
        assert header.sectionResizeMode(1) == QHeaderView.Fixed
        width_before = header.sectionSize(1)
        assert width_before >= 52

        parent = channel_list._file_items["f0"]
        first = parent.child(0)
        second = parent.child(1)
        first.setText(1, "8140")
        second.setText(1, "32053")
        qapp.processEvents()

        delegate = tree.itemDelegate()

        def _pts_anchor_and_ink(item):
            cell = tree.visualRect(tree.indexFromItem(item, 1))
            assert cell.isValid() and cell.width() > 0, (
                f"Pts cell missing for {item.text(0)}"
            )
            band = delegate.pts_geometry(cell)
            image = tree.viewport().grab().toImage()
            xs = []
            for y in range(band.top() + 2, band.bottom() - 1):
                for x in range(band.left(), band.right() + 1):
                    if image.pixelColor(x, y).lightness() < 200:
                        xs.append(x)
            assert xs, f"Pts ink missing for {item.text(0)}"
            return max(xs), band.right()

        tree.clearSelection()
        qapp.processEvents()
        first_right, first_anchor = _pts_anchor_and_ink(first)
        second_right, second_anchor = _pts_anchor_and_ink(second)
        assert first_anchor == second_anchor

        tree.setCurrentItem(second)
        second.setSelected(True)
        qapp.processEvents()
        assert header.sectionSize(1) == width_before

        first_right_sel, first_anchor_sel = _pts_anchor_and_ink(first)
        second_right_sel, second_anchor_sel = _pts_anchor_and_ink(second)
        assert first_anchor_sel == first_anchor == second_anchor_sel
        assert abs(first_right_sel - first_right) <= 1
        assert abs(second_right_sel - second_right) <= 1
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


def test_projection_roles_share_channel_leaf_anchors(qapp, qtbot):
    """time / fft_sources / analysis_candidates keep one column-0 layout."""
    nav = FileNavigator()
    qtbot.addWidget(nav)
    _add_attached(nav, "f0", FakeFd())
    nav.resize(520, 420)
    nav.show()
    qtbot.waitExposed(nav)
    tree = nav.channel_list.tree
    tree.expandAll()
    qapp.processEvents()

    parent = nav.channel_list._file_items["f0"]
    item = parent.child(0)
    tree.setCurrentItem(item)
    item.setSelected(True)
    qapp.processEvents()
    delegate = tree.itemDelegate()

    anchors = {}
    for role in ("time", "fft_sources", "analysis_candidates"):
        nav.set_projection_role(role)
        qapp.processEvents()
        cell = tree.visualRect(tree.indexFromItem(item, 0))
        check, swatch, text = delegate.channel_geometry(
            cell, with_checkbox=(role != "analysis_candidates"),
        )
        anchors[role] = (check.x() if check.isValid() else None, swatch.x(), text.x())

    assert anchors["time"] == anchors["fft_sources"]
    # Candidate mode drops the checkbox but keeps swatch/text on one band.
    assert anchors["analysis_candidates"][0] is None


def test_time_mode_file_row_paints_checkbox_like_channels(qapp, qtbot):
    """File parents must keep a visible checkbox in time/fft_sources roles."""
    from mf4_analyzer.ui_kit import load_stylesheet

    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        nav = FileNavigator()
        qtbot.addWidget(nav)
        _add_attached(nav, "f0", FakeFd(filename="tiaodamping.csv", short_name="tiaodamping"))
        nav.resize(520, 420)
        nav.show()
        qtbot.waitExposed(nav)
        tree = nav.channel_list.tree
        tree.expandAll()
        qapp.processEvents()

        file_item = nav.channel_list._file_items["f0"]
        channel_item = file_item.child(0)
        delegate = tree.itemDelegate()

        def _checkbox_ink(item):
            idx = tree.indexFromItem(item, 0)
            cell = tree.visualRect(idx)
            data = item.data(0, Qt.UserRole)
            if data and data[0] == "channel":
                box = delegate.channel_geometry(cell)[0]
            else:
                box = delegate.parent_geometry(cell)[0]
            image = tree.viewport().grab().toImage()
            return sum(
                1
                for y in range(box.top(), box.bottom() + 1)
                for x in range(box.left(), box.right() + 1)
                if image.pixelColor(x, y).lightness() < 235
            ), box.left()

        nav.set_projection_role("time")
        qapp.processEvents()
        file_ink, file_left = _checkbox_ink(file_item)
        channel_ink, channel_left = _checkbox_ink(channel_item)
        assert file_ink > 20, "time-mode file row lost its checkbox"
        assert channel_ink > 20, "time-mode channel row lost its checkbox"
        assert file_left < channel_left

        nav.set_projection_role("analysis_candidates")
        qapp.processEvents()
        assert not (file_item.flags() & Qt.ItemIsUserCheckable)
        assert not (channel_item.flags() & Qt.ItemIsUserCheckable)
        ch_cell = tree.visualRect(tree.indexFromItem(channel_item, 0))
        check, swatch, _text = delegate.channel_geometry(
            ch_cell, with_checkbox=False,
        )
        assert check.isNull() or check.width() == 0
        assert swatch.left() == ch_cell.left() + delegate.LEFT_INSET
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


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


def test_follow_link_menu_is_compact_and_emits_prefs(qapp, qtbot):
    from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs

    nav = FileNavigator()
    qtbot.addWidget(nav)

    assert nav.btn_auto_attach.maximumWidth() <= 24
    # Icon-only chrome like the kebab: no InstantPopup/setMenu triangle.
    assert nav.btn_auto_attach.menu() is None
    assert nav.btn_auto_attach.popupMode() != QToolButton.InstantPopup
    assert nav._follow_menu is not None
    assert nav.auto_attach_enabled() is True
    assert nav.follow_prefs() == FollowPrefs(True, False, False)
    enabled_icon_key = nav.btn_auto_attach.icon().cacheKey()
    assert "已启用 1 项" in nav.btn_auto_attach.toolTip()
    assert nav.btn_auto_attach.property("active") == "true"
    assert not nav.btn_auto_attach.isCheckable()

    with qtbot.waitSignal(nav.follow_prefs_changed, timeout=200) as emitted:
        nav._act_attach_on_load.setChecked(False)

    assert emitted.args[0] == FollowPrefs(False, False, False)
    assert nav.auto_attach_enabled() is False
    assert nav.btn_auto_attach.icon().cacheKey() != enabled_icon_key
    assert nav.btn_auto_attach.toolTip() == "未启用文件范围跟随"
    assert nav.btn_auto_attach.property("active") == "false"

    with qtbot.waitSignal(nav.follow_prefs_changed, timeout=200) as emitted:
        nav._act_inherit_on_new_view.setChecked(True)
    assert emitted.args[0].inherit_on_new_view is True
    assert "已启用 1 项" in nav.btn_auto_attach.toolTip()
    assert nav.btn_auto_attach.property("active") == "true"

    nav.set_follow_prefs(FollowPrefs(True, True, True))
    assert nav.follow_prefs().enabled_count() == 3
    assert "已启用 3 项" in nav.btn_auto_attach.toolTip()


def test_follow_link_active_chrome_survives_hover_and_idle_stays_plain(qapp, qtbot):
    """Active follow link keeps its wash; idle never flashes a pressed wash."""
    from mf4_analyzer.ui_kit import load_stylesheet
    from mf4_analyzer.ui.main_window.file_scope_follow import FollowPrefs
    from PyQt5.QtGui import QHoverEvent
    from PyQt5.QtCore import QEvent

    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        load_stylesheet(qapp)
        nav = FileNavigator()
        qtbot.addWidget(nav)
        nav.resize(320, 240)
        nav.show()
        qtbot.waitExposed(nav)
        btn = nav.btn_auto_attach

        def _chrome_pixel():
            """Sample near a corner so we read the button fill, not the glyph."""
            image = btn.grab().toImage()
            return image.pixelColor(2, 2)

        def _is_wash(color):
            # Accent wash is a light blue (#eef4ff / #edf5ff family). Transparent
            # idle reads near-white / parent fill with almost no blue bias.
            return color.blue() >= color.red() + 10 and color.green() > color.red()

        nav.set_follow_prefs(FollowPrefs(True, False, False))
        qapp.processEvents()
        assert btn.property("active") == "true"
        active_idle = _chrome_pixel()
        assert _is_wash(active_idle), (
            f"active follow link should keep a wash, got {active_idle.name()}"
        )

        # Hover must not erase the active tint (generic role=icon:hover used to).
        enter = QHoverEvent(
            QEvent.HoverEnter, btn.rect().center(), btn.rect().center(),
        )
        qapp.sendEvent(btn, enter)
        qapp.processEvents()
        active_hover = _chrome_pixel()
        assert _is_wash(active_hover), (
            f"hover cleared active follow wash to {active_hover.name()}"
        )

        nav.set_follow_prefs(FollowPrefs(False, False, False))
        qapp.processEvents()
        assert btn.property("active") == "false"
        idle = _chrome_pixel()
        assert not _is_wash(idle), (
            f"idle follow link should be plain, got {idle.name()}"
        )

        # Pressed/hover on the all-off icon must stay plain — a wash looked
        # like "enabled" and contradicted the link-off glyph.
        press = QHoverEvent(
            QEvent.HoverMove, btn.rect().center(), btn.rect().center(),
        )
        qapp.sendEvent(btn, press)
        btn.setDown(True)
        qapp.processEvents()
        idle_pressed = _chrome_pixel()
        btn.setDown(False)
        qapp.processEvents()
        assert not _is_wash(idle_pressed), (
            f"idle follow press flashed wash {idle_pressed.name()}"
        )
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)


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


def _file_mime(fids):
    mime = QMimeData()
    mime.setData(_FileRow.MIME_TYPE, json.dumps(list(fids)).encode("utf-8"))
    return mime


def _shown_file_nav(qtbot, *entries):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    for fid, fd in entries:
        nav.add_file(fid, fd)
    nav.resize(320, 480)
    nav.show()
    qtbot.waitExposed(nav)
    nav._file_holder.adjustSize()
    return nav


def _pos_on_row(row, *, after=False):
    geo = row.geometry()
    y = geo.bottom() - 1 if after else geo.top() + 1
    return QPoint(max(4, geo.center().x()), y)


def _file_list_drop(nav, mime, pos, action=Qt.MoveAction):
    event = QDropEvent(
        pos, action | Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    event._mime_ref = mime
    nav._handle_file_list_drop(event, nav._file_holder)
    return event


def test_file_list_drop_moves_first_card_to_end(qapp, qtbot):
    nav = _shown_file_nav(
        qtbot,
        ("f0", FakeFd(filename="a.csv")),
        ("f1", FakeFd(filename="b.csv")),
        ("f2", FakeFd(filename="c.csv")),
    )
    mime = _file_mime(["f0"])
    captured = []
    nav.file_order_requested.connect(
        lambda fids, target, placement: captured.append(
            (list(fids), list(target), placement)
        )
    )

    with qtbot.assertNotEmitted(nav.files_attach_requested):
        with qtbot.assertNotEmitted(nav.file_close_requested):
            event = _file_list_drop(
                nav, mime, _pos_on_row(nav._ordered_file_rows()[-1], after=True)
            )

    assert event.isAccepted()
    assert event.dropAction() == Qt.MoveAction
    assert captured == [(["f0"], ["f2"], "after")]
    nav.project_file_order(["f1", "f2", "f0"])
    assert nav.ordered_file_fids() == ["f1", "f2", "f0"]
    assert [
        nav.channel_list.tree.topLevelItem(idx).data(0, Qt.UserRole)[1]
        for idx in range(nav.channel_list.tree.topLevelItemCount())
    ] == ["f1", "f2", "f0"]


def test_file_list_drop_moves_last_card_to_front(qapp, qtbot):
    nav = _shown_file_nav(
        qtbot,
        ("f0", FakeFd(filename="a.csv")),
        ("f1", FakeFd(filename="b.csv")),
        ("f2", FakeFd(filename="c.csv")),
    )
    mime = _file_mime(["f2"])
    captured = []
    nav.file_order_requested.connect(
        lambda fids, target, placement: captured.append(
            (list(fids), list(target), placement)
        )
    )

    event = _file_list_drop(
        nav, mime, _pos_on_row(nav._ordered_file_rows()[0], after=False)
    )

    assert event.dropAction() == Qt.MoveAction
    assert captured == [(["f2"], ["f0"], "before")]
    nav.project_file_order(["f2", "f0", "f1"])
    assert nav.ordered_file_fids() == ["f2", "f0", "f1"]


def test_file_list_same_slot_drop_is_noop(qapp, qtbot):
    nav = _shown_file_nav(
        qtbot,
        ("f0", FakeFd()),
        ("f1", FakeFd()),
    )
    mime = _file_mime(["f0"])
    with qtbot.assertNotEmitted(nav.file_order_requested):
        event = _file_list_drop(
            nav, mime, _pos_on_row(nav._ordered_file_rows()[0], after=True)
        )
    assert event.isAccepted()
    assert nav.ordered_file_fids() == ["f0", "f1"]


def test_file_list_group_card_moves_as_one_block(qapp, qtbot):
    source = "C:/data/grouped.hdf"
    nav = _shown_file_nav(
        qtbot,
        ("f0", FakeFd(filepath=source, label_suffix="1 kHz")),
        ("f1", FakeFd(filepath=source, label_suffix="2 kHz")),
        ("f2", FakeFd(filename="other.csv")),
    )
    mime = _file_mime(["f1", "f0"])
    captured = []
    nav.file_order_requested.connect(
        lambda fids, target, placement: captured.append(
            (list(fids), list(target), placement)
        )
    )

    event = _file_list_drop(
        nav, mime, _pos_on_row(nav._ordered_file_rows()[-1], after=True)
    )

    assert event.dropAction() == Qt.MoveAction
    assert captured == [(["f0", "f1"], ["f2"], "after")]
    nav.project_file_order(["f2", "f0", "f1"])
    assert nav.ordered_file_fids() == ["f2", "f0", "f1"]
    tree = nav.channel_list.tree
    assert tree.topLevelItemCount() == 2
    assert tree.topLevelItem(0).data(0, Qt.UserRole)[0] == "file"
    assert tree.topLevelItem(1).data(0, Qt.UserRole)[0] == "source"


def test_file_list_unknown_or_malformed_mime_is_ignored(qapp, qtbot):
    nav = _shown_file_nav(qtbot, ("f0", FakeFd()), ("f1", FakeFd()))
    last = _pos_on_row(nav._ordered_file_rows()[-1], after=True)
    with qtbot.assertNotEmitted(nav.file_order_requested):
        bad = QMimeData()
        bad.setData(_FileRow.MIME_TYPE, b"not-json")
        event = _file_list_drop(nav, bad, last)
        assert not event.isAccepted()

        missing = _file_mime(["missing"])
        event = _file_list_drop(nav, missing, last)
        assert not event.isAccepted()

        mixed = _file_mime(["f0", "f1"])
        event = _file_list_drop(nav, mixed, last)
        assert not event.isAccepted()
    assert nav.ordered_file_fids() == ["f0", "f1"]


def test_file_insert_line_clears_on_leave_drop_and_noop(qapp, qtbot):
    nav = _shown_file_nav(qtbot, ("f0", FakeFd()), ("f1", FakeFd()))
    mime = _file_mime(["f0"])
    move = QDragMoveEvent(
        _pos_on_row(nav._ordered_file_rows()[-1], after=True),
        Qt.MoveAction | Qt.CopyAction,
        mime,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    move._mime_ref = mime
    nav._handle_file_list_drag_move(move, nav._file_holder)
    assert nav._file_insert_line.isVisible()

    leave = QDragLeaveEvent()
    nav.eventFilter(nav._file_holder, leave)
    assert not nav._file_insert_line.isVisible()

    nav._handle_file_list_drag_move(move, nav._file_holder)
    assert nav._file_insert_line.isVisible()
    _file_list_drop(
        nav, mime, _pos_on_row(nav._ordered_file_rows()[-1], after=True)
    )
    assert not nav._file_insert_line.isVisible()

    nav._handle_file_list_drag_move(
        QDragMoveEvent(
            _pos_on_row(nav._ordered_file_rows()[0], after=True),
            Qt.MoveAction | Qt.CopyAction,
            mime,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
        nav._file_holder,
    )
    assert not nav._file_insert_line.isVisible()


def test_file_list_and_channel_pane_keep_move_vs_copy_actions(qapp, qtbot):
    nav = _shown_file_nav(qtbot, ("f0", FakeFd()), ("f1", FakeFd()))
    mime = _file_mime(["f0"])

    file_event = _file_list_drop(
        nav, mime, _pos_on_row(nav._ordered_file_rows()[-1], after=True)
    )
    assert file_event.dropAction() == Qt.MoveAction

    channel_event = QDropEvent(
        QPointF(4, 4), Qt.CopyAction | Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    channel_event._mime_ref = mime
    nav.channel_list.dropEvent(channel_event)
    assert channel_event.dropAction() == Qt.CopyAction
    assert channel_event.isAccepted()


def test_file_row_drag_parent_is_stable_host(qapp, qtbot, monkeypatch):
    nav = _shown_file_nav(qtbot, ("f0", FakeFd()))
    parents = []

    class _FakeDrag:
        def __init__(self, parent):
            parents.append(parent)

        def setMimeData(self, mime):
            self.mime = mime

        def exec_(self, *args, **kwargs):
            return Qt.CopyAction

    monkeypatch.setattr("mf4_analyzer.ui.file_navigator.QDrag", _FakeDrag)
    row = nav._ordered_file_rows()[0]
    row._drag_start = QPoint(0, 0)
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtCore import QEvent

    event = QMouseEvent(
        QEvent.MouseMove,
        QPoint(40, 40),
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    row.mouseMoveEvent(event)
    assert parents == [nav.window()]
