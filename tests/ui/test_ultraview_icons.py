"""Programmatic icons used by UltraView's floating narrow rail."""
from __future__ import annotations

import pytest

from mf4_analyzer.ui_kit.icons import Icons


@pytest.mark.parametrize(
    "factory_name",
    (
        "ultraview_library",
        "ultraview_layout",
        "ultraview_free_grid",
        "ultraview_filter",
        "ultraview_unplaced",
        "ultraview_display",
        "ultraview_presentation",
        "ultraview_overview",
        "ultraview_fit",
        "ultraview_fit_to_image",
        "ultraview_reset_zoom",
        "ultraview_zoom_out",
        "ultraview_zoom_in",
        "ultraview_help",
        "ultraview_add",
        "ultraview_open_source",
        "ultraview_remove_from_board",
        "ultraview_sync",
        "ultraview_move_to_tray",
        "ultraview_pin",
    ),
)
def test_ultraview_narrow_rail_icons_render_as_real_qicons(qapp, factory_name):
    """The icon-only chrome must not silently fall back to a text glyph."""
    icon = getattr(Icons, factory_name)()
    pixmap = icon.pixmap(20, 20)

    assert not icon.isNull(), factory_name
    assert not pixmap.isNull(), factory_name
    image = pixmap.toImage()
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    ), factory_name
