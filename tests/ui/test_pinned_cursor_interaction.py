"""Real Qt P-key routing for pinned cursors (plan Task 2 / A01–A12)."""
from __future__ import annotations

import numpy as np
import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt5.QtGui import QFocusEvent
from PyQt5.QtGui import QCursor, QKeyEvent, QMouseEvent
from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.pinned_cursor_state import empty_collection, next_record


@pytest.fixture
def production_style(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet

    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


def _plot_speed(canvas):
    t = np.linspace(0.0, 1.0, 200)
    canvas.plot_channels(
        [
            (
                "speed",
                True,
                t,
                np.sin(2 * np.pi * t),
                "#1769e0",
                "rpm",
                "fid-a",
            ),
        ],
        mode="overlay",
    )


def _make_stack(qtbot, qapp, *, mode="single"):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1100, 560)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, mode)
    _plot_speed(cs.canvas_time)
    qapp.processEvents()
    return cs


def _viewport(canvas):
    return canvas._glw.viewport()


def _plot_point(canvas, frac):
    vp = _viewport(canvas)
    return QPoint(max(8, int(vp.width() * frac)), max(8, int(vp.height() * 0.45)))


def _aim(qtbot, canvas, frac, controller=None):
    vp = _viewport(canvas)
    qtbot.waitUntil(lambda: vp.width() > 20 and vp.height() > 20, timeout=2000)
    local = _plot_point(canvas, frac)
    x = canvas.data_x_from_viewport_pos(local)
    if x is None:
        for candidate in (0.3, 0.4, 0.5, 0.6, 0.7):
            local = _plot_point(canvas, candidate)
            x = canvas.data_x_from_viewport_pos(local)
            if x is not None:
                break
    global_pos = vp.mapToGlobal(local)
    QCursor.setPos(global_pos)
    qtbot.mouseMove(vp, local)
    if controller is not None:
        controller._last_mouse_global = global_pos
    QApplication.processEvents()
    return local


def _press_p(target, *, autorepeat=False):
    override = QKeyEvent(
        QEvent.ShortcutOverride, Qt.Key_P, Qt.NoModifier, "p",
    )
    press = QKeyEvent(
        QEvent.KeyPress, Qt.Key_P, Qt.NoModifier, "p", autorepeat, 1,
    )
    QApplication.sendEvent(target, override)
    QApplication.sendEvent(target, press)
    QApplication.processEvents()
    return override


def _records(cs, canvas=None):
    canvas = cs.canvas_time if canvas is None else canvas
    collection = cs.pinned_cursors_for_canvas(canvas)
    return () if collection is None else collection.records


def _axis_label_for(cs, canvas, record_id, endpoint):
    for label in cs._pinned_cursors.axis_labels_for(canvas):
        geom = label.geom()
        if geom is None:
            continue
        if any(
            member[0] == record_id and member[1] == endpoint
            for member in geom.members
        ):
            return label
    raise AssertionError(f"missing bottom label for {record_id}/{endpoint}")


def _drag_delta():
    return max(24, QApplication.startDragDistance() + 8)


def _send_mouse(
    widget, etype, local, *, button=Qt.LeftButton, buttons=None, global_pos=None,
):
    """Dispatch a QMouseEvent that carries a real screen-space globalPos."""
    local = QPoint(local)
    window = widget.window()
    window_pos = widget.mapTo(window, local) if window is not None else QPoint(local)
    if global_pos is None:
        global_pos = widget.mapToGlobal(local)
    else:
        global_pos = QPoint(global_pos)
    if buttons is None:
        if etype == QEvent.MouseButtonRelease:
            buttons = Qt.NoButton
        elif etype == QEvent.MouseMove:
            buttons = Qt.LeftButton
        else:
            buttons = button
    event = QMouseEvent(
        etype,
        QPointF(local),
        QPointF(window_pos),
        QPointF(global_pos),
        button,
        Qt.MouseButtons(buttons),
        Qt.NoModifier,
    )
    QApplication.sendEvent(widget, event)
    return QPoint(global_pos)


def _endpoint_value(record, endpoint):
    if endpoint == "a":
        return record.ax
    if endpoint == "b":
        return record.bx
    return record.x


def _expected_committed_endpoint(cs, canvas, original, endpoint, press_global, release_global):
    overlay = canvas._pinned_overlay
    original_value = _endpoint_value(original, endpoint)
    dx = release_global.x() - press_global.x()
    viewport_pos = overlay.bottom_axis_viewport_pos_for_physical(original_value)
    viewport = canvas._glw.viewport()
    endpoint_global = viewport.mapToGlobal(viewport_pos)
    pending = QPoint(int(round(endpoint_global.x() + dx)), endpoint_global.y())
    mapped = overlay.bottom_axis_global_to_viewport(pending)
    raw = cs._pinned_cursors._physical_x(canvas, original.domain, mapped)
    controller = cs._pinned_cursors
    owner = controller._owner(canvas)
    requested = controller._commands.requested_endpoint(
        original, endpoint, raw, controller._axis_edit_bounds(owner),
    )
    sample = controller._evaluate_intent(canvas, requested)
    candidate, _sample = controller._commands.accept_endpoint_sample(
        requested, endpoint, sample,
    )
    return controller._commands.endpoint_value(candidate, endpoint)


def test_a01_mouse_over_plot_without_click_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    local = _aim(qtbot, cs.canvas_time, 0.35, cs._pinned_cursors)
    expected = cs.canvas_time.data_x_from_viewport_pos(local)
    feedback = []
    cs.pin_feedback.connect(feedback.append)

    override = _press_p(vp)

    assert override.isAccepted()
    records = _records(cs)
    assert len(records) == 1
    assert records[0].mode == "single"
    assert records[0].domain == "time"
    assert records[0].ordinal == 1
    assert records[0].x == pytest.approx(expected)
    assert any("P1 已固定" in item for item in feedback)
    pills = cs._pinned_cursors.pills_for(cs.canvas_time)
    assert len(pills) == 1
    assert records[0].panel_expanded is False
    assert pills[0].isVisible() is False
    assert pills[0].pin_role() == "pinned"


def test_a02_p_uses_latest_physical_x_not_throttled_pill(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.25, cs._pinned_cursors)
    local = _aim(qtbot, cs.canvas_time, 0.72, cs._pinned_cursors)
    expected = cs.canvas_time.data_x_from_viewport_pos(local)
    sample = cs.canvas_time._cursor.evaluate_single_cursor_sample(expected)

    _press_p(vp)

    records = _records(cs)
    assert len(records) == 1
    assert records[0].x == pytest.approx(expected)
    assert sample is not None
    assert records[0].x == pytest.approx(sample.x)


def test_a03_autorepeat_and_same_point_do_not_duplicate(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    _press_p(vp)
    _press_p(vp, autorepeat=True)
    _press_p(vp)
    assert len(_records(cs)) == 1

    _aim(qtbot, cs.canvas_time, 0.75, cs._pinned_cursors)
    _press_p(vp)
    assert len(_records(cs)) == 2
    xs = sorted(item.x for item in _records(cs))
    assert xs[1] - xs[0] > 0.05


def test_a05_dual_none_a_only_complete_equal_and_reversed(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    vp = _viewport(cs.canvas_time)
    cursor = cs.canvas_time._cursor
    feedback = []
    cs.pin_feedback.connect(feedback.append)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)

    _press_p(vp)
    assert _records(cs) == ()
    assert any("A" in item or "B" in item for item in feedback)

    cursor._ax = 0.20
    cursor._bx = None
    cursor._placing = "B"
    feedback.clear()
    _press_p(vp)
    assert _records(cs) == ()
    assert any("先放置 B" in item for item in feedback)

    cursor._bx = 0.80
    _press_p(vp)
    records = _records(cs)
    assert len(records) == 1
    assert records[0].mode == "dual"
    assert records[0].ax == pytest.approx(0.20)
    assert records[0].bx == pytest.approx(0.80)
    placement = cs.canvas_time.snapshot_cursor_placement()
    assert placement["ax"] == pytest.approx(0.20)
    assert placement["bx"] == pytest.approx(0.80)

    t = np.linspace(0.0, 1.0, 200)
    same = float(t[100])
    cursor._ax = same
    cursor._bx = same
    _press_p(vp)
    records = _records(cs)
    assert len(records) == 2
    equal = records[1]
    assert equal.ax == pytest.approx(equal.bx)

    cursor._ax = 0.90
    cursor._bx = 0.10
    _press_p(vp)
    reversed_pin = _records(cs)[2]
    assert reversed_pin.ax == pytest.approx(0.90)
    assert reversed_pin.bx == pytest.approx(0.10)


def test_a08_off_does_not_create_and_keeps_existing_pins(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    _press_p(vp)
    assert len(_records(cs)) == 1

    cs.set_cursor_mode("off")
    qapp.processEvents()
    override = _press_p(vp)
    assert not override.isAccepted()
    assert len(_records(cs)) == 1
    pills = cs._pinned_cursors.pills_for(cs.canvas_time)
    assert pills and pills[0].isVisible() is False
    assert not cs.cursor_pill_visible()


def test_a12_mouse_target_not_focus_and_text_and_ultraview(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    cs.enter_split()
    qapp.processEvents()
    secondary = cs.secondary_canvas()
    _plot_speed(secondary)
    cs.set_cursor_mode_for_canvas(secondary, "single")
    qapp.processEvents()

    cs.set_focused_card(cs._time_card)
    _aim(qtbot, secondary, 0.4, cs._pinned_cursors)
    _press_p(_viewport(secondary))
    assert _records(cs, cs.canvas_time) == ()
    assert len(_records(cs, secondary)) == 1

    edit = QLineEdit(cs)
    edit.setGeometry(8, 8, 160, 24)
    edit.show()
    edit.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    before = len(_records(cs, secondary))
    _aim(qtbot, secondary, 0.7, cs._pinned_cursors)
    override = _press_p(_viewport(secondary))
    assert not override.isAccepted()
    assert len(_records(cs, secondary)) == before

    cs.stack.setCurrentWidget(cs.page_ultraview)
    qapp.processEvents()
    uv = cs.page_ultraview
    qtbot.mouseMove(uv, uv.rect().center())
    cs._pinned_cursors._last_mouse_global = uv.mapToGlobal(uv.rect().center())
    override = _press_p(uv)
    assert not override.isAccepted()


def test_gesture_in_progress_does_not_pin(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    vp = _viewport(cs.canvas_time)
    local = _aim(qtbot, cs.canvas_time, 0.4, cs._pinned_cursors)
    qtbot.mousePress(vp, Qt.LeftButton, pos=local)
    qapp.processEvents()
    override = _press_p(vp)
    assert not override.isAccepted()
    assert _records(cs) == ()
    qtbot.mouseRelease(vp, Qt.LeftButton, pos=local)


def test_bottom_label_drag_previews_without_dirty_then_commits_once(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.35, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    before_capture = controller.capture_fingerprint_for(canvas)
    revisions = []
    transaction_states = []
    controller.intent_changed.connect(lambda: revisions.append(controller.user_intent_revision))
    controller.axis_edit_state_changed.connect(
        lambda observed, active: transaction_states.append(active)
        if observed is canvas else None
    )
    label = _axis_label_for(cs, canvas, original.record_id, "x")
    start = label.rect().center()

    qtbot.mousePress(label, Qt.LeftButton, pos=start)
    qtbot.mouseMove(label, QPoint(start.x() + _drag_delta(), start.y()))
    qapp.processEvents()
    qapp.processEvents()

    owner = controller._owner(canvas)
    assert owner.axis_edit is not None
    assert owner.axis_edit.record_id == original.record_id
    assert controller.is_axis_edit_active(canvas)
    assert controller.axis_edit_is_settled(canvas) is False
    assert _records(cs)[0].x == pytest.approx(original.x)
    assert controller.capture_fingerprint_for(canvas) == before_capture
    assert revisions == []
    assert transaction_states == [True]

    qtbot.mouseRelease(
        label, Qt.LeftButton, pos=QPoint(start.x() + _drag_delta(), start.y()),
    )
    qapp.processEvents()

    moved = _records(cs)[0]
    assert moved.x != pytest.approx(original.x)
    assert moved.panel_expanded is False
    assert owner.axis_edit is None
    assert controller.is_axis_edit_active(canvas) is False
    assert controller.axis_edit_is_settled(canvas)
    assert revisions == [controller.user_intent_revision]
    assert transaction_states == [True, False]


def test_bottom_label_direct_release_commits_without_a_mouse_move(qapp, qtbot):
    """A rapid press/release still owns the release coordinate as a drag."""
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.35, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    revisions = []
    controller.intent_changed.connect(
        lambda: revisions.append(controller.user_intent_revision)
    )
    label = _axis_label_for(cs, canvas, original.record_id, "x")
    start = label.rect().center()
    release = QPoint(start.x() + _drag_delta(), start.y())

    qtbot.mousePress(label, Qt.LeftButton, pos=start)
    # No intermediate mouse move: this is the reported fast-drop path.
    qtbot.mouseRelease(label, Qt.LeftButton, pos=release)
    qapp.processEvents()

    moved = _records(cs)[0]
    assert moved.x != pytest.approx(original.x)
    assert moved.panel_expanded is False
    assert revisions == [controller.user_intent_revision]
    assert not controller.is_axis_edit_active(canvas)


def test_bottom_label_drag_escape_and_cursor_mode_cancel_are_zero_dirty(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.45, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    revisions = []
    transaction_states = []
    controller.intent_changed.connect(lambda: revisions.append(controller.user_intent_revision))
    controller.axis_edit_state_changed.connect(
        lambda observed, active: transaction_states.append(active)
        if observed is canvas else None
    )
    label = _axis_label_for(cs, canvas, original.record_id, "x")
    start = label.rect().center()

    qtbot.mousePress(label, Qt.LeftButton, pos=start)
    qtbot.mouseMove(label, QPoint(start.x() + _drag_delta(), start.y()))
    qapp.processEvents()
    qtbot.keyClick(label, Qt.Key_Escape)
    qapp.processEvents()
    assert controller._owner(canvas).axis_edit is None
    assert _records(cs)[0].x == pytest.approx(original.x)
    assert revisions == []
    assert transaction_states == [True, False]

    qtbot.mousePress(label, Qt.LeftButton, pos=start)
    qtbot.mouseMove(label, QPoint(start.x() + _drag_delta(), start.y()))
    qapp.processEvents()
    cs.set_cursor_mode_for_canvas(canvas, "off")
    qapp.processEvents()
    assert controller._owner(canvas).axis_edit is None
    assert _records(cs)[0].x == pytest.approx(original.x)
    assert revisions == []
    assert transaction_states == [True, False, True, False]
    qtbot.mouseRelease(label, Qt.LeftButton, pos=start)


def test_bottom_label_arrow_uses_time_domain_millisecond_step(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.5, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    revisions = []
    controller.intent_changed.connect(lambda: revisions.append(controller.user_intent_revision))
    label = _axis_label_for(cs, canvas, original.record_id, "x")

    label.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(label, Qt.Key_Right)
    qapp.processEvents()

    moved = _records(cs)[0]
    assert moved.x == pytest.approx(original.x + 0.001)
    assert revisions == [controller.user_intent_revision]


def test_bottom_label_arrow_uses_custom_x_pixel_mapping(qapp, qtbot):
    from tests.ui.test_custom_x_cursor_contract import _plot_custom_x

    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    x = np.linspace(0.0, 10.0, 201)
    _plot_custom_x(
        canvas,
        [("speed", True, x, np.sin(x), "#1769e0", "rpm", "fid-a")],
        unit="mm",
        label="travel",
        identity=("fid-a", "travel"),
    )
    _aim(qtbot, canvas, 0.5, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    assert original.domain == "channel"
    label = _axis_label_for(cs, canvas, original.record_id, "x")

    label.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(label, Qt.Key_Right)
    qapp.processEvents()

    moved = _records(cs)[0]
    assert moved.x > original.x
    assert moved.x - original.x != pytest.approx(0.001)


def test_bottom_label_arrow_uses_next_effective_fft_frequency(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    cs.set_mode("fft")
    canvas = cs.canvas_fft
    cs.set_cursor_mode_for_canvas(canvas, "single")
    frequencies = np.array([1.0, 10.0, 50.0, 100.0, 200.0])
    canvas.plot_spectra(
        [{
            "freq": frequencies,
            "amp": np.arange(1.0, 6.0),
            "label": "force",
            "channel": "force",
            "fid": "fid-a",
            "color": "#2563eb",
            "time": np.linspace(0.0, 1.0, 8),
            "signal": np.zeros(8),
        }],
        xlim=(0.0, 200.0), amp_label="Amplitude", title="FFT",
    )
    collection, _ = next_record(empty_collection(), {
        "mode": "single",
        "domain": "frequency",
        "x": 50.0,
        "x_unit": "Hz",
        "bindings": [{"fid": "fid-a", "channel": "force"}],
    })
    cs.set_pinned_cursors_for_canvas(canvas, collection)
    qapp.processEvents()
    original = _records(cs, canvas)[0]
    assert cs._pinned_cursors.availability_for(canvas, original.record_id) == "ready"
    label = _axis_label_for(cs, canvas, original.record_id, "x")

    label.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(label, Qt.Key_Right)
    qapp.processEvents()

    assert _records(cs, canvas)[0].x == pytest.approx(100.0)


def test_bottom_label_arrow_keeps_frf_log_frequency_in_hz(qapp, qtbot):
    from tests.ui.test_pinned_cursor_geometry import _frf_result

    cs = _make_stack(qtbot, qapp)
    cs.set_mode("frf")
    canvas = cs.canvas_frf
    cs.set_cursor_mode_for_canvas(canvas, "single")
    canvas.set_result(
        _frf_result(log=True),
        {"frequency_scale": "log", "magnitude_scale": "linear"},
        {},
    )
    collection, _ = next_record(empty_collection(), {
        "mode": "single",
        "domain": "frf",
        "x": 10.0,
        "x_unit": "Hz",
        "bindings": [{"fid": "fid-a", "channel": "force"}],
    })
    cs.set_pinned_cursors_for_canvas(canvas, collection)
    qapp.processEvents()
    original = _records(cs, canvas)[0]
    assert cs._pinned_cursors.availability_for(canvas, original.record_id) == "ready"
    label = _axis_label_for(cs, canvas, original.record_id, "x")

    label.setFocus(Qt.OtherFocusReason)
    qtbot.keyClick(label, Qt.Key_Right)
    qapp.processEvents()

    assert _records(cs, canvas)[0].x == pytest.approx(100.0)


def test_coincident_dual_members_expose_separate_a_b_targets(qapp, qtbot):
    cs = _make_stack(qtbot, qapp, mode="dual")
    canvas = cs.canvas_time
    collection, _ = next_record(empty_collection(), {
        "mode": "dual",
        "domain": "time",
        "ax": 0.4,
        "bx": 0.4,
        "x_unit": "s",
        "bindings": [{"fid": "fid-a", "channel": "speed"}],
    })
    cs.set_pinned_cursors_for_canvas(canvas, collection)
    qapp.processEvents()
    original = _records(cs)[0]
    label = _axis_label_for(cs, canvas, original.record_id, "a")
    QApplication.sendEvent(label, QEvent(QEvent.Enter))
    qapp.processEvents()
    a_button = next(
        button for button in label._buttons
        if button.property("endpoint") == "a"
    )
    b_button = next(
        button for button in label._buttons
        if button.property("endpoint") == "b"
    )
    assert a_button.property("record_id") == original.record_id
    assert b_button.property("record_id") == original.record_id
    assert a_button is not b_button


def test_queued_layout_keeps_committed_user_anchor_and_ignores_drag_reflow(
    qapp, qtbot,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.35, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    record = _records(cs)[0]
    controller = cs._pinned_cursors
    controller.toggle_record_panel(canvas, record.record_id)
    controller.flush_layout(canvas)
    qapp.processEvents()
    pill = controller.pills_for(canvas)[0]
    start_pos = QPoint(pill.pos())
    controller.reflow_visible()
    pending = controller._projector._pending_owners
    assert pending
    assert all(len(item) == 2 for item in pending)

    start = pill.rect().center()
    delta = QPoint(36, 28)
    _send_mouse(pill, QEvent.MouseButtonPress, start)
    _send_mouse(pill, QEvent.MouseMove, start + delta)
    qapp.processEvents()
    dragged = QPoint(pill.pos())
    assert pill.is_dragging()
    assert dragged != start_pos
    controller.reflow_visible()
    qapp.processEvents()
    assert pill.pos() == dragged
    _send_mouse(pill, QEvent.MouseButtonRelease, start + delta)
    qapp.processEvents()
    qapp.processEvents()
    controller.flush_layout(canvas)
    qapp.processEvents()

    committed = _records(cs)[0]
    assert pill.is_user_placed()
    assert committed.anchor != record.anchor
    expected = controller._projector._pos_from_anchor(
        committed.anchor, pill, pill.safe_rect(),
    )
    assert pill.pos() == QPoint(*expected)
    assert pill.pos() != start_pos


@pytest.mark.parametrize(
    "mode,payload,endpoint,other",
    [
        ("single", {"x": 0.35}, "x", None),
        ("dual", {"ax": 0.25, "bx": 0.75}, "a", "b"),
        ("dual", {"ax": 0.25, "bx": 0.75}, "b", "a"),
        ("dual", {"ax": 0.42, "bx": 0.42}, "a", "b"),
        ("dual", {"ax": 0.80, "bx": 0.20}, "a", "b"),
    ],
)
def test_bottom_label_release_commits_the_expected_sample(
    qapp, qtbot, mode, payload, endpoint, other,
):
    cs = _make_stack(qtbot, qapp, mode=mode)
    canvas = cs.canvas_time
    collection, _ = next_record(empty_collection(), {
        "mode": mode,
        "domain": "time",
        "x_unit": "s",
        "bindings": [{"fid": "fid-a", "channel": "speed"}],
        **payload,
    })
    cs.set_pinned_cursors_for_canvas(canvas, collection)
    qapp.processEvents()
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    revisions = []
    controller.intent_changed.connect(
        lambda: revisions.append(controller.user_intent_revision)
    )
    label = _axis_label_for(cs, canvas, original.record_id, endpoint)
    target = label
    if label.geom() is not None and label.geom().kind == "cluster":
        QApplication.sendEvent(label, QEvent(QEvent.Enter))
        qapp.processEvents()
        target = next(
            button for button in label._buttons
            if button.property("endpoint") == endpoint
        )
    start = target.rect().center()
    release = QPoint(start.x() + _drag_delta(), start.y())
    press_global = _send_mouse(target, QEvent.MouseButtonPress, start)
    move_global = QPoint(press_global.x() + 8, press_global.y())
    _send_mouse(
        target, QEvent.MouseMove, QPoint(start.x() + 8, start.y()),
        global_pos=move_global,
    )
    release_global = QPoint(press_global.x() + _drag_delta(), press_global.y())
    _send_mouse(
        target, QEvent.MouseButtonRelease, release, global_pos=release_global,
    )
    qapp.processEvents()

    moved = _records(cs)[0]
    expected = _expected_committed_endpoint(
        cs, canvas, original, endpoint, press_global, release_global,
    )
    assert _endpoint_value(moved, endpoint) == pytest.approx(expected, abs=1e-9)
    assert revisions == [controller.user_intent_revision]
    if other is not None:
        assert _endpoint_value(moved, other) == pytest.approx(
            _endpoint_value(original, other)
        )
    assert moved.panel_expanded is False
    assert not controller.is_axis_edit_active(canvas)


def test_bottom_label_click_within_threshold_toggles_without_commit(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.4, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    revisions = []
    controller.intent_changed.connect(
        lambda: revisions.append(controller.user_intent_revision)
    )
    label = _axis_label_for(cs, canvas, original.record_id, "x")
    start = label.rect().center()
    jitter = max(1, QApplication.startDragDistance() - 1)
    _send_mouse(label, QEvent.MouseButtonPress, start)
    _send_mouse(label, QEvent.MouseButtonRelease, QPoint(start.x() + jitter, start.y()))
    qapp.processEvents()
    moved = _records(cs)[0]
    assert moved.x == pytest.approx(original.x)
    assert moved.panel_expanded is True
    assert revisions == [controller.user_intent_revision]


def test_bottom_label_release_coordinate_wins_over_last_move(qapp, qtbot):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.3, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    label = _axis_label_for(cs, canvas, original.record_id, "x")
    start = label.rect().center()
    move = QPoint(start.x() + _drag_delta(), start.y())
    release = QPoint(start.x() + _drag_delta() * 2, start.y())
    press_global = _send_mouse(label, QEvent.MouseButtonPress, start)
    _send_mouse(label, QEvent.MouseMove, move)
    qapp.processEvents()
    release_global = _send_mouse(label, QEvent.MouseButtonRelease, release)
    qapp.processEvents()
    moved = _records(cs)[0]
    expected = _expected_committed_endpoint(
        cs, canvas, original, "x", press_global, release_global,
    )
    moved_from_last_move = _expected_committed_endpoint(
        cs, canvas, original, "x", press_global, label.mapToGlobal(move),
    )
    assert moved.x == pytest.approx(expected, abs=1e-9)
    assert moved.x != pytest.approx(moved_from_last_move, abs=1e-6)


def test_pill_drag_keeps_tether_emphasis_across_child_leave(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.35, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    record = _records(cs)[0]
    controller = cs._pinned_cursors
    controller.toggle_record_panel(canvas, record.record_id)
    controller.flush_layout(canvas)
    qapp.processEvents()
    pill = controller.pills_for(canvas)[0]
    overlay = canvas._pinned_overlay
    assert overlay.tether_items()
    idle_pen = overlay.tether_items()[0].pen()
    idle_width = idle_pen.widthF()
    idle_alpha = idle_pen.color().alpha()
    QApplication.sendEvent(pill, QEvent(QEvent.Enter))
    qapp.processEvents()
    start = pill.rect().center()
    _send_mouse(pill, QEvent.MouseButtonPress, start)
    qapp.processEvents()
    assert pill.is_dragging()
    assert overlay.highlight_id() == record.record_id
    active_pen = overlay.tether_items()[0].pen()
    assert active_pen.widthF() > idle_width
    assert active_pen.color().alpha() > idle_alpha
    QApplication.sendEvent(pill, QEvent(QEvent.Leave))
    QApplication.sendEvent(pill._pin_btn, QEvent(QEvent.Enter))
    qapp.processEvents()
    assert pill.is_dragging()
    assert overlay.highlight_id() == record.record_id
    still_active = overlay.tether_items()[0].pen()
    assert still_active.widthF() == pytest.approx(active_pen.widthF())
    assert still_active.color().alpha() == active_pen.color().alpha()
    _send_mouse(pill, QEvent.MouseButtonRelease, start + QPoint(12, 8))
    qapp.processEvents()


def test_axis_label_capture_leave_keeps_emphasis_then_resynthesizes(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.4, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    original = _records(cs)[0]
    controller = cs._pinned_cursors
    overlay = canvas._pinned_overlay
    projector = controller._projector
    label = _axis_label_for(cs, canvas, original.record_id, "x")
    QApplication.sendEvent(label, QEvent(QEvent.Enter))
    qapp.processEvents()
    start = label.rect().center()
    qtbot.mousePress(label, Qt.LeftButton, pos=start)
    qapp.processEvents()
    state = projector._states[id(canvas)]
    assert state.capture_target == original.record_id
    assert overlay.highlight_id() == original.record_id
    assert label._highlighted is True
    QApplication.sendEvent(label, QEvent(QEvent.Leave))
    qapp.processEvents()
    assert state.capture_target == original.record_id
    assert overlay.highlight_id() == original.record_id
    assert label._highlighted is True
    release = QPoint(start.x() + _drag_delta(), start.y())
    qtbot.mouseRelease(label, Qt.LeftButton, pos=release)
    qapp.processEvents()
    assert original.record_id in str(overlay.highlight_id() or "")
    assert _records(cs)[0].panel_expanded is False
    label.clearFocus()
    QApplication.sendEvent(label, QFocusEvent(QEvent.FocusOut, Qt.OtherFocusReason))
    QApplication.sendEvent(label, QEvent(QEvent.Leave))
    qapp.processEvents()
    qapp.processEvents()
    assert overlay.highlight_id() in (None, "", (), [])
    assert label._highlighted is False


def test_axis_label_child_enter_does_not_drop_capture_emphasis(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.42, cs._pinned_cursors)
    for frac in (0.40, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47):
        _aim(qtbot, canvas, frac, cs._pinned_cursors)
        _press_p(_viewport(canvas))
    qapp.processEvents()
    overlay = canvas._pinned_overlay
    clusters = [
        label for label in cs._pinned_cursors.axis_labels_for(canvas)
        if label.geom() is not None and label.geom().kind == "cluster"
    ]
    assert clusters
    cluster = clusters[0]
    QApplication.sendEvent(cluster, QEvent(QEvent.Enter))
    qapp.processEvents()
    member_buttons = [
        child for child in cluster.findChildren(QPushButton)
        if child.objectName() == "pinnedAxisLabelMember"
    ]
    assert member_buttons
    member = member_buttons[0]
    start = member.rect().center()
    qtbot.mousePress(member, Qt.LeftButton, pos=start)
    qapp.processEvents()
    highlighted = overlay.highlight_id()
    assert highlighted not in (None, "", (), [])
    QApplication.sendEvent(cluster, QEvent(QEvent.Leave))
    QApplication.sendEvent(member, QEvent(QEvent.Enter))
    qapp.processEvents()
    assert overlay.highlight_id() == highlighted
    assert cluster._highlighted is True
    qtbot.mouseRelease(member, Qt.LeftButton, pos=start)
    qapp.processEvents()


def test_pill_mode_button_focus_does_not_drop_emphasis_after_capture(
    qapp, qtbot, production_style,
):
    cs = _make_stack(qtbot, qapp)
    canvas = cs.canvas_time
    _aim(qtbot, canvas, 0.36, cs._pinned_cursors)
    _press_p(_viewport(canvas))
    record = _records(cs)[0]
    controller = cs._pinned_cursors
    controller.toggle_record_panel(canvas, record.record_id)
    controller.flush_layout(canvas)
    qapp.processEvents()
    pill = controller.pills_for(canvas)[0]
    overlay = canvas._pinned_overlay
    projector = controller._projector
    QApplication.sendEvent(pill, QEvent(QEvent.Enter))
    start = pill.rect().center()
    _send_mouse(pill, QEvent.MouseButtonPress, start)
    qapp.processEvents()
    assert overlay.highlight_id() == record.record_id
    mode_btn = pill._mode_control.button_for("full")
    mode_btn.setFocus(Qt.TabFocusReason)
    QApplication.sendEvent(pill, QFocusEvent(QEvent.FocusOut, Qt.TabFocusReason))
    qapp.processEvents()
    qapp.processEvents()
    assert overlay.highlight_id() == record.record_id
    _send_mouse(pill, QEvent.MouseButtonRelease, start)
    qapp.processEvents()
    qapp.processEvents()
    state = projector._states[id(canvas)]
    assert state.capture_target in (None, "", (), [])
    assert overlay.highlight_id() == record.record_id
