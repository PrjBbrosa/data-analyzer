# TraceLab 频谱拖动性能优化 Implementation Plan

> **For agentic workers:** 使用 `superpowers:executing-plans` 顺序执行。本计划仅为分析与文档，不授权产品实施、派生 agent、提交或推送。实施步骤使用 checkbox 跟踪。

**Goal:** 降低频谱平移和缩放中的重复扫描、抽点与自动 Y 开销，缩小更新耗时波动，同时保持完整频段、深谷、窄峰、NaN 断点和真实范围恢复正确性。

**Architecture:** 复用时域的交互调度原则，保留频谱自己的 peak trace 和原始幅值适配语义。结果接入时准备查询信息；交互时按覆盖范围、有效样本区间和显示密度复用数据；曲线更新与自动 Y 共用受控刷新事务。先优化现有 owner，不抽出跨所有 canvas 的统一大基类。

**Tech Stack:** 当前 NumPy、PyQt5、pyqtgraph、pytest/pytest-qt；真实 macOS Cocoa 事件/绘制探针与受控无 profiler 性能测量。

日期：2026-09-12。源码调查 HEAD：`21c3ef12`。状态：**计划完成；性能优化尚未实施**。

关联：[自动范围正确性计划](2026-09-11-analysis-auto-range-correctness-plan.md)、[该阶段验收记录](../verify/2026-09-11-analysis-auto-range-correctness.md)。本次建立在当前已实现的范围逻辑上，不退回全频段粗抽点或裁谷规则。历史验收不替代本次稳定快照验证。

## 1. 对现有结论的评审

**结论基本成立，优化方向可采用；“先覆盖缓存、最后窗口查找”的顺序应调整。** 覆盖缓存不能修复同步自动 Y 对全量数组的扫描；这两类开销需要分别消除，并用同一个刷新事务协调。

| 判断 | 当前证据与限定 |
|---|---|
| 平移导致重复绘图 | `line_canvas.py:_refresh_spectrum_display` 的 key 包含精确浮点 `xlim`；窗口一移动就 miss，调用 `_spectrum_plot_arrays` 和每条曲线 `setData`。即使窗口仍包住全部数据，也会重复生成同样的显示内容 |
| 大数组反复扫描 | `_spectrum_plot_arrays` 对整个 freq 做 finite/inside/crossing 判定；`display_ranges.py:visible_line_values` 对整条 X/Y/valid 做窗口及两侧交点判断。每次查询都是按总长度工作，不只是按可见数据量工作 |
| 自动 Y 绕过 16 ms 调度 | `_emit_viewport_intent` 对纯 X 操作同步调用 `_fit_active_spectrum_y`；原始可见幅值扫描与 `setYRange` 发生在拖动回调内 |
| 时域复用更充分 | `canvas.py:_schedule_coarse_refresh_if_needed` 先检查 coverage；出缓存才受限刷新，`_settle_visible_data` 最后精确更新。有 generation、防旧回调和 timeout 时再检查间隔的机制 |
| 导航动画时长导致拖动慢 | 当前热点链是 ViewBox→原始数据查询/抽点→setData/paint，并未经过选择背景动画；没有依据通过修改 320 ms 动效解决这些开销 |

原探针已找到并读取：`.state/fft-drag-analysis/probe.py`、`results.json`、`fft-True-profile.txt`、`fft-False-profile.txt`、`time-False-profile.txt`。

| 历史探针场景 | 单次回调+processEvents P50 | P95 |
|---|---:|---:|
| FFT，自动 Y | 8.96 ms | 20.47 ms |
| FFT，手动 Y | 2.57 ms | 13.84 ms |
| 时域对照 | 5.40 ms | 6.40 ms |

这些数值与用户转述一致。profile 的 39 次被测拖动内，自动 Y 查询约 188 ms，频谱抽点路径约 194 ms；它们支持热点判断。嵌套函数累计耗时不可相加当作总耗时，results 的调用计数还包含边界事件，不应等同于 39 次采样次数。

**测量限制：**

- 开启 cProfile 与函数计时 wrapper，会扰动大量 Python 桶循环的耗时。
- 无事件节奏控制，连续直接调用 ViewBox.mouseDragEvent，再 processEvents；自动 Y 较慢时也给 16 ms timer 更多触发机会，因此不能把调用次数差全归为算法差。
- 仅两个约 59 万点合成序列、一个宽视口（-11000..21000，数据 0..12000）、一个执行顺序和一组短样本；没有用户原文件、窄窗/缓存边缘/真实拖动的全面对照。
- 时域与 FFT 的布局、Y 策略、绘制项目并不完全相同；不是公平的完整渲染算法跑分。
- 脚本未保存 Qt platform、DPR、窗口实际几何、HEAD 和环境清单；本次未独立复跑验证其 Cocoa 环境。按“现有探针证据”引用，不能声称已证实用户屏幕的掉帧率或整机 FPS。

## 2. 哪些可以复用时域，哪些不能

| Canvas | 可复用机制 | 必须保留的独立语义 | 本次动作 |
|---|---|---|---|
| 时域 | coverage、缓冲区、generation、合并更新、最终 settle 的设计参考 | min/max 包络、自定义 X、多轴、raster/ink 策略 | 只作对照，不搬移或重写 |
| FFT 频谱 | 覆盖命中只平移、越界补数据、离散精确刷新、局部活动判定 | 每桶峰值折线、原始幅值 min/max、频率有限段与断点 | 本次主实施范围 |
| FRF | 本地交互活动、AA 延迟恢复、测量方法 | 幅值/相位/相干度、log Hz、低相干与 NaN 分段。相位不能按幅值最大点抽样 | 当前 `_on_interactive_range_changed` 不 setData；测量对照，不预先加缓存 |
| 时频/阶次主热图 | 合并事件、避免不必要重建 | 2D ImageItem、颜色范围、frame center/coverage、真实矩阵读数 | 保持图像平移；不套一维 envelope |
| 时频/阶次切片 | 依赖轴判定、相同索引复用、合并 setData/Y-fit | 切片方向、固定帧/频率索引、raw mask、主图同步 | 列为后续独立候选，先测量，当前不改代码 |

**禁止直接复制：** 时域 100 ms coarse 参数、min/max envelope、raw 点数阈值、全套 renderer/raster、多轴状态机。它们解决的成本与视觉问题不同。共享代码只有在至少两条实际路径需要相同输入/输出合同时再提取；当前仅新增频谱 owner 内必要状态与中立查询工具。

## 3. 固定合同

### 3.1 数据与正确性

1. 原始结果只读，不修改 FFT、采样率、NFFT、线性/dB 值、有效 mask、来源身份、统计或游标输入。
2. 继续使用 peak trace；不能以“更顺滑”为由退回全频段一次抽点、丢失窄窗细节、跨 NaN 造桥或使用 min/max 色带。
3. 自动 Y 始终从当前可见原始有效数据及边界交点计算，不能读取 peak trace 当作全部数据。深谷必须参与 Y 范围，即便它没成为某像素桶的最大点。
4. 有限非递减频率路径可二分查找；不能假设所有兼容输入都有序。NaN X/Y、重复 X、非单调 X、单点、空数据保留既有行为及测试。
5. 有限/单调/分段性质在新结果或显示数值版本接入时验证一次；热路径不得每次重验整条数组。禁止排序 X 而不同时保留其真实邻接语义。
6. 缓存用 owner 的结果/显示 revision，不用裸 `id(entry)` 作为唯一失效依据。结果替换、dB/Linear/reference/weighting 的显示数组变化、曲线增删都明确失效；结果相同但显示数值改变也不能命中旧 Y。

### 3.2 调度与自动 Y

- 用户平移/缩放即时改变 ViewBox，事件回调只提交最新目标、标记 dirty 和记录真实用户意图，不同步扫描全数组。
- 当前 16 ms 数据刷新周期作为第一版待测目标继续使用；同一周期曲线更新和自动 Y 查询合并一次，不能额外在鼠标回调内计算 Y。timeout 以 monotonic 再检查最小间隔，不能假定 Qt timer 精确到点。
- 缓存完全命中时不调用 setData；可见原始样本区间和边界交点未变时，自动 Y 也复用。全数据均在视口内是最重要的 O(1) 命中场景。
- 自动 Y 允许在受控显示刷新时更新，不引入 100 ms 全程冻结或插值动画。停止/释放、Home、应用参数、View 恢复、导出/截图前，必须精确刷新到最终范围。
- 停止后的最终数据 flush 与 AA 恢复分开：数据可在独立 0 ms 离散事务中完成，AA 的 150 ms quiet timer 保持原区间，不用 `start(0)` 改写它。
- 自动 Y 的程序 `setYRange` 不得被下一次鼠标事件误判为用户 Y 缩放：更新手动比较基线并受程序范围事务保护。纯 X 拖动后 `viewport_origin.y` 仍为 auto；真实 Y 拖动才暂停自动 Y。
- held drag 暂停指针不等于结束；wheel/惯性靠本地活动 quiet settle。foreign window 的鼠标按下不阻塞本 canvas 完成。

### 3.3 覆盖缓存与显示密度

- 缓存命中同时需要：相同 revision、缓存覆盖目标中的真实数据、显示密度足够、有效断点仍完整。只比较 xlim 相等过于严格，只比较 coverage 又不够。
- 先实现无 overscan 的索引内容复用：全数据一直可见、或选中的样本与两侧邻接线段没变时，平移不重新 setData。边界交点的数值即使索引不变仍可能变化，Y 查询 key 必须包含有效交点位置。
- 再给连续平移引入每侧半个可见跨度的缓冲候选（首轮参数，需 Cocoa 测量确认）。缓存不能跨大跨度缩放继续使用不足分辨率的旧抽点。
- 缓冲区抽点数应按当前横向像素密度扩展。例如缓存跨度是 viewport 的两倍，则给约两倍可见宽度的桶预算；不能把两个窗口的数据塞回原来一个窗口的桶数，重现“显示细节变稀”。实际数据端点处裁剪缓冲。
- 桶边界尽量与数据/稳定网格对齐，有限度复用；缓存边缘更新后应无可见峰值跳跃。最终 settle 按最终实际几何验证峰值和断点。
- 保存一个当前覆盖窗口，不引入无限多 viewport 的 LRU。metadata、mask 和有限段索引按每条曲线一份保存；记录内存增量，禁止每次事件复制整条数据。
- 画布变宽/缩放放大导致像素密度不足时重建；窗口缩小可在密度充足时复用。DPR/布局变化按实际绘图区宽度重新验证，不只看 QWidget 外宽。

## 4. 实施步骤与文件

所有路径相对 `/Users/donghang/Downloads/data analyzer`。新增类/函数写在指定 owner；不扩展 `ui/pg_canvases.py` facade，不增加 MainWindow 状态。

### T0 — 建立可比较的测量与失败用例

**文件：** 新建 `scripts/probe_spectrum_interaction.py`、`tests/ui/test_spectrum_interaction.py`；参考当前 `.state/fft-drag-analysis/`，不覆盖历史输出。

- [ ] 记录 HEAD、dirty scope 与相关文件 digest。当前无关改动位于 motion/channel_config_bar 及其测试，保留它们；若执行时状态变化重新记录。
- [ ] 探针拆为两种模式：无 profiler 的性能测量；单独启用 cProfile 的归因。两者不混用性能统计。
- [ ] 性能模式用 GUI 事件循环定时发真实 viewport press/move/release 和 wheel；记录预定/实际事件时间、callback 时间、paint 时间、最终 settle 时间和原始样本。保留直接 ViewBox 调用模式用于定位，但输出清楚标记。
- [ ] 每场景预热，再运行至少 5 轮、每轮至少 120 个事件；交错 FFT auto-Y/manual-Y 与时域顺序。用相同窗口尺寸、曲线数、数据、输入轨迹与事件节奏。测试 60 Hz 和 120 Hz 目标输入，不能用紧循环耗时倒推 FPS。
- [ ] 记录 Qt platform、Qt/pyqtgraph/NumPy 版本、DPR、实际 plot geometry、是否 profiler、数据参数、事件轨迹、curve setData/全数组扫描/峰值抽点/Y-fit 次数。计数与耗时统计排除准备、首显和最终 settle，另栏报告这些开销。
- [ ] 写确定性失败用例：全覆盖横移仍 setData；纯 X 拖动在回调中执行 raw Y 全扫描；多个 range 事件只应刷新最新目标；deferred auto-Y 不得变成用户 Y 意图。

**检查：** 新增测试应在旧实现显示明确失败原因；性能比较保存未修改版本结果到 `.state/spectrum-pan-performance/baseline/`。不跑全量基线。

### T1 — 结果级准备与快速窗口查询

**依赖：** T0。**文件：** `mf4_analyzer/signal/display_ranges.py`；新建 `tests/signal/test_display_range_index.py`；修改 `line_canvas.py` 的结果接入/清理与查询调用。

- [ ] 增加只读 `PreparedLineRange` 查询对象，统一拥有已校验的 X/Y/valid 引用、有限段索引、是否适用有序快路径、全有效幅值边界。由频谱结果接入创建，内部不持有 Qt 对象。
- [ ] 公开查询合同：`prepare_line_range(x, y, *, valid_mask=None)` 返回对象；`query(xlim)` 返回有效 source slice 描述、边界交点信息和精确幅值范围；输入维度、同形检查沿用 `visible_line_values`。不要求每次构造所有可见值副本。
- [ ] 单调有限快路径使用 searchsorted 查左右边界并保留相邻点；纯 X NaN 分段、Y invalid gap 与重复 X 不能跨段插值。非单调输入走现有精确通用路径，不静默排序或改变结果。
- [ ] 在已选择子区间上求 extrema；全覆盖时复用全有效边界。缓存 mask 与有限段信息，避免每次构造全量 `isfinite/flatnonzero/minimum/maximum` 数组。
- [ ] 索引相同且不含变化的边界交点时复用 Y；有交点时用当前 lo/hi 重算交点并与区间 extrema 合并，不误用旧插值值。
- [ ] 测试与现有 `visible_line_values + line_amplitude_limits` 逐场景对照，另加手算 crossing/NaN/深谷用例，避免仅证明两条错误实现相等。
- [ ] 原 helper 保留兼容；Batch 和切片暂不强制迁移新缓存。cold preparation 的时间和额外内存单独记录，不能用把耗时移到首显来宣称全面加速。

**Focused：** `tests/signal/test_display_range_index.py`、`tests/signal/test_display_ranges.py`；`tests/ui/test_pg_line_canvas.py` 中窗口边界、mask、NaN 和 auto-Y 用例。

### T2 — 曲线更新与自动 Y 合并为一次事务

**依赖：** T1。**文件：** `line_canvas.py`；`tests/ui/test_spectrum_interaction.py`、`tests/ui/test_pg_line_canvas.py`、`tests/ui/test_analysis_multiview_integration.py`。

- [ ] `_emit_viewport_intent` 保留即时意图通知，移除其中同步 raw Y-fit；只请求最新目标刷新。结果/视口/自动策略 revision 一起进入请求，下一次 tick 读取最新值。
- [ ] 现有 `_spectrum_refresh_timer` 合并曲线及 Y dirty；即使曲线缓存命中也检查 Y 是否需要更新，不得因 trace key 相同跳过新参考值或策略。
- [ ] 添加明确的 generation 和程序刷新 guard；timeout 过期、clear、切 View 或结果替换后旧请求不可写入新画布。timer 停止与 wrapper 销毁按现有 Qt 生命周期处理。
- [ ] 在当前新窗口完成查询→必要 setData→必要自动 Y→手动基线同步→最终质量调度，一次事务完成。程序 Y 变化不触发 viewport_action_committed；纯 X 用户拖动只提交 X。
- [ ] Home、restore、参数 Apply、鼠标释放以及截图/导出前走 `flush_pending_spectrum_display()`；该新增方法同步完成最新数据/Y 请求，不改变 150 ms AA quiet timer。
- [ ] 检查第一下 wheel/非左键操作的事件顺序：range 可能先于 manual-range 信号；所有请求入口都应受同一调度，不能仅靠某个回调稍后将 canvas 标 busy。
- [ ] 用可控时间测试最小刷新间隔与 latest-wins，不用实际 sleep 断言精确调用次数；timeout 早醒须再次检查间隔。

**Focused：** 新的调度测试；现有纯 X auto-Y、逐轴来源、程序刷新不提交意图、idle/local press/foreign press/clear 测试；`test_analysis_multiview_integration.py` 中相应真实入口。

### T3 — 内容与覆盖缓存，平移尽量只变换图形

**依赖：** T2。**文件：** `line_canvas.py`；按需在新建 `mf4_analyzer/ui/pg_canvas/spectrum_display.py` 放置频谱专用 cache 数据类及纯计划计算；不把时域 canvas 当父类或调用它的私有 renderer。

- [ ] 先实现索引内容命中：当所有数据仍在窗口中且显示密度足够，连续横移不重做 peak trace、不 setData、自动 Y 复用全局有效边界。
- [ ] 再实现 §3.3 缓冲覆盖与密度合同；`spectrum_display.py` 如创建，只接收 revision、数据索引描述、目标范围、像素宽度，返回复用/重建计划，不读 MainWindow/Inspector。
- [ ] 缓存越界请求受控重建并始终使用最新目标；用户放大时立即使不足密度的缓存失效。旧缓存不能一直拉伸到释放才补细节。
- [ ] 仍然调用 peak trace，有限 leg 保留边界端点与 NaN 隔断；每个 leg 分配与其可见跨度对应的预算，不把整张图的宽度预算重复给无数短段。
- [ ] resize/show/真实 plot rect 变化、曲线增删、dB/Linear/reference 变化、新结果、clear、Home、历史回退都验证失效。不要单凭 entry 对象 id 复用。
- [ ] 保留当前 AA ink/point gate 和 paint backstop；使用增加缓冲后的真实 drawn points 判定，不能虚报点数保持绿灯。如缓存令质量 gate 明显退化，先缩减缓存方案，不修改既有校准阈值。
- [ ] 若 T1–T3 后窄窗 raw extrema 查询仍是主要热点，再用测量决定是否增加分块 extrema 索引；本轮默认不实现多级金字塔或第二套信号数据库。

**Focused：** 新建 `tests/ui/test_spectrum_display_cache.py`；`test_spectrum_interaction.py`；当前 peak-trace、NaN、深谷、resize、Home、AA point/ink/backstop 用例。

### T4 — Cocoa 复测与其他画布对照

**依赖：** T3。**文件：** `scripts/probe_spectrum_interaction.py`；实施完成时新建 `docs/analyzer/verify/2026-09-12-spectrum-pan-performance.md`。

- [ ] 用 T0 同机同参数、无 profiler 的配置复测，至少覆盖下表全部频谱场景；同时保存计数与正确性数值、截图及结果文件。
- [ ] 大数据、窄窗、峰值跨边界、重复出入缓存的结果不能只看耗时；读取 raw/trace 点、Y limits、NaN breaks，确认正确性无回退。
- [ ] 真实 MainWindow 再验一次，因为旧探针裸画布没有 `analysis_range_adapter`、Pane 来源同步和状态提示；分别报告单 canvas 与完整产品路径。
- [ ] 时频/阶次开启/关闭切片做对照，记录 `_sync_slice_to_heatmap_view`、`_apply_slice`、setData 和 raw Y 查询时间；FRF 记录三曲线渲染及 log/ticks，不预设它和 FFT 同因。
- [ ] 仅当其他画布有独立明确热点时，另列后续任务：切片候选为“只响应影响当前方向的轴/索引变化，合并 setData/Y-fit”；FRF 候选取决于测量，不套 peak trace。当前不得借测量顺便修改它们。
- [ ] 记录相关代码指纹前后一致。若并行改动影响测量路径，本轮对比标为不可比较并只重做受影响场景。

## 5. 验收与性能目标

以下为本计划目标，不是已经测得的改进。

| 场景 | 正确性/结构门 | 性能评估 |
|---|---|---|
| 2×594001 点，宽窗持续包住所有数据，X 平移 | 准备完成后区间不变：0 次全数组重验、0 次 trace setData；Y 复用 | 相比 T0 同机无 profiler 基线，auto-Y 回调+paint P95 至少下降 30%；同时报告 median、最大值、>16.7 ms 比例 |
| 手动 Y 同场景 | 拖动不做 Y 查询，不因精确 xlim 变化重绘数据 | P95 不回退超过 10%；不能用 auto-Y 的进步掩盖手动路径退化 |
| 0..200 Hz 窄窗与缓存内平移 | 当前像素密度、窄峰、真实深谷与边界邻点正确；cache hit 不 setData | 报告 cache 命中率、重建次数、P95 和峰值越界帧，不设脱离实际几何的固定点数 |
| 连续越界、快速 wheel zoom、resize | 不显示旧结果、无跨 NaN 造桥；最终 flush 与精确查询一致 | 报告重建帧 P95 与停止到最终正确画面的延迟，至少不高于基线；缓存增长不得产生持续卡顿 |
| 新结果/Linear↔dB/reference/多曲线 | revision 失效正确，Y 来源仍 raw；cold preparation 只一次 | 首显时间、峰值内存单列，与前值比较；>20% 回退必须解决或缩减缓存设计，不直接宣称完成 |
| 按住停顿、松开、foreign mouse、clear/delete | 本地活动正确、最终更新一次、旧 timer 无写入、150 ms AA timer 不变 | 调度频率用确定性测试，Cocoa 定时抖动只作为实测 |
| MainWindow/双 Pane/历史/导出 | 自动 Y 不被错标手动、原统计和导出不变、每 Pane 正确 | 单独记录与裸画布差异 |

性能目标以相同源码依赖/机器环境的可比较场景为准；不保证所有设备达到 60/120 FPS。任一正确性门失败即不通过；热点降低但端到端 P95 未达目标时继续按测量定位，不以 helper 微基准替代验收。

## 6. 测试与交付门

新增测试名为本计划要求创建的文件；实施时先运行新增具体 node，失败→修复→通过分别记录，owner 完成时再汇总文件。

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/signal/test_display_range_index.py tests/signal/test_display_ranges.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_spectrum_interaction.py tests/ui/test_spectrum_display_cache.py tests/ui/test_pg_line_canvas.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -k 'viewport or auto_y or range_adapter' -q
```

`-k` 门执行前检查 collected/selected 清单，必须覆盖本次新增的真实入口节点，不能把 0 selected 当通过。稳定结果后只运行适用边界：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_signal_no_gui_import.py tests/test_batch_render_import_boundary.py tests/test_packaging_imports.py -q
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_batch_render_qt.py::test_fft_auto_y_uses_visible_original_values tests/ui/test_pg_heatmap_canvas.py::test_slice_db_mask_excludes_zero_but_preserves_real_deep_valley -q
git diff --check
```

- 若修改通用 envelope，则补跑其直接 owner 测试；未修改时域不跑整个时域套件，只选 raw-union/交互参考节点作必要对照。未修改 QSS/帮助文案，不触发无关 UI 门。
- 本轮不是发布或全局架构重构，默认无全量 suite。若新问题需要全量，先说明原因、检查已有 pytest 进程，协调者在稳定快照顺序运行 main（排除 acquisition_ui）与 acquisition_ui，禁止并行全门。
- 没有新增用户操作入口，原则上不需要帮助改动；若实施改变可见的自动暂停/恢复语义，则必须同步 `ui/hints.py`、`ui/quickref.py` 并重审此前范围合同，不能悄悄改变。
- 性能产物放 `.state/spectrum-pan-performance/`；verify 文档只记录真实命令、平台、通过/失败、限制和证据路径，不写预测通过数。Cocoa 不等同于 Windows frozen 或客户原文件验收。
- 交付前检查 lessons 状态；仅在复发模式获得回归或确定性测量证据后按项目流程记录，不为文档阶段创建臆测教训。

**本次文档验收：** 路径、符号、任务/场景覆盖与格式检查；不修改产品代码，不复跑历史 profiler 当作新性能结论。原正确性阶段与当前性能阶段分别记录，互不替代。
