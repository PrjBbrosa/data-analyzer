# 叠加模式·手动共轴组 + 通道缩进调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 叠加模式下，用户在通道树多选若干通道、右键「合并为共轴」，让这组通道画在同一根 Y 轴/同一量程上以可比幅值；并把通道树左侧浪费的缩进收窄、改造成共轴组徽标槽。

**Architecture:** 共轴分组是 `MultiFileChannelWidget` 的视图状态（`(fid,ch)->group_id` 字典），经 `_build_time_plot_data` 写进绘图行 `meta["axis_group"]`，再由 `TimeDomainCanvasPG.plot_channels` 的 overlay 分支按 group 归并——同组通道绑进同一个 aux ViewBox + 同一根 Y 轴（量程取并集自动缩放）。组色板 `axis_group_palette` 在「树徽标」与「共享轴」间共用，保证颜色一致。

**Tech Stack:** Python · PyQt5（QTreeWidget / `drawBranches`）· pyqtgraph（ViewBox / AxisItem）· pytest-qt。

## Global Constraints

- 仅在 **overlay** 模式生效；subplot/single 不受影响。
- 分组**不持久化存盘**（仅当前会话内有效）。
- 异单位也允许合并，共享轴标记「(混合单位)」。
- UI/渲染改动**必须真机截图验证**（CLAUDE.md 红线：别凭「属性设上了+单测过」判定修好；offscreen grab ≠ 真机）。
- 嵌入菜单/浮层的自定义 QWidget 必须透明背景（本特性沿用既有 `channelContextMenu` 设置，勿改坏）。
- 每次 `git commit` 末尾附仓库规范脚注：
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0119evXg8Z2CQ9p1pnNbLjAe
  ```
  下文 commit 步骤为简洁省略脚注正文，实际提交务必带上。
- 执行建议在**独立 git worktree（从 `main` 切）**进行：当前工作树有 codex 正在跑的 blf 改动，隔离以零接触它。

---

## File Structure

- `mf4_analyzer/ui/axis_group_palette.py` **(新建)** — 共轴组固定色板 + `axis_group_color(gid)`；树徽标与共享轴共用。
- `mf4_analyzer/ui/widgets/__init__.py` **(改)** — `_CheckTolerantTree` 多选/缩进/`drawBranches` 徽标；`MultiFileChannelWidget` 共轴组状态、信号、右键菜单、生命周期清理。
- `mf4_analyzer/ui/main_window/window.py` **(改)** — `_build_time_plot_data` 透传 `axis_group`；接线 `axis_groups_changed → 重绘`。
- `mf4_analyzer/ui/pg_canvas/canvas.py` **(改)** — overlay 分支按 group 归并 ViewBox/轴；解析 `axis_group` 进 `vis`。
- `mf4_analyzer/ui/pg_canvas/overlay_axes.py` **(改)** — `_bind_channel` 增加共享轴标签/颜色/跳过样式的参数。
- `tests/ui/test_channel_axis_groups.py` **(新建)** — 数据模型 + 菜单决策 + 缩进/色板。
- `tests/ui/test_overlay_shared_axis.py` **(新建)** — meta 透传回归 + 共享 ViewBox 归并。

---

## Task 1: 共轴组数据模型 + 多选 + 组色板

**Files:**
- Create: `mf4_analyzer/ui/axis_group_palette.py`
- Modify: `mf4_analyzer/ui/widgets/__init__.py`（imports；`MultiFileChannelWidget.__init__` ~207-267；`remove_file` ~448-480）
- Test: `tests/ui/test_channel_axis_groups.py`

**Interfaces:**
- Produces（供 Task 2/3/4 使用）:
  - `axis_group_palette.axis_group_color(group_id:int) -> str`（hex）
  - `MultiFileChannelWidget.axis_groups_changed`（`pyqtSignal()`）
  - `MultiFileChannelWidget.axis_group_for(fid:str, ch:str) -> int|None`
  - `MultiFileChannelWidget.merge_axis_group(keys:Iterable[(str,str)]) -> int|None`
  - `MultiFileChannelWidget.split_axis_group(keys:Iterable[(str,str)]) -> None`
  - `MultiFileChannelWidget.checked_axis_groups() -> dict[(str,str), int]`
  - `MultiFileChannelWidget._effective_groups(axis_groups:dict, checked_keys:set) -> dict`（staticmethod，纯函数）
  - `MultiFileChannelWidget._axis_group_menu_plan(sel_keys:list) -> (bool, bool)`（Task 2 用，但本任务一并加）

- [ ] **Step 1: 写失败测试**（`tests/ui/test_channel_axis_groups.py`）

```python
"""共轴组数据模型 + 组色板测试。"""
import pytest

from mf4_analyzer.ui.axis_group_palette import axis_group_color
from mf4_analyzer.ui.widgets import MultiFileChannelWidget


class TestAxisGroupPalette:
    def test_distinct_colors_for_first_groups(self):
        cols = [axis_group_color(g) for g in (1, 2, 3)]
        assert len(set(cols)) == 3

    def test_cycles_and_is_hex(self):
        assert axis_group_color(1) == axis_group_color(1 + 6)  # 6-color cycle
        assert axis_group_color(1).startswith("#")

    def test_nonpositive_falls_back_to_first(self):
        assert axis_group_color(0) == axis_group_color(1)


class TestAxisGroupModel:
    def test_merge_assigns_one_group(self, qapp):
        w = MultiFileChannelWidget()
        gid = w.merge_axis_group([("f1", "a"), ("f1", "b")])
        assert gid == 1
        assert w.axis_group_for("f1", "a") == 1
        assert w.axis_group_for("f1", "b") == 1

    def test_merge_below_two_is_noop(self, qapp):
        w = MultiFileChannelWidget()
        assert w.merge_axis_group([("f1", "a")]) is None
        assert w.axis_group_for("f1", "a") is None

    def test_second_merge_makes_new_group_id(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        gid2 = w.merge_axis_group([("f1", "c"), ("f1", "d")])
        assert gid2 == 2

    def test_merge_folds_into_min_existing_group(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])   # group 1
        w.merge_axis_group([("f1", "c"), ("f1", "d")])   # group 2
        # selecting members of group 1 and group 2 → fold all into 1
        w.merge_axis_group([("f1", "b"), ("f1", "c")])
        for ch in ("a", "b", "c", "d"):
            assert w.axis_group_for("f1", ch) == 1

    def test_split_removes_and_dissolves_singleton(self, qapp):
        w = MultiFileChannelWidget()
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        w.split_axis_group([("f1", "a")])
        # b left alone → group of one → auto-dissolved
        assert w.axis_group_for("f1", "a") is None
        assert w.axis_group_for("f1", "b") is None

    def test_merge_emits_signal(self, qapp):
        w = MultiFileChannelWidget()
        seen = []
        w.axis_groups_changed.connect(lambda: seen.append(1))
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        assert seen == [1]

    def test_effective_groups_drops_unchecked_and_singletons(self):
        groups = {("f1", "a"): 1, ("f1", "b"): 1, ("f1", "c"): 2, ("f1", "d"): 2}
        checked = {("f1", "a"), ("f1", "b"), ("f1", "c")}  # d unchecked
        eff = MultiFileChannelWidget._effective_groups(groups, checked)
        assert eff == {("f1", "a"): 1, ("f1", "b"): 1}  # group2 lost a member → singleton dropped

    def test_menu_plan(self, qapp):
        w = MultiFileChannelWidget()
        assert w._axis_group_menu_plan([("f1", "a")]) == (False, False)
        assert w._axis_group_menu_plan([("f1", "a"), ("f1", "b")]) == (True, False)
        w.merge_axis_group([("f1", "a"), ("f1", "b")])
        assert w._axis_group_menu_plan([("f1", "a"), ("f1", "b")]) == (True, True)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/ui/test_channel_axis_groups.py -q`
Expected: FAIL（`ModuleNotFoundError: axis_group_palette` / `AttributeError: merge_axis_group`）

- [ ] **Step 3: 建色板模块** `mf4_analyzer/ui/axis_group_palette.py`

```python
"""叠加共轴组的固定色板。

由通道树（组徽标）与 overlay 绘图（共享轴画笔）共用，使某组在树里的徽标色与
图上的共享轴色一致。
"""

_AXIS_GROUP_COLORS = (
    "#f97316",  # orange
    "#0ea5e9",  # sky
    "#a855f7",  # violet
    "#10b981",  # emerald
    "#ef4444",  # red
    "#eab308",  # amber
)


def axis_group_color(group_id):
    """返回 ``group_id``（1 基）对应的组色，循环使用。非正数回退首色。"""
    if not group_id or int(group_id) < 1:
        return _AXIS_GROUP_COLORS[0]
    return _AXIS_GROUP_COLORS[(int(group_id) - 1) % len(_AXIS_GROUP_COLORS)]
```

- [ ] **Step 4: 改 widgets imports**（`mf4_analyzer/ui/widgets/__init__.py` 顶部）

在 `from PyQt5.QtWidgets import (...)` 块加入 `QAbstractItemView`（按字母序插在 `QFrame` 前），并在文件顶部 import 区加：

```python
from collections import Counter

from ..axis_group_palette import axis_group_color
```

- [ ] **Step 5: 加状态 + 多选**（`MultiFileChannelWidget`）

在类体信号区（`channels_changed = pyqtSignal()` 附近，~198）加：

```python
    # Emitted when overlay shared-axis groups change (merge/split).
    axis_groups_changed = pyqtSignal()
```

在 `__init__` 创建 `self.tree` 之后、`layout.addWidget(self.tree)` 之前（~244-260 区间）加：

```python
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree._owner = self  # _CheckTolerantTree.drawBranches reads group state
        self.tree.setIndentation(16)  # 收窄默认~20；并复用为共轴徽标槽（Task 3）
```

在 `__init__` 末尾的状态初始化区（`self._raster_items = {}` 之后，~267）加：

```python
        self._axis_groups = {}      # (fid, ch) -> group_id:int
        self._axis_group_seq = 0
        self.axis_groups_changed.connect(self.tree.viewport().update)
```

- [ ] **Step 6: 加数据模型方法**（放在 `get_checked_channels` 之后，~495）

```python
    # ---- overlay shared-axis groups -------------------------------------
    def axis_group_for(self, fid, ch):
        return self._axis_groups.get((str(fid), str(ch)))

    def _new_axis_group_id(self):
        self._axis_group_seq += 1
        return self._axis_group_seq

    def merge_axis_group(self, keys):
        """Put ``keys`` (iterable of (fid, ch)) on one shared axis.

        If any key already belongs to a group, fold everything into the
        smallest such group id; else allocate a fresh id. Returns the group
        id, or None when fewer than 2 keys are given."""
        keys = [(str(f), str(c)) for (f, c) in keys]
        if len(keys) < 2:
            return None
        existing = sorted({self._axis_groups[k] for k in keys if k in self._axis_groups})
        gid = existing[0] if existing else self._new_axis_group_id()
        fold = set(existing[1:])
        if fold:
            for k, g in list(self._axis_groups.items()):
                if g in fold:
                    self._axis_groups[k] = gid
        for k in keys:
            self._axis_groups[k] = gid
        self._prune_axis_groups()
        self.axis_groups_changed.emit()
        return gid

    def split_axis_group(self, keys):
        """Remove ``keys`` from their groups; dissolve any group left < 2."""
        changed = False
        for (f, c) in keys:
            k = (str(f), str(c))
            if k in self._axis_groups:
                del self._axis_groups[k]
                changed = True
        if changed:
            self._prune_axis_groups()
            self.axis_groups_changed.emit()

    def _prune_axis_groups(self):
        counts = Counter(self._axis_groups.values())
        for k, g in list(self._axis_groups.items()):
            if counts[g] < 2:
                del self._axis_groups[k]

    @staticmethod
    def _effective_groups(axis_groups, checked_keys):
        """Restrict groups to checked channels and drop singleton groups."""
        eff = {k: g for k, g in axis_groups.items() if k in checked_keys}
        counts = Counter(eff.values())
        return {k: g for k, g in eff.items() if counts[g] >= 2}

    def checked_axis_groups(self):
        checked = {(f, c) for (f, c, _color) in self.get_checked_channels()}
        return self._effective_groups(self._axis_groups, checked)

    def _axis_group_menu_plan(self, sel_keys):
        """(can_merge, can_split) for the right-click menu (Task 2)."""
        sel = [(str(f), str(c)) for (f, c) in sel_keys]
        can_merge = len(sel) >= 2
        can_split = any(k in self._axis_groups for k in sel)
        return can_merge, can_split
```

- [ ] **Step 7: 生命周期清理**（`remove_file`，在删除 `self._colors` 那段之后，~451）

```python
        for k in [k for k in self._axis_groups if k[0] == fid]:
            del self._axis_groups[k]
        self._prune_axis_groups()
```

- [ ] **Step 8: 运行确认通过**

Run: `pytest tests/ui/test_channel_axis_groups.py -q`
Expected: PASS（全部）

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/ui/axis_group_palette.py mf4_analyzer/ui/widgets/__init__.py tests/ui/test_channel_axis_groups.py
git commit -m "feat(ui): 共轴组数据模型+通道树多选+组色板"
```

---

## Task 2: 右键菜单 合并/拆分共轴组

**Files:**
- Modify: `mf4_analyzer/ui/widgets/__init__.py`（`_on_context_menu` ~423-446）
- Test: `tests/ui/test_channel_axis_groups.py`（追加；菜单决策已在 Task 1 测了 `_axis_group_menu_plan`，此处测「选中→合并」联动）

**Interfaces:**
- Consumes: `merge_axis_group` / `split_axis_group` / `_axis_group_menu_plan`（Task 1）。
- Produces: 扩展后的 `_on_context_menu` 在多选≥2 时提供「合并为共轴」，选中含已分组项时提供「拆分共轴组」。

- [ ] **Step 1: 写失败测试**（追加到 `TestAxisGroupModel`，模拟「右键收集选中键 → 合并」的纯逻辑路径）

```python
    def test_collect_selected_channel_keys_then_merge(self, qapp):
        # 直接驱动数据模型，模拟 _on_context_menu 收集到的 sel_keys → 合并
        w = MultiFileChannelWidget()
        sel_keys = [("f1", "a"), ("f1", "b"), ("f1", "c")]
        can_merge, can_split = w._axis_group_menu_plan(sel_keys)
        assert (can_merge, can_split) == (True, False)
        w.merge_axis_group(sel_keys)
        assert {w.axis_group_for("f1", c) for c in ("a", "b", "c")} == {1}
        # 再对其中一个拆分
        can_merge, can_split = w._axis_group_menu_plan([("f1", "a")])
        assert can_split is True
        w.split_axis_group([("f1", "a")])
        assert w.axis_group_for("f1", "a") is None
```

- [ ] **Step 2: 运行确认失败/通过基线**

Run: `pytest tests/ui/test_channel_axis_groups.py -q`
Expected: 该用例 PASS（逻辑已由 Task 1 实现）——若 FAIL 说明 Task 1 有缺漏，先修。本步用于锁基线；菜单 UI 联动在真机（Task 6）验。

- [ ] **Step 3: 扩展 `_on_context_menu`**（整体替换 ~423-446）

```python
    def _on_context_menu(self, pos):
        """Right-click menu on a channel row: 设为左轴，以及（多选时）合并/拆分
        共轴组。文件行与空白处忽略。"""
        item = self.tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] != 'channel':
            return
        _kind, fid, ch = data
        # 收集当前 Ctrl/Shift 多选中的通道键；若右键的行不在选区内，则只针对该行。
        sel_keys = []
        for it in self.tree.selectedItems():
            d = it.data(0, Qt.UserRole)
            if d and d[0] == 'channel':
                sel_keys.append((d[1], d[2]))
        if (fid, ch) not in sel_keys:
            sel_keys = [(fid, ch)]
        can_merge, can_split = self._axis_group_menu_plan(sel_keys)

        self.channel_context_menu_requested.emit()
        menu = QMenu(self.tree)
        menu.setObjectName("channelContextMenu")
        menu.setWindowFlags(
            menu.windowFlags()
            | Qt.FramelessWindowHint
            | Qt.NoDropShadowWindowHint
        )
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        act_primary = menu.addAction("设为左轴")
        act_merge = menu.addAction("合并为共轴") if can_merge else None
        act_split = menu.addAction("拆分共轴组") if can_split else None
        chosen = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_primary:
            self.primary_channel_requested.emit(fid, ch)
        elif act_merge is not None and chosen is act_merge:
            self.merge_axis_group(sel_keys)
        elif act_split is not None and chosen is act_split:
            self.split_axis_group(sel_keys)
```

- [ ] **Step 4: 运行确认通过 + 无回归**

Run: `pytest tests/ui/test_channel_axis_groups.py tests/ui/test_side_panel_widgets.py -q`
Expected: PASS（含既有侧栏控件用例，确认菜单改动未破坏既有「设为左轴」路径）

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/widgets/__init__.py tests/ui/test_channel_axis_groups.py
git commit -m "feat(ui): 通道树右键 合并/拆分共轴组"
```

---

## Task 3: 通道缩进收窄 + drawBranches 组徽标

**Files:**
- Modify: `mf4_analyzer/ui/widgets/__init__.py`（`_CheckTolerantTree` ~91-194：`__init__` 加 `_owner`、新增 `drawBranches` + `_paint_group_badge`）
- Test: `tests/ui/test_channel_axis_groups.py`（追加缩进/无崩溃用例）

**Interfaces:**
- Consumes: `axis_group_color`（Task 1）、`_owner.axis_group_for`（Task 1）。
- Produces: 通道行在勾选框左侧的缩进槽里画组徽标（组色方块 + 组号）；文件行保留默认展开箭头。

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestChannelTreeIndent:
    def test_indentation_is_narrowed(self, qapp):
        w = MultiFileChannelWidget()
        assert w.tree.indentation() == 16

    def test_owner_back_reference_set(self, qapp):
        w = MultiFileChannelWidget()
        assert w.tree._owner is w

    def test_drawbranches_smoke_renders_to_pixmap(self, qapp):
        # 兜底冒烟：分组状态下 grab() 不抛异常（真实观感在 Task 6 真机验）
        from PyQt5.QtCore import QCoreApplication
        w = MultiFileChannelWidget()
        w.resize(260, 300)
        w.show()
        QCoreApplication.processEvents()
        w._axis_groups[("f1", "a")] = 1  # 直接置状态绕过 add_file
        w.tree.viewport().update()
        QCoreApplication.processEvents()
        pm = w.grab()
        assert not pm.isNull()
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/ui/test_channel_axis_groups.py::TestChannelTreeIndent -q`
Expected: FAIL（`indentation()` 仍是默认值；`_owner` 不存在）

- [ ] **Step 3: `_CheckTolerantTree.__init__` 加 `_owner`**（~105-107）

```python
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._consume_check_release = False
        self._owner = None  # set by MultiFileChannelWidget; drawBranches reads it
```

- [ ] **Step 4: 新增 `drawBranches` + 徽标绘制**（加在 `_CheckTolerantTree` 内，`mouseDoubleClickEvent` 之后 ~194）

```python
    def drawBranches(self, painter, rect, index):
        item = self.itemFromIndex(index)
        data = item.data(0, Qt.UserRole) if item is not None else None
        # 文件/源/采样率行：保留默认展开箭头。
        super().drawBranches(painter, rect, index)
        if not (data and data[0] == 'channel'):
            return
        owner = self._owner
        if owner is None:
            return
        gid = owner.axis_group_for(data[1], data[2])
        if not gid:
            return
        self._paint_group_badge(painter, rect, gid)

    def _paint_group_badge(self, painter, rect, gid):
        """在缩进槽右端（紧贴勾选框前）画组徽标：组色圆角方块 + 白色组号。
        画在 rect 右端，与树深度无关，规避多层缩进导致的错位。"""
        side = 12
        x = rect.right() - side - 2
        y = rect.top() + (rect.height() - side) // 2
        badge = QRect(x, y, side, side)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(axis_group_color(gid))))
        painter.drawRoundedRect(badge, 3, 3)
        painter.setPen(QPen(QColor('#ffffff')))
        f = painter.font()
        f.setPointSizeF(7.5)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(badge, Qt.AlignCenter, str(gid))
        painter.restore()
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/ui/test_channel_axis_groups.py -q`
Expected: PASS

- [ ] **Step 6: 真机渲染验证（CLAUDE.md 红线）**

启动 GUI，加载任意含 ≥3 通道的文件，勾选并多选 2 个同单位通道 → 右键「合并为共轴」。截图确认：
1. 子通道缩进比改前明显收窄（原红框空白区基本消除）。
2. 已分组通道在勾选框**左侧**出现组色小方块 + 组号，不与勾选框/色点/文字重叠。
3. 不同组徽标颜色不同。

若 16px 槽过窄/过宽，微调 `setIndentation(N)` 后重新截图。把截图留档。
（macOS 原生渲染：offscreen `grab()` ≠ 真机，必须真机截图。）

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/widgets/__init__.py tests/ui/test_channel_axis_groups.py
git commit -m "feat(ui): 通道树缩进收窄+drawBranches 共轴组徽标"
```

---

## Task 4: meta 透传 axis_group + canvas 解析 + companion 回归守卫

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py`（`_build_time_plot_data` ~1952-1995；接线 ~399）
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（`plot_channels` 行解析 ~470-505；subplot 解包 ~535；single 解包 ~640）
- Test: `tests/ui/test_overlay_shared_axis.py`（新建）

**Interfaces:**
- Consumes: `MultiFileChannelWidget.checked_axis_groups()`（Task 1）。
- Produces: 绘图行对分组通道带 `meta={"axis_group": gid}`；`plot_channels` 把 `axis_group` 透传进 `vis` 元组第 8 位（`(name, t, sig, color, unit, data_id, p_visible, axis_group)`），供 Task 5 消费。**本任务不改变 overlay 渲染**（axis_group 暂被忽略，分组通道仍各自独立轴）——纯数据贯通 + 回归守卫。

**关键事实（读真码确认）:** `canvas.py:483` 的 companion 分流**已经**按 `meta.get("companion_of")` 精确匹配，并非「meta 是否存在」。所以给 primary 加 `axis_group` meta **不会**被误判为 companion——spec 里的「修分流判据」其实无需修；本任务仅加回归测试锁住该行为。

- [ ] **Step 1: 写失败测试**（`tests/ui/test_overlay_shared_axis.py`）

```python
"""overlay 共轴：meta 透传回归 + 共享 ViewBox 归并。"""
import numpy as np
from PyQt5.QtCore import QCoreApplication


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


class TestAxisGroupMetaIsPrimary:
    def test_primary_with_axis_group_meta_not_swallowed_as_companion(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 7}),
            ("b", True, t, np.cos(t), "#0a0", "rpm", "f2"),  # 7-tuple, ungrouped
        ]
        canvas.plot_channels(rows, mode="overlay")
        # 两个 primary（gid=7 单成员仍是独立 slot），都建轴 → 2 根轴
        assert len(canvas.axes_list) == 2

    def test_companion_still_separated_when_axis_group_present(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#00f", "Nm", "f2", {"axis_group": 2}),
            ("a (LP)", True, t, np.sin(t) * 0.5, "#f00", "Nm", "f1",
             {"companion_of": "a", "dash": True}),
        ]
        canvas.plot_channels(rows, mode="overlay")
        # 2 个 primary（gid 1/2 各单成员）→ 2 轴；companion 不另起轴
        assert len(canvas.axes_list) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/ui/test_overlay_shared_axis.py::TestAxisGroupMetaIsPrimary -q`
Expected: FAIL —— `vis` 解析仍是 7 元组，给 8 元组 `axis_group` 行会在 overlay 分支的 `for ... in enumerate(vis[1:])` 处 `ValueError: not enough values to unpack`（或 axis_group 未被解析）。

- [ ] **Step 3: canvas 解析 axis_group**（`canvas.py` ~470-505）

在行解析循环里，把 `meta` 提取后加 `axis_group`，并把它带进 `primaries`：

将（~474-495）：
```python
        for row in ch_list:
            if len(row) >= 8 and isinstance(row[7], dict):
                name, visible, t, sig, color, unit, data_id, meta = row[:8]
            elif len(row) >= 7:
                name, visible, t, sig, color, unit, data_id = row[:7]
                meta = None
            else:
                name, visible, t, sig, color, unit = row[:6]
                data_id = None
                meta = None
            companion_of = meta.get("companion_of") if meta else None
            if companion_of is not None:
                ...
                continue
            primaries.append(
                (name, bool(visible), t, sig, color, unit, data_id)
            )
```
改为在 `primaries.append` 处带上 axis_group：
```python
            axis_group = meta.get("axis_group") if meta else None
            primaries.append(
                (name, bool(visible), t, sig, color, unit, data_id, axis_group)
            )
```
（`axis_group = ...` 这行放在 `companion_of` 判断之后、`primaries.append` 之前。）

- [ ] **Step 4: `vis` 透传 axis_group**（`canvas.py` ~501-505）

```python
        vis = [
            (name, t, sig, color, unit, data_id, p_visible, axis_group)
            for (name, p_visible, t, sig, color, unit, data_id, axis_group) in primaries
            if p_visible or companion_visible_by_source.get(name)
        ]
```

- [ ] **Step 5: 修 subplot/single 解包为 8 元组**（axis_group 在这两支忽略）

`canvas.py` ~535（subplot）：
```python
            for i, (name, t, sig, color, unit, data_id, p_visible, _axis_group) in enumerate(vis):
```
`canvas.py` ~640（single）：
```python
            name, t, sig, color, unit, data_id, p_visible, _axis_group = vis[0]
```
（overlay 分支 ~603 的 `for idx, (name, t, sig, color, unit, data_id, p_visible) in enumerate(vis[1:], start=1)` 与 ~597 的 `*vis[0][:6]` 将在 Task 5 整体重写，本任务暂保持其能跑——把 ~603 也临时改成 8 元组解包 `..., p_visible, _axis_group)`，避免本任务中途 overlay 崩溃。）

- [ ] **Step 6: 运行确认通过**

Run: `pytest tests/ui/test_overlay_shared_axis.py::TestAxisGroupMetaIsPrimary tests/ui/test_pg_timedomain_canvas.py tests/ui/test_time_filter_overlay.py -q`
Expected: PASS（含既有 overlay/subplot 与滤波叠加用例，确认 8 元组改造零回归）

- [ ] **Step 7: window.py 透传 axis_group**（`_build_time_plot_data`）

在循环前（~1952 `data = []` 之前）加：
```python
        eff_groups = self.channel_list.checked_axis_groups()
```
把主行 append（~1974）：
```python
            data.append((name, show_orig, x_axis, sig, color, unit, fid))
```
改为：
```python
            gid = eff_groups.get((fid, ch))
            if gid is not None:
                data.append((name, show_orig, x_axis, sig, color, unit, fid,
                             {"axis_group": gid}))
            else:
                data.append((name, show_orig, x_axis, sig, color, unit, fid))
```

- [ ] **Step 8: 接线 axis_groups_changed → 重绘**（`window.py` ~399 后）

```python
        self.channel_list.axis_groups_changed.connect(self._ch_changed)
```

- [ ] **Step 9: 运行确认通过 + 全量冒烟**

Run: `pytest tests/ui/test_overlay_shared_axis.py -q && pytest -q`
Expected: PASS（默认 `-m "not slow"`）

- [ ] **Step 10: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/main_window/window.py tests/ui/test_overlay_shared_axis.py
git commit -m "feat(canvas): 贯通 axis_group(meta→vis)+接线重绘，companion 分流回归守卫"
```

---

## Task 5: overlay 共享 ViewBox/轴 归并

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（overlay 分支 ~573-634）
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`（`_bind_channel` ~292-365）
- Test: `tests/ui/test_overlay_shared_axis.py`（追加）

**Interfaces:**
- Consumes: `vis` 元组第 8 位 `axis_group`（Task 4）、`axis_group_color`（Task 1）。
- Produces: 同 `axis_group` 的通道绑进**同一 aux ViewBox + 同一根 Y 轴**；`_bind_channel` 新增关键字参 `axis_label=None, axis_color=None, update_axis_style=True`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/ui/test_overlay_shared_axis.py`）

```python
class TestOverlaySharedViewBox:
    def test_group_members_share_one_viewbox_and_axis(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t),     "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t),     "#0a0", "Nm",  "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(2 * t), "#00f", "rpm", "f2"),  # ungrouped
        ]
        canvas.plot_channels(rows, mode="overlay")
        # a,b 塌成一个 slot；c 自己一个 → 共 2 根轴
        assert len(canvas.axes_list) == 2
        # 第 0 个 slot（组 1）的 ViewBox 同时持有 a、b 两条曲线
        shared_vb = canvas.axes_list[0].view_box
        assert shared_vb is not None
        assert len(shared_vb.addedItems) == 2
        # c 自己的 ViewBox 只有一条
        solo_vb = canvas.axes_list[1].view_box
        assert len(solo_vb.addedItems) == 1

    def test_shared_axis_union_range_covers_both(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.full_like(t, 1.0),  "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.full_like(t, 50.0), "#0a0", "Nm", "f1", {"axis_group": 1}),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        lo, hi = canvas.axes_list[0].get_ylim()
        # 并集量程必须同时覆盖 1 与 50（独立轴时各自只覆盖自己）
        assert lo <= 1.0 + 1e-6 and hi >= 50.0 - 1e-6
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/ui/test_overlay_shared_axis.py::TestOverlaySharedViewBox -q`
Expected: FAIL（当前每通道各自 ViewBox → `axes_list` 长度 3、shared_vb 只有 1 条曲线）

- [ ] **Step 3: `_bind_channel` 增加共享轴参数**（`overlay_axes.py`）

签名（~292-295）改为：
```python
    def _bind_channel(
        self, axis_handle, name, t, sig, color, unit, data_id,
        *, xlabel=None, skip_envelope=False,
        axis_label=None, axis_color=None, update_axis_style=True,
    ):
```
把轴标签/样式段（~348-359）：
```python
        try:
            if self._overlay_mode:
                label = self._overlay_axis_label(axis_handle, name, unit)
            else:
                label = _subplot_ylabel_text(name, unit)
            axis_handle.set_ylabel(label)
            _apply_pg_axis_font(axis_handle.y_axis_item())
        except Exception:
            pass
        if self._overlay_mode:
            self._configure_overlay_axis_geometry(axis_handle)
        self._apply_pg_axis_style(axis_handle, color)
```
改为：
```python
        if update_axis_style:
            try:
                if axis_label is not None:
                    label = axis_label
                elif self._overlay_mode:
                    label = self._overlay_axis_label(axis_handle, name, unit)
                else:
                    label = _subplot_ylabel_text(name, unit)
                axis_handle.set_ylabel(label)
                _apply_pg_axis_font(axis_handle.y_axis_item())
            except Exception:
                pass
            if self._overlay_mode:
                self._configure_overlay_axis_geometry(axis_handle)
            self._apply_pg_axis_style(
                axis_handle, axis_color if axis_color is not None else color
            )
```
（曲线添加段 ~318-346 不变：每条曲线仍用自身 `color` 画笔、按自身复合键注册到 `channel_data`/`_channel_lines`；`target_vb.addItem` 已支持多曲线同 ViewBox。）

- [ ] **Step 4: overlay 分支按 group 归并**（`canvas.py` 整体替换 ~592-619，即从「Channel 1 →」到右轴 for 循环结束）

把现有「first_handle + vis[1:] 循环」替换为 slot 归并：
```python
            # 按 axis_group 归并成「轴槽」：未分组通道各占一槽；同 group 的通道
            # 共享一槽（一个 aux ViewBox + 一根 Y 轴，量程取并集自动）。槽序保持
            # 通道首次出现顺序；槽 0 绑左轴，其余绑右轴。
            slots = []
            slot_of_gid = {}
            for v in vis:
                gid = v[7]
                if gid is None:
                    slots.append({"gid": None, "members": [v]})
                elif gid in slot_of_gid:
                    slots[slot_of_gid[gid]]["members"].append(v)
                else:
                    slot_of_gid[gid] = len(slots)
                    slots.append({"gid": gid, "members": [v]})

            for slot_idx, slot in enumerate(slots):
                handle = self._overlay_axes._add_overlay_axis_handle(pi, slot_idx)
                self.axes_list.append(handle)
                members = slot["members"]
                gid = slot["gid"]
                if gid is None:
                    name, t, sig, color, unit, data_id, p_visible, _ag = members[0]
                    self._overlay_axes._bind_channel(
                        handle, name, t, sig, color, unit, data_id,
                        xlabel=xlabel, skip_envelope=defer_first_frame,
                    )
                    self._set_primary_line_visible(name, p_visible)
                else:
                    units = {m[4] for m in members}
                    group_label = next(iter(units)) if len(units) == 1 else "(混合单位)"
                    group_color = axis_group_color(gid)
                    for j, m in enumerate(members):
                        name, t, sig, color, unit, data_id, p_visible, _ag = m
                        self._overlay_axes._bind_channel(
                            handle, name, t, sig, color, unit, data_id,
                            xlabel=xlabel, skip_envelope=defer_first_frame,
                            axis_label=group_label if j == 0 else None,
                            axis_color=group_color if j == 0 else None,
                            update_axis_style=(j == 0),
                        )
                        self._set_primary_line_visible(name, p_visible)
```
并在 `canvas.py` 顶部 import 区加：
```python
from ..axis_group_palette import axis_group_color
```
（删除被替换掉的 `first_handle = ... _add_overlay_axis_handle(pi, 0)`、`*vis[0][:6]` 绑定、以及 `vis[1:]` 右轴循环；保留其后的 `_apply_overlay_emphasis()` / `showGrid` / `_build_overlay_y_grid()`。）

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/ui/test_overlay_shared_axis.py -q`
Expected: PASS（含 Task 4 的回归用例：单成员 group 仍是独立 slot，`axes_list==2`）

- [ ] **Step 6: 无回归**

Run: `pytest tests/ui/test_pg_timedomain_canvas.py tests/ui/test_overlay_grid_ticks.py tests/ui/test_time_filter_overlay.py tests/ui/test_axis_interaction.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/pg_canvas/canvas.py mf4_analyzer/ui/pg_canvas/overlay_axes.py tests/ui/test_overlay_shared_axis.py
git commit -m "feat(canvas): overlay 同组通道共享 ViewBox/Y 轴(并集量程)"
```

---

## Task 6: 交互/网格/强调适配 + 整体真机验证

**Files:**
- Inspect / 视需要 Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py`（`_apply_overlay_emphasis`、`_repin_overlay_channel_ticks`、`_snap_overlay_channel_to_grid`、Y 拖拽里用 `_selected_overlay_channel` 的选择逻辑）
- Test: `tests/ui/test_overlay_shared_axis.py`（追加交互断言）

**Interfaces:**
- Consumes: Task 5 的「一个 handle 持多条曲线」结构。
- Produces: 共享轴下的选择/强调/网格对齐/拖拽行为正确（不崩、语义符合 spec ⑥：拖共享轴整组同步；网格把共享轴当一根轴）。

**说明:** Task 5 已把「组→一个 handle」，多数既有 overlay 逻辑按 handle/ViewBox 迭代，理论上把组当一根轴即正确（拖整组、网格对齐按一根轴）——这正是 spec ⑥ 想要的。本任务先用断言+真机确认，再仅针对暴露出的「按通道下标假设 == handle 数」之类问题做定点修。

- [ ] **Step 1: 写交互断言测试**（追加）

```python
class TestOverlayGroupInteraction:
    def test_repin_and_emphasis_run_without_error_on_grouped(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "Nm", "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(3 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        # 触发网格重钉/强调（既有 API），grouped handle 不应抛异常
        canvas._overlay_axes._apply_overlay_emphasis()
        canvas._overlay_axes._repin_overlay_channel_ticks()
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 2

    def test_mixed_unit_group_does_not_crash(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t),  "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t),  "#0a0", "rpm", "f1", {"axis_group": 1}),
        ]
        canvas.plot_channels(rows, mode="overlay")
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 1
```

> 注：`_repin_overlay_channel_ticks` / `_apply_overlay_emphasis` 的精确签名以真码为准；若需参数，先 Read 这两个函数再补齐调用。

- [ ] **Step 2: 运行；按失败定点修**

Run: `pytest tests/ui/test_overlay_shared_axis.py::TestOverlayGroupInteraction -q`
- 若 PASS：既有逻辑已兼容「多曲线/轴」，无需改源码，进入 Step 3。
- 若 FAIL：Read 对应函数，定位「假设 `len(axes_list)==通道数`」或「按通道下标取 handle」之处，改为按 handle 迭代 / 按曲线（`_channel_lines`）迭代。改完重跑至 PASS。

- [ ] **Step 3: 全量回归**

Run: `pytest -q`
Expected: PASS（默认 not slow）。如触及性能用例，另跑 `pytest -m slow tests/ui/test_pg_timedomain_canvas.py -q`。

- [ ] **Step 4: 整体真机验证（CLAUDE.md 红线）**

启动 GUI，用真实 EPS 数据走完整链路，截图确认：
1. **共轴塌缩**：选 2 个同单位通道（如两路扭矩）合并 → 叠加图上塌成**一根共享 Y 轴**、两条曲线落同一量程、可直接比幅值；轴色 = 组色。
2. **独立轴并存**：再叠加一个不同单位通道（如电机转速）→ 它保持自己的独立轴，未被压扁。
3. **混合单位**：把异单位通道并入一组 → 共享轴标签显示「(混合单位)」，不报错。
4. **拖拽**：拖共享轴 → 整组一起平移/缩放；拖独立轴互不影响。
5. **网格**：overlay 网格按共享轴当一根轴对齐，无多色重叠网格。
6. **树徽标 + 缩进**：树里分组通道徽标色与图上共享轴色一致；缩进收窄到位。
7. **滤波叠加**：对已分组通道开「显示滤波后」→ 虚线 companion 落在该组共享轴上。

截图留档；发现问题回到对应 Task 修复。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(canvas): 共轴组交互/网格适配 + 真机验证收口"
```

---

## Self-Review（计划 vs spec 覆盖核对）

- spec ① 目标/范围 → Task 1-6 全覆盖；「仅 overlay/不持久化/异单位允许」写进 Global Constraints。
- spec ② 数据模型 `_axis_groups` → Task 1。
- spec ③ 交互（多选 ExtendedSelection + 右键合并/拆分 + 两套独立状态）→ Task 1（多选）+ Task 2（菜单）。
- spec ④ 视觉标识（树徽标 drawBranches + 共享轴色/标签 + 混合单位）→ Task 3（树）+ Task 5（轴色/标签）。
- spec ④ 绘图（共享 ViewBox；否决 Y-link）→ Task 5。
- spec ④「修 companion 分流」→ 读真码发现**已**按 `companion_of` 匹配，降级为 Task 4 回归守卫（已在计划注明该偏差）。
- spec ⑥ 量程/拖拽/网格 → Task 5（并集量程）+ Task 6（拖整组/网格按一根轴）。
- spec ⑦ 生命周期/边界（remove 清理、companion 跟随源轴、切模式保留）→ Task 1（清理）+ Task 4/5（companion）+ Task 6（真机第 7 点）。
- spec ⑧ 缩进 → Task 3。
- spec ⑨ YAGNI（不做拖轴合并/不持久化/不跨模式）→ 未排任务，符合。
- 类型一致性：`axis_group` 贯穿 meta→primaries→vis 第 8 位；`merge_axis_group/split_axis_group/checked_axis_groups/_effective_groups/_axis_group_menu_plan/axis_group_for` 命名在 Task 1 定义、Task 2/4 一致引用；`axis_group_color` 单一来源被树与 canvas 共用。
- 占位符扫描：无 TBD/TODO；每个改码步骤均给出完整代码。
