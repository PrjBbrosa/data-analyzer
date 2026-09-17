# 页面切换动效安全性与性能 Follow-up Plan

- 日期：2026-09-16
- 状态：待实施；本次仅交付计划。
- 分析基线：HEAD `0bcac91e`。工作区有另一项 FFT 游标实现的在途修改，涉及 `stack.py` 等共享文件；实施前确认稳定快照及归属，不覆盖、不回退、不混入本补丁。
- 用户目标：修复切换动效不明显/未起作用的问题，优先保持可靠性，不加重已有偶发卡顿。
- 前序：[流畅性与页面过渡计划](2026-09-15-interaction-smoothness-and-page-transition-plan.md)、[两波审查修复计划](2026-09-16-two-wave-review-optimization-plan.md)。本文收窄为当前已启用的时域单 Pane View 交接，不继续前序尚未准入的分区扩展。
- 执行方式：单协调者顺序推进；不要求并行 agent，不自动提交、发布或 bump 版本。

## 1. 风险判断与实施决定

可以做窄范围修复，但不能承诺没有新增 bug 或显示成本。

| 风险 | 当前判断 | 控制措施 |
|---|---|---|
| 数值结果 / 新增 DSP | 展示层修复不需要新增数据计算，预期风险低 | 不改采样、滤波、FFT、结果缓存；以 Off/Light 的计算调用次数和终态数据对照证明。 |
| 输入与生命周期 | 风险中等；取消条件原本承担防止旧图覆盖新结果的职责 | 先区分正常 paint 与语义失效，保留 token、输入保护、关闭/resize/身份失效。不能只删除 Paint guard。 |
| 性能 | 尚未验证；修复后动画持续时间增加，可能增加重绘 | 捕获、目标 ready、overlay paint、下层曲线 paint、事件延迟分别计数计时；未达门的场景直接终态。 |
| 原有卡顿 | 根因尚未确定，动效不会自动消除主线程阻塞 | Off 路径先测量；只对明确重复且语义等价的局部工作去重，其他热点另记后续。 |

本轮优先顺序：正确性 → 不增加响应阻塞 → 动效完整播放。若只能通过增加目标截图、每帧曲线重绘或复杂缓存才能持续动画，则不扩大实现，保留 Off/直接终态并报告性能门未达。

## 2. 当前证据及限制

1. `window.py` 仅执行 `set_page_transition_enabled_sections(("time",))`；`_view_mixin.py:_begin_time_view_page_transition` 排除分屏、无文件、非时域。FFT View 和跨 Section 没有启用，不属于此轮“启用失效”修复。
2. `page_transition.py:eventFilter` 在 target ready 后把 `QEvent.Paint` 当成 `target-surface-invalidated`；paint 本身不能证明数据或几何被替换。
3. 最小真实 QWidget / Cocoa 探针使用当前 controller、生产无目标 pixmap 路径、真实 input target：`accept_target=True`，时长 300 ms，约 1 ms 后因 `target-surface-invalidated` 取消；offscreen 对照约 0 ms 取消。证明 controller 有过早取消路径，不代表已采集用户原窗口的完整 View 切换。
4. 空 ChartStack 的自然 paint 探针返回 `target-paint-not-requested`，没有完成恢复事务，不能作为生产链路通过或失败证据；实施时必须加载数据并走完整 View restore。
5. 现有 integration 测试含 QObject 模拟 paint fence，不能替代真实 QWidget/GraphicsView 事件循环。已有手动推进 animation clock 测试也不能证明自然重绘期间动画会持续。
6. 前序记录的小负载抓图 P95 及“无取消”结果来自旧快照/场景，不复用为当前性能验收；前序目标截图曾触发昂贵补绘，继续禁止该生产路径。

## 3. 不变边界

- 保持 300 ms、0 px；导航及业务提交不等待动画。finished 只清理展示资源。
- 只修当前 time 单 Pane 准入。FFT/FRF/热图、分屏、跨 Section、勾选通道不新增整图动效。
- 不引入全局偏好、每 View 图像缓存、每帧抓图、目标二次截图、`QGraphicsOpacityEffect`、轮询或事件循环强行 pumping。
- 不改 `TimeRenderGate`、X `flush=False` → Y → `settle_view_restore()` 顺序、150 ms quiet timer、独立 0 ms settle timer、ink/AA/raster 阈值。
- 不改数组、单位、View 身份/保存状态、dirty、pin、计算 job 和错误处理语义。
- 延用现有 presentation token/generation，控制器不访问 MainWindow 业务数据；优先从已有 owner 获取有效性事实。

## 4. 正常绘制与真正失效的区别

### 4.1 必须允许

- 同一已就绪目标的正常 expose/paint、覆盖层透明度变化造成的底层合成。
- 目标数据/身份/最终范围未变时的合法质量收敛；不得为了保留动画抑制正式画布的必要 paint。
- 无用户输入和语义变更的完整动画结束。自动测试既检查时间进度，也检查 transition_finished、最终像素与资源释放。

### 4.2 必须取消或重定向

| 事件 | 行为 |
|---|---|
| 新 View 导航 | 原业务 owner 接受目标；按已有 A→B→C 重定向，不排队。 |
| 来源/结果/参数/通道集合/有效范围变化 | 旧呈现失效，撤去覆盖显示真实画布；不能等下一次任意 Paint 才猜发生变化。 |
| View 删除、文件关闭、项目替换、canvas clear | 按身份/代际撤层；迟到 ack 不得重新启用。 |
| resize、DPR、隐藏/失活/关闭、目标销毁 | 保留现有生命周期清理；延后回调不得触碰失效 wrapper。 |
| pending 图面输入 | 阻止被覆盖图面操作；导航、取消、关窗保持可用；不缓存重放。 |
| ready 图面输入 | 撤层后交由真实目标处理原事件一次；保留当前 MouseMove 也提前结束的策略，不顺手改交互语义。 |
| 显式复制/导出 | 取消过渡，再按原正确目标和 flush 契约捕获。 |

实施前列出“触发源 → 已有 owner 事件/generation → 取消入口”的表，特别覆盖 ready 后的内容变更。仅在现有通知确有缺口时新增窄的呈现失效通知，放在 canvas owner；不建设全局 revision 系统，不复制业务状态。正常 paint 只做至多 O(1) 的已存代际比较，不遍历数据/通道或重新算 signature。尚不能证明失效完整性的场景先不动画。

## 5. 成本预算与测量口径

修复前、修复后 Off、修复后 Light 使用同机、同数据、同参数/范围、同窗口/DPR及稳定源码快照。性能采样与 profiler、截图录屏分开，避免探针自己触发重绘影响时延。

### 5.1 独立观测

- 输入回调、首次导航反馈、目标自然 paint ready、首次目标参与显示、完全交接及质量稳定分别记时。
- 离开端点 `QWidget.grab` 次数和耗时；目标抓图次数必须为 0。抓图可能触发 paint，不等于免费读取屏幕。
- overlay paint 与底层 GraphicsView/曲线 paint 次数、耗时分别计量，包含动画结束后的迟到 quality/UltraView 工作。
- 计算提交、prepare、plot/setData、restore/settle、UltraView 捕获次数与 Off 对照。动画每帧新增计算、数据扫描、plot/setData 必须为 0。
- 主线程 heartbeat lag P50/P95/max、最长单次 paint、像素缓冲峰值、取消原因与发生阶段。正常完成、输入中断、身份失效和性能降级分开计数。

### 5.2 准入门（沿用前序门槛，不代表已达标）

| 项目 | 通过标准 |
|---|---|
| 动效新增准备 | Light 相对同版本 Off 的目标 ready P95 增量 ≤10 ms。 |
| 正常合成 | overlay paint 工作 P95 ≤4 ms；60 Hz 参考下 paint 间隔 P95 ≤20 ms。Qt paint 统计不声称显示器 FPS。 |
| 完整交接 | Light 稳定 P95 ≤ Off +300 ms +20 ms；报告动画后迟到长 paint。 |
| 原直接切换路径 | 修复后 Off 相对修复前 Off 的 ready/稳定 P95 回退 ≤max(10%, 5 ms)。 |
| 事件响应 | Light heartbeat lag P95 相对 Off 增量 ≤max(Off 的 10%, 5 ms)；>50 ms 主线程停顿单列归因。 |
| 下层重绘 | 不出现随动画帧数增长的昂贵曲线重画；不能仅凭 overlay 自身很快放行。正常窗口合成与真实曲线执行分开观测。 |
| 内存 | 保持一组临时过渡，峰值像素缓冲（含临时副本）≤前序 64 MiB；结束引用归零，20 次重定向不累积。 |
| 静止 | 结束且现有质量/捕获收敛后，无动效自身驱动的刷新。 |

每组预热 5 次、至少 30 个暖样本；冷启动独立进程。覆盖普通小数据、多通道、百万点/滤波叠加、Custom-X、宽窗/高 DPR；另测至少 20 次快速反向。使用可公开合成数据并尽量加用户真实文件，无法取得时明确缺口。

同步 grab 不能被事后超时中断；不把“发现卡了再取消”称作避免首次阻塞。无准入证据或已知昂贵的路径，在 capture 前按可验证条件走直接终态。若不能建立可靠的低成本准入边界，则关闭当前 page-transition Light，而不是增加黑盒启发式。此降级仅影响动效，不撤销业务切换。

## 6. 任务分解与 Gate

### F0：稳定快照、红测试、真实链路证据

Owner：`tests/ui/test_page_transition.py`、`test_page_transition_integration.py`；探针放 `.state/page-transition-followup/`。

- 固定 HEAD/相关 dirty 文件哈希；共享文件在其他任务修改期间不跑性能验收。
- 补真实 QWidget 的自然事件循环回归，证明普通 paint 会提前取消；不靠手工跳到 300 ms 绕过绘制。
- 加载合成时域数据、两个真实 View，通过 MainWindow 标签/快捷键入口完成 restore 和自然 ack；记录提前取消的实际原因，允许探针先证伪当前猜测。
- 首轮仅运行受影响 focused baseline；不做全套基线。

### F1：最小生命周期修复

Owner：`ui/chart_stack/page_transition.py`；必要时 `stack.py` 与 `ui/pg_canvas/canvas.py` 的窄失效通知。

- 完成 §4 失效表后，把普通 paint 与语义失效分开；保留输入保护、看门狗、身份/几何检查和迟到回执失效。
- 不改画布绘制方式，不取消必要 quality paint，不新增 target capture。
- focused：`test_page_transition.py`、`test_page_transition_integration.py`；`test_view_switch_integration.py` 中目标删除条目；`test_view_switch_reentrancy.py`。
- 新用例覆盖自然绘制完整完成、paint 中真正数据替换、pending/ready 输入、窗口关闭、无 ack 超时、A→B→C 连续性及清理。

### F2：性能 A/B 与条件性低风险优化

Owner：探针优先复用 `scripts/probe_interaction_motion.py` 的基建；若新增独立探针须专用于当前时域过渡，临时结果不入 Git。

- 按 §5 测三组；明确原有卡顿发生于 capture、恢复/prepare、画布 paint 还是捕获尾部，不能把“动效修好”写成“卡顿修好”。
- 本计划允许的优化限于已证实、同一事务内语义相同的重复展示通知/无效刷新，必须先有调用次数及终态对照，且位于已触及的 presentation owner。
- 如果热点在数值准备、I/O、滤波、渲染策略或长期缓存，记录 owner/证据后另立窄任务；本轮不异步化、不重构缓存。
- 若透明覆盖层导致昂贵下层逐帧绘制，F1 不算准入成功；优先直接终态，不改成双截图/长期缓存来“补救”。

### F3：集成、视觉与交付

- 运行受影响 `test_ultraview_capture.py`、`test_ultraview_capture_facts.py`、`test_split_routing.py` 条目，实施时先确认具体 node IDs，0 selected 不算通过。
- 边界：`tests/ui/test_no_lambda_signal_connections.py`、`test_main_window_state_ownership.py`、`test_import_boundaries.py`。触及 canvas 时加 `test_pg_canvas_backref_invariants.py` 与 `test_pg_timedomain_canvas.py` 中 restore/discrete settle/paint backstop 条目；不放宽阈值或白名单。
- 测试使用项目 `.venv`、隔离 QSettings 和临时目录；停止 timer、断开临时连接、排空 deferred deletes。正常退出才算通过。
- Cocoa 完整 MainWindow 前台验证自然动画、首次输入、连点/反向、清晰度、截图目标；Windows 源码/Full/Lite 独立验收，没有证据为 UNKNOWN。
- 若准入范围或用户可见规则改变，同步 `ui/hints.py`、`ui/quickref.py` 及其 focused 测试。纯修复不虚构新增功能文案。
- 新增验证记录 `docs/analyzer/verify/2026-09-16-page-transition-safety-performance-followup.md`，分别报告生命周期修复、Off 原卡顿、Light 增量、平台门与最终启用范围。
- 检查 lesson status 和 `git diff --check`。默认不跑 full suite；只有新证据需要扩展时说明原因，遵守单一稳定快照、单协调者规则。

## 7. 关闭条件与本次交付

实施完成需要：普通 paint 不再误取消；语义失效仍正确撤层；不新增计算/重复提交；真实生产入口视觉与性能门通过，或对未准入场景明确保留直接终态。不以空控件测试、手动 animation clock 或 offscreen 耗时替代原生性能。

本次只新增本文；核对引用、owner、范围及空白，不运行实现测试，不修改产品代码。所有风险等级为计划阶段判断，修复效果与性能均待实施验证。

## 当前执行台账（2026-09-17）

上文「本次只新增本文」是 9 月 16 日编写时状态，保留。生命周期修复已落地，见 [验证记录](../verify/2026-09-16-page-transition-safety-performance-followup.md)。2026-09-17 审查修复不回退该合同；Cocoa/Windows 性能仍 UNKNOWN。
