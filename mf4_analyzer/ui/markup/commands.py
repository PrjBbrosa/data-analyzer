from __future__ import annotations

from PyQt5.QtCore import QPointF, QRect
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsScene, QUndoCommand


class _AddItemCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, item: QGraphicsItem):
        super().__init__("添加标注")
        self._scene = scene
        self._item = item

    def redo(self):
        if self._item.scene() is None:
            self._scene.addItem(self._item)

    def undo(self):
        if self._item.scene() is self._scene:
            self._scene.removeItem(self._item)


class _CropCommand(QUndoCommand):
    def __init__(self, editor: "MarkupEditor", crop_rect: QRect):
        super().__init__("裁剪")
        from PyQt5.QtGui import QPixmap
        self._editor = editor
        self._before_pixmap = QPixmap(editor._current_pixmap)
        self._before_positions = editor._item_positions()
        self._after_pixmap = editor._current_pixmap.copy(crop_rect)
        offset = crop_rect.topLeft()
        self._after_positions = {
            item: QPointF(pos.x() - offset.x(), pos.y() - offset.y())
            for item, pos in self._before_positions.items()
        }

    def redo(self):
        self._editor._apply_crop_state(self._after_pixmap, self._after_positions)

    def undo(self):
        self._editor._apply_crop_state(self._before_pixmap, self._before_positions)


class _MoveCommand(QUndoCommand):
    def __init__(self, moves):
        super().__init__("移动标注")
        self._moves = [(item, QPointF(old), QPointF(new)) for item, old, new in moves]

    def redo(self):
        for item, _old, new in self._moves:
            item.setPos(new)

    def undo(self):
        for item, old, _new in self._moves:
            item.setPos(old)


class _DeleteCommand(QUndoCommand):
    def __init__(self, scene: QGraphicsScene, items):
        super().__init__("删除标注")
        self._scene = scene
        self._items = list(items)

    def redo(self):
        for item in self._items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)

    def undo(self):
        for item in self._items:
            if item.scene() is None:
                self._scene.addItem(item)


class _GeometryCommand(QUndoCommand):
    def __init__(self, editor: "MarkupEditor", item, before, after):
        super().__init__("调整标注")
        self._editor = editor
        self._item = item
        self._before = before
        self._after = after

    def redo(self):
        self._editor._restore_geometry(self._item, self._after)

    def undo(self):
        self._editor._restore_geometry(self._item, self._before)


class _StyleCommand(QUndoCommand):
    def __init__(self, editor: "MarkupEditor", entries):
        super().__init__("修改样式")
        self._editor = editor
        self._entries = entries

    def redo(self):
        for item, _before, after in self._entries:
            self._editor._apply_style_to(item, after[0], after[1])

    def undo(self):
        for item, before, _after in self._entries:
            self._editor._apply_style_to(item, before[0], before[1])
