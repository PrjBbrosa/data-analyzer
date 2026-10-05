# 分析 View 结果有效性与跨 View 对比实施 Review

- 结论：**NEEDS REWORK**。FRF 原始缓存身份问题已修复，但跨 View 的完整目标路由尚未闭环，存在写错 View、显示错参数和错误轴联动。
- 对照计划：`docs/analyzer/plans/2026-10-04-analysis-view-result-validity-and-cross-view-comparison-plan.md`，已逐节核对。
- 审查快照：`72b08435..6306b3b1fd4ef40bccc8bf612d07fdd99569fa13`。重点为 `99256024`、`87e33fa7`、`7f9908e7`、`519ca4df`、`6306b3b1`；区间中的 `612b7e68` 是时域图表设置 chrome 的独立改动，不在本次功能验收结论内。
- 本轮只 review：没有修改产品源码、正式测试或计划；仅写本报告和 `.state/analysis-view-review-20261004/` 诊断材料。未改动已有 lesson 文件。
- 以下 9 项均有定向失败探针，其中画布调用 spy 与真实图线/项目文件验证分开注明。8 项是新增跨 View 路径暴露的问题；R7 是原有有效性缺口尚未补齐。

## 1. 严重度排序的发现

### R1 · P1：结束对比没有恢复主侧 Inspector，后续 capture 把 B 的参数写进 A

- 位置：`mf4_analyzer/ui/main_window/_analysis_mixin.py:753-764`，尤其 `760-761`。
- 重现：FFT A 的 window=hanning、B=hamming；打开 A/B；聚焦 B；结束 View 对比；再走 `_capture_active_analysis_view('fft')`。
- 实测：关闭后 Inspector 仍为 hamming，A 原先的 hanning 随 capture 被改成 hamming。
- 原因：先关闭 owner、销毁 peer 展示，未提交离焦状态并投影回保留的 host。此时派发目标已退回 A，而控件仍代表 B。
- 影响：下一次计算、切 View 或保存可能悄悄修改 A 的分析条件。不是单纯标题或高亮没刷新。
- 修复要求：结束对比是“提交当前焦点 → 解除绑定 → 明确保留 View/pane → 完整投影”的一次事务；参数、来源、时间、facts、焦点保持一致。
- 证据：`test_close_restores_host_inspector`，真实 MainWindow 状态断言失败，日志 `CLOSE inspector=hamming host after capture=hamming`。

### R2 · P1：对比聚焦 B 后切到时域保存，项目文件会把 A 保存成 B 的参数

- 位置：`mf4_analyzer/ui/main_window/_analysis_mixin.py:446-466,1515-1519`；保存调用点 `_project_io_mixin.py:2458-2460`。
- 重现：同样设置 A=hanning、B=hamming，聚焦 B，切时域，执行真实 `save_project()`。
- 实测：切时域后 A 仍正确；保存后 A 在内存及 `.tlproj` JSON 中均变为 hamming。
- 原因：`_comparison_routes()` 只在 section 当前可见时成立。保存遍历所有 section 时，隐藏 FFT 被当成 manager.active=A，但其独立 Inspector 控件仍保留 B；无条件 capture 将其写入 A。
- 影响：无需结束对比即可污染持久化项目。只修 R1 的关闭流程不能修这个问题。
- 修复要求：隐藏 section 不从控件猜所属 View；保留明确的 Inspector 投影身份，或在离开时完成 capture 后直接序列化模型。增加实际 save/open 文件回归。
- 证据：`test_save_from_time_preserves_hidden_comparison_host`，实际 JSON 断言失败，`HIDDEN SAVE host saved=hamming host live=hamming`。

### R3 · P1：“全时段/指定范围”仍写主侧，聚焦 B 时清掉的是 A 的范围

- 位置：`mf4_analyzer/ui/main_window/window.py:2797-2812`。
- 重现：A 范围=(0.1,0.8)，B=(0.2,0.7)，聚焦 B 后调用按钮所连的 `_on_time_range_enabled_changed(False)`。
- 实测：A→None，B 保留原范围。
- 原因：此入口仍使用 `manager.active` 和主 page 的 `focused_index()`。数值范围编辑已使用显式目标，但模式切换没有迁移。
- 影响：用户以为 B 已恢复全时段，实际 B 仍按指定范围分析，同时 A 的分析请求被改写。四个分析模块共享此入口；运行探针直接确认 FFT。
- 修复要求：模式切换、数值输入 flush、最大范围、计算前确认统一解析同一 `(section, view_id, pane_index)`。
- 证据：`test_peer_full_range_toggle_only_updates_peer`，真实 PaneState 断言失败。

### R4 · P1：跨 View 查到了各自的缓存，绘制时却共用当前 Inspector 的显示参数

- 位置：`_analysis_mixin.py:1135-1144,1177-1179`；`window.py:1906-1916,1941`；`_order_mixin.py:851`。
- 重现：两侧缓存幅值均为 2，A 设 Linear，B 设 dB；打开对比。
- 实测：A 和 B 图线均为 2；B 应按该探针的参考值转换为约 6.0206 dB。
- 原因：查缓存传入了 state，但 `_plot_fft_entries()` 又读当前 `fft_ctx`。热图 `_render_cached_heatmap()` / `_render_order_on()` 也重新读当前控件。
- 影响：独立的数值结果会按另一 View 的幅值模式、参考值或显示范围呈现，比较结论不可信。FFT 为真实曲线数据验证；FFT-time/Order 是同类调用链的源码证据，未冒充逐模块数值复现。
- 修复要求：render 显式接收所属 View 的 display snapshot 和按该来源解析的 reference，异步完成同样按任务所属 View 取最新显示意图；不能临时切 Inspector 来代替传参。
- 证据：`test_fft_each_side_uses_own_display_params`，读取真实 `getData()` 失败。

### R5 · P1：FRF 聚焦 B 修改显示，参数保存给 B，画布更新的却是 A

- 位置：`_frf_mixin.py:330-336`；同类预设路径 `_analysis_mixin.py:1696-1701`。
- 重现：FRF A/B 并排，聚焦 B，执行 `magnitude_scale=linear` 的显示变更处理。
- 实测：`set_display_params` 只调用 host，没有调用 peer。
- 原因：`_active_frf_state()` 已能返回 B，但绘图循环仍用 `page.pane_canvas()`，后者代表主侧。
- 影响：右侧参数与曲线不一致，左侧图被改而左侧模型没变；切换后还可能跳回另一种显示。幅值、相位、频率轴等共用此入口。
- 修复要求：直接编辑和 display-only preset 都按 View/pane binding 找 canvas。
- 证据：`test_peer_frf_display_edit_only_updates_peer`。这是生产处理函数的画布调用 spy，非前台像素验收。

### R6 · P1：B 的计算参数变更后，有效性判定仍检查并标记 A

- 位置：`_analysis_mixin.py:1721-1768`，特别 `1753,1761`；FRF 另见 `_frf_mixin.py:243-247,288-318`。
- 重现：FFT A/B 并排、聚焦 B，修改 B 的 window，再走 compute-params-changed。
- 实测：stale 标记只发给 host，未发给 peer。
- 原因：参数同步使用 focus target，随后的 reconcile 又取 `mgr.active`。FRF 的 visible/stale 条件也把 peer 排除在当前展示之外。
- 影响：B 的旧曲线可能继续以当前结果的形式保留，A 无故被标过期；还原参数、预设和 facts 可能继续与画面不一致。
- 修复要求：将 state/target 贯穿 reconcile、cache lookup、stale、facts 和 repaint；不要在中途重新取 active manager。
- 证据：`test_peer_compute_edit_stales_peer_canvas`，画布 stale 调用 spy 失败。探针没有声称完成了各模块的前台旧图/facts 视觉验收。

### R7 · P2：FRF 时间范围改回原值后仍不能复用已有结果

- 位置：`_frf_mixin.py:251-259,916-928`；范围变更入口 `_analysis_mixin.py:2964-2991`。
- 重现：真实 FRF job 计算范围 0.1–3.8 s；改成 0.2–3.8；再改回 0.1–3.8。
- 实测：原结果仍在 cache；`effective_time_range=None`，lookup 返回 None。
- 原因：范围变更清掉 effective facts，而 lookup 仍把“effective range 非空”作为准入前提。canonical request 尚未成为充分的结果身份。
- 影响：依然出现已有完全匹配结果却要求重算；输入/输出换回也共用 clear_effective 路径，需补对应回归。此项属于未完成的旧问题横展，不是声称本次新引入。
- 修复要求：从当前有效请求构建 key，缓存命中后从结果恢复 effective facts；不要用被清空的上次运行事实阻断匹配。
- 证据：`test_frf_range_revert_reuses_cached_result`，真实数值 job 与真实 cache，`effective=None cached=True lookup=None`。

### R8 · P2：FRF 保存 B 的相机状态时，读取的是 A 的坐标范围

- 位置：`_frf_mixin.py:158-173`；调用点 `_analysis_mixin.py:1523-1524`。
- 重现：A 的频率视窗 1–10 Hz，B 为 20–100 Hz；聚焦 B 并 capture B。
- 实测：B 保存的 xlim 变成 (1,10)。三个 Y 面板也在同一读取循环中。
- 原因：传入的 state 可以是 B，但 canvas 固定从主 page 获取。
- 影响：离开模块、计算前 capture 或保存后重开会丢失 B 的视窗，并复制 A 的缩放。焦点切换路径也应统一覆盖 FRF 特有的三组 Y 范围。
- 修复要求：使用目标 binding 抓取 FRF 相机，覆盖 pane 数量不相等的两侧。
- 证据：`test_peer_frf_capture_uses_peer_camera`，真实 canvas 范围断言失败。

### R9 · P2：跨 View 轴联动没有检查 log/linear，物理频率被错误映射

- 位置：`_analysis_mixin.py:1016-1042`，尤其 `1039`。
- 重现：FRF A 频率轴 log，B linear，两侧初始都是 10–100 Hz，打开跨 View 轴联动。
- 实测：操作被接受；A 仍为 (10,100)，B 变为 (1,2)。
- 原因：直接 `setXLink` 同步 ViewBox 内部坐标，未校验尺度，也未按物理 Hz 转换。
- 影响：同屏看似联动，实际查看不同频段；与计划“仅联动语义、单位、尺度兼容的轴”冲突。
- 修复要求：第一版拒绝不兼容尺度并给出原因；若要允许异尺度联动，须显式做物理坐标转换及回环保护。联动开启后的尺度变更也须重新验证。
- 证据：`test_frf_axis_link_requires_matching_scales`，真实 canvas/轴链接，`accepted=True host=(10,100) peer=(1,2)`。

## 2. 已完成与尚不充分之处

| 计划 | 当前判断 | 依据 |
| --- | --- | --- |
| T0 缺陷冻结 | 已增加对应正式测试 | `test_frf_main_window.py:1072` 起有实际 job 往返，不再只用恢复键反向造缓存；仍不能用新增绿测推断所有交互组合都正确 |
| T1 FRF canonical key | 主缺陷已闭环；整体验收 partial | 原 4 组 uniform/jitter × full/range 探针全部转绿；R7 说明匹配请求复用仍有残缺；原始用户文件/前台环境未验证 |
| T2 有效性与迟到任务 | partial | 单 View display-only preset、计算参数改回和旧 FFT-time 请求拦截通过；接入 comparison 后 R6 重新破坏有效性路由 |
| T3 显式目标与焦点 | NEEDS REWORK | owner、canvas mapping、计算入口已建立；capture/render/range/reconcile 尚存 active-manager/Inspector 隐式选择，R1–R6/R8 |
| T4 菜单、持久化与帮助 | partial | 两种菜单能力已分开，比较关系独立序列化，hints/quickref/四指南更新；真实参数持久化被 R2 破坏，联动被 R9 破坏 |
| T5 集成与原生验收 | 未完成 | Grok 全套仍在运行；本轮为 offscreen，未操作用户前台 TraceLab、未跑 Windows frozen |

计划文件仍写“待实施”，没有交付后的逐项完成证据，因此不能据此宣称所有任务已完成。

另外两个明确待补的边界，不计入上述已运行复现数量：

- 色阶兼容 `_comparison_levels_compatible()` 只比较四个 params 字段（1002–1014），没有核对两侧实际来源单位和 Auto reference 的解析结果。需按计划补不同量纲、不同自动参考值，以及开启后改变来源/模式的拒绝/解锁测试。
- 对比已打开后新增/关闭内部 pane：`_on_analysis_split()`（1293 起）仍只处理 host 的 page/manager，没有同步 comparison binding 的步骤。需覆盖 A/B 为 1/2、2/1、2/2 的动态变更，不能只在打开前建立双 pane。

## 3. 验证记录与证据边界

均使用项目 `.venv`、`QT_QPA_PLATFORM=offscreen`、独立临时目录和已有 QSettings/Qt 生命周期 fixture。

| 执行 | 原样结果摘要 | 含义 |
| --- | --- | --- |
| 新增 probe 第一组 | `5 failed, 28 warnings in 1.52s` | R1/R3/R4/R5/R8 |
| 新增 probe 第二组 | `3 failed, 5 deselected, 23 warnings in 1.04s` | R6/R7/R9 |
| 实际保存 probe | `1 failed, 8 deselected, 8 warnings in 0.69s` | R2，确实写出并读取临时项目 JSON |
| 上轮原始缺陷 probes | `9 passed, 50 warnings in 1.59s` | 原主缺陷已修复；其中参数改回项主要记录观察值，不能扩充为所有 revert 情形通过 |
| 当前正式 comparison tests | `9 passed, 76 warnings in 2.78s` | 现有测试能通过，但未覆盖上述失败组合 |

日志：`.state/analysis-view-review-20261004/{probe,additional-probe,save-probe,original-probes-now,existing-comparison}.log`。测试源为该目录 `test_review.py`。

第一次尝试把 `.state` probe 和正式 UI 测试放在同一命令时，显式 `-p ui.conftest` 与自动发现发生重复注册，pytest 在收集前退出。该尝试为无效验证；之后拆成两个正确命令，结果如表。不将它记为产品失败。

运行新增 probes 的命令：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.:tests .venv/bin/python -m pytest -q -s -p ui.conftest .state/analysis-view-review-20261004/test_review.py
```

Grok 的全套入口为 `pytest -q --ignore=tests/acquisition_ui`，父进程安排主套件后单独运行 acquisition。复核 `/tmp/analysis-view-validity-full.meta` 与日志；启动 HEAD 为本审查 HEAD。本轮没有启动第二个 full gate。最后检查时主套件进度约 54%，输出已出现 `F` 标记，但尚无最终失败摘要，具体失败归因为 UNKNOWN；不能提前报绿，也不能将这些标记直接归为本报告的发现。该全套并未包含本轮新写的 `.state` 失败探针。

本次源码 HEAD 在探针前后均为 `6306b3b1`，没有产品 dirty 改动。原生 Cocoa、真实用户数据、十二 FRF 子图的窄窗/性能、Windows Full/Lite 均为 **UNKNOWN**，不能用 offscreen 结果替代。

## 4. 建议修复顺序与复验门

1. **先解决写错状态：R1/R2/R3。** 一个显式 target 贯穿结束、离开模块和保存；增加“聚焦 peer → 切模块 → 保存/重开”和“结束 → 计算/保存”真实路径。
2. **再解决显示与有效性：R4/R5/R6/R8。** render、capture、reconcile 全程显式传 state/target；实际曲线、facts、坐标与模型同时断言。对比两侧故意使用不同参数，覆盖异步完成时另一侧获得焦点。
3. **补回退与联动：R7/R9。** 时间、I/O、RPM 等改回缓存请求无需重算；不兼容轴和色阶拒绝联动。不得通过自动重算掩盖身份问题。
4. **最后完成验收。** 先让本报告 9 个红探针转绿，再运行各 owner focused gates 及状态所有权/import/signal 边界；复用正在执行的 full gate 作为当前快照记录。修复集成后按计划另定稳定里程碑，避免多个全套并发。

修复后的最小交互矩阵：四分析模块 × host/peer 焦点 × 1/2 pane，包含开/关/替换对比、时间模式、参数/预设、迟到任务、保存/重开、动态 pane、游标/导出；随后做 Cocoa 原生验收。

现有 lessons 已覆盖“投影不是用户意图”和 pane-local source ownership；本轮 lesson gate 为 `lesson_required: False`，不再新增重复经验条目。
