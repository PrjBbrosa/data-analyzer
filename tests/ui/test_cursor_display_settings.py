"""Cursor display options, pure projection, and adaptive widget contracts."""

from dataclasses import replace
from itertools import product
import re

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
                    avg_value=3.0 + index, delta_value=1.5 + index,
                ),
                CursorDisplayBranch(
                    label="X↓", current_value=2.25 + index,
                    min_value=0.0 + index, max_value=4.0 + index,
                    avg_value=2.0 + index, delta_value=-0.5 + index,
                ),
            ),
        )
        for index in range(count)
    )


@pytest.mark.parametrize("bits", tuple(product((False, True), repeat=6)))
def test_all_64_options_project_deterministically_without_orphans(bits):
    options = _options(bits)
    enabled = [
        label for label, flag in (
            ("Min", options.show_min_value),
            ("Max", options.show_max_value),
            ("Avg", options.show_avg_value),
            ("Δ", options.show_delta_value),
        ) if flag
    ]
    all_metrics = {"Min", "Max", "Avg", "Δ"}
    for x_mode, factory in (("time", _time_rows), ("custom", _custom_rows)):
        for count in (1, 2):
            for mini in (False, True):
                projection = build_cursor_presentation(
                    factory(count), options,
                    cursor_mode="dual", x_mode=x_mode, mini=mini,
                )
                assert len(projection.blocks) == count
                assert projection.html.strip()
                assert not re.search(r"<td(?:\s[^>]*)?>\s*</td>", projection.html)
                assert all(block.visible_rows for block in projection.blocks)
                assert all(block.identity is not None for block in projection.blocks)
                for block in projection.blocks:
                    labels = [row.label for row in block.visible_rows]
                    if x_mode == "time":
                        metric_labels = [item for item in labels if item in all_metrics]
                        assert metric_labels == ([] if mini else enabled)
                        if mini:
                            assert "Δ" not in labels
                            assert "●" in projection.html
                            if options.show_delta_value:
                                assert "△" in projection.html
                                assert "Δ=" in projection.tooltip
                            else:
                                assert "△" not in projection.html
                                assert "Δ=" not in projection.tooltip
                    else:
                        assert "X↑" in labels and "X↓" in labels
                        visible_metrics = [item for item in labels if item in all_metrics]
                        if mini:
                            priority = next(
                                (name for name in ("Δ", "Avg", "Max", "Min") if name in enabled),
                                None,
                            )
                            assert visible_metrics == ([priority, priority] if priority else [])
                            assert "●" in projection.html
                        else:
                            assert visible_metrics == enabled * 2
                            assert "●" not in projection.html
                    for label in enabled:
                        assert label in projection.tooltip
                    for label in (all_metrics - set(enabled)):
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
    full = build_cursor_presentation(
        _custom_rows(), CursorDisplayOptions(),
        cursor_mode="single", x_mode="custom", mini=False,
    )
    mini = build_cursor_presentation(
        _custom_rows(), CursorDisplayOptions(),
        cursor_mode="single", x_mode="custom", mini=True,
    )
    full_visible = [row.label for row in full.blocks[0].visible_rows]
    mini_visible = [row.label for row in mini.blocks[0].visible_rows]
    assert full_visible != mini_visible
    assert full_visible[0] == "Rack Force 1"
    assert mini_visible[0] == "●"
    assert "X↑" in full_visible and "X↓" in full_visible
    assert "X↑" in mini_visible and "X↓" in mini_visible
    assert "3.25 N" in full.html and "3.25 N" in mini.html
    assert "2.25 N" in full.html and "2.25 N" in mini.html
    assert "Rack Force 1" in full.html
    assert "●" in mini.html
    assert "Rack Force 1" not in mini.html
    assert not ({"Min", "Max", "Avg", "Δ"} & set(full_visible))
    assert not ({"Min", "Max", "Avg", "Δ"} & set(mini_visible))
    assert full.html != mini.html


@pytest.mark.parametrize("cursor_mode", ("single", "dual"))
@pytest.mark.parametrize("mini", (False, True))
@pytest.mark.parametrize(
    "diagnostic",
    (
        "当前 X 不在有效路径内",
        "X/Y 形状不兼容",
        "无法可靠区分升程/回程",
    ),
)
def test_custom_x_diagnostic_only_channel_is_a_populated_block(
    cursor_mode, mini, diagnostic
):
    channel = CursorDisplayChannel(
        identity=("source-a", "Rack Force"),
        source_label="source-a",
        channel_label="Rack Force",
        color="#1769e0",
        unit_suffix=" N",
        diagnostic=diagnostic,
    )

    projection = build_cursor_presentation(
        (channel,), CursorDisplayOptions(),
        cursor_mode=cursor_mode, x_mode="custom", mini=mini,
    )

    assert len(projection.blocks) == 1
    block = projection.blocks[0]
    assert block.identity == ("source-a", "Rack Force")
    assert [(row.label, row.value) for row in block.visible_rows] == [
        ("状态", diagnostic),
    ]
    assert diagnostic in projection.html
    assert diagnostic in projection.tooltip
    assert "source-a / Rack Force" in projection.tooltip


def test_time_x_single_full_uses_channel_name_not_a_value_label():
    projection = build_cursor_presentation(
        _time_rows(), CursorDisplayOptions(),
        cursor_mode="single", x_mode="time", mini=False,
    )
    rows = projection.blocks[0].visible_rows
    assert [(row.label, row.value) for row in rows] == [("Speed 1", "4.25 rpm")]
    assert "Speed 1=4.25 rpm" in projection.tooltip
    assert "Value" not in projection.html
    assert projection.html.count("<tr>") == 1
    assert not ({"Min", "Max", "Avg", "Δ"} & {row.label for row in rows})


def test_time_x_single_mini_uses_colored_dot_instead_of_name():
    projection = build_cursor_presentation(
        _time_rows(), CursorDisplayOptions(),
        cursor_mode="single", x_mode="time", mini=True,
    )
    rows = projection.blocks[0].visible_rows
    assert [(row.label, row.value) for row in rows] == [("●", "4.25 rpm")]
    assert "Speed 1=4.25 rpm" in projection.tooltip
    assert "●" in projection.html
    assert "Speed 1" not in projection.html
    assert "Value" not in projection.html
    assert projection.html.count("<tr>") == 1
    assert not ({"Min", "Max", "Avg", "Δ"} & {row.label for row in rows})


def test_time_x_single_missing_current_value_never_falls_back_to_statistics():
    channel = replace(_time_rows()[0], current_value=None)
    projection = build_cursor_presentation(
        (channel,), CursorDisplayOptions(),
        cursor_mode="single", x_mode="time", mini=False,
    )
    assert [(row.label, row.value) for row in projection.blocks[0].visible_rows] == [
        ("Speed 1", "—"),
    ]
    assert "Δ=" not in projection.tooltip
    assert "Min=" not in projection.tooltip
    assert "Max=" not in projection.tooltip
    assert "Avg=" not in projection.tooltip


@pytest.mark.parametrize("cursor_mode", ("single", "dual"))
@pytest.mark.parametrize("x_mode", ("time", "custom"))
@pytest.mark.parametrize(
    "options",
    (
        CursorDisplayOptions(),
        CursorDisplayOptions(False, False, False, False, False),
    ),
)
def test_mini_html_differs_from_full_for_every_mode_pair(cursor_mode, x_mode, options):
    factory = _time_rows if x_mode == "time" else _custom_rows
    channels = factory(2)
    full = build_cursor_presentation(
        channels, options, cursor_mode=cursor_mode, x_mode=x_mode, mini=False,
    )
    mini = build_cursor_presentation(
        channels, options, cursor_mode=cursor_mode, x_mode=x_mode, mini=True,
    )
    assert full.blocks and mini.blocks
    assert full.html != mini.html


def test_single_full_emits_one_table_row_per_channel_without_value_label():
    for x_mode, factory in (("time", _time_rows), ("custom", _custom_rows)):
        projection = build_cursor_presentation(
            factory(3), CursorDisplayOptions(),
            cursor_mode="single", x_mode=x_mode, mini=False,
        )
        assert projection.html.count("<tr>") == 3
        assert "Value" not in projection.html


def test_dual_time_mini_emits_one_table_row_per_channel():
    projection = build_cursor_presentation(
        _time_rows(3), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=True,
    )
    assert projection.html.count("<tr>") == 3
    assert "●" in projection.html
    assert "△" in projection.html
    assert "Min" not in projection.html
    assert "Max" not in projection.html
    assert "Avg" not in projection.html
    for block in projection.blocks:
        assert len(block.visible_rows) == 1
        assert "Δ=" in projection.tooltip


def test_dual_custom_mini_keeps_identity_and_branches_on_one_row():
    projection = build_cursor_presentation(
        _custom_rows(2), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="custom", mini=True,
    )
    assert projection.html.count("<tr>") == 2
    assert "●" in projection.html
    assert "X↑" in projection.html and "X↓" in projection.html
    assert "Δ" in projection.html
    assert "Min" not in projection.html
    assert "Max" not in projection.html
    assert "Avg" not in projection.html


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
    settings.setValue(
        "charts/time_cursor/display_options_v1",
        '{"show_max_point":true,"show_min_point":false,'
        '"show_max_value":true,"show_min_value":true,"show_avg_value":false}',
    )
    loaded = store.load()
    assert loaded.show_delta_value is True
    assert loaded == CursorDisplayOptions(True, False, True, True, False)


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
    # Two sources so D1 keeps the qualified prefix on the visible face.
    # This width still forces constrained rendering for the full identity, but
    # leaves enough measured text space to prove both retained identity ends.
    parent.resize(440, 210)
    pill = CursorPill(parent)
    qtbot.addWidget(pill)
    source = "source_begin_" + "x" * 70 + "_source_end"
    other = "other_begin_" + "z" * 70 + "_other_end"
    channel = "channel_begin_" + "y" * 70 + "_channel_end"
    full_identity = f"{source} / {channel}"
    projection = build_cursor_presentation((
        CursorDisplayChannel(
            identity=(source, channel), source_label=source, channel_label=channel,
            color="#1769e0", unit_suffix=" V", delta=1.0,
            min_value=0.0, max_value=2.0, avg_value=1.0,
        ),
        CursorDisplayChannel(
            identity=(other, channel), source_label=other, channel_label=channel,
            color="#ef4444", unit_suffix=" V", delta=1.5,
            min_value=0.0, max_value=3.0, avg_value=1.5,
        ),
    ), CursorDisplayOptions(), cursor_mode="dual", x_mode="time", mini=False)
    pill.set_display_projection(projection)
    parent.show()
    pill.show()
    qapp.processEvents()
    visible = pill.detail_text()
    assert pill.layout_category() == "constrained"
    assert projection.omit_visible_source_prefix is False
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


def test_single_source_projection_omits_visible_prefix_but_keeps_tooltip(qapp):
    channel = _time_rows(1)[0]
    for mini in (False, True):
        projection = build_cursor_presentation(
            (channel,), CursorDisplayOptions(),
            cursor_mode="single", x_mode="time", mini=mini,
        )
        assert projection.omit_visible_source_prefix is True
        assert "run_0 / " in projection.tooltip
        assert "run_0 / " not in projection.html
        assert "Speed 1" in projection.html or "●" in projection.html


def test_cursor_display_popover_uses_native_popup_shell_chrome(qapp, qtbot):
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    assert popover.windowFlags() & Qt.Popup
    assert popover.windowFlags() & Qt.FramelessWindowHint
    assert popover.windowFlags() & Qt.NoDropShadowWindowHint
    assert popover.testAttribute(Qt.WA_TranslucentBackground)


def test_cursor_display_popover_paints_opaque_background(qapp, qtbot):
    from PyQt5.QtGui import QColor, QImage, QPainter

    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    popover.resize(280, 260)
    popover.show()
    qapp.processEvents()

    image = QImage(popover.size(), QImage.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    popover.render(painter)
    painter.end()

    sample = image.pixelColor(image.width() // 2, 8)
    grid = QColor("#e5eaf2")
    assert sample.alpha() >= 245
    assert not (
        abs(sample.red() - grid.red()) < 12
        and abs(sample.green() - grid.green()) < 12
        and abs(sample.blue() - grid.blue()) < 12
    )
    assert sample.red() >= 240 and sample.green() >= 240 and sample.blue() >= 240


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
    host = getattr(card, "_toolbar_host", None)
    if host is not None:
        host.ensure_widget_visible(button)
        qapp.processEvents()
        mapped = button.mapTo(host.viewport(), button.rect().center())
        assert host.viewport().rect().contains(mapped)
    card.set_cursor_mode("single")
    qtbot.mouseClick(button, Qt.LeftButton)
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


def test_cursor_display_settings_icon_is_list_checks_not_chart_options_tune(
    qapp, qtbot,
):
    import qtawesome as qta
    from mf4_analyzer.ui.chart_stack import ChartStack
    from mf4_analyzer.ui.chart_stack._helpers import _ICON_COLOR

    stack = ChartStack()
    qtbot.addWidget(stack)
    stack.show()
    qapp.processEvents()
    card = stack._time_card
    button = card.cursor_display_settings_button()
    size = button.iconSize()
    actual = button.icon().pixmap(size).toImage()
    expected = qta.icon(
        "mdi.format-list-checks", color=_ICON_COLOR,
    ).pixmap(size).toImage()
    chart_options = qta.icon(
        "mdi.tune-vertical", color=_ICON_COLOR,
    ).pixmap(size).toImage()
    assert actual == expected
    assert actual != chart_options
    assert card._options_btn.icon().pixmap(size).toImage() == chart_options


def test_tooltip_uses_branch_role_for_full_path_label():
    channel = CursorDisplayChannel(
        identity=("source-a", "Rack Force"),
        source_label="source-a",
        channel_label="Rack Force",
        unit_suffix=" N",
        branches=(
            CursorDisplayBranch(
                "全程", min_value=1.0, max_value=5.0, avg_value=3.0,
            ),
        ),
    )
    projection = build_cursor_presentation(
        (channel,), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="custom", mini=False,
    )
    lines = projection.tooltip.splitlines()
    assert "全程" in lines
    assert "全程=" not in projection.tooltip
    assert "Min=1 N" in projection.tooltip


def test_custom_x_dual_full_puts_each_branch_on_its_own_table_row():
    projection = build_cursor_presentation(
        _custom_rows(), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="custom", mini=False,
    )
    html = projection.html
    assert html.count("<tr>") == 3
    rows = re.findall(r"<tr>.*?</tr>", html, flags=re.DOTALL)
    up_rows = [row for row in rows if "X↑" in row]
    down_rows = [row for row in rows if "X↓" in row]
    assert len(up_rows) == 1 and len(down_rows) == 1
    assert up_rows[0] != down_rows[0]
    assert "X↓" not in up_rows[0]
    assert "X↑" not in down_rows[0]


def test_custom_x_dual_full_single_branch_still_one_branch_row():
    channel = replace(_custom_rows()[0], branches=(_custom_rows()[0].branches[0],))
    projection = build_cursor_presentation(
        (channel,), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="custom", mini=False,
    )
    html = projection.html
    assert html.count("<tr>") == 2
    rows = re.findall(r"<tr>.*?</tr>", html, flags=re.DOTALL)
    branch_rows = [row for row in rows if "X↑" in row]
    assert len(branch_rows) == 1
    assert "X↓" not in html


def test_time_x_dual_full_value_order_is_min_max_avg_delta():
    projection = build_cursor_presentation(
        _time_rows(), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="time", mini=False,
    )
    labels = [row.label for row in projection.blocks[0].visible_rows]
    assert labels == ["Min", "Max", "Avg", "Δ"]


def test_delta_switch_hides_delta_column_on_time_and_custom_x():
    options = replace(CursorDisplayOptions(), show_delta_value=False)
    time_proj = build_cursor_presentation(
        _time_rows(), options, cursor_mode="dual", x_mode="time", mini=False,
    )
    custom_proj = build_cursor_presentation(
        _custom_rows(), options, cursor_mode="dual", x_mode="custom", mini=False,
    )
    time_labels = [row.label for row in time_proj.blocks[0].visible_rows]
    custom_labels = [row.label for row in custom_proj.blocks[0].visible_rows]
    assert time_labels == ["Min", "Max", "Avg"]
    assert "Δ" not in time_labels
    assert "Δ" not in custom_labels
    assert "Δ=" not in time_proj.tooltip
    assert "Δ=" not in custom_proj.tooltip


def test_all_six_off_keeps_identity_and_never_blanks_the_panel():
    options = CursorDisplayOptions(False, False, False, False, False, False)
    time_proj = build_cursor_presentation(
        _time_rows(), options, cursor_mode="dual", x_mode="time", mini=False,
    )
    custom_proj = build_cursor_presentation(
        _custom_rows(), options, cursor_mode="dual", x_mode="custom", mini=False,
    )
    assert time_proj.blocks and time_proj.html.strip()
    assert custom_proj.blocks and custom_proj.html.strip()
    assert "Speed 1" in time_proj.html
    assert "X↑" in custom_proj.html and "X↓" in custom_proj.html
    assert "Δ" not in [row.label for row in time_proj.blocks[0].visible_rows]


def test_custom_x_mini_defaults_to_delta_then_falls_back_to_avg():
    default = build_cursor_presentation(
        _custom_rows(), CursorDisplayOptions(),
        cursor_mode="dual", x_mode="custom", mini=True,
    )
    labels = [row.label for row in default.blocks[0].visible_rows]
    assert labels.count("Δ") == 2
    assert "Avg" not in labels
    assert "X↑" in labels
    assert "1.5 N" in default.html
    assert "Avg=" in default.tooltip
    assert "Min=" in default.tooltip
    assert "Max=" in default.tooltip

    without_delta = build_cursor_presentation(
        _custom_rows(), replace(CursorDisplayOptions(), show_delta_value=False),
        cursor_mode="dual", x_mode="custom", mini=True,
    )
    fallback = [row.label for row in without_delta.blocks[0].visible_rows]
    assert fallback.count("Avg") == 2
    assert "Δ" not in fallback
    assert "Δ=" not in without_delta.tooltip
    assert "Avg=" in without_delta.tooltip
    assert "Min=" in without_delta.tooltip


def test_popover_places_delta_checkbox_after_avg_in_stats_group(qapp, qtbot):
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    names = [name for name, _label in popover._LABELS]
    assert names[-2:] == ["show_avg_value", "show_delta_value"]
    assert popover.checkbox("show_delta_value").text() == "显示差值"
    assert names.index("show_max_value") == 2


def test_popover_refit_drops_forced_min_height_when_note_hidden(qapp, qtbot):
    popover = CursorDisplayPopover()
    qtbot.addWidget(popover)
    popover.set_cursor_mode("single")
    popover.show()
    qapp.processEvents()
    qtbot.wait(30)
    tall = popover.height()
    popover.set_cursor_mode("dual")
    qapp.processEvents()
    qtbot.wait(30)
    assert popover.height() <= tall
    hint = popover.sizeHint().expandedTo(popover.minimumSizeHint())
    assert popover.height() == hint.height()
    assert popover.height() == max(hint.height(), 0)
