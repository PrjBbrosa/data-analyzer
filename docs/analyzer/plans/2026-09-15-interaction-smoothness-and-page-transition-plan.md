# TraceLab 操作流畅性与图面连续过渡优化 Plan

日期：2026-09-15。状态：**执行中；原计划内容保留为范围基线，M0 的用户视觉选择与抓图准入结论已回写。**

目标：让 **View 切换、分析页面切换、勾选通道** 更跟手，并让图面切换有连续过渡。**现有功能与数值行为是需要保护的基线；本计划是体验优化，不以功能缺陷修复或架构重写为前提。**

调查基线：HEAD `f28f5820591810636ca061c80b416dc9a78816a1`，v8.2.4。实施前重新确认当前源码；本计划不授权提交、推送或发布。

## 1. 方案概要

分开解决两件事，并分别验收：

1. **响应成本：** 减少同一次操作中重复的通道树、候选列表、事实信息更新。保留必要的状态恢复、校验和绘图职责。
2. **视觉连续性：** 点击后立即沿用已有导航反馈，旧图与就绪的新图做短暂淡化交接；试验很轻的位移，避免整页硬切。

顺序为 **冻结行为与测量 → 原型对比 → 局部去重 → 图面过渡接入 → 联合验收**。原型可以先看手感，生产启用必须通过响应和鲁棒性门。

主线程被同步工作占住时，Qt 动画同样无法前进。先启动动画、再执行原有重任务，不能保证丝滑；增加动效时长也不能代替性能优化。

### 1.1 本轮实施范围

| 范围 | 计划处理 | 完成边界 |
| --- | --- | --- |
| 时域 View、通道勾选 | 通道树差异更新、事务内合并过滤/布局 | 选择、隐藏、附件、主副 Pane 与绘图语义一致 |
| 分析 Section / View | 候选列表不变时避免重建；变化时批量更新 | FFT、时频、阶次、FRF 各自保留来源与参数合同 |
| 同次分析恢复 | effective facts 在最终状态上同步一次 | 保留独立调用与 `render=False` 的职责 |
| 图面连续过渡 | 先接时域与 FFT；同一呈现机制按门扩至其他分析页 | 不修改数据、曲线数值、坐标插值或计算时机 |
| 条件性昂贵绘制 | 重测原始/滤波叠加的绘制成本 | 为过渡准入提供证据；若需改画法，独立设计后处理 |

长生命周期数据缓存、FFT/I/O 全面异步化、全局缓存驱逐、GPU 后端替换放在 §8，不作为完成本轮的隐藏任务。UltraView、Batch、采集不推广页面动效，只验证共享边界未受影响。

### 1.2 依据与相邻工作

- [本次流畅性调查](../reviews/2026-09-15-interaction-smoothness-audit.md)：2,000 个候选、仅显示 2 条曲线时，时域 View 同步回调约 130–156 ms、FFT View 约 222–226 ms；通道树两次投影与候选重建占比较大。它们是少样本诊断，**不是 P95、FPS 或优化后验收**。报告中的优先级用于定位性能成本，本计划不据此扩大为功能修复。
- [此前 Section 性能计划](2026-09-12-section-switch-performance-plan.md)：当前已有 FFT retained reveal、时域 Section 延后入口和一次 facts 调用内 prepared 复用；实施时接续已有 owner，不重复建设。此前验收状态不能代替新基线。
- [选中背景滑动合同](../specs/2026-09-10-selection-slide-rollout-spec.md)：复用业务即时提交、程序恢复直接定位、打断与生命周期原则。其历史 400 ms 不作为当前值；当前 `ui_kit/motion.py` 为 `selection_navigation=320`、`selection_control=300`。
- [View 质量结算合同](../specs/2026-08-15-view-switch-quality-settlement-spec.md)：继续保留最终几何一次结算与 150 ms 交互 quiet window。

下文源码、测试路径相对仓库根目录；简写 `ui/` 为 `mf4_analyzer/ui/`，`ui_kit/` 为 `mf4_analyzer/ui_kit/`。拟新增文件和接口均明确标注，不能当作已有能力。

## 2. 图面过渡方向

### 2.1 推荐视觉

**推荐候选：淡化交接 + 很轻的位移。** 导航栏、View 标签、Inspector 和侧栏保持原位；过渡只覆盖中间图面呈现区域，包括与图绑定的标题、轴、图例及浮动游标读数，边界以真实 Qt 几何裁剪。

| 候选 | 看到的效果 | 取舍 |
| --- | --- | --- |
| A：仅淡化交接 | 旧图逐渐退去，新图逐渐清晰 | 最安静，读图干扰较小；作为基准方案 |
| B：淡化 + 轻移，**已选** | 新图轻轻进入，旧图同步退去 | 保留 B 的呈现/打断策略；本次已选值为 **300 ms、0 个逻辑像素**，因此当前画面不发生实际位移 |
| C：整页横向推移 | 整张页面移出、另一张移入 | 移动距离大，坐标与分屏更容易干扰阅读；本轮不实施 |

M0 原型最初比较 A/B 与当前直接切换，B 的原始候选为 **200 ms、8 个逻辑像素**；该值保留为历史比较条件，不是当前选择。用户已确认 B，参数为 **300 ms、0 个逻辑像素**：B 仍是局部图面交接、generation 打断和可选轻移的呈现策略，但本次不产生横向或纵向位移。日后若要恢复非零位移，必须重新进行原型比较和原生准入，不能从历史候选自动回填。

这项选择是用户确认的视觉目标，仍不是已准入的生产参数。原型默认的“模拟内容就绪：等待 100 ms”只用于比较等待期手感，**不是**生产就绪机制，也不能变成固定 sleep。生产仍须由当前恢复事务与自然 paint 确认目标正确渲染后才可开始交接。沿用 `selection_easing()` 的运动节奏，给图面独立 token，拟名 `page_transition`；不改现有 320/300 ms 导航/参数时长，也不改轻量 demo 的 `page_enter=140`。

### 2.2 一次切换的可见过程

| 阶段 | 视觉与操作规则 |
| --- | --- |
| 接收输入 | 原导航状态与滑动反馈按既有确认时序启动；不等待图面动画结束 |
| 目标恢复中 | 有合格旧图时短暂保留，并明确呈现“正在切换”的瞬态反馈；不把旧图当作新目标的可读、可操作数据 |
| 目标内容就绪 | 原始数据/结果、来源、最终范围与布局已正确，开始 A/B 过渡；不先清空成白页再淡入 |
| 交接结束 | 撤去呈现层，显示原有真实画布；位置、清晰度、颜色、光标与命中区域精确一致 |
| 目标为空、缺源或未计算 | 交接到现有合法空态/预览/提示；不制造结果，不自动计算 |

不为凑齐时长人为等待数据，也不等待导航滑块先走完才开始图面过渡。恢复本身耗时较长时，保留现有真实进度语义；本轮不假装能让所有同步计算持续动画。

**勾选通道不播放整图淡化。** 复选框立即确认，沿用现有增量绘图；优先让已有曲线、坐标和图面不发生无意义重建。通道新增行的独立出现动效暂不进入范围，避免连续勾选造成反复闪动或改变布局行为。

### 2.3 呈现实现方向与成本约束

拟新增 `ui/chart_stack/page_transition.py:PageTransitionController`，由 `ChartStack` 持有，管理临时图像、插值和清理；复用 `MotionPolicy`、`ValueDriver`。业务 owner 仍是原 View manager / analysis coordinator，呈现 owner 不读取或修改项目数据。

- 初始候选是**两张临时图像在单一局部覆盖层内合成**。实测发现到达端点的 `QWidget.grab()` 在交替时会触发约 490 ms 的补绘，故已改为只保留离开图像、在目标的自然 paint 确认后将其透明淡出到真实目标；视觉仍为 B 的纯淡化，且不逐帧调用 `plot_*`、`setData`、全窗 layout、QSS 或 `processEvents()`。
- 每次有效切换最多捕获一次离开图面、一次到达图面；瞬态合成不能依赖每帧 `QWidget.grab()`。不为每个 View 常驻一套画布或截图。
- 不直接给整个实时图表挂 `QGraphicsOpacityEffect`。需用真实 paint 计数证明覆盖层不会把下层昂贵曲线每帧重画；否则该原型不能生产启用。
- 图像捕获也会重绘。离开捕获、目标捕获（若使用）、合成、撤层后的 paint 必须分开测；调用截图 API 不等于免费读取已有屏幕像素。若目标捕获不准入，可用自然 paint 下的真实目标作为淡化底图，但不得把这降格为固定等待。
- M0 的 exposed Cocoa 探针中，`ChartStack.grab_presentation_pixmap()` 单次抓图耗时 **480.7377 ms**，并触发一次 `GraphicsLayoutWidget` paint。它是导出/UltraView 的完整结算路径，不准入 M1 的离开或到达端点抓取，更不能用于动画帧。M1 必须新增单独、局部且职责受限的 capture seam，再分别测量其离开/到达成本。
- 目标内容就绪必须由当前恢复事务与实际渲染证据、尤其自然 paint 确认，不能用 `singleShot(0)`、原型的 100 ms 选项或其他固定等待代替。遮盖层可能阻止底层自然 paint：原型必须证明目标能完成一次正确渲染，不出现“等首帧才撤层、被遮挡又不能首帧”的循环。需要显式局部渲染时只能在 GUI 线程完成，并计入性能预算。
- 不插值 X/Y 数据、轴值、热图色阶或 dB/单位，不显示假中间计算结果。临时图像只属于过渡，不能成为游标取数或持久结果。
- 图像按真实 DPR 捕获；以实际像素缓冲字节记账。1600×950、DPR 2 的两张 RGBA 图像约 46.4 MiB，尚不含抓图/合成临时副本。原型初始峰值预算为 **64 MiB**，包含这些副本；若无法满足，先缩小覆盖范围或直接终态，不降低正式图面分辨率。
- 每个图面宿主仅一组活动过渡，完成/取消立即释放像素引用。扩大预算前重新测量；全屏、高 DPI、双 Pane 必须单列，不能仅测小窗口。

### 2.4 打断、输入与捕获合同

以下是拟新增呈现合同；实现前在原型中确定具体接线，不增加散落在多个 MainWindow mixin 中的状态旗标。

| 事件 | 必须行为 |
| --- | --- |
| 相同目标重复点击 | 保持原业务信号合同，不重新播放 |
| 快速 A→B→C 或反向 | 不排队播放 B；由已有业务 owner 确认合法目标，过期的呈现 generation 失效 |
| 过渡中重定向 | 从当前可见的图像混合状态继续交接，不跳回 A 的原图；合成使用已有图像，最多保留一对端点，不能无限累积纹理或目标队列 |
| 新目标暂未就绪 | 当前混合图仅作过渡背景，清晰标识 pending；恢复完成由原事务负责，动画不能冻结或推迟业务提交 |
| 图面输入 | 目标已就绪时先结束过渡，再按目标真实画布处理原事件一次；禁止向位移中的旧图取点。未就绪时只限制被覆盖图面，导航、取消、关窗仍按原逻辑可用；不缓存并重放过期点击 |
| View 删除/重排、源关闭、项目替换 | identity / generation 不匹配即取消；不得按旧数组索引提交或恢复旧图 |
| resize、DPR/屏幕变化、窗口隐藏/失活 | 停止并清理过渡，交由现有恢复路径显示当前合法目标；再次显示不补播 |
| 程序恢复、项目打开、Off/Reduced | 直接使用原有恢复路径完成终态，不动画，不改变信号/dirty/pin/job 行为 |
| 异常或抓图失败 | 释放临时资源并回到真实画布/原有错误提示；预期降级有节流诊断，程序错误不静默吞掉 |
| 动画 finished | 只撤层/释放资源；不能在这里切 View、恢复范围、提交计算或保存状态 |

呈现 token 至少区分 Section、稳定 `view_id`、Pane 组合/宿主生命周期、本次恢复 generation、最终几何与 DPR。业务 state 不保存 token、bitmap 或动画进度。对象连接 `destroyed` 清理并在延后回调中检查 `sip.isdeleted()`。

**复制、导出、UltraView 与保存：** 原截图/导出 owner 只读取当前真实目标，不包含覆盖层和混合图。用户显式复制/导出时提前撤去过渡，并走既有 flush/稳定性合同；目标未就绪时沿用原等待/失败路径，不导出旧图。UltraView 自动捕获继续由现有 coordinator 的 ref、digest 和稳定性决定；必要离开捕获不能被新目标覆盖。分别定义“目标内容就绪”和“动效结束”，避免 capture 与过渡互相等待。仅停止动效不等于取消保存或计算。

## 3. 必须保持的现有行为

| 合同 | 不变内容与对照方式 |
| --- | --- |
| 数值 | 同输入的数组、dtype、长度、NaN/Inf 位置、时间对齐、峰谷、Fs/NFFT、滤波、计权、单位、dB reference 相同；本轮不改数值算法 |
| 身份 | 保留 `(fid, channel)` 与 `_ChannelKeyDict`；同名异源不能合并，失效数据不能因缓存命中继续显示 |
| 恢复 | 先捕获离开 View，再应用目标附件、参数、来源、范围；共享 Inspector/导航树跟随正确 Pane，不能跳过整段恢复 |
| 坐标/交互 | X/Y 限、auto/manual、`viewport_origin`、Custom-X、轴组、联动、游标、标注、图卡历史与重建回调保持 |
| 绘制质量 | time View 保持 X `flush=False` → Y → `settle_view_restore()` 一次结算；150 ms quiet timer 与独立 0 ms settle timer 不混用；不改已标定 ink/AA/raster 门限 |
| 分析结果 | 普通切换不自动计算；结果未算、缓存 miss、stale 与预览仍准确。项目重开合法重算队列保留 |
| 状态/生命周期 | dirty、保存/撤销意图、信号次数、风险提示、异常 finally、任务 generation、cache pins、关闭取消路径一致 |
| 截图/持久化 | UltraView/复制/导出对应正确目标；项目和预设不包含运行期优化状态 |

相同已接受业务输入序列的最终语义须与原路径相等；允许的新增差异仅为过渡像素、时间线及 §2.4 明确列出的短暂图面输入保护。另测 pending 期间哪些事件被阻止、ready 后原事件只执行一次，不能借“终态相同”遗漏输入测试。现有失败单独报告，不能修改预期值把它包装成本轮优化通过。

## 4. 执行任务与门

下列任务按原定顺序小步集成，每项可以独立撤回；各任务当前状态以其内的补记和对应证据为准。同一 owner 的在途修改先整合到稳定快照再测量。

### T0 — 冻结行为、补可比较基线

**Owner：** 探针与 focused tests；原始证据存 `.state/smoothness-transition/`。复用 `scripts/probe_interaction_motion.py`、已有 `.state/smoothness-audit-20260915/` 诊断，不复制历史读数为新基线。

- [ ] 记录 HEAD、dirty 范围、相关源码/探针内容指纹、依赖版本、Qt platform、窗口/图面尺寸、DPR 与负载。隔离 QSettings、最近文件、缓存和输出；正常 teardown 才算有效运行。
- [ ] 用真实 QTest 鼠标/键盘路径覆盖 View、Section、勾选；改进此前分析 View 直接调用槽的诊断。分别观测输入回调、首次反馈 paint、目标 ready、动效/最终质量稳定、最大单次 paint、heartbeat lag。
- [ ] 冻结 §3 行为快照与必要回归：同名异源、主副 Pane、不同范围/参数、隐藏/记录通道、Custom-X、搜索/展开状态、未算/缺源、连点、关窗、项目重开。
- [ ] 只为本轮新边界补确定性测试；已有正确行为先通过，新去重要求可先失败。性能计数必须同时有终态断言，不能只断言“少调一次函数”。
- [ ] 把滤波叠加的长 paint 单列重测，分别改变线型、窗口几何、原始/滤波显示组合；保留真实原始/滤波区分度，定位捕获旧图是否也昂贵。该组不拿来概括普通切换。

**门：** 对应现有 `test_view_switch_reentrancy.py`、`test_view_switch_integration.py`、`test_section_entry_presentation.py`、`test_analysis_source_scope.py`、`test_split_routing.py` 的受影响节点；以及 §5 矩阵基线。没有 baseline 的分区不得先声称优化收益。**不跑通用全套基线。**

### M0 — 先验证 A/B 手感和原生合成成本（**部分完成**）

**Owner：** 独立原型与探针，先不接生产窗口。拟交付 `docs/analyzer/ui-prototypes/2026-09-15-chart-page-transition.html`，用于比较 A/B；原生探针放 `.state/smoothness-transition/`，使用真实 chart cards/生产 QSS。

- [x] 用相同图面素材展示直接切换、纯淡化、淡化轻移，包含连点反向、慢就绪、空态与双 Pane。用户已选 B，当前原型默认 **300 ms / 0 px**，并将“模拟内容就绪”默认设为 **等待 100 ms**；立即与 600 ms 保留供比较。
- [x] 已对现有单时域图面的导出抓图路径执行 exposed Cocoa 窄探针：一次 `grab_presentation_pixmap()` 为 480.7377 ms，含一次下层 `GraphicsLayoutWidget` paint。该结果只是否定现有路径的 M1 准入，不构成局部覆盖层、首帧/撤层像素、圆角、双 Pane、P95 或内存验收。
- [x] 已写出可执行的动效准入表，见 `.state/smoothness-transition/m0/admission.md`。现有 helper 已标为不准入；数据、布局或质量状态改变后旧成本证据不自动沿用；没有对应证据则直接终态。
- [x] 已对照用户选择更新本文候选状态。HTML 仅用于选择效果和等待期手感；100 ms 不携带生产 ready 语义，Cocoa 与自然 paint 确认才决定实现是否可接入。
- [ ] 尚未有局部覆盖层或新的窄 capture seam；因此抓图次数、下层 paint、首帧/撤层像素、曲线清晰度、圆角裁剪、DPR、峰值像素内存与清理仍未完成原生验证。若双图合成每帧带出底层重画、首帧等待成环或内存超预算，允许退为 A，不以延长动画掩盖停顿。

**门：** 用户视觉选择已完成；§2 视觉/打断合同与 §5 动效成本的生产准入尚未完成。现有抓图 helper 的 480.7377 ms 是负向 Cocoa 证据，M1 不得复用它；必须先建立新的局部 capture seam 与自然 paint ready 确认。无需为开始做原型额外请求通用权限。

### T1 — 通道树投影减少重复工作

**Owner：** `ui/widgets/channel_tree.py`；`ui/view_bridge.py` 与 `ui/main_window/_view_mixin.py` 仅做事务接线。色块需要复用时由 `ui/widgets/_swatches.py` 负责有界 GUI 资源。

- [ ] 为附件、checked、hidden、颜色的真实变化建立差异更新；不变颜色不重建 QIcon，不变项不 `setCheckState/setHidden/setIcon`。首批允许 O(N) 的轻量比较，先消除昂贵 Qt 写入，不重写 QTreeWidget 为新 model。
- [ ] 在树 owner 内增加可嵌套的批量投影作用域：保留 setter 的即时默认合同，同一投影末尾一次过滤/可见性/布局结算；异常退出与嵌套 guard 恢复正确。
- [ ] no-op 依据须包含树内容/附件/搜索/checked-only/记录节点及相关上下文；不能只比较最后一次入参。文件加载、重命名、配置应用、删除和树重建后必须重新投影。
- [ ] 保留 `checked` 对 hidden 的清理、未勾选→勾选默认可见、父级勾选、搜索展开恢复、选择/滚动、记录节点排除等现有语义。
- [ ] 先用树 setter 幂等性压低两次投影成本；仅在实证主 Pane 前后目标完全相同后，省略第二次相同投影。副 Pane 渲染后的共享控件恢复仍执行；不能直接删除 finally。
- [ ] 连续勾选每次业务变更准确生效；本阶段不新增输入去抖，不丢中间选择操作，也不延迟 dirty 或风险确认。

**Focused：** `tests/ui/test_channel_widget_setters.py`、`test_channel_filter_context.py`、`test_recolor_navigator_swatch_sync.py`、`test_view_bridge.py`、`test_view_switch_reentrancy.py`、`test_split_routing.py`。新增节点覆盖嵌套/异常、相同投影无冗余 Qt 写入、树重建失效、主副栏最后目标正确。

**通过标准：** 状态/信号对照一致，500/2,000 候选组明显减少投影与布局成本。若去重必须引入无法证明的长期状态缓存，保留该处旧路径。

### T2 — 分析候选列表按内容更新、批量结算

**Owner：** `ui_kit/widgets/searchable_combo.py`；四个 `ui/inspector_sections/contextual_{fft,fft_time,order,frf}.py`；`window.py:_refresh_analysis_candidates` 保留原编排职责。

- [ ] 先比较完整有序候选描述，包括复合 identity、显示文本、tooltip/角色内容；相同集合不 clear/add，不以“附件没变”推断目录没变。首批直接比较元数据序列，不要求先建设全项目 revision 系统。
- [ ] 候选相同仍应用目标 View 的当前来源，包括 -1 未选择；候选模型复用不等于控件恢复可以省略。
- [ ] 必须重建时提供可嵌套批量入口，保留现有 `clear` 的 proxy detach → model mutation → rebind 顺序；popup/delegate/geometry 在批次末一次同步，不逐项重复。
- [ ] 保留普通 `addItem/addItems/clear` 的公开行为与外部调用者；不得吞 model 错误或阻断模型必须发出的结构信号来换速度。
- [ ] 保留 FRF 两个来源、Order 信号/RPM 候选差异；重命名/顺序改变/缺源后正确更新，原选中 identity 存在则保留，未选择不自动跳第一项，程序应用不误触发计算。

**Focused：** `tests/ui/test_searchable_combo.py`、`test_analysis_source_scope.py`、`test_analysis_multiview_integration.py` 中候选/来源/恢复节点。新增批量入口及四分区 round-trip 节点；Cocoa 反复打开补全 popup，确认无 model 一致性警告、选中错位和失效 wrapper。

### T3 — 同次分析恢复只整理一次最终 facts

**Owner：** `ui/main_window/_analysis_mixin.py`，必要时 `_fft_mixin.py`；不修改 `analysis_time_axis.py` 或数值算法。

- [ ] 列出 `_render_analysis_view_from_cache` 的全部入口、早返回与恢复分支。指定每条路径的 facts 同步 owner；普通 render、`render=False`、独立 cache restore、无结果与项目 restore 均有明确职责。
- [ ] 仅合并同次恢复中相同最终上下文的重复同步；原有需要同步的独立调用保留默认行为。不得简单删除函数末尾同步造成其他入口缺更新。
- [ ] prepared 仅限当前同步事务内借用，禁止跨事件循环复用 mutable Navigator/Inspector 数据；现有单次 `_sync_fft_effective_facts` 内复用保留，不重复实施旧计划。
- [ ] 对比来源分组、blocked/short/non-finite、Fs provenance、Auto/Manual NFFT、range、单位与错误提示；记录 prepare 次数和数组字节，不改变 cache key、pin 或 compute 提交次数。

**Focused：** `tests/ui/test_analysis_multiview_integration.py` 的 facts/weighting/round-trip 节点、`test_analysis_source_scope.py`，以及 `tests/signal/test_fft_effective_facts.py`、`tests/test_analysis_time_axis.py`。新增 render=False、独立 restore、缺源分支断言；不扩至全 signal suite。

### M1 — 接入时域和 FFT 图面过渡

**前置：** M0 视觉选择完成，T1–T3 对相应路径通过；现有 export/UltraView helper 已因 480.7377 ms 单次 Cocoa 抓图不准入，必须先建立新的局部 capture seam，并由恢复事务与自然 paint 确认目标 ready。若已有机器/场景不能承担该新 seam 的成本，保留直接呈现并明确记录未覆盖范围。

**Owner：** 拟新增 `ui/chart_stack/page_transition.py`，`ui/chart_stack/stack.py` 持有；`window.py`、`_view_mixin.py`、`_analysis_mixin.py` 仅对接已确认目标与事务完成事件。需要新增画布 ready 通知时扩展既有 quality/presentation owner，保持 backref 声明。

**执行补记（时域 Light 已启用；FFT 未准入）：** 已增加
`PageTransitionController`、300 ms `page_transition` token、取消/释放与快速重定向契约，以及时域与 FFT 的自然-paint ready fence。生产启动只把 `time` 加入准入集合；单 Pane 时域 View 的标签、快捷键等既有 `_switch_view` 入口在原业务事务提交后接入。FFT 接线保留但仍走直接恢复，直到有独立的 Cocoa 端点和自然 paint 证据。

在 exposed Cocoa、1200×760、DPR 2、2 条 × 10,000 点合成时域数据上，5 次预热后 30 次真实生产入口切换均完成、无取消；离开端点局部抓取 P50 **2.66 ms**、P95 **6.35 ms**、最大 **6.45 ms**，仅保留一张 **6,606,720 B** 图像。尝试到达端点抓取时交替样本出现约 **490 ms** 补绘，故不准入；现在由自然 paint 回执启动“离开帧淡出至实时目标”，不使用原型的 100 ms 或任何 ready 定时器。原始记录在 `.state/smoothness-transition/m1/native-local-transition-capture.json`。

- [~] 已为状态机、取消、快速重定向、Off 和自然 paint 栅栏写确定性测试；20 次反向、全部业务信号计数的矩阵仍留 T4。
- [~] 已接单 Pane 时域的真实 View 标签/快捷键入口；项目/预设恢复、Toolbar 分区切换与 FFT View 保持直接终态。
- [~] 已覆盖相同宿主重建另一时域 View，并在改写前取得合格离开图像；已有画布显隐、双 Pane 不在本次启用范围。
- [~] 时域 ready 由恢复事务后的自然 paint 确认；FFT fence 已有但 cache miss、retained reveal 和双 Pane 未取得准入证据。
- [ ] 交接期间目标数据若被新结果/参数/来源更新替换，先使旧呈现失效并走正式画布路径；不让过期截图在撤层时闪回。
- [x] 默认通用 helper 仍关闭；仅已验收的时域调用点显式启用 Light。本轮不新增全局偏好/QSettings/OS 动效监听；不宣称自动跟随系统设置。
- [~] 复制/导出会取消瞬态并取终态；UltraView 自动离场预览复用离开帧，目标预览延至 handoff 结束。`ui/hints.py`、`ui/quickref.py` 已说明时域单图切换；保存、真实客户文件和全部截图矩阵留 T4。

**Focused：** 拟新增 `tests/ui/test_page_transition.py`、`test_page_transition_integration.py`；复用 `tests/ui_kit/test_motion.py`、`tests/ui/test_view_switch_reentrancy.py`、`test_section_entry_presentation.py`、`test_ultraview_capture.py`、`test_project_dirty_guard.py` 对应节点。

**硬门：** Off/Light 终态数据与语义相同；无空白泄漏、旧图取点、抓混合图、重复业务提交、永久 pending；静止后无自发动画更新。真实 Cocoa 通过 §5 后才算该路径完成。

### M2 — 以同一合同扩至时频、阶次、FRF

**Owner：** 同一过渡 controller；各 analysis page/画布仅提供必要呈现事实，不扩建第二套过渡状态机。

- [ ] 各分区先测 empty/cached/双 Pane/切片开关/异步结果到达；验证热图色阶、FRF 相位、源身份和几何均来自原路径。
- [ ] 逐分区应用 §2–§3 合同，不复用 FFT 的结果签名冒充通用有效性；不顺手改热图 dB 缓存或 FRF 绘图算法。
- [ ] 单/双 Pane 数量或布局变化时，覆盖区域使用统一宿主最终几何；暂时不做 Pane 自身尺寸动画。
- [ ] 某分区不能满足抓图/帧时间/内存门时保留原展示、记录 `partial` 与 measured owner，不为统一动效强制启用。

**Focused：** 新增 integration 文件的分区参数化节点，结合 `test_frf_canvas.py`、`test_analysis_multiview_integration.py`、`test_ultraview_capture_facts.py` 对应路径。热图相关测试按实际触及 owner 选择；只有 presentation 接线时不运行所有分析算法测试。

### T4 — 联合验收与交付

- [ ] 在稳定快照上比较：原基线 → T1–T3 动效关闭 → T1–T3 动效启用，分别报告每段收益/新增成本；不相加独立阶段百分比。
- [ ] §5 场景、§3 终态与 §2.4 中断/输入/截图矩阵都有证据；宽窄窗口、生产字体/QSS、真实用户数据和平台分开结论。
- [ ] 交付代码/聚焦测试及拟新增 `docs/analyzer/verify/2026-09-15-interaction-smoothness-and-page-transition.md`；原始 JSON/图片/录屏留 `.state/`。报告每个分区是否启用、效果参数、未达标场景和原因。
- [ ] 检查 lessons 状态，完成适用边界和 `git diff --check`。不把用户视觉确认、offscreen 测试、Cocoa 性能和 Windows 验收混成一个“通过”。

## 5. 性能验收与场景

### 5.1 测量口径

同机、相同数据/参数/范围/pen/窗口/DPR，稳定源码快照；每组 5 次预热、至少 30 次样本，记录 P50/P95/max。冷路径另起进程分组。性能组关闭 cProfile 和全方法 wrapper；归因与录屏单独运行。无显示合成器时间戳时只报告 Qt paint/事件时序，不声称实际显示器 FPS。

四个时点独立记录：**首次可见反馈、目标数据/几何 ready、首次目标内容参与显示、完全交接且质量稳定**。ready 在覆盖层后完成不等于用户已经看清新图；完整交接时间必须包含动画时长，不能藏到统计外。稳定条件由实际 pending、paint、identity/geometry 验证，不能用固定等待代替。

### 5.2 待验证目标

以下为工程目标，不是现有保证；T0 记录可复现基线后执行。功能门优先，性能未达标写 `partial`，不擅自扩展高风险方案。

| 指标 | 目标 |
| --- | --- |
| 常用 warm 操作首个反馈 paint | P95 ≤ 50 ms；同时报告主线程最大停顿 |
| 500/2,000 候选组 | T1–T3 动效关闭时，目标 ready P95 较原基线下降 ≥30%；分别报告 View、Section、勾选 |
| 普通小数据 warm 场景 | 目标 ready P95 争取 ≤100 ms；不得为达数值跳过状态恢复 |
| 未命中热点的路径 | ready/最终质量 P95 不回退超过 `max(基线 10%, 5 ms)` |
| 动效新增准备成本 | 相对优化后 Off，ready P95 增量 ≤10 ms；离开/到达捕获分别报告。超过则不启用该路径 |
| 动效合成 | 局部 paint 工作 P95 ≤4 ms；60 Hz 参考下 paint 间隔 P95 ≤20 ms，单次 GUI 停顿 >50 ms 单列；高刷新率另报预算 |
| 完整稳定画面 | Light 的稳定 P95 不超过优化后 Off + 所选动效时长 +20 ms；另报迟到的最大 quality/capture paint，不能把原停顿搬到动效后 |
| 峰值内存/长连点 | 遵守 §2.3 字节上限；最多一对端点，20 次快速重定向无累积；结束后像素引用为 0，重复循环 RSS 不持续上升 |

阈值不能充当同步抓图的“超时保护”：Qt 同步 paint 无法在超时后撤回已经发生的阻塞。已知昂贵或尚无成本证据的路径先不主动抓图；需要通过原型/基线证明其准入，不能第一次卡住后才称已保护。

### 5.3 必测场景

| 场景组 | 重点 |
| --- | --- |
| 空、小数据、首次进入 | 正确空态/预览；没有幻影默认来源；无新增计算 |
| 500/2,000 候选，显示 2–3 条 | 树/候选去重收益，真实勾选与批量选择合同 |
| 百万点、范围裁剪、滤波、Custom-X | 准备与 paint 分开计时；旧路径保真；昂贵抓图不强行准入 |
| 时域/FFT View、五 Section 往返 | 目标参数、数据、范围、游标、历史与终态图片一致 |
| 同名异源、缺源、源重命名/重载 | 候选与控件失效正确，旧缓存/截图不会冒名 |
| 主副 Pane、不同范围、隐藏/记录曲线 | 焦点与共享侧栏正确，布局/联动/截图范围一致 |
| 20 次连点/反向、重排/删除 View | 最后合法目标正确，无动画队列、旧回调或重复操作 |
| 搜索补全、颜色配置、文件附件变化 | no-op 不遗漏合法更新，popup 与滚动/展开状态正确 |
| 动效中缩放/点击/快捷键/导出/关窗 | 不向旧图取点；原事件一次；保存/取消与生命周期正确 |
| DPR/窗口改变、长会话、多 View | 图像对齐、圆角/清晰度、内存释放与无静止自发刷新 |

矩阵按风险组合选择，不要求做所有维度的笛卡尔积；高成本组与普通组分别出结论。

## 6. 测试边界与平台门

- 每项先跑拥有该行为的 focused 测试，再补实际触及的边界；测试中创建的 Qt 对象显式归属，停止 timer，排空 deferred deletes。统一使用项目 `.venv`、隔离设置和可写临时目录。
- `ChartStack/MainWindow` 接线后：`tests/ui/test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`。
- 触及 `pg_canvas` collaborator 时：`tests/ui/test_pg_canvas_backref_invariants.py`；涉及 settle/reveal 时跑 `test_pg_timedomain_canvas.py` 中 `TestViewRestoreSettlement`、`TestDiscreteSettle` 及 paint backstop，和 `test_pg_line_canvas.py` 对应 reveal/AA 节点。不能放宽阈值或白名单。
- 共享控件/QSS 变化时：`tests/ui_kit/test_qss_border_shorthand.py` 和真实圆角/几何；探针与测试隔离检查使用 `tests/ui/test_qsettings_isolation.py`。
- 涉及缓存绑定/任务恢复的 integration 节点保留 `tests/ui/test_analysis_cache_pinning.py`、`test_analysis_jobs.py` 的适用门；没有改 worker 服务则不展开异步化专项。
- `-k` 先核对实际收集节点，0 selected 不算通过。本轮默认不跑全 suite；若集成证据表明跨边界风险需要全门，记录原因，仅一名协调者在稳定快照检查运行进程后执行一次：main 排除 `tests/acquisition_ui`，完成后另起进程跑 acquisition，禁止并行全门。
- **Offscreen：** 确定性状态/信号/像素结构；**Cocoa：** 原生真实控件、自然 paint、手感/耗时；**前台用户文件：** 真实使用验收；**Windows：** 100%/150%/200% 源码运行与 frozen 包分别记录。没有对应平台运行就写 `UNVERIFIED`，不能以 macOS 或源码检查替代。
- 本计划不包含发布打包。Windows frozen 缺口不虚报为已验收；若后续用于发布，另执行版本/打包/发布门。

## 7. 防回归与回退方式

1. **先冻结，逐项优化。** T1、T2、T3 与 M1/M2 分开提交候选补丁和 A/B 证据；不要一次混入状态重构、渲染重写和新动画。
2. **独立关闭动效。** 关闭后走原有恢复路径，无覆盖层、额外抓图或新导航队列；性能去重仍可独立验收。
3. **不能证明则保留旧路径。** 无法确认相同上下文时继续完整投影，未知绘制成本不准入动画；不能牺牲验证、诊断或结果完整性换时间。
4. **回退按责任模块。** 若某一步功能对照失败，先撤回该步；不通过增加全局旗标、强制 sleep、吞异常、修改测试期望或加线程强杀来补救。
5. **完成结论分层。** 文档完成、实现完成、功能对照通过、性能目标通过、视觉认可和各平台验收分别标注。通过测试降低回归风险，不能声称绝对“不会出现 bug”。

## 8. 后续优化方向：有测量缺口时再展开

| 方向 | 价值 | 开始前需要的证明 |
| --- | --- | --- |
| 时域裁剪/滤波准备结果复用 | 减少重复准备与数组地址变化导致的重建 | 枚举数据/时间轴/参数/Custom-X 的真实 mutation owner；保留先裁剪再滤波、NaN 与端点语义；缓存有字节预算。不得删除现有 source-revision guard |
| FFT/热图/FRF 显示对象复用 | 降低已有数值结果的显示重建成本 | 逐分区完整失效表：结果/单位/颜色/计权/范围意图/geometry/DPR；业务恢复仍执行，不能用 FFT 签名覆盖所有分析 |
| 昂贵虚线/叠加绘制路径 | 解决特定宽窗的大 paint | 分离线型与几何贡献，证明峰谷、NaN、原始/滤波可辨与导出一致；如改质量准入，先更新治理 spec 并 Cocoa 标定 |
| 自动预览捕获调度 | 降低点击后的长尾竞争 | 区分后台刷新、离开前必需捕获、用户主动同步和保存；沿用既有 ref/digest/重试 owner，避免延后到永久 pending |
| FFT/加载/保存纯数据任务异步化 | 重任务期间更可响应 | 快照所有权、任务 generation、取消/关闭、源删除与结果提交合同；复用既有服务，不把 QWidget 操作放 worker |
| 准备/显示/结果缓存字节观测 | 防止长会话内存压力拖慢响应 | 共享数组去重计账，保留 pinned View 结果；驱逐/落盘改变行为前需独立恢复设计 |

T1–T3 后仍有瓶颈时，按实际最长 paint/主线程阶段选择一个方向补充窄计划。不得因为本表出现某项就自动实施。

## 9. 本轮文档交付检查

原始计划稿仅新增本 Plan；其后 M0 新增独立 HTML 原型和 `.state/smoothness-transition/m0/` 证据。本次回写只更新该原型、M0 选择/准入状态和相应计划文字，不修改产品代码、旧计划/调查结论、测试或全局设置。检查范围为：真实 owner 与既有动效机制、相邻合同、引用路径/拟新增路径区分、任务依赖与验证边界、全文一致性及空白检查。

本次没有产品运行时行为变化，因此不运行产品 runtime suite，也不填写产品性能通过结论；HTML 仅做定向静态/浏览器检查。保留其他任务的未跟踪文件与在途改动。
