# 时频与阶次手动色阶状态修复 Plan

日期：2026-10-08

状态：已获实施与 agent 并行授权；实现及验收进展见[执行记录](../verify/2026-10-08-heatmap-manual-color-scale-state-verification.md)。原生/平台未运行子项单列。

唯一产品合同：[Spec](../specs/2026-10-08-heatmap-manual-color-scale-state-spec.md)

## 1. 执行约束与完成标准

用户在 Spec/Plan 后明确授权“直接安排 agent 同步执行”。本次包含实现、定向验证及文档收尾；不包含 commit、push 或 release。

实际由父 agent 统一接口和集成，三个 worker 分别负责共享策略/持久状态、画布/控件、回归测试。共享合同先约定；后续任务沿依赖派发、文件所有权显式交接，同一文件不同时交给两个 worker。

实施目标为 Spec A01–A16 的适用门禁；Cocoa/前台 A17 和 Windows Full/Lite A18 分别报告。没有原生或 frozen 证据时不得宣称全平台问题已关闭。

本计划不要求全量 baseline；先对受影响 owner 建立失败用例，再实现，再运行相关边界。初始文档阶段仅检查范围/引用/diff；实施阶段执行下述 focused 与边界门禁。

## 2. 当前基线与文件所有权

分析时 HEAD 为 `875221db`。以下已有修改不是本任务工作：FRF validation recovery、hints/quickref、Windows Lite 构建脚本及测试、lessons INDEX 和关联未跟踪文档/测试。实施前重读 `git status` 与目标 diff，保留这些修改；尤其 hints/quickref 若需补充说明，只加与本任务有关的最小块，不能覆盖原改动。

下表 `ui/`、`heatmap_color_policy.py`、`db_reference.py` 相对 `mf4_analyzer/`；省略目录的 mixin / `_state_holders.py` 相对 `mf4_analyzer/ui/main_window/`。

| Owner/接缝 | 允许修改目的 | 禁止扩展 |
| --- | --- | --- |
| `ui/analysis_view_state.py` | 可选基准记录、验证、序列化、深拷贝 | 重做 View/Pane 全模型 |
| `ui/analysis_view_bridge.py` | 热图持久化请求快照接入、保护非 Z capture | 导入 MainWindow、改 FFT/FRF capture 语义 |
| `ui/main_window/analysis_context.py` | 持有并注入色阶协调器 | 新增分散 MainWindow 状态 |
| `ui/heatmap_color_coordinator.py` | 来源/拥有者解析、请求与投影转换、整轮 prepare | DSP、Qt 画图、通用事务框架 |
| `_state_holders.py` | 冻结 render 输入、signature/retain 关闭循环 | 保存新的控件或画布全局引用 |
| `_analysis_mixin.py` | View/split/comparison/edit/capture 路由 | 全文件搬迁或广泛重构 |
| `_fft_time_mixin.py`、`_order_mixin.py` | 两 renderer 只读准备好的有效输入 | 各自复制另一份 reference 策略 |
| `ui/pg_canvas/heatmap_canvas.py` | 显式已解析 levels、画布兼容调用、最终 slice 投影 | 在 compatibility facade 写实现 |
| `ui/analysis_section_page.py` | 锁定传播/最终提交，消除中间窗口反馈 | 更改布局/按钮外观 |
| `ui/dialogs/chart_options.py`、contextual 热图入口 | 精确用户 Z 编辑与还原快照（确有需要时） | 改所有 spinbox 全局行为 |
| `ui/main_window/window.py` | 窄适配 cached-render、协调器初始化接缝 | 新策略或大段业务逻辑 |
| `ui/project_io.py`、`_project_io_mixin.py` | remap、save/restore、当前值展开桥接 | 改其他 section/schema 历史 |
| `heatmap_color_policy.py` | 中立标量策略/基准校验；复用现有 reference resolver | 引入 GUI 或新单位目录 |

测试临时证据放 `.state/heatmap-color-state/`。正式测试使用版本化合成 fixture，不依赖 `.state/manual-level-diagnosis/`。不编辑 CLAUDE.md；本轮不改共享 AGENTS/CLAUDE 约束。

## 3. T0：冻结复现和入口行为

依赖：无。输出：失败回归、入口/状态清单、稳定快照记录。对应 A01–A03、A05–A09、A12、A13。

1. 记录 HEAD、相关 dirty diff、是否有同 owner 文件的并发编辑。只读确认正在运行的 pytest 及工作目录，避免重复或重叠宽门禁。
2. 读取相关 lessons：`codex-analysis-view-restore-projection-guards.md`、`analysis-view-tests-seed-attachments.md`、`programmatic-view-projection-is-not-user-intent.md`、`pyqt-ui/2026-09-25-chart-options-restore-commits-opening-snapshot.md`。不批量载入 corpus。
3. 核对 Spec D1/D2 的当前真实符号与旧 reference Spec §8.3–8.4；Spec 以当前代码为核验对象，历史记录不是新的绿色 baseline。
4. 在 `tests/ui/test_heatmap_color_state_integration.py`（本次新增）构造真实 MainWindow、已 attach 来源、两个已缓存 View；时频/阶次参数化。复用稳定 fixture 所有权方式，避免从另一个测试模块导入私有 fixture/helper 形成耦合。
5. 把旧观察探针改为会失败的业务断言：20 轮后各 View 仍保持初始窗口，raw/display arrays 在同 reference 下不变，Inspector 只对应焦点，计算提交次数为零。`assert matrix_unchanged` 单独通过不算完成。
6. 加入普通 split 的 pane 顺序/焦点对照和 Auto 元数据 reference 比值场景。直接种入 cache 只用于状态恢复边界；另保留至少一条实际计算结果路径。
7. 冻结实际 Z 入口作用域：Inspector、colorbar、chart options、预设、锁定/解锁及 comparison；记录当前 View.params 与 pane appearance 的优先关系。若现有明确合同和 Spec §6 有冲突，先修订文档再实施，不默改产品作用域。

Focused baseline：新失败 nodeids，以及既有 `tests/ui/test_pg_heatmap_canvas.py` 的 `test_heatmap_manual_levels_shift_with_reference_delta`、`test_heatmap_auto_levels_rederive_after_reference_change`、`test_heatmap_level_shift_never_clips_matrix`；`tests/ui/test_analysis_multiview_integration.py::test_fft_time_and_order_viewport_roundtrip`。

Gate：至少 A01/A03 以产品断言失败，并且失败原因与 D1/D2 一致；不是源未 attach、缓存 miss、QSettings 泄漏或未排空事件导致的假失败。禁止先跑全套 tests/ui。

## 4. T1：确定请求与基准模型，先完成纯策略

依赖：T0。输出：单一基准记录、确定性解析接口、模型测试。对应 A04、A07、A10–A13。

1. 在 `PaneState` 增加可选 `heatmap_color_basis`，字段遵守 Spec §4.3。追加 dataclass 字段保持原位置参数兼容；to/from dict 深拷贝，不序列化运行缓存。
2. 维护 View 默认/pane 覆盖现有权威层级；基准只补齐请求的物理解释，不复制一份持久有效范围。缺基准首帧零平移。
3. 实现纯 prepare：输入请求、origin、source、基准、当前 reference/模式，输出有效策略及必要的一次基准绑定建议。准备阶段不得改控件或画布；事务成功后由单一 owner 接受基准绑定。
4. 建立数值测试：±30/120 dB、1→10→1、相同值重复、极小极大正有限 reference、非法 scalar/lo≥hi；证明计算使用 anchor/current 而非 previous-frame/current。
5. 定义来源换绑、单位/quantity 变化、fallback 恢复、auto/Linear 的明确 re-anchor/未绑定行为。无有效来源不能伪造 reference=1 作为历史。
6. 在 `AnalysisContext` 初始化协调器，明确 reset/teardown。新 module 保持单一职责，所需依赖显式注入，不把 MainWindow 作为无边界后门。

新增 focused：`tests/ui/test_heatmap_color_policy.py`（标量/状态策略）、`tests/ui/test_heatmap_color_coordinator.py`（事务与目标）；扩展 `tests/ui/test_analysis_view_state.py`（record 合法性、旧缺省、copy）。没有矩阵算法修改，不编写镜像实现的测试；用数值例子、往返与不变性约束。

边界：`tests/ui/test_main_window_state_ownership.py`，新 import 路径涉及中立层时增加 `tests/ui/test_import_boundaries.py`、`tests/test_signal_no_gui_import.py`。任何 ratchet 不能扩 whitelist 过关。

Gate：相同输入求值幂等；合法 reference 变更正确且可逆；非法基准只局部失效。请求与有效值在 API 上可辨认，不靠布尔命名含糊区分。

## 5. T2：接通只读渲染，关闭 View/split 漂移

依赖：T1。输出：时频/阶次统一 prepare → paint → final projection。对应 A01–A05、A08、A09、A12、A15。

1. 在缓存恢复、正常计算完成、comparison render 三个路径上从所属请求准备每个 pane 的不可变输入；组恢复事务完成前不投影 Inspector，明确每个输入的 section/view/pane/source 与 reference。
2. `_render_cached_heatmap` 不再每个 pane 临时从共享控件采集下一轮请求；`_render_fft_time_on` / `_render_order_on` 允许消费已经准备的快照，保留既有可调用签名的窄适配。
3. 新增画布显式最终 levels 路径，时频 `plot_result` 与阶次 `_paint_order_heatmap` 都只应用解析结果。正式路径移除 `_last_db_reference`/`previous_db_reference` 作为请求偏移来源。保留裸 canvas 默认行为及兼容 import，并测试两种路径不会重复 shift。
4. 调整 render DTO 与 reveal signature：输入包含真实有效色阶/当前参考，不能把上次 canvas reference 当期望状态；同步所有 DTO 构造测试和 fields-change signature tests。
5. 删除或转移 render 内手动/自动 levels 的逐 pane Inspector 回写；在最后一次统一投影。补普通 split 焦点判定，使未绑定 comparison 的非焦点画布也不能写控件。
6. 同步接入最小持久请求 capture 保护：切 View 前不能把有效投影重新存成请求。此项不能等 T3 才做，否则“同源 reference 变更后再切 View”会重新污染基准。T3 再补齐全部编辑入口与 preset/save 消费者。
7. 将锁定合并挪到全组有效窗口已知之后，输出一次最终 levels；图像、色条、手动 slice 使用同一值。避免 `levels_rebased` 产生中间 union/replot 循环，拖动仍不重写活跃 handle 的起点。
8. 最终色阶/锁定 settle 后才提交 retain/reveal 与 UltraView 通知；后台结果检查请求身份，过期目标不能写当前控件。

Focused：T0 新 integration 回归；`tests/ui/test_pg_heatmap_canvas.py` 中 levels、reference、manual slice、presentation/retain 相关 nodeids；`tests/ui/test_analysis_multiview_integration.py` 中 heatmap render inputs、unchanged entry、reference change、viewport restore 用例；`tests/ui/test_analysis_view_comparison_regressions.py` 的背景回写与 bound pane 用例。

边界：`tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_main_window_state_ownership.py`；新增/改接 signal 时运行 `tests/ui/test_no_lambda_signal_connections.py`。不修改 slice math/布局时不追加全部 UI layout suite。

Gate：A01/A03 红转绿；同一数据同一 reference 矩阵逐元素不变；交换 pane 渲染顺序结果一致；实际同源 reference 更改仍正确，零新增计算。

## 6. T3：统一编辑入口与捕获，防止其他路径重新污染

依赖：T2。输出：显式 Z 提交边界、投影精度保护、预设/图表/锁定一致性。对应 A06–A09、A11、A13。

1. 建立“用户提交 Z / reference 变更 / 非 Z 参数修改 / 投影恢复”可辨识入口；优先扩展现有 contextual handlers 和事务回调，不新增笼统事件总线。
2. `capture_params_to_state` 使用明确的持久请求快照接缝；热图保存原始请求 z，非热图和既有 duck-typed 调用保留默认行为。`_sync_active_analysis_params`、compute edits、preset commit 和 save 全部检查该接缝。
3. 处理 Inspector 单边编辑：区分真实编辑字段和仅显示字段，未编辑边界使用 owner/有效结果的 double 值；不从 round 后的 spin 读回丢精度。测试超出旧 spin 范围的 reference 投影。
4. 所有真实 Z 提交按 Spec §6 原子更新请求和受影响 pane 的 reference 基准。pane chart override 必须提前纳入 prepare；appearance 最后投影不得再次覆盖本轮已解析 Z。
5. 色条 drag、结束、双击恢复和 chart-options Apply/还原走相同 owning commit；还原包含打开时请求 origin/基准。仅标题/cmap 修改不触碰 Z；Cancel 无副作用。对话框期间 owner 已变化时拒绝陈旧提交或沿用已有明确绑定，不能落入新焦点。
6. 预设应用含 Z 时刷新该 View 的请求与基准并清理冲突 Z 覆盖；保留其他 appearance。reference 投影不影响 baseline 的请求比较。导出用户预设明确展开当前 effective 数字，不导出来源基准。
7. 锁定真实编辑在单事务中提交全部参与 owner，程序传播不重复提交。comparison 沿用兼容性检查；扩展切焦点、换配对、pane 添加/删除、退出对比测试。
8. Spec §6 的覆盖处理与 §7 解除锁定恢复自身窗口涉及可见语义，实施这些条款时必须同步 hints/quickref 的最小说明；不得把它们当成无交互影响的内部调整。若 T0 经证据修订 Spec 为完全保留原语义，才能记录无需新增说明的依据。不得混入已有 FRF 文案改动。

Focused：新 coordinator/integration 测试；`tests/ui/test_analysis_view_bridge.py`、`tests/ui/test_preset_state.py` 的相关合同；`tests/ui/test_dialogs.py` 的三个 chart-options restore 用例；`tests/ui/test_analysis_view_comparison.py` 与 regressions 的受影响颜色/焦点场景。触及 contextual 编辑后运行 `tests/ui/test_inspector.py` 对应热图 Z/amp/preset 测试。

边界：桥接改动必须加 FFT/FRF capture 对照；修改 hints 时跑 `tests/ui/test_hints.py`；只有 QSS 真正变化才需 QSS gates，本任务不预设要改样式。

Gate：只改 X/Y、切焦点、save、重绘、自动回显均不改变请求数字；精度不逐轮丢失；没有“色条看对了、Inspector/pane appearance 存错了”的半修复。

## 7. T4：项目兼容、来源重映射与输出接缝

依赖：T3。输出：新旧项目可重放、输出值展开正确。对应 A10、A12–A14。

1. 核对当前 nested schema，再做一次 additive 版本推进；实现基准字段序列化、source fid remap、缺源清理、View duplicate 深拷贝。
2. 为当前 schema 和无基准旧 payload 做项目 JSON round-trip：请求及基准保持；旧数字首帧不平移；catalog 在重开前变化时按原 anchor 投影。
3. 覆盖损坏字段、schema 与字段 presence 不一致、source fid 相同名字不同实体、missing source；不能把 source 名称或 View ID 当成 fid remap。
4. 保存前 capture 使用请求快照，不读 hidden section 的共享 UI；补“当前焦点在另一个 section/comparison peer 时保存”的实际临时项目测试。保持 restore dirty guard，迁移不自动保存用户文件。
5. 检查 `_remember_batch_preset`、GUI 当前设置 → Batch 和 preset 导出所有消费者：无基准消费者必须接收展开后的有效范围；既有原生 recipe 数字语义不变，不向 Batch renderer 引入 GUI/canvas 状态。
6. 验证截图/复制/UltraView 当前画面和切片读取最终 levels；抓取前后请求、基准和焦点不变。只在发现实际消费者缺口时改其适配，不为推测风险改写捕获系统。

Focused：`tests/ui/test_analysis_view_state.py`、`tests/test_project_io_analysis_views.py`、`tests/ui/test_project_session.py` 中新增/相关热图保存恢复用例；`tests/ui/test_ultraview_project_session.py` 的直接受影响场景；`tests/test_batch_render_qt_heatmap.py`、`tests/test_batch_heatmap_producer_contract.py` 中手动 levels 与当前参数桥接场景。

边界：若改变 Batch 导入接缝，运行 `tests/test_batch_render_import_boundary.py`；若确实新增模块/动态依赖，运行 `tests/test_packaging_imports.py` 并核对 hidden imports。不修改 Batch orchestration，因此不预设 `test_batch_run_reporter.py`；若实际触及编排，必须追加此门禁并说明原因。

Gate：不用 canvas 历史也能通过保存重开；新代码不试图猜测修正旧项目中已漂移的值；GUI 有效范围与 Batch/图片输出一致，raw 数值输出不变。

## 8. T5：集成与真实渲染验收

依赖：T4。输出：A01–A18 的证据矩阵，清晰的未完成平台 gate。

先复用同一稳定快照已通过 focused 结果，仅为最新变化或尚未覆盖的集成组合追加运行。检查完整差异、残留写入点与错误路径，不泛化成全仓审计。

重点静态复核：

```bash
rg -n 'reference_delta_since_last_render|previous_db_reference|_last_manual_levels_shifted|canvas_previous_db_reference' mf4_analyzer tests
rg -n 'spin_z_floor|spin_z_ceiling|z_floor|z_ceiling|z_min|z_max' mf4_analyzer/ui/main_window mf4_analyzer/ui/analysis_view_bridge.py
```

保留的历史字段必须有兼容用途与测试，不能仅为了零搜索结果删除 API。检查每个剩余控件写入属于纯投影还是真实提交；检查 `_project_heatmap_pane_appearance` 不再重复应用旧 Z 数字。

### 8.1 Focused/边界汇总

| 验收 | 主要承载测试 | 责任步骤 |
| --- | --- | --- |
| A01–A03、A05、A12 | 新 `test_heatmap_color_state_integration.py`，已有 multiview 对照 | T0/T2 |
| A04、A11 | 新 policy/coordinator 数值用例、pg_heatmap 旧参考变化用例 | T1/T2/T3 |
| A06–A07、A13 | bridge、preset、inspector、dialogs 定向用例 | T3 |
| A08–A09 | integration、analysis_section_page 锁定用例、comparison/regressions | T2/T3 |
| A10 | analysis_view_state、project_io_analysis_views、project_session | T4 |
| A14 | Batch 当前参数/热图、UltraView/图片产物 | T4/T5 |
| A15–A16 | multiview retain/signature、旧 canvas API、所有权/import/signal gates | T2/T5 |
| A17 | 独立 Cocoa 进程与前台 TraceLab | T5 |
| A18 | 实际 Windows Full/Lite frozen | T5/发布验收 |

新增测试已落地；现有测试按实际受影响 nodeids 选取，实施报告保存实际命令。测试必须验证用户行为及跨边界不变性，不能只断言新字段名或模拟 helper 调用次数。

命令模板：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本步骤文件或nodeid> -q
```

所有 UI 测试使用项目 fixture 隔离 QSettings；本机真实 preset store 不能成为测试条件。新 Widget 显式 owner，处理 deferred delete，关闭 dialog/定时器。遵守 repo-root collector fixture 修复；不能通过固定文件参数顺序、sleep 或 xfail 掩盖 fixture 丢失。

### 8.2 Cocoa 与前台验收

独立新进程使用 `QT_QPA_PLATFORM=cocoa`，记录 OS/Qt/pyqtgraph、HEAD/dirty fingerprint、来源、reference、请求/基准、image/cbar/slice ranges 和焦点。

1. 用可公开重建的信号 fixture，实际计算两个时频 View 与两个阶次 View，分别使用已知 reference 比值。手动设置不同上下限以避免“两图本来相同”掩盖串写。
2. 各往返至少 20 轮，自动比较每个 owner 与实际 levels；捕获初始、中间、末轮图片，核对色条实际绘出的数字和切片幅值轴，而不只检查 QSS/控件属性。
3. 重复双窗格焦点 0/1、锁定开/关、comparison host/peer，进行一次真实拖动和图表还原；真实参考值 1→10→1 应移动并恢复，不得“修好切换”同时禁用合法补偿。
4. 保存临时项目、关闭重开，再导出 PNG/复制/UltraView；对相同结果的指定绘图区自动比较，剔除时间戳、鼠标等非数据装饰时写明区域。
5. 若用户原始项目可获得，用它复核原投诉。不可获得则明确“合成前台已验收、原项目复核 UNVERIFIED”；不得修改或覆盖用户原项目。

无前台能力、异常退出、崩溃、超时、中断都记 UNVERIFIED，不把前面输出的通过项推定为整组通过。

### 8.3 Windows 与全量门禁

Windows Full/Lite 必须基于修复后的同一源码快照重新构建，分别运行核心 View/split/保存恢复路径，记录包版本/构建身份。未执行则保留 A18=UNVERIFIED，不以 build-script tests 代替 frozen 验收。

本修复默认没有全量 suite 门禁。只有实际范围扩大为广泛跨边界重构、合并/发布验收或新增 order/teardown 污染证据时才扩大：先记录理由和唯一执行 owner，检查 pytest 进程及 cwd，稳定集成快照最多跑一次。主套件 `--ignore=tests/acquisition_ui` 完成后再独立运行 acquisition_ui，不并行；相关文件在运行中改变则结果标 UNVERIFIED。

## 9. T6：文档、教训和交付收尾

依赖：所有已授权实施步骤结束。输出：实际完成/未完成矩阵与可复核变更。

1. 对照 A01–A18 逐项附测试 nodeid、命令/日志或渲染产物与结论；区分源码实现、offscreen、独立 Cocoa、前台、Windows frozen。
2. 如用户可见操作说明有变化，同步 hints/quickref 与必要的用户指南；不写“全平台修复”而遗漏 A17/A18，不为这项修复主动提升版本或改历史 dated spec 的历史版本。
3. 若实施发现新的反复模式、测试关闭遗漏 bug，执行 lessons require/status 流程；只提炼本次稳定经验，不复制已有投影 lesson，不编辑用户记忆库。
4. `git diff --check`，核对 scope 和此前无关 dirty 文件未被吸收；临时结果留 `.state/`，清理自己造成且不再需要的运行残留，不删除其他任务产物。
5. 更新本 Plan 状态时写实际证据，不提前勾选 PASS。只有后续明确要求 commit/push 才执行，并重新检查分支与精确 staging 范围。

## 10. 风险、停止条件与回退

| 风险 | 处理与验证 |
| --- | --- |
| 只禁用 canvas delta 导致合法 reference 修改失效 | T1 数值合同及 T2 独立画布/主窗口双路径测试必须同时保留 |
| 有效值再被 capture、preset 或 appearance 覆盖 | T3 覆盖全部显式提交/非提交入口，A07/A13 不可省略 |
| schema 与其他任务并发推进 | T0/T4 重核 schema 和 dirty diff，不硬覆盖到固定数字 |
| 窗格 origin/来源失配 | owner+复合 source+policy_owner 验证，fid remap 和 delete/duplicate 测试 |
| reference/有效范围溢出或 spin 舍入 | Spec §4.4 原精度、非有限拒绝、极值边界，不放松断言 |
| 锁定在中间帧触发循环或引用旧 View | 整组 prepare/settle，一次最终传播，空 pane 与绘制顺序测试 |
| 修改 shared capture 影响 FFT/FRF | 显式可选快照接缝，保留原 fallback，focused 非热图对照 |
| GUI→Batch 传入 anchor 数字而非有效数字 | T4 在桥接端展开，Batch 数学和独立 recipe 保持原义 |

遇到需要改变 reference 物理单位规则、删除公共 API、重做自动色阶、扩大其他分析模型或覆盖用户已有项目的情况，停止相应依赖步骤并先修订 Spec/Plan；独立已授权工作可继续。不得以删旧测试、放宽 ratchet 或取消合法补偿作为回退。

实现试验失败时只回退本任务精确改动；用户旧项目不被迁移写回，因此无需自动改写用户数据。按请求锚定方案不能推断修复此前已经保存的错误数字，此限制应保留在交付说明中。

## 11. 本次执行收口

- T0–T4：核心实现与已识别编辑/持久化/输出接缝完成；失败先行与最终门禁详见执行记录。
- T5：offscreen 定向 **935 passed, 1 skipped**；冻结源 Cocoa 显示窗口核心路径 **2 passed**。A17 全部原生交互组合、用户原项目和 A18 Windows frozen 尚未验收，不能勾选为完整发布通过。
- T6：Spec/Plan、验收矩阵、hints/quickref 和 lesson 已更新；没有 commit/push。
- 实施细化：逐 pane 输入从所属持久请求冻结，组事务结束前不投影 Inspector；减少同时持有的输入而保留顺序独立性。协调器位于 `ui/heatmap_color_coordinator.py`，纯策略位于中立 `heatmap_color_policy.py`。原生自动 Z 现在可复用已解析画面，相关旧强制重画断言已更新为状态/像素范围不变量。
