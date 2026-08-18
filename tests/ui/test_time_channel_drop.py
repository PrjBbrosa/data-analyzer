"""Channel MIME drops onto the time-domain View and bottom X axis."""
import pytest
from PyQt5.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt5.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent

from mf4_analyzer.ui.channel_drag import INTERNAL_CHANNEL_MIME, encode_channel_drag
from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE, PER_SOURCE_NAME, CustomXAxisSpec
from tests.ui.test_split_focus_routing import _enter_split
from tests.ui.test_split_routing import (
    _has_channel,
    _make_speed_vs_torque_views,
)
from tests.ui.test_view_switch_integration import (
    _checked_pairs,
    _fid,
    _make_loaded_window,
    _narrow_xlim,
    _set_checked,
)


def _viewport(canvas):
    return canvas._glw.viewport()


def _channel_mime(fid, channel):
    mime = QMimeData()
    mime.setData(INTERNAL_CHANNEL_MIME, encode_channel_drag(fid, channel))
    return mime


def _drop_on(qapp, widget, mime, pos, *, action=Qt.CopyAction):
    enter = QDragEnterEvent(pos, action, mime, Qt.LeftButton, Qt.NoModifier)
    enter._mime_ref = mime
    qapp.sendEvent(widget, enter)
    drop = QDropEvent(QPointF(pos), action, mime, Qt.LeftButton, Qt.NoModifier)
    drop._mime_ref = mime
    qapp.sendEvent(widget, drop)
    qapp.processEvents()
    return enter, drop


def test_drop_channel_onto_plot_joins_view(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    w.navigator.set_checked_channels([])
    qapp.processEvents()

    mime = _channel_mime(fid, "speed")
    viewport = _viewport(w.canvas_time)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))
    enter, drop = _drop_on(qapp, viewport, mime, pos)

    assert enter.isAccepted()
    assert drop.isAccepted()
    assert (fid, "speed") in _checked_pairs(w)
    assert _has_channel(w.canvas_time, "speed")
    assert w.chart_stack._time_card.property("dropZone") in (None, "", False)


def test_drop_duplicate_channel_is_noop(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    mime = _channel_mime(fid, "speed")
    viewport = _viewport(w.canvas_time)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))
    _drop_on(qapp, viewport, mime, pos)

    assert _checked_pairs(w).count((fid, "speed")) == 1


def test_drop_attaches_unattached_source(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    state = w.view_manager.get(w.view_manager.active)
    state.attached_file_ids = []
    state.checked = []
    w._project_view_controls(w.view_manager.active)

    mime = _channel_mime(fid, "torque")
    viewport = _viewport(w.canvas_time)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))
    _drop_on(qapp, viewport, mime, pos)

    state = w.view_manager.get(w.view_manager.active)
    assert fid in state.attached_file_ids
    assert (fid, "torque") in {(str(a), str(b)) for a, b in state.checked}


def test_drop_routes_to_secondary_split_pane(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    _enter_split(w, qapp)
    secondary = w.chart_stack.secondary_canvas()
    secondary_idx = w._view_index_for_canvas(secondary)
    fid = _fid(w)
    before = list(w.view_manager.get(w._primary_view_idx).checked)

    mime = _channel_mime(fid, "speed")
    viewport = _viewport(secondary)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))
    _drop_on(qapp, viewport, mime, pos)

    assert w.chart_stack.focused_canvas() is secondary
    secondary_state = w.view_manager.get(secondary_idx)
    assert (fid, "speed") in {(str(a), str(b)) for a, b in secondary_state.checked}
    assert list(w.view_manager.get(w._primary_view_idx).checked) == before


def test_drop_preserves_xlim_and_existing_ylims(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()
    xlim = _narrow_xlim(w, 0.20, 0.62)
    old_ylims = dict(w.canvas_time.get_visible_ylims())

    mime = _channel_mime(fid, "torque")
    viewport = _viewport(w.canvas_time)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))
    _drop_on(qapp, viewport, mime, pos)

    restored = w.canvas_time.get_visible_xlim()
    assert restored[0] == pytest.approx(xlim[0], rel=0, abs=1e-6)
    assert restored[1] == pytest.approx(xlim[1], rel=0, abs=1e-6)
    new_ylims = w.canvas_time.get_visible_ylims()
    for key, pair in old_ylims.items():
        if key in new_ylims:
            assert new_ylims[key][0] == pytest.approx(pair[0])
            assert new_ylims[key][1] == pytest.approx(pair[1])


def test_drop_ignores_missing_channel_and_restore_guard(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    w.navigator.set_checked_channels([])
    viewport = _viewport(w.canvas_time)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))

    _drop_on(qapp, viewport, _channel_mime(fid, "no-such-channel"), pos)
    assert _checked_pairs(w) == []

    w._restoring_project = True
    try:
        _drop_on(qapp, viewport, _channel_mime(fid, "speed"), pos)
    finally:
        w._restoring_project = False
    assert _checked_pairs(w) == []


def test_xaxis_drop_rect_is_bottom_band_not_plot(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    w.resize(1400, 820)
    qapp.processEvents()

    viewport = _viewport(w.canvas_time)
    x_rect = w.chart_stack.xaxis_drop_rect(w.canvas_time)
    assert x_rect is not None
    assert x_rect.height() < viewport.height() * 0.28
    assert x_rect.top() > viewport.height() * 0.55


def test_drop_on_xaxis_applies_per_source_spec(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    qapp.processEvents()
    w.resize(1400, 820)
    qapp.processEvents()

    x_rect = w.chart_stack.xaxis_drop_rect(w.canvas_time)
    assert x_rect is not None and x_rect.height() > 0
    pos = x_rect.center()
    mime = _channel_mime(fid, "speed")
    _drop_on(qapp, _viewport(w.canvas_time), mime, pos)

    spec = w._custom_xaxis_spec
    assert spec.mode == CHANNEL_MODE
    assert spec.resolver == PER_SOURCE_NAME
    assert spec.source_fid is None
    assert spec.channel == "speed"
    assert spec.label == "speed"
    assert w.inspector.top.xaxis_mode() == "channel"
    assert w.inspector.top.xaxis_channel_data() == (PER_SOURCE_NAME, None, "speed")


def test_apply_time_xaxis_spec_matches_inspector_apply(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    qapp.processEvents()

    spec = CustomXAxisSpec(
        mode=CHANNEL_MODE,
        resolver=PER_SOURCE_NAME,
        channel="speed",
        label="speed",
    )
    w.apply_time_xaxis_spec(spec, w.canvas_time, sync_inspector=True)
    applied = w._custom_xaxis_spec
    w.inspector.top.set_xaxis_mode("channel")
    w._on_xaxis_mode_changed("channel")
    w.inspector.top.set_xaxis_channel_data((PER_SOURCE_NAME, None, "speed"))
    w.inspector.top.set_xaxis_label("speed")
    w._apply_xaxis()
    again = w._custom_xaxis_spec
    assert (applied.mode, applied.resolver, applied.channel, applied.source_fid) == (
        again.mode, again.resolver, again.channel, again.source_fid
    )


def test_drag_leave_clears_drop_highlight(qtbot, qapp, loaded_csv):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    mime = _channel_mime(fid, "speed")
    viewport = _viewport(w.canvas_time)
    pos = QPoint(max(8, viewport.width() // 2), max(8, viewport.height() // 3))
    enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    enter._mime_ref = mime
    qapp.sendEvent(viewport, enter)
    qapp.processEvents()
    assert w.chart_stack._time_card.property("dropZone") == "plot"

    leave = QDragLeaveEvent()
    qapp.sendEvent(viewport, leave)
    qapp.processEvents()
    assert w.chart_stack._time_card.property("dropZone") in (None, "", False)
