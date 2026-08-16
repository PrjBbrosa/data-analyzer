"""Dual-cursor data-space placement snapshot/restore (spec D3/D4)."""

from __future__ import annotations

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.pg_canvas.cursor import CursorController


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
    canvas.plot_channels(
        [("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-1")],
        mode="subplot",
    )
    QCoreApplication.processEvents()
    return canvas


def _visible_display_names(canvas):
    hidden = canvas._cursor._hidden_channel_names()
    data = canvas.channel_data
    if hasattr(data, "composite_items"):
        return [
            ch for _ck, ch, _values in data.composite_items() if ch not in hidden
        ]
    return [ch for ch, _values in data.items() if ch not in hidden]


def _capture_dual_pill(canvas):
    last = {"info": None, "rows": None}

    def on_info(text):
        last["info"] = text

    def on_rows(rows):
        last["rows"] = rows

    canvas.dual_cursor_info.connect(on_info)
    canvas.dual_cursor_rows.connect(on_rows)
    return last


def _place_dual_ab(canvas, ax=0.25, bx=0.75):
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    CursorController.restore_placement(canvas._cursor, {"ax": ax, "bx": bx})
    QCoreApplication.processEvents()


def test_single_cursor_mode_snapshot_is_none(qapp):
    canvas = _pg_canvas(qapp)
    canvas.set_cursor_visible(True)
    cursor = canvas._cursor
    cursor._ax = 0.40
    cursor._bx = 0.70
    assert cursor.snapshot_placement() is None
    assert CursorController.snapshot_placement(cursor) is None


def test_dual_placed_a_and_b_snapshot_has_ax_bx(qapp):
    canvas = _pg_canvas(qapp)
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    cursor = canvas._cursor
    cursor._ax = 0.25
    cursor._bx = 0.75
    assert cursor.snapshot_placement() == {"ax": pytest.approx(0.25), "bx": pytest.approx(0.75)}
    cursor._bx = None
    assert cursor.snapshot_placement() == {"ax": pytest.approx(0.25), "bx": None}


def test_reset_cursor_state_clears_snapshot(qapp):
    canvas = _pg_canvas(qapp)
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    cursor = canvas._cursor
    cursor._ax = 0.25
    cursor._bx = 0.75
    canvas.reset_cursor_state()
    assert cursor.snapshot_placement() is None
    assert cursor._ax is None
    assert cursor._bx is None


def test_restore_placement_with_dual_on_redraws_a_b_lines(qapp):
    canvas = _pg_canvas(qapp)
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(True)
    cursor = canvas._cursor
    CursorController.restore_placement(cursor, {"ax": 0.30, "bx": 0.80})
    assert cursor._ax == pytest.approx(0.30)
    assert cursor._bx == pytest.approx(0.80)
    a_items = cursor._cursor_a_items
    b_items = cursor._cursor_b_items
    assert a_items
    assert b_items
    assert all(item.isVisible() for item in a_items)
    assert all(item.isVisible() for item in b_items)
    assert [item.value() for item in a_items] == pytest.approx([0.30] * len(a_items))
    assert [item.value() for item in b_items] == pytest.approx([0.80] * len(b_items))


def test_invalid_restore_does_not_turn_dual_off(qapp):
    canvas = _pg_canvas(qapp)
    canvas.set_dual_cursor_mode(True)
    cursor = canvas._cursor
    cursor._ax = 0.10
    cursor.restore_placement(None)
    cursor.restore_placement({"ax": float("nan"), "bx": 0.5})
    cursor.restore_placement("not-a-dict")
    assert cursor._dual is True
    assert cursor._ax == pytest.approx(0.10)


def test_dual_placed_a_and_b_pill_rows_match_visible_channels(qapp):
    canvas = _pg_canvas(qapp)
    last = _capture_dual_pill(canvas)
    _place_dual_ab(canvas)
    visible = _visible_display_names(canvas)
    rows = last["rows"] or []
    assert visible
    assert len(rows) == len(visible)
    blob = (last["info"] or "") + " ".join(str(row[0]) for row in rows)
    for name in visible:
        assert name in blob


def test_plot_channels_recomputes_dual_pill_for_new_channel(qapp):
    canvas = _pg_canvas(qapp)
    last = _capture_dual_pill(canvas)
    _place_dual_ab(canvas)
    assert len(last["rows"] or []) == 1

    t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
    canvas.plot_channels(
        [
            ("speed", True, t, np.sin(2 * np.pi * t), "#1769e0", "rpm", "fid-1"),
            ("torque", True, t, np.cos(2 * np.pi * t), "#dc2626", "Nm", "fid-1"),
        ],
        mode="subplot",
    )
    QCoreApplication.processEvents()
    rows = last["rows"] or []
    assert len(rows) == 2, (
        f"pill row count stayed {len(rows)} after adding a channel"
    )
    blob = (last["info"] or "") + " ".join(str(row[0]) for row in rows)
    assert "torque" in blob


def test_off_then_dual_keeps_placement_and_restores_pill(qapp):
    canvas = _pg_canvas(qapp)
    last = _capture_dual_pill(canvas)
    _place_dual_ab(canvas)
    cursor = canvas._cursor
    ax, bx = cursor._ax, cursor._bx
    cursor._placing = "B"

    canvas.set_dual_cursor_mode(False)
    QCoreApplication.processEvents()
    assert cursor._ax == pytest.approx(ax)
    assert cursor._bx == pytest.approx(bx)
    assert cursor._placing == "B"
    assert cursor.snapshot_placement() is None
    assert last["info"] == ""
    a_items = cursor._cursor_a_items
    b_items = cursor._cursor_b_items
    assert a_items and all(not item.isVisible() for item in a_items)
    assert b_items and all(not item.isVisible() for item in b_items)

    canvas.set_dual_cursor_mode(True)
    QCoreApplication.processEvents()
    assert cursor._ax == pytest.approx(ax)
    assert cursor._bx == pytest.approx(bx)
    a_items = cursor._cursor_a_items
    b_items = cursor._cursor_b_items
    assert a_items and all(item.isVisible() for item in a_items)
    assert b_items and all(item.isVisible() for item in b_items)
    assert [item.value() for item in a_items] == pytest.approx([ax] * len(a_items))
    assert [item.value() for item in b_items] == pytest.approx([bx] * len(b_items))
    rows = last["rows"] or []
    assert len(rows) == len(_visible_display_names(canvas))
    blob = (last["info"] or "") + " ".join(str(row[0]) for row in rows)
    for name in _visible_display_names(canvas):
        assert name in blob
