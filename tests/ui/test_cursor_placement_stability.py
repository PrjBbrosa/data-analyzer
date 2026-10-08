"""Continuous pin updates publish settled geometry and reserve actual panel size."""
from dataclasses import replace

import numpy as np
from PyQt5.QtCore import QRect

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.pinned_cursor_state import (
    PinnedCursorAnchor, empty_collection, next_record,
)


def _stack_with_pins(qtbot, qapp, count=1):
    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.resize(1100, 640)
    stack.show()
    qtbot.waitExposed(stack)
    canvas = stack.canvas_time
    time = np.linspace(0, 1, 200)
    canvas.plot_channels([
        ("torque", True, time, np.sin(time), "#16a34a", "Nm", "source"),
    ], mode="overlay")
    qapp.processEvents()
    collection = empty_collection()
    for index in range(count):
        collection, _ = next_record(collection, {
            "domain": "time", "mode": "single", "x": 0.3 + index * 0.2,
            "x_unit": "s", "bindings": [{"fid": "source", "channel": "torque"}],
            "panel_expanded": True,
        })
    stack.set_pinned_cursors_for_canvas(canvas, collection)
    qapp.processEvents()
    controller = stack._pinned_cursors
    for intent in stack.pinned_cursors_for_canvas(canvas).records:
        if not intent.panel_expanded:
            controller.toggle_record_panel(canvas, intent.record_id)
    qapp.processEvents()
    controller.flush_layout()
    collection = stack.pinned_cursors_for_canvas(canvas)
    return stack, canvas, controller, collection


def test_growing_pin_updates_occupied_rect_before_preserving_neighbors(qtbot, qapp):
    stack, canvas, controller, collection = _stack_with_pins(qtbot, qapp, 2)
    projector = controller._projector
    state = projector.state_for(id(canvas))
    pills = [state.pills[record.record_id] for record in collection.records]
    safe = pills[0].safe_rect()
    for index, pill in enumerate(pills):
        pill.setFixedSize(100, 100)
        pill.move(safe.left() + index * 120, safe.top())
        pill.show()
        state.auto_panel_rects[collection.records[index].record_id] = QRect(pill.geometry())
    state.auto_panel_safe_rect = QRect(safe)
    pills[0].setFixedSize(170, 100)
    projector.arrange_pinned_panels(id(canvas), canvas, collection)
    assert all(pill.isVisible() and safe.contains(pill.geometry()) for pill in pills)
    assert not pills[0].geometry().intersects(pills[1].geometry())
    for record, pill in zip(collection.records, pills):
        assert state.auto_panel_rects[record.record_id] == pill.geometry()


def test_content_update_publishes_only_final_bottom_anchor(qtbot, qapp, monkeypatch):
    stack, canvas, controller, collection = _stack_with_pins(qtbot, qapp)
    projector = controller._projector
    intent = replace(collection.records[0], anchor=PinnedCursorAnchor(
        h_edge="right", v_edge="bottom", nx=1.0, ny=1.0,
    ))
    collection = replace(collection, records=(intent,))
    pill = projector.pill_for(id(canvas), intent.record_id)
    pill.mark_user_placed(True)
    projector.apply_anchor(pill, collection, pill_record_id=intent.record_id)
    assert pill.isVisible()
    assert projector.state_for(id(canvas)).canvas is canvas
    assert not projector._in_layout
    before_size = pill.size()
    published = []
    overlay = canvas._pinned_overlay
    original = type(overlay).set_tethers

    def record(target, tethers):
        if target is overlay:
            published.append(tuple(tethers))
        original(target, tethers)

    monkeypatch.setattr(type(overlay), "set_tethers", record)
    monkeypatch.setattr(projector, "pill_content", lambda *_args: (
        "P1<br>t=31.5925s<br>unavailable: acquisition gap", None,
    ))
    projector.project_record(
        id(canvas), canvas, intent, None, collection=collection,
    )
    assert pill.geometry().bottomRight() == pill.safe_rect().bottomRight()
    mapped = projector._map_stack_rect_to_canvas(canvas, pill.parentWidget(), pill.geometry())
    expected = tuple(float(value) for value in mapped.getRect())
    assert pill.size() != before_size
    assert len(published) == 1
    assert len(published[0]) == 1
    assert published[0][0].panel_rect == expected
    assert collection.records[0].anchor == intent.anchor


def test_display_update_preserves_saved_bottom_anchor(qtbot, qapp):
    from types import SimpleNamespace
    from mf4_analyzer.ui.cursor_display_model import CursorDisplayChannel

    stack, canvas, controller, collection = _stack_with_pins(qtbot, qapp)
    projector = controller._projector
    intent = replace(collection.records[0], anchor=PinnedCursorAnchor(
        h_edge="right", v_edge="bottom", nx=0.8, ny=0.65,
    ))
    collection = replace(collection, records=(intent,))
    pill = projector.pill_for(id(canvas), intent.record_id)
    pill.mark_user_placed(True)
    projector.apply_anchor(pill, collection, pill_record_id=intent.record_id)
    previous_bottom_right = pill.geometry().bottomRight()
    old_height = pill.height()
    sample = SimpleNamespace(channels=tuple(
        CursorDisplayChannel(
            identity=("source", f"torque {index}"), source_label="source",
            channel_label=f"torque {index}", unit_suffix="Nm", current_value=1.8,
        ) for index in range(4)
    ))
    projector.update_display_projection(
        id(canvas), canvas, intent, sample, "ready", collection,
    )
    assert pill.height() > old_height
    assert pill.geometry().bottomRight() == previous_bottom_right


def test_grown_panel_near_safe_edge_relocates_without_overflow(qtbot, qapp):
    stack, canvas, controller, collection = _stack_with_pins(qtbot, qapp)
    projector = controller._projector
    state = projector.state_for(id(canvas))
    intent = collection.records[0]
    pill = state.pills[intent.record_id]
    safe = pill.safe_rect()
    pill.setFixedSize(100, 100)
    pill.move(safe.right() - 99, safe.bottom() - 99)
    state.auto_panel_rects[intent.record_id] = QRect(pill.geometry())
    state.auto_panel_safe_rect = QRect(safe)
    pill.setFixedSize(170, 140)
    projector.arrange_pinned_panels(id(canvas), canvas, collection)
    assert pill.isVisible()
    assert safe.contains(pill.geometry())
    assert state.auto_panel_rects[intent.record_id] == pill.geometry()
