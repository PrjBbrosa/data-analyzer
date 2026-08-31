"""Owner tests for the single cursor-display pipeline (spec §3.5 / §3.7)."""

from __future__ import annotations

import ast
from functools import partial
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.cursor_display import CursorDisplayChannel
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayOptions as ModelOptions,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class _LegacyCursorSource(QObject):
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)


def _plot_speed(canvas):
    canvas.plot_channels(
        [
            (
                "speed",
                True,
                np.asarray([0.0, 0.5, 1.0]),
                np.asarray([1.0, 2.0, 3.0]),
                "#1769e0",
                "rpm",
                "fid-a",
            ),
        ],
        mode="overlay",
    )


def _count_pill_writes(pill):
    counts = {"projection": 0, "single_detail": 0, "detail": 0}
    orig_projection = pill.set_display_projection
    orig_single = pill.set_single_detail_html
    orig_detail = pill.set_detail_html

    def set_display_projection(*args, **kwargs):
        counts["projection"] += 1
        return orig_projection(*args, **kwargs)

    def set_single_detail_html(*args, **kwargs):
        counts["single_detail"] += 1
        return orig_single(*args, **kwargs)

    def set_detail_html(*args, **kwargs):
        counts["detail"] += 1
        return orig_detail(*args, **kwargs)

    pill.set_display_projection = set_display_projection
    pill.set_single_detail_html = set_single_detail_html
    pill.set_detail_html = set_detail_html
    return counts


def _connect_legacy(cs, source):
    source.cursor_info.connect(partial(cs._on_cursor_info, source=source))
    source.dual_cursor_info.connect(partial(cs._on_dual_cursor_info, source=source))


def test_live_single_emit_projects_once_without_legacy_detail(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "single")
    _plot_speed(cs.canvas_time)
    qapp.processEvents()

    counts = _count_pill_writes(cs._pill)
    cs.canvas_time._emit_single_cursor_html(0.5)
    qapp.processEvents()

    assert counts["projection"] == 1
    assert counts["single_detail"] == 0
    assert cs._pill.has_detail()
    assert "t=0.5000s" in cs._pill.primary_text()
    assert "speed" in cs._pill.detail_text()


def test_live_dual_emit_projects_once_without_legacy_detail(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    _plot_speed(cs.canvas_time)
    cs.set_cursor_mode_for_canvas(cs.canvas_time, "dual")
    cs.canvas_time._cursor.ax = 0.0
    cs.canvas_time._cursor.bx = 1.0
    qapp.processEvents()

    counts = _count_pill_writes(cs._pill)
    cs.canvas_time._emit_dual_cursor_html()
    qapp.processEvents()

    assert counts["projection"] == 1
    assert counts["detail"] == 0
    assert counts["single_detail"] == 0
    assert cs._pill.has_detail()
    assert "A=" in cs._pill.primary_text()


def test_legacy_cursor_info_source_still_fills_detail(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode("time")
    cs.set_cursor_mode("single")
    source = _LegacyCursorSource(cs)
    _connect_legacy(cs, source)

    counts = _count_pill_writes(cs._pill)
    source.cursor_info.emit(
        '<span style="color:#111827;">t=1.0000s</span>'
        '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
        '<span style="color:#1769e0;">speed=<b>2 rpm</b></span>'
    )

    assert counts["projection"] == 0
    assert counts["single_detail"] == 1
    assert cs._pill.has_detail()
    assert "t=1.0000s" in cs._pill.primary_text()
    assert "2 rpm" in cs._pill.detail_text()
    assert "speed" in cs._pill.detail_text()


def test_legacy_dual_cursor_info_source_still_fills_detail(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode("time")
    cs.set_cursor_mode("dual")
    source = _LegacyCursorSource(cs)
    _connect_legacy(cs, source)

    counts = _count_pill_writes(cs._pill)
    source.cursor_info.emit("A=1.0s")
    source.dual_cursor_info.emit("<b>legacy-stats</b>")

    assert counts["detail"] == 1
    assert counts["projection"] == 0
    assert cs._pill.primary_text() == "A=1.0s"
    assert "legacy-stats" in cs._pill.detail_text()


def test_managed_cursor_info_keeps_row_cache(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode("time")
    cs.set_cursor_mode("single")
    channel = CursorDisplayChannel(
        identity=("fid-a", "speed"),
        source_label="runA",
        channel_label="speed",
        current_value=2.0,
        unit_suffix=" rpm",
    )
    cs.canvas_time.single_cursor_rows.emit((channel,))
    assert cs.canvas_time in cs._cursor_rows_by_canvas

    counts = _count_pill_writes(cs._pill)
    cs.canvas_time.cursor_info.emit(
        '<span style="color:#111827;">t=0.5000s</span>'
        '<span style="color:#cbd5e1;">  &nbsp;│&nbsp;  </span>'
        '<span style="color:#1769e0;">speed=<b>2 rpm</b></span>'
    )

    assert cs.canvas_time in cs._cursor_rows_by_canvas
    assert counts["single_detail"] == 0
    assert counts["projection"] == 0
    projection = cs._pill._display_projection
    assert projection is not None
    assert projection.blocks[0].identity == ("fid-a", "speed")
    assert cs._pill.has_detail()


def test_dto_import_paths_share_the_same_class():
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        CursorDisplayOptions as ReexportOptions,
    )

    assert ReexportOptions is ModelOptions
    assert ReexportOptions() == ModelOptions()


def test_pg_canvas_cursor_imports_neutral_model_not_chart_stack():
    src = REPO_ROOT / "mf4_analyzer" / "ui" / "pg_canvas" / "cursor.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert "mf4_analyzer.ui.cursor_display_model" in imported
    assert all(
        name != "mf4_analyzer.ui.chart_stack.cursor_display"
        and not name.startswith("mf4_analyzer.ui.chart_stack.")
        for name in imported
    )
