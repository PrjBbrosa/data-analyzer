# 色图再次进入的双闪与 Tooltip 等待时间优化计划

- 日期：2026-09-23
- 状态：共享切换白闪已修复，源码聚焦回归与 Cocoa 真实项目合成帧对比通过；Windows frozen 与屏幕连续录像未验收。最新结论见 §6；§1–5 保留初稿与上一轮执行记录。
- 基线：`e4be0e1b`，干净工作树，TraceLab 8.3.2。
- 接续：`2026-09-23-switch-smoothness-plan.md` 的页面过渡、离散画质保持和热力图保留揭示；本计划聚焦它们组合后的再次进入体验，不重开未完成的 Windows AA 阈值标定。
- 用户现象：截图中的 FFT-vs-Time 单 Pane 色图首次切入基本正常，再次切入时可见两次频闪；Inspector 的时间范围等输入控件提示出现太慢，不同位置等待时间似乎不一致。

## 1. 分析结论与证据边界

### 1.1 色图双闪：已定位到两次后续绘制，前台像素原因待确认

`MainWindow._on_mode_changed` 先建立跨 Section 过渡、再显示目标页并恢复 View；同 Section 的 View 切换也通过 `_on_analysis_switch` 建立过渡。FFT-vs-Time / Order 缓存命中时，`_render_analysis_view_from_cache` 可保留当前图像，只恢复视口；签名不命中才重新 `plot_result`。因此“第二次”与“第一次”确实可能走不同的绘图分支。涉及 `window.py:2047-2125`、`_analysis_mixin.py:250-266, 2806-2818`。

过渡的目标自然 paint 确认后，覆盖层淡出。`PageTransitionController._finish` 当前依次隐藏覆盖层、解冻目标控件更新、发 `transition_finished`；后者释放目标画布的离散 AA hold。解冻可先产生一帧非 AA，随后的 0 ms 离散画质结算再产生 AA 帧。涉及 `page_transition.py:490-509, 572-584, 690-715`，`stack.py:1570-1616`。`PgHeatmapCanvas.showEvent` 每次显示都立即对齐，并安排 0 ms 的延后对齐；这还可能带来额外的目标页绘制，需在帧日志中区分，不能仅凭源码把它定为双闪主因（`heatmap_canvas.py:2004-2042`）。

本轮只读诊断运行：

```text
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python scripts/probe_switch_smoothness.py \
  --scenario section --points 50000 --reps 2 --win-w 1536 --win-h 824 \
  --motion light --out .state/2026-09-23-heatmap-repeat-probe.json
```

探针 24 次切换均已完成；三个分析 Section 均有结果。在第二轮 `fft -> fft_time`，目标画布先于约 156/162 ms 绘制过渡所需的非 AA 帧，淡入结束后又于约 418 ms 绘制非 AA 帧、424 ms 绘制 AA 帧；`time -> fft_time` 为约 300/307 ms。Order 回访也出现结束后的非 AA、AA 相邻两帧。对应原始 JSON 的 `raw[].paints`；以上是 **macOS offscreen 的事件与光栅代理证据**，不是前台“闪两次”的像素证明。探针只覆盖跨 Section，尚未覆盖截图所示 View 2 的同 Section A→B→A 路径。

**工作假设：**过渡结束的“解冻重绘”与“AA 恢复重绘”分别把同一目标暴露给屏幕，是双闪的主要来源；热力图显示时的二次对齐可能叠加一帧。先用前台逐帧证据判定每帧究竟是空白、旧图、范围移动，还是仅切片曲线 AA 变化，再决定改动位置。不得把“两次 paint”直接等同于“两次肉眼可见频闪”。

### 1.2 Tooltip：显示样式已统一，等待时间未统一

主应用启动时安装 `glass_tooltip`，它只拦截 Qt 已送来的 `QEvent.ToolTip` 并立即显示玻璃提示；没有设置悬停唤醒延迟（`app.py:333-346`，`glass_tooltip.py:188-229`）。当前主应用用 Fusion；本机离屏查询 `SH_ToolTip_WakeUpDelay = 700 ms`、`SH_ToolTip_FallAsleepDelay = 2000 ms`。后一项意味着连续悬停与首次悬停的体感可能不同，具体事件时序仍需在前台测量。

截图里的“全时段”来自隐藏 `combo_range` 的 item Tooltip，经 `SegmentedChoice.bind` 复制到可见按钮；起止输入框自身也设有 Tooltip（`persistent_top.py:247-283`，`segmented_choice.py:110-119`），它们都等 Qt 的唤醒事件。另有独立的预设悬浮卡 **300 ms**（`presets.py:541, 1094`）；侧边收起条 **150 ms** 是“探出面板”的动作延时，不是 Tooltip（`side_panels.py:82-104`）；View 关闭槽使用原生 `QToolTip.showText`（`view_tabbar.py:438-453`）。所以用户感到不同位置不同步有代码依据，不能通过只改玻璃提示的绘制速度解决。

## 2. 目标与不变量

1. 对已计算、单 Pane 的 FFT-vs-Time / Order：首次进入和 A→B→A 回访都只呈现一个稳定目标画面；淡入完成后不再连续暴露两种目标画质或短暂空白。若允许 AA，最终画质仍为 AA。
2. 横向覆盖 Time、FFT、FFT-vs-Time、FRF、Order 的跨 Section 与同 Section View 切换；分屏、未计算、项目恢复、取消和快速重定向保持现有直达/失效规则。只修实测命中的共享路径，不为五个 Section 各复制一套逻辑。
3. 主应用的普通 QWidget Tooltip 首次悬停目标约 **350 ms**，先在 macOS 与 Windows 测量后定值；同一区域输入框、分段按钮和图表工具按钮遵循同一策略。预设悬浮卡保持独立的 300 ms，侧边 150 ms peek 不纳入 Tooltip 政策。提示持续时间、文案和位置不因缩短等待而改变。
4. 输入、拖动、菜单、失焦和 Tooltip 跨控件移动时不出现误弹、遮挡或重复 show/hide；不能以隐藏提示或永久关闭 AA 来消除闪烁。

## 3. 实施任务与验证门

### T0 · 复现与逐帧归因（先完成）

- 用截图对应的 `1.tlproj` / 数据在前台重复“首次进入、离开、再次进入”；分别走 Section A→B→A、色图 View 1→2→1→2、快速重定向。记录 OS、缩放、窗口尺寸、是否单 Pane、是否缓存命中。若该项目源数据在本机不可用，用现有合成探针明确标注替代证据。
- 扩展**本地诊断探针**，按过渡 generation 记录 `showEvent`、即时/延后对齐、签名命中、目标自然 paint、覆盖层开始/结束、`updatesEnabled`、AA hold 释放及每次画布 paint；截取局部画面或逐帧哈希，对比相邻可见帧。既有 `.state` JSON 不入库。
- 对 `--motion light/off`、保留揭示命中/强制失效作诊断 A/B；只在探针进程控制，不新增产品开关。先判定双闪发生于淡入中、淡入尾或淡入后，避免把重画、几何对齐和画质升级混成一个原因。
- 同时记录 Inspector 分段按钮、起止编辑框、图表工具按钮、View 槽和预设卡的 Enter→ToolTip→popup show 时间；分别测首次悬停、2 秒内换控件、超过 2 秒再悬停，macOS/Windows 各取多次中位数。核查 `QAbstractSpinBox` 内部 editor 的事件归属。
- **门槛：**找到与肉眼两闪对应的两次可见像素变化，或将工作假设标为未证实并据实调整后续方案。Windows 未测标 `UNVERIFIED`，不能用 offscreen 代替。

### T1 · 合并过渡结束时的目标暴露与画质结算

- Owner：`ui/chart_stack/page_transition.py`、`stack.py` 与现有画质协作者；仅在 T0 证明的共享边界改动。先写一个能在真实 `PgHeatmapCanvas` 上失败的帧序/状态用例，保护淡入结束后没有“非 AA 可见帧 → AA 可见帧”的相邻暴露。
- 候选最小做法：在目标仍被冻结时完成允许的画质状态结算，再解冻并只提交最终画面；若同步结算造成动画尾部阻塞，则保留现有异步 AA，但延后非 AA 暴露，比较两种方案的前台帧时间后选取。保持 150 ms 交互静默窗、0 ms 离散定时器与 ink/兜底阈值合同；不直接交换两个 signal 调用顺序而忽略其异步定时器。
- 如 T0 证明多余帧来自 `showEvent` 的延后对齐，单独限定其仅在几何未稳定时执行一次；先保护首次显示、DPR/字体变化及分屏对齐，不能删除首次对齐修复。
- 聚焦：`test_section_page_transition.py`、`test_page_transition_integration.py`、`test_discrete_quality_hold.py`、`test_pg_heatmap_canvas.py`、`test_slice_panel.py`。边界：`test_pg_canvas_backref_invariants.py`、`test_main_window_state_ownership.py`、`test_no_lambda_signal_connections.py`、`test_import_boundaries.py`。复测 Time/FFT/FRF 的恢复、取消与重定向；无改变的路径不做全面重写。

### T2 · 统一普通 Tooltip 的唤醒策略

- Owner：`ui_kit/glass_tooltip.py` 与主应用初始化。优先通过单一 Qt style policy 覆盖 `SH_ToolTip_WakeUpDelay`，让所有普通 `QEvent.ToolTip`（包括 Inspector 和图表工具按钮）得到同一个候选 350 ms；保持 `SH_ToolTip_FallAsleepDelay` 与显示时长原值。先验证 Fusion/Qt 在 macOS 与 Windows 真正采用该 hint，且 View 的原生 `QToolTip.showText` 没有被双重显示。
- 如果 style hint 在某平台无效，才考虑玻璃提示自己的单一悬停调度器；它必须处理子控件、Leave/Hide、窗口失焦、销毁、连续悬停和已有 120 ms 收起定时器。禁止为每个输入框散落 `QTimer`。
- 聚焦：`tests/ui/test_glass_tooltip.py`、`tests/ui/test_analysis_time_range_intent.py`、`tests/ui/test_hint_nudges.py`，以及针对真实 `SegmentedChoice`、`CompactDoubleSpinBox`、图表按钮的事件/延迟探针。检查预设卡 300 ms、侧边 peek 150 ms 没有变义；检查 Tooltip 文案仍与 `ui/hints.py`、`ui/quickref.py` 的现有交互说明一致。若用户可见提示行为发生增删或改名，同步更新二者。

### T3 · 横向回归与交付

- 用 T0 的同一数据和窗口尺寸前台比较改前/改后逐帧结果；至少包含两个热力图、五个 Section、View 回访、首次进入、分屏、无缓存、快速重定向。报告“可见目标帧变化次数”和单次最长阻塞，不只报告函数调用次数。
- macOS Cocoa 与 Windows 源码前台分开验收；发布前如需要 frozen 验收，Full/Lite 分开记录。已有 `switch-smoothness` 探针和验证报告只能作为历史对照，不能当本补丁结果。
- 在 owner 与边界用例通过后做 `git diff --check`、链接/范围检查；没有新的风险或失败不扩到全套测试。新产品改动若形成可复发模式，再走 lessons gate。

## 4. 初稿分析阶段边界（2026-09-23）

计划初稿只完成分析，没有改 Tooltip 策略、页面过渡、AA 或热力图渲染代码；当时也未做截图所示项目的前台逐帧复现。以下执行记录更新这些初稿状态。

## 5. 执行记录（2026-09-23）

### T0：已按“假设未证实”路径调整

- 对合成 50,000 点 View A→B→A 路径补跑了 macOS offscreen 与 Windows 原生 Qt 探针，窗口逻辑尺寸均为 1365×720。Windows 第二次回访的淡出结束约 395.9 ms，结束后的首个目标画布 paint 在约 400.8 ms，AA 已开启；该探针记录的是 paint/状态，不含屏幕像素。
- macOS offscreen 第二次回访在淡出结束后约 291.9 ms 记录到非 AA paint、约 299.2 ms 记录到 AA paint。它与 Windows 原生事件顺序不同，仍是 offscreen 代理证据。
- 当前 `1.tlproj` 前台观察及截图没有捕获相邻可见帧或局部像素哈希，无法证明“两次 paint”对应用户看到的两次闪烁，也没有区分旧图、空白、范围移动和 AA 变化。因此本次不把共享过渡/AA 边界认定为根因。

### T1：未实施

T0 没有满足“肉眼两闪对应的两次可见像素变化”门槛。为避免按 offscreen 事件顺序误改真实画布，未更改页面过渡、AA hold 或热力图 show/对齐路径，也未新增伪造可见帧结论的测试。

### T2：已实现并验证

- `glass_tooltip` 安装时将当前 Qt style 包装为单一 wake policy，把普通 QWidget Tooltip 的 `SH_ToolTip_WakeUpDelay` 设为 350 ms；其他 style hint 和 style objectName 沿用原值。预设卡 300 ms 与侧边 peek 150 ms 仍由原有独立定时器控制。
- 新增 `test_tooltip_wake_policy_is_shared_and_preserves_fall_asleep_delay`，覆盖 350 ms、fall-asleep hint、style identity 和重复安装幂等。
- macOS 与 Windows 原生 Qt/QTest 控件探针均读取到 350 ms wake hint。合成鼠标输入下，首次普通 Tooltip 显示约 353–392 ms；短时间跨控件仍按已有快速唤醒显示，约 33–70 ms。该测量不等同于人工前台验收。
- 聚焦门通过：`tests/ui/test_glass_tooltip.py`、`tests/ui/test_analysis_time_range_intent.py`、`tests/ui/test_hint_nudges.py` 共 103 passed；有 20 条既有 NumPy shape deprecation warnings。

### T3：部分完成，热图前台像素验收未完成

T2 的两个原生 Qt 平台探针已测量；尚未完成计划要求的热图前台逐帧对比、五个 Section/分屏/无缓存/快速重定向矩阵。由于 T1 未实施且 T0 像素根因未证实，这些热图场景不作为本次通过项。`git diff --check` 通过。


## 6. 用户复测仍闪后的重新定位与修复（2026-09-23）

### 6.1 判定：上一轮未实施热图修复，初稿 AA 归因也不足

当前工作区上一轮只修改了 `glass_tooltip.py`、其测试和 Tooltip lesson；§5 也明确记录 T1 未实施。因此“执行 plan 后仍闪”并非已经修复热图后又回归。初稿将结束后的两次 paint / AA 变化列为主要嫌疑，未发现过渡期间的实际白底泄漏；本节以像素证据修正这条归因。

### 6.2 已证实的原因

共享 `PageTransitionController.accept_target()` 在自然 paint 后禁用目标控件更新，却仅保留旧图并逐渐降低旧图透明度。Qt 的 `setUpdatesEnabled(False)` 不会保留目标子控件在透明兄弟控件下的参与绘制资格：透明覆盖层更新时，目标被跳过，露出宿主白底；过渡结束解冻后目标重新出现。

最小实验“黑图 → 同一张黑图”在旧实现的进度 0/25%/50%/75%/100% 得到 `#000000 / #404040 / #808080 / #c0c0c0 / #ffffff`。这证明可见内容错误，与 AA 状态无关。首次计算、未缓存、禁用动效的路径可能跳过这段过渡，所以不能仅根据“首次正常”排除共享控制器。

同时，原双快照路径将源、目标分别以 `1-p` 和 `p` 的透明度做 SourceOver，合成 alpha 为 `1-p+p²`；中点只有约 75% 不透明度，也会漏底。新增测试在修复前分别失败于 `#404040` 与 alpha 191，而不是仅统计 paint 次数。

### 6.3 实施范围

只修改共享 `ui/chart_stack/page_transition.py` 的合成与冻结顺序：

1. 自然绘制确认后，使用已有的 0 ms 延后回调，在 paint 调用栈退出后缓存一次完整目标画面；按覆盖区域和 DPR 裁剪，随后才禁止目标更新。
2. 先以完整不透明度绘制目标，再覆盖 `1-p` 的旧图。过渡期间始终有完整底图。
3. 抓取失败则取消过渡并展示真实目标；抓取引发布局/生命周期失效时校验 token，避免冻结失效目标。完成、取消、快速重定向仍由现有清理路径解冻、释放两张临时图。
4. 所有已启用过渡的时域、频谱、时频、阶次、频响共享该修复。计算、缓存身份、坐标轴恢复、AA 阈值与结束后的质量结算均保持原有语义。

这是对旧“完全不抓目标图”的性能选择的必要修正：保留“不在 paint 回调内 grab”的安全边界，增加一次延后目标截图。没有改成每个动画帧重画整张曲线。切换中最多保留两张局部端点快照，结束后释放。

### 6.4 当前验证结果

| 检查 | 结果与证据类别 |
| --- | --- |
| 共享控制器、ChartStack 集成、五 Section 矩阵 | 86 passed、1 skipped；另增真实 PgHeatmapCanvas 重复切换像素用例 1 passed，均为 offscreen |
| 离散质量保持、backref/import/状态所有权、信号连接边界 | 30 passed |
| Cocoa 像素检查 | 6 passed；真实热图控件像素用例另 1 passed |
| 实际 `testdoc/1.tlproj` | 原生 Cocoa，1365×820 逻辑窗口，三轮 View 1 → View 2；逐约 16 ms 采样 QWidget 合成图 |
| 实际项目修复前后对比 | View 2 的过渡进度 >98% 时，终态应为暗色的区域中，旧逻辑约 99.34% 像素变成亮白，新逻辑为 0%；三轮一致 |
| 24 次跨 Section 探针 | 无取消、无语义 delta、目标淡入期间无 AA 绘制；offscreen 性能代理，不等同于原生性能验收 |
| 原有曲线重绘上限 | `test_time_tab_switch_completes_natural_fade` 的 ≤8 次门槛保持通过 |

实际项目对比通过探针仅替换旧/新合成与冻结方法进行 A/B，其他源码与数据相同。暗色定义 RGB 各分量 <30；亮白判定各分量 >160，采样区域限定在图表过渡区域。主图、色条、下方切片来自实际项目；没有保存或修改该项目文件。

本地证据在 `.state/heatmap-flicker-fix/`：`project-before-cocoa.json`、`project-after-cocoa.json`、`before-cocoa-lap1-view2.png`、`after-cocoa-lap1-view2.png`、`owner-tests-after.log`、`boundaries.log`、`cocoa-pixels.log`、`cocoa-heatmap.log`、`section-after.json`。其中项目像素是 QWidget 合成帧，**不是操作系统屏幕录像**；截图工具选到了既有 Python 主进程，故没有将该截图当作探针验证证据。

性能代价：50k 合成数据的第二轮热图进入，新增目标截图约 5.3–6.9 ms（offscreen），稳态动画帧间隔约 16 ms。快照存储由一张变成两张；没有用此结果宣称所有平台更快。已有 FFT 离开时昂贵 AA 源截图仍是独立性能问题。

未完成的发布验收：Windows Full/Lite 冻结包及连续屏幕录像。本轮默认 Windows Python 缺少 PyQt5，未安装或改动其环境。当前修复在源码工作区；已经启动的旧进程、旧 exe 不会自动加载本次修改。
