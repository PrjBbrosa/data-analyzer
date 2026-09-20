# 进度区压缩、Cursor 拖动残影与 Pin 生命周期优化计划

- 日期：2026-09-20。
- 基线：`24b45a94435049809f7035f12c5fbbb9663a7884`。开始时仅有无关未跟踪文件 `ssh-keygen`；未读取或修改该文件。
- 范围：分析、诊断探针、编写 plan；**没有修改产品代码**。
- 状态：**分析与执行计划已形成，产品修复未开始**。进度压缩及孤儿 Pin 按钮已复现；连接线对比度有源码证据；用户截图中的拖动连续残影根因仍为 **UNKNOWN**，必须完成 R0 动态取证后才能选择其修法。
- 执行方式：单协调者顺序实施。无需新建全局管理器、拆分模块或并行 agent。
- 输入：用户两张截图及四项反馈。历史计划只用于核对已有实现，不继承其完成声明，也不把附带文字当作新增实施授权。

## 1. 结论与优先级

| 优先级 | 问题 | 本轮结论 | 用户影响 |
| --- | --- | --- | --- |
| P1 | 进度文字一直压缩 | **已确认**：同步工作阶段更新文字后只 repaint，新的 sizeHint 未落实为布局宽度 | 有空余空间仍显示“绘图 · 构…”，阶段和百分比不可见 |
| P1 | P1/P2 在，点击无面板，新建 Pin 后旧按钮消失 | **已确认一条完整同构路径**：空集合替换未清空 overlay，reflow 重建孤儿标签 | 界面与真实记录不一致；点击没有可操作的 intent |
| P1 | 拖动时留下多条位置线，松手才消失；Cursor 面板也有拖动问题 | **截图确认现象，像素残影根因未确认**。本轮模拟手势未发现 Pin 图元随每次 move 累积 | 拖动中位置判断不可信；不能以最终截图干净作为通过 |
| P2 | 灰色连接线太淡，有时找不到 | **已确认样式过弱及遮挡覆盖缺口**：1px 低 alpha；避障只包含其他 Pin 面板 | 白底/网格/曲线中难跟踪，普通 live Cursor 面板仍可能遮住路径 |
| P2 | 测试通过但以上问题仍存在 | **已确认测试盲区**：检查稳定后的文字、model/pill 数量和路径几何，未覆盖同步工作期和完整投影清理 | “测试通过”被误读为拖动和生命周期验收完成 |

这几项不能合并成一个“刷新不及时”修复：进度是布局未结算，孤儿按钮是逻辑投影未替换，拖动残影可能是损伤区域/合成问题，浅色线则涉及视觉对比和遮挡。各自在行为 owner 内修复。

## 2. 已确认的根因与证据

### 2.1 进度区：文字请求了新宽度，但同步工作期间实际槽位保持旧宽度

真实调用链：

1. `main_window/window.py:4227` `_begin_compute_progress("时间域绘制中", total=1000)`；`phase_progress` 后续送入“绘图 · 准备/构建/应用”。
2. `compute_progress.py` `_apply_label_text` 设置 `_full_label`、调用 `updateGeometry()`，随后立刻按当前槽位执行 `_refresh_label_elision()`。
3. `main_window/window.py:746` `_update_compute_progress(process_events=True)` **只调用进度控件 repaint**；只有 `flush_events=True` 才处理事件队列。绘图阶段使用前者。
4. `updateGeometry()` 请求的父布局重算尚未执行，`repaint()` 也不是布局提交。于是新的完整文字不断按旧宽度省略，直到同步绘图返回事件循环；届时进度控件往往已经隐藏。

本轮用真实 `MainWindow + SurfaceStatusBar + 生产 QSS`，在充足窗口宽度下复现，offscreen 与 Cocoa 一致：

| 时点 | 完整内容 | 可见内容 | 控件宽度 | 新 sizeHint | 文本预算 |
| --- | --- | --- | --- | --- | --- |
| 初始“绘图”后，同步更新构建阶段 | 绘图 · 构建 · 57% | 绘图 · 构… | 262px | 298px | 72px |
| 初始“时间域绘制中”后，同步更新构建阶段 | 绘图 · 构建 · 57% | 绘图 · 构… | 268px | 298px | 72px |
| 仅在探针中激活 statusBar/进度内部 layout，再按最终 rect 重算 elision | 绘图 · 应用 · 57% | 完整 | 298px | 298px | 已足够 |

局部布局对照没有调用额外 `processEvents()`。这是定位实验，不是已提交实现。截图里的省略号与此路径直接一致；本轮不声称重放了用户原始数据绘图全过程。

旧问题的 `label.setIndent(0)` 已在当前代码中，不能再把本次归因于默认 QLabel indent。QSS 160px 进度条、72px 最小文字槽位确实加剧窄宽表现，但在本次复现里窗口有空间，**根因不是单纯最大宽度太小**。

旧测试为什么通过：`tests/ui/test_compute_progress.py:108` 的完整 CAN 文案测试用了 `flush_events=True` 和后续 `qapp.processEvents()`；painted-ink 测试主动按 `sizeHint()` 设置宽度。它们验证了布局结算后的文本，不覆盖绘图的同步更新路径。

相邻风险：`window.py:876` 关闭状态提示是把字设为透明，仍保留标签及布局空间。真正空间紧张时也可能压缩进度区；这是源码确认的预算问题，不能与上述已复现的异步布局缺口混为一谈。

### 2.2 孤儿 P1/P2：空集合没有清掉全部派生投影

关键 owner：

- `pinned_cursor_controller.py:360` `set_collection`：取消编辑/重投影，`_clear_pills()`，赋新集合；**只有新集合非空才执行 `_mark_records_pending` / schedule**，空集合没有同步 overlay。
- `pinning/presentation.py:210` `clear_widgets`：清理 pill 和 axis-label 字典，但不拥有 overlay records/items。
- `pinning/presentation.py:285` `reflow_now`：调用 `overlay.reproject()`。
- `pinning/presentation.py:898` `project_axis_labels`：按 overlay layout 建立标签；当前 collection 只用于 open 样式，没有过滤 layout 中不属于当前集合的 record ID。
- `pinned_cursor_controller.py:522` `toggle_record_panel`：找不到对应 intent 就返回，所以孤儿按钮点不出面板。

本轮真实 ChartStack、两个 single Pin、offscreen 与 Cocoa 都得到：

| 操作 | model records | pills | overlay records / lines | axis labels |
| --- | --- | --- | --- | --- |
| 建立 P1/P2 | 2 | 2 | 2 / 2 | 2 |
| 调用正式入口替换为空集合，消费队列 | 0 | 0 | **2 / 2** | 0 |
| 正式 `reflow_visible()`，消费队列 | 0 | 0 | **2 / 2** | **2，均可见** |
| 调用旧 record 的 toggle | 0 | 0 | 2 / 2 | 2，仍无面板 |
| 探针写入一个新 record 并调用当前 owner 重投影 | 1 | 1 | 1 / 1 | 1，旧两个消失 |

最后一步是定向 owner 探针，未冒充原生 P 按键重放。它解释了用户观察的“重新 P 后旧 P1/P2 消失”：一次非空同步终于替换了旧 overlay。

触发范围不是只有手动 clear：`view_bridge.py:305` 和 `analysis_view_bridge.py:100` 都调用同一个 collection setter。View/pane 复用、旧项目缺少 Pin 字段、恢复到无 Pin 状态，均需覆盖。实际用户最初经过哪个操作仍未知，不能武断认定只发生于 View 切换。

已有 `test_view_switch_does_not_carry_p1` 检查 model、pill 和 ViewState，没有检查 overlay records、scene lines、axis labels，更没有继续 resize/reflow；因此不能拦住本缺陷。

### 2.3 连接线：低对比样式与不完整的遮挡模型

`pg_canvas/pinned_cursor_overlay.py:127` `_tether_pen` 固定颜色 `#607892`，idle alpha=118、highlight alpha=185，两者都只有 **1.0 逻辑像素虚线**。与白底合成后的名义颜色约为 `#b5c1cd` / `#8c9db0`，实际抗锯齿边缘更淡。对比单 Pin 位置线的完全不透明、1.5px / 2.25px，关联线明显弱一档。当前未建立最终合图中的最小可见性指标。

`pinning/presentation.py:467` `sync_tethers` 仅从 `overlay.records()` 和 `state.pills` 构造 obstacles。**普通 live Cursor 面板、其他覆盖 QWidget 不在避障输入中**。即使纯几何路由没有穿其他 Pin，也可能被 live 面板盖住。该缺口有源码证据；其对用户截图的具体贡献未定量复现。

另外，`_on_pinned_pill_event` 与标签 Enter/Leave/Focus 驱动高亮；拖动高亮没有独立的捕获期优先级。应测试从父面板进入标题按钮、离开控件但仍抓鼠标时是否降回 idle。此项是明确待验假设，不能提前宣称是残影根因。

已有上一轮修复仍然有效：实际 panel rect、四边候选 port、Move/Resize 跟随、面板外路由都已存在。**不重新实施“加一条连接线”或泛泛提高 z 值**；scene 的 z 值不能跨越 QWidget 遮挡。

### 2.4 拖动残影：当前证据不足以归因到“重复添加线”

用户截图中，多条蓝色虚线密集分布在拖动走过的 X 位置，且用户报告松手后消失。这证明拖动期显示异常；截图不能告诉我们那些位置是否仍有活图元。

当前数据链为 `PinnedAxisLabel move → preview_axis_edit → 0ms 合并 → _flush_axis_edit_preview → project_record + sync_overlay`。`_sync_lines`（overlay:1679）按 `(record_id, endpoint)` 重用每个 ViewBox 的线，位置更新走 `InfiniteLine.setValue`，不是每次 move 都追加一条线。

本轮四分图的 offscreen 模拟手势：8 次底部拖动、8 次面板拖动、释放，Pin 线始终 **4 条、对象 ID 不变**，X 从 0.3 更新到约 0.508386，scene line 总数没有逐帧增长。收集到拖动中的自然 viewport paint。它排除了这条探针路径的图元泄漏，**不能证明用户环境没有像素残影**。

原生 Cocoa 同类注入探针也未观察到 Pin 线数量增长，但底部手势在中途取消回到 0.3，后续出现普通 live 游标；取消原因未定位，不能把它作为拖动验收通过或与用户故障等同。最终 `grab()` 是重新渲染的控件图像，不是保留自然 backing store 的屏幕录像。

需继续区分的分支：

1. **损伤区域/合成残影**：当前 GraphicsView 继承 pyqtgraph 的 `MinimalViewportUpdate`、background cache；CursorPill 有 `WA_TranslucentBackground` / `WA_NoSystemBackground`。检查旧位置线、旧/新面板范围及 tether 变化是否都被自然重绘覆盖。这些配置只是调查入口，不是已证实缺陷。
2. **图元遗留**：检查 scene 中所有 Pin/live/旧 View 图元，而不只 managed 字典。逻辑空集合漏洞已经确认，需排除与拖动叠加。
3. **手势与延迟任务**：旧 scope/布局回调、FocusOut/Ungrab/Hide、视口几何变化导致 cancel；同时检查 live cursor 是否在捕获期恢复。记录首次异常发生层，而非靠 sleep 掩盖。

本地 pyqtgraph 的 InfiniteLine 几何/pen 更新也纳入旧损伤范围观察，但本轮没有证明库 bug；禁止直接改 site-packages 或归咎显卡。

## 3. 横向检查范围与边界

| 模块/场景 | 共享路径及结论 | 实施时必须验证 |
| --- | --- | --- |
| 时域 Time-X / Custom-X | 同一 controller/projector/overlay；空替换缺陷共用 | 分屏/叠加、single/dual/off、X 轴变更；物理坐标不转成显示坐标存储 |
| FFT 多 pane、preview | 同一 Pin 投影和 collection setter；潜在同类空替换风险 | FFT View/pane 切换、无结果→有结果→空；Pin 线不能画进 time preview |
| FRF 三图、线性/对数频率 | 同一 overlay，专用 Hz↔view 坐标适配 | 三图图元一致；非正 log 频率保持不可表示状态，不伪造边缘坐标 |
| 普通 live Cursor 面板 | 共用 CursorPill 拖动与透明绘制；不是独立 Pin 模型 | 单/双、full/mini、拖动中及松手后的旧范围清理；作为 tether 的 QWidget 障碍 |
| View/项目恢复、旧项目 | 两个 bridge 将 collection 投影到复用 canvas | 空是明确替换；pending→empty、empty→非空、rapid A→B→A、旧任务不可复活 |
| 文件/通道关闭 | `clear_all()` 当前显式 `overlay.clear()`；不能说所有清理都坏 | 最后文件关闭、部分源关闭、关最后 Pin；未关闭记录和身份保持 |
| UltraView、复制图片 | 使用源 canvas 的捕获/展示；最终 capture 可能重绘并掩盖残影 | 原生实时视图与复制分别验收；源已空时不能捕获旧 Pin；不修改 author connector 系统 |
| FFT/FRF/阶次/FFT-time/项目恢复的进度 | 共用 ComputeProgressWidget；调用者 process/flush 行为不同 | 逐一覆盖同步更新和异步返回；恢复 token 仍唯一，不重入 restore pump |
| Batch、采集状态栏 | 未证明共用本进度或 Pin owner | 本轮不进行泛化改造；只在发现共用调用链时扩大范围 |

继续保留 composite channel identity、各域数据求值、现有 scope/record UUID、编号、collapse/expand 意图、用户 anchor。没有证据要求修改 DSP、project schema 或 MainWindow 状态所有权。

## 4. 目标交互与不可退化条件

1. 正常支持窗口宽度下，“绘图 · 构建 · 100%”等规范短文案在工作期间完整可见。真正空间不足时先降低帮助提示占用、再让进度条按测量后的紧凑策略收缩；阶段/百分比优先。长文件名继续走原有状态消息/tooltip，不塞入进度标签。
2. 拖 Pn 时，当前记录的各子图只显示当前 endpoint 位置，其他 Pin 和 dual 另一个端点保留；**不通过拖动时隐藏所有线来规避残影**。展开面板同步显示预览读数，释放提交一次；取消恢复原值。
3. 拖面板只改变 anchor，位置线的数据坐标不变；tether 跟随接口，旧像素在手势中消失，不能等松手修复。
4. 关联线正常态就可辨识；hover/focus/drag 明显加强。保留中性关联线和 A/B 端点语义，不把所有线改为同一种醒目色。建议实测候选：idle 1.25–1.5px、高 alpha；active 1.75–2px、近不透明。最终数值由合图测量选定，不直接把候选写成常量。
5. Pn 可見意味着它属于当前 collection，点击能展开/收起对应记录或给出当前不可用状态；不存在“按钮有但记录无”的正常状态。空间不足与用户收起必须继续区分。
6. 不新增 Pin 管理面板、工具条、模式开关或成功计数。交互提示变化时同步 `ui/hints.py` 与 `ui/quickref.py`；本轮计划没有新增快捷键。

## 5. 执行顺序、文件 owner 与验收门

### R0 — 固化失败用例与拖动期动态取证

**Owner**：相关测试文件；诊断脚本和帧数据放 `.state/2026-09-20-progress-pin-audit/`，不加入运行时默认热路径。

- 把 2.1 探针转成失败回归：完成初始 show/layout 后，在后续一串同步 `_update_compute_progress(process_events=True)` 间不额外 pump/设置固定宽度。每一阶段断言文字与 painted ink，不仅检查最后一帧；记录 sizeHint、实际 rect、label contentsRect。
- 把 2.2 探针转成失败回归：非空→空→消费队列→reflow→resize/pan；同时检查 model、pills、axis labels、overlay records/lines/tethers/ports/extrema、scene 残留。pending 非空→空也必须覆盖。
- 残影取证用用户原环境或同平台可重复合成数据：4 分图、2 个以上 Pin、两张展开面板，press→多次 move→停住但不松手→release→settle；另走普通 live/pinned 面板拖动。
- 每帧记录 scope/record/endpoint、原值/preview/commit、图元 ID/scene owner、旧/新 scene bounds、viewport paint region、面板旧/新 rect、DPR、Qt/backend 版本、capture/cancel 原因、live suppression。对采样/日志做诊断开关与节流。
- 取证必须有**自然屏幕帧或窗口录像**；`grab/render` 会重新绘制，只可作“重新渲染参考帧”。将自然帧旧位置的像素与参考帧比较，排除曲线/网格本身；使用区分色的合成信号。先区分真实图元和旧像素。
- 若原始残影仍未复现，R3 保持 UNKNOWN，交付已确认修复也不得宣称四项全部关闭。无需阻塞独立的 R1/R2。

**Focused gate**：新增 progress、lifecycle 回归先失败；拖动证据链至少定位首次错误层。无需全量 baseline。

### R1 — 进度布局在局部 repaint 前结算

**Owner**：`ui/compute_progress.py`；`ui/main_window/window.py` 仅连接 status-bar 局部布局提交；有真实窄宽证据才改对应 QSS/提示布局。

- 将“更新完整文案 → 申请并落实父/内部槽位 → 按最终 label contentsRect elide → repaint”作为一个明确顺序。由拥有 statusBar 的位置协调父布局，子控件不任意 resize 布局管理的兄弟。
- 保留 `indent=0`、水平 ink mask、QSS chrome 的实测预算；必要时响应 label 自身 Resize/Font/Style/DPR，避免父宽度不变但内部槽位变了仍保留旧省略文本。
- 优先采用已定位的局部 layout activation/规范短文案宽度预算；不得为“刷新文字”恢复全局 `processEvents()`，不得重入绘图、项目恢复或用户事件。
- 窄宽策略以生产完整状态栏为对象：帮助按钮、版本、risk label、提示开/关均参与；透明提示不应在 busy 时占用本可释放的文字预算。进度条紧凑宽度必须同步处理 QSS min/max，不能只改 Python `_BAR_WIDTH`。
- 每次阶段更新保持 token guard 和百分比钳制，不新增并列进度状态 owner。

**Focused**：`test_compute_progress.py` 新同步序列及既有 painted-ink；`test_compute_progress_integration.py` 中受影响 caller。

**Boundary**：`test_timedomain_mode_switch_empty_frame.py`、现有 project-restore progress/token 用例；改 QSS 才加 `tests/ui_kit/test_qss_border_shorthand.py`。真实 Cocoa 同步绘图截图；Windows 对应环境补验。

### R2 — collection 替换是包括空值的完整投影事务

**Owner**：`chart_stack/pinned_cursor_controller.py`、`chart_stack/pinning/presentation.py`；overlay 复用现有 clear/set_records 接口，只有确证清理不足才修改。

- 同一替换入口取消旧编辑、旧 reproject、旧布局请求；替换 owner.collection；清除/更新 widgets 与 overlay。**empty 分支必须显式发布空投影**，不能依靠下一次非空 Pin、重建图表或 resize 才清理。
- 选择调用 `overlay.clear()` 或完整空 `sync_overlay` 时，明确 tether、高亮、extrema、layout callback 的顺序，保证回调看到的是新集合；不在旧集合仍生效时重建标签。
- label 投影检查当前集合成员/作用域，拒绝旧 layout 的孤儿 record；它是防御性边界，不替代上游清空图元。
- 复用既有 layout token/scope 检查，避免再造全局 generation。非空→新非空与 pending→empty 都不能收到旧队列投影。
- 不修改 Pn 编号、旧项目兼容或 capture 空集合的身份规则；`None` 与显式 empty 按现有 bridge 合同分别处理，不贸然把“未绑定”当成清空。

**Focused**：`test_pinned_cursor_lifecycle.py`、`test_pinned_cursor_panels.py`、`test_pinned_cursor_geometry.py` 对应 replacement/teardown 场景；Time/FFT/FRF 参数化覆盖。

**Boundary**：`test_pinned_cursor_architecture.py`、`test_pg_canvas_backref_invariants.py`；涉及 bridge 时追加相关 View/pane restore 用例；`test_pinned_cursor_capture.py` 验证空替换后的复制/UltraView 无旧投影。

### R3 — 按 R0 证据修复拖动旧位置的失效范围

**Owner**：由首次异常层决定：axis edit/projector、overlay，或共用 CursorPill/GraphicsView。该任务**尚不能指定唯一实现方案**。

- 若 scene 项增长：修正拥有者/移除/重用逻辑，固定每个 `(record, endpoint, ViewBox)` 的数量；不能靠全屏 repaint 隐藏活图元。
- 若 scene 正确而屏幕残影：修正 old/new bounds 的损伤提交，考虑 panel/tether/line 的联合范围、透明 QWidget 下方绘制和 DPR。优先只对所属 viewport 合并一次更新，保持每事件循环一次，不在每个 move 同步 repaint 整个 MainWindow。
- 只有诊断对照证实 MinimalViewportUpdate/cache 组合导致丢损伤，才评估局部改变 update mode/cache。禁止无证据全局启用 FullViewportUpdate；必须比较多分图交互耗时和 paint 次数。
- 若是捕获/cancel/live 恢复冲突：修正捕获期优先级及结束顺序。记录并区分真实数据版本变化、窗口失焦与程序布局；不删除合法 stale 校验，不延长 sleep。
- 数据预览仍不写持久集合；release 使用最终坐标只 dirty 一次；Escape、模式切换、View 替换、源失效要对称收尾。

**Focused**：`test_pinned_cursor_interaction.py` 加“展开面板+多分图+多 move”的中间帧/图元用例；共用 CursorPill 则补普通 live 拖动、快速 release 和 safe-rect 场景。

**Boundary**：改 canvas 时跑 backref；碰通用 GraphicsView 时覆盖 Time/FFT/FRF 对应 paint-timer/游标测试。验收必须包含原平台自然帧，offscreen 数量测试不替代像素结果。

### R4 — tether 可见性、捕获期强调与实际遮挡

**Owner**：`pinning/presentation.py` 的几何 DTO、`pg_canvas/pinned_cursor_overlay.py` 的路由/画笔；不把控件对象放进中立记录。

- 采用可辨识 idle + 更强 active 的两级线宽/alpha；验证亮底、灰网格、密集波形、normal/Retina/Windows 缩放。以最终路径可见像素和连续性为准，不能只断言 pen 常量。
- 把同画布可见 live Cursor 面板加入 obstacle；检查 legend/其他浮层确实会遮挡的部分，按实际宿主边界处理，避免拉入整个 UltraView 作者连接器系统。
- 拖动捕获期保持 active，Enter/Leave 子控件不能撤销拖动强调；结束后恢复 hover/focus 状态，取消/销毁时复位。
- 路由结果必须在可见 host 内、位于面板外；边缘、拥挤、目标 offscreen 时有确定回退。仅端口且无路径要能解释，不画到错误端点。保留上一轮候选 port 与障碍检查，不推翻已有布局。
- 面板 Move/Resize 跟随只更新几何，不采样、不 dirty、不整表重排；测量并合并冗余 `_sync_tethers`，只有实际重复开销成立才优化。

**Focused**：geometry 的 path/port/obstacle 测试，新增 live-panel 障碍与 host 边缘，以及 final composite 可见像素；interaction 验证捕获期强调；capture 验证合图一致。

### R5 — 稳定快照收口

- R1–R4 各 owner 门通过后，协调者只跑一次适用的整合文件集合；复用本轮/实施轮同一指纹结果，不每个小补丁重复全套。
- 核对 HEAD、工作区改动，`git diff --check`，隔离 QSettings。此范围不要求通跑 `tests/ui` 或整个仓库。
- 记录“实现、focused、offscreen 合图、Cocoa 自然手势、用户原场景、Windows”六种状态。缺任一对应证据就明确标注 `UNVERIFIED`。
- 没有自然拖动证据，不把 R3/R4 标成 completed；没有 Windows 环境，不以 macOS 注入手势声称通过 Windows。

## 6. 最小验收矩阵

采用共享 owner 的代表组合，不做无意义全排列；以下每行必须有具体证据：

| 维度 | 必测代表 | 核心断言 |
| --- | --- | --- |
| 进度时序 | begin→准备→构建→应用→finish，全程同步；异步更新另测 | 每个 busy 阶段完整，未额外 pump；tooltip/ink/百分比正确 |
| 状态栏预算 | 支持的最小窗口宽度、常用宽屏；提示开/关；risk 显示 | 真有空间时不 elide；窄宽有明确优先级，按钮仍可访问 |
| Pin 替换 | 非空→空、非空→非空、pending→空，随后 pan/resize/reflow | model、所有 projection、scene 同步；旧任务不复活 |
| 底部拖动 | Time 四分图，single；dual A/B、A=B、A>B；展开/收起 | 中间每帧只保留合法线，读数/位置一致，release dirty 一次 |
| 面板拖动 | live 与 pinned；full/mini；越过曲线和另一面板 | anchor 持续跟随，旧范围无残影，Pin X 不变 |
| 域适配 | Custom-X、FFT 含 preview、多 pane FRF log | 坐标不串域，preview 无 Pin，三图一致 |
| 生命周期 | View/pane 切换、项目恢复、关最后文件、关部分源、close/unpin/off | 有效 Pin 保留，应该删除的全部删除，不靠新 P 自愈 |
| tether | 白底网格、多 Pin/live 遮挡、边缘、offscreen | idle 可见、drag 更强、路径在 host 内且无错误关联 |
| 平台/捕获 | Cocoa；用户实际平台及缩放；复制/UltraView | 自然显示与重新渲染证据分开，松手前已正确 |

## 7. 本轮已执行的验证及限制

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_compute_progress.py \
  tests/ui/test_pinned_cursor_interaction.py \
  tests/ui/test_pinned_cursor_lifecycle.py \
  tests/ui/test_pinned_cursor_geometry.py -q
```

结果：**98 passed, 154 warnings in 149.64s**，正常退出。它是当前既有 owner 测试结果，不是问题已修复的证据。

本地诊断证据（不纳入 Git）：

- `.state/2026-09-20-progress-pin-audit/probe.py`、`probe.log`、`probe-cocoa.log`：状态栏同步阶段与空集合残留；Cocoa 包含局部 layout 对照。
- `drag_probe.py`、`drag-offscreen.log`、`drag-cocoa.log`：四分图、8 次轴标签 move / 8 次 panel move、图元身份和自然 viewport paint region；Cocoa 中途取消已如实记载。
- `stale-labels.png`、`progress-before-*.png`、`progress-local-layout-*.png`、`drag-*.png`：控件重新渲染证据，**不是自然屏幕拖动残影验收**。

历史 [2026-09-19 牵引可见性修复计划](2026-09-19-pin-interaction-visibility-remediation-plan.md) 的 94 passed 和已实现条目不重复计算为本轮证据。继续保留其仍适用的 quick-release、最新 anchor、外部路由、实测 label geometry 合同；本计划补的是同步布局、完整清空、动态损伤和实际可见性缺口。
