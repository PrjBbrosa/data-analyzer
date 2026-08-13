# UltraView View 栏右侧固定入口实施计划

- 日期：2026-08-13
- 状态：自动门禁已通过；UVR-A15 真实 macOS 前台仍为 UNVERIFIED
- 规格：
  `docs/analyzer/specs/2026-08-13-ultraview-view-rail-dock-spec.md`
- 原型：
  `docs/analyzer/ui-prototypes/2026-08-13-ultraview-entry-options.html`

## 0. 目标、边界和完成定义

把当前顶部 Toolbar 的可见 `总览` 入口迁到时域及四个分析工作区的 View 栏最右侧，
应用 Electric Spectrum 图标/文字，并在所有 split/compare 控件组合与窄宽度下保持稳定。

本计划不实现或修改 UltraView Board 功能。实现只触及入口组件、两个 View 行挂载点、
信号路由、必要帮助文案与聚焦测试。当前 worktree 已有其他 UltraView 和 UI 改动；执行者
必须先重新读取 diff，逐文件保护，不得覆盖或顺带提交无关变更。

完成必须同时满足：

1. `UVR-A01…A15` 有代码、测试或前台证据对应；
2. 顶部不再有可见 UltraView 主入口，五个 source View 行各有一个最右 Dock；
3. 现有 `open_ultraview()`、`add_to_ultraview_requested(section, view_id)` 与零计算语义
   不回归；
4. 聚焦测试、边界测试、确定性渲染检查通过；
5. 真实 macOS 前台截图通过后，才可声明视觉验收完成。

## Task 1 — 冻结当前行为与状态矩阵（RED 前置）

**读取/可能扩展**

- `tests/ui/test_view_tabbar.py`
- `tests/ui/test_view_tabbar_mount.py`
- `tests/ui/test_analysis_section_page.py`
- `tests/ui/test_toolbar.py`
- `tests/ui/test_ultraview_mode_integration.py`

**步骤**

1. 记录 `git status --short` 和上述 owner 文件的现有 diff；只标记本任务计划触碰的
   hunks，不清理其他人的改动。
2. 先运行现有聚焦测试，记录 pre-change baseline；失败项先分类为本任务前置问题或已有
   debt，不在代码中绕过。
3. 为 §4.2 全部状态组合写参数化测试，冻结当前控件逻辑：
   - 时域未合并 / 已合并；
   - line analysis 单 pane / 双 pane；
   - heatmap analysis 单 pane / 双 pane；
   - manager 达 `max_views`。
4. 断言 `_split_clear` 的两套文案与 signal 语义保持不同；断言分析外部按钮当前由
   `_refresh_compare_buttons()` 控制。
5. 先写迁移后的 RED expectations：Dock 为宿主行最后项，Toolbar 可见入口不存在，
   点击任一 Dock 只发一个无参数 open intent。

**建议命令**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_analysis_section_page.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_ultraview_mode_integration.py -q
```

**Exit gate**：旧行为 baseline 已记录；新入口/顺序测试因功能尚未实现而稳定失败，不因
测试夹具缺失或 Qt teardown 崩溃失败。

## Task 2 — 实现 Electric Spectrum Dock 组件

**新增**

- `mf4_analyzer/ui/widgets/ultraview_entry.py`
- `tests/ui/test_ultraview_entry.py`

**按需修改**

- `mf4_analyzer/ui/widgets/__init__.py`（只有公共 import 确实需要时才 re-export）

**测试先行**

1. 组件固定高度不超过 View 栏 28px；full 模式包含图标和 `UltraView`，compact 模式
   仅图标，但 `accessibleName` / tooltip 不变。
2. 用 signal spy 证明鼠标 click 与键盘 Space/Enter 都产生一次 `clicked`。
3. 以固定 palette、字体和 DPR 渲染 normal/hover/pressed/focus 快照，采样证明：
   - 图标与 glyph 内包含 `#0969DC / #734EE6 / #BD299F` 邻域；
   - 背景/边框未被大面积渐变污染；
   - 右下角和圆角外像素没有 backing rectangle。
4. 对三个色标和 `#FFFFFF`、`#FBFCFF` 做纯函数 WCAG contrast 测试，最低 4.5:1。
5. 2× DPR 下渲染尺寸和边缘不糊；不要断言平台字体导致的脆弱整图 hash。

**实现**

1. 使用 `QAbstractButton` 或 `QPushButton` 子类，保留标准 button state、focus policy 和
   signal；不手写一套点击状态机。
2. 使用 `QPainterPath.addText()` + `QLinearGradient` 绘制 glyph；2×2 rounded tiles 与
   文字共享同一从左到右的渐变坐标。
3. `sizeHint()` 来自 icon、字体 metrics、内边距与 gap 实测；只固定行内高度，不固定
   full 模式宽度。
4. 提供具名 API，例如 `set_compact(bool)` / `is_compact()`；compact 不改 action 语义。
5. 对象名、accessible name、tooltip 和 test diagnostic API 固定，不让测试去读私有
   painter 临时状态。

**Exit gate**：`test_ultraview_entry.py` 全绿，Electric Spectrum 和可访问状态有确定性
证据；未挂载到产品前不宣称前台外观通过。

## Task 3 — 建立可复用的宿主行宽度判定

**优先修改**

- `mf4_analyzer/ui/widgets/ultraview_entry.py`
- `tests/ui/test_ultraview_entry.py`

**可能修改**

- `mf4_analyzer/ui/view_tabbar.py`
- `tests/ui/test_view_tabbar.py`

**步骤**

1. 提取纯判定 helper，输入为 `available_width`、当前可见 non-dock items 的真实
   `minimumSizeHint/sizeHint`、margins、spacing、full/icon Dock hints，输出 full 或
   compact；不得读取 MainWindow，也不得包含固定窗口宽度断点。
2. 宿主 resize、split clear 显隐、分析 compare toggle 显隐后重新判定；用一次 deferred
   layout pass 合并同一事件循环中的多次 relayout，避免闪烁和递归 resize。
3. 从 compact 恢复 full 使用同一 intrinsic full requirement。若测试复现临界值抖动，
   增加由字体 metrics/gap 推导的滞回，并为上下边界写测试。
4. 若外部 Dock 模式变化后 `ViewTabBar` 未自动重新 fit，新增公开具名
   `ViewTabBar.refresh_fit()`，内部调用既有 `_sync_tabbar_width()`；不要让页面直接调用
   私有方法。
5. 参数化多 View、长名称、split clear、overflow、当前 tab 在尾部等组合，证明当前
   View 不隐藏、不切换，固定 action 不出界。

**Exit gate**：宽窄切换仅由 live hints 决定；不存在 `width < N`；反复 resize 不抖动，
`roomy → compact → overflow` 原合同保持。

## Task 4 — 挂载到时域和四个分析 View 行

**修改**

- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/analysis_section_page.py`
- `tests/ui/test_view_tabbar_mount.py`
- `tests/ui/test_analysis_section_page.py`

**步骤**

1. 时域 `ChartStack.attach_view_tabbar()`：
   - 在 `timeViewBottomDock` 的 hint bar 之前建立 28px horizontal host；
   - 挂载 `[ViewTabBar stretch=1] [separator] [UltraViewDock]`；
   - 保持 time dock 浅色 surface、顶部 hairline 与 hint bar 顺序/高度不变；
   - 重复调用仍返回既有 bar，不创建第二个 Dock 或重复连接。
2. 分析 `AnalysisSectionPage._compare_row`：
   - 保留 `btn_link` / `btn_lock_levels` 的页面所有权；
   - 在二者之后追加 separator 与 Dock；
   - 不把分析状态或 compare buttons 移进共享 `ViewTabBar`。
3. 给页面/ChartStack 提供只读 diagnostic 属性或 `findChild` 稳定 objectName，供测试读取
   顺序和 geometry，不暴露可写产品状态。
4. 按状态矩阵逐一 show、processEvents、读取 geometry：
   - Dock 的 `right()` 始终等于 host contents right（扣除既有右 margin）；
   - `split clear / link / lock` 全在 Dock 左侧且不重叠；
   - 行高保持 28px，分析和时域 hairline 对齐。
5. 在窄宽下允许 Dock icon-only 与 View overflow；不允许 layout 通过扩大宿主最小宽度
   掩盖问题。

**Exit gate**：五个 source section 都符合 `UVR-A01/A03/A04/A08/A10/A11`；UltraView
页面自身没有递归 Dock。

## Task 5 — 统一打开信号并迁走 Toolbar 入口

**修改**

- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/toolbar.py`
- `tests/ui/test_toolbar.py`
- `tests/ui/test_ultraview_mode_integration.py`

**步骤**

1. `ChartStack` 增加 `open_ultraview_requested = pyqtSignal()`；时域与四个分析 Dock 的
   `clicked` 均只转发到这一信号。
2. MainWindow 在统一 wiring 区只连接一次：

   ```python
   self.chart_stack.open_ultraview_requested.connect(self.open_ultraview)
   ```

3. 删除 Toolbar 左组的可见 `btn_ultraview`、`ultraview_requested` signal、layout/wire/
   enabled-state 引用；相应测试改为断言顶部没有可见入口。
4. 隐藏 `btn_mode_ultraview` 只作为当前兼容属性保留，不接入 layout、focus chain 或 mode
   mapping。不要在本任务无证据删除它。
5. 覆盖五个 Dock：每次 click 仅触发一次 `open_ultraview()`。已有 sheet 时验证 raise 路径，
   `_ultraview_sheet` identity 不变。
6. 回归 `add_to_ultraview_requested(str, str)`：View 右键动作仍携带当前稳定
   `(section, view_id)`；不要把 open signal 和 add intent 合并。
7. 复用现有 job-isolation probe，证明打开/置前不调用 `do_plot/do_fft/do_fft_time/
   do_frf/do_order` 或 analysis coordinator submit。

**Exit gate**：`UVR-A02/A05/A06/A11/A12` 全绿；产品只有 View rail 一个主发现入口，
Toolbar 不留空白 spacer 或错误对称宽度。

## Task 6 — 同步提示、QuickRef 与帮助

**修改**

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `mf4_analyzer/help/ultraview-guide.html`
- 对应 hints/quickref/help tests

**步骤**

1. 新增/更新提示：“各工作区 View 栏最右侧 UltraView：打开跨 View 只读对照，不重新
   计算”。不把 UltraView 写成分析算法。
2. QuickRef 和 help guide 删除“顶部/顶栏总览”路径，改为 View 栏右端品牌入口；保留
   View 右键“加入总览”作为添加内容动作。
3. 全库搜索旧可见入口文案；历史 dated specs/plans 只由本规格的 supersede 声明解释，
   不回写历史事实。
4. 更新可见交互登记测试，避免只改一处文案。

**Exit gate**：`UVR-A14` 通过；运行时帮助与新位置一致，历史记录保持原样。

## Task 7 — 自动化几何、像素与边界验证

**新增/修改**

- 优先扩展现有 UI visual verifier；确有独立价值时新增
  `tools/verify_ultraview_entry.py`
- 对应 `tests/test_verify_ultraview_entry.py`
- 生成证据放 `.state/ultraview-entry/`，默认不提交

**矩阵**

| section | pane/merge | 宽度 | 预期右侧动作 |
|---|---|---|---|
| time | single | roomy / narrow | UltraView |
| time | merged | roomy / narrow | 取消合并 → UltraView |
| fft | 2 panes | roomy / narrow | 关闭 → 联动 → UltraView |
| frf | 2 panes | roomy / narrow | 关闭 → 联动 → UltraView |
| fft_time | 2 panes | roomy / narrow | 关闭 → 联动 → 锁色阶 → UltraView |
| order | 2 panes | roomy / narrow | 关闭 → 联动 → 锁色阶 → UltraView |

每格自动断言：

- object visibility、layout index、geometry 不重叠、Dock 右边缘固定；
- 当前 View 可见，overflow count 与 menu 内容正确；
- full/icon-only 与 live hints 判定一致；
- Electric Spectrum 像素、圆角外透明/正确底色、focus ring；
- 1×/2× DPR，默认字体与至少一个较大 UI 字体；
- 连续切换 split/section/resize 不创建重复 signal connection 或 widget。

**Exit gate**：自动证据 manifest 列出所有矩阵格，无人工挑图；offscreen 异常退出、
timeout 或 crash 记为 `UNVERIFIED`。

## Task 8 — 聚焦回归与架构边界

先运行修改 owner 的聚焦套件，再运行相关 guard：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_entry.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_analysis_section_page.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_job_isolation.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
```

检查点：

- `ui/widgets/ultraview_entry.py` 不 import MainWindow/coordinator/numeric modules；
- 没有新增多文件 MainWindow mutable state；
- 没有新增 `.connect(lambda ...)`；
- custom paint 不用 QSS border shorthand 破坏 radius；
- Qt parent、timer/deferred resize callback 在 teardown 时安全，重复创建/销毁不出现
  `sip.isdeleted` wrapper 复用。

聚焦与边界全绿后，按仓库当前规则分两进程跑主 suite 与 acquisition suite。任何 crash、
timeout 或中断均为 `UNVERIFIED`，不能用已完成的测试数量推断通过。

## Task 9 — 真实 macOS 前台验收

1. 用真实 TraceLab、真实应用字体和当前主题启动，不以 HTML 原型或 offscreen Qt 代替。
2. 捕获 Task 7 的六类状态，至少包含：
   - 普通时域宽/窄；
   - 时域合并；
   - FFT 双 pane；
   - 时频双 pane最大动作组合；
   - 12 View 达上限且发生 overflow；
   - UltraView 窗口已打开后再次点击置前。
3. 检查 28px 高度、右 margin、分隔线、文字基线、Retina 渐变、hover/pressed/focus、
   圆角外像素和临时动作出现时的横向位移。
4. 对比自动 screenshot/geometry manifest；有差异先回到 owning widget 修复，不靠反复
   调 QSS padding 猜位置。
5. Windows frozen 前台验收若本轮无法执行，明确记录为 `UNVERIFIED`，不得由 macOS 或
   source test 替代。

**Exit gate**：用户可在每个工作区相同位置找到 UltraView；最大动作组合仍清楚、无重叠，
Electric Spectrum 字标精致但不抢过分析内容。

## Task 10 — 文档、diff 与提交范围收口

1. 更新本计划 checkbox/实际命令结果；如需 durable verification，写入
   `docs/analyzer/verify/`，不提交 `.state/` 截图缓存。
2. 全库第二遍搜索：

   ```bash
   rg -n "顶部.*总览|顶栏.*总览|btn_ultraview|ultraview_requested" \
     mf4_analyzer tests docs/analyzer --glob '!specs/2026-08-12-*' \
     --glob '!plans/2026-08-12-*'
   rg -n "UltraView|Electric Spectrum|0969DC|734EE6|BD299F" \
     mf4_analyzer tests docs/analyzer
   ```

3. `git diff --check`；逐文件查看 diff，确认没有混入当前 worktree 的其他 UltraView 生命周期、
   QSS、toolbar Save split 或 line-canvas 改动。
4. 若用户要求 commit，只 stage 本任务文件和必要测试；先展示 staged scope，再提交。
5. 检查 lessons 状态。只有出现可复用的新失败模式才创建候选；“按既有测量式宽度合同
   实现成功”本身不需要重复 lesson。

## 11. 验收映射

| 验收项 | 主要 Task | 主要证据 |
|---|---:|---|
| UVR-A01/A03/A04 | 1, 4 | 状态矩阵 + layout index/geometry tests |
| UVR-A02 | 5 | Toolbar owner tests + 前台截图 |
| UVR-A05/A06 | 5 | signal spy + sheet identity + context-menu intent |
| UVR-A07/A13 | 2, 7 | deterministic paint/contrast/keyboard tests |
| UVR-A08/A09/A10 | 3, 4, 7 | measured fit + resize/overflow geometry manifest |
| UVR-A11 | 1, 4, 5 | max_views 参数化测试 |
| UVR-A12 | 5, 8 | 既有 job-isolation 零计算探针 |
| UVR-A14 | 6 | hints/quickref/help tests |
| UVR-A15 | 9 | 真实 macOS 前台截图与操作记录 |

只有所有自动门禁通过，并且 `UVR-A15` 有真实前台证据，才可把本计划标为完成。
