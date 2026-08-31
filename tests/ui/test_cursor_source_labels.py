"""Owner tests for cursor source-label resolution (no internal fid leakage)."""
from __future__ import annotations

import numpy as np
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.plot_helpers import (
    DualCursorRow,
    resolve_cursor_source_label,
)


def _fid_blob(*parts):
    return "".join("" if part is None else str(part) for part in parts)


class TestResolveCursorSourceLabel:
    def test_identity_tuple_uses_resolver_not_fid(self):
        source, channel = resolve_cursor_source_label(
            "Speed",
            ("f0", "Speed"),
            fid_resolver=lambda fid: "runA",
        )
        assert source == "runA"
        assert channel == "Speed"
        assert "f0" not in source
        assert "f0" not in channel

    def test_prefixed_display_wins_without_resolver(self):
        source, channel = resolve_cursor_source_label(
            "[runA] Speed",
            ("f0", "Speed"),
            fid_resolver=None,
        )
        assert source == "runA"
        assert channel == "Speed"
        assert "f0" not in source

    def test_no_prefix_no_resolver_blanks_source(self):
        source, channel = resolve_cursor_source_label(
            "Speed",
            ("f0", "Speed"),
            fid_resolver=None,
        )
        assert source == ""
        assert channel == "Speed"
        blob = _fid_blob(source, channel)
        assert "f0" not in blob

    def test_json_identity_matches_tuple(self):
        source, channel = resolve_cursor_source_label(
            "Speed",
            '["f0","Speed"]',
            fid_resolver=lambda fid: "runA",
        )
        assert source == "runA"
        assert channel == "Speed"
        assert "f0" not in source

    def test_prefixed_fid_is_never_a_display_label(self):
        source, channel = resolve_cursor_source_label(
            "[f0] Speed",
            ("f0", "Speed"),
            fid_resolver=lambda fid: "runA",
        )
        assert source == "runA"
        assert channel == "Speed"
        assert source != "f0"


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _plot_rows(canvas, rows):
    t = np.linspace(0.0, 1.0, 50)
    plotted = []
    for name, fid, amp, color in rows:
        plotted.append((
            name,
            True,
            t,
            np.full_like(t, amp),
            color,
            "",
            fid,
        ))
    canvas.plot_channels(plotted, mode="overlay")
    QCoreApplication.processEvents()


def _emit_single(canvas, x=0.5):
    htmls, structured = [], []
    canvas.cursor_info.connect(htmls.append)
    canvas.single_cursor_rows.connect(structured.append)
    canvas.set_cursor_visible(True)
    canvas.set_dual_cursor_mode(False)
    canvas._emit_single_cursor_html(float(x))
    QCoreApplication.processEvents()
    return htmls[-1] if htmls else "", structured[-1] if structured else []


def _no_fid(text):
    assert "f0" not in text
    assert "f1" not in text


def test_canvas_emission_never_leaks_fid(qapp):
    canvas = _pg_canvas(qapp)
    _plot_rows(canvas, [("ch", "f0", 1.0, "#1769e0")])
    canvas.set_source_label_resolver(lambda fid: "runA")
    html, rows = _emit_single(canvas)
    assert rows
    channel = rows[0]
    _no_fid(str(channel.source_label))
    _no_fid(str(channel.qualified_label))
    _no_fid(html)
    assert channel.channel_label == "ch"
    assert channel.source_label == "runA"
    assert channel.qualified_label == "runA / ch"


def test_two_source_batch_keeps_distinct_source_labels(qapp):
    canvas = _pg_canvas(qapp)
    _plot_rows(canvas, [
        ("Speed", "f0", 1.0, "#1769e0"),
        ("Speed", "f1", 2.0, "#ef4444"),
    ])
    canvas.set_source_label_resolver(
        lambda fid: {"f0": "runA", "f1": "runB"}.get(fid, "")
    )
    html, rows = _emit_single(canvas)
    assert len(rows) == 2
    sources = [row.source_label for row in rows]
    assert all(sources)
    assert sources[0] != sources[1]
    assert set(sources) == {"runA", "runB"}
    labels = [row.qualified_label for row in rows]
    assert labels[0] != labels[1]
    for row in rows:
        _no_fid(row.source_label)
        _no_fid(row.qualified_label)
        assert row.channel_label == "Speed"
    _no_fid(html)


def test_single_source_batch_keeps_resolved_label_and_omits_visible_prefix(qapp):
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        CursorDisplayOptions,
        build_cursor_presentation,
    )

    canvas = _pg_canvas(qapp)
    _plot_rows(canvas, [
        ("Speed", "f0", 1.0, "#1769e0"),
        ("Torque", "f0", 2.0, "#ef4444"),
    ])
    canvas.set_source_label_resolver(lambda fid: "runA")
    html, rows = _emit_single(canvas)
    assert len(rows) == 2
    assert {row.source_label for row in rows} == {"runA"}
    assert {row.channel_label for row in rows} == {"Speed", "Torque"}
    for row in rows:
        assert row.qualified_label.startswith("runA / ")
        _no_fid(row.qualified_label)
    _no_fid(html)
    projection = build_cursor_presentation(
        rows, CursorDisplayOptions(),
        cursor_mode="single", x_mode="time", mini=False,
    )
    assert "runA / " in projection.tooltip
    assert "runA / " not in projection.html
    assert projection.omit_visible_source_prefix is True


def test_chart_stack_injects_resolver_onto_existing_and_future_canvases(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    names = {"f0": "runA", "f1": "runB"}
    cs.set_source_label_resolver(lambda fid: names[fid])
    assert cs.canvas_time._cursor._source_label_resolver is not None
    assert cs.canvas_time._cursor._source_label_resolver("f0") == "runA"
    cs.enter_split()
    secondary = cs.secondary_canvas()
    assert secondary is not None
    assert secondary._cursor._source_label_resolver("f1") == "runB"


def test_chart_stack_dual_two_sources_stay_distinguishable(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_source_label_resolver(
        lambda fid: {"f0": "runA", "f1": "runB"}[fid]
    )
    rows = [
        DualCursorRow(
            channel_name="Speed",
            min_value=0.0,
            max_value=1.0,
            avg=0.5,
            delta=0.1,
            unit_suffix="",
            color="#1769e0",
            identity=("f0", "Speed"),
            label="Speed",
        ),
        DualCursorRow(
            channel_name="Speed",
            min_value=0.0,
            max_value=2.0,
            avg=1.0,
            delta=0.2,
            unit_suffix="",
            color="#ef4444",
            identity=("f1", "Speed"),
            label="Speed",
        ),
    ]
    cs._on_dual_cursor_rows(rows, source=cs.canvas_time)
    channels = cs._cursor_rows_by_canvas[cs.canvas_time][2]
    assert len(channels) == 2
    assert channels[0].source_label == "runA"
    assert channels[1].source_label == "runB"
    assert channels[0].qualified_label != channels[1].qualified_label
    for channel in channels:
        _no_fid(channel.source_label)
        _no_fid(channel.qualified_label)


def test_chart_stack_dual_single_source_omits_prefix(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_source_label_resolver(lambda fid: "runA")
    rows = [
        DualCursorRow(
            channel_name="Speed",
            min_value=0.0,
            max_value=1.0,
            avg=0.5,
            delta=0.1,
            unit_suffix="",
            color="#1769e0",
            identity=("f0", "Speed"),
            label="Speed",
        ),
        DualCursorRow(
            channel_name="Torque",
            min_value=0.0,
            max_value=2.0,
            avg=1.0,
            delta=0.2,
            unit_suffix="",
            color="#ef4444",
            identity=("f0", "Torque"),
            label="Torque",
        ),
    ]
    cs._on_dual_cursor_rows(rows, source=cs.canvas_time)
    channels = cs._cursor_rows_by_canvas[cs.canvas_time][2]
    assert {channel.source_label for channel in channels} == {"runA"}
    assert {channel.channel_label for channel in channels} == {"Speed", "Torque"}
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        CursorDisplayOptions,
        build_cursor_presentation,
    )
    projection = build_cursor_presentation(
        channels, CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    )
    assert "runA / " in projection.tooltip
    assert "runA / " not in projection.html
