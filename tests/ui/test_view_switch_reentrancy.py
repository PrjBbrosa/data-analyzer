"""The time-domain View pipeline must be serial, and never render blank.

Two field bugs, one root cause. A time render is not atomic: it pumps the Qt
event loop from ``_begin_compute_progress`` so the status-bar progress reaches
the screen. Rapid View-tab clicking therefore delivered the NEXT switch inside
the render building the PREVIOUS one:

* the nested ``_capture_focused_view`` read a half-applied screen (navigator
  already projected to the incoming View, canvas still on the outgoing frame)
  and wrote that mixture into whichever View held the focus — "切来切去，
  View 2 变成 View 3 的内容了，通道都换了";
* the same write dropped a long file's zoom window onto a short file's View,
  putting the viewport entirely outside the data — a blank chart that 绘图
  could not fix (a visibility-delta replot never touches X) and only
  右键·全图 recovered.

Cover: the pump excludes user input, a switch that still lands mid-render is
deferred instead of interleaved (newest intent wins), captures are suppressed
while a render is in flight, and a View whose saved window no longer frames its
data is reframed rather than rendered empty.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from PyQt5.QtCore import QEventLoop
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window import window as window_mod


def _csv(path, *, duration, columns):
    t = np.linspace(0.0, float(duration), 2000)
    frame = {"time": t}
    frame.update({name: fn(t) for name, fn in columns.items()})
    pd.DataFrame(frame).to_csv(path, index=False)
    return str(path)


def _window(qtbot, qapp):
    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1200, 760)
    window.show()
    qapp.processEvents()
    return window


def _visible_channels(canvas):
    """Channel names actually painted (visible PlotDataItem with >= 2 points)."""
    drawn = []
    for _ck, name, (_handle, line) in canvas._channel_lines.composite_items():
        pdi = getattr(line, "plot_data_item", None)
        if pdi is None or not pdi.isVisible():
            continue
        x, _y = pdi.getData()
        if x is not None and len(x) >= 2:
            drawn.append(str(name).split("] ")[-1])
    return sorted(drawn)


def _checked(window):
    return sorted(ch for _fid, ch, _color in window.navigator.get_checked_channels())


def _state_channels(state):
    return sorted(ch for _fid, ch in state.checked)


def _seed_view(window, qapp, fid, channels, *, xlim=None, new_view=False):
    """Build one time View: attach the file, check channels, plot, capture."""
    if new_view:
        window._on_view_new()
        qapp.processEvents()
        window._attach_files_to_focused_view([fid])
        qapp.processEvents()
    window.navigator.set_checked_channels([(fid, ch) for ch in channels])
    qapp.processEvents()
    window.plot_time()
    qapp.processEvents()
    if xlim is not None:
        window.canvas_time.restore_visible_xlim(xlim)
        qapp.processEvents()
    window._capture_focused_view()


@pytest.fixture
def three_view_window(qtbot, qapp, tmp_path):
    """One file, three Views with disjoint channel sets and distinct zooms."""
    path = _csv(
        tmp_path / "eps.csv",
        duration=50.0,
        columns={
            "steer_torque": lambda t: np.sin(2 * np.pi * 0.5 * t),
            "motor_speed": lambda t: np.cos(2 * np.pi * 0.3 * t),
            "motor_torque": lambda t: np.sin(2 * np.pi * 1.1 * t),
            "rack_force": lambda t: t % 5.0,
        },
    )
    window = _window(qtbot, qapp)
    window.load_file(path)
    qapp.processEvents()
    fid = next(iter(window.files))

    _seed_view(window, qapp, fid, ["steer_torque", "motor_speed"])
    _seed_view(window, qapp, fid, ["motor_torque", "rack_force"],
               xlim=(10.0, 16.0), new_view=True)
    _seed_view(window, qapp, fid, ["steer_torque", "motor_torque"],
               xlim=(20.0, 30.0), new_view=True)
    window._switch_view(0)
    qapp.processEvents()
    return window, fid


class _QAppPumpProxy:
    """Stand-in for ``QApplication`` that runs ``hook`` on each pump.

    Simulates precisely what the real defect needed: an event delivered while
    the render is on the stack. Everything else forwards to the real class.
    """

    def __init__(self, hook):
        self.hook = hook
        self.flags = []

    def __getattr__(self, name):
        return getattr(QApplication, name)

    def processEvents(self, *args, **kwargs):
        self.flags.append(args[0] if args else None)
        self.hook()
        return QApplication.processEvents(*args, **kwargs)


def test_progress_pump_never_delivers_user_input(three_view_window, monkeypatch):
    """The pump exists to paint the bar, not to run the next click."""
    window, _fid = three_view_window
    proxy = _QAppPumpProxy(lambda: None)
    monkeypatch.setattr(window_mod, "QApplication", proxy)

    window.plot_time()

    assert proxy.flags, "the time plot must still pump the progress bar"
    assert all(
        flag == QEventLoop.ExcludeUserInputEvents for flag in proxy.flags
    ), f"a bare processEvents() re-enters the pipeline: {proxy.flags}"


def test_switch_landing_inside_a_render_does_not_interleave(
    three_view_window, qapp, monkeypatch
):
    """View 2 must not end up showing View 3's channels."""
    window, _fid = three_view_window
    before = [_state_channels(state) for state in window.view_manager.views]

    fired = []

    def click_view_three():
        if fired:
            return
        fired.append(True)
        window._switch_view(2)

    monkeypatch.setattr(window_mod, "QApplication", _QAppPumpProxy(click_view_three))
    window._switch_view(1)
    monkeypatch.undo()
    qapp.processEvents()

    assert fired, "the pump must have delivered the nested switch"
    # Newest intent wins, and every surface agrees on it.
    active = window.view_manager.active
    assert active == 2
    assert window._focused_view_idx == 2
    assert _checked(window) == ["motor_torque", "steer_torque"]
    assert _visible_channels(window.canvas_time) == ["motor_torque", "steer_torque"]
    # No View absorbed another View's selection.
    assert [_state_channels(state) for state in window.view_manager.views] == before


def test_deferred_switch_keeps_each_view_window(three_view_window, qapp, monkeypatch):
    """The interleaved capture used to overwrite a View's zoom; it must not."""
    window, _fid = three_view_window
    windows_before = [state.xlim for state in window.view_manager.views]

    monkeypatch.setattr(
        window_mod, "QApplication", _QAppPumpProxy(lambda: window._switch_view(2)),
    )
    window._switch_view(1)
    monkeypatch.undo()
    qapp.processEvents()

    assert [state.xlim for state in window.view_manager.views] == windows_before
    assert window.canvas_time.get_visible_xlim() == pytest.approx(
        (20.0, 30.0), abs=0.05
    )


def test_last_switch_wins_when_several_land_in_one_render(
    three_view_window, qapp, monkeypatch
):
    """Rapid clicking means "take me to the tab I stopped on"."""
    window, _fid = three_view_window
    fired = []

    def click_three_then_one():
        if fired:
            return
        fired.append(True)
        window._switch_view(2)
        window._switch_view(0)

    monkeypatch.setattr(
        window_mod, "QApplication", _QAppPumpProxy(click_three_then_one),
    )
    window._switch_view(1)
    monkeypatch.undo()
    qapp.processEvents()

    assert fired
    assert window.view_manager.active == 0
    assert window._focused_view_idx == 0
    assert _visible_channels(window.canvas_time) == ["motor_speed", "steer_torque"]


def test_capture_is_suppressed_while_a_render_is_in_flight(three_view_window):
    """The screen is a mixture mid-render; capturing it corrupts a View."""
    window, _fid = three_view_window
    state = window.view_manager.get(0)
    state.checked = []
    state.xlim = (1.0, 2.0)

    window._time_render.enter()
    try:
        window._capture_focused_view()
    finally:
        window._time_render.leave()

    assert state.checked == []
    assert state.xlim == (1.0, 2.0)

    # Outside the gate the same call captures normally.
    window._capture_focused_view()
    assert _state_channels(state) == ["motor_speed", "steer_torque"]


def test_view_window_outside_its_data_is_reframed_not_blanked(
    qtbot, qapp, tmp_path
):
    """A window that no longer frames the data must not render an empty chart."""
    long_path = _csv(
        tmp_path / "long.csv",
        duration=260.0,
        columns={"steer_torque": lambda t: np.sin(t)},
    )
    short_path = _csv(
        tmp_path / "short.csv",
        duration=49.5,
        columns={"L": lambda t: 0.4 * np.sin(50 * t)},
    )
    window = _window(qtbot, qapp)
    window.load_file(long_path)
    window.load_file(short_path)
    qapp.processEvents()
    long_fid, short_fid = list(window.files)

    _seed_view(window, qapp, long_fid, ["steer_torque"], xlim=(118.41, 125.03))
    _seed_view(window, qapp, short_fid, ["L"], new_view=True)

    # However it got there (stale project, re-entrant capture), the second
    # View now carries a window that lies past the end of its own recording.
    # The stale window still overlaps the short recording, but would leave
    # roughly three quarters of the chart blank if restored verbatim.
    window.view_manager.get(1).xlim = (0.0, 185.0)
    # Project restore and other direct applications do not pass through a
    # switch that first captures/replaces the stale state.  Exercise that real
    # boundary: the restore itself must reject a viewport outside the data.
    window._apply_active_view(1)
    qapp.processEvents()

    assert _visible_channels(window.canvas_time) == ["L"]
    lo, hi = window.canvas_time.get_visible_xlim()
    assert (lo, hi) == pytest.approx((0.0, 49.5), abs=0.05)


def test_zoomed_view_window_is_still_restored_verbatim(three_view_window, qapp):
    """The reframe guard must not cost a legitimate zoom its window."""
    window, _fid = three_view_window
    window._switch_view(1)
    qapp.processEvents()

    assert window.canvas_time.get_visible_xlim() == pytest.approx(
        (10.0, 16.0), abs=0.05
    )
    assert _visible_channels(window.canvas_time) == ["motor_torque", "rack_force"]
def test_closing_the_window_drops_a_parked_switch(three_view_window, qapp, monkeypatch):
    """A parked switch must not replay into a tree that is being torn down.

    Replaying it runs a full render whose own progress pump lets the queued
    deferred-delete through, so the rest of the render then touches destroyed
    children (PillSwitch / ComputeProgressWidget / QStackedWidget).
    """
    window, _fid = three_view_window
    monkeypatch.setattr(
        window_mod, "QApplication", _QAppPumpProxy(lambda: window._switch_view(2)),
    )
    window._switch_view(1)
    monkeypatch.undo()

    assert (
        window._time_render.pending_view_id is not None
        or window._time_render.drain_scheduled
    ), "the switch must actually be parked for this test to mean anything"

    raised = []
    original = MainWindow._drain_pending_view_switch

    def recording_drain(self):
        try:
            return original(self)
        except RuntimeError as exc:      # deleted C++ object reached the slot
            raised.append(exc)
            raise

    monkeypatch.setattr(MainWindow, "_drain_pending_view_switch", recording_drain)
    window.close()
    for _ in range(5):
        qapp.processEvents()

    assert raised == []
    assert window._time_render.pending_view_id is None
