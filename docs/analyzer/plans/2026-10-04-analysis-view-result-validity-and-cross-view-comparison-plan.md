# 分析 View 结果恢复、有效性判定与跨 View 对比优化计划

- 日期：2026-10-04；基线：`72b08435`。
- 状态：**分析与确定性探针完成，待实施。没有修改产品源码或正式测试。**
- 用户问题：FRF 修改指定时间并计算后，离开再回来提示重算；FFT / FFT vs Time / Order / FRF 只有“添加对比窗格”，缺少与其他 View 对比。
- 范围：先修结果身份和恢复，再补跨 View 对比；横展到参数、来源、预设、异步完成、缓存驻留、项目恢复和焦点路由。
- 证据边界：截图是用户提供的前台证据；本轮使用真实 MainWindow 的 offscreen 探针及真实数值 job，但没有操作用户当前窗口或使用截图原文件。不能把合成数据复现称为原文件前台验收。
- 工作区原有 `docs/lessons-learned/INDEX.md` 修改与 `runtime-resources-must-survive-duplicate-cleaning.md` 未跟踪文件保持不动。

## 1. 结论与优先级

| 优先级 | 结论 | 证据与影响 |
| --- | --- | --- |
| P1 | **FRF 写入与恢复缓存使用不同的 Fs** | 自动重建时间轴后，job 按实际 Fs 写缓存，View 恢复按原文件 Fs 查缓存。已复现全时段和指定范围均失败；时间范围没丢、原结果仍在缓存，却显示需要计算。 |
| P1 | **FFT vs Time 的旧任务回调缺少当前计算请求校验** | 同一 View 的段长从 0.5 s 改为 1.0 s 后，0.5 s 任务完成仍进入绘图。确定性回调探针已确认；真实慢线程与前台交互尚待验收。Order 有同类代码路径，列为待复现，不能直接宣称相同故障已经发生。 |
| P2 | **只改变显示的预设也会使 FRF 被标为过期** | 同样只把幅值改为 linear，直接操作不 stale，加载预设却 stale；计算缓存仍命中。共享 preset 提交判定覆盖其他分析 section，需一起修正并逐模块验证。 |
| P2 | **计算参数改回原值后，状态仍停留在 stale** | 段长 0.3→0.4→0.3，缓存重新命中，但有效事实仍显示过期。结果状态依赖“发生过修改”的事件，而没有重新对齐当前请求。 |
| 产品缺口 | **View 内双窗格与跨 View 对比确实是两个功能** | 分析页明确使用 `active_pane` 菜单模式，忽略被右击 View 的目标索引，只对当前 View 增删 PaneState。不是菜单偶发消失，也不能靠改文案补齐。 |

## 2. 第一问题：已确认的根因链

源码定位（均为本基线，后续按符号定位）：

1. `mf4_analyzer/ui/main_window/_frf_mixin.py:338` `_frf_prepare_pair_samples`：先按原始物理时间裁剪；非均匀时调用 `prepare_analysis_time_axis`，返回局部 `input_fs` 和重建后的 effective range。
2. 同文件 `:469` `_build_frf_candidate`：候选 `params.fs` 使用上述实际 Fs；job 也用相同 Fs。`frf_coordinator.py:194` `_build_context` 据此建键，`:283` `_on_job_finished` 保存该键。
3. `_frf_mixin.py:748` `_frf_cache_key_for_pane`：却重新赋值 `params['fs'] = float(input_fd.fs)`，同时读取 `pane.effective_time_range`。原 FileData 没有被修改，因此它的 Fs 与分析实际 Fs 可以不同。
4. `_frf_mixin.py:767` `_render_frf_view_from_cache`：读不到结果就 reset 并显示“点击『计算频响』生成”，也清空有效事实；不是重新计算失败。
5. `_analysis_mixin.py:2889` 附近的结果保存与 `:2898` pin replacement：恢复时用错误键替换 pane 的 pin 集合，实际结果随后还可能失去驻留保护。这是代码推导出的后续影响，尚未做缓存压力复现。

### 确定性复现

真实 FRF 数值 job → 按生产候选 key 入缓存 → 正常完成渲染 → 新建 View → 切回原 View：

| 输入条件 | 原 Fs / job Fs | key 一致 | 切回有结果 | 请求范围保留 | 原时间轴不变 |
| --- | --- | --- | --- | --- | --- |
| 均匀、全时段 | 1000 / 1000 | 是 | 是 | 是 | 是 |
| 均匀、指定 0.1–3.8 s | 1000 / 1000 | 是 | 是 | 是 | 是 |
| 非均匀、全时段 | 1000 / 1000.029999999954 | 否 | 否 | 是 | 是 |
| 非均匀、指定 0.1–3.8 s | 1000 / 1000.0299999999818 | 否 | 否 | 是 | 是 |

四组的实际结果均仍在原缓存键下。即使界面把两个 Fs 都显示为相近的数，JSON key 比较仍可能不同；不应通过粗暴舍入 Fs 解决身份分歧。

用户截图的有效事实已显示“时间轴：已自动重建 · 仅本次分析”，与上述触发条件高度吻合。尚未拿原文件复现，不能断言它是用户环境中的唯一触发因素。

现有测试盲点：`tests/ui/test_frf_main_window.py:84` 的 `_seed_frf_cache` 用“恢复键”反过来造缓存，所以能证明恢复链自洽，却不能证明真实 job 的写入键与恢复键一致。时间轴隔离测试验证了不改原始数据，但 FRF 项没有完整验证 job→cache→View 往返。

## 3. 横向展开：不只检查时间

| 维度 | 当前结论 | 目标合同 |
| --- | --- | --- |
| 分析时间 | FRF 重建路径确认失败；均匀路径两个对照通过 | full、指定范围、非零起点、端点未落在采样格、微小浮点差都能恢复；requested/effective/display 分开 |
| 计算参数 | FRF 真正改段长会 miss 并 stale，行为合理；改回后 stale 未消除 | estimator、window、段长、overlap、NFFT、FFT averaging/weighting、Order RPM 等按实际数值依赖判定 |
| 显示参数 | FRF 直接改幅值不失效；显示预设误 stale 已确认 | 幅值单位、相位展开、对数轴、相干阈值/淡化、色图、色阶、坐标视窗不启动 DSP；显示所需派生量按各模块已有合同重投影 |
| 预设 | `_analysis_mixin.py:773` 用完整 params 比较，再统一 stale | 与直接编辑共享计算差异判定；改预设名称/基准不等于数值变化 |
| 来源 | 当前模型使用 `(fid, channel)`；FRF 输入输出有方向，Order 含 RPM | 同名跨文件、I/O 交换、RPM 更换、通道数据/时间轴修订、文件关闭都必须正确失效；无关文件加载不影响已有结果 |
| View/pane/section | 已有范围与参数恢复 guard；不能据此认定所有边界已完成 | A/B/A、模块往返、双 pane 焦点、复制/重排、12 Views×2 panes 均不串写；恢复不发用户修改事件 |
| 异步完成 | FRF 有 pane generation；FFT-time 回调仅验证 View id，确定性探针失守；Order 待复现 | 完成任务绑定 dispatch 的 section/view/pane/request；当前请求变化后不能把旧结果当新结果画出 |
| 缓存驻留 | 有 pinning，主缺陷可使实际 key 脱离 pin | 同一 canonical key 用于写入、恢复、facts、pin、UltraView 引用；关闭/删除准确释放 |
| 项目重开 | 项目保存意图，不保存数值 cache；已有恢复队列会重建结果 | 普通切 View 不计算；冷项目重开依既有队列计算，两种生命周期明确区分 |
| 数值错误/空态 | 当前 cache miss 常合并成“点击计算” | 区分未算、参数已变、来源不可用、失败、缓存缺失；不把内部 key 不一致包装成用户操作错误 |

其他模块的 Fs 路径已有不同保护：FFT `_fft_effective_params_for_source`、FFT-time `_fft_time_effective_params_for_source`、Order `_order_effective_params_for_source` 在查缓存时进行有效参数准备。因此不能把 FRF 的具体 Fs 缺陷直接宣称为四模块共同缺陷。

时间域仍以 ViewState/绘图意图为主，不套分析结果 cache 方案。保留 Custom-X 物理时间裁剪、时域 full 下静默投影和 FFT 时间预览 pan/zoom 不改分析范围的现有合同。

### 两项补充探针

- FRF：直接 display edit → cache hit、facts 不 stale；相同 display-only preset → cache hit、facts stale。计算参数改动 → miss、stale；改回 → hit、仍 stale。
- FFT-time：真实 job 使用段长 0.5 s；当前 View 改为 1.0 s 后调用完成处理，仍调用一次 `_render_fft_time_on`。最后绘制被 spy 替代，故这是**完成准入验证**，不是成品截图或线程竞态验收。需实施前补 coordinator/实际队列边界用例。

## 4. 结果有效性修复方案

### 4.1 先统一 FRF 请求身份

- 把 FRF 参数标准化、原始时间裁剪、时间轴准备事实及 canonical cache key 汇合在一个 owner 路径，候选构造、lookup、facts 和 pin 都使用它。
- 默认放在现有 FRF owner/coordinator 边界；只有确定多个入口需要共享准备描述时才提取中性 helper。不得复制 DSP 公式或在 compatibility facade 实现。
- lookup 从目标 View/pane 的意图及其来源解析，不借当前 Inspector 值补另一个 View 的缺失参数。旧项目缺字段用明确版本默认值迁移。
- `requested range` 是用户意图；原始样本选择是输入事实；`effective range/Fs` 是本次分析事实。`pane.effective_time_range` 不能单独充当当前结果身份。
- lookup 使用同一准备策略的轻量描述，不运行 FFT、不复制输入/输出信号、不分配完整重建时间网格。若复用短期准备事实，归现有 owner 管理，并明确源 revision、请求 signature、清理边界；本阶段不引入全局结果注册表。
- 不修改原 FileData.fs/time_array；不关闭自动时间轴修复；不舍入 key 来容忍错误；不通过自动重算掩盖错误。

### 4.2 统一直接编辑、预设和恢复的分类

沿用各模块 compute-only projection（FRF `_COMPUTE_FIELDS`、FFT cache params、FFT-time cache params、Order cache params）；区分 requested intent 与 source-specific effective compute facts，不能仅做完整字典比较。

| 操作 | 数值任务 | 已有结果状态 |
| --- | --- | --- |
| 无修改的 View/pane/section 恢复 | 不提交 | 复用相同结果与有效事实 |
| 显示调整或 display-only preset | 不提交 | 保持 current，重投影当前显示 |
| 数值参数/有效来源/范围变化 | 仅用户点击计算后提交 | 有对应缓存就恢复；否则明确 stale |
| 改回原计算请求 | 不提交 | 对应缓存存在时恢复 current；缺失时说明原因 |
| 计算中只改显示 | 不追加 DSP | 完成后按所属 View 的最新显示意图绘制 |
| 计算中改计算请求 | 不冒充新请求完成 | 旧结果可按旧身份入缓存，但不能发布为当前结果；源已删除/修订等情况按既有失效合同丢弃 |

结果状态应由已有 request/result/facts owner 统一判定，避免在按钮、canvas、facts 各加一个互不一致的 dirty bool。保留旧图时明确“上次结果”；无结果时显示准确空态。切换回来的匹配结果要同时恢复图、有效事实、缓存 pin 与游标/标注。

### 4.3 异步与生命周期

- 计算有效性校验使用 `(section, view_id, pane_index, request_signature/source_revision)`；显示完成另查当前可见 canvas binding。
- 保留 AnalysisJobService 单一队列所有权，不用 section-wide cancel 误取消另一个 pane/View。
- FFT-time 先补“改参数不再点计算”“改来源”“关闭第二 pane 再建同索引”“显示调整”准入测试；Order 先复现，再做必要修复。
- 任务完成后不把 dispatch-time 的显示参数覆盖当前显示；有效事实必须对应实际画出的结果。
- View 删除、关闭全部、源卸载、项目替换后，不允许迟到任务重新写回已释放的绑定或 pins。

## 5. 第二问题：两种对比保留为独立能力

### 5.1 当前实现与限制

- `analysis_section_page.py:211` 为四分析页配置 `split_action_mode='active_pane'`。
- `view_tabbar.py:1542` 该模式只允许当前 View 增删窗格；另一分支才是“与此 View 并排”。
- `window.py:1497` 的分析菜单连接忽略 `_idx`，调用 `_on_analysis_split(section, True)`。
- `_analysis_mixin.py:454` 只向当前 `state.panes` 添加空 PaneState。
- `analysis_view_state.py`：params 在 **View 层**；sources/time_range/viewport/游标在 **pane 层**。因此同一 View 两窗格可以比较不同来源/范围，但共享该 View 的算法参数。
- `_render_analysis_view_from_cache` 的多处路径仍读 active manager/Inspector。不能简单把 B 的 PaneState 塞进 A，或仅切换菜单 mode；否则 B 会使用 A 的参数、文件范围和焦点路由。

### 5.2 推荐交互（作为本 plan 的实施默认值）

| 功能 | 操作 | 参数及数据归属 |
| --- | --- | --- |
| 添加对比窗格 | 当前 View 菜单保留现有入口，关闭后回到一个 pane | 同一 View 的共同分析参数；每个 pane 自己的来源/范围 |
| 与其他 View 并排 | 非当前标签提供“与此 View 并排”；当前标签提供“与其他 View 并排…”目标列表 | A/B 各自完整参数、文件附件、pane 与结果；都可聚焦后编辑 |
| 结束 View 对比 | 明确“结束 View 对比”，与“关闭对比窗格”分开 | 不删除任一 View，不改其 panes |

- 第一版限**同一分析模块**的两个 View，四个分析模块均可用；跨模块总览继续用 UltraView。
- A 参数 H1/段长 2 s，B 参数 H2/段长 1 s 时必须显示两个真正独立的结果；不能共用 A 的 params。
- 显示清楚的 View 名称/颜色和当前焦点；Inspector 标明所属 View 与 pane。聚焦 B 后的来源、参数、计算按钮、游标、图表选项、范围编辑都操作 B。
- 布局采用两个 View 区域左右并排。各区域保留其既有 1/2 pane；双 pane 在较窄区域内可上下排列，最多呈现 2 Views×2 panes。**不把 4 个显示区域持久化成一个 View 的 4 panes，不修改 MAX_PANES=2。**
- 小窗口保持最小可用尺寸，提供聚焦区域展开/返回对比；不得悄悄删除或隐藏未提示的 pane。四个 FRF pane 是最多十二子图，需真实渲染验证可读性与延迟。
- 打开/关闭对比只切展示与 binding，不启动分析；无结果的一侧保持空态与计算入口，另一侧不受影响。
- 默认跨 View 联动关闭，保留各自视窗。用户打开联动时，仅联动轴语义、单位与尺度兼容的图；FFT/FRF 联动 Hz，FFT-time/Order 依具体轴语义判断。联动只改相机，不改分析时间或数值参数。
- 色阶锁定仅用于兼容热图（量纲、幅值模式、dB reference/weighting 等一致），不强行锁不相容的图。View 内已有 compare 设置与跨 View 联动设置分开保存。
- 当前 host View A 可记住一个目标 B；替换只改变展示关系。切 C 使用 C 自己的关系；回 A 恢复 A/B。点击已显示 B 的标签只转移焦点，不生成 B→A 环。
- B 重命名/重排按 view_id 保持关系；删除 B 自动结束该关系。复制 View 不继承跨 View 关系，不复制 runtime cache 或 canvas wrapper。

### 5.3 所有权与数据结构

1. 在现有 `AnalysisContext` 之下引入有界的对比展示 owner，管理 host/peer view_id、focused `(view_id, pane_index)`、canvas binding 和临时联动连接；不是新的 MainWindow 跨 mixin 字段集合。
2. View/pane 继续是意图真源；canvas 只投影。抽出 `AnalysisSectionPage` 现有 pane host 所必需的组合边界，保留一个 section tabbar；避免嵌套完整页面导致重复 tabbar/信号。
3. 将此次必要的 render/capture/source lookup/计算路由改成显式目标上下文；active-manager helper 保留兼容包装，但对比路径不得依赖它隐式选目标。
4. 外侧 canvas 到 `(section, view_id, pane_index)` 必须可逆；点击、输入 flush、预设提交、source scope、状态提示、异步回调、copy/export 都从此 binding 解析。
5. runtime results 由原 cache 共享，两个展示区域不得深复制大型数组。跨 View 显示不转移 cache pin 所属 View；销毁展示只解除展示连接，删除 View 才释放其结果驻留。
6. 比较关系放 section manager 的独立持久化 payload，以 view_id 存储 host→peer 及联动选项；不复用 `AnalysisViewState.compare`（其语义是 View 内 panes）。`_assemble_project_document` 目前只写 analysis 的 active/views，须补读写与向后兼容迁移。丢失目标安全解链且可观察；不写 canvas、结果或 process-local token。
7. UltraView 继续引用实际 View/pane；一个跨 View 展示关系不能生成内容混合、身份为 A 的假 View。当前对比整体导出明确标识 A/B；单图导出与图表选项遵循焦点。

## 6. 实施任务与验收门

顺序执行；本 plan 不要求并行 agent。T1 可独立交付，不必等待跨 View 功能。

### T0：冻结问题与修正测试前置条件

- 将本轮合成数据探针移入对应正式 owner tests，断言生产 job→coordinator key→cache→restore，而不是用 restore key 自造“正确”cache。
- 在真实 widget 路径先进入 section/ensure_ready，再操作 canvas；保留 QSettings 隔离及 Qt teardown。
- 逐一归因本轮 10 个既有失败：先修测试前置条件不适应懒创建的问题；剩余不匹配单独记录，不能统一视为“过期测试”或放宽断言。
- 完成门：非均匀 full/range 和显示预设的缺陷测试修前红；均匀对照绿。旧失败清楚区分产品失败/fixture 不匹配。
- focused：`tests/ui/test_frf_main_window.py`、`tests/ui/test_analysis_time_isolation.py`；不做全套 baseline。

### T1：FRF canonical request 与恢复闭环

- Owner：`_frf_mixin.py`、`frf_coordinator.py`，必要时 `analysis_time_axis.py` 的纯准备描述；不改数值算法。
- 覆盖 Fs、effective range、参数默认值/归一化、facts 与 pin 的一致性；禁止增加恢复时 DSP。
- focused：`test_frf_main_window.py`、`test_frf_coordinator.py`、`test_analysis_time_isolation.py`、`test_analysis_view_cache_residency.py`。
- 若动时间准备中性层，加 `tests/test_analysis_time_axis.py`、`tests/test_signal_no_gui_import.py`；MainWindow 状态变更加 `tests/ui/test_main_window_state_ownership.py`。
- 完成门：四组复现都绿；A/B/A、跨模块往返、双 pane、复制、12 Views 巡回都不增加 job 提交；缓存压力下实际结果保持驻留。

### T2：横向有效性、预设与迟到任务

- Owner：`_analysis_mixin.py` 的 preset/edit 分派与各分析 coordinator/mixin；使用各模块已有 compute projection。
- 先修 display-only preset 与参数改回；再补 FFT-time 迟到完成准入。Order 先增加实际回调/队列复现，确认后修同类路径。
- focused：`tests/ui/test_preset_bar_lifecycle.py`、`test_analysis_view_bridge.py`、`test_analysis_multiview_integration.py`、`test_frf_coordinator.py`、`test_fft_time_coordinator.py`、`test_analysis_time_range_intent.py`、`test_order_cache_key_params.py`；新增用例放相应 owner 文件。
- 边界：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_import_boundaries.py`；涉及 signal 只允许中性依赖。
- 完成门：修改显示零 DSP、有效事实保持 current；参数/来源真变才 stale；参数还原恢复已有结果；迟到任务不覆盖新请求、不串 pane、不复活已删 View。旧图与 facts 不互相矛盾。

### T3：先建立跨 View 的明确目标上下文

- Owner：`analysis_context.py` 及窄对比 owner、`analysis_section_page.py`、必要的 `_analysis_mixin.py` 适配。
- 在启用菜单前，用两 View 不同参数/来源证明 cache-only 渲染、焦点 capture、source scope 和 compute dispatch 全部按显式目标路由。
- focused：新增 `tests/ui/test_analysis_view_comparison.py`，配合 `test_analysis_source_scope.py`、`test_analysis_section_page.py`、`test_analysis_multiview_integration.py`。
- 边界：`test_main_window_state_ownership.py`、`test_import_boundaries.py`、`test_no_lambda_signal_connections.py`；若触及 pg_canvas host 再运行 backref invariants，不能借此扩大 whitelist。
- 完成门：A/B 参数相互独立；每侧 1/2 panes、聚焦/离焦、待提交输入和异步完成均准确；构建/关闭展示释放 timer/signal/Qt wrapper。

### T4：菜单、展示、持久化与帮助

- Owner：`view_tabbar.py`、`analysis_section_page.py`、对比 owner、`_project_io_mixin.py` / `mf4_analyzer/ui/project_io.py`，以及 `mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`、相关指南。
- 单独的 View 内 split 与跨 View compare 信号/操作，不让一个 `split_requested` 根据当前 UI 猜两种语义。
- focused：`tests/ui/test_view_tabbar.py`、`test_analysis_section_page.py`、新增比较 tests、`tests/test_project_io_analysis_views.py`、相关 project-session 用例、既有 help contract tests。
- 核对重命名/重排/复制/删除/关闭全部、旧项目、缺失目标、不同源 fid remap、单图及整体导出、UltraView 实际引用。
- UI/QSS 如有变更加 `tests/ui_kit/test_qss_border_shorthand.py`；更新交互帮助，不做产品版本 bump。
- 完成门：四分析模块都能独立使用两种对比；每个动作有明确 View/pane 归属；普通切换无计算；原生布局无裁切、缺角、遮挡。

### T5：集成与原生验收

- 合成回归矩阵先通过，再在 macOS Cocoa 前台加载代表性非均匀数据，按用户步骤调整范围→计算→A/B/A；记录 compute 请求计数、实际 key、源时间不变及画面/facts。
- 跨 View 验收：FFT、FFT-time、Order、FRF × 单/双 pane；FRF 最大组合、窄窗、缩放/游标/切片/色阶/图表选项/预设/导出/重开项目。验收过程中不修改采样率来回避问题。
- Windows 源码/原生与冻结 Full/Lite 分开列状态；没有跑冻结包就标 UNKNOWN。本任务不以 source/offscreen 代替用户截图环境的验收。
- 仅 T3–T4 跨 UI/状态/持久化的稳定集成里程碑安排一次 full gate，由主执行者独占：记录前后 HEAD 与 dirty 范围、检查已有 pytest，主套件 `--ignore=tests/acquisition_ui` 完成后另起进程跑 acquisition_ui；不并发、不重复绿测。
- T1 独立修复只需其 focused/boundary gates 与 Cocoa 复现，不等此 full gate。

## 7. 本轮执行证据与未完成项

探针与日志保存在 `.state/analysis-view-audit-20261004/`，不提交生成物：

- `test_probe.py`：合成数据与实际 job；使用 `-p ui.conftest`，继承隔离 QSettings / Qt 生命周期 fixture。
- `probe.log`：`2 failed, 2 passed`，失败为非均匀 full/range 的 View 往返。
- `edit-probe.log`：`1 failed, 3 passed`，失败为 display-only preset；计算参数还原的 stale 残留作为观察值记录，没有冒充该项独立通过断言。
- `async-probe.log`：`1 failed`，FFT-time 0.5→1.0 s 后旧完成仍被准入。
- `existing-gates.log`：八个相关现有测试文件合跑，`10 failed, 279 passed, 138 warnings in 26.27s`。10 个失败都在 `test_frf_main_window.py`：4 个 charts-not-ready，1 个 cursor mode、1 个项目恢复列表为空、4 个 facts 为空/未 stale。后几类是否都源于懒创建尚未逐项证明，**现有测试基线非绿**。
- 本轮没有运行全套，没有原生 Cocoa 或 Windows frozen 验收；也没有修复上述产品缺陷。
- lesson：现有 `analysis-time-preparation-preserves-original-source.md` 已要求“lookup 与 dispatch 使用相同实际采样率”，`programmatic-view-projection-is-not-user-intent.md` 已覆盖恢复事务；本轮不重复新增 lesson。实施时以真实 job 往返回归补齐已有规则的验证缺口。

复现命令（故意保留 bug 暴露的失败，实施后应转绿）：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.:tests .venv/bin/python -m pytest -q -s -p ui.conftest .state/analysis-view-audit-20261004/test_probe.py
```

本文件是文档交付；文档自身只需路径、符号、范围、一致性及 `git diff --check`，不另跑运行时全套。上述测试用于诊断事实，不代表 plan 已执行。
