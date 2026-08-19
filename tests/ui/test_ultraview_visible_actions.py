"""Visible UltraView actions must have a Page/coordinator consumer."""
from __future__ import annotations

from PyQt5.QtWidgets import QToolButton

from mf4_analyzer.ui.chart_stack.ultraview.chrome import AUTHOR_TOOLS
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.ultraview_state import default_board


def test_visible_creation_controls_all_have_page_consumers(qapp, qtbot):
    page = UltraViewPage()
    qtbot.addWidget(page)
    page.resize(1280, 760)
    page.show()
    page.set_board(default_board())
    qapp.processEvents()

    rail = page.tool_rail()
    assert rail.receivers(rail.panel_requested) > 0
    assert rail.receivers(rail.free_grid_toggled) > 0
    assert rail.receivers(rail.sync_all_requested) > 0

    visible_enabled = [
        button
        for button in rail.findChildren(QToolButton)
        if button.isVisible() and button.isEnabled()
    ]
    assert visible_enabled, "release rail should still expose wired panel actions"

    for button in visible_enabled:
        tool = str(button.property("authorTool") or "")
        if tool:
            assert rail.receivers(rail.tool_requested) > 0, (
                f"{tool} is visible+enabled but Page has no tool_requested consumer"
            )
            assert rail.receivers(rail.tool_pinned_changed) > 0, (
                f"{tool} is visible+enabled but Page has no pin consumer"
            )
            continue
        if button is rail.free_grid_button() or button is rail.sync_all_button():
            continue
        assert button.property("panel"), (
            f"visible enabled rail button {button.objectName()} has no known consumer"
        )

    for tool in AUTHOR_TOOLS:
        button = rail.tool_button(tool)
        if button is None or not button.isVisible() or not button.isEnabled():
            continue
        assert rail.receivers(rail.tool_requested) > 0, (
            f"{tool} is visible+enabled but Page has no tool_requested consumer"
        )
