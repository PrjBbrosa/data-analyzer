# 分屏模式共轴组合并 — 设计

**日期**：2026-06-27
**状态**：已批准，待转实现计划
**作者**：brainstorming（主 Claude + 用户）

## 背景与动机

时域「分屏」模式下，每个可见通道独占一行子图（`canvas.py:537-551`：
`for i, ... : self._add_plot_item(row=i, col=0)`）。所有行用
`setRowStretchFactor(row, 1)` 均分视口高度，无最小行高。通道一多（实测 20 通道）
每行被压到 ~26px，标题压在波形上、完全不可读。

「叠加」模式早已支持按 `axis_group` 把同组通道合并到一个轴槽
（`canvas.py:592-632`），但分屏模式读了 `axis_group`（`canvas.py:538` 的
`_axis_group`）却**从不使用**——每通道照样占一行。

## 决策：只做共轴合并，不做滚动条

曾评估"加竖向滚动条 + 顶部固定时间轴"方案（见对话工况预览
`scratchpad/scroll_mockup.html`）。**用户决定放弃滚动**——"太乱了"。
最终范围收敛为：**让 `axis_group` 在分屏模式也生效**，同组通道合并到一行、
共享一根 Y 轴，从源头减少行数来缓解纵向拥挤。

**不在本次范围**：滚动条、`QScrollArea`、顶部固定时间轴、AA 绿灯重锚、
最小行高、导出整图改动。这些都不做。

## 目标行为

分屏模式下：

- 同 `axis_group` 的可见通道合并到**一行**：一个 PlotItem、一个 ViewBox、
  **一根共享 Y 轴**，量程取成员**并集**（auto-range 自然得到），**轴色 = 组色**
  （复用叠加的 `axis_group_color(gid)`，与通道树徽标共色板）。组内各曲线**保留
  各自通道色**。
- 未分组通道（`axis_group is None`）仍**各占一行**，行为与现在完全一致。
- 行数 = 槽数（slot count），而非通道数。
- 与叠加模式语义一致：两模式用**同一套归槽逻辑**。

非分屏模式（叠加 / 单通道）**完全不动**。

## 架构与改动点

核心是把分屏的行构建从「每通道一行」改成「每槽一行」，并复用叠加现成的
归槽 + 多曲线绑定机制。

### 1. 抽出共用的归槽函数

叠加模式的归槽逻辑（`canvas.py:595-605`）原地内联。抽成一个共用 helper
（如 `_group_visible_into_slots(vis) -> list[{"gid", "members"}]`），叠加与分屏
共同调用，保证两模式槽序、合并规则**绝对一致**（槽序 = 通道首次出现顺序）。

### 2. 分屏行构建改为按槽

`canvas.py:537-575` 的分屏分支改写：

```
slots = self._group_visible_into_slots(vis)
for slot_idx, slot in enumerate(slots):
    pi = self._add_plot_item(row=slot_idx, col=0)
    handle = PgAxisHandle(plot_item=pi, owner_canvas=self)
    self.axes_list.append(handle)
    members = slot["members"]
    is_bottom = (slot_idx == len(slots) - 1)
    if slot["gid"] is None:
        # 单成员：与今天一致
        name, t, sig, color, unit, data_id, p_visible, _ = members[0]
        self._overlay_axes._bind_channel(handle, name, t, sig, color, unit,
            data_id, xlabel=xlabel if is_bottom else None,
            skip_envelope=defer_first_frame)
        self._set_primary_line_visible(name, p_visible)
    else:
        # 多成员：所有成员绑到同一个 handle（同一 PlotItem 主 ViewBox），
        # 镜像叠加的 619-632：只在 j==0 设组标签/组色/刷新轴样式。
        group_color = axis_group_color(slot["gid"])
        for j, m in enumerate(members):
            name, t, sig, color, unit, data_id, p_visible, _ = m
            self._overlay_axes._bind_channel(handle, name, t, sig, color, unit,
                data_id, xlabel=xlabel if is_bottom else None,
                skip_envelope=defer_first_frame,
                axis_color=group_color if j == 0 else None,
                update_axis_style=(j == 0))
            self._set_primary_line_visible(name, p_visible)
    self._overlay_axes._configure_subplot_bottom_axis(handle, is_bottom=is_bottom)
```

关键复用：`_bind_channel` **本就支持把多条曲线绑到同一个 handle**（叠加多成员
槽即如此，`canvas.py:623-632`）。共享 Y 轴的"量程取并集"靠该 PlotItem 单一
ViewBox 的 auto-range 自然实现，无需手动算并集。

### 3. 行内标签（`_subplot_label_specs`）

现 `_subplot_label_specs`（`canvas.py:562-565`）是每行一条 `(handle, name,
color, unit)`，供 `_recheck_subplot_label_placement` 做 inside/outside 翻转。
分组行需展示**该行全部成员**。实现细节（留给计划/实现敲定，二选一）：

- **A**：每行扩成多条 label spec（一行多个成员名各自一条），翻转逻辑按行聚合；
- **B**：分组行用单条组标签（组色 + 成员名/计数），单成员行不变。

倾向 **A**（信息完整、与叠加多曲线 label 体验一致），但若 A 的 bbox 翻转复杂度
过高，B 可接受。最终以真机渲染可读为准。

### 4. 底部时间轴与左轴对齐

- `_configure_subplot_bottom_axis(handle, is_bottom=...)`：`is_bottom` 判定从
  "最后一个通道"改为"最后一个槽"（`slot_idx == len(slots)-1`）。逻辑不变，
  仅计数单位由通道→槽。
- `_unify_subplot_left_axis_widths()`（`canvas.py:575`）、
  `_propagate_xlim_to_siblings`、`_unify_subplot_bottom_axis_heights` 对"行"
  无差别，按槽数行数照常工作，无需特殊处理。

## 不改动项（明确边界）

- **滚轮**：纯滚轮 / Ctrl / Shift 仍作用于鼠标所在行（`overlay_axes.py:1388-1418`）。
  分组行的滚轮平移/缩放作用于该行共享 Y 轴（即全体成员），自然一致。
- **叠加模式、单通道模式、绿灯、导出、X 轴联动**：全部不动。

## 边界情况

- **组内只剩 1 个可见通道**（其余被取消勾选）：该槽 `members` 长度=1，自然退化为
  单曲线行（走单成员路径 or 多成员路径仅 1 条，视实现，两者结果一致）。
- **组内混合单位**（误把扭矩+温度分一组）：仍按 auto-range 并集画在一根 Y 轴上，
  用户自负，**与叠加模式行为一致**（叠加用 `(混合单位)` 标签，分屏可复用或省略）。
- **分屏 ↔ 叠加切换**：两模式共用归槽 helper，组归并结果一致，切换无突变。
- **全部通道都未分组**：槽数=通道数，分屏退化为今天的逐通道一行，零行为变化。

## 测试（pytest-qt）

1. 分组后分屏**行数 = 槽数**（未分组各一行 + 每组一行）。
2. 同组多通道**共享同一个 ViewBox / 同一根 Y 轴**；Y 量程 = 成员并集。
3. 分组行**轴色 = `axis_group_color(gid)`**；组内曲线各保留通道色。
4. 未分组通道仍各占一行，单曲线单轴（回归不破）。
5. 组内只剩 1 可见通道 → 退化单曲线行。
6. 分屏 ↔ 叠加切换，归槽结果一致。
7. 底部时间轴落在最后一个**槽**所在行。
8. **真机渲染验证**（截图）：分组行可读、轴色正确、标题不再无意义重复——
   遵循项目"必验真机渲染"铁律，不靠"属性设上了+单测过"判定。

## 关联与后续

- 复用并对齐既有共轴组特性（叠加模式，见
  `memory: project-overlay-shared-axis-groups`：aux ViewBox 共轴、轴色=组色、
  树徽标共色板、`axis_group` 走 meta 8 元组 `v[7]`）。
- 该特性曾遗留"`/update-hints` 放出共轴 hint"（当时 `ship="later"` 隐着）。
  分屏共轴落地后，走 `/update-hints` 复核是否放出共轴相关提示。
