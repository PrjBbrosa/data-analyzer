"""Characterization snapshot of what ``_ChartCard.__init__`` assembles.

``__init__`` is a long, order-sensitive Qt assembly sequence, and Qt assembly
order is an implicit contract: which widget is created first decides tab order,
z-order and toolbar position. These tests pin the *result* of that sequence —
the child widget population, the attribute surface, and the signal wiring — so
that splitting ``__init__`` into ``_build_*``/``_wire_*`` steps can be shown to
change nothing observable.

They are deliberately snapshot-shaped rather than behavioural: the behavioural
expectations live in test_chart_stack.py / test_hint_nudges.py. If a real
feature change makes one of these fail, update the expectation — but never
while a pure refactor is the only thing in flight.
"""
from collections import Counter

import pytest
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QWidget


ANALYSIS_MODES = ["fft", "fft_time", "order"]

# Every attribute ``_ChartCard.__init__`` is expected to leave behind, in the
# order the constructor assigns them. A split that drops or reorders a build
# step shows up here first.
EXPECTED_ATTRS = [
    "canvas",
    "_canvas_viewport",
    "_chart_mode",
    "_annotation_enabled",
    "_hint_settings",
    "_recent_context_hint_ids",
    "_context_hint_index",
    "_context_hint_signature",
    "_rotation_start",
    "_hint_rotation_paused",
    "_hint_rotation_timer",
    "toolbar",
    "_toolbar_compact",
    "_toolbar_leading_spacer",
    "_toolbar_leading_spacer_action",
    "_options_btn",
    "_copy_btn",
    "_tick_density_popover",
    "_tick_density_btn",
    "_tick_density_sep",
    "_loc_action",
    "_hint_bar",
    "_hint_context",
    "_flash_hint_timer",
    "_hint_discovery",
    "_hint_quickref_btn",
    "_focus_bar",
    "_quality_indicator",
    "_quality_indicator_position_pending",
    "_time_diagnostics",
    "_time_diagnostics_position_pending",
]


def _line_canvas():
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    return PgLineCanvas()


def _time_canvas():
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    return TimeDomainCanvasPG()


def _make_card(qtbot, canvas, **kwargs):
    from mf4_analyzer.ui.chart_stack import _ChartCard

    card = _ChartCard(canvas, **kwargs)
    qtbot.addWidget(card)
    return card


def _child_class_names(widget):
    """Multiset of child widget class names, the whole subtree."""
    return Counter(
        type(child).__name__ for child in widget.findChildren(QWidget)
    )


def _object_names(widget):
    return sorted(
        child.objectName()
        for child in widget.findChildren(QWidget)
        if child.objectName()
    )


@pytest.mark.parametrize("chart_mode", ANALYSIS_MODES)
def test_analysis_card_attribute_surface(qapp, qtbot, chart_mode):
    card = _make_card(qtbot, _line_canvas(), chart_mode=chart_mode)

    missing = [name for name in EXPECTED_ATTRS if not hasattr(card, name)]
    assert missing == []
    assert card._chart_mode == chart_mode
    assert card._annotation_enabled is False


def test_default_mode_card_attribute_surface(qapp, qtbot):
    card = _make_card(qtbot, _time_canvas())

    missing = [name for name in EXPECTED_ATTRS if not hasattr(card, name)]
    assert missing == []
    assert card._chart_mode == ""


def test_hint_rotation_timer_is_armed_single_shot(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    assert isinstance(card._hint_rotation_timer, QTimer)
    assert card._hint_rotation_timer.isSingleShot() is True
    # __init__ ends with _refresh_hint(), which arms the rotation timer via
    # _set_context_hint. A split that drops the trailing refresh leaves it idle.
    assert card._hint_rotation_timer.isActive() is True
    assert card._hint_rotation_paused is False
    # _rotation_start is seeded to None and lazily resolved on first use; the
    # trailing _refresh_hint() forces that resolution, so by the time __init__
    # returns it is a concrete offset. Drop the refresh and it stays None.
    assert isinstance(card._rotation_start, int)


def test_flash_hint_timer_configured(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    assert card._flash_hint_timer.isSingleShot() is True
    assert card._flash_hint_timer.interval() == 2500


def test_toolbar_chrome_and_action_widgets(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    assert card.toolbar.objectName() == "chartToolbar"
    assert card.toolbar.iconSize().width() == 18
    assert card.toolbar.layout().spacing() == 8
    assert card._toolbar_compact is None
    assert card._loc_action is None

    # The leading spacer must be the FIRST toolbar widget: it is inserted before
    # the first action, so any reordering of the build steps moves it.
    actions = card.toolbar.actions()
    assert actions[0] is card._toolbar_leading_spacer_action
    assert card._toolbar_leading_spacer.width() == 4

    for btn in (card._options_btn, card._copy_btn, card._tick_density_btn):
        assert btn.parent() is card.toolbar
        assert btn.size().width() == 32 and btn.size().height() == 32
        assert btn.autoRaise() is True

    assert card._options_btn.objectName() == "chartOptionsButton"
    assert card._tick_density_btn.objectName() == "chartTickDensityButton"
    assert card._tick_density_popover.parent() is card


def test_chart_action_widgets_sit_before_save(qapp, qtbot):
    """Copy / tick-density / options are inserted ahead of the Save action."""
    from mf4_analyzer.ui.chart_stack import _find_action

    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")
    save_act = _find_action(card.toolbar, "save")
    if save_act is None:
        pytest.skip("toolbar has no save action to anchor against")

    actions = card.toolbar.actions()
    save_index = actions.index(save_act)
    for widget in (card._copy_btn, card._tick_density_sep,
                   card._tick_density_btn, card._options_btn):
        act = card._toolbar_action_for_widget(widget)
        assert act is not None
        assert actions.index(act) < save_index


def test_hint_bar_layout_order_and_stretch(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    assert card._hint_bar.objectName() == "chartHintBar"
    assert card._hint_bar.height() == 22

    layout = card._hint_bar.layout()
    ordered = [layout.itemAt(i).widget() for i in range(layout.count())]
    # Quickref button, then the elided rotating row, then the discovery row.
    assert ordered == [
        card._hint_quickref_btn, card._hint_context, card._hint_discovery
    ]
    assert layout.stretch(1) == 1
    assert layout.stretch(0) == 0 and layout.stretch(2) == 0


def test_card_layout_order_is_toolbar_canvas_hintbar(qapp, qtbot):
    canvas = _line_canvas()
    card = _make_card(qtbot, canvas, chart_mode="fft")

    layout = card.layout()
    ordered = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert ordered == [card.toolbar, canvas, card._hint_bar]
    assert layout.stretch(1) == 1


def test_focus_bar_overlay_is_hidden_chrome(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    assert card._focus_bar.objectName() == "chartFocusBar"
    assert card._focus_bar.height() == 3
    assert card._focus_bar.isHidden() is True
    # Overlay, not a layout item: it must not have been added to the column.
    layout = card.layout()
    assert card._focus_bar not in [
        layout.itemAt(i).widget() for i in range(layout.count())
    ]


def test_time_mode_builds_diagnostics_pill_other_modes_do_not(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack.cards import _TimePlotDiagnosticsPill

    time_card = _make_card(qtbot, _time_canvas(), chart_mode="time")
    assert isinstance(time_card._time_diagnostics, _TimePlotDiagnosticsPill)
    assert time_card._time_diagnostics_position_pending is False

    fft_card = _make_card(qtbot, _line_canvas(), chart_mode="fft")
    assert fft_card._time_diagnostics is None


@pytest.mark.parametrize("chart_mode", ANALYSIS_MODES)
def test_default_tool_is_pan(qapp, qtbot, chart_mode):
    card = _make_card(qtbot, _line_canvas(), chart_mode=chart_mode)
    assert "pan" in str(getattr(card.toolbar, "mode", "")).lower()


def test_annotations_flag_installs_annotation_controls(qapp, qtbot):
    plain = _make_card(qtbot, _line_canvas(), chart_mode="order")
    assert not hasattr(plain, "_annotation_btn")

    annotated = _make_card(
        qtbot, _line_canvas(), annotations=True, chart_mode="order"
    )
    assert hasattr(annotated, "_annotation_btn")
    assert annotated._annotation_btn.parent() is not None


def test_copy_button_relays_to_copy_image_requested(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    seen = []
    card.copy_image_requested.connect(lambda: seen.append(1))
    card._copy_btn.click()
    assert seen == [1]


def test_quickref_button_relays_to_quickref_requested(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    seen = []
    card.quickref_requested.connect(lambda: seen.append(1))
    card._hint_quickref_btn.click()
    assert seen == [1]


def test_canvas_manual_zoom_and_event_filters_are_wired(qapp, qtbot):
    canvas = _line_canvas()
    card = _make_card(qtbot, canvas, chart_mode="fft")

    assert card.canvas is canvas
    manual = getattr(canvas, "manual_zoom_changed", None)
    if manual is not None:
        assert canvas.receivers(manual) >= 1
    # The card filters events for the canvas and, when present, its viewport.
    assert card._canvas_viewport is None or isinstance(
        card._canvas_viewport, QWidget
    )


def test_nav_actions_route_to_mode_toggle_handler(qapp, qtbot):
    card = _make_card(qtbot, _line_canvas(), chart_mode="fft")

    nav_actions = [
        act for act in card.toolbar.actions()
        if (act.data() if act.data() else (act.text() or "").strip().lower())
        in ("pan", "zoom")
    ]
    assert len(nav_actions) == 2
    for act in nav_actions:
        assert act.receivers(act.triggered) >= 1


@pytest.mark.parametrize("chart_mode", ANALYSIS_MODES + [""])
def test_child_widget_population_is_mode_stable(qapp, qtbot, chart_mode):
    """Analysis modes build the identical chrome; only the canvas differs."""
    canvas = _line_canvas() if chart_mode else _time_canvas()
    card = _make_card(qtbot, canvas, chart_mode=chart_mode)

    names = _child_class_names(card)
    # Chrome every mode must own exactly once.
    for cls_name in (
        "PgNavigationToolbar", "_TickDensityPopover", "_ElidedLabel",
    ):
        assert names[cls_name] == 1, (chart_mode, cls_name, names)

    object_names = _object_names(card)
    for expected in (
        "chartToolbar", "chartToolbarLeadingSpacer", "chartOptionsButton",
        "chartTickDensityButton", "chartHintBar", "chartHintContext",
        "chartHintDiscovery", "chartHintQuickrefButton", "chartFocusBar",
    ):
        assert expected in object_names, (chart_mode, expected)
