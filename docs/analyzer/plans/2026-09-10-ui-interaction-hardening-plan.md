# UI 与操作逻辑收口执行 Plan

日期：2026-09-10。状态：**计划完成，产品实施未开始**。

目标：关闭最近两天提交 review 的 F01–F11，补齐用户事件→状态→反馈/计算/保存的边界，并保留已有 Qt 视觉和运行语义。

架构：沿用 `AnalysisContext/AnalysisTimeRangeController`、`AnalysisViewState/analysis_view_bridge`、`preset_state`、Batch 中性规划与控件适用性 owner；不添加平行的状态框架或 renderer。

技术栈：项目 `.venv`、现有 Qt/pyqtgraph、pytest/pytest-qt、Cocoa 控件像素探针、Windows Full/Lite 独立验收。

依据：[Review](../reviews/2026-09-10-ui-interaction-two-day-review.md)、[Spec](../specs/2026-09-10-ui-interaction-hardening-spec.md)。审查基线 `29ab049c5932a5fb17b4478cb8fa8b0fb3cd6043`。本文中的代码动作均为未来执行项；没有借写计划修改产品。

## 1. 已知事实与执行约束

- 当前 review 在冻结 archive 上完成；2634 个跟踪文件在测试后与 HEAD 一致。
- 现有 UI focused：482 passed/8 failed；render+IO：368 passed/1 failed/3 skipped；boundary：80 passed/1 skipped；补充 lifecycle+merge：72 passed。详细失败归因见 review，不能把这些数当下一次代码的自动基线。
- 11 个 review-only 期望行为探针失败，覆盖已确认缺口。它们在 `.state/review-20260910/snapshot/tests/ui/test_review_20260910_gaps.py`，可辅助迁移，但正式测试不能依赖此路径。
- Cocoa 本轮三项为 2 pass/1 fail：原 offscreen 的标题/窗口两项通过，disabled active-blue 确认失败。完整前台与 Windows frozen 仍未跑。
- 用户已有 `presets.py`、`style.qss`、`hints.py`、`quickref.py` 等未提交修改。实施前必须重新检查；不能覆盖、还原或一起提交。
- 当前授权是 review 与文档。收到“按 plan 执行”等实施指令后才改产品；这是本次用户任务范围，非额外人为审批门槛。

## 2. 波次、依赖与所有权

建议默认顺序执行，避免同一 owner 被多个任务同时修改。

```text
T0 scope/fingerprint
  ├─ T1 输入/精度/即时提示 ─ T2 来源修订/多 pane 事务
  ├─ T3 目标基准/版本证据 ─ T4 View 同步/dirty
  ├─ T5 Batch 规划数量/默认/origin ─ T6 disabled/几何
  └─ T7 ZFD fixture 供应
             所有适用任务 ─ T8 集成、文案、平台与报告
```

T2/T4 都会触及 `_analysis_mixin.py`，即使未来用户授权 agents，也只能顺序交接或由同一个集成人维护。T5/T6 共享 Batch 文件，同样顺序进行。T7 的 fixtures/tests 可独立，但不额外跑全量。

只有用户明确要求 agents 时才拆分：每个 worker 有唯一文件集合、只跑其 focused/boundary tests；协调者拥有共享接线、schema 审查和唯一集成 gate。本计划本身不授权自动创建多个 agent。

## 3. T0：确认当前范围与建立可重现失败

需求：全部任务的前置证据。所有者：实施协调者。修改：仅 `.state/ui-interaction-hardening/` 本机记录。

- [ ] 读取当时 `AGENTS.md`、本 spec/plan；核对当前 HEAD、branch、`git status --short` 与相关差异。列出哪些 review finding 已被后来提交关闭。
- [ ] 查询现有 pytest 进程及 cwd；不与同 checkout 的 full gate 重叠。没有正在运行的全量任务时也不因此启动全套 baseline。
- [ ] 记录本次 HEAD、相关脏文件、运行环境、QPA、字体/屏幕/DPR。保留 review archive，不在原证据上改源码。
- [ ] 将需要修复的 review 探针迁到下述对应正式 owner 测试文件，使用真实用户事件和模型结果；保持原场景，不拷贝包装五个旧测试的诊断技巧到生产测试。
- [ ] 对每个准备改的 owner，先跑新增失败 case 及对应已有 focused case；只复现待修复项，不重跑本轮全部已绿套件。
- [ ] 如发现当前相关源码已有变化，先比较原因、更新 finding 状态，再进入对应任务；不能把 review 的旧失败直接套到新代码。

完成条件：每个待改任务有当前可复现 case 或明确的已修复证据、唯一 owner 和命令。没有代码变化时，docs-only 检查限引用/一致性/`git diff --check`，不跑 runtime gate。

## 4. T1：时间输入、精度与真实编辑提示

关闭：F01 的文本/勾选分支、F02、F06。需求：R01/R03/R04；验收 A01/A02/A05/A06。

修改文件：

- `mf4_analyzer/ui/inspector_sections/persistent_top.py`
- `mf4_analyzer/ui/main_window/analysis_time_range.py`
- `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`（只改既有接线）
- `tests/ui/test_analysis_time_range_intent.py`
- `tests/ui/test_analysis_time_range_confirm.py`

执行步骤：

- [ ] 先建立真实输入事件测试：Qt intermediate 文本 `-`，失焦后点击 Compute、直接点击 Compute、Return 三种顺序都不把旧值当新输入。
- [ ] 在 PersistentTop 的用户文本事件处记录原始文本与 edit revision；程序投影更新已投影基准并保持静默。无效输入有独立状态/通知，不从 fallback value 伪造 span。
- [ ] 保留有效 `range_edited(float,float)` 消费者；新增查询/invalid 通知经既有 window handler 进入 controller。禁止 top 导入 MainWindow/controller UI 实现。
- [ ] flush 对同一 revision 幂等；focus-out 与 compute flush 同时到达只提交一次。未编辑 focus-out 不成为草稿。
- [ ] `_enable_focused_analysis_time_range` 分开“无草稿”和“非法草稿”；非法时保留输入并回投未启用状态，只有显式 full 才放弃。
- [ ] `_capture_analysis_time_range` 只捕获真实尚未提交的编辑，不再用精度受限的 `spin.value()` 覆盖已启用模型。保留 source-derived 精确末点。
- [ ] 真实用户编辑完成后，取得最终 controller intent 再投影；处理 needs_review/errors/notes，不能拿 note_enabled 之前的旧 draft 返回值更新 enabled 文案。
- [ ] 验证取消、切 View、程序 apply/restore 的零脏/零任务语义，保留 time-domain 既有范围行为。

Focused：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_analysis_time_range_intent.py tests/ui/test_analysis_time_range_confirm.py tests/ui/test_analysis_context.py
```

边界：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`。如果只更改信号处理，不跑全 `tests/ui`。

退出条件：A01/A02/A05/A06 都从真实入口通过；10.00049 s 无编辑捕获不变，末样本保留由实际截取结果断言支撑；失焦与 Compute 没有重复任务。失败时只保留正在编辑的原意图，不使用 silent-full 兜底。

## 5. T2：来源修订与计算范围原子提交

依赖：T1。关闭：F01 的 coverage/多 pane 分支、F07；补全 F06 的来源复核。需求：R01/R02/R04；验收 A03/A04/A07/A08。

修改文件：`ui/main_window/analysis_time_range.py`、`analysis_context.py`、`_analysis_mixin.py`、`io/file_data.py`；相关测试为 `test_analysis_time_range_intent.py`、`test_analysis_time_range_confirm.py`、`test_frf_time_range_surface.py`、`tests/test_file_data_time_axis.py`。只有实际需要才改 source restore 调用者，不增加多处 MainWindow 状态写入。

- [ ] 先加 coverage 红测：0–10 对 20–30、部分越界、FFT 多来源不同覆盖、FRF 角色缺失与无交集。
- [ ] 加两 pane 事务测试：第二项无效、取消、对话框期间来源变化；第一次写入前冻结所有候选，任何拒绝都不改前面的 pane。
- [ ] 集中复用 `parse_span` 与 `enabled_covers_sources`，产出明确验证原因；draft 与 enabled 进入同一规则，不另建 UI 与 compute 两套判定。
- [ ] 范围确认仅提供有效 local；显式 full/cancel 按 spec 处理。提交后一次投影、一次已有 cache/effective facts 失效，不重复提交 job。
- [ ] 为 FileData 显式维护轴 revision，签名加入来源实例和轴实例/修订令牌。先检索全部 `time_array` 写点，当前集中于 FileData；新增代码不得在未通知 owner 的地方原位改轴。
- [ ] 签名保留 composite identity、排序无关和 FRF/Order 角色语义；覆盖同首尾/同点数替换。测试 fakes 显式提供事实，不靠真实 owner 缺字段时默默 False/0。
- [ ] 来源变化、View 删除、clear/open/reset 路径对称清理 draft/review/revision 引用；禁止持久化运行期令牌。
- [ ] 确认 Order 的 RPM 对齐仍走原 owner，FFT full overlay 不被错误压成交集；非均匀时间准备不改源数据。

Focused：T1 的两个 time-range 文件，加 `tests/ui/test_frf_time_range_surface.py`、`tests/ui/test_analysis_view_bridge.py`、`tests/test_file_data_time_axis.py`。最后一个是不同目录，按 repo conftest 规则保持 fixture 正常，不能用固定顺序掩盖异常。

边界：`tests/test_signal_no_gui_import.py`、`tests/test_native_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`。只有更改 job/result 路径时追加该 owner 的提交/取消测试。

退出条件：目标预验证原子性、角色与轴修订、生命周期均通过；不扫描大数组来处理每次文本编辑；失败反馈包含目标原因，不依赖 worker 才知道范围无效。

## 6. T3：目标预设基准与来源证据

关闭：F04/F05。需求：R05/R06；验收 A09–A12。

修改文件：`ui/inspector_sections/preset_state.py`、`presets.py`、`ui/analysis_view_state.py`、必要的四种 Contextual 既有参数 owner；测试 `test_preset_state.py`、`test_preset_axis_preservation.py`、`test_analysis_view_state.py`、`test_preset_bar_lifecycle.py`、`tests/test_project_io_analysis_views.py`。

- [ ] 加红测：手动轴与内置 target 不同，选择 keep 后实际轴保留、目标差异存在；同槽重应用可执行。
- [ ] 对四种 Contextual 建立 target resolver 与真实 apply 的等价证据：partial patch、别名、Auto NFFT、overlap、dB、RPM、轴 auto/range 和单位变化。
- [ ] 构造 before/target/applied 三个值；target 不经真实 UI 双重 apply 获取。仅抽取已证明需要共享的归一化规则。
- [ ] `_commit_loaded_slot` 接收目标比较快照与加载 source payload，不重新采合并后的控件值定义 target。成功后仍采 complete params 供 View 保存，两个表面不混用。
- [ ] baseline nested version 2 加载 source_payload；`preset_state` 和 `analysis_view_state` 分别做好语义/结构校验，保持依赖方向。
- [ ] v1 迁移保留原 snapshot 并把来源证据记为未知；不从当前全局槽填历史，也不猜测旧 keep 前 target。下一次用户成功加载建立 v2。
- [ ] 覆盖同名内容重写、改名、清空、恢复内置、切 View、复制 View、保存/重开和损坏 payload。两个 View 不共享可变对象。
- [ ] no-op 只在已知来源未变且规范 target/current 完全一致时发生；unknown 来源给可解释状态并允许重新加载。

Focused：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q tests/ui/test_preset_state.py tests/ui/test_preset_axis_preservation.py tests/ui/test_analysis_view_state.py tests/ui/test_preset_bar_lifecycle.py tests/test_project_io_analysis_views.py
```

边界：`tests/ui/test_import_boundaries.py`、`tests/test_packaging_imports.py`。不增加顶层项目版本或 APP_VERSION；确有新导入才更新隐藏导入测试。

退出条件：目标与最终应用结果的不同有直接断言；v1/v2 项目都可恢复，未知不伪装已知；没有因比较 helper 复制另一套参数 apply 逻辑。

## 7. T4：预设成功事务、View 立即同步与 dirty guard

依赖：T3；与 T2 共享 `_analysis_mixin.py`，顺序交接。关闭：F03。需求：R07；验收 A13/A14。

修改文件：`presets.py`、四种 Contextual 的既有信号面、`analysis_view_bridge.py`、`main_window/analysis_context.py`、`_analysis_mixin.py`、必要的 `window.py` 绑定。测试：`test_preset_bar_lifecycle.py`、`test_analysis_view_bridge.py`、`test_project_dirty_guard.py`。

- [ ] 先加真实 MainWindow 测试：保存后等参数跨槽加载必须 dirty；不先切 View，不手工调用 capture/mark_dirty 帮产品补线。
- [ ] 定义唯一成功事务事件（如 `preset_committed`），在 applied 与 baseline 均成功后发出。取消/失败、programmatic set_baseline 不发。
- [ ] 由已有 analysis owner 调用完整 bridge 同步 params+baseline，再一次 mark_user_mutation；不得让 PresetBar 引用 MainWindow 或直接操作 manager。
- [ ] 协调已有 params/display 差异信号顺序：防止半提交状态和两次 dirty；仍按实际差异做 effective-facts 失效，不用 baseline-only 事件强迫重算。
- [ ] 覆盖参数相同来源不同、参数不同、同槽已更新、完全一致 no-op、保存为新基准；明确只改全局槽而未加载时的行为。
- [ ] 覆盖 save→load→close cancel/save/discard，项目重开恢复，programmatic restore 零 dirty；真实关闭路径不通过提前捕获制造假通过。
- [ ] 故障注入验证 apply 失败回滚和程序错误可见；既有 `_collect_safe` 不能使事务空 payload 成功。

Focused：上述三个测试文件，加 `tests/test_project_io_analysis_views.py`。边界：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_qsettings_isolation.py`。

退出条件：A13/A14 从用户按钮到保存保护完整闭合；基准变化需要保存但不多算一次，View capture 不再承担唯一补救责任。

## 8. T5：Batch 规划数量、默认方法和引导 origin

关闭：F09/F11；调查引导通用 changed 信号。需求：R08/R11；验收 A15/A16/A19/A20。

修改文件：`ui/drawers/batch/sheet.py`、`analysis_panel.py`、`method_buttons.py`；中性 seam 在确有必要时调整 `batch.py` 的 metadata-only preview 与 `batch_grouping.py`，FRF 继续用 `batch_frf.py`。测试：`test_batch_method_buttons.py`、`test_batch_method_guidance.py`、`test_batch_review_regressions.py`、`test_batch_smoke.py`、`test_batch_toolbar.py`。

- [ ] 先迁移稀疏来源 2≠4 红测，再增加同名不同 fid、单文件多逻辑来源、common/available、custom-X 不可用、FRF 半配对/有效配对。
- [ ] 以现有 `BatchRunner.preview_outputs(..., source_channels=...)` 的 metadata-only 任务与 `group_render_tasks` 为语义基准。当前 preview 还包含输出校验和 `path.exists()`；卡片重绘不能反复触碰输出目录。
- [ ] 如无法直接复用计数，抽出已有 metadata-only render task/group 阶段供 preview 和 Sheet 共用，再让 preview 继续自己的冲突文件检查；不复制一套筛选/FRF 算法。
- [ ] 保留 `seed_source_channels()`；禁止卡片调用会 loader 的 `_expand_tasks` 默认路径、启动线程/DSP 或按显示 label 分组。
- [ ] 一次 pipeline recompute 得到数量事实，三种分组卡/底栏/preview 使用相同 snapshot；pending 和失败不填笛卡尔积数字。
- [ ] 规定关闭图片导出时文案为分组示意或 0 实际图片，区分 artifact count 与 image group count。
- [ ] 保留 time 新窗口默认；需要 FFT 的旧 smoke 显式 apply_method。lock case 记录 before，操作后比较状态、信号和完整输出快照；不只把字符串 fft 改成 time。
- [ ] 用真实异步回调验证 probe/偏好/preset restore 是否误计用户配置；先复现，若成立再以已有事务 guard 或明确 origin 修复。成功导入与取消分别覆盖。
- [ ] 同方法用户 activation 可以改变指导提示，但 methodChanged/业务 apply 只能在真实方法变更时发生；引导不增加 run eligibility。

Focused：上列五个 UI 文件，加 `tests/ui/test_batch_input_panel.py`、`test_batch_frf_pair_editor.py`、`test_batch_settings.py`。若触及中性规划，再跑 `tests/test_batch_source_integration.py`、`tests/test_batch_frf_pairing.py`、`tests/test_batch_grouping_display_name.py`。

边界：中性规划修改跑 `tests/test_batch_render_import_boundary.py`、`tests/test_signal_no_gui_import.py`；修改 runner 编排时必须加 `tests/test_batch_run_reporter.py`。单纯卡片文字投影不触发无关全量 renderer suite。

退出条件：A15/A16 数量、身份、pending 一致；默认/handoff 优先级有独立测试；loader、线程和磁盘冲突检查没有进入高频卡片重绘。

## 9. T6：禁用反馈及几何平台收口

依赖：T5 的 Batch 文件交接。关闭：F10；区分 offscreen/Cocoa 几何前提。需求：R09/R12；验收 A17/A18/A23。

修改文件：`analysis_panel.py`、`method_buttons.py`、必要的 `ui_kit/control_style.py` 和 scoped QSS；测试 `test_batch_method_buttons.py`、`test_batch_review_regressions.py`、`test_batch_output_panel.py`、`tests/ui_kit/test_segmented_choice.py`。

- [ ] 先固定自绘预设卡 disabled active-blue 像素红测，扩展 grouping 卡标题/圆点/公式区域；显式 checkable/checked，避免测试实际没画选中态。
- [ ] 自绘颜色读取 effective enabled 与共享 palette/tokens；保留 checked 的可辨识禁用表现，不清掉用户参数。
- [ ] 在真实 BatchSheet 上覆盖 parent lock，不只对子按钮 setEnabled(False)；鼠标、键盘、滚轮零变更/零信号。
- [ ] preview/run 成功、失败、取消后恢复应适用部分；图片关闭、Auto、Linear 等仍保持业务禁用和原值。
- [ ] 单分析 dB 入口先列动作语义与有效参数；管理目录合理可用时保持，不把未证问题当批量禁用理由。
- [ ] 修正窄列/1080 测试的已知字体与可用屏幕前提；独立保留小屏幕夹取/底栏可达测试，不删除失败断言或关闭生产屏幕保护。
- [ ] 读取用户已有差异圆点/进度标签修复，独立核对是否已解决对应像素问题；需要整合时仅修改本任务必要 hunk，不重写已有实现。

Focused：上述测试加 `tests/ui/test_batch_first_show_geometry.py`、`tests/ui/test_batch_compact_contract.py`、`tests/ui_kit/test_dialog_geometry.py`。边界：`tests/ui_kit/test_qss_border_shorthand.py`、`tests/ui/test_no_lambda_signal_connections.py`。

原生 gate：Cocoa 下以生产 QSS、真实字体、DPR 截图验证选中/未选中×直接/祖先禁用与恢复；记录颜色区域和像素，不只断言属性。Windows 至少覆盖 native 与 Fusion 的相同状态；未有机器时标 UNKNOWN。

退出条件：F10 有真实 Cocoa 绿色像素证据，交互锁/保值通过；不会以 offscreen 字体预算问题指挥无依据的生产字号调整。

## 10. T7：ZFD 干净 checkout 与真实 corpus 门禁

关闭：F08。需求：R10；验收 A21/A22。可独立于 UI 任务。

修改文件：`tests/test_zfd_format.py`、既有 ZFD fixture helper；新增受控小型 manifest（建议 `tests/fixtures/zfd/corpus_manifest.json`）、仅服务该 corpus 的环境变量读取/helper；必要时新增 `tests/fixtures/zfd/README.md` 说明样本供应。固定使用 `TRACELAB_ZFD_CORPUS_ROOT` 和 `TRACELAB_REQUIRE_ZFD_CORPUS=1`，在该测试模块/fixture helper 读取，不修改 root conftest。

- [ ] 先在不含 `.state`/testdoc 本机样本的干净 archive 复现现有失败，保存命令与退出码。
- [ ] 实现上述 corpus root/必需模式；普通 suite 无 corpus 时只跳过可选真实样本 case，合成/解析边界仍运行。必需模式缺 manifest/文件/hash 不符均 fail。
- [ ] 不把本机 `samples.json` 直接复制进 tests 当无来源事实。为六个已有样本登记稳定 ID、hash、来源许可边界与受控预期；不默认提交客户二进制。
- [ ] 复用既有合成 builder，补完整数组和值/时间断言：长记录、边界点、dtype、单位、元数据错误、截断、计数不足、非有限/无效 dt。
- [ ] 元数据 A4 与值证据分开；支持 profile 不变，纯 parser 正确性与两个消费者 parity 分开。
- [ ] 在普通干净 checkout 与带六个本机样本的 corpus 模式分别跑。若原始长客户文件仍缺失，结果明确 UNKNOWN，不延伸产品支持声明。

Focused：`tests/test_zfd_format.py`、`tests/test_source_adapters.py`、`tests/test_batch_source_integration.py`、`tests/test_io_load_notices.py`。如只改 fixture 供应，无须重跑已绿的整套 Qt renderer。

边界：保持 corpus helper 的本模块范围，不改 root conftest。如实现实际触及共享 collection/fixture，才追加 `tests/test_conftest_autouse_scope.py` 与 `tests/ui/test_qsettings_isolation.py`。若 parser 未改，不追加无关 IO 重构测试。

退出条件：默认 checkout gate 自包含且真实样本供应契约可验证；显式 corpus gate 不能通过 skip 伪造绿色；数值测试有独立 oracle。

## 11. T8：集成、帮助与最终验收报告

依赖：T1–T7 的适用任务完成。需求：R12，检查所有 R/A 对应关系。所有者：唯一实施协调者。

文档/帮助文件：`mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`；新增实际执行报告 `docs/analyzer/reviews/2026-09-10-ui-interaction-hardening-execution.md`。本次不先创建空“已完成”报告；实施完成时写实际 snapshot/命令/平台结果。

- [ ] 同步非法输入恢复、目标基准、槽位未知/已更新、数量待确定和禁用原因；保持现有控件词汇，不把 schema、revision 等实现名放到用户提示。
- [ ] 只检查本轮实际修改/新增的 broad catch；分别注入 expected data error、Qt destroyed wrapper、programming error。证明可恢复错误有反馈、意外错误有上下文，避免日志风暴。
- [ ] 收齐各任务 focused/boundary 结果。没有后续相关改动的绿测直接复用；有共享 owner 后续变化时，说明影响并补跑该边界，不重复整个历史集合。
- [ ] 在最终稳定源快照跑一次下列必要集成范围；执行前后记录 HEAD/相关 dirty fingerprint，过程中相关源变化则标 UNVERIFIED。
- [ ] 完成 A23 Cocoa/前台矩阵，必要 Windows native/frozen 独立验收。用几何/像素自动比较，少量关键场景人工核对，不让用户逐张找差异。
- [ ] 更新 R01–R12、A01–A24、F01–F11 状态，每项关联命令/断言/截图或 UNKNOWN 原因。待证横展必须写“复现并修复”或“未复现及检查边界”，不可默默消失。
- [ ] `git diff --check`、changed-file scope、测试文件引用、旧 schema/public imports 与 hints/quickref 一致性检查。
- [ ] 检查 lesson 状态。若出现已有规则未覆盖的重复模式，按项目流程写一条精简 lesson；已有用户脏 index 先协调，不把本次文档当记忆更新指令。

建议集成范围（去重后一次执行，已有最终同快照结果可以复用）：

1. 时间范围 intent/confirm + analysis bridge/state + project dirty guard + project IO analysis views。
2. 预设 state/axis preservation/lifecycle；基准像素表面若改动再加 difference render。
3. Batch smoke/review regressions/toolbar/method guidance/output panel/FRF pair editor；规划变化对应 source/grouping/FRF tests。
4. 适用的 import、backref、state ownership、lambda、QSS、QSettings/conftest 边界；未改 canvas 时不为此重跑 paint 性能大集。
5. 普通 ZFD gate 与独立 corpus gate；不混合统计。
6. `tests/test_help_content.py`；只有发布/版本改动时再做对应 release/package gate。

这轮是有范围的逻辑修复，**不默认要求全套基线或全套 UI**。若用户随后要求发布/合并验收、发现跨模块顺序/teardown 污染，或实现确已扩大为跨边界重构，再说明理由执行 full gate：唯一 owner，先 `--ignore=tests/acquisition_ui`，完成后新进程单跑 `tests/acquisition_ui`，不并发。异常退出/timeout/源快照漂移均是 UNVERIFIED。

### 原生验收矩阵

| 场景 | 方法/平台范围 | 要保存的证据 |
| --- | --- | --- |
| 时间编辑→Compute→切 View→保存重开 | FFT、FFT-vs-Time、Order、FRF；Cocoa 前台 | 精确模型区间、任务次数、状态提示、cancel 前后对比 |
| 预设 keep/reapply/等参数跨槽→关闭保护 | 四种单分析；Cocoa | target/current/baseline 对应、提示、dirty guard，两个 View 隔离 |
| Batch 首显、紧凑宽度和小屏幕 | 五方法；至少 1080×760、较大窗口、较小 available screen | post-show frame/client geometry、首帧/settle 后差异、底栏可达 |
| disabled 与恢复 | 直接/祖先锁、选中/未选中、preview/run 三种终态 | 生产 QSS 像素、控件值/信号/适用性快照 |
| 长轴标签/ColorBar/hover 屏幕边缘 | GUI 与 Batch 代表导出 | tick draw specs + 字形区域像素、同源 artifact，不只 parity |
| Windows Full/Lite frozen | 新构建包，两种配置分别操作 | 包版本、启动、上述关键交互；未跑标 UNKNOWN |

## 12. 风险控制、回退与交付标准

| 风险 | 控制措施 | 失败时处理 |
| --- | --- | --- |
| Qt 在 slot 前自动解释文本 | 在真实 textEdited/事件时捕获原意图，多事件顺序测试 | 保留 invalid，不退到旧值计算 |
| 预设 target resolver 与实际 apply 漂移 | 四种 Contextual 的部分补丁/别名/单位等价证据 | 限缩到 owner 共享规则，不另加字典补丁 |
| 事务期间旧 paramsChanged 提前标脏 | 现有 apply guard + 唯一成功提交边界 | 回滚 before/baseline，禁止双信号假完成 |
| schema v1 没有历史 source payload | 明确 unknown，成功用户重载才建立 v2 | 不猜历史，不阻断旧项目读取 |
| 数量投影引入 UI 卡顿 | metadata-only 规划、复用一次事实、禁止 loader/磁盘逐帧检查 | 返回 pending/待确定而非执行昂贵计算 |
| 运行解锁覆盖业务禁用 | 重新合成适用性，保存用户值 | 仅恢复允许部分，生命周期测试保护 |
| 同时工作的用户改动被覆盖 | 初始/最终 diff 范围复查，共享文件逐 hunk 协调 | 不回滚用户改动；必要时隔离任务工作区 |

后续提交应按可验证的责任边界组织：时间范围、预设、Batch、ZFD 测试供应可各自成组；schema+消费者和事件+接线不能拆成单独无法工作的提交。是否 commit/push 按届时用户指令，不在当前文档任务中执行。

完成标准：所有确认 P1 已修复且有真实入口测试；F04–F11 有对应当前行为或明确平台状态；spec 的未验证平台条目保留 UNKNOWN。最终报告同时写变更、验证和剩余门禁，不能以“测试数量很多”宣称整体正确。
