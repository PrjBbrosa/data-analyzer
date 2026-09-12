"""Pure layout-planning tests for the bounded cursor table (spec R4/R5).

Font measurements are injected numbers, so these tests need no QApplication
and no widget; real font measurement is exercised by T2 geometry tests.
"""

import pytest

from mf4_analyzer.ui.chart_stack.cursor_table_layout import (
    TableLayoutPlan,
    choose_table_layout,
    compute_wcap,
)

LABELS4 = ("Min", "Max", "Avg", "Δ")
LABEL_WIDTHS4 = (24.0, 26.0, 22.0, 10.0)

LABELS3 = ("Min", "Avg", "Δ")
LABEL_WIDTHS3 = (24.0, 22.0, 10.0)

LABELS1 = ("Avg",)
LABEL_WIDTHS1 = (22.0,)


def plan(content, envelope=60.0, labels=LABELS4, widths=LABEL_WIDTHS4):
    return choose_table_layout(
        content_width=content,
        value_envelope_width=envelope,
        field_labels=labels,
        field_label_widths=widths,
    )


# ---- R4 budget ------------------------------------------------------------


@pytest.mark.parametrize("wsafe,expected", [
    (1184, 640),
    (884, 530),
    (784, 470),
    (544, 360),
    (484, 360),
    (344, 344),
    (200, 200),
    (0, 0),
])
def test_compute_wcap(wsafe, expected):
    assert compute_wcap(wsafe) == expected


# ---- R5 structure choice ---------------------------------------------------


def test_four_fields_wide_host_uses_the_canonical_grouped_form():
    result = plan(content=620)
    assert result.kind == "grouped"
    assert result.metric_column_count == 4
    # envelope 60 + pad 10 = 70 per column; names do not add a variable
    # signal column on wide hosts.
    assert result.column_width == 70.0
    assert result.signal_column_width == 0.0
    assert result.required_width == 4 * 70
    assert result.header_rows == 1
    assert result.rows_per_channel == 2


def test_normal_widths_keep_one_grouped_structure():
    for content in (700, 620, 480, 460, 280):
        result = plan(content=content)
        assert result.kind == "grouped"
        assert result.signal_column_width == 0.0


def test_grouped_grid_keeps_shared_columns():
    result = plan(content=460)
    assert result.kind == "grouped"
    assert result.metric_column_count == 4
    assert result.column_width == 70.0
    assert result.signal_column_width == 0.0
    assert result.required_width == 4 * 70
    assert result.header_rows == 1
    assert result.rows_per_channel == 2


def test_grid_too_wide_falls_back_to_compact_two_pairs():
    # content 250 < 280: compact; pair = (26+4) + (60+10) = 100, gap 10.
    result = plan(content=250)
    assert result.kind == "compact"
    assert result.label_column_width == 30.0
    assert result.pairs_per_row == 2
    assert result.rows_per_channel == 1 + 2
    assert result.required_width == 2 * 100 + 10
    assert result.header_rows == 0
    assert result.metric_column_count == 4


def test_compact_single_pair_when_two_pairs_do_not_fit():
    result = plan(content=150)
    assert result.kind == "compact"
    assert result.pairs_per_row == 1
    assert result.rows_per_channel == 1 + 4
    assert result.required_width == 100.0


def test_three_fields_change_structure_boundaries():
    # 3 columns x 70 = 210, so all normal widths use the same grouped form.
    wide = plan(content=620, labels=LABELS3, widths=LABEL_WIDTHS3)
    assert wide.kind == "grouped"
    assert wide.metric_column_count == 3
    # 240 content: the grid still fits, so the canonical form is grouped.
    assert plan(content=240, labels=LABELS3,
                widths=LABEL_WIDTHS3).kind == "grouped"
    # 200 content: grid 210 > 200 -> compact.
    assert plan(content=200, labels=LABELS3,
                widths=LABEL_WIDTHS3).kind == "compact"


def test_single_field_uses_grouped_form_when_it_fits():
    result = plan(content=620, labels=LABELS1, widths=LABEL_WIDTHS1)
    assert result.kind == "grouped"
    assert result.metric_column_count == 1
    assert result.column_width == 70.0


def test_no_enabled_fields_is_identity_list():
    result = plan(content=620, labels=(), widths=())
    assert result.kind == "identity"
    assert result.metric_column_count == 0
    assert result.column_width == 0.0
    assert result.header_rows == 0
    assert result.rows_per_channel == 1
    assert result.name_budget == 620.0


def test_value_envelope_controls_column_width_not_kind():
    # Envelope 200 -> pair value column 210; the 4-column grid (840) no
    # longer fits so the structure degrades to compact with two pairs
    # per row: pair = (26+4) + (200+10) = 240, gap 10.
    result = plan(content=620, envelope=200.0)
    assert result.kind == "compact"
    assert result.label_column_width == 30.0
    assert result.pairs_per_row == 2
    assert result.required_width == 2 * 240 + 10


def test_label_wider_than_envelope_grows_column():
    # A huge label ("MaximumValue") must still fit the shared column.
    result = plan(content=620, envelope=30.0,
                  labels=LABELS4, widths=(120.0, 26.0, 22.0, 10.0))
    assert result.column_width == 130.0


def test_zero_content_never_raises():
    for labels, widths in (
        (LABELS4, LABEL_WIDTHS4),
        ((),
         ()),
    ):
        result = plan(content=0, labels=labels, widths=widths)
        assert result.required_width >= 0.0
        assert result.kind in {"identity", "compact", "grouped"}


def test_plan_is_frozen_and_deterministic():
    first = plan(content=460)
    second = plan(content=460)
    assert first == second
    with pytest.raises(Exception):
        first.kind = "compact"


def test_name_budget_follows_structure():
    # The name row spans the grid, so the budget is the grid width (R5):
    # the full content width would wrap again inside the cell.
    assert plan(content=620).name_budget == 4 * 70.0
    assert plan(content=460).name_budget == 4 * 70.0
    assert plan(content=150).name_budget == 100.0
    assert plan(content=620).name_max_lines == 2


# ---- DTO display fields (R2) -----------------------------------------------


def test_dual_time_projection_carries_unitless_metric_texts():
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        build_cursor_presentation,
    )
    from mf4_analyzer.ui.cursor_display_model import (
        CursorDisplayChannel,
        CursorDisplayOptions,
    )

    channels = [
        CursorDisplayChannel(
            identity="s1", source_label="", channel_label="Torque",
            unit_suffix="U_Nm", min_value=0.04102, max_value=0.1592,
            avg_value=0.1001, delta=-0.3387,
        ),
        CursorDisplayChannel(
            identity="s2", source_label="", channel_label="Missing",
            unit_suffix="", min_value=None, max_value=None,
            avg_value=None, delta=None,
        ),
    ]
    projection = build_cursor_presentation(
        channels, CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    )
    assert projection.blocks[0].metric_texts == (
        "0.04102", "0.1592", "0.1001", "-0.3387",
    )
    assert projection.blocks[0].unit_text == "U_Nm"
    # Missing values stay "—", never 0 (R2); empty unit stays empty.
    assert projection.blocks[1].metric_texts == ("—", "—", "—", "—")
    assert projection.blocks[1].unit_text == ""
    # Legacy rows keep the joined unit value (compat contract).
    assert projection.blocks[0].visible_rows[0].value == "0.04102U_Nm"


def test_metric_texts_follow_enabled_field_order_and_toggles():
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        build_cursor_presentation,
    )
    from mf4_analyzer.ui.cursor_display_model import (
        CursorDisplayChannel,
        CursorDisplayOptions,
    )

    channels = [
        CursorDisplayChannel(
            identity="s1", source_label="", channel_label="Torque",
            unit_suffix="U_Nm", min_value=1.0, max_value=2.0,
            avg_value=3.0, delta=4.0,
        ),
    ]
    options = CursorDisplayOptions(
        show_min_value=False, show_max_value=False,
    )
    projection = build_cursor_presentation(
        channels, options, cursor_mode="dual", x_mode="time", mini=False,
    )
    # Only Avg and Δ remain, in product order.
    assert projection.blocks[0].metric_texts == ("3", "4")


def test_single_cursor_supplies_current_value_column():
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        build_cursor_presentation,
    )
    from mf4_analyzer.ui.cursor_display_model import (
        CursorDisplayChannel,
        CursorDisplayOptions,
    )

    channels = [
        CursorDisplayChannel(
            identity="s1", source_label="", channel_label="Torque",
            current_value=1.5,
        ),
    ]
    single = build_cursor_presentation(
        channels, CursorDisplayOptions(),
        cursor_mode="single", x_mode="time", mini=False,
    )
    assert single.blocks[0].metric_texts == ("1.5",)
    assert single.blocks[0].unit_text == ""


def test_short_identity_uses_actual_width_and_horizontal_priority():
    result = choose_table_layout(content_width=440, value_envelope_width=60,
                                 field_labels=LABELS4, field_label_widths=LABEL_WIDTHS4,
                                 signal_width=110)
    assert result.kind == "horizontal"
    assert result.signal_column_width == 110
    assert result.required_width == 390


def test_long_identity_has_bounded_horizontal_column():
    result = choose_table_layout(content_width=620, value_envelope_width=60,
                                 field_labels=LABELS4, field_label_widths=LABEL_WIDTHS4,
                                 signal_width=900, branch_width=32)
    assert result.kind == "horizontal"
    assert result.signal_column_width == 260
    assert result.branch_column_width == 32
    assert result.required_width == 572


def test_direction_width_participates_in_compact_fit():
    result = choose_table_layout(content_width=225, value_envelope_width=60,
                                 field_labels=LABELS4, field_label_widths=LABEL_WIDTHS4,
                                 signal_width=90, branch_width=32)
    assert result.kind == "compact"
    assert result.pairs_per_row == 1
    assert result.required_width == 132
    assert result.branch_column_width == 32
