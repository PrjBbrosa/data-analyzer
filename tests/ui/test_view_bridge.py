from mf4_analyzer.ui import view_bridge
from mf4_analyzer.ui.view_state import ViewState


class _Nav:
    def __init__(self):
        self._checked = [("f1", "rpm", "#111111")]
        self._hidden = [("f1", "rpm")]
        self._colors = {("f1", "rpm"): "#111111", ("f1", "spd"): "#222222"}
        self.set_checked = None
        self.set_hidden = None
        self.set_colors = None
        self.blocked = []

    def blockSignals(self, blocked):
        old = self.blocked[-1] if self.blocked else False
        self.blocked.append(blocked)
        return old

    def get_checked_channels(self):
        return list(self._checked)

    def get_channel_colors(self):
        return dict(self._colors)

    def get_hidden_channels(self):
        return list(self._hidden)

    def set_checked_channels(self, checked):
        self.set_checked = list(checked)

    def set_hidden_channels(self, hidden):
        self.set_hidden = list(hidden)

    def set_channel_colors(self, colors):
        self.set_colors = dict(colors)


class _Canvas:
    def __init__(self):
        self._xlim = (0.0, 9.0)
        self._ylims = {"f1::rpm": (-1.0, 1.0)}
        self.applied_x = "<unset>"
        self.applied_y = None
        self.cursor_visible = None
        self.dual_cursor = None

    def get_visible_xlim(self):
        return self._xlim

    def restore_visible_xlim(self, xlim):
        self.applied_x = xlim

    def get_visible_ylims(self):
        return dict(self._ylims)

    def restore_visible_ylims(self, ylims):
        self.applied_y = dict(ylims)

    def set_cursor_visible(self, visible):
        self.cursor_visible = visible

    def set_dual_cursor_mode(self, enabled):
        self.dual_cursor = enabled


class _Stack:
    def __init__(self):
        self.canvas_time = _Canvas()
        self._plot_mode = "overlay"
        self._cursor_mode = "single"
        self.blocked = []

    def blockSignals(self, blocked):
        old = self.blocked[-1] if self.blocked else False
        self.blocked.append(blocked)
        return old

    def plot_mode(self):
        return self._plot_mode

    def cursor_mode(self):
        return self._cursor_mode

    def set_plot_mode(self, mode):
        self._plot_mode = mode

    def set_cursor_mode(self, mode):
        self._cursor_mode = mode


class _InspectorTop:
    def __init__(self):
        self._range_enabled = True
        self._range_values = (0.0, 9.0)
        self._xaxis_label = "Time (s)"
        self._tick_density = (10, 6)

    def range_enabled(self):
        return self._range_enabled

    def range_values(self):
        return self._range_values

    def xaxis_label(self):
        return self._xaxis_label

    def tick_density(self):
        return self._tick_density


class _Inspector:
    def __init__(self):
        self.top = _InspectorTop()


class _Window:
    def __init__(self):
        self.navigator = _Nav()
        self.chart_stack = _Stack()
        self.inspector = _Inspector()
        self._custom_xaxis_fid = None
        self._custom_xaxis_ch = None
        self._custom_xlabel = None
        self._overlay_primary = ("f1", "rpm")
        self.restored_axis_opts = None
        self.cursor_mode_syncs = []

    def _restore_view_axis_opts(self, axis_opts):
        self.restored_axis_opts = axis_opts

    def _on_cursor_mode_changed(self, mode):
        self.cursor_mode_syncs.append(mode)
        self.chart_stack.canvas_time.set_cursor_visible(mode != "off")
        self.chart_stack.canvas_time.set_dual_cursor_mode(mode == "dual")


def test_capture_view_reads_full_screen_state():
    win = _Window()

    state = view_bridge.capture_view(win)

    assert state.checked == [("f1", "rpm")]
    assert state.hidden_channels == [("f1", "rpm")]
    assert state.colors == {("f1", "rpm"): "#111111"}
    assert state.plot_mode == "overlay"
    assert state.cursor_mode == "single"
    assert state.xlim == (0.0, 9.0)
    assert state.ylims == {"f1::rpm": (-1.0, 1.0)}
    assert state.overlay_primary == ("f1", "rpm")
    assert state.axis_opts["range_filter"] == {
        "enabled": True,
        "start": 0.0,
        "end": 9.0,
    }
    assert state.axis_opts["x_axis"] == {
        "mode": "time",
        "fid": None,
        "channel": None,
        "label": "Time (s)",
    }
    assert state.axis_opts["tick_density"] == {"x": 10, "y": 6}


def test_capture_view_reads_custom_xaxis_from_window_state():
    win = _Window()
    win._custom_xaxis_fid = "f1"
    win._custom_xaxis_ch = "angle"
    win.inspector.top._xaxis_label = "Angle"

    state = view_bridge.capture_view(win)

    assert state.axis_opts["x_axis"] == {
        "mode": "channel",
        "fid": "f1",
        "channel": "angle",
        "label": "Angle",
    }


def test_capture_view_uses_channel_name_for_blank_custom_xaxis_label():
    win = _Window()
    win._custom_xaxis_fid = "f1"
    win._custom_xaxis_ch = "angle"
    win.inspector.top._xaxis_label = ""

    state = view_bridge.capture_view(win)

    assert state.axis_opts["x_axis"] == {
        "mode": "channel",
        "fid": "f1",
        "channel": "angle",
        "label": "angle",
    }


def test_capture_into_preserves_tab_metadata_and_updates_screen_state():
    win = _Window()
    win.navigator._checked = [("f2", "torque", "#333333")]
    win.navigator._hidden = [("f2", "torque")]
    win.navigator._colors = {("f2", "torque"): "#333333"}
    win.chart_stack._plot_mode = "subplot"
    win.chart_stack._cursor_mode = "dual"
    win.chart_stack.canvas_time._xlim = (2.0, 5.0)
    win.chart_stack.canvas_time._ylims = {"f2::torque": (-2.0, 2.0)}
    win._custom_xaxis_fid = "f2"
    win._custom_xaxis_ch = "angle"
    win._overlay_primary = ("f2", "torque")
    win.inspector.top._range_enabled = False
    win.inspector.top._range_values = (1.0, 8.0)
    win.inspector.top._xaxis_label = "Angle"
    win.inspector.top._tick_density = (12, 7)
    state = ViewState(
        name="My View",
        tab_color="#abcdef",
        checked=[("old", "old")],
        colors={("old", "old"): "#000000"},
        plot_mode="overlay",
        cursor_mode="single",
        xlim=(0.0, 1.0),
        ylims={"old": (0.0, 1.0)},
        overlay_primary=("old", "old"),
        axis_opts={"tick_density": {"x": 1, "y": 1}},
    )

    view_bridge.capture_into(state, win)

    assert state.name == "My View"
    assert state.tab_color == "#abcdef"
    assert state.checked == [("f2", "torque")]
    assert state.hidden_channels == [("f2", "torque")]
    assert state.colors == {("f2", "torque"): "#333333"}
    assert state.plot_mode == "subplot"
    assert state.cursor_mode == "dual"
    assert state.xlim == (2.0, 5.0)
    assert state.ylims == {"f2::torque": (-2.0, 2.0)}
    assert state.overlay_primary == ("f2", "torque")
    assert state.axis_opts == {
        "range_filter": {"enabled": False, "start": 1.0, "end": 8.0},
        "x_axis": {
            "mode": "channel",
            "fid": "f2",
            "channel": "angle",
            "label": "Angle",
        },
        "tick_density": {"x": 12, "y": 7},
    }


def test_apply_view_writes_widgets_and_restore_axis_hook_without_replot():
    win = _Window()
    state = ViewState(
        name="v",
        tab_color="#000000",
        checked=[("f1", "rpm")],
        hidden_channels=[("f1", "rpm")],
        colors={("f1", "rpm"): "#abcdef"},
        plot_mode="subplot",
        cursor_mode="off",
        overlay_primary=None,
        axis_opts={"tick_density": {"x": 12, "y": 7}},
    )

    view_bridge.apply_view(state, win)

    assert win.navigator.set_colors == {("f1", "rpm"): "#abcdef"}
    assert win.navigator.set_checked == [("f1", "rpm")]
    assert win.navigator.set_hidden == [("f1", "rpm")]
    assert win.chart_stack._plot_mode == "subplot"
    assert win.chart_stack._cursor_mode == "off"
    assert win._overlay_primary is None
    assert win.restored_axis_opts == {"tick_density": {"x": 12, "y": 7}}
    assert win.cursor_mode_syncs == []
    assert win.chart_stack.canvas_time.cursor_visible is False
    assert win.chart_stack.canvas_time.dual_cursor is False
    assert win.navigator.blocked == [True, False]
    assert win.chart_stack.blocked == [True, False]


def test_apply_view_syncs_canvas_cursor_state_when_signals_are_blocked():
    win = _Window()
    state = ViewState(
        name="v",
        tab_color="#000000",
        cursor_mode="dual",
    )

    view_bridge.apply_view(state, win)

    assert win.cursor_mode_syncs == []
    assert win.chart_stack.canvas_time.cursor_visible is True
    assert win.chart_stack.canvas_time.dual_cursor is True


def test_restore_axes_calls_canvas_restore_methods():
    win = _Window()
    state = ViewState(
        name="v",
        tab_color="#000000",
        xlim=(2.0, 5.0),
        ylims={"f1::rpm": (-2.0, 2.0)},
    )

    view_bridge.restore_axes(state, win)

    assert win.chart_stack.canvas_time.applied_x == (2.0, 5.0)
    assert win.chart_stack.canvas_time.applied_y == {"f1::rpm": (-2.0, 2.0)}


def test_restore_axes_passes_none_xlim_through_canvas_contract():
    win = _Window()
    state = ViewState(name="v", tab_color="#000000", xlim=None, ylims={})

    view_bridge.restore_axes(state, win)

    assert win.chart_stack.canvas_time.applied_x is None
    assert win.chart_stack.canvas_time.applied_y == {}
