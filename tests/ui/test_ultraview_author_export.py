"""Author-object bounds and PNG/overview compositor contracts."""
from __future__ import annotations

from PyQt5.QtGui import QColor

from mf4_analyzer.ui.chart_stack.ultraview.author_geometry import board_point_to_pixels
from mf4_analyzer.ui.chart_stack.ultraview.compositor import (
    compose_board,
    free_grid_output_size,
    image_sha256,
)
from mf4_analyzer.ui.chart_stack.ultraview.elastic_workspace import (
    author_content_bounds,
    content_bounds,
)
from mf4_analyzer.ui.chart_stack.ultraview.free_grid import export_grid_metrics
from mf4_analyzer.ui.chart_stack.ultraview.widgets import BoardOverview
from mf4_analyzer.ui.ultraview_state import (
    BoardBox,
    BoardPoint,
    GridBounds,
    ShapeObject,
    StickyObject,
    StrokeObject,
    UnknownAuthorObject,
    default_board,
    set_layout,
)


def _negative_author_objects():
    return (
        StickyObject(
            "note-negative", "sticky", box=BoardBox(-6.0, -3.0, 2.0, 2.0),
            palette="yellow", text="负坐标便签",
        ),
        ShapeObject(
            "shape-top", "shape", box=BoardBox(-5.5, -2.5, 1.0, 1.0),
            shape="rectangle", fill_palette="green", stroke_palette="green",
        ),
        StrokeObject(
            "stroke-far", "stroke",
            points=(BoardPoint(8.0, 7.0), BoardPoint(10.0, 7.0)),
            palette="red", width_px_100=12,
        ),
    )


def test_author_content_bounds_are_signed_conservative_and_skip_unknown():
    objects = _negative_author_objects() + (
        UnknownAuthorObject({"kind": "future-sparkle", "id": "future"}),
    )

    author = author_content_bounds(objects)

    # The Sticky establishes the negative crop origin; the Stroke's one-cell
    # ink margin protects its rounded cap at the positive far edge.
    assert author == GridBounds(-6, -3, 17, 11)
    assert content_bounds((), author_objects=objects) == author


def test_free_grid_author_only_export_crops_signed_content_and_preserves_z_order(qapp):
    board = default_board()
    board.author_objects = list(_negative_author_objects()[:2])
    author = author_content_bounds(board.author_objects)
    metrics = export_grid_metrics(())

    image = compose_board(board, {}, {}, scale=1, title=False)

    # A Board without cards must still export only the signed author union;
    # it must not fall back to the ordinary empty 12-column board floor.
    pitch_x, pitch_y = metrics.exact_pitch()
    padding = metrics.exact_padding()
    assert (image.width(), image.height()) == (
        round(2 * padding + author.column_span * pitch_x),
        round(2 * padding + author.row_span * pitch_y),
    )
    assert (image.width(), image.height()) == free_grid_output_size(board, 1, title=False)

    mapped = board_point_to_pixels(
        (-5.0, -2.0), metrics, origin_offset=(author.column, author.row)
    )
    assert mapped is not None
    color = image.pixelColor(round(mapped[0]), round(mapped[1]))
    # The later green rectangle must paint above the earlier yellow Sticky.
    assert color.green() > color.red()


def test_free_grid_compositor_and_overview_include_author_ink_but_skip_unknown(qapp):
    board = default_board()
    board.author_objects = list(_negative_author_objects()) + [
        UnknownAuthorObject({"kind": "future-sparkle", "id": "future"}),
    ]
    image = compose_board(board, {}, {}, scale=1, title=False)
    assert image.isNull() is False

    # BoardOverview is deliberately a compositor consumer.  Its projection
    # must therefore inherit author ink without a parallel thumbnail renderer.
    overview = BoardOverview()
    overview.set_projection(board, {}, {})
    overview.show()
    qapp.processEvents()
    assert overview._image.isNull() is False
    assert image_sha256(overview._image) == image_sha256(image)
    overview.close()


def test_template_compositor_hides_persisted_author_objects(qapp):
    board = default_board()
    set_layout(board, "split_horizontal")
    baseline = image_sha256(compose_board(board, {}, {}, scale=1, title=False))
    board.author_objects = [
        StickyObject(
            "template-hidden", "sticky", box=BoardBox(0.0, 0.0, 5.0, 4.0),
            palette="red", text="模板模式不得显示",
        )
    ]

    hidden = compose_board(board, {}, {}, scale=1, title=False)

    assert image_sha256(hidden) == baseline
    assert QColor(hidden.pixel(0, 0)).alpha() == 255
