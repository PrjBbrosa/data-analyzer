# Repository Instructions

**Project:** TraceLab / MF4 Data Analyzer — PyQt5 桌面 GUI，做工程测量数据的导入、
时域/频域/阶次分析、批处理，以及 CAN/XCP 采集回放。版本单一事实源是
`mf4_analyzer/app_meta.py` 的 `APP_VERSION`（当前 v7.9.9），别在别处硬编码版本号。
升版本要同步的扇出面：`README.md` · `docs/analyzer/README.md` 的 Current Product
Baseline · `mf4_analyzer/help/` 下使用说明（`meta.version`/`versionLabel`/`updated`
+ changelog 新增条目）与四个分析指南 · `docs/analyzer/user-guide/user-guide.html` ·
`tools/build_windows_folder*.ps1` 的 `$Version` · `tools/run_windows_exe.bat` 的
`APPNAME` · 四个测试契约（`test_help_content.py` · `test_windows_build_script.py` ·
`test_packaging_imports.py` · `ui/test_project_session.py`）。
`docs/analyzer/specs|plans|acquisition/` 下的历史文档记录当时状态，**不要**跟着改
（唯一例外：`acquisition/runbooks/stage-8-pr4-bench.md` 的构建路径被
`test_windows_build_script.py` 契约钉在当前版本上，升版要同步）。

## Dev commands
```bash
pip install -r requirements.txt   # 依赖；Windows 采集另见 requirements-windows-acquisition.txt
python "MF4 Data Analyzer V1.py"  # 启动 GUI（薄启动器 → mf4_analyzer.app.main）
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest
pytest -m slow                    # 仅性能/长跑用例（pytest.ini 默认 -m "not slow"）
```
- 本机验证走仓库 venv（`.venv/bin/python`）；裸 `python` / `pytest` 未必存在。
- Qt 用例需要 offscreen 平台；`TMPDIR=/tmp` 用来绕开下面 Gotchas 里的 TCC 问题。
- 默认套件约 6400 条，主体约 7 分钟 + `tests/acquisition_ui` 约 15 秒（2026-08-11 本机实测；
  早先记的「近 20 分钟」已不成立）。仍建议改动局部时先跑对应子目录，收尾再跑全量。
- **全量要分两条命令跑**：裸 `pytest -q` 会在 `tests/acquisition_ui` 段被 pyqtgraph
  `LabelItem.resizeEvent` 的 `RuntimeError`（已删 `QGraphicsTextItem`）打成 **segfault**，
  约 4% 处中断、无汇总。交错相关——单独跑该目录不崩。要拿全量数字：
  `--ignore=tests/acquisition_ui` 跑主体，另起一条单独跑该目录。
- **动手前先记下当前失败数**，别把既有失败算到自己的改动头上。
  当前基线（2026-08-12 实测，HEAD `56c42f4d`）：主体 **6048 passed / 11 skipped /
  0 failed / 0 errors**，`tests/acquisition_ui` 单独 **355 passed**。
  **不要把 6048/0 抄到 `cf530b92`**：`56c42f4d..cf530b92` 已有 8 条红（parity Y-tick
  分叉、selection_signature QSS token、drawers 几何、hints 三条）；其中
  characterization 一条被 `eab5600d` 重钉转绿。guideline-hardening 16-Task 批在
  `eab5600d` 套件层面零新增失败。F1–F8 follow-up 收口（`guideline/followup-f1-f8`）：
  主体 **6230 passed / 12 skipped / 0 failed**（跟踪树；未跟踪 UltraView 会让
  `test_search_field` 扫到裸 `QLineEdit` 搜索框，不计入本批），
  `tests/acquisition_ui` **359 passed**。详见
  `docs/analyzer/plans/2026-08-13-guideline-hardening-followup-plan.md` §5。
  2026-08-15 post-v8-review-fixes 合入后实测:主体 **6978 passed / 13 skipped /
  9 failed**——9 条全部是完整顺序下的既有顺序污染(单跑/子集跑全绿,清单见
  `docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6,待专项治理),
  `tests/acquisition_ui` **359 passed**。
  2026-08-15 `feat/view-switch-quality-settlement`(基于 `380e5ac2`)实测:主体
  **7046 passed / 24 skipped / 11 failed**——9 条同上顺序污染 + 2 条 `380e5ac2`
  干净树上就红的 `test_qss_palette_ratchet` / `test_qss_selector_liveness`(那次
  ultraview 提交引入,非本分支);`tests/acquisition_ui` **359 passed**。
  主体一条命令在 `f85b5d4e`..`56c42f4d` 期间还有**另一处**交错 segfault
  （channel-tree delegate paint 中途被 gen-0 GC 回收弱引用顶层 widget），已由
  `tests/ui/conftest.py` 的「post-call 钉住顶层 widget → teardown 泵完事件再释放
  + collect」修复——**别删那段 pin 逻辑**，机制、实验与引入提交见
  `docs/analyzer/reviews/2026-08-11-channel-tree-paint-segfault-triage.md` §6。
  期间曾出现过的 Batch 2 failed + 8 errors（几何契约漏同步 + `BatchSheet`
  lambda/属性回调导致的僵尸 wrapper teardown 簇）已随上述修复清零，定性与引入点
  见同一文档 §4.2/§4.3——别从旧版验收文档把「单独进程运行通过」的说法抄回来，
  teardown 簇里 4-5 条单跑也确定性复现。
  唯一环境性风险是 `tests/test_gen_help_screenshots.py`：它依赖未入库的本机 `testdoc/`
  样本目录，本机有样本所以通过，新克隆会红，那不是代码问题。
  本文先前记录的三条「历史既有红」已全部转绿并从本文删除（别从旧版抄回；其中
  `test_hint_nudges` 那条连用例名都改了）。渲染 parity 那次的定性过程留在
  `tools/verify_batch_qt_render_parity.py` 的注释与该文件的守卫用例里。
  跑 `tools/verify_batch_qt_render_parity.py` **必须带 `--output-dir` 指向临时目录**，
  否则会写脏 `docs/superpowers/verify/batch-qt-render/` 的已跟踪证据。

## Architecture
`mf4_analyzer/` 主包：
- `app.py` 入口 · `app_meta.py` 版本与资源路径
- `io/` 导入层：`loader.py` 总入口 + 各格式模块（`ascii_format` / `csv_format` /
  `head_hdf` / `wwt_format` / `zfd_format` / `mat_format`）
- `signal/` 纯数值算法（`fft` / `order` / `order_cot` / `filters` / `envelope` /
  `spectrogram` / `weighting` / `adaptive` / `channel_math`）——**禁止 import PyQt5 或
  matplotlib.pyplot**
- `render_profile.py` UI 中立的显示策略画像 + `envelope_ink_dev_px` 等纯函数
  （`ui/pg_canvas/render_profile.py` 只是再导出 shim，别往里加实现）
- `ui/` 主界面：
  - `main_window/` 8-mixin 组装（`window.py:98` 的 MRO）+ 显式协作对象：
    `analysis_context.py`（跨 mixin 的分析服务面）· `fft_time_coordinator.py` ·
    `_state_holders.py`（原本散写的状态改由具名 dataclass 持有，窗口侧留 property shim）
  - `pg_canvas/` pyqtgraph 画布：`canvas.py` 宿主 + `renderer` / `quality` / `cursor` /
    `overlay_axes` / `annotations` / `tick_density` / `dense_raster` / `slice_panel` 等
    协作者，全部经 `_backref._CanvasBackref` 代理回宿主，各自用
    `_owned_names` / `_delegate_names` 声明状态归属
  - `chart_stack/` · `drawers/` · `inspector_sections/` · `markup/` · `widgets/` ·
    `view_state.py`（View 管理）· `hints.py` + `quickref.py`（两个发现性面）
  - `canvases.py` / `pg_canvases.py` 是**兼容 shim**（打包 hidden import、测试
    monkeypatch 缝），别往里加实现
- `ui_kit/` 通用控件与样式：`style.qss` · `fonts.py`（中文字体）· `popup_shell.py` · `icons.py`
- 批处理：`batch.py` 已收成编排层（`BatchRunner` + 私有 `_RunReporter`），DTO / DSP /
  IO / 校验 / 清单 / 输出各自成模块（`batch_types` · `batch_compute` · `batch_output` ·
  `batch_validation` · `batch_manifest` · `batch_recipe` · `batch_preprocess` ·
  `batch_grouping` · `batch_series_spool` · `batch_statistics` …）；`batch_render_qt/`
  是 GUI-free 的 Qt 渲染导出，经 `batch_render.py` 门面进入，可选依赖缺失由
  `renderer_import_policy.py` 判定
- `acquisition/`（清单/预检）· `acquisition_capture/`（XCP/Vector 运行时）·
  `acquisition_ui/`（Cockpit 界面）
- `help/` 应用内 HTML 帮助页

仓库其余部分：`tests/`（pytest / pytest-qt，按 `signal` `ui` `ui_kit` `integration`
`perf` `acquisition_ui` 分目录）· `scripts/`（冒烟/回归/性能探针）· `tools/`（帮助页截图、
Windows 打包脚本、渲染对比）· `configs/` · `assets/`。

**渲染栈**：图表全量走 pyqtgraph（时域、FFT、阶次、时频、批处理导出）。matplotlib 已从
运行时移除（`requirements.txt` 里也没有），代码里残留的 `matplotlib` 字样只是历史注释和
配色兼容函数，不是活依赖。

## 机械护栏（这些是 2026-08 架构加固的产出，改动必须维持）
下面每条都由常驻测试机械看守。**红了就修代码，不是放宽护栏**；确实要改护栏，先改对应
spec 再改测试，并在提交里写清为什么。
- **状态所有权棘轮** `tests/ui/test_main_window_state_ownership.py`：AST 扫描
  `ui/main_window/*.py`，冻结「在 ≥2 个文件被写」的属性集合。白名单**只许缩小**
  （治理起点 17 项，现存 6 项，全是 `_project_io_mixin` 与 `window.py` 之间的
  文件/会话身份）。新增多文件赋值属性会立刻红。注意判据：`self.X = v` 算写，
  `self.X.field = v` 不算——所以迁移的方向是把裸散状态搬进具名 holder。
- **画布状态归属** `tests/ui/test_pg_canvas_backref_invariants.py`：断言各协作者
  写穿到宿主的属性集合**恰好等于**白名单。想写穿新属性，先问该状态是不是应该归协作者。
- **UI 三层分层** `tests/ui/test_import_boundaries.py`：`ui_kit` 是最底层，不 import
  `ui` / `acquisition_ui`；`ui` 不 import `acquisition_ui`（反向允许）。
- **signal 无 GUI** `tests/test_signal_no_gui_import.py`：子进程投毒法强制
  `signal/` 不碰 PyQt5 / matplotlib.pyplot。
- **批渲染无 UI 副作用** `tests/test_batch_render_import_boundary.py`：`import
  mf4_analyzer.batch_render` 不得把 `ui` 包或 `MainWindow` 拉进 `sys.modules`。
- **原生依赖惰性化** `tests/test_native_import_boundaries.py`：`pya2l` / `pyxcp`
  只能在函数体内 import（白名单外无例外），保证没装驱动的机器照样能起。
- **批处理 / GUI 渲染一致性** `tests/test_batch_qt_render_parity.py` + `tools/
  verify_batch_qt_render_parity.py`：比的是「真正必须一致的东西」——数据范围、视图中心、
  数据不被裁、真实墨迹不重叠；字号与 padding 分侧按各自产品常量校验，别把两侧并成一个
  常量比。
- **批处理内核不许静默失败**：`batch.py` 有 `logger`，吞掉的基础设施失败必须留痕；
  进度发射与结果记录**单点**走 `_RunReporter`（`tests/test_batch_run_reporter.py`
  看守，含 `test_run_routes_every_event_through_the_reporter` 和
  `test_reporter_stays_private_to_the_batch_module`）。新增编排分支不要再手写第二份
  emit/record。
- **目录 conftest 作用域** 仓库根 `conftest.py` + `tests/test_conftest_autouse_scope.py`：
  pytest 9.1.1 在参数「离开又回到同一目录」时（`pytest tests/ui/a.py tests/x.py
  tests/ui/b.py`）会为该目录重建第二个 collector 节点，而 fixture 查找按**节点身份**匹配，
  于是该目录 conftest 的 fixture **静默失效**——不报错、不告警，测试照跑，只是没了 fixture。
  根 conftest 让被重复收集的目录复用首次生成的子目录节点，恢复「一个目录一个节点」。
  **别删根 conftest，也别往里加项目 fixture**（那是各目录 conftest 的事）。
  `tests/ui/test_qsettings_isolation.py` 是它失效时的第二道显性告警：没有隔离，UI 测试
  会去读写开发机真实的 `MF4Analyzer/DataAnalyzer` 偏好，把本机残留读成测试前置状态。
- **QSS border 简写 lint** `tests/ui_kit/test_qss_border_shorthand.py`：状态规则里的
  `border:` 简写会把基线 `border-radius` 打成 0（Qt 不是 CSS）。白名单只许缩小；
  扫描含 `#id[attr]`（按 objectName 反查 `setObjectName` 所属类）和
  `::sub-control:state`。
- **`.connect(lambda` 棘轮** `tests/ui/test_no_lambda_signal_connections.py`：AST 冻结
  `ui/` + `acquisition_ui/` 的 lambda 信号连接数，只许缩小。`window.py` 在 F6 后为 33。
  新连接改 bound method / `functools.partial`，不要把 `self` 关进 lambda。
- **paint 计时器哨兵** `tests/ui/test_pg_timedomain_canvas.py` 的
  `test_frame_paint_backstop_is_installed_on_real_canvas`：真画布必须装上
  `install_frame_paint_timer` 回退，armed AA 帧才能进 `_note_aa_frame`。失败分支要
  `logger.warning`，不要静默。
- **View 恢复是一个事务，只结算一次** `tests/ui/test_pg_timedomain_canvas.py` 的
  `TestViewRestoreSettlement`（几何一致性 + `_refresh_visible_data` 恰好 1 次）与
  `TestDiscreteSettle`（离散结算三分支 + memo 生命周期）：`_render_view_to_canvas`
  必须走 `restore_visible_xlim(flush=False)` → `restore_visible_ylims` →
  `settle_view_restore()`，在**最终几何**上刷一遍、判一次。**离散结算不许改交互
  静默窗**——`timer.interval() == 150` 被钉住（`QTimer.start(int)` 会永久改
  interval，所以离散路径用独立的 0 ms `discrete_timer`，别合并成一个计时器）。
  分析画布同理：`plot_spectra` / `set_result` 返回时曲线 AA 必须全 off，AA 按
  ink **AND** 点数两条腿判、并有实测 backstop 兜底
  （`tests/ui/test_pg_line_canvas.py` 的 `test_plot_spectra_returns_with_aa_off_and_discrete_timer_armed`
  / `test_spectrum_ink_gate_blocks_noise_floor_and_allows_peaks` /
  `test_point_budget_leg_still_ands_with_ink`，`tests/ui/test_frf_canvas.py` 的
  `test_frf_set_result_arms_discrete_aa_instead_of_painting_an_aa_frame` /
  `test_frf_noise_phase_and_coherence_are_rejected_by_the_ink_gate` /
  `test_frf_backstop_trips_and_blacklists_the_view_signature`）。
  新常量（`_SYNC_AA_MAX_MS` · 谱行 `_SPECTRUM_INK_AA_ON/OFF` 95k/145k ·
  `_FRF_INK_AA_ON/OFF` 75k/115k；预览行复用 `_INK_AA_ON/OFF`）和下面那几个一样是
  **标定值不是旋钮**：要改先改
  `docs/analyzer/specs/2026-08-15-view-switch-quality-settlement-spec.md` §5，再用
  `scripts/probe_view_switch_quality.py analysis-calibrate` 在真机重测。

## 时域渲染成本判据：ink（墨水量）
2026-08-08 起，时域渲染**成本**的统一判据是 ink（`ink_dev_px = Σ min(|Δy|, y_span)
/ y_span × row_height_px × dpr`，纯函数 `render_profile.envelope_ink_dev_px`）。
成本的真实自变量是要画的**垂直墨迹量**，不是点数、不是采样密度、不是通道数。
spec：`docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md`。
- 三个预测消费者 + 一道实测兜底：交互路径按 `_INK_OFF_BUDGET` 比例降桶（下限
  `_INK_MIN_BUCKETS`）· 向量 AA 闸门与导出按 `_INK_AA_ON`/`_INK_AA_OFF` 判 ·
  光栅缓存准入共用同一条带（AA 付不起的形状正是光栅路径存在的理由，共用边界防两个决策
  在边界互相抖）· `ui/pg_canvas/quality.py` 的常驻 paint 计时 + 签名闩锁是**实测兜底**，
  前三者都是预测，兜底保证预测错了也最多为一个签名付一帧。
- **别再拿原始采样密度（源点数/像素宽）当成本门禁。** 实测这类判据两头都错：假阳性
  （2×500k 平滑 overlay，ink 只有阈值的 1/71，却被旧门禁拦下）+ 假阴性（10k 点满幅振荡，
  旧门禁零贡献放行，真实 AA 帧 29.8 s）。`quality._overlay_density_pressure_status`
  因此被删，`test_overlay_density_pressure_reason_is_retired` 看着它别复活。
  注意区分**仍然合法**的两处：`renderer._SUBPLOT_DENSE_DECIMATION` 用同一比率决定
  「要不要降桶」——那是**保真**判据（每像素列已塌成 min/max 墙，粗化不丢特征），不是成本
  门禁；AA 闸门里那条按**已绘 segment 数**的腿也留着，它与 ink 腿是 AND 的正交约束。
- ink 表没记录过的曲线**必须当场测量**，不能当成 0——`plot_channels` 尾部就
  `schedule_idle_quality()`，首帧走 bind envelope 不经 `_refresh_visible_data`，
  当年这个空表就是 66 s 一帧的活口。
- 那几个常量是**标定值不是旋钮**（Cocoa @ dpr 2.0 的 ns/px 系数）。要改：先改 spec §5，
  再用 `scripts/probe_aa_ink_budget.py` 在**真机**重测（offscreen 量不出 paint 成本），
  `tests/ui/test_pg_timedomain_canvas.py::TestInkBudget` 只栅栏量级。
- 性能门禁：`scripts/benchmark_timedomain_interaction.py --assert-standards`
  （`COCOA_LIMITS_MS`），准则与已接受参考读数在
  `docs/analyzer/specs/2026-07-26-plot-performance-standards.md`。**别放宽上限**来让改动通过。

## 产品约束（碰导入 / View 相关代码前必读）
- 支持格式：MF4/MDF、CSV/Excel/HDF、BLF+DBC、CANoe ASC CAN 日志（`.asc` 自动识别，配 DBC，
  与 BLF 同链路）、音视频、通用 ASCII（`.asc`/`.fdc`）、
  NI TDMS（`.tdms`）、WinWert（`.wwt`）、ZFGE2/TestRunPRO（`.zfd`）、
  MATLAB（`.mat`，v7.3 经 HDF5）。
- ASCII 需要可识别的时间列，或已验证的固定宽度采样元数据；TDMS 需要有效波形时基
  ——**绝不臆造采样率**。`.asc` 先经 CANoe 取证，命中走 CAN 日志链路，未命中才按通用 ASCII 解析。
- `.tdms_index` 是 TDMS 配套索引，永远不是可导入的数据文件。
- WWT 用文件自带的 `Zeit` 时基并保留单位/缩放/偏移；ZFD 在时基无效时可用**显式标注为
  估算**的 1 kHz 回退；MAT 只认可识别的时间变量，不猜工程单位。
- **一个物理文件可能展开成多个逻辑来源**（`LoadedSource`）：WWT 按 `(点数, dt, t0)`
  合并 `Zeit` 块，HDF 按采样率拆分。**同采样率但录制时长不同也会拆**——实测
  `testdoc/2024_3_17/SFNS_40_X04-CSER_000009.wwt` 拆成 `Weg`（10450 点）与
  `Rack Force`/`Rack Travel`（9460 点）两组，两组都是精确 1000 Hz。
  各组通道集可以**互不相交**，所以「共同信号」为 0、通道选择器显示 `(4/5)` 都是正常的。
  批处理规划是 no-load 的，拿不到磁盘来源的通道表，必须由调用方经
  `BatchRunner.seed_source_channels()` 喂进探针结果（`BatchSheet._make_runner` 已接），
  否则会把目标信号排到根本没有它的子来源上。
- 批处理与 GUI 共用同一套 ASCII/TDMS 导入规则。
- View 上限按 manager 区分：时域与四个分析分区统一 12（`ui/view_state.MAX_VIEWS`；
  时域在 `ui/main_window/window.py` 显式传 `max_views=12`）。窄宽度下 tab 先压成序号、
  再溢出到 `»`；改动要保住活动 View 可见性、tooltip 全名、拖拽重排与右键菜单。

## Gotchas
- **验真机渲染**：UI/视觉/性能问题（尤其 macOS 原生）必须验真实渲染（截图 / objc 读原生
  属性 / 真机计时），别凭「属性设上了 + 单测过」判定修好。`offscreen` 只能当排版草稿，
  量不出 paint 成本，也不能写成视觉验收通过。`scripts/probe_aa_ink_budget.py` 的
  docstring 直接引用了这条。
- 嵌入浮层/菜单的自定义 `QWidget` 必须透明背景；`WA_TranslucentBackground` 会让本体 QSS
  失效 → 需 `paintEvent` 或内部子 widget 兜底。
- 项目位于 `~/Downloads`：子进程跑过后触发 macOS TCC，对项目目录 EPERM。解法：给终端
  Full Disk Access、把 `TMPDIR` 指向 `/tmp`，或把项目移出 Downloads。
- 用户的分析领域是 **EPS（电动助力转向）**：阶次分析 base 用电机转速，示例信号用
  方向盘扭矩 / 电机转速 / 电机扭矩，别写成发动机（engine）。

## 文档与并行工具链
- 新的分析器文档（计划、评审、用户指南、UI 原型）放 `docs/analyzer/`，子目录分工见
  `docs/analyzer/README.md` 的 Routing 表；`docs/superpowers/` 是历史工作流归档，
  别往里加新内容。
- `docs/analyzer/verify/` 与 `evidence/` 存**真机测量基线与锚点清单**（重构前的行号快照、
  性能读数）。要复现或对比历史读数先翻这里，别重新发明基线。
- 结构治理类改动的既有范式：spec（设计 + 为什么现在做 + 量化收益）配 plan（分 Task），
  见 `docs/analyzer/specs|plans/2026-08-04-*` 与 `2026-08-08-*`。新的同类改动照这个格式走。
- `AGENTS.md` 是 **Codex 侧与本文平级的契约文件**（它开头自己声明 "for Codex only"，
  也写明别去改 `CLAUDE.md` / `.claude/`）。它按 Version And Documentation Contracts /
  Architecture Contracts / Robustness Rules / Change Discipline / Verification Gates
  组织，覆盖的是**同一套护栏**（状态所有权棘轮的 shrink-only、ink 判据、import boundary
  清单、禁止宽泛 `except Exception`），只是换了另一份表述——**别把它当 lessons 系统读**。
  真要动某条护栏，记得两份文件都描述了它（该文件在持续迭代，以当前内容为准）。
- `docs/lessons-learned/` + `scripts/lessons/` 才是 Codex 的 lessons 系统（AGENTS.md
  最后一节），Claude 不需要走它的 check/promote 流程。其中 `pyqt-ui/`
  `signal-processing/` `refactor/` 下的踩坑记录可以当参考检索；`orchestrator/` 是已废弃的
  多 agent 调度产物。
- `/update-hints` 是项目内命令：UI 交互有增删改时，用它同步 `ui/hints.py`（滚动提示）与
  `ui/quickref.py`（操作速查面板）。
