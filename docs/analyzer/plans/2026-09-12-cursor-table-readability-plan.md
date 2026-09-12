# Cursor 表格对齐与受限宽度实施计划

> 历史执行记录：本文件的完成声明不代表最新截图缺陷已修复。当前范围与执行状态以[全模式排版修复计划](2026-09-12-cursor-rendering-parity-repair-plan.md)和修订 spec 为准。

- 日期：2026-09-12
- 状态：T0–T3、T5 已完成（2026-09-12）；T4 的 offscreen 自动门禁已完成，macOS 前台与 Windows 缩放验收仍为 UNKNOWN。
- 规格：[cursor-table-readability-spec](../specs/2026-09-12-cursor-table-readability-spec.md)
- 阅读基线：`82948f02`。初始未跟踪项为前一轮 HTML 与无关 `ssh-keygen`；保留后者，不参与本任务。
- 执行方式：同一实施者顺序推进；没有独立并行任务，不调度子代理。

## 1. 最终交付物与验收目标

默认采用共享的“名称整行 + 对齐数值”表格，按所属 canvas 的可用空间才降为“每行两项”。宽宿主只提供上限，面板按数值网格的真实所需宽度收缩；不依赖横向滚动，不无限撑宽，不自动关指标或切 mini。

完成条件是 spec A01–A10 的必要证据齐全，尤其是：实际文本列对齐、pane 独立边界、primary 不超宽、64 开关组合、无 tooltip 回退、拖动期间宽度稳定。不能只提交 CSS/HTML 近似稿或一张宽屏截图。

本次文档交付无需 runtime suite：尚未改可执行逻辑；仅做路径、符号、合同一致性、差异范围与 whitespace 检查。下列测试均为**未来实施门禁**，不代表本轮已执行。

## 2. 变更文件与所有权

| 文件 | 允许的变更 | 不承担的责任 |
|---|---|---|
| `mf4_analyzer/ui/cursor_display_model.py` | 有默认值的展示字段，保留旧构造及旧 value 字符串 | Qt 对象、字体计算、采样、设置迁移 |
| `mf4_analyzer/ui/chart_stack/cursor_table_layout.py`（新） | 测量值到共享列布局的确定性计划 | widget 创建、文件/source 解析、DSP |
| `mf4_analyzer/ui/chart_stack/cursor_display.py` | 普通双游标 full 表格、单位分离、同一 formatter 的数字文本 | 改单游标/Custom-X 算法、从字符串推算单位 |
| `mf4_analyzer/ui/chart_stack/cursor_pill.py` | 应用预算、primary 换行、共享网格、布局状态/清理、绘制 | 全局/跨 pane 状态管理 |
| `mf4_analyzer/ui/chart_stack/stack.py` | canvas 坐标映射、既有更新入口、resize/split 重新预算 | MainWindow 新状态簇、另建游标信号管线 |
| `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py` | 新表格适配说明与既有 mini/no-tooltip 语义 | 变更分析教程中的计算定义 |
| owner tests / 规格与验证记录 | 语义、真实几何、渲染和平台证据 | 放宽不相关 ratchet 或改历史快照结论 |

不编辑 `CLAUDE.md`、`.claude/`、信号算法、绘图 facade 或全局版本号。若实际实现需要动表外生产文件，先说明直接依赖和必要性，更新计划后再推进；不因旧审计扩大为架构拆分。

## 3. T0 — 冻结 owner 事实与真实字体可行性

**目的**：确认 spec 的 640 / 60% / 360 初值、Qt 富文本列宽控制和 primary 换行是否可实现；先排除 HTML 在 Qt 中失效的风险。

1. 复核 `git status --short`、HEAD 和本任务 owner 文件的差异；保留其他会话修改。读取相关 lessons：圆角子控件像素、Cursor Pill View Apply、Shared Pill Section Gate。旧 lesson 的已迁移代码路径按当前文件复核。
2. 运行受影响 owner 基线：`test_cursor_display_settings.py`、`test_cursor_single_pipeline.py`、`test_cursor_source_labels.py`；不运行 pre-change full suite。
3. 在 `.state/cursor-table/` 建临时真实 `CursorPill` 探针，使用现有应用 QSS、实际 Qt 字体、长信号名和截图的四通道数字。截图只用作显示 fixture，不伪造原始信号与对应统计计算。
4. 量测普通 P=1200/900/800/560/500/360、260×72，以及非等宽左右/上下 split。记录 canvas 映射矩形、pill 外框、primary/detail 宽度、单元格文字右边缘与占用高度。
5. 验证一个 Qt table 能按预算锁定共享列；名称跨列不能挤宽数值列。验证现有 primary 受控片段换行不拆数字、不修改 legacy formatter 冻结输出。
6. 写聚焦失败测试：长名称自然撑宽、primary 先到时溢出、分屏按 stack 而非自身 canvas 预算。测试直接验收用户后果，不断言未来私有 helper 名称。

**输出**：`.state/cursor-table/` 探针与测量；spec R4 初值确认/有证据修订；QLabel/QTextDocument 可行性结论。若 QLabel 无法可靠固定表列，确定 owner 内薄绘制控件的最小替代并更新 T2；不直接换成通用大型 QTableWidget。

**门禁**：既有基线结果如实记录；新增失败 probe 能稳定复现目标约束。真实 Cocoa 数值未确认时状态为 needs calibration，不声称已经满足 A01/A02。此任务不要求整仓测试。

### T0 执行记录（2026-09-12，HEAD 82948f02，工作区无 owner 文件改动）

1. 工作区复核：未跟踪项仅为 4 个本任务文档 + 无关 `ssh-keygen`；owner 文件无差异。定向 lessons 已读（cursor-pill-view-apply、shared-pill-needs-section-gate、rounded-child-widgets-need-pixel-corner-check），对应路径已按当前文件复核。
2. owner 基线：`test_cursor_display_settings.py` + `test_cursor_single_pipeline.py` + `test_cursor_source_labels.py` = **146 passed**（5.48 s）。
3. 探针：`.state/cursor-table/probe_pill.py`（应用 QSS + 全局图表字体 + 真实 CursorPill），输出 `t0_measurements.json`。
4. 测量结论（offscreen、dpr 1.0、SF 系 fallback 字体；**非 Cocoa 标定**）：
   - 当前实现 natural 布局把 pill 撑到 511 px：P=560 时超 Wcap=360、P=1200 时 511≤640 不超；低高度 260×72 整块截断正确（0 通道 + `+4 channels` 摘要）。
   - split 场景复现 spec 缺陷：pill 预算取父级 stack（1184）而非所属 canvas（600→Wcap 360），pill 宽 511。
5. 可行性结论：
   - **E1 共享列宽可行**：单个 QTextDocument `<table>` + `<col width>` + 名称 `colspan` 行，4 个数值列右边缘跨 4 通道完全一致（[68,132,196,260]×4），名称跨列不挤宽数值列。QLabel rich text 路径成立，不需要薄绘制控件。
   - **E2 primary 换行**：`&nbsp;` 黏连的 20 位数字与指数在 300 px 宽下不被拆断；但普通空格处（`· B `）会把标签与值拆到两行——实施时片段必须用不可断分隔（nbsp）把 label 与 value 连成换行单位。
   - `.4g` 值宽包络注意：`-1.234E-05` 为 10 字符，11 px Consolas 下约 66 px，固定列宽需按包络预留（R8），不是按当前值。
6. 聚焦失败测试：`.state/cursor-table/test_t0_constraints.py`，当前 **3 failed / 1 passed**，稳定复现：窄宿主超预算、长 primary 先到溢出、split 按 stack 预算；共享列右边缘对齐（可行性守卫）通过。
7. R4 初值（640/60%/360）维持 spec 原值：offscreen 测量未推翻它们（360 在 560 px 宿主下已能容纳紧凑/分组路径），Cocoa 标定留 T4。

## 4. T1 — 结构化字段与布局计划

**依赖**：T0 的表格渲染路径确定。

1. 在中立 DTO 末尾添加必要的可选展示字段：裸数字的已格式化文本、原单位。旧 `value`、`tooltip_rows`、`qualified_label`、复合 identity 保持。新数据来自 `_formatted` 和原始 unit 字段；不从 value 中拆单位。
2. 新建 `cursor_table_layout.py`，明确输入为 pane 预算、内边距/按钮占位、实际字体测量和启用字段；输出为分组/紧凑布局、列宽及名称显示预算。宽宿主不得切成另一种完整表格结构；不把逻辑像素与设备像素混用。
3. 实现 spec R4/R5；关闭字段从列模型移除；四项全关仍有身份列表。单位不占全表独立宽列。
4. 定义布局周期与数值宽度预留：主机宽高/字体/字段/通道集合/mode 是结构输入；仅值更新不触发缩水和断点振荡。新状态只由 pill 持有，列出初始化与清理点。
5. 新增纯布局测试 `tests/ui/test_cursor_table_layout.py`，包括 1/2/3/4 指标、极长单位/标签、零预算、值宽包络、同名来源与转义。测试可注入测量结果，真实字体测试留 T2/T4。

**owner 门禁**：新布局测试、`test_cursor_display_settings.py`、`test_cursor_source_labels.py`。64 组合继续覆盖全部语义，不把不再适用的 HTML 表行数断言当产品合同；只替换新目标分支的结构断言，保留其他分支的断言。

**边界门禁**：`tests/ui/test_import_boundaries.py`、`tests/test_signal_no_gui_import.py`；确认中立 DTO 无 Qt/renderer 导入。输出为 spec R1–R6 的可执行布局契约。

## 5. T2 — 单表渲染与 primary 共同限宽

**依赖**：T1。

1. `render_cursor_presentation` 仅对 `cursor_mode=dual, x_mode=time, mini=False` 使用新单表；其他投影继续既有路径。
2. 应用共享列宽、一次表头、色标/深色数值/单位辅助行。分组→紧凑的变化保留启用字段顺序；宽度上限不等于表格目标宽度。不要通过多个独立 table 的碰巧相同 sizeHint 冒充共享网格。
3. 将预算用于 primary 和 detail，预留 toggle 空间。普通双游标 primary 使用既有已格式化片段分行；未知 legacy 富文本保持兼容，不引入通用 HTML 猜测器。
4. 路由 `set_primary` 与 `set_display_projection` 的先后更新，避免中间 adjustSize 越界；一次结构化 move 只能写一次 projection，纯测量不调用实际 widget setText 多次。
5. final 布局下做整通道高度选择，包含 primary/表头/摘要；零条时只保留能容纳的摘要。保留 `visible_channel_count` 等兼容行为；禁止只 resize 外框造成内容裁切。
6. 保留 `_clear_content_tooltip`，不为省略名称恢复 title/hover。底板继续由真实 paintEvent 绘制；本轮不调整共享透明度常量来顺带改变 FFT/FRF。

**owner 门禁**：`test_cursor_table_layout.py`、`test_cursor_display_settings.py`、`test_cursor_single_pipeline.py`、`test_cursor_pill_formatting.py`。新增实际 QWidget 测试 `tests/ui/test_cursor_table_geometry.py`，度量文本与单元格边界；浮层宽度正确但文字已裁切属于失败。

**相关现有节点**：`test_cursor_pill_never_attaches_a_content_tooltip`、`test_all_64_options_project_deterministically_without_orphans`、`test_single_move_applies_projection_exactly_once`；`test_chart_stack.py` 的 toggle/pill 圆角与位置节点。

**输出**：spec A01–A06 的聚焦结果，T0 已确认的 Qt 真实渲染路径。未运行应用前台时仍不填写 Cocoa PASS。

## 6. T3 — 所属 pane 边界、resize 与生命周期

**依赖**：T2。

1. 在 ChartStack 把 card/canvas 的已映射可见矩形传给 pill；目标仍是现有 `_update_pill_content`。不重新 parent、不复制一个 coordinator、不把画布引用放进中立 DTO。
2. 主次 pane 均独立预算；分割条拖动、窗口 resize、字体/DPI 变化、首次 show 和 View/snapshot 恢复重新计算。必须找出实际 split resize 信号/事件入口，不能只改外层 `ChartStack.resizeEvent` 后假设分割条也覆盖。
3. `_reposition_one_pill`、拖动 clamp、popover avoid/restore 使用同一 pane safe rect；主动拖动后 top/right 尽量保留，夹紧后不累积误差。
4. 新布局状态在 clear、退出 split、切换 active section、恢复另一 View 时清理或以新结构重算。避免 snapshot 恢复旧像素预算；snapshot 保存用户显示意图，恢复时按当前实际 pane 测量。
5. 保留 off-screen source gate。回归普通 single、Custom-X、FFT/FRF legacy 共享 pill 不被新表格模式污染；不改变 X↑/X↓ 分支数和已计算的 delta。

**owner 门禁**：新 geometry tests、`test_cursor_single_pipeline.py`；现有 `test_split_routing.py`、`test_split_per_pane_controls.py`、`test_pill_switch.py`，以及 `test_chart_stack.py` 中 user anchor、secondary clear、off、narrow、copy/composite 相关节点。

**边界门禁**：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`。若没有新增 pg_canvas 写入，不无条件重跑 backref；若出现这类写入，先说明必要性，再加 `test_pg_canvas_backref_invariants.py`。不能扩大 whitelist。

**输出**：spec A06/A07/A09，含 70:30 左右分屏和上下分屏拖动证据。几何记录必须同时包含 stack、canvas、safe rect，避免测错对象仍通过。

## 7. T4 — 真实视觉与稳定性校准

**依赖**：T3 稳定代码快照。此任务为单一实施者的视觉门禁，不发起 full suite。

1. 运行新 geometry/layout owner tests，确认 spec A01–A08。对所有 fixture 的外框/文字 bounds 做自动比较；收集小量代表截图，不把几十张图交给用户逐个找错误。
2. macOS 实际 TraceLab 前台验证宽图、560 窄图、非等宽 split；长名称、缺失值和混合单位至少覆盖一次。保留真实后显示几何、最终字形宽度和角像素。真实 Cocoa QWidget 探针与前台 TraceLab 记录分列。
3. 连续 100 次更新，记录投影写入次数、布局切换次数、列边缘变化、总展示更新耗时分布；同一格式包络内列边缘不跳动。记录前后相同 fixture 成本，不设无依据的时间门槛，不声称 HTML 性能证明 Qt 性能。
4. Windows 100%/150%/200% 验证字体 fallback、数据/单位完整性、边界和分割拖动。没有 Windows 环境时明确 UNKNOWN；源码和 offscreen 均不能替代。无需为本次 UI 改动主动构建新发布包，Full/Lite frozen 验收仅在另有发布任务时追加。
5. 验证 copy-as-image 与 presentation capture：新表格仍出现在图像中，缩放只做一次，透明圆角没有矩形底板。相关 owner tests 位于 `test_chart_stack.py` 的 compositing/capture 节点。
6. 若 640/60%/360 或列宽初值被真实字体证据推翻，记录原因并修订 spec R4，再修改实现并只重跑受影响门禁；不静默调参。

**输出**：按需要创建 `docs/analyzer/verify/2026-09-12-cursor-table-readability.md` 汇总证据；原始截图和临时性能日志留 `.state/cursor-table/`，不自动纳入 Git。记录运行 HEAD/相关 dirty scope，期间变更则相应结果 UNVERIFIED。

## 8. T5 — 文案、有限集成与交付

**依赖**：T4；平台 UNKNOWN 不伪装关闭。

1. 同步 `hints.py` 与 `quickref.py`，说明表格随空间分行、`−/+` 保持用户选择、面板不显示 hover tooltip。保留 quickref 字数约束；不沿用原型中“B 推荐”或 hover title 的行为。
2. 运行 `tests/ui/test_hints.py`、`tests/ui/test_quickref.py`。运行一次尚未覆盖的相关边界：QSS 改动才加 `tests/ui_kit/test_qss_border_shorthand.py`；绘制/调度改动加现有 paint-timer backstop，实际节点执行前用 `--collect-only` 解析。
3. 聚焦 owner 与适用边界已在同一稳定快照通过时复用结果，不重复全组。不会因 UI 改动运行全部 `tests/ui`，不会默认跑完整 suite。若后续明确要求 release/merge gate，另行指定单一全量负责人并按仓库双进程顺序执行。
4. 检查 `git diff --check`、必要文件范围、相互链接、临时状态清理与 lesson status。只在产生本任务的新持续性经验时标记/晋升；不清除别的任务遗留 lesson requirement。
5. 更新 spec / plan / verify 状态：实现结果、owner 证据、未跑平台各自列明。完成文档/代码不自动意味着 commit/push 获得授权；后续发布请求再按 named-path scope 执行。

**输出**：可评审的最小 patch、中文结果与仍开放的真实平台门禁。

## 9. 命令与执行约束

owner 测试命令基例（未来执行）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_cursor_display_settings.py \
  tests/ui/test_cursor_single_pipeline.py \
  tests/ui/test_cursor_source_labels.py -q
```

新测试文件在对应任务创建后再加入命令；不可把尚不存在的节点记成已通过。每次选用 `test_chart_stack.py` 具体节点时，用当前源码/collection 验证节点存在；不要为了方便把该文件之外所有 UI 测试加入。

所有 test widget 明确 parent/qtbot owner；需要 top-level 的探针关闭后排空 deferred delete。性能测量使用独立稳定 fixture，不能污染用户 QSettings。若基线出现顺序相关异常，先检查 fixture closure/隔离问题，不加 sleep、xfail 或固定排序掩盖。

## 10. 对照表与升级条件

| Spec 合同 | 主要实施任务 | 证据 |
|---|---|---|
| R1/R2，共用列/单位/数值 | T1/T2 | DTO/64组合、布局单测、真实文字列边缘 |
| R3/R4，pane边界/预算 | T0/T3/T4 | 映射后的矩形、不同宽度/缩放/分屏 |
| R5/R6，降级/长标签 | T1/T2/T4 | 两结构、一项回退、无 tooltip、无半值裁切 |
| R7，primary | T0/T2 | primary先到、长数字、零区间、toggle间隙 |
| R8，稳定性/高度/锚点 | T2/T3/T4 | 100次更新、整块摘要、resize/restore/avoid |
| A09/A10，兼容/平台 | T3/T4/T5 | legacy冻结、Custom-X、capture、独立平台状态 |

只有下列事实需要升级范围或修订设计：

- 解决宽度必须改变计算、丢弃启用值或恢复 hover；这超出本规格，先报告具体反例。
- 自适应实现需要让 `pg_canvas` 依赖 chart-stack/Qt DTO，或增加 MainWindow 跨文件裸写；先改 owner 方案。
- 分屏中已映射区域无空间同时容纳弹层与 pill，或者无法在不改变产品语义下保留 primary；记录精确尺寸和不可满足条件，再调整明确的降级规则。
- Qt 渲染后文字越界、异常退出、测试超时均不能按“看上去已经对齐”放行。平台缺证据可交付实现并标 partial，但不能写成最终视觉验收完成。

## 11. 实施与验证记录（2026-09-12）

- T1/T2：新增中立 `cursor_table_layout.py`，Time-X 双游标 full 使用一次表头、共享数值列和单位辅助文本；主读数也受所属面板宽度限制。single、Custom-X、FFT/FRF 保留既有渲染路径。
- T3：`ChartStack` 将每个 canvas 的可见矩形映射为独立 safe rect；分割条拖动后两侧 pill 各自重算预算。分屏重绘保存当前主 pill，并让仅发 legacy 信号的调用方在结构化 rows 未到时延后一轮补 detail；rows 到达则取消兜底，保持一次结构化投影写入。
- T5：已同步 `hints.py` 与 `quickref.py`，说明双游标在窄图分行、每个 pane 独立边界、`−/+` 与无 hover tooltip。
- 自动证据：offscreen Qt 聚焦 UI 门禁 **364 passed, 214 warnings**，另有 100 次值更新稳定性节点 **1 passed**；图表 pill/copy/compositing 节点 **20 passed**；导入边界 **11 passed**。详见 [验证记录](../verify/2026-09-12-cursor-table-readability.md)。
- 未替代的接受门槛：未运行 macOS 前台 TraceLab，也未运行 Windows 100%/150%/200% 缩放验证；两者均为 UNKNOWN，不以 offscreen 结果替代。
