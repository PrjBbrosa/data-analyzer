# 近期 25 个提交复审修复执行计划

- 日期：2026-10-11。
- 状态：**待实施**。本次只交付复审与文档；未改产品代码、未提交实现。
- 配套 [spec](../specs/2026-10-11-recent-commits-review-remediation-spec.md)；问题编号
  H/C/O/K/S 与验收编号 A1–A11 以 spec 为准。
- Review 终点与编写时 HEAD：`4667dd06`。实施前按符号重新定位。

## 1. 实施原则与依赖

在 owning module 做最小修复；先把 spec 中的确定性复现移入正式测试（红），再改代码（绿）；
不运行通用的 pre-change 全量基线。不得修改 `CLAUDE.md` / `.claude`、吸收无关 dirty、扩大
棘轮白名单、以 xfail / 固定顺序 / sleep 掩盖失败。每个 Task 只跑自己的 owner 用例和列出的
边界护栏；全量门禁只由 T13 的协调者在稳定里程碑跑一次。

依赖关系：

- T1（H1）与 T6（H2–H5）、T7（H3）都改 `heatmap_color_coordinator.py` / `_analysis_mixin.py`
  的色阶段落，**同一 owner 串行**，T1 先行。
- T2（C1/C2/C4/C5/C6/C7）与 T3（C3）都触及对比关系，T2 先行；T2 同时改
  `_analysis_mixin.py`，与 T1/T6/T7 的改动区域不同但同文件，由协调者负责合并顺序。
- T4（O1/O5/O8）与 T5（O2/O3/O4/O6/O7）：T4 改画布与 handle，T5 改对话框；T5 的 O7 与 T1
  的 `_last_auto_levels` 清理相邻，T5 在 T1 之后。
- T9（K1/K5/K6）与 T10（K3/K4/K7）都改 `cursor_pill.py` / `presentation.py`，串行。
- T11（S4/S7）独立。T12（S1–S3/S5/S6/S8–S13/S17）独立但需要 Windows 真机门禁。
- T14（文档 / changelog）最后，依赖发版 owner 的 8.4.3 决定。

若采用并行 agents，分为「热图色阶（T1/T6/T7/T8）」「对比目标（T2/T3）」「图表选项
（T4/T5）」「游标与 Pin（T9/T10）」「IO 与启动器（T11/T12）」五条 lane，文件所有权互不
重叠；协调者持有 `_analysis_mixin.py` 的合并、hints/quickref、T13 与 T14。

| 任务 | 问题 / 验收 | 主要责任文件（前缀 `mf4_analyzer/`） |
| --- | --- | --- |
| T0 | 全部 | 测试入口、未确认项探针 |
| T1 | H1 H7 H10 / A1 | ui/heatmap_color_coordinator.py、ui/pg_canvas/heatmap_canvas.py、ui/main_window/_fft_time_mixin.py:834 |
| T2 | C1 C2 C4 C5 C6 C7 / A2 | ui/main_window/_analysis_mixin.py、analysis_comparison.py、_frf_mixin.py、_fft_time_mixin.py |
| T3 | C3 / A3 | ui/main_window/_project_io_mixin.py |
| T4 | O1 O5 O8 / A4 | ui/pg_canvas/line_canvas.py、ui/_axis_handle.py、ui/analysis_view_state.py、ui/project_io.py |
| T5 | O2 O3 O4 O6 O7 / A5 | ui/dialogs/chart_options.py、ui/main_window/_analysis_mixin.py（两个 heatmap capture 函数） |
| T6 | H2 H4 H5 H8 / A6 | ui/main_window/analysis_context.py、_analysis_mixin.py、_fft_time_mixin.py、heatmap_color_policy.py |
| T7 | H3 / A6 | ui/main_window/_analysis_mixin.py（levels_dragged）、ui/db_reference_settings.py |
| T8 | H6 / A6 | colormaps/registry.py、colormaps/__init__.py、qt_analysis_shared.py 及消费者 |
| T9 | K1 K5 K6 / A7 | ui/chart_stack/pinned_cursor_controller.py、pinning/sampling.py、ui/pinned_cursor_facts.py、cursor_pill.py |
| T10 | K2 K3 K4 K7 / A7 A8 | ui/pg_canvas/heatmap_canvas.py（colorbar）、ui/chart_stack/pinning/presentation.py、cursor_pill.py |
| T11 | S4 S7 / A10 | io/head_hdf.py |
| T12 | S1–S3 S5 S6 S8–S13 S17 / A9 | native/startup_launcher/*、startup_native_feedback.py、tools/*.ps1、tools/measure_windows_startup.py、tests/test_startup_launcher_core.py |
| T13 | 全部 | 唯一全量集成门禁 |
| T14 | S14 S15 S16 H9 O10 O11 O12 O9 / A11 | help/、README.md、docs/analyzer/README.md、chart_stack/toolbar.py、stack.py、cards.py、line_canvas.py、help/__init__.py |

## 2. T0 — 锁定状态与未确认项

1. 记录 `git rev-parse HEAD`、`git status --short`；确认 spec §1 列出的符号仍在原 owner。
2. 把 spec §1.1–§1.2 中「已复现」的探针逐一改写为正式失败测试（见各 Task 的 Red tests），
   不复用 `/tmp` 探针文件。
3. 用专项探针关闭或升级下列**未确认项**，结果写入 `.state/review-20261011-progress.md`：
   - U‑H1：复制 View（同结果同参数）后 pane 画布复用图片，`settle()` 是否把 basis 写到旧 View
     的 pane。成立则并入 T1。
   - U‑H2：`_on_analysis_focus_changed` 末尾的 `_settle_heatmap_color` 与
     `_on_analysis_view_switched` 内 `transaction` 的嵌套深度。
   - U‑H3：catalog 中 provider=pyqtgraph 的条目在 `requirements.txt` 钉住的 pyqtgraph 版本下
     是否全部内置；`_resolve_colormap` 对 `pg.colormap.get` 返回 None 抛错而非回退。
   - U‑C1：FRF 同 pane 快速两次「计算」且参数相同时 facts 同步是否丢失。
   - U‑C2：宿主结果在 peer 聚焦时迟到绘制，facts 面板是否显示 peer 参数。
   - U‑C3：peer 聚焦时 duplicate 宿主，副本 params 是否被 peer 污染。
   - U‑K1：游标显示弹窗打开时切换 Pin 数值/完整，`apply_anchor` 是否撤销弹窗避让。
   - U‑K2：`frf_plot_host.schedule_alignment` 在 `apply_alignment` 之后再次排队是否覆盖跨
     pane 钉宽（与 K2 同类）。
   - U‑K3：`frozen_batch_acceptance.alignment_recorded` 跨 item any 的多 item 混合场景。
   - U‑S1：HEAD HDF simultaneous 规则（24 kHz / 72.2 s）的官方对照；在完成前 T14 的 changelog
     措辞按 spec §10.2 收敛。
4. 初始 A1–A11 均为 NOT RUN。

**T0 验证**：失败测试能稳定复现；未确认项有结论或明确「需真机」。本任务不跑全量。

## 3. T1 — 热图自然窗来自数据（H1 / H7 / H10，P1）

### 3.1 Red tests

- `tests/ui/test_heatmap_color_state_integration.py`：新增「两个自动色阶 View、数据相差 60 dB」
  用例，参数化 `section ∈ {fft_time, order}` × `mode ∈ {db, linear}`，切 A→B→A 后
  `_img.getLevels()` 等于该 View 自身 `_auto_db_window` / `_finite_data_bounds`。第二个 View 的
  params 必须改一个进入缓存键的字段（order 用 `max_order`，fft_time 用 `t_win_s`），否则两
  View 共用一条缓存掩盖问题。
- 同文件：dB → 线性 → dB 切换；分屏锁定 → 解锁；跨 View 锁定 → 结束对比。
- `tests/ui/test_heatmap_color_coordinator.py`：fake canvas 补 `_last_auto_levels` /
  `_z_color_auto` / `_color_window_policy` / `_matrix_disp`；新增「`_last_auto_levels` 带过期值」
  用例断言 `complete()` 不读它；`complete()` 返回 False 后 `_prepared` / `_pending_basis` 为空。
- `tests/ui/test_pg_heatmap_canvas.py`：`project_color_levels(auto=True, union)` 后
  `_automatic_color_window()` 不变。

### 3.2 最小实现

按 spec §3.1：`complete()` 的 `z_auto` 分支只经 `_automatic_color_window()`；确认
`_color_window_policy` 在 `plot_or_update_heatmap` / `plot_result` 两条路径都按本次
`amplitude_mode` 更新（`_remember_color_policy`）。评估删除 `_last_auto_levels`：唯一读者
`_fft_time_mixin.py:834` 若已被 `levels_are_resolved` 路径取代则一并删除；否则把它改为只由
`plot_*` 写、`project_color_levels` 不写。`reset()` 接入 `_clear_analysis_canvas` 或删除。

### 3.3 Gates 与出口

- Focused：上述三个文件 + `tests/ui/test_heatmap_color_projection.py`、
  `tests/ui/test_analysis_multiview_integration.py -k heatmap`。
- Boundary：`tests/ui/test_pg_canvas_backref_invariants.py`、
  `tests/ui/test_main_window_state_ownership.py`。
- A1 出口：四种模式切换、模式切换、锁定/解锁均为各自自然窗；fake canvas 与真画布字段一致。

## 4. T2 — 所有分析写入经 target（C1 / C2 / C4 / C5 / C6 / C7，P1）

### 4.1 Red tests

`tests/ui/test_analysis_view_comparison_regressions.py`，四分区参数化：

- peer 聚焦 → 删除 peer：`ctx.current_params()` == 宿主 params；`_capture_active_analysis_view`
  后宿主 `window` 不变。
- peer 聚焦 → 关闭其他（保留宿主，宿主索引 0）：同上。
- peer 聚焦 → 关闭全部 View（若有该入口）：同上。
- peer 聚焦 → 宿主画布 `analysis_range_adapter[1]({'x': (False, (10, 100))})`：宿主只有
  `x_auto/x_min/x_max` 变化；peer 不变；反向（peer 画布）只改 peer。
- FRF：peer 聚焦 → 触发宿主重算，`_frf_compute_values_for_state(host)` 返回宿主 `state.params`。
- `tests/ui/test_analysis_view_comparison.py`：双 pane peer 的外观事件路由到正确 pane；离开分区
  再回来 `_render_comparison_view` 每侧 1 次。

### 4.2 最小实现

按 spec §4.1：抽出单点「state → Inspector」投影入口并在 `_forget_analysis_view` 之后按
「peer 曾持焦点」条件调用；`_analysis_range_policy` / `_apply_analysis_range_policy` 改经
`_target_from_sender`；peer 卡片按 pane 索引绑定并挂范围适配器；`_frf_compute_values_for_state`
改 `_analysis_state_for_capture`；`_present_comparison` 跳过已渲染一侧；`id()` 键改代际。
新增信号连接一律 `functools.partial`。

### 4.3 Gates 与出口

- Focused：`tests/ui/test_analysis_view_comparison.py`、
  `tests/ui/test_analysis_view_comparison_regressions.py`、`tests/ui/test_analysis_time_isolation.py`、
  `tests/ui/test_frf_main_window.py -k compare`。
- Boundary：`tests/ui/test_main_window_state_ownership.py`、
  `tests/ui/test_no_lambda_signal_connections.py`。
- A2 出口：spec §4.2 表格全部成立；棘轮未放宽。

## 5. T3 — 对比关系随会话清理（C3，P2）

- Red：`tests/ui/test_session_reset_on_last_close.py` 新增「对比打开 → 关闭全部文件（keep /
  close 两种决定）→ `comp.relations_payload(sec) == {}` 且 Inspector 显示新默认 View」；
  `tests/ui/test_project_session.py` 新增「保存载荷不含悬空 host」。
- 实现：spec §5。
- Gates：上述两个文件 + `tests/test_project_io_analysis_views.py`；边界同 T2。
- A3 出口：两种决定均清空；重开工程无误报 toast。

## 6. T4 — 分析画布 log 刻度坐标统一（O1 / O5 / O8，P1）

### 6.1 决策记录

实施者先在本节记录选 A（统一坐标 + scale 进外观模型）还是 B（分析画布暂关 log）。选 B 时
必须同时登记 A 的后续 Task 与 owner，不得只留 B。

### 6.2 Red tests

- `tests/ui/test_pg_line_canvas.py`：log 模式下 `plot_spectra(y_min=1, y_max=100)` 后
  `get_engineering_ylim() ≈ (1, 100)`；自动量程下界 > 0；X 轴同理；
  `_fit_active_spectrum_y` 同样。
- `tests/ui/test_analysis_multiview_integration.py`：对话框设 log + 手动量程 → OK → 读回
  工程量程；重开对话框字段 == 输入。
- `tests/ui/test_view_appearance_isolation.py`：分析画布 View A log / View B linear 隔离；
  `tests/test_project_io_analysis_views.py`：`scale` 回环、缺键 = linear。
- `tests/ui/test_axis_handle*.py`：`_write_axis_limits` 对拒绝返回值有 `logger.warning`。

### 6.3 Gates 与出口

- Focused：上述文件 + `tests/ui/test_chart_options_capability.py`、`tests/ui/test_dialogs.py -k log`。
- Boundary：`tests/ui/test_pg_canvas_backref_invariants.py`（新增的画布状态若写穿宿主须声明
  `_owned_names`）；`tests/ui/test_pg_line_canvas.py::test_plot_spectra_returns_with_aa_off_and_discrete_timer_armed`
  必须继续通过——量程路径改动不得触碰 AA / 150 ms timer。
- A4 出口：spec §6.2。

## 7. T5 — 图表选项提交语义（O2 / O3 / O4 / O6 / O7，P2）

- 产品决策先于实现：按 spec §7 默认「无改动 OK 为 no-op」。若发版 owner 否决，在本节记录
  并改为「还原按钮在空提交后可用」的替代合同。
- Red：`tests/ui/test_dialogs.py`：手输 + Key_Up / 滚轮后 `value_for_commit()` == 显示值；
  颜色-only apply → 还原 → `apply_analysis_range_policy` 未被调用；
  `test_analysis_chart_options_unchanged_apply_reapplies_parameters` 改为断言 no-op（或按决策
  保留）。`tests/ui/test_analysis_multiview_integration.py`：用户缩放 → 开关对话框 OK →
  viewport 与 `viewport_origin` 不变；heatmap `cmap` 未改时 `chart_appearances` 为空；
  `z_*` 不被 capture 带回。
- 实现：spec §7；删除 `_store_heatmap_color_policy`。
- Gates：`tests/ui/test_dialogs.py`、`tests/ui/test_dialog_with_handle.py`、
  `tests/ui/test_analysis_multiview_integration.py`；若动了 hints/quickref（新增显式重置按钮），
  跑 `tests/ui/test_hint_nudges.py` 与 quickref 用例。
- A5 出口：spec §7 验收三条。

## 8. T6 — 协调器错误路径（H2 / H4 / H5 / H8，P2）

- Red：`tests/ui/test_heatmap_color_coordinator.py`：坏 preset（`z_floor >= z_ceiling`）经
  `preset_committed` 不抛到钩子、状态栏有反馈、`logger.warning` 一次；retain 判定
  （`_heatmap_picture_is_current`）后 `_prepared` 为空；fallback 参考下 `pane.heatmap_color_basis`
  保留。`tests/ui/test_heatmap_color_state_integration.py`：`_sync_active_analysis_params` 对
  非 policy `ValueError` 不吞。
- 实现：spec §8 前四条。
- Gates：两个文件 + `tests/ui/test_inspector.py -k preset`。
- A6（部分）出口：无未捕获 `HeatmapColorPolicyError`；无副作用判定。

## 9. T7 — 色条拖拽热路径（H3，P2）

- Red：`tests/ui/test_heatmap_color_coordinator.py` 计数：连续 50 次 `levels_changed` 期间
  `resolve_db_reference_for_source` 调用 ≤ 1、`commit` 在释放后恰好 1 次；
  `tests/ui/test_pg_heatmap_canvas.py`：拖拽期间画布 levels 实时跟随。
- 实现：拖拽中只投影，释放后 commit；`DbReferenceSettings.snapshot()` 脏标记缓存。
  **不得**调用 150 ms 空闲 timer 的 `start(int)`。
- Gates：两个文件 + `tests/ui/test_pg_timedomain_canvas.py::TestDiscreteSettle`（确认 timer
  interval 未被动过）。

## 10. T8 — 色板注册表惰性化（H6，P2）

- Red：`tests/test_heatmap_colormap_registry.py`：monkeypatch 资源缺失 / sha256 不匹配 /
  `pg.colormap.get` 返回 None 三种情况下 `import mf4_analyzer.qt_analysis_shared` 成功且解析
  到 `FALLBACK_HEATMAP_CMAP`，`logger.error` 一次；`tests/test_windows_build_script.py`：
  `--add-data` 源目录存在且与 `importlib.resources` 包名一致。
- 实现：spec §8 第五条；`SUPPORTED_HEATMAP_COLORMAPS` 消费者（对话框、Batch builder、
  `batch_render_smoke.py`、校验工具）同步改为调用。
- Gates：上述 + `tests/test_batch_render_import_boundary.py`、`tests/test_packaging_imports.py`、
  `tests/ui/test_colormap_parity.py`、`tests/test_batch_render_qt_heatmap.py`。

## 11. T9 — FRF Pin 来源状态（K1 / K5 / K6，P2）

- Red：`tests/ui/test_frf_pinning.py`：三种来源变体（角色互换 / 不同文件 / 空上下文）后卡片
  primary 含明确状态文案、`has_detail()` False；legacy role-less + swapped →
  `evaluate_intent` 为 None；重投影后 `frf_sample.channels` 不含时域占位行。
- 实现：spec §9 前两条。
- Gates：`tests/ui/test_frf_pinning.py`、`tests/ui/test_pinned_cursor_lifecycle.py`、
  `tests/ui/test_pinned_cursor_interaction.py`；若改了用户可见文案，同步 `ui/hints.py` /
  `ui/quickref.py` 并跑其用例。
- A7（部分）出口：三种变体文案；Cocoa 卡片截图列为待真机。

## 12. T10 — colorbar 对齐与卡片事务（K2 / K3 / K4 / K7，P2/P3）

- Red：`tests/ui/test_analysis_section_page.py`：在
  `test_split_fft_time_heatmap_and_slice_plot_areas_align` 之后追加 pane 1
  `_on_cbar_levels_finished` → 两 pane 主图宽度仍一致；
  `tests/ui/test_cursor_placement_stability.py`：N=4 一次 `_reproject_now` 中 `set_tethers` 1 次、
  `arrange_pinned_panels` 1 次；`tests/ui/test_cursor_content_stability.py`：ready → pending →
  ready 尺寸回落、pending 态 `_primary.minimumHeight() == 0` 且 `has_detail()` False；
  `tests/ui/test_cursor_layout_stability.py`：3000 次更新后测量缓存长度有界。
- 实现：spec §9 后三条。
- Gates：上述四个文件 + `tests/ui/test_cursor_table_geometry.py`、
  `tests/ui/test_pinned_cursor_geometry.py`；边界 `tests/ui/test_no_lambda_signal_connections.py`。
- A8 出口：计数与尺寸断言成立；原生 Cocoa 的卡片连续序列复测列为待真机。

## 13. T11 — HEAD HDF code page 与校验顺序（S4 / S7，P2/P3）

- Red：`tests/test_head_hdf.py`：`code page: 1252` + 非 ASCII 通道名可读，数据与时间轴与 936
  版本逐元素一致；未知 code page `errors="replace"` + warning；
  `tests/test_head_hdf_timebase.py`：`nbr of scans` 巨大但文件很小 → `ValueError`（数据错误）
  而非 `MemoryError`；时间轴只分配一次（用 `tracemalloc` 峰值或 monkeypatch `np.arange` 计数）。
- 实现：spec §10.2。
- Gates：`tests/test_head_hdf*.py`、`tests/ui/test_project_session.py -k hdf`；边界
  `tests/test_signal_no_gui_import.py`（IO 层不碰 UI）。
- A10 出口：两条红转绿；U‑S1 的官方对照状态写入 `.state` 并反映到 T14 文案。

## 14. T12 — 原生启动器加固（S1–S3 / S5 / S6 / S8–S13 / S17）

### 14.1 可移植部分（本机可验）

- `tests/test_startup_launcher_core.py` 编译器选择按 `clang++ → g++ → c++`；
  `native/startup_launcher/tests/test_core.cc` 加：深嵌套 JSON fail、`1e300` 版本号 fail、无换行
  长输入有界、`"0\n"` / `" 1 "` / 小写键的 panel 判定与 Python 一致、session 机新增
  `pipe_eof` / `timeout` 分支。
- `tests/test_startup_native_feedback.py`：EOF 与 watchdog 超时各有 caplog `warning` 断言；
  带 `dpi` / 坐标系字段的 `presented` 用例；`v` 非数字时 reader 线程不静默死亡。
- `tests/test_windows_build_script.py`：`launcher_win32.cc` 含 `_CRT_RAND_S`（或
  `BCryptGenRandom`）；生成目录与 `/Fo` 指向 `build\`；`.gitignore` 含 `*.obj`。

### 14.2 Win32 部分（需真机）

按 spec §10.1 修改 `launcher_win32.cc` / `launch_dispatch.cc` / `json_value.cc` / `protocol.cc`
/ `tools/*.ps1` / `tools/measure_windows_startup.py`。门禁：一次 `-NativeStartupLauncher` MSVC
构建成功；单屏 100%、主屏 150% + 副屏启动、Python 侧句柄打开失败（人为注入）三场景截图，
面板均在主窗显示后消失，主窗位置在可见区域。

### 14.3 Gates 与出口

- Focused：上述三个测试文件 + `tests/test_startup_import_boundary.py`、`tests/test_startup_timing.py`。
- Boundary：`tests/test_native_import_boundaries.py`。
- A9 出口：可移植 parity 全绿；Windows 三场景有截图。缺任一则报告「代码完成、Windows 验收
  待完成」，原生启动器继续不进发布说明。

## 15. T13 — 唯一全量集成门禁

仅在 T1–T12 中已完成的任务合入同一稳定快照后由协调者跑一次，按 CLAUDE.md / AGENTS.md 的
两条命令串行前台执行（主体 `--ignore=tests/acquisition_ui`，再单跑该目录）。跑前跑后记录
`HEAD` 与脏文件范围；期间相关文件被改即 `UNVERIFIED`。见红先对照
`docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6 与
`docs/analyzer/verify/2026-10-05-full-suite-failure-triage.md` 的既有红清单，不把既有红算到
本轮头上。`pgrep -fl pytest` 确认无并行全量。

## 16. T14 — 文档、changelog 与低风险加固

- changelog / README：按 spec §11 补 8.4.2 之后四个功能；HEAD 色板默认对旧工程的影响（H9）；
  HEAD HDF 时间措辞按 U‑S1 状态收敛。若发版 owner 决定升 8.4.3，走 CLAUDE.md 列出的全部
  扇出面与四个测试契约（`test_help_content.py`、`test_windows_build_script.py`、
  `test_packaging_imports.py`、`ui/test_project_session.py`）。
- 在本节登记 S15「HDF 指纹核验未接线」为已知未实现；**不改**
  `2026-09-25-head-hdf-timebase-robustness-plan.md`。
- macOS 帮助（S14）：`Popen` / `openUrl`、`dirs_exist_ok` 或临时名 + rename、旧 stamp 清理；
  `tests/test_help_browser_open.py` 加「dest 已存在且缺文件 → 重建」用例，macOS 专属路径仍
  按平台 skip 并单列未验收。
- 工具栏历史栈 / 分屏 / cards（O10 / O11 / O12）与 `line_canvas._apply_title_text` 的宽泛
  except（O9）：`tests/ui/test_toolbar_section_contract.py` 加「回到基线发 home、切 View 清栈、
  `ChartStack.exit_split` 丢弃挂起手势」；except 收窄为 `RuntimeError` 并注明 wrapper 已删。
- 本任务中纯文档改动（changelog / README / 本 plan 登记）只需 `git diff --check` 与
  `tests/test_help_content.py`；不需要其他运行时测试。

## 17. 本次文档交付的验证

本次只新增两份文档，无可执行行为改动：

- 检查 spec / plan 引用的符号在 HEAD 存在（已逐一 `rg` 核对；`sync_heatmap_layouts` 为页面侧
  分屏对齐入口的真实名称）。
- `git diff --check` 通过。
- 未运行全量套件；复审期间运行的聚焦测试与探针（热图自动窗四组合、FFT log 量程、对比四分区
  H1–H5、chart options 171 项 focused 基线、启动器 / HDF / 帮助 287 项 focused）均在 HEAD
  `4667dd06` 的干净工作区完成，仅作为问题存在性证据，不作为任何 Task 的通过证据。
