"""Pure geometry for the markup editor's resize handles.

Spec: docs/analyzer/specs/2026-08-04-chartstack-markup-slimming-design.md (D-D5).

Only the maths lives here -- no QGraphicsItem, no scene, no editor state. The
parts that map between item and scene coordinates, create handle items and push
undo commands stay on ``MarkupEditor``, because they are inseparable from Qt.

What this buys: the eight-role handle table used to be written out four times
(anchor points for item handles, anchor points for crop handles, the role/edge
switch for dragging an item, the same switch for dragging the crop box). Two of
those copies carried a ``crop_`` prefix on the role names, so a change had to be
made in four places in two spellings. Now there is one table and one switch.
"""
from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF

# Corner and edge-midpoint roles, in the order handles are created. The order
# matters: it decides the order of MarkupEditor._handles, which is the
# tie-break when two handles are within hit tolerance of the same point.
HANDLE_ROLES = ("tl", "top", "tr", "right", "br", "bottom", "bl", "left")

CROP_ROLE_PREFIX = "crop_"

# Smallest scale a drag may produce, so an item cannot be shrunk to nothing and
# become unclickable.
MIN_DRAG_SCALE = 0.25


def bare_role(role: str) -> str:
    """Strip the crop prefix so crop and item handles share one role table."""
    return role[len(CROP_ROLE_PREFIX):] if role.startswith(CROP_ROLE_PREFIX) else role


def handle_points(rect: QRectF) -> dict:
    """Return ``{role: anchor point}`` for ``rect``'s corners and edge midpoints."""
    center = rect.center()
    return {
        "tl": rect.topLeft(),
        "top": QPointF(center.x(), rect.top()),
        "tr": rect.topRight(),
        "right": QPointF(rect.right(), center.y()),
        "br": rect.bottomRight(),
        "bottom": QPointF(center.x(), rect.bottom()),
        "bl": rect.bottomLeft(),
        "left": QPointF(rect.left(), center.y()),
    }


def resize_rect(rect: QRectF, role: str, point: QPointF) -> QRectF:
    """Return ``rect`` with the edge or corner named by ``role`` moved to
    ``point``, normalized so dragging an edge past its opposite flips the rect
    rather than producing a negative width.

    ``role`` may carry the crop prefix. An unknown role leaves the rect alone.
    """
    result = QRectF(rect)
    role = bare_role(role)
    if role == "tl":
        result.setTopLeft(point)
    elif role == "top":
        result.setTop(point.y())
    elif role == "tr":
        result.setTopRight(point)
    elif role == "right":
        result.setRight(point.x())
    elif role == "br":
        result.setBottomRight(point)
    elif role == "bottom":
        result.setBottom(point.y())
    elif role == "bl":
        result.setBottomLeft(point)
    elif role == "left":
        result.setLeft(point.x())
    return result.normalized()


def centered_scale_factor(center, point, width: float, height: float) -> float:
    """Scale for an item that grows about its centre (badges).

    The larger of the two half-axis ratios wins, so the drag tracks whichever
    axis the pointer is furthest along.
    """
    half_width = max(width / 2.0, 0.001)
    half_height = max(height / 2.0, 0.001)
    return max(
        abs(point.x() - center.x()) / half_width,
        abs(point.y() - center.y()) / half_height,
        MIN_DRAG_SCALE,
    )


def corner_scale_factor(top_left, point, width: float, height: float):
    """Scale for an item anchored at its top-left (text, pen paths).

    Returns None when the item has no measurable extent in either axis, which
    the caller reads as "leave the scale alone".
    """
    candidates = []
    if width > 0.001:
        candidates.append((point.x() - top_left.x()) / width)
    if height > 0.001:
        candidates.append((point.y() - top_left.y()) / height)
    if not candidates:
        return None
    return max(max(candidates), MIN_DRAG_SCALE)


def handle_hit_tolerance(screen_px: float, zoom: float) -> float:
    """Convert a screen-space grab radius into scene units.

    The zoom floor keeps the tolerance finite when the view is zoomed far out.
    """
    return screen_px / max(zoom, 0.1)


def nearest_within_tolerance(centers, point: QPointF, tol: float):
    """Return the index of the centre nearest ``point`` within a ``tol``-sized
    square around it, or None. Ties keep the earliest index.
    """
    nearest = None
    nearest_distance = None
    for index, center in enumerate(centers):
        hit_rect = QRectF(
            center.x() - tol,
            center.y() - tol,
            tol * 2,
            tol * 2,
        )
        if hit_rect.contains(point):
            distance = (center.x() - point.x()) ** 2 + (center.y() - point.y()) ** 2
            if nearest_distance is None or distance < nearest_distance:
                nearest = index
                nearest_distance = distance
    return nearest
