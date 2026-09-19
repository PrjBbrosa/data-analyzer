# Pin / View 结构治理 · 实施计划

- 日期：2026-09-19。状态：**计划待实施；本次仅交付 spec/plan**。
- 设计：[Pin / View 结构治理 spec](../specs/2026-09-19-pin-view-structure-governance-design.md)。对应旧 [加固计划 T9](2026-09-19-view-isolation-and-pinned-cursor-hardening-plan.md)。
- 检查基线：`c75c47e3cba6e41fd5208affaa966f972336b434` + 当时未提交的 Pin 修改，详见 spec §7 的 blob。执行前必须重新定位，不能拿本次检查当稳定运行时 baseline。
- 前置：正在进行的 [底部 Pin 与闪退修复](2026-09-19-pin-bottom-handles-and-crash-fix-plan.md) 完成相关 focused/原生崩溃 gate，产品交互形成稳定快照。**不和该计划并发改同一批文件**。
- 执行方式：单协调者、顺序小步。不要求 agents、不自动 commit/push，不回滚他人代码。每个任务都是独立可审查 patch；不以历史计划的 commit/revert 文字推导新授权。

## 1. 判定与实施边界

有必要治理，但旧 T9 需 revision：删除 UndoStack 目标；区分纯 facts 和依赖 Qt 的采样适配；保留已修的 F-V2-5，不重做“首 fid”修复；chrome/resize 优化独立于机械搬迁。

包 A（控制器拆分）与包 B（外观 API）可分别交付，不互相成为不必要的阻塞；包 C（事件去重）的 geometry 部分依赖 Projector 完成。推荐顺序：T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8。如果 B 的身份存储边界需要扩展，停止 B 并交代，不扩大成全画布 key 重构；A/C 已通过的成果可单独验收。

### 沿用 2026-08-04 范式，但不沿用过时门禁

采用 [机械拆分 plan](2026-08-04-ui-mechanical-splits-implementation.md) 的兼容/monkeypatch 清查和逐步迁移，以及 [所有权 plan](2026-08-04-main-window-state-ownership-implementation.md) 的先立边界、后迁状态。新任务不跑泛化的前置全套/全 UI baseline；每步只跑 owner 和相关 boundary，最终稳定里程碑才跑一次全量。

## 2. T0 — 稳定快照、兼容清查与行为冻结

**改动归属：** 新增 `tests/ui/test_pinned_cursor_architecture.py`；必要的 characterization 并入既有 Pin/外观测试。临时清查与 baseline 记录放 `.state/pin-structure/`，不提交生成物。

- [ ] 核对前置产品计划的实际执行状态；记录 HEAD、dirty、相关 blob、测试命令和平台。若 controller 正被另一任务改动，暂停该文件迁移而不是抢改。
- [ ] 列出原 controller 每个方法的目标 owner、读写状态、Qt 副作用及消费者。列出 façade 导出、常量、`pin_feedback_level`、ChartStack/bridge/capture 调用；不按分节注释自动搬。
- [ ] 审计 tests/scripts 的 `_owner`、`_last_mouse_global`、`_application_filter_installed`、静态类引用、module globals monkeypatch；给每个 seam 标记保留转发 / 有证据的测试迁移。conftest 的 filter 哨兵必须覆盖真正 Router。
- [ ] 冻结已验收行为：P 的 ShortcutOverride/KeyPress 序列、树焦点与输入框、同点去重、unpin 再 P 编号、close 不撤销、默认收起/多开、拖动最后样本/取消、clear/install 是否 dirty、capture fingerprint 和内容。
- [ ] 新增 architecture guard：collaborator 不反向 import façade/stack/window；collection 写入和 `intent_changed` emission 有明确 owner；Projector 控件表只在 Projector 内改。先以当前事实记录迁移目标，不能用放宽白名单换绿。
- [ ] 外观测试锁住同 fid 不同绑定已有修复；建立明确 expected target 的 owner 测试，不只比较新旧两个同错路径。

**运行：** 仅新增/涉及的 nodes：`tests/ui/test_pinned_cursor_interaction.py`、`test_pinned_cursor_panels.py`、`test_pinned_cursor_lifecycle.py`、`test_pinned_cursor_capture.py`、`test_view_appearance_isolation.py`。纯 refactor 特征测试先在稳定旧结构上绿；新增安全/去重合同先红，并记录具体失败。

**完成：** 对每项迁移有可执行行为 oracle 和清晰兼容表；无需全量 pre-baseline，也不复用历史通过数。

## 3. T1 — 纯 facts 与格式化先分离

**创建：** `mf4_analyzer/ui/pinned_cursor_facts.py`、`tests/test_pinned_cursor_facts_rules.py`。
**修改：** controller、`ui/chart_stack/cursor_display.py`；身份解析若确需移出 GUI helper，原路径保留显式委托。

- [ ] 提取 `_reconcile_sample`、identity/binding helpers、诊断行及数值存在性规则；依赖参数显式传入。不传 canvas/host，不调用 Qt，不修改数字取样算法。
- [ ] `_evaluate/_axis_compatible/_canvas_generations` 留给 Qt adapter，不能为了凑“纯 evaluator”复制画布采样逻辑。
- [ ] 坐标/header/status HTML 迁到 `cursor_display.py`，保留单/双、full/mini、单位、颜色、escaping 和有效坐标表达。
- [ ] 每个纯函数以既有输入/输出特征用例验证，cover hidden/unchecked/unavailable、binding_id、空 sample、非有限值、不同域、dual A=B/A>B；不顺手修改 `_key_in` 的既有匹配合同。若发现新错配，单列失败证据和 scope 决策。

**Gate：** 新纯规则 tests；`tests/test_pinned_cursor_state.py`、`tests/ui/test_pinned_cursor_facts.py`、`test_cursor_pill_formatting.py`、`test_cursor_table_geometry.py` 关联 nodes。fresh subprocess 对 `pinned_cursor_facts` / state / display-model 投毒 PyQt5、pyqtgraph 后 import；中立模块不得间接拉入 `plot_helpers` 的 GUI 依赖。`tests/ui/test_import_boundaries.py`。

## 4. T2 — 采样适配与命令边界

**创建：** `ui/chart_stack/pinning/{__init__,sampling,commands}.py`、`tests/ui/test_pin_commands.py`、`tests/ui/test_pin_sampling_adapter.py`。
**修改：** controller；已有底部拖动实现若已另有 helper，优先复用/迁入，不造第二套事务。

- [ ] Sampling 迁入 Qt canvas dispatch、axis/revision、bound/hidden snapshot；无自有 sample cache。用最小 fake canvas 直接测试四域，另保留真实画布 parity。
- [ ] Commands 接收不可变意图/事实及有限依赖；产出命令结果。controller 统一更新 collection、runtime facts 与 reservation/live suppression，再按冻结顺序投影和反馈。
- [ ] 迁入新建/去重/取消固定/关闭/展开/编辑命令，保留 caller signatures。拖动临时状态归 Commands，持久集合仍归 controller。
- [ ] preview/cancel/相同有效坐标无 commit；成功 release 一次 commit/intent_changed；晚到结果须符合 owner/scope/generation。
- [ ] 去掉本轮迁移范围中的 stale “undo” 注释，不重引入 `_ClosedPin` 或撤销入口。

**Gate：** 新 adapter/commands tests，`test_pinned_cursor_interaction.py`、`test_pinned_cursor_facts.py`、`test_pinned_cursor_lifecycle.py`；与实际领域适配变更对应的 `test_custom_x_cursor_contract.py`、`test_pg_line_canvas.py`、`test_frf_canvas.py` 节点。新增 architecture guard，不改 DSP oracle。

## 5. T3 — 输入 Router 与投影 Projector，收拢可变状态

**创建：** `ui/chart_stack/pinning/{key_router,presentation}.py`。
**修改：** controller、必要的 stack 窄适配、Pin owner tests；有必要时更新 conftest 的诊断查询，不取消哨兵。

- [ ] Router 抽出 application filter 与只读 hit；绑定发生在已有 pane_added / 协调者确认命中之后，不能谓词内隐式建 owner。
- [ ] 保留 show/hide/close 安装卸载、输入法控件/模态/UltraView/FFT preview 排除、非自动重复 P。一次事件内复用一次 hit；ShortcutOverride 到 KeyPress 间重新校验窗口和目标，不能复用失效命中。
- [ ] Projector 接管 pill/label maps、局部事件过滤、anchor 应用、overlay DTO、offscreen 标记与高亮。controller 不再直接 new/delete/move pill 或手改其私有内容。
- [ ] 控件信号只发送记录/端点命令；Projector 不改 collection、不采样。overlay 图元仍归 canvas `PinnedCursorOverlay`，不复制它的重投影逻辑。
- [ ] 拆 `_OwnerState` 的逻辑 state 与 presentation state；不共享可任意写的大对象。destroyed/clear/unbind 取消时序、计时器和连接归属按 spec §3.2 实现。
- [ ] 旧 façade 转发保持真实晚绑定与 filter 状态；兼容 `_owner` 测试视图只能只读，不增加供产品写穿的新入口。

**Gate：** `test_pinned_cursor_architecture.py`（新增）、`test_pinned_cursor_interaction.py`、`test_pinned_cursor_panels.py`、`test_pinned_cursor_lifecycle.py`、`test_pinned_cursor_geometry.py`、`test_pinned_cursor_capture.py`、`test_split_container.py` 对应节点。真实 app filter 个数与 QObject 销毁后回调计数必须正确；保留原生崩溃 subprocess regression。`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`；涉及 collaborator 声明才加 `test_pg_canvas_backref_invariants.py`。

**阶段完成：** façade 稳定、状态单 owner、新协作者能脱离 MainWindow 直接测。不开行数门，不为消除几个委托方法破坏兼容。

## 6. T4 — 外观身份与画布公开 API（先新增，暂不删旧入口）

**创建：** `ui/chart_appearance_model.py`、`ui/pg_canvas/appearance.py`、`tests/ui/test_canvas_appearance_api.py`。
**修改：** `ui/pg_canvas/canvas.py`、实际普通/滤波 row builder、`ui/time_curve_bindings.py` 的 metadata 传递、必要的增量 bind 路径。不动数值处理。

- [ ] 先补同源双 binding/同名歧义/伴随线/主从轴/缺省 meta 的明确身份测试；确认现有曲线存储是否保留需要区分的记录。
- [ ] 添加可选 appearance identity metadata，保持已有 6/7/8 项 row 契约；不会因新 meta 改 X/Y、单位、顺序、可见性或计算结果。
- [ ] 全量 bind、selection delta、源删除、clear 同步 registry，且在 `chart_rebuilt` 前可用。新 metadata 若影响身份但不影响曲线数组，也必须触发 registry 更新；不能被旧 signature/cache 判为无变化而跳过。
- [ ] canvas 公开接口按 spec §4：稳定 target、精确 companion source、共享 X-aware snapshot、apply 与最终范围 repair。Qt 实现在 appearance collaborator；小型中立 DTO 不 import canvas/ViewState。
- [ ] 身份不明返回带原因的 unavailable，不猜前缀、不首 fid。旧行仍绘图；记录 transient diagnostics，热路径按现有节流约束。
- [ ] 若 recolor 需 typed identity signal，保持旧信号兼容，列出所有消费者；MainWindow 只选一路。若同名记录已被底层存储合并，按 spec 的范围边界暂停该子项，禁止自动扩展 key schema。

**Gate：** 新 API tests，`tests/ui/test_view_appearance_isolation.py`、`test_time_curve_bindings.py`、`test_time_filter_overlay.py`、`test_pg_timedomain_canvas.py` 中 selection delta / bind / restore settlement 节点，`test_subplot_shared_axis.py`。boundary：`test_pg_canvas_backref_invariants.py`、`test_import_boundaries.py`；中立 appearance model 子进程 Qt 投毒。比较冷重建/增量路径的明确 target 与 rendered output，不能只比两个同错 digest。

## 7. T5 — View 外观调用方迁移与越界读棘轮

**修改：** `_view_mixin.py` 的 companion resolve、capture、xlabel ownership、key lookup、apply、repair、inside-label 操作相关方法；复用现有 codec key helper。
**测试：** 新增 `tests/ui/test_view_appearance_boundary.py` 或在既有边界文件增加有语义的扫描。

- [ ] View 仍独占状态写入与 dirty/共享投影门控；canvas 不接受整个 state/window，不读取 navigator/files。
- [ ] façade 查询/动作替换私有结构遍历。移除前缀猜测；未知/歧义不静默写错 target。
- [ ] 在限定外观调用链内，直接属性和 `getattr` 形式的私有字段访问均归零；扫描禁止这些字段重新流回 MainWindow。不能只是改变量名或挪到另一个 mixin 绕 guard。
- [ ] 保留稳定编码、同 fid 不同 binding 的已修复行为；legacy missing field/旧行策略需有测试，不升级工程 schema。

**Gate：** `test_view_appearance_boundary.py`（新增）、`test_view_appearance_isolation.py`、`test_view_state_isolation.py`、`test_view_switch_integration.py`、`test_project_session.py` 关联 nodes；`test_main_window_state_ownership.py`、`test_pg_canvas_backref_invariants.py`。确认 `restore_visible_xlim(flush=False)` → ylims → `settle_view_restore()` 次序及 150ms quiet timer 不变。

## 8. T6 — Chrome 幂等（行为优化，独立红绿）

**修改：** `ui/chart_stack/cursor_pill.py`；必要时调用点只减重复设置，不修改读数语义。

- [ ] 先为相同 role/hint 的重复设置计数，证明旧实现有重复 polish；计数限定该 pill 按钮，排除 QApplication 初始化主题噪声。
- [ ] role style、hint 文本、几何分开按变化更新；theme/font/style/DPR 变化仍有失效入口。不能因同 role 早退而漏掉真实 hint 或动作布局变化。
- [ ] 测 100 次相同内容设置额外 role polish 为零，hint-only 不重刷角色样式，live/pinned 切换与 full/mini 角落布局保持。

**Gate：** `tests/ui/test_cursor_pill_formatting.py`、`test_chart_stack.py::test_cursor_pill_toggle_stays_pinned_to_top_right_corner` 及 pinned 对偶、`test_cursor_table_geometry.py`、`test_pinned_cursor_panels.py`；`tests/ui_kit/test_qss_border_shorthand.py`。用真实 style 渲染，不只看 property 值；Cocoa 外观另验。

## 9. T7 — Resize 合并与稳定捕获 flush

**前置：** T3。**修改：** Projector、stack resize/splitter 请求点、现有 capture 的稳定布局入口；不改 data sampling 调度。

- [ ] 建失败计数用例：同一事件轮连续几何通知重复排字；记录原最终几何与捕获像素。
- [ ] Projector 一个拥有明确 QObject parent 的 single-shot geometry timer，latest geometry wins；同 size/content/style 不重复 reflow。原数据 reproject timer 保持原职责。
- [ ] 原点变化只定位/引线；缩小/放大、长文本宽度变化、awaiting_space、隐藏用户卡、font/DPR 变化分别验证。不按半行文字裁切过关。
- [ ] `flush_layout` 在复制/合图/UltraView 前消费 pending 最终布局；同 token 无第二次排版。事务 preview 的 capture 延后照旧；reset/销毁/切 View 不执行旧队列。
- [ ] 防 reentrant layout，下一轮请求有界；无持续空转 timer。resize 不采样、无 dirty、无额外 FFT/FRF 计算。

**Gate：** `tests/ui/test_pinned_cursor_geometry.py`、`test_pinned_cursor_capture.py`、`test_pinned_cursor_lifecycle.py`、`test_cursor_table_geometry.py`、`test_fft_cursor_layout.py`、`test_ultraview_capture_facts.py`、`test_ultraview_capture.py` 关联 nodes。新增 burst/flush/cancel 计数与像素用例。20 Pin × 6 子图的 Cocoa 测量在 T8 做，不用 offscreen 声称帧率。

## 10. T8 — 集成、性能与平台验收

- [ ] 总验收矩阵：下表全部有证据或明确 UNVERIFIED。新增模块的静态 import 对 packaging 可见；检查现有 hidden-import 规则，不无依据增加手写名单。
- [ ] 相关边界最终合并运行一次：`tests/ui/test_pinned_cursor_architecture.py`（新增）、`test_view_appearance_boundary.py`（新增）、`test_pg_canvas_backref_invariants.py`、`test_import_boundaries.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`tests/test_packaging_imports.py`、`tests/test_signal_no_gui_import.py`、`tests/test_native_import_boundaries.py`。边界未触及的 Batch 不加泛化重测。
- [ ] 跨输入、状态、画布、捕获的最终稳定里程碑安排一次全量，由协调者唯一运行。先检查 pytest 进程及 cwd；记 HEAD/dirty/hash，主套件 `--ignore=tests/acquisition_ui` 完成后单独跑 `tests/acquisition_ui`。相关源码变化或异常退出记 UNVERIFIED；不从部分通过推断整套成功。
- [ ] Cocoa 前后台分开测：相同窗口、数据、DPR、开启面板数，0/3/20 Pin、单图/6 子图、连续 hover、resize、splitter。报告 polish/reflow/采样次数与 frame p50/p95，至少多次相同脚本交错前后对照；收益低于测量波动则不声称提速。沿用 `scripts/benchmark_timedomain_interaction.py --assert-standards` 既有标准，不临时放宽。
- [ ] Cocoa 前台实际看完整字形/角落/竖线、同点多按钮、多面板、取消拖动与复制图；图像/几何对比只能冻结窗口和数据后进行。Windows source 与 Full/Lite frozen 100%/150%/200% 分开记录；无环境记 UNVERIFIED。
- [ ] 文案不新增交互，无需借本结构任务重写 hints/quickref；若执行中改变公开交互则超出本 spec，先修订契约并同步两份说明。
- [ ] `git diff --check`、变更范围、lesson status；不改历史 spec 成果数字、不自动发布/提交。

| ID | 完成标准 |
| --- | --- |
| S01 | 原 controller import/ChartStack/bridge/capture 入口稳定，晚绑定测试 seam 没有静默失效 |
| S02 | 一个 app filter；隐藏/销毁无泄漏，哨兵仍验证真实 Router |
| S03 | collection 与意图通知唯一出口，preview/cancel/reflow 不写持久状态 |
| S04 | Sampling 不格式化 UI，纯 facts 无 Qt；Projector 不采样/改 collection |
| S05 | 新建默认收起、多开、坐标编辑、取消/编号/full-mini 行为符合前置产品快照 |
| S06 | 外观调用链私有字段读归零，已修同 fid 绑定行为保留，无 display-prefix 猜测 |
| S07 | stable target 在全量/增量/clear/重开一致；未知/歧义不可误写其他来源 |
| S08 | 100 次相同 role/hint 额外 role polish 为 0；真实变化及 style 更新不漏 |
| S09 | 同轮 resize 合并，稳定布局不重排、原点变化不排字、geometry 不采样 |
| S10 | capture flush 用最终几何；主副/分析合图与 UltraView 无旧图/重复层 |
| S11 | 所有 timer/连接/回调销毁对称；原生 mapTo 回归未被重构带回 |
| S12 | focused/boundary/最终平台结果分别记录，不以 HTML 或 offscreen 代替 Cocoa/Windows |

## 11. 停止条件与本次文档交付

出现以下情况先定位并报告：前置实现仍变化；必须改变 DSP/curve-key 存储 schema 才能完成身份要求；公开兼容无法保留；新的生命周期崩溃；性能优化破坏最终像素/捕获。不能自动扩大到全仓拆分，也不对用户工作执行 reset/revert。

本次只新增本 plan 与对应 spec，外加 `.state/` 调研记录。检查链接、代码锚点、测试路径、历史冲突和 diff；**未运行 runtime suite，也未实施任何结构修改**。旧 T9 原文保留为历史依据；本文明确替代其结构建议，不覆盖它的历史验证结果。
