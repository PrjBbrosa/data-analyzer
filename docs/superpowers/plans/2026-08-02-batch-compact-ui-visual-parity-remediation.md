# 批处理紧凑 UI —— HTML 视觉对标修复计划

**日期：** 2026-08-02
**状态：** 已实施；Qt 离屏矩阵 PASS，macOS 前台验收未执行
**Supersedes：** `docs/superpowers/plans/2026-08-01-batch-compact-ui-redesign.md`
中关于视觉实现、几何验收和“已完成”的部分；原计划的行为/接线任务继续作为历史实现依据。
**Governing Spec：**
`docs/superpowers/specs/2026-08-01-batch-compact-ui-redesign-design.md`
**视觉基准：**
`docs/analyzer/ui-prototypes/2026-08-01-batch-compact-ui-redesign.html`

## 1. 修复目标

保留当前分支已经完成并通过目标测试的业务接线：共享单次分析预设、dirty 取消选中、
方法正确的 `time_range` / dB 归属、固定 XLSX/PNG 输出、runner 生命周期和 XLSX 分 sheet。
重新实现 BatchSheet 的可见层级，使真实 Qt 渲染在 1080×760 与 1440×900 下与 HTML 的
信息架构、密度、对齐、卡片状态和滚动行为一致。

本计划不以“控件存在”“对象名一致”或 pytest 绿色作为视觉完成证据。完成必须同时具备：

1. HTML 可见动作与 Qt widget/state transition 一一映射；
2. 关键尺寸由测试约束；
3. 每个主要状态有真实 QSS 的 Qt 离屏截图；
4. 执行者实际打开截图并逐项判定；
5. macOS 前台结果与离屏结果分开报告。

## 2. 设计方向

### 2.1 产品与受众

- 产品：TraceLab 工程测量文件批量分析配置器。
- 用户：需要一次核对“数据源—分析方法—产物”的试验/标定工程师。
- 单一任务：在一个窗口内快速确认批处理配置，然后安全运行。

### 2.2 视觉令牌

直接继承 HTML，不另造一套主题：

| 角色 | 色值 |
|---|---|
| 主文字 | `#172033` |
| 次级文字 | `#64748b` |
| 边框 | `#dbe4ef` / `#c8d4e3` |
| 输入蓝 | `#1769e0` |
| 分析绿 | `#0ea875` |
| 输出橙 | `#ef8c00` |
| 分析/输出弱底色 | `#fcfefd` / `#fffdfa` |

- 正文：系统 UI 字体（macOS 优先 PingFang SC / SF Pro Text）。
- 数据摘要：等宽字体（SF Mono / Menlo fallback）。
- 常规控件高 36 px；圆角 8–9 px；卡片仅使用细边框和选中填充，不增加阴影堆叠。

### 2.3 布局与标志性元素

```text
┌─ 50 工具栏 ───────────────────────────────────────────────┐
├─ 62 流水线：INPUT 29% │ ANALYSIS 39% │ OUTPUT 32% ───────┤
│  输入滚动区           │ 分析滚动区      │ 输出滚动区          │
│  文件/目标/预处理      │ 方法/波形或预设  │ 导出/坐标范围         │
├─ 54 状态/任务事实/进度/动作 ──────────────────────────────┤
└───────────────────────────────────────────────────────────┘
```

本界面的标志性元素只有一个：三张“图片如何合并”波形卡。它们必须通过 `F`/`S` 标签、
多坐标框或叠加曲线直接解释分组语义；其他区域保持安静、紧凑，不添加无关装饰。

### 2.4 允许的 Qt 微调

- macOS 红黄绿窗口控制继续由原生窗口框架负责，不在内容区伪造。
- Qt 字体度量、焦点框和原生滚动条允许 ±4 px 微调。
- 1080 宽度可隐藏分组/预设副说明，但标题、波形、数量公式和选中态必须保留。
- 所有微调都必须写入最终 evidence，不能用来改变布局层级或恢复已删除 section。

## 3. 当前失败基线

当前 `/tmp/tracelab-batch-compact-ui-proof-output` 离屏图只证明结构可渲染，不能作为
HTML 对标 PASS。已确认的失败包括：

- 根布局仍有 18 px 外边距和 14 px 栏间空隙，三栏不是 HTML 的连续分割面；
- pipeline 仍是三张高边框卡，不是 62 px 扁平编号摘要条；
- 分组卡只有直线草图且最小高 94 px，缺少坐标框、F/S、公式和解释；
- 预设是普通按钮，缺少 61 px 卡片及参数摘要；
- 参数仍为单列 `QFormLayout`，1440 下信息密度明显低于 HTML，且出现标签/控件挤压；
- Output 坐标组被显式扁平化，和 HTML 的有边框坐标卡方向相反；
- 文件管理器仍是大空白旧列表；
- footer 为 48 px，内容顺序和 HTML 的 54 px 状态栏不一致。

## 4. HTML → Qt 操作/状态映射

| HTML 表面 | Qt 责任 | 必须证明的状态 |
|---|---|---|
| 50 px title/toolbar | `BatchSheet` header host | 默认、不可同步、导入/导出按钮 |
| 62 px pipeline | `PipelineStrip` | 文件/信号、方法/分组或预设、输出事实 |
| 文件摘要卡 | `InputPanel` | 空、就绪、部分异常、打开管理器 |
| 文件管理 modal | `InputPanel` + authoritative `FileListWidget` | 路径、探测状态、移除、添加入口 |
| 方法 tabs | `AnalysisPanel` / `MethodButtonGroup` | 四方法 active 切换 |
| 三张波形卡 | `_GroupingCards` | task/source/signal + layout enabled/disabled |
| 四张预设卡 | `AnalysisPanel` | applied、dirty、disabled、自定义空槽 |
| 参数双列网格 | `DynamicParamForm` | FFT、FFT vs Time、Order 不同字段和滚动 |
| 固定导出卡 | `OutputPanel` | data-only/image-only/both/both-off |
| 坐标范围卡 | `OutputPanel` | time 无 dB；谱方法有 dB；Z 仅热图方法 |
| 54 px footer | `BatchSheet` status presenter | valid、blocked、running、cancelling、completed |

## 5. 分阶段执行

### Phase 0 — 计划与红色视觉合同

**Files**

- `docs/superpowers/plans/2026-08-02-batch-compact-ui-visual-parity-remediation.md`
- `task_plan.md`
- `findings.md`
- `progress.md`
- `tests/ui/test_batch_compact_contract.py`
- `tests/ui/test_batch_smoke.py`
- `tests/ui/test_batch_method_buttons.py`

**工作**

- [x] 保存当前 1080/1440 Qt 失败基线并记录偏差。
- [x] 写出本 superseding plan，保留原 Spec 与行为边界。
- [x] 为 50/62/54、0 栏间距、29:39:32、panel 背景、132 px 波形卡、61 px 预设卡、
  有边框 axis card、结构化 modal 添加 RED-first 几何/内容合同。
- [x] 红测只证明当前视觉未实现，不修改业务结果断言。

**Gate：** 新视觉合同在旧实现上按预期失败；既有行为合同保持绿色。

### Phase 1 — 窗口骨架、流水线与三栏表面

**Files**

- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/ui/drawers/batch/pipeline_strip.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_smoke.py`

**工作**

- [x] root 内容外边距改为 0；header/pipeline/footer 固定 50/62/54。
- [x] toolbar host 自带左右 14–18 px 内边距，按钮 32 px 高；保持原生窗口标题栏边界。
- [x] `PipelineStrip` 改成三段连续平面，使用 24 px `01/02/03` 色块和一行事实。
- [x] detail HBox spacing=0；通过边框而非空白分栏。
- [x] 三个 scroll pane 使用 HTML 对应背景和 16/18 px 内容 padding；滚动内容保留
  `QSizePolicy.Minimum`，footer 永远不进入滚动区。
- [x] 1080/1440 都断言分割点误差 ≤6 px，最长 `FFT vs Time` 文案不裁切。

**Gate：** 先生成 shell-only 1080/1440 截图；分栏、固定行和背景通过目视后进入 Phase 2。

### Phase 2 — Input 摘要与结构化文件管理器

**Files**

- `mf4_analyzer/ui/drawers/batch/input_panel.py`
- `mf4_analyzer/ui/drawers/batch/file_list.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_input_panel.py`

**工作**

- [x] 主界面文件卡加入文件图标、数量/共同信号摘要、就绪/异常 pill；遵循 Governing
  Spec §3.1 的单行摘要上限，不在主栏恢复文件 chip 或大列表。
- [x] 状态文字完全来自 `FileListWidget`/source registry；不使用 HTML 示例常量。
- [x] 管理器改为 540 px 级 modal：header facts、添加动作、结构化文件行、路径、探测状态、
  删除动作；继续复用同一 authoritative file model，不重复探测。
- [x] 空/失败/部分就绪状态有截图与测试；关闭 modal 后 pipeline/信号宇宙即时更新。

**Gate：** main file card 与 modal 两张截图目视通过；添加/移除/探测现有测试绿色。

### Phase 3 — Analysis 波形卡、预设卡与参数密度

**Files**

- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_method_buttons.py`
- `tests/ui/test_batch_compact_contract.py`

**工作**

- [x] `_GroupingCard` 自绘完整卡片：radio、标题、52 px 波形区域、F/S 标签、动态数量公式、
  解释文字；task/source/signal 三图形不依赖说明即可区分。
- [x] 张数通过真实逻辑源数/信号数注入；保持 `none/source/channel` schema。
- [x] 预设卡改为 61 px 左对齐 title+summary 卡；1080 compact mode 为 38 px 并隐藏
  summary；applied/dirty/disabled 均有独立视觉。
- [x] `DynamicParamForm` 从单列 form 改为 2 列字段网格，label 在控件上方；full-width 字段
  只用于确实需要整行的项。保持现有 widget 对象和参数读写 API，避免逻辑重写。
- [x] FFT 的源数据区间作为参数网格最后一整行；FFT vs Time/Order 不占隐藏空行。

**Gate：** time task/source/signal、FFT applied/dirty、FFT/heatmap 参数态截图全部通过。

### Phase 4 — Output 导出卡与坐标范围卡

**Files**

- `mf4_analyzer/ui/drawers/batch/output_panel.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_output_panel.py`
- `tests/ui/test_batch_compact_contract.py`

**工作**

- [x] 输出目录与导出内容按 HTML 两行布局；导出复选框和固定事实进入一张 bordered card。
- [x] 反转旧 `_flatten_axis_group_chrome()` 的无边框方向，建立 bordered `axis-card`：header、分隔行、
  auto/全时段、min/max、单位、副说明。
- [x] time 隐藏 dB 和 Z 且不留 geometry；FFT 显示 dB+X/Y；FFT vs Time/Order 显示
  dB+X/Y/Z。
- [x] 输出摘要只保留一行；不恢复格式、尺寸、冲突、恢复或输出预览 section。
- [x] 现有 `_axis_row_parts`、dB resolver 和 `get_outputs()` 继续作为逻辑权威。

**Gate：** time/FFT/FFT-vs-Time/Order 坐标卡截图与既有 recipe/output tests 同时通过。

### Phase 5 — Footer 状态投影与响应式细化

**Files**

- `mf4_analyzer/ui/drawers/batch/sheet.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_runner_thread.py`
- `tests/ui/test_batch_smoke.py`

**工作**

- [x] footer 固定 54 px，顺序为状态点/文本、任务事实、进度条、关闭/运行或取消动作。
- [x] idle-valid/blocked/running/cancelling/completed 使用同一 presenter；不从 label 反推状态。
- [x] 1080 compact mode 收紧 panel padding并隐藏允许隐藏的副说明；1440 保持 HTML 密度。
- [x] 三栏各自可滚到最后控件，footer 不移动；无水平滚动、重叠和标签压住控件。

**Gate：** 六种 footer 状态测试绿色；1080 最长页面滚动可达。

### Phase 6 — 离屏矩阵、目视循环与回归

**Files**

- `tools/render_batch_compact_ui.py`
- `tests/ui/test_batch_compact_render.py`（需要时新增）
- `/tmp/tracelab-batch-compact-ui-proof-output`（临时证据，不提交）
- `findings.md`
- `progress.md`

**工作**

- [x] probe 使用临时 QSettings/XDG 路径、固定 Qt platform/DPR=1、真实 API 状态切换。
- [x] 生成 1080×760：time task/source/signal、file modal、FFT applied/dirty/range、
  FFT-vs-Time、Order、blocked/running/completed。
- [x] 生成 1440×900：time、FFT、heatmap、running 总览。
- [x] 输出 geometry JSON，包含 fixed rows、栏宽、scroll reachability、卡片/控件尺寸和文字
  content rect。
- [x] 主执行者实际打开每张图；任一 FAIL 回到所属 Phase 修复并重跑完整矩阵。
- [x] 运行 directed UI/core tests、完整 batch cluster、Inspector preset tests、
  `git diff --check` 和 lessons gate。

**Gate：** PASS。最终矩阵含 24 张 PNG / 22 个 sheet 状态 / 2 个 modal 状态；完整
batch 集为 `735 passed, 1 baseline failed`，同一失败已从干净 `HEAD` 归档单独复现；
Inspector 集 `221 passed`。macOS 前台验收仍单独标为未执行。

## 6. 不变量与禁止项

- 不修改 BatchRunner 的 GUI-free 边界，不重写数值算法或渲染器。
- 不删除后端 CSV/resume/retry 兼容能力，只保持它们不出现在默认 BatchSheet。
- 不把 HTML 示例文件、计数、路径或参数写成产品常量。
- 不以 QSS token、objectName、结构测试或另一位 agent 的结论替代截图目视。
- 不污染真实 QSettings；render probe 的用户状态必须在运行前后保持不变。
- 不提交 `/tmp` 截图、绝对用户路径或无关 `.playwright-cli` 产物。
- 不在用户未要求时提交、推送或合并。

## 7. 完成定义

只有同时满足以下条件才可结束本计划：

1. HTML→Qt 映射表中的每个表面都有实现、交互测试和至少一个截图状态；
2. 50/62/54、29:39:32、连续分栏、卡片高度及文字可见性有机器断言；
3. 分组波形、预设、参数网格、文件 modal、axis card 与 footer 在截图中达到 HTML 层级；
4. 1080×760 和 1440×900 矩阵由主执行者实际打开并记录 PASS；
5. 当前分支既有行为回归绿色，无新增 batch/Inspector 失败；
6. 离屏证据与 macOS 前台证据分别报告；
7. 工作树范围审查完成，但不自动 commit/push。
