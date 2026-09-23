# Windows 下 Section / View 切换不顺滑：原因分析

日期：2026-09-23。版本：v8.3.2。分析 HEAD：`ef63e1e6`（第二轮补充基于同一源码）。

本报告分两轮完成。第一轮分析时域 View 切换；第二轮补充时域、FFT、阶次、FFT vs Time 四个
Section 之间来回切换的卡顿。两轮都只做分析、诊断测量和文档，**没有修改产品代码**。
诊断脚本 `scripts/probe_switch_smoothness.py` 可在 Windows 真机上复跑同一组测量。

优化设计与实施计划另见：

- spec：`docs/analyzer/specs/2026-09-23-switch-smoothness-spec.md`
- plan：`docs/analyzer/plans/2026-09-23-switch-smoothness-plan.md`

## 结论

**主因不是 Python 的硬限制，而是软件自身的渲染策略和时序：一次切换会在 GUI 主线程上串行做好几次“整张图重绘”，其中最贵的是抗锯齿（AA）曲线重绘。** 同一画面的非 AA 重绘约 5–9 ms，AA 重绘约 100–220 ms。

**View 切换**（第一轮）：切回一个允许 AA 的时域 View，会连续触发三次约 220 ms 的 AA 整图重绘：淡入中途的 AA 升级、淡入结束解冻后的重绘、UltraView 自动预览截图。

**Section 切换**（第二轮）：四个 Section 的代价差别很大，卡顿集中在“进入 FFT vs Time”“进入阶次”“进入时域”和“离开 FFT vs Time”四个方向。

| 进入的 Section | 点击处理同步段 | 主线程最长阻塞 | 淡入结束（240 ms 动画） | 主要原因 |
|---|---:|---:|---:|---|
| FFT（结果未变） | 约 43 ms | 约 75 ms | 约 340 ms | 基本顺畅，已有“结果未变不重画” |
| FFT（首次、需要重画） | 约 45 ms | 约 160 ms | **约 1110 ms** | 淡入握手被预览图的延迟自动缩放判废，等满 1 s 看门狗后硬切 |
| 阶次 | 约 134 ms | 约 235 ms | 约 485 ms | 热力图首次显示的反复布局和刻度计算、从缓存重画整套结果 |
| FFT vs Time | 约 145 ms | **约 430 ms** | 约 680 ms | 4097 点切片曲线**永远 AA**、每次进入画约 5 帧；外加上面两项 |
| 时域 | 约 38 ms | 约 230 ms | 约 590 ms | 与 View 切换同一机制：AA 升级落在淡入里 + 解冻后再画一次 |

从 FFT vs Time 离开时，离开页截图会让热力图再做一次约 100 ms 的 AA 重绘，所以“从 FFT vs Time 出去”的同步段是 133–228 ms，从其他 Section 出去只有约 40 ms。

诊断对照（只在探针里关掉或修补，不是产品设置）同时去掉切片 AA、刻度重复计算、淡入内 AA 升级、UltraView 自动截图，并修好 FFT 的淡入握手之后：

- 进入 FFT vs Time 的最长阻塞从约 430 ms 降到约 165 ms，淡入结束从约 680 ms 降到约 415 ms；
- 进入阶次从约 235 ms 降到约 155 ms；
- 进入时域从约 230 ms 降到 100 ms；
- 首次进入 FFT 不再等 1 s 看门狗。

剩下的约 90–100 ms 同步段主要是“每次进入分析 Section 都从缓存重画一整套结果”和热力图页面的布局，这是 spec 里“保留揭示”（retained reveal）和布局合并两项要处理的。

Python 的作用是“放大器”，不是主因。所有编排和绘制串行跑在一个 GUI 线程上；每次切换约 20–50 ms 的 Python 层编排开销；偶发 15–65 ms 的 GC 停顿。最贵的 AA 光栅化发生在 Qt 的 C++ 代码里，换成 C++ 写同样的架构也一样慢。

## 1. 一次“卡”的时域 View 切换在时间线上长什么样

场景：切回 View A（3 条 200k 点带噪正弦，ink 146.7k 设备像素，低于 `_INK_AA_ON = 200k`，因此允许 AA）。125% 缩放，淡入开启（生产默认）。时间从点击开始计。

| 时刻 | 主线程在做什么 | 耗时 | 用户看到的 |
|---|---:|---:|---|
| 0–55 ms | 同步处理：截取离开页、投影 Navigator/Inspector、选择增量（`subplot-object-reuse`，约 5 ms）、范围恢复与结算 | 约 50 ms | 什么都没变，标签高亮也还没画出来 |
| 约 61 ms | 目标画布第一次自然 paint（非 AA）→ 淡入开始 | 8 ms | 淡入开始 |
| 约 75 ms | 离散结算触发 AA 升级，整图 AA 重绘 | **约 220 ms** | **淡入在第 3 帧冻住** |
| 约 300–535 ms | 淡入继续播完剩下的帧 | 每帧约 2 ms | 淡入“卡一下再走” |
| 约 540 ms | 淡入结束，解冻目标画布，再次 AA 重绘 | **约 220 ms** | 这段时间点击、滚轮会排队 |
| 约 767 ms | UltraView 自动预览截图（强制 AA） | **约 220 ms** | 同上 |

切换后大约 1 秒内，主线程约有 720 ms 在忙，其中约 660 ms 是三次 AA 整图重绘。反过来切到 View B 时（ink 302.7k，高于 `_INK_AA_OFF = 300k`，屏幕上不开 AA），淡入按时约 320 ms 结束，最长阻塞约 40 ms。用户在两个 View 之间来回点，就会感觉“有时顺、有时卡”。

## 2. Section 切换：按方向拆开的代价

场景：同一个文件（8 通道 × 200k 点 @ 10 kHz，含 `motor_speed` 600→3000 rpm 斜坡和 `motor_torque` 2/6 阶纹波），四个 Section 都已算好结果（FFT 3 通道；阶次和 FFT vs Time 各 1 通道，阶次用电机转速做基准）。125% 缩放，窗口 1536×824 逻辑像素，淡入开启。探针按欧拉回路把 12 个有向切换各走一遍，共 3 圈。表中是第 2、3 圈的中位数（第 1 圈含首次进入，单独说明）。

### 2.1 12 个方向的基线

| 切换 | 同步段 ms | 最长阻塞 ms | 淡入结束 ms | 目标页 paint 合计 ms |
|---|---:|---:|---:|---:|
| 时域 → FFT | 44 | 77 | 341 | 32 |
| 阶次 → FFT | 43 | 75 | 340 | 34 |
| FFT vs Time → FFT | 141 | 172 | 438 | 133 |
| 时域 → 阶次 | 134 | 237 | 489 | 31 |
| FFT → 阶次 | 134 | 234 | 485 | 35 |
| FFT vs Time → 阶次 | 228 | 327 | 578 | 131 |
| 时域 → FFT vs Time | 148 | 436 | 688 | 525 |
| FFT → FFT vs Time | 141 | 427 | 678 | 530 |
| 阶次 → FFT vs Time | 145 | 431 | 682 | 528 |
| FFT → 时域 | 38 | 232 | 597 | 489 |
| 阶次 → 时域 | 38 | 230 | 579 | 481 |
| FFT vs Time → 时域 | 133 | 229 | 674 | 581 |

“目标页 paint 合计”包含离开页截图、淡入期间和结束后的所有画布 paint。进入时域的 489 ms 里约 450 ms 是两次 AA 帧；进入 FFT vs Time 的 525 ms 里约 104 ms 是 UltraView 截图，其余主要是切片曲线的 AA 帧。

第 1 圈的“时域 → FFT”是首次需要重画 FFT：淡入结束 **1113 ms**，过渡记录为 `target-paint-timeout`（见 S2）。

### 2.2 淡入不是原因

关掉淡入（`--motion off`）后，最长阻塞基本不变：进入 FFT vs Time 约 400–415 ms，进入阶次约 200 ms，进入时域约 230 ms。同步段少了约 30 ms（不再截取离开页、不建覆盖层）。所以卡顿来自切换期间主线程上的工作量，不是淡入动画本身；淡入只是让它更容易被看出来（动画冻住）。

## 3. 测量方法与证据等级

- 环境：Linux offscreen，Qt 5.15.14 / PyQt5 5.15.11 / pyqtgraph 0.14.0 / Python 3.12.3，4 vCPU Intel Xeon。生产 QSS、Fusion、中文字体；QSettings 隔离。
- View 场景数据：合成 CSV，8 通道 × 200k 点 @ 10 kHz；View A、View B 各勾 3 条不同通道。另测 1000 通道 × 2000 点（候选列表规模）和 8 通道 × 1M 点。窗口按物理像素恒定约 1920×1030 设置（100% / 125% / 150%）。
- Section 场景数据：见 §2。四个 Section 的结果由真实入口计算（`do_fft`、`do_order_time`、`do_fft_time`），不是注入的假结果。
- 操作走真实入口：`view_tabbar.switch_requested`、`toolbar.mode_changed`。
- 计时：主线程最长阻塞用 1 ms 心跳定时器测量；逐帧 paint 记录每次画布 paint 的耗时、是否 AA、是否在 UltraView 截图内、是哪种画布；关键函数用包装计时（每个方向输出前 15 项）。
- **证据等级：** offscreen 使用的 `QRasterPaintEngine` 与 Windows Widgets 相同，所以 paint 耗时可作为 CPU 光栅成本的代理。但它**不是** Windows 前台证据：没有 GDI/DWM 刷新，字体引擎不同，也不是 frozen exe。样本数只够定位结构性问题，不够给 P95 或发布验收结论。
- 落在测量窗口之后的阻塞可能漏计，所以时间线以逐帧 paint 记录为准。

复跑方法（Windows 源码环境去掉 `QT_QPA_PLATFORM`）：

```bash
# View 场景
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 PYTHONPATH=. \
  .venv/bin/python scripts/probe_switch_smoothness.py \
  --win-w 1536 --win-h 824 --motion light --out view.json
# Section 场景
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 PYTHONPATH=. \
  .venv/bin/python scripts/probe_switch_smoothness.py --scenario section \
  --reps 3 --win-w 1536 --win-h 824 --motion light --out section.json
```

诊断开关（环境变量，只在探针进程里 monkeypatch，不改产品代码）：

| 开关 | 作用 | 用来验证 |
|---|---|---|
| `PROBE_NO_AA_UPGRADE=1` | 时域和分析线图的离散 AA 升级不执行 | W2、S3 |
| `PROBE_NO_UV_AUTOCAPTURE=1` | UltraView 自动预览截图不执行（离开时同步截图保留） | W1、S5 |
| `PROBE_NO_SLICE_AA=1` | 热力图切片曲线永远不开 AA | S1、S6 |
| `PROBE_TICK_MEMO=1` | 热力图底轴刻度按（X 范围、轴宽、目标）记忆 | S4 |
| `PROBE_ACK_PREPARE=1` | 线图在记录淡入握手几何前先让场景完成布局（`scene.prepareForPaint()`） | S2 |

## 4. 发现

### 4.1 View 切换（第一轮）

#### W1 · P1 · UltraView 自动预览截图每次切换都强制做一次 AA 整图重绘

**路径：** `_render_view_onto_canvas` 末尾调用 `coord.request_capture(new_ref, canvas, "time-render")`，淡入期间由 `_defer_capture_for_page_transition` 挂到 `transition_finished`，之后进入 `_publish_grab` → `_grab_image` → `ChartStack.grab_presentation_pixmap` → `renderer.grab_pixmap`。只要 `_export_aa_affordable()` 为真，就在 `_quality._curves_antialiased()` 里强制 AA 做一次 `QWidget.grab()`。

**实测：** 每次切换约 220 ms；View B 在 100% 缩放下 ink 242k，处于滞回带里，屏幕上没开 AA，但截图判据只比 `_INK_AA_OFF`，所以仍被强制 AA，单次 **729 ms**。

**为什么每次都截（第二轮补充的根因）：** 截图去重 `_has_current_preview` 要求 digest **和** `presentation_revision` 都没变。切换时从缓存重画会发出视图范围、布局等“展示信号”，`_on_idle_presentation_signal` 收到后**无条件**递增 revision（为了让之后打开 UltraView 时知道缩放/光标变过）。于是即使 digest 完全相同，revision 也每次 2→3，去重永远不命中。`request_capture` 本身也不看 UltraView 是否可见，`_inactive()` 只看是否已关闭。

**为什么说是多余成本：** 用户没打开 UltraView 时也在截；截出来的是缩略图，AA 在缩略尺寸上几乎看不出差别。离开时的 `offer_capture_bound_canvas` 按合同同步执行（UV-A18），不在本项范围。

代码：`ui/main_window/_view_mixin.py:1149–1154`；`ui/main_window/ultraview_capture_coordinator.py:520`、`:569`、`:1521`、`:2169`；`ui/pg_canvas/renderer.py:877–928`；`ui/chart_stack/stack.py:2060`。

#### W2 · P1 · AA 升级落在淡入动画里，而且同一画面画了两次

**路径：** `settle_view_restore` → `QualityManager.settle_after_discrete_render`。memo 没有“便宜”的记录时，启动 0 ms 的 `discrete_timer`，下一轮事件循环就调用 `try_enable_idle_quality` 把曲线 AA 打开并 update。页面过渡在目标首帧自然 paint 后开始淡入，在下一轮才冻结目标画布更新，所以 AA 首帧正好插在淡入的第 2–3 帧之间。淡入结束解冻时，画布又整图重绘一次，而且还是约 220 ms 的 AA 代价。

**实测：** 淡入帧间隔 `[11, 23, 225, 20, 16, 16, …]` ms；淡入结束 535 ms，而 240 ms 的淡入本应在约 320 ms 结束。关掉 AA 升级后，帧间隔最大约 23 ms，淡入 313 ms 结束。

**与现有设计合同的关系：** 2026-08-15 View 切换质量结算 spec 把“离散切换下一轮就升级 AA”当作改进，这在没有淡入时成立；2026-09-17 五个 Section 全开淡入之后，这个“下一轮”正好是动画最需要主线程的时候。两项工作各自正确，叠加起来就冲突了。UltraView 截图已经有“等过渡结束或取消再做”的钩子，离散 AA 结算没有。

代码：`ui/pg_canvas/quality.py:871–917`、`:926`；`ui/chart_stack/page_transition.py:476–507`、`:676`；`ui/chart_stack/stack.py:1756–1786`。

#### W3 · P1 · AA 准入与兜底阈值没有在 Windows 上标定，且对“切换”这种离散事件过宽

- `_INK_AA_ON / _INK_AA_OFF = 200k / 300k` 设备像素，依据是 Cocoa dpr 2 的实测。ink spec 状态行写“已实施，待 Windows 复标定”，§7.4 要求进 release 前完成；`docs/analyzer/README.md` 也列为未完成的发布门。到 v8.3.2 为止没有找到 Windows 复标定记录。
- 兜底 `_BACKSTOP_FIRST_AA_MS = 1000`、`_BACKSTOP_STEADY_AA_MS = 250`，所以一张 220 ms 的 AA 帧永远不会熔断，每次切回都重复付。
- 本机 AA 成本约 1.5–3 µs/设备像素 ink，与 spec 的 Cocoa 平滑对照（145k dev → 240 ms）同量级。

这些常量是标定值不是旋钮，改动必须先改 spec §5，再在真机重测。本报告只提出问题，不改数值。

代码：`ui/pg_canvas/renderer.py:144–167`；`ui/pg_canvas/quality.py:82–85`、`:127`。

#### W4 · P2 · 切换是“点击处理函数里同步重建”，点击后没有先给视觉反馈

所有时域 View 共用一张 `canvas_time`。切换 View 等于在点击处理函数里截取离开页、投影通道树、准备数据、增量或重建曲线、恢复 X/Y、结算质量。这段期间事件循环不转，标签高亮、按下态都画不出来。实测小数据同步段 45–57 ms，1000 候选通道约 50–60 ms；09-15 审计在 Cocoa 上测到 2000 候选通道 130–156 ms。

#### W5 · P2 · 通道树投影仍做两次，成本随通道数线性增长

一次时域切换调用两次 `apply_controls_from_state`（`_render_view_onto_canvas` 开头一次，finally 里的 `_project_view_controls` 又一次）。8 通道约 13 ms，1000 通道约 30 ms。

代码：`ui/main_window/_view_mixin.py:576`、`:1075`、`:1146`；`ui/view_bridge.py:184`。

#### W6 · P2 · 回到时域 Section 时重新准备绘图数据

`_render_time_section_entry` → `_plot_time_preserving_xlim` 会重新 `_build_time_plot_data`（本场景约 21 ms），与 09-15 审计的 F4 一致。

#### W7 · P3 · Python GC 偶发停顿

加载文件后常驻约 12–15 万个 Python 对象，一次完整第 2 代回收约 17 ms；切换中观察到单次 60–65 ms 的第 2 代停顿。`gc.freeze()` 后降到约 0 ms。

### 4.2 Section 切换（第二轮）

#### S1 · P1 · FFT vs Time 的切片曲线永远开 AA，每次进入要画约 5 帧

**现象：** FFT vs Time 页面下方的切片曲线（本场景 4097 点）在**每次**重建时都直接打开 AA，没有 ink 闸门、没有实测兜底，也不在 08-08 / 08-15 两份 spec 的范围内。只含这条曲线的重绘，AA 约 108 ms，非 AA 约 8.5 ms。阶次的切片只有 382 点，AA 7.4 ms / 非 AA 5.6 ms，所以阶次不明显。

**为什么一次进入要付约 5 次：** 首次 paint、首次显示后的延迟对齐重绘、淡入结束解冻后的重绘、UltraView 截图、以及下次离开时的离开页截图（S6），每次都是整张视口重绘，切片 AA 都要重新光栅化。cProfile 显示时间在 `PlotCurveItem` 的 `drawPath`，热力图 `drawImage` 本身只有约 9 ms，平滑缩放不是问题。

**诊断对照：** `PROBE_NO_SLICE_AA=1`（配合 `PROBE_TICK_MEMO=1`）后，进入 FFT vs Time 的目标页 paint 合计从约 528 ms 降到约 38 ms，UltraView 截图从 104 ms 降到 6 ms，最长阻塞从约 430 ms 降到约 170 ms。

代码：`ui/pg_canvas/slice_panel.py:108–123`（`_reset_slice_quality_for_rebuild` 固定 `_slice_aa_on = True`）；`ui/pg_canvas/heatmap_canvas.py:402`、`:854–891`。

#### S2 · P1 · 首次需要重画的 FFT 进入：淡入握手被判废，等满 1 s 后硬切

**现象：** 第 1 圈“时域 → FFT”淡入结束在 1113 ms，过渡以 `target-paint-timeout` 取消，用户看到的是约 1 秒冻结的淡入，然后画面硬切。

**根因：** 页面过渡在应用目标状态后调用 `request_presentation_paint_ack`，线图此时记录一个几何快照（各 plot 的场景矩形和 `viewRange`），等下一次自然 paint 时再比对。FFT 页下方的时域预览在首次 paint 里才完成 pyqtgraph 的延迟自动缩放，X 范围从 (-0.399, 20.373) 变成 (-0.708, 20.657)，于是 `_presentation_paint_acked` 判定几何不一致，**取消握手且不再重新申请**。过渡控制器只能等 1000 ms 看门狗超时。

**诊断对照：** `PROBE_ACK_PREPARE=1` 在记录几何前先调用 `scene.prepareForPaint()`，让延迟布局和自动缩放先落定，第 1 圈淡入结束从 1113 ms 降到 475 ms，没有取消。

**为什么只在“首次”出现：** FFT 结果未变时走“保留揭示”，不重画，预览范围已经稳定；只有结果签名变化（首次进入、重新计算、换通道）才会重画。所以用户会感觉“有时候切 FFT 特别卡一下”。热力图和 FRF 画布有同样的握手协议，本轮没有复现同样的失败，但协议上“判废即放弃”的形状相同。

代码：`ui/pg_canvas/line_canvas.py:1014–1070`；`ui/chart_stack/page_transition.py:184–188`、`:586`。

#### S3 · P1 · 进入时域 Section：与 View 切换同一机制

从任何分析 Section 回到时域都付约 450 ms 的两次 AA 帧（W2 + W3 的解冻重绘），外加约 33 ms 的时域入口重绘（W6）。`PROBE_NO_AA_UPGRADE=1` 后，最长阻塞从约 230 ms 降到约 100 ms，淡入结束从约 590 ms 降到约 358 ms。

#### S4 · P2 · 热力图页面首次显示时的反复布局与刻度计算

**现象：** 每次进入阶次或 FFT vs Time，底轴刻度函数 `_apply_target_bottom_ticks` 被调用 28–32 次，合计 124–178 ms（非 profile 的真实计时）。

**根因：** 热力图 `showEvent` 里调用 `_align_slice_to_main` 4 次、`reset_split_layout_alignment` 2 次，再用 `singleShot(0)` 排一次 `_deferred_first_show_align`，加上布局过程中 12–14 次 `ViewBox.resizeEvent`，每一次都重算刻度。`_apply_target_bottom_ticks` 每次枚举约 30 个候选步长（6 个量级 × 5 个因子），每个候选最多生成 500 个值并逐个调用纯 Python 的 `tickStrings`，没有记忆。范围和宽度多数时候并没有变。

**诊断对照：** `PROBE_TICK_MEMO=1`（按 X 范围、轴宽、目标记忆）与 `PROBE_NO_SLICE_AA=1` 一起，进入阶次的同步段从约 134 ms 降到约 92 ms，最长阻塞从约 235 ms 降到约 157 ms。

代码：`ui/pg_canvas/analysis_axes.py:161`；`ui/pg_canvas/heatmap_canvas.py:1831`、`:1911`、`:1957`；`ui/pg_canvas/_split_mixin.py:373`。

#### S5 · P2 · UltraView 截图去重在 Section 切换中同样失效

根因同 W1 补充：digest 不变但 revision 每次 +1。进入 FFT vs Time 时截图约 104 ms（大部分是 S1 的切片 AA），进入阶次约 5–12 ms，进入时域是 W1 的 220–730 ms。

#### S6 · P2 · 离开 FFT vs Time 时，离开页截图再付一次切片 AA

淡入需要先截取离开页。离开 FFT vs Time 时这次截图会让热力图整张重绘，切片 AA 约 100 ms，所以从 FFT vs Time 出发的同步段是 133–228 ms，其他方向约 40 ms。去掉 S1 后降回约 35–92 ms。

#### S7 · P3 · 每次进入分析 Section 都完整回放一次 View 上下文

**现象：** FFT 在结果签名未变时直接“保留揭示”；阶次和 FFT vs Time 没有对应机制。每次进入都走 `_apply_active_analysis_context` → `_on_analysis_view_switched(render=True)`，从缓存把结果重新画一遍（约 73–76 ms，其中重画约 52 ms：阶次 `_render_order_on` 约 39 ms，含 dB 转换、掩码、自动 dB 窗口和切片初值；FFT vs Time `_render_fft_time_on` 约 51 ms，其中 `plot_result` 约 42 ms）。阶次 Inspector 的 nfft 预览每次进入调用 `revolutions_from_rpm` 约 8 次；FFT vs Time 的 dB 参考提示计算约 15 ms。

这部分在去掉 S1–S5 后成为剩余约 90 ms 同步段的主要来源：`_on_analysis_view_switched` 约 48 ms（其中缓存重画约 35 ms）、`ChartStack.set_mode` 约 13 ms、过渡开始约 10 ms。

代码：`ui/main_window/_analysis_mixin.py:893`；`ui/main_window/_order_mixin.py:632`；`ui/main_window/_fft_time_mixin.py:656`；`ui/main_window/window.py:1680`、`:1786`（FFT 签名）。

### 4.3 已测过、不是主因的项

| 项 | 观察 | 判断 |
|---|---|---|
| 淡入动画本身 | 每帧约 2 ms；关掉淡入后 Section 切换的最长阻塞基本不变（§2.2） | 不是主因；淡入只是让主线程阻塞更容易被看见 |
| Windows 分数缩放（125% / 150%） | 物理像素相同时，100% / 125% / 150% 的同步段、淡入帧成本、离开页截图无显著差异 | offscreen 下不是主因；DWM/GDI 刷新与字体引擎仍需 Windows 真机确认 |
| 热力图图像绘制 | `drawImage` 约 9 ms，平滑缩放开关无影响 | 不是主因；贵的是切片曲线 |
| frozen exe（PyInstaller） | 运行期执行同样的字节码和 Qt DLL | 影响启动和首次导入，不影响稳态切换 |
| 动画定时器 | offscreen 帧间隔稳定 16 ms | Windows 上 Qt5 Widgets 不跟 vsync 对齐，偶有重复帧，量级远小于 200 ms 阻塞 |

### 4.4 仍然存在但本轮未重测

- 09-15 审计的 F1（原始 + 滤波虚线叠加时 `drawPath` 十余秒）：两条都显示时仍走虚线路径。
- FRF Section、分屏、UltraView 打开状态、多个分析 View 之间的切换：机制相同（离散 AA、握手、截图），本轮没有单独测。

## 5. 回答：是 Python 的限制，还是软件底层时序的限制？

| 成本来源 | 典型量级 | 属于谁 | 换 C++ 会消失吗 |
|---|---:|---|---|
| AA 整图重绘（W1–W3、S1、S3、S6） | 每次 100–220 ms，一次切换最多 3–5 次 | 软件的渲染策略与调度；AA 光栅化本身在 Qt C++ 里 | 不会：同样的策略在 C++ 里一样慢 |
| 淡入握手判废（S2） | 等满 1000 ms | 软件时序协议 | 不会 |
| 重复布局与刻度计算（S4） | 120–180 ms | 软件逻辑（重复做同一件事） | 会变快数倍，但重复工作仍在 |
| 从缓存完整重画、同步重建（W4、S7） | 45–150 ms | 软件架构 | 会变快，但结构不变 |
| 投影与数据准备的重复工作（W5、W6） | 20–60 ms，随通道数增长 | 软件逻辑 | 会变快数倍 |
| Python 编排开销 | 每次约 20–50 ms | Python（解释执行、sip 调用） | 会明显变快 |
| GC 停顿（W7） | 偶发 15–65 ms | Python | 会消失 |
| 单 GUI 线程、CPU 光栅、无 vsync | 决定上限 | Qt5 Widgets 框架 | 用 C++ Qt5 Widgets 也一样 |

所以，**能感知到的“卡一下”（200 ms 以上的冻结和 1 秒的淡入停顿）主要来自软件自己的渲染调度和时序协议，可以在现有 Python + PyQt5 + pyqtgraph 栈上优化，不需要换语言或框架。** Python 让剩下的几十毫秒更难压到 16 ms 以内；如果目标是每帧都 60 fps，那才会碰到 Python 和 Qt5 Widgets 的上限。

## 6. 优化方向

完整设计见 spec，分步实施与验收见 plan。按收益/风险排序的摘要如下，D-x 编号与 spec 一致。

| 顺序 | 设计项 | 解决 | 预期收益（本报告场景，offscreen 诊断投影） |
|---|---|---|---|
| 1 | D-D 淡入握手几何稳定：采样前先完成场景布局；判废后有界重申请；看门狗超时留痕 | S2 | 首次进入 FFT 不再冻 1 s |
| 2 | D-C 热力图切片曲线纳入质量规则：重建时 AA 关，首帧后按 ink 判、有实测兜底 | S1、S6 | 进入 FFT vs Time 少约 250 ms 阻塞；离开 FFT vs Time 的同步段降回约 40–90 ms |
| 3 | D-E UltraView 自动预览按需截图：revision 只在展示事实真的变化时递增；UltraView 不可见且无消费者时只标记过期；自动预览不强制 AA | W1、S5 | 每次切换少 5–730 ms |
| 4 | D-A 离散 AA 结算感知过渡：淡入进行中不升级，结束或取消后升级一次；解冻重绘不走 AA | W2、S3 | 进入时域最长阻塞约 230 → 100 ms，淡入不再冻住 |
| 5 | D-F 刻度记忆与首次显示对齐合并 | S4 | 进入阶次 / FFT vs Time 少约 40–80 ms 同步段 |
| 6 | D-G 热力图 Section 的保留揭示（独立的结果完整性签名） | S7 | 进入阶次 / FFT vs Time 再少约 35–50 ms |
| 7 | D-B 离散切换的 AA 帧预算 + Windows 复标定 | W3 | 从根上限制允许多贵的 AA 帧 |
| 8 | D-H 时域入口复用数据、点击先反馈、差异投影 | W4–W6 | 20–60 ms，随通道数增长 |
| 9 | D-I 加载完成后 `gc.freeze()` | W7 | 去掉偶发 15–65 ms 抖动 |

第一轮报告的第 9 项“最近使用的 View 各保留一张画布，切换变成翻页”**撤回**：它与 2026-09-15 计划“不为每个 View 常驻画布或截图”的约束冲突，而且 D-A 到 D-G 已能覆盖本报告里 200 ms 以上的主要冻结。“AA 光栅放到后台线程”列为 spec 的非目标，只在 D-A/D-B/D-C 完成后 Windows 仍不达标时再立项。

诊断投影（探针同时打开 `PROBE_ACK_PREPARE`、`PROBE_NO_SLICE_AA`、`PROBE_TICK_MEMO`、`PROBE_NO_AA_UPGRADE`、`PROBE_NO_UV_AUTOCAPTURE`）：

| 进入的 Section | 最长阻塞 ms（基线 → 投影） | 淡入结束 ms | 同步段 ms |
|---|---:|---:|---:|
| FFT vs Time | 430 → 160–173 | 680 → 410–424 | 145 → 约 100 |
| 阶次 | 235 → 152–158 | 485 → 约 405 | 134 → 约 92 |
| 时域 | 230 → 100 | 590 → 358 | 38 → 35 |
| FFT（首次需重画） | 162 → 165 | 1113 → 475 | 45 → 41 |
| 从 FFT vs Time 离开 | 172–330 → 76–152 | — | 133–228 → 35–89 |

这些是“把问题关掉”的上界估计，不是产品修复后的实测。产品实现要保留 AA 质量（只是换时机）和 UltraView 预览（只是按需），实际收益以 plan 的验收测量为准。

## 7. 建议的 Windows 真机验证

1. 记录机器信息：CPU 型号、Windows 缩放比例、分辨率、电源模式，以及源码运行还是 Full/Lite exe。
2. 在 Windows 源码环境前台运行 `scripts/probe_switch_smoothness.py`（去掉 `QT_QPA_PLATFORM`），View 场景和 Section 场景都跑默认值与 §3 的诊断开关，与本报告的 offscreen 数字对照。
3. 用用户真实的文件复现：设置 `TRACELAB_PERF=1` 启动，时域探针会把每次绘图和 paint 耗时写到 `~/tracelab_perf.log`（见 `ui/pg_canvas/_perf_probe.py`）。
4. 第一轮工程目标（尚未验收的目标值，在 plan Task 0 按 Windows 基线校准）：点击到可见反馈 ≤ 50 ms；切换期间主线程单次最长阻塞 ≤ 100 ms；淡入期间最大帧间隔 ≤ 33 ms；不出现 `target-paint-timeout`。

## 8. 本轮范围与限制

- 没有修改产品代码，没有提交任何常量改动。`scripts/probe_switch_smoothness.py` 只用于诊断，不被产品或测试导入；诊断开关只在探针进程里 monkeypatch。
- 没有在 Windows 前台、Windows frozen exe、macOS Cocoa 上运行；FRF、分屏、UltraView 打开状态、滤波叠加没有测量。
- 数字来自合成数据，View 场景每组 5–8 次，Section 场景每个方向 3 次，属于定位证据，不是 P95/P99 或发布验收结论。
- 纯文档与诊断脚本改动，没有运行时行为变化，因此没有跑 pytest。脚本已在当前 HEAD 上完整运行（View 场景默认与两个诊断开关；Section 场景基线、淡入关闭与 7 组诊断组合，均正常退出）。
- 参考的既有记录：`reviews/2026-09-15-interaction-smoothness-audit.md`（F1–F8）、`verify/2026-09-12-section-switch-performance.md`、`verify/2026-09-16-page-transition-safety-performance-followup.md`、`verify/2026-09-16-all-sections-page-transition-expansion.md`、`specs/2026-08-08-timedomain-aa-ink-budget-spec.md`、`specs/2026-08-15-view-switch-quality-settlement-spec.md`。这些记录中 Cocoa 与 Windows 的性能准入仍为 UNKNOWN，本报告不改变这一状态。
