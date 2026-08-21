"""Programmatic icons used by UltraView's floating narrow rail."""
from __future__ import annotations

import pytest

from mf4_analyzer.ui_kit.icons import Icons

_DRAW_SUBTOOL_FACTORIES = (
    "ultraview_draw_pen",
    "ultraview_draw_highlighter",
    "ultraview_draw_eraser",
    "ultraview_draw_lasso",
)


def _icon_image(icon):
    pixmap = icon.pixmap(20, 20)
    assert not pixmap.isNull()
    image = pixmap.toImage()
    scale = image.width() / 20.0
    return image, scale


def _ink_bbox(image, min_alpha=1):
    min_x, min_y = image.width(), image.height()
    max_x, max_y = -1, -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() >= min_alpha:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    return min_x, min_y, max_x, max_y


def _alpha_mask(image, min_alpha=1):
    return bytes(
        1 if image.pixelColor(x, y).alpha() >= min_alpha else 0
        for y in range(image.height())
        for x in range(image.width())
    )


@pytest.mark.parametrize(
    "factory_name",
    (
        "ultraview_author_select",
        "ultraview_author_laser",
        "ultraview_author_sticky",
        "ultraview_author_text",
        "ultraview_author_shapes",
        "ultraview_author_draw",
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
        "ultraview_draw_pen",
        "ultraview_draw_highlighter",
        "ultraview_draw_eraser",
        "ultraview_draw_lasso",
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


@pytest.mark.parametrize("factory_name", _DRAW_SUBTOOL_FACTORIES)
def test_ultraview_draw_subtool_icons_are_opaque_qicons(qapp, factory_name):
    icon = getattr(Icons, factory_name)()
    image, _scale = _icon_image(icon)
    assert not icon.isNull(), factory_name
    assert any(
        image.pixelColor(x, y).alpha() > 0
        for x in range(image.width())
        for y in range(image.height())
    ), factory_name


@pytest.mark.parametrize("factory_name", _DRAW_SUBTOOL_FACTORIES)
def test_ultraview_draw_subtool_icons_do_not_clip_outer_ring(qapp, factory_name):
    """Outer 2 logical pixels stay empty — the 3px inset must not clip."""
    icon = getattr(Icons, factory_name)()
    image, scale = _icon_image(icon)
    inset = max(1, int(round(2 * scale)))
    leaks = [
        (x, y, image.pixelColor(x, y).alpha())
        for y in range(image.height())
        for x in range(image.width())
        if (
            x < inset
            or y < inset
            or x >= image.width() - inset
            or y >= image.height() - inset
        )
        and image.pixelColor(x, y).alpha() != 0
    ]
    assert leaks == [], factory_name


def test_ultraview_draw_subtool_icons_have_distinct_alpha_masks(qapp):
    masks = []
    for factory_name in _DRAW_SUBTOOL_FACTORIES:
        icon = getattr(Icons, factory_name)()
        image, _scale = _icon_image(icon)
        masks.append(_alpha_mask(image))
    assert len(set(masks)) == 4


@pytest.mark.parametrize("size", (18, 20))
@pytest.mark.parametrize(
    "factory_name",
    (
        "ultraview_author_select",
        "ultraview_author_laser",
        "ultraview_author_sticky",
        "ultraview_author_text",
        "ultraview_author_shapes",
        "ultraview_author_draw",
    ),
)
def test_ultraview_author_icons_share_optical_ink_box(qapp, factory_name, size):
    icon = getattr(Icons, factory_name)()
    pixmap = icon.pixmap(size, size)
    image = pixmap.toImage()
    scale = image.width() / float(size)
    min_x, min_y, max_x, max_y = _ink_bbox(image)
    inset = 2 * scale
    assert min_x >= inset - 1, (factory_name, size, min_x, inset)
    assert min_y >= inset - 1, (factory_name, size, min_y, inset)
    assert max_x < image.width() - inset + 1, (factory_name, size, max_x, inset)
    assert max_y < image.height() - inset + 1, (factory_name, size, max_y, inset)
    width = (max_x - min_x + 1) / scale
    height = (max_y - min_y + 1) / scale
    assert 10 <= width <= 16.5, (factory_name, size, width)
    assert 10 <= height <= 16.5, (factory_name, size, height)


def test_ultraview_draw_subtool_ink_stays_inside_shared_safe_box(qapp):
    """Ink bounding boxes share a 3px logical inset on the 20px canvas."""
    for factory_name in _DRAW_SUBTOOL_FACTORIES:
        icon = getattr(Icons, factory_name)()
        image, scale = _icon_image(icon)
        min_x, min_y, max_x, max_y = _ink_bbox(image)
        inset = 3 * scale
        assert min_x >= inset, (factory_name, min_x, inset)
        assert min_y >= inset, (factory_name, min_y, inset)
        assert max_x < image.width() - inset, (factory_name, max_x, inset)
        assert max_y < image.height() - inset, (factory_name, max_y, inset)
