# 最近两天提交复审：数据身份、启动交接与预览一致性修复规格

- 日期：2026-09-25。
- 状态：**已按本文实施**。聚焦测试和本机 Cocoa 自动化场景已有证据；全量套件中断，Windows 包与 native 绘制未验收。不代表可以发布。详见配套 plan 第 13 节。
- 配套：[执行计划](../plans/2026-09-25-review-remediation-plan.md)。
- Review 基线：`c4b1ae90655dac8ee7cbebd13186aa5bf4cd2408..f83eee615963c721b5c4b5d48a5702d4ec731cfb`，25 个提交、180 个改动文件。专项探针主要来自 `8a6f7897` 快照，共享过渡增量另在 `f83eee61` 快照验证。
- 文档编写时 HEAD 为 `f83eee61`，工作区存在正在开发的 native startup launcher、splash、collapsible、ChartStack 等修改。实施前须按符号和行为重新定位；不得用历史行号覆盖这些修改。

## 1. 问题与证据

| ID | 等级 | 已确认事实 | 归因 |
| --- | --- | --- | --- |
| F1 | P1 | 真实 MF4 的非 master `Time` 信号覆盖公共轴：真实时间 `[0,.1,.2,.3]` 变成信号值 `[10,20,30,40]`，fs 从应有的 10 Hz 变为 0.1 Hz。`t/zeit` 已加载却被信号列表隐藏；单个 `Time` 信号文件报无可导入通道。 | 名称与时间身份混用的历史遗留；`ef63e1e6` 改为物理 master 判定时未横展到列命名和消费端。 |
| F2 | P2 | hidden ACK 先于 handover listener、EOF 晚于 finish 时，真实 socket/子进程正常 exit 0，超过 fallback 后主窗仍未显示。 | `0186a58f` 的一次性 reveal 通知遗漏晚订阅。 |
| F3 | P2 | MF4 late 通道仅覆盖 2–3 秒，共享轴为 0–4 秒；加载端有端点填充警告，Batch 却 `done`、warnings 为空，Replay payload 同样丢失诊断。 | `ef63e1e6` 新增诊断只完成交互导入路径。 |
| F4 | P2 | FRF 连续 Ctrl+滚轮改变真实 X 范围，revision 却 `[1,2,2]`；第二次缩放后 focus-inspect 不截图，仍复用同一 PreviewStore record。 | `1e672f97` 的范围 fingerprint 没适配 FRF getters。 |
| F5 | P2 | FRF 图片预览引用未定义的 `output_settings`，三个既有测试同根 `NameError`，UI 提示预览不可用。 | 8 月 9 日 `c1bea5fa4` 的历史遗留，不算近期新增回归。 |
| F6 | P2 | macOS 显式启用 splash 后，widget 检测到的 reduceMotion=True 被 child 的 Windows-only detector 覆盖成 False。 | `09ccaebf` 的平台偏好接线问题；macOS 默认 auto 不开 splash 不受此路径影响。 |
| F7 | P3 | 20,000 点 high-ink 切片切方向后变成 4 点、ink=0，AA 仍关闭且两个恢复 timer 都停止。 | `1e672f97` 新 quality policy 未覆盖方向切换。 |
| V1 | 测试门禁 | C4 AST 断言仍要求 builder 使用 `_SLICE_MAX_SPAN_DB`，但 review 基线已移除该依赖。 | 过期测试；不是已确认数值错误。 |
| V2 | 测试门禁 | splash peak/shadow 测试用逻辑坐标索引物理 QImage。高 DPI 配置后宽 640 的 widget 得到宽 667 的图像，组合运行误采样。 | 测试坐标体系错误；不能据此修改产品外观。 |

Review 中通过的定向测试不证明无其他 bug。本文限定关闭以上问题；原生窗口合成、Windows 包和全量 suite 的未验收状态单独保留。

## 2. 目标与范围

### 2.1 成功目标

1. MF4 的真实时间与采样率不会被信号名称污染；probe、load、GUI、Batch、Replay 对同一通道身份一致。
2. splash 已关闭的事实不会因 listener 注册时机丢失；主窗只在正确的 GUI 线程显示一次，退出后不会被迟到通知复活。
3. MF4 对齐、覆盖损失、端点填充和跳过通道的诊断，贯通交互导入、Batch 结果/manifest 和 Replay 加载 UI。
4. FRF 每次实际 viewport 变化都能使其 UltraView 预览失效；无变化时仍去重。
5. FRF Batch 预览和正式运行使用一致的输出设置与分组身份。
6. 动画遵守系统偏好；切片方向切换按最终曲线重新结算质量；测试在不同 DPR 下采样正确。

### 2.2 非目标与保持项

不改变 MF4 最长共享轴、重复时间保留最后值、倒退拒绝、交集约束和插值算法；不改变 FFT/FRF/Order 数值算法。保留数据格式、公共 imports、来源复合身份、用户选择和历史项目格式。

不重新设计启动 native launcher，不改 page-transition 合成策略、不重标定 ink/AA 阈值、不引入新的全局缓存，不做广泛架构拆分。版本升级、提交、推送、发布不属于本文实施范围。Windows QuickRef backdrop 的潜在圆角问题只有待验证线索，未纳入已确认修复。

## 3. D1 — MF4 时间列与信号身份（F1）

### 3.1 决策与 owner

选择“**显式时间列元数据 + 仅碰撞信号的确定性重命名**”。不再把 MF4 的 `t/zeit/time` 名称本身当作时间身份，也不改动其他格式的历史启发式识别。

Owner：[loader.py](../../../mf4_analyzer/io/loader.py)、[source_adapters.py](../../../mf4_analyzer/io/source_adapters.py)、[file_data.py](../../../mf4_analyzer/io/file_data.py)。公共命名逻辑在 IO 层，只产生中立数据，供 probe/load 共用。

### 3.2 数据合同

- `DataLoader.load_mf4()` 保持三元组返回和公共轴列 `Time`；`DataFrame.attrs['source_metadata']` 增加 `time_column='Time'`。该字段表示精确的列身份，而非大小写模糊匹配。
- `FileData` 在存在显式 `time_column` 时，从指定列建立时间轴，`get_signal_channels()` 仅排除该列；其他名字像时间的数值信号仍可选。元数据指向不存在列时显式报数据错误，不能回退到别的信号或虚构采样率。
- 未提供 `time_column` 的旧 FileData、CSV/Excel/其他格式继续走现有识别逻辑，不借本任务迁移全部格式。
- MF4 的 physical time master 按现有 MDF block 类型识别并排除；普通信号 `time/t/zeit` 保留既有去重后的信号键，不因名称像时间再改名或过滤。只有精确占用保留列 `Time` 的信号需要额外改名。
- 碰撞键沿用物理 occurrence 风格，例如 `Time [g:c]`。预先保留全部原有信号名和公共轴名；若该字符串也被真实信号占用，再按稳定顺序追加消歧后缀，直到唯一。相同文件 probe/load 得到完全相同映射，不能根据“哪些样本成功读入”临时重新分配名字。
- 扩展既有 `renamed_channels` 诊断，记录 original、renamed、physical_occurrence；保留单位和通道元数据映射。无碰撞信号不改名；不得以短标签作 identity。
- 不新增缺省 fs。空、单点、倒退、非有限值、非一维等边界仍由现有 MF4 owner 校验；此次只保证名称不会改写轴，单点采样率不在本任务中编造。

### 3.3 消费、兼容与退出规则

Registry 的 descriptor、loaded FileData、Batch 缓存/磁盘路径以及 Replay 都消费同一时间身份和信号映射。Replay 不再把首列作为 MF4 时间轴兜底；正常 MF4 loader 必须给出显式时间列。

旧项目/预设中不受碰撞影响的名字原样可用。涉及重命名时，只允许根据同源物理 occurrence 或唯一、明确的旧名映射匹配；歧义或缺失走现有缺失通道反馈，不猜测、不悄悄绑定其他通道。既有错误轴上保存的手动范围/计算结果不能自动宣称已纠正；重新导入产生正确数据事实，保留用户手动采样率覆盖的现有语义。

验收必须同时检查时间值、fs、信号样本、可选择通道、probe/load 一致性和项目重新打开。仅断言“加载不抛错”不够。

## 4. D2 — 启动 reveal 是可重放状态（F2）

Owner：[startup_feedback.py](../../../mf4_analyzer/startup_feedback.py) 保存完成事实；[startup_handover.py](../../../mf4_analyzer/startup_handover.py) 负责 GUI 线程恰好一次显示。

### 4.1 状态交付合同

- Feedback 缓存本 session 的 `can_reveal` 完成 payload。缓存与 listener 列表变更使用同一把已有锁，callback 在锁外执行。
- 新 listener 注册时：未完成则订阅后续事件；已经完成且未 close 则补发缓存的 `can_reveal`。注册与完成交错均不能漏送。重复注册同一 callback 为 no-op；不重放所有历史 raw/stage 消息。
- 完成状态的缓存意味着“事实已就绪”，不意味着任何时候都可以显示主窗。只有 handover.begin 后注册的 owner 接收；session 不匹配、closed、Qt 对象销毁、退出中均拒绝迟到显示。
- `StartupHandover` 保持幂等 `_show_called` 和 GUI receiver；不依靠 sleep、额外固定延迟、嵌套事件循环、主窗 first paint 或无 receiver 的 singleShot 修复竞态。
- hidden ACK 仍在实际 hide 之后发出；disabled/degraded/child exit/fallback 继续沿既有 reveal 条件，不把“child 正在退出”伪装成已隐藏。close 清 listener/可重放状态并保留正确清理。

| 通知与订阅顺序 | 必须结果 |
| --- | --- |
| listener → finish → hidden | 正常显示一次 |
| hidden → listener → finish → EOF | 重放完成事实，显示一次 |
| hidden → EOF → listener | 正常退出或既有降级路径均能完成显示一次 |
| listener 注册与 hidden 并发 | 无漏送；重复交付也不能重复 show |
| disabled / spawn failure / 超时 | 沿已有 fallback 完成；失败原因可观测 |
| close / 取消 → 迟到 hidden 或 EOF | 不显示、不访问已删除 QWidget |

### 4.2 与并行 native launcher 的接缝

当前未提交 `startup_native_feedback.py` 也有 `add_listener/_notify_reveal`，实施时必须盘点实际装配到 app 的全部 backend。若 native backend 已进入同一实施快照，则必须满足同一晚订阅合同并运行其合同测试；不能只修 Python-child 后宣称全局完成。沿已有 public listener seam 复用合同，避免新造第二套 MainWindow reveal 状态。未整合的 launcher 工作不由本计划接管。

## 5. D3 — 源数据诊断贯通 Batch 与 Replay（F3）

### 5.1 唯一生产端与元数据

加载端继续产生 `source_metadata['warnings']` 和 `mf4_alignment`，消费者不重新计算警告、不另写插值或覆盖判据。对端点填充、范围裁剪、重复时刻整理、跳过通道保留原来源上下文；按源身份 + 文本稳定去重，同名不同源不能合并。

### 5.2 Batch

Owner：[batch.py](../../../mf4_analyzer/batch.py) 的已解析 source 与既有 `_RunReporter`；沿用 item.warnings、effective facts、manifest 和结果详情 UI。

- 已加载数据和磁盘解析两条入口一致。在实际取得 source 后将其诊断带入对应 item；不为 metadata-only Preview 重新加载整文件或伪造尚未获得的诊断。
- 所有成功产物必须带上已知源警告；有数据之后才失败的任务也保留已有警告。source 尚未加载的 cancelled/skipped 项不虚构 source facts。
- 单任务、分组、FRF input/output 和 Order 的跨源 RPM 都要保留参与源的诊断；group 保留成员 source identity，不能只留下代表源。
- 结构化对齐信息进入现有 item effective-facts/manifest 的 source-diagnostics 子记录，由 owning source 身份索引；不进入 requested params、preset 或 project 用户意图。新字段向后兼容，旧 manifest 缺字段按未知处理。
- `done` 可继续代表计算完成，同时明确呈现警告，不新增 status 枚举或把所有补齐自动变成失败。结果详情可查看完整警告，摘要使用现有 warning presentation。
- CSV/XLSX 数据 schema 和 `series=original` 保持既有“未经过用户滤波”的含义；通过结果/manifest 明确数据可能经加载对齐，不能声称 `original` 等于原始测量。不开 manifest 也必须能在结果里看到警告。
- retry/resume 不丢警告、不重复追加、不另发 progress，不破坏 `_RunReporter` 单 owner。

### 5.3 Replay

Owner：[acquisition_capture/backends.py](../../../mf4_analyzer/acquisition_capture/backends.py) 的 ReplaySource/source_from_mf4；[acquisition_ui/replay_tab.py](../../../mf4_analyzer/acquisition_ui/replay_tab.py) 的 load_file 和展示。

- ReplaySource 增加有默认值的 warnings 与 source_metadata 字段；warnings 使用不可变 tuple，metadata 使用独立 default factory，四个既有必需构造参数保持兼容。结构数据复制到 payload，不持有临时 DataFrame/Qt 对象。
- source_from_mf4 读取同一 source metadata、显式时间列及信号映射；时间和值不再二次推断。正常无警告文件的回放行为、速度/暂停/seek 不变。
- `load_file()` 在启用 Play 前更新文件级警告区，显示“已按公共时间轴对齐，可能包含非原始测量值”及加载端详细原因；使用非阻塞、可持续查看的只读文本，不能仅记录日志或一闪而过。
- 警告跟随 source 生命周期：换无警告文件清除，换失败文件不把新警告贴到旧 source，停止/暂停仍保留当前文件的警告。长中文文本在最小支持窗口宽度换行，不挤出传输控件。
- 这是新增可见反馈，实施时同步 `ui/hints.py`、`ui/quickref.py` 的相关说明，不新增按钮或快捷键。

## 6. D4 — FRF viewport 事实与 UltraView 缓存（F4）

Owner：[pg_canvas/frf_canvas.py](../../../mf4_analyzer/ui/pg_canvas/frf_canvas.py) 提供范围事实；[ultraview_capture_coordinator.py](../../../mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py) 继续持有指纹、revision、capture 调度。

选择在 FRF 增加只读兼容接口：`get_visible_xlim()` 委托现有 `get_xlim()`；`get_visible_ylims()` 委托 `get_ylims()`。不在中立层引入 GUI，也不把 FRF 细节散入每个缓存消费者。

- X 使用物理 Hz，覆盖线性和 log frequency；Y 使用 magnitude/phase/coherence 的稳定键和当前数值。空 result 按既有 None/空事实约定，不造范围。
- 实际范围变化必须经过现有 presentation 信号到达 coordinator，包括连续 Ctrl/Shift 滚轮、平移、轴编辑、Home；检查这些入口，缺失时在 FRF owner 补接线，不靠手工无条件 bump revision。
- 相同范围、普通 paint、缓存重放不递增 revision；保留 cross-view restore guard、pane 绑定、源隐藏前 capture、Board 延后补截及 generation 校验。
- 真实改变会令旧 record 不再 current；后续合法消费者请求最终发布新截图。截图不能只更新计数而仍展示旧像素，也不能为了修复而每次 paint 强制截图。

## 7. D5 — FRF Batch 预览和运行的输出合同（F5）

Owner：`BatchRunner._preview_frf_outputs()`。使用既有 `_requested_output_settings(preset.outputs)` 获取同一请求的输出快照，并传入分组规划。保持 metadata-only、不加载信号、不计算 FRF。

验收覆盖 group_by=none/source/channel、data-only/image-only/both，以及实际支持的图片布局/格式配置。所有合同合法的组合中，Preview 的成员、group identity、artifact 数量和代表输出与 Run 一致；不支持组合走已有显式校验，不因本次顺手扩展功能。现有相同 PNG bytes 对比仍保留。

## 8. D6 — 单一平台动画偏好（F6）

Owner：`ui/startup_splash.py` 的现有跨平台 detector 和 widget；`startup_splash_child.py` 的初始化接线。保留 widget 已确定的 system reduced-motion，取消 Windows-only 默认 False 对其覆盖。若 detector 需移动，仍只保留一个事实来源，守住 startup stdlib import boundary。

平台检测失败沿现有可观测降级，不把 False 解释为 macOS 已确认关闭减少动态。明确注入的测试偏好保留支持；mac 默认 auto gate、Windows 正常播放、stage/progress 和 finish/hidden 功能保持。

若执行快照已整合 native splash，测试并记录其 reduce-motion 合同，禁止仅依据 Python widget 通过就宣布 native backend 通过；native 绘制本身属于相邻 launcher 计划，按接缝协作而非接管。

## 9. D7 — 切片方向变化后的离散质量结算（F7）

Owner：`ui/pg_canvas/slice_panel.py:set_slice_direction` 及已有 `_reset_slice_quality_for_rebuild/_arm_slice_discrete_aa`。

方向实际改变时，旧曲线的 quality decision 失效；重建期间 AA 关闭，样本及最终轴几何更新完成后，调用既有离散 settle。重新测新曲线 ink/point/backstop，不继承旧方向的 high-ink 拒绝；也不能在廉价→昂贵方向继续沿用 AA on。

复用现有独立 0 ms timer，不改 150 ms 交互 quiet timer 的 interval，不改阈值或强制打开 AA。相同方向设置为 no-op；hidden/clear/destroy 和 transition hold 仍遵守 existing lifecycle，晚回调不能复活旧曲线。backstop 对不同签名分别生效，不能清空全部黑名单规避它。

## 10. D8 — 测试合同修复（V1/V2）

- V1：用当前 `_auto_db_line_limits → signal.display_ranges.line_amplitude_limits` 的真实合同取代死符号断言，保留中立 owner 的绝对数值测试及 Batch 委托验证。覆盖常量、空/全非有限、有效 mask。若测试 owner 已覆盖，删去过期断言并明确替代位置，不增加同义 AST 测试、不退回旧计算。
- V2：将 QWidget 逻辑采样位置按所采 QImage/QPixmap 的实际 DPR 转换后再索引。DPR=1、2、一个受平台支持的分数比例都跑独立进程；每次记录实际 DPR。Qt 高 DPI 属性必须在 QApplication 前设置，不能靠固定 pytest 文件顺序过测。
- 继续验证角落透明、阴影边界及谱线峰顶真实像素，而非只检查 style token。组合入口、单独入口、前置 DPI 配置的结果一致。平台不支持指定分数比例时记录 UNKNOWN/skip 原因，不能冒充该 DPR 已验收。

## 11. 验收清单

| ID | 可验证出口 | 证据类别 |
| --- | --- | --- |
| A1 / F1 | Time/t/zeit/碰撞后缀真实 MF4 的轴、fs、样本、units、probe/load/selectable 一致；旧格式/项目不误绑定 | 真实文件、IO/GUI/Batch/Replay 集成 |
| A2 / F2 | 上述所有顺序下 eligible handover 显示一次、close 后零次；真实 child hidden 后自然 exit 0 | 确定性交错、真实 socket/Qt/进程 |
| A3 / F3 | 同一源诊断贯通 Batch item/manifest/details、Replay payload/加载 UI，重试不重复、换源不残留 | 真实导出产物、backend、Qt 渲染 |
| A4 / F4 | 第二次及后续 X/Y 变化使旧预览失效并发布新像素；同范围不额外 grab | 真实 FRF/capture/store，含 log Hz |
| A5 / F5 | 三个既有 NameError 回归转绿；合法输出组合的 preview/run 身份和产物一致 | metadata-only sentinel、真实产物 |
| A6 / F6 | mac 显式 splash 尊重 reduce-motion，Windows 正常；finish/hidden 无退化 | 平台偏好注入、真实 child、平台前台 |
| A7 / F7 | 双方向按新曲线结算、hold/hide/clear 安全、150 ms timer 不变 | 真实 heatmap/slice、前台渲染 |
| A8 / V1 | 过期符号依赖移除，现有数值与 owner 边界有实证保护 | 绝对数值测试 + 委托测试 |
| A9 / V2 | 逻辑/物理坐标转换正确，多 DPR 和入口顺序一致 | 独立 Qt 进程的像素断言 |

功能实现、focused/boundary、全量集成、macOS 前台、Windows frozen 是不同状态列。所有适用列有证据后才能关闭对应问题；平台未运行时可报告“代码完成、原生验收待完成”，不能写整体完成。
