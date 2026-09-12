# TraceLab 顶部 Section 切换性能优化 Implementation Plan

> **执行更新（2026-09-12）：** 用户随后授权按此计划安排 agent 执行，并授权 Codex 接续额度耗尽的 Grok 会话。T1/T2/T3 局部实现已落地；整体验收为 PARTIAL，时域性能目标未达到。详见 [接续验收记录](../verify/2026-09-12-section-switch-performance.md)。历史调查读数保留，未提交或推送。

**Goal:** 降低有数据 View 的顶部 Section 来回切换阻塞，同时保留状态恢复、范围正确性、游标与历史、分析事实、项目恢复和 UltraView 的既有行为。

**Architecture:** 先保留完整业务恢复链路，在拥有相关行为的模块内优化绘制时机、进度刷新和单次调用内的重复准备。第一阶段不跳过整个 `plot_time()` / `_apply_active_analysis_context()`，不建立跨五个分区的通用缓存。完整时域恢复复用及其他分析分区的渲染复用设为独立后续门。

**Tech Stack:** 当前 PyQt5、pyqtgraph、NumPy、pytest/pytest-qt；真实 macOS Cocoa 事件与 paint 探针；独立 QSettings 和 `.state/` 证据。

日期：2026-09-12。调查 HEAD：`21c3ef12a0b3beb50967e876974e75dd7c60a6d0`。
状态：**T1/T2/T3 局部实现完成；整体 PARTIAL，严格性能与客户全矩阵尚未通过。**

相关文档：

- [频谱拖动性能计划](2026-09-12-spectrum-pan-performance-plan.md)：独立任务，尤其与 `line_canvas.py`、频谱抽点和自动 Y 调度存在文件交集。
- [View 切换质量结算合同](../specs/2026-08-15-view-switch-quality-settlement-spec.md)：保留最终几何一次结算、150 ms 交互计时器和既有质量阈值。
- [原生交互动效合同](../specs/2026-09-05-native-interaction-motion-pilot-spec.md)：业务提交与动效呈现分离，不能等动画结束再改变业务状态。

执行协调：本计划与频谱拖动计划共享 `line_canvas.py`，须顺序集成，不能同时修改该 owner。若拖动优化先落地，T0 必须在其完成后的稳定源码上重新建立基线；若本计划先落地，拖动计划同样刷新相关基线。保留其他会话的代码、测试与探针产物，不顺手纳入本补丁。

## 1. 结论、方案选择与证据边界

### 1.1 不能把“重算”视为一种操作

| 操作 | 当前职责 | 本轮政策 |
|---|---|---|
| FFT / STFT / Order / FRF 数值计算 | 生成分析结果；项目恢复还有待执行任务 | 保留计算入口、缓存键、任务生命周期；普通切换不新增计算 |
| View 捕获和控件投影 | 保存离开页，恢复目标参数、来源、范围、焦点 | 始终执行必要投影，不能因曲线缓存命中而跳过 |
| 信号准备 / 事实整理 | 时间轴检查、裁剪、有效采样率、NFFT 与健康信息 | 先消除同一调用内的重复输入准备，不直接缓存整个事实卡 |
| 绘图模型更新 | 同步曲线、坐标语义、范围、诊断、历史等 | 第一阶段保持原路径，尊重现有 selection delta |
| Qt 绘制 / 抗锯齿 / 布局 | 把已存在的对象画到屏幕 | 主要优化对象；必须保证最终画面及稳定状态正确 |

可选方案：

1. **推荐：保留业务恢复，优化呈现与局部重复准备。** 风险可分段验证，先覆盖时域↔频谱；每一步都可单独撤回。
2. **直接跳过未变化 View 的整段恢复。** 潜在收益较大，但要覆盖文件、滤波、Custom-X、分屏、轴组、记录曲线、范围和全局显示配置的失效，当前证据不足，不作为第一阶段。
3. **每个 View 常驻独立画布或用截图代替切换。** 引入内存、输入命中、游标、历史和 UltraView 绑定问题，不纳入本计划。

### 1.2 已有测量能证明什么

本地证据目录：`.state/section-switch-analysis/`。

- `probe_ab.py`、`ab/results.json`：真实 Cocoa、1600×950、DPR=2，2 条各 1,188,000 点、24 kHz 合成数据，已缓存 FFT。正常退出；记录的选定源码指纹前后一致。
- 多次切换后，最长一次 `processEvents()` 调用耗时的中位数：空页面约 33–35 ms，回 FFT 约 115 ms，回时域约 176 ms。
- 诊断性绕过频谱曲线 paint 后，FFT 对应读数约 46 ms；绕过预览 paint 后约 95 ms。它们只定位成本，绕过绘制不能进入产品。
- FFT 回切命中 `_fft_last_render_sig`，`_enter_fft_mode` 约 0.4 ms；未调用 `plot_spectra` 重建。曲线仍发生多轮 paint，因此“缓存命中”不能证明“切换便宜”。
- `controls/results.json` 的另一组实验分别降低 AA、绕过时域重绘，支持二者都有成本；该组绝对值与前组不同，不拼接成同一个前后性能结论。
- `profile-time-profile.txt` 显示时域 `plot_time` 的显著时间嵌套在 `_begin_compute_progress` 的事件泵内；不能把它全部记成数据算法时间。`profile-fft-profile.txt` 显示 Qt `drawPath` 为主要热点之一。
- 第一版 `probe.py` 在结果保存后因错误调用 `mark_clean()` 退出失败；它的 profile 仅供热点定位，不算成功验收。后续探针改用真实 `mark_saved()` 正常退出。

**限制：** 样本少、合成数据、程序 `button.click()`、计时 wrapper；没有真实鼠标节奏、客户源文件或显示合成器 presentation timestamp。一次 `processEvents()` 可包含多个 paint，以上不是单帧耗时、FPS、P95 或完整内容就绪时间。旧探针指纹只覆盖选定文件，不能称为全仓快照。其他三种分析分区只完成源码追踪，未证实相同热点占比。

## 2. 连接与副作用保留矩阵

完整路径从仓库根目录解析；本矩阵中的 `ui/`、`main_window/`、`pg_canvas/` 分别简写 `mf4_analyzer/ui/`、`mf4_analyzer/ui/main_window/`、`mf4_analyzer/ui/pg_canvas/`。下列为本次读取的当前 owner，实施时按符号定位，不依赖旧行号。

| 链路 / owner | 不能丢失的职责 | 优化边界及验证 |
|---|---|---|
| `ui/toolbar.py:_apply_mode` → `main_window/window.py:_on_mode_changed` | 一次选择一次 `mode_changed`；鼠标动效、程序切换 snap、重复点击 no-op | 不能把业务挪到动画 `finished`；只提前动画启动不能解决 paint 阻塞 |
| `_capture_focused_view` / `_capture_active_analysis_view` | 离开页真实范围、参数、来源、游标、标注进入正确 View | 先捕获离开页再投影目标；不能在混合状态或渲染重入时捕获 |
| `_project_view_controls` → `ui/view_bridge.py:apply_controls_from_state` | 文件附件、通道颜色/勾选/隐藏、主副 Pane 分叠、游标、轴组、Custom-X、记录树 | 保留 `_applying_view` 和 dirty restore scope；全量恢复跳过暂不实施 |
| `_apply_active_analysis_context` → `_on_analysis_view_switched` | Pane 数量、联动/色阶锁定、目标附件、候选源、参数、时间范围、覆盖层 | 保留 `_applying_analysis_view`；非焦点来源从 `state.panes` 读取，不从共享 navigator 猜测 |
| `_maybe_fill_empty_analysis_on_mode_entry` | 按现有 follow prefs 填充空 View 的附件 | 不改变空页语义，不把测试 seed 当产品规则；测试覆盖 prefs 开/关 |
| `_enter_fft_mode` / `_fft_render_signature` | 已应用目标状态后的保留曲线复用；失配时缓存恢复或时间预览 | 本轮不放宽签名命中范围；单一旧签名不能充当全 Section / 所有 Pane 的完整有效性证明 |
| `_plot_time_preserving_xlim` / `_plot_time_on_canvas` | 风险提示、数据准备/滤波、selection delta 或重建、游标 X 语义、范围输入、ticks、诊断、统计与状态提示 | 第一阶段仍执行。保留其他调用者：设为左轴、显示设置等也调用 preserving-xlim，不可全局改成回切专用 |
| `pg_canvas/canvas.py:try_apply_selection_delta` | 相同数据/兼容模型已能增量更新 | “进入 plot_time”不等于“每次重建画布”；记录 delta 命中与 full rebuild 原因，避免再造一套重复缓存 |
| `_render_view_onto_canvas` / `canvas.settle_view_restore` | X 无 flush → Y → ticks → 最终几何一次结算；包络、ink、raster、AA | 不把 Section 回切机械替换成该路径；它与保留画布显隐是不同入口，先测量状态与范围差异 |
| `_begin/_update/_finish_compute_progress` | token 所有权、异常结束、项目恢复进度优先级 | 当前 begin 会泵整个事件队列；update 的常规路径只 repaint 小进度控件，只有 `flush_events=True` 才泵队列。不能误删成全局“禁止 processEvents” |
| `line_canvas.py` replot callbacks / 图卡历史绑定 | 重建后重新绑定 ViewBox、鼠标模式与历史基线 | 保留画布回切不应重复重置历史；重建时不能漏绑。新增质量 hook 不能伪造一次 replot |
| `_sync_fft_effective_facts` | 每来源有效 Fs/NFFT、blocked 状态、NaN/constant、时间轴 provenance、Fs 冲突、facts 分组 | 局部 prepared input 复用后逐字段相等；不能只保留视觉摘要 |
| `ultraview_capture_coordinator.py` / `ultraview_coordinator.py` | 正确 ref 绑定、稳定性判断、捕获重试、PreviewStore、用户主动同步和导出 | AA 暂缓不能让 capture 永久 pending，也不能抓半成品；不得把 capture 是否执行仅绑定到“本次有没有 plot” |
| `project_dirty.py` / 项目恢复任务 | 程序投影不增加 dirty；待恢复分析按 view_id 执行；关闭/取消先走既有保护 | 新状态仅运行时，clear/销毁/项目替换对称失效；不能序列化到 View/preset |

## 3. 第一阶段固定合同

### 3.1 保留业务与数值语义

1. 不删除 `_on_mode_changed` 的 capture、附件/候选/参数投影，也不直接删除时域回切重绘。
2. 普通 warm Section 切换不得调用数值计算或提交新 job。项目打开后 `_analysis_restore_pending` 属于合法例外：保留既有按 View 身份调度、去重与结果接入。
3. 单/双 Pane、焦点、同名异源、隐藏曲线、记录曲线、全空/部分缺源、筛选与删除保持原语义。两 Pane 必须分别验证，不只看主图。
4. 原始数据、工程单位、时间轴、滤波、NFFT、频率加权、dB reference、raw extrema 与游标数据不变。分析准备优化仍先按原始时间裁剪；重建不是重采样。
5. View 进入后的手动/自动范围、`viewport_origin`、联动与 Home/参数恢复行为保持一致。不能用“X/Y 看起来相同”代替范围意图一致。
6. 不改变 MotionPolicy、曲线线宽、AA/ink/point 阈值、150 ms quiet window。当前 motion.py 有其他任务改动，不纳入本补丁。

### 3.2 显示与调度

- 首次显示完整有效曲线，不允许空白占位、缺一条曲线、错误范围或旧 View 覆盖目标 View。允许分析曲线短暂使用 AA-off，但最终按既有 gate 恢复；不强制绿灯。
- 目标是减少首显阶段的昂贵重复 paint，而不是在用户停手后集中补一次大卡顿。必须同时记录首次反馈、内容就绪、最终质量稳定和迟到的 paint 峰值。
- `singleShot(0)` 不是“必然在首帧之后”。新增恢复调度要记录真实 paint 与几何就绪顺序，不能用固定 sleep 或多加两个 0 ms timer 作为证明。
- Qt 对象和绘制仍在 GUI 线程。不得把 `plot_time`、`plot_spectra` 或 widget 操作移到 worker。
- 快速往返、隐藏、销毁、关闭、项目替换时，过期呈现回调失效；运行时身份至少能区分 canvas 生命周期与本次呈现 generation。复用已有 owner，不添加跨多个 mixin 写入的散落属性。
- 新的 presentation pending 必须接入既有稳定性判定。导出/复制图片/UltraView 主动同步在明确 settle 后读最终画面，或遵循已有等待/重试合同。
- 不在动画 `finished` 中执行绘图、提交任务或写 View。动效关闭、减少动态效果、程序切换均能独立完成恢复。

## 4. 顺序执行任务

接续状态（细项勾选只代表有证据的完成项）：

|任务|状态|说明|
|---|---|---|
|T0|PARTIAL|恢复12场景；修复history断言与探针测量。完整副作用/严格稳定帧仍有缺口。|
|T1|实现完成，性能验收partial|真实paint驱动reveal、显式grab、取消与capture合同通过focused测试；Cocoa为诊断证据。|
|T2|实现完成，目标未达|进度泵缩小、目标校验/合并/重入门已验证；时域20%目标未达到。|
|T3|完成|prepared仅本次调用复用；19新节点与既有数值/facts合同通过。|
|T4|PARTIAL|已记录组合比较与单MF4功能验证；不扩展到高风险缓存。|


### T0 — 冻结副作用与建立可比较基线

**Owner / files:** 探针使用 `.state/section-switch-performance/`；参考 `scripts/probe_interaction_motion.py`。新增测试放 `tests/ui/test_section_entry_presentation.py`；在 `tests/ui/test_analysis_multiview_integration.py` 复用现有 `two_file_win` 和附件 seed helpers。

- [ ] 记录 HEAD、dirty 路径、Qt/pyqtgraph 版本、platform、DPR、实际 frame/client/viewport 几何和系统负载；对整个 `mf4_analyzer/`、探针与相关测试保存内容哈希。测量期间相关代码变化则该轮不可比较。
- [ ] 改进临时探针：真实 Qt mouse click、输入回调起止、toolbar/chart 各自 paint 起止、16 ms heartbeat、延迟 job 提交、最终 ranges、曲线身份、质量 pending、replot callback 和 UltraView capture 计数。性能组不启用 cProfile；profile 独立运行。
- [ ] 读取全部基线 fixture 参数，明确 FFT 实际 NFFT 和结果长度，不从输入点数推断输出点数。QSettings、最近文件和项目 dirty 状态隔离；关闭和 deferred delete 正常退出才接受结果。
- [ ] 在未改产品前冻结当前行为：`test_fft_section_switch_away_and_back_preserves_spectrum`、`test_fft_single_signal_survives_fft_time_weighting_drift`，以及下列新增场景的规范化快照。
- [ ] 新增场景：已缩放的时域↔FFT；双 Pane 不同源与不同范围；在其他分区改全局通道颜色/单位/数据后回来；未算结果的预览；follow prefs 空 View；范围草稿；项目恢复中切换；快速 time→fft→order→time；关闭前仍有 deferred callback。
- [ ] 快照比较明确排除性能时间、瞬态动画几何、随机 View ID 和当前 Section 本身；比较源身份、参数、range/origin、可见曲线数据、游标模式/值、历史可继续前进后退、dirty、diagnostics、cache pins、pending jobs 和 UltraView 目标 ref。
- [ ] 审查首次显隐为什么有多轮 paint：记录 show/resize、view-range 信号、进度泵、quality timer 与 paint 的时间线。未找到触发者，不直接压掉 Qt paint/update。

**门：** 先完成受影响的上述 focused node，不跑全套 `tests/ui`。基线现存失败单独列出，不能改期望使它消失。T0 产出每个副作用的保留位置和可执行断言，缺项则相应优化不进入实施。

### T1 — FFT 保留画布的首显质量调度

**Owner / files:** `mf4_analyzer/ui/pg_canvas/line_canvas.py`；窄接线在 `mf4_analyzer/ui/main_window/window.py`；测试 `tests/ui/test_section_entry_presentation.py`、`tests/ui/test_pg_line_canvas.py`。仅在需扩展真实 paint 通知时修改 `pg_canvas/quality.py`，并补 `_CanvasBackref`/delegate 声明相关门。实施前更新治理 spec 的 §3.4，说明 retained Section reveal 与新结果/View 重建的区别，不修改历史测量。

- [ ] 写失败测试 `test_fft_retained_reveal_keeps_curves_ranges_and_history`：保留曲线对象和 raw 数据，未提交计算、未 clear/plot，最终 X/Y/origin、历史与光标数据一致。
- [ ] 写失败测试 `test_fft_reveal_quality_settles_after_real_paint`：记录实际首个内容 paint；验证恢复质量不能仅依赖 0 ms timeout 已运行。合成低墨量和高墨量均覆盖，结果遵从现有 gate/backstop。
- [ ] 在 PgLineCanvas 内建立局部 reveal 生命周期。拟新增入口 `begin_section_reveal()`，在离开页 capture 完成之后、FFT page 显示之前，对现有每个目标 Pane 的 canvas 分别调用；新建 Pane 由原渲染生命周期接管：停止旧的升级请求，仅调整呈现 AA 状态，保留曲线/范围/历史。结束由真实内容 paint 与最终几何就绪驱动，使用现有独立离散结算；不等待导航动画。
- [ ] 生命周期状态由 PgLineCanvas 初始化和清理：generation、是否等待首帧、是否有 geometry/range pending。`full_reset`、隐藏、销毁和结果替换清理旧回调。新结果正常渲染与 retained reveal 同时出现时，统一由当前 generation 结算一次。
- [ ] 先按上述方案实测。若首帧虽然便宜，AA 恢复却在动画中引入同样长停顿，则该方案不达性能门；不得靠固定延迟或永久禁用 AA 交付。使用现有 latch 的真实成本证据继续定位，改变阈值需另修治理合同并重新标定。
- [ ] 接入 capture stability：内容就绪/质量稳定可正确被读取，隐藏页取消不能使 UltraView 主动同步永久等候；新 reveal hook 不触发 replot callbacks 或重置历史。
- [ ] 保持 toolbar 业务 signal 时序；不在本任务顺手重排 `_apply_mode`。若剩余同步投影仍阻碍首次反馈，另以真实点击时间线定位，不能仅靠先启动动画宣称已解决。

**Focused 门：** 新增 reveal nodes、`test_pg_line_canvas.py::test_plot_spectra_returns_with_aa_off_and_discrete_timer_armed`、`test_pg_line_canvas.py::test_backstop_trips_and_blacklists_spectrum_signature`、`test_pg_quality_backstop.py`、已有两条 FFT round-trip 回归。Cocoa 必须验证实际首帧、最后一帧和中间无空白；offscreen 只证明状态机。

### T2 — 时域回切保留全部绘图职责，缩小进度事件泵

**Owner / files:** `mf4_analyzer/ui/main_window/window.py`；仅需要承载已证明的回调身份时扩展 `_state_holders.py:TimeRenderGate`。测试 `tests/ui/test_section_entry_presentation.py`、`tests/ui/test_compute_progress_integration.py`、`tests/ui/test_timedomain_mode_switch_empty_frame.py`、`tests/ui/test_view_switch_reentrancy.py`。

- [ ] 写失败测试 `test_time_section_entry_preserves_plot_side_effects_without_global_progress_pump`：仍调用风险/prepare/delta-or-rebuild/范围/ticks/诊断/状态结束；token 成对结束，begin 不因本次回切泵整个事件队列。原有加载、主动绘图、设为左轴和项目恢复入口维持默认行为。
- [ ] 为 Section 回切单独传递 keyword-only 原因，不修改所有 `_plot_time_preserving_xlim()` 调用者的含义。拟定 `_plot_time_preserving_xlim(*, section_entry=False)` → `plot_time(..., section_entry=False)` → `_plot_time_on_canvas(..., section_entry=False)`；默认 False 完全保留现有调用合同。
- [ ] 仅该原因下 `_begin_compute_progress(..., process_events=False)`，由现有小进度控件 repaint 提供必要可见反馈。保留 update/finish 的 token 和异常 finally。不能把所有 `process_events` / `flush_events` 改成 False。
- [ ] 保留 `_canvas_display_update_scope` 和 `TimeRenderGate`。即使只 repaint 小进度条，Cocoa 也可能带出画布 paint，因此 full rebuild 的 clear 到最终恢复期间仍禁止空画面泄漏。不要扩大屏蔽更新范围到整个窗口。
- [ ] Section 延迟入口执行前核对当前 mode、待执行目标 View 身份及对象存活；重复回切待办最多保留最新有效目标。优先扩展既有 gate；不能仅捕获数组索引，也不能改变 UltraView 明确要求的串行逐源同步队列。
- [ ] 完整复测 cold/full rebuild、滤波、大数据、空/全隐藏通道及异常。若禁泵令长任务进度不可见或合法恢复依赖停滞，先恢复此局部改动；不得通过删掉反馈或静默吞异常换取性能。
- [ ] 分别记录 `try_apply_selection_delta` 命中、`plot_channels` 次数、范围/几何刷新与 paint；T2 不能声称“零重绘”或“整段缓存恢复”。

**门：** 上述 focused tests；同机 Cocoa time↔FFT 比较；保持范围/空帧、进度异常结束、项目恢复队列和关窗正确。T1/T2 独立计时，最后再测组合效果。

### T3 — FFT 事实整理只做一次相同输入准备

**Owner / files:** `mf4_analyzer/ui/main_window/_fft_mixin.py`；测试在 `tests/ui/test_analysis_multiview_integration.py`。不更改 `analysis_time_axis.py` 数值算法、不引入跨切换持久缓存。

- [x] 写失败测试 `test_fft_facts_reuses_prepared_signal_once_per_source`：当前 `_sync_fft_effective_facts` 先 fetch，接着 `_fft_effective_params_for_source` 又 fetch；要求同一来源同一范围在这两步只准备一次，最终 facts 分组和 cache key 保持相等。
- [x] 将 `_fft_effective_params_for_source(fft_params, fid, ch, time_range, *, prepared=None)` 作为兼容扩展。`prepared=None` 保留原 fetch；非 None 只接受同一调用刚取得的 `(sig, fs)`，包括 `(None, None)` 或空信号，继续走原有效参数分支。
- [x] `_sync_fft_effective_facts` 用同一份 `fft_params` 和 time_range 调 `_fft_fetch_signal(..., params=fft_params)`，然后传 `prepared=(sig, fs)`。所有正常、空、blocked/manual/auto-NFFT 行为仍由原 `_fft_effective_params_for_source` / `_resolve_fft_effective_params` 决定，不复制算法。
- [x] prepared 仅借用当前调用的数组，不挂在 MainWindow、不跨事件循环、不保存到 View/preset；不在生成 prepared 与消费期间泵事件。来源变化后的下一次调用重新准备。
- [x] 测试同名异源、不同 Fs、NaN/constant、短/空、非有限时间、非均匀时间、局部区间、缺源、Auto/Manual NFFT、result miss 与 blocked 事实。保留原有异常类型与提示，不放宽时间轴检查。
- [x] `_fft_preview_n_samples` 引发的另一次扫描先保留；本轮收益报告只计算已消除的重复准备。不能以此宣称跨回切所有扫描已清零。

**门：** 新增事实 prepared 节点、现有 FFT effective/auto-NFFT/分析时间轴相关 owner 节点以及既有 round-trip。T0 的事实快照逐字段相等；单独确认 cache key 与数值计算次数未变。

### T4 — 集成、真实数据验收与其他分区调查

**Owner / files:** `.state/section-switch-performance/`；新增 durable 验收记录 `docs/analyzer/verify/2026-09-12-section-switch-performance.md`，只在实施后填写真实结果。

- [ ] T1/T2/T3 各自 focused 和适用边界通过后，测组合结果，不叠加各阶段百分比。
- [ ] 按 §5 运行真实 Cocoa 场景，包含当前用户实际数据（可用时）和相同窄/宽窗口。没有原数据时标记客户验收 `UNVERIFIED`，不以合成序列替代。
- [ ] 时频/阶次/频响分别测 empty、cached、split、切片开/关、结果到达前切走。它们目前在 `_render_analysis_view_from_cache` 下重绘，不能直接套 FFT 的 signature 或 AA 生命周期。
- [ ] 若其他分区仍有显著问题，记录具体 owner/副作用/耗时，另增明确任务后实施；本阶段没有自动授权跨三个分区改造。
- [ ] 用户主动 UltraView 同步、切换后立即复制/导出、项目保存再打开、图卡历史与游标读数完成验收。不得仅用曲线数量和截图相似度替代。
- [ ] 检查 lessons 状态；本次 docs-only 不创建推测性教训。实施中若回归证实复发模式，按项目流程记录与关闭。

## 5. 验证设计与性能目标

### 5.1 测量协议

- 同机、同 DPR/窗口/曲线 pen、同数据/参数/可见范围；新旧实现交错分组，各 5 次 warmup 后每方向至少 30 次 warm 样本，cold 独立新进程测量。输入间隔由 Qt timer 调度，覆盖正常点击和快速连点。
- 正式性能组关闭 cProfile、全函数 wrapper 和额外截图；轻量记录回调、paint、heartbeat。详细归因组单独运行，不能混用分位数。用独立录屏/截图核对视觉，不把它的耗时当正式基准。
- 分开报告：input callback、首个导航反馈 paint、目标内容 ready、稳定质量 paint、最大单次 paint、heartbeat lag、>16.7 ms 样本比例。报告 P50/P95/max 与样本数；无 compositor 时间戳时不声称显示器 FPS。
- 内容 ready 需要目标 Section/View/Pane 身份、完整曲线和最终范围正确；stable 还需必要数据/geometry/reveal pending 收敛。AA 被既有 gate 拒绝仍可稳定，不要求所有质量点变绿。
- 初始 probe 的 `pump_max_ms` 只作诊断旁证，不作为新验收指标。固定等待时间不能记入内容完成耗时，timeout/异常退出为 `UNVERIFIED`。

### 5.2 场景与门

| 场景 | 必须保持的行为 | 性能门（待测目标） |
|---|---|---|
| 空页面与小数据 | 完整投影、即时选择、正确空态 | P95 不回退超过 max(基线 10%, 2 ms) |
| 2×1,188,000 点、cached FFT↔time | 数据/范围/身份/历史/游标一致；普通回切 0 compute submit | FFT 内容 ready P95 下降至少 25%；时域下降至少 20%；分别报告，不互相抵消 |
| 同场景最终质量 | 最终 AA 决策和画面符合已有合同 | stable P95 不回退超过 max(基线 10%, 5 ms)；不得把阻塞迁移到迟到的质量恢复 |
| 宽窗、低频窄窗、密集噪声/窄峰 | 原始频谱范围和低谷/峰值、包络、自动/手动 Y 正确 | 报告首显与后续最慢 paint，不能只测便宜窗口 |
| 双 Pane、焦点在副 Pane、隐藏/记录曲线 | 来源、颜色、轴组、范围、X 联动、历史分属正确 Pane | 不要求等同单 Pane，但不得有新增重复重建或明显性能回退 |
| 未算/部分缓存/缓存失配 | 保留预览、stale/空态和“点击计算”；不偷偷计算 | 不用 warm 性能要求迫使跳过必要恢复 |
| 冷加载、项目恢复、结果异步到达 | 任务按 View 身份准确完成；token/dirty 合同成立 | 冷路径 P95 不回退超过 max(基线 10%, 5 ms)；进度可见 |
| 连点、resize/DPR变化、关闭 | 最新目标一致；旧 callback 不改隐页/销毁对象；最终 geometry 结算正确 | 最后输入到正确最终画面单独报告，不积压整队无效渲染 |
| UltraView/导出/复制/历史 | 正确 ref、稳定图片、可继续回退前进 | 不出现永久 pending、旧图误发布、额外计算 |

这些是同机优化目标，不是已经达成的数值，也不是所有机器的 60/120 Hz 承诺。功能门失败优先撤回该步骤。功能通过但性能目标未达成则记录 `partial` 并定位剩余成本，不能宣布整体完成或自动启动高风险复用。

### 5.3 Focused 与边界命令

新增测试文件/节点在任务中已明确；实施时先跑对应新增 node 的失败→修复→通过，再运行其 owner 文件。以下是集成阶段清单，不是每个任务反复重跑的模板。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_section_entry_presentation.py tests/ui/test_compute_progress_integration.py tests/ui/test_timedomain_mode_switch_empty_frame.py tests/ui/test_view_switch_reentrancy.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -k 'section_switch_away_and_back or weighting_drift or facts_reuses_prepared_signal or viewport or auto_y or range_adapter' -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_line_canvas.py tests/ui/test_pg_quality_backstop.py tests/ui/test_toolbar.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_view_switch_integration.py tests/ui/test_split_routing.py tests/ui/test_analysis_source_scope.py tests/ui/test_file_scope_follow.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_ultraview_capture.py -k 'stability or unstable or replot_same_view or user_sync or ignores_destroyed or yellow_aa or red or ref' -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_project_dirty_guard.py -k 'programmatic or selection_render_preview or close_cancel or reentrant_close' -q
```

- 每条 `-k` 执行前用 `--collect-only` 检查节点清单，0 selected 不是通过。项目恢复、历史和导出场景若现有 node 不足，T0 新增具体端到端断言，不能仅靠宽泛筛选名称充当覆盖。
- 修改 time quality 或其结算时补 `tests/ui/test_pg_timedomain_canvas.py` 的 `TestViewRestoreSettlement`、`TestDiscreteSettle` 与 paint backstop；未修改时域质量算法时不跑整份大型画布套件。
- T3 补 `tests/signal/test_fft_effective_facts.py`、`tests/test_analysis_time_axis.py`、`tests/signal/test_auto_nfft_compute_contract.py`，验证事实、空/短/非有限和 NFFT 合同。没有数值算法改动不扩到全部 signal suite。
- 历史门复用 `tests/ui/test_standard_desktop_interactions.py::test_chart_camera_history_uses_alt_left_right_not_undo`，同时由 T0 补实际 Section 往返后的 history 行为；普通导出/复制和 UltraView 主动同步的组合场景放入新增 presentation 文件，不以 toolbar 孤立测试替代。
- 适用边界：`tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`。若引入中立模块变更，追加对应无 GUI import gate；不得把 UI 状态塞进 signal/io。
- UI 外观不改，不新增措辞测试；若实施改变用户可见恢复/反馈语义，同步 `ui/hints.py`、`ui/quickref.py` 并重审本计划。
- 本阶段不属于 release/全局架构重构，默认不跑 full suite。若新发现证明需要全门，先记录原因、检查现有 pytest 进程，单一协调者在稳定快照中顺序跑 main（排除 acquisition_ui）和 acquisition_ui；不得重叠或重复稳定里程碑的全门。
- Cocoa、foreground TraceLab 客户文件、Windows source packaging 和 Windows frozen 分别记录。没有新 frozen 运行就不声称 Windows 性能验收。

## 6. 后续高风险方向：满足证明条件后再单独展开

**完整时域恢复复用目前不进入第一阶段。** `FileData` 已有 `source_instance_token`、`time_axis_revision`，但它们不是完整通道内容/显示/滤波版本；`_selection_array_fingerprint` 的指针/shape 也不是原地内容变化的充分证明。`_fft_render_signature` 面向 FFT 原有局部用途，不能复用为全分区有效性 key。

若第一阶段仍无法满足体验目标，下一份实施任务必须先完成：

1. 枚举所有会改变时域数据、显示、轴组、记录曲线、全局单位/颜色、滤波与 Custom-X 的 mutation owner；每个事件都有失效断言。无法证明的数据来源一律回退现有路径，不进行 O(N) 全数组 hash 来“节省”绘图。
2. 把复用资格分成内容仍有效、几何仍有效和业务投影已完成。内容相同但 resize/DPR/分屏改变仍要刷新正确分辨率、ticks、ink 与 raster。
3. 将 §2 中原本依赖 plot 的必要副作用提供明确保留路径，特别是风险提示、cursor X context、诊断、统计、范围输入和捕获可用状态；每项有行为对照，不能仅证明少调用一次函数。
4. 证明已有 selection delta 为什么仍不足，再决定新增 owner-held cache，而不是新增跨 MainWindow 写入的并行状态。
5. 提交窄范围方案和回归/性能证据；未完成以上证明不得删除 `QTimer.singleShot(0, ...)` 后的业务恢复或把所有分析分区统一改成“有缓存就返回”。

## 7. 初始文档交付检查（历史）

本次仅新增本 plan。验收为：读取并核对引用的实际 owner、识别共享函数的其他调用者、检查既有相关测试和相邻性能计划、完整回读本文、检查引用/陈旧标识与 `git diff --check`。没有修改可执行行为，不运行 runtime suite；这不是产品功能或性能通过声明。

保留当前无关 dirty 文件与现有频谱拖动 plan。无提交、推送或全局工具修改。
