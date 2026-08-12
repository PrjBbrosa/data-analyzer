# 分析 View 来源隔离：最终验收与试运行建议

- 日期：2026-08-11
- 分支：`codex/analysis-view-source-isolation-pilot`
- 基础提交：`9ed578dff63bf0e516dbb0da90e3c80ab500c264`
- 当前候选：基础提交 + 本轮 2 个未提交窄修复 + 对应测试/lesson
- 审查范围：Task 10 状态矩阵、候选性能、两进程全量与 Batch 归因、真实 macOS Cocoa 前台

## 1. 结论先行

**建议：允许继续“受限试运行”，但暂不宣布 Stage 1 正式全量验收完成。**

来源隔离的状态模型与主要行为已经闭环：新 View 为空、已有 View 精确恢复、模式/View/Pane
切换不提交计算、局部 detach 不污染 sibling、分组文件关闭默认取消、项目 round-trip 与
deferred restore 均通过。性能也低于既定门槛。

本轮额外发现并修复了两个真实问题：

1. Order View 冷缓存切换时，程序化应用 dB reference 会冒充用户编辑，延迟提交计算；
2. 项目重开到 `FRF · View 2` 后，最后一次时域恢复把左栏 owner 误写为
   `时域 · View 2`。

正式验收仍保留两个证据边界：

- macOS 前台已覆盖 3 文件/4 logical sources、五模式、多 View、空态、Inspector 默认、
  项目保存重开及分组文件全局关闭默认取消；但系统级控制工具无法完成 Qt 嵌套拖拽循环，
  因而“前台拖入 → 角色选择 → 局部 detach/明确级联”未形成真实手势证据；
- 主全量仍有既存 Batch 红项。已在原始基线 `1617b2d0` 逐项复现，确认不是来源隔离回归，
  但仓库全量本身不能写成全绿。

## 2. 本轮新增修复

### R1：View restore 不得触发冷缓存计算

- 现象：Order View 切换时，Inspector 的 dB reference `valueChanged` 被当作用户编辑；事件队列
  排空后调用 `do_order_time()`，冷缓存进一步提交 `AnalysisJobService.submit_batch()`。
- 根因：程序化 View apply 缺少信号边界保护。
- 修复：`_on_db_reference_value_edited()` 在 `_applying_analysis_view` 或 preset apply 期间直接返回。
- 证据：新增测试
  `test_order_view_switch_with_cold_cache_does_not_submit_worker`，修复前红、修复后绿；最终
  Task-10 矩阵记录 `job_submissions: []`。

### R2：项目重开不得让隐藏时域覆盖分析 owner

- 现象：保存时 Time 和 FRF 均处于 View 2，重开后顶部/Inspector/画布是 FRF，但左栏空态写成
  `当前“时域 · View 2”尚未加入文件`。
- 根因：`open_project()` 最后恢复 Time manager 时，`_apply_active_view()` 在非时域模式仍调用
  `_project_view_controls()`，覆盖共享 navigator。
- 修复：时域控件只在当前可见模式为 `time` 时投影。
- 证据：新增测试
  `test_open_project_keeps_analysis_empty_owner_after_time_view_restore`，修复前稳定红；修复后
  offscreen 与真实 Cocoa 均显示 `FRF · View 2`。

## 3. Task 10 状态矩阵

探针：`.state/analysis-source-isolation-pilot/task10_state_matrix.py`
结果：`.state/analysis-source-isolation-pilot/task10-state-matrix.json`

| 项目 | 结果 |
| --- | --- |
| 输入 | 3 个物理文件，4 个 logical sources；分组 HDF 产生 `2x` / `1x` 两来源 |
| 切换规模 | 5 模式 × 2 View，预热 3 轮，正式 50 轮 |
| 状态比较 | 250 次 transition comparison 全部通过 |
| 计算提交 | 0 次 |
| Time detach B | PASS；不改分析与 sibling Time View |
| FFT detach B | 取消与确认均 PASS；共享 cache 边界保持 |
| 分组全局关闭 | 2 logical sources 汇总为 1 次确认；取消后全保留 |
| 项目重开 | 3 physical / 4 logical 完整恢复 |
| deferred restore | reorder 后仍按 `view_id` 恢复，PASS |

保存动作会捕获 live Inspector 的派生展示参数（例如有效 NFFT preview）。因此探针先锁定
attachment/source/range 等路由状态在保存前后不变，再把保存后的序列化状态作为重开 oracle；
这不是放宽来源隔离断言。

## 4. 性能门禁

探针：`.state/analysis-source-isolation-pilot/task10_candidate_benchmark.py`
比较：`.state/analysis-source-isolation-pilot/task10-candidate-comparison.json`

条件：真实 `MainWindow`、隔离 QSettings、6 CSV × 300 通道 = 1,800 candidates、5 次预热、
50 次测量；基线为 `1617b2d0`。此项为 offscreen 定量门禁，不冒充 Cocoa 前台流畅度。

| 路径 | 基线 p50 / p95 | 当前 p50 / p95 | GO 门槛 | 判定 |
| --- | ---: | ---: | ---: | --- |
| 全 section candidate refresh | 538.9529 / 555.1843 ms | 548.8396 / 567.7764 ms | 693.9804 ms | PASS |
| attachment projection | 2.9761 / 3.2114 ms | 8.1937 / 8.5333 ms | 53.2114 ms | PASS |

Candidate p95 相比基线增加 2.27%。Projection 的相对增幅较大，但绝对 p95 为 8.53 ms，仍显著
低于 `max(baseline × 1.25, baseline + 50 ms)` 门槛；本轮前台模式/View 操作未观察到肉眼冻结。

## 5. 自动化门禁与 Batch 归因

### 最终工作树

- 聚焦来源隔离 + 项目恢复：`540 passed, 787 warnings in 76.06s`；
- import / signal / packaging 边界：`9 passed, 1 skipped in 0.88s`；
- Task-10 状态矩阵：PASS；
- 两进程最终全量：主进程
  `5914 passed, 9 skipped, 3 deselected, 2 failed, 8 errors in 650.27s`；
  acquisition `355 passed, 4 warnings in 8.62s`。

### 已确认的 Batch 基线红项

前一轮完整主进程结果为
`5913 passed, 9 skipped, 3 deselected, 2 failed, 8 errors in 564.10s`；独立 acquisition 为
`355 passed in 8.72s`。两类主红项都在原始基线 `1617b2d0` 的干净 worktree 中复现：

1. Batch segmented choice：测试期望 `x=72`，实际 `x=71`；
2. Batch signal picker：测试期望 `height=38`，实际 `height=32`；
3. 三个 BatchSheet 用例 test body 已通过，pytest-qt teardown 时访问已删除的 C++ wrapper；
4. 后续 BLF setup error 是前项 teardown 污染，单独进程运行通过。

因此这些是 Batch 几何/生命周期既存债务，不是 `ca5cf843`、`9ed578df` 或本轮两处修复造成的
来源隔离回归。本轮没有修改 Batch 产品代码或测试来“做绿”。

## 6. 真实 macOS Cocoa 前台

- Qt 平台：`cocoa`
- 产品版本：`v7.9.7`
- HEAD：`9ed578dff63bf0e516dbb0da90e3c80ab500c264`
- 说明：前台进程加载的是该 HEAD 上的当前工作树，因此包含本报告列出的两处未提交窄修复。
- QSettings：隔离在 `.state/analysis-source-isolation-pilot/foreground-settings/`，未污染开发者设置。

已观察：

1. 3 个物理文件显示为 3 张卡；分组 HDF 显示 2 轨并展开为 2 logical sources；
2. Time、FFT、FFT-time、Order、FRF 均创建到 View 2；新 View 文件/来源为空，分析 Inspector
   回到该 section 默认；
3. 五模式及 View 1/2 来回切换可用，窄左栏 owner 文案可读；
4. 保存并重开 `.tlproj` 后，3 physical / 4 logical、五 section 的 View 1/2 与 active FRF View 2
   恢复；第二处修复后左栏 owner 与顶部一致为 `FRF · View 2`；
5. 关闭分组 HDF 时只出现一次依赖摘要，列出 Time View 1 的两个 attachment，焦点默认位于
   “取消”；取消后两个 logical sources 都保留。

截图：

- `../../../.state/analysis-source-isolation-pilot/foreground-01-time-loaded.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-02-time-empty-view.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-03-fft-empty-view.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-04-fft-time-empty-view.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-05-order-empty-view.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-06-frf-empty-view.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-07-project-reopened.jpg`
- `../../../.state/analysis-source-isolation-pilot/foreground-08-global-close-cancel.jpg`

未形成真实手势证据：Qt 的 `QDrag` 进入嵌套事件循环后，系统级控制工具的拖拽没有完成 drop；
因此前台“拖文件加入分析 View、右侧选择角色、局部 detach、确认全局级联”标为
**UNVERIFIED in foreground**。这些状态合同已由 Task-10 矩阵和 focused tests 自动化覆盖，
但两类证据不互相替代。

## 7. A1–A18 最终台账

| ID | 状态 | 最终证据 |
| --- | --- | --- |
| A1 | PASS | schema/state round-trip 测试；新 analysis attachment 显式空 |
| A2 | PASS | schema 6 migration；旧 Pane roles 推导，显式空不补全 |
| A3 | PASS | 四 section candidate 按 active View attachment 隔离 |
| A4 | PASS | Time switch/detach 不改分析；Task-10 matrix |
| A5 | PASS | FFT navigator 只写当前 FFT Pane，不污染 Time |
| A6 | PASS | analysis-candidates 不可勾选；header/flags/widget 集成测试 |
| A7 | PASS | 四分析新 View 空状态 + 默认 Inspector；Cocoa 截图 03–06 |
| A8 | PASS | Duplicate 深复制状态，生成新 `view_id` |
| A9 | PASS | 250 次切换零状态漂移、零 job；冷缓存回归测试 |
| A10 | PASS | detach 只清当前 View，共享 cache 保留；矩阵取消/确认 |
| A11 | PASS | 全局 close 完整 preflight、默认取消、明确 cascade 测试；Cocoa 默认取消 |
| A12 | PASS | channel delete 与 exact-X/overlay 依赖合同及清图测试 |
| A13 | PASS | 所有 section/View/Pane 项目 round-trip；3/4 来源实测 |
| A14 | PASS | missing refs health + degraded-save 默认阻止 |
| A15 | PASS | reorder 后 deferred restore 按 `view_id`，矩阵通过 |
| A16 | PASS | hints/quickref/header/FRF 文案测试同步 |
| A17 | PARTIAL | 3 文件 × 多 View × 5 模式 Cocoa 走查通过；拖入/角色/局部 detach/明确级联前台手势未证实 |
| A18 | PASS | 1,800 candidates benchmark 低于两条 p95 门槛 |

## 8. 试运行建议与后果控制

可以继续给少量真实工程试运行，原因是没有命中 spec 的状态破坏类 NO-GO：未见来源被切空、
FFT 污染 Time、inactive section 被保存覆盖、局部 detach 跨 View 失效、项目静默丢失，亦未见
候选刷新肉眼冻结。

试运行期间建议保留以下限制：

1. 不把本轮称为“正式全量验收通过”；A17 仍是 PARTIAL；
2. 重点观察真实鼠标的拖入、角色选择和局部 detach 文案，发现一例错误立即停止扩大范围；
3. Batch 的几何/teardown 债务单独立项，不与来源隔离补丁混修；
4. 先提交本轮两处修复与测试，再扩大试运行，避免用户运行的树与证据树不一致；
5. Stage 2 unresolved/relink 仍未实现：全局明确关闭会清理引用，不承诺未来自动重连。

## 9. Git 与证据边界

本报告生成时未执行 commit/push。既有三份 Grok/Codex review artifact 保持未改；本轮产品改动
仅涉及 `window.py`、`_view_mixin.py` 及两份对应测试，另新增一条 restore/projection lesson 和本
验收报告。`.state/analysis-source-isolation-pilot/` 为本地探针、JSON、JUnit、项目和截图证据，
不建议提交 Git。
