"""Preset hover cards stay inside the work area and summarize overflow (S09)."""
from __future__ import annotations

import pytest
from PyQt5.QtCore import Qt

from mf4_analyzer.ui.inspector_sections.presets import _PresetHoverCard
from mf4_analyzer.ui_kit.dialog_geometry import (
    FrameInsets,
    IntRect,
    SCREEN_MARGIN,
    apply_plan,
    as_rect,
    plan_geometry,
)


def test_hover_card_caps_to_compact_budget_and_reports_omitted_chips(qapp, qtbot):
    card = _PresetHoverCard()
    qtbot.addWidget(card)
    params = {f"param_{index:02d}": ("值" * 8) + str(index) for index in range(40)}
    card.set_summary(
        name="方向盘扭矩预设",
        params=params,
        kind="frf",
        label_map={},
    )
    available = IntRect(0, 0, 640, 360)
    card._fit_to_budget(available)
    anchor = IntRect(200, 80, 48, 28)
    plan = plan_geometry(
        available,
        (card.width(), card.height()),
        frame=FrameInsets(),
        margin=SCREEN_MARGIN,
        anchor=anchor,
        position="above",
        gap=10,
    )
    apply_plan(card, plan)
    card.show()
    qtbot.waitExposed(card)
    qapp.processEvents()
    frame = as_rect(card.frameGeometry())
    safe = available.adjusted(
        SCREEN_MARGIN, SCREEN_MARGIN, -SCREEN_MARGIN, -SCREEN_MARGIN,
    )
    assert safe.contains_rect(frame)
    assert card._overflow is not None
    assert card._overflow.isVisible()
    assert "另有" in card._overflow.text()


@pytest.mark.parametrize("edge", ["left", "right"])
@pytest.mark.parametrize("slot", [1, 2, 3, 4])
def test_full_time_frequency_preset_avoids_trigger_when_neither_vertical_side_fits(
    qapp, qtbot, monkeypatch, edge, slot,
):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual, presets
    from mf4_analyzer.ui_kit import load_stylesheet

    old_sheet = qapp.styleSheet()
    load_stylesheet(qapp)
    context = FFTTimeContextual()
    qtbot.addWidget(context)
    bar = context.preset_bar
    qtbot.addWidget(bar._hover_card)
    if slot == 4:
        bar._write(slot, "自定义", context._collect_preset())
    context.resize(288, 720)
    context.show()
    qapp.processEvents()
    button = bar._load_btns[slot]
    center = button.mapToGlobal(button.rect().center())
    available = IntRect(center.x() - (100 if edge == "left" else 1200),
                        center.y() - 300, 1366, 600)
    monkeypatch.setattr(presets, "resolve_available_rect", lambda **_: available)
    try:
        bar._show_hover(slot)
        card = bar._hover_card
        assert card.height() > 300  # Actual full summary, not the old tiny probe.
        row = bar.rect().translated(bar.mapToGlobal(bar.rect().topLeft()))
        assert not card.frameGeometry().intersects(row)
        assert available.adjusted(8, 8, -8, -8).contains_rect(as_rect(card.frameGeometry()))
    finally:
        bar._hide_hover()
        qapp.setStyleSheet(old_sheet)


def test_preset_summary_cannot_steal_mouse_input_if_screen_is_too_small(qtbot):
    card = _PresetHoverCard()
    qtbot.addWidget(card)
    assert card.windowFlags() & Qt.WindowTransparentForInput
    assert card.testAttribute(Qt.WA_TransparentForMouseEvents)
