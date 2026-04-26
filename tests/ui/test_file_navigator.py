from mf4_analyzer.ui.file_navigator import FileNavigator


def test_file_navigator_constructs(qapp):
    nav = FileNavigator()
    assert nav.channel_list is not None


def test_file_navigator_signals_exist(qapp):
    nav = FileNavigator()
    assert hasattr(nav, 'file_activated')
    assert hasattr(nav, 'file_close_requested')
    assert hasattr(nav, 'close_all_requested')
    assert hasattr(nav, 'channels_changed')


class FakeFd:
    def __init__(self, filename="sample.csv", short_name="sample", rows=100, fs=1000.0, duration=5.0):
        self.filename = filename
        self.short_name = short_name
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


def test_file_row_added(qapp):
    nav = FileNavigator()
    nav.add_file("f0", FakeFd())
    assert nav.file_list_count() == 1


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
    nav.add_file("f0", FakeFd())
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
    nav.add_file("f0", FakeFd())
    nav.channel_list._all()
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).checkState(0) == Qt.Checked


def test_channel_none_button_clears(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    nav.channel_list._all()
    nav.channel_list._none()
    fi = nav.channel_list._file_items["f0"]
    for i in range(fi.childCount()):
        assert fi.child(i).checkState(0) == Qt.Unchecked


def test_channel_inv_button_toggles(qapp, qtbot):
    nav = FileNavigator()
    qtbot.addWidget(nav)
    nav.add_file("f0", FakeFd())
    fi = nav.channel_list._file_items["f0"]
    fi.child(0).setCheckState(0, Qt.Checked)
    nav.channel_list._inv()
    assert fi.child(0).checkState(0) == Qt.Unchecked
    assert fi.child(1).checkState(0) == Qt.Checked


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
    nav.add_file("f0", WideFd())
    with patch('mf4_analyzer.ui.widgets.QMessageBox.question',
               return_value=False) as q:
        nav.channel_list._all()
    assert q.called
