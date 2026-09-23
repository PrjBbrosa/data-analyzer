# Windows 下页面 / View 切换不顺滑：原因分析与优化方向

日期：2026-09-23。版本：v8.3.2。分析 HEAD：`ef63e1e6`。

本轮只做分析、诊断测量和报告，**没有修改产品代码**。新增一个诊断脚本
`scripts/probe_switch_smoothness.py`，用于在 Windows 真机上复跑同一组测量。

## 结论

**主因不是 Python 的硬限制，而是软件自身的渲染策略和时序：一次切换会在 GUI 主线程上串行做好几次“整张图重绘”，其中最贵的是抗锯齿（AA）重绘。** 在同一画面上，非 AA 重绘一帧约 5–9 ms，AA 重绘一帧约 220 ms，相差 20–40 倍。

一次普通的时域 View 切换（目标 View 的 ink 落在 AA 准入带内）会触发三次这种 AA 整图重绘：

1. **View 恢复后的 AA 画质升级。** 离散结算用 0 ms 定时器决定升级，正好落在淡入动画的第 3 帧，动画冻住约 225 ms。
2. **淡入结束、画布解冻后，同一画面再做一次 AA 重绘**，又是约 220 ms。
3. **UltraView 自动预览截图。** 每次切换后都在主线程强制开 AA 重绘整张图，220–730 ms；用户没打开 UltraView 时也会执行，屏幕上因 ink 超标未开 AA 的 View 也会被强制 AA。

这些 AA 准入阈值是在 macOS（Cocoa，dpr 2）上标定的。ink 预算 spec 明写“Windows 真机复标定后方可发布”，README 也把它列为未完成的发布门；兜底阈值（首帧 1000 ms、稳态 250 ms）本来就放行 200 ms 以上的帧。Windows 办公本单核性能通常低于 Apple Silicon，同一帧只会更贵。

诊断对照（只在探针里关掉，不是产品设置）：关掉第 1、3 项后，同一场景的淡入从 535 ms 回到按时的 313 ms，主线程最长阻塞从约 225 ms 降到约 34 ms，从 FFT 回到时域的最长阻塞从约 230 ms 降到约 91 ms。第 2 项在关掉第 1 项后自然消失。

Python 的作用是“放大器”，不是主因。它带来的是：所有编排和绘制都串行跑在一个 GUI 线程上；每次切换约 20–50 ms 的 Python 层编排开销；偶发 15–65 ms 的 GC 停顿。最贵的 AA 光栅化发生在 Qt 的 C++ 代码里，换成 C++ 写同样的架构也一样慢。Qt5 Widgets 纯 CPU 光栅、Windows 上不跟显示器 vsync 对齐，这些是框架层面的上限，但不是当前卡顿的主要来源。

## 1. 一次“卡”的切换在时间线上长什么样

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

## 2. 测量方法与证据等级

- 环境：Linux offscreen，Qt 5.15.14 / PyQt5 5.15.11 / pyqtgraph 0.14.0 / Python 3.12.3，4 vCPU Intel Xeon。生产 QSS、Fusion、中文字体；QSettings 隔离。
- 数据：合成 CSV，8 通道 × 200k 点 @ 10 kHz；View A、View B 各勾 3 条不同通道。另测 1000 通道 × 2000 点（候选列表规模）和 8 通道 × 1M 点。
- 窗口按物理像素恒定约 1920×1030 设置：100% 缩放为 1920×1030 逻辑像素，125% 为 1536×824，150% 为 1280×686。
- 操作走真实入口：`view_tabbar.switch_requested`、`toolbar.mode_changed`。每组 5–8 次，丢掉第一次预热。
- **证据等级：** offscreen 使用的 `QRasterPaintEngine` 与 Windows Widgets 相同，所以 paint 耗时可作为 CPU 光栅成本的代理。但它**不是** Windows 前台证据：没有 GDI/DWM 刷新，字体引擎不同，也不是 frozen exe。样本数只够定位结构性问题，不够给 P95 或发布验收结论。
- 主线程最长阻塞用 1 ms 心跳定时器测量。落在测量窗口之后的阻塞（例如较晚的 UltraView 截图）可能漏计，所以时间线以逐帧 paint 记录为准。

复跑方法（Windows 源码环境去掉 `QT_QPA_PLATFORM`）：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen QT_SCALE_FACTOR=1.25 PYTHONPATH=. \
  .venv/bin/python scripts/probe_switch_smoothness.py \
  --win-w 1536 --win-h 824 --motion light --out result.json
# 诊断对照（仅探针内生效）：
PROBE_NO_AA_UPGRADE=1 PROBE_NO_UV_AUTOCAPTURE=1 ...同上
```

## 3. 发现（按对体感的影响排序）

### W1 · P1 · UltraView 自动预览截图每次切换都强制做一次 AA 整图重绘

**路径：** `_render_view_onto_canvas` 末尾调用 `coord.request_capture(new_ref, canvas, "time-render")`，由 0 ms 定时器进入 `_publish_grab` → `_grab_image` → `ChartStack.grab_presentation_pixmap` → `_grab_pixmap_hidpi` → `renderer.grab_pixmap`。只要 `_export_aa_affordable()` 为真，就在 `_quality._curves_antialiased()` 里强制 AA 做一次 `QWidget.grab()`。

**实测：** 每次切换约 220 ms；View B 在 100% 缩放下 ink 242k，处于滞回带里，屏幕上没开 AA，但截图判据只比 `_INK_AA_OFF`，所以仍被强制 AA，单次 **729 ms**。

**为什么说是多余成本：**

- `ultraview_coordinator._inactive()` 只看是否已关闭，所以用户没打开 UltraView、没有任何 Board 引用这个 View 时也在截。
- 截出来的是缩略图，AA 在缩略尺寸上几乎看不出差别。
- 切换离开时的 `offer_capture_bound_canvas` 是按合同同步执行的（UV-A18）。开淡入时它复用离开页截图，不开淡入时会再同步 grab 一次。

代码：`ui/main_window/_view_mixin.py:1149–1154`；`ui/main_window/ultraview_capture_coordinator.py:520`、`:1603`、`:1697`；`ui/pg_canvas/renderer.py:877–928`；`ui/chart_stack/stack.py:2060`；`ui/main_window/ultraview_coordinator.py:656`。

### W2 · P1 · AA 升级落在淡入动画里，而且同一画面画了两次

**路径：** `settle_view_restore` → `QualityManager.settle_after_discrete_render`。memo 没有“便宜”的记录时，启动 0 ms 的 `discrete_timer`，下一轮事件循环就调用 `try_enable_idle_quality` 把曲线 AA 打开并 update。页面过渡在目标首帧自然 paint 后开始淡入，只在下一轮才 `_freeze_input_target_updates`，所以 AA 首帧（含设备坐标缓存重建）正好插在淡入的第 2–3 帧之间。淡入结束解冻时，画布又整图重绘一次，而且还是约 220 ms 的 AA 代价，说明上一帧的缓存没能复用（根因待 owner 排查；可能与冻结期间的 update 合并、缓存失效或几何有关）。

**实测：** 淡入帧间隔 `[11, 23, 225, 20, 16, 16, …]` ms；淡入结束时间 535 ms，而 240 ms 的淡入本应在约 320 ms 结束。关掉 AA 升级后，帧间隔最大约 23 ms，淡入 313 ms 结束。

**这与现有设计合同的关系：** 2026-08-15 View 切换质量结算 spec 把“离散切换不再等 150 ms、下一轮就升级 AA”当作改进，目的是减少“锯齿→平滑”的可见跳变。这在没有淡入时成立；2026-09-17 五个 Section 全开淡入之后，这个“下一轮”正好是动画最需要主线程的时候。两项工作各自正确，叠加起来就出现了冲突。

代码：`ui/pg_canvas/quality.py:871–917`、`:926`；`ui/chart_stack/page_transition.py:476–507`、`:676`；`ui/chart_stack/stack.py:1756–1786`。

### W3 · P1 · AA 准入与兜底阈值没有在 Windows 上标定，且对“切换”这种离散事件过宽

- `_INK_AA_ON / _INK_AA_OFF = 200k / 300k` 设备像素，依据是 Cocoa dpr 2 的实测（spec §3.2 / §5）。spec 状态行写着“已实施，待 Windows 复标定”，§7.4 要求“进 release 前必须完成”；`docs/analyzer/README.md` 也写 “Windows ink threshold recalibration remains a separate release gate”。到 v8.3.2 为止没有找到 Windows 复标定记录。
- 即便在 Mac 上，“平滑对照组”的 AA 帧也是 240 ms（首帧 474 ms），被 spec 定为“今日可接受、必须放行”。兜底 `_BACKSTOP_FIRST_AA_MS = 1000`、`_BACKSTOP_STEADY_AA_MS = 250`，所以一张 220 ms 的 AA 帧永远不会熔断，每次切回都重复付。实测第 0、2、4 次切回 View A 都付了约 220 ms。
- 本机 AA 成本约 1.5–3 µs/设备像素 ink（146.7k → 约 220 ms；242k → 约 730 ms），与 spec 的 Cocoa 平滑对照（145k dev → 240 ms）同量级。Windows 目标机器如果单核更慢，按比例更贵。

这些常量是标定值不是旋钮。按 `CLAUDE.md` / `AGENTS.md`，改动必须先改 spec §5，再在真机上用 `scripts/probe_aa_ink_budget.py` / `scripts/probe_view_switch_quality.py` 重测。本报告只提出问题，不改数值。

代码：`ui/pg_canvas/renderer.py:144–167`；`ui/pg_canvas/quality.py:82–85`、`:127`；`docs/analyzer/specs/2026-08-08-timedomain-aa-ink-budget-spec.md` §5、§7.4。

### W4 · P2 · 切换是“点击处理函数里同步重建”，点击后没有先给视觉反馈

所有时域 View 共用一张 `canvas_time`。切换 View 等于在点击处理函数里：截取离开页 → 把目标 View 的附件、颜色、勾选、隐藏投影到通道树 → 准备数据 → 增量或重建曲线 → 恢复 X/Y → 结算质量。这段期间事件循环不转，标签高亮、按下态都画不出来。

中途唯一的事件泵是 `_begin_compute_progress` 里的 `processEvents(ExcludeUserInputEvents)`（约 7–10 ms）。它的目的是让进度条上屏，并不保证先画标签。实测小数据同步段 45–57 ms，1000 候选通道时约 50–60 ms（目标有数据时）；09-15 审计在 Cocoa 上测到 2000 候选通道时 130–156 ms。

淡入只能遮住“新图没准备好”的那段，不能让点击本身显得跟手。`2026-09-15` 计划 §1 已经写明：主线程被同步工作占住时，动画同样无法前进。

### W5 · P2 · 通道树投影仍做两次，成本随通道数线性增长

09-15 审计的 F2 已部分落地：`view_bridge.apply_controls_from_state` 外包了 `channel_projection_batch`。但一次时域切换仍调用两次 `apply_controls_from_state`：`_render_view_onto_canvas` 开头一次，finally 里的 `_project_view_controls` 又一次。

| 候选通道数 | `apply_controls_from_state` ×2 | `_project_view_controls` |
|---:|---:|---:|
| 8 | 约 13 ms | 约 6.6 ms |
| 1000 | 约 30 ms | 约 14.4 ms |

真实 MF4 常有几百到上千个通道，这部分在 Windows 较慢的 CPU 上会接近 50–100 ms。

代码：`ui/main_window/_view_mixin.py:576`、`:1075`、`:1146`；`ui/view_bridge.py:184`。

### W6 · P2 · 回到时域 Section 时重新准备绘图数据

从 FFT 回到时域，`_render_time_section_entry` → `_plot_time_preserving_xlim` 会重新 `_build_time_plot_data`（本场景约 21 ms），与 09-15 审计的 F4 一致：数据准备在增量判断之前执行。去掉 W1/W2 后，回到时域的最长阻塞约 91 ms，其中这部分是最大的单项之一。

### W7 · P3 · Python GC 偶发停顿

启动并加载文件后，常驻约 12–15 万个 Python 对象，一次完整第 2 代回收约 17 ms。切换过程中观察到单次第 2 代停顿 60–65 ms、第 1 代约 30 ms（包含 sip/Qt 包装对象析构）。`gc.freeze()` 之后，第 2 代回收降到约 0 ms。影响不大，但它是纯 Python 带来的、随机出现的抖动。

### 已测过、不是主因的项

| 项 | 观察 | 判断 |
|---|---|---|
| Windows 分数缩放（125% / 150%） | 物理像素相同时，100% / 125% / 150% 的同步段、淡入帧成本（约 2–2.8 ms/帧）、离开页截图（5–12 ms）无显著差异 | offscreen 下不是主因；DWM/GDI 刷新与字体引擎仍需 Windows 真机确认 |
| 淡入覆盖层本身 | 每帧约 2 ms；目标画布冻结后不会每帧重放 GraphicsView | 不是主因；问题在于 W2 插进来的 AA 帧 |
| frozen exe（PyInstaller） | 运行期执行的是同样的字节码和 Qt DLL | 影响启动和首次导入（另见 `2026-09-22-windows-startup-and-idle-preload-plan.md`），不影响稳态切换 |
| 动画定时器 | offscreen 帧间隔稳定 16 ms | Windows 上 Qt5 Widgets 不跟 vsync 对齐，偶有重复帧，量级远小于 200 ms 阻塞 |

### 仍然存在但本轮未重测

- 09-15 审计的 F1（原始 + 滤波虚线叠加时 `drawPath` 十余秒）：目前只对“只显示滤波”的情况改成实线（`canvas.py:_sync_companion_dash_styles`），两条都显示时仍走虚线路径。
- FFT / FFT vs Time / Order / FRF 已计算结果的 View 切换：同样有离散 AA 结算（`_SPECTRUM_INK_*`、`_FRF_INK_*`）和 UltraView 截图，机制相同，本轮没有测。

## 4. 回答：是 Python 的限制，还是软件底层时序的限制？

| 成本来源 | 典型量级 | 属于谁 | 换 C++ 会消失吗 |
|---|---:|---|---|
| AA 整图重绘（W1/W2/W3） | 每次约 220 ms，一次切换最多 3 次 | 软件的渲染策略与调度；AA 光栅化本身在 Qt C++ 里 | 不会：同样的策略在 C++ 里一样慢 |
| 同步重建、无先行反馈（W4） | 45–150 ms | 软件架构：共享画布，切换即重建 | 不会消失，但会变快 |
| 投影与数据准备的重复工作（W5/W6） | 20–60 ms，随通道数增长 | 软件逻辑 | 会变快数倍，但重复工作仍在 |
| Python 编排开销 | 每次约 20–50 ms | Python（解释执行、sip 调用） | 会明显变快 |
| GC 停顿（W7） | 偶发 15–65 ms | Python | 会消失 |
| 单 GUI 线程、CPU 光栅、无 vsync | 决定上限 | Qt5 Widgets 框架 | 用 C++ Qt5 Widgets 也一样 |

所以，**能感知到的“卡一下”（200 ms 以上的冻结）主要来自软件自己的渲染调度，可以在现有 Python + PyQt5 + pyqtgraph 栈上优化，不需要换语言或框架。** Python 让“剩下的”几十毫秒更难压到 16 ms 以内。如果目标是每帧都 60 fps，那才会碰到 Python 和 Qt5 Widgets 的上限。

## 5. 优化方向（建议，本轮未实施）

下面按“收益/风险比”排序，每项写明 owner 和必须保住的合同。都需要先在 Windows 真机拿到前后对照，不能只凭 offscreen 结论验收。

| 顺序 | 方向 | Owner | 预期收益（本报告场景） | 风险 / 必守合同 |
|---|---|---|---|---|
| 1 | UltraView 自动预览不强制 AA；只在 UltraView 页可见或有 Board 引用该 View 时才截图，否则记为“脏”，打开 UltraView 时再补截 | `ultraview_capture_coordinator`；`renderer.grab_pixmap` 增加“自动预览”调用口径 | 每次切换少 220–730 ms 主线程阻塞 | 离开时同步截图合同（UV-A18）、digest/generation 校验、显式复制/导出仍保留 AA；项目保存需要的预览要在保存路径补齐 |
| 2 | 淡入进行中不做离散 AA 升级：等 `transition_finished` 后再升级一次；并排查解冻后第二次 AA 重绘为何没复用缓存 | `pg_canvas/quality.py` 离散结算 + `chart_stack` 过渡 | 淡入不再冻住（最大帧间隔约 225 ms → 约 23 ms），并少一次约 220 ms 的重绘 | `TestDiscreteSettle`：150 ms 交互定时器 `interval()` 不变、离散路径独立 0 ms 定时器；`TestViewRestoreSettlement` 一次结算；淡入取消/重定向路径也要补一次升级 |
| 3 | Windows 复标定 AA 准入带；为离散切换单独设较低的 AA 首帧预算（超过即按签名拉黑，不再每次付），或按本机实测的 ns/px 自适应 | spec §5 → `renderer.py` / `quality.py` 常量 | 从根上限制“允许多贵的 AA 帧” | 标定值不是旋钮：先改 spec，再用 `probe_aa_ink_budget.py` 在 Windows 真机测；`TestInkBudget` 只栅栏量级 |
| 4 | 点击先给反馈：切换先让标签/覆盖层画出一帧，再在下一轮做重建 | `_view_mixin._switch_view` / `TimeRenderGate` | 点击到可见反馈从 45–150 ms 降到约 1 帧 | 连点 A→B→C 最后一次生效、重入保护、View 删除/重排期间的身份校验 |
| 5 | 去掉重复投影，改为差异投影（W5 / 09-15 F2 剩余部分） | `view_bridge`、`channel_tree` | 1000 通道时约 15–30 ms | 副栏恢复、隐藏曲线、复合通道身份 |
| 6 | 回到时域时复用已准备的数据（W6 / 09-15 F4） | `window._build_time_plot_data` 数据准备 owner | 约 20 ms，随数据量增长 | 先截取再滤波的语义；不能用显示名作 key |
| 7 | 启动完成、文件加载完成后调用 `gc.freeze()`，适度调高 GC 阈值 | `app.py` / 加载完成点 | 去掉偶发 15–65 ms 抖动 | 低风险；需要观察长会话内存 |
| 8 | 结构性：AA 光栅在后台线程画到 `QImage`，GUI 线程只贴图 | `pg_canvas/dense_raster` | AA 质量不再阻塞交互 | Qt 对象只能在 GUI 线程创建和绘制；`QImage` + `QPainter` 可在工作线程使用，但要重新设计生命周期、取消和 generation |
| 9 | 结构性：最近使用的 2–3 个时域 View 各保留一张画布，切换变成翻页 | `chart_stack` / `_view_mixin` | 回切近乎零成本 | 内存；与 09-15 计划“不为每个 View 常驻一套画布”的约束冲突，需要产品决策 |

不建议现在做的：改用 OpenGL 视口（ink spec §6 已因质量和兼容性放弃）、迁移 Qt6、整体异步化。它们的改动面远大于 1–3 项，而 1–3 项已能覆盖本报告里 200 ms 以上的主要冻结。

## 6. 建议的 Windows 真机验证

1. 记录机器信息：CPU 型号、Windows 缩放比例、分辨率、电源模式，以及源码运行还是 Full/Lite exe。
2. 在 Windows 源码环境、前台运行 `scripts/probe_switch_smoothness.py`（去掉 `QT_QPA_PLATFORM`），分别跑默认和两个诊断开关。结果与本报告的 offscreen 数字对照，可以直接判断 W1/W2 在 Windows 上的实际量级。
3. 用用户真实的文件复现：设置 `TRACELAB_PERF=1` 启动，现有的时域探针会把每次绘图和 paint 耗时写到 `~/tracelab_perf.log`（见 `ui/pg_canvas/_perf_probe.py`）。
4. 建议的第一轮工程目标（尚未验收的目标值）：点击到可见反馈 ≤ 50 ms；切换期间主线程单次最长阻塞 ≤ 100 ms；淡入期间最大帧间隔 ≤ 33 ms。

## 7. 本轮范围与限制

- 没有修改产品代码，没有提交任何常量改动。新增的 `scripts/probe_switch_smoothness.py` 只用于诊断，不被产品或测试导入。
- 没有在 Windows 前台、Windows frozen exe、macOS Cocoa 上运行；分屏、UltraView 打开状态、已计算的分析 View、滤波叠加没有测量。
- 数字来自合成数据、每组 5–8 次，属于定位证据，不是 P95/P99 或发布验收结论。
- 纯文档与诊断脚本改动，没有运行时行为变化，因此没有跑 pytest。脚本已在当前 HEAD 上完整运行（默认与两个诊断开关各一次，正常退出）。
- 参考的既有记录：`2026-09-15-interaction-smoothness-audit.md`（F1–F8）、`verify/2026-09-12-section-switch-performance.md`、`verify/2026-09-16-page-transition-safety-performance-followup.md`、`verify/2026-09-16-all-sections-page-transition-expansion.md`、`specs/2026-08-08-timedomain-aa-ink-budget-spec.md`、`specs/2026-08-15-view-switch-quality-settlement-spec.md`。这些记录中 Cocoa 与 Windows 的性能准入仍为 UNKNOWN，本报告不改变这一状态。
