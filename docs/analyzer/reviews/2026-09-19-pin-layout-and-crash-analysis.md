# Pin 布局与闪退分析

2026-09-19；基于当前 `a5c10c79` 的已有脏工作区、用户截图、系统崩溃报告与独立诊断进程。此次没有修改应用源码。HTML 是交互原型，不是 Qt 验收。

## Findings

### P1：Pin 引导线坐标映射可直接导致原生崩溃

`mf4_analyzer/ui/pg_canvas/pinned_cursor_overlay.py:1211`、`:1214` 用 `canvas.mapTo(glw, point)` 从父控件映射到后代控件。当前 Qt5 运行时中，此方向可在原生 `QWidget::mapTo` 中触发 SIGSEGV；外围 Python `try/except` 无法捕获。对象存活检查不足以保护错误的映射关系。

最新用户操作时段的系统报告为 `~/Library/Logs/DiagnosticReports/Python-2026-09-19-164137.ips`，进程从 16:39:18 运行到 16:41:35，主线程 `QWidget::mapTo` → PyQt 包装 → Python 回调，调用链下方有 `QTimer::timerEvent`，访问地址 `0x28`。Pin 的几何定时器在 `pinned_cursor_overlay.py:634` 连接 `_reproject_geometry`，后者调用 `_sync_leaders`。

隔离诊断 `.state/probe_pin_mapto.py` 构造真实父/子 Qt 控件，直接调用当前生产 `_sync_leaders`，结果：

```text
ancestor: True
Fatal Python error: Segmentation fault
.../pinned_cursor_overlay.py, line 1211 in _sync_leaders
exit code: 139
```

安全方向对照：`glw.viewport().mapFrom(canvas, point)` 再传入 `glw.mapToScene`，同环境坐标往返为 True，退出 0。后续修复需同时遵守 QGraphicsView 的 viewport 坐标域，而非只调换 mapTo/mapFrom 字样。

通常 Pin 标签因聚集、贴边、排布位移而生成 leader，进而进入该分支（`:317`）。这说明故障可能在缩放、标签拥挤时出现，不一定每次 Pin 都立即出现。尚未复现用户原始文件和完整前台操作；系统报告没有 Python 源行，所以“该缺陷可崩溃”已证实，“这次事故必然由此行触发”仍是高度吻合的判断。

同类危险调用还在 `chart_stack/pinned_cursor_controller.py:790`、`:794`、`:795` 的频谱命中检查里；此次未单独调用该生产分支。当天 10:36、11:28 的既有报告也以 mapTo/0x28 开头；12:16 的报告则是 Python 退出时 `sip_api_visit_wrappers`，不能合并为同一个根因。本次诊断新产生的崩溃记录不计入用户历史事故。

建议下一步先修坐标映射与 focused subprocess regression，再做 Cocoa 下密集 Pin、边界标签、缩放和频谱命中验收。此报告没有执行修复。

### P2：继承浮动面板位置，加标题避让，必然容易堆叠

`chart_stack/pinned_cursor_controller.py:1021` 起，新 Pin 直接继承 live pill 的 x/y；`:1230` 起 `_nudge_live_from_pins` 仅对已固定面板最多 26px 高的标题矩形做避让，而不是整个面板矩形。避让对象是 live pill，并非统一重新布局所有 Pin。

因此并不是代码写死“屏幕正中央”，而是连续 Pin 复制同一浮动位置后，仅移动少量距离。用户截图的阶梯式重叠与该逻辑一致。手动已摆放的 live pill 会跳过自动避让。

`:1191` 的 anchor 恢复只做边界约束，没有固定面板之间的碰撞解算。`cursor_pill.py:32` 的白背景 alpha 为 235/255，会让下层内容透出少量，放大重叠时的视觉干扰；但截图中的所有浅色文本不能仅凭此常量归因。

### P2：默认竖线对比过低

`pg_canvas/pinned_cursor_overlay.py:40` 起，single pin 为 `#7090be`，默认 alpha 110/255；`:1032` 默认宽度 1.0，虚线。白底上混合后约为 `#c1cfe3`，与浅色网格区分不足。高亮时才变为 alpha 220、宽度 1.5。

建议默认清晰蓝灰 `#54749d` / 1.5px 虚线，选中 `#006bea` / 2.5px 实线，编号与面板同步高亮。通过线型、粗细、编号共同区分，不仅靠颜色；通道继续保留原有颜色。双游标仍需保留 A/B 端点语义，本轮原型仅演示单点 Pin。

## 三种交互方案

原型：`../ui-prototypes/2026-09-19-pin-layout-options.html`。

| 方案 | 新 Pin 去向 | 多 Pin | 主要代价 |
| --- | --- | --- | --- |
| A 右侧停靠（优先建议） | 图表内固定读数列表，按时间排序 | 滚动；列表和竖线联动 | 缩窄绘图区，可考虑收起原 Inspector |
| B 底部对比 | 对比表新增一行，通道共享列 | 数值横向对齐；纵向滚动 | 降低绘图区高度，多通道需横向滚动 |
| C 就近单卡 | 对应竖线附近，只展开选中 Pin | 其他只保留编号；编号条选择 | 不能同时展开多张；仍有局部遮挡 |

共同规则：Pin 绑定数据坐标，编号删除后不复用，视野外保留记录并标明状态；面板内容用不透明底。原型包含方案切换、密集 8 点、线条强弱对照、拖动/方向键调整 Pin、双击新增、删除、范围缩放；使用合成数据，不读取用户数据。

## 验证边界

- 原生崩溃诊断：独立 offscreen 子进程生产方法复现 exit 139；安全坐标映射对照 exit 0。
- 本轮未做产品修复，因此不运行完整应用测试套件，也不宣称修复通过。
- 浏览器检查仅验证 HTML 原型；不替代 Qt 前台、macOS/Windows 产品验收。
- Chromium 实际检查：1440×1000 下 A/B/C 截图，密集 8 点、切换方案、缩放、添加、方向键和鼠标拖动；390×844 下页面无横向溢出。截图位于 `.state/pin-layout-{a,b,c,mobile}.png`。这些检查不构成所有边界条件验收。
