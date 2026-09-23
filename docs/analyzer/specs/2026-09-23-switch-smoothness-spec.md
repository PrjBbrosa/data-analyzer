# Section / View 切换平顺性（switch smoothness）设计

> 状态：**D-A、D-C、D-D、D-E、D-F（F1/F2）、D-G、D-I 已在源码落地。D-B 与 D-F 的 F3 未做**
> （D-B 要等 Windows 真机标定）。实施计划见
> `docs/analyzer/plans/2026-09-23-switch-smoothness-plan.md`。问题与全部数字出自
> `docs/analyzer/reviews/2026-09-23-windows-switch-smoothness-analysis.md`（下称“报告”），
> 可用 `scripts/probe_switch_smoothness.py`（`--scenario view|section`）复跑。
>
> 编写基线：`ef63e1e6`（v8.3.2）。报告里的数字是 Linux offscreen 的 CPU 光栅代理，
> **不是** Windows 前台或 Cocoa 证据；本文的收益估计同样只是投影，验收以 plan 的
> 真机测量为准。
>
> 起因是用户观察：Windows 下“不管是功能模块，还是 View 切换，都是卡卡的感觉”，
> 以及“时域、FFT、阶次这些来回切都卡”。

## 0. 一句话

**切换本身不贵，贵的是切换期间在主线程上被重复触发的整图重绘和重复布局。** 本设计
不降低任何画质、不改 ink 阈值、不加固定延时，只做四件事：让 AA 帧在淡入结束后
**最多发生一次**；让没有质量规则的热力图切片曲线**纳入同一套规则**；让淡入握手在
几何稳定后再采样、失败时**有界重试并留痕**；让 UltraView 自动预览和热力图刻度
**不做没有变化的重复工作**。之后再用“保留揭示”和 Windows 标定去掉剩余的同步段。

## 1. 问题（摘要，详见报告 §2、§4）

| 编号 | 现象 | 根因（一句话） | 报告位置 |
|---|---|---|---|
| P-1 | 进入 FFT vs Time 最长阻塞约 430 ms | 热力图切片曲线每次重建都直接开 AA，一次进入约 5 次整图重绘都带 AA | S1、S6 |
| P-2 | 首次需要重画的 FFT 进入冻 1 s 后硬切 | 淡入握手在延迟自动缩放完成前采样几何，paint 后不一致即放弃，只能等 1000 ms 看门狗 | S2 |
| P-3 | 进入时域 / 切回允许 AA 的 View，淡入冻住约 225 ms，解冻后再冻约 220 ms | 离散 AA 结算的“下一轮事件循环”落在淡入里；解冻重绘又是 AA 帧 | W2、S3 |
| P-4 | 每次切换后多一次 5–730 ms 的截图 | UltraView revision 被“值没变的展示信号”递增，去重永不命中；自动预览强制 AA；UltraView 不可见时也截 | W1、S5 |
| P-5 | 进入阶次 / FFT vs Time 多 124–178 ms 刻度计算 | 热力图首次显示时 6 次同步对齐 + 1 次延迟对齐 + 十余次 resize，每次都从头枚举约 30 个候选步长 | S4 |
| P-6 | 进入阶次 / FFT vs Time 同步段约 90–135 ms | 每次进入都从缓存完整重画结果；只有 FFT 有“保留揭示” | S7 |
| P-7 | 允许 AA 的一帧可以贵到 220–730 ms 而不熔断 | 准入带和兜底按 Cocoa 标定，兜底 250 ms 本就放行这类帧；没有 Windows 标定 | W3 |
| P-8 | 时域入口和 View 切换的其余同步段 | 投影做两次、入口重新准备数据、点击后无先行反馈 | W4–W6 |
| P-9 | 偶发 15–65 ms 停顿 | 加载后大量长寿对象参与第 2 代 GC | W7 |

## 2. 目标与非目标

### 2.1 目标

1. **淡入期间不插入 AA 帧。** 任一 Section / View 的淡入期间，目标页不因质量升级做 AA 重绘；淡入结束或取消后，每个需要升级的画布**恰好**结算一次。
2. **一次切换最多一张 AA 帧。** 同一画布在一次切换里，AA 光栅最多付一次；解冻重绘、截图、离开页截图不再各自付一次。
3. **淡入握手不因可预期的布局落定而失败。** 延迟自动缩放、首次布局不导致 `target-paint-timeout`；真正失败时有日志说明是哪个几何分量变了。
4. **没有变化就不重复做。** UltraView 自动预览、热力图刻度、首次显示对齐只在输入真正变化时重做。
5. **进入热力图 Section 可以不重画。** 结果和展示输入都没变时，阶次 / FFT vs Time 与 FFT 一样直接揭示已有画面。
6. **成本判据按目标平台标定。** Windows 上的 AA 准入与离散切换预算有真机依据。

### 2.2 初始工程目标（待 plan Task 0 用 Windows 基线校准，不是承诺）

| 指标 | 目标 | 说明 |
|---|---|---|
| 切换期间主线程单次最长阻塞 | ≤ 100 ms（淡入期间 ≤ 33 ms） | 包括截图、质量结算；AA 帧若仍需要，落在淡入之后 |
| 淡入结束时间 | ≤ 动画时长 + 100 ms | 240 ms 动画 → ≤ 340 ms |
| `target-paint-timeout` | 0 次 | 12 个方向 × 3 圈，含首次进入 |
| 点击处理同步段 | 分析 Section ≤ 60 ms；时域 ≤ 40 ms | 保留揭示命中时 |
| 同一画布一次切换的 AA 帧数 | ≤ 1 | 由 paint 记录统计 |

### 2.3 非目标

- **不改 ink 阈值和 150 ms 交互静默窗。** `_INK_AA_ON/OFF`、`_SPECTRUM_INK_AA_ON/OFF`、`_FRF_INK_AA_ON/OFF`、`_BACKSTOP_*` 只在 D-B 的标定流程里、按 §5 改。
- **不永久关闭 AA，不用固定延时交付“就绪”。** 所有推迟都由事件（过渡结束/取消、几何落定、输入静默）触发。
- **不为每个 View 常驻一张画布或截图**（2026-09-15 计划约束；报告撤回了第一轮的“多画布翻页”建议）。
- **不把 AA 光栅搬到工作线程。** Qt 对象只在 GUI 线程创建和绘制；该方向只在本设计全部落地后 Windows 仍不达标时另立 spec。
- **不复用 FFT 的结果签名**作为其他 Section 的有效性判据。
- **不改变离开页同步截图合同（UV-A18）**，不改变显式复制/导出的 AA 质量。
- 不换 OpenGL 视口、不迁移 Qt6、不整体异步化。

## 3. 设计

七个设计项按依赖和收益排序。每项写明 owner、机制、必须保住的合同。

### 3.1 D-D · 淡入握手几何稳定（解决 P-2）

**Owner：** 各画布自己的握手实现：`ui/pg_canvas/line_canvas.py`、`heatmap_canvas.py`、`frf_canvas.py`、`canvas.py`（时域）。过渡控制器 `ui/chart_stack/page_transition.py` 只负责看门狗留痕。

**机制：**

1. **采样前先落定布局。** `request_presentation_paint_ack` 在记录几何快照前调用 `self._glw.scene().prepareForPaint()`。这是 pyqtgraph 在每次 paint 前本来就会做的一步（ViewBox 在这里完成延迟自动缩放和矩阵更新），提前做不会增加总工作量，只是让快照与 paint 看到同一份几何。
2. **判废后有界重申请。** paint 前后的几何比对不一致时，不再直接放弃：
   - 若可见性仍成立且 generation 未变，用新几何重新登记快照并请求一次 viewport update，计数 +1；
   - 重申请上限 `_PAINT_ACK_MAX_REARMS = 2`（**结构常量，不是标定值**：它限制的是“布局连锁落定”的轮数，不是时间）；
   - 超过上限才取消，并记录 `logger.warning`（经现有诊断节流），内容包含变化的几何分量（哪个 plot、`viewRange` 前后值、尺寸/DPR）。
3. **看门狗超时留痕。** `PageTransitionController._on_target_ack_watchdog_timeout` 在 `cancel("target-paint-timeout")` 前记录一次节流 warning，带 Section/View 身份。1000 ms 看门狗本身不变。

**为什么不是“去掉几何比对”：** 比对保证淡入揭示的是用户最终会看到的那一帧。本设计只让它在几何**真正稳定**后判定，而不是放宽判定。

**实现注记：** 四处握手实现形状相同。若逐行比对证明语义等价，可以抽到 `ui/pg_canvas/` 下的共享 helper；不等价的地方保留并注释差异（AGENTS.md：先证明语义等价再合并）。

### 3.2 D-C · 热力图切片曲线纳入质量规则（解决 P-1）

**Owner：** `ui/pg_canvas/slice_panel.py`（切片协作者）与 `heatmap_canvas.py`（宿主）。新增状态归切片协作者，在其 `_owned_names` 中声明；不扩大 `test_pg_canvas_backref_invariants.py` 的写穿白名单。

**机制（与 08-15 spec §3.4 的分析画布规则一致）：**

1. **重建时 AA 关。** `_reset_slice_quality_for_rebuild` 改为 `_slice_aa_on = False`，不再在重建调用里直接开 AA。
2. **离散结算。** 切片重建完成后走与线图相同的离散结算：独立的单次 0 ms 定时器，受 D-A 的过渡保持约束。交互期间的 `_slice_aa_idle_timer` 行为不变。
3. **ink 闸门。** 升级前用中立层的 `render_profile.envelope_ink_dev_px` 计算切片曲线的 ink（按切片 plot 的像素高和 DPR），超过准入带则不开 AA。准入带在标定前**借用** `_SPECTRUM_INK_AA_ON/OFF`（同为分析页的单条线图），并在 §5 标注为“借用、待标定”。
4. **实测兜底。** 复用 `quality_backstop.AaFrameLatch`：切片 AA 帧若超过兜底阈值，按签名拉黑，本签名后续不再升级；质量指示按现有口径显示“受限”。
5. **截图与离开页截图不强制切片 AA。** 自动预览和离开页截图使用屏幕当前的切片 AA 状态（见 D-E）。

**合同：** 用户停下交互后，便宜的切片仍然会变平滑；只有 ink 超带或实测超兜底的切片保持非 AA，而且这个状态是可观察的，不是静默降级。

### 3.3 D-E · UltraView 自动预览按需截图（解决 P-4）

**Owner：** `ui/main_window/ultraview_capture_coordinator.py`；截图口径在 `ui/pg_canvas/renderer.py:grab_pixmap` 与 `ui/chart_stack/stack.py:grab_presentation_pixmap`。

**机制：**

1. **revision 只在事实变化时递增（E1）。** `_on_idle_presentation_signal` 不再对每次信号都 `bump_presentation_revision`。每个 ref 记录一份“展示事实指纹”，由 `_PIXEL_AFFECTING_SIGNALS` 对应的事实组成（可见范围、markup revision、双光标信息、手动缩放状态）；新指纹与已记录的不同才递增。从缓存重画、恢复到同一范围时，指纹不变，revision 不变，去重命中。
   - 指纹只做比较，不持久化，不进 `presentation_digest`，与 revision 本身的会话语义一致。
   - 浮点范围按画布已有的范围比较口径判等，不自造容差。
2. **不可见且无消费者时只标记过期（E2）。** `request_capture` 在 UltraView 页不可见、且该 ref 没有需要即时预览的消费者时，只把 ref 记为 stale，不截图。消费者清单在 plan Task 0 盘点（至少包括：UltraView Board 可见缩略图、临时检视、项目保存需要的预览）。UltraView 显示时按可见缩略图顺序、经现有空闲调度逐个补截；项目保存路径在保存前补齐需要的预览。
3. **自动预览不强制 AA（E3）。** 自动预览截图使用屏幕当前的曲线 AA 状态，不经 `_curves_antialiased()` 强制打开。显式复制、导出、保存图片保持现在的强制 AA。
4. **保持：** UV-A18 离开页同步截图；digest/generation 校验；截图“不能永远 pending、不能抓半成品帧”（09-15 计划约束）。E2 的 stale 状态必须在 UltraView 显示或保存时被消费，不能无限期挂起。

### 3.4 D-A · 离散 AA 结算感知页面过渡（解决 P-3，并约束 D-C）

**Owner：** 过渡的持有方是 `ui/chart_stack/`（它知道目标页和画布）；结算的执行方是各画布的质量 owner（时域 `ui/pg_canvas/quality.py` 的 `QualityManager`，线图/FRF 的 `_arm_discrete_aa`，切片协作者）。画布不 import `chart_stack`。

**机制：**

1. **过渡持有“质量保持”。** `ChartStack` 在开始页面过渡时，对目标页的画布调用 `hold_discrete_quality(token)`；在 `transition_finished` 或 `transition_cancelled` 时调用 `release_discrete_quality(token)`。这与 UltraView 已有的 `_defer_capture_for_page_transition`（等过渡结束或取消再截）是同一种接线方式。
2. **保持期间只登记，不升级。** 离散结算（`settle_after_discrete_render` 的 0 ms 分支、线图的 `_arm_discrete_aa`、切片的离散结算）在保持期间只记录“有一次待结算”。memo 记为便宜（≤ `_SYNC_AA_MAX_MS`）的同步分支也一样推迟，避免淡入第 1 帧就是 AA 帧。
3. **释放时结算恰好一次。** 释放时若有待结算，启动**同一个**独立 0 ms `discrete_timer`，由它调用原有的 `try_enable_idle_quality` / `_enable_idle_quality`。所有闸门（ink、点数、兜底、输入忙）照旧在那里判定。
4. **解冻重绘不是 AA 帧。** 因为 AA 在保持期间没有打开，淡入结束解冻时的重绘是非 AA 帧；随后的一次升级是本次切换唯一的 AA 帧，并被现有 paint 计时兜底测量。
5. **没有过渡时行为不变。** 动效关闭、过渡被判定不适用、或画布不在目标页时，离散结算与今天完全相同。
6. **生命周期：** token 与过渡 generation 绑定；重定向（A→B→C）时旧 token 释放、新 token 持有，只有最终目标结算；画布销毁或 `clear()` 时清空保持状态。保持状态有唯一 owner，显式初始化，不依赖 `getattr(..., False)`。

**必须保住的合同：** `TestDiscreteSettle`（150 ms 定时器 `interval()` 不变、离散路径使用独立 0 ms 定时器）；`TestViewRestoreSettlement`（View 恢复结算恰好一次）；分析画布 `plot_spectra` / `set_result` 返回时曲线 AA 全关；paint 计时兜底仍安装在真画布上。

**与 08-15 spec 的关系：** 08-15 把“离散切换下一轮就升级”作为对“等 150 ms”的改进。本设计保留这个改进，只加一条：**有页面过渡时，“下一轮”指过渡结束后的下一轮。**

### 3.5 D-F · 热力图刻度记忆与首次显示对齐合并（解决 P-5）

**Owner：** `ui/pg_canvas/analysis_axes.py`（刻度计算）；`heatmap_canvas.py` / `_split_mixin.py`（显示时对齐）。

**机制：**

1. **F1 刻度记忆。** `_apply_target_bottom_ticks` 按每个轴对象记忆最近一次的输入键和输出。键包括 X `viewRange`、轴像素宽、DPR、目标刻度数、可见性、字体度量和格式化器身份；键相同直接复用上次的刻度，不再枚举候选。记忆挂在轴对象上，随轴销毁。
2. **F2 候选剪枝。** 生成刻度字符串前，先用“值个数 × 最小标签间距 > 轴宽”排除必然放不下的候选，不再为它们逐个调用 `tickStrings`。剪枝只能排除“结果必然被拒”的候选，输出与不剪枝时逐位相同。
3. **F3 首次显示对齐合并（在 F1、F2 之后按测量决定是否做）。** `showEvent` 中同步的 4 次 `_align_slice_to_main` 与 2 次 `reset_split_layout_alignment` 合并为一次最终几何上的对齐；保留一次 `_deferred_first_show_align`。合并必须发生在 D-D 的握手采样之前，保证淡入揭示的是对齐后的几何。

**合同：** 刻度结果（位置、文字、精度）与改前逐位一致，由参数扫描测试冻结；`test_tick_label_precision.py` 与 `tests/ui_kit/test_ticks_math.py` 不变。

### 3.6 D-G · 热力图 Section 的保留揭示（解决 P-6）

**Owner：** `ui/main_window/_analysis_mixin.py`（进入路径）、`_order_mixin.py`、`_fft_time_mixin.py`（渲染入口）。签名状态放在已有的具名 holder（`_state_holders.py`）或各 Section 的渲染 owner 中，不新增 `MainWindow` 多文件写入。

**机制：**

1. **显式的渲染输入。** 为阶次和 FFT vs Time 各定义一个不可变的渲染输入对象（结果身份与 generation、dB 参考与方式、色图与色阶、轴模式与范围、切片位置、单位与标签、画布尺寸与 DPR 等），`_render_order_on` / `_render_fft_time_on` **只从这个对象读取**展示参数。签名是它的哈希。
2. **完整性靠结构保证。** 因为渲染函数只读输入对象，签名天然覆盖所有影响像素的输入；另加一条测试：逐个改变输入对象的每个字段，断言签名改变并触发重画。
3. **进入时比较。** `_on_analysis_view_switched(render=True)` 在热力图 Section 上先比较签名；相同且画布仍持有该结果的画面时，走“保留揭示”（只做可见性、facts 与握手），不重画。不同则照旧重画并更新签名。
4. **失效：** 结果重算、View 切换到不同结果、画布 `clear()`、项目重开、画布销毁时签名清空。
5. **附带：** 阶次 Inspector 的 nfft 预览按（转速通道身份、参数）记忆 `revolutions_from_rpm` 结果；FFT vs Time 的 dB 参考提示只在输入变化时重算。两者的记忆都在各自 owner 内，随输入身份失效。

**合同：** 不复用 `_fft_last_render_sig`；View 身份用复合 source/channel 身份，不用显示名；保留揭示仍要经过 D-D 的握手和 D-A 的质量保持。

### 3.7 D-B · 离散切换的 AA 帧预算与 Windows 标定（解决 P-7）

**Owner：** 标定值所在的 `ui/pg_canvas/renderer.py` / `quality.py` 以及 08-08、08-15 spec 的 §5；本 spec 只定义流程和新常量的语义。

**机制：**

1. **Windows 复标定现有准入带。** 按 08-08 spec §7.4 用 `scripts/probe_aa_ink_budget.py` 与 `scripts/probe_view_switch_quality.py analysis-calibrate` 在 Windows 目标机上重测，结果回写相应 spec §5。若 Windows 与 Cocoa 系数差异显著，按平台选择常量，并在 spec 中记录平台判定方式。
2. **离散切换预算（新常量，待标定）。** `_DISCRETE_AA_FRAME_BUDGET_MS`：D-A 释放后的那次升级，若该签名的 memo 已记录 AA 帧超过预算，就不再在离散切换后自动升级，改为等下一次真实的交互静默（150 ms 定时器路径）再判断。质量指示显示“等待”，不是“关闭”。预算只影响**离散切换后何时升级**，不改变 AA 是否被允许（仍由 ink 闸门与兜底决定）。
3. **决策门：** 第 2 条改变的是用户可见的画质时机，需要在 Windows 基线出来后确认。若 D-A 落地后 Windows 上“淡入结束后的一次 AA 帧”已经可以接受，第 2 条不做。

### 3.8 D-H · 时域入口与 View 切换的剩余同步段（P-8）

本 spec 不重复设计，接续已有 owner：

- 通道树重复投影（W5）：2026-09-15 计划 T1。
- 时域入口重复准备数据（W6）：2026-09-15 审计 F4。
- 点击先行反馈（W4）：`2026-09-12-navigation-feedback-timing-followup.md` 与 09-15 计划 §2.2 的既有确认时序。

这些工作纳入本 spec 的统一验收矩阵（§6），方便在同一探针下看到叠加后的效果。

### 3.9 D-I · 加载完成后冻结长寿对象（P-9）

**Owner：** 文件加载完成点（`ui/main_window/` 的加载完成回调）与 `app.py` 启动完成点。

**机制：** 启动完成和每次文件加载完成后调用一次 `gc.freeze()`，把当时存活的对象移出分代回收；不改 GC 阈值。关闭文件后调用 `gc.unfreeze()` 再 `gc.freeze()`，避免已关闭文件的对象被永久冻结。需要在长会话里观察内存（plan Task 9）。

### 3.10 改后的一次切换（预期形状）

以“时域 → FFT vs Time”为例：

| 阶段 | 改前 | 改后（设计预期） |
|---|---|---|
| 同步段 | 约 148 ms：离开页截图、完整重画、6 次对齐、约 30 次刻度计算 | 保留揭示命中时约 40–60 ms；刻度复用 |
| 淡入 | 首帧后切片 AA 帧、延迟对齐重绘插入，最长阻塞约 430 ms | 只有非 AA 帧，最长阻塞 ≤ 33 ms（目标） |
| 淡入结束 | 解冻重绘带切片 AA（约 100 ms）；UltraView 截图约 104 ms | 解冻重绘非 AA；切片按 ink 判定后最多一次 AA 帧；UltraView 不可见时不截 |
| 下次离开 | 离开页截图再付一次切片 AA | 离开页截图用屏幕当前状态，不强制 AA |

## 4. 机械护栏（新增/更新）

| 护栏 | 位置 | 断言 |
|---|---|---|
| 握手在自动缩放落定后采样 | `tests/ui/test_presentation_paint_ack_lifecycle.py` | 首次 paint 会改变 `viewRange` 的线图，握手成功确认，不取消 |
| 握手有界重试 | 同上 | 连续两次几何变化后确认；第三次变化才取消，并有一条 warning |
| 看门狗留痕 | `tests/ui/test_page_transition.py` | `target-paint-timeout` 取消前记录一条带身份的 warning |
| 过渡中不升级 AA | `tests/ui/test_section_page_transition.py`、`test_page_transition_integration.py` | 过渡期间目标画布 AA 始终关；`transition_finished` 后恰好一次升级；取消、重定向同样恰好一次 |
| 离散结算合同不变 | `tests/ui/test_pg_timedomain_canvas.py::TestDiscreteSettle`、`::TestViewRestoreSettlement` | 现有断言不变并继续通过 |
| 切片重建 AA 关 | `tests/ui/test_slice_panel.py`、`test_pg_heatmap_canvas.py` | 重建返回时切片 AA 关；离散定时器已 armed |
| 切片 ink 闸门与兜底 | 同上（参照 `test_pg_line_canvas.py` 的谱行用例） | 高 ink 切片不升级；超兜底的签名被拉黑 |
| 切片状态归属 | `tests/ui/test_pg_canvas_backref_invariants.py` | 新状态在切片协作者 `_owned_names` 内；写穿白名单不扩大 |
| revision 只随事实变化 | `tests/ui/test_ultraview_capture.py`、`test_ultraview_capture_facts.py` | 同范围重画不递增 revision；真实缩放、markup、光标变化仍递增 |
| 不可见时不截图 | `tests/ui/test_ultraview_capture.py` | UltraView 不可见且无消费者：不 grab、ref 标记 stale；显示后补截；保存前补齐 |
| 自动预览不强制 AA | `tests/ui/test_ultraview_capture.py` + renderer 用例 | 自动预览 grab 期间 AA 状态等于屏幕状态；显式导出仍强制 AA |
| 刻度逐位一致 | `tests/ui/test_analysis_axes.py`（新增参数扫描） | 记忆 + 剪枝输出与原算法逐位相同；键变化时重算 |
| 热力图保留揭示签名完整 | `tests/ui/test_analysis_multiview_integration.py`（新增） | 改变渲染输入的任一字段都触发重画；全不变时不重画 |
| lambda 棘轮 | `tests/ui/test_no_lambda_signal_connections.py` | 新增的过渡/质量接线不用 lambda |
| 状态所有权 | `tests/ui/test_main_window_state_ownership.py` | 不新增多文件写入 |

## 5. 标定值（不是旋钮）

| 常量 | 状态 | 来源 / 标定方法 |
|---|---|---|
| `_INK_AA_ON / _INK_AA_OFF`（200k / 300k） | 不变；Windows 待复标定 | 08-08 spec §5；`scripts/probe_aa_ink_budget.py` 在 Windows 真机 |
| `_SPECTRUM_INK_AA_ON/OFF`（95k / 145k）、`_FRF_INK_AA_ON/OFF`（75k / 115k） | 不变；Windows 待复标定 | 08-15 spec §5；`scripts/probe_view_switch_quality.py analysis-calibrate` |
| 切片曲线准入带 | **新增，借用谱行 95k / 145k，待标定** | 扩展 `probe_view_switch_quality.py analysis-calibrate` 覆盖切片行，Cocoa 与 Windows 各测一次后回写本节 |
| 切片兜底阈值 | **新增，借用 `_BACKSTOP_FIRST_AA_MS` / `_BACKSTOP_STEADY_AA_MS`，待标定** | 同上 |
| `_DISCRETE_AA_FRAME_BUDGET_MS` | **新增，未定值；是否启用取决于 D-B 决策门** | Windows 基线中“淡入结束后一次 AA 帧”的实测分布 |
| `_PAINT_ACK_MAX_REARMS = 2` | 结构常量（限制布局连锁轮数，不是时间） | 由握手测试覆盖；改动需说明新的连锁来源 |
| 过渡看门狗 1000 ms、交互静默窗 150 ms、`_SYNC_AA_MAX_MS = 50` | 不变 | 各自既有 spec |

改任何“待标定”值：先改本节，再在对应真机上用上表的探针重测；offscreen 读数不能作为标定依据。

## 6. 验收

证据等级分开记录，不能互相替代：offscreen（确定性结构与代理成本）、Windows 源码前台、Windows Full/Lite frozen、macOS Cocoa。

1. **结构（offscreen，必须）：** §4 全部护栏通过；`scripts/probe_switch_smoothness.py --scenario section` 12 个方向 × 3 圈中，`target-paint-timeout` 为 0；淡入期间目标页 AA paint 为 0；每画布每次切换 AA 帧 ≤ 1。
2. **代理成本（offscreen，对照报告 §2.1）：** 进入 FFT vs Time、阶次、时域的最长阻塞与淡入结束时间不劣于报告 §6 的诊断投影；保留揭示命中时同步段达到 §2.2 目标。
3. **Windows 源码前台（必须，发版前）：** 同一探针 View 与 Section 场景，100% / 150% 缩放各一组；记录 CPU、电源模式、分辨率。§2.2 的目标在 Task 0 校准后按校准值判定。
4. **Windows frozen（必须，发版前）：** Full 与 Lite 各跑一次 Section 场景，确认与源码前台同量级。
5. **macOS Cocoa（必须，不退化）：** 08-15 spec §6 的探针重跑，不出现超出重复测量波动的退化；D-C 切片标定在此完成 Cocoa 一侧。
6. **画质：** 淡入结束后，允许 AA 的画布最终是 AA 状态；显式导出、复制仍是 AA；UltraView 缩略图与屏幕状态一致。

## 7. 风险与回退

| 风险 | 表现 | 缓解 / 回退 |
|---|---|---|
| D-A 保持未释放 | 某画布永远不升级 AA | token 绑定过渡 generation；finished、cancelled、画布销毁、`clear()` 都释放；测试覆盖重定向和取消；单独 revert D-A 提交即可回到今天的行为 |
| D-A 让“锯齿 → 平滑”晚出现约一个动画时长 | 用户在淡入结束后看到一次平滑切换 | 这是有意的取舍（淡入期间不卡）；若产品不接受，可仅对 ink 高于某值的画布启用保持，但需要新的标定和 spec 修订 |
| D-D 重试掩盖真实的几何抖动 | 淡入揭示的不是最终帧 | 重试有上限；超过上限仍取消并记录几何差异；看门狗不变 |
| D-E 指纹漏掉某个影响像素的事实 | UltraView 缩略图过期 | 指纹由 `_PIXEL_AFFECTING_SIGNALS` 的全部事实组成，测试逐项改变；digest 校验仍在 |
| D-E stale 预览在保存时缺失 | 项目预览为空或旧 | 保存路径补齐；Task 0 盘点所有消费者后再实施 |
| D-C 借用的准入带不适合切片 | 切片该平滑时不平滑，或 AA 帧仍贵 | 标定前质量指示可观察；Cocoa 与 Windows 标定后回写 §5 |
| D-F 记忆键漏项 | 刻度与范围不符 | 参数扫描逐位对比；键包含字体度量与 DPR；可单独 revert |
| D-G 签名不完整 | 进入时看到旧画面 | 渲染只读输入对象；逐字段测试；签名失效点覆盖重算、清空、重开 |
| D-I 冻结对象导致内存不回收 | 长会话内存上升 | 关闭文件时 unfreeze 再 freeze；长会话观察；可单独 revert |

每个设计项独立提交、独立可回退；D-A 与 D-C 共享“质量保持”接口，D-C 的非保持部分（重建 AA 关、闸门、兜底）可先于 D-A 落地。

## 8. 与既有文档的关系

- `specs/2026-08-08-timedomain-aa-ink-budget-spec.md`：ink 判据与准入带的来源。本 spec 不改其数值，D-B 执行其 §7.4 要求的 Windows 复标定。
- `specs/2026-08-15-view-switch-quality-settlement-spec.md`：离散结算与分析画布 AA 规则的来源。D-A 在其 §3.2 的离散结算上增加“过渡保持”；D-C 把其 §3.4 的规则扩展到热力图切片。
- `plans/2026-09-12-section-switch-performance-plan.md`：FFT 保留揭示与时域 Section 延后入口的来源。D-G 为热力图 Section 建立独立签名，不复用 FFT 签名。
- `plans/2026-09-15-interaction-smoothness-and-page-transition-plan.md`：页面过渡、截图准入与“不常驻每 View 画布”的约束来源。D-D 修补其自然 paint 握手的失败形状；D-H 接续其 T1。
- `reviews/2026-09-23-windows-switch-smoothness-analysis.md`：本 spec 的问题与数字来源。
