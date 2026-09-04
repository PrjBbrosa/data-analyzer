"""Frozen-output tests for the cursor pill's HTML formatting helpers.

Spec: docs/analyzer/specs/2026-08-04-chartstack-markup-slimming-design.md (D-D1).

These six helpers turn the canvas' cursor-readout HTML into the pill's primary
line, its full/mini detail tables and the mini-mode tooltip. Before package D
they lived on ``ChartStack`` and were only reachable through whole-window tests;
this file pins their exact output so the move into ``cursor_pill.py`` is
provably behaviour-preserving.

Every expected value below was captured from the pre-move implementation on
``main`` @ ``ab19622f`` and frozen verbatim -- none of it was derived by
re-deriving the production format string. The pill's HTML output is explicitly
off-limits for "drive-by prettification" (plan, 明确禁止), so a diff here means
a regression, not a test that needs updating.

Corpus is EPS-flavoured (steering-wheel torque / motor speed / motor torque),
matching the readouts the fixtures in ``test_chart_stack.py`` use.
"""
import pytest

from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP
from mf4_analyzer.ui.chart_stack import cursor_pill


# ---------------------------------------------------------------------------
# Inputs -- representative cursor-readout strings as the canvas emits them
# ---------------------------------------------------------------------------

SINGLE_ONE_CHANNEL = _CURSOR_HTML_SEP.join([
    '<span style="color:#111827;">t=35.0358s</span>',
    '<span style="color:#64748b;">[eps_run]</span> '
    '<span style="color:#ef4444;">Rte_PA_mAtMotorTorque_xds16=<b>-1.841 Nm</b></span>',
])

SINGLE_MULTI_CHANNEL = _CURSOR_HTML_SEP.join([
    '<span style="color:#111827;">t=89.1278s</span>',
    '<span style="color:#64748b;">[eps_run]</span> '
    '<span style="color:#ef4444;">Rte_ESChkPlausi_mESMotorTorque_xds16=<b>0 Nm</b></span>',
    '<span style="color:#64748b;">[eps_run]</span> '
    '<span style="color:#1769e0;">Rte_MotorSpeed_xds16=<b>1250 rpm</b></span>',
])

ESCAPED_ENTITIES = _CURSOR_HTML_SEP.join([
    '<span style="color:#111827;">t=35.0358s</span>',
    '<span style="color:#22c55e;">escaped=<b>1 &lt;A&gt;&amp;</b></span>',
])

# Dual-cursor readouts carry no separator -- the whole string is the primary line.
DUAL_NO_SEPARATOR = '<b>A=1.0s  B=2.0s  ΔT=1.0s</b>'


# ---------------------------------------------------------------------------
# Frozen outputs
# ---------------------------------------------------------------------------

_MONO = "font-family:'SF Mono',Menlo,Consolas,monospace;"

SINGLE_ONE_PRIMARY = '<span style="color:#111827;">t=35.0358s</span>'

SINGLE_ONE_FULL_DETAIL = (
    '<table cellspacing="0" cellpadding="0">'
    '<tr><td style="padding-top:0; padding-bottom:0; line-height:1.15;">'
    '<span style="color:#64748b;">[eps_run]</span> '
    '<span style="color:#ef4444;">Rte_PA_mAtMotorTorque_xds16=<b>-1.841 Nm</b></span>'
    '</td></tr></table>'
)

SINGLE_ONE_MINI_DETAIL = (
    '<table cellspacing="0" cellpadding="0" style="font-size:12px;">'
    '<tr>'
    '<td style="padding-top:0; padding-right:5px; line-height:1.15;">'
    '<span style="color:#ef4444;">●</span></td>'
    '<td style="padding-top:0; color:#ef4444; line-height:1.15; '
    f'{_MONO} font-weight:650;">-1.841 Nm</td>'
    '</tr></table>'
)

SINGLE_ONE_TOOLTIP = 'Rte_PA_mAtMotorTorque_xds16=-1.841 Nm'

SINGLE_MULTI_PRIMARY = '<span style="color:#111827;">t=89.1278s</span>'

SINGLE_MULTI_FULL_DETAIL = (
    '<table cellspacing="0" cellpadding="0">'
    '<tr><td style="padding-top:0; padding-bottom:0; line-height:1.15;">'
    '<span style="color:#64748b;">[eps_run]</span> '
    '<span style="color:#ef4444;">Rte_ESChkPlausi_mESMotorTorque_xds16=<b>0 Nm</b></span>'
    '</td></tr>'
    '<tr><td style="padding-top:2px; padding-bottom:0; line-height:1.15;">'
    '<span style="color:#64748b;">[eps_run]</span> '
    '<span style="color:#1769e0;">Rte_MotorSpeed_xds16=<b>1250 rpm</b></span>'
    '</td></tr></table>'
)

SINGLE_MULTI_MINI_DETAIL = (
    '<table cellspacing="0" cellpadding="0" style="font-size:12px;">'
    '<tr>'
    '<td style="padding-top:0; padding-right:5px; line-height:1.15;">'
    '<span style="color:#ef4444;">●</span></td>'
    '<td style="padding-top:0; color:#ef4444; line-height:1.15; '
    f'{_MONO} font-weight:650;">0 Nm</td>'
    '</tr>'
    '<tr>'
    '<td style="padding-top:2px; padding-right:5px; line-height:1.15;">'
    '<span style="color:#1769e0;">●</span></td>'
    '<td style="padding-top:2px; color:#1769e0; line-height:1.15; '
    f'{_MONO} font-weight:650;">1250 rpm</td>'
    '</tr></table>'
)

SINGLE_MULTI_TOOLTIP = (
    'Rte_ESChkPlausi_mESMotorTorque_xds16=0 Nm\n'
    'Rte_MotorSpeed_xds16=1250 rpm'
)


@pytest.fixture
def stack(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    return cs


# ---------------------------------------------------------------------------
# _format_single_cursor_variants_for_pill -- the four-tuple the pill consumes
# ---------------------------------------------------------------------------

def test_single_channel_readout_splits_into_frozen_variants(stack):
    primary, full_detail, mini_detail, tooltip = (
        stack._format_single_cursor_variants_for_pill(SINGLE_ONE_CHANNEL)
    )

    assert primary == SINGLE_ONE_PRIMARY
    assert full_detail == SINGLE_ONE_FULL_DETAIL
    assert mini_detail == SINGLE_ONE_MINI_DETAIL
    assert tooltip == SINGLE_ONE_TOOLTIP


def test_multi_channel_readout_splits_into_frozen_variants(stack):
    primary, full_detail, mini_detail, tooltip = (
        stack._format_single_cursor_variants_for_pill(SINGLE_MULTI_CHANNEL)
    )

    assert primary == SINGLE_MULTI_PRIMARY
    assert full_detail == SINGLE_MULTI_FULL_DETAIL
    assert mini_detail == SINGLE_MULTI_MINI_DETAIL
    assert tooltip == SINGLE_MULTI_TOOLTIP


def test_first_detail_row_has_no_top_padding_and_later_rows_do(stack):
    """Row spacing is what keeps the pill compact; only rows 2..n get 2px.
    The full table has one cell per row, the mini table has two."""
    _p, full_detail, mini_detail, _t = (
        stack._format_single_cursor_variants_for_pill(SINGLE_MULTI_CHANNEL)
    )

    assert full_detail.count('padding-top:0;') == 1
    assert full_detail.count('padding-top:2px;') == 1
    assert mini_detail.count('padding-top:0;') == 2
    assert mini_detail.count('padding-top:2px;') == 2
    assert 'padding-top:6px' not in full_detail + mini_detail


def test_mini_variant_drops_channel_names_and_keeps_only_values(stack):
    _p, _full, mini_detail, _t = (
        stack._format_single_cursor_variants_for_pill(SINGLE_MULTI_CHANNEL)
    )

    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16' not in mini_detail
    assert 'Rte_MotorSpeed_xds16' not in mini_detail
    assert '[eps_run]' not in mini_detail
    assert '=' not in stack._strip_html(mini_detail)
    assert '0 Nm' in mini_detail and '1250 rpm' in mini_detail


def test_mini_variant_colours_the_dot_with_the_channel_not_the_prefix(stack):
    """``#64748b`` is the dimmed ``[file]`` prefix colour; the dot must take the
    channel's own colour instead."""
    _p, _full, mini_detail, _t = (
        stack._format_single_cursor_variants_for_pill(SINGLE_MULTI_CHANNEL)
    )

    assert '<span style="color:#ef4444;">●</span>' in mini_detail
    assert '<span style="color:#1769e0;">●</span>' in mini_detail
    assert '<span style="color:#64748b;">●</span>' not in mini_detail


def test_mini_variant_keeps_entities_escaped_while_tooltip_unescapes(stack):
    """The mini cell is rebuilt as plain text then re-escaped, so ``&lt;`` must
    survive as markup; the tooltip is plain text and gets the real characters."""
    _p, _full, mini_detail, tooltip = (
        stack._format_single_cursor_variants_for_pill(ESCAPED_ENTITIES)
    )

    assert '1 &lt;A&gt;&amp;' in mini_detail
    assert '1 <A>&' not in mini_detail
    assert tooltip == 'escaped=1 <A>&'


@pytest.mark.parametrize('text', [
    DUAL_NO_SEPARATOR,
    'naked text',
    '',
])
def test_readout_without_separator_passes_through_as_primary_only(stack, text):
    assert stack._format_single_cursor_variants_for_pill(text) == (text, '', '', '')


def test_none_readout_is_tolerated(stack):
    assert stack._format_single_cursor_variants_for_pill(None) == (None, '', '', '')


def test_value_without_bold_markup_falls_back_to_text_after_equals(stack):
    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=1.0s</span>',
        '<span style="color:#7c3aed;">[eps_run] Rte_HandWheelTorque_xds16=7.25 Nm</span>',
    ])

    _p, _full, mini_detail, tooltip = (
        stack._format_single_cursor_variants_for_pill(text)
    )

    assert '>7.25 Nm</td>' in mini_detail
    assert 'Rte_HandWheelTorque_xds16' not in mini_detail
    assert tooltip == 'Rte_HandWheelTorque_xds16=7.25 Nm'


# ---------------------------------------------------------------------------
# _format_cursor_info_for_pill -- the mode gate in front of the splitter
# ---------------------------------------------------------------------------

def test_only_single_mode_splits_the_readout(stack):
    primary, detail = stack._format_cursor_info_for_pill(
        SINGLE_MULTI_CHANNEL, 'single')
    assert primary == SINGLE_MULTI_PRIMARY
    assert detail == SINGLE_MULTI_FULL_DETAIL

    primary, detail = stack._format_cursor_info_for_pill(
        SINGLE_MULTI_CHANNEL, 'dual')
    assert primary == SINGLE_MULTI_CHANNEL
    assert detail == ''


def test_separatorless_text_is_untouched_even_in_single_mode(stack):
    assert stack._format_cursor_info_for_pill(DUAL_NO_SEPARATOR, 'single') == (
        DUAL_NO_SEPARATOR, '')


def test_omitted_mode_is_resolved_from_the_live_cursor_mode(stack):
    """``mode=None`` must consult ``cursor_mode()`` -- the one stateful thread in
    this otherwise pure group, and the reason the delegate keeps the default."""
    stack.set_cursor_mode('single')
    assert stack._format_cursor_info_for_pill(SINGLE_MULTI_CHANNEL) == (
        SINGLE_MULTI_PRIMARY, SINGLE_MULTI_FULL_DETAIL)

    stack.set_cursor_mode('off')
    assert stack._format_cursor_info_for_pill(SINGLE_MULTI_CHANNEL) == (
        SINGLE_MULTI_CHANNEL, '')


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('value,expected', [
    ('', ''),
    (None, ''),
    ('plain', 'plain'),
    ('<span style="color:#ef4444;"><i>steer<b>ing</b></i>=<b>3<sub>2</sub></b></span>',
     'steering=32'),
    ('a &lt;b&gt; &amp; c&nbsp;d', 'a <b> & c\xa0d'),
])
def test_strip_html_removes_tags_then_unescapes(stack, value, expected):
    assert stack._strip_html(value) == expected


# ---------------------------------------------------------------------------
# _single_cursor_channel_color
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('part,expected', [
    # The dimmed [file] prefix colour is skipped in favour of the channel's.
    ('<span style="color:#64748b;">[eps_run]</span> '
     '<span style="color:#ef4444;">n=<b>1</b></span>', '#ef4444'),
    # Nothing coloured at all -> the default ink.
    ('<span>n=<b>1</b></span>', '#111827'),
    # Only the prefix colour present -> it is used rather than inventing one.
    ('<span style="color:#64748b;">[eps_run] n=<b>1</b></span>', '#64748b'),
    # Colour appears only after the bold value -> still found by the fallback.
    ('<b>1</b><span style="color:#22c55e;">tail</span>', '#22c55e'),
    (None, '#111827'),
])
def test_channel_colour_prefers_the_channel_over_the_prefix(stack, part, expected):
    assert stack._single_cursor_channel_color(part) == expected


# ---------------------------------------------------------------------------
# _mini_single_cursor_part
# ---------------------------------------------------------------------------

def test_mini_part_is_a_two_cell_row_with_frozen_styling(stack):
    assert stack._mini_single_cursor_part(
        '<span style="color:#ef4444;">n=<b>-1.841 Nm</b></span>', '0'
    ) == (
        '<tr>'
        '<td style="padding-top:0; padding-right:5px; line-height:1.15;">'
        '<span style="color:#ef4444;">●</span></td>'
        '<td style="padding-top:0; color:#ef4444; line-height:1.15; '
        f'{_MONO} font-weight:650;">-1.841 Nm</td>'
        '</tr>'
    )


def test_mini_part_threads_the_top_padding_into_both_cells(stack):
    row = stack._mini_single_cursor_part(
        '<span style="color:#ef4444;">n=<b>-1.841 Nm</b></span>', '2px')
    assert row.count('padding-top:2px;') == 2


def test_mini_part_shows_an_em_dash_when_there_is_no_value(stack):
    row = stack._mini_single_cursor_part('', '0')
    assert '>—</td>' in row
    assert 'color:#111827;' in row


# ---------------------------------------------------------------------------
# _plain_single_cursor_tooltip_line
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('part,expected', [
    ('<span style="color:#64748b;">[eps_run]</span> '
     '<span style="color:#ef4444;">Rte_PA_mAtMotorTorque_xds16=<b>-1.841 Nm</b></span>',
     'Rte_PA_mAtMotorTorque_xds16=-1.841 Nm'),
    # No '=' -> the [file] prefix is still stripped off the bare readout.
    ('<span style="color:#64748b;">[eps_run]</span> <span>bare readout</span>',
     'bare readout'),
    ('', ''),
    (None, ''),
    # nbsp and runs of whitespace collapse to single spaces.
    ('<span>a\xa0\xa0 b  =  <b>  1   2 </b></span>', 'a b=1 2'),
    # Empty name -> the value alone, with no stray '='.
    ('<span>=<b>5</b></span>', '5'),
])
def test_tooltip_line_is_plain_name_equals_value(stack, part, expected):
    assert stack._plain_single_cursor_tooltip_line(part) == expected


# ---------------------------------------------------------------------------
# Direct module-level use -- no ChartStack, no widget, no QApplication
# ---------------------------------------------------------------------------

def test_formatting_works_without_constructing_any_widget():
    """The point of the move: these are callable as plain functions. No fixture
    is requested here on purpose, so this fails if formatting ever starts
    needing a live widget again."""
    assert cursor_pill.format_single_cursor_variants(SINGLE_MULTI_CHANNEL) == (
        SINGLE_MULTI_PRIMARY,
        SINGLE_MULTI_FULL_DETAIL,
        SINGLE_MULTI_MINI_DETAIL,
        SINGLE_MULTI_TOOLTIP,
    )
    assert cursor_pill.format_cursor_info(SINGLE_ONE_CHANNEL, 'single') == (
        SINGLE_ONE_PRIMARY, SINGLE_ONE_FULL_DETAIL)
    assert cursor_pill.strip_html('<b>7.25</b>&nbsp;Nm') == '7.25\xa0Nm'
    assert cursor_pill.single_cursor_channel_color(
        '<span style="color:#64748b;">[eps_run]</span> '
        '<span style="color:#ef4444;">n=<b>1</b></span>') == '#ef4444'
    assert '—' in cursor_pill.mini_single_cursor_part('', '0')
    assert cursor_pill.plain_single_cursor_tooltip_line(
        '<span>[eps_run] n=<b>1</b></span>') == 'n=1'


def test_format_cursor_info_requires_an_explicit_mode():
    """Resolving the default from live state stays on ChartStack; the module
    function must not grow a mode default that silently guesses."""
    with pytest.raises(TypeError):
        cursor_pill.format_cursor_info(SINGLE_ONE_CHANNEL)


def test_chart_stack_delegates_are_pure_pass_throughs(stack):
    """Every ChartStack method kept for compatibility must return exactly what
    the module function returns."""
    part = ('<span style="color:#64748b;">[eps_run]</span> '
            '<span style="color:#ef4444;">Rte_MotorSpeed_xds16=<b>1250 rpm</b></span>')

    assert (stack._format_single_cursor_variants_for_pill(SINGLE_MULTI_CHANNEL)
            == cursor_pill.format_single_cursor_variants(SINGLE_MULTI_CHANNEL))
    assert (stack._format_cursor_info_for_pill(SINGLE_MULTI_CHANNEL, 'single')
            == cursor_pill.format_cursor_info(SINGLE_MULTI_CHANNEL, 'single'))
    assert (stack._mini_single_cursor_part(part, '2px')
            == cursor_pill.mini_single_cursor_part(part, '2px'))
    assert (stack._plain_single_cursor_tooltip_line(part)
            == cursor_pill.plain_single_cursor_tooltip_line(part))
    assert (stack._single_cursor_channel_color(part)
            == cursor_pill.single_cursor_channel_color(part))
    assert stack._strip_html(part) == cursor_pill.strip_html(part)


def _custom_x_pill_rows():
    from mf4_analyzer.ui.plot_helpers import DualCursorBranch, DualCursorRow
    from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE

    return [
        DualCursorRow(
            channel_name="[sfns] Rack Force",
            min_value=1.0,
            max_value=3.0,
            avg=2.0,
            delta=None,
            unit_suffix=" N",
            color="#ef4444",
            mode=CHANNEL_MODE,
            branches=(
                DualCursorBranch(1, 1.0, 3.0, 2.0),
                DualCursorBranch(-1, 0.0, 2.0, 1.0),
            ),
        )
    ]


def test_custom_x_pill_full_mode_has_branch_subrows_without_delta(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    pill = CursorPill()
    qtbot.addWidget(pill)
    pill.set_dual_rows(_custom_x_pill_rows())
    html = pill.detail_text()
    assert "X↑" in html and "X↓" in html
    assert "Rack Force" in html
    assert "△" not in html
    assert "N" in html


def test_custom_x_pill_mini_keeps_direction_avg_without_hover_tooltip(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    pill = CursorPill()
    qtbot.addWidget(pill)
    pill.set_dual_rows(_custom_x_pill_rows())
    pill._toggle_mode()
    html = pill.detail_text()
    assert "X↑" in html and "X↓" in html
    assert "Avg" in html
    assert pill._detail.toolTip() == ""
