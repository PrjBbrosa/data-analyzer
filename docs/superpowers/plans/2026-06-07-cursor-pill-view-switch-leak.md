# Cursor Pill View-Switch Leak Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 切换或新建 view 时，游标 pill 不再显示上一个 view 的游标读数。

**Architecture:** `_render_view_to_canvas` 里的 snapshot/restore 机制原本是为分屏副屏（off-screen 渲染）设计的；用已有参数 `update_primary_ui` 作门控，只在 `update_primary_ui=False`（副屏）时才保存和恢复 pill，从而修复所有 view 切换场景（新建 view、tab 切换），不影响分屏保护逻辑。

**Tech Stack:** PyQt5, pytest-qt

---

## 涉及文件

- 修改：`mf4_analyzer/ui/main_window.py`（`_render_view_to_canvas` 方法，约 588–613 行）
- 测试（新增两个用例）：`tests/ui/test_split_routing.py`
- 回归（现有，必须继续通过）：`tests/ui/test_split_routing.py::test_split_render_preserves_active_cursor_pill`

---

### Task 1：新增「新建 view 不泄漏 pill」回归测试

**Files:**
- Modify: `tests/ui/test_split_routing.py`

- [ ] **Step 1：在 `test_split_routing.py` 末尾追加测试**

在文件末尾（现有最后一个测试之后）加入：

```python
def test_new_view_does_not_carry_cursor_pill_from_previous_view(
    qtbot, qapp, loaded_csv
):
    """Creating a new view must not inherit the previous view's pill content."""
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "speed")
    w.plot_time()

    # Put a pill reading on View 1.
    w.chart_stack.set_cursor_mode("single")
    w.chart_stack._pill.set_primary("A=5.0s")
    w.chart_stack._pill.setVisible(True)
    qapp.processEvents()

    # Create a new blank View 2.
    w._on_view_new()
    qapp.processEvents()

    # The new view has cursor_mode="off"; pill must be empty.
    assert w.chart_stack.cursor_pill_text() == ""
    assert w.chart_stack.cursor_pill_visible() is False
```

- [ ] **Step 2：运行该测试，确认它失败**

```bash
cd "/Users/donghang/Downloads/data analyzer"
pytest tests/ui/test_split_routing.py::test_new_view_does_not_carry_cursor_pill_from_previous_view -v
```

期望：**FAILED**（pill 文字非空，因为 restore 把旧内容带回来了）

---

### Task 2：新增「切换到 cursor_mode=off 的已有 view 会清空 pill」回归测试

**Files:**
- Modify: `tests/ui/test_split_routing.py`

- [ ] **Step 1：在 Task 1 测试之后再追加一个测试**

```python
def test_switch_to_cursor_off_view_clears_pill(qtbot, qapp, loaded_csv):
    """Switching to an existing view whose cursor_mode='off' must clear the pill."""
    w, _fid, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    # After _make_speed_vs_torque_views, active view is 0 (speed, single cursor).
    # Force a known pill reading on the active canvas.
    w.chart_stack.set_cursor_mode("single")
    w.chart_stack._pill.set_primary("A=3.0s")
    w.chart_stack._pill.setVisible(True)
    qapp.processEvents()

    # View 1 (torque) has cursor_mode="dual" from _make_speed_vs_torque_views;
    # manually set it to "off" so we can test the clear path.
    w.view_manager.get(1).cursor_mode = "off"

    # Switch to View 1.
    w._switch_view(1)
    qapp.processEvents()

    assert w.chart_stack.cursor_pill_text() == ""
    assert w.chart_stack.cursor_pill_visible() is False
```

- [ ] **Step 2：运行该测试，确认它失败**

```bash
pytest tests/ui/test_split_routing.py::test_switch_to_cursor_off_view_clears_pill -v
```

期望：**FAILED**

- [ ] **Step 3：确认现有分屏 pill 保护测试仍在（后续作回归用）**

```bash
pytest tests/ui/test_split_routing.py::test_split_render_preserves_active_cursor_pill -v
```

期望：**PASSED**（这个测试应该在改动之后也继续通过）

---

### Task 3：修复 `_render_view_to_canvas` — 用 `update_primary_ui` 作门控

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py:588-613`

- [ ] **Step 1：找到 `_render_view_to_canvas` 方法**

文件：`mf4_analyzer/ui/main_window.py`，约第 588 行：

```python
def _render_view_to_canvas(self, idx, canvas, *, update_primary_ui):
    if canvas is None:
        return
    if not (0 <= idx < len(self.view_manager.views)):
        return
    state = self.view_manager.get(idx)

    cursor_pill_snapshot = self.chart_stack.cursor_pill_snapshot()
    restore_idx = self._focused_view_idx
    old_applying_view = getattr(self, '_applying_view', False)
    self._applying_view = True
    try:
        self._view_bridge.apply_controls_from_state(state, self, canvas)
        self._plot_time_on_canvas(canvas, update_primary_ui=update_primary_ui)
        canvas.restore_visible_xlim(state.xlim)
        canvas.restore_visible_ylims(state.ylims)
        tick_opts = (state.axis_opts or {}).get('tick_density') or {}
        canvas.set_tick_density(
            int(tick_opts.get('x', 10)),
            int(tick_opts.get('y', 6)),
        )
    finally:
        self._applying_view = old_applying_view
        if restore_idx is not None:
            self._project_view_controls(restore_idx)
        self.chart_stack.restore_cursor_pill_snapshot(cursor_pill_snapshot)
```

- [ ] **Step 2：把快照逻辑改为仅在副屏渲染时触发**

将上述代码替换为：

```python
def _render_view_to_canvas(self, idx, canvas, *, update_primary_ui):
    if canvas is None:
        return
    if not (0 <= idx < len(self.view_manager.views)):
        return
    state = self.view_manager.get(idx)

    # Snapshot/restore is only needed when rendering an off-screen secondary
    # canvas (split mode). For primary view switches the pill should reflect
    # the new view's state, not the previous view's readout.
    cursor_pill_snapshot = (
        self.chart_stack.cursor_pill_snapshot() if not update_primary_ui else None
    )
    restore_idx = self._focused_view_idx
    old_applying_view = getattr(self, '_applying_view', False)
    self._applying_view = True
    try:
        self._view_bridge.apply_controls_from_state(state, self, canvas)
        self._plot_time_on_canvas(canvas, update_primary_ui=update_primary_ui)
        canvas.restore_visible_xlim(state.xlim)
        canvas.restore_visible_ylims(state.ylims)
        tick_opts = (state.axis_opts or {}).get('tick_density') or {}
        canvas.set_tick_density(
            int(tick_opts.get('x', 10)),
            int(tick_opts.get('y', 6)),
        )
    finally:
        self._applying_view = old_applying_view
        if restore_idx is not None:
            self._project_view_controls(restore_idx)
        if cursor_pill_snapshot is not None:
            self.chart_stack.restore_cursor_pill_snapshot(cursor_pill_snapshot)
```

关键变化：
1. `cursor_pill_snapshot` 只在 `not update_primary_ui` 时才取值，否则为 `None`
2. finally 块里只在 `cursor_pill_snapshot is not None` 时才 restore

---

### Task 4：运行全部相关测试

**Files:** 无改动，只运行测试

- [ ] **Step 1：运行两个新测试，确认它们现在通过**

```bash
cd "/Users/donghang/Downloads/data analyzer"
pytest tests/ui/test_split_routing.py::test_new_view_does_not_carry_cursor_pill_from_previous_view \
       tests/ui/test_split_routing.py::test_switch_to_cursor_off_view_clears_pill -v
```

期望：两个都 **PASSED**

- [ ] **Step 2：运行分屏回归测试，确认保护逻辑未受影响**

```bash
pytest tests/ui/test_split_routing.py::test_split_render_preserves_active_cursor_pill -v
```

期望：**PASSED**

- [ ] **Step 3：运行整个分屏 pane controls 测试套件**

```bash
pytest tests/ui/test_split_routing.py tests/ui/test_split_per_pane_controls.py -v
```

期望：全部 **PASSED**

- [ ] **Step 4：运行 main_window 相关套件（快速冒烟）**

```bash
pytest tests/ui/test_main_window_smoke.py -v --timeout=60
```

期望：全部 **PASSED**

---

### Task 5：提交

- [ ] **Step 1：提交**

```bash
cd "/Users/donghang/Downloads/data analyzer"
git add mf4_analyzer/ui/main_window.py tests/ui/test_split_routing.py
git commit -m "fix(ui): cursor pill no longer leaks into new/switched view

Gate snapshot/restore in _render_view_to_canvas on update_primary_ui.
Only secondary-canvas (split) renders need to preserve the active pill;
primary view switches should reflect the new view's own cursor state.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
