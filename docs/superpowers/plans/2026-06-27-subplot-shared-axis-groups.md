# 分屏模式共轴组合并 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让时域「分屏」模式下同 `axis_group` 的通道合并到一行、共享一根 Y 轴（量程取并集、轴色=组色），从源头减少行数缓解纵向拥挤。

**Architecture:** 抽出叠加模式现成的「按 axis_group 归槽」逻辑为共用 helper，分屏行构建从「每通道一行」改成「每槽一行」；多成员槽把所有曲线绑到同一个子图 PlotItem 的主 ViewBox（`_bind_channel` 本就支持多曲线绑同一 handle），共享 Y 轴的并集量程由该 ViewBox 的 auto-range 自然得到。叠加 / 单通道模式完全不动。

**Tech Stack:** Python 3, PyQt5, pyqtgraph, pytest + pytest-qt。

## Global Constraints

- 不做滚动条 / QScrollArea / 顶部固定时间轴 / 绿灯重锚 / 最小行高 / 导出整图改动（用户已明确放弃滚动方案）。
- 叠加模式、单通道模式、滚轮调度（`overlay_axes.py:1388-1418`）、X 轴联动、AA 绿灯、导出路径：**零改动**。
- 组色一律走 `from mf4_analyzer.ui.axis_group_palette import axis_group_color`（canvas.py:106 已导入），不另造色板。
- `pytest.ini` 默认 `-m "not slow"`；新测试不打 `slow` 标记。
- 真机渲染验证为项目铁律：UI 改动必须截图验真实渲染，不靠「属性设上了 + 单测过」判定（见 Task 4）。
- 提交锁定路径（`git commit -- <paths>`），不裹挟工作树里 codex 并行改动的文件。
- 提交信息结尾附 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

## 关键既有事实（实现者须知）

- `plot_channels(ch_list, mode=..., xlabel="Time (s)")`（`canvas.py:435`）。公开 row 形如
  `(name, visible, t, sig, color, unit, data_id, {"axis_group": N})`（第 8 位是 meta dict）。
- 内部转成 `vis` 元组 `(name, t, sig, color, unit, data_id, p_visible, axis_group)`，
  **axis_group 在 `vis[i][7]`**（int 或 None）。见 `canvas.py:495-508`。
- `subplot_mode = (mode == "subplot" and len(vis) > 1)`（`canvas.py:516`）。
- 当前分屏分支：`canvas.py:537-575`，每通道 `_add_plot_item(row=i, col=0)`。
- 叠加归槽逻辑原型：`canvas.py:595-632`。
- `_bind_channel(axis_handle, name, t, sig, color, unit, data_id, *, xlabel=None,
  skip_envelope=False, axis_label=None, axis_color=None, update_axis_style=True)`
  （`overlay_axes.py:292`）。多成员槽对每个成员调一次，仅 `j==0` 设
  `axis_label`/`axis_color`/`update_axis_style=True`（叠加 `canvas.py:623-632`）。
- `_subplot_label_specs`：4 元组 `(handle, name, color, unit)` 列表，被
  `canvas.py:2449`（inside/outside 判定）与 `canvas.py:2537`
  （`_recheck_subplot_label_placement`）消费。当前 1:1 对应通道（`canvas.py:562-565`）。
- `_configure_subplot_bottom_axis(axis_handle, *, is_bottom)`（`overlay_axes.py:666`）。
- 测试范式见 `tests/ui/test_overlay_shared_axis.py`（canvas 级，`plot_channels` + 断言 `axes_list`）。

## File Structure

- **Modify** `mf4_analyzer/ui/pg_canvas/canvas.py`
  - 新增私有方法 `_group_visible_into_slots(self, vis)`（归槽 helper）。
  - 叠加分支（`595-605`）改调 helper（纯重构）。
  - 分屏分支（`537-575`）改为按槽构建。
- **Create** `tests/ui/test_subplot_shared_axis.py`（分屏共轴全部用例）。
- 标签/底轴逻辑：复用既有 `_recheck_subplot_label_placement` /
  `_unify_subplot_left_axis_widths` / `_unify_subplot_bottom_axis_heights`，
  仅把 `_subplot_label_specs` 与 `is_bottom` 的计数单位从「通道」改成「槽」。

---

### Task 1: 抽出共用归槽 helper（纯重构，零行为变化）

把叠加内联的归槽逻辑抽成 `_group_visible_into_slots`，叠加改调它。叠加行为不变，由现有 `test_overlay_shared_axis.py` 守住回归。

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py:595-605`（抽取）、新增方法
- Test: `tests/ui/test_subplot_shared_axis.py`（新建，先放 helper 单测）

**Interfaces:**
- Produces: `_group_visible_into_slots(self, vis) -> list[dict]`，每元素
  `{"gid": int|None, "members": list[vis_tuple]}`；未分组通道各占一槽，
  同 gid 通道合并到首次出现位置的槽，槽序 = 通道首次出现顺序。

- [ ] **Step 1: 写失败测试**

新建 `tests/ui/test_subplot_shared_axis.py`：

```python
"""分屏共轴：归槽 helper + 分屏行合并 + 边界。"""
import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.axis_group_palette import axis_group_color


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _curve_count(vb):
    return sum(1 for it in vb.addedItems if isinstance(it, pg.PlotDataItem))


def _vis(name, color, unit, data_id, gid):
    t = np.linspace(0.0, 1.0, 50, dtype=np.float64)
    # vis 元组：(name, t, sig, color, unit, data_id, p_visible, axis_group)
    return (name, t, np.sin(t), color, unit, data_id, True, gid)


class TestGroupIntoSlots:
    def test_ungrouped_each_own_slot(self, qapp):
        canvas = _pg_canvas(qapp)
        vis = [_vis("a", "#f00", "Nm", "f1", None),
               _vis("b", "#0a0", "Nm", "f2", None)]
        slots = canvas._group_visible_into_slots(vis)
        assert [s["gid"] for s in slots] == [None, None]
        assert [len(s["members"]) for s in slots] == [1, 1]

    def test_same_gid_merges_preserving_first_order(self, qapp):
        canvas = _pg_canvas(qapp)
        vis = [_vis("a", "#f00", "Nm", "f1", 1),
               _vis("c", "#00f", "rpm", "f2", None),
               _vis("b", "#0a0", "Nm", "f1", 1)]
        slots = canvas._group_visible_into_slots(vis)
        # a 与 b 同组 1 → 合到第 0 槽；c 未分组 → 第 1 槽
        assert [s["gid"] for s in slots] == [1, None]
        assert [m[0] for m in slots[0]["members"]] == ["a", "b"]
        assert [m[0] for m in slots[1]["members"]] == ["c"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/ui/test_subplot_shared_axis.py::TestGroupIntoSlots -v`
Expected: FAIL — `AttributeError: 'TimeDomainCanvasPG' object has no attribute '_group_visible_into_slots'`

- [ ] **Step 3: 实现 helper**

在 `canvas.py` 类内新增方法（放在 `plot_channels` 附近）：

```python
    def _group_visible_into_slots(self, vis):
        """按 axis_group 把可见通道归并成「轴槽」。

        未分组通道（gid is None）各占一槽；同 gid 通道合并到该组首次
        出现位置的槽。槽序 = 通道首次出现顺序。叠加与分屏共用，保证两
        模式归并结果一致。返回 ``[{"gid": int|None, "members": [vis...]}]``。
        """
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
        return slots
```

- [ ] **Step 4: 叠加分支改调 helper**

把 `canvas.py:595-605` 的内联归槽（`slots = []` ... 整段 for 循环）替换为：

```python
            slots = self._group_visible_into_slots(vis)
```

保留其后 `for slot_idx, slot in enumerate(slots):` 不变。

- [ ] **Step 5: 运行 helper 单测 + 叠加回归**

Run: `pytest tests/ui/test_subplot_shared_axis.py::TestGroupIntoSlots tests/ui/test_overlay_shared_axis.py -v`
Expected: PASS（helper 单测通过；叠加现有用例全绿，行为零变化）

- [ ] **Step 6: 提交**

```bash
git add tests/ui/test_subplot_shared_axis.py
git commit -m "$(printf 'refactor(canvas): extract _group_visible_into_slots helper\n\n叠加归槽逻辑抽成共用方法,分屏将复用;叠加行为零变化。\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')" -- mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_subplot_shared_axis.py
```

---

### Task 2: 分屏按槽构建 + 共享 Y 轴 + 组色（核心）

分屏行构建从「每通道一行」改成「每槽一行」：单成员槽行为同今天；多成员槽把所有成员曲线绑到同一行 PlotItem 的主 ViewBox，Y 轴并集量程靠 auto-range，轴色=组色，行标签=成员名连接。

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py:537-575`（分屏分支重写）
- Test: `tests/ui/test_subplot_shared_axis.py`

**Interfaces:**
- Consumes: `_group_visible_into_slots`（Task 1）、`axis_group_color`、`_bind_channel`、`_configure_subplot_bottom_axis`。
- Produces: 分屏 `axes_list` 长度 = 槽数；分组行 `axes_list[k].view_box` 持有该组全部曲线；`_subplot_label_specs` 每槽一条 `(handle, label, color, unit)`，分组行 color=组色。

- [ ] **Step 1: 写失败测试**

追加到 `tests/ui/test_subplot_shared_axis.py`：

```python
def _row(name, color, unit, data_id, gid=None):
    t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
    meta = {"axis_group": gid} if gid is not None else None
    base = (name, True, t, np.sin(t) if name != "b" else np.cos(t),
            color, unit, data_id)
    return base + (meta,) if meta is not None else base


class TestSubplotGroupMerge:
    def test_row_count_equals_slot_count(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1", gid=1),
            _row("b", "#0a0", "Nm", "f1", gid=1),
            _row("c", "#00f", "rpm", "f2"),  # ungrouped
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # a,b 合一行；c 一行 → 2 行
        assert len(canvas.axes_list) == 2

    def test_group_row_holds_all_member_curves(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1", gid=1),
            _row("b", "#0a0", "Nm", "f1", gid=1),
            _row("c", "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        assert _curve_count(canvas.axes_list[0].view_box) == 2  # a+b 同行
        assert _curve_count(canvas.axes_list[1].view_box) == 1  # c 单行

    def test_group_row_union_range_covers_all_members(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.full_like(t, 1.0),  "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", True, t, np.full_like(t, 50.0), "#0a0", "Nm", "f1", {"axis_group": 1}),
            ("c", True, t, np.full_like(t, 5.0),  "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        lo, hi = canvas.axes_list[0].get_ylim()
        assert lo <= 1.0 + 1e-6 and hi >= 50.0 - 1e-6

    def test_group_row_label_uses_group_color(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1", gid=1),
            _row("b", "#0a0", "Nm", "f1", gid=1),
            _row("c", "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        # 分屏标签每槽一条 → 2 条
        assert len(canvas._subplot_label_specs) == 2
        grp_color = canvas._subplot_label_specs[0][2]
        assert grp_color == axis_group_color(1)

    def test_ungrouped_subplot_unchanged(self, qapp):
        canvas = _pg_canvas(qapp)
        rows = [
            _row("a", "#f00", "Nm", "f1"),
            _row("b", "#0a0", "Nm", "f2"),
            _row("c", "#00f", "rpm", "f3"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 3
        assert all(_curve_count(h.view_box) == 1 for h in canvas.axes_list)
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/ui/test_subplot_shared_axis.py::TestSubplotGroupMerge -v`
Expected: FAIL — 多成员槽未实现，`test_group_row_holds_all_member_curves` 得到 1 行/逐通道（`axes_list==3`），断言不符。

- [ ] **Step 3: 重写分屏分支**

把 `canvas.py:537-575` 的分屏 `if subplot_mode:` 块体替换为下述实现（`# NOTE: ...setXLink` 注释段及其后的 `_subplot_label_specs`/`_recheck`/`_unify` 调用一并按下方重写）：

```python
        if subplot_mode:
            slots = self._group_visible_into_slots(vis)
            n_slots = len(slots)
            self._subplot_label_specs = []
            for slot_idx, slot in enumerate(slots):
                pi = self._add_plot_item(row=slot_idx, col=0)
                handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
                self.axes_list.append(handle)
                members = slot["members"]
                is_bottom = (slot_idx == n_slots - 1)
                if slot["gid"] is None:
                    name, t, sig, color, unit, data_id, p_visible, _ag = members[0]
                    self._overlay_axes._bind_channel(
                        handle, name, t, sig, color, unit, data_id,
                        xlabel=xlabel if is_bottom else None,
                        skip_envelope=defer_first_frame,
                    )
                    self._set_primary_line_visible(name, p_visible)
                    self._subplot_label_specs.append((handle, name, color, unit))
                else:
                    gid = slot["gid"]
                    group_color = axis_group_color(gid)
                    units = {m[4] for m in members}
                    group_unit = next(iter(units)) if len(units) == 1 else "(混合单位)"
                    group_label = " · ".join(str(m[0]) for m in members)
                    for j, m in enumerate(members):
                        name, t, sig, color, unit, data_id, p_visible, _ag = m
                        self._overlay_axes._bind_channel(
                            handle, name, t, sig, color, unit, data_id,
                            xlabel=xlabel if (is_bottom and j == 0) else None,
                            skip_envelope=defer_first_frame,
                            axis_label=group_label if j == 0 else None,
                            axis_color=group_color if j == 0 else None,
                            update_axis_style=(j == 0),
                        )
                        self._set_primary_line_visible(name, p_visible)
                    self._subplot_label_specs.append(
                        (handle, group_label, group_color, group_unit)
                    )
                self._overlay_axes._configure_subplot_bottom_axis(
                    handle, is_bottom=is_bottom,
                )
            # NOTE: 不调用 setXLink；X 范围经 _propagate_xlim_to_siblings 精确传播
            # （原因见旧注释，保留该机制不变）。
            self._recheck_subplot_label_placement()
            self._unify_subplot_left_axis_widths()
```

注意：删除原 `562-565` 的 `_subplot_label_specs = [...vis[i]...]` 推导式（已在循环内按槽构建）。`PgAxisHandle`、`axis_group_color`、`_propagate_xlim_to_siblings` 均已在文件作用域可用（`axis_group_color` 见 `canvas.py:106`）。

- [ ] **Step 4: 运行新测试 + 分屏回归**

Run: `pytest tests/ui/test_subplot_shared_axis.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_canvas_compactness.py -v`
Expected: PASS（新分组用例 + 分屏既有回归全绿）

- [ ] **Step 5: 提交**

```bash
git commit -m "$(printf 'feat(subplot): merge axis_group channels into shared-Y rows\n\n分屏按槽构建:同组通道合到一行共享一根Y轴(量程并集/轴色=组色),\n未分组仍各占一行。复用叠加 _bind_channel 多曲线绑定。\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')" -- mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_subplot_shared_axis.py
```

---

### Task 3: 边界 + 两模式一致性 + 底轴归属 + 全量回归

覆盖退化、混合单位、分屏↔叠加归槽一致、底部时间轴落在最后一槽，并跑全量 pytest 防回归。

**Files:**
- Test: `tests/ui/test_subplot_shared_axis.py`
- Modify（仅当回归暴露问题时）: `mf4_analyzer/ui/pg_canvas/canvas.py`

**Interfaces:**
- Consumes: Task 1/2 的 helper 与分屏分支。

- [ ] **Step 1: 写失败/守护测试**

追加到 `tests/ui/test_subplot_shared_axis.py`：

```python
class TestSubplotGroupEdges:
    def test_group_with_one_visible_member_degrades_to_single_curve(self, qapp):
        # 组 1 两成员，但 b 未勾选(visible=False) → 该组只剩 1 可见 → 单曲线行
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True,  t, np.sin(t), "#f00", "Nm", "f1", {"axis_group": 1}),
            ("b", False, t, np.cos(t), "#0a0", "Nm", "f1", {"axis_group": 1}),
            ("c", True,  t, np.sin(2 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # b 不可见且无 companion → 不入 vis；组 1 只剩 a → 退化单曲线
        assert len(canvas.axes_list) == 2
        assert _curve_count(canvas.axes_list[0].view_box) == 1

    def test_mixed_unit_group_does_not_crash(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "rpm", "f1", {"axis_group": 1}),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        canvas._recheck_subplot_label_placement()
        QCoreApplication.processEvents()
        assert len(canvas.axes_list) == 1  # 两成员同组 → 1 行

    def test_subplot_and_overlay_group_into_same_slots(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "Nm",  "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(3 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        n_sub = len(canvas.axes_list)
        canvas.plot_channels(rows, mode="overlay")
        n_ovl = len(canvas.axes_list)
        assert n_sub == n_ovl == 2  # 两模式共用归槽 → 槽数一致

    def test_bottom_axis_on_last_slot(self, qapp):
        canvas = _pg_canvas(qapp)
        t = np.linspace(0.0, 1.0, 200, dtype=np.float64)
        rows = [
            ("a", True, t, np.sin(t), "#f00", "Nm",  "f1", {"axis_group": 1}),
            ("b", True, t, np.cos(t), "#0a0", "Nm",  "f1", {"axis_group": 1}),
            ("c", True, t, np.sin(3 * t), "#00f", "rpm", "f2"),
        ]
        canvas.plot_channels(rows, mode="subplot")
        QCoreApplication.processEvents()
        # 最后一槽(c 行)底轴可见;非末槽底轴隐藏
        last_ax = canvas.axes_list[-1]._ax("bottom")
        first_ax = canvas.axes_list[0]._ax("bottom")
        assert last_ax is not None and last_ax.isVisible()
        assert not first_ax.isVisible()
```

- [ ] **Step 2: 运行确认状态**

Run: `pytest tests/ui/test_subplot_shared_axis.py::TestSubplotGroupEdges -v`
Expected: 多数应已 PASS（Task 2 已实现核心）；若 `test_bottom_axis_on_last_slot` 因 `_ax("bottom")` 可见性断言不符而 FAIL，进入 Step 3 修正；否则跳到 Step 4。

- [ ] **Step 3:（条件）修正底轴可见性**

若 `_configure_subplot_bottom_axis` 的 `is_bottom` 判定已按槽传入（Task 2 已传 `is_bottom=(slot_idx == n_slots - 1)`）但断言仍失败，核对断言用的可见性 API 与该方法实际设置方式（读 `overlay_axes.py:666` 起的实现），把测试断言对齐到其真实设置的属性（如 `showAxis`/`setStyle(showValues=...)`）。不改生产逻辑，只对齐测试到既有契约。

- [ ] **Step 4: 全量回归**

Run: `pytest tests/ui -q`
Expected: PASS（无回归；如 `test_channel_axis_groups.py` / `test_overlay_shared_axis.py` / `test_main_window_smoke.py` 等全绿）

- [ ] **Step 5: 提交**

```bash
git commit -m "$(printf 'test(subplot): edges + subplot/overlay slot parity for axis groups\n\n退化(单可见成员)/混合单位/两模式归槽一致/底轴落末槽;全量 ui 回归绿。\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')" -- mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_subplot_shared_axis.py
```

---

### Task 4: 真机渲染验证 + hint 复核（人工）

单测过 ≠ 真机对。按项目铁律截图验真实渲染，并复核共轴 hint 是否放出。

**Files:**
- 无代码改动（除非真机暴露问题）；可能触及 `/update-hints` 维护的 `hints.py` / quickref。

- [ ] **Step 1: 启动真机**

Run: `python "MF4 Data Analyzer V1.py"`
载入一个多通道文件（如对话截图的 EPS taiyaok），切到时域「分屏」。

- [ ] **Step 2: 截图验证分组渲染**

在通道树选 ≥2 个通道 → 右键合并共轴组（`merge_axis_group`），观察分屏：
- 同组通道**合到一行**、共享一根 Y 轴；
- 该行 Y 轴**轴色 = 组色**，与通道树徽标同色；
- 组内每条曲线**各保留通道色**；
- 未分组通道仍各占一行；
- 行数明显减少（拥挤缓解）；
- 底部时间轴在最后一行、标签可读不重叠。

逐项截图比对。任一不符 → 回到 systematic-debugging，先诊断显示层（`_recheck_subplot_label_placement` 的 inside/outside 翻转 / 轴 pen）再定点修，**不靠属性值臆断**。

- [ ] **Step 3: hint 复核**

Run: `/update-hints`
核对：分屏共轴已落地，决定是否放出此前 `ship="later"` 隐着的共轴相关提示（footer 滚动提示 + 操作速查面板二者同步）。按命令产出落地。

- [ ] **Step 4:（如有）提交真机修正 / hint**

```bash
git commit -m "$(printf 'fix(subplot)/docs(hints): real-device polish for subplot axis groups\n\n<按真机所见与 hint 复核结果填写具体改动>\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')" -- <改动路径>
```

---

## Self-Review

**1. Spec coverage（逐条对照 spec）：**
- 同组合并到一行/共享一根 Y/并集/轴色=组色 → Task 2（`test_group_row_*`）✓
- 组内曲线保留通道色 → Task 2 实现（`_bind_channel` 用各自 color），Task 4 真机验 ✓
- 未分组各一行 → Task 2 `test_ungrouped_subplot_unchanged` ✓
- 两模式共用归槽一致 → Task 1 helper + Task 3 `test_subplot_and_overlay_group_into_same_slots` ✓
- 行内标签显示成员 → Task 2 采用 spec 兜底方案 B 的变体（成员名 `" · "` 连接作单条行标签，组色），规避 inside-label 多 TextItem 重叠；spec 已许可 A 复杂时回退。真机可读性 Task 4 验 ✓
- 底部时间轴按槽落末行 → Task 2 `is_bottom=(slot_idx==n_slots-1)` + Task 3 `test_bottom_axis_on_last_slot` ✓
- 边界（单可见成员退化 / 混合单位 / 切换一致 / 全未分组）→ Task 3 ✓
- 不动滚轮/叠加/单通道/绿灯/导出 → 仅改 `subplot_mode` 分支与抽取重构，叠加由现有用例守 ✓
- 测试 8 条 + 真机 → Task 1/2/3 pytest + Task 4 截图 ✓
- hint 复核 → Task 4 Step 3 ✓

**2. Placeholder scan：** 无 TBD/TODO；每个代码步给出完整代码；Task 3 Step 3 为条件修正且写明对齐既有契约的具体做法，非占位。

**3. Type consistency：** `_group_visible_into_slots` 返回 `[{"gid","members"}]` 在 Task 1 定义、Task 2/3 一致消费；`_subplot_label_specs` 全程 4 元组 `(handle, label, color, unit)`；`vis[7]`=axis_group 贯穿；`_bind_channel` 关键字参数与 `overlay_axes.py:292` 签名一致。

---

## Execution Handoff

见 writing-plans 的执行选项（subagent-driven / inline）。
