"""Real-render geometry contracts for the bounded shared cursor table (A01/A02).

These tests measure the actually rendered rich-text layout (QTextDocument
blocks), not just the HTML strings: value columns must share their right
edges across channels, the document must not exceed the label width (no
clipped text), and the pill frame must respect the R4 budget.
"""

from dataclasses import replace

import pytest

from PyQt5.QtCore import QRect, QSettings
from PyQt5.QtGui import QTextDocument
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.cursor_display import build_cursor_presentation
from mf4_analyzer.ui.chart_stack.cursor_table_layout import compute_wcap
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayChannel,
    CursorDisplayOptions,
)

CHANNELS = (
    CursorDisplayChannel(
        identity="c1", source_label="", channel_label="CenterFeelTorque",
        color="#00aa9b", unit_suffix="U_Nm",
        min_value=0.0, max_value=0.0, avg_value=0.0, delta=0.0,
    ),
    CursorDisplayChannel(
        identity="c2", source_label="", channel_label="InertiaModification",
        color="#eb8500", unit_suffix="U_Nm",
        min_value=0.04102, max_value=0.1592, avg_value=0.1001, delta=-0.3387,
    ),
    CursorDisplayChannel(
        identity="c3", source_label="", channel_label="RackForceMerge",
        color="#ff0752", unit_suffix="",
        min_value=-2923.0, max_value=-2908.0, avg_value=-2916.0, delta=-1.231,
    ),
    CursorDisplayChannel(
        identity="c4", source_label="", channel_label="TorsionBarTorque",
        color="#00aa9b", unit_suffix="U_Nm",
        min_value=-1.779, max_value=-1.723, avg_value=-1.751, delta=0.05743,
    ),
)

LONG_CHANNELS = (
    CursorDisplayChannel(
        identity="L1", source_label="", channel_label="a" * 150,
        color="#111111", unit_suffix="long unit with spaces",
        min_value=1.234e-5, max_value=9.999, avg_value=None, delta=-0.5,
    ),
    CursorDisplayChannel(
        identity="L2", source_label="", channel_label="b" * 150,
        color="#222222", unit_suffix="",
        min_value=None, max_value=None, avg_value=None, delta=None,
    ),
)

PRIMARY = (
    'A <b>0.0000&nbsp;s</b> &nbsp;·&nbsp; '
    'B <b>4.9750&nbsp;s</b><br>'
    'ΔT <b>4.9750&nbsp;s</b> &nbsp;·&nbsp; '
    '1/ΔT <b>0.20101&nbsp;Hz</b>'
)


def make_pill(qtbot, width, height=720):
    from mf4_analyzer.ui.chart_stack.cursor_pill import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(width, height)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    parent.show()
    return parent, pill


def projection(channels=CHANNELS, **options):
    return build_cursor_presentation(
        channels, CursorDisplayOptions(**options),
        cursor_mode="dual", x_mode="time", mini=False,
    )


def doc_blocks(pill):
    """Lay out the pill's detail HTML exactly like the label renders it."""
    doc = pill._detail.document
    doc.documentLayout().documentSize()
    blocks = []
    block = doc.begin()
    while block.isValid():
        rect = doc.documentLayout().blockBoundingRect(block)
        blocks.append((block.text(), rect))
        block = block.next()
    return doc, blocks


def value_column_right_edges(pill):
    """Right edges of numeric cells, grouped by column index across rows."""
    doc, blocks = doc_blocks(pill)
    edges = []
    for text, rect in blocks:
        if text[:1].isdigit() or (text[:1] == "-" and len(text) > 1):
            edges.append(round(rect.x() + rect.width(), 1))
    n = len(pill._display_projection.metric_labels)
    if not n or not edges:
        return doc, []
    return doc, [edges[col::n] for col in range(n)]


def test_wide_table_columns_align_across_channels(qapp, qtbot):
    parent, pill = make_pill(qtbot, 1200)
    pill.set_primary(PRIMARY)
    pill.set_display_projection(projection())
    qapp.processEvents()
    assert pill._table_plan.kind == "horizontal"
    doc, columns = value_column_right_edges(pill)
    assert len(columns) == 4
    assert len(columns[0]) == 4  # one value per channel per column
    for group in columns:
        assert len(set(group)) == 1, f"column right edges drift: {group}"
    # No horizontal clipping: the rendered document must fit the label.
    assert doc.size().width() <= pill._detail.width() + 1


def test_grouped_table_columns_align_across_channels(qapp, qtbot):
    parent, pill = make_pill(qtbot, 400)
    pill.set_primary(PRIMARY)
    pill.set_display_projection(projection())
    qapp.processEvents()
    assert pill._table_plan.kind == "grouped"
    doc, columns = value_column_right_edges(pill)
    assert len(columns) == 4
    for group in columns:
        assert len(set(group)) == 1, f"column right edges drift: {group}"
    assert doc.size().width() <= pill._detail.width() + 1


def test_compact_table_pairs_share_slot_edges(qapp, qtbot):
    parent, pill = make_pill(qtbot, 360)
    pill.set_primary(PRIMARY)
    # Very wide scientific values force the compact fallback at this host.
    wide = tuple(
        CursorDisplayChannel(
            identity=ch.identity, source_label="",
            channel_label=ch.channel_label, color=ch.color,
            unit_suffix=ch.unit_suffix,
            min_value=-1.234e-308, max_value=-1.234e-308,
            avg_value=-1.234e-308, delta=-1.234e-308,
        )
        for ch in CHANNELS
    )
    pill.set_display_projection(projection(wide))
    qapp.processEvents()
    assert pill._table_plan.kind == "compact"
    assert pill._table_plan.pairs_per_row == 2
    doc, _columns = value_column_right_edges(pill)
    # Compact slots: every even (value) cell within a row pair shares edges.
    blocks = doc_blocks(pill)[1]
    value_edges = [
        round(r.x() + r.width(), 1)
        for text, r in blocks
        if text[:1].isdigit() or (text[:1] == "-" and len(text) > 1)
    ]
    assert len(value_edges) == 16  # 4 channels x 2 value rows x 2 pairs
    for slot in range(2):
        group = value_edges[slot::2]
        assert len(set(group)) == 1, f"slot {slot} edges drift: {group}"
    assert doc.size().width() <= pill._detail.width() + 1


def test_pill_frame_respects_wcap_across_host_widths(qapp, qtbot):
    for width in (1200, 900, 800, 560, 500, 360):
        parent, pill = make_pill(qtbot, width)
        pill.set_primary(PRIMARY)
        pill.set_display_projection(projection())
        qapp.processEvents()
        wsafe = pill.safe_rect().width()
        budget = min(640, wsafe)
        assert pill.width() <= budget, (
            f"host {width}: pill {pill.width()} > Wcap {budget}"
        )
        assert pill.width() <= wsafe
        assert pill.height() <= pill.safe_rect().height()
        parent.close()
        pill.close()


def test_long_names_are_elided_and_do_not_widen_value_columns(qapp, qtbot):
    parent, pill = make_pill(qtbot, 800)
    pill.set_display_projection(projection(LONG_CHANNELS))
    qapp.processEvents()
    visible = pill.detail_text()
    assert "..." in visible
    assert "a" * 150 not in visible
    # Value cells keep their shared right edges even with 60-char names.
    doc, columns = value_column_right_edges(pill)
    for group in columns:
        if len(group) >= 2:
            assert len(set(group)) == 1, f"column edges drift: {group}"
    assert doc.size().width() <= pill._detail.width() + 1


def test_missing_values_stay_dash_and_unit_stays_in_name_area(qapp, qtbot):
    parent, pill = make_pill(qtbot, 800)
    pill.set_display_projection(projection(LONG_CHANNELS))
    qapp.processEvents()
    visible = pill.detail_text()
    assert "—" in visible
    assert "long unit with spaces" in visible  # unit shown as-is
    # The unit lives in the name cells (marked by the colour dot); value
    # cells carry only the formatted number or the dash.
    doc, blocks = doc_blocks(pill)
    for text, _rect in blocks:
        if "●" in text:
            continue  # name/unit cell
        assert "long unit with spaces" not in text


def test_primary_first_stays_inside_budget_and_late_rows_join(qapp, qtbot):
    parent, pill = make_pill(qtbot, 500)
    long_primary = (
        'A <b>12345678901234567890&nbsp;s</b> &nbsp;·&nbsp; '
        'B <b>-1.2345678901234567E-19&nbsp;s</b><br>'
        'ΔT <b>12345678901234567890&nbsp;s</b> &nbsp;·&nbsp; '
        '1/ΔT <b>0.20101&nbsp;Hz</b>'
    )
    pill.set_primary(long_primary)
    pill.setVisible(True)
    qapp.processEvents()
    budget = compute_wcap(pill.safe_rect().width())
    assert pill.width() <= budget
    # Rows may exceed the preferred ratio to keep complete horizontal rows.
    pill.set_display_projection(projection())
    qapp.processEvents()
    assert pill.width() <= min(640, pill.safe_rect().width())


def test_dual_primary_regroups_into_fragments_when_narrow(qapp, qtbot):
    parent, pill = make_pill(qtbot, 400)
    long_primary = (
        '<span style="color:#111827;">A=123456789012.3456s</span>'
        '│<span style="color:#111827;">B=123456789012.3456s</span>'
        '│<span style="color:#111827;">ΔT=123456789012.3456s</span>'
        '│<span style="color:#111827;">1/ΔT=0.20Hz</span>'
    )
    from mf4_analyzer.ui.chart_stack.cursor_pill import _CURSOR_HTML_SEP

    pill.set_primary(_CURSOR_HTML_SEP.join(
        f'<span style="color:#111827;">{p}</span>' for p in (
            "A=123456789012.3456s", "B=123456789012.3456s",
            "ΔT=123456789012.3456s", "1/ΔT=0.20Hz",
        )
    ))
    pill.setVisible(True)
    qapp.processEvents()
    budget = compute_wcap(pill.safe_rect().width())
    assert pill.width() <= budget
    # The regrouped primary keeps the fragments intact: every segment text
    # appears once and no number is split by the regrouping itself.
    text = pill.primary_text()
    assert text.count("A=123456789012.3456s") == 1
    assert "<br>" in text


def test_mini_uses_shared_priority_column(qapp, qtbot):
    parent, pill = make_pill(qtbot, 1200)
    mini_projection = build_cursor_presentation(
        CHANNELS, CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=True,
    )
    pill.set_display_projection(mini_projection)
    qapp.processEvents()
    # Mini shows one shared priority column instead of all full statistics.
    visible = pill.detail_text()
    assert pill._table_plan.kind == "horizontal"
    assert "●" in visible
    assert "Δ" in visible
    assert "Min" not in visible and "Avg" not in visible


def test_identity_only_projection_has_no_metric_header(qapp, qtbot):
    parent, pill = make_pill(qtbot, 800)
    pill.set_display_projection(build_cursor_presentation(
        CHANNELS[:2],
        CursorDisplayOptions(
            show_max_value=False, show_min_value=False,
            show_avg_value=False, show_delta_value=False,
        ),
        cursor_mode="dual", x_mode="time", mini=False,
    ))
    qapp.processEvents()
    assert pill._table_plan.kind == "identity"
    visible = pill.detail_text()
    assert "信号 / 单位" not in visible
    assert "Min" not in visible and "Avg" not in visible
    # Names still visible with their units.
    assert "CenterFeelTorque" in visible
    assert "U_Nm" in visible
    assert pill._detail.toolTip() == ""
    assert pill._primary.toolTip() == ""


def test_value_envelope_keeps_columns_stable_across_100_updates(qapp, qtbot):
    """Shorter values may not shrink a settled full-table column envelope."""
    parent, pill = make_pill(qtbot, 500)
    wide = tuple(
        replace(
            channel,
            min_value=-1.234e-308,
            max_value=-1.234e-308,
            avg_value=-1.234e-308,
            delta=-1.234e-308,
        )
        for channel in CHANNELS
    )
    narrow = tuple(
        replace(
            channel,
            min_value=0.0,
            max_value=0.0,
            avg_value=0.0,
            delta=0.0,
        )
        for channel in CHANNELS
    )
    pill.set_display_projection(projection(wide))
    qapp.processEvents()
    initial_kind = pill._table_plan.kind
    _doc, initial_columns = value_column_right_edges(pill)
    initial_edges = tuple(tuple(group) for group in initial_columns)

    for index in range(100):
        pill.set_display_projection(projection(narrow if index % 2 else wide))
        qapp.processEvents()
        assert pill._table_plan.kind == initial_kind
        _doc, columns = value_column_right_edges(pill)
        assert tuple(tuple(group) for group in columns) == initial_edges


def test_primary_updates_do_not_escape_the_settled_table_budget(qapp, qtbot):
    """The high-rate A/B readout must not undo the table reflow on each move."""
    parent, pill = make_pill(qtbot, 1200)
    pill.set_display_projection(projection())
    qapp.processEvents()
    expected_kind = pill._table_plan.kind
    budget = compute_wcap(pill.safe_rect().width())
    for index in range(12):
        pill.set_primary(
            'A <b>123456789.1234&nbsp;s</b> &nbsp;·&nbsp; '
            'B <b>-123456789.1234&nbsp;s</b><br>'
            f'ΔT <b>{index + 0.1234:.4f}&nbsp;s</b> &nbsp;·&nbsp; '
            '1/ΔT <b>0.20101&nbsp;Hz</b>'
        )
        qapp.processEvents()
        assert pill._table_plan.kind == expected_kind
        assert pill.width() <= budget
        assert pill.safe_rect().contains(pill.geometry())


def test_full_table_uses_its_measured_content_width_not_the_whole_cap(qapp, qtbot):
    """A wide host is a ceiling, not an instruction to leave a blank slab."""
    parent, pill = make_pill(qtbot, 1200)
    pill.set_display_projection(projection())
    qapp.processEvents()
    budget = compute_wcap(pill.safe_rect().width())
    assert pill._table_plan.required_width + 20 < budget
    assert pill.width() < budget - 20


def test_split_pills_budget_against_their_own_canvas(qapp, qtbot, tmp_path):
    """A narrow split pane must not borrow width from its sibling pane."""
    from mf4_analyzer.ui.chart_stack import ChartStack
    settings = QSettings(str(tmp_path / "cursor.ini"), QSettings.IniFormat)
    stack = ChartStack(cursor_settings=settings)
    qtbot.addWidget(stack)
    stack.resize(1000, 500)
    stack.show()
    stack.set_mode("time")
    stack.enter_split()
    stack._time_split.setSizes([700, 300])
    secondary = stack.secondary_canvas()
    assert secondary is not None
    for canvas in (stack.canvas_time, secondary):
        stack.set_cursor_mode_for_canvas(canvas, "dual")
        canvas.dual_cursor_rows.emit(CHANNELS)
    qapp.processEvents()

    def assert_panes_are_independent():
        for pill, canvas in (
            (stack._pill, stack.canvas_time),
            (stack._pill_secondary, secondary),
        ):
            assert pill is not None
            top_left = canvas.mapTo(stack.stack, canvas.rect().topLeft())
            bottom_right = canvas.mapTo(stack.stack, canvas.rect().bottomRight())
            expected = stack.stack.contentsRect().intersected(
                QRect(top_left, bottom_right)
            ).adjusted(8, 8, -8, -8)
            assert pill.safe_rect() == expected
            assert pill.width() <= min(640, expected.width())
            assert expected.contains(pill.geometry())

    assert_panes_are_independent()
    # QSplitter's own move signal, not ChartStack.resizeEvent, must remeasure
    # both widgets after a user adjusts the divider.
    stack._time_split.moveSplitter(300, 1)
    qapp.processEvents()
    assert_panes_are_independent()

@pytest.fixture
def production_style(qapp):
    from mf4_analyzer.ui_kit import load_stylesheet
    previous = qapp.styleSheet()
    load_stylesheet(qapp)
    yield
    qapp.setStyleSheet(previous)


def painted_document(pill):
    """Use the paint document; legacy QLabel fallback mirrors its NoWrap flag."""
    if hasattr(pill._detail, 'document'):
        return pill._detail.document
    from PyQt5.QtGui import QTextOption
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setDefaultFont(pill._detail.font())
    option = doc.defaultTextOption()
    option.setWrapMode(QTextOption.NoWrap)
    doc.setDefaultTextOption(option)
    doc.setHtml(pill.detail_text())
    doc.setTextWidth(pill._detail.width())
    return doc


def assert_painted_glyphs_contained(pill):
    doc = painted_document(pill)
    doc.size()
    block = doc.begin()
    while block.isValid():
        layout = block.layout()
        origin = doc.documentLayout().blockBoundingRect(block).topLeft()
        for index in range(layout.lineCount()):
            line = layout.lineAt(index)
            bounds = line.naturalTextRect().translated(origin)
            if block.text():
                assert bounds.left() >= -1, (block.text(), bounds)
                assert bounds.right() <= pill._detail.width() + 1, (
                    block.text(), bounds, pill._detail.width())
                assert bounds.bottom() <= pill._detail.height() + 1, (
                    block.text(), bounds, pill._detail.height())
        block = block.next()


def test_production_long_name_and_unit_have_no_clipped_glyphs(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 600, 500)
    channels = tuple(replace(ch, channel_label=name,
                             unit_suffix='long unit with spaces')
                     for ch, name in zip(CHANNELS, (
                         'Rte_RackPosCorrPlausi_wSteeringAngle_xds16',
                         'Rte_RFCD2_kAppll_RackForceMerge_xds16',
                         'Rte_RScal_nAppll_RotorSpeed_xds16')))
    pill.set_display_projection(projection(channels))
    pill.show()
    qapp.processEvents()
    assert_painted_glyphs_contained(pill)


def test_production_short_names_share_the_numeric_row(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 800)
    channels = tuple(replace(ch, channel_label=name, unit_suffix=unit)
                     for ch, name, unit in zip(CHANNELS,
                         ('L', 'R', 'MOTOR Y', 'MOTOR X'),
                         ('Pa', 'Pa', 'm/s^2', 'm/s^2')))
    pill.set_display_projection(projection(channels))
    pill.show()
    qapp.processEvents()
    assert pill._table_plan.kind == 'horizontal'
    assert_painted_glyphs_contained(pill)


@pytest.mark.parametrize("width", [320, 500, 800, 1200])
@pytest.mark.parametrize("cursor_mode", ["single", "dual"])
@pytest.mark.parametrize("x_mode", ["time", "custom"])
@pytest.mark.parametrize("mini", [False, True])
def test_all_modes_use_painted_document_bounds(qapp, qtbot, production_style,
                                               width, cursor_mode, x_mode, mini):
    from mf4_analyzer.ui.cursor_display_model import CursorDisplayBranch
    parent, pill = make_pill(qtbot, width, 500)
    channels = (
        CursorDisplayChannel(identity="missing", source_label="", channel_label="Tol_oben [mm]",
                             diagnostic="区间内无数据"),
        CursorDisplayChannel(identity="ok", source_label="", channel_label="Druckstückspiel",
                             unit_suffix=" mm", current_value=.03552,
                             min_value=.0289, max_value=.0409, avg_value=.03552, delta=-.002658,
                             branches=(CursorDisplayBranch("X↑", .03552, .0289, .0409, .03552, -.002658),
                                       CursorDisplayBranch("X↓", .0443, .0402, .0492, .0443, .001047))),
    )
    pill.set_display_projection(build_cursor_presentation(channels, CursorDisplayOptions(),
                               cursor_mode=cursor_mode, x_mode=x_mode, mini=mini))
    pill.show()
    qapp.processEvents()
    assert pill._detail._document_active
    assert pill.safe_rect().contains(pill.geometry())
    assert_painted_glyphs_contained(pill)
    if x_mode == "custom":
        assert "区间内无数据" in pill._detail.document.toPlainText()
        assert "X↑" in pill._detail.document.toPlainText()
        assert "X↓" in pill._detail.document.toPlainText()
    # Scientific notation and signs must stay together in one numeric cell.
    doc = pill._detail.document
    block = doc.begin()
    while block.isValid():
        if block.text() and block.text()[0] in "-0123456789":
            assert block.layout().lineCount() == 1, block.text()
        block = block.next()


def test_short_horizontal_names_and_values_have_equal_row_origins(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 800)
    pill.set_display_projection(projection(tuple(replace(ch, channel_label=name)
                                for ch, name in zip(CHANNELS, ("L", "R", "MOTOR Y", "MOTOR X")))))
    pill.show()
    qapp.processEvents()
    _doc, blocks = doc_blocks(pill)
    names = [rect.y() for text, rect in blocks if text.startswith("●")]
    values = [rect.y() for text, rect in blocks if text and text[0] in "-0123456789"]
    assert len(names) == 4
    for index, name_y in enumerate(names):
        assert all(abs(value_y - name_y) <= 1 for value_y in values[index * 4:index * 4 + 4])


def test_name_entities_cross_renderer_boundary_once(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 800)
    pill.set_display_projection(projection((replace(CHANNELS[0], channel_label="L <A&B>"),)))
    pill.show()
    qapp.processEvents()
    assert "L <A&B>" in pill._detail.document.toPlainText()
    assert "&lt;" not in pill._detail.document.toPlainText()
    assert_painted_glyphs_contained(pill)


def test_low_height_omits_whole_custom_channel_and_its_branches(qapp, qtbot, production_style):
    from mf4_analyzer.ui.cursor_display_model import CursorDisplayBranch
    parent, pill = make_pill(qtbot, 500, 100)
    channels = tuple(replace(ch, branches=(
        CursorDisplayBranch('X↑', .1, .2, .3, .4, .5),
        CursorDisplayBranch('X↓', .6, .7, .8, .9, 1.0))) for ch in CHANNELS)
    pill.set_display_projection(build_cursor_presentation(channels, CursorDisplayOptions(),
                               cursor_mode='dual', x_mode='custom', mini=False))
    pill.show()
    qapp.processEvents()
    assert pill.visible_channel_count() < len(channels)
    visible = pill._detail.document.toPlainText()
    assert visible.count('X↑') == visible.count('X↓') == pill.visible_channel_count()
    assert_painted_glyphs_contained(pill)
    assert pill.safe_rect().contains(pill.geometry())


def test_font_change_invalidates_measurement_signature_and_clear_resets_budget(qapp, qtbot):
    parent, pill = make_pill(qtbot, 800)
    pill.set_display_projection(projection())
    initial = pill._layout_signature
    font = pill._detail.font()
    font.setFamily('Courier')
    pill._detail.setFont(font)
    pill.reflow_to_parent()
    assert pill._layout_signature != initial
    pill.clear()
    assert pill._table_plan is None
    assert pill._pane_content_width == 0
    assert not pill._detail._document_active


def test_long_underscore_name_uses_two_lines_before_elision(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 800)
    name = 'Rte_RackPosCorrPlausi_wSteeringAngle_xds16'
    pill.set_display_projection(projection((replace(CHANNELS[0], channel_label=name),)))
    pill.show()
    qapp.processEvents()
    assert len(pill._name_elisions[0]) == 2
    assert pill._name_elisions[0][0].startswith('Rte_')
    assert pill._name_elisions[0][-1].endswith('xds16')
    assert_painted_glyphs_contained(pill)


@pytest.mark.parametrize('width', [360, 500, 800])
def test_primary_paint_bounds_reserve_actual_toggle_margin(qapp, qtbot, production_style, width):
    from mf4_analyzer.ui.chart_stack.cursor_pill import _CURSOR_HTML_SEP
    parent, pill = make_pill(qtbot, width)
    fields = ('A=28.2041s', 'B=24.7643s', 'ΔT=-3.4399s', '1/ΔT=0.29Hz')
    pill.set_primary(_CURSOR_HTML_SEP.join(fields))
    pill.set_display_projection(projection())
    pill.show()
    qapp.processEvents()
    doc = pill._primary.document
    assert pill._primary.contentsMargins().right() == 24
    assert doc.size().width() <= pill._primary.contentsRect().width()
    block = doc.begin()
    while block.isValid():
        origin = doc.documentLayout().blockBoundingRect(block).topLeft()
        for index in range(block.layout().lineCount()):
            bounds = block.layout().lineAt(index).naturalTextRect().translated(origin)
            assert bounds.right() <= pill._primary.contentsRect().width() + 1
            assert bounds.bottom() <= pill._primary.contentsRect().height() + 1
        block = block.next()
    assert all(field in doc.toPlainText() for field in fields)


@pytest.mark.parametrize('width,height', [(120, 240), (400, 55)])
def test_unfit_numeric_or_primary_summary_uses_space_state(qapp, qtbot, production_style,
                                                          width, height):
    from mf4_analyzer.ui.chart_stack.cursor_pill import _CURSOR_HTML_SEP
    parent, pill = make_pill(qtbot, width, height)
    pill.set_primary(_CURSOR_HTML_SEP.join(('A=28.2041s', 'B=24.7643s',
                                          'ΔT=-3.4399s', '1/ΔT=0.29Hz')))
    channels = (replace(CHANNELS[0], min_value=-1.234e-308,
                        max_value=-1.234e-308, avg_value=-1.234e-308, delta=-1.234e-308),)
    pill.set_display_projection(projection(channels))
    pill.show()
    qapp.processEvents()
    assert '空间不足' in pill._detail.document.toPlainText()
    assert pill.visible_channel_count() == 0
    assert pill.safe_rect().contains(pill.geometry())
    assert_painted_glyphs_contained(pill)
    assert '-1.234e-308' not in pill.detail_text()


def test_tiny_pane_suppresses_outer_show_and_recovers(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 40, 30)
    pill.set_primary('A=28.2041s')
    pill.set_display_projection(projection())
    # ChartStack asks to show after applying a projection; this must not
    # resurrect a clipped fallback when even its state label cannot fit.
    pill.setVisible(True)
    pill.show()
    qapp.processEvents()
    assert not pill.isVisible()
    assert pill.awaiting_space()
    parent.resize(500, 420)
    pill.reflow_to_parent()
    qapp.processEvents()
    assert pill.isVisible()
    assert not pill.awaiting_space()
    assert pill.visible_channel_count() == len(CHANNELS)
    assert '空间不足' not in pill.detail_text()
    assert pill.primary_text() == 'A=28.2041s'
    assert_painted_glyphs_contained(pill)
    assert pill.safe_rect().contains(pill.geometry())


def test_hidden_space_state_does_not_restore_after_explicit_hide(qapp, qtbot, production_style):
    parent, pill = make_pill(qtbot, 40, 30)
    pill.set_display_projection(projection())
    pill.setVisible(True)
    assert pill.awaiting_space()
    pill.setVisible(False)
    parent.resize(500, 420)
    pill.reflow_to_parent()
    assert not pill.isVisible()
    assert not pill.awaiting_space()
    pill.clear()
    assert not pill._space_hidden


def test_chartstack_repositions_space_hidden_pill_on_safe_rect_growth(qapp, qtbot,
                                                                   monkeypatch, production_style):
    from mf4_analyzer.ui.chart_stack import ChartStack
    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.resize(800, 500)
    stack.show()
    stack.set_mode('time')
    stack.set_cursor_mode_for_canvas(stack.canvas_time, 'dual')
    stack.canvas_time.dual_cursor_rows.emit(CHANNELS)
    qapp.processEvents()
    pill = stack._pill
    safe = [QRect(8, 8, 24, 14)]

    def sync_safe_rect(target, card):
        return target.set_safe_rect(safe[0])

    monkeypatch.setattr(stack, '_sync_pill_safe_rect', sync_safe_rect)
    stack._reposition_one_pill(pill, stack._time_card)
    assert pill.awaiting_space()
    assert not pill.isVisible()
    # Exercise the actual outer unconditional setVisible(True) call.
    stack._refresh_cursor_projection(stack.canvas_time)
    assert not pill.isVisible()
    assert pill.awaiting_space()
    safe[0] = QRect(8, 8, 484, 404)
    stack._reposition_one_pill(pill, stack._time_card)
    qapp.processEvents()
    assert pill.isVisible()
    assert not pill.awaiting_space()
    assert pill.visible_channel_count() == len(CHANNELS)
    assert safe[0].contains(pill.geometry())
    assert_painted_glyphs_contained(pill)
