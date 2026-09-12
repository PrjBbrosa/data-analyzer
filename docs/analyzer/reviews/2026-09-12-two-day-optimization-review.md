# 2026-09-11～12 优化提交综合 Review

日期：2026-09-12。结论：**needs revision / partial**。主要优化已进入真实调用链，已有测试总体稳定；但补充边界探针发现新的正确性和 UI 状态问题，性能目标也尚未全部达到，不能认定“优化全面落实且没有新 bug”。

本次交付为审查、失败复现与后续设计，未修产品代码，未提交或推送。

配套：[优化 Spec](../specs/2026-09-12-optimization-robustness-spec.md)、[执行 Plan](../plans/2026-09-12-optimization-robustness-plan.md)。

**后续产品决策（2026-09-12）：** 用户取消范围状态提示条和“恢复参数范围”按钮，改用 Home 查看全图、重新点击计算按参数显示。F06 保留为审查时的历史证据，专用入口撤销后不再要求继续补按钮 dirty；当前目标见修订后的 R06/T5。其余 findings 的历史结论不随此更新改写。

## 1. Findings：按严重性排序

以下 F01～F06 的行号对应冻结提交 `9cda71ad`；F07 对应审查期间新增的 `d1299597` 及候选快照。正在工作的 checkout 行号可能变化，应同时按符号定位。P1 是可导致错误分析显示的问题；P2 是可复现的局部行为缺陷；F06 单列为 P3 状态记账缺口，不夸大为已证明的数据丢失。

### F01 · P1 · 小幅值 Linear 频谱平移后，自动 Y 不再包含可见数据

- **位置：** `mf4_analyzer/ui/pg_canvas/line_canvas.py:2985`，`PgLineCanvas._fit_active_spectrum_y`。引入：`eb5d149b`。
- **触发：** Linear 幅值处于 `1e-12～1e-10`，自动 Y 开启，X 从低幅值窗口平移到高幅值窗口。
- **复现：** `x=[0,1,2,3]`，`y=[1e-12,2e-12,1e-10,2e-10]`。X 为 `0..1` 时 Y 是 `(9.5e-13,2.05e-12)`；X 改到 `2..3` 并 flush 后，Y 仍不变，正确目标应是 `(9.5e-11,2.05e-10)`。可见频谱全部在上界之外，主频谱看起来为空。
- **根因：** 新的 no-op 优化用 `np.allclose(..., rtol=0, atol=1e-9)` 判断是否需要 setYRange。这个绝对工程量阈值比数据本身还大，掩盖了真实范围变化。中立层算对了目标，显示层提前返回又把正确结果丢掉。
- **证据：** offscreen 失败；生产 QSS、真实暴露的 Cocoa 窗口、DPR 2 下同样失败，截图已检查。失败发生在最终 flush 后，不是临时交互帧。
- **系统修复方向：** 范围 no-op 必须与单位缩放无关，并保护“自动范围包含有效可见极值”这一不变量。先验证不同数量级、单位等比变换与 manual Y，再调整拥有此行为的 canvas guard；不可换一个更小的固定 epsilon 后结束。

### F02 · P2 · 清除通道筛选的恢复算法退化为平方复杂度

- **位置：** `ui/widgets/channel_tree.py:3194`、`:3225`，及 `_tree_item_for_data`（`:1380` 附近）。引入：`569fdc0c`。
- **触发：** 文件含大量通道，进入搜索/仅选中筛选，再清除筛选以恢复树上下文。
- **复现：** 合成 500 / 1,000 / 2,000 个叶节点，恢复分别读取身份 **125,751 / 501,501 / 2,003,001 次**。数量翻倍，扫描约四倍。带计数包装的耗时约 0.056 / 0.218 / 0.892 秒；这些耗时只作诊断，不作为产品性能 SLA。
- **根因：** 快照记录所有节点，包含没有展开意义的叶节点；恢复对每个身份重新从树根 DFS 查找。原本的语义身份是正确的，但没有界定查找成本。
- **影响：** 大通道文件清筛选会阻塞 GUI，新的“保留上下文”体验可能比原来的直接清空更卡。
- **系统修复方向：** 每次恢复构造局部身份索引或一次遍历应用快照；复杂度 O(N+K)，保留复合身份、generation、滚动锚点和被删除节点处理。不创建跨树重建持有 Qt wrapper 的永久缓存。横查 replace-file 的展开恢复，避免同类逐节点 DFS。

### F03 · P2 · 图卡同步回调重入后，选中背景指向旧模式

- **位置：** `ui/chart_stack/cards.py:1475`、`:1506`；频率图卡同类顺序在 `:1760`。引入：`f036d2f2`。
- **触发：** 模式 signal 的同步接收槽重新选定有效模式。控制级探针分别将 overlay 重定向到 subplot、dual 重定向到 off。
- **复现：** 最终 `plot_mode='subplot'`，按钮文字状态也为分屏，indicator target 却是“叠加”；最终 cursor 为 off，背景却落在“双游标”。Cocoa 等待 450 ms 后仍能看到文字与底板错位。
- **根因：** `_apply_*` 先 emit 业务 signal，再按外层旧参数定位 indicator。内层较新的状态已提交，外层返回又补放过期目标。
- **横向审查：** `9cda71ad` 已在 Toolbar 修正同类顺序，但 TimeChartCard 的布局/游标及 FrequencyCursorCard 仍留有同类尾部写入。频率图卡目前是源码证据，尚未独立做同样 Cocoa 复现；Batch MethodButtonGroup 也需检查回调前呈现及销毁路径，不能把它直接算作已复现缺陷。
- **限制：** 这是实际控件的确定性重入 probe；尚未证明用户通过某一完整 MainWindow 操作一定触发该重定向。不是所有正常点击都会错。
- **系统修复方向：** 每个控件 owner 完成状态和呈现目标后再通知；同步回调产生的新目标保持权威。保留 View manager 确认机制，不能在请求尚未获准时移动 View marker，也不能让业务等待动画结束。

### F04 · P2 · Batch 有 item 时，详情投影丢失 run 级警告

- **位置：** `ui/drawers/batch/result_details.py:150`，`project_result_rows`。引入：`569fdc0c`。
- **触发：** `BatchRunResult` 同时包含正常 items 和独立的 run warnings / blocked reasons。
- **复现：** 一个 done item 加 `warnings=['RUN_ONLY_WARNING']`，详情 rows 只有 item 的“未提供详细原因”，没有 run 警告。
- **根因：** run 级诊断的投影整体置于 `if not items:` 内，把“有条目”等同于“条目已承载所有诊断”。
- **影响边界：** 页脚仍有 `format_batch_run_warnings` 汇总路径，不能称所有警告在 UI 全部消失；问题是详情列表与详情复制缺少完整 run 级证据。
- **系统修复方向：** run / group / item 分别投影自身诊断，与是否存在 items 无关；保留来源和输出归属，不把 run warning 随意附到每个 item，不编造缺失原因。

### F05 · P2 · Batch 输入滤波改变后，旧结果仍显示“本次运行结果”

- **位置：** `ui/drawers/batch/sheet.py:570`、`:958`、`:654`；`input_panel.py:1069`。引入：`569fdc0c` 的结果详情生命周期。
- **真实接线：** FilterPanel.changed → InputPanel.changed → `_on_input_scope_changed` → 刷新候选/重算规划；这条路径没有 `_mark_result_previous`。其他来源/参数通过独立信号才进入 `_on_user_configuration`。
- **复现：** 真实 BatchSheet 接收一个完成结果，打开详情，点击输入滤波启用开关。开关为 True，但 `_result_stale=False`，标题仍为“本次运行结果”。
- **影响：** 用户改变计算前提后仍可能将旧诊断理解为当前配置的输出。结果数据本身没有被重新计算或篡改。
- **系统修复方向：** 给成功的用户配置变更一个明确语义入口。覆盖滤波、输入范围、源删除、方法、分析参数、输出及恢复默认值；区分用户修改与元数据到达、程序投影、preset restore，不是在所有 `changed` 上盲目置脏。

### F07 · P2 · 新增 X 标签修复仍按文本猜测来源，会清除同名手写标签

- **审查补录：** 开始审查后新增 `d1299597`；不能把它计入 `9cda71ad` 的通过结果。
- **位置：** `ui/main_window/window.py:3191`、`_view_mixin.py:1127`（候选行号）；`ui/inspector_sections/persistent_top.py:402`、`:625`。
- **复现：** 通道 X 为 speed，用户明确编辑标签为 speed，`textEdited` 已使 `_xlabel_auto_from_channel=False`；调用真实 `_apply_xaxis()` 后它又变 True，随后 View 恢复仍为 True，切回 time 时标签被清空。候选探针失败。
- **根因：** apply / restore 使用 `not label or label == channel` 推断“自动生成”；显示内容相同不能证明用户意图相同。新增参数名是 provenance，但持久状态仍没有保存 provenance。
- **修复方向：** label origin 在 Custom-X 意图 owner 中明确建模并贯穿 apply/capture/View/project；widget 仅投影。旧项目没有 origin 时保留已声明的兼容推断，新用户编辑必须覆盖它。新旧项目 round-trip、拖放生成、手写同名、手写异名均要覆盖。
- **限制：** 当前复现位于 `d1299597` + 单独冻结的在途改动候选；引入位置由该提交 diff 确认，不能声称纯 `d1299597` 的整套测试已通过。

### F06 · P3 · “恢复参数范围”漏记语义 revision，依赖离开项目时补算 digest

- **位置：** `ui/main_window/_analysis_mixin.py:434`，`_restore_analysis_parameter_ranges`。引入：`21c3ef12`。
- **复现：** FFT 用户改 X 后，设置 holder 保存点，再点击页面范围恢复入口；Pane origin 从 user/auto 变 auto/auto，序列化状态改变，但 revision 与 save_point 都为 2，`holder.is_dirty=False`。
- **根因：** 邻近 range-policy Apply 会 `mark_user_mutation()`，恢复按钮直接写 Pane 并 render，遗漏相同语义记账。
- **影响边界：** `_project_io_mixin.py:103` 会在有 saved_digest 时计算 canonical digest，因此尚不能据此断言关窗一定不提示或会丢失保存数据。当前证明的是 eager revision 合同不完整。
- **修复方向：** 成功且实际改变状态的一次用户恢复，记一次语义 mutation；no-op 和程序恢复记零次。与视口 Apply 复用 owner 内的提交边界，不新增另一套 dirty 状态。

## 2. 性能与候选集成缺口

### G01 · 性能目标尚未闭环

依据已提交的 [频谱性能记录](../verify/2026-09-12-spectrum-pan-performance.md) 末轮数据：

| 指标 | 原门槛 | 记录结果 | 判断 |
|---|---:|---:|---|
| FFT auto-Y，60 Hz 场景 callback+paint P95 | 相对 T0 至少降低 30%；≤13.09 ms | 18.70 → 16.64 ms，改善 11.0% | 未达到 |
| FFT manual-Y 同场景 P95 | 回退不超过 10%；≤10.84 ms | 9.85 → 16.41 ms，回退约 66% | 未达到 |
| 宽窗缓存命中后全量扫描 / setData | 消除重复工作 | 已记录结构性改善，相关 owner 测试本次通过 | 局部落实 |

这些是历史同机探针数据，不是本次重新测出的最新耗时。记录指出强制 paint、事件积压及对照长尾影响，不能将每个慢帧都归因于新增缓存，也不能据此声称缓存优化已解决卡顿。

在途 Section 优化记录也明确 partial：cached FFT 内容就绪 P95 217.97→90.98 ms；time 231.55→188.43 ms，约 19%，未达 20%。该测量缺生产全局样式及交错 A/B，稳定字段不直接证明首帧已是最终几何/质量。需要按最终集成快照补验收，保留原门槛，不能通过降低门槛消除失败。

### G02 · 在途动效合同与测试、文档未同步

单独冻结的候选 owner gate：**156 passed，1 failed**。唯一现有测试失败是 `tests/ui/test_toolbar.py::test_toolbar_production_light_uses_navigation_slide_and_keeps_five_keys`，断言 `selection_navigation==400`，当前 WIP 为 320。

这是候选集成合同不一致，不等于 320 ms 本身是产品 bug。需由动效任务确认接受值并同步相关消费者测试和当前合同。未提交 follow-up 仍写 Toolbar 为 emit 后启动、F0/F1 尚未实施，而 `9cda71ad` 已完成该局部修正；后续计划必须以实际代码重定基线，避免再实施旧指令。

## 3. 审查范围与逐提交落实

- 时间窗口：Asia/Shanghai，2026-09-11 00:00 至 2026-09-12 审查结束。
- 初始冻结：`9cda71ad52ef4daac15fc51bf88ffae060fd1f8c`；差异基点 `76c0edec`。9 个提交，122 个文件，17,196 行增加 / 695 行删除，含测试、探针、文档与原型，不能把该总量当作产品复杂度。
- 期间新增提交：`d1299597d000860970b4f50f8aa1a4fac850f264`，作为第 10 项补录。
- 初始 archive 的产品源码未被本次测试修改；失败 probe 仅写在 `.state` 下的测试副本。候选另存 `candidate-manifest.json`，固定 d129 + 19 个相关在途文件，未混用两个结果集。

| 提交 | 优化与实际落点 | 本次结论 |
|---|---|---|
| `4c19fd10` | 交互原型及选中背景 Spec/Plan | 文档与运行入口已对应；HTML 不是 Cocoa 验收 |
| `f036d2f2` | SelectionIndicator / SegmentedChoice / Toolbar / 图卡 / Batch 方法按钮 | 主路径落实，既有 owner 通过；F03 回调重入遗漏，历史部分绘制间隔和 Windows 门未通过 |
| `8cc27316` | 8.2.3 范围、preset、ZFD 帮助说明 | help 内容测试通过；不代表本文重新验收 Windows 发布包 |
| `a6bab11f` | ComputeProgress QLabel 显式关闭 implicit indent | 根因修复落在实际 QLabel，owner 通过；原生历史记录为补充，未重跑全部百分比矩阵 |
| `a8d4b231` | SearchableCombo 搜索提示及通道配置栏 | 提示已进入实际控件，未发现新正确性问题；候选的空占位处理单独通过 owner 测试 |
| `569fdc0c` | 通道筛选恢复、PillSwitch 动效、View marker、Batch 结果详情 | 主要体验落实，存在 F02/F04/F05；其余相关控件测试通过 |
| `21c3ef12` | 中立自动范围、可见窗频谱、热图/切片同步、逐轴 viewport_origin、Batch 共用范围 | 主链已实现并通过现有 owner/production 测试；F06 记账遗漏；需要保留跨 Pane / 项目及单位边界 |
| `eb5d149b` | PreparedSeries、trace 缓存、合并刷新与 X-only pan | 缓存结构及多场景正确性已有覆盖；F01 新回归；G01 端到端性能未达标 |
| `9cda71ad` | Toolbar 在同步模式 signal 前启动反馈 | 局部顺序修复及现有重入测试通过；未横向闭合图卡同类顺序 |
| `d1299597` | 程序通道 X 标签恢复来源、切 time 清自动标题 | 自动/异名标题现有测试通过；F07 同名手写标签仍错误 |

## 4. 接线与其他 UI 影响矩阵

| 用户入口 | 状态 owner → 消费者 | 本次证据 | 剩余风险 / 必要回归 |
|---|---|---|---|
| FFT X 平移、缩放、Home、resize | ViewBox → PgLineCanvas → PreparedSeries/trace → Y/quality | 现有 line/cache/interaction 测试通过；F01 原生复现 | 单位等比、空窗、NaN 间隙、manual Y、历史/导出最终 flush |
| 恢复参数范围 / ChartOptions Apply | 分析协调层 → Pane origin/limits → render/dirty | Apply 已记账，restore 漏记 F06 | no-op、分屏 linked X、保存点与关闭 guard |
| 时频/Order 主图可见范围 | Heatmap → slice → 中立范围 helper | heatmap/slice/production/Batch renderer 测试通过 | 实际客户数据、浮动切片、View 恢复组合没有完整原生验收 |
| Toolbar Section 导航 | Toolbar → MainWindow → render gate/section | 已提交 Toolbar owner 通过；WIP reveal/time gate 新测试通过 | 真正首个正确内容 paint、rapid switch/关闭/export；不能由动画 active 推导流畅 |
| 图卡布局/游标 | Card → 同步业务槽 → indicator | F03 实际控件失败 | 时域 + 频率焦点路由 + 删除/禁用/程序重定向 |
| View marker | switch request → manager confirm → marker/render | marker/tabbar/reentrancy 现有测试通过 | busy gate 延迟确认、overflow、删除活动 View；无证据时不改为乐观 marker |
| 通道筛选 | channel tree 身份快照 → deferred restore | 小树语义测试通过；F02 复杂度失败 | 2k/10k 通道、replace/remove、重复名字、只恢复展示上下文 |
| Batch 滤波/范围/源 | InputPanel → Sheet 规划与结果 stale | 滤波实际开关失败 F05 | 参数恢复、移除来源、异步元数据、运行中编辑策略 |
| Batch 结果详情 / 复制 | BatchRunResult → frozen rows → detail view | 既有 rows/输出归属测试通过；F04 失败 | run+group+item 混合、空结果、取消/blocked、文件消失 |
| 自定义 X 标签 | CustomXAxisSpec → apply/capture/restore → Inspector | F07 失败 | 同名手写与自动来源须分别保存；PER_SOURCE_NAME/EXACT_SOURCE 保持身份 |
| PillSwitch / SegmentedChoice / 公共 QSS | 控件 owner → 现有消费者 | 既有控件、Batch、QSS border、lambda ratchet 通过 | disabled/父级禁用原生像素和 Windows 100%/150% 未完整复核 |
| 旧范围/preset/Batch/ZFD 修复 | 既有 controller / state / planner / IO owner | 本次额外横向 owner gate，见 §6 | 不能以早前报告的通过数替代当前证据；本地真实 ZFD corpus 单独验收 |

## 5. 代码逻辑、架构与鲁棒性判断

### 值得保留的结构

1. `signal/display_ranges.py` 成为 GUI/Batch 共用的中立范围 owner，兼容包装保留；本次 import boundary 通过，没有把 UI 依赖倒灌到 signal。继续让 raw 有效样本决定极值，显示抽点只决定绘制成本。
2. `spectrum_display.py` 的 PreparedSeries / trace 缓存把数据准备与交互显示分开，失效依据结果和几何；不是每帧重新计算 FFT。宽窗缓存消除了重复扫描，但性能必须看真实 paint。
3. Pane 的 `viewport_origin` 显式区分 auto/user/home/legacy，比把任意 capture 当作用户缩放可靠；逐轴恢复与 ChartOptions adapter 保留了共享对话框边界。
4. Batch 详情只投影冻结结果，不另造 runner/compute/reporter；输出归属仍按 group/item 分开。问题是边界形状覆盖不足，不需要重写 Batch。
5. 在途 Section 方案扩展现有 TimeRenderGate，并以 View 对象身份和 generation 约束 deferred work；FFT prepared 只借用本次调用数据。方向比新增长寿命跨 View 缓存更可控。

### 应系统改善的责任边界

| 反复出现的缺口 | 系统性约束 | 合适 owner | 不应扩张成 |
|---|---|---|---|
| 正确目标被优化 guard 丢弃（F01） | 单位无关、极值包含、失效后必须同步完成 | PgLineCanvas + 中立范围测试 | 新的一套范围算法或另一个 magic epsilon |
| 身份正确但恢复成本失控（F02） | 一次遍历 / 局部索引、明确复杂度预算 | Channel tree | 全局 Qt 节点缓存 |
| 回调后补写过期状态（F03） | 确认状态 → 呈现目标 → 通知；较新提交优先 | 各选择控件 owner | 全局 UI event bus / 动画完成驱动业务 |
| 配置、视图变化未完整记账（F05/F06） | 用户成功提交与程序投影分开；单 owner 一次提交 | BatchSheet / 分析协调层 | 广播所有 changed 为 dirty，或新的跨 mixin 状态簇 |
| 信息来源被推断或丢弃（F04/F07） | run/group/item 诊断及 label origin 显式保真 | 结果 DTO 投影 / Custom-X 意图 | 用显示文本当身份或来源 |
| “结构变快”被当作整体完成（G01/G02） | 固定快照、正确性+自然 paint+最终质量证据 | 一个验收协调者 | 并发全套测试和多个不可比性能报告 |

不建议按 `line_canvas.py` 行数或近期补丁数量发起大拆分。应先补上述不变量和生命周期测试，只有同一职责确实横跨多个 owner 时，才把该职责移入现有 collaborator。保持 MainWindow 协调、canvas 呈现、中立层数学与 Batch orchestration 的既有依赖方向。

## 6. 本次执行的验证与证据边界

| 证据集 | 快照 | 实际结果 | 可说明什么 |
|---|---|---|---|
| 两日差异涉及的 46 个测试文件 | 9cda archive | **1814 passed，473 warnings，222.90 s** | 现有受影响 owner / production / renderer 合同总体稳定 |
| 10 个适用边界测试文件 | 9cda archive | **43 passed，1 skipped，8.94 s** | import、state/backref、QSettings、collection、QSS；skip 不算通过 |
| 审查新增控制/数据探针 | 9cda archive | **7 个预期断言失败**（首轮 5，扩展 2） | F01～F06 的边界缺口，含图卡两模式；不是 7 个不同根因 |
| Cocoa 重复验证 | 9cda archive，生产 QSS、暴露窗口、DPR 2 | **3 个相同断言失败** | F01 及 F03 两模式已在实际 QWidget 渲染中复现 |
| 在途候选 owner | d129 + 固定 overlay | **156 passed，1 failed，26.86 s** | Section/FFT prepared/通道提示等 focused 通过；G02 尚有合同冲突 |
| X label 新边界 | 同一候选 | **1 个预期断言失败，0.78 s** | F07 用户同名编辑经真实 apply 后来源丢失 |
| 旧修复与共用消费者横向 gate，13 个文件 | 9cda archive | **307 passed，3 skipped，35.11 s** | 时间意图、preset/dirty、Batch、ZFD；不替代客户 corpus |

本次没有运行全套。已按 changed-owner、影响边界及确定的共用消费者追加检查；当前任务是 review，没有集成产品修改，不需要泛化成完整发布验收。

本次没有完整前台 TraceLab 用户流程巡检、Windows Full/Lite frozen、Windows 100%/150%、客户文件全矩阵，也没有重跑原生性能全矩阵。Cocoa 控件截图是本次直接证据；既有性能报告是历史证据；offscreen 逻辑通过不能代替其他平台。

测试后逐项核对两个快照各 **2,680 个 tracked 文件**：archive 与 9cda Git blob 一致，candidate 与 d129 Git blob/声明 overlay 一致，均无意外变化。新增 review probe 是单独的 untracked 测试证据，不在这 2,680 个文件中。候选 overlay 的复制前、复制后与副本 SHA256 也一致。主工作区同期存在其他任务修改，因此不将其描述为“从审查开始以来完全未变”。

本地复核材料位于 `.state/review-20260912/`：`initial.json`、`initial-dirty.patch`、`head/`、`focused-files.json`、`run_focused.py`、`focused.log/xml`、`boundary.log`、`probes.log`、`extra-probes.log`、`cocoa-probes.log`、`candidate-manifest.json`、`candidate.log`、`label-probe.log`、`lateral.log`。截图位于 `.state/cocoa/` 的 `small-linear-auto-y.png`、`reentry-plot.png`、`reentry-cursor.png`；只作为本地证据，不加入 Git。

新增探针定位：`.state/review-20260912/head/tests/ui/test_review_20260912_probes.py` 与 `.state/review-20260912/candidate/tests/ui/test_review_20260912_label.py`。两者均未加入正式测试树。快照校验记录为 `snapshot-verification.json`。

Lessons 已按范围读取。F03 的回调顺序复发由既有 `toolbar-feedback-precedes-sync-mode-delivery.md` 覆盖，本次用图卡失败证据及 R03/T3 将其横向落实；不重复新增同义 lesson，也未修改已有 dirty 的 lessons INDEX。

## 7. 实施优先级

1. **先关闭 F01，恢复分析显示正确性。** 同时建立幅值数量级和单位等比回归。
2. **按 owner 闭合 F02～F07。** 图卡状态、Batch 结果可信度、标签来源分别独立小步处理，不混到一个 UI 大补丁中。
3. **协调当前在途 Section / motion / label 工作。** 重定真实集成基线，关闭 G02，复测必要组合。
4. **最后完成 G01 的原生性能与跨 UI 验收。** 功能正确之后才讨论进一步缓存/绘制结构调整；未达到门槛继续标 partial。

详细任务、失败测试、验收与回退规则见配套 Plan。本文与 Spec/Plan 的完成不表示修复已实施。
