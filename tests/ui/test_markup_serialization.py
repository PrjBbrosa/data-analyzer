"""Round-trip and payload-shape tests for markup annotation serialization.

Spec: docs/analyzer/specs/2026-08-04-chartstack-markup-slimming-design.md (D-D3).

``_serialize_item`` / ``_deserialize_item`` back the markup editor's annotation
clipboard: copy turns each selected QGraphicsItem into a plain tuple, paste
rebuilds it. The tuple shape is the contract between the two halves -- reorder
a field or drop one and copy/paste breaks silently, since nothing validates the
payload on the way back in.

So the payload constants in BACKCOMPAT_PAYLOADS are frozen from the pre-move
implementation on ``main`` @ ``ab19622f`` and must not be "tidied": the layout
tests below assert the exact field order for every one of the six item kinds.

Scope note: these payloads live only in ``_annotation_clipboard`` for the
lifetime of one editor session. Saving an annotated image flattens it to a
pixmap (``save_result``), so there is no on-disk annotation format that this
tuple has to stay compatible with.
"""
import pytest

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainterPath, QPixmap
from PyQt5.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
)

from mf4_analyzer.ui.markup.editor import MarkupEditor
from mf4_analyzer.ui.markup.items import _ArrowAnnotationItem


def _pixmap(width=200, height=160, color="#f7f7f7"):
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(color))
    return pixmap


@pytest.fixture
def editor(qapp, qtbot):
    ed = MarkupEditor(_pixmap())
    qtbot.addWidget(ed)
    return ed


# ---------------------------------------------------------------------------
# Field-order contract -- frozen from the pre-move implementation
# ---------------------------------------------------------------------------

# kind -> the tuple layout the serializer emits and the deserializer unpacks.
PAYLOAD_LAYOUTS = {
    "rect": ("kind", "rect", "pos", "color", "width"),
    "line": ("kind", "line", "pos", "color", "width"),
    "path": ("kind", "path", "pos", "color", "width"),
    "text": ("kind", "text", "pos", "color", "font_px"),
    "arrow": ("kind", "start", "end", "pos", "color", "width"),
    "number": ("kind", "circle_rect", "label_text", "label_pos", "pos",
               "color", "width", "scale", "label_px"),
}


def _make_rect(editor):
    return editor.add_rect_item(QRectF(10, 12, 40, 30))


def _make_line(editor):
    return editor.add_line_item(QRectF(5, 6, 50, 40))


def _make_path(editor):
    path = QPainterPath(QPointF(3, 4))
    path.lineTo(20, 25)
    path.lineTo(40, 10)
    return editor.add_path_item(path)


def _make_arrow(editor):
    return editor.add_arrow_item(QRectF(QPointF(8, 9), QPointF(60, 70)))


def _make_text(editor):
    item = editor.add_text_item(QPointF(15, 18), "Rte_MotorSpeed")
    item.setPlainText("Rte_MotorSpeed")
    editor._finalize_text_item(item)
    return item


def _make_number(editor):
    return editor.add_number_item(QRectF(30, 35, 0, 0))


FACTORIES = {
    "rect": _make_rect,
    "line": _make_line,
    "path": _make_path,
    "arrow": _make_arrow,
    "text": _make_text,
    "number": _make_number,
}


@pytest.mark.parametrize("kind", sorted(PAYLOAD_LAYOUTS))
def test_payload_keeps_its_frozen_field_layout(editor, kind):
    """Length and field order are the copy/paste contract. Changing them is a
    silent break, so they are pinned per kind."""
    payload = editor._serialize_item(FACTORIES[kind](editor))

    assert payload is not None, f"{kind} did not serialize"
    assert payload[0] == kind
    assert len(payload) == len(PAYLOAD_LAYOUTS[kind])


def test_every_supported_item_kind_is_covered():
    """Guard against a new annotation kind landing with no round-trip test."""
    assert set(PAYLOAD_LAYOUTS) == set(FACTORIES)
    assert set(PAYLOAD_LAYOUTS) == {
        "rect", "line", "path", "text", "arrow", "number"}


def test_unknown_item_type_serializes_to_none(editor):
    from PyQt5.QtWidgets import QGraphicsEllipseItem as _Ellipse
    assert editor._serialize_item(_Ellipse(QRectF(0, 0, 5, 5))) is None


def test_none_payload_deserializes_to_none(editor):
    assert editor._deserialize_item(None) is None


def test_unknown_kind_deserializes_to_none(editor):
    assert editor._deserialize_item(("polygon", 1, 2, 3, 4)) is None


# ---------------------------------------------------------------------------
# Round trips -- geometry and style field by field
# ---------------------------------------------------------------------------

def test_rect_round_trip_preserves_geometry_and_style(editor):
    editor.set_color(QColor("#1769e0"))
    editor.set_stroke_width(6)
    original = _make_rect(editor)
    original.setPos(QPointF(7, 9))

    restored = editor._deserialize_item(editor._serialize_item(original))

    assert isinstance(restored, QGraphicsRectItem)
    assert restored.rect() == QRectF(10, 12, 40, 30)
    assert restored.pos() == QPointF(7, 9)
    assert restored.pen().color().name() == "#1769e0"
    assert restored.pen().width() == 6


def test_line_round_trip_preserves_endpoints_and_style(editor):
    editor.set_color(QColor("#22c55e"))
    editor.set_stroke_width(3)
    original = _make_line(editor)
    original.setPos(QPointF(2, 3))
    expected = QLineF(original.line())

    restored = editor._deserialize_item(editor._serialize_item(original))

    assert isinstance(restored, QGraphicsLineItem)
    assert restored.line() == expected
    assert restored.pos() == QPointF(2, 3)
    assert restored.pen().color().name() == "#22c55e"
    assert restored.pen().width() == 3


def test_path_round_trip_preserves_every_element(editor):
    editor.set_color(QColor("#7c3aed"))
    editor.set_stroke_width(2)
    original = _make_path(editor)
    original.setPos(QPointF(1, 1))

    restored = editor._deserialize_item(editor._serialize_item(original))

    assert isinstance(restored, QGraphicsPathItem)
    assert restored.path().elementCount() == original.path().elementCount()
    for i in range(restored.path().elementCount()):
        before = original.path().elementAt(i)
        after = restored.path().elementAt(i)
        assert (after.x, after.y) == (before.x, before.y)
    assert restored.pos() == QPointF(1, 1)
    assert restored.pen().color().name() == "#7c3aed"
    assert restored.pen().width() == 2


def test_arrow_round_trip_preserves_start_and_end(editor):
    editor.set_color(QColor("#ef4444"))
    editor.set_stroke_width(5)
    original = _make_arrow(editor)
    original.setPos(QPointF(4, 5))

    restored = editor._deserialize_item(editor._serialize_item(original))

    assert isinstance(restored, _ArrowAnnotationItem)
    assert restored.start == original.start
    assert restored.end == original.end
    assert restored.pos() == QPointF(4, 5)
    assert restored.pen().color().name() == "#ef4444"
    assert restored.pen().width() == 5


def test_text_round_trip_preserves_content_colour_and_pixel_size(editor):
    editor.set_color(QColor("#0f766e"))
    original = _make_text(editor)
    original.setPos(QPointF(11, 13))
    font = original.font()
    font.setPixelSize(37)
    original.setFont(font)

    restored = editor._deserialize_item(editor._serialize_item(original))

    assert isinstance(restored, QGraphicsTextItem)
    assert restored.toPlainText() == "Rte_MotorSpeed"
    assert restored.pos() == QPointF(11, 13)
    assert restored.defaultTextColor().name() == "#0f766e"
    assert restored.font().pixelSize() == 37


def test_number_round_trip_preserves_badge_circle_label_and_scale(editor):
    editor.set_color(QColor("#f59e0b"))
    editor.set_stroke_width(4)
    original = _make_number(editor)
    original.setScale(1.75)

    payload = editor._serialize_item(original)
    restored = editor._deserialize_item(payload)

    assert isinstance(restored, QGraphicsItemGroup)
    circle = next(c for c in restored.childItems()
                  if isinstance(c, QGraphicsEllipseItem))
    label = next(c for c in restored.childItems()
                 if isinstance(c, QGraphicsSimpleTextItem))
    original_circle = next(c for c in original.childItems()
                           if isinstance(c, QGraphicsEllipseItem))
    original_label = next(c for c in original.childItems()
                          if isinstance(c, QGraphicsSimpleTextItem))

    assert circle.rect() == original_circle.rect()
    assert label.text() == original_label.text()
    assert label.pos() == original_label.pos()
    assert label.font().pixelSize() == original_label.font().pixelSize()
    assert label.font().bold()
    assert label.brush().color().name() == QColor(Qt.white).name()
    assert restored.pos() == original.pos()
    assert restored.scale() == pytest.approx(1.75)
    assert circle.pen().color().name() == "#f59e0b"
    assert circle.pen().width() == 4
    assert circle.brush().color().name() == "#f59e0b"


def test_deserialize_restores_the_editor_active_style(editor):
    """Rebuilding an item borrows the editor's colour/width to drive the item
    factories; the user's current pen must be put back afterwards."""
    editor.set_color(QColor("#111827"))
    editor.set_stroke_width(9)
    payload = ("rect", QRectF(0, 0, 5, 5), QPointF(0, 0), QColor("#ef4444"), 2)

    editor._deserialize_item(payload)

    assert editor._color.name() == "#111827"
    assert editor._stroke_width == 9


# ---------------------------------------------------------------------------
# Backwards compatibility -- payloads captured from the pre-move implementation
# ---------------------------------------------------------------------------

# Captured verbatim on main @ ab19622f by serializing one item of each kind
# (via the FACTORIES above, with the colour/width each round-trip test uses) and
# transcribing the result. Do NOT regenerate these from the current code --
# that would defeat the point. A failure here means the payload contract moved.
BACKCOMPAT_PAYLOADS = {
    "rect": (
        "rect", QRectF(10.0, 12.0, 40.0, 30.0), QPointF(7.0, 9.0),
        QColor("#1769e0"), 6,
    ),
    "line": (
        "line", QLineF(5.0, 6.0, 55.0, 46.0), QPointF(2.0, 3.0),
        QColor("#22c55e"), 3,
    ),
    "text": (
        "text", "Rte_MotorSpeed", QPointF(11.0, 13.0),
        QColor("#0f766e"), 37,
    ),
    "arrow": (
        "arrow", QPointF(8.0, 9.0), QPointF(60.0, 70.0), QPointF(4.0, 5.0),
        QColor("#ef4444"), 5,
    ),
    # circle_rect and label_pos come out of font metrics for the badge glyph,
    # so these two values are whatever the capturing machine's font produced.
    # Feeding them back in is deterministic (they are just applied), which is
    # why they are safe to freeze on the deserialize side -- see
    # test_serializer_still_emits_the_frozen_payloads for the serialize side.
    "number": (
        "number", QRectF(-16.0, -16.0, 32.0, 32.0), "1",
        QPointF(-4.6875, -12.0), QPointF(30.0, 35.0),
        QColor("#f59e0b"), 4, 1.75, 20,
    ),
}


def _serialize_reference_item(editor, kind):
    """Rebuild the exact item each frozen payload was captured from."""
    style = {
        "rect": ("#1769e0", 6),
        "line": ("#22c55e", 3),
        "path": ("#7c3aed", 2),
        "arrow": ("#ef4444", 5),
        "text": ("#0f766e", 4),
        "number": ("#f59e0b", 4),
    }[kind]
    editor.set_color(QColor(style[0]))
    editor.set_stroke_width(style[1])
    item = FACTORIES[kind](editor)
    pos = {
        "rect": QPointF(7, 9), "line": QPointF(2, 3), "path": QPointF(1, 1),
        "arrow": QPointF(4, 5), "text": QPointF(11, 13),
    }.get(kind)
    if pos is not None:
        item.setPos(pos)
    if kind == "text":
        font = item.font()
        font.setPixelSize(37)
        item.setFont(font)
    if kind == "number":
        item.setScale(1.75)
    return item


@pytest.mark.parametrize("kind", ["rect", "line", "text", "arrow"])
def test_serializer_still_emits_the_frozen_payloads(editor, kind):
    """Closes the loop on the frozen constants: without this, the backcompat
    tests below would pass against any self-consistent made-up payload, because
    deserialize only echoes back what it is handed."""
    item = _serialize_reference_item(editor, kind)
    assert editor._serialize_item(item) == BACKCOMPAT_PAYLOADS[kind]


def test_serializer_still_emits_the_frozen_path_payload(editor):
    """QPainterPath has no useful __eq__ for this, so compare element-wise."""
    item = _serialize_reference_item(editor, "path")
    kind, path, pos, color, width = editor._serialize_item(item)

    assert kind == "path"
    assert [(path.elementAt(i).x, path.elementAt(i).y)
            for i in range(path.elementCount())] == [
        (3.0, 4.0), (20.0, 25.0), (40.0, 10.0)]
    assert pos == QPointF(1.0, 1.0)
    assert color == QColor("#7c3aed")
    assert width == 2


def test_serializer_still_emits_the_frozen_number_payload(editor):
    """Badge circle/label geometry is font-metric dependent, so only the
    machine-independent fields are pinned to literals; the two geometry fields
    are asserted to echo the source item faithfully."""
    item = _serialize_reference_item(editor, "number")
    (kind, circle_rect, label_text, label_pos, pos,
     color, width, scale, label_px) = editor._serialize_item(item)

    source_circle = next(c for c in item.childItems()
                         if isinstance(c, QGraphicsEllipseItem))
    source_label = next(c for c in item.childItems()
                        if isinstance(c, QGraphicsSimpleTextItem))

    assert kind == "number"
    assert label_text == "1"
    assert pos == QPointF(30.0, 35.0)
    assert color == QColor("#f59e0b")
    assert width == 4
    assert scale == pytest.approx(1.75)
    assert label_px == 20  # round(_number_radius 16 * 1.25)
    assert circle_rect == source_circle.rect()
    assert label_pos == source_label.pos()


def test_backcompat_rect_payload_still_restores(editor):
    item = editor._deserialize_item(BACKCOMPAT_PAYLOADS["rect"])
    assert isinstance(item, QGraphicsRectItem)
    assert item.rect() == QRectF(10.0, 12.0, 40.0, 30.0)
    assert item.pos() == QPointF(7.0, 9.0)
    assert item.pen().color().name() == "#1769e0"
    assert item.pen().width() == 6


def test_backcompat_line_payload_still_restores(editor):
    item = editor._deserialize_item(BACKCOMPAT_PAYLOADS["line"])
    assert isinstance(item, QGraphicsLineItem)
    assert item.line() == QLineF(5.0, 6.0, 55.0, 46.0)
    assert item.pos() == QPointF(2.0, 3.0)
    assert item.pen().color().name() == "#22c55e"
    assert item.pen().width() == 3


def test_backcompat_path_payload_still_restores(editor):
    path = QPainterPath(QPointF(3, 4))
    path.lineTo(20, 25)
    path.lineTo(40, 10)
    item = editor._deserialize_item(
        ("path", path, QPointF(1.0, 1.0), QColor("#7c3aed"), 2))

    assert isinstance(item, QGraphicsPathItem)
    assert item.path().elementCount() == 3
    assert item.pos() == QPointF(1.0, 1.0)
    assert item.pen().color().name() == "#7c3aed"
    assert item.pen().width() == 2


def test_backcompat_text_payload_still_restores(editor):
    item = editor._deserialize_item(BACKCOMPAT_PAYLOADS["text"])
    assert isinstance(item, QGraphicsTextItem)
    assert item.toPlainText() == "Rte_MotorSpeed"
    assert item.pos() == QPointF(11.0, 13.0)
    assert item.defaultTextColor().name() == "#0f766e"
    assert item.font().pixelSize() == 37


def test_backcompat_arrow_payload_still_restores(editor):
    item = editor._deserialize_item(BACKCOMPAT_PAYLOADS["arrow"])
    assert isinstance(item, _ArrowAnnotationItem)
    assert item.start == QPointF(8.0, 9.0)
    assert item.end == QPointF(60.0, 70.0)
    assert item.pos() == QPointF(4.0, 5.0)
    assert item.pen().color().name() == "#ef4444"
    assert item.pen().width() == 5


def test_backcompat_number_payload_still_restores(editor):
    item = editor._deserialize_item(BACKCOMPAT_PAYLOADS["number"])
    assert isinstance(item, QGraphicsItemGroup)
    circle = next(c for c in item.childItems()
                  if isinstance(c, QGraphicsEllipseItem))
    label = next(c for c in item.childItems()
                 if isinstance(c, QGraphicsSimpleTextItem))

    assert circle.rect() == QRectF(-16.0, -16.0, 32.0, 32.0)
    assert circle.pen().color().name() == "#f59e0b"
    assert circle.pen().width() == 4
    assert label.text() == "1"
    assert label.pos() == QPointF(-4.6875, -12.0)
    assert label.font().pixelSize() == 20
    assert label.font().bold()
    assert item.pos() == QPointF(30.0, 35.0)
    assert item.scale() == pytest.approx(1.75)


# ---------------------------------------------------------------------------
# Clipboard integration -- the only production caller
# ---------------------------------------------------------------------------

def test_copy_then_paste_reproduces_the_annotation_offset_by_twelve(editor):
    editor.set_color(QColor("#1769e0"))
    editor.set_stroke_width(6)
    original = _make_rect(editor)
    original.setPos(QPointF(7, 9))
    original.setSelected(True)

    editor.copy_selected_annotations()
    pasted = editor.paste_annotations()

    assert len(pasted) == 1
    assert isinstance(pasted[0], QGraphicsRectItem)
    assert pasted[0].rect() == QRectF(10, 12, 40, 30)
    assert pasted[0].pos() == QPointF(19, 21)
    assert pasted[0].pen().color().name() == "#1769e0"


def test_copying_an_unsupported_item_leaves_paste_a_no_op(editor):
    editor._annotation_clipboard = [None]
    assert editor.paste_annotations() == []
