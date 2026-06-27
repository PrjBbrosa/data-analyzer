# 游标 Pill 几何锚定可靠性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 TimeDomain 单游标/双游标切换时 cursor pill 漂移、越界或跳到屏幕中间的问题。

**Architecture:** 将 cursor pill 的内容更新与几何收口集中到 `ChartStack`。所有会改变 pill 尺寸的 signal handler 都通过一个 geometry wrapper：用户拖放过的 pill 保留右边缘，默认 pill 回到 emitting canvas 的右上角。`CursorPill` 只保留局部 `+` / `-` toggle 的右边缘移动 helper。

**Tech Stack:** PyQt5 · pytest-qt · QLabel rich text · offscreen Qt · existing ChartStack/CursorPill signal routing。

设计依据：`docs/superpowers/specs/2026-06-27-cursor-pill-geometry-reliability-design.md`

---

## Global Constraints

- 只触碰本计划列出的文件。
- 不修改 `mf4_analyzer/ui/pg_canvas/cursor.py` 的 emit 顺序。
- 不修改 cursor 数值计算、插值或双游标统计。
- 不改变单游标 mini value-only 的字符串契约。
- 不改变 `CursorPill` 圆角绘制方式或 QSS 视觉状态。
- split 模式下必须保持 primary/secondary pill 路由独立。
- 测试命令使用仓库 venv；每个任务步骤都列出完整 pytest 命令。
- 当前工作树可能有无关改动；提交时只 stage 本计划列出的文件。

---

## File Structure

- Modify `mf4_analyzer/ui/chart_stack/cursor_pill.py`
  将右边缘移动 helper 暴露为 `move_preserving_right_edge()`，供 `ChartStack` 的统一 geometry wrapper 调用。

- Modify `mf4_analyzer/ui/chart_stack/stack.py`
  新增 `_update_pill_content()` 和 `_on_dual_cursor_rows()`；将 `cursor_info`、`dual_cursor_info`、`dual_cursor_rows` 三条路径都纳入统一几何处理。

- Modify `tests/ui/test_chart_stack.py`
  增加 primary pill 的内容变宽、内容变窄、默认锚定回归测试。

- Modify `tests/ui/test_split_per_pane_controls.py`
  增加 secondary pill 的 `dual_cursor_rows` 几何保护和 primary/secondary 不串扰测试。

---

## Task 1: 写 primary pill 几何失败测试

**Files:**
- Modify: `tests/ui/test_chart_stack.py`

**Purpose:** 先固定当前可靠性 bug：内容更新导致 pill 尺寸变化时，用户拖放位置应该保留右边缘，而不是保留左边界或越界。

- [ ] **Step 1: 在 imports 可用区域确认无需新增全局依赖**

`tests/ui/test_chart_stack.py` 已经在现有测试里局部 import `ChartStack`、`CursorPill`、`_CURSOR_HTML_SEP`，本任务继续使用局部 import，不新增文件级 import。

- [ ] **Step 2: 添加 dual rows 变宽不越界测试**

在 `test_cursor_pill_toggle_expand_stays_inside_parent_right_edge` 后追加：

```python
def test_user_placed_primary_pill_preserves_right_edge_after_dual_rows_resize(
    qapp, qtbot
):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('dual')
    qapp.processEvents()

    cs._pill.set_primary("<span>A=1.0s │ B=2.0s</span>")
    cs._pill.set_detail_html("<table><tr><td>short</td></tr></table>")
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    cs._pill.move(cs.stack.width() - cs._pill.width() - 8, 48)
    qapp.processEvents()

    old_right = cs._pill.x() + cs._pill.width()
    rows = [
        (
            "very_long_channel_name_that_expands_the_dual_cursor_rows_width",
            -1.0,
            2.0,
            0.5,
            1.5,
            " Nm",
            "#ef4444",
        ),
        (
            "another_long_channel_name_to_force_a_wider_floating_pill",
            -3.0,
            4.0,
            0.25,
            -0.75,
            " deg",
            "#1769e0",
        ),
    ]

    cs.canvas_time.dual_cursor_rows.emit(rows)
    qapp.processEvents()

    new_right = cs._pill.x() + cs._pill.width()
    assert new_right <= cs.stack.width()
    assert abs(new_right - min(old_right, cs.stack.width())) <= 1
```

- [ ] **Step 3: 添加宽内容切回窄内容不漂到中间测试**

继续在同一测试区域追加：

```python
def test_user_placed_primary_pill_preserves_right_edge_when_content_shrinks(
    qapp, qtbot
):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('dual')
    qapp.processEvents()

    cs._pill.set_primary("<span>A=1.0s │ B=2.0s │ ΔT=1.0s</span>")
    cs._pill.set_detail_html(
        "<table><tr><td>"
        "very_long_dual_cursor_channel_name_that_makes_the_pill_wide=123 Nm"
        "</td></tr></table>"
    )
    cs._pill.setVisible(True)
    cs._pill.mark_user_placed(True)
    cs._pill.move(cs.stack.width() - cs._pill.width() - 8, 56)
    qapp.processEvents()

    old_right = cs._pill.x() + cs._pill.width()
    old_x = cs._pill.x()

    cs.set_cursor_mode('single')
    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=3.0000s</span>',
        '<span style="color:#1769e0;">speed=<b>5 rpm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)
    qapp.processEvents()

    new_right = cs._pill.x() + cs._pill.width()
    assert cs._pill.x() > old_x
    assert abs(new_right - old_right) <= 1
```

- [ ] **Step 4: 添加未拖放 pill 仍自动锚定测试**

继续追加：

```python
def test_default_primary_pill_reanchors_to_canvas_after_mode_content_resize(
    qapp, qtbot
):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(900, 420)
    cs.show()
    cs.set_mode('time')
    cs.set_cursor_mode('single')
    qapp.processEvents()

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=1.0000s</span>',
        '<span style="color:#ef4444;">long_name=<b>1 Nm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)
    qapp.processEvents()

    canvas_origin = cs.canvas_time.mapTo(cs.stack, cs.canvas_time.rect().topLeft())
    expected_right = canvas_origin.x() + cs.canvas_time.width() - 8
    actual_right = cs._pill.x() + cs._pill.width()
    assert abs(actual_right - expected_right) <= 2
    assert cs._pill.is_user_placed() is False
```

- [ ] **Step 5: 运行新测试确认失败**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_user_placed_primary_pill_preserves_right_edge_after_dual_rows_resize \
  tests/ui/test_chart_stack.py::test_user_placed_primary_pill_preserves_right_edge_when_content_shrinks \
  tests/ui/test_chart_stack.py::test_default_primary_pill_reanchors_to_canvas_after_mode_content_resize \
  -q
```

Expected:

- 前两个测试至少一个失败：当前 `set_dual_rows()` 直连或 user-placed clamp-left 策略不会保留右边缘。
- 第三个测试应通过或保持接近通过，用来证明默认锚定契约没有被新测试误伤。

---

## Task 2: 集中 primary/dual 内容更新的几何收口

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/cursor_pill.py`
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Test: `tests/ui/test_chart_stack.py`

**Purpose:** 把尺寸变化后的“保留右边缘或自动锚定”集中到 `ChartStack`，并修复 `dual_cursor_rows` 最后 resize 但不 reposition 的问题。

- [ ] **Step 1: 暴露 CursorPill 右边缘移动 helper**

在 `mf4_analyzer/ui/chart_stack/cursor_pill.py` 中，把现有 `_move_preserving_right_edge()` 改为 public helper，并保留 private alias：

```python
    def _toggle_mode(self):
        old_right = self.x() + self.width()
        old_top = self.y()
        self._mode = "mini" if self._mode == "full" else "full"
        self._update_toggle_button()
        self._refresh_detail()
        self.adjustSize()
        self.move_preserving_right_edge(old_right, old_top)

    def move_preserving_right_edge(self, right_edge, top):
        parent = self.parentWidget()
        new_x = int(right_edge) - self.width()
        new_y = int(top)
        if parent is not None:
            anchor_right = max(0, min(int(right_edge), parent.width()))
            max_x = max(parent.width() - self.width(), 0)
            max_y = max(parent.height() - self.height(), 0)
            new_x = max(0, min(anchor_right - self.width(), max_x))
            new_y = max(0, min(new_y, max_y))
        self.move(new_x, new_y)

    _move_preserving_right_edge = move_preserving_right_edge
```

- [ ] **Step 2: 将 primary dual_cursor_rows 连接改走 ChartStack**

在 `mf4_analyzer/ui/chart_stack/stack.py:228-229` 附近，将：

```python
        if hasattr(self.canvas_time, 'dual_cursor_rows'):
            self.canvas_time.dual_cursor_rows.connect(self._pill.set_dual_rows)
```

改为：

```python
        if hasattr(self.canvas_time, 'dual_cursor_rows'):
            self.canvas_time.dual_cursor_rows.connect(
                lambda rows: self._on_dual_cursor_rows(rows, self.canvas_time)
            )
```

- [ ] **Step 3: 新增 `_update_pill_content()`**

在 `ChartStack._on_dual_cursor_info()` 前或 `_reposition_pill()` 前新增：

```python
    def _update_pill_content(self, pill, card, update):
        was_user_placed = pill.is_user_placed()
        old_right = pill.x() + pill.width()
        old_top = pill.y()
        update()
        if not pill.isVisible():
            return
        if was_user_placed:
            pill.move_preserving_right_edge(old_right, old_top)
            pill.raise_()
        else:
            self._reposition_one_pill(pill, card)
```

- [ ] **Step 4: 包装 `_on_cursor_info()` 内容更新**

将 `mf4_analyzer/ui/chart_stack/stack.py:1040-1059` 的 `_on_cursor_info()` 改为：

```python
    def _on_cursor_info(self, text, source=None):
        mode = self._cursor_mode_for_canvas(source)
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)
        if not text:
            pill.clear()
            self._reposition_pill()
            return

        def update():
            if mode == 'single':
                primary, detail, mini_detail, tooltip = (
                    self._format_single_cursor_variants_for_pill(text)
                )
                pill.set_primary(primary)
                pill.set_single_detail_html(detail, mini_detail, tooltip)
            else:
                primary, _detail = self._format_cursor_info_for_pill(text, mode)
                pill.set_primary(primary)
            pill.setVisible(self._cursor_pill_visible_for_mode())

        self._update_pill_content(pill, card, update)
```

- [ ] **Step 5: 包装 `_on_dual_cursor_info()` 内容更新**

将 `mf4_analyzer/ui/chart_stack/stack.py:1158-1165` 的 `_on_dual_cursor_info()` 改为：

```python
    def _on_dual_cursor_info(self, text, source=None):
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)

        def update():
            pill.set_detail_html(text)
            if self.current_mode() == 'time' and (text or pill.primary_text()):
                pill.setVisible(True)

        self._update_pill_content(pill, card, update)
```

- [ ] **Step 6: 新增 `_on_dual_cursor_rows()`**

在 `_on_dual_cursor_info()` 后新增：

```python
    def _on_dual_cursor_rows(self, rows, source=None):
        if source is not None:
            self._active_cursor_card = self._card_for_canvas(source)
        pill = self._pill_for_canvas(source)
        card = self._card_for_canvas(source)

        def update():
            pill.set_dual_rows(rows)
            if self.current_mode() == 'time' and (rows or pill.primary_text()):
                pill.setVisible(True)

        self._update_pill_content(pill, card, update)
```

- [ ] **Step 7: 运行 primary 几何测试**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_user_placed_primary_pill_preserves_right_edge_after_dual_rows_resize \
  tests/ui/test_chart_stack.py::test_user_placed_primary_pill_preserves_right_edge_when_content_shrinks \
  tests/ui/test_chart_stack.py::test_default_primary_pill_reanchors_to_canvas_after_mode_content_resize \
  tests/ui/test_chart_stack.py::test_cursor_pill_toggle_collapse_preserves_right_edge \
  tests/ui/test_chart_stack.py::test_cursor_pill_toggle_expand_stays_inside_parent_right_edge \
  -q
```

Expected: all selected tests pass.

---

## Task 3: 覆盖 secondary pill 和 split 路由

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Modify: `tests/ui/test_split_per_pane_controls.py`

**Purpose:** 防止 primary 修复把 split 模式打回全局 pill；secondary canvas 的 rows 更新也必须走同一 geometry wrapper。

- [ ] **Step 1: 将 secondary dual_cursor_rows 连接改走 ChartStack**

在 `mf4_analyzer/ui/chart_stack/stack.py:646-647` 附近，将：

```python
            if hasattr(canvas, 'dual_cursor_rows'):
                canvas.dual_cursor_rows.connect(self._pill_secondary.set_dual_rows)
```

改为：

```python
            if hasattr(canvas, 'dual_cursor_rows'):
                canvas.dual_cursor_rows.connect(
                    lambda rows, c=canvas: self._on_dual_cursor_rows(rows, c)
                )
```

- [ ] **Step 2: 添加 secondary rows 几何测试**

在 `tests/ui/test_split_per_pane_controls.py::test_split_secondary_single_cursor_mini_detail_stays_on_secondary_pill` 后追加：

```python
def test_user_placed_secondary_pill_preserves_right_edge_after_dual_rows_resize(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    cs._secondary_card.set_cursor_mode("dual")
    qapp.processEvents()

    assert cs._pill_secondary is not None
    cs.canvas_time.cursor_info.emit("t=9.0s | primary=1")
    cs._pill_secondary.set_primary("<span>A=1.0s │ B=2.0s</span>")
    cs._pill_secondary.set_detail_html("<table><tr><td>short</td></tr></table>")
    cs._pill_secondary.setVisible(True)
    cs._pill_secondary.mark_user_placed(True)
    cs._pill_secondary.move(
        cs.stack.width() - cs._pill_secondary.width() - 8,
        64,
    )
    qapp.processEvents()

    old_primary_right = cs._pill.x() + cs._pill.width()
    old_right = cs._pill_secondary.x() + cs._pill_secondary.width()
    rows = [
        (
            "secondary_long_channel_name_that_expands_the_pill_width",
            -1.0,
            2.0,
            0.5,
            1.5,
            " Nm",
            "#1769e0",
        )
    ]

    cs.secondary_canvas().dual_cursor_rows.emit(rows)
    qapp.processEvents()

    new_right = cs._pill_secondary.x() + cs._pill_secondary.width()
    assert new_right <= cs.stack.width()
    assert abs(new_right - min(old_right, cs.stack.width())) <= 1
    assert cs._pill.x() + cs._pill.width() == old_primary_right
    assert "t=9.0s" in cs.cursor_pill_text()
```

- [ ] **Step 3: 运行 split 几何测试**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_per_pane_controls.py::test_user_placed_secondary_pill_preserves_right_edge_after_dual_rows_resize \
  tests/ui/test_split_per_pane_controls.py::test_secondary_canvas_cursor_readout_reaches_secondary_pill \
  tests/ui/test_split_per_pane_controls.py::test_split_dual_cursor_results_show_on_both_pane_pills \
  tests/ui/test_split_per_pane_controls.py::test_split_secondary_single_cursor_mini_detail_stays_on_secondary_pill \
  -q
```

Expected: all selected tests pass.

---

## Task 4: 回归验证、lesson gate、提交

**Files:**
- Verify only unless a test exposes a narrow issue in files already modified by this plan.

**Purpose:** 证明修复覆盖 cursor pill 主要入口，并保留 split/view routing 与 rounded pill 视觉契约。

- [ ] **Step 1: 运行 cursor pill 与 split 回归集合**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py \
  tests/ui/test_split_routing.py \
  -q
```

Expected: all tests pass. Record the exact pass count.

- [ ] **Step 2: 运行圆角像素回归**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_cursor_pill_renders_transparent_rounded_corners \
  -q
```

Expected: pass.

- [ ] **Step 3: 检查 whitespace**

Run:

```bash
git diff --check -- \
  mf4_analyzer/ui/chart_stack/cursor_pill.py \
  mf4_analyzer/ui/chart_stack/stack.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py \
  docs/superpowers/specs/2026-06-27-cursor-pill-geometry-reliability-design.md \
  docs/superpowers/plans/2026-06-27-cursor-pill-geometry-reliability.md
```

Expected: no output.

- [ ] **Step 4: Lesson gate**

Run:

```bash
/usr/bin/python3 scripts/lessons/check.py --require "cursor pill content updates need shared geometry anchoring"
```

Expected: command records a lesson requirement.

Create `.state/lesson-candidate.md` from `docs/lessons-learned/_template.md`, fill it with:

```markdown
---
id: codex-cursor-pill-content-geometry-anchoring
status: active
owners: [codex]
keywords: [cursor-pill, geometry, user-placed, dual_cursor_rows, split-pane]
paths:
  - mf4_analyzer/ui/chart_stack/stack.py
  - mf4_analyzer/ui/chart_stack/cursor_pill.py
  - tests/ui/test_chart_stack.py
  - tests/ui/test_split_per_pane_controls.py
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py tests/ui/test_split_per_pane_controls.py tests/ui/test_split_routing.py -q
---

# Cursor Pill Content Geometry Anchoring

Trigger: Touching cursor pill content updates, single/dual cursor mode switching, `dual_cursor_rows`, or split-pane cursor pill routing.

Past failure: Fixing only `CursorPill._toggle_mode()` preserved the right edge for `+` / `-`, but single/dual cursor switching still resized the pill through `set_primary`, `set_detail_html`, `set_single_detail_html`, and direct `dual_cursor_rows -> set_dual_rows` paths. User-placed pills then kept the clamped left edge when content shrank, making the pill jump toward the center or offscreen.

Rule: All size-changing cursor pill content updates must pass through a shared geometry wrapper. User-placed pills preserve the pre-update right edge and top; default pills re-anchor to the emitting canvas/card. `dual_cursor_rows` must route through `ChartStack`, not directly into `CursorPill`.

Verification: Run the cursor pill, split per-pane, and split routing suites together so primary and secondary pills, single/dual switching, and view routing are covered.
```

Promote it:

```bash
/usr/bin/python3 scripts/lessons/promote.py
```

Expected: a new lesson appears under `docs/lessons-learned/` and `docs/lessons-learned/INDEX.md` updates.

- [ ] **Step 5: Inspect changed-file scope**

Run:

```bash
git status --short
git diff --stat -- \
  mf4_analyzer/ui/chart_stack/cursor_pill.py \
  mf4_analyzer/ui/chart_stack/stack.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py \
  docs/superpowers/specs/2026-06-27-cursor-pill-geometry-reliability-design.md \
  docs/superpowers/plans/2026-06-27-cursor-pill-geometry-reliability.md \
  docs/lessons-learned/INDEX.md \
  docs/lessons-learned/codex-cursor-pill-content-geometry-anchoring.md
```

Expected: only this plan's implementation/docs/lesson files are in the intended commit set; unrelated dirty files remain unstaged.

- [ ] **Step 6: Commit only relevant files**

Run:

```bash
git add \
  mf4_analyzer/ui/chart_stack/cursor_pill.py \
  mf4_analyzer/ui/chart_stack/stack.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py \
  docs/superpowers/specs/2026-06-27-cursor-pill-geometry-reliability-design.md \
  docs/superpowers/plans/2026-06-27-cursor-pill-geometry-reliability.md \
  docs/lessons-learned/INDEX.md \
  docs/lessons-learned/codex-cursor-pill-content-geometry-anchoring.md
git commit -m "fix(ui): stabilize cursor pill geometry across mode changes"
```

Expected: commit succeeds and excludes unrelated dirty files.

---

## Self-Review Checklist

- [ ] Spec requirement “user-placed pill preserves right edge” is covered by Task 1 primary tests and Task 3 secondary test.
- [ ] Spec requirement “default pill reanchors to canvas” is covered by Task 1 default-anchor test.
- [ ] Spec requirement “dual_cursor_rows goes through ChartStack” is covered by Task 2 primary connect change and Task 3 secondary connect change.
- [ ] Spec requirement “split panes do not cross-write pills” is covered by existing split tests plus the new secondary geometry test.
- [ ] No plan step requires changing cursor calculations or `pg_canvas/cursor.py` emit order.
- [ ] 没有留下占位式执行描述；每个改代码步骤都有具体路径、代码片段和验证命令。
