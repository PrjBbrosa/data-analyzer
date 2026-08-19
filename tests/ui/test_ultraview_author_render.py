"""Deterministic QImage contracts for UltraView author-object rendering."""
from __future__ import annotations

from PyQt5.QtGui import QColor, QImage, QPainter

from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import board_point_to_pixels
from mf4_analyzer.ui.chart_stack.ultraview.author_render import draw_author_objects
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import GridMetrics
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    BoardPoint,
    ConnectorEndpoint,
    ConnectorObject,
    ShapeObject,
    StickyObject,
    StrokeObject,
    TextObject,
)


def _metrics() -> GridMetrics:
    return GridMetrics(
        board_width=640,
        board_height=420,
        column_width=120,
        row_height=88,
        gutter=16,
        padding=20,
        resolution=2,
    )


def _render(objects, *, origin=(-3.0, -2.0), theme="light") -> tuple[QImage, GridMetrics]:
    image = QImage(720, 480, QImage.Format_ARGB32)
    image.fill(QColor(255, 255, 255, 0))
    painter = QPainter(image)
    try:
        draw_author_objects(
            painter,
            objects,
            _metrics(),
            origin_offset=origin,
            theme=theme,
        )
    finally:
        painter.end()
    return image, _metrics()


def test_render_preserves_author_z_order_and_signed_origin_mapping(qapp):
    sticky = StickyObject(
        "sticky", "sticky", box=BoardBox(-2.0, 1.0, 3.0, 2.0), palette="yellow"
    )
    shape = ShapeObject(
        "shape", "shape", box=BoardBox(-1.5, 1.25, 2.0, 1.5),
        shape="rectangle", fill_palette="green", stroke_palette="green",
    )
    image, metrics = _render((sticky, shape))

    mapped = board_point_to_pixels((-1.0, 1.75), metrics, origin_offset=(-3.0, -2.0))
    assert mapped is not None
    color = image.pixelColor(round(mapped[0]), round(mapped[1]))
    # The later green rectangle is above the earlier yellow Sticky.  Its pixel
    # position additionally proves that a negative board coordinate was rebased
    # through the supplied signed origin rather than clamped to zero.
    assert color.green() > color.red()
    assert color.alpha() == 255


def test_highlighter_retains_contract_alpha_in_transparent_qimage(qapp):
    stroke = StrokeObject(
        "highlight", "stroke",
        points=(BoardPoint(0.0, 0.0), BoardPoint(4.0, 0.0)),
        tool="highlighter", palette="blue", width_px_100=8,
    )
    image, metrics = _render((stroke,), origin=(-1.0, -1.0))
    midpoint = board_point_to_pixels((2.0, 0.0), metrics, origin_offset=(-1.0, -1.0))
    assert midpoint is not None
    color = image.pixelColor(round(midpoint[0]), round(midpoint[1]))
    assert color.blue() > color.red()
    assert 75 <= color.alpha() <= 95


def test_cjk_text_and_all_author_primitives_leave_deterministic_ink(qapp):
    objects = (
        TextObject(
            "text", "text", box=BoardBox(-2.5, -1.5, 3.5, 1.5), text="中文标注 ABC",
            font_size=18, text_palette="ink", fill_palette="gray",
        ),
        ShapeObject(
            "diamond", "shape", box=BoardBox(1.0, -1.0, 2.0, 1.5), shape="rhombus",
            fill_palette="cyan", text="形状", stroke_palette="blue",
        ),
        ConnectorObject(
            "elbow", "connector",
            start=ConnectorEndpoint(BoardPoint(-1.0, 2.0)),
            end=ConnectorEndpoint(BoardPoint(3.0, 4.0)),
            route="elbow", elbow_bias=0.5, start_head="arrow", end_head="arrow",
            stroke_palette="red", stroke_width=3,
        ),
    )
    image, _metrics_value = _render(objects)

    dark_ink = 0
    red_ink = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() and max(color.red(), color.green(), color.blue()) < 100:
                dark_ink += 1
            if color.alpha() and color.red() > color.green() + 35 and color.red() > color.blue() + 35:
                red_ink += 1
    assert dark_ink > 20  # CJK text / shape label is actually painted.
    assert red_ink > 20   # Elbow route plus both arrowheads are actually painted.


def test_unknown_or_empty_objects_do_not_break_a_valid_painter(qapp):
    image, _metrics_value = _render((object(),))
    assert image.isNull() is False
    assert image.pixelColor(0, 0).alpha() == 0
