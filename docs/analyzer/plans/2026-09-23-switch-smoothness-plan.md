# Section / View 切换平顺性优化计划

- 日期：2026-09-23。
- 状态：**源码实施已到 Task 1–6，以及 Task 4（D-A）；Task 8 全局 GC 冻结经复审撤回。Task 0 的 Windows 基线、Task 5 的 F3、Task 7 的 Windows 真机标定未做。** 本次复审修正了热力图保留揭示期间的 AA hold、离开 Section 前的延后预览、探针 AA 口径与跨字体刻度回归。验证范围见 `docs/analyzer/verify/2026-09-23-switch-smoothness-followup.md`。Task 7 不改现有 ink / 兜底常量，也不引入 `_DISCRETE_AA_FRAME_BUDGET_MS`（决策门没有 Windows 读数）。
- 编写基线：`ef63e1e6`，`app_meta.py` 版本 `v8.3.2`。执行前重新记录 HEAD 与相关文件指纹；源码变化后，报告里的数字只能作为参考，不能当作基线。
- 设计：`docs/analyzer/specs/2026-09-23-switch-smoothness-spec.md`（下称 spec，设计项编号 D-A…D-I）。
- 问题与数字：`docs/analyzer/reviews/2026-09-23-windows-switch-smoothness-analysis.md`（下称报告）。
- 用户观察：Windows 下功能模块（Section）和 View 切换都“卡卡的、不丝滑”；时域、FFT、阶次来回切都卡。
- 执行方式：默认单负责人顺序实施，每个 Task 独立提交、独立可回退。不要求多代理；若并行，只能按 §3.4 的文件归属拆分，全量门禁由协调者独占。

## 1. 目标、范围与完成口径

### 1.1 用户体验目标

1. 淡入动画不再中途冻住；首次进入 FFT 不再冻 1 秒后硬切。
2. 进入 FFT vs Time、阶次、时域时，主线程不再出现 200 ms 以上的阻塞。
3. 画质不降低：淡入结束后，允许 AA 的曲线仍然变平滑；显式导出、复制仍是 AA。
4. UltraView 缩略图、项目预览仍然正确，只是不再做没有变化的截图。

### 1.2 初始性能目标

与 spec §2.2 相同，Task 0 用 Windows 基线校准；校准要记录硬件和原因，不能在不达标后悄悄放宽。

| 指标 | 初始目标 |
|---|---|
| 切换期间主线程单次最长阻塞 | ≤ 100 ms；淡入期间 ≤ 33 ms |
| 淡入结束时间 | ≤ 动画时长 + 100 ms |
| `target-paint-timeout` | 0 次（12 方向 × 3 圈，含首次进入） |
| 点击处理同步段（保留揭示命中） | 分析 Section ≤ 60 ms；时域 ≤ 40 ms |
| 同一画布一次切换的 AA 帧数 | ≤ 1 |

### 1.3 范围限制

- 不改 ink 阈值、兜底阈值、150 ms 交互静默窗、1000 ms 过渡看门狗；只有 Task 7 可以在标定流程里改标定值。
- 不永久关闭 AA，不用固定延时交付“就绪”，不为每个 View 常驻画布或截图，不把 AA 光栅搬到工作线程。
- 不复用 FFT 结果签名；不改变 UV-A18 离开页同步截图；不改变显式导出、复制的画质。
- 用户可见的交互不变。若 Task 7 引入新的可见质量状态文字，按 AGENTS.md 同步 `ui/hints.py` 与 `ui/quickref.py`。

## 2. 已有证据与待确认项

### 2.1 已确认（报告，offscreen 代理）

| 问题 | 证据 | 对应 Task |
|---|---|---|
| 切片曲线永远 AA（S1、S6） | 4097 点切片重绘 AA 108 ms / 非 AA 8.5 ms；进入 FFT vs Time paint 合计约 528 ms | Task 2 |
| FFT 握手判废（S2） | 第 1 圈淡入结束 1113 ms，`target-paint-timeout`；`PROBE_ACK_PREPARE` 后 475 ms | Task 1 |
| AA 升级落在淡入里（W2、S3） | 淡入帧间隔含 225 ms；`PROBE_NO_AA_UPGRADE` 后进入时域阻塞约 230 → 100 ms | Task 4 |
| UltraView 去重失效（W1、S5） | digest 相同、revision 每次 +1；每次切换截图 5–730 ms | Task 3 |
| 刻度重复计算（S4） | 每次进入 28–32 次，124–178 ms | Task 5 |
| 每次进入完整重画（S7） | `_on_analysis_view_switched` 约 73–76 ms，其中重画约 52 ms | Task 6 |
| 准入带未在 Windows 标定（W3） | 08-08 spec 状态行与 §7.4；README 发布门 | Task 7 |
| GC 停顿（W7） | 第 2 代停顿 60–65 ms；全局 freeze 方案有循环回收缺陷，已撤回 | Task 8；性能问题待后续设计 |

### 2.2 Task 0 必须补齐

1. Windows 源码前台基线（报告里没有任何 Windows 数字）。
2. UltraView 预览的全部消费者清单（Task 3 的前提）。
3. 四处握手实现的逐行差异（Task 1 决定是否抽共享 helper）。
4. 阶次、FFT vs Time 渲染函数实际读取的全部展示输入（Task 6 的前提）。

## 3. 必须保持的设计合同

### 3.1 渲染质量

- `TestDiscreteSettle`：150 ms 定时器 `interval() == 150`；离散路径使用独立的单次 0 ms 定时器。
- `TestViewRestoreSettlement`：`_render_view_to_canvas` 依次调用 `restore_visible_xlim(flush=False)`、`restore_visible_ylims`、`settle_view_restore()`，恰好结算一次。
- 分析画布 `plot_spectra` / `set_result` 返回时曲线 AA 全关；AA 由 ink **与**点数两条腿共同判定；实测兜底覆盖二者。
- 真画布安装 paint 计时兜底（`test_frame_paint_backstop_is_installed_on_real_canvas`）。
- 未测量过的曲线必须当场测量，不能当作 0 ink。

### 3.2 页面过渡与截图

- 过渡的“就绪”来自目标画布的自然 paint 握手，不来自时长。
- 离开页截图同步执行（UV-A18）；自动预览不能永远 pending，也不能抓半成品帧。
- 过渡重定向时只有最终目标生效。

### 3.3 状态与分层

- 新状态有唯一 owner、显式初始化，并在 `clear()`、销毁、项目或 View 恢复时对称重置；必需的保护不依赖 `getattr(..., False)`。
- 画布协作者的新状态在其 `_owned_names` 中声明，不扩大 `test_pg_canvas_backref_invariants.py` 的写穿白名单。
- `test_main_window_state_ownership.py` 只许缩小；新接线不用 `.connect(lambda`。
- `ui/pg_canvas/` 不 import `ui/chart_stack/`；质量保持由 `chart_stack` 注入。
- 不加宽泛的 `except Exception: pass`；新 warning 走现有诊断节流。

### 3.4 并行时的文件归属（仅在需要并行时适用）

| 工作包 | 独占文件 |
|---|---|
| Task 1 | `line_canvas.py`、`heatmap_canvas.py`、`frf_canvas.py`、`canvas.py` 的握手段；`page_transition.py` 看门狗段 |
| Task 2 | `slice_panel.py`；`heatmap_canvas.py` 切片质量段 |
| Task 3 | `ultraview_capture_coordinator.py`；`renderer.grab_pixmap` 自动预览口径 |
| Task 5 | `analysis_axes.py`；`_split_mixin.py` |
| Task 6 | `_analysis_mixin.py`、`_order_mixin.py`、`_fft_time_mixin.py`、`_state_holders.py` |

Task 4 同时涉及 `chart_stack/stack.py`、`quality.py`、`line_canvas.py`、`frf_canvas.py`、`slice_panel.py`，必须在 Task 1、Task 2 合入后串行执行。

## 4. Task 0：建立可信基线

**目的：** 拿到同一 HEAD 上可比较的“改前”数字，并补齐 §2.2 的四项前提。

**步骤：**

- [ ] 记录 HEAD、脏文件范围、Python/Qt/pyqtgraph 版本、机器信息。
- [ ] offscreen 基线：`scripts/probe_switch_smoothness.py` View 场景（默认、`PROBE_NO_AA_UPGRADE`、`PROBE_NO_UV_AUTOCAPTURE`）与 Section 场景（基线、`--motion off`、`PROBE_ACK_PREPARE`、`PROBE_NO_SLICE_AA` + `PROBE_TICK_MEMO`、全部开关），结果放 `.state/switch-smoothness/baseline/`。HEAD 与报告相同且工作区干净时，可以复用报告的读数，但要注明。
- [ ] Windows 源码前台基线：同上两个场景，100% 与 150% 缩放各一组；记录 CPU、电源模式、分辨率。据此校准 §1.2 的目标值，并写回本文。
- [ ] 聚焦用例基线（不跑全量）：本文各 Task 列出的 owner 用例在改前跑一遍，记录既有红（先对照 `docs/analyzer/reviews/2026-08-15-post-v8-batch-review.md` §6 的顺序污染清单）。
- [ ] UltraView 预览消费者清单：搜索 `ultraview_capture_coordinator` 的预览读取方，列出每个消费者需要“即时”还是“可延后”，写入 `.state/switch-smoothness/uv-consumers.md`。
- [ ] 四处 `request_presentation_paint_ack` / `_presentation_paint_ack_token` / `_presentation_paint_acked` 的逐行差异，写入 `.state/switch-smoothness/paint-ack-diff.md`。
- [ ] 列出 `_render_order_on`、`_render_fft_time_on` 及其下游读取的全部展示参数，写入 `.state/switch-smoothness/heatmap-render-inputs.md`。

**验证：** 无产品代码改动，不跑额外测试。

**产出：** 基线 JSON、Windows 读数、三份清单；§1.2 目标值校准记录。

## 5. Task 1：淡入握手几何稳定（D-D）

**Owner：** `ui/pg_canvas/line_canvas.py`、`heatmap_canvas.py`、`frf_canvas.py`、`canvas.py`；`ui/chart_stack/page_transition.py`。

**步骤：**

- [ ] 先写失败用例：一张首次 paint 会改变 `viewRange` 的线图（延迟自动缩放），申请握手后 paint，断言确认成功、不取消。改前应失败。
- [ ] 在四处 `request_presentation_paint_ack` 记录几何前调用 `self._glw.scene().prepareForPaint()`（时域画布按其实际的 scene 访问方式）。
- [ ] 实现有界重申请：几何不一致且可见、generation 未变时重新登记，最多 `_PAINT_ACK_MAX_REARMS = 2` 次；超过上限取消，并记录节流 warning，包含变化的几何分量。
- [ ] `_on_target_ack_watchdog_timeout` 取消前记录节流 warning，带 Section/View 身份。
- [ ] 按 Task 0 的差异清单决定是否抽共享 helper：语义逐行等价才抽；否则四处分别实现并注释差异。

**聚焦用例：** `tests/ui/test_presentation_paint_ack_lifecycle.py`、`test_page_transition.py`、`test_page_transition_integration.py`、`test_section_page_transition.py`、`test_pg_line_canvas.py`（握手相关）、`test_pg_heatmap_canvas.py`（握手相关）、`test_frf_canvas.py`（握手相关）。

**边界护栏：** `test_pg_canvas_backref_invariants.py`、`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`。

**测量验收：** Section 场景 3 圈（含第 1 圈首次进入）`target-paint-timeout` 为 0；第 1 圈“时域 → FFT”淡入结束接近 `PROBE_ACK_PREPARE` 的 475 ms。

**回退：** 单独 revert 本 Task 提交；看门狗仍保证最坏 1 s 后结束过渡。

## 6. Task 2：热力图切片曲线纳入质量规则（D-C，不含过渡保持）

**Owner：** `ui/pg_canvas/slice_panel.py`、`heatmap_canvas.py`（切片质量段）。

**步骤：**

- [ ] 先写失败用例：切片重建返回时 `_slice_aa_on` 为 False，且离散定时器已 armed。
- [ ] `_reset_slice_quality_for_rebuild` 改为 AA 关；新增切片的独立单次 0 ms 离散定时器，到期时经闸门判定升级。交互路径的 `_slice_aa_idle_timer` 不变。
- [ ] 闸门：用 `render_profile.envelope_ink_dev_px` 计算切片 ink，借用 `_SPECTRUM_INK_AA_ON/OFF` 滞回判定；常量引用处注明“借用、待标定”（spec §5）。
- [ ] 兜底：接入 `quality_backstop.AaFrameLatch`，超兜底的签名拉黑，质量状态可观察。
- [ ] 新状态（离散定时器、latch、ink 缓存）在切片协作者 `_owned_names` 中声明；定时器在画布销毁时停止。
- [ ] 自动预览与离开页截图不强制切片 AA（与 Task 3 的 E3 口径一致；若 Task 3 未合入，本 Task 只保证切片自身不在截图中被强制打开）。
- [ ] 扩展 `scripts/probe_view_switch_quality.py analysis-calibrate` 覆盖切片行，供 Task 7 标定。

**聚焦用例：** `tests/ui/test_slice_panel.py`、`test_pg_heatmap_canvas.py`、`test_pg_quality_backstop.py`、`test_ultraview_capture.py`（热力图截图相关）。

**边界护栏：** `test_pg_canvas_backref_invariants.py`、`test_pg_line_canvas.py::test_spectrum_ink_gate_blocks_noise_floor_and_allows_peaks`（确认借用常量未被改动）、`test_no_lambda_signal_connections.py`。

**测量验收：** 进入 FFT vs Time 的目标页 paint 合计接近 `PROBE_NO_SLICE_AA` 的约 40 ms（不含淡入后那一次允许的 AA 帧）；从 FFT vs Time 离开的同步段降回约 40–90 ms。

**回退：** 单独 revert；切片回到永远 AA。

## 7. Task 3：UltraView 自动预览按需截图（D-E）

**Owner：** `ui/main_window/ultraview_capture_coordinator.py`；`ui/pg_canvas/renderer.py:grab_pixmap`、`ui/chart_stack/stack.py:grab_presentation_pixmap` 的自动预览口径。

**依赖：** Task 0 的消费者清单。

**步骤（按 E1 → E3 → E2 顺序，各自提交）：**

- [ ] E1 先写失败用例：同一 View 从缓存重画到相同范围，revision 不变；真实缩放、markup、双光标、手动缩放变化时 revision 递增。
- [ ] E1 实现：每个 ref 记录由 `_PIXEL_AFFECTING_SIGNALS` 对应事实组成的指纹，只在指纹变化时 `bump_presentation_revision`。指纹不持久化，不进 digest；ref 失效时清除。
- [ ] E3：为 `grab_pixmap` 增加“自动预览”口径，使用屏幕当前的 AA 状态；显式复制、导出、保存图片保持强制 AA，并有用例区分两种口径。
- [ ] E2：UltraView 页不可见且清单中没有即时消费者时，`request_capture` 只标记 stale；UltraView 显示时经现有空闲调度按可见顺序补截；保存路径在保存前补齐。stale 状态必须在显示或保存时被消费。
- [ ] 确认 UV-A18 离开页同步截图、`_defer_capture_for_page_transition`、digest/generation 校验不受影响。

**聚焦用例：** `tests/ui/test_ultraview_capture.py`、`test_ultraview_capture_facts.py`、`test_ultraview_structure.py`、`test_ultraview_compatibility.py`，以及 Task 0 清单里各消费者的 owner 用例（项目保存、临时检视）。

**边界护栏：** `test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`、`test_pg_canvas_backref_invariants.py`（若 renderer 口径改动触及协作者）。

**测量验收：** UltraView 关闭时，View 与 Section 场景中 UltraView 截图 paint 为 0；打开 UltraView 后缩略图与屏幕一致；项目保存得到的预览与改前一致。

**回退：** E1、E2、E3 各自可单独 revert。

## 8. Task 4：离散 AA 结算感知页面过渡（D-A）

**Owner：** `ui/chart_stack/stack.py`（持有与释放）；`ui/pg_canvas/quality.py`（时域）、`line_canvas.py`、`frf_canvas.py`、`slice_panel.py`（执行）。

**依赖：** Task 1、Task 2 已合入。

**步骤：**

- [ ] 先写失败用例（offscreen，走真实入口）：切回允许 AA 的时域 View 与进入时域 Section，过渡期间目标画布 AA 始终关；`transition_finished` 后恰好一次升级。另写取消、重定向（A→B→C）、动效关闭四个变体。
- [ ] 在各质量 owner 上实现 `hold_discrete_quality(token)` / `release_discrete_quality(token)`：保持期间离散结算（含 `_SYNC_AA_MAX_MS` 同步分支）只登记待结算；释放时若有待结算，启动**原有**的独立 0 ms 离散定时器。150 ms 定时器不触碰。
- [ ] `ChartStack` 在开始过渡时对目标页画布持有，在 `transition_finished` / `transition_cancelled` 时释放；token 绑定过渡 generation，重定向时释放旧 token。接线使用 bound method。
- [ ] 保持状态在 `clear()`、画布销毁、项目重开时清空；不依赖 `getattr(..., False)`。
- [ ] 确认解冻重绘是非 AA 帧，随后的一次升级被 paint 计时兜底测量。

**聚焦用例：** `tests/ui/test_pg_timedomain_canvas.py::TestDiscreteSettle`、`::TestViewRestoreSettlement`、`::test_frame_paint_backstop_is_installed_on_real_canvas`、`test_pg_line_canvas.py::test_plot_spectra_returns_with_aa_off_and_discrete_timer_armed`、`test_frf_canvas.py::test_frf_set_result_arms_discrete_aa_instead_of_painting_an_aa_frame`、`test_section_page_transition.py`、`test_page_transition_integration.py`、`test_view_switch_integration.py`、`test_view_switch_reentrancy.py`、`test_slice_panel.py`。

**边界护栏：** `test_pg_canvas_backref_invariants.py`、`test_import_boundaries.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`。

**测量验收：** View 场景淡入帧间隔最大 ≤ 33 ms（offscreen 代理）、淡入结束接近动画时长 + 约 70 ms；Section 场景进入时域最长阻塞接近诊断投影的 100 ms；每画布每次切换 AA 帧 ≤ 1。

**回退：** 单独 revert；回到“下一轮就升级”。

## 9. Task 5：热力图刻度记忆与首次显示对齐合并（D-F）

**Owner：** `ui/pg_canvas/analysis_axes.py`；`heatmap_canvas.py`、`_split_mixin.py`（F3）。

**步骤：**

- [ ] 先写冻结用例：对一组参数（范围跨 6 个量级、轴宽 80–2000 px、DPR 1/1.25/1.5/2、不同目标刻度数与格式化器）记录现算法的刻度位置与文字。
- [ ] F1：按轴对象记忆（X `viewRange`、轴像素宽、DPR、目标数、可见性、字体度量、格式化器身份）→ 输出；键相同直接复用。
- [ ] F2：生成字符串前按“值个数 × 最小标签间距 > 轴宽”剪掉必然被拒的候选；冻结用例逐位一致。
- [ ] 测量 F1+F2 后进入阶次 / FFT vs Time 的同步段；若首次显示对齐仍超过约 30 ms，再做 F3：`showEvent` 中的 4 次 `_align_slice_to_main` 与 2 次 `reset_split_layout_alignment` 合并为最终几何上的一次，保留 `_deferred_first_show_align`，并确认在 Task 1 的握手采样之前完成。

**聚焦用例：** `tests/ui/test_analysis_axes.py`、`test_tick_label_precision.py`、`tests/ui_kit/test_ticks_math.py`、`test_pg_heatmap_canvas.py`（布局与对齐相关）、`test_presentation_paint_ack_lifecycle.py`（F3 时）。

**边界护栏：** `test_pg_canvas_backref_invariants.py`、`test_import_boundaries.py`。

**测量验收：** 进入阶次 / FFT vs Time 时刻度计算合计 ≤ 20 ms；刻度输出逐位一致。

**回退：** F1、F2、F3 各自可单独 revert。

## 10. Task 6：热力图 Section 的保留揭示（D-G）

**Owner：** `ui/main_window/_analysis_mixin.py`、`_order_mixin.py`、`_fft_time_mixin.py`；签名状态放在 `_state_holders.py` 的具名 holder 或各渲染 owner。

**依赖：** Task 0 的渲染输入清单；Task 1（揭示仍走握手）。

**步骤：**

- [ ] 按清单为阶次、FFT vs Time 各定义不可变渲染输入对象；重构 `_render_order_on`、`_render_fft_time_on` 只从该对象读取展示参数。先做纯重构并用现有用例冻结行为，再加签名。
- [ ] 签名 = 渲染输入对象哈希 + 结果身份/generation。`_on_analysis_view_switched(render=True)` 在热力图 Section 上先比较签名，命中且画布仍持有该画面时走保留揭示。
- [ ] 失效点：重算、View 切换到不同结果、`clear()`、项目重开、画布销毁。
- [ ] 逐字段用例：改变渲染输入对象的任一字段都触发重画；全不变时不重画。
- [ ] 附带：阶次 nfft 预览按（转速通道复合身份、参数）记忆 `revolutions_from_rpm`；FFT vs Time 的 dB 参考提示只在输入变化时重算。

**聚焦用例：** `tests/ui/test_analysis_multiview_integration.py`、`test_section_page_transition.py`、`test_view_switch_integration.py`，以及阶次、FFT vs Time 的现有渲染与 Inspector 用例（Task 0 列出）。

**边界护栏：** `test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`。

**测量验收：** 结果未变时进入阶次 / FFT vs Time 的同步段 ≤ 60 ms（offscreen 代理），并在 Windows 前台复测。

**回退：** 签名比较一处开关式 revert 即回到每次重画；渲染输入对象的纯重构可保留。

## 11. Task 7：Windows 标定与离散切换 AA 预算（D-B）

**Owner：** 08-08、08-15 spec §5 与本 spec §5；常量所在的 `renderer.py`、`quality.py`、`line_canvas.py`、`frf_canvas.py`、`slice_panel.py`。

**依赖：** Task 2、Task 4 已合入；Windows 目标机可用。

**步骤：**

- [ ] 在 Windows 目标机上运行 `scripts/probe_aa_ink_budget.py` 与 `scripts/probe_view_switch_quality.py analysis-calibrate`（含 Task 2 扩展的切片行），并在 Cocoa 上补测切片行。
- [ ] 先改相应 spec §5，再改常量；若需要按平台区分，spec 中写明平台判定方式。
- [ ] 决策门：用 Windows 读数判断“淡入结束后的一次 AA 帧”是否可接受。可接受则不引入 `_DISCRETE_AA_FRAME_BUDGET_MS`；不可接受时按 spec §3.7 实现，并确认质量状态显示“等待”而不是“关闭”。如新增可见状态文字，同步 `ui/hints.py` 与 `ui/quickref.py`。
- [ ] 跑 `scripts/benchmark_timedomain_interaction.py --assert-standards`，不放宽上限。

**聚焦用例：** `tests/ui/test_pg_timedomain_canvas.py::TestInkBudget`、`test_pg_line_canvas.py` 的 ink 闸门与点数腿用例、`test_frf_canvas.py` 的 ink 闸门与兜底用例、`test_slice_panel.py`、`test_pg_quality_backstop.py`。

**边界护栏：** `test_pg_canvas_backref_invariants.py`、`test_import_boundaries.py`。

**测量验收：** Windows 前台 View 与 Section 场景达到 Task 0 校准后的目标。

**回退：** 常量改动与预算逻辑分开提交，各自可 revert。

## 12. Task 8：撤回全局冻结，恢复循环回收（D-I）

**Owner：** 文件加载完成回调（`ui/main_window/`）与 `app.py` 启动完成点。

**步骤：**

- [x] 删除启动、加载和关闭路径的全局 freeze/unfreeze，保留默认 GC。
- [x] 用真实循环对象与弱引用验证重复加载、关闭单个源、关闭全部源后的可回收性；不再使用 mock 调用次数作为内存安全证据。
- [ ] 长会话 RSS 和第 2 代 GC 停顿仍需真机观察；不得将本次可回收性用例当作性能验收。

**聚焦用例：** `tests/ui/test_gc_freeze_on_load.py`；加载与关闭的现有 owner 用例（Task 0 列出）、`tests/ui/test_startup_preload.py`。

**边界护栏：** `test_main_window_state_ownership.py`、`test_packaging_imports.py`。

**验收边界：** 此次修正恢复对象回收；不承诺消除 ≥ 30 ms 的第 2 代 GC 停顿。未来 GC 优化须同时验证停顿和长会话内存。

**回退：** 不恢复已知会保留循环垃圾的全局冻结方案。

## 13. Task 9：接续已有工作（D-H）

不在本计划内实现，只纳入统一验收：

- 通道树重复投影：`2026-09-15-interaction-smoothness-and-page-transition-plan.md` T1。
- 时域入口重复准备数据：`2026-09-15-interaction-smoothness-audit.md` F4。
- 点击先行反馈：`2026-09-12-navigation-feedback-timing-followup.md` 与 09-15 计划 §2.2。

这些项的实施与验收由原计划负责；本计划的最终验收矩阵会记录它们落地前后的叠加效果。

## 14. 最终验收矩阵

| 证据等级 | 内容 | 判定 |
|---|---|---|
| offscreen 结构 | spec §4 全部护栏；Section 场景 12 方向 × 3 圈 `target-paint-timeout` 为 0，淡入期间目标页 AA paint 为 0，每画布每次切换 AA 帧 ≤ 1 | 必须通过 |
| offscreen 代理成本 | View 与 Section 场景对照报告 §2.1 与 §6 投影 | 不劣于投影 |
| Windows 源码前台 | View 与 Section 场景，100% / 150% | 达到 Task 0 校准目标 |
| Windows Full / Lite frozen | Section 场景各一次 | 与源码前台同量级 |
| macOS Cocoa | 08-15 spec §6 探针；本探针 View 与 Section 场景 | 不出现超出重复测量波动的退化 |
| 画质 | 淡入结束后允许 AA 的画布为 AA；导出、复制为 AA；UltraView 缩略图与屏幕一致 | 必须通过 |
| 全量测试 | 发版或合并验收时按 AGENTS.md / CLAUDE.md 两条命令串行执行一次 | 既有红对照已知清单 |

没有对应平台运行的一行写 `UNVERIFIED`，不能用 offscreen 或源码检查替代。

## 15. 验证、实施顺序与回退

- **顺序：** Task 0 → Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7 → Task 8。Task 1、2、3、5 彼此独立，可调整顺序；Task 4 依赖 Task 1、2；Task 7 依赖 Task 2、4；Task 6 依赖 Task 1。
- **每个 Task：** 先写失败用例或确定性探针；再实现；跑本 Task 的聚焦用例与边界护栏；用探针复测并把读数记到 `.state/switch-smoothness/<task>/`；最后 `git diff --check`。不因为改了一个 UI 文件就跑整个 `tests/ui`。
- **全量测试：** 只在最终合并验收时跑一次，先 `--ignore=tests/acquisition_ui` 跑主体，再单独跑 `tests/acquisition_ui`，前后记录 HEAD 与脏文件范围；中断或期间文件被改记为 `UNVERIFIED`。
- **回退：** 每个 Task（以及 Task 3 的 E1/E2/E3、Task 5 的 F1/F2/F3）独立提交，可单独 revert；Task 4 revert 后 Task 2 的切片仍按“下一轮”结算，不会失去 AA。

## 16. 交付物与依据

- 产品改动：按 Task 分提交。
- 测试：spec §4 列出的新增与更新用例。
- 标定：08-08、08-15 与本 spec §5 的回写；Windows 与 Cocoa 读数。
- 证据：`.state/switch-smoothness/`（本地，不入库）；持久的真机读数按 Routing 表放 `docs/analyzer/verify/`。
- 依据：报告；spec；`specs/2026-08-08-timedomain-aa-ink-budget-spec.md`；`specs/2026-08-15-view-switch-quality-settlement-spec.md`；`plans/2026-09-12-section-switch-performance-plan.md`；`plans/2026-09-15-interaction-smoothness-and-page-transition-plan.md`。
