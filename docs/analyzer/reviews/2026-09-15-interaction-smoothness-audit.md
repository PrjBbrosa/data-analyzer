# Analyzer 交互流畅性与鲁棒性审查

日期：2026-09-15。当前版本：v8.2.4；审查 HEAD：`f28f5820591810636ca061c80b416dc9a78816a1`。

## 结论

**有明确且值得优先处理的优化空间。用户最关心的 View 切换、分析页面切换、勾选通道，主要问题是同步重复投影、重复准备数据，以及计算缓存与显示缓存之间的断层。** 可以先减少重复工作，保留现有数值与状态语义；进一步异步化需要明确任务身份、失效和取消合同。

另外复现了一个条件性严重问题：百万点信号同时显示原始与滤波曲线时，即使显示数据已减至约 2,004 点、AA 已关闭，Qt 路径绘制仍可让一次重绘阻塞十余秒。该问题应单列处理，不能假定已有降采样与 AA 回退已覆盖全部昂贵绘制。

本轮只做分析、诊断探针和报告，没有修改产品代码。原有未跟踪项 `ssh-keygen` 未读取、未修改。未提交、未推送。

## 证据与测量口径

- 代码：直接阅读当前 checkout 的实际事件入口、状态投影、数据准备、画布、任务与缓存实现。
- 实测：项目 `.venv`，真实 macOS Cocoa，1600×950，DPR 2，Fusion + 生产 QSS，独立 MainWindow，隔离 QSettings，合成数据。
- 时域 View/Section 通过 QTest 点击；分析 View 调用产品切换槽；通道勾选通过真实 QTreeWidgetItem 检查状态信号。它们不等同于全部真实鼠标操作验收。
- 普通计时只加少量方法包装；单独运行 cProfile 做归因。**两类结果不混合。** 子方法为包含耗时，存在嵌套，不能相加。
- 表中的时间是操作同步回调返回时间。Section 的延后绘图不全包含在其中；另统计随后 240 ms 事件循环中的调用次数。没有测 compositor 呈现时间，不能换算 FPS，也不能宣称达到首帧/稳定帧目标。
- 每组 View/勾选操作采 4 次，Section 每方向 2 次，适合定位结构性问题，不足以发布 P95/P99 性能验收结论。
- 重复 View 使用相同附件、相同已选源，FFT 数值结果已缓存。这是检查“本来可以复用，却仍在做工作”的场景；复杂拓扑切换未纳入。
- 三组诊断和补充剖析的源码快照检查均一致；前后 Git HEAD 相同，产品源码无差异。

### 本机观察值

|合成文件|时域 View 切换|勾选/取消第 3 通道|FFT View 切换|
|---|---:|---:|---:|
|500 个候选通道，每通道 1,000 点；初始绘制 2 条|67–69 ms|60–84 ms|94–97 ms|
|2,000 个候选通道，每通道 1,000 点；初始绘制 2 条|130–156 ms|155–170 ms|222–226 ms|
|4 个候选通道，每通道 1,000,000 点；初始绘制 2 条|24–35 ms|19–89 ms|73–78 ms|

这是不同场景之间的定位比较，不是优化前后 A/B。勾选组包含首次新增行和后来复用行，不能把两者视为同一耗时分布。

在 2,000 候选通道组中，FFT Section 进入的同步回调约 207–210 ms；其间约 153 ms 是候选列表重建。此时保留画布命中，未再次调用 `_plot_fft_entries`。

## 按严重性与用户路径排序的发现

### F1 · P1 · 滤波叠加存在十余秒的 GUI 绘制阻塞

**触发：** 两条百万点信号，时域分图，同时显示原始与低通滤波曲线，宽时间窗口，重复绘图。

**当前证据：** 第一组合成信号非 cProfile 回调 14,761.7 ms，其中两次 `filter.apply` 合计 31.6 ms，`plot_channels` 47.6 ms。第二组独立合成信号的 cProfile 归因：回调 18,064 ms，两个 GraphicsView paint 合计约 17,960 ms，`QPainter.drawPath` 约 17,882 ms，滤波约 30 ms。两组波形不同，不能把 14.8→18.1 秒视为同一场景回退。

补充剖析前后各曲线均为约 2,004 个显示点，AA=False；原始线为 SolidLine，滤波线为 DashLine。本地 pyqtgraph 的 `_shouldUseDrawLineSegments` 将虚线排除在快速 `drawLines` 路径之外；慢 `drawPath` 的直接证据已经成立，线型与几何各自贡献尚需专门 A/B 拆分。

**还有一次操作触发两次昂贵 paint：** 约 8.99 秒落在 `_begin_compute_progress → processEvents`，另约 8.98 秒落在 `_update_compute_progress → ComputeProgressWidget.set_progress`。这说明“只刷新进度控件”的预期仍可能在实际 Qt 路径中触发图表绘制，不能只检查显式 `canvas.repaint()`。

代码位置：`mf4_analyzer/ui/main_window/window.py:711`、`:738`、`:4056`；`ui/compute_progress.py:186`；`ui/pg_canvas/canvas.py:1968`；`ui/pg_canvas/quality.py:174`。本地依赖证据：`.venv/lib/python3.12/site-packages/pyqtgraph/graphicsItems/PlotCurveItem.py:769`、`:1004`。

**优化方向：** 将该宽窗虚线路径纳入现有绘制质量 owner 的成本控制与缓存复用，审查进度更新触发的中间帧；先做逐曲线/线型/几何 A/B，随后选择保留区分度的显示实现。仅关 AA 或把滤波移入 worker 无法解决这个已复现的主要耗时。不应直接删除滤波线、减少真实数据、取消峰值保真，或未经验证切换全局 GPU 后端。

### F2 · P1 · 时域切换与勾选都会重复投影整棵通道树

**路径：** `_ch_changed → _replot_canvas_for_view → _render_view_onto_canvas → apply_controls_from_state`，finally 再 `_project_view_controls → apply_controls_from_state`。普通 View 切换同样经过这两次投影。第二次对恢复副栏共享控件有意义，但单栏主 View 也无条件执行。

`apply_controls_from_state` 依次设置附件、颜色、勾选、隐藏状态。树实现没有充分的内容未变判断：设置附件与勾选分别跑 `_apply_filters`；颜色恢复遍历所有叶节点，并重新创建色块 QPixmap/QIcon；最后再投影一次。

**实测：** 2,000 通道、仅显示两条曲线，一次 warm 时域切换有 2 次完整控件投影、4 次过滤遍历、12 次 checked 查询；最后一轮两次控件投影合计 121.1 ms，其中颜色 setter 合计 72.3 ms。真正 `try_apply_selection_delta` 约 1.4 ms。勾选通道有 5 次过滤遍历、14 次 checked 查询。

代码位置：`ui/main_window/window.py:3567`；`ui/main_window/_view_mixin.py:292`、`:703`、`:1263`；`ui/view_bridge.py:184`；`ui/widgets/channel_tree.py:1447`、`:3041`、`:3107`、`:3301`；`ui/widgets/_swatches.py:30`。

**优化方向：** 在既有 View 投影事务中识别主/副栏恢复需求；对附件、颜色、checked、hidden 做差异投影；一次事务只结算一次过滤、父级勾选和布局。相同颜色/尺寸/DPR 的色块可在 Qt GUI owner 内有界复用。保留搜索展开状态、复合通道身份、隐藏曲线与副栏恢复语义。

**预期价值：** 对用户当前问题覆盖最广，而且大量收益来自消除无效 Qt 工作，不需要改变数值算法。

### F3 · P1 · 分析 View 每次切换都清空并重建候选列表

**路径：** `_on_analysis_view_switched` 无条件 `_refresh_analysis_candidates`；FFT/FFT-vs-Time/Order setter 清空 combo 后逐项 `addItem`，FRF 对两份 combo 重复填充。附件集合及通道目录未变也这样做。

更底层的 `SearchableComboBox.addItem` 每加一项，都重新检查 completer 绑定、设置委托并同步 popup 几何；虽然已避免把同一 source model 重复绑定，外围工作仍逐项执行。这里有明确重复开销；未证明为 O(N²)，不作该复杂度断言。

**实测：** 500 候选条目，FFT View 回调 94–97 ms，其中候选重建 51–52 ms；2,000 条目时回调 222–226 ms，候选重建约 160 ms。进入 FFT Section 命中保留画布也仍承担候选重建。

代码位置：`ui/main_window/_analysis_mixin.py:763`；`ui/main_window/window.py:3412`；`ui/inspector_sections/contextual_fft.py:823`、`contextual_order.py:652`、`contextual_fft_time.py:438`、`contextual_frf.py:505`；`ui_kit/widgets/searchable_combo.py:307`、`:351`、`:383`。

**优化方向：** 以附件身份、通道目录/名称/顺序 revision 判断候选列表是否真正变化；同候选只切换选中身份。必要更新提供批量入口，popup/delegate/geometry 最后同步一次。不能破坏目前为 Cocoa model reset 问题保留的 proxy detach/rebind 顺序，也不能把未选择状态自动设为首项。

### F4 · P1 · 数据准备发生在增量判断之前，还会让相同内容失去复用

**路径：** `_plot_time_on_canvas` 先 `_build_time_plot_data`，再 `try_apply_selection_delta`。前者对全部可见已选通道准备数据，范围开启时用布尔 mask 创建新数组，滤波开启时每条源重新执行 filter。后者用数组内存地址、shape、stride、dtype 判断 source revision。

因此，即使源、范围、参数完全没改，重新截取/滤波产生新地址，也会落到 `source-revision-changed`，继续重建画布。这是当前身份合同下的合理防旧数据保护；问题应修在上游稳定准备结果，而不是把这个检查删掉。

**实测：** 百万点组，同一范围重复两次 `plot_time` 均得到 `source-revision-changed`，发生完整 `plot_channels`，同步回调 72.1/87.5 ms。相同滤波重复绘图也失败于该 guard，两条过滤均重复计算。

代码位置：`ui/main_window/window.py:4086`、`:4162`、`:4278`、`:4497`；`ui/pg_canvas/canvas.py:1296`、`:1375`、`:1480`。

**优化方向：** 在数据准备 owner 建立有界的准备结果复用，先识别哪些源/参数变化，再准备新增/失效通道；同一已验证时间轴/范围复用切片索引。单调时间轴可使用边界索引，非单调、NaN、重复时间、Custom-X 保留当前明确语义。不能用显示名作 key，也不能每次点击重新 hash 全部样本来判断是否变化。

滤波缓存必须保留当前“先按采集时间截取，再滤波”的边界语义；不能擅自改为全段滤波后截取，两者结果可能不同。

### F5 · P2 · FFT 计算命中缓存后，数据扫描与显示重建仍较多

**当前链路：** FFT Section 回切已有 `_fft_render_signature` 保留画布复用，但 FFT View 切换仍走 `plot_spectra`：重新准备范围索引、删除两排曲线、创建频谱与时域预览曲线、恢复范围与标注。

另外 `_on_analysis_view_switched` 在 `_render_analysis_view_from_cache` 返回后同步 effective facts，而后者末尾已经同步过一次。facts 的健康信息会扫描信号有限值与极差；取信号的 `_fft_fetch_signal` 又会验证时间轴，`materialize=False` 只避免建新网格，并不避免 `isfinite/diff/min/max` 扫描。

**实测：** 两条已缓存源一次 FFT View 切换共 10 次 `prepare_analysis_time_axis`、2 次 facts 同步。百万点组约 10–11 ms 在时间轴准备，约 54–57 ms 在 `_plot_fft_entries`；总回调约 73–78 ms。小样本双源同样有 10 次时间轴准备，只是扫描成本较低。

代码位置：`ui/main_window/_analysis_mixin.py:763`、`:2298`；`ui/main_window/_fft_mixin.py:342`、`:434`；`ui/main_window/window.py:1654`、`:1786`；`ui/pg_canvas/line_canvas.py:1819`；`analysis_time_axis.py:18`；`io/file_data.py:98`。

**优化方向：** 先把同一投影事务的 facts 同步收敛为一次，并复用调用内准备；再以源/时间轴 revision 缓存已验证事实。为各 Pane 增加明确的显示结果复用判定，覆盖结果 generation、显示参数、dB reference、源颜色/单位、范围与 viewport origin。不同 View 的坐标范围、游标、标注不能因数值结果相同而被跳过恢复。

FFT-vs-Time 有局部 dB 缓存，但热图更新仍会扫描有效值/范围并 `setImage`；Order 的 cache restore 还会在调用侧重新进行 dB 变换。不能将 FFT 的保留画布能力直接视为其他三个分区已具备。代码：`ui/pg_canvas/heatmap_canvas.py:875`、`:1396`；`ui/main_window/_order_mixin.py:600`。这些分区本轮只有代码证据，未跑相同性能矩阵。

### F6 · P2 · 主线程重任务与任务生命周期还不统一

- 普通 FFT 的 `do_fft` 与项目恢复 FFT 仍同步执行 `_fft_compute_arrays`。FFT-vs-Time/Order/FRF 才走现有 `AnalysisJobService` 或 coordinator。代码：`ui/main_window/_fft_mixin.py:541`、`:620`、`:679`。
- `_load_one_impl` 同步调用 MF4/Excel 等 loader，靠阶段进度和排除用户输入的事件泵反馈。代码：`ui/main_window/_project_io_mixin.py:778`。
- `save_project` 在 GUI 路径采集状态、保存预览 sidecar，再写 authoritative JSON。语义 JSON 本身是引用式项目；潜在重项主要是预览/序列化/I/O，需要分别测量。代码：同文件 `:2112`。
- worker shutdown 在等待 2 秒后存在 `terminate()` fallback。它是现状风险，不是推荐的取消方法。代码：`ui/analysis_jobs.py:208`。扩大 worker 使用前，应审查协作取消和关闭行为，不能把强杀线程作为流畅性的保证。

**优化方向：** 扩展既有服务支持耗时的纯数据工作，GUI 线程只负责短的状态提交和 Qt 创建/绘制。保留任务 generation、源/目标 View 身份校验，避免后台任务访问可变 Navigator/Inspector。不要建立第二套彼此独立的队列与状态旗标。

### F7 · P2 · 点击后的附带截图也会参与事件循环竞争

UltraView 在 View 渲染后安排预览 capture，`_start_timer` 使用 0 ms 单次 timer。正常时域切换的 cProfile 中，后续 dispatch 出现 `_publish_grab` 约 17 ms，其中抓图约 13 ms。此测量有 profiler，不能作为稳定延迟指标；它确认了附带工作确实执行。

代码：`ui/main_window/_view_mixin.py:803`；`ui/main_window/ultraview_capture_coordinator.py:1313`、`:1766`。

**优化方向：** 继续使用现有 capture owner 的 digest、generation、几何稳定与弱引用校验；合并重复请求，为前台交互留出优先级，正常预览可按稳定帧/预算延后。用户显式抓图、离开源前必要捕获和保存所需快照需单独保留，不能盲目把所有 capture 都禁用。

### F8 · P2 · 缓存按条数与 View pin 管理，缺少数值结果字节预算

当前分析缓存上限针对未 pin 的条目；被 View 引用的结果不受该条数上限约束。FFT 32、其他分区 12 是未 pin 条数预算，不是总结果数或总字节上限。多个 View、大频谱/大热图组合存在内存上升与系统换页的可能，影响“用久以后越来越卡”。本轮未复现内存压力，不将其报告为当前已发生的泄漏。

代码：`ui/analysis_cache.py:1`、`:18`、`:42`；`ui/main_window/window.py:567`。

**优化方向：** 先记录结果/准备数据/显示/预览各层真实常驻字节及共享数组；新增缓存必须有明确字节预算和清理归属。现有 pin 是“View 切换不能突然丢结果”的产品合同，不能直接驱逐 pinned 结果换取数字好看；如要引入落盘或压力退化，需要单独定义恢复行为。

## 其他交互的覆盖与剩余问题

|操作|本轮结论|后续重点|
|---|---|---|
|时域 View、FFT View、勾选|代码 + Cocoa 诊断，以上为明确问题|先处理 F2/F3/F4，F1 条件性严重问题单列|
|FFT/时域 Section 往返|代码 + Cocoa 诊断|保留已有 FFT reveal；减少周边投影；测首反馈与最终稳定帧|
|FFT-vs-Time、Order、FRF 切换|代码审查|按结果、显示参数、几何分层复用；分别实测|
|时域/FFT 平移缩放|已存在 envelope/显示缓存、节流、AA quiet window、paint backstop|本轮未重测常规拖动 P95；重点补虚线、叠加、双 Pane 高成本路径|
|单游标|已有 33 ms 更新节流|需要测读数/布局成本，不先把刷新率调高|
|双游标|区间统计有整段布尔筛选与有限值/extrema 扫描|索引/统计复用是候选；主路径为点击放置与恢复，不声称每个鼠标移动都扫描|
|热图切片|拖动每次寻找最近索引并 `_apply_slice`|索引未变时跳过数据重写、合并范围与布局；需保留末次更新|
|文件加载、保存/导出、项目重开|关键同步路径代码审查|长任务分阶段反馈与后台纯数据工作；本轮未实测完整 I/O|
|UltraView、Batch、采集全链路|只检查相关 capture/任务边界|本轮没有完整交互审查与性能验收|

游标与切片证据：`ui/pg_canvas/cursor.py:700`、`:1160`；`ui/pg_canvas/slice_panel.py:283`、`:350`。统计条当前 `_STATS_STRIP_ENABLED=False`，因此不能把 `_build_time_statistics` 里的全数组统计当作默认时域卡顿主因。

## 建议实施顺序与负责边界

下面是后续建议，并非本轮已授权实现的变更。

|顺序|目标与 owner|收益/风险|聚焦验证|
|---|---|---|---|
|1|F1：`pg_canvas` 质量/绘制 owner 与进度 owner 联合定位并消除长 paint|条件性巨大收益；需原始/滤波可区分、峰值/NaN/导出验证|`test_time_filter_overlay.py`、`test_timedomain_hotpath_perf.py`、画布 paint backstop、真实 Cocoa 宽窄窗/线型对照|
|2|F2/F3：View 投影与 Navigator/Inspector 候选更新去重|对当前常用操作最直接；不改数值|`test_view_switch_reentrancy.py`、`test_searchable_combo.py`、`test_section_entry_presentation.py`；500/2000 候选 A/B|
|3|F4/F5：准备数据与 facts 复用，收敛一次投影的重复工作|大数据与滤波收益；失效正确性是主要风险|`test_time_filter_overlay.py`、`test_analysis_time_axis.py`、`test_file_data_time_axis.py`、`test_analysis_multiview_integration.py`、prepared range owner tests|
|4|F5/F7：显示结果分层复用、捕获调度|进一步降低切换后长尾；避免只改善回调时间|`test_section_entry_presentation.py`、`test_ultraview_capture.py`、各画布 owner tests；稳定帧和交互 heartbeat|
|5|F6/F8：扩展现有任务服务、建立缓存字节观测|改善重任务与长会话；生命周期和内存合同需先明确|`test_analysis_jobs.py`、`test_analysis_cache_pinning.py`；取消/关闭/源删除/项目重开和长会话压力|

相应改动再按实际边界选择 `test_main_window_state_ownership.py`、`test_pg_canvas_backref_invariants.py`、导入边界等；不为每项重复跑完整 UI suite。

## 鲁棒性必须保持的合同

1. **状态只由原 owner 持有。** View/Panes 保存用户意图；Navigator/Inspector 是投影。去重不能让副栏、附件、隐藏通道、Custom-X、坐标范围或 viewport origin 串入其他 View。
2. **稳定身份与失效。** 数据准备 key 至少审查源/通道、数据与时间轴 revision、采样率、采集时间范围、滤波参数及 X 解析身份；显示 key 另外审查结果 generation、dB reference/单位/颜色/显示选项与几何/DPR。不要用对象地址假装语义版本，也不要因缓存而跳过必要的数据验证。
3. **只合并可替代的绘制/导航请求。** 最后一次导航意图可以覆盖旧导航；新增/删除通道、参数提交、保存等语义操作仍需准确记录。现有 TimeRenderGate 的“渲染中到来的请求最后一个生效”不等于普通 Qt 输入队列里的每个点击都会自动被合并。
4. **异步结果先校验再提交。** 任务完成时核对窗口存活、View/Pane/source 身份及 generation。Qt 对象只能在 GUI 线程创建和绘制；取消用协作机制，禁止旧结果回写。
5. **保真与收尾。** 空/短/非有限/非单调数据、边界端点、峰谷与 NaN 断点均保留既有合同；交互结束必须精确结算；导出与屏幕显示不得取得未完成/旧 generation 图像。
6. **缓存不能无限增长。** 复用收益必须与峰值内存一起验收；保留 View pin 的可见结果保障。

## “有预期”的可验收定义

建议为这次工作明确三个不同时间点：**操作被接收的可见反馈、目标内容正确出现、最终质量与几何稳定。** 只记录槽函数返回或 cache hit 无法代表后两者。

- 优先报告 P50/P95/P99、最长主线程阻塞、>50/100 ms 的事件循环延迟次数，并分离冷/热路径。建议将约 50 ms 内可见反馈、常用 warm 切换约 100 ms 内内容就绪作为第一轮工程目标；这是建议目标，不是当前已通过的门限。
- 重任务显示实际阶段；能准确计算分母时才显示百分比，其他阶段用不定进度。确认用户意图后尽快给反馈，耗时内容按对应 View 身份提交，不能出现新标签下可交互的旧数据。
- 对快速 A→B→C、连续勾选、切换中删除/重排 View、关闭源、关闭窗口、取消与失败分别检查最终身份和视图一致性。
- 小数据、高候选数、百万点、多源/多采样率、滤波、范围截取、Custom-X、双 Pane、热图和高 DPI 必须分组。不能只用一种“大文件”替代整个矩阵。
- 性能验收使用无 cProfile 的真实输入和自然 paint，同机稳定快照交错 A/B；截图/结构门、Cocoa、客户文件、Windows frozen 分开记录。

## 已执行的验证与限制

隔离 Cocoa 探针 3 组均正常退出，补充滤波剖析正常退出。诊断位于 `.state/smoothness-audit-20260915/`：`probe.py`、`c500/result.json`、`c2000/result.json`、`million/result.json`、`filter_probe.py`、`filter-profile/profile.txt`。

聚焦验证命令：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_view_switch_reentrancy.py \
  tests/ui/test_section_entry_presentation.py \
  tests/ui/test_analysis_jobs.py \
  tests/ui/test_analysis_cache_pinning.py -q
```

结果：**38 passed，82 warnings，7.83s**。warnings 为本地 pyqtgraph 使用 NumPy shape 赋值的 deprecation。它们支持现有防重入、切换、任务和 pin 合同仍通过，不证明性能改善或整个产品无缺陷。

本轮未跑全套、客户文件矩阵、Windows frozen，未进行修改后的性能验收，因为产品实现尚未改变。此前的性能报告仅作为查找线索，未把历史数字当作当前测量。
