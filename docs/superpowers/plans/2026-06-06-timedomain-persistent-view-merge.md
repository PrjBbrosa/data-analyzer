# 时域多 View 持久合并与双栏状态同步 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前时域 split compare 从临时对比升级为持久 view 合并关系，并让双栏内每个 pane 的通道、布局、游标、缩放和坐标设置都写回它自己的 `ViewState`。

**Architecture:** 保留现有 `ViewState` / `ViewManager` / `ViewCaptureBridge` / `ViewTabBar` 分层。`ViewManager` 增加对称 split pair；`MainWindow` 增加 pane-to-view binding；全局控件在 split active 时投影为 focused pane 的 state；secondary 重绘复用现有 plot 管线，但必须先投影 secondary state，渲染后再恢复 focused controls。

**Tech Stack:** Python 3.12 · PyQt5 · pyqtgraph · pytest + pytest-qt。

**对应 spec:** `docs/superpowers/specs/2026-06-06-timedomain-persistent-view-merge-design.md`

---

## 修订说明（2026-06-06 review 后）

本计划在 review 中发现 4 处会导致功能不达标 / 状态错乱的实现缺口，已就地修正，实现时以本节为准：

1. **plot_mode / cursor_mode 必须按 pane 寻址，不能走「临时全局 apply」。**
   `_plot_time_on_canvas` 渲染 secondary 时，布局读 `chart_stack.plot_mode_for_canvas(canvas)`→**secondary card**、游标读 `_cursor_mode_for_canvas(canvas)`；而旧 `apply_view` 写 plot_mode 走 `chart_stack.set_plot_mode()`，只改 `_primary_plot_mode`，**够不到 secondary card**。所以 channel/colors/overlay_primary/range 可以继续走临时全局 apply，但 plot_mode/cursor 必须经由 chart_stack 的 canvas-keyed setter 写到目标 card。否则 secondary 切走再切回后布局/游标不保持。Task 3 改为 pane-aware bridge，Task 4/5 把 `canvas` 一路传下去。
2. **`set_active` 不再发 `split_changed`。** 否则在已合并 view 间切换会同时触发 `_on_view_split` 和 `_apply_active_view`，各做一遍两栏整屏渲染（双触发）。`split_changed` 只留给显式 `set_split`/`clear_split_for`；切换的渲染交给 `active_changed → _apply_active_view` 单一路径。见 Task 2 Step 3。
3. **`duplicate()` 也要按对象身份重排 `_split_pairs`。** 它在 `idx+1` 处 `insert`，会把其后下标 +1，整数键 pair 会错位。见 Task 2 Step 3。
4. **`ViewTabBar` 要接 `split_changed` 才能刷新合并状态片。** 创建/取消合并只发 `split_changed`，旧连线只有 `views_changed`/`active_changed`。见 Task 7 Step 2。

另纳入两个功能点：再合并会静默拆掉旧合并 → 给提示（Task 7 Step 3）；合并状态片标出当前在编辑哪一栏（Task 7 Step 2）。

---

## 0. 文件结构

**修改：**

- `mf4_analyzer/ui/view_state.py`：增加持久 split pair 管理；调整 `set_active` 不再清 pair。
- `mf4_analyzer/ui/view_bridge.py`：拆出 controls capture/apply 与 canvas ranges capture。
- `mf4_analyzer/ui/main_window.py`：增加 pane binding、focused view capture/projection、state-based secondary render、range sync。
- `mf4_analyzer/ui/chart_stack.py`：暴露 secondary canvas/card 生命周期钩子，确保 secondary range signal 可连接；保持 focus routing；**新增 canvas-keyed 写侧 `set_plot_mode_for_canvas` / `set_cursor_mode_for_canvas` 与公开读侧 `cursor_mode_for_canvas`**，让 bridge 能把 plot_mode/cursor 写到正确的 pane（见修订说明 1）。
- `mf4_analyzer/ui/view_tabbar.py`：增加 `取消合并` 菜单项与合并状态片。
- `mf4_analyzer/ui/pg_canvases.py`：增加 `visible_range_changed`，在 X/Y 用户范围变化后发射。

**测试：**

- `tests/ui/test_view_manager.py`
- `tests/ui/test_split_routing.py`
- `tests/ui/test_split_focus_routing.py`
- `tests/ui/test_split_per_pane_controls.py`
- `tests/ui/test_view_tabbar.py`
- `tests/ui/test_pg_timedomain_canvas.py`

---

## Task 1: 写红灯测试覆盖三个用户反馈

**Files:**

- Modify: `tests/ui/test_split_routing.py`
- Modify: `tests/ui/test_split_per_pane_controls.py`
- Modify: `tests/ui/test_split_focus_routing.py`

- [ ] **Step 1: 改写 split 切换退出测试为持久保持测试**

在 `tests/ui/test_split_routing.py` 中把旧的 `test_split_renders_compare_view_and_switch_exits` 改为新语义：

```python
def test_split_pair_persists_when_switching_between_paired_views(
    qtbot, qapp, loaded_csv
):
    w, _fid_value, view1_xlim, view1_ylims, view2_xlim, view2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )

    # View 0 = speed, View 1 = torque. Start on View 0 and pair with View 1.
    assert w.view_manager.active == 0
    w.view_manager.set_split(1)
    qapp.processEvents()

    assert w.chart_stack.split_active() is True
    assert w.view_manager.split_with == 1
    assert _has_channel(w.canvas_time, "speed")
    assert _has_channel(w.chart_stack.secondary_canvas(), "torque")

    # Switching to the paired view keeps split active, but primary/secondary swap.
    w._switch_view(1)
    qapp.processEvents()

    assert w.chart_stack.split_active() is True
    assert w.view_manager.active == 1
    assert w.view_manager.split_with == 0
    assert _has_channel(w.canvas_time, "torque")
    assert _has_channel(w.chart_stack.secondary_canvas(), "speed")
    _assert_pair(w.canvas_time.get_visible_xlim(), view2_xlim)
    _assert_canvas_ylims(w.canvas_time, view2_ylims)
    _assert_pair(w.chart_stack.secondary_canvas().get_visible_xlim(), view1_xlim)
    _assert_canvas_ylims(w.chart_stack.secondary_canvas(), view1_ylims)

    # Switching back also keeps the pair.
    w._switch_view(0)
    qapp.processEvents()

    assert w.chart_stack.split_active() is True
    assert w.view_manager.active == 0
    assert w.view_manager.split_with == 1
    assert _has_channel(w.canvas_time, "speed")
    assert _has_channel(w.chart_stack.secondary_canvas(), "torque")
```

- [ ] **Step 2: 增加“secondary plot mode 不偷 active channels”测试**

在 `tests/ui/test_split_per_pane_controls.py` 追加：

```python
def test_secondary_plot_mode_toggle_uses_secondary_view_state_not_active(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack

    # Move to View 1 (torque), then merge View 0 (speed) into it.
    w._switch_view(1)
    qapp.processEvents()
    w.view_manager.set_split(0)
    qapp.processEvents()

    assert _has_channel(cs.canvas_time, "torque")
    assert not _has_channel(cs.canvas_time, "speed")
    assert _has_channel(cs.secondary_canvas(), "speed")
    assert not _has_channel(cs.secondary_canvas(), "torque")

    _click_card(qapp, cs._secondary_card)
    assert cs.focused_canvas() is cs.secondary_canvas()

    # Toggle the focused secondary pane layout through the shared control.
    cs._time_card.set_plot_mode("overlay")
    qapp.processEvents()

    assert cs._secondary_card.plot_mode() == "overlay"
    assert _has_channel(cs.secondary_canvas(), "speed")
    assert not _has_channel(cs.secondary_canvas(), "torque")
    assert _has_channel(cs.canvas_time, "torque")
    assert not _has_channel(cs.canvas_time, "speed")
```

- [ ] **Step 3: 增加 secondary 范围写回测试**

在 `tests/ui/test_split_focus_routing.py` 追加：

```python
def test_secondary_range_changes_write_back_to_original_view_state(
    qtbot, qapp, loaded_csv
):
    w, _fid_value, _v1_xlim, _v1_ylims, _v2_xlim, _v2_ylims = (
        _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    )
    cs = w.chart_stack

    w._switch_view(1)
    qapp.processEvents()
    w.view_manager.set_split(0)
    qapp.processEvents()

    secondary = cs.secondary_canvas()
    assert secondary is not None
    assert w.view_manager.split_with == 0

    target_xlim = (0.23, 0.47)
    secondary.restore_visible_xlim(target_xlim)
    w._capture_canvas_ranges_for_bound_view(secondary)

    assert w.view_manager.get(0).xlim == pytest.approx(target_xlim)

    # Open View 0 as primary; it should keep the secondary pane's last range.
    w._switch_view(0)
    qapp.processEvents()
    assert w.canvas_time.get_visible_xlim() == pytest.approx(target_xlim)
```

Add `import pytest` to this file if it is not already present.

- [ ] **Step 4: 增加“secondary 保持自己的 plot_mode”测试（覆盖修订说明 1）**

这条专门堵住「channel/range 对了、但 secondary 布局不对」的盲区：secondary 渲染必须从它自己的 `ViewState.plot_mode` 取布局，而不是沿用 secondary card 上一次的 toggle 值。

在 `tests/ui/test_split_routing.py` 追加：

```python
def test_secondary_pane_keeps_its_own_plot_mode_across_switches(
    qtbot, qapp, loaded_csv
):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack

    # View 0 = speed/overlay, View 1 = torque/subplot.
    w.view_manager.get(0).plot_mode = "overlay"
    w.view_manager.get(1).plot_mode = "subplot"

    assert w.view_manager.active == 0
    w.view_manager.set_split(1)
    qapp.processEvents()

    # primary = View 0 (overlay), secondary = View 1 (subplot).
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "overlay"
    assert cs.plot_mode_for_canvas(cs.secondary_canvas()) == "subplot"

    # Switch to View 1: panes swap, each keeps its own layout.
    w._switch_view(1)
    qapp.processEvents()
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "subplot"
    assert cs.plot_mode_for_canvas(cs.secondary_canvas()) == "overlay"

    # Switch back: still each its own.
    w._switch_view(0)
    qapp.processEvents()
    assert cs.plot_mode_for_canvas(cs.canvas_time) == "overlay"
    assert cs.plot_mode_for_canvas(cs.secondary_canvas()) == "subplot"
```

- [ ] **Step 5: 运行红灯测试**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_routing.py::test_split_pair_persists_when_switching_between_paired_views \
  tests/ui/test_split_routing.py::test_secondary_pane_keeps_its_own_plot_mode_across_switches \
  tests/ui/test_split_per_pane_controls.py::test_secondary_plot_mode_toggle_uses_secondary_view_state_not_active \
  tests/ui/test_split_focus_routing.py::test_secondary_range_changes_write_back_to_original_view_state \
  -q
```

Expected: FAIL。失败原因应分别指向 split 被清、secondary 布局沿用 card 旧值、secondary 重绘拿 active channels、缺少 `_capture_canvas_ranges_for_bound_view` 或范围未写回。

- [ ] **Step 6: 提交红灯测试**

```bash
git add tests/ui/test_split_routing.py tests/ui/test_split_per_pane_controls.py tests/ui/test_split_focus_routing.py
git commit -m "test(view): cover persistent split view state routing"
```

---

## Task 2: ViewManager 持久 pair 模型

**Files:**

- Modify: `mf4_analyzer/ui/view_state.py`
- Modify: `tests/ui/test_view_manager.py`

- [ ] **Step 1: 增加 ViewManager pair 单测（并改写旧的 clears-split 用例）**

> ⚠️ 先改写现存的 `test_set_active_clears_split`（`tests/ui/test_view_manager.py:116`）。它断言「`set_active` 会清 split 并发 `split_changed(None)`」，正是新设计要推翻的旧语义，且 Task 8 的 grep（`exit.*split|set_split(None)|...`）**抓不到它**。用下面的 `test_set_split_creates_symmetric_pair_and_active_partner` + `test_set_active_to_unpaired_view_hides_split_without_deleting_pair` 取代它。`test_set_active_current_view_is_noop`（同文件:133）仍成立，保留不动。

在 `tests/ui/test_view_manager.py` 追加：

```python
def test_set_split_creates_symmetric_pair_and_active_partner():
    m = ViewManager()
    m.new_view()
    m.set_active(0)
    m.set_split(1)

    assert m.partner_for(0) == 1
    assert m.partner_for(1) == 0
    assert m.split_with == 1

    m.set_active(1)
    assert m.split_with == 0


def test_set_active_to_unpaired_view_hides_split_without_deleting_pair():
    m = ViewManager()
    m.new_view()
    m.new_view()
    m.set_active(0)
    m.set_split(1)

    m.set_active(2)
    assert m.split_with is None
    assert m.partner_for(0) == 1
    assert m.partner_for(1) == 0

    m.set_active(0)
    assert m.split_with == 1


def test_clear_split_for_removes_pair_from_both_sides():
    m = ViewManager()
    m.new_view()
    m.set_active(0)
    m.set_split(1)

    m.clear_split_for(1)
    assert m.partner_for(0) is None
    assert m.partner_for(1) is None
    assert m.split_with is None


def test_reorder_keeps_pair_with_view_objects():
    m = ViewManager()
    m.new_view()
    m.new_view()
    m.views[0].name = "A"
    m.views[1].name = "B"
    m.views[2].name = "C"
    m.set_active(0)
    m.set_split(1)

    m.reorder(0, 2)

    names = [v.name for v in m.views]
    a_idx = names.index("A")
    b_idx = names.index("B")
    assert m.partner_for(a_idx) == b_idx
    assert m.partner_for(b_idx) == a_idx


def test_delete_clears_pair_for_deleted_view_and_remaps_others():
    m = ViewManager()
    m.new_view()
    m.new_view()
    m.set_active(0)
    m.set_split(2)

    m.delete_view(1)

    assert len(m.views) == 2
    assert m.partner_for(0) == 1
    assert m.partner_for(1) == 0

    m.delete_view(1)
    assert m.partner_for(0) is None
    assert m.split_with is None
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_manager.py -q
```

Expected: FAIL with missing `partner_for` / `clear_split_for` or old `set_active` clearing split.

- [ ] **Step 3: 修改 `ViewManager`**

在 `mf4_analyzer/ui/view_state.py`：

```python
class ViewManager(QObject):
    ...
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.views: list[ViewState] = [self._make(0)]
        self.active = 0
        self.split_with: int | None = None
        self._split_pairs: dict[int, int] = {}

    def partner_for(self, idx: int) -> int | None:
        if not self._is_valid_index(idx):
            return None
        partner = self._split_pairs.get(idx)
        if partner is None or not self._is_valid_index(partner):
            return None
        return partner

    def has_split_pair(self, idx: int) -> bool:
        return self.partner_for(idx) is not None

    def _set_active_split_from_pairs(self) -> None:
        self.split_with = self.partner_for(self.active)

    def set_active(self, idx: int) -> None:
        if not self._is_valid_index(idx) or idx == self.active:
            return
        self.active = idx
        # Sync the active-partner snapshot SILENTLY. Do NOT emit split_changed
        # here (修订说明 2): 否则在已合并 view 间切换会同时触发 _on_view_split
        # 和 _apply_active_view，各做一遍两栏整屏渲染。split_changed 只留给显式
        # set_split / clear_split_for；切换由 active_changed → _apply_active_view
        # 读 split_with 后单路径重绘。tabbar 状态片仍靠 active_changed →
        # _sync_active → _update_split_chip 在切换时刷新文案。
        self._set_active_split_from_pairs()
        self.active_changed.emit(idx)

    def set_split(self, idx: int | None) -> None:
        if idx is None:
            self.clear_split_for(self.active)
            return
        if idx == self.active or not self._is_valid_index(idx):
            return
        self.clear_split_for(self.active, emit=False)
        self.clear_split_for(idx, emit=False)
        self._split_pairs[self.active] = idx
        self._split_pairs[idx] = self.active
        old_split = self.split_with
        self._set_active_split_from_pairs()
        if self.split_with != old_split:
            self.split_changed.emit(self.split_with)

    def clear_split_for(self, idx: int | None = None, *, emit: bool = True) -> None:
        target = self.active if idx is None else idx
        partner = self._split_pairs.pop(target, None)
        if partner is not None:
            self._split_pairs.pop(partner, None)
        old_split = self.split_with
        self._set_active_split_from_pairs()
        if emit and self.split_with != old_split:
            self.split_changed.emit(self.split_with)
```

Update `delete_view()` and `reorder()` with view-object based remapping:

```python
def _snapshot_pairs_by_object(self) -> list[tuple[ViewState, ViewState]]:
    out = []
    seen = set()
    for a, b in self._split_pairs.items():
        if a in seen or b in seen:
            continue
        if self._is_valid_index(a) and self._is_valid_index(b):
            out.append((self.views[a], self.views[b]))
            seen.add(a)
            seen.add(b)
    return out

def _restore_pairs_by_object(self, pairs: list[tuple[ViewState, ViewState]]) -> None:
    self._split_pairs = {}
    for a_state, b_state in pairs:
        if a_state in self.views and b_state in self.views:
            a = self.views.index(a_state)
            b = self.views.index(b_state)
            self._split_pairs[a] = b
            self._split_pairs[b] = a
    self._set_active_split_from_pairs()
```

Use these snapshots before and after `delete_view()` / `reorder()` **以及 `duplicate()`**（修订说明 3）：`duplicate()` 在 `idx + 1` 处 `insert`，会把其后所有 view 的下标 +1，而 `_split_pairs` 是整数键，不重排就会指向错位的 view。`new_view()` 追加在末尾、不移位，可不处理。具体做法：在这些方法里先 `pairs = self._snapshot_pairs_by_object()`，完成 list 变更后 `self._restore_pairs_by_object(pairs)`（其末尾会 `self._set_active_split_from_pairs()` 重算 `split_with`）。被删/被复制的 view 自身的 pair 会因「对象已不在/副本未配对」而自然落空——符合「副本默认未合并、删除即解除合并」语义。

注意信号：`delete_view` / `reorder` 重排后要按「active 的 partner 是否变化」决定补发 `split_changed`（修订 2 后这是触发 `_on_view_split` 重绘的唯一途径）。即重排前记下 `old_split = self.split_with`，重排后若 `self.split_with != old_split` 则 `self.split_changed.emit(self.split_with)`。这样：删掉 active 的伙伴 → 发 `split_changed(None)` → 退回单栏；删/排无关 view → `split_with` 不变 → 不重绘、合并关系保留。`delete_view` 现有「无条件清 split」的旧逻辑要换成这套。补一条用例：合并 0↔1、active=0，删一个无关的 View 2，断言合并仍在（`partner_for(0) == 1` 且未发多余 `split_changed`）。

新增 `duplicate` pair 重排单测：

```python
def test_duplicate_remaps_unrelated_pair_after_insert():
    m = ViewManager()
    m.new_view()
    m.new_view()  # views: 0,1,2; active=2
    m.set_active(0)
    m.set_split(2)  # pair 0 <-> 2

    m.duplicate(0)  # 在 idx 1 处插入副本，view 2 → 下标 3

    names_len = len(m.views)
    assert names_len == 4
    # 原 0 <-> 2 这对要跟着对象走，不能错位到副本上
    assert m.partner_for(0) == 3
    assert m.partner_for(3) == 0
    assert m.partner_for(1) is None  # 副本未配对
```

- [ ] **Step 4: 运行 ViewManager 测试**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_manager.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/view_state.py tests/ui/test_view_manager.py
git commit -m "feat(view): persist split pairs across view switches"
```

---

## Task 3: Bridge 拆分 controls 与 canvas ranges（pane-aware）

**Files:**

- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `mf4_analyzer/ui/view_bridge.py`
- Modify: `tests/ui/test_view_switch_integration.py`

- [ ] **Step 1: 添加 bridge ranges 测试**

在 `tests/ui/test_view_switch_integration.py` 追加：

```python
def test_bridge_can_capture_canvas_ranges_without_replacing_controls(
    qtbot, qapp, loaded_csv
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "speed")
    w.plot_time()
    qapp.processEvents()

    state = w.view_manager.get(0)
    state.checked = [(fid, "speed")]
    target = _narrow_xlim(w, 0.25, 0.50)
    ylims = _set_distinct_ylims(w, 0.15)

    w._view_bridge.capture_canvas_ranges_into(state, w.canvas_time)

    assert state.checked == [(fid, "speed")]
    assert state.xlim == pytest.approx(target)
    assert set(state.ylims) == set(ylims)
```

- [ ] **Step 2: 跑测试确认失败**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_switch_integration.py::test_bridge_can_capture_canvas_ranges_without_replacing_controls -q
```

Expected: FAIL with missing `capture_canvas_ranges_into`。

- [ ] **Step 3: 给 `chart_stack.py` 增加 canvas-keyed 读/写侧（修订说明 1）**

读侧已有 `plot_mode_for_canvas(canvas)` 与私有 `_cursor_mode_for_canvas(canvas)`；补一个公开读侧别名和两个写侧，复用已有的 `_silent` 写法，让 bridge 能把 plot_mode/cursor 写到目标 pane 而不是只写主栏：

```python
def cursor_mode_for_canvas(self, canvas):
    """Public read accessor mirroring plot_mode_for_canvas."""
    return self._cursor_mode_for_canvas(canvas)

def set_plot_mode_for_canvas(self, canvas, mode):
    if mode not in ("subplot", "overlay"):
        return
    if self._secondary_card is not None and canvas is self._secondary_card.canvas:
        self._set_secondary_plot_mode_silent(mode)
    else:
        self._primary_plot_mode = mode
        if not self._shared_time_controls_follow_secondary():
            self._set_shared_plot_mode_silent(mode)

def set_cursor_mode_for_canvas(self, canvas, mode):
    if mode not in ("off", "single", "dual"):
        return
    if self._secondary_card is not None and canvas is self._secondary_card.canvas:
        self._set_secondary_cursor_mode_silent(mode)
        target = self._secondary_card.canvas
    else:
        self._primary_cursor_mode = mode
        if not self._shared_time_controls_follow_secondary():
            self._set_shared_cursor_mode_silent(mode)
        target = self.canvas_time
    target.set_cursor_visible(mode != "off")
    target.set_dual_cursor_mode(mode == "dual")
```

这些 setter 走 `_silent` 系列、不发 `plot_mode_changed` / `cursor_mode_changed`，所以 apply 期间不会回灌 MainWindow 的 `_on_plot_mode_changed` / `_on_cursor_mode_changed`，避免 reentrancy。

- [ ] **Step 4: 修改 `view_bridge.py` 为 pane-aware（修订说明 1）**

`channel` / `colors` / `overlay_primary` / `axis_opts` 仍从全局控件采集（focused pane 已把它们投影到全局），但 `plot_mode` / `cursor_mode` 必须按目标 canvas 读写。capture/apply 都加可选 `canvas` 参数，默认主 canvas（非 split 路径行为不变）。

```python
def capture_controls_into(state: ViewState, window, canvas=None) -> None:
    fresh = capture_view(window)
    state.checked = fresh.checked
    state.colors = fresh.colors
    state.overlay_primary = fresh.overlay_primary
    state.axis_opts = fresh.axis_opts
    chart_stack = window.chart_stack
    target = canvas if canvas is not None else chart_stack.canvas_time
    state.plot_mode = chart_stack.plot_mode_for_canvas(target)
    state.cursor_mode = chart_stack.cursor_mode_for_canvas(target)


def capture_canvas_ranges_into(state: ViewState, canvas) -> None:
    get_xlim = getattr(canvas, "get_visible_xlim", None)
    get_ylims = getattr(canvas, "get_visible_ylims", None)
    if callable(get_xlim):
        state.xlim = get_xlim()
    if callable(get_ylims):
        state.ylims = get_ylims()


def apply_controls_from_state(state: ViewState, window, canvas=None) -> None:
    navigator = window.navigator
    chart_stack = window.chart_stack
    target = canvas if canvas is not None else chart_stack.canvas_time
    with _signals_blocked(navigator), _signals_blocked(chart_stack):
        navigator.set_channel_colors(state.colors)
        navigator.set_checked_channels(state.checked)
        chart_stack.set_plot_mode_for_canvas(target, state.plot_mode)
        chart_stack.set_cursor_mode_for_canvas(target, state.cursor_mode)
    window._overlay_primary = state.overlay_primary
    restore_axis_opts = getattr(window, "_restore_view_axis_opts", None)
    if callable(restore_axis_opts):
        restore_axis_opts(state.axis_opts)
```

`apply_controls_from_state` **不再走旧 `apply_view` 里的 `_sync_canvas_cursor_mode`**——那条会回调 `window._on_cursor_mode_changed`，在渲染非聚焦 pane 时把 partner 的游标模式写进 active view、并切换错的 canvas（修订说明 1 的 cursor 污染）。游标可见性改由 `set_cursor_mode_for_canvas` 在目标 canvas 上直接设。

Change existing `capture_into`（非 split 兼容路径，仍以主 canvas 为目标）:

```python
def capture_into(state: ViewState, window) -> None:
    capture_controls_into(state, window, window.chart_stack.canvas_time)
    capture_canvas_ranges_into(state, window.chart_stack.canvas_time)
```

旧 `apply_view`（line 80）保留作兼容，但新渲染路径一律走 `apply_controls_from_state`。

- [ ] **Step 5: 运行 bridge/view switch 测试**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_switch_integration.py tests/ui/test_split_routing.py -q
```

Expected: existing failures from new split semantics may remain until later tasks; bridge-specific new test should pass.

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/view_bridge.py tests/ui/test_view_switch_integration.py
git commit -m "feat(view): pane-aware control capture and canvas range capture"
```

---

## Task 4: MainWindow pane binding 与 state-based 渲染

**Files:**

- Modify: `mf4_analyzer/ui/main_window.py`

- [ ] **Step 1: 增加 pane binding 初始化**

In `MainWindow.__init__`, after view manager/chart stack setup:

```python
self._primary_view_idx = self.view_manager.active
self._secondary_view_idx = None
self._focused_view_idx = self.view_manager.active
```

- [ ] **Step 2: 添加 helper methods**

Add near the existing view methods:

```python
def _sync_pane_bindings_from_manager(self):
    active = self.view_manager.active
    partner = self.view_manager.split_with
    self._primary_view_idx = active
    self._secondary_view_idx = partner
    if partner is None:
        self._focused_view_idx = active
    elif self._focused_view_idx not in (active, partner):
        self._focused_view_idx = active


def _view_index_for_canvas(self, canvas):
    if canvas is self.canvas_time:
        return self._primary_view_idx
    secondary = self.chart_stack.secondary_canvas()
    if secondary is not None and canvas is secondary:
        return self._secondary_view_idx
    return None


def _canvas_for_view_index(self, idx):
    if idx == self._primary_view_idx:
        return self.canvas_time
    if idx == self._secondary_view_idx:
        return self.chart_stack.secondary_canvas()
    return None


def _capture_canvas_ranges_for_bound_view(self, canvas):
    if getattr(self, "_applying_view", False):
        return
    idx = self._view_index_for_canvas(canvas)
    if idx is None or not (0 <= idx < len(self.view_manager.views)):
        return
    self._view_bridge.capture_canvas_ranges_into(self.view_manager.get(idx), canvas)


def _capture_focused_view(self):
    idx = self._focused_view_idx
    if idx is None or not (0 <= idx < len(self.view_manager.views)):
        return
    # canvas 决定 plot_mode/cursor 从哪个 pane 读（修订说明 1）：focused 是
    # secondary 时必须读 secondary card，否则会把主栏 mode 当成它的 mode 存进去。
    canvas = self._canvas_for_view_index(idx) or self.canvas_time
    self._view_bridge.capture_controls_into(self.view_manager.get(idx), self, canvas)
    self._view_bridge.capture_canvas_ranges_into(self.view_manager.get(idx), canvas)


def _project_view_controls(self, idx):
    if idx is None or not (0 <= idx < len(self.view_manager.views)):
        return
    canvas = self._canvas_for_view_index(idx) or self.canvas_time
    old = getattr(self, "_applying_view", False)
    self._applying_view = True
    try:
        self._view_bridge.apply_controls_from_state(self.view_manager.get(idx), self, canvas)
    finally:
        self._applying_view = old
```

- [ ] **Step 3: 替换 `_capture_current_view` 调用语义**

Change `_capture_current_view()` to delegate to focused:

```python
def _capture_current_view(self):
    self._capture_focused_view()
```

- [ ] **Step 4: 添加 state-based render helper**

```python
def _render_view_to_canvas(self, idx, canvas, *, update_primary_ui):
    if canvas is None or not (0 <= idx < len(self.view_manager.views)):
        return
    state = self.view_manager.get(idx)
    restore_idx = self._focused_view_idx
    cursor_pill_snapshot = self.chart_stack.cursor_pill_snapshot()
    old_applying_view = getattr(self, "_applying_view", False)
    self._applying_view = True
    try:
        self._view_bridge.apply_controls_from_state(state, self, canvas)
        self._plot_time_on_canvas(canvas, update_primary_ui=update_primary_ui)
        canvas.restore_visible_xlim(state.xlim)
        canvas.restore_visible_ylims(state.ylims)
        tick_opts = (state.axis_opts or {}).get("tick_density") or {}
        canvas.set_tick_density(int(tick_opts.get("x", 10)), int(tick_opts.get("y", 6)))
    finally:
        self._applying_view = old_applying_view
        if restore_idx is not None:
            self._project_view_controls(restore_idx)
        self.chart_stack.restore_cursor_pill_snapshot(cursor_pill_snapshot)
```

Keep `_render_view_into` as a wrapper or replace its callers:

```python
def _render_view_into(self, state, canvas):
    idx = self.view_manager.views.index(state)
    self._render_view_to_canvas(idx, canvas, update_primary_ui=False)
```

- [ ] **Step 5: Update `_switch_view`, `_apply_active_view`, `_on_view_split`**

`_switch_view`:

```python
def _switch_view(self, idx):
    if idx == self.view_manager.active:
        return
    if not (0 <= idx < len(self.view_manager.views)):
        return
    self._capture_focused_view()
    self.view_manager.set_active(idx)
```

`_apply_active_view`:

```python
def _apply_active_view(self, idx):
    if not (0 <= idx < len(self.view_manager.views)):
        return
    self._sync_pane_bindings_from_manager()
    partner = self.view_manager.split_with
    if partner is None:
        self.chart_stack.exit_split()
    else:
        self.chart_stack.enter_split()
    self._render_view_to_canvas(idx, self.canvas_time, update_primary_ui=True)
    if partner is not None:
        self._render_view_to_canvas(
            partner,
            self.chart_stack.secondary_canvas(),
            update_primary_ui=False,
        )
    self._focused_view_idx = idx
    self._project_view_controls(idx)
```

`_on_view_split`:

```python
def _on_view_split(self, other_idx):
    self._capture_focused_view()
    self._sync_pane_bindings_from_manager()
    if other_idx is None:
        self.chart_stack.exit_split()
        self._secondary_view_idx = None
        self._focused_view_idx = self.view_manager.active
        self._render_view_to_canvas(self.view_manager.active, self.canvas_time, update_primary_ui=True)
        self._project_view_controls(self.view_manager.active)
        return
    self.chart_stack.enter_split()
    self._render_view_to_canvas(self.view_manager.active, self.canvas_time, update_primary_ui=True)
    self._render_view_to_canvas(other_idx, self.chart_stack.secondary_canvas(), update_primary_ui=False)
    self._focused_view_idx = self.view_manager.active
    self._project_view_controls(self._focused_view_idx)
```

- [ ] **Step 6: 运行红灯测试子集**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_routing.py::test_split_pair_persists_when_switching_between_paired_views \
  tests/ui/test_split_per_pane_controls.py::test_secondary_plot_mode_toggle_uses_secondary_view_state_not_active \
  -q
```

Expected: first test should pass or be closer; second may still fail until Task 5 focus/control routing.

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/main_window.py
git commit -m "feat(view): bind split panes to view states"
```

---

## Task 5: Focused pane controls routing

**Files:**

- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `mf4_analyzer/ui/chart_stack.py` only if focus signal lacks enough data

- [ ] **Step 1: Update focus handler**

Replace `_on_chart_focus_changed` body:

```python
def _on_chart_focus_changed(self, secondary_focused):
    if not self.chart_stack.split_active():
        return
    self._capture_focused_view()
    if secondary_focused:
        self._focused_view_idx = self._secondary_view_idx
        which = "对比"
    else:
        self._focused_view_idx = self._primary_view_idx
        which = "主"
    if self._focused_view_idx is not None:
        self._project_view_controls(self._focused_view_idx)
    self.view_tabbar.set_focused_side(secondary_focused)  # 状态片高亮当前编辑栏
    self.statusBar.showMessage(f"聚焦{which}视图：通道勾选将作用于此栏", 2000)
```

- [ ] **Step 2: Route channel changes to focused view state**

Update `_ch_changed()`:

```python
def _ch_changed(self):
    focused = self.chart_stack.focused_canvas()
    idx = self._view_index_for_canvas(focused)
    if idx is not None and 0 <= idx < len(self.view_manager.views):
        self._view_bridge.capture_controls_into(self.view_manager.get(idx), self)
    invalidate = getattr(focused, "invalidate_envelope_cache", None)
    if callable(invalidate):
        invalidate("selection changed")
    if self.files and self.chart_stack.current_mode() == "time":
        self._replot_canvas_for_view(idx, focused)
```

Add helper:

```python
def _replot_canvas_for_view(self, idx, canvas):
    if idx is None or canvas is None:
        return
    cur_xlim = self._safe_capture_xlim_for(canvas)
    try:
        self._render_view_to_canvas(
            idx,
            canvas,
            update_primary_ui=(canvas is self.canvas_time),
        )
    finally:
        if cur_xlim is not None:
            self._safe_restore_xlim_for(canvas, cur_xlim)
        self._capture_canvas_ranges_for_bound_view(canvas)
```

- [ ] **Step 3: Route plot mode changes to focused view**

Update `_on_plot_mode_changed`:

```python
def _on_plot_mode_changed(self, mode):
    if getattr(self, "_applying_view", False):
        return  # apply/render 期间用 _silent setter，不应再触发重绘（修订说明 1）
    canvas = self.chart_stack.focused_canvas()
    idx = self._view_index_for_canvas(canvas)
    if idx is not None and 0 <= idx < len(self.view_manager.views):
        self.view_manager.get(idx).plot_mode = mode
    self._replot_canvas_for_view(idx, canvas)
```

Update `_replot_secondary_preserving_xlim()` to use bound state:

```python
def _replot_secondary_preserving_xlim(self):
    canvas = self.chart_stack.secondary_canvas()
    idx = self._view_index_for_canvas(canvas)
    self._replot_canvas_for_view(idx, canvas)
```

- [ ] **Step 4: Route cursor changes to focused view**

Update `_on_cursor_mode_changed`:

```python
def _on_cursor_mode_changed(self, mode):
    if getattr(self, "_applying_view", False):
        return  # 防止 apply 期间的游标回灌污染 active view（修订说明 1）
    canvas = self.chart_stack.focused_canvas()
    idx = self._view_index_for_canvas(canvas)
    if idx is not None and 0 <= idx < len(self.view_manager.views):
        self.view_manager.get(idx).cursor_mode = mode
    canvas.set_cursor_visible(mode != "off")
    canvas.set_dual_cursor_mode(mode == "dual")
```

- [ ] **Step 5: 运行 focus/controls tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_focus_routing.py \
  tests/ui/test_split_per_pane_controls.py \
  -q
```

Expected: PASS after adjusting assertions that previously assumed controls did not project focused state.

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_split_focus_routing.py tests/ui/test_split_per_pane_controls.py
git commit -m "feat(view): route controls through focused split pane"
```

---

## Task 6: Canvas range signal and ViewState range sync

**Files:**

- Modify: `mf4_analyzer/ui/pg_canvases.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `tests/ui/test_pg_timedomain_canvas.py`
- Modify: `tests/ui/test_split_focus_routing.py`

- [ ] **Step 1: Add canvas signal test**

In `tests/ui/test_pg_timedomain_canvas.py`, add a focused test near range tests:

```python
def test_visible_range_changed_emits_on_restore_xlim(qtbot, qapp):
    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    canvas.resize(600, 360)
    canvas.show()
    canvas.plot_channels(_five_channel_rows()[:1], mode="subplot")
    qapp.processEvents()

    seen = []
    canvas.visible_range_changed.connect(lambda: seen.append(True))
    canvas.restore_visible_xlim((0.2, 0.6))
    qapp.processEvents()

    assert seen
```

- [ ] **Step 2: Add signal in `pg_canvases.py`**

In signal section:

```python
visible_range_changed = pyqtSignal()
```

Emit in `_emit_xrange_changed` after the existing `xrange_changed.emit(...)`:

```python
self.visible_range_changed.emit()
```

Emit after Y mutations:

```python
target.set_ylim(...)
self.visible_range_changed.emit()
```

Add emits in:

- `restore_visible_ylims`
- `_apply_overlay_y_drag_at`
- `_handle_wheel_dispatch` Y paths after successful `set_ylim`

Do not emit while no plot exists.

- [ ] **Step 3: Connect range signals for primary and secondary**

In `MainWindow`, replace one-off primary `xrange_changed` connection with helper:

```python
def _connect_canvas_range_signals(self, canvas):
    xrange_changed = getattr(canvas, "xrange_changed", None)
    if xrange_changed is not None:
        xrange_changed.connect(self._on_time_canvas_xrange_changed)
    visible_range_changed = getattr(canvas, "visible_range_changed", None)
    if visible_range_changed is not None:
        visible_range_changed.connect(
            lambda c=canvas: self._capture_canvas_ranges_for_bound_view(c)
        )
```

Call for primary during init:

```python
self._connect_canvas_range_signals(self.canvas_time)
```

When secondary is first created in `chart_stack.enter_split()`, MainWindow needs to connect it once. 因为修订 2 后「切到已合并 view」只走 `_apply_active_view`（不再经 `_on_view_split`），secondary card 可能首次在 `_apply_active_view` 里创建，所以 **每一处 `enter_split()` 之后都要调用**（`_apply_active_view` 与 `_on_view_split` 两处），紧接在 `enter_split()` 后、渲染 secondary 之前：

```python
self.chart_stack.enter_split()
self._ensure_secondary_range_signal_connected()
```

Helper:

```python
def _ensure_secondary_range_signal_connected(self):
    canvas = self.chart_stack.secondary_canvas()
    if canvas is None or getattr(canvas, "_view_range_connected", False):
        return
    self._connect_canvas_range_signals(canvas)
    canvas._view_range_connected = True
```

- [ ] **Step 4: Run range sync tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py::test_visible_range_changed_emits_on_restore_xlim \
  tests/ui/test_split_focus_routing.py::test_secondary_range_changes_write_back_to_original_view_state \
  -q
```

Expected: PASS.

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py mf4_analyzer/ui/main_window.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_split_focus_routing.py
git commit -m "feat(view): sync split pane ranges back to ViewState"
```

---

## Task 7: 取消合并 UI

**Files:**

- Modify: `mf4_analyzer/ui/view_tabbar.py`
- Modify: `mf4_analyzer/ui/main_window.py`
- Modify: `tests/ui/test_view_tabbar.py`

- [ ] **Step 1: Add ViewTabBar tests**

In `tests/ui/test_view_tabbar.py`, add:

```python
def test_split_status_chip_visible_for_active_pair(qtbot):
    manager = ViewManager()
    manager.new_view()
    manager.set_active(0)
    manager.set_split(1)

    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)
    bar.show()

    assert bar._split_chip.isVisible()
    assert "View 1" in bar._split_chip.text()
    assert "View 2" in bar._split_chip.text()


def test_clear_split_chip_emits_active_index(qtbot):
    manager = ViewManager()
    manager.new_view()
    manager.set_active(0)
    manager.set_split(1)
    bar = ViewTabBar(manager)
    qtbot.addWidget(bar)

    seen = []
    bar.clear_split_requested.connect(seen.append)
    qtbot.mouseClick(bar._split_clear, Qt.LeftButton)

    assert seen == [0]
```

- [ ] **Step 2: Add signals and chip widgets**

In `ViewTabBar`:

```python
clear_split_requested = pyqtSignal(int)
```

In `__init__`, after plus button（状态片放在 `layout.addStretch(1)` 之后，靠右贴边）:

```python
self._focused_is_secondary = False
self._split_chip = QLabel(self)
self._split_chip.setObjectName("viewSplitChip")
self._split_clear = QPushButton("×", self)
self._split_clear.setObjectName("viewSplitClear")
self._split_clear.setFixedSize(22, 22)
self._split_clear.clicked.connect(self._on_split_clear_clicked)
layout.addWidget(self._split_chip, 0)
layout.addWidget(self._split_clear, 0)
```

并在 `__init__` 末尾的信号连线处补上 **`split_changed`**（修订说明 4）——否则创建/取消合并时状态片不会刷新（旧连线只有 `views_changed` / `active_changed`）：

```python
manager.split_changed.connect(lambda _partner: self._update_split_chip())
```

Add:

```python
def _on_split_clear_clicked(self):
    self.clear_split_requested.emit(self._manager.active)

def set_focused_side(self, is_secondary):
    # MainWindow 在焦点 pane 切换时调用，让状态片加粗当前正在编辑的那一栏，
    # 呼应 spec §5.2「全局控件代表 focused pane」。
    self._focused_is_secondary = bool(is_secondary)
    self._update_split_chip()

def _update_split_chip(self):
    partner = self._manager.partner_for(self._manager.active)
    visible = partner is not None
    self._split_chip.setVisible(visible)
    self._split_clear.setVisible(visible)
    if not visible:
        self._focused_is_secondary = False
        return
    a = self._manager.get(self._manager.active).name  # primary（active）
    b = self._manager.get(partner).name               # secondary（partner）
    if self._focused_is_secondary:
        b = f"<b>{b}</b>"
    else:
        a = f"<b>{a}</b>"
    self._split_chip.setText(f"合并: {a} + {b}")
```

`QLabel` 默认按富文本渲染 `<b>`，无需额外设置。Call `_update_split_chip()` from `refresh()` and `_sync_active()`（active 变化会重置高亮到主栏，符合「切换后焦点默认回 primary」）。

- [ ] **Step 3: Update context menu**

In `_on_context_menu`：右键 view `idx` 的 partner 决定显示「取消合并」还是「与此 View 并排」。额外处理「active 已有合并、又对另一个 view 选并排会静默拆旧合并」的情况（功能点）：把菜单文案改成可见的「替换当前合并」，并在执行前确认。

```python
partner = self._manager.partner_for(idx)
active_partner = self._manager.partner_for(self._manager.active)
will_replace = (
    partner is None
    and idx != self._manager.active
    and active_partner is not None
    and active_partner != idx
)
if partner is not None:
    split_action = menu.addAction("取消合并")
elif will_replace:
    split_action = menu.addAction("与此 View 并排（替换当前合并）")
else:
    split_action = menu.addAction("与此 View 并排")
    split_action.setEnabled(idx != self._manager.active)
```

On chosen:

```python
elif chosen is split_action:
    if partner is not None:
        self.clear_split_requested.emit(idx)
    else:
        if will_replace:
            from PyQt5.QtWidgets import QMessageBox
            ans = QMessageBox.question(
                self, "替换合并",
                f"“{self._manager.get(self._manager.active).name}” 当前已与 "
                f"“{self._manager.get(active_partner).name}” 合并；改为与 "
                f"“{self._manager.get(idx).name}” 合并会解除原合并。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self.split_requested.emit(idx)
```

- [ ] **Step 4: Wire MainWindow**

In `MainWindow.__init__`:

```python
self.view_tabbar.clear_split_requested.connect(self._on_view_clear_split)
```

Add:

```python
def _on_view_clear_split(self, idx):
    self._capture_focused_view()
    self.view_manager.clear_split_for(idx)
```

- [ ] **Step 5: Run ViewTabBar tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_tabbar.py -q
```

Expected: PASS.

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/view_tabbar.py mf4_analyzer/ui/main_window.py tests/ui/test_view_tabbar.py
git commit -m "feat(view): add cancel split controls"
```

---

## Task 8: Update conflicting tests and run focused suite

**Files:**

- Modify tests touched by previous tasks only

- [ ] **Step 1: Find old split-exit expectations**

Run:

```bash
rg -n "switch.*exit|exit.*split|set_split\\(None\\)|split_active\\(\\) is False|clears_split|set_active.*split|切换.*并排" tests/ui
```

Expected: list old assumptions.

- [ ] **Step 2: Update only expectations contradicted by new spec**

Allowed changes:

- Tests that say switching between paired views exits split must assert persistent split.
- Tests that explicitly call `view_manager.set_split(None)` should remain valid as cancel/clear behavior.
- Tests for focus routing should still assert only focused pane changes.

- [ ] **Step 3: Run focused View suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_state.py \
  tests/ui/test_view_manager.py \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_split_routing.py \
  tests/ui/test_split_focus_routing.py \
  tests/ui/test_split_per_pane_controls.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Run pyqtgraph focused canvas suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_timedomain_canvas.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: whitespace check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 6: 提交**

```bash
git add tests/ui
git commit -m "test(view): align split tests with persistent pairing"
```

---

## Task 9: Live verification

**Files:**

- No source edits unless live verification reveals a regression.

- [ ] **Step 1: Launch app**

Run:

```bash
PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"
```

Expected: TraceLab opens.

- [ ] **Step 2: Manual scenario**

Use any small CSV/MF4 with at least two numeric channels:

1. View 1: select channel A, plot.
2. Create View 2: select channel B, plot.
3. On View 2, right-click View 1 and choose `与此 View 并排`.
4. Confirm primary pane shows channel B and secondary pane shows channel A.
5. Click secondary pane, switch 分屏/叠加.
6. Confirm secondary remains channel A and primary remains channel B.
7. Zoom/pan secondary.
8. Click View 1 tab; confirm View 1 keeps the zoom/pan from step 7.
9. Click View 2; confirm merge returns.
10. Cancel merge from context menu.
11. Recreate merge, cancel from tabbar chip `×`.

- [ ] **Step 3: Record result in final response**

Report:

- focused pytest commands run and passed
- whether live app verification passed
- any known residual risk

Do not claim live verification if only offscreen tests were run.

---

## Self-review checklist

- [ ] Spec requirement 1 covered by Task 2 and Task 4.
- [ ] Spec requirement 2 covered by Task 4.
- [ ] Spec requirement 3 covered by Task 5 and Task 6.
- [ ] Spec requirement 4 covered by Task 3（pane-aware bridge）+ Task 1 Step 4（plot_mode 持久化）+ Task 4/5.
- [ ] Spec requirement 5 covered by Task 7.
- [ ] Existing cursor pill preservation covered by keeping existing `tests/ui/test_split_routing.py` tests.
- [ ] 修订 1（plot_mode/cursor pane-aware）：Task 3 canvas-keyed 读写 + Task 1 Step 4 红灯测试。
- [ ] 修订 2（无双触发）：`set_active` 不发 `split_changed`（Task 2 Step 3）。
- [ ] 修订 3（duplicate pair 不错位）：`duplicate()` 套对象快照重排 + 单测（Task 2 Step 3）。
- [ ] 修订 4（状态片响应 split_changed）：`ViewTabBar` 连 `split_changed`（Task 7 Step 2）。
- [ ] 功能：再合并替换确认（Task 7 Step 3）；状态片高亮当前编辑栏（Task 7 Step 2 + Task 5 Step 1）。
- [ ] No task edits unrelated FFT/order/batch code.
- [ ] No placeholder strings remain in this plan.
