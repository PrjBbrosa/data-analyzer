# 标注编辑器二次修改打磨 + 工具栏重做 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让标注元素在任意工具下都能选中并二次修改（选中/移动/改尺寸/改样式/删除/粘贴全部可撤销），并把顶栏的颜色×6 + 线宽×4 收进二级「样式」菜单。

**Architecture:** 全部改动集中在 `mf4_analyzer/ui/markup/editor.py` 单文件；交互层 `_MarkupGraphicsView` 负责命中/光标/手势提交，`MarkupEditor` 持有 `QUndoStack` 与所有 `QUndoCommand`。不动复制发布管道、缩略图、出口 2。

**Tech Stack:** PyQt5 `QGraphicsScene`/`QGraphicsView`、`QUndoStack`/`QUndoCommand`、`QPainterPathStroker`、`QMenu`+`QWidgetAction`，pytest-qt 离屏测试。

**前置阅读：** 设计 `docs/superpowers/specs/2026-05-31-markup-reedit-and-toolbar-design.md`；工具栏方案 `docs/analyzer/ui-prototypes/2026-05-31-markup-toolbar-options.html`（默认落地方案 A）。

**测试命令（统一）：**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

---

## Files

- Modify: `mf4_analyzer/ui/markup/editor.py`（唯一改动源）
- Modify: `tests/ui/test_markup_editor.py`（新增本计划全部测试）

新增 import（加到 `editor.py` 顶部对应 from 块）：
- `from PyQt5.QtGui import ... QPainterPathStroker`（加进现有 `PyQt5.QtGui` 导入清单）
- `from PyQt5.QtWidgets import ... QMenu, QWidgetAction`（加进现有 `PyQt5.QtWidgets` 导入清单）

模块级常量（加在 `import qtawesome as qta` 之后）：

```python
_HIT_TOLERANCE = 12.0          # arrow/line 命中加粗（场景单位）
_HIT_SCREEN_PX = 8.0           # markup_item_at 邻域命中的屏幕容差
```

---

### Task 1: 任意工具下都能点中细线 / 箭头（修命中区 + 箭头 shape bug）

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`_ArrowAnnotationItem.shape` `:95-101`、`markup_item_at` `:815-822`）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试**

加到 `tests/ui/test_markup_editor.py` 末尾（文件已 `from PyQt5.QtCore import QPointF, QRectF`）：

```python
def test_arrow_shape_has_clickable_width(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    arrow = editor.add_arrow_item(QRectF(10, 10, 80, 0))  # 水平箭头 y=10
    # 距中心线 2px 的点应落在加粗后的 shape 内
    assert arrow.shape().contains(QPointF(40, 12))


def test_markup_item_at_uses_fuzzy_tolerance_for_thin_line(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    line = editor.add_line_item(QRectF(20, 20, 60, 0))  # 水平线 y=20
    editor.set_zoom(1.0)
    assert editor.markup_item_at(QPointF(40, 24)) is line  # 4px 偏移仍命中


def test_near_click_selects_line_under_draw_tool_without_drawing(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    line = editor.add_line_item(QRectF(20, 20, 60, 0))
    editor.set_zoom(1.0)
    editor.set_tool("arrow")
    before = len(_markup_items(editor))
    editor.show()
    pos = editor._view.mapFromScene(QPointF(40, 23))
    qtbot.mouseClick(editor._view.viewport(), Qt.LeftButton, pos=pos)
    QApplication.processEvents()
    assert line.isSelected()
    assert len(_markup_items(editor)) == before  # 没有误画新线
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "arrow_shape or fuzzy or near_click"
```

预期：`test_arrow_shape_has_clickable_width` 失败（零宽 shape 不含点）、`test_markup_item_at_uses_fuzzy` 失败（精确命中拿不到）、`near_click` 失败（点空 → 画了新线）。

- [ ] **Step 3: 实现**

(a) `editor.py` 顶部 `from PyQt5.QtGui import (...)` 块内加入 `QPainterPathStroker`。

(b) 重写 `_ArrowAnnotationItem.shape`（替换 `:95-101`）：

```python
    def shape(self):
        path = QPainterPath()
        path.moveTo(self.start)
        path.lineTo(self.end)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self._pen.widthF(), _HIT_TOLERANCE))
        shape = stroker.createStroke(path)
        shape.addPolygon(self._arrow_head())
        return shape
```

(c) 重写 `markup_item_at`（替换 `:815-822`），加私有 `_first_markup`：

```python
    def markup_item_at(self, point: QPointF):
        item = self._first_markup(self._scene.items(point))
        if item is not None:
            return item
        tol = _HIT_SCREEN_PX / max(self._zoom, 0.1)
        region = QRectF(point.x() - tol, point.y() - tol, tol * 2, tol * 2)
        return self._first_markup(
            self._scene.items(region, Qt.IntersectsItemShape, Qt.DescendingOrder)
        )

    def _first_markup(self, items):
        for item in items:
            if item is self._background_item or item.data(0) == "editor_handle":
                continue
            if item.data(0) == "crop_overlay":
                continue
            return item
        return None
```

- [ ] **Step 4: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：新增 3 个测试通过，旧测试全绿。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "fix(markup): fuzzy hit area + stroked arrow shape so thin items are clickable in any tool"
```

---

### Task 2: 任意工具显示手柄 + 画笔/序号选中反馈 + 开始绘制清旧选

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`refresh_handles` `:884-892`、`_add_handles_for_item` `:912-936`、`handle_at` `:857-861`、`mousePressEvent` 绘制分支 `:206-209`）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试**

```python
def test_handles_shown_under_any_tool_not_only_select(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(20, 20, 40, 30))
    rect.setSelected(True)
    editor.set_tool("pen")
    editor.refresh_handles()
    assert editor._handles  # 画笔工具下选中也有手柄


def test_pen_and_number_show_selection_outline(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    from PyQt5.QtGui import QPainterPath
    path = QPainterPath(QPointF(10, 10))
    path.lineTo(40, 40)
    pen_item = editor.add_path_item(path)
    pen_item.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    assert any(getattr(h, "_role", "") == "" for h in editor._handles)


def test_starting_new_shape_clears_prior_selection(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(5, 5, 18, 12))
    rect.setSelected(True)
    editor.set_tool("rect")
    _drag_scene(qtbot, editor, (60, 55), (95, 72))  # 空白处拉新矩形
    assert not rect.isSelected()
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "any_tool or outline or clears_prior"
```

预期：`any_tool` 失败（select 外不画手柄）、`outline` 失败（path 无手柄）、`clears_prior` 失败（旧选未清）。

- [ ] **Step 3: 实现 — refresh_handles 去掉 select 早退**

替换 `refresh_handles`（`:884-892`）：

```python
    def refresh_handles(self):
        self._clear_handles()
        if self._tool == "crop" and self._crop_item is not None:
            self._add_crop_handles()
            return
        for item in self.selected_markup_items():
            self._add_handles_for_item(item)
```

- [ ] **Step 4: 实现 — 画笔/序号选中轮廓 + handle_at 跳过无 role 标记**

在 `_add_handles_for_item`（`:912-936`）末尾追加分支：

```python
        elif isinstance(item, (QGraphicsPathItem, QGraphicsItemGroup)):
            self._add_selection_outline(item)
```

新增方法（放在 `_add_handles_for_item` 之后）：

```python
    def _add_selection_outline(self, item):
        rect = item.mapToScene(item.boundingRect()).boundingRect()
        marker = QGraphicsRectItem(rect)
        marker.setData(0, "editor_handle")
        marker._role = ""
        marker._target = None
        marker.setZValue(70)
        marker.setPen(QPen(QColor("#1769e0"), 1, Qt.DashLine))
        marker.setBrush(QBrush(Qt.NoBrush))
        marker.setAcceptedMouseButtons(Qt.NoButton)
        marker.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._scene.addItem(marker)
        self._handles.append(marker)
```

替换 `handle_at`（`:857-861`）让它忽略无 role 的轮廓标记：

```python
    def handle_at(self, point: QPointF):
        for handle in self._handles:
            if not getattr(handle, "_role", ""):
                continue
            if handle.sceneBoundingRect().adjusted(-2, -2, 2, 2).contains(point):
                return handle
        return None
```

- [ ] **Step 5: 实现 — 开始绘制时清旧选**

在 `_MarkupGraphicsView.mousePressEvent` 进入绘制分支前（`:206` 的 `self._start = point` 之前）插入一行：

```python
        self._editor.clear_selection()
        self._start = point
        self._dragging_tool = tool
        self._preview = self._create_preview(tool, point)
        event.accept()
```

- [ ] **Step 6: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：新增 3 测试通过；`test_selected_text_has_resize_handle_that_scales_text`、`test_select_tool_drags_existing_item`、`test_existing_item_can_be_dragged_even_when_draw_tool_is_active` 仍绿。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): show handles under any tool, outline pen/number selection, clear selection when drawing new shape"
```

---

### Task 3: 二次修改全部可撤销（删除/移动/改尺寸/改样式/粘贴）

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（新增命令类；改 `delete_selected_annotations` `:789-793`、`move_selection_by` `:784-787`、`set_color`/`set_stroke_width` `:699-709`、`paste_annotations` `:800-813`、`_apply_style` `:750-766`；改 `_MarkupGraphicsView.__init__`/`mousePressEvent`/`mouseReleaseEvent` 手柄与移动分支）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试**

```python
def test_delete_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    editor.delete_selected_annotations()
    assert len(_markup_items(editor)) == 0
    editor._undo_stack.undo()
    assert len(_markup_items(editor)) == 1


def test_move_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    editor.move_selection_by(7, 3)
    assert rect.pos() == QPointF(7, 3)
    editor._undo_stack.undo()
    assert rect.pos() == QPointF(0, 0)


def test_resize_handle_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    before = QRectF(rect.rect())
    handle = next(h for h in editor._handles if getattr(h, "_role", "") == "br")
    editor._view._resize_handle = handle
    editor._view._resize_before = editor._geometry_snapshot(rect)
    editor.drag_handle(handle, rect.mapToScene(QPointF(80, 70)))
    after = QRectF(rect.rect())
    assert after != before
    editor._view._commit_resize()
    editor._undo_stack.undo()
    assert QRectF(rect.rect()) == before


def test_style_change_is_undoable(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_color(QColor("#2563eb"))
    editor.set_stroke_width(4)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    editor.set_color(QColor("#059669"))
    assert rect.pen().color().name() == "#059669"
    editor._undo_stack.undo()
    assert rect.pen().color().name() == "#2563eb"


def test_paste_is_single_undo(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    editor.copy_selected_annotations()
    editor.paste_annotations()
    assert len(_markup_items(editor)) == 2
    editor._undo_stack.undo()
    assert len(_markup_items(editor)) == 1
```

`tests/ui/test_markup_editor.py` 顶部已 `from PyQt5.QtGui import QColor` —— 确认 `QColor` 已在 import 列。

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "undoable or single_undo"
```

预期：全部失败（删除/移动/改样式不进栈，`_geometry_snapshot`/`_commit_resize` 不存在）。

- [ ] **Step 3: 实现 — 新增命令类**

在 `_CropCommand`（`:79`）之后插入：

```python
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
    def __init__(self, scene, items):
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
    def __init__(self, editor, item, before, after):
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
    def __init__(self, editor, entries):
        super().__init__("修改样式")
        self._editor = editor
        self._entries = entries  # [(item, (color, width) before, (color, width) after)]

    def redo(self):
        for item, _before, after in self._entries:
            self._editor._apply_style_to(item, after[0], after[1])

    def undo(self):
        for item, before, _after in self._entries:
            self._editor._apply_style_to(item, before[0], before[1])
```

- [ ] **Step 4: 实现 — 快照 / 还原 / 样式辅助方法**

在 `MarkupEditor` 内 `_apply_style`（`:750`）附近新增/替换：

```python
    def _apply_style(self, item):
        self._apply_style_to(item, self._color, self._stroke_width)

    def _apply_style_to(self, item, color, width):
        pen = QPen(QColor(color), int(width))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        if isinstance(item, _ArrowAnnotationItem):
            item.set_pen(pen, QColor(color))
        elif isinstance(item, (QGraphicsRectItem, QGraphicsLineItem, QGraphicsPathItem)):
            item.setPen(pen)
        elif isinstance(item, QGraphicsTextItem):
            item.setDefaultTextColor(QColor(color))
        elif isinstance(item, QGraphicsItemGroup):
            for child in item.childItems():
                if isinstance(child, QGraphicsEllipseItem):
                    child.setPen(pen)
                    child.setBrush(QBrush(QColor(color)))

    def _item_style(self, item):
        if isinstance(item, QGraphicsTextItem):
            return (QColor(item.defaultTextColor()), self._stroke_width)
        pen = self._item_pen(item)
        if pen is not None:
            return (QColor(pen.color()), pen.width())
        return (QColor(self._color), self._stroke_width)

    def _geometry_snapshot(self, item):
        if isinstance(item, QGraphicsRectItem):
            return ("rect", QRectF(item.rect()), QPointF(item.pos()))
        if isinstance(item, _ArrowAnnotationItem):
            return ("arrow", QPointF(item.start), QPointF(item.end), QPointF(item.pos()))
        if isinstance(item, QGraphicsLineItem):
            return ("line", QLineF(item.line()), QPointF(item.pos()))
        return ("scale", float(item.scale()), QPointF(item.pos()))

    def _restore_geometry(self, item, snap):
        kind = snap[0]
        if kind == "rect":
            item.setRect(snap[1])
            item.setPos(snap[2])
        elif kind == "arrow":
            item.prepareGeometryChange()
            item.start = QPointF(snap[1])
            item.end = QPointF(snap[2])
            item.setPos(snap[3])
            item.update()
        elif kind == "line":
            item.setLine(snap[1])
            item.setPos(snap[2])
        else:
            item.setScale(snap[1])
            item.setPos(snap[2])
        self.refresh_handles()
```

- [ ] **Step 5: 实现 — 删除/移动/样式/粘贴走命令**

替换 `delete_selected_annotations`（`:789-793`）：

```python
    def delete_selected_annotations(self):
        items = [
            item for item in self.selected_markup_items()
            if item.scene() is self._scene
        ]
        if items:
            self._undo_stack.push(_DeleteCommand(self._scene, items))
        self.refresh_handles()
```

替换 `move_selection_by`（`:784-787`）：

```python
    def move_selection_by(self, dx: float, dy: float):
        moves = [
            (item, QPointF(item.pos()), QPointF(item.pos().x() + dx, item.pos().y() + dy))
            for item in self.selected_markup_items()
        ]
        if moves:
            self._undo_stack.push(_MoveCommand(moves))
        self.refresh_handles()
```

替换 `set_color`/`set_stroke_width`（`:699-709`）：

```python
    def set_color(self, color: QColor) -> None:
        entries = []
        for item in self.selected_markup_items():
            before = self._item_style(item)
            entries.append((item, before, (QColor(color), before[1])))
        self._color = QColor(color)
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self.refresh_handles()

    def set_stroke_width(self, width: int) -> None:
        entries = []
        for item in self.selected_markup_items():
            before = self._item_style(item)
            entries.append((item, before, (before[0], int(width))))
        self._stroke_width = int(width)
        if entries:
            self._undo_stack.push(_StyleCommand(self, entries))
        self._refresh_style_button_icon()
        self.refresh_handles()
```

> `_refresh_style_button_icon` 在 Task 6 实现；本任务先加一个空安全版（Task 6 会替换其实现）。在 `MarkupEditor` 内新增：
> ```python
>     def _refresh_style_button_icon(self):
>         pass
> ```

替换 `paste_annotations`（`:800-813`）外层包宏：

```python
    def paste_annotations(self):
        if not self._annotation_clipboard:
            return
        self.clear_selection()
        pasted = []
        self._undo_stack.beginMacro("粘贴标注")
        for payload in self._annotation_clipboard:
            item = self._deserialize_item(payload)
            if item is None:
                continue
            item.moveBy(12, 12)
            item.setSelected(True)
            pasted.append(item)
        self._undo_stack.endMacro()
        self.refresh_handles()
        return pasted
```

- [ ] **Step 6: 实现 — 手柄缩放 / 拖动移动 在手势结束时落命令**

`_MarkupGraphicsView.__init__`（`:154-167`）新增字段：

```python
        self._resize_handle = None
        self._resize_before = None
```

（`_resize_handle` 已存在，补 `_resize_before = None`。）

`mousePressEvent` 命中手柄分支（`:176-180`）改为记录快照：

```python
        handle = self._editor.handle_at(point)
        if handle is not None:
            self._resize_handle = handle
            target = getattr(handle, "_target", None)
            self._resize_before = (
                self._editor._geometry_snapshot(target) if target is not None else None
            )
            event.accept()
            return
```

`mouseReleaseEvent` 手柄分支（`:251-255`）改为提交命令，并抽出 `_commit_resize`（供测试直调）：

```python
        if self._resize_handle is not None:
            self._commit_resize()
            event.accept()
            return
```

新增方法（放在 `_MarkupGraphicsView` 内）：

```python
    def _commit_resize(self):
        target = getattr(self._resize_handle, "_target", None) if self._resize_handle else None
        if target is not None and self._resize_before is not None:
            after = self._editor._geometry_snapshot(target)
            if after != self._resize_before:
                self._editor._undo_stack.push(
                    _GeometryCommand(self._editor, target, self._resize_before, after)
                )
        self._resize_handle = None
        self._resize_before = None
        self._editor.refresh_handles()
```

`mouseReleaseEvent` 移动分支（`:256-261`）改为提交移动命令：

```python
        if self._move_start is not None:
            moves = [
                (item, old, QPointF(item.pos()))
                for item, old in self._move_positions.items()
                if QPointF(item.pos()) != old
            ]
            if moves:
                self._editor._undo_stack.push(_MoveCommand(moves))
            self._move_start = None
            self._move_positions = {}
            self._editor.refresh_handles()
            event.accept()
            return
```

- [ ] **Step 7: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：5 个新 undo 测试通过；`test_style_controls_apply_to_new_and_selected_items`、`test_delete_arrow_keys_and_copy_paste_operate_on_selection`、`test_apply_crop_rect_is_undoable` 仍绿。

- [ ] **Step 8: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): make move/resize/delete/style/paste undoable via QUndoCommand"
```

---

### Task 4: hover / resize 光标反馈

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`MarkupEditor` 新增 `_cursor_for` 与 `_HANDLE_CURSORS`；`_MarkupGraphicsView.mouseMoveEvent` 非拖拽分支 `:239-241`）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试**

```python
def test_cursor_reflects_handle_item_and_empty(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_zoom(1.0)
    rect = editor.add_rect_item(QRectF(20, 20, 40, 30))
    rect.setSelected(True)
    editor.set_tool("select")
    editor.refresh_handles()
    corner = next(h for h in editor._handles if getattr(h, "_role", "") == "br")
    assert editor._cursor_for(corner.pos()) == Qt.SizeFDiagCursor
    assert editor._cursor_for(QPointF(40, 35)) == Qt.SizeAllCursor      # 矩形体内 → 移动
    assert editor._cursor_for(QPointF(5, 5)) == Qt.ArrowCursor          # 空白 + 选择工具
    editor.set_tool("rect")
    assert editor._cursor_for(QPointF(5, 5)) == Qt.CrossCursor          # 空白 + 绘图工具
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "cursor"
```

预期：`_cursor_for` 不存在 → AttributeError。

- [ ] **Step 3: 实现**

在 `MarkupEditor` 类体内（紧跟 `TOOLS = (...)` `:372` 之后）加类属性：

```python
    _HANDLE_CURSORS = {
        "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
        "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
        "top": Qt.SizeVerCursor, "bottom": Qt.SizeVerCursor,
        "left": Qt.SizeHorCursor, "right": Qt.SizeHorCursor,
    }
```

新增方法（放在 `handle_at` 附近）：

```python
    def _cursor_for(self, point: QPointF):
        handle = self.handle_at(point)
        if handle is not None:
            role = getattr(handle, "_role", "")
            if role.startswith("crop_"):
                role = role[5:]
            return self._HANDLE_CURSORS.get(role, Qt.SizeAllCursor)
        if self.markup_item_at(point) is not None:
            return Qt.SizeAllCursor
        return Qt.ArrowCursor if self._tool == "select" else Qt.CrossCursor
```

`_MarkupGraphicsView.mouseMoveEvent` 非拖拽分支（`:239-241`）改为：

```python
        if self._dragging_tool is None:
            self.viewport().setCursor(self._editor._cursor_for(point))
            super().mouseMoveEvent(event)
            return
```

- [ ] **Step 4: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：cursor 测试通过，全量绿。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): hover/resize cursor feedback over items and handles"
```

---

### Task 5: 选择工具下双击文字直接重编辑

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`_MarkupGraphicsView.mouseDoubleClickEvent` `:291-296`）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试**

```python
def test_double_click_text_in_select_tool_reedits(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    text = editor.add_text_item(QPointF(20, 20), "peak")
    text.clearFocus()
    editor.set_tool("select")
    editor.set_zoom(1.0)
    editor.show()
    before = len([i for i in _markup_items(editor) if isinstance(i, QGraphicsTextItem)])
    pos = editor._view.mapFromScene(QPointF(24, 24))
    qtbot.mouseDClick(editor._view.viewport(), Qt.LeftButton, pos=pos)
    QApplication.processEvents()
    after = len([i for i in _markup_items(editor) if isinstance(i, QGraphicsTextItem)])
    assert text.hasFocus()
    assert after == before  # 没有新增文字 item
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "double_click_text"
```

预期：双击未进入编辑（`hasFocus()` 为 False）。

- [ ] **Step 3: 实现**

替换 `mouseDoubleClickEvent`（`:291-296`）：

```python
    def mouseDoubleClickEvent(self, event):
        if self._editor._tool == "crop" and self._editor.active_crop_rect().isValid():
            self._editor.apply_active_crop()
            event.accept()
            return
        point = self._clamp(self.mapToScene(event.pos()))
        existing = self._editor.markup_item_at(point)
        if isinstance(existing, QGraphicsTextItem):
            self._editor.focus_text_item(existing)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
```

- [ ] **Step 4: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：双击测试通过；`test_text_tool_click_existing_text_reopens_it_without_adding_new_item` 仍绿。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): double-click text re-enters editing under any tool"
```

---

### Task 6: 工具栏重做 —— 颜色/线宽收进「样式」二级菜单（方案 A）

> **用户已确认方案 A**（单一样式气泡，见 `2026-05-31-markup-toolbar-options.html`），按此落地。
> `set_color`/`set_stroke_width` 公共契约不变，只换「触发它们的 UI 控件」。

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py`（`_build_toolbar` 颜色循环 `:576-593` 与线宽循环 `:595-605`；`_refresh_style_button_icon` Task 3 占位版 → 真实实现）
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: 写失败测试 + 改一条既有测试**

> 关键：方案 A 的 swatch 在 `QMenu` 弹出前不在 `editor` 子控件树里，**必须从 `QWidgetAction.defaultWidget()` 面板里取**，不要用 `editor.findChild(ren)`。新增一个 helper 取面板：

```python
def _style_panel(editor):
    return editor._style_button.menu().actions()[0].defaultWidget()


def test_color_and_width_collapsed_into_style_menu(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    toolbar = editor.findChild(QWidget, "markupEditorToolbar")
    permanent = [
        b for b in toolbar.findChildren(QToolButton)
        if b.objectName().startswith(("markupColor_", "markupWidth_"))
        and b.parent() is toolbar
    ]
    assert permanent == []                         # 顶栏不再常驻颜色/线宽
    style_btn = editor.findChild(QToolButton, "markupStyleButton")
    assert style_btn is not None
    assert style_btn.menu() is not None            # 颜色/线宽在二级菜单里
    panel = _style_panel(editor)
    assert panel.findChild(QToolButton, "markupColor_059669") is not None


def test_style_menu_still_drives_set_color(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    rect = editor.add_rect_item(QRectF(10, 10, 30, 20))
    rect.setSelected(True)
    swatch = _style_panel(editor).findChild(QToolButton, "markupColor_059669")
    assert swatch is not None
    swatch.click()
    assert rect.pen().color().name() == "#059669"
```

`tests/ui/test_markup_editor.py` 顶部确认已 import `QWidget`（在 `from PyQt5.QtWidgets import (...)` 列加上 `QWidget` 若缺）。

同时**改写既有 `test_style_controls_are_compact_not_placeholder_buttons`（`tests/ui/test_markup_editor.py:219-231`）**，让它从样式面板取 swatch（否则收进菜单后 `editor.findChildren` 取空、`assert style_buttons` 会失败）：

```python
def test_style_controls_are_compact_not_placeholder_buttons(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)

    style_buttons = [
        button for button in _style_panel(editor).findChildren(QToolButton)
        if button.objectName().startswith(("markupColor_", "markupWidth_"))
    ]

    assert style_buttons
    assert all(button.width() <= 34 for button in style_buttons)
    assert all(button.height() <= 34 for button in style_buttons)
    assert all(button.text() == "" for button in style_buttons)
```

- [ ] **Step 2: 跑红**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "collapsed or style_menu"
```

预期：`markupStyleButton` 不存在；颜色按钮仍是顶栏常驻。

- [ ] **Step 3: 实现 — 顶部 import**

`editor.py` 的 `from PyQt5.QtWidgets import (...)` 块加入 `QMenu, QWidgetAction`。

- [ ] **Step 4: 实现 — 用样式按钮替换颜色/线宽两段循环**

删除 `_build_toolbar` 中颜色循环（`:576-593`）与线宽循环（`:595-605`），在原位置替换为：

```python
        self._style_button = QToolButton(toolbar)
        self._style_button.setObjectName("markupStyleButton")
        self._style_button.setToolTip("样式（颜色 / 线宽）")
        self._style_button.setAutoRaise(True)
        self._style_button.setFixedSize(QSize(58, 32))
        self._style_button.setPopupMode(QToolButton.InstantPopup)
        self._style_button.setStyleSheet(self._compact_tool_button_qss())
        style_menu = QMenu(self._style_button)
        style_action = QWidgetAction(style_menu)
        style_action.setDefaultWidget(self._build_style_panel(style_menu))
        style_menu.addAction(style_action)
        self._style_button.setMenu(style_menu)
        layout.addWidget(self._style_button)
        self._refresh_style_button_icon()
```

- [ ] **Step 5: 实现 — 样式面板 + 按钮回显图标**

把 Task 3 的占位 `_refresh_style_button_icon` 替换为真实实现，并新增 `_build_style_panel`、`_style_button_icon`（放在 `_color_icon`/`_width_icon` 附近）：

```python
    def _build_style_panel(self, menu):
        panel = QWidget()
        panel.setObjectName("markupStylePanel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(8)

        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        for name, color in (
            ("红色", "#e53935"), ("橙色", "#f97316"), ("黄色", "#eab308"),
            ("绿色", "#059669"), ("蓝色", "#2563eb"), ("黑色", "#111827"),
        ):
            button = QToolButton(panel)
            button.setObjectName(f"markupColor_{color[1:]}")
            button.setIcon(self._color_icon(QColor(color)))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(name)
            button.setAutoRaise(True)
            button.setFixedSize(QSize(30, 30))
            button.setStyleSheet(self._compact_tool_button_qss())
            button.clicked.connect(
                lambda checked=False, c=color, m=menu: (self.set_color(QColor(c)), m.hide())
            )
            color_row.addWidget(button)
        outer.addLayout(color_row)

        width_row = QHBoxLayout()
        width_row.setSpacing(8)
        for width in (2, 4, 6, 8):
            button = QToolButton(panel)
            button.setObjectName(f"markupWidth_{width}")
            button.setIcon(self._width_icon(width))
            button.setIconSize(QSize(24, 18))
            button.setToolTip(f"{width}px")
            button.setAutoRaise(True)
            button.setFixedSize(QSize(34, 30))
            button.setStyleSheet(self._compact_tool_button_qss())
            button.clicked.connect(
                lambda checked=False, w=width, m=menu: (self.set_stroke_width(w), m.hide())
            )
            width_row.addWidget(button)
        outer.addLayout(width_row)
        return panel

    def _refresh_style_button_icon(self):
        button = getattr(self, "_style_button", None)
        if button is not None:
            button.setIcon(self._style_button_icon(self._color, self._stroke_width))
            button.setIconSize(QSize(44, 18))

    def _style_button_icon(self, color: QColor, width: int):
        pix = QPixmap(44, 18)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#d0d7e2"), 1))
        painter.setBrush(QBrush(QColor(color)))
        painter.drawEllipse(QRectF(2, 4, 11, 11))
        painter.setPen(QPen(QColor("#374151"), max(1, int(width)), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(20, 9), QPointF(40, 9))
        painter.end()
        return QIcon(pix)
```

> `set_color`/`set_stroke_width`（Task 3 已实现）末尾已调用 `self._refresh_style_button_icon()`，此处真实实现接管，键面随选色/选宽实时回显。

- [ ] **Step 6: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：2 个新测试通过；`test_style_controls_are_compact_not_placeholder_buttons`（swatch 仍 ≤34、无文字）、`test_toolbar_uses_icons_and_primary_done_button`（样式键有图标无文字）、`test_toolbar_omits_delete_and_single_copy_buttons` 仍绿。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): collapse color/width into a style popover with live state readout"
```

---

## 全量回归 + 真机验证

- [ ] **Step 1: 全量单测**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

预期：本计划新增测试 + 原有测试全绿。

- [ ] **Step 2: 真机验证（本仓库铁律：只认真机渲染/截图，不认「属性设上了 + 单测过」）**

启动 app → 复制任一图卡 → 点缩略图开编辑器，逐条验：
1. 画线/箭头后**不切工具**，在其附近点一下即可选中并出现手柄；拖端点能改形。
2. 选中元素：`Delete` 删除后 `Ctrl+Z` 还原；拖动后 `Ctrl+Z` 还原位置；拉手柄改尺寸后 `Ctrl+Z` 还原尺寸；改色/改粗细后 `Ctrl+Z` 还原；粘贴后 `Ctrl+Z` 一步退回。
3. 鼠标移到元素显示移动光标、移到手柄显示对应缩放光标、绘图工具空白处显示十字。
4. 选择工具下双击已有文字直接重编辑。
5. 顶栏只剩一个「样式」键（键面显示当前色 + 线宽），点开可改颜色/线宽；图标利落、「完成复制」蓝色主按钮醒目。
6. 回归：画/选/删/裁剪/复制/保存/完成复制照常；颜色粗细对新建和已选元素仍生效。

- [ ] **Step 3: lesson gate**

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```

预期：除非实现中发现可复用的工作流/回归风险，否则无需新增 lesson。

---

## Self-Review（已自检）

- **Spec 覆盖**：现状 1/2/3→Task 1；4/5/6→Task 2；9→Task 3；7→Task 4；8→Task 5；10→Task 6。全部有对应任务。
- **类型一致**：`_geometry_snapshot`/`_restore_geometry` 快照元组结构在 Task 3 内自洽；`_apply_style_to(item, color, width)` 在 `_StyleCommand`、`set_color`、`set_stroke_width`、`_apply_style` 中签名一致；`_refresh_style_button_icon` 在 Task 3 占位、Task 6 落地，调用点不变。
- **占位扫描**：无 TBD/“稍后实现”；每个改动步给了完整代码块与精确行号锚点。
