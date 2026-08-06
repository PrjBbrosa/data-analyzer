"""Direct unit tests for the markup editor's handle geometry.

Spec: docs/analyzer/specs/2026-08-04-chartstack-markup-slimming-design.md (D-D5).

This maths used to be inlined four times inside MarkupEditor methods that also
map coordinates and mutate scene items, so it could only be exercised by
driving synthetic mouse events at a live editor. These are plain value-type
functions -- no QApplication, no scene, exact numbers.
"""
import pytest

from PyQt5.QtCore import QPointF, QRectF

from mf4_analyzer.ui.markup import handles


RECT = QRectF(10, 20, 100, 60)  # x 10..110, y 20..80


# ---------------------------------------------------------------------------
# Anchor points
# ---------------------------------------------------------------------------

def test_handle_points_covers_four_corners_and_four_edge_midpoints():
    points = handles.handle_points(RECT)

    assert list(points) == list(handles.HANDLE_ROLES)
    assert points["tl"] == QPointF(10, 20)
    assert points["tr"] == QPointF(110, 20)
    assert points["br"] == QPointF(110, 80)
    assert points["bl"] == QPointF(10, 80)
    assert points["top"] == QPointF(60, 20)
    assert points["right"] == QPointF(110, 50)
    assert points["bottom"] == QPointF(60, 80)
    assert points["left"] == QPointF(10, 50)


def test_handle_point_order_is_stable():
    """Creation order decides MarkupEditor._handles order, which is the
    tie-break when two handles overlap under the pointer."""
    assert handles.HANDLE_ROLES == (
        "tl", "top", "tr", "right", "br", "bottom", "bl", "left")


def test_handle_points_of_an_empty_rect_all_collapse_to_one_spot():
    points = handles.handle_points(QRectF(5, 5, 0, 0))
    assert all(p == QPointF(5, 5) for p in points.values())


# ---------------------------------------------------------------------------
# Role prefix
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role,expected", [
    ("crop_tl", "tl"),
    ("crop_bottom", "bottom"),
    ("tl", "tl"),
    ("scale", "scale"),
    ("", ""),
])
def test_bare_role_strips_only_the_crop_prefix(role, expected):
    assert handles.bare_role(role) == expected


# ---------------------------------------------------------------------------
# Resizing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role,point,expected", [
    ("tl", QPointF(20, 30), QRectF(20, 30, 90, 50)),
    ("tr", QPointF(100, 30), QRectF(10, 30, 90, 50)),
    ("br", QPointF(100, 70), QRectF(10, 20, 90, 50)),
    ("bl", QPointF(20, 70), QRectF(20, 20, 90, 50)),
    # Edge handles move one edge only; the other axis is untouched.
    ("top", QPointF(999, 30), QRectF(10, 30, 100, 50)),
    ("bottom", QPointF(999, 70), QRectF(10, 20, 100, 50)),
    ("left", QPointF(20, 999), QRectF(20, 20, 90, 60)),
    ("right", QPointF(100, 999), QRectF(10, 20, 90, 60)),
])
def test_resize_rect_moves_the_named_edge_or_corner(role, point, expected):
    assert handles.resize_rect(RECT, role, point) == expected


def test_resize_rect_accepts_prefixed_crop_roles_identically():
    assert (handles.resize_rect(RECT, "crop_tl", QPointF(20, 30))
            == handles.resize_rect(RECT, "tl", QPointF(20, 30)))


def test_resize_rect_normalizes_when_dragged_past_the_opposite_edge():
    """Dragging the left edge past the right must flip the rect, not produce a
    negative width that later renders inside-out."""
    flipped = handles.resize_rect(RECT, "left", QPointF(200, 0))

    assert flipped.width() > 0
    assert flipped.height() > 0
    assert flipped == QRectF(110, 20, 90, 60)


def test_resize_rect_leaves_an_unknown_role_alone():
    assert handles.resize_rect(RECT, "scale", QPointF(0, 0)) == RECT


def test_resize_rect_does_not_mutate_its_input():
    original = QRectF(RECT)
    handles.resize_rect(RECT, "br", QPointF(0, 0))
    assert RECT == original


# ---------------------------------------------------------------------------
# Scale factors
# ---------------------------------------------------------------------------

def test_centered_scale_tracks_the_axis_the_pointer_is_furthest_along():
    center = QPointF(50, 50)
    # 40 / (80/2) = 1.0 on x, 10 / (20/2) = 1.0 on y -> tie at 1.0
    assert handles.centered_scale_factor(
        center, QPointF(90, 60), 80, 20) == pytest.approx(1.0)
    # Push x out to 80 -> 80/40 = 2.0 wins over y
    assert handles.centered_scale_factor(
        center, QPointF(130, 60), 80, 20) == pytest.approx(2.0)


def test_centered_scale_is_symmetric_about_the_centre():
    center = QPointF(50, 50)
    assert handles.centered_scale_factor(center, QPointF(90, 50), 80, 20) == \
        handles.centered_scale_factor(center, QPointF(10, 50), 80, 20)


def test_corner_scale_measures_from_the_top_left_anchor():
    top_left = QPointF(10, 20)
    # 100 wide: pointer 200 to the right of the anchor -> 2.0
    assert handles.corner_scale_factor(
        top_left, QPointF(210, 20), 100, 50) == pytest.approx(2.0)


def test_corner_scale_takes_the_larger_axis():
    top_left = QPointF(0, 0)
    assert handles.corner_scale_factor(
        top_left, QPointF(150, 300), 100, 100) == pytest.approx(3.0)


def test_corner_scale_ignores_an_axis_with_no_extent():
    top_left = QPointF(0, 0)
    assert handles.corner_scale_factor(
        top_left, QPointF(150, 999), 100, 0) == pytest.approx(1.5)


def test_corner_scale_returns_none_when_the_item_has_no_extent():
    """The caller reads None as 'leave the scale alone' rather than dividing by
    a degenerate size."""
    assert handles.corner_scale_factor(QPointF(0, 0), QPointF(1, 1), 0, 0) is None


@pytest.mark.parametrize("factory,args", [
    (handles.centered_scale_factor, (QPointF(50, 50), QPointF(50, 50), 80, 20)),
    (handles.corner_scale_factor, (QPointF(0, 0), QPointF(-999, -999), 100, 100)),
])
def test_scale_never_drops_below_the_minimum(factory, args):
    """Without a floor a drag onto the anchor shrinks the item to nothing and
    it can no longer be grabbed."""
    assert factory(*args) == pytest.approx(handles.MIN_DRAG_SCALE)
    assert handles.MIN_DRAG_SCALE == 0.25


# ---------------------------------------------------------------------------
# Hit testing
# ---------------------------------------------------------------------------

def test_hit_tolerance_grows_as_the_view_zooms_out():
    assert handles.handle_hit_tolerance(14, 1.0) == pytest.approx(14)
    assert handles.handle_hit_tolerance(14, 2.0) == pytest.approx(7)
    assert handles.handle_hit_tolerance(14, 0.5) == pytest.approx(28)


def test_hit_tolerance_is_clamped_at_extreme_zoom_out():
    """The 0.1 floor stops the grab radius exploding (and, at zoom 0, a
    division by zero)."""
    assert handles.handle_hit_tolerance(14, 0.01) == pytest.approx(140)
    assert handles.handle_hit_tolerance(14, 0.0) == pytest.approx(140)


def test_nearest_within_tolerance_picks_the_closest_centre():
    centers = [QPointF(0, 0), QPointF(10, 0), QPointF(30, 0)]
    assert handles.nearest_within_tolerance(centers, QPointF(9, 0), 5) == 1


def test_nearest_within_tolerance_ignores_centres_outside_the_box():
    centers = [QPointF(0, 0), QPointF(100, 100)]
    assert handles.nearest_within_tolerance(centers, QPointF(99, 99), 5) == 1
    assert handles.nearest_within_tolerance(centers, QPointF(50, 50), 5) is None


def test_nearest_within_tolerance_keeps_the_first_of_two_equal_candidates():
    centers = [QPointF(0, 0), QPointF(0, 0)]
    assert handles.nearest_within_tolerance(centers, QPointF(0, 0), 5) == 0


def test_nearest_within_tolerance_handles_an_empty_scene():
    assert handles.nearest_within_tolerance([], QPointF(0, 0), 5) is None


def test_hit_zone_is_square_not_circular():
    """The tolerance box is a square, so a diagonal corner just inside it still
    counts -- matching what the editor did before the extraction."""
    centers = [QPointF(0, 0)]
    assert handles.nearest_within_tolerance(centers, QPointF(4.9, 4.9), 5) == 0
    assert handles.nearest_within_tolerance(centers, QPointF(5.1, 0), 5) is None
