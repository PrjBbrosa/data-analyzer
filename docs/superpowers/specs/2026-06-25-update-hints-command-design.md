# /update-hints 命令 + hint 注册表维护 设计

**日期**：2026-06-25
**状态**：已确认设计，执行中
**改动面**：新增 `.claude/commands/update-hints.md`（项目内命令）；
`mf4_analyzer/ui/hints.py`（zoom.guard 文案、ship 过滤、共轴预置）；
`tests/ui/test_hints.py`

## 背景 / 问题

UI 交互迭代快（最近 overlay 框选 Y、即将的共轴组…），且很多操作是「想破头也
没人知道」的隐藏交互（Alt 拖曲线、右键设左轴、框选缩放）。提示文案集中在
`mf4_analyzer/ui/hints.py` 的 `_HINTS` 注册表里，但**没有机制保证新交互被补进
提示** —— 提交一多就更新不过来。

## 目标

1. 把「核对新交互 vs 提示注册表、补/改提示」做成**可重复手动触发**的项目内
   命令 `/update-hints`。
2. 首次运行即清积压：修过期的 `zoom.guard`、预置「共轴组」提示。

## 非目标（YAGNI）

- 不做定时云端 agent、不做提交时强制守卫测试（日后可作为补充层再加）。
- 不做全局命令（仅项目内，随仓库走）。
- 不覆盖自明交互（带可见文字的普通按钮 / 菜单 / 已有 tooltip 的快捷键）。

## 触发模型 + 门槛（已与用户确认）

- **触发**：手动 `/update-hints`，想更新时跑一次；Claude 全量核对 + 起草，
  用户审核确认。
- **门槛**：只覆盖**非自明交互** —— 修饰键（Alt/Ctrl/Shift + 点击/拖拽/滚轮）、
  右键菜单动作、框选/拖拽手势、双击、点击取样等「看不出来」的操作。

## `/update-hints` 命令流程（命令文件 = 固定 checklist）

1. **定范围**：读最近提交 + `docs/superpowers/specs|plans/` 下新/改的设计；
   **全量核对**（不依赖标记文件，自愈、抗漏）。
2. **枚举非自明交互点**（grep，read-only）：`modifiers()/AltModifier/
   ControlModifier/ShiftModifier`、`_on_context_menu/addAction`、
   `RectMode/框选`、`mouseDoubleClick`、拖拽/点击取样 handler。
3. **比对**：每个交互点看 `_HINTS` + `_FLASH_TIPS` 是否已有对应**交互**
   （按行为比，不只看 id）。
4. **分类**：缺失 / 过期（文案与现行为不符）/ 在途（spec 有、功能未落地 →
   `ship="later"` 预置）。
5. **起草**（守约定）：选 surface/tier/mode 门控/retire 事件/priority；
   **文案必须 ≤ `HINT_MAX_WIDTH`（18 全宽单位）**，逐条用
   `hints.hint_display_width(text)` 校验。
6. **报候选给用户审核**（理由 + 文案 + 宽度），确认后写回 `hints.py`，
   必要时同步 `test_hints.py`。
7. **验证**：`pytest tests/ui/test_hints.py`（宽度预算 + 过滤必须全绿）。
8. **汇报**：列实际改动 + 测试结果 + 仍 `ship="later"` 待落地的项。

## 首次运行的具体改动

### 1. 过期修正：`zoom.guard`

- 旧：`框选缩放时，拖框优先于选择曲线`（旧「拖框优先于选曲线」守卫语义）。
- `c87de0fb` 后行为变了：overlay 框选 **X/Y 同缩、所有通道各自按比例调 Y、
  不需选中通道**（见 `2026-06-24-overlay-box-zoom-y-all-channels-design.md`）。
- 新：`框选 → X/Y 同缩 · 各通道按比例缩 Y`（id 不变，仅改文案，避免动 wiring）。

### 2. 在途预置：共轴组（`ship="later"`）

- 功能未实现（仅 `24d0ce7e` 计划 +
  `2026-06-24-overlay-shared-axis-and-channel-indent-design.md`）。交互：overlay
  下 `Ctrl/Shift 多选通道 → 右键「合并为共轴」→ 组内共享一根 Y 轴 + ①②③ 徽标`。
- 预置两条 `ship="later"`（overlay + time 门控）：
  - discovery `coaxis.merge`：`多选通道右键可合并为共轴比幅值`
  - context `coaxis.gesture`（tier A）：`Ctrl/Shift 多选通道，右键合并为共轴`
- 文案在功能落地时由 `/update-hints` 下次运行定稿，并把 `ship` 翻 `now` +
  接 retire 事件（`axis_group_menu`）。

### 3. 配套必修：`ship="later"` 应在**所有** surface 隐藏

- 现状：`discovery_hint` 过滤 `ship=="now"`，但 `context_hints` /
  `rotation_hints` **不过滤 ship** —— 预置的 context 提示会照常进轮播。
- 修：抽 `_is_shipped(hint)`（`ship == "now"`），三处统一调用。语义统一为
  `ship="later"` = 已登记、处处不显，直到翻 `now`。对现有全部 `ship="now"`
  提示**行为不变**。

## 测试（TDD）

- `zoom.guard` 文案：不再含旧「优先」语义、提及「通道」；仍 ≤18 宽（既有
  budget 测试覆盖）。
- 共轴预置：`coaxis.merge` / `coaxis.gesture` 存在且 `ship == "later"`；
  overlay+time 下 `discovery_hint` / `context_hints` / `rotation_hints` 均
  **不返回**它们（验证 ship 处处隐藏）。
- 既有 `test_context_hints_filter_by_mode_and_tier_priority`（overlay 仅
  `overlay.drag_y`）天然守住「`ship=later` 的 `coaxis.gesture` 不漏进 context」。

## 涉及文件

- `.claude/commands/update-hints.md`（新，项目内命令）
- `mf4_analyzer/ui/hints.py`
- `tests/ui/test_hints.py`
- 本 spec
