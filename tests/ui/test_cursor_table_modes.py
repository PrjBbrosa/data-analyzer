"""Structured cursor table coverage independent of QWidget geometry."""

from html.parser import HTMLParser
from itertools import product

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.cursor_display import (
    build_cursor_presentation, render_cursor_presentation,
)
from mf4_analyzer.ui.chart_stack.cursor_table_layout import TableLayoutPlan
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayBranch, CursorDisplayChannel, CursorDisplayOptions,
)


def channel(**overrides):
    values = dict(
        identity=('run-a', 'signal'), source_label='run-a',
        channel_label='A&B <signal>', unit_suffix=' mm', color='#123456',
        current_value=1.25, min_value=-2., max_value=3., avg_value=1e-5,
        delta=-.75, branches=(
            CursorDisplayBranch('X↑', 1.25, -2., 3., 1e-5, -.75),
            CursorDisplayBranch('全程', None, None, None, None, None),
        ),
    )
    values.update(overrides)
    return CursorDisplayChannel(**values)


def plan(kind='horizontal', count=4):
    return TableLayoutPlan(
        kind, 85., 160., 150., 2, 28., 80., 2, 500., 1, 1, count,
    )


@pytest.mark.parametrize('bits', tuple(product((False, True), repeat=6)))
@pytest.mark.parametrize('x_mode,cursor_mode,mini', tuple(product(
    ('time', 'custom'), ('single', 'dual'), (False, True),
)))
def test_table_projection_covers_modes_and_all_settings(bits, x_mode, cursor_mode, mini):
    options = CursorDisplayOptions(*bits)
    projection = build_cursor_presentation(
        (channel(),), options, cursor_mode=cursor_mode, x_mode=x_mode, mini=mini,
    )
    labels = tuple(label for label, enabled in zip(
        ('Min', 'Max', 'Avg', 'Δ'), bits[3:4] + bits[2:3] + bits[4:],
    ) if enabled)
    if cursor_mode == 'single':
        labels = ('Value',)
    elif mini:
        labels = tuple(label for label in ('Δ', 'Avg', 'Max', 'Min') if label in labels)[:1]
    assert projection.metric_labels == labels
    block = projection.blocks[0]
    assert block.unit_text.strip() == 'mm'
    assert len(block.table_rows) == (2 if x_mode == 'custom' else 1)
    assert all(len(row.metric_texts) == len(labels) for row in block.table_rows)
    if x_mode == 'custom':
        assert [row.branch_label for row in block.table_rows] == ['X↑', '全程']
        assert all(value == '—' for value in block.table_rows[1].metric_texts)
    html = render_cursor_presentation(projection, layout_plan=plan(count=len(labels)))
    assert html.count('<table ') == 1
    assert 'color:#123456' in html
    if not mini:
        assert 'A&amp;B &lt;signal&gt;' in html
    else:
        assert 'A&amp;B &lt;signal&gt;' not in html
    if x_mode == 'custom':
        assert 'X↑' in html and '全程' in html


@pytest.mark.parametrize('kind', ('horizontal', 'grouped', 'compact', 'identity'))
def test_diagnostic_branches_and_channel_omission_stay_in_same_table(kind):
    projection = build_cursor_presentation(
        (channel(branches=(), diagnostic='区间内无数据 <unknown>'),
         channel(identity=('run-b', 'signal'), source_label='run-b'),
         channel(identity=('run-c', 'signal'), source_label='run-c')),
        CursorDisplayOptions(), cursor_mode='dual', x_mode='custom', mini=False,
    )
    html = render_cursor_presentation(projection, layout_plan=plan(kind), visible_count=2)
    assert html.count('<table ') == 1
    assert html.index('区间内无数据 &lt;unknown&gt;') < html.index('</table>')
    assert 'X↑' in html and '全程' in html
    assert '+1 channels' in html
    assert 'run-b /' in html and 'run-c /' not in html


def test_plain_name_lines_escape_once_and_take_precedence_over_old_override():
    projection = build_cursor_presentation(
        (channel(),), CursorDisplayOptions(), cursor_mode='dual', x_mode='time', mini=False,
    )
    html = render_cursor_presentation(
        projection, layout_plan=plan(), header_overrides=('old',),
        header_lines=(('A&B', '<signal>'),),
    )
    assert 'A&amp;B<br>&lt;signal&gt;' in html
    assert '&amp;amp;' not in html and '&lt;br&gt;' not in html
    assert 'old' not in html
    legacy = render_cursor_presentation(
        projection, layout_plan=plan(), header_overrides=('A<br>B',),
    )
    assert 'A&lt;br&gt;B' in legacy


def test_diagnostic_and_real_branch_are_not_mutually_exclusive():
    projection = build_cursor_presentation(
        (channel(diagnostic='部分路径不可用'),), CursorDisplayOptions(),
        cursor_mode='single', x_mode='custom', mini=True,
    )
    rows = projection.blocks[0].table_rows
    assert [row.branch_label for row in rows[:2]] == ['X↑', '全程']
    assert rows[-1].diagnostic == '部分路径不可用'


class TableCells(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.rows = []
        self.current_cell = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.rows.append([])
        if tag == 'td':
            self.current_cell = [dict(attrs), '']
            self.rows[-1].append(self.current_cell)

    def handle_data(self, data):
        if self.current_cell is not None:
            self.current_cell[1] += data

    def handle_endtag(self, tag):
        if tag == 'td':
            self.current_cell = None


@pytest.mark.parametrize('kind', ('horizontal', 'grouped', 'compact'))
def test_branch_values_and_diagnostic_reuse_grid_columns(kind):
    projection = build_cursor_presentation(
        (channel(branches=(), diagnostic='无数据'), channel()),
        CursorDisplayOptions(), cursor_mode='dual', x_mode='custom', mini=False,
    )
    grid = TableCells(render_cursor_presentation(projection, layout_plan=plan(kind))).rows
    branch = next(row for row in grid if any(cell[1] == 'X↑' for cell in row))
    branch_index = 1 if kind == 'horizontal' else 0
    assert branch[branch_index][1] == 'X↑'
    if kind == 'compact':
        assert [cell[1] for cell in branch[branch_index + 1:]] == ['Min', '-2', 'Max', '3']
    else:
        assert [cell[1] for cell in branch[branch_index + 1:]] == ['-2', '3', '1e-05', '-0.75']
    diagnostic = next(row for row in grid if any(cell[1] == '无数据' for cell in row))
    assert diagnostic[branch_index + 1][0]['colspan'] == '4'


def test_omitting_branch_channel_preserves_diagnostic_column_position():
    projection = build_cursor_presentation(
        (channel(branches=(), diagnostic='无数据'), channel()),
        CursorDisplayOptions(), cursor_mode='dual', x_mode='custom', mini=False,
    )
    grid = TableCells(render_cursor_presentation(
        projection, layout_plan=plan(), visible_count=1,
    )).rows
    diagnostic = next(row for row in grid if any(cell[1] == '无数据' for cell in row))
    assert len(diagnostic) == 3  # identity / reserved branch / diagnostic
    assert diagnostic[2][0]['colspan'] == '4'


@pytest.mark.parametrize('kind', ('horizontal', 'grouped', 'compact', 'identity'))
@pytest.mark.parametrize('empty_projection', (False, True))
def test_zero_visible_channels_has_no_orphan_table_header(kind, empty_projection):
    projection = build_cursor_presentation(
        () if empty_projection else (channel(),), CursorDisplayOptions(),
        cursor_mode='dual', x_mode='custom', mini=False,
    )
    html = render_cursor_presentation(
        projection, layout_plan=plan(kind), visible_count=0,
    )
    assert '<table' not in html
    assert 'Min' not in html and '方向' not in html
    if empty_projection:
        assert html == ''
    else:
        assert '+1 channels' in html


def _make_mode_pill(qtbot, parent_width=800):
    from mf4_analyzer.ui.chart_stack.cursor_pill import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(parent_width, 420)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    parent.show()
    pill.show()
    return parent, pill


def _click_mode(qtbot, pill, mode):
    button = pill._mode_control.button_for(mode)
    qtbot.mouseClick(button, Qt.LeftButton)


def test_mode_control_idempotent_click_does_not_emit(qapp, qtbot):
    _parent, pill = _make_mode_pill(qtbot)
    spy = QSignalSpy(pill.display_mode_changed)
    assert pill.display_mode() == "full"
    assert pill._mode_control.button_for("full").isChecked()
    assert pill._mode_control.button_for("full").text() == "完整"
    assert pill._mode_control.button_for("mini").text() == "数值"

    _click_mode(qtbot, pill, "full")
    qapp.processEvents()
    assert pill.display_mode() == "full"
    assert len(spy) == 0

    _click_mode(qtbot, pill, "mini")
    qapp.processEvents()
    assert pill.display_mode() == "mini"
    assert list(spy) == [["mini"]]

    _click_mode(qtbot, pill, "mini")
    qapp.processEvents()
    assert pill.display_mode() == "mini"
    assert list(spy) == [["mini"]]


def test_restore_snapshot_and_projection_sync_mode_without_signal(qapp, qtbot):
    _parent, pill = _make_mode_pill(qtbot)
    pill.set_display_mode("mini")
    snapshot = pill.snapshot()
    pill.set_display_mode("full")
    spy = QSignalSpy(pill.display_mode_changed)

    pill.restore_snapshot(snapshot)
    qapp.processEvents()
    assert pill.display_mode() == "mini"
    assert pill._mode_control.button_for("mini").isChecked()
    assert len(spy) == 0

    projection = build_cursor_presentation(
        (channel(),), CursorDisplayOptions(), cursor_mode="dual", x_mode="time",
        mini=False,
    )
    pill.set_display_projection(projection)
    qapp.processEvents()
    assert pill.display_mode() == "full"
    assert pill._mode_control.button_for("full").isChecked()
    assert len(spy) == 0


def test_two_cursor_pills_keep_independent_display_modes(qapp, qtbot):
    first_parent, first = _make_mode_pill(qtbot)
    second_parent, second = _make_mode_pill(qtbot)
    first_spy = QSignalSpy(first.display_mode_changed)
    second_spy = QSignalSpy(second.display_mode_changed)

    _click_mode(qtbot, second, "mini")
    qapp.processEvents()
    assert first.display_mode() == "full"
    assert second.display_mode() == "mini"
    assert len(first_spy) == 0
    assert list(second_spy) == [["mini"]]

    first.set_display_mode("mini", emit_signal=False)
    qapp.processEvents()
    assert first.display_mode() == "mini"
    assert second.display_mode() == "mini"
    assert len(first_spy) == 0
    assert list(second_spy) == [["mini"]]
    first_parent.close()
    second_parent.close()


def test_mode_control_keyboard_reaches_and_activates_without_toggle_back(qapp, qtbot):
    _parent, pill = _make_mode_pill(qtbot)
    control = pill._mode_control
    mini = control.button_for("mini")
    full = control.button_for("full")
    spy = QSignalSpy(pill.display_mode_changed)

    assert mini.focusPolicy() & Qt.TabFocus
    assert full.focusPolicy() & Qt.TabFocus
    full.setFocus()
    qtbot.keyClick(full, Qt.Key_Left)
    qapp.processEvents()
    assert pill.display_mode() == "mini"
    assert list(spy) == [["mini"]]

    qtbot.keyClick(mini, Qt.Key_Space)
    qapp.processEvents()
    assert pill.display_mode() == "mini"
    assert list(spy) == [["mini"]]

    qtbot.keyClick(mini, Qt.Key_Right)
    qapp.processEvents()
    assert pill.display_mode() == "full"
    assert list(spy) == [["mini"], ["full"]]

    assert "完整" in control.accessibleName()
    assert "完整" in control.toolTip()
