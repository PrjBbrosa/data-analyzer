# 时域合并改单向 + 工具栏双栏路由 + 顶部焦点线 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已合入的「时域多 View 持久合并」基础上，按用户实测反馈做三组调整：
1. **合并改单向**：在 View 2 上合并 View 1 后，**只有 View 2 显示「2 + 1」**，View 1 自己仍是单栏（切到 View 1 单栏、切回 View 2 恢复合并）。
2. **工具栏分类路由**：并排时 pan/缩放、前进/后退、存图、游标**不再需要先点某栏**——pan/缩放/游标两栏同时生效，前进/后退两栏各走各的历史，存图两栏拼一张；只有 home / 分叠 / 坐标config 作用于「聚焦栏」并弹一次瞬时提示。
3. **焦点提示改轻量**：聚焦栏只用**顶部一条 tab 色细线**标识（不包边框），且**导出图片不含这条线**。

**对应前序：** `docs/superpowers/plans/2026-06-06-timedomain-persistent-view-merge.md`（已合入，commit `5a4c22e1`）。
**交互预览：** `docs/superpowers/mockups/split-focus-indicator.html`（已经用户确认）。

**Tech Stack:** Python 3.12 · PyQt5 · pyqtgraph · pytest + pytest-qt。

---

## 设计依据（已和用户敲定）

| 操作 | 并排时行为 | 是否点栏 | 是否弹提示 |
| --- | --- | --- | --- |
| pan / 缩放 | 两栏同时武装，拖哪栏动哪栏 | 否 | 否 |
| 游标 | 两栏同时开/关 | 否 | 否 |
| 前进 / 后退 | 两栏各回退/前进**自己的**历史，空栈侧 no-op | 否 | 否 |
| 存图 / 复制图 | 两栏**拼成一张**导出 | 否 | 否 |
| home（复位） | 作用于**聚焦栏**（默认主栏） | 点栏切换目标 | 是（1.5s） |
| 分叠（分屏/叠加） | 作用于**聚焦栏** | 点栏切换目标 | 是（1.5s） |
| 坐标 config（应用） | 作用于**聚焦栏** | 点栏切换目标 | 是（1.5s） |

- **焦点提示**：聚焦栏顶部一条 3px、该栏 tab 色的细线；未聚焦栏无线。数据区**不做任何变暗/降饱和**。
- **导出排除**：单栏存图抓 `canvas` 像素，焦点线在 card 上、天然不含；两栏拼图也只拼 canvas 像素，不含线/边框。
- **提示频率**：仅 home/分叠/config，且**仅在并排时**弹；切焦点不弹；单栏模式一律不弹；不设任何常驻提示区。

---

## 0. 文件结构

**修改：**

- `mf4_analyzer/ui/view_state.py`：`_split_pairs` 改为**单向** host→source；`set_split` / `clear_split_for` / `_snapshot_pairs_by_object` / `_restore_pairs_by_object` 跟着改单向。
- `mf4_analyzer/ui/chart_stack.py`：`PgNavigationToolbar` 增加「广播到对端栏」的 pan/缩放/前进/后退；存图改两栏拼图；焦点线颜色按聚焦 view 设置。
- `mf4_analyzer/ui_kit/style.qss`：`#chartCard[focused="true"]` 由整框改为仅顶部线。
- `mf4_analyzer/ui/main_window.py`：home/分叠/config 的 toast；游标作用两栏；焦点线颜色注入；存图走两栏拼图入口。

**测试：**

- `tests/ui/test_view_manager.py`、`tests/ui/test_split_routing.py`、`tests/ui/test_split_focus_routing.py`、`tests/ui/test_split_per_pane_controls.py`
- `tests/ui/test_pg_timedomain_canvas.py`（toolbar 双栏 / 拼图）
- `tests/ui/test_view_tabbar.py`（chip 文案不变，回归）

---

## Task 1: 合并改单向（ViewManager）

**Files:** Modify `mf4_analyzer/ui/view_state.py`、`tests/ui/test_view_manager.py`

- [ ] **Step 1: 改写对称单测为单向，并加单向断言**

`tests/ui/test_view_manager.py` 里现有 `test_set_split_creates_symmetric_pair_and_active_partner` 断言的是对称（`partner_for(1)==0`），与新语义冲突，**改写**为：

```python
def test_set_split_is_directional_host_only(qtbot):
    m = make()
    m.new_view()
    m.set_active(0)

    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.set_split(1)            # 在 View0(host) 上合并 View1(source)

    assert blocker.args == [1]
    assert m.partner_for(0) == 1   # host 显示合并
    assert m.partner_for(1) is None  # source 仍单栏 ← 单向关键
    assert m.split_with == 1

    # 切到 source：单栏；切回 host：恢复合并
    split_events = []
    m.split_changed.connect(split_events.append)
    m.set_active(1)
    assert m.split_with is None
    m.set_active(0)
    assert m.split_with == 1
    # set_active 仍不得自发 split_changed（沿用前序修订 2）
    assert split_events == []
```

`test_clear_split_for_removes_pair_from_both_sides` 改名/改为单向（清 host 即解除）：

```python
def test_clear_split_for_host_removes_pair(qtbot):
    m = make(); m.new_view(); m.set_active(0); m.set_split(1)
    with qtbot.waitSignal(m.split_changed, timeout=100) as blocker:
        m.clear_split_for(0)
    assert blocker.args == [None]
    assert m.partner_for(0) is None
    assert m.split_with is None


def test_clear_split_for_source_also_unmerges_host(qtbot):
    # 取消 source 一侧时，指向它的 host 也要解除（防御）
    m = make(); m.new_view(); m.set_active(0); m.set_split(1)
    m.clear_split_for(1)
    assert m.partner_for(0) is None
```

`test_reorder_keeps_pair_with_view_objects` / `test_delete_*` / `test_duplicate_remaps_unrelated_pair_after_insert`：断言改为单向（只查 host→source 方向），其余结构不变。例如 duplicate：

```python
    assert m.partner_for(0) == 3   # host 跟着对象走
    assert m.partner_for(3) is None  # source 方向不存在（单向）
    assert m.partner_for(1) is None  # 副本未配对
```

- [ ] **Step 2: 跑测试确认红灯**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_manager.py -q
```

Expected: FAIL（现仍是对称实现）。

- [ ] **Step 3: 改 `view_state.py` 为单向**

```python
def set_split(self, idx: int | None) -> None:
    if idx is None:
        self.clear_split_for(self.active)
        return
    if idx == self.active or not self._is_valid_index(idx):
        return
    if self._split_pairs.get(self.active) == idx:
        return
    old_split = self.split_with
    self._split_pairs.pop(self.active, None)   # host 换 source：先清自己旧的
    self._split_pairs[self.active] = idx        # 单向：只写 host → source
    self._set_active_split_from_pairs()
    if self.split_with != old_split:
        self.split_changed.emit(self.split_with)

def clear_split_for(self, idx: int | None = None, *, emit: bool = True) -> None:
    target = self.active if idx is None else idx
    if not self._is_valid_index(target):
        return
    old_split = self.split_with
    self._split_pairs.pop(target, None)                 # target 作为 host
    for host, src in list(self._split_pairs.items()):    # target 作为某 host 的 source
        if src == target:
            self._split_pairs.pop(host, None)
    self._set_active_split_from_pairs()
    if emit and self.split_with != old_split:
        self.split_changed.emit(self.split_with)

def _snapshot_pairs_by_object(self):
    out = []
    for host, src in self._split_pairs.items():           # 单向，无需 dedup
        if self._is_valid_index(host) and self._is_valid_index(src):
            out.append((self.views[host], self.views[src]))  # 有序 host→source
    return out

def _restore_pairs_by_object(self, pairs):
    self._split_pairs = {}
    for host_state, src_state in pairs:
        h = self._index_of_state(host_state)
        s = self._index_of_state(src_state)
        if h >= 0 and s >= 0:
            self._split_pairs[h] = s                       # 仅写 host→source
    self._set_active_split_from_pairs()
```

`partner_for` / `has_split_pair` / `set_active` / `_index_of_state` 不变。`main_window._sync_pane_bindings_from_manager` 读 `split_with = partner_for(active)`，**无需改动**——单向语义自然产生「只有 host 分栏」。

- [ ] **Step 4: 跑绿**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_manager.py -q
```

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/view_state.py tests/ui/test_view_manager.py
git commit -m "feat(view): 合并改单向（仅 host 显示 2+1，source 仍单栏）"
```

---

## Task 2: 对齐 split 集成测试到单向语义

**Files:** Modify `tests/ui/test_split_routing.py`、`tests/ui/test_split_focus_routing.py`、`tests/ui/test_split_per_pane_controls.py`

- [ ] **Step 1: 改写「切到对端仍分栏」的断言**

`test_split_pair_persists_when_switching_between_paired_views`（test_split_routing.py）目前断言切到 View 1 仍分栏（对称）。改为单向语义：

```python
def test_directional_merge_only_host_splits(qtbot, qapp, loaded_csv):
    w, _fid, v1_xlim, v1_ylims, v2_xlim, v2_ylims = _make_speed_vs_torque_views(...)
    assert w.view_manager.active == 0          # host = View0(speed)
    w.view_manager.set_split(1)                 # source = View1(torque)
    qapp.processEvents()
    assert w.chart_stack.split_active() is True
    assert _has_channel(w.canvas_time, "speed")
    assert _has_channel(w.chart_stack.secondary_canvas(), "torque")

    # 切到 source(View1) → 单栏，只剩 torque
    w._switch_view(1); qapp.processEvents()
    assert w.chart_stack.split_active() is False
    assert _has_channel(w.canvas_time, "torque")

    # 切回 host(View0) → 恢复合并
    w._switch_view(0); qapp.processEvents()
    assert w.chart_stack.split_active() is True
    assert _has_channel(w.canvas_time, "speed")
    assert _has_channel(w.chart_stack.secondary_canvas(), "torque")
```

- [ ] **Step 2: 修正其余依赖「切到对端仍分栏」的用例**

`test_secondary_pane_keeps_its_own_plot_mode_across_switches`、`test_secondary_plot_mode_toggle_uses_secondary_view_state_not_active`、`test_secondary_range_changes_write_back_to_original_view_state` 等：凡是 `set_split` 后切到 **source** 再断言「分栏/副栏」的，改为「切到 source = 单栏；副栏相关断言只在 active=host 时做」。范围写回那条仍成立（切到 source 单栏会显示 source 自己被写回的 xlim）。

- [ ] **Step 3: 跑这几支测试转绿**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_routing.py tests/ui/test_split_focus_routing.py \
  tests/ui/test_split_per_pane_controls.py -q
```

- [ ] **Step 4: 提交**

```bash
git add tests/ui/test_split_routing.py tests/ui/test_split_focus_routing.py tests/ui/test_split_per_pane_controls.py
git commit -m "test(view): split 集成测试对齐单向合并语义"
```

---

## Task 3: pan / 缩放 / 前进 / 后退 作用两栏

**Files:** Modify `mf4_analyzer/ui/chart_stack.py`、`tests/ui/test_pg_timedomain_canvas.py`（或 split 测试）

并排时 pan/缩放要**两栏同时武装**（拖哪栏动哪栏），前进/后退**两栏各走各的历史**。当前 `_click_*` 经 `_focused_nav_delegate` 只作用聚焦栏（`chart_stack.py:782-798`）。

- [ ] **Step 1: 测试——并排时 pan 让两栏 view box 都进 PanMode / zoom 进 RectMode**

```python
def test_split_pan_zoom_arm_both_panes(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    w.view_manager.set_split(1); qapp.processEvents()
    import pyqtgraph as pg
    tb = w.chart_stack._time_toolbar
    tb._click_zoom()                       # 共享工具栏点缩放
    qapp.processEvents()
    for canvas in (w.canvas_time, w.chart_stack.secondary_canvas()):
        for ax in canvas.axes_list:
            vb = getattr(ax, "view_box", None)
            if vb is not None:
                assert vb.state['mouseMode'] == pg.ViewBox.RectMode
```

（具体读 mouseMode 的方式按 canvas 实际接口调整；要点是两栏都生效，无需先点某栏。）

- [ ] **Step 2: 给 `PgNavigationToolbar` 加「对端广播」**

```python
# __init__ 里
self._peer_toolbars_provider = None     # 返回需同步的对端工具栏列表

def _peers(self):
    provider = self._peer_toolbars_provider
    if provider is None:
        return []
    try:
        peers = provider() or []
    except Exception:
        return []
    return [t for t in peers if t is not None and t is not self]

def set_mouse_mode(self, mode):
    """设置 pan/zoom 模式并应用到本栏 view boxes，不切换、不再广播。"""
    self.mode = mode
    self.apply_current_mouse_mode()
```

`_click_*` 改为广播（pan/缩放/前进/后退**不再走 focused delegate**，固定本栏 + 对端）：

```python
def _click_pan(self, *_a):
    self.pan()
    for t in self._peers():
        t.set_mouse_mode(self.mode)

def _click_zoom(self, *_a):
    self.zoom()
    for t in self._peers():
        t.set_mouse_mode(self.mode)

def _click_back(self, *_a):
    self.back()
    for t in self._peers():
        t.back()

def _click_forward(self, *_a):
    self.forward()
    for t in self._peers():
        t.forward()
```

`_click_home` 保持走 `(self._delegate() or self).home()`（聚焦栏）。

- [ ] **Step 3: ChartStack 提供对端工具栏列表**

在 `enter_split()` 建好副栏后、`exit_split()` 时维护：

```python
self._time_toolbar._peer_toolbars_provider = (
    lambda: [self._secondary_card.toolbar]
    if (self.split_active() and self._secondary_card is not None) else []
)
```

（放在 `_time_toolbar` 创建处一次性设置即可，provider 内部按 `split_active()` 动态返回。）

- [ ] **Step 4: 跑绿 + 提交**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(view): 并排 pan/缩放/前进后退 作用两栏，免点栏"
```

---

## Task 4: 存图 / 复制图 两栏拼一张

**Files:** Modify `mf4_analyzer/ui/chart_stack.py`、`tests/ui/test_pg_timedomain_canvas.py`

`save_figure`（`chart_stack.py:742`）和 `_copy_card_image`（2135）现在抓单个 canvas。并排时改为**两栏 canvas 各 `_grab_pixmap_hidpi` 后左右拼一张**（只拼 canvas 像素，自动不含焦点线/边框）。

- [ ] **Step 1: 测试——并排存图产出的 pixmap 宽度≈两栏之和**

```python
def test_split_save_image_combines_both_panes(qtbot, qapp, loaded_csv, monkeypatch, tmp_path):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    w.view_manager.set_split(1); qapp.processEvents()
    out = tmp_path / "out.png"
    monkeypatch.setattr(
        "mf4_analyzer.ui.chart_stack.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out), "PNG (*.png)"),
    )
    w.chart_stack._time_toolbar._click_save()
    assert out.exists()
    from PyQt5.QtGui import QImage
    img = QImage(str(out))
    single = _grab_pixmap_hidpi(w.canvas_time)
    assert img.width() >= single.width() * 1.8   # 约两栏拼接
```

- [ ] **Step 2: 实现合并导出**

ChartStack 加：

```python
def _combined_split_pixmap(self):
    """把主/副两栏 canvas 像素左右拼成一张（含小间隔），不含任何 card chrome。"""
    left = _grab_pixmap_hidpi(self.canvas_time)
    right = _grab_pixmap_hidpi(self._secondary_card.canvas)
    if left is None or right is None:
        return None
    gap = 8
    out = QPixmap(left.width() + gap + right.width(), max(left.height(), right.height()))
    out.fill(Qt.white)
    p = QPainter(out)
    p.drawPixmap(0, 0, left)
    p.drawPixmap(left.width() + gap, 0, right)
    p.end()
    return out
```

`save_figure` / `_copy_card_image`（或新增 `_click_save` 的 ChartStack 入口）在 `split_active()` 时用 `_combined_split_pixmap()`，否则沿用单栏抓取。`_click_save` 走 ChartStack 提供的回调（类似已有 `set_secondary_replot_callback` 模式）或直接判断。

- [ ] **Step 3: 跑绿 + 提交**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(view): 并排存图/复制图两栏拼一张（不含焦点线）"
```

---

## Task 5: 焦点提示改顶部线 + 导出排除

**Files:** Modify `mf4_analyzer/ui_kit/style.qss`、`mf4_analyzer/ui/chart_stack.py`、`mf4_analyzer/ui/main_window.py`、`tests/ui/test_split_focus_routing.py`

- [ ] **Step 1: QSS 由整框改顶部线**

`style.qss:1118` `QWidget#chartCard[focused="true"]`：去掉四边 accent border，改为仅顶部线，例如：

```css
QWidget#chartCard[focused="true"] {
    border: 1px solid #e4e8ef;        /* 和未聚焦同一中性边，不做整框强调 */
    border-top: 3px solid #2d7ff9;    /* 占位色；实际由代码按聚焦 view 的 tab 色覆盖 */
}
```

- [ ] **Step 2: 焦点线颜色按聚焦 view 的 tab 色**

`_refresh_focus_borders`（`chart_stack.py:1736`）给聚焦 card 设置内联 `border-top` 颜色 = 聚焦 view 的 `tab_color`；未聚焦 card 清除。颜色由 MainWindow 在焦点/切 view 时注入（ChartStack 不直接知道 view 颜色）：

```python
# main_window：焦点或 active 变化后
color = self.view_manager.get(self._focused_view_idx).tab_color
self.chart_stack.set_focus_accent(color)     # ChartStack 写到聚焦 card 的 border-top
```

（若注入颜色的接线偏麻烦，退而求其次：QSS 固定一个中性 accent 色，不随 view 变——仍满足「顶部一条线」。实现时二选一，优先 tab 色。）

- [ ] **Step 3: 测试——聚焦只改顶部线、导出不含线**

- 属性层面：`set_focused_card(secondary)` 后，secondary card `property("focused")` 为 True、primary 为 False（沿用现有，保证未回退）。
- 导出排除：Task 4 的拼图测试已覆盖（抓 canvas 不含 card 顶部线）；单栏 `save_figure` 同理（抓 canvas）。再加一条：并排时 `_combined_split_pixmap()` 的左半区顶部行像素**不是** tab 色（即没把线拍进去）——或简化为「断言导出走的是 canvas grab 路径」。

- [ ] **Step 4: 跑绿 + 提交**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_split_focus_routing.py -q
git add mf4_analyzer/ui_kit/style.qss mf4_analyzer/ui/chart_stack.py mf4_analyzer/ui/main_window.py tests/ui/test_split_focus_routing.py
git commit -m "feat(view): 焦点提示改顶部细线，导出图不含"
```

---

## Task 6: home / 分叠 / 坐标config 瞬时提示

**Files:** Modify `mf4_analyzer/ui/main_window.py`、`tests/ui/test_split_focus_routing.py`

仅这三类、且**仅并排时**弹 1.5s toast；切焦点、pan/缩放/前进后退/存图/游标都不弹；单栏不弹。复用现有 `self.toast(msg, level)`（`main_window.py:248`）。

- [ ] **Step 1: 测试——分叠/home/config 并排时弹一次，其余不弹**

```python
def test_split_layout_change_shows_focused_pane_hint(qtbot, qapp, loaded_csv, monkeypatch):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    w.view_manager.set_split(1); qapp.processEvents()
    msgs = []
    monkeypatch.setattr(w, "toast", lambda msg, level='info': msgs.append(msg))
    w._on_plot_mode_changed("overlay")     # 分叠
    qapp.processEvents()
    assert msgs and "主栏" in msgs[-1]

def test_pan_does_not_toast(qtbot, qapp, loaded_csv, monkeypatch):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    w.view_manager.set_split(1); qapp.processEvents()
    msgs = []
    monkeypatch.setattr(w, "toast", lambda msg, level='info': msgs.append(msg))
    w.chart_stack._time_toolbar._click_pan(); qapp.processEvents()
    assert msgs == []

def test_layout_change_single_view_no_toast(qtbot, qapp, loaded_csv, monkeypatch):
    w = _make_loaded_window(...)            # 单栏
    msgs = []
    monkeypatch.setattr(w, "toast", lambda msg, level='info': msgs.append(msg))
    w._on_plot_mode_changed("overlay"); qapp.processEvents()
    assert msgs == []
```

- [ ] **Step 2: 在三个 handler 里加提示**

加一个小工具，只在并排时发：

```python
def _hint_focused_pane(self, action_label):
    if not self.chart_stack.split_active():
        return
    idx = self._focused_view_idx
    if idx is None or not (0 <= idx < len(self.view_manager.views)):
        return
    role = "主栏" if idx == self._primary_view_idx else "副栏"
    name = self.view_manager.get(idx).name
    self.toast(f"{action_label} 作用于 {role} · {name} · 点另一栏可改", "info")
```

- `_on_plot_mode_changed`：写完 `focused_state.plot_mode` 后 `self._hint_focused_pane("分叠")`。
- home：home 走 chart_stack 工具栏的 `_click_home`（聚焦栏）。在 MainWindow 侧接 home 后调用 `_hint_focused_pane("复位")`——若无现成 home 信号，给 `PgNavigationToolbar.home()` 发一个 `home_triggered` 信号或在 `_focused_nav_delegate` 路径回调 MainWindow。最小做法：ChartStack home 后 emit 一个信号，MainWindow 连上发 toast。
- `_apply_xaxis`（坐标 config 应用，`main_window.py`）：成功后把现有 `self.toast("横坐标已更新","success")` 换/补为 `self._hint_focused_pane("坐标设置")`（并排时；单栏保留原“横坐标已更新”即可）。

- [ ] **Step 3: 跑绿 + 提交**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_split_focus_routing.py -q
git add mf4_analyzer/ui/main_window.py mf4_analyzer/ui/chart_stack.py tests/ui/test_split_focus_routing.py
git commit -m "feat(view): home/分叠/坐标 仅并排时弹一次聚焦栏提示"
```

---

## Task 7: 游标作用两栏

**Files:** Modify `mf4_analyzer/ui/main_window.py`、`tests/ui/test_split_focus_routing.py`

并排时切游标模式**两栏同时**开/关（对比用），不弹提示。`_on_cursor_mode_changed`（`main_window.py`）现在只作用 focused canvas。

- [ ] **Step 1: 测试**

```python
def test_split_cursor_applies_to_both_panes(qtbot, qapp, loaded_csv):
    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    w.view_manager.set_split(1); qapp.processEvents()
    w._on_cursor_mode_changed("single"); qapp.processEvents()
    assert w.canvas_time.cursor_visible() is True
    assert w.chart_stack.secondary_canvas().cursor_visible() is True
    # 两个 view 的 cursor_mode 都写回
    assert w.view_manager.get(w._primary_view_idx).cursor_mode == "single"
    assert w.view_manager.get(w._secondary_view_idx).cursor_mode == "single"
```

（`cursor_visible()` 按 canvas 实际接口取；没有就读 dual/visible 内部状态。）

- [ ] **Step 2: 实现**

`_on_cursor_mode_changed`：并排时对主、副两个 canvas 都 `set_cursor_visible` / `set_dual_cursor_mode`，并把两个绑定 view 的 `cursor_mode` 都写为 `mode`；单栏沿用原逻辑（仅 focused）。保留前序的 `_applying_view` 守卫。

- [ ] **Step 3: 跑绿 + 提交**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_split_focus_routing.py -q
git add mf4_analyzer/ui/main_window.py tests/ui/test_split_focus_routing.py
git commit -m "feat(view): 并排游标两栏同时开关"
```

---

## Task 8: 全量回归 + 真机视觉验证

**Files:** 无源码改动（除非验证暴露回归）

- [ ] **Step 1: 全量 UI 套件**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui -q
```

Expected: PASS（注意前序 1002 基线，新增/改写后数目变化合理）。

- [ ] **Step 2: whitespace**

```bash
git diff --check
```

- [ ] **Step 3: 真机场景**（offscreen 盖不到，必须人工）

```bash
PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"
```

1. View 1 选 speed、View 2 选 torque；在 **View 2** 上右键 View 1「与此 View 并排」。
2. 确认 **View 2 = 主 torque + 副 speed**；切到 **View 1 = 单栏 speed**；切回 View 2 恢复合并。**（单向）**
3. 不点任何栏，直接按 **缩放**，分别拖主栏和副栏——两栏都能框选缩放。**（pan/缩放两栏）**
4. **前进/后退** 各自回退；**存图** 得到两栏拼一张、且图里**没有顶部焦点线**。
5. 聚焦栏只有**顶部一条线**（主栏橙/副栏蓝），点另一栏线随之移动；数据区不变暗。
6. 点 **分叠 / home / 坐标应用** 各弹一次 1.5s 提示「作用于 主栏/副栏…」；pan/缩放/前进后退/存图/切焦点都不弹；单栏模式不弹。
7. **游标** 一键两栏同时出现。

- [ ] **Step 4: 在最终回复记录**：跑过并通过的 pytest 命令、真机是否通过、残留风险。只跑 offscreen 不得声称做过真机验证。

---

## Self-review checklist

- [ ] 合并单向：host 显示 2+1、source 单栏、切回 host 恢复（Task 1/2）。
- [ ] `set_active` 仍不自发 `split_changed`（沿用前序修订 2，单测断言保留）。
- [ ] pan/缩放/前进后退两栏生效、免点栏（Task 3）；游标两栏（Task 7）。
- [ ] 存图两栏拼一张且不含焦点线（Task 4 + Task 5 导出排除）。
- [ ] 焦点=顶部线、非整框；颜色随聚焦 view tab 色（或中性 accent 退路）（Task 5）。
- [ ] 提示仅 home/分叠/config 且仅并排；切焦点/pan/缩放/前进后退/存图/游标不弹；单栏不弹（Task 6）。
- [ ] 无常驻提示区。
- [ ] 不动 FFT/阶次/批处理无关代码。
- [ ] 无占位字符串残留。
```
