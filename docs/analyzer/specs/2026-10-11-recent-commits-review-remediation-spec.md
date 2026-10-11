# 近期 25 个提交复审：分析 View 目标归属、色阶自然窗与图表选项坐标修复规格

- 日期：2026-10-11。
- 状态：**待实施**。本文只记录复审结论与修复合同；未修改产品代码，未运行全量套件。
- 配套：[执行计划](../plans/2026-10-11-recent-commits-review-remediation-plan.md)。
- Review 基线：`2b14ce80..4667dd06`（25 个提交，2026-09-25 → 2026-10-08；`99648ef0` 为纯文档）。
  编写时 HEAD 为 `4667dd06`，工作区干净。实施前按符号与行为重新定位，不要用本文行号覆盖
  并行改动。
- 证据类别：本文所有「已复现」均为 offscreen Qt 探针或真实 `MainWindow` 集成探针；
  macOS Cocoa、Windows 前台与 Windows 冻结包均**未运行**。偏静态的 Win32 / MSVC 结论
  单独标注。

## 1. 问题与证据

按五条审查线编号：H = 热图色阶与色板（`548cddc5` `4b7c20be`）、C = 分析 View 对比与结果
身份（`99256024`…`67d88ee1` 七个提交）、O = 图表选项事务 / 工具栏焦点 / 面板 chrome
（`e5866743` `7afa55af` `72b08435` `612b7e68` `1f984342`）、K = 游标卡片 / FRF Pin /
通道树 / 全量回归修复（`4667dd06` `875221db` `8b5d0485` `dc915675`）、S = 原生启动器 /
HEAD HDF / 帮助 / 发版扇出（`a3572d44` `a0e495a4` `8e182abb` `3efd5e5a` `d4930248`
`e7220e60`）。

### 1.1 P1 — 数据显示错误 / 状态被覆盖

| ID | 已确认事实 | 归因 |
| --- | --- | --- |
| H1 | 自动色阶的热图 View 继承上一个 View 的色阶窗。真实 `MainWindow` 探针：View A 数据 0.01–1.2，View B 数据 10–1200（+60 dB）；切到 B 后 Order dB 显示 (−28.5, 1.58) 而 B 自身自然窗为 (31.5, 61.6)，Order 线性与 FFT‑Time 线性同样显示 (0.01, 1.2) 而非 (10, 1200)。只有 FFT‑Time dB 一条路径正确。 | `HeatmapColorCoordinator.complete()` 把画布字段 `_last_auto_levels` 当「本数据自然窗」真值；而 `project_color_levels(auto=True, …)` 把它当「上次投影」在写（`set_levels_locked` 与 `settle` 的 union 投影都会写入），且 `plot_or_update_heatmap`（Order）与 `plot_result` 线性分支从不刷新它。 |
| C1 | 对比中 peer 持有焦点时，通过**删除 peer / 关闭其他 View**隐式结束对比，Inspector 仍显示 peer 参数；随后任何 capture（计算、保存、切模式）把 peer 参数写进宿主 `state.params`。四个分区（fft / fft_time / order / frf）全部复现：宿主 `window='hanning'` 变为 `'hamming'`。 | `_on_analysis_delete` / `_on_analysis_close_others` 依赖 `ViewManager` 的**条件式** `active_changed` 重投影宿主；宿主索引小于 peer 时该信号不发。R1「关闭对比恢复宿主」只覆盖显式 close 路径。 |
| C2 | 对比中 peer 聚焦，在宿主画布 Chart Options 改一次 X 范围：宿主全部计算参数被 peer 覆盖（`window`/`t_win_s` 等），且 patch 写进宿主而 Inspector 显示的是 peer。 | `_analysis_range_policy` / `_apply_analysis_range_policy` 仍按 `mgr.active` + 实时 Inspector（`requested_params_from_context`）取参，没有走 `AnalysisViewTarget`。 |
| O1 | FFT 分区图表选项把 Y 刻度设为 log（手动 1..100 或自动）后：ViewBox 收到工程值 1..100 当 log10 坐标，工程量程变成 10..1e100；自动量程下变成 (2.5e‑308, 1.6e308)，曲线坍成一条线；重开对话框字段被 clamp 为 0.0 / 1e15。X 轴同理。 | `PgAxisHandle.set_engineering_*lim` 在 log 下做了 log10 转换，但 `PgLineCanvas.plot_spectra` 与 `_fit_active_spectrum_y` 用工程值直接 `setXRange/setYRange`；对话框经 `_apply_analysis_range_policy → _render_analysis_view_from_cache → plot_spectra` 绕过了 handle。 |

### 1.2 P2 — 真实流程中的功能缺陷

| ID | 已确认事实 | 归因 |
| --- | --- | --- |
| C3 | 关闭全部文件（保留项目 / 关闭项目两种决定）都不清理对比关系；悬空 `relations_payload` 随下次保存写入工程，再次打开触发「目标 View 不在此项目中」误报。 | `_reset_empty_workspace_session` 与 `_commit_project_session_end` 不调 `_teardown_comparison_display`；保存时也不按存活 `view_id` 过滤。 |
| O2 | `_ChartFloatSpin` 手输 5 后 Key_Up / 滚轮：显示 6.0，`value_for_commit()` 仍返回 5.0；`_committed` 也记 5.0，「还原」还不回用户看到的值。 | `setValue` 在 `_edited_text` 非空时直接返回，步进不清旧文本。 |
| O3 / O4 | 分析画布**无任何改动**点 OK/Apply，对 x、y 同时重放 range policy，把用户视口 origin 从 `user` 清成 `auto`（视口 (40,120) → (0,498.5)），此时还原按钮禁用、不可逆；仅改颜色后点「还原」也重放两轴 range policy，与 Apply 不对称。`tests/ui/test_dialogs.py::test_analysis_chart_options_unchanged_apply_reapplies_parameters` 把该语义冻结成了预期。 | `_commit_analysis_policy` 的 `elif not appearance_dirty: axes = {"x","y"}` 分支；`restore_opened` 复用同一分支。 |
| O5 | 分析画布 log 刻度不进 `chart_appearances`：`full_reset()` + 为另一 View 重绘后仍是 log；跨 View 泄漏、工程不持久化。 | `_commit_chart_options` 只捕获 title/labels/grid/line_colors；`_normalize_appearance_spec` 无 scale 键；无 `setLogMode(False)` 复位。时域有 `x_scale/y_scale` 且有隔离测试，分析画布没有。 |
| H2 | 手工编辑过的 preset（`z_floor >= z_ceiling` 或 reference ≤ 0）经 `preset_committed → sync_committed_preset → commit(origin="preset")`，`HeatmapColorPolicyError` 未捕获，直达 Qt 槽的全局异常钩子，preset 事务半途中断。 | `analysis_context.sync_committed_preset` 无捕获；`preset_state` 加载层不校验 z 顺序。渲染路径已有 `_reject_heatmap_color_render` 出口。 |
| H3 | 色条拖拽每个 `levels_changed` 都走完整 `commit → _anchor_request → resolve_db_reference_for_source → DbReferenceSettings.snapshot()`（每次重算 catalog）并 `deepcopy` basis 写回 pane。 | 拖拽中与释放后未区分；`snapshot()` 无脏标记缓存。 |
| H4 | `_sync_active_analysis_params` 用 `except ValueError` 捕获 policy 错误后返回 `None`，上游把「渲染被拒」当「无变化」；非 policy 来源的 `ValueError`（编程错误）被同样降级。 | 捕获范围大于 `HeatmapColorPolicyError`；返回值不区分「无变化」与「被拒」。 |
| H5 | `_heatmap_picture_is_current` 为判断能否复用缓存图片而调用 `_fft_time_render_inputs`，后者在 `color_policy is None` 时调用 `coordinator.prepare`（写 `_prepared`）；判定后若决定复用图片，这条 prepared 记录永远不会 `complete`。 | 只读判定路径带副作用；prepare/complete 配对合同被破坏。 |
| H6 | `colormaps/registry.py` 在 import 时读 `catalog.json`、校验 sha256 并构建 `SUPPORTED_HEATMAP_COLORMAPS`；`qt_analysis_shared.py` 顶部 import 该常量。资源缺失/损坏会让主窗口与 Batch 渲染都起不来，而设计里本有 pyqtgraph 内置的 `FALLBACK_HEATMAP_CMAP="gnuplot2"`。 | 资源读取不是惰性的；`tests/test_packaging_imports.py` 不验证 `--add-data` 路径与资源文件一致性。 |
| K1 | FRF Pin 来源更换后状态呈现错误：换成不同文件/通道 → 标题正常、正文空白、无任何说明；输入/输出角色互换 → 标题「无数据」但正文仍是旧来源的 \|H\|/φ/γ² 读数（146×139 → 116×223）。quickref 承诺的「更换来源后旧 Pin 暂停读数」用户看不到。 | `evaluate_intent` 对 FRF 不匹配正确返回 `None`，但 `_reproject_now` 把 `None` 交给时域语义的 `_reconcile_sample`，为每个 binding 造「无数据/未勾选」占位行；`CursorPill.set_display_projection(None)` 不清 `_detail`。 |
| K2 | 分屏 FFT‑Time：页面对齐后两 pane colorbar 轴宽 (26.22, 26.22)、主图 (455.22, 455.22)；在 pane 1 拖动 colorbar 结束后变为 (26.22, 34.48) / (455.22, 446.95)，主图再次错开约 8 px。 | `dc915675` 的 colorbar 对齐只修了页面主动对齐；`_on_cbar_levels_finished` 等 5 处仍无条件 `_size_colorbar_value_axis` 把本 pane 轴宽钉回本地刻度需求，且不发 `layout_geometry_changed`。 |
| S1 | 原生 Windows 启动面板没有管道 EOF / 超时退路：运行时存活但管道已关（例如 Python 侧 `NativeStartupFeedback.start()` 打开继承句柄失败后 `_degraded` 直接 reveal 主窗，或 S5 的策略分歧导致 `scrub_native_bootstrap(close_handles=True)`）时，面板整场会话压在桌面上；窗口是 `WS_POPUP | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`，`WM_CLOSE` 无人能发。（静态 + 可移植核心编译验证） | `runtime_thread` 循环条件只有「子进程还活着」，`PeekNamedPipe` / `WriteFile` 失败被静默忽略。 |
| S2 | `launcher_win32.cc` 使用 `rand_s` 但未定义 `_CRT_RAND_S`，`-NativeStartupLauncher` 的 MSVC 编译预期失败于 `C3861`。（静态；本机无 MSVC，仓库亦无 Windows 构建证据） | 源文件与 `build_startup_launcher.ps1` 都未定义该宏。 |
| S3 | 启动器上报的 `screen` 是 PER_MONITOR_AWARE_V2 下的物理像素 `rcWork`，而 `StartupHandover._move_onto_launch_screen` 把它当 Qt 逻辑坐标（`AA_EnableHighDpiScaling` + `PassThrough`）。主屏 150% + 副屏启动时主窗落到虚拟桌面之外。（静态） | 两侧坐标系未在协议里声明；单屏 100% 时两套坐标重合，容易漏测。 |
| S4 | HEAD HDF 新增 `code page != "936"` 即整文件 `NotImplementedError`。把夹具头部改成 `1252` 即复现。德/英文系统上 ArtemiS/HEAD Recorder 默认写 1252，这类文件以前可读（非 ASCII 名乱码但数据与时间轴正确），现在读不了。 | 文本编码事实被当成布局事实；计划文档的「未知布局 fail closed」针对的是时间/布局语义。 |
| S5 | 启动器与 Python 的 opt-in 策略不等价：C++ `env_get` 只裁 `' '`/`'\t'`（`"0\n"` → Python False / C++ True，可移植核心的自带 fixture 已复现失败）；C++ 环境变量键大小写敏感而 Windows / `os.environ` 不敏感。分歧时落到 S1 的卡死路径。 | 两套解析各写一份。 |

### 1.3 P3 — 加固 / 覆盖缺口 / 文档漂移

| ID | 事实 | 处置 |
| --- | --- | --- |
| H7 | `HeatmapColorCoordinator.reset()` 无调用者；真实清理走 `forget` / `forget_canvas` 两条路径；`complete()` 返回 `False` 时 `_prepared` 条目滞留。 | 统一清理入口，`complete` 失败同步弹出。 |
| H8 | `reference_source == "fallback"` 或 source 为 `None` 时 basis 直接置 `None` 并写回 pane，手动色阶锚点静默丢失、无日志。 | fallback 时保留旧 basis、`logger.info` 一次。 |
| H9 | 旧工程 / 旧 preset 未持久化 `cmap` 时 HEAD 默认色板替换用户此前看到的 `gnuplot2`，无提示。计划文档已授权。 | 只补 changelog 说明，不改代码。 |
| H10 | 协调器单测的 fake canvas 缺 `_last_auto_levels` / `_z_color_auto` 字段，`complete()` 永远走 `_automatic_color_window` 分支，与真画布行为不同（H1 因此假绿）。 | 随 H1 补齐 fake。 |
| C4 | peer 卡片 `_wire_peer_card` 硬编码 pane 0 且不挂 `analysis_range_adapter`；多 pane peer 的外观/范围事件路由退化。 | 随 C2 一并按 pane 索引绑定。 |
| C5 | `_frf_compute_values_for_state` 按 `manager.active` 判断是否读实时 Inspector，与 R2 的 capture 语义不一致。 | 改用 `_analysis_state_for_capture("frf") is state`。 |
| C6 | 切回分区时宿主 / peer 双重渲染：`_render_analysis_view_from_cache` 已走 `_render_comparison_view`，随后 `_restore_remembered_comparison → _present_comparison` 再渲一次。 | 二选一跳过。 |
| C7 | `analysis_comparison._by_canvas` 与 FFT‑Time `pane_token` 用 `id(canvas)` / `id(pane)` 作进程内身份键。 | 改 `AnalysisViewTarget` / `itertools.count` 代际。 |
| O6 | `_store_heatmap_color_policy` 无调用方（死代码）。 | 删除。 |
| O7 | `_capture_heatmap_chart_options` 只要 `_cmap_name` 非空就写 `cmap`，`chart_appearances` 永远非空；同时把已失效的 `z_*` 原样带回，而 `_project_heatmap_pane_appearance` 又会剥掉——两处策略相反。 | 与默认 cmap 比较后再写；`z_*` 由协调器单点决定。 |
| O8 | `_write_axis_limits` 丢弃 `set_engineering_*lim` 的 bool 拒绝返回值。 | 至少 `logger.warning`。 |
| O9 | `line_canvas._apply_title_text` 多处 `except Exception:` 吞异常。 | 收窄为 `RuntimeError` 并注明原因。 |
| O10 | 历史栈 XY 回退一律发 `viewport_action_committed("user", …)`，回到基线也标成 user；`rebind_history_capture` 只在栈空时播种，切 View 后旧栈可在新 View 回放。 | 基线回退发 `home`；切 View 清栈。 |
| O11 | `ChartStack.exit_split` 不对隐藏副工具栏 `discard_pending_history`（`AnalysisSectionPage.exit_split` 有做）。 | 对齐。 |
| O12 | `cards.py` 用 `AttributeError.name == "_focused"` 区分初始化时序。 | 显式 `_focused = None` 初始化。 |
| K3 | 每条 `project_record` 内嵌一次 `arrange_pinned_panels`：N 个 Pin 的一次重投影做 N+1 次排布、N+2 次连接线发布（N=8 时 10 次 `set_tethers`、56 ms offscreen）。 | 集合级只在事务末排布一次。 |
| K4 | `set_display_projection(None)` 不释放 `_primary` 最小高度（HEAD pending 态 249×131 vs 旧 249×92）、不清隐藏 `_detail`（既有缺陷叠加）。 | 走 `_clear_display_projection()`。 |
| K5 | role-less FRF 旧记录对输入/输出互换按集合比较而接受，重采样为 H⁻¹ 读数。 | 有序对比较或要求 FRF 记录必带角色。 |
| K6 | FRF Pin 每次重投影都被塞入两行时域占位通道（K1 根因）。 | 随 K1 短路。 |
| K7 | `_measure_span` 测量缓存按每个数值字符串缓存、结构周期内无上限（live 3000 次更新 → 11557 项）。既有，但本提交接入了更多测量。 | LRU / 容量上限。 |
| S6 | 原生启动器 JSON 解析无深度限制；1 MB 线程栈下 ≤4 KB、3000 层即栈溢出。 | 深度计数 >32 即 fail。 |
| S7 | HEAD HDF `nbr of scans` 损坏时先分配时间轴再查数据区字节数，`MemoryError` 而非数据错误；时间轴校验建两遍全量数组。 | 截断检查前移、解析式校验。 |
| S8 | `NativeStartupFeedback` 的 EOF / 超时回退不写日志，与「fallback 必须可观测」不符。 | 两处 `logger.warning`。 |
| S9 | GDI+ `Graphics` 在 `DeleteDC` 之后才析构；`CreateThread` 失败时既不启动运行时也不退出。 | 内层作用域；失败走 `create_pipes` 失败同一出口。 |
| S10 | 读缓冲无上限（仅按行限 4 KB）；`double → int` 强转越界 UB（`1e300` → `INT_MIN` 仍 `ok=1`）。 | 总量上限；`isfinite` + 夹紧。 |
| S11 | `measure_windows_startup.py` 超时只 `kill` 启动器，`CREATE_BREAKAWAY_FROM_JOB` 的运行时成为孤儿。 | 按进程树杀。 |
| S12 | 生成头文件目录落在发布目录内；`cl` 的 `.obj` 落在 CWD 且未 gitignore。 | 都指向 `build\` 临时目录。 |
| S13 | 原生 / Qt 两侧 1.5× 缩放判据不同（Qt 侧含 `SHADOW_PAD`）。 | 同源常量。 |
| S14 | macOS 帮助副本：`subprocess.run(open)` 阻塞 GUI 线程；副本按 stamp 累积不清理；两实例首开 `copytree` 竞争 → `FileExistsError`。 | `Popen` / `openUrl`；`dirs_exist_ok` 或临时名 + rename。 |
| S15 | `classify_saved_hdf_sampling` 的指纹核验参数在产品路径永远为 `None`（`ProjectFileRef` 无指纹字段）。 | plan 中记为未实现，或补字段。 |
| S16 | 8.4.2 之后合入的四个用户可见功能（通道名复制 / FRF Pin / HEAD 色板默认 / 手动色阶跨 View 保留）未进主册 changelog 与 README；hints / quickref 已同步。 | 升 8.4.3 补条目，或追加进 8.4.2 条目并更新 `updated`。 |
| S17 | `tests/test_startup_launcher_core.py` 只认 `clang++`：无则 skip、坏则红；核心解析器无畸形输入用例。 | 按 `clang++ → g++ → c++` 取第一个可用。 |

### 1.4 已审查且未发现缺陷的部分

`8b5d0485` 通道名复制（复制 `Qt.UserRole` 真实列名，多选只给共轴操作，无 lambda）；`dc915675`
的 QSS 重写（逐选择器渲染比对，仅删 8 个无引用死选择器，状态规则 `border:` 简写集合不变）与
`tests/ui/conftest.py` 输入隔离（子进程验证只影响 QTest 残留按键）；`8e182abb` 弹窗退出；
四个完成回调的代际 / request-key 门控（未发现把过期结果发布到错误 View 的路径）；FRF 缓存键
经 `materialize=False` 规范化后含裁剪范围，未发现碰撞；`da2e9e87` 时间范围精度自洽；
`e7220e60` 8.4.2 扇出完整一致；`.connect(lambda` 棘轮与 state-ownership 白名单未放宽；
`heatmap_color_policy.py` / `colormaps/registry.py` 不 import UI。

未确认项（需要专项探针或真机）集中列在配套 plan 的 T0。

## 2. 目标与范围

### 2.1 成功目标

1. 任何热图 View 在自动色阶下显示**它自己数据**的自然窗；锁定 / 解锁 / 切 View / dB↔线性
   切换都不会把别人的窗口或 union 当成自己的自然窗。
2. 「Inspector 当前投影的是哪一个 View」是一个在**所有**结束对比的路径上都被维护的不变量；
   任何按画布触发的参数写入（范围策略、FRF 重算取值）都经 `AnalysisViewTarget` 定位目标，
   不再按 `mgr.active` 或实时 Inspector 推断。
3. 对比关系的生命周期与 View 生命周期一致：View 消失、会话清空、工程关闭都清理关系；
   保存载荷不含悬空 host。
4. 图表选项对分析画布暴露的每一项都有一致的坐标系与持久化模型：log 刻度要么完整进入
   `chart_appearances` 并与 `plot_spectra` 坐标统一，要么对分析画布关闭该能力。
5. 对话框的「一次可逆提交」名副其实：无改动 OK 是 no-op；还原只撤销 Apply 做过的事；
   数值字段显示值 == 提交值。
6. 协调器、preset、注册表的错误路径按既有分类处理：数据错误给用户反馈并留痕，编程错误
   不降级；资源缺失退回 `FALLBACK_HEATMAP_CMAP` 而不是 import 失败。
7. FRF Pin 的「来源已更换」是一个用户可见、文案明确的状态；分屏 colorbar 对齐在用户交互
   后仍保持。
8. 原生 Windows 启动器在任何管道 / 策略分歧下都能自行退场；坐标系在协议里显式；opt-in
   构建链路至少完成过一次真实 MSVC 构建。HEAD HDF 的 `code page` 只决定解码器。
9. 发版面与 changelog 跟上 8.4.2 之后的用户可见功能。

### 2.2 非目标与保持项

不改 FFT / FRF / Order / Spectrogram 数值算法；不改 ink / AA 阈值；不重标定分析色阶带；
不改工程文件格式（只允许向后兼容地新增键）；不改 `_ChannelKeyDict` 语义；不放宽任何棘轮
白名单；不把 `test_analysis_chart_options_unchanged_apply_reapplies_parameters` 之类的冻结
测试改成 xfail——要么改产品语义并同步改测试，要么保留并在本文记录为有意行为。
不重新设计对比交互、不新增 View 上限、不引入第二套 MainWindow 跨 mixin 状态。
原生启动器仍保持 opt-in，不写进发布说明，直到 S1–S3 / S5 有 Windows 真机证据。
版本升级、提交、推送、发布不属于本文实施范围。

## 3. D1 — 热图自然窗来自数据，不来自画布缓存（H1 / H10 / H7）

Owner：[heatmap_color_coordinator.py](../../../mf4_analyzer/ui/heatmap_color_coordinator.py)
持有「自然窗」的事实；[heatmap_canvas.py](../../../mf4_analyzer/ui/pg_canvas/heatmap_canvas.py)
只负责投影。

### 3.1 合同

- 「自然窗」定义为**本次渲染输入**在当前 `amplitude_mode` 下的自动窗：dB 走 `_auto_db_window`
  （与 Order 画法 `vmin_override` 同一函数），线性走 `_finite_data_bounds`。`complete()` 在
  `z_auto` 时**只**从当前画布矩阵（`_automatic_color_window()`，其 `_color_window_policy`
  必须已按本次 `amplitude_mode` 更新）或从 `inputs` 的 z 矩阵求值，**不得**读取
  `_last_auto_levels`。
- `_last_auto_levels` 的语义收敛为「最近一次投影给 Inspector spin 回写用的值」；若没有消费者
  需要它（`_fft_time_mixin.py:834` 一处读取），随本任务删除该字段，避免再有第三个写者。
- `project_color_levels(auto=True, union)` 不得改变任何「自然窗」事实；union 只是投影。
- `complete()` 返回 `False` 的所有分支都要同步弹出 `_prepared` / `_pending_basis` 条目；
  `reset()` 要么被 `_clear_analysis_canvas` / 工程关闭统一调用，要么删除。
- 协调器单测的 fake canvas 必须带真画布的 `_last_auto_levels`（若保留）、`_z_color_auto`、
  `_color_window_policy`、`_matrix_disp`，并提供一个「带过期值」的变体。

### 3.2 验收

| 场景 | 必须结果 |
| --- | --- |
| 两个自动色阶 View，数据相差 60 dB，Order dB / Order 线性 / FFT‑Time dB / FFT‑Time 线性，切 A→B→A | 每次切换后 `_img.getLevels()` == 该 View 自身自然窗 |
| 同一 View dB → 线性 → dB | 每次自然窗按新模式重算，不残留 dB 数值 |
| 分屏锁定（union）→ 解锁 | 解锁后各 pane 回到各自自然窗 |
| 跨 View 锁定 → 结束对比 | 宿主回到自身自然窗 |
| `complete()` 因非法 levels 返回 False | `_prepared` / `_pending_basis` 中无该画布 |

## 4. D2 — 分析 View 目标归属：所有写入经 target（C1 / C2 / C4 / C5 / C6 / C7）

Owner：[_analysis_mixin.py](../../../mf4_analyzer/ui/main_window/_analysis_mixin.py) 与
[analysis_comparison.py](../../../mf4_analyzer/ui/main_window/analysis_comparison.py)；
FRF 取值在 [_frf_mixin.py](../../../mf4_analyzer/ui/main_window/_frf_mixin.py)。

### 4.1 合同

- 提供**单点**「把某个 state 投影到 Inspector」入口（复用 R1 的 close 恢复逻辑或
  `_on_analysis_view_switched(section, idx, render=False)` 抽出的部分）。所有结束关系的路径
  ——显式 close、删除 peer、关闭其他、关闭全部 View、关闭全部文件、工程打开 / 关闭——在
  `_forget_analysis_view` / `teardown` 后，若被结束关系中的 peer 曾持有焦点，必须显式调用它，
  不依赖 `ViewManager` 的条件式 `active_changed`。
- `_analysis_range_policy` / `_apply_analysis_range_policy` 改为按发出信号的画布反查
  `AnalysisViewTarget`（复用 `_target_from_sender` / `_canvas_for_view_pane`）；非焦点 state
  的 `requested` 基于 `state.params` 而非 Inspector；patch 只写目标 state 的 `x_*` / `y_*`
  （fft_time 的 `freq_*`）键。peer 卡片按真实 pane 索引绑定外观与范围适配器。
- `_frf_compute_values_for_state` 的「是否读实时 Inspector」判据改为
  `self._analysis_state_for_capture("frf") is state`。
- 切回分区时宿主 / peer 各渲染一次；`_present_comparison` 接收「宿主已渲染」标志或
  `_restore_remembered_comparison` 跳过已绑定一侧。
- 进程内身份键改为 `AnalysisViewTarget` 或 `itertools.count` 代际，不再用 `id()`。
- 不新增多文件 MainWindow 写属性；不新增 `.connect(lambda`。

### 4.2 验收

| 场景（四分区参数化） | 必须结果 |
| --- | --- |
| peer 聚焦 → 删除 peer / 关闭其他（保留宿主） / 关闭全部 View | `ctx.current_params()` == 宿主 params；`_capture_active_analysis_view` 后宿主 params 不变 |
| peer 聚焦 → 宿主画布 range adapter 应用 `{'x': (False, (10,100))}` | 宿主只有 `x_auto/x_min/x_max` 变化，`window` / `t_win_s` 不变；peer 不变 |
| peer 聚焦 → peer 画布 range adapter | 只改 peer |
| peer 聚焦 → 触发宿主重算（FRF） | 宿主以自身 `state.params` 计算 |
| 离开分区再回来 | `_render_comparison_view` 每侧恰好 1 次 |

## 5. D3 — 对比关系随会话清理（C3）

Owner：[_project_io_mixin.py](../../../mf4_analyzer/ui/main_window/_project_io_mixin.py)。

- `_reset_empty_workspace_session` 与 `_commit_project_session_end` 都调用
  `_teardown_comparison_display()`（或至少 `comp.teardown()`），顺序在 `reset_to_single_default()`
  之前，使 Inspector 重投影落在新的默认 View 上。
- `_analysis_views_payload` 保存前按各 manager 现有 `view_id` 过滤 `relations_payload`，作为
  第二道防线；过滤掉的行 `logger.info` 一次。
- 验收：关闭全部文件（keep / close 两种决定）后 `comp.relations_payload(sec) == {}`；保存载荷
  不含悬空 host；重新打开不弹「目标 View 不在此项目中」。

## 6. D4 — 分析画布的 log 刻度与量程坐标统一（O1 / O5 / O8）

Owner：[line_canvas.py](../../../mf4_analyzer/ui/pg_canvas/line_canvas.py)、
[_axis_handle.py](../../../mf4_analyzer/ui/_axis_handle.py)、
[analysis_view_state.py](../../../mf4_analyzer/ui/analysis_view_state.py)。

### 6.1 决策

两个可接受出口，实施时二选一并在 plan 记录：

- **A（推荐）**：`plot_spectra` / `_fit_active_spectrum_y` / `_program_spectrum_range` 内的
  全部量程写入统一经 `PgAxisHandle.set_engineering_*lim`（或等价的「按当前 scale 转换」
  helper）；自动量程在 log 下用**最小正幅值**作下界而不是 0；`scale` 进入 spectrum / preview
  role 的 appearance spec（`_normalize_appearance_spec` + `_commit_chart_options` +
  `apply_user_appearance` + `full_reset` 复位 `setLogMode(False)`），工程持久化向后兼容
  （缺键 = linear）。
- **B（止血）**：分析画布 `supports_log_scale` 返回 False，对话框不再暴露 log 字段，直到 A
  完成。B 不得长期停留，plan 中必须有 A 的后续任务。

无论 A/B：`_write_axis_limits` 不得丢弃 `set_engineering_*lim` 的拒绝返回值，至少
`logger.warning`。

### 6.2 验收

- log 模式下 `plot_spectra(y_min=1, y_max=100)` 后 `get_engineering_ylim() ≈ (1, 100)`；自动
  量程下下界为正且曲线可见；X 轴同理。
- 对话框端到端：设 log + 手动量程 → OK → 读回工程量程一致；重开对话框字段 == 用户输入。
- View A 设 log，切到 View B（linear）：B 为 linear；工程保存 / 重开后 A 仍为 log。
  `tests/ui/test_view_appearance_isolation.py` 增加分析画布用例。

## 7. D5 — 图表选项提交语义（O2 / O3 / O4 / O6 / O7）

Owner：[chart_options.py](../../../mf4_analyzer/ui/dialogs/chart_options.py)。

- `_ChartFloatSpin.setValue` / `stepBy` 在值与 `_edited_text` 解析值不同时清空
  `_edited_text`；`value_for_commit()` 永远等于显示值。
- **产品决策**：无改动 OK / Apply 为 no-op，不重放 range policy；「按参数面板量程重置视口」
  若仍需要，做成显式按钮（并同步 `ui/hints.py` / `ui/quickref.py`），不藏在空提交里。
  `test_analysis_chart_options_unchanged_apply_reapplies_parameters` 随之改为断言 no-op。
  若产品方坚持原语义，则在本文记录为有意行为并补「还原按钮在此情况下可用」。
- `restore_opened` 只撤销 `_committed` 相对 `_opened` 的差异；颜色-only 的还原不得调用
  `apply_analysis_range_policy`。
- 删除 `_store_heatmap_color_policy`；`_capture_heatmap_chart_options` 只在 cmap 与默认不同时
  写入，`z_*` 由协调器单点决定。
- 验收：用户缩放 → 开关对话框 OK → viewport 与 origin 不变；颜色-only apply → 还原 →
  `apply_analysis_range_policy` 未被调用；手输 + Key_Up / 滚轮 → 提交值 == 显示值。

## 8. D6 — 热图协调器与注册表的错误路径（H2 / H3 / H4 / H5 / H6 / H8）

- `sync_committed_preset` 捕获 `HeatmapColorPolicyError`，走 `_reject_heatmap_color_render`
  同一出口并给状态栏反馈；或在 `preset_state` 加载层校验 z 顺序并给出 item 级错误。两者都
  不得吞掉其他异常。
- `_sync_active_analysis_params` 只捕获 `HeatmapColorPolicyError`，`logger.warning` 留痕，
  返回值区分「无变化」与「被拒」。
- `_fft_time_render_inputs` 增加 `dry_run` 或接受已解析 policy；`_heatmap_picture_is_current`
  不得留下 `_prepared` 记录。
- 色条拖拽：拖拽中只投影画布，释放（或复用既有 150 ms 空闲窗，**不改其 interval**）后才
  `commit`；`DbReferenceSettings.snapshot()` 加脏标记缓存。
- `colormaps/registry.py` 的 catalog 读取改为惰性 `lru_cache` 函数；失败 `logger.error` 并返回
  仅含 fallback 的最小目录；`SUPPORTED_HEATMAP_COLORMAPS` 改为函数或惰性属性，所有消费者同步。
  `tests/test_windows_build_script.py` 钉住 `--add-data` 源目录存在。
- fallback 参考下保留旧 basis 不写回，`logger.info` 一次。
- 验收见 plan T6–T8。

## 9. D7 — FRF Pin 来源状态与分屏 colorbar（K1 / K2 / K5 / K6 / K3 / K4 / K7）

Owner：[pinned_cursor_controller.py](../../../mf4_analyzer/ui/chart_stack/pinned_cursor_controller.py)、
[pinning/sampling.py](../../../mf4_analyzer/ui/chart_stack/pinning/sampling.py)、
[cursor_pill.py](../../../mf4_analyzer/ui/chart_stack/cursor_pill.py)、
[pinning/presentation.py](../../../mf4_analyzer/ui/chart_stack/pinning/presentation.py)、
[heatmap_canvas.py](../../../mf4_analyzer/ui/pg_canvas/heatmap_canvas.py)。

- `intent.domain == "frf"` 时 `_reproject_now` / `_reconcile_sample` 短路：不生成通道占位行，
  直接产出带明确 diagnostic（如「来源已更换」）的 `UNAVAILABLE` 样本，由 `pill_content` 显示。
  role-less 旧记录以 `(input, output)` 有序对比较。
- `CursorPill.set_display_projection(None)` 走 `_clear_display_projection()`：清隐藏 `_detail`、
  `_primary.setMinimumHeight(0)`。
- `_size_colorbar_value_axis` 在 `_split_aligned` 时跳过或发 `layout_geometry_changed` 让页面
  重跑 `sync_heatmap_layouts`；`heatmap_layout_metrics` 的 colorbar 项与左轴一样取
  `max(ticks, axis.width())`。
- 重投影事务内只在末尾 `arrange_pinned_panels` 一次、`set_tethers` 一次（N ≥ 2 断言）。
- `_measure_span` 缓存加容量上限（LRU），结构签名变化仍整体重置。
- 验收：三种来源变体的卡片 primary/detail 文本；legacy + swapped → `evaluate_intent` 为 None；
  分屏 colorbar 拖动后主图宽度一致；N=4 时 `set_tethers` 调用 1 次；ready→pending→ready
  尺寸回落且 pending 态 `has_detail()` False。

## 10. D8 — 原生启动器与 HEAD HDF（S1–S13 / S17）

Owner：`native/startup_launcher/*`、[startup_native_feedback.py](../../../mf4_analyzer/startup_native_feedback.py)、
[head_hdf.py](../../../mf4_analyzer/io/head_hdf.py)、`tools/build_startup_launcher.ps1`。

### 10.1 启动器

- `runtime_thread` 把 `ERROR_BROKEN_PIPE` / `ERROR_NO_DATA` 视为 EOF → `hide_panel("pipe_eof")`；
  「首个 stage 之后 N 秒无 finish」有上限，常量与 Python 侧 `HANDOVER_FALLBACK_TIMEOUT_S` 同源
  （生成进 `startup_resources.h`，不手抄）。`WM_CLOSE` 可达（Esc）。
- `#define _CRT_RAND_S` 置于任何系统头之前，或改 `BCryptGenRandom`；`tests/test_windows_build_script.py`
  加源级断言。
- `presented.screen` 改为逻辑坐标（`MulDiv(…, 96, dpi)`）或协议显式带 `dpi` 与坐标系字段；
  Python `parse_screen_rect` 拒绝未声明坐标系的 payload。
- `launch_dispatch.cc` 裁剪全部 ASCII 空白、环境变量键大小写不敏感；parity fixture 加
  `"0\n"`、`" 1 "`、小写键用例。
- JSON 深度 >32 fail；读缓冲总量上限；`double → int` 先 `isfinite` 再夹紧；GDI+ `Graphics`
  内层作用域；`CreateThread` 失败走 `create_pipes` 失败同一出口；`measure_windows_startup.py`
  按进程树杀；生成目录与 `.obj` 进 `build\`；1.5× 判据同源。
- `_reader_main` EOF 与 `_watchdog_main` 超时各一条 `logger.warning`。
- `test_startup_launcher_core.py` 按 `clang++ → g++ → c++` 取第一个能编译空程序的编译器。
- **Windows 真机门禁**：一次 `-NativeStartupLauncher` MSVC 构建 + 单屏 100% / 主屏 150% +
  副屏启动 / 管道断开三种场景截图。没有这组证据不得关闭 S1–S3 / S5。

### 10.2 HEAD HDF

- `code page` 映射成解码器（936 → cp936、1252 → cp1252、65001 → utf‑8；未知值
  `errors="replace"` + warning），不是拒载条件。
- 字节数 / 截断检查前移到任何大数组分配之前；时间轴校验改解析式（首步与末步相对误差），
  只建一次轴。
- 验收：1252 头部 + 非 ASCII 通道名可读、数据与时间轴与 936 版本一致；`nbr of scans` 巨大
  但文件很小 → `ValueError` 而非 `MemoryError`。
- 绝对时间语义（24 kHz / 72.2 s）仍待 HEAD Companion 官方对照（U1）；在对照完成前 changelog
  / README 把「恢复真实采样间隔」改成「按头部 delta 恢复，官方对照待完成」。

## 11. D9 — 文档与发版面（S14 / S15 / S16 / H9）

- 主册 changelog 与 README 补 8.4.2 之后的四个用户可见功能，并注明 HEAD 色板成为默认对旧工程
  的影响（H9）。升 8.4.3 还是追加进 8.4.2 由发版 owner 决定；升版须走 CLAUDE.md / AGENTS.md
  的全部扇出与四个测试契约。
- `2026-09-25-head-hdf-timebase-robustness-plan.md` **不改**；在本 plan 记录 S15「指纹核验未
  接线」为已知未实现。
- macOS 帮助：`Popen` / `openUrl`；`copytree(dirs_exist_ok=True)` 或临时名 + rename；旧 stamp
  目录在成功复制新目录后清理。

## 12. 验收清单

| ID | 可验证出口 | 证据类别 |
| --- | --- | --- |
| A1 / H1 | 四种模式 × 两 View 切换、dB↔线性、锁定/解锁、跨 View 锁定后各自自然窗 | 真实 `MainWindow` offscreen 集成 + 协调器单测（真字段 fake） |
| A2 / C1 C2 C5 | 四分区隐式结束对比后 Inspector/宿主 params；范围策略只改目标轴键 | offscreen 集成 |
| A3 / C3 | 关闭全部文件两种决定后关系为空；保存载荷无悬空 host | offscreen + 工程文件回环 |
| A4 / O1 O5 | log 下量程 == 工程量程；跨 View 隔离；工程回环 | 画布单测 + 对话框端到端 |
| A5 / O2 O3 O4 | 提交值 == 显示值；空提交 no-op；还原对称 | 对话框单测 |
| A6 / H2–H6 H8 | 坏 preset 不抛到钩子；拖拽 commit 次数有界；retain 判定无副作用；资源缺失可降级 | 单测 + 子进程 import |
| A7 / K1 K2 K5 | 三种来源变体文案；colorbar 拖动后对齐；legacy swapped 拒绝 | 真实 ChartStack offscreen；**Cocoa 卡片截图待真机** |
| A8 / K3 K4 K7 | N≥2 一次 `set_tethers`；pending 态尺寸回落；缓存有界 | offscreen |
| A9 / S1–S3 S5 S6 S10 | 可移植核心 parity 与畸形输入；**Windows 真机三场景** | g++ / clang++ 核心测试 + Windows 前台 |
| A10 / S4 S7 | 1252 可读；巨大计数 → 数据错误 | IO 单测 |
| A11 / S16 H9 | changelog / README 与功能面一致 | `test_help_content.py` + 文档核对 |

功能实现、focused / boundary、全量集成、macOS 前台、Windows 真机是不同状态列。平台未运行时
报告「代码完成、原生验收待完成」，不得写整体完成。
