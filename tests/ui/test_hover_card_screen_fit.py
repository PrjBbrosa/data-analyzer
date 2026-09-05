"""Preset hover cards stay inside the work area and summarize overflow (S09)."""
from __future__ import annotations

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
