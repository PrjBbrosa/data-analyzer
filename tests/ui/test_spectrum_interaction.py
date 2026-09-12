"""Spectrum pan/zoom interaction contracts (offscreen T0 red tests).

Desired behavior from docs/analyzer/plans/2026-09-12-spectrum-pan-performance-plan.md
§T0 / §3.2–3.3. These assertions encode the target; they must fail on the
pre-optimization owner (exact-xlim cache key, sync callback Y-scan, per-event
rebuild, programmatic auto-Y mistaken for user Y).
"""
from __future__ import annotations

import inspect

import numpy as np
import pytest
import pyqtgraph as pg
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QMouseEvent, QWheelEvent
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.signal.display_ranges import PreparedLineRange
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas


@pytest.fixture
def canvas(qapp):
    c = PgLineCanvas()
    c.resize(640, 480)
    yield c
    c.deleteLater()


def _entry(label='f1 · vib', color='#2563eb', n=256):
    freq = np.linspace(0.0, 500.0, n)
    amp = np.exp(-((freq - 120.0) / 15.0) ** 2)
    time = np.linspace(0.0, 1.0, 200)
    signal = np.sin(2.0 * np.pi * 12.0 * time)
    return {
        'label': label,
        'color': color,
        'freq': freq,
        'amp': amp,
        'time': time,
        'signal': signal,
    }


def _plot_fft(canvas, entry=None, xlim=(0.0, 500.0)):
    if entry is None:
        entry = _entry()
    canvas.plot_spectra(
        [entry], xlim=xlim, amp_label='Amplitude', title='FFT',
        y_auto=True, y_min=0.0, y_max=0.0,
    )
    return entry


def _fire_spectrum_refresh_timer(canvas):
    """Drive the 16 ms coalesced refresh without sleeping on wall-clock."""
    timer = canvas._spectrum_refresh_timer
    timer.stop()
    now = canvas._spectrum_monotonic()
    canvas._spectrum_last_refresh_at = now - 0.020
    timer.timeout.emit()


def _watch_callback_y_scans(canvas, monkeypatch):
    """Record raw-Y work that still sits on the interactive callback stack."""
    import mf4_analyzer.ui.pg_canvas.line_canvas as line_mod

    scans = []
    orig_visible = line_mod.visible_line_values

    def wrapped_visible(*args, **kwargs):
        if _callback_stack_hit():
            scans.append('visible_line_values')
        return orig_visible(*args, **kwargs)

    monkeypatch.setattr(line_mod, 'visible_line_values', wrapped_visible)

    orig_auto = canvas._auto_amplitude_y_range

    def wrapped_auto(entries, xlim):
        if _callback_stack_hit():
            scans.append('_auto_amplitude_y_range')
        return orig_auto(entries, xlim)

    monkeypatch.setattr(canvas, '_auto_amplitude_y_range', wrapped_auto)

    orig_query = PreparedLineRange.query

    def wrapped_query(self, xlim, **kwargs):
        if _callback_stack_hit():
            scans.append('PreparedLineRange.query')
        return orig_query(self, xlim, **kwargs)

    monkeypatch.setattr(PreparedLineRange, 'query', wrapped_query)
    return scans


def _callback_stack_hit():
    names = {frame.function for frame in inspect.stack()}
    return bool(names & {'_emit_viewport_intent', '_on_interactive_range_changed'})


def _amp_setdata_log(canvas, monkeypatch):
    calls = []
    orig = pg.PlotDataItem.setData

    def wrapped(self, *args, **kwargs):
        if self in canvas._amp_curves:
            calls.append((args, kwargs))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(pg.PlotDataItem, 'setData', wrapped)
    return calls


def test_full_coverage_pan_does_not_rebuild_setdata(canvas, qapp, monkeypatch):
    """All finite bins still inside the window: pan must not curve.setData.

    Coverage/density/revision is the hit condition; exact xlim floats are not.
    """
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas, xlim=(0.0, 500.0))
    qapp.processEvents()

    setdata_calls = _amp_setdata_log(canvas, monkeypatch)
    # Still covers 0..500; only the viewport translates.
    canvas._plot_amp.setXRange(-40.0, 540.0, padding=0)
    canvas._refresh_spectrum_display()

    assert setdata_calls == [], (
        'full-coverage pan must not call curve.setData; '
        f'rebuilt {len(setdata_calls)} time(s)'
    )


def test_pure_x_drag_does_not_scan_raw_y_on_callback_stack(canvas, qapp, monkeypatch):
    """Interactive X callback may only submit the latest target / dirty flags.

    Raw `visible_line_values` / `_auto_amplitude_y_range` belong on a later
    coalesced refresh, not on `_emit_viewport_intent`.
    """
    _plot_fft(canvas)
    qapp.processEvents()

    scans = _watch_callback_y_scans(canvas, monkeypatch)

    canvas._begin_view_interaction()
    canvas._plot_amp.setXRange(20.0, 180.0, padding=0)
    canvas._idle_activity.note_pulse()
    canvas._plot_amp.vb.sigRangeChangedManually.emit([True, False])

    assert scans == [], (
        'pure X drag scanned raw Y on the interactive callback stack: '
        f'{scans!r}'
    )


def test_range_event_burst_refreshes_only_latest_xlim(canvas, qapp, monkeypatch):
    """Several X-range events while busy coalesce to one latest-wins refresh.

    Drive the 16 ms timer explicitly. Today's idle `_request_spectrum_refresh`
    rebuilds immediately when not busy; the busy path still Y-fits every event.
    """
    _plot_fft(canvas)
    qapp.processEvents()

    plot_xlims = []
    orig_plot = canvas._spectrum_plot_arrays

    def wrapped_plot(freq, amp, *, xlim=None):
        used = xlim if xlim is not None else canvas._plot_amp.vb.viewRange()[0]
        plot_xlims.append((float(used[0]), float(used[1])))
        return orig_plot(freq, amp, xlim=xlim)

    monkeypatch.setattr(canvas, '_spectrum_plot_arrays', wrapped_plot)

    y_xlims = []
    orig_y = canvas._auto_amplitude_y_range

    def wrapped_y(entries, xlim):
        y_xlims.append((float(xlim[0]), float(xlim[1])))
        return orig_y(entries, xlim)

    monkeypatch.setattr(canvas, '_auto_amplitude_y_range', wrapped_y)

    canvas._begin_view_interaction()
    windows = [(10.0 + 20.0 * i, 210.0 + 20.0 * i) for i in range(4)]
    for lo, hi in windows:
        canvas._plot_amp.setXRange(lo, hi, padding=0)
        canvas._idle_activity.note_pulse()
        canvas._on_interactive_range_changed(canvas._plot_amp)
    latest = tuple(float(v) for v in canvas._plot_amp.vb.viewRange()[0])

    burst_plot = list(plot_xlims)
    burst_y = list(y_xlims)
    _fire_spectrum_refresh_timer(canvas)
    after_plot = plot_xlims[len(burst_plot):]
    after_y = y_xlims[len(burst_y):]

    assert burst_plot == [], (
        'range events rebuilt traces immediately for '
        f'{burst_plot!r}; refresh must wait for the coalesced timer '
        f'(latest xlim {latest!r})'
    )
    assert burst_y == [], (
        'range events scanned raw Y for intermediate xlims '
        f'{burst_y!r}; only the latest xlim {latest!r} may refresh'
    )
    assert after_plot == [latest], (
        'timer tick must rebuild once for the latest xlim '
        f'{latest!r}; got {after_plot!r}'
    )
    assert after_y in ([], [latest]), (
        'timer tick may Y-fit the latest xlim only; '
        f'got {after_y!r}'
    )


def test_programmatic_auto_y_is_not_user_y_intent(canvas, qapp):
    """Pure X drag + programmatic auto-Y must keep origin.y auto.

    A later `_on_interactive_range_changed` must not treat the auto-Y
    `setYRange` as a user Y zoom (`viewport_action_committed` axes include y).
    """
    from PyQt5.QtTest import QSignalSpy

    entry = _entry()
    entry['amp'] = entry['freq'] / 10.0
    policy = {'y_auto': True, 'viewport_origin': {'x': 'auto', 'y': 'auto'}}
    canvas.analysis_range_adapter = (lambda: policy, None)

    def _commit_origin(action, axes):
        for axis in axes:
            policy['viewport_origin'][axis] = action

    canvas.viewport_action_committed.connect(_commit_origin)
    spy = QSignalSpy(canvas.viewport_action_committed)

    _plot_fft(canvas, entry=entry)
    qapp.processEvents()

    canvas._begin_view_interaction()
    canvas._plot_amp.setXRange(0.0, 200.0, padding=0)
    canvas._plot_amp.vb.sigRangeChangedManually.emit([True, False])

    # Deferred auto-Y: X moved again, then programmatic Y-fit, then the
    # next interactive range callback. Must not flip origin.y.
    canvas._plot_amp.setXRange(0.0, 80.0, padding=0)
    canvas._fit_active_spectrum_y()
    canvas._idle_activity.note_pulse()
    canvas._on_interactive_range_changed(canvas._plot_amp)
    canvas._end_view_interaction()

    y_commits = [tuple(evt) for evt in spy if 'y' in tuple(evt[1])]
    assert y_commits == [], (
        'programmatic auto-Y was committed as user Y intent: '
        f'{y_commits!r}'
    )
    assert policy['viewport_origin']['y'] == 'auto'
    assert canvas._spectrum_y_auto is True


def test_spectrum_refresh_timeout_respects_monotonic_interval(
        canvas, qapp, monkeypatch):
    """Qt may wake the 16 ms timer early; re-check monotonic remaining."""
    clock = [1000.0]
    canvas._spectrum_monotonic = lambda: clock[0]
    _plot_fft(canvas)
    qapp.processEvents()

    plot_xlims = []
    orig_plot = canvas._spectrum_plot_arrays

    def wrapped_plot(freq, amp, *, xlim=None, prepared=None):
        used = xlim if xlim is not None else canvas._plot_amp.vb.viewRange()[0]
        plot_xlims.append((float(used[0]), float(used[1])))
        return orig_plot(freq, amp, xlim=xlim, prepared=prepared)

    monkeypatch.setattr(canvas, '_spectrum_plot_arrays', wrapped_plot)

    canvas._begin_view_interaction()
    canvas._plot_amp.setXRange(20.0, 180.0, padding=0)
    assert canvas._spectrum_refresh_timer.isActive()
    assert plot_xlims == []

    clock[0] = 1000.005
    canvas._spectrum_refresh_timer.timeout.emit()
    assert plot_xlims == []
    assert canvas._spectrum_refresh_timer.isActive()

    clock[0] = 1000.020
    canvas._spectrum_refresh_timer.stop()
    canvas._spectrum_refresh_timer.timeout.emit()
    latest = tuple(float(v) for v in canvas._plot_amp.vb.viewRange()[0])
    assert plot_xlims == [latest]


def test_flush_pending_spectrum_display_runs_latest_and_keeps_idle_aa_interval(
        canvas, qapp, monkeypatch):
    _plot_fft(canvas)
    qapp.processEvents()
    assert canvas._aa_idle_timer.interval() == 150

    y_xlims = []
    orig_y = canvas._auto_amplitude_y_range

    def wrapped_y(entries, xlim):
        y_xlims.append((float(xlim[0]), float(xlim[1])))
        return orig_y(entries, xlim)

    monkeypatch.setattr(canvas, '_auto_amplitude_y_range', wrapped_y)

    canvas._begin_view_interaction()
    windows = [(10.0 + 20.0 * i, 210.0 + 20.0 * i) for i in range(4)]
    for lo, hi in windows:
        canvas._plot_amp.setXRange(lo, hi, padding=0)
    latest = tuple(float(v) for v in canvas._plot_amp.vb.viewRange()[0])
    assert canvas._spectrum_refresh_timer.isActive()
    assert y_xlims == []

    canvas.flush_pending_spectrum_display()
    assert canvas._spectrum_refresh_timer.isActive() is False
    assert canvas._aa_idle_timer.interval() == 150
    assert y_xlims == [latest]


def test_stale_spectrum_refresh_timeout_does_not_write_after_reset_or_replot(
        canvas, qapp, monkeypatch):
    _plot_fft(canvas)
    qapp.processEvents()
    canvas._begin_view_interaction()
    canvas._plot_amp.setXRange(20.0, 180.0, padding=0)
    assert canvas._spectrum_refresh_timer.isActive()
    armed = canvas._spectrum_refresh_armed_generation

    setdata_calls = _amp_setdata_log(canvas, monkeypatch)
    y_calls = []
    orig_y = canvas._auto_amplitude_y_range

    def wrapped_y(entries, xlim):
        y_calls.append(tuple(xlim))
        return orig_y(entries, xlim)

    monkeypatch.setattr(canvas, '_auto_amplitude_y_range', wrapped_y)

    canvas.full_reset()
    assert canvas._spectrum_display_generation != armed
    canvas._spectrum_refresh_timer.timeout.emit()
    assert setdata_calls == []
    assert y_calls == []
    assert canvas._amp_curves == []

    _plot_fft(canvas)
    canvas._begin_view_interaction()
    canvas._plot_amp.setXRange(30.0, 90.0, padding=0)
    _plot_fft(canvas, entry=_entry(label='next'))
    setdata_calls.clear()
    y_calls.clear()
    canvas._spectrum_refresh_timer.timeout.emit()
    assert setdata_calls == []
    assert y_calls == []


def test_wheel_ctrl_x_does_not_scan_y_on_emit_stack(canvas, qapp, monkeypatch):
    _plot_fft(canvas)
    qapp.processEvents()
    scans = _watch_callback_y_scans(canvas, monkeypatch)
    y_xlims = []
    orig_y = canvas._auto_amplitude_y_range

    def wrapped_y(entries, xlim):
        y_xlims.append((float(xlim[0]), float(xlim[1])))
        return orig_y(entries, xlim)

    monkeypatch.setattr(canvas, '_auto_amplitude_y_range', wrapped_y)

    consumed = canvas._handle_wheel_dispatch(
        delta=120, modifiers=Qt.ControlModifier, x_pos=250.0, y_pos=0.5,
        view_box=canvas._plot_amp.vb,
    )
    assert consumed is True
    assert scans == [], (
        'ctrl-wheel X zoom scanned raw Y on the interactive callback stack: '
        f'{scans!r}'
    )
    assert y_xlims == [], (
        'ctrl-wheel X zoom must coalesce; Y-scan ran immediately: '
        f'{y_xlims!r}'
    )
    assert canvas._spectrum_refresh_timer.isActive()
    assert canvas._aa_idle_timer.interval() == 150


class _FakeDrag:
    """pyqtgraph mouseDragEvent stand-in; dy=0 is a pure horizontal pan."""

    def __init__(self, pos, last, *, start=False, finish=False):
        self._pos = pg.Point(pos)
        self._last = pg.Point(last)
        self._down = pg.Point(last)
        self._start = start
        self._finish = finish

    def button(self):
        return Qt.LeftButton

    def isStart(self):
        return self._start

    def isFinish(self):
        return self._finish

    def pos(self):
        return self._pos

    def lastPos(self):
        return self._last

    def buttonDownPos(self, *_args):
        return self._down

    def accept(self):
        return None

    def ignore(self):
        return None

    def isAccepted(self):
        return True

    def modifiers(self):
        return Qt.NoModifier


def _amp_plot_body_pan(canvas, *, dx=40.0, dy=0.0):
    vb = canvas._plot_amp.vb
    down = (50.0, 40.0)
    moved = (50.0 + dx, 40.0 + dy)
    vb.mouseDragEvent(_FakeDrag(down, down, start=True), axis=None)
    vb.mouseDragEvent(_FakeDrag(moved, down), axis=None)
    vb.mouseDragEvent(_FakeDrag(moved, moved, finish=True), axis=None)


def _send_viewport_amp_drag(canvas, *, dx=25.0, dy=0.0):
    vb = canvas._plot_amp.vb
    (x0, x1), (y0, y1) = vb.viewRange()
    scene_pos = vb.mapViewToScene(QPointF((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    start = QPointF(canvas._glw.mapFromScene(scene_pos))
    end = QPointF(start.x() + dx, start.y() + dy)
    viewport = canvas._glw.viewport()
    QApplication.sendEvent(viewport, QMouseEvent(
        QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier,
    ))
    QApplication.sendEvent(viewport, QMouseEvent(
        QEvent.MouseMove, end, Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
    ))
    QApplication.sendEvent(viewport, QMouseEvent(
        QEvent.MouseButtonRelease, end, Qt.LeftButton, Qt.NoButton,
        Qt.NoModifier,
    ))


def _watch_amp_setyrange(canvas, monkeypatch):
    calls = []
    orig = pg.PlotItem.setYRange

    def wrapped(self, *args, **kwargs):
        if self is canvas._plot_amp:
            calls.append((args, kwargs))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(pg.PlotItem, 'setYRange', wrapped)
    return calls


def test_spectrum_plot_body_left_pan_is_x_only_keeps_auto_y(canvas, qapp):
    """Plot-body left pan with dy=0 must commit X only and keep auto-Y."""
    from PyQt5.QtTest import QSignalSpy

    policy = {'y_auto': True, 'viewport_origin': {'x': 'auto', 'y': 'auto'}}
    canvas.analysis_range_adapter = (lambda: policy, None)

    def _commit_origin(action, axes):
        for axis in axes:
            policy['viewport_origin'][axis] = action

    canvas.viewport_action_committed.connect(_commit_origin)
    spy = QSignalSpy(canvas.viewport_action_committed)

    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas)
    qapp.processEvents()
    x_before, y_before = canvas._plot_amp.vb.viewRange()

    _amp_plot_body_pan(canvas, dx=40.0, dy=0.0)
    qapp.processEvents()
    _send_viewport_amp_drag(canvas, dx=25.0, dy=0.0)
    qapp.processEvents()

    x_after, y_after = canvas._plot_amp.vb.viewRange()
    y_commits = [tuple(evt) for evt in spy if 'y' in tuple(evt[1])]
    assert y_commits == [], f'plot-body pan committed Y: {y_commits!r}'
    assert policy['viewport_origin']['y'] == 'auto'
    assert canvas._spectrum_y_auto is True
    assert y_after == pytest.approx(y_before)
    assert x_after != pytest.approx(x_before)


def test_spectrum_shift_wheel_pauses_auto_y(canvas, qapp):
    """A real Shift+wheel through the viewport still emits Y and pauses auto-Y."""
    from PyQt5.QtTest import QSignalSpy

    policy = {'y_auto': True, 'viewport_origin': {'x': 'auto', 'y': 'auto'}}
    canvas.analysis_range_adapter = (lambda: policy, None)

    def _commit_origin(action, axes):
        for axis in axes:
            policy['viewport_origin'][axis] = action

    canvas.viewport_action_committed.connect(_commit_origin)
    spy = QSignalSpy(canvas.viewport_action_committed)

    canvas.show()
    qapp.processEvents()
    _plot_fft(canvas)
    qapp.processEvents()
    vb = canvas._plot_amp.vb
    x_before, y_before = vb.viewRange()
    scene_pos = vb.mapViewToScene(QPointF(
        (x_before[0] + x_before[1]) / 2.0,
        (y_before[0] + y_before[1]) / 2.0,
    ))
    pos = QPointF(canvas._glw.mapFromScene(scene_pos))
    global_pos = QPointF(canvas._glw.viewport().mapToGlobal(pos.toPoint()))
    event = QWheelEvent(
        pos, global_pos, QPoint(), QPoint(0, 120), Qt.NoButton,
        Qt.ShiftModifier, Qt.ScrollUpdate, False,
    )
    assert QApplication.sendEvent(canvas._glw.viewport(), event)
    qapp.processEvents()
    x_after, y_after = vb.viewRange()

    assert x_after == pytest.approx(x_before)
    assert (y_after[1] - y_after[0]) != pytest.approx(y_before[1] - y_before[0])
    y_commits = [tuple(evt) for evt in spy if 'y' in tuple(evt[1])]
    assert y_commits, 'Shift+wheel must emit Y intent'
    assert policy['viewport_origin']['y'] == 'user'
    assert canvas._spectrum_y_auto is False


def test_fit_active_spectrum_y_skips_identical_setyrange(canvas, qapp, monkeypatch):
    canvas.show()
    qapp.processEvents()
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    _plot_fft(canvas, xlim=(0.0, 500.0))
    qapp.processEvents()
    canvas.flush_pending_spectrum_display()

    calls = _watch_amp_setyrange(canvas, monkeypatch)
    canvas._fit_active_spectrum_y()
    after_first = len(calls)
    canvas._fit_active_spectrum_y()
    assert len(calls) == after_first, (
        f'second identical _fit_active_spectrum_y called setYRange: '
        f'{calls[after_first:]!r}'
    )

    before_pan = len(calls)
    canvas._plot_amp.setXRange(-40.0, 540.0, padding=0)
    canvas.flush_pending_spectrum_display()
    issued = len(calls) - before_pan
    assert issued <= 1, (
        f'full-coverage pan issued {issued} auto-Y setYRange call(s)'
    )


def test_manual_y_fit_does_not_query_auto_amplitude(canvas, qapp, monkeypatch):
    _plot_fft(canvas)
    qapp.processEvents()
    canvas._spectrum_y_auto = False
    queries = []
    orig = canvas._auto_amplitude_y_range

    def wrapped(entries, xlim):
        queries.append((float(xlim[0]), float(xlim[1])))
        return orig(entries, xlim)

    monkeypatch.setattr(canvas, '_auto_amplitude_y_range', wrapped)
    assert canvas._fit_active_spectrum_y() is False
    assert queries == []


def test_spectrum_hit_unchanged_y_does_not_churn_quality(canvas, qapp, monkeypatch):
    canvas.show()
    qapp.processEvents()
    monkeypatch.setattr(canvas, '_spectrum_pixel_width', lambda: 400)
    _plot_fft(canvas, xlim=(0.0, 500.0))
    qapp.processEvents()
    canvas.flush_pending_spectrum_display()

    disable = []
    idle = []
    arm = []
    monkeypatch.setattr(
        canvas, 'disable_interactive_quality', lambda *a, **k: disable.append(1))
    monkeypatch.setattr(
        canvas, 'schedule_idle_quality', lambda *a, **k: idle.append(1))
    monkeypatch.setattr(canvas, '_arm_discrete_aa', lambda *a, **k: arm.append(1))
    y_calls = _watch_amp_setyrange(canvas, monkeypatch)

    canvas._plot_amp.setXRange(-20.0, 520.0, padding=0)
    disable.clear()
    idle.clear()
    arm.clear()
    y_calls.clear()
    canvas._spectrum_y_dirty = True
    canvas._run_spectrum_display_transaction(schedule_quality=True)

    assert y_calls == []
    assert disable == []
    assert idle == []
    assert arm == []
