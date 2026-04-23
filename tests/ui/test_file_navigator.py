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
