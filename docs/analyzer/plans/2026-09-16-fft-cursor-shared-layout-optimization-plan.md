# FFT 游标面板共享布局与边界优化计划

- 日期：2026-09-16
- 状态：待实施；本次仅编写计划，不修改产品代码。
- 当前分析基线：`0bcac91e`；实施前复核 HEAD、工作区及本文符号。
- 用户问题：FFT 整个游标框超出图表边界或被遮挡；希望复用时域游标属性。
- 执行方式：顺序实施，单一协调者维护共享契约；本计划不要求并行 agent。

## 1. 结论与范围

复用时域已有的 `CursorPresentation → CursorPill → cursor_table_layout` 展示链路，让 FFT 单/双游标均使用同一套尺寸预算、实际文档测量、完整通道块保留、颜色、full/mini 和锚点约束。FFT 的读数含义由原频谱 owner 提供，不把频率端点幅值冒充时域区间统计。

本轮包含 FFT 单/双游标、full/mini、所属频谱图边界、窗口和图内布局变化、时域/FFT 切换隔离。FRF 保持现有显示语义并做共享组件回归；不扩展 FFT-vs-Time/Order，不改 DSP、采样算法、项目 schema 或产品版本。

历史参考：[游标表格规格](../specs/2026-09-12-cursor-table-readability-spec.md)。该规格当时明确排除 FFT/FRF；本计划仅新增 FFT 接入范围和频谱区域边界规则，其时域规则继续有效。历史文件中的执行授权和 agent 分工不延续为本次授权。

## 2. 已核实事实与复现

| 当前 owner / 符号 | 事实与后果 |
|---|---|
| `cursor_pill.py:set_frequency_dual_rows`、`set_single_detail_html` | 清除结构化 projection，按 HTML 自然尺寸 `adjustSize()`；FFT 没有使用时域的受限表格排版。 |
| `cursor_pill.py:reflow_to_parent` | projection 为 None 时直接返回；FFT 不能靠调用此函数获得自适应。 |
| `stack.py:_reposition_one_pill` | 只有结构化 projection 才随 safe rect 变化重排；位置 clamp 不能容纳大于区域的框。 |
| `stack.py:_sync_pill_safe_rect` | 取整个 canvas widget，FFT 包含上方频谱及下方时域预览，不等于频谱绘图区。 |
| `stack.py` 主 pill 的 `display_mode_changed` 连接 | source 固定为 `canvas_time`，FFT 接入共享 projection 前必须修正路由，防止 toggle 重放时域缓存。此项为静态风险，尚未在本轮独立复现。 |
| `cursor_pill.py:move_preserving_right_edge` | 仍按父 widget 而非所属 safe rect 约束；统一路径时需覆盖拖动后更新和 toggle。 |
| `line_canvas.py:set_dual_cursor_frequencies` | 依次发送 primary、legacy detail、结构化频谱 rows；直接新增 projection 会产生多个实际写入，须收敛 live UI 入口。 |

本轮使用真实 ChartStack、生产 QSS 和隔离 QSettings 的 offscreen Qt 探针：

| 窗口 / 内容 | 可用 canvas 安全区域 | 实际 pill | 结果 |
|---|---|---|---|
| 1000×700，16 通道双游标 | 984×587 | 219×715 | 底部越界，覆盖预览和底栏后被裁切 |
| 650×420，8 通道双游标 | 634×307 | 219×371 | 底部越界 |
| 650×420，2 个超长名称 | 634×307 | 1237×113 | 右侧越界 |

临时证据位于 `.state/fft-cursor-diagnosis/`，不提交；用合成读数复现布局缺陷，不代表用户原始数据或前台验收。Cocoa 前台及 Windows 状态均为 UNKNOWN。

## 3. 共用属性与领域差异

| 属性 | 决策 |
|---|---|
| 圆角、字体、颜色、单位位置、列对齐 | 复用现有 CursorPill / renderer；通道文字跟随通道颜色。 |
| 宽度预算 | 复用 `compute_wcap` 与现有硬上限，按实际内容收缩；不新增 FFT 常量副本。 |
| 长名称、多行、极窄空间 | 复用受限换行/中间省略及完整数字保护；不缩字号、不截半个数值。 |
| 高度 | 复用整通道块保留及 `+N channels` 摘要；更高空间恢复内容。 |
| full/mini | 保留共享 pill 现有模式状态；FFT mini 与时域一致隐藏名称/来源、保留色点及读数，双游标 mini 保留 Δ。不自动切 mini。 |
| 拖动与位置 | 共用 top/right 保持及 safe rect clamp；所有更新、toggle、resize 使用同一所属边界。 |
| 时域六项显示设置 | 继续只作用时域。极值点与 Min/Max/Avg 不是 FFT A/B 端点的同义项，不把 `charts/time_cursor/display_options_v1` 扩展成频谱设置。 |
| FFT 内容 | 单游标保留当前幅值及现有相对首条曲线差值；双游标 full 为 A、B、Δ=B−A；primary 保留 f 或 A/B/Δf。 |

空间不足策略的局限必须明确：`+N channels` 是省略提示，不是可点击详情，也不表示全部通道可见。此轮不新增滚动、详情窗口、tooltip 或字段配置；若需要在极小面板内访问全部通道，应另行设计显式入口。

## 4. 数据与显示契约

1. 沿用 `CursorPresentation`、`CursorDisplayBlock`、`CursorTableRow` 的通用列标签和格式化文本。新增 FFT projection builder 放在 `cursor_display.py`，只投影，不计算谱值或差值。
2. FFT 输入需要明确的中立读数 DTO 时，在 `cursor_display_model.py` 添加具名字段；A/B 独立表示，禁止借用 min/max/avg 字段。单游标保留相对首曲线差值及首曲线无差值的条件，不把它混同双游标 B−A。
3. 从现有 entry/来源数据传递复合身份与真实显示名称；不能从 legend 文本反解析来源。实施前确认 entry 生产端能提供哪些身份字段；若不足，只沿该生产 seam 补元数据，不扩大为分析架构改造。
4. 数值、差值、吸附频率、精度和空状态以现有 line_canvas 结果为准；展示层不新增计算。当前频谱 rows 单位为空时保持空，不从 amp label 或名称猜单位，不把 dB 当线性单位。
5. live FFT 每次逻辑读数更新最终仅调用一次 `set_display_projection`；legacy 字符串信号及 public 返回值保留供兼容调用，但不再争写 managed FFT detail。primary 和 rows 同批应用，避免前一个领域内容的中间态。
6. 单游标、双游标仅放 A、A/B 完整、off、空数据均有明确清理路径；隐藏来源发信号不能清除当前可见来源结果。
7. 当前 presentation 缓存复用 ChartStack 现有 owner 并按 canvas 隔离；clear、pane 移除、View 恢复对称清理。不得让缓存保存已删除 Qt wrapper，不新增 MainWindow 状态或持久化键。
8. primary 用明确 label/value 片段控制换行，纳入 toggle 占位；不得仅依赖时域分隔符去拆 FFT 的 `|` 文本，不从 HTML 反算频率。

## 5. 几何与事件契约

- FFT 目标边界采用上方频谱数据视口，排除下方时域预览、工具栏、底栏和其他分析 pane；时域继续使用已有 canvas safe rect，FRF 不在此轮更改边界定义。
- `PgLineCanvas` 提供窄的只读区域接口，将 `_plot_amp.vb` 的 scene 矩形通过 GraphicsView/viewport 映射到 canvas widget 坐标；ChartStack 再映射到 pill 父级、相交并 inset 8 个 Qt 逻辑像素。不得混用 scene、widget 或截图坐标，也不手动乘 DPR。
- FFT 已知 owner 几何无效/隐藏/尚未布局时，先隐藏并等待布局完成；不得退回整个 stack 或其他 pane。区分“没有 provider 的 legacy canvas”和“FFT provider 暂无有效区域”。
- 默认位置直接采用同一个 safe rect 的右上角。所有拖动、内容增长、toggle、恢复和避让都使用此边界；框尺寸必须先满足边界，再执行位置 clamp。
- 接入现有 `layout_geometry_changed` 等 owner 事件，核对首显、resize、预览高度改变、分析多 pane 布局改变、字体/DPI 改变。需要合并时使用 owner 持有的单次刷新，不轮询，不重复连接，不触发 FFT 重算。
- toggle 路由到当前有效 active card/canvas；时域副 pane 按自身 owner 路由。时域设置变化不能重绘当前 FFT pill，旧时域缓存不能覆盖 FFT 内容。
- snapshot/restore、复制图片和 UltraView 继续使用当前展示结果；结构化恢复不能退回无约束 HTML 自然尺寸。

## 6. 实施步骤与验证归属

### Task 0：冻结受影响行为并建立失败回归

- 检查 HEAD/dirty scope，仅运行受影响 focused baseline；不运行全量基线。
- 将上述三种越界转为真实 ChartStack 几何/绘制回归；覆盖 single/dual 和 full/mini。
- 冻结 FFT 原有单游标跨曲线差值、双游标 A/B/Δ、仅 A、off、空数据、返回字符串及单位行为。
- owner 测试：`tests/ui/test_chart_stack.py` 的 FFT 游标条目、`tests/ui/test_pg_line_canvas.py` 的读数条目；新增 `tests/ui/test_fft_cursor_layout.py` 集中存放几何回归。

### Task 1：接入共享 projection 和单一更新入口

- 文件：`ui/cursor_display_model.py`（必要的 DTO）、`ui/pg_canvas/line_canvas.py`（事实输出）、`ui/chart_stack/cursor_display.py`（FFT builder）、`ui/chart_stack/stack.py`（路由/缓存）。
- 通用 renderer/planner 原则上直接复用；只有实际不能表达 A/B/Δ 的具体分支才做局部扩展，不复制布局算法。
- 消除 managed FFT 的 legacy detail 竞争；修正 toggle 与设置刷新路由；保留外部兼容信号。
- focused：FFT 读数、projection 字段/身份/转义、一次更新计数、FFT↔Time↔FRF 切换及 full/mini 恢复。

### Task 2：所属频谱边界和共享空间处理

- 文件：`ui/pg_canvas/line_canvas.py`（区域接口）、`ui/chart_stack/stack.py`（坐标映射/事件）、`ui/chart_stack/cursor_pill.py`（统一锚点和约束）。
- 完成宽高预算、名称处理、完整块省略、空间不足/恢复、首显和 resize 重排；不通过仅设置 maximumWidth/Height 来掩盖被裁文档。
- focused：`test_fft_cursor_layout.py`、`test_cursor_table_geometry.py`、`test_cursor_table_modes.py`、`test_cursor_single_pipeline.py`；拖动和共享改动同时覆盖 `test_split_routing.py`、`test_pill_switch.py` 的相关条目。

### Task 3：提示、集成与真实渲染验收

- 更新 `ui/hints.py` 和 `ui/quickref.py`：FFT mini 隐去名称、空间不足摘要及放大恢复规则；保留文案宽度约束。
- focused：`tests/ui/test_hints.py`，并从现有 capture/snapshot/UltraView 测试中选择确实经过修改 seam 的条目，执行前记录具体 node IDs；不运行所有 UI 测试。
- 边界：`tests/ui/test_import_boundaries.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_main_window_state_ownership.py`；若触及 pg_canvas backref 声明则加 `tests/ui/test_pg_canvas_backref_invariants.py`。仅修改中立 DTO 不允许引入 Qt。
- Qt 命令统一采用项目运行时及隔离设置：`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`。手工探针同样隔离 QSettings。
- macOS Cocoa 前台检查实际频谱/预览比例、拖动、缩放、toggle、切 View；Windows 100%/150%/200% 单独记结果，没有环境就写 UNKNOWN。
- 记录 `git diff --check`、lesson status、证据路径和未通过门槛。本轮不要求 full suite；仅新出现跨模块/顺序污染问题时说明原因后扩展验证。

## 7. 验收矩阵

| 场景 | 必须满足 |
|---|---|
| FFT single/dual × full/mini，0/1/2/8/16/50 通道 | 可见外框完全在所属频谱 safe rect 内；无半个通道块，无被裁数值；省略数量正确。 |
| 650×420、1000×700、极低高度及长名称 | 复现中的越界消失；只依据当前频谱区域预算，primary 与 toggle 同样受限。 |
| 长单位、重复名/不同来源、负数、指数、缺失、特殊字符 | 不猜单位、不合并身份、不改变数值语义、不重复转义；颜色正确。非有限/短数组沿用计算 owner 既有行为，发现计算缺陷另记，不在布局补丁中静默修补。 |
| 首显、预览比例变化、缩小再放大、分析多 pane | 及时重排且不跨预览/邻 pane；空间恢复后保留用户 full/mini 意图。 |
| 先时域读数，再 FFT，再点击 −/+ | 不恢复时域值、不串 primary/detail；时域设置更新也不改 FFT 内容。 |
| 用户拖动后更新、连续数值更新 100 次 | top/right 在允许范围内稳定；只必要增长，不重复全表测量或 DSP。 |
| clear/off/空结果/仅 A/View 恢复/关闭 pane | 无旧行、旧来源、旧布局缓存或无效 Qt wrapper。 |
| 时域八种模式、FRF、截图合成 | 现有领域含义及显示正常；共享更改无回归。 |

验收必须同时看 frame geometry 与实际绘制文档；外框没有越界不能替代文本完整性检查。offscreen PASS、Cocoa 前台 PASS、Windows PASS 分别记录。

## 8. 本次计划交付检查

本次为文档变更，不执行上述实现任务。检查 owner/路径、现有契约一致性、工作区范围及 `git diff --check`；不需要运行 runtime suite。既有临时探针仅作为问题证据，不计入修复验收。
