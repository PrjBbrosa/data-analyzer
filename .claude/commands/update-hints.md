---
description: 核对最近 UI 改动，给「非自明交互」补/改 chart hint（项目内命令）
---

# /update-hints — 维护 chart hint 注册表

任务：核对自上次以来的 UI 交互改动，找出**非自明交互**里「缺提示 / 提示过期 /
在途未登记」的，起草并（经用户确认后）写回提示注册表。

设计依据：`docs/superpowers/specs/2026-06-25-update-hints-command-design.md`。

## 单一事实源

- 注册表：`mf4_analyzer/ui/hints.py` —— `_HINTS`（persistent/discovery/context/
  anchor 四种 surface）+ `_FLASH_TIPS`（事件一次性提示）。
- 系统设计：`docs/superpowers/specs/2026-06-01-chart-hint-system-design.md`。
- 守卫测试：`tests/ui/test_hints.py`（宽度预算 + mode 过滤 + 持久化）。

## 门槛：只管「非自明交互」

补提示的是**看不出来、想破头也不知道**的操作：

- 修饰键手势：`Alt/Option/Ctrl/Shift + 点击 / 拖拽 / 滚轮`。
- 右键菜单动作（图表、左侧通道树、预设槽…）。
- 框选 / 橡皮筋 / 拖拽手势、双击重置、点击取样（点曲线选源、点谱图取切片）。

**不补**：带可见文字的普通按钮 / 菜单、已在 tooltip 里给出快捷键的项（自明）。

## 流程

1. **定范围**：`git log --oneline -30`，并扫 `docs/superpowers/specs/` 与
   `docs/superpowers/plans/` 里新/改的设计文档。**全量核对**，不依赖标记文件。
2. **枚举交互点**（grep，read-only）：
   - 修饰键：`event.modifiers()`、`AltModifier`、`ControlModifier`、
     `ShiftModifier`、`Qt.Alt`。
   - 右键：`_on_context_menu`、`addAction(`、`customContextMenuRequested`。
   - 手势：`RectMode`、`框选`、`mouseDoubleClick`、`mousePress`/drag handler、
     点击取样（`pick` / `选为` / `切片`）。
3. **比对注册表**：每个交互点，看 `_HINTS` / `_FLASH_TIPS` 是否已有对应
   **交互**（按行为比，不只看 id）。
4. **分类**：
   - **缺失**：交互存在、无提示 → 拟新增。
   - **过期**：提示文案描述的行为已变（对照 spec / 代码）→ 改文案，**id 尽量
     不变**（避免动 wiring / 测试）。
   - **在途**：spec 有、功能未落地 → 用 `ship="later"` 预置草案（处处不显，
     功能落地时下次运行翻 `ship="now"` + 接 retire 事件）。
5. **起草**（守约定）：
   - 选 surface：`persistent`（普适常驻）/ `discovery`（一次性「有此能力」，配
     `retire_on` 事件）/ `context`（按 mode 门控、轮播）/ `anchor`（基础手势，
     长驻）。
   - 设门控：`modes` / `plot_modes` / `cursor_modes` / `mouse_modes` /
     `chart_kinds` / `requires`。
   - 领域：用户分析 **EPS（电动助力转向）**，阶次 base = 电机转速；示例信号用
     EPS 名（方向盘扭矩 / 电机转速 / 电机扭矩），别用 engine。
   - Mac/Win 修饰键并列写 `Option/Alt`。
   - **宽度**：文案 ≤ `HINT_MAX_WIDTH`（18 全宽单位），逐条用
     `hints.hint_display_width(text)` 验（CJK / 全宽标点计 1；ASCII / 空格 /
     `·` / `→` 计 0）。
6. **报候选给用户**：列 `[分类] id · surface/门控 · 文案（宽度 N）· 理由`，
   等用户确认 / 改文案。
7. **写回**：改 `mf4_analyzer/ui/hints.py`；若动了不变量（如 ship / surface
   语义）同步 `tests/ui/test_hints.py`。
8. **验证**：`pytest tests/ui/test_hints.py`（必须全绿，尤其宽度预算）。
9. **汇报**：列实际改动 + 测试结果 + 仍 `ship="later"` 待落地的项。

## 注意

- 优先**改现有提示**而非加重复条目。
- 别动测量算法 / 非提示代码；只碰注册表 + 其测试。
- 项目在 `~/Downloads` 时 Bash 可能 EPERM（macOS TCC）—— 测试若被挡，请用户
  用 `! pytest tests/ui/test_hints.py` 或给终端授 Full Disk Access。
