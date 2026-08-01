# 批处理绘图迁移 Qt/pyqtgraph —— 设计 Spec

**日期：** 2026-08-01
**状态：** 已确认（四个关键决策由用户于 2026-08-01 拍板；已吸收执行前审查修订）
**配套执行计划：** `docs/superpowers/plans/2026-08-01-batch-qt-render-migration.md`

---

## 0. 已确认的产品决策（不得在执行中重开）

| # | 决策 | 结论 |
|---|---|---|
| D1 | 输出格式 | **PNG-only**。SVG/PDF 下线；冻结验收从 CSV+PDF 改为 CSV+PNG |
| D2 | B1–B4 渲染缺陷 | **迁移直接吸收**：正确行为写成新 Qt 渲染器的验收红测，不再修 matplotlib 版 |
| D3 | matplotlib 去留 | **彻底移除**：requirements、冻结打包、裁剪契约机器一并删除 |
| D4 | 视觉范围 | **曲线区对齐 timedomain**（色轮/线宽/网格/字体/轴样式），**保留**批处理报告元素（图头、facts 事实条、页脚、图例、colorbar、三主题） |

前置事实（review `docs/superpowers/reports/2026-08-01-batch-time-domain-wave-review.md`）：
A1（`source_paths` 驱动的批处理整体 blocked）是与渲染内核无关的 P0 回归，
**必须在迁移接线前单独修复**（见 plan Batch 1）。

执行解释：

- 本迁移的“视觉对齐”不是只对 token 或对象属性做断言。4 种 kind 必须使用同一份
  prepared payload，分别在新 batch Qt 渲染器和现有单文件 pyqtgraph canvas 上离屏
  出图，保存成对 PNG、plot-area crop 和 contact sheet，并由执行 agent 实际打开检查。
- 用户提供的主界面“时域 / FFT / FFT vs Time / 阶次”导航只用于说明单文件模块来源，
  **不得**进入批量 PNG。输出只允许 Spec §0 D4 已批准的批量报告元素和对应单文件 Plot
  绘图区；不得混入 Qt/pyqtgraph 默认按钮、菜单、边框、滚动条、焦点框、工具栏、状态
  提示或其他控件 chrome。
- 最终协调/主 agent 必须基于待验收 commit **亲自重跑**完整离屏矩阵，并再次打开四个
  模块的 contact sheet 复核；worker 的测试摘要、截图结论或 `evidence.json` 不能替代
  主 agent 的独立目视确认。
- 离屏证据是每个渲染 Batch 的硬 Gate，但不替代 macOS 前台真机验收；两类证据必须
  分开记录。
- 执行必须从包含本 Spec/Plan 的干净提交或独立 worktree 开始，不得在带有其他未提交
  产品修改的 checkout 中按 Task 提交。

---

## 1. 背景与目标

### 现状

- `mf4_analyzer/batch_render.py` 是产品运行时**唯一** matplotlib 使用者
  （OO Agg，无 pyplot），承担报告级出图：4 种 kind（`time`/`fft`/`fft_time`/
  `order_time`）× PNG/SVG/PDF，图头/facts/页脚/图例/colorbar/twinx 双 Y/
  subplot/三主题/CJK 字体链/像素+dpi 元数据。
- 主界面 timedomain 及分析区已全部 pyqtgraph 化（`mf4_analyzer/ui/pg_canvas/`）。
- 测试强制 `batch_render.py` 源码不含 PyQt/pyqtgraph
  （`tests/test_batch_renderer.py::test_renderer_source_is_gui_framework_free`），
  本迁移**反转**该契约。
- 2026-07-31 刚为 matplotlib 冻结打包做过裁剪契约（`tools/matplotlib_frozen_contract.py`
  等），本迁移将其**整体退役**。

### 目标

1. 批处理导出图的曲线区渲染与 timedomain 视觉一致（同一调色/线宽/网格/字体/轴样式）。
2. 产品运行时零 matplotlib：依赖、打包、契约机器全部移除。
3. 吸收 B1–B4：双 Y 配色可区分、subplot 排版可读、面板标题按分组语义、图头不泄露
   JSON/绝对路径。
4. 保持 `BatchRunner` 的既有语义不变：manifest requested/effective outputs、
   data-only 降级、原子写、resume/retry、分组渲染。
5. 4 种 kind 的 plot area 在相同数据、显示参数和像素几何下，达到现有单文件 plot 的
   同等级显示效果：数据/范围/LUT/levels 精确一致，色轮/线宽/网格/字体/轴样式一致，
   无转置、漏线、裁切、文字重叠或明显锯齿退化。

### 非目标

- 不改 timedomain UI 的任何行为/外观/接口。
- 不改 `mf4_analyzer/signal` 数值层（dB 转换仍走 `SpectrogramAnalyzer.amplitude_to_db`）。
- 不做批处理结果的 GUI 内嵌预览（维持"落盘 + 打开文件夹"）。
- 不引入渲染并行化（维持 `BatchRunner.run` 串行编排）。

---

## 2. 架构设计

### 2.1 模块布局

```
mf4_analyzer/
  batch_render.py            # 保留为公共门面：re-export 公共 API（import 路径不变）
  batch_render_qt/           # 新包：Qt/pyqtgraph 渲染实现
    __init__.py              # render_batch_image / BatchRenderContext / BatchSeries
                             # / BatchTimeFigureSpec 实现与导出
    _dispatch.py             # QApplication 生命周期 + 跨线程渲染调度
    _builder.py              # payload -> GraphicsLayoutWidget 场景构建（4 kinds）
    _page.py                 # 报告页合成：图头/facts/页脚/图例布局
    _theme.py                # white/transparent/dark 三主题 token
    _fonts.py                # Qt CJK 字体解析 + glyph 覆盖检查
    _export.py               # widget -> QImage -> PNG（dpi/metadata）
  batch_image_options.py     # SUPPORTED_IMAGE_FORMATS 收缩为 {"png"}
```

约束：

- `mf4_analyzer/batch.py` **顶层仍不得 import Qt**。现有惰性导入点
  （`_probe_image_backend` / `_write_image` 内部 `from .batch_render import ...`）
  保持惰性；`_probe_image_backend` 的 ImportError 探测语义原样保留（探测目标随
  实现自然变为 PyQt5/pyqtgraph 可用性），data+image → data-only 降级、
  manifest `degraded_reason`、`degraded_count` 全部不变。
- `tests/test_signal_no_gui_import.py`（signal 层禁 GUI import）必须保持全绿。
- 公共 API 按当前真实调用冻结：
  `render_batch_image(payload, path, params=None, options=None, context=None,
  warnings_out=None)`。不得擅自改成 keyword-only，也不得漏掉 `warnings_out`；非法 cmap
  等 renderer warning 仍通过该 list 回传。跨线程 marshal 时只由 GUI 线程写，worker
  在阻塞返回后读取。
- `BatchRenderContext`、`BatchSeries`、`BatchTimeFigureSpec`、
  `BatchRenderOptions` 字段名均不变（`format` 的合法值域收缩，见 §3）；
  `BatchRenderOptions` 继续定义在 GUI-free 的 `batch_image_options.py` 并由门面 re-export。
- 私有 `_build_batch_figure` **不属于**保留 API。facade 切换时必须先处理当前
  `BatchRunner._build_export_scene` 对它的兼容引用：删除该仅测试兼容 wrapper，或改成
  明确命名的 Qt scene 测试 helper；不得留下指向已删除 matplotlib 私有函数的入口。
- 私有 API 的 blast radius 还包括 `tests/test_db_conversion_convergence.py` 中的
  `_build_export_scene` 消费者；这些测试改到共享 dB-reference producer/formatter 契约，
  不能因为删除 wrapper 一并丢掉。`batch_series_spool.py` 仍通过公共 facade 获取
  `BatchSeries`，门面必须继续 re-export 该类型。
- `RenderGroup` 实际定义在 `mf4_analyzer/batch_grouping.py`；B4 的 `display_name`
  字段与构造测试必须在该模块落地，`batch.py` 只消费结果。

### 2.2 QApplication 生命周期与线程边界（关键设计）

三种运行形态：

| 形态 | 线程 | QApplication |
|---|---|---|
| GUI 批处理 | `BatchRunnerThread`（QThread worker）调用 `run()` | 已存在（主线程） |
| 无 GUI CLI（冻结烟测/冻结验收/时域分组验收） | 主线程 | 不存在，需创建 |
| pytest | 主线程（offscreen） | 根测试用 `pytest-qt` 的 `qapp` fixture 或显式 `ensure_app()`；不得误以为只对 `tests/ui/` 生效的 conftest 会覆盖根测试 |

设计：

1. `_dispatch.ensure_app()`：
   - 已有 `QApplication.instance()` 且确为 `QApplication` → 直接用；若只有
     `QCoreApplication`，抛出明确错误，禁止继续创建 QWidget。
   - 没有且当前是主线程 → `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`
     后创建 `QApplication([])` 并缓存（CLI 路径）。
   - 没有且当前是非主线程 → 抛出带明确文案的 `RuntimeError`（不允许在 worker
     线程隐式建 app）。
2. `_dispatch.render_on_gui_thread(fn) -> result`：
   - 当前线程 == `app.thread()` → 直接执行。
   - 否则通过常驻 `app.thread()` 的 `_RenderDispatcher(QObject)` 以
     **BlockingQueuedConnection**（`QMetaObject.invokeMethod` 或等价信号+
     `QWaitCondition`）在主线程执行，异常必须跨线程原样重抛（携带原 traceback
     文本）。
   - `render_batch_image` 全程走此入口；每张图一次 marshal，图内不回跳线程。
3. 崩溃/退出防护：app 正在退出（`aboutToQuit` 已发）时 fail-fast 返回渲染错误，
   走 BatchRunner 既有的"图片写入失败 → 整组回滚"路径。

GUI e2e 必须通过真实 `ui/drawers/batch/runner_thread.py::BatchRunnerThread` 验证该边界：
pytest-qt 泵主事件循环，worker 同步等待 marshal；主线程不得反向同步等待 worker。
`warnings_out` 只由 GUI 线程写，caller 只在 blocking call 返回后读取，并验证 GUI-thread
异常原样传播。发布事务权威仍是 `batch_output.atomic_write_set`；backend 只允许在预留
输出路径之前的 import/probe 失败时降级为 data-only，Qt build/marshal/PNG save 等
writer-time 失败必须整组回滚。现有 `_write_image` 的内层 staging 在本迁移中保持不动，
不得借 renderer 切换顺手重构原子写层级。

平台选择：调用方显式设置的 `QT_QPA_PLATFORM` 优先，`ensure_app()` 只用
`setdefault`。源代码/pytest CLI 默认走 `offscreen`；Windows 冻结 verifier 若要验证
原生平台，必须显式传 `QT_QPA_PLATFORM=windows`，不得一边默认 offscreen、一边声称
验证了 Windows GUI platform。

已知风险与预算（由 plan Batch 0 spike 出证据）：

- 主线程逐图渲染会占用 GUI 线程。`500 ms` 只作为技术 STOP 线，不能作为“无感知
  冻结”的证明。预算：**单图（1920×1080、8 面板 subplot、每面板 1e5 点 envelope
  后）p95 ≤ 500 ms**，同时在 GUI batch 运行期间用 50 ms heartbeat 记录事件循环，
  **最大间隙 ≤ 200 ms**；任一超预算或人工操作感到连续卡顿，spike 报告必须给出
  降级方案评估（候选：渲染子进程池），并回到用户处决策，不得自行扩腹地。
- BlockingQueuedConnection 死锁面：主线程永不反向同步等待 worker（现状如此，
  BatchRunnerThread 只发 progress 信号），spike 需包含模态对话框打开时的渲染
  可达性验证。

### 2.3 离屏场景构建与导出

- 构建：`_builder` 建 `pg.GraphicsLayoutWidget`，`resize(width_px, height_px)`，
  设置 `Qt.WA_DontShowOnScreen` 后 `show()` + `processEvents()` 完成布局
  （在真实 GUI 平台上不闪窗口；offscreen 平台等价）。用后立刻
  `close()+deleteLater()`，不缓存 widget。
- 场景去 chrome：每个 `PlotItem` 显式 `hideButtons()`、关闭 context menu 和鼠标交互；
  宿主 widget/viewport 不画 frame、不出现 scrollbar/focus rect。测试必须内省这些状态，
  并在导出像素中验证绘图区角落没有默认按钮或控件占位。不得为了“像 Qt”添加任何
  单文件 Plot 本身不存在的装饰。
- 导出（`_export`）：**不用 `widget.grab()`**（HiDPI 下 devicePixelRatio 会使
  像素尺寸漂移）。改为：
  1. `QImage(width_px, height_px, Format_ARGB32_Premultiplied)`，按主题填充
     背景（transparent 主题填 `Qt.transparent`）；
  2. `QPainter` + `widget.render(painter)`，painter 显式开
     `Antialiasing | TextAntialiasing`（导出恒 AA，对齐 timedomain 导出行为）；
     同时所有曲线 `PlotDataItem`/`PlotCurveItem` 必须显式 `antialias=True`，因为
     pyqtgraph item paint 会按自身选项重设 painter hint；只开 QPainter hint 不算完成；
  3. `setDotsPerMeterX/Y(round(dpi / 0.0254))` 写 PNG pHYs（保留"像素几何
     权威、dpi 只是元数据"的既有语义）；
  4. `QImage.setText` 保留现有 `_render_metadata(context)` 的键值（tEXt chunk）；
  5. 存盘仍经 `batch_output.atomic_write`，本层只写 temp 路径。
- 禁 OpenGL（历史 lesson：OpenGL 会导致全白导出）。

### 2.4 各 kind 的场景规格

沿用现有 payload 契约（`(kind, payload)`），逐 kind：

**`time`（DataFrame 或 `BatchTimeFigureSpec`）**

- overlay：单 PlotItem；≤2 个 Y 单位（沿用 `_validate_time_spec_units` 上限
  与 fail-closed 文案），第二单位走右侧 aux ViewBox + AxisItem（对齐
  timedomain overlay 的多轴做法，替代 twinx）。
- **B1 吸收**：整图一个统一色轮跨左右轴顺序分配；验收断言"所有 series 的
  `(color, linestyle)` 两两不同"。
- subplot：GraphicsLayout 逐行 addPlot；X 范围显式传播（对齐 timedomain 的
  `_propagate_xlim_to_siblings` 思路，不用 setXLink）；仅底行画 X 轴标签；
  Y 标签按单位共享或行内简短标注。
- **B2 吸收**：8 面板（`_MAX_SUBPLOT_PANELS` 上限工况）必须可读。验收断言：
  相邻面板任何文本项的 sceneBoundingRect 互不相交。
- **B3 吸收**：面板标题按 `group_by` 分派——`source` 分组用 channel 名，
  `channel` 分组用文件名；同一张图内标题语义必须一致。该分派必须在
  `BatchRunner._render_group` 的 producer 端完成，renderer 只消费已决定的安全标题；
  只给 `_builder` 人工构造标题的测试不算完成。
- linestyle：`-`→SolidLine、`--`→DashLine（滤波伴随曲线沿用虚线约定）。

**`fft`（DataFrame）**

- 单 PlotItem 折线；dB 模式沿用现有 params 语义；固定色 `#1769e0` 保留。

**`fft_time` / `order_time`（x/y/matrix 对象或 DataFrame pivot）**

- `pg.ImageItem(axisOrder="row-major")`；X/time 使用 analyzer 的 coverage 起止边界
  （缺失时才按中心点回退），Y/frequency/order 保持真实单文件画布的首尾坐标，最终用
  `QRectF(x0, y_first, x1-x0, y_last-y_first)` 设置 extent。默认色图与非法 cmap
  fallback **固定为 turbo**；合法 cmap 继续按现有单文件/批处理语义生效，统一复用
  `heatmap_canvas._resolve_colormap`。turbo LUT 已有
  `tests/ui/test_colormap_parity.py` 黄金锁定；非法 cmap → turbo + warning 语义保留。
- 手动 Z：`z_auto=False` 时 `setLevels((z_floor, z_ceiling))`。
- colorbar：`pg.ColorBarItem`（只读、不可交互），标签沿用现有
  `colorbar_label`（dB/Amplitude）逻辑，dB 转换仍调
  `SpectrogramAnalyzer.amplitude_to_db`，导出数据不因显示模式改变。Qt 的 dB
  display matrix 必须与该 helper/真实单文件路径逐元素一致；旧 mpl renderer 私有的
  peak-200 数据截断不是 parity 目标，视觉下限只通过 color levels 表达。

**报告页合成（`_page`，所有 kind 共用）**

- 图头两行（LabelItem 行）：`source_display_name · group` / `channel · method`。
  **B4 吸收**：`RenderGroup.display_name` 是完整、安全的首行 display 文本（source
  分组 = 文件名 + 人类可读 group identity；channel 分组 = 通道名）；grouped render
  传入 context 时令 `source_display_name=display_name`、`group=""`，禁止把完整 display
  name 再和 group 重复拼接。`group_key`、group ID、source identity 保持机器身份用途、
  **禁止**进入任何图面文本。验收使用精确泄露守卫：断言原始 `group_key` 和已知
  `source_identity` 绝对路径不出现在任何 LabelItem/TextItem；不得用“禁止所有
  `[`/`"` 字符”代替，因为合法通道名本身可能含这些字符。producer-shaped 测试必须从
  `BatchRunner._render_group` 捕获实际 spec/context，并同时检查 Qt 文本项与 PNG metadata；
  只测人工安全 context 不算 B4 验收。
- facts 事实条：window/NFFT/weighting/averaging/overlap/Fs/dB 标签 +
  组图 `members=k/n`，字段与现实现一致（`effective_facts`）。
- 页脚：`Task <id> · TraceLab batch export`。
- 图例：time 多 series 时合并图例（跨左右轴合并为一个），报告风格显式图例框
  （批处理图脱离交互上下文，不采用 timedomain 的"内嵌标签替代图例"）。

### 2.5 视觉契约（timedomain 对齐表）

写入 `_theme.py` 并被测试断言，作为显式契约而非巧合：

| 维度 | 取值 | 来源 |
|---|---|---|
| 曲线色轮 | `mf4_analyzer._palette.FILE_PALETTES[0]` 循环 | timedomain Navigator 配色 |
| 线宽默认 | **1.5 px**。同时修改 `BatchRenderOptions.line_width`、`BatchOutput.image_line_width`、`batch_recipe.OUTPUT_DEFAULTS`、preset 导入缺省和 GUI 默认选中项；只改 renderer 默认无效。旧预设显式保存的 1.0 继续尊重 | timedomain `_overlay_default_lw` |
| 背景（white 主题） | `#ffffff` | `TimeDomainCanvasPG` |
| 轴 pen | `#9ca3af`（dark 主题给出等价深色 token） | timedomain |
| 网格 | 主刻度、alpha≈0.28、仅左/下轴 | `show_major_grid_left_bottom_only` |
| 字体 | Qt CJK 链（微软雅黑/PingFang SC/Noto Sans CJK SC…+ 西文回退） | `pg_canvas/fonts.py` 同源候选表 |
| 字号 | plot axis/tick 9 pt；subplot panel title 10 pt；报告图头 12 pt、facts 8.5 pt、页脚 7.5 pt | timedomain font helper + 现 batch 报告层级 |
| 抗锯齿 | 导出恒开 | timedomain 导出行为 |
| dark 主题 | 沿用现 batch dark 主题语义，token 化后由测试锁定 | batch 现状 |

字体实现注意：若 `mf4_analyzer/ui/pg_canvas/fonts.py` 可被无副作用 import，
直接复用其候选解析；否则把候选表提为两处共享的轻量常量模块，禁止复制两份
漂移（执行时二选一并写入测试锁定两侧一致）。

### 2.6 CJK 证明策略（替代 matplotlib glyph warning 机制）

matplotlib 的 missing-glyph warning 机制在 Qt 下不存在，替代双保险：

1. **字体覆盖检查**：`_fonts.resolve_cjk_font()` 用 `QRawFont.supportsCharacter`
   /`QFontMetrics.inFontUcs4` 验证契约文本 `单帧振动加速度` 逐字覆盖；无可用
   CJK 字体时报告显式环境门（与现状一致：报 skip/fail，不伪成功）。
2. **墨迹像素证明**：渲染含契约文本图头的图，对图头区域做"非背景像素数
   下限"断言，并与空标题渲染对比差异显著（防 tofu/空渲染）。

冻结烟测（§6）沿用这两条作为 `ok` 判据，替代原 glyph_warnings 判据。

### 2.7 离屏单文件 plot 对齐证明（硬合同）

新增 `tools/verify_batch_qt_render_parity.py`，使用同一份 prepared payload 分别驱动：

- `time` → 新 batch renderer 与 `TimeDomainCanvasPG`；
- `fft` → 新 batch renderer 与 `PgLineCanvas`；
- `fft_time` / `order_time` → 新 batch renderer 与 `PgHeatmapCanvas`。

reference canvas 和 batch plot area 使用相同有效 viewport 像素尺寸。工具必须保存完整
batch PNG、reference PNG、按真实 scene/view geometry 截出的 plot-area crop、并排
contact sheet 和机器可读 `evidence.json`。禁止用固定坐标猜 crop。JSON 至少记录
commit SHA、生成时间、`QT_QPA_PLATFORM`、Qt platformName、Qt/pyqtgraph 版本、case
清单、viewport、产物 SHA256 与各机器断言结果，避免拿旧图冒充当前实现。

最低矩阵：

| 模块 | 必测场景 |
|---|---|
| time | 单曲线；raw+filtered；overlay 双 Y；8-panel subplot；`x_source=channel` custom-X |
| fft | linear 与 dB；自动范围与手动 X/Y 范围 |
| fft_time | 非对称 2×3 矩阵；linear/dB；auto/manual levels；非法 cmap→turbo warning |
| order_time | 非对称 2×3 矩阵；auto/manual levels；真实 order/time 轴 extent |
| 横切 | white 主对齐；transparent/dark 语义；1080p/4K；CJK 图头与轴标签 |

Heatmap 必须用非对称矩阵的四角颜色/坐标断言抓住转置、上下翻转或把中心坐标误当
coverage 边界的问题。

每个 case 的通过条件：

1. **数值/结构：** curve X/Y、axis range、matrix、LUT、levels 与单文件路径一致；
2. **视觉 token：** 曲线色、1.5 px 默认线宽、linestyle、9 pt 轴字体、网格、轴 pen 一致；
3. **几何/像素：** 无空图、漏线、裁切、转置、文字相交，plot-area 指定色与墨迹存在；
   无 Qt/pyqtgraph 默认按钮、菜单、边框、滚动条、焦点框或导航控件；
4. **双层目视：** 实现 worker 必须实际打开每张 contact sheet，逐 case 写
   `PASS/FAIL + 备注`；最终协调/主 agent 还必须在待验收 commit 上亲自重跑并复核四个
   模块。只看到 pytest、worker 摘要或 evidence JSON 绿色不得签字。

离屏 parity 失败时，相关 Batch 停止；不得推迟到最终前台验收再处理。

---

## 3. PNG-only 格式收缩与旧预设语义（D1）

- `batch_image_options.SUPPORTED_IMAGE_FORMATS` → `frozenset({"png"})`；
  `BatchRenderOptions` 校验随之收缩，报错文案更新。
- **只在可信旧 preset/recipe 文件导入边界兼容**：`batch_preset_io.py`（以及带显式
  legacy-import 标记的 recipe 文件 importer）读到存量
  `image_format in {"svg","pdf"}` 时，构造 canonical
  `BatchOutput(image_format="png", requested_image_format=<原值>)`。新增
  `requested_image_format: str | None = None` 仅保存本次导入/运行的迁移来源；原生 PNG
  为 `None`。preset 再保存时只写 canonical `image_format="png"`，不持久化该 provenance；
  当前运行的 requested settings、item/group warning 和 manifest 已足够保留审计事实。
  `batch_recipe._duck_outputs` 等普通 canonicalizer 不是旧文件边界，不得无条件迁移；
  新代码直接构造 `BatchOutput(image_format="pdf"|"svg")` 仍按 unsupported format
  拒绝，不能把新的非法请求静默伪装成旧预设。
- runner 的 `requested_outputs["image"]` 使用
  `requested_image_format or image_format`，`effective_outputs["image"]` 固定为 `png`；
  二者不同时生成一条冻结文案的中文 warning，写入专用
  `migration_warnings: tuple[str, ...]`，再统一传播到 item/group warning 与 manifest。
  文案模板固定为：`旧预设图像格式 {requested_upper} 已迁移为 PNG；本次仅输出 PNG。`
  这不是 backend degradation，禁止复用 `degraded_reason`。所有 duck-field 白名单必须
  显式包含 provenance/warning 所需字段，避免跨层静默丢失。
- recipe fingerprint 使用 canonical effective `image_format="png"`，不纳入
  `requested_image_format`，让迁移 preset 与等价原生 PNG recipe 具有相同 artifact
  语义。`requested_output_settings` 仍保留原请求用于审计。
- resume caller 必须传当前 canonical effective `png`，不得优先采用 prior manifest 的
  requested pdf/svg。判定只以 fingerprint + `effective_outputs.image == "png"` + PNG
  artifact format/扩展名/checksum 完整为完成；manifest 可允许已记录的 requested 为
  png/pdf/svg。旧 manifest 若 effective 或 artifact 仍是 PDF/SVG，不得复用为 PNG。
- GUI `output_panel.py`：格式下拉只留 PNG（`("PNG","png")`），移除 SVG/PDF 两项；
  "PNG DPI" 行保留且恒可用（不再有非 png 分支禁用逻辑）。
- CLI：`frozen_batch_acceptance.py` 请求 CSV+**PNG**；
  `batch_render_smoke.py` 矩阵 4 kinds × `("png",)`（12 → 4 个产物）。
- 相关矢量语义测试（PDF MediaBox、SVG XML、fonttype、Poppler 提取）随
  matplotlib 一并删除，**不迁移**。

---

## 4. B1–B4 吸收方式（D2）

| 缺陷 | 吸收位置 | 验收红测（先红后绿） |
|---|---|---|
| B1 双 Y 同色 | `_builder` 统一色轮 | 所有 series `(color, linestyle)` 两两不同（含跨左右轴） |
| B2 subplot 排版 | `_builder` subplot 布局 | 8 面板下所有相邻文本项 sceneBoundingRect 不相交 |
| B3 面板标题 | `_builder` 标题分派 | source 分组标题=channel、channel 分组标题=文件名，同图语义一致 |
| B4 图头泄露 | `batch_grouping.py` RenderGroup `display_name` + `batch.py` plumbing + `_page` | 精确断言原始 `group_key`/已知绝对源路径不在任何 LabelItem/TextItem；合法通道名可含 `[`/`"` |

matplotlib 版渲染器**不再接收任何修复**；迁移完成前它保持现状运行。

---

## 5. 测试策略

### 断言分层（替代 Figure/Axes 深绑）

1. **结构断言**（主力）：pyqtgraph 对象可内省——PlotItem 数量、
   `PlotDataItem.getData()` 数值、`opts["pen"]` 颜色/线型、AxisItem label、
   ImageItem levels/LUT、LabelItem 文本。等价替换现在的
   `axes.lines/get_linestyle/images[0].get_cmap` 断言。
2. **几何断言**：文本项 `sceneBoundingRect` 不相交（B2）、布局行列数。
3. **像素特征断言**：非全白、指定色存在、图头墨迹下限（CJK 证明）、
   输出 QImage 宽高==options、dpi 元数据 round-trip。
   **不用整图黄金 PNG**（跨平台字体渲染差异会让金图脆断）。
4. **文件级断言**：非空、原子写、manifest artifact_facts
   （path/format/size/width/height/dpi/sha256）不变。
5. **离屏成对渲染断言**：按 §2.7 保存 batch/reference/crop/contact sheet；机器断言
   负责数值、token、几何与像素存在性，执行 agent 负责逐张目视并在报告签字。

### 报废/改写清单（执行前必须 grep 全量测试树，见 lesson
`refactor/2026-06-18-mpl-canvas-retirement-test-blast-radius`）

- `tests/test_batch_renderer.py`：~41 用例按上述分层重写；
  `test_renderer_source_is_gui_framework_free` 反转为"禁 matplotlib"守卫。
- `tests/test_batch_runner.py`：`_build_batch_figure`、`mpl.image.imread`
  相关断言改 QImage/结构断言。
- `BatchRunner._build_export_scene`：删除或迁为仅测试 Qt scene helper，确保产品路径不再
  import `_build_batch_figure`。
- `tests/test_batch_preset_io.py` / `tests/test_batch_recipe.py` /
  `tests/test_batch_manifest.py`：补旧格式 provenance、canonical fingerprint、
  requested/effective/resume 组合矩阵。
- `tests/test_matplotlib_frozen_contract.py` + `tools/matplotlib_frozen_contract.py`：
  删除。
- `tests/test_frozen_batch_render_smoke.py`：按新 smoke 判据改写。
- 全量门禁：在 Batch 1 修完 A1 后从干净 commit 运行
  `pytest -p no:randomly --ignore=tests/acquisition_ui -q`，记录完整 failed nodeid 集合；
  后续失败集合必须是该集合的子集。不能只比较失败数量，也不预填历史估算数字。

### 新增守卫

- `batch.py` 顶层无 Qt import（源码扫描测试）。
- `mf4_analyzer` 全包无 matplotlib import（替代原方向的守卫，Batch 5 起生效）。
- 渲染线程契约测试：从非 GUI 线程调用 `render_batch_image`（存在 app 时）
  能正确 marshal 且异常可传播；无 app 且非主线程时报清晰错误。
- `tests/test_batch_qt_render_parity.py`：锁定 §2.7 全矩阵的结构/范围/LUT/levels/
  geometry，并验证 parity 工具没有缺 case 或把 reference 与 batch 指向同一实现。

---

## 6. 打包与依赖变更（D3）

移除清单：

- `requirements.txt`：删 matplotlib（`tools/` 下开发对比脚本仍可在开发机自装，
  文档注明；不入产品依赖）。
- `mf4_analyzer/io/runtime_dependencies.py`：删 matplotlib
  `FrozenImportDependency`。
- `tools/build_windows_folder*.ps1`：删 `MPLBACKEND=Agg`、mpl-data 裁剪、
  DejaVu 字体白名单逻辑；PyInstaller excludes 增加 `matplotlib`
  （连带评估 `contourpy/kiwisolver/cycler/fontTools/PIL` 是否失去唯一使用者）。
- `tools/matplotlib_frozen_contract.py`、`tools/verify_frozen_batch_render.py`
  中 matplotlib 专属校验：删除/改写。冻结 PNG 检查改用 Qt `QImage`；不得依赖
  Matplotlib 曾经传递安装的 Pillow，也不得用复用旧 venv 掩盖 fresh-build 缺包。
- lessons：`matplotlib-pruning-needs-frozen-render-matrix` 标记 superseded；
  `batch-render-cjk-glyph-coverage` 改写为 Qt 版规则；新增"Qt 离屏批渲染
  线程边界"lesson。

新增打包契约：

- 冻结包 platforms 插件必须同时包含 `qoffscreen` 与 `qwindows`。每个 onedir flavor
  的冻结验证分两次：
  `QT_QPA_PLATFORM=offscreen` 跑 headless 4-kind 矩阵；Windows 真机再显式
  `QT_QPA_PLATFORM=windows` 用 `WA_DontShowOnScreen` 跑原生平台矩阵。证据 JSON
  必须记录实际 platform，二者不可互相冒充。因此 full/lite 共四份 evidence：
  full-offscreen、full-windows、lite-offscreen、lite-windows；同一 flavor 的两份证据
  绑定同一 EXE SHA，full 与 lite 不要求 SHA 相同。
- 冻结烟测判据：4 kind × PNG 非空 + CJK 双保险（§2.6）+ turbo 取样正确。
- 在拆除 Matplotlib **之前**先保存 fresh full/lite 的 EXE/build SHA 与 `_internal`
  字节数/文件数；拆除后再生成同口径值。只有 after-build 值不能反推可信 before baseline。

---

## 7. 风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| 主线程渲染卡 GUI | 高 | Batch 0 同时测单图 p95 与 50 ms GUI heartbeat；p95>500 ms 或最大 event-loop gap>200 ms 即停，子进程方案不擅自实施 |
| BlockingQueuedConnection 死锁 | 中 | 单向 marshal 设计 + 模态对话框场景 spike + 退出防护 |
| CJK 证明弱于 mpl warning 机制 | 中 | 字体覆盖检查 + 墨迹像素双保险；无 CJK 字体环境显式门 |
| `WA_DontShowOnScreen` 平台差异（macOS/Windows 布局激活） | 中 | Batch 0 spike 双平台路径验证（macOS 真机 + offscreen；Windows 冻结验收在 Batch 6） |
| 透明背景/暗主题在 QImage 路径的表现 | 低 | spike 覆盖三主题各出一图 |
| 测试重写引入断言弱化（重蹈 B1"全绿但坏"） | 高 | 每个 B 缺陷的红测先行；像素/几何断言强制保留；review gate 检查断言强度 |
| 老预设含 svg/pdf 硬失败 | 中 | 归一化为 png + warning（§3），有专项测试 |
| 大图（4K）内存峰值变化 | 低 | 沿用"先释放大表再渲染"的编排；spike 含 4K 单图内存观测 |
| 视觉与 timedomain"看起来仍不一样" | 中 | §2.5 契约表逐项测试锁定 + Batch 6 真机对照截图验收（CLAUDE.md 验真机渲染 gotcha） |
| Heatmap 转置/extent 半格偏移 | 高 | row-major + QRectF coverage 合同；非对称 2×3 四角/坐标离屏对照 |
| 旧格式归一化导致 resume 误判 | 高 | requested provenance 与 canonical effective format 分离；只复用有效 PNG checksum |

## 8. 总验收标准

1. Batch 2/3/4 的 §2.7 离屏矩阵全部 PASS；实现 worker 与最终协调/主 agent 均已实际
   打开全部 contact sheet，最终协调/主 agent 已在待验收 commit 亲自重跑，报告逐 case
   有签字，4 种 kind 的 plot area 与对应单文件 plot 同等级，无漏线、转置、裁切、
   重叠或明显 AA 退化。
2. **在拆除 matplotlib 依赖与打包契约前**，GUI 真机（macOS）跑一次含
   overlay/subplot/双 Y/heatmap
   的批处理，产出 PNG
   曲线区与 timedomain 同数据截图肉眼一致（色轮/线宽/网格/字体），报告元素
   完整，8 面板可读，无 JSON/路径泄露。
3. 三个无 GUI CLI 入口全部可跑：冻结烟测 4 产物 ok=true；冻结验收 CSV+PNG
   全链路绿；时域分组验收含 `render_layout=subplot` 与 `x_source=channel`
   组合（补上 review 指出的验收矩阵缺口）。
4. `rg "matplotlib" mf4_analyzer/` 零运行时 import（注释和明确兼容命名除外）；
   requirements/打包无
   matplotlib；冻结包体积对比有记录。
5. `pytest -p no:randomly --ignore=tests/acquisition_ui -q` 没有出现 Batch 1 基线集合
   之外的新 failed nodeid；默认裸 pytest 的既有 SIGSEGV 若仍存在，单独标 `UNVERIFIED`。
6. B1–B4 四条红测转绿并保持在套件内。
7. Windows onedir 若尚未完成 offscreen + native-platform 双烟测，只能标记
   “源码实施完成 / Windows 发布 NO-GO”，不得把总验收写成完成。

## 附录 A：Spike 结论

**执行日期：** 2026-08-01

**工作树 commit：** `612bdd595bdfcecd41a7bedab1259f5c7f1d9383`

**证据目录：** `scratchpad/batch-qt-spike/`

**Evidence generated_at：** `2026-08-01T14:54:33.497934+00:00`
**Gate 0：** **PASS，放行 Batch 2**

### A.1 渲染与视觉证据

- 独立 `GraphicsLayoutWidget` 原型已覆盖 time 双 Y、time 8-panel subplot、FFT、
  非对称 2×3 heatmap，以及 white/transparent/dark 三主题；完整 batch PNG 为
  1920×1080，使用 `QImage + QPainter + QWidget.render`，曲线 item 显式 AA，禁用
  OpenGL。
- 同一 prepared payload 已分别送入原型与现有 `TimeDomainCanvasPG`、
  `PgLineCanvas`、`PgHeatmapCanvas`；crop 来自真实 `PlotItem.sceneBoundingRect()`，
  非固定坐标，也不是 whole-canvas grab。四张 parity contact sheet 及三主题/CJK 两张
  contact sheet 已由执行 agent 用 `view_image(detail="original")` 全部逐张打开，最终
  结果均 PASS；逐项签字在 `scratchpad/batch-qt-spike/visual-review.md`。
- heatmap 与真实 single-file 默认调用保持相同 `_SmoothImageItem` bilinear transform、
  `axisOrder="row-major"`、`QRectF(-0.5, 5.0, 3.0, 20.0)` coverage、turbo LUT 和
  `[0, 1]` levels；非对称矩阵目视与结构检查均无转置/翻转，colorbar 未裁切。
- FFT 两侧均保留 `Channel` legend；subplot 原型关闭 auto SI prefix，轴值/单位与
  reference 一致。batch 居中 panel title 与 single-file 左上内嵌 label 的差异属于
  Spec B3 已批准的报告层标题语义，不是导航或 Qt chrome。
- time 双 Y batch 不再手写更宽范围，而是在最终几何下先取 pyqtgraph auto-range
  padding，再复用现有 `_frame_to_nice` 10 分格语义。最终机器证据记录并断言
  batch/reference 的 X 均为 `[0,10]`、Acceleration Y 均为 `[-1,1]`、Speed Y 均为
  `[1320,1720]`；绝对容差 `1e-9` 下 X/Y 均相等。
- 每个原型 PlotItem 均关闭 auto-range button、context menu 和鼠标交互；宿主关闭
  frame、scrollbar、focus。三主题完整页未发现主界面导航、toolbar/status、默认按钮、
  菜单、焦点框或其他违禁 chrome。

### A.2 CJK、像素、DPI 与平台

- 本机解析 `PingFang SC`，`QRawFont.supportsCharacter` 对契约文本
  `单帧振动加速度` 七个字符全部为 true；标题/空标题对照区域差异为 3313 pixels，
  目视无 tofu 或空字形。
- offscreen 三主题完整 PNG 尺寸均精确为 1920×1080；144 DPI 回读为
  143.9926 DPI（PNG pHYs 舍入），`Case`/`Commit`/`Theme`/`Title` text metadata
  可回读。
- `QT_SCALE_FACTOR=2 + offscreen` 与 native `QT_QPA_PLATFORM=cocoa` 均实际运行在
  DPR 2，输出仍为精确 1920×1080、144 DPI。cocoa probe 使用
  `WA_DontShowOnScreen`；该证据证明 native platform 构建/渲染路径，不替代后续
  macOS 前台批处理验收。

### A.3 线程合同

- QThread worker 经 `BlockingQueuedConnection` 在 GUI thread 执行并回传结果：PASS。
- `ValueError("spike sentinel")` 类型、文案和 traceback note 跨线程回传：PASS。
- application-modal `QDialog` 打开时 worker render request 仍可达：PASS。
- app exiting 标志置位后以 `Qt application is exiting; render rejected` fail-fast：PASS。

### A.4 性能、heartbeat 与内存

计时范围固定为：**build/layout + 一次 `show/processEvents` + QImage render +
cleanup + lossless PNG encode**。初版原型重复调用一次 `processEvents()`，造成双 Y
p95 虚高；删除该重复布局/paint drain 并缓存不变的 commit SHA 后复测，不改变数据、
像素、分辨率、曲线 envelope 信息或 500 ms 预算。最终每类 20 次结果：

| 1920×1080 case | p50 | p95 | render p95 | PNG encode p95 | 预算 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| time 双 Y overlay | 389.76 ms | 435.08 ms | 340.77 ms | 99.00 ms | ≤500 ms | PASS |
| time 8-panel（每 panel 100k raw points，经 min/max envelope） | 230.54 ms | 240.60 ms | 175.86 ms | 68.76 ms | ≤500 ms | PASS |
| heatmap | 95.28 ms | 105.29 ms | 47.34 ms | 57.95 ms | ≤500 ms | PASS |

worker 连续请求 20 张 8-panel 图时，50 ms heartbeat 最大间隙为 **110.77 ms**，
超过 100 ms 次数为 **7**，低于 200 ms 预算。4K 单图含 PNG encode 的时间为：双 Y
1267.95 ms、8-panel 646.15 ms、heatmap 345.34 ms；同一进程 peak RSS 从
1,566,588,928 增至 1,835,581,440 bytes，观测峰值增量 **268,992,512 bytes**。

### A.5 放行边界

Gate 0 的机器断言与执行 agent 目视均通过，Batch 2 可按本 Spec 实施。该放行不覆盖：

- 最终协调/主 agent 在待验收 commit 上对四模块完整矩阵的独立重跑与目视签字；
- macOS 前台真实批处理操作中的主观卡顿验收；
- Windows onedir 的 offscreen/native 双平台冻结烟测。

这些项目继续由后续 Gate 4.5/6 控制，不得用本附录替代。
