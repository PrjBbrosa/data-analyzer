# 批处理通道选择与图片输出视觉优化 Implementation Plan

> 状态：IMPLEMENTED / OFFSCREEN VERIFIED（2026-08-01）
>
> 视觉基准：`docs/analyzer/ui-prototypes/2026-08-01-batch-input-output-target.html`
>
> 范围：用户确认的 1/2/3，以及批处理曲线变细；不包含另一个 session 正在处理的自定义横坐标、多文件长度不一致及其扩展场景。

## Goal

把已确认 HTML 的操作模型落到真实 PyQt 批处理链路：

1. 目标信号的搜索输入与已选通道共用原始选择框，popup 只显示候选列表。
2. 多选通道始终限制在控件内部，窄列宽用“有限标签 + `+N`”摘要，不产生横向溢出或随数量无限增高。
3. OUTPUT 默认只显示目录、导出勾选和紧凑摘要；齿轮按钮紧跟“图片”，按需展开完整输出设置。
4. 批处理图片默认白底、浅网格、深色文字，曲线默认 `1.0 px`；背景与线宽可在输出设置中调整并进入 preset/manifest/fingerprint。
5. 最终交付前完成 focused tests、相关 batch tests、真实文件渲染检查与 Qt offscreen 几何/像素检查。

## Approved HTML → PyQt operation map

| HTML 状态/动作 | PyQt 落点 | 验收 |
| --- | --- | --- |
| 原选择框内直接输入 | `SignalPickerPopup._search` 移入 `SignalPickerDisplay` | popup 中不存在第二个搜索框；输入即时过滤候选 |
| 已选通道 chip | 单行响应式 chip 容器 | 长名称按像素省略；窄宽只保留可放下的 chip |
| `+N` 溢出摘要 | `SignalPickerOverflow` 标签 | 20+ 选择时仍不超过 host 宽度；tooltip 可查看隐藏项 |
| 下拉候选勾选 | 保留现有 checkbox 列表与 partial/single-select 语义 | 已选、禁用、搜索、ESC、focus-out 回归通过 |
| “图片”后的齿轮 | `OutputPanel` 中 check row 的 checkable tool button | 默认关闭；点击展开/收起，不改变输出值 |
| 紧凑输出摘要 | 齿轮下方/同区域的 elided label | CSV/PNG、尺寸、背景、线宽可读且不撑宽 288 px 列 |
| 图片设置卡 | 隐藏的 inline settings frame | 保留现有格式、尺寸、custom、DPI、冲突、manifest、resume 操作 |
| 白底细线预览 | `BatchRenderOptions` + `batch_render.py` 主题 | 默认 figure/axes 为白色，文字为深色，曲线为 1.0 px |

## Task 1 — RED tests：原框搜索与多选防溢出

**Files**

- Modify: `tests/ui/test_batch_signal_picker.py`
- Later modify: `mf4_analyzer/ui/drawers/batch/signal_picker.py`

**Tests first**

- [x] 搜索框的父级是原显示框，popup 中没有额外 `QLineEdit`。
- [x] `show_popup()` 后输入直接过滤 `visible_items()`，ESC 仍关闭。
- [x] 288 px 宽、20 个长通道名时：display frame 不超过 picker，chip/overflow/search/arrow 全部位于 frame 内。
- [x] 隐藏选择显示为 `+N`，tooltip 包含隐藏通道；删除可见 chip 后计数与 checkbox 同步。
- [x] 现有 partial unavailable、single-select、selectionChanged 合同继续通过。

## Task 2 — RED tests：OUTPUT 默认收纳与完整 round-trip

**Files**

- Modify: `tests/ui/test_batch_output_panel.py`
- Modify: `tests/test_batch_preset_io.py`
- Modify: `tests/test_batch_validation.py`
- Later modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Later modify: `mf4_analyzer/batch.py`
- Later modify: `mf4_analyzer/batch_recipe.py`
- Later modify: `mf4_analyzer/batch_image_options.py`
- Later modify: `mf4_analyzer/batch_validation.py`

**Tests first**

- [x] 输出设置 frame 初始隐藏，按钮位于“图片”之后；点击只切可见性。
- [x] 收起摘要反映 data/image format、有效尺寸、背景与线宽。
- [x] 288 px 列宽下 checkbox、齿轮与摘要不裁切/不横向撑宽。
- [x] `BatchOutput` 新默认：`image_background="white"`、`image_line_width=1.0`。
- [x] get/apply、preset JSON、旧 JSON migration、recipe fingerprint 全量 round-trip。
- [x] `validate_outputs` 对 Mapping 与 duck object 使用同一规则，拒绝未知背景、bool/非有限/越界线宽；关闭图片时忽略图片字段。

## Task 3 — Implement PyQt interaction

### 3.1 SignalPicker

- [x] 把 `_search` 放入原始显示框；popup 只保留候选状态行和 checkbox list。
- [x] 显示框固定单行高度，按可用像素宽度决定展示 1–2 个 chip，其余汇总为 `+N`。
- [x] chip 文本用 `QFontMetrics.elidedText`，布局只允许在 display frame 内；resize 时重算。
- [x] 搜索、键盘、click-away、remove、single-select、partial-selectable 保持原语义。

### 3.2 OutputPanel

- [x] export row 保留“数据文件 / 图片 / 齿轮”，摘要使用独立 elided label。
- [x] 将 data/image/operation 相关设置移入默认隐藏的 inline frame；轴范围和 dB reference 保持原位置与语义。
- [x] 增加背景和线宽控件；所有 programmatic apply 在 signal blocker 内完成，用户修改仍进入唯一 `changed` 流。
- [x] image disabled/custom/non-PNG 时的 enabled 状态与自定义值保留合同继续成立。

## Task 4 — Output schema and renderer

### 4.1 Portable output contract

- [x] 扩展 `BatchOutput`、`OUTPUT_DEFAULTS`、fingerprint fields、duck-output fallback。
- [x] 扩展 `BatchRenderOptions`，背景支持 `white/transparent/dark`，线宽支持有限数值 `0.5–4.0 px`。
- [x] 所有 grouped/per-task renderer 调用均传递 background 和 line width。
- [x] manifest 的 requested output settings 自动包含新字段；旧 preset 读取采用安全默认值。

### 4.2 Rendering

- [x] 白色默认主题：figure/axes `#ffffff`，主文字 `#273449`，次文字 `#64748b`，spine `#94a3b8`，grid `#d8e0ea`。
- [x] FFT 显式曲线改为 TraceLab blue；Time/grouped curves 保留可区分色轮并统一使用 configured line width。
- [x] subplot title、legend、colorbar、suptitle、facts、footer 全部跟随主题，避免只改画布留下浅色文字。
- [x] transparent 使用透明 figure/axes 与浅色主题文字；dark 保留原有深色可选项。

## Task 5 — Verification and offscreen proof

### Focused tests

- [x] `tests/ui/test_batch_signal_picker.py`
- [x] `tests/ui/test_batch_output_panel.py`
- [x] `tests/test_batch_validation.py`
- [x] `tests/test_batch_preset_io.py`
- [x] `tests/test_batch_renderer.py`
- [x] runner 中 renderer option forwarding 的现有/新增用例

### Related batch gates

- [x] `tests/ui/test_batch_smoke.py`
- [x] `tests/test_batch_runner.py`
- [x] `git diff --check`

### Offscreen proof

- [x] 使用隔离的 `TMPDIR`、`XDG_CONFIG_HOME`、`QT_QPA_PLATFORM=offscreen`，不污染真实 QSettings。
- [x] 渲染 288 px 窄列与 360 px 常规列：20 个长通道时控件不溢出且显示 `+N`。
- [x] 渲染 OUTPUT 收起态和展开态：齿轮位置、摘要、settings frame、底部控件可达。
- [x] 生成真实默认 PNG；用 Pillow 验证四角/figure 背景为白色，并检查 Matplotlib artist `linewidth == 1.0`。
- [x] 人工查看 offscreen 图片，确认没有裁切、叠压、黑底或粗线回归。

## Stop conditions

- 搜索框仍出现在 popup 内：停止交付。
- 任一选中数量或 288 px 列宽可把 picker 撑出 host：停止交付。
- UI 值能保存但 runner 任一路径未传给 renderer：停止交付。
- 只改 figure 背景而标题、坐标、colorbar 仍是浅色：停止交付。
- 仅测试通过但未查看 offscreen 图片：停止交付。

## Dirty-worktree boundary

- 当前已有 `.playwright-cli/*` 未跟踪文件属于既有工作，不删除、不纳入。
- 已确认 HTML 原型保留为本任务设计证据。
- 不执行 commit/push/merge/branch cleanup，除非用户后续明确要求。

## Execution record（2026-08-01）

- Qt batch UI 最终：`183 passed in 8.18s`。
- Batch contract/renderer/runner focused suite 最终：`385 passed in 5.83s`。
- Offscreen proof：`.state/batch-input-output-polish-proof/proof.json`。
- 关键实测：picker `288×38`、1 个可见 chip、`+19`；active search width `247`；OUTPUT 360 px 列的 settings right edge `359`；PNG corner RGBA `[255, 255, 255, 255]`、line width `1.0`。
