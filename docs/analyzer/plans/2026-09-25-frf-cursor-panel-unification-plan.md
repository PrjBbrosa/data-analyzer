# 频响游标面板接入共享展示链路优化计划

- 日期：2026-09-25
- 状态：已按本计划实施（2026-09-25）。活动频响游标接入共享投影；Cocoa 前台与 Windows frozen 仍为 UNKNOWN。
- 分析基线：`main` / `88ca379d`，工作区包含既有启动器、版本、帮助、Inspector 等修改；本文结论来自当前工作树。实施前重新检查 HEAD 和相关文件变更。
- 用户问题：频响页的游标面板为何没有同步更新为新的展示形式。
- 执行方式：顺序实施，不要求子 agent；先固定 FRF 行为，再接入共享组件。

## 1. 结论

**FRF 活动游标仍走 legacy HTML/text，而固定游标已使用结构化展示。这是接入不完整，不是当前证据所能支持的 FRF 计算停更。**

截图中的 `f=… | |H|=… | phase=… | coherence=…` 被整体当作 primary 标题。`CursorPill` 外壳已有“数值／完整”控件，但 FRF 没有提供该控件需要的结构化明细和缓存，因此出现新控件配旧内容。

隔离探针进一步复现双游标缺陷：完整 → 数值 → 完整后，幅值、相位、相干度明细全部消失，重新发送游标读数才会重新填入。单游标改变采样频率时文本会更新；用户原始数据、鼠标事件现场和 Windows 包尚未检查，不能据此排除另一个现场数值刷新问题。

推荐复用现有 `FrfCursorSample → build_frf_cursor_presentation → CursorPresentation → CursorPill`，为活动游标补齐唯一更新入口。保留频响指标语义与当前数值算法，不扩大为全局游标重构。

## 2. 已核实的证据

代码行号对应分析时的工作树；实施时以符号为准。

| 位置 | 当前行为及影响 |
|---|---|
| `mf4_analyzer/ui/pg_canvas/frf_canvas.py:2063`，`set_cursor_frequency` | 从 `_frf_sample_from_index` 取事实，但只发送拼接的 `cursor_info(str)`；四个字段全部在一串普通 ` \| ` 分隔文本中。 |
| `mf4_analyzer/ui/chart_stack/stack.py:2450`，`_is_managed_frequency_canvas` | 只认 `PgLineCanvas`，FRF 没有进入受管理的频域结构化路径。 |
| `stack.py:2454`，`_on_cursor_info`；`cursor_pill.py:300`，`format_single_cursor_variants` | legacy 分割器只认特定 HTML `│` 分隔符；FRF 普通 ` \| ` 不匹配，返回整串 primary 和空 detail。 |
| `stack.py:2532`，`_on_dual_cursor_info`；`cursor_pill.py:1134`，`set_detail_html` | FRF 双游标直接写 HTML，同时清空可重建明细的 rows/full/mini 状态。 |
| `cursor_pill.py:1830`，`set_display_mode`；`:1903`，`_refresh_detail` | toggle 尝试从结构化投影或存储行重建；FRF 两者均没有，旧 detail 被清空。 |
| `stack.py:2654`，`_refresh_cursor_projection` | 依赖 `_cursor_rows_by_canvas`；FRF 未发布结构化读数，缓存缺席，toggle 回调不能恢复。 |
| `frf_canvas.py:1990–2050`，FRF evaluate 方法 | 已有具名、只读的单／双游标事实；无需反解析 HTML，也无需重复 FRF 数学计算。 |
| `cursor_display.py:924`，`build_frf_cursor_presentation`；`pinning/presentation.py:517`，`presentation_for` | 已有幅值／相位／相干度三块结构化展示，但固定游标使用它，活动游标未接入。 |
| `tests/ui/test_chart_stack.py:226`，`test_frf_cursor_toolbar_reuses_the_off_single_dual_controls` | 现有测试明确期待 `coherence=` 留在 primary，只测 off/single/dual，未测 full→mini→full；旧布局被测试保留。 |

历史范围解释：[FFT 接入计划](2026-09-16-fft-cursor-shared-layout-optimization-plan.md)明确只接入 FFT，保留 FRF 既有语义；[固定游标计划](2026-09-18-pinned-cursor-implementation-plan.md)要求 FRF 具名事实和固定展示。当前树验证了二者覆盖范围之间留下的活动 FRF 缺口；这些历史计划不构成本次产品实施授权。

### 2.1 运行时诊断

使用真实 `ChartStack`、生产 QSS、合成三点 FRF 数据、隔离 INI QSettings，窗口 1048×700，Qt offscreen。探针调用真实游标 setter 与模式切换入口，并保存实际 widget 渲染图；未注入修复代码。

| 场景 | 结果 |
|---|---|
| single / full | primary 含全部四字段；detail 空，projection 无，canvas 读数缓存无。 |
| single / mini | primary/detail 与 full 相同，面板尺寸也相同。 |
| single 从 67.5 Hz 改到 100 Hz | 文本数值随新频率更新，说明 setter→信号→面板仍通。 |
| dual / full | 有 legacy A/B/Δ HTML，仍无 projection 和缓存。 |
| dual / mini | 三项明细被清空，只剩 A/B/Δf 标题。 |
| dual 再回 full | 明细仍为空，不能恢复。 |
| 独立调用既有 FRF builder | 已生成 `\|H\|`、`phase`、`coherence` 三块，证明基础展示能力存在。 |

临时证据：`.state/frf-cursor-plan-20260925/probe.py`、`result.json`、`single_full.png`、`single_mini.png`、`dual_full.png`、`dual_mini.png`、`dual_full_again.png`。它们是合成数据的诊断证据，不提交到 Git，不替代截图原始项目验收。

截图上的 P 属于活动面板固定入口，不能与已固定面板曾移除冗余 P 的要求混同。本轮不以截图中的 P 判断版本陈旧，也不删除活动入口。

## 3. 方案比较与选择

| 方案 | 成本与局限 | 决策 |
|---|---|---|
| A：修改分隔符／缓存 legacy HTML | 改动表面上少，但双游标可逆模式、布局预算、固定前后一致性仍分裂；普通 `\|` 与 `\|H\|` 也不能安全作为通用分隔规则。 | 不采用。 |
| B：复用既有 FRF 事实与共享 projection | 补活动发布、路由和缓存，统一 live/pinned 的展示策略，复用现有几何算法；改动集中在事实输出及展示 owner。 | **推荐。** |
| C：重做所有分析游标控制器／重构 MainWindow | 超出当前问题，增加时域、FFT、持久化和输入路由回归面。 | 不采用。 |

范围内：FRF single/dual/off、仅 A 的中间态、数值／完整、固定前后一致性、有效 canvas 路由、生命周期清理和真实布局。范围外：FRF DSP、相位差定义、采样算法、项目 schema、产品版本、全局样式、时频／阶次功能扩展、新的自动告警规则。

## 4. 目标展示与语义

### 4.1 显示规则

| 状态 | primary | 明细 |
|---|---|---|
| 单游标／完整 | `f=67.5 Hz` | 三行：幅值 `\|H\|`、相位 `φ`、相干度 `γ²`，对齐当前值与各自单位。 |
| 单游标／数值 | 相同物理频率 | 三行紧凑读数，仍保留短指标标签 `\|H\| / φ / γ²`，省略长名称。 |
| 双游标仅 A | `A=… Hz` 与“点击 B 选择第二点” | 不显示上一次 A/B/Δ；暂不生成完整双点结果，固定提示沿用“待 B”规则。 |
| 双游标／完整 | `A=… Hz`、`B=… Hz`、`Δf=… Hz` | 三指标 × A、B、Δ=B−A 表格。 |
| 双游标／数值 | 相同 A/B/Δf | 三指标 × Δ 列；保留短指标标签及单位。 |
| off／clear／无有效频率 | 隐藏活动面板 | 清除本 canvas 展示缓存；固定记录按既有独立生命周期处理。 |
| 指标非有限、频率仍有效 | 保留频率 | 对应字段显示 `—`，其余有效字段保留；不将无效值改为 0。 |

FRF 三行是三个不同物理量，不能直接照搬 FFT 的 mini“隐藏全部名称、仅留同色圆点”策略。当前 builder 借用了 FFT projector；接入时必须补 FRF 的短标签策略，不能只加一根信号就宣告完成。

同一个 FRF builder 同时供活动与固定面板使用；主标题和 P/Pn/× 行为仍由各自角色管理。布局控件、字号、圆角及拖动算法继续复用，不新建另一套 FRF 面板。

### 4.2 数值契约

- 频率来自吸附后的事实，始终是 Hz，log 轴不得显示／保存 log10 坐标。
- 幅值和相位来自当前显示变换后的 owner 数组；dB、linear、wrapped/unwrapped 切换后不能混用前一版本事实。
- 幅值单位沿用 `_magnitude_unit_suffix()`；相位用 °，相干度无单位。缺失单位不猜测，不新增传递比定义。
- 差值沿用现有 evaluate 的有符号 B−A；相位不额外包角，相干度差值不变成百分比。
- 注意精度差异：活动 FRF 当前幅值／相位 `.5g`，相干度 `.4g`；通用 `_formatted` 是 `.4g`。FRF projector 应显式保留活动读数精度，正差值保留 `+`；固定 FRF 同步该策略。不得为统一 FRF 改掉 FFT／时域全局精度。
- 空数组、短数组、非有限、shape 不匹配沿用 canvas 现有校验／evaluate 语义；展示层不截断数组、不补采样率、不承担计算修复。

## 5. 更新、归属与几何契约

1. `PgFrfCanvas` 在同一次采样中发布具名事实。建议增加一个 FRF 活动读数信号及小型只读 payload，承载模式、A/B 完整性和 `FrfCursorSample`；已有 DTO 能表达的内容直接复用，只为仅 A／清空状态补必要字段。DTO 保持 Qt-free，不依赖 ChartStack。
2. compatibility `cursor_info` / `dual_cursor_info` 和 public setter 返回字符串继续保留；受管理 FRF 的 legacy 信号不再争写面板。未知 legacy 来源继续可用。不在槽内从字符串提取频率或数值。
3. `ChartStack` 负责可见 section/card 校验、当前 source 和缓存，FRF 复用已有按 canvas 存储／销毁清理边界。必要时最小扩展该缓存记录，避免另建 MainWindow 状态或跨 mixin 写入。
4. 结构化读数每次有效事件仅走一次 `_update_pill_content → set_display_projection`。primary、三指标和固定提示一并应用；FRF 不落入延后一拍的 legacy fallback。不简单扩大 `isinstance` 判断而遗漏配套结构化事件。
5. full/mini 从同一份具名事实重建，不重新运行 FRF 算法，也不要求再次移动鼠标。resize 仅重排，不能触发 FRF 重算。
6. 隐藏 section 发空信号不得清空当前可见面板；pane 切换、删除和 Qt `destroyed` 清理沿用 owner 规则，缓存不得复活已删除 wrapper。关游标／clear 同步失效旧读数，不能在后续 toggle 时回放旧值。
7. 模式变化、重算、显示参数变化遵循当前行为：单游标重绘后暂清空并等下一次有效鼠标读数；双游标从保留位置重新取当前事实。不在本轮暗加单游标位置持久化。固定记录的重新求值继续归 pinning owner。
8. 复用 `frequency_cursor_host_rect()` 现有三图数据区联合边界、8 个逻辑像素 inset 与布局事件；不要复制 FFT 上方谱图专属区域规则。尺寸预算、文档测量和锚点都基于所属 pane。
9. 保持拖动后的 top/right 锚点，toggle、resize、内容重排不能漂移或跨 pane。几何未就绪时遵守现有暂隐／恢复机制，不退回整个主窗口。
10. 常规宽高保证三指标完整。极小空间不得截半个数值或自动改变用户模式；复用受限布局／空间不足机制。若采用剩余块摘要，应在 FRF 中表述为“项指标”，不能显示误导的“channels”。这类措辞差异以显式展示属性传给共享布局，不在数值层识别 UI 文本。

## 6. 实施步骤与验证归属

### T0：冻结事实与建立失败回归

- 检查相关 dirty scope、读取本轮探针；不运行全量基线。
- 在 `tests/ui/test_cursor_single_pipeline.py` 增加 FRF single/dual 每次仅一次 projection 写入、无 legacy detail 写入的用例。
- 新增 `tests/ui/test_frf_cursor_layout.py`（计划文件，当前尚不存在）：真实 ChartStack 的 single full/mini 与 dual full→mini→full、仅 A、off/clear 回归。先验证新断言在修复前失败。
- 更新 `test_chart_stack.py::test_frf_cursor_toolbar_reuses_the_off_single_dual_controls`：primary 只承载频率，三指标从结构化 detail 检查；保留工具栏及三条联动线覆盖。
- 沿用 `test_frf_canvas.py`、`test_pinned_cursor_facts.py` 中的 FRF 数值／单位／非有限／Hz 契约，不把旧字符串布局断言当作目标验收。

### T1：接入活动 FRF 事实和唯一展示入口

- 文件归属：`ui/pg_canvas/frf_canvas.py`（发布事实、清空状态）、`ui/cursor_display_model.py`（必要的中立状态 DTO）、`ui/chart_stack/stack.py`（连接、source gate、缓存、统一 apply）。
- 对单点、完整双点、仅 A、无结果、off/clear 成对发布与清理；完成 legacy UI 竞争隔离。
- focused：新增 pipeline 用例、FRF canvas 的 cursor 用例、`test_chart_stack.py` 的 FRF 工具栏用例。
- 完成标准：改频率时标题／数值同批更新，full/mini 无需鼠标新事件即可恢复，空／隐藏来源不串写。

### T2：统一 live/pinned 的 FRF 指标展示

- 文件归属：`chart_stack/cursor_display.py`（FRF 名称、短标签、精度和 A/B/Δ 投影）；只有现有模型无法表达短标签策略时，局部扩展 `cursor_display_model.py` 和 `cursor_pill.py`／`cursor_table_layout.py` 的展示契约，默认保持其他领域原行为。
- `chart_stack/pinning/presentation.py` 继续使用同一 builder，不再新增第二个 FRF formatter。仅在当前接缝确有需要时修改该文件。
- 三指标采用一致的 full/mini、缺失值及单位策略；标题不重复承载三指标。
- focused：`test_frf_cursor_layout.py` 的格式／几何参数化，`test_cursor_table_geometry.py`、`test_cursor_table_modes.py` 中实际受共享属性影响的用例，以及 `test_pinned_cursor_facts.py` 的 FRF 用例。共享默认值改变时补最小 Time/FFT 对照。
- 完成标准：数值 token 完整可读、角色切换不改数值、短标签可辨、三图同频率。

### T3：生命周期、文案与平台验收

- 验证 Time↔FFT↔FRF、FRF 多 pane、View 恢复、显示变换、固定／取消、复制图像和 UltraView snapshot 对本次改动入口的影响；只扩展触及的用例。
- 提示交互变化同时更新 `ui/hints.py` 和 `ui/quickref.py`，明确 FRF 数值模式保留短指标标签、双游标数值模式看 Δ，以及仅 A 时等待 B。
- 文案 focused：`tests/ui/test_hints.py`、`tests/ui/test_quickref.py`、`tests/ui/test_quickref_status_hints.py` 中受影响的模式和文案契约。
- 路由回归选择 `test_pill_switch.py`、`test_split_routing.py` 和 `test_project_session.py` 中 FRF/游标用例；固定、捕获与恢复从 `test_pinned_cursor_panels.py`、`test_pinned_cursor_geometry.py`、`test_pinned_cursor_capture.py`、`test_pinned_cursor_lifecycle.py` 选择穿过修改 seam 的具体节点，执行前记录 node IDs。
- 边界：`test_import_boundaries.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`；修改 QSS 才加 `tests/ui_kit/test_qss_border_shorthand.py`，触及 backref 声明才加 `test_pg_canvas_backref_invariants.py`。不因改动 FRF 展示而跑全部 `tests/ui`。
- 真实 widget 图像检查须使用生产 QSS 与实际绘制的 QTextDocument，测量数字、单位、标题控件占位及外框，不仅检查 HTML 和颜色字符串。
- Qt 命令：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <focused nodes>`；探针隔离 QSettings，关闭并排空 Qt 对象。
- 单独记录 Cocoa 前台和 Windows frozen 100%/150%/200% 检查结果；缺少环境就记 UNKNOWN，不用 offscreen 代替。
- 最后检查 diff、引用和 lesson status。此范围不要求 full suite；若出现跨模块／测试顺序污染，说明新增原因后再扩大。

## 7. 验收矩阵

| 维度 | 必须满足 |
|---|---|
| single × full/mini | 频率在标题；三指标均在明细；切换可逆，mini 指标可辨。 |
| dual：仅 A／A=B／A<B／A>B × full/mini | 中间态不复用旧 B；Δ 符号与 B−A 一致；完整↔数值重复切换不丢明细。 |
| dB/linear × wrapped/unwrapped × linear/log 频轴 | 单位和读数与当前曲线一致，全部位置为 Hz；不改相位差定义。 |
| 空数据／单点／部分 NaN/Inf／全部无效指标 | 不崩溃、不伪造 0、不回放旧事实；有效频率和有效指标按契约保留。 |
| 1048×700／650×420／低高度／多 pane | 面板在 FRF 所属 safe rect；正常区域三项完整，极小区域明确降级；放大后恢复用户模式。 |
| 字体／DPI／窗口缩放／拖动后 toggle | 实际字形和外框不越界；标题控件不压数值，位置不漂移。 |
| Time↔FFT↔FRF／隐藏 source emits | 无跨域旧 primary／detail；隐藏空事件不擦除当前卡片。 |
| 重算／显示变换／clear／pane 销毁／View 恢复 | 无旧 data revision 内容复活，无已删除 Qt 对象访问；新读数与新曲线一致。 |
| 活动→固定／多个固定／移除固定 | 表格指标、单位和精度一致；P／Pn／× 按现有角色合同工作，无冗余固定 P。 |
| 复制图像／UltraView | 捕获当前展示及模式，无旧 HTML 回退；不把瞬时缓存写入工程。 |

## 8. 本轮交付与证据边界

- 已交付本计划、当前代码链路分析和 offscreen 真实 widget 诊断；计划中各 T0–T3 尚未执行。
- 本轮是文档变更，无需产品回归全套。为验证诊断，运行现有 FRF 聚焦测试，结果为 **7 passed, 15 deselected, 16 warnings，exit 0**；warnings 来自 pyqtgraph 的 NumPy shape 弃用提示。测试覆盖既有工具栏、双点数值、单位和只读事实，未覆盖本轮新发现的模式往返缺陷，不能作为未来修复完成证据。
- 已读取相关 lessons：shared pill section gate、实际绘制文档的几何验收、标题控件占位与 Cocoa polish；这些规则纳入本计划。分析阶段没有新的已验证修复，不另建重复 lesson。
- 用户截图原始项目、Cocoa 前台和 Windows frozen 的目标效果均为 UNKNOWN。临时探针只证明本文列出的更新链路和 toggle 缺陷。

本轮聚焦命令：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_frf_cursor_toolbar_reuses_the_off_single_dual_controls \
  tests/ui/test_frf_canvas.py::test_frf_dual_cursor_reports_frequency_delta_and_both_frf_values \
  tests/ui/test_frf_canvas.py::test_frf_canvas_cursor_magnitude_carries_its_scale_unit \
  tests/ui/test_pinned_cursor_facts.py -k 'frf' -q
```
