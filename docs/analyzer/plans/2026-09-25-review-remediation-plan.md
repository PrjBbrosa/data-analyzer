# 最近两天提交复审修复执行计划

- 日期：2026-09-25。
- 状态：**T1–T8 已有实现与聚焦证据；全量中断；新增 T10–T14（测试效率与失败治理）待实施；Windows 包和 native 绘制未验收**。历史实施记录见第 13 节，新增计划见第 14 节。配套 [spec](../specs/2026-09-25-review-remediation-spec.md)。
- 对应问题：F1–F7、V1/V2，以及尚未归因的全量失败；验收编号 A1–A12 以 spec 为准。
- Review 终点与编写时 HEAD：`f83eee615963c721b5c4b5d48a5702d4ec731cfb`。历史 review 使用隔离快照，不代表当前 dirty tree 已验收。

## 1. 实施原则与依赖

在 owning module 做小修复，先将确定性复现移入正式测试，再修代码；不运行通用的 pre-change full-suite baseline。不得修改 `CLAUDE.md/.claude`、吸收无关 dirty、扩大 ratchet 白名单、以 xfail/固定顺序/sleep 掩盖失败。

默认实施顺序：**T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9**。F1 先修；T2 消费 T1 的时间身份/元数据；T3/T4 与 native launcher 在同一入口协调；T2 与 T6 都触及 batch.py，必须由同一 owner 集成，不能并行改同文件。

上述是原修复顺序。针对已中断的全量，当前后续顺序为 **T10 证据与有界入口 → T11 fixture 引用修复 → T12 失败归因与修复 → T13 性能对照及按需分组 → T14 稳定集成 → 完成 T9 平台/交付**。T10 不跑全量基线；本次仅修订文档，不启动这些实施步骤。

若后续明确采用 agents，分为 IO+Batch+Replay、Startup、FRF+Slice 三条边界清楚的 lane，父协调者持有共享合同、hints/quickref、T8 与 T9；worker 只跑 focused/boundary，禁止各自跑全套。本次写文档不启动实现 agents。

| 任务 | 问题 / 验收 | 主要责任文件 |
| --- | --- | --- |
| T1 | F1 / A1 | io/loader.py、source_adapters.py、file_data.py；Replay 时间读取接缝 |
| T2 | F3 / A3 | batch.py、acquisition_capture/backends.py、acquisition_ui/replay_tab.py；既有结果展示 |
| T3 | F2 / A2 | startup_feedback.py、startup_handover.py；实施时存在的其他 feedback backend |
| T4 | F6 / A6 | startup_splash_child.py、ui/startup_splash.py 的偏好接线 |
| T5 | F4 / A4 | ui/pg_canvas/frf_canvas.py、ultraview_capture_coordinator.py 的既有合同 |
| T6 | F5 / A5 | batch.py:_preview_frf_outputs |
| T7 | F7 / A7 | ui/pg_canvas/slice_panel.py |
| T8 | V1/V2 / A8/A9 | 过期常量测试、splash 像素测试及其已有 helper |
| T9 | 全部 | 集成、用户说明、平台验收与最终记录 |
| T10 | A10 | 失败证据台账、现有 run_test_gate.py / select_test_gate.py 入口 |
| T11 | A11 | tests/ui/conftest.py、test_qt_fixture_lifecycle.py |
| T12 | A10 | 按真实失败分配测试 owner；产品缺陷回到 owning module |
| T13 | A12 | runner / selector 与必要的分组清单、性能证据 |
| T14 | A10–A12 | 父协调者唯一稳定集成验收 |

文件前缀默认为 `mf4_analyzer/`；没有列出的文件只有在真实调用链证明必要后才能纳入，并在任务记录注明原因。

## 2. T0 — 锁定当前状态与回归入口

1. 记录 `git rev-parse HEAD`、`git status --short`、相关 tracked/untracked diff 指纹，确认哪些已由并行任务修复。用符号定位代替历史行号。
2. 重点核对正在开发的 `startup_native_feedback.py/startup_launch_policy.py/startup_visual_contract.py`、native launcher、app/splash/ChartStack 修改。区分已合并、未完成和已占用 owner；不得拿 `f83` 文件覆盖当前实现。
3. 阅读 spec 全文，复核 F1–F7 的现有入口。历史 `.state/review-20260925-*-probe.py` 仅作本机参考；即使 `.state` 已删除，也能按 spec 的样本、时序和结果重新建立正式测试。
4. 按后续每项 focused 文件先重现必要失败。F5 复用现有三个失败用例；不重复造等价测试。V1/V2 先区分测试缺陷与产品行为，不能将错误测试作为产品修复目标。
5. 将任务状态和证据路径记录到 `.state/review-remediation-progress.md`（实施时创建）。初始 A1–A9 均为 NOT RUN，而非沿用历史通过计数。

**T0 验证：** 快照/dirty 边界和测试入口可用，失败原因对应 review。此任务本身不需要全量运行；无关已知失败另列，不触发广泛清理。

## 3. T1 — 先保护 MF4 的时间身份（F1，P1）

### 3.1 Red tests

在 `tests/_helpers/mf4_factory.py` 复用真实 MF4 factory，向 `tests/test_mf4_loader.py`、`tests/test_source_adapters.py`、`tests/test_file_data_time_axis.py` 增加必要合同：

- Time+sig：时间 `[0,.1,.2,.3]`、Time 信号 `[10,20,30,40]`；断言 fs=10、时间原值、两路信号保真。
- 单 Time、t、zeit、普通 time；physical master 名称不同但仍排除；同名不同 occurrence、信号本来就叫 `Time [g:c]`、不同通道枚举顺序的稳定消歧。
- probe、load、descriptor、FileData.get_signal_channels 完全一致。已有跳过/无交集/重复时刻/倒退/单点规则继续通过。
- 旧无显式时间元数据 FileData 的 CSV/Excel 对照；非法 time_column 明确失败，禁止悄悄回退到信号或 1 kHz。

### 3.2 最小实现

按 spec D1 实现公共 IO 命名映射和精确 time_column。重用既有 renamed_channels/physical_occurrence，不增加 MainWindow channel-name 状态。保持 loader 三元组签名及无碰撞名字。

同步 Replay 的时间/信号读取使用该明确身份；此步仅保证数据选择，诊断 UI 在 T2 完成。追踪旧项目/Batch preset 的匹配，保留无歧义兼容，歧义走缺失反馈。

### 3.3 Gates 与出口

- **Focused：** `tests/test_mf4_loader.py`、`tests/test_source_adapters.py`、`tests/test_file_data_time_axis.py`、`tests/test_acquisition_capture_backends.py`。
- **UI/持久化：** `tests/ui/test_mf4_import_flow.py`；在 `tests/ui/test_project_session.py` 中只运行/新增本任务的命名、保存后重开相关用例，不因触及元数据运行全 UI。
- **Boundary：** `tests/test_startup_import_boundary.py`、`tests/test_native_import_boundaries.py`、`tests/test_signal_no_gui_import.py`。
- **A1 出口：** 留存真实 fixture 的轴/fs/信号/映射结果，至少一条 GUI 可选择 + 项目重开 + Batch 或 Replay 的真实消费链。任何错误时间轴或歧义自动绑定仍存在则阻断集成。

## 4. T2 — 把源诊断送到所有消费端（F3）

依赖 T1。和 T6 共用 Batch owner。

### 4.1 Red tests 与实现

1. 真实 MF4 fixture：ref=0..4 秒，late=2..3 秒；保存加载端 warnings/mf4_alignment。
2. 在 `tests/test_batch_runner.py` / `tests/test_batch_manifest.py` 验证 memory/disk 两路径，item、manifest 的警告与 provenance 都存在；数据产物仍保留原 schema 和数值。用 data-only 运行覆盖没有 renderer 的链路。
3. 按 spec D3 接入已有 source/result/reporter，不在每个计算方法各追加一份逻辑。复核 time/fft/fft_time/order_time/frf，分组成员、多源 RPM、FRF input/output 的源身份；通过共享入口的参数化测试加有风险分支实测完成横展。
4. 验证 retry/resume、manifest 关闭、loaded 后失败、load 前取消/跳过的规则；不额外发 progress、不静默吞编程错误。
5. ReplaySource 添加默认字段；`source_from_mf4` 带出源诊断，`ReplayTab.load_file` 在 Play 可用前更新只读警告区。正常/有警告/换源/加载失败各有真实 backend 或 Qt 测试。加载失败若保留旧 source，必须同时保留旧诊断，不能发生身份错配。
6. `ui/hints.py`、`ui/quickref.py` 加入相关反馈说明；不新增快捷键。采用当前版本的文本结构，避免改写无关提示。

### 4.2 Gates 与出口

- **Focused backend：** `tests/test_batch_runner.py` 的相关 source/分组/FRF/Order 用例、`tests/test_batch_manifest.py`、`tests/test_acquisition_capture_backends.py`。
- **Focused UI：** `tests/ui/test_batch_result_details.py`、`tests/acquisition_ui/test_replay_tab.py`。Replay UI 在独立进程运行；不要与 Analyzer 主 UI 混在一个 pytest 进程。
- **Boundary：** `tests/test_batch_run_reporter.py`、`tests/test_batch_render_import_boundary.py`、`tests/test_native_import_boundaries.py`、`tests/ui/test_import_boundaries.py`。新增 QSS 才运行 `tests/ui_kit/test_qss_border_shorthand.py`；信号接线改动运行 `tests/ui/test_no_lambda_signal_connections.py`。
- **A3 出口：** 真实导出结果/manifest 可追溯 source；Replay 警告区实际渲染并检查最小宽度、长中文、换源清理，结果包含正确填充提示。只验证 payload 字段不算 UI 验收。

## 5. T3 — 修复晚订阅 reveal（F2）

### 5.1 Red tests

在 `tests/test_startup_feedback.py` 建立锁/事件控制的 deterministic 交错，而非随机重复撞竞态。覆盖 spec D2 的六类顺序，尤其 hidden→add_listener→finish→EOF；重复订阅、不同 session、移除 listener、close 后注册也要覆盖。

在 `tests/test_startup_splash_integration.py` 用真实 socket/child 验证问题序列，assert window show 次数、GUI 线程、hidden 和自然 exit 0。控制同步屏障即可稳定复现，不用无限等待或长 sleep 证明“最终可能成功”。

### 5.2 实现与 native 接缝

在 feedback 已有锁中保存可重放 terminal payload；注册与通知对列表/缓存原子操作，callback 锁外调用。Handover 保持 show/closed/session guard，不另开 timer 兜底状态。

T0 若发现 native feedback 已整合，给它运行同一 listener 合同测试并同步修复；其已有 `tests/test_startup_native_feedback.py` 仅在实施快照真实存在时纳入。若 native owner 正在并行修改，先通过共享接口和待合并 patch 协调，不覆盖文件，也不能关闭 A2 的全局状态。

### 5.3 Gates 与出口

- **Focused：** `tests/test_startup_feedback.py`、`tests/test_startup_splash_integration.py`、`tests/test_startup_splash_child.py`、`tests/test_startup_entrypoints.py`。
- **Boundary：** `tests/test_startup_import_boundary.py`、`tests/test_startup_timing.py`，以及整合后实际存在的 native feedback 合同测试。
- **A2 出口：** early/normal/fallback 均 eligible show 一次、close 后零次，worker 不直接操作 QWidget；真实 child 自然结束，无 test cleanup 或 terminate 冒充成功。平台 handover 连续帧在 T9 验收。

## 6. T4 — 保留跨平台减少动态偏好（F6）

先在真实 StartupSplash 上注入 reduce-motion=True，按 child 初始化次序执行，验证它不会被非 Windows 默认 False 改写。对照 False、检测失败、Windows、mac auto/off 和显式 on。

按 spec D6 保留单一 detector，优先删除多余覆盖而非造新全局配置。检验动画 timer/阶段文本更新与 finish/hidden，不能仅断言一个布尔字段。

- **Focused：** `tests/ui/test_startup_splash.py`、`tests/test_startup_splash_child.py`、`tests/test_startup_splash_integration.py`。
- **Boundary：** `tests/test_startup_import_boundary.py`。只有新增/迁移 import seam 才加 `tests/test_packaging_imports.py`。
- **A6 出口：** 注入偏好与真实 child 行为一致；mac 显式 on 前台验证静态/减少动态仍显示进度且能交接。native backend 若已整合，单列其平台证据，不用 Python UI 测试替代。

## 7. T5 — 修复 FRF 到 UltraView 的范围接线（F4）

1. 将 review 的真实 MainWindow+FRF 探针迁入 `tests/ui/test_ultraview_capture.py`：第一次 Ctrl+滚轮后真实截图入库，再次缩放后旧 record 必须失效，focus-inspect 最终发布新像素。
2. 在 `tests/ui/test_frf_canvas.py` 保护 `get_visible_xlim/get_visible_ylims` 合同：Hz 在线性/log 下正确，三个 Y 键稳定，空 result 安全；保持现有 public getters。
3. 补齐真实平移、Shift/Y 缩放、Home、Inspector 轴编辑的信号链，先检查既有接线，避免重复连接。对应 pane/View 的同范围 no-op、普通 paint、cross-view restore 和隐藏源延后截图要有对照。
4. 实现以 FRF owner 只读接口适配为主；coordinator 如无需改动则不动，禁止全局每信号无条件 bump 或强制截图。

- **Focused：** `tests/ui/test_frf_canvas.py`、`tests/ui/test_ultraview_capture.py`、`tests/ui/test_ultraview_mode_integration.py`；涉及 split 恢复时运行 `tests/ui/test_analysis_multiview_integration.py` 中相关用例。
- **Boundary：** `tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`；触及 backref 合同时加 `tests/ui/test_pg_canvas_backref_invariants.py`。
- **A4 出口：** 第二次/后续 X 与 Y 操作之后新图片可见，而相同范围没有额外抓图。实际截图内容和 source/view 绑定都验证，不能只看 revision 数字。

## 8. T6 — 修复 FRF Batch 预览（F5）

先运行已有三个失败测试：

```text
tests/test_batch_runner.py::test_batch_frf_group_preview_and_run_share_identity_members_and_png_bytes
tests/test_batch_runner.py::test_batch_frf_preview_is_metadata_only_and_estimated
tests/test_batch_runner.py::test_batch_frf_representative_preview_loads_only_selected_group_and_computes
```

在 `_preview_frf_outputs` 从当前 preset.outputs 调用既有 `_requested_output_settings`，再传入 grouping。与 `_frf_render_tasks_from_plan` 和 Run 的合同核对，禁止从 UI 记忆值补一个不同的快照。

已有测试不足时，补 metadata-only forbidden-load sentinel、合法 grouping/output 组合。对 unsupported 配置保持既有错误，而非无条件 fallback 到默认配置。

- **Focused：** 上述三项、`tests/ui/test_batch_preview_dialog.py` 的 FRF/代表输出场景；实施后跑 `tests/test_batch_runner.py`，T2 若同一稳定版本已经完整通过则复用结果，不重复运行。
- **Boundary：** `tests/test_batch_run_reporter.py`，若只修 planning、T2 之后该文件未变则复用同 snapshot 结果；`tests/test_batch_render_import_boundary.py` 保证 metadata-only 没导入 renderer。
- **A5 出口：** 真实 UI 预览能打开，成员/identity/数量/PNG 与 Run 一致。不能只证明 NameError 消失。

## 9. T7 — 切片方向后的 quality settle（F7）

在 `tests/ui/test_slice_panel.py` / `tests/ui/test_pg_heatmap_canvas.py` 中用 20,000×4 alternating/constant matrix 重现 high-ink→cheap，并反向验证 cheap→high-ink 先降 AA 再判定。

按 spec D7，在方向真实变化时使旧 quality decision 失效，更新最终数据/几何后调用既有离散结算。覆盖相同方向 no-op、hidden/clear/destroy、transition hold/cancel、backstop 不跨签名误伤；不要改 threshold 或 150 ms interval。

- **Focused：** `tests/ui/test_slice_panel.py`、`tests/ui/test_pg_heatmap_canvas.py`、`tests/ui/test_discrete_quality_hold.py`。
- **Boundary：** `tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_pg_timedomain_canvas.py` 中既有 `TestDiscreteSettle` 与 paint-timer backstop；保持有关 quiet timer 的断言。
- **A7 出口：** 两方向按新曲线正确测量、停止输入后廉价切片恢复平滑、昂贵切片受限；Cocoa/Windows 实际像素和曲线外观在 T9 验收，不用 offscreen 计时宣称性能改善。

## 10. T8 — 修正测试自身的合同（V1/V2）

### V1

读取 `tests/test_guideline_hardening_task7_c_constants.py` 与当前 `_auto_db_line_limits` 调用链。以当前 `signal/display_ranges.py:line_amplitude_limits` 合同替代对 `_SLICE_MAX_SPAN_DB` 的死引用检查；绝对范围预期留给 numeric owner，Batch 检查委托、mask 和既有空输入 fallback。

**Focused：** `tests/test_guideline_hardening_task7_c_constants.py`、`tests/signal/test_display_ranges.py`；修改了共享 dB helper 才扩到 `tests/ui/test_auto_color_span.py` 和相关 Batch parity。本任务原则上只修改测试，不为修过期断言改数值实现。

### V2

峰顶和 outer-shadow 用图像真实 DPR 换算坐标。widget 坐标、图像像素、边缘抗锯齿容差分别说明，容差不能大到漏掉真正的 clipping/不透明角落。

**Focused：** `tests/ui/test_startup_splash.py` 的相关像素测试，独立进程 DPR=1/2/受支持分数比例，再跑其与 `tests/test_startup_entrypoints.py` 的两种收集顺序。不通过测试顺序规避 Qt startup 属性；有属性副作用的 probe 保持子进程隔离。

**Boundary：** `tests/test_conftest_autouse_scope.py`、`tests/ui/test_qsettings_isolation.py`。真实 UI fixtures 保持 ownership、deferred delete、QSettings 隔离，不能改根 conftest 的用途。

**A8/A9 出口：** 错误 AST gate 不再阻断，正确数值仍被保护；多个 DPR 和运行入口一致，像素测试仍能拦住真实外观回归。

## 11. T9 — 集成、原生验收与交付

### 11.1 文档与状态同步

更新 A1–A12 的证据表：implementation、focused/boundary、integration、Cocoa、Windows frozen 分列。必要用户文案同步 hints/quickref；本次没有发布版本变更，不扩展到版本 bump 或重写历史 help 基线。

各任务完成后只保留必要改动；`git diff --check` 和 changed-file review。检查 lesson 状态，只有新重复失败模式才按项目制度记录；不得替并行 page-switch/launcher 任务清除其 requirement。

### 11.2 唯一全量集成 gate

**理由：** 本计划联合修改 IO 身份、Batch/Replay 数据反馈、线程交接和 Qt 缓存生命周期，横跨多个 ownership 与进程边界，因此在所有 focused/boundary 完成后的稳定集成点做一次全量检查；不在 T0 或各 worker 重复做。

父协调者执行前检查已有 pytest 进程及 cwd，等待/复用同 snapshot 的权威运行，禁止重叠全套。记录 HEAD、dirty 文件范围和内容指纹；结束再记录，相关源码变化则结果记 UNVERIFIED。

**2026-09-25 修订：先完成 T10–T13，再进入本 gate。禁止复用直接调用 pytest 的无界 shell。** 使用已有 watchdog，两个阶段仍为主集、acquisition_ui 的顺序独立进程：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python scripts/run_test_gate.py --full-suite --soft-timeout-seconds 900 --hard-timeout-seconds 1500
```

上述为现有两阶段入口，超时按 phase 生效，是资源上限，不是承诺 25 分钟通过。T13 若证明主集必须进一步分组，先完成覆盖清单和 runner 验证，再以顺序 `--phase` 清单替换本入口；不能把分组后局部通过称为全量。超时/崩溃后不传 `--continue-after-unverified` 盲目推进；先诊断，不单纯提高超时。即时失败记录必须保留。

不硬编码历史 pass 数。异常退出、segfault、timeout 都是 UNVERIFIED；失败逐一归因，禁止从此前部分通过数量推导整体通过。新修复改变相关源码后才有理由重跑对应 gate，重跑全套前记录原因。

### 11.3 平台验收矩阵

| 环境 | 必做场景 | 通过依据 |
| --- | --- | --- |
| macOS Cocoa 前台 | MF4 命名通道选择；FRF 连续 X/Y 缩放→UltraView 检视；双方向切片；Replay 长警告换源；显式 splash + reduce-motion | 实际点击/滚轮、范围与像素、无残留/遮挡，QSettings 隔离 |
| Windows fresh Full/Lite frozen | 启动正常/提前关 splash/降级；MF4 时间轴和 Batch 警告/FRF 预览；Replay 仅在包含采集功能的包中；多 DPI | 包版本/commit/backend 可追溯，实际导出结果，连续帧证明 handover 顺序 |
| 已整合的 Modular/native launcher | 当前配置实际 backend 同一 reveal/reduce-motion 合同，启动关闭及 fallback | 真实包和进程证据，源码 mock 不替代 |

平台不可用则记录具体未执行项，保留待验收状态。不能因为可自动化 gate 通过就关闭 native appearance；也不能把未证实 QuickRef 圆角线索混入必修清单。

### 11.4 最终交付与停止规则

1. 输出每个 F/V 的修复、回归证据、横展检查和仍开放的平台 gate。
2. 同步 plan 的任务状态和实际执行偏差；没有证据的行仍写 NOT RUN/UNVERIFIED。
3. 不为“更彻底”无界增加审查、全套复跑或重构。全量失败进入 T12 台账，已证实的测试缺陷属于新增修复范围；真实产品缺陷记录影响、owner 与最小回归，未关闭时保留阻断，不用“无关遗留”充当通过豁免。
4. 未获后续请求不 commit/push/release。F1 未关闭时不将本计划成果作为可发布的数据正确性修复。

## 12. 本次文档交付的验证

本轮只新增 spec/plan，不修改产品、测试或运行配置。检查覆盖 F1–F7/V1/V2、A1–A9 映射、owner/依赖、现有文件引用、dirty-worktree 接缝及 `git diff --check`。无需跑 runtime pytest；上文所有执行和验收步骤仍待实施，历史 review 输出没有被计作修复后的结果。

第 12 节只描述写文档那一轮。之后的实施和验收以第 13 节为准。

## 13. 执行记录（2026-09-25）

实施 HEAD：`cc8d1733be13db59376a7a2a3bb09f435e66263c`。没有 commit / push / release。`git diff --check` 通过。`scripts/lessons/check.py --status` 为 `lesson_required: False`，没有新 lesson，也没有清掉其他任务的 requirement。

四条车道同时改互不重叠的文件：IO+Batch+Replay（T1→T2→T6）、Startup（T3→T4）、FRF+Slice（T5→T7）、父协调者（T8、hints/quickref、本记录）。既有未提交的 native launcher、collapsible、Windows 打包脚本没有被回滚，也不算本计划的验收对象。

### 13.1 偏差

- `StartupHandover` 未改。单次显示仍靠原有 `_show_called`、session、close 和已销毁 Qt 对象。
- 减少动态只删掉 child 里 Windows-only 的第二次 `set_reduced_motion`。`ui/startup_splash.py` 里已有的跨平台检测器保持原样。`launcher_win32.cc` 的绘制路径没有改。
- 旧工程里存成裸 `Time` 的通道，GUI 重开仍走现有「名字对不上就不勾选」。Batch 预设对唯一旧名会映到 `Time [g:c]`。没有把旧的错误轴范围说成已经自动纠正。
- 滚动提示受 18 个全角预算限制，footer 文案是「回放对齐可能含非原始值」。完整说明在 quickref「回放对齐提示」，以及批处理「运行警告」里补上的加载对齐句。
- 全量套件在约 75% 被要求停掉，不重跑。

### 13.2 证据

| ID | 实现 | 聚焦 / 边界 | 集成全量 | Cocoa | Windows frozen |
| --- | --- | --- | --- | --- | --- |
| A1 | 显式 `time_column`，只重命名恰好占用 `Time` 的信号 | loader、adapters、file data、导入、项目重开、Replay 读取通过 | INTERRUPTED | 通道可选 + 项目重开 通过 | NOT RUN |
| A2 | Python 与 native feedback 都重放已完成的 `can_reveal` | 启动聚焦 112，边界 18 | INTERRUPTED | 真实 child：hidden 先于 listener，GUI 线程显示一次并自行 exit 0 | NOT RUN |
| A3 | 诊断从已加载 source 进入 reporter / manifest；Replay 在 Play 前显示只读警告 | batch_runner 289；Replay UI 单独进程 7 | INTERRUPTED | Replay 长警告、换干净文件清除 通过 | NOT RUN |
| A4 | FRF `get_visible_xlim/ylims`，范围变化走既有信号 | 与 A7 合计 461 | INTERRUPTED | 连续 X/Y 缩放后新像素、同范围不再截 通过 | NOT RUN |
| A5 | 预览使用 `_requested_output_settings(preset.outputs)` | 三个 NameError 用例含在 289 里；预览对话框 16 | INTERRUPTED | NOT RUN（无单独 Cocoa 预览场景） | NOT RUN |
| A6 | child 不再覆盖 widget 的减少动态 | 含在启动 112 里 | INTERRUPTED | 显式减少动态：计时器在、相位不动、阶段文案仍更新 | native 绘制 NOT RUN |
| A7 | 换向后丢掉旧质量决策再离散结算 | 含在 461 里；150 ms 未改 | INTERRUPTED | 高 ink→便宜、便宜→高 ink、同向 no-op 通过 | NOT RUN |
| A8 | 只改测试，委托 `line_amplitude_limits` | 21 passed | INTERRUPTED | 不适用 | 不适用 |
| A9 | 逻辑点按图像 DPR 取样 | DPR 1/2/1.5；两种收集顺序各 47；conftest 9 | INTERRUPTED | 峰顶与外壳角在 Cocoa grab 上通过。子进程 DPR 探针仍是 offscreen | NOT RUN |

Cocoa 这 12 条是 `QT_QPA_PLATFORM=cocoa`、一块屏幕上的自动化手势和像素断言（3.80s + Replay 0.36s），不是人工把整个安装包点一遍。QSettings 仍由 UI 测试夹具隔离。

全量：主集 `--ignore=tests/acquisition_ui` 从 10:42 跑到约 13:30，停在约 75%。进度标记 50 failed、64 skipped、0 error。失败名字还没打印。`tests/acquisition_ui` 整目录没开始。结论 **INTERRUPTED / UNVERIFIED**。

因此 F1–F7 不能写成发布级关闭。数据正确性修复在 Windows 包未跑、全量未完成时不能当作可发布。

细节：`.state/review-remediation-test-summary.md` 与各 `review-remediation-lane-*.md`。

## 14. 新增实施计划：测试效率与全量失败治理

本节状态为 **PLANNED / NOT RUN**，不改写第 13 节历史结果。用户要求同时优化测试耗时，并将确认属于测试自身的失败一并修复。当前不能将约 50 个失败标记统一认定为测试错误。

### 14.1 T10 — 建立可追溯失败台账与有界入口（A10）

**已核实证据：** `/tmp/review-remediation-full-main.log` 只有进度字符，末尾约 76%，没有 nodeid/失败栈；历史报告约记为 75%。`.pytest_cache/v/cache/lastfailed` 有 248 条记录，mtime 为 2026-09-25 10:41:39，早于主集 10:42:22 启动，不能视为本次失败名单。13:26 的原生采样确认 GC 活跃、进程 footprint 3.5 GB/峰值 4.6 GB，但短时采样不能证明全部耗时原因或失败根因。

1. 先将可用日志、采样、启动脚本和 cache 复制到本任务 `.state/` 证据目录，记录时间、哈希、HEAD 和工作区指纹，防止 `/tmp` 清理。仅 status 名单或 tracked diff 不足以覆盖 untracked 源码；确认 runner 指纹包含相关 untracked 文件内容。
2. 建立 `.state/review-remediation-failures.jsonl`：每项包含 `id/nodeid/phase`、run id、快照、平台/DPR、错误与原始日志位置、独立运行/组合运行结果、分类及置信度、根因组、owner、修复及回归证据、状态。多个用例可共享根因，仍分别保留状态；同一用例 call/teardown 失败也分别记录。
3. 对旧 50 个标记先保留一条 `UNKNOWN / identities unavailable` 批次记录；不从点号位置和当前 collection 顺序猜名字。cache 仅作候选，校验 nodeid 是否仍存在后，以新进程定向复现。旧批次无法恢复时保留证据缺口，以后续完整的新运行替代验收，不能伪造逐条映射。
4. 所有后续诊断走现有 runner `--phase`，保留即时 `failures.jsonl`、pytest events 和心跳。单批诊断建议软 120 秒、硬 180 秒、`--maxfail=3`，串行执行；一次诊断 wave 最多三批，到预算先归因，不循环刷全套。maxfail 后未执行项留在队列，后续显式列出剩余 nodeid，防止总被前几个失败挡住。
5. 没有可信 nodeid 的部分，在 T11 后按小模块、限时批次重建**当前**失败清单；记录 planned/executed/unrun。collection 也受 runner 超时约束。不得把一次 `--lf` 的结果当作 50 个失败的复现或完整覆盖。

**Owner / gates：** 父协调者持有台账与 runner/selector 接缝。若只配置入口无需改 runner；确需改动则运行 `tests/test_run_test_gate.py`、`tests/test_test_gate_selection.py` 的对应合同，验证首个失败立即落盘、超时状态、退出码和只终止自己的进程。台账出口要求每个新观察到的失败可追溯，未知项显式保留。

### 14.2 T11 — 修复测试 fixture 自身的引用滞留（A11）

**已复现：** `tests/ui/conftest.py` 的 `_pin_owned_routers/_pin_owned_controllers` 在 item 完整 teardown 后仍保留强引用。单条现有测试的探针用时 0.72 秒；两个 C++ 对象已删除，Python 对象在 full GC 后仍存活；仅释放 item 属性再 GC，存活数 2→0。该证据不代表已解释所有失败或全部耗时。

1. 在 `tests/ui/test_qt_fixture_lifecycle.py` 先增加独立子进程回归，检查前一 item 完整 teardown 后 Python owner/host 能释放；异常/泄漏检查失败路径也释放 item 记录，session 自有对象不被误删。
2. 在 UI fixture owner 修复：保留泄漏判定所需引用至检查完成，在 `finally` 释放；确定释放、DeferredDelete 和 GC 的安全次序，保证下个用例前完成回收。不能简单换成弱引用导致真实泄漏不可见，也不能删除 GC/paint pin 或吞掉检查异常。
3. 验证实际 app filter 泄漏仍失败；registry/heap 一致、QSettings 和 QSS 恢复、dense-raster admission 不被上一用例对象占用。根 conftest 的 collector 修复不承载新 fixture。

**Owner / focused：** 同一测试设施 owner 独占 `tests/ui/conftest.py` 与生命周期测试；运行 `tests/ui/test_qt_fixture_lifecycle.py`。**Boundary：** `tests/test_conftest_autouse_scope.py`、`tests/ui/test_qsettings_isolation.py`，以及 `tests/ui/test_pg_timedomain_canvas.py` 中选出的 raster admission/生命周期相关用例（实施时登记精确 nodeid）。先不运行整个 tests/ui。

### 14.3 T12 — 按根因修复失败，禁止把产品 bug 改成绿灯（A10）

| 分类 | 认定证据 | 修复与出口 |
| --- | --- | --- |
| 产品缺陷 | 断言对应有效产品合同；真实调用链/输入稳定违约 | 回 owning module 最小修复；先保留失败回归；单例、消费链和相邻边界通过。不能为过测修改预期 |
| 过期或错误测试 | 当前 spec/用户行为/独立数值 oracle 证明原断言失效；不能只拿实现自身证明实现正确 | 更新断言、fixture 或 mock 边界；说明替代覆盖，受控错误输入/变异仍能触发失败 |
| fixture/隔离/顺序污染 | 单例通过、指定前置组合失败；定位 QSettings、QSS、DPR、Qt ownership、全局缓存或 collector fixture closure 差异 | 修状态 owner 的对称清理；单例及触发组合、反向顺序通过。若源于产品共享状态则转产品类别；固定顺序、自动重试和 sleep 不算修复 |
| 环境/平台条件 | 缺依赖、平台不支持或 DPI/字体/窗口条件有实证 | 修测试环境或用准确前提限制；补适用平台验证。平台专属 skip 有原因且保持 NOT RUN，不能替代目标平台验收 |
| 性能/资源/超时 | 分阶段事件、内存/线程/采样证据定位瓶颈 | 修泄漏、无界等待或测量合同，设可解释预算；仅加 timeout 或降断言不足以关闭 |
| 未知 | 证据不足、旧日志没有名字、暂未重现 | 保持 UNKNOWN，指定下一项最小复现；不得默认归为 flaky 或测试错误 |

按根因成组处理，优先 collection/setup 及 fixture 故障，再处理独立断言；减少同根级联失败的重复工作。每组先跑一个代表复现，修复后覆盖组内所有受影响 nodeid 及相邻反例。独立通过而组合失败时才扩大到最小前置序列；比较实际 fixture closure，不靠穷举全部排列。

原 V1（死符号）和 V2（DPR 坐标）是已确认测试问题的例子，不能把该结论外推到新的 50 个标记。对窗口像素、时间轴、数值精度和信号接线，保留行为断言与独立 oracle；不得大幅放宽容差、删除测试、扩大白名单、无理由 skip/xfail 或换成仅“不抛异常”。

**Owner / gates：** 台账分配每组的测试文件和产品 owner，不多人改同一 conftest；每组登记最小 red→green、同根 nodeid、相应边界。失败数下降不等于问题关闭，必须有原因与覆盖证据。新增数值修复若超出原 D1–D8，先在 spec 登记精确合同与边界，禁止借测试治理重设计算法。

### 14.4 T13 — 测量收益，必要时顺序分组（A12）

1. 选定覆盖 ChartStack/Pin、QSS、MainWindow 的有限代表集合，记录精确 nodeid、环境和修复前后代码指纹；仅比较预期 fixture 补丁不同的两个版本，其他产品改动相同。每次单进程、软 120 秒/硬 180 秒；对照超时可直接作为退化证据，不为基线耗费数小时。
2. 对比墙钟、setup/call/teardown、GC 时间与次数、存活 owner 数、RSS 趋势。先检验 T11 消除持续引用增长；未测到的收益写 UNKNOWN，不先承诺倍数。CPU 高占用本身不等于 bug，重点减少无效遍历和累计资源。
3. 只有仍有可测瓶颈时才调整 heap 全扫描频率或 static_source 分类；保留每项 owner 泄漏检测、定向全堆交叉检查和异常路径。纯源码测试可使用现有 static_source，真实 Qt 测试不得为省时误标。调整必须证明不会漏掉泄漏/隔离失败。
4. 只有小规模测量显示大进程仍明显累积时，扩展现有 runner 的顺序分组与清单校验。基于一次稳定 collection 清单比较默认 `not slow` 集合与各组并集，保证无缺失、无重复、参数化 nodeid 完整；失败、跳过、未运行分开计数。显式 slow/native/frozen 仍独立，不能混称覆盖。
5. acquisition_ui 保持独立进程；另保留代表性同进程跨模块顺序/清理合同，避免分组隐藏污染。已知失败在原触发组合转绿后才能关单。单时刻最多一个测试 gate，禁止 `-n auto`；数值库线程限制仅在过量线程证据支持时固化。

**Gates / 出口：** fixture 策略变化复用 T11 focused/boundary；runner/selector 变化运行其对应测试，并验证清单遗漏/重复会阻断验收。报告实测收益及证据范围；在小规模预算内确认成本可控之后，才为集成选择分组和预算。

### 14.5 T14 — 一次稳定集成与失败关闭（A10–A12）

前置条件：T11 回归通过；当前已定位的 T12 失败修复或明确保留阻断；T13 给出有界运行配置；源码快照稳定。父协调者执行第 11.2 节的一次 gate，各 worker 不跑全套。若本轮仍失败，立即保留证据并回对应 focused owner，不自动循环全量。

最终报告同时给出：原中断批次的证据缺口、新运行 collection/执行覆盖、分类台账（确认测试问题/确认产品问题/环境未验收/未知）、修复前后测量、未运行平台与状态。旧批次的缺失名单可由同范围的新完整运行替代验收，但不能宣称旧 50 条逐一证实。存在失败/未知或缺失集合时不能写“全量通过”。

### 14.6 本次文档修订的验证边界

本轮修改 plan/spec，核对现有日志、cache 时间戳、runner 接口和已有小探针；不运行新测试，不执行 T10–T14，不修改源码或 fixture。检查完整文档的编号、依赖、门禁命令、路径和 `git diff --check`；文档本身无需 runtime suite。
