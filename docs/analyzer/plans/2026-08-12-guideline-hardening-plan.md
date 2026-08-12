# Guideline 驱动的全局加固 —— 实施 plan

**关联**：`docs/analyzer/specs/2026-08-12-guideline-hardening-spec.md`（方向性决策，
执行偏离先回 spec 补记）；隐患编号（A1…E9）见
`docs/analyzer/reviews/2026-08-12-optimization-commit-pattern-review.md` §4。

**基线 HEAD**：`cf530b92`（v7.9.9）。测试基线（2026-08-12 实测）：主体
`--ignore=tests/acquisition_ui` **6048 passed / 11 skipped / 0 failed / 0 errors**，
`tests/acquisition_ui` 单独 **355 passed**。

---

## 0. 执行 agent 必读（每个 Task 通用）

- **环境**：本机验证一律用仓库 venv 的**绝对路径**
  `"/Users/donghang/Downloads/data analyzer/.venv/bin/python"`（worktree 里没有
  `.venv`，相对路径必挂）。Qt 用例前缀 `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen
  PYTHONPATH=.`。
- **起点核对**：动手前 `git log -1 --format=%H` 确认基于 `cf530b92` 或其后代；
  若 worktree 落后，先 `git merge --ff-only main` 补齐。**动手前先跑本 Task 的
  聚焦测试记下失败数**，别把既有失败算到自己头上。
- **全量验证要分两条命令**：裸 `pytest -q` 会在 `tests/acquisition_ui` 段交错
  segfault。主体用 `--ignore=tests/acquisition_ui`，该目录另起一条单独跑。
- **禁区**：不删 `tests/ui/conftest.py` 的顶层 widget pin 逻辑；不删仓库根
  `conftest.py`；不放宽任何机械护栏（状态所有权棘轮 shrink-only、backref 白名单、
  import 边界、parity）；不改 ink/AA 常量数值；不放宽性能门禁。
- **RED→GREEN**：每个 Task 先写复现测试（红），再修（绿）。UI/视觉类改动
  offscreen 只能当排版草稿，收尾在真机验证一次（macOS Cocoa）。
- **提交粒度**：每个 Task 独立提交（或按 Task 内小节拆分），提交信息引用
  隐患编号（如 `fix(ui): A1 时域 View 捕获加 mode 守卫`）。
- 若改动了 UI 交互（新增提示/文案变化），收尾跑一次 `/update-hints` 核对两个
  发现性面是否需要同步。

---

## P0 批（数据正确性，先做）

### Task 1: 时域 View 捕获守卫 + 「全部」三分区作用域（A1、A2、F11）

**Files**: `mf4_analyzer/ui/main_window/_view_mixin.py`（`_capture_focused_view`）·
`window.py`（`_plotted_time_extent`、`_on_time_range_max_requested`）·
`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` · `frf_canvas.py` ·
`mf4_analyzer/ui/main_window/_channel_scope_mixin.py`（`_on_source_load_finished`）

- [ ] `_capture_focused_view` 开头加 `if self.chart_stack.current_mode() != 'time':
  return`（修在函数内部，不逐调用点补——三个出口 `_project_io_mixin.py:1447` /
  `window.py:3841` / `window.py:1711` 同根因）。
- [ ] RED 测试：FFT 模式下 attach 子集文件 → `save_project` → 断言 Time View 1 的
  `attached_file_ids`/`checked`/`colors` 未被分析投影覆写（现有
  `test_project_session.py:346` 只断言 mode 与文案，不够）。
- [ ] `PgHeatmapCanvas`/`PgFrfCanvas` 补「已绘数据 X 范围」getter（与
  `get_data_x_union` 同契约，无数据返回 None）；`_plotted_time_extent` 回退链
  插在 `_time_data_extent()` 之前。全局兜底保留（空画布仍合法）。
- [ ] RED 测试：长短两文件，阶次/时频/FRF View 只 attach 短文件 → 「全部」→
  时间范围为短文件时长（照 `cf530b92` 的测试样式，三分区各一条）。
- [ ] F11：`_open_data_paths` 多文件循环给 `_load_one` 传 `notify=False` 类机制，
  循环后聚合一条「已加入 … · N 个文件」toast（照 `_close_files` 的 notify 先例，
  单文件路径行为不变）。
- [ ] 验证：`tests/ui/test_project_session.py` + 新增用例 + 状态所有权棘轮
  `tests/ui/test_main_window_state_ownership.py`。

### Task 2: 工程文件 ylims 重映射与恢复侧校验（A3、B6）

**Files**: `mf4_analyzer/ui/project_io.py`（`remap_view_fids`）·
`mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
（`_filter_time_view_state_for_removed_fids`）· `mf4_analyzer/ui/view_state.py`
（`_coerce_pair`）· 参考 `mf4_analyzer/ui/pg_canvas/_shared.py`（key 编码）

- [ ] `remap_view_fids` 解码 ylims key（`json.loads` → `[fid, name]`）、重映射 fid、
  重编码；老工程无 ylims 时兼容跳过。
- [ ] 关文件清理路径扫 ylims，删被关 fid 的条目。
- [ ] `_coerce_pair` 补校验：`float()` 转换 + `isfinite` + 相对容差退化判定
  （复用 `ui_kit/ticks_math._DEGENERATE_SPAN_RATIO`，**不要发明新阈值**），
  非法返回 None（恢复侧静默跳过该项，走自动取景）。
- [ ] RED 测试：保存→重开，断言逐通道 Y 缩放存活（现在必红）；含残差 span 的
  旧工程 dict 直接喂 `from_dict`，断言不还原病态窗口。
- [ ] 验证：`tests/ui/test_project_session.py` 全文件 +
  `tests/ui/test_pg_timedomain_canvas.py -k ylim`。

### Task 3: 异步结果按派发 view_id 路由绘制（A7、F13）

**Files**: `mf4_analyzer/ui/main_window/_order_mixin.py`
（`_on_order_job_finished`）· `_fft_time_mixin.py`
（`_on_fft_time_render_requested`）· `_analysis_mixin.py`（`_on_analysis_split`）

- [ ] 两个回调里比对 `ctx.get('view_id')` 与该分区 manager 的 active view_id：
  不一致时**只跳过绘制**——`_store_analysis_result` 的缓存/pin 落盘保持原样
  （dispatch-time view_id 那半本来就对）。参考 `fft_time_coordinator.py:47` 注释。
- [ ] F13：`_on_analysis_split` 退出分屏时 fft_time/order 也失效 pane-1 的 pin
  （现在只有 FRF 走 `invalidate_pane`）。
- [ ] RED 测试：伪造慢 job——派发后切 View 再回调，断言画布未被旧 View 结果改写、
  缓存仍按派发 view 存储；切回后 `_render_analysis_view_from_cache` 能取到。
- [ ] 验证：`tests/ui/test_main_window_smoke.py -k "order or fft_time"` +
  相关 coordinator 测试。

### Task 4: 程序化 apply 守卫补全（A8、F8、F10、F14）

**Files**: `mf4_analyzer/ui/main_window/window.py`
（`_apply_audio_weighting_default`）· `_view_mixin.py`（`_on_view_split`）·
`mf4_analyzer/ui/inspector_sections/persistent_top.py`（`set_range_limits`）·
`window.py:997/1028`（rename 链）

- [ ] `_apply_audio_weighting_default` 开头判 `_applying_analysis_view` 早退。
  **产品语义不变**：加载音频时默认 A 计权照常（该路径不在 apply 区间）。
  RED 测试：音频文件 + FFT View 的 weighting=None → 切走切回 → 断言 weighting
  仍为 None 且 UI 与 state 一致。
- [ ] F8：`_on_view_split` 两处 else 拆开「无文件」与「非时域」（照
  `_apply_active_view:228-239` 已修形状）；`_render_view_to_canvas` 的 finally
  投影加同款 mode 判断。
- [ ] F14：`set_range_limits` 的 `sp.setRange()` 包 blockSignals（当前无订阅者，
  属排雷；加一行注释说明为什么）。
- [ ] F10：View 重命名后刷新 navigator empty-state 文案（rename 信号链上补一次
  `set_empty_state_context`）。
- [ ] 验证：`tests/ui/test_main_window_smoke.py` + `tests/ui/test_inspector.py` +
  新增用例。

### Task 5: IO 头部容错与估算标注（A4、A5、P3 小项）

**Files**: `mf4_analyzer/io/zfd_format.py` · `head_hdf.py` · `loader.py` ·
`source_adapters.py`

- [ ] A4：ZFD `dt` 接受区间改「有限且 `0 < dt <= 3600`」；≤1 Hz 慢采样文件不再
  被压成 1 kHz。构造测试文件覆盖 dt=2.0（0.5 Hz）。`fs_estimated` 的 UI 出口在
  Task 11 接（本 Task 先保证标记正确写入 metadata）。
- [ ] A5：`ch order` / `nbr of scans` 缺失时抛头部级错误，消息指明缺失行名，
  不再让 demux 静默跳过；`factor_by_ch.get(i, 1)` 命中默认值时把「factor 系推测」
  记入 `source_metadata`。
- [ ] `.asc` 嗅探：`source_adapters.py:648-654` 的外层 `except` 收窄——
  `ImportError` 单独接住并转成指向 python-can 缺失的明确报错，不再送 ASCII 解析器。
- [ ] MDF 元数据：`source_adapters.py:260-268` 查找失败时单位记为 None 而非 ""
  （与「本来无单位」可区分），下游显示逻辑核对 None 处理。
- [ ] 验证：`tests/test_zfd_format.py` `tests/test_head_hdf*.py`（按实际文件名）
  `tests/test_loader*.py` + `tests/integration` 相关。

---

## P1 批（安全网与真值收口）

### Task 6: 渲染安全网——未知不当零（B1-B5、B7）

**Files**: `mf4_analyzer/ui/pg_canvas/quality.py` · `renderer.py` · `canvas.py` ·
`mf4_analyzer/qt_analysis_shared.py`

- [ ] B1：`canvas.py:607` 消费 `install_frame_paint_timer` 返回值，失败
  `logger.warning` 留痕；新增哨兵测试在真 canvas 上断言 `_note_aa_frame` 会被
  调用（backstop 存在性断言）。
- [ ] B3：`_line_ink_now` 测量失败返回 `None`（不是 0.0）；
  `_frame_native_ink_total` 对 None 的语义=「本帧不放行 AA」，**不写入**
  `_line_ink_state`。⚠️ 教训边界：失败路径只覆盖真异常，别把首帧正常路径卷进来
  （`0c07517a` 曾因「无记录一律拒绝」34 条用例转红）。
- [ ] B2：`renderer.py:568-573` `get_ylim()` 失败时跳过 ink 记录（不写 0.0）；
  删掉「y_span 0.0 reports zero ink」那句把 bug 当特性的注释。
- [ ] B4：`_quantize_y_span_key`/`_view_signature` 的退化哨兵与 `log2(1.0)=0`
  分离（独立哨兵值）。
- [ ] B7：`quality_status` 里 `density["error"]` 分支挪到 raster-cost 之后，
  恢复「解释顺序==决策顺序」不变量；该不变量补一条测试。
- [ ] B5：`_finite_data_bounds`/`_slice_autorange` 引入相对容差退化判定；
  全非有限返回哨兵而非 0..1。下游（热力图色标、切片）按「无数据」分支处理。
- [ ] ⚠️ 常量是标定值：本 Task 不改任何 `_INK_*` 阈值数值。
- [ ] 验证：`tests/ui/test_pg_timedomain_canvas.py`（含 TestInkBudget）+
  `tests/ui/test_pg_quality*.py` + `tests/test_batch_qt_render_parity.py`。

### Task 7: GUI ↔ batch 常量收口（C1、C3-C5、C8、C9、C12、C13）

**Files**: `mf4_analyzer/batch_render_qt/_page.py` · `_builder.py` ·
`mf4_analyzer/qt_analysis_shared.py` · `batch_compute.py` ·
`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` · `frf_canvas.py` ·
`batch_render_qt/_palette.py` · `ui/main_window/_order_mixin.py`

- [ ] C1：`_page.py:155` 的 `point_size=9.0` 改用 theme 字号（随 `scaled_fonts`
  缩放）；补测试：`font_scale=1.5` 时该标签字号同步放大。
- [ ] C3：`_AUTO_SPAN_DB`/`_AUTO_CEILING_PERCENTILE` 上提 `qt_analysis_shared`，
  `_builder.py` 改 import（函数级分叉照 shared docstring 维持，只收常量）。
- [ ] C4：删 `_DISPLAY_DEAD_SPAN_DB`，改用已 import 的 `_SLICE_MAX_SPAN_DB`。
- [ ] C5：`batch_output_scale` 委托 `batch_render_qt.contract.render_in_db`
  （让 `batch.py:155` 的注释成真）；`amplitude_axis` 腿保留。
- [ ] C8：`interp` 默认值与平滑集合收进 `qt_analysis_shared`，两侧 import。
- [ ] C9：`amplitude_mode` 判据收成共享 helper，三种方言（`'db' in`、
  `== "amplitude_db"`、`== 'Amplitude dB'`）全改调用；Order 批处理缺省对齐
  GUI 侧（dB）——这是 parity 修复不是行为新增，提交信息里写明。
- [ ] C12：`frf_canvas.py:571` 改调 `_is_log_frequency()`；`set_display_params`
  对 `frequency_scale` 做 `.strip().lower()` 归一化（对齐批处理侧
  `BatchFrfFigureSpec.__post_init__`）。
- [ ] C13：默认改 `_palette.py` docstring 承认分叉（spec §5-2 裁决前不动色值）。
- [ ] 验证：`tests/test_batch_qt_render_parity.py` +
  `tools/verify_batch_qt_render_parity.py` 真跑一遍 + `tests/test_batch_*` 相关。

### Task 8: verify 工具回读原则（C2、C3 parity 侧）

**Files**: `tools/verify_frozen_batch_render.py` · `mf4_analyzer/batch_render_smoke.py` ·
`tools/verify_batch_qt_render_parity.py`

- [ ] C2：frozen 验收的 turbo 端点 RGB 改运行时从 `pg.colormap.get("turbo")` 回读
  （`cmap="turbo"` 道具参数保留——道具常量由测试钉死是对的，RGB 期望必须回读）；
  另补一条**出货默认 gnuplot2**（本地 LUT 路径）的冻结断言（端点纯黑/纯白，
  选图内非文字区采样点避开底色混淆）。
- [ ] parity 工具 `:232-235`：99.0/30.0 改 import Task 7 收口后的共享常量；
  `'gnuplot2'` 字面量改用已 import 的 `DEFAULT_HEATMAP_CMAP` 拼接。
- [ ] 在两个工具头部注释写明「参照值必须从产品回读，禁止字面量重声明」契约
  （引用本 spec §3.3）。
- [ ] 验证：两个工具各真跑一遍全绿；`tests/test_windows_build_script.py`
  `tests/test_packaging_imports.py` 不受影响。

### Task 9: 散落默认值收口（C6、C7、C10、C11、P3 格式化小项）

**Files**: `mf4_analyzer/ui/pg_canvas/tick_density.py` · `overlay_axes.py` ·
`analysis_axes.py` · `mf4_analyzer/ui_kit/qt_chart_fonts.py`（按实际文件名）·
`batch_compute.py` · `ui/drawers/batch/method_buttons.py` ·
`ui/main_window/_fft_mixin.py` · `_fft_time_mixin.py` · `_order_mixin.py` ·
`ui/pg_canvas/context_menu.py`

- [ ] C6：`tick_density.py:42-43` 改 import `DEFAULT_CHART_TICK_DENSITY`
  （注意 import 方向：`chart_stack/toolbar.py` → 若形成环，把常量下沉到
  更低层模块再双向 import）。
- [ ] C7：`qt_chart_fonts` 增 `CHART_FONT_PT = 9.0`，三个函数签名默认 + 三处
  `_pg_chart_font(9)` 量测点全部引用；补测试断言量测与渲染引用同一符号。
- [ ] C10：overlap 归一化收成一个共享 helper（含 `>1 → /100` 启发式 + `[0,0.95]`
  钳位），三处改调用；`avg_overlap`/`overlap` 两 key 现状保留（key 合并涉及
  序列化兼容，超出本次范围，helper docstring 记录）。
- [ ] C11：`coherence_threshold` 与窗函数默认/候选顺序收具名常量（放
  `signal/analysis_defaults.py`，纯常量无 GUI import——注意
  `tests/test_signal_no_gui_import.py` 会看守）；**只收敛声明不改数值**；
  五处 0.8 与候选列表全改引用；`flattop` 排序不一致以多数派（第 6 位）定版。
- [ ] `db_reference` 五行双胞胎回退（`_fft_time_mixin.py:483` /
  `_order_mixin.py:508`）收成一个 helper。
- [ ] `context_menu.py:374`：分支判据照 `_fmt_rate` 修法（按格式化后的值分支）。
- [ ] 验证：相关单测 + `tests/ui/test_import_boundaries.py` +
  `tests/test_signal_no_gui_import.py`。

### Task 10: 批处理 warnings 出口 + 静默重建（D1、D2、A6）

**Files**: `mf4_analyzer/ui/drawers/batch/sheet.py`（`_show_result_toast`）·
`task_list.py` · `mf4_analyzer/batch.py`（`:5052-5079`、`:5386`）·
`batch_compute.py`（`uniform_time_axis_for_spectrogram`）· `batch_statistics.py`

- [ ] D1：Run 完成的 toast/footer 与 task_list 行 tooltip 渲染
  `BatchRunResult.warnings`；>3 条折叠为「N 条警告，详见 manifest」。
  ⚠️ 只补消费端渲染，不新增 emit——进度/结果单点走 `_RunReporter` 的纪律由
  `tests/test_batch_run_reporter.py` 看守。
- [ ] D2：统计诊断 `{code,message,suggestion}` 结构完整下传（`batch.py:5079`
  不再只取 code），UI 渲染 message+suggestion；humanizer 正则不改。
- [ ] A6：`uniform_time_axis_for_spectrogram` 返回值加 warnings；重建时产出与
  FRF 同格式审计警告；改写后 fs 回写 `effective_params`（manifest 与实际一致）。
  RED 测试：抖动轴批处理 → manifest 含重建警告且 fs 为重建值。
- [ ] 验证：`tests/test_batch_run_reporter.py` + `tests/test_batch_*` +
  `tests/ui/test_batch_toolbar.py` 族。

### Task 11: IO 加载诊断 UI 出口（D3、D4、A4 出口侧）

**Files**: `mf4_analyzer/ui/main_window/_project_io_mixin.py`（各格式加载分支）·
`mf4_analyzer/io/loader.py` · `wwt_format.py` · `mat_format.py`

- [ ] 照 HDF `dropped_channels` → `format_dropped_channels_notice` → toast 模板，
  接通：WWT `skipped_channels`、MAT `skipped_vars`、ZFD `fs_estimated`
  （文案必须含「估算」，如「⚠️ ZFD 时基无效，按 1 kHz 估算显示」）。
- [ ] TDMS：`loader.py:251-256` 的 continue 先补跳过载荷（原因分类：非一维/空/
  非数值）再接同一出口。
- [ ] D4：三处重名去重把改名映射记入 `source_metadata`，加载后单条汇总提示
  （「N 个通道重名，已加序号区分」）。
- [ ] 验证：`tests/test_wwt_format.py` `tests/test_mat_format.py`
  `tests/test_zfd_format.py` + `tests/ui/test_project_session.py` 相关 +
  真实样本（`testdoc/` 本机可用时）冒烟。

### Task 12: 异常分派结构化 + 通道编辑器消息宿主（D10、D11）

**Files**: `mf4_analyzer/signal/frf.py` · `batch_compute.py` ·
`mf4_analyzer/ui/main_window/_frf_mixin.py` · `_project_io_mixin.py`（`:405-414`）·
`ui/channel_editor_drawer.py` · `window.py`（导出 handler 族）

- [ ] D11：FRF cancelled/overflow 改自定义异常类型（`signal/frf.py` 定义并抛，
  `batch_compute.py:310/314` 按类型接）；`FrfPreflightError` 加 `code` 字段，
  `_frf_mixin.py:413` 按 code 分派（中文子串匹配删除）；
  `_project_io_mixin.py:408` 的 TypeError 措辞探测改 `inspect.signature` 预检。
  ⚠️ `signal/` 禁 GUI import 的边界不变（异常类定义在 signal 侧没问题）。
- [ ] D10：通道编辑器抽屉照 BatchSheet 先例自持 toast（`isVisible()` 时 own、
  关闭后回落 parent）；模态期间的 statusBar 消息随 toast 一并自持展示；
  `_on_export_clicked` 的 emit/accept 顺序不动（导出期间保持打开是刻意交互）。
  验证方法照 `38d1c81a`：`grabWindow` 真实层叠截图，**不是** `widget.grab()`。
- [ ] 验证：`tests/signal/test_frf*.py` + `tests/ui/test_channel_editor*.py` +
  `tests/test_batch_compute*.py`（按实际文件名 `pytest --collect-only -q` 先查）。

---

## P2 批（文案、物理层、生命周期）

### Task 13: 文案与实现对齐（D5-D9）

**Files**: `mf4_analyzer/ui/inspector_sections/contextual_fft.py` ·
`contextual_fft_time.py` · `contextual_order.py` · `help/frf-guide.html` ·
`ui/drawers/batch/analysis_panel.py`

- [ ] D5（默认按 spec §5-1 文案如实化，owner 另有裁决除外）：FFT「重叠」tooltip
  与摘要如实说明当前作用域；不接线、不删控件。
- [ ] D6：两处「自动 NFFT」tooltip 重写：单帧=整段 FFT；平均模式下按窗长起步、
  经 min_frames/数据长度上限/[64,8192] 收敛。删掉指向不存在「窗长」控件的表述。
- [ ] D7：`order_res`/NFFT tooltip 补条件限定（自动 NFFT 下 `order_res` 反向驱动
  nfft；手动 NFFT 下仅为插值网格，不增加信息）。文风照 `contextual_frf.py:44-62`。
- [ ] D8：`help/frf-guide.html:116` 行标签「数据被阻断」→「自动重建」。
  ⚠️ help 内容变更后跑 `tests/test_help_content.py` 契约；只改内容不动版本字段。
- [ ] D9：placeholder `"0.0, 120.0 s"` 去单位 → `"0.0, 120.0"`；错误文案补
  「数字不要带单位」。
- [ ] 验证：`tests/ui/test_inspector*.py` + `tests/test_help_content.py` +
  批处理面板相关单测；文案改动跑 `/update-hints` 核对。

### Task 14: QSS 物理层 + 机械护栏（E1、E2）

**Files**: `mf4_analyzer/ui_kit/style.qss` · 新增 `tests/ui_kit/test_qss_border_shorthand.py`

- [ ] E1：`channelTree::item:selected`（含 `::branch:selected`）补自身
  `border-radius`（父 9px − border 1px = 8px 或按视觉取 6px）或 viewport 内缩；
  真机像素验证照 `f4a6b923` 的角部墨迹比值法。
- [ ] E2：9 处 `border:` 简写改 `border-color:`（`:1827` dropActive、`:3045/3051`
  plotRiskLabel、`:2406/2416` preset-load、`:2267` dbReferenceEditor error、
  `:813` navActive、`:1206` segment:checked、`:1123` role="tool"、`:2935/2944`
  ChannelEditorDialog、`:2650/2655` cursorPill 死代码顺手清理）。
- [ ] 新增机械护栏：解析 `style.qss` 的 lint 测试——状态选择器规则块内出现
  `border:` 简写且其基线块声明过 `border-radius` 即红；白名单空起点、
  只许缩小（照棘轮范式）。
- [ ] 验证：`tests/ui_kit/` 全目录 + 真机截图核对拖拽悬停/风险 pill/预设 applied
  三个此前「未爆」状态。

### Task 15: 消息框 fit / Elide / Toast 派生 / Inspector 栈（E3-E6）

**Files**: 见 E3 清单 7 文件 · `ui/file_navigator.py` · `ui/widgets/db_reference.py` ·
`ui/widgets/toast.py` · `window.py:450` · `markup/editor.py` ·
`drawers/batch/sheet.py:1569` · `ui/inspector.py`

- [ ] E3：13 个按钮补 `fit_message_box_buttons_to_text`（清单见 review §4.3-E3；
  `_channel_scope_mixin.py:246/518` 文案最长优先）。
- [ ] E5：`file_navigator._ElidedLabel` 与 `db_reference._reflow_source_text` 改
  `ElideMiddle`（tooltip 保留）。
- [ ] E6：Toast 让位改「显示时从真实邻居高度派生」——主窗按底部 chrome 实高求和；
  `sheet.py` 在 `_present_footer` 状态变更时重派生；`markup/editor.py` 按自身
  toolbar 实高。`DEFAULT_BOTTOM_MARGIN` 降级为最终兜底并注明。
- [ ] E4：`Inspector.contextual_stack` 照 `_TargetStack`（`input_panel.py:70-98`）
  补 sizeHint/minimumSizeHint 取当前页 + `currentChanged` invalidate。
  ⚠️ 与首开压扁修复（`b5ec2969` 的 `_settle_page`）共存，回归测试两个方向都要跑：
  `tests/ui/test_inspector_first_show_layout.py` + 新增「切到矮页无死白」用例。
- [ ] 验证：`tests/ui/test_inspector*.py` + toast/messagebox 相关单测 + 真机核对。

### Task 16: 生命周期清理 + 棘轮（E7、E8、E9）

**Files**: `ui/chart_stack/stack.py` · `ui/inspector_sections/contextual_{order,fft,fft_time}.py` ·
`ui/analysis_section_page.py` · `acquisition_ui/main_window/_toolbar_mixin.py` ·
`acquisition_ui/widgets/left_pane.py` · `drawers/batch/*.py` ·
`inspector_sections/time_filter.py` · `ui/inspector.py` ·
`ui_kit/widgets/searchable_combo.py` · 新增共享 `_weak_bound` 工具 ·
新增 `tests/ui/test_no_lambda_signal_connections.py`

- [ ] E8：30 处 `.connect(lambda *_: ...)` 改信号对信号直连（PyQt 允许参数截断）
  或 bound method；带常量参数的 relay 用 `functools.partial`（partial 持有的是
  bound method 引用，仍需确认 receiver 生命周期——inspector 5 处 relay 建议改
  ctx 侧信号签名）。
- [ ] E7：`sheet.py` 的 `_weak_bound` 上提为共享工具（建议
  `mf4_analyzer/ui_kit/qt_lifecycle.py`）；9 处 bound-method 存储改 WeakMethod：
  `chart_stack.set_secondary_replot_callback`、三个 `set_auto_nfft_provider`、
  `analysis_section_page.py:291-312` 的 4 处 + lambda、
  `left_pane.set_pin_state_provider`、`input_panel.set_source_context` 的自环。
- [ ] 新增棘轮：AST 扫描 `ui/`+`acquisition_ui/` 的 `.connect(lambda`，冻结
  文件→数量白名单，shrink-only（照 `test_main_window_state_ownership.py` 范式；
  清理完成后白名单应为空或接近空）。
- [ ] E9：`searchable_combo` 的 `_highlight_char_indexes`/`_split_combo_label` 按
  `(text, query)` 缓存；QFont/QColor 提类属性；`casefold()` 移出循环。
  ⚠️ 这是性能修理，不是 GC 段错误的修法（triage 文档明令不许靠减分配防复发）。
- [ ] 验证：`tests/ui/test_batch_*`（BatchSheet teardown 簇曾是同因，全部要绿）+
  `tests/acquisition_ui` 单独进程 + 新增棘轮测试。
  ⚠️ 高风险回归面：信号改直连后参数个数/顺序变化要逐个核对 slot 签名。

---

## 收尾（全部 Task 完成后）

- [ ] 两条命令跑全量：主体 `--ignore=tests/acquisition_ui` 与
  `tests/acquisition_ui` 单独，对照基线（6048/11/0 + 355）只增不减。
- [ ] `tools/verify_batch_qt_render_parity.py` 与
  `tools/verify_frozen_batch_render.py` 真跑全绿。
- [ ] 真机（macOS Cocoa）走查：channelTree 选中角部、三个「未爆」QSS 状态、
  通道编辑器导出 toast、Inspector 四页切换、批处理 Run warnings 展示。
- [ ] CLAUDE.md 基线段落若失败数变化需同步；新增机械护栏在 CLAUDE.md
  「机械护栏」节补一行（QSS border lint、lambda 连接棘轮、paint 计时器哨兵）。
- [ ] 汇总提交评审记录（照 review 目录惯例追记到 pattern-review 文档 §6）。
