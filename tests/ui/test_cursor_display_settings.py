"""Cursor display options, pure projection, and adaptive widget contracts."""

from dataclasses import replace
from itertools import product

from PyQt5.QtCore import QSettings, QRect, Qt
from PyQt5.QtTest import QSignalSpy
from PyQt5.QtWidgets import QWidget
import pytest

from mf4_analyzer.ui.chart_stack.cursor_display import (
    CursorDisplayBranch,
    CursorDisplayChannel,
    CursorDisplayOptions,
    CursorDisplayPopover,
    CursorDisplaySettingsStore,
    build_cursor_presentation,
)


def _options(bits):
    return CursorDisplayOptions(*bits)


def _time_rows(count=1, *, duplicate_label=False):
    return tuple(
        CursorDisplayChannel(
            identity=(f"source-{index}", "Speed"),
            source_label=f"run_{index}",
            channel_label="Speed" if duplicate_label else f"Speed {index + 1}",
            color="#1769e0",
            unit_suffix=" rpm",
            current_value=4.25 + index,
            delta=2.5 + index,
            min_value=1.0 + index,
            max_value=9.0 + index,
            avg_value=5.0 + index,
            diagnostic=f"diagnostic-{index}",
        )
        for index in range(count)
    )


def _custom_rows(count=1, *, duplicate_label=False):
    return tuple(
        CursorDisplayChannel(
            identity=(f"source-{index}", "Rack Force"),
            source_label=f"trace_{index}",
            channel_label="Rack Force" if duplicate_label else f"Rack Force {index + 1}",
            color="#ef4444",
            unit_suffix=" N",
            diagnostic=f"branch-diagnostic-{index}",
            branches=(
                CursorDisplayBranch(
                    label="X↑", current_value=3.25 + index,
                    min_value=1.0 + index, max_value=5.0 + index,
                    avg_value=3.0 + index,
                ),
                CursorDisplayBranch(
                    label="X↓", current_value=2.25 + index,
                    min_value=0.0 + index, max_value=4.0 + index,
                    avg_value=2.0 + index,
                ),
            ),
        )
        for index in range(count)
    )


@pytest.mark.parametrize("bits", tuple(product((False, True), repeat=5)))
def test_all_32_options_project_deterministically_without_orphans(bits):
    options = _options(bits)
    enabled = [
        label for label, flag in (
            ("Min", options.show_min_value),
            ("Max", options.show_max_value),
            ("Avg", options.show_avg_value),
        ) if flag
    ]
    for x_mode, factory in (("time", _time_rows), ("custom", _custom_rows)):
        for count in (1, 2):
            for mini in (False, True):
                projection = build_cursor_presentation(
                    factory(count), options,
                    cursor_mode="dual", x_mode=x_mode, mini=mini,
                )
                assert len(projection.blocks) == count
                assert projection.html.strip()
                assert "></td>" not in projection.html
                assert all(block.visible_rows for block in projection.blocks)
                assert all(block.identity is not None for block in projection.blocks)
                for block in projection.blocks:
                    labels = [row.label for row in block.visible_rows]
                    if x_mode == "time":
                        assert "Δ" in labels
                        metric_labels = [item for item in labels if item in {"Min", "Max", "Avg"}]
                        assert metric_labels == ([] if mini else enabled)
                    else:
                        assert "X↑" in labels and "X↓" in labels
                        assert "Δ" not in labels
                        visible_metrics = [item for item in labels if item in {"Min", "Max", "Avg"}]
                        if mini:
                            priority = next(
                                (name for name in ("Avg", "Max", "Min") if name in enabled),
                                None,
                            )
                            assert visible_metrics == ([priority, priority] if priority else [])
                        else:
                            assert visible_metrics == enabled * 2
                    for label in enabled:
                        assert label in projection.tooltip
                    for label in ({"Min", "Max", "Avg"} - set(enabled)):
                        assert f"{label}=" not in projection.tooltip
                assert "diagnostic-" in projection.tooltip or "branch-diagnostic-" in projection.tooltip
                assert "run_" in projection.tooltip or "trace_" in projection.tooltip


@pytest.mark.parametrize("x_mode,rows", (("time", _time_rows(2)), ("custom", _custom_rows(2))))
@pytest.mark.parametrize("mini", (False, True))
def test_point_bits_do_not_change_result_projection_or_layout_category(x_mode, rows, mini):
    baseline = CursorDisplayOptions(False, False, True, False, True)
    toggled = replace(baseline, show_max_point=True, show_min_point=True)
    left = build_cursor_presentation(
        rows, baseline, cursor_mode="dual", x_mode=x_mode, mini=mini,
    )
    right = build_cursor_presentation(
        rows, toggled, cursor_mode="dual", x_mode=x_mode, mini=mini,
    )
    assert left == right
    assert left.layout_category == right.layout_category


def test_custom_x_single_shows_current_branches_only_in_full_and_mini():
    for mini in (False, True):
        projection = build_cursor_presentation(
            _custom_rows(), CursorDisplayOptions(),
            cursor_mode="single", x_mode="custom", mini=mini,
        )
        visible = [row.label for row in projection.blocks[0].visible_rows]
        assert visible == ["X↑", "X↓"]
        assert "3.25 N" in projection.html
        assert "2.25 N" in projection.html
        assert not ({"Min", "Max", "Avg", "Δ"} & set(visible))


def test_time_x_single_shows_only_the_real_current_value_in_full_and_mini():
    for mini in (False, True):
        projection = build_cursor_presentation(
            _time_rows(), CursorDisplayOptions(),
            cursor_mode="single", x_mode="time", mini=mini,
        )
        rows = projection.blocks[0].visible_rows
        assert [(row.label, row.value) for row in rows] == [("Value", "4.25 rpm")]
        assert "Value=4.25 rpm" in projection.tooltip
        assert not ({"Min", "Max", "Avg", "Δ"} & {row.label for row in rows})


def test_time_x_single_missing_current_value_never_falls_back_to_statistics():
    channel = replace(_time_rows()[0], current_value=None)
    projection = build_cursor_presentation(
        (channel,), CursorDisplayOptions(),
        cursor_mode="single", x_mode="time", mini=False,
    )
    assert [(row.label, row.value) for row in projection.blocks[0].visible_rows] == [
        ("Value", "—"),
    ]
    assert "Δ=" not in projection.tooltip
    assert "Min=" not in projection.tooltip
    assert "Max=" not in projection.tooltip
    assert "Avg=" not in projection.tooltip


def test_duplicate_display_labels_keep_two_composite_blocks_and_full_tooltip_identity():
    projection = build_cursor_presentation(
        _time_rows(2, duplicate_label=True), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=True,
    )
    assert [block.identity for block in projection.blocks] == [
        ("source-0", "Speed"), ("source-1", "Speed")
    ]
    assert "run_0 / Speed" in projection.tooltip
    assert "run_1 / Speed" in projection.tooltip


def test_settings_store_uses_one_json_key_and_defaults_each_invalid_field(tmp_path):
    settings = QSettings(str(tmp_path / "cursor.ini"), QSettings.IniFormat)
    store = CursorDisplaySettingsStore(settings)
    assert store.load() == CursorDisplayOptions()
    saved = CursorDisplayOptions(True, False, False, True, False)
    store.save(saved)
    assert settings.allKeys() == ["charts/time_cursor/display_options_v1"]
    assert store.load() == saved
    settings.setValue(
        "charts/time_cursor/display_options_v1",
        '{"show_max_point":false,"show_min_point":"bad","show_max_value":0}',
    )
    assert store.load() == CursorDisplayOptions(False, True, True, True, True)


def test_cursor_pill_natural_then_constrained_width_and_whole_block_truncation(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(760, 420)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    projection = build_cursor_presentation(
        _time_rows(5), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    )
    pill.set_display_projection(projection)
    parent.show()
    qapp.processEvents()
    assert pill.layout_category() == "natural"
    assert pill.visible_channel_count() == 5
    parent.resize(250, 130)
    pill.reflow_to_parent()
    qapp.processEvents()
    assert pill.layout_category() == "constrained"
    assert pill.width() <= parent.width() - 16
    assert pill.height() <= parent.height() - 16
    assert 0 < pill.visible_channel_count() < 5
    assert "+" in pill.detail_text() and "channels" in pill.detail_text()
    assert "run_4 / Speed 5" in pill._detail.toolTip()


def test_cursor_pill_user_anchor_and_popover_collision_restore_without_drift(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(720, 380)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    pill.set_display_projection(build_cursor_presentation(
        _time_rows(2), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    ))
    parent.show()
    pill.show()
    pill.move(parent.width() - pill.width() - 8, 24)
    pill.mark_user_placed()
    qapp.processEvents()
    original = pill.geometry()
    original_right = original.right()
    pill.set_display_projection(build_cursor_presentation(
        _time_rows(3), CursorDisplayOptions(False, False, True, True, True),
        cursor_mode="dual", x_mode="time", mini=False,
    ))
    assert abs(pill.geometry().right() - original_right) <= 1
    assert pill.y() == original.y()
    popover_rect = QRect(pill.x() + pill.width() - 24, pill.y(), 180, 220)
    pill.avoid_rect(popover_rect, gap=8)
    assert not pill.geometry().intersects(popover_rect.adjusted(-8, -8, 8, 8))
    pill.restore_after_avoidance()
    restored = pill.geometry()
    pill.avoid_rect(popover_rect, gap=8)
    pill.restore_after_avoidance()
    assert pill.geometry() == restored


def test_cursor_pill_restores_original_right_anchor_after_width_changes_while_avoided(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(900, 500)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    pill.set_display_projection(build_cursor_presentation(
        _time_rows(1), CursorDisplayOptions(False, False, False, False, False),
        cursor_mode="dual", x_mode="time", mini=False,
    ))
    parent.show()
    pill.show()
    pill.move(620, 30)
    pill.mark_user_placed()
    qapp.processEvents()
    original_right = pill.geometry().right()
    original_top = pill.y()
    obstacle = QRect(pill.x() + pill.width() - 20, pill.y(), 180, 220)
    pill.avoid_rect(obstacle, gap=8)
    pill.set_display_projection(build_cursor_presentation(
        _time_rows(3), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    ))
    assert pill.width() > 0
    pill.restore_after_avoidance()
    assert abs(pill.geometry().right() - original_right) <= 1
    assert pill.y() == original_top


def test_cursor_pill_extremely_short_host_shows_only_fitting_summary(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    parent.resize(260, 72)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    projection = build_cursor_presentation(
        _time_rows(3), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    )
    pill.set_display_projection(projection)
    parent.show()
    pill.show()
    qapp.processEvents()
    assert pill.layout_category() == "constrained"
    assert pill.visible_channel_count() == 0
    assert "+3 channels" in pill.detail_text()
    assert "run_0 / Speed 1" not in pill.detail_text()
    assert pill.height() <= pill.safe_rect().height()


def test_cursor_pill_middle_elides_constrained_identity_but_tooltip_keeps_full_text(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    parent = QWidget()
    qtbot.addWidget(parent)
    # This width still forces constrained rendering for the full identity, but
    # leaves enough measured text space to prove both retained identity ends.
    parent.resize(440, 210)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    source = "source_begin_" + "x" * 70 + "_source_end"
    channel = "channel_begin_" + "y" * 70 + "_channel_end"
    full_identity = f"{source} / {channel}"
    projection = build_cursor_presentation((CursorDisplayChannel(
        identity=(source, channel), source_label=source, channel_label=channel,
        color="#1769e0", unit_suffix=" V", delta=1.0,
        min_value=0.0, max_value=2.0, avg_value=1.0,
    ),), CursorDisplayOptions(), cursor_mode="dual", x_mode="time", mini=False)
    pill.set_display_projection(projection)
    parent.show()
    pill.show()
    qapp.processEvents()
    visible = pill.detail_text()
    assert pill.layout_category() == "constrained"
    assert full_identity not in visible
    assert "..." in visible
    displayed_identity = pill._middle_elide_label(
        full_identity, int(pill._detail.maximumWidth() * 1.2)
    )
    assert displayed_identity in visible
    assert displayed_identity.startswith(source[0])
    assert displayed_identity.endswith(channel[-1])
    assert pill._detail.toolTip().splitlines()[0] == full_identity
    assert pill.width() <= pill.safe_rect().width()


def test_cursor_display_popover_uses_native_popup_shell_chrome(qapp, qtbot):
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    assert popover.windowFlags() & Qt.Popup
    assert popover.windowFlags() & Qt.FramelessWindowHint
    assert popover.windowFlags() & Qt.NoDropShadowWindowHint
    assert popover.testAttribute(Qt.WA_TranslucentBackground)


def test_time_card_settings_button_stays_beside_cursor_segment_and_emits_options(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack

    stack = ChartStack()
    qtbot.addWidget(stack)
    # The real three-pane MainWindow leaves the chart toolbar about 500 px wide
    # at its minimum window size.  This is the actual constrained container,
    # not the much wider standalone ChartStack default.
    stack.resize(500, 440)
    stack.show()
    qapp.processEvents()
    card = stack._time_card
    button = card.cursor_display_settings_button()
    assert button.isVisible()
    assert all(item.isVisible() for item in card._cursor_buttons.values())
    assert button.geometry().left() >= card._cursor_buttons["dual"].geometry().right()
    assert button.geometry().right() <= card.toolbar.contentsRect().right()
    card.set_cursor_mode("single")
    button.click()
    qapp.processEvents()
    popover = card.cursor_display_popover()
    assert popover.isVisible()
    assert "双游标统计" in popover.context_note()
    spy = QSignalSpy(card.cursor_display_options_changed)
    popover.checkbox("show_avg_value").click()
    assert len(spy) == 1
    assert spy[0][0].show_avg_value is False
    card.set_cursor_mode("off")
    assert not popover.isVisible()
