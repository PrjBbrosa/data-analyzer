# Channel Tree Drag-Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a left-button drag across channel rows from accidentally creating a multi-row selection while retaining intentional single and modifier-click selection.

**Architecture:** Keep the channel tree in `ExtendedSelection` mode so Qt continues to provide its established plain-click, `Ctrl+click`, and `Shift+click` semantics. Extend `_CheckTolerantTree` only at the mouse-move boundary: consume an in-progress left-button row drag before `QTreeWidget` can enter drag-selection state. The existing checkbox press/release interception remains unchanged.

**Tech Stack:** Python 3, PyQt5 `QTreeWidget`, pytest, pytest-qt.

## Global Constraints

- Do not change checkbox membership, batch-checkbox confirmation, context-menu, expansion, or keyboard-navigation behavior.
- A left-button drag across tree rows must not alter the blue selection, even with `Ctrl` or `Shift` held.
- Preserve `ExtendedSelection`; modifier behavior is supplied by Qt on click, not reimplemented.
- Dragging scrollbars is out of scope and must remain native.
- Use `QT_QPA_FONTDIR=C:\Windows\Fonts` for focused PyQt visual/widget tests on this Windows checkout.

---

### Task 1: Suppress channel-row drag selection

**Files:**
- Modify: `tests/ui/test_channel_widget.py`
- Modify: `mf4_analyzer/ui/widgets/__init__.py:350-385`
- Modify: `mf4_analyzer/ui/quickref.py:177-188`

**Interfaces:**
- Consumes: `_CheckTolerantTree.mousePressEvent`, `mouseReleaseEvent`, and the existing `QAbstractItemView.ExtendedSelection` mode.
- Produces: `_CheckTolerantTree.mouseMoveEvent(event)`, which consumes mouse-move events while `event.buttons()` contains `Qt.LeftButton`.

- [x] **Step 1: Write the failing regression test**

Add a `QMouseEvent(QEvent.MouseMove, ...)` helper that sends a move event with
`button=Qt.NoButton` and `buttons=Qt.LeftButton` to the channel tree viewport.
Create `test_channel_tree_left_drag_does_not_extend_selection`: expand a real
three-channel fixture, start a left-button press at the first leaf row, send a
left-button move to the third leaf row, release, and assert that only the
first leaf remains selected. The test catches the regression where
`QTreeWidget.mouseMoveEvent` enters Qt's range/drag-selection state.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```powershell
$env:QT_QPA_FONTDIR='C:\Windows\Fonts'
.\.venv\Scripts\python.exe -m pytest tests\ui\test_channel_widget.py::test_channel_tree_left_drag_does_not_extend_selection -q
```

Expected: the assertion reports more than the first channel row in
`tree.selectedItems()`.

- [x] **Step 3: Implement the minimal event guard**

Add `_CheckTolerantTree.mouseMoveEvent`. If an event has `Qt.LeftButton` in
`event.buttons()`, accept it and return without calling the superclass;
otherwise call `super().mouseMoveEvent(event)`. Do not alter the existing
press, release, or double-click handlers.

```python
def mouseMoveEvent(self, event):
    if event.buttons() & Qt.LeftButton:
        event.accept()
        return
    super().mouseMoveEvent(event)
```

- [x] **Step 4: Update the channel-tree quick reference**

Change the "合并为共轴比幅值" row to describe `Ctrl+单击` as non-adjacent
selection and `Shift+单击` as range selection, while retaining the
"多选右键" gesture.

- [x] **Step 5: Run focused verification and verify GREEN**

Run:

```powershell
$env:QT_QPA_FONTDIR='C:\Windows\Fonts'
.\.venv\Scripts\python.exe -m pytest -q tests\ui\test_channel_widget.py tests\ui\test_file_navigator.py tests\ui\test_quickref.py tests\ui\test_quickref_panel.py
git diff --check
```

Expected: all selected tests pass and `git diff --check` produces no output.

- [x] **Step 6: Commit the implementation**

```powershell
git add -- mf4_analyzer/ui/widgets/__init__.py mf4_analyzer/ui/quickref.py tests/ui/test_channel_widget.py docs/superpowers/plans/2026-07-29-channel-tree-drag-selection.md docs/lessons-learned/INDEX.md docs/lessons-learned/codex-channel-tree-drag-selection-guard.md
git commit -m "fix(ui): prevent channel tree drag selection"
```
