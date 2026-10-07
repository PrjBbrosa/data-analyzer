import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QMenu

from mf4_analyzer.ui.file_navigator import FileNavigator


class _FileData:
    data = [1, 2, 3]
    time_array = [0.0, 0.01, 0.02]
    filename = "sample.csv"
    short_name = "sample"
    fs = 100.0
    channel_units = {"扭矩_Rte_TAS_mTorsionBarTorque_xds16": "Nm"}

    def get_signal_channels(self):
        return ["扭矩_Rte_TAS_mTorsionBarTorque_xds16", "speed", "torque"]

    def get_color_palette(self):
        return ["#1769e0", "#8b5cf6", "#f43f5e"]


@pytest.fixture
def navigator(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.resize(320, 600)
    nav.add_file("source-a", _FileData())
    nav.set_attached_file_ids(["source-a"])
    nav.show()
    qtbot.waitExposed(nav)
    nav.channel_list.tree.expandAll()
    qapp.processEvents()
    old_text = qapp.clipboard().text()
    qapp.clipboard().setText("unchanged")
    yield nav
    qapp.clipboard().setText(old_text)


def _open_menu(nav, item, qapp):
    tree = nav.channel_list.tree
    tree.scrollToItem(item)
    qapp.processEvents()
    pos = tree.visualItemRect(item).center()
    assert tree.itemAt(pos) is item
    nav.channel_list._on_context_menu(pos)


@pytest.mark.parametrize("section,role", [
    ("时域", "time"),
    ("频谱", "fft_sources"),
    ("时频", "analysis_candidates"),
    ("阶次", "analysis_candidates"),
    ("频响", "analysis_candidates"),
])
def test_single_channel_copies_full_name_in_every_section(
    navigator, qapp, monkeypatch, section, role,
):
    navigator.set_attachment_context(section_label=section, view_name="View 1")
    navigator.set_projection_role(role)
    widget = navigator.channel_list
    item = widget._file_items["source-a"].child(0)
    name = item.data(0, Qt.UserRole)[2]
    item.setText(0, "扭矩_Rte…xds16")
    widget.tree.setCurrentItem(item)
    changed = QSignalSpy(widget.channels_changed)
    primary = QSignalSpy(widget.primary_channel_requested)
    checked = item.checkState(0)

    def choose_copy(menu, *_args):
        assert "设为左轴" in [a.text() for a in menu.actions()]
        return next(a for a in menu.actions() if a.text() == "复制通道名")

    monkeypatch.setattr(QMenu, "exec_", choose_copy)
    _open_menu(navigator, item, qapp)

    assert qapp.clipboard().text() == name
    assert item.checkState(0) == checked
    assert not changed
    assert not primary


@pytest.mark.parametrize("role", ["time", "fft_sources", "analysis_candidates"])
@pytest.mark.parametrize("grouped", [False, True])
def test_multiple_channels_only_offer_axis_group_actions(
    navigator, qapp, monkeypatch, role, grouped,
):
    navigator.set_projection_role(role)
    widget = navigator.channel_list
    root = widget._file_items["source-a"]
    if grouped:
        widget.merge_axis_group([
            root.child(i).data(0, Qt.UserRole)[1:] for i in range(2)
        ])
    widget.tree.setCurrentItem(root.child(0))
    root.child(1).setSelected(True)
    assert len(widget.tree.selectedItems()) == 2
    labels = []

    def cancel(menu, *_args):
        labels.extend(a.text() for a in menu.actions())
        return None

    monkeypatch.setattr(QMenu, "exec_", cancel)
    _open_menu(navigator, root.child(0), qapp)

    assert "复制通道名" not in labels
    assert "设为左轴" not in labels
    assert labels == (
        ["合并为共轴", "拆分共轴组"] if grouped else ["合并为共轴"]
    )
    assert qapp.clipboard().text() == "unchanged"


def test_right_click_outside_selection_copies_clicked_channel(
    navigator, qapp, monkeypatch,
):
    widget = navigator.channel_list
    root = widget._file_items["source-a"]
    widget.tree.setCurrentItem(root.child(0))
    root.child(1).setSelected(True)

    def choose_copy(menu, *_args):
        return next(a for a in menu.actions() if a.text() == "复制通道名")

    monkeypatch.setattr(QMenu, "exec_", choose_copy)
    _open_menu(navigator, root.child(2), qapp)

    assert qapp.clipboard().text() == "torque"


def test_file_row_does_not_open_channel_copy_menu(navigator, qapp, monkeypatch):
    opened = []

    def capture(menu, *_args):
        opened.append(menu)
        return None

    monkeypatch.setattr(QMenu, "exec_", capture)
    _open_menu(navigator, navigator.channel_list._file_items["source-a"], qapp)

    assert not opened
    assert qapp.clipboard().text() == "unchanged"
