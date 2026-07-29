# Channel Selection Highlight B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make selected channel rows clearly visible on Windows by applying the approved scheme B background color `#B7D3F2`.

**Architecture:** Keep the generic selected-row fill in the shared QSS rule scoped to `QTreeWidget#channelTree`, and synchronize the custom channel-leaf delegate that owns leaf-row painting. Reuse the delegate's selected-color constant for its branch gutter, protected by a real Qt rendering test that samples the visible row body and gutter.

**Tech Stack:** Qt 5 QSS, PyQt5, pytest

## Global Constraints

- Change only the selected background of the channel tree.
- Use `#B7D3F2` (case-insensitive in the test).
- Preserve dark text, channel swatches, checkboxes, spacing, and all other tree states.

---

### Task 1: Apply And Protect Scheme B

**Files:**
- Modify: `mf4_analyzer/ui/widgets/__init__.py:128,425`
- Modify: `mf4_analyzer/ui_kit/style.qss:1176-1183`
- Test: `tests/ui/test_channel_widget.py`

**Interfaces:**
- Consumes: `_ChannelLeafDelegate.SELECTED_BG`, `_CheckTolerantTree.drawBranches`, and the `QTreeWidget#channelTree` selected QSS selectors.
- Produces: selected channel bodies, branch gutters, and non-leaf selected rows with background `#b7d3f2`.

- [x] **Step 1: Write the failing Qt rendering test**

```python
def test_channel_tree_selected_rows_render_approved_windows_highlight(qapp, qtbot):
    old_sheet = qapp.styleSheet()
    old_style = qapp.style().objectName()
    try:
        qapp.setStyle("Fusion")
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        widget = MultiFileChannelWidget()
        qtbot.addWidget(widget)
        widget.resize(520, 360)
        _add_attached_file(widget, "file-a", _MultiChannelFileData())
        widget.show()
        qtbot.waitExposed(widget)
        item = widget._file_items["file-a"].child(0)
        widget.tree.setCurrentItem(item)
        item.setSelected(True)
        qapp.processEvents()
        row = widget.tree.visualItemRect(item)
        image = widget.tree.viewport().grab().toImage()
        expected = QColor("#b7d3f2")
        body_x = widget.tree.columnViewportPosition(2) + 4
        assert image.pixelColor(body_x, row.center().y()) == expected
        assert image.pixelColor(2, row.center().y()) == expected
    finally:
        qapp.setStyleSheet(old_sheet)
        qapp.setStyle(old_style)
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_channel_widget.py::test_channel_tree_selected_rows_render_approved_windows_highlight --basetemp D:\\tmp\\pytest-channel-highlight-red`

Expected: FAIL because the current selected background is `#e8efff`.

- [x] **Step 3: Apply the approved color to every selected-row painter**

```qss
QTreeWidget#channelTree::item:selected {
    background-color: #b7d3f2;
}
QTreeWidget#channelTree::branch:selected {
    background-color: #b7d3f2;
}
```

```python
class _ChannelLeafDelegate(QStyledItemDelegate):
    SELECTED_BG = QColor("#b7d3f2")

# _CheckTolerantTree.drawBranches
painter.fillRect(rect, _ChannelLeafDelegate.SELECTED_BG)
```

- [x] **Step 4: Run focused and surrounding tests**

Run: `.venv\\Scripts\\python.exe -m pytest -q tests/ui/test_channel_widget.py tests/ui/test_channel_axis_groups.py --basetemp D:\\tmp\\pytest-channel-highlight-green`

Expected: PASS.

- [x] **Step 5: Verify the final diff**

Run: `git diff --check && git diff -- mf4_analyzer/ui/widgets/__init__.py mf4_analyzer/ui_kit/style.qss tests/ui/test_channel_widget.py`

Expected: only the synchronized selected-background paths and their rendering test change.
