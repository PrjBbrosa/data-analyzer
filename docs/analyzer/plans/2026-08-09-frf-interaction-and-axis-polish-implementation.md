# FRF 交互、提示与坐标轴精修实施计划

日期：2026-08-09

状态：**Implemented；2026-08-09 已按后续确认扩展为 FRF/频谱双游标与 minor grid**

Follow-up to：

- `docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`
- `docs/analyzer/plans/2026-08-09-frf-post-implementation-review-and-optimization.md`

本计划承接上一份 review 计划已经完成的 O1–O5，不改写其历史记录；新增范围来自
2026-08-09 前景界面复核：参数解释不足、FRF 游标缺少显式开关、FRF 网格偏淡，
以及 log 频率轴缺少未标数字的小刻度。

## 1. 目标与验收结果

本轮只做五项产品精修：

1. H1/H2 不再只显示缩写；为 FRF Inspector 中所有需要专业知识才能正确理解的控件
   补齐 tooltip，文案有一个集中来源；
2. FRF 与频谱均采用时域同款 `游标关 / 单游标 / 双游标` 控件，默认关闭；双游标按 A、B
   两次点击，读取两点与 `Δf`，关闭时不再出现指针线或残留读数；
3. 明确显示“系统延迟始终保留，不做补偿”，但不伪装成可切换开关；
4. FRF 三行图主网格透明度由 `0.12` 统一为时域使用的 `0.28`；
5. log X 轴在 1–100 Hz 等跨十进位范围把 2–9、20–90 画为无标签的纵向次网格，并与
   幅值、相位、相干性三张图对齐。

完成判据不是“QSS/属性值已改”，而是：focused tests 通过，真实 macOS 前景 TraceLab
中能看到按钮状态、网格对比和小刻度，且关闭游标时没有竖线或残留读数。

## 2. 已确认的当前事实

| 项目 | 当前实现事实 | 用户可见影响 |
| --- | --- | --- |
| Tooltip | `contextual_frf.py` 的 FRF 专属控件目前只有“交换输入/输出”按钮有 tooltip；H1/H2、分段、NFFT、相位、相干阈值等没有 | 专业参数只能猜含义或另开帮助页 |
| H1/H2 | 下拉项仅为 `H1`、`H2` | 无法从选择项判断输出噪声/输入噪声假设 |
| 系统延迟 | spec 明确首版始终保留真实系统延迟，不提供延迟移除；Inspector 没有稳定的可见说明 | 容易误以为相位展开等于去延迟，或期待一个可关闭开关 |
| 游标 | 旧实现只有 FRF 单一游标开关，频谱没有同等入口 | 频率读数交互与时域不一致，无法双点比较 |
| 网格 | `FrfStackedPlotHost` 调用 `show_major_grid_left_bottom_only(..., alpha=0.12)`；时域使用 `0.28` | FRF 灰底网格明显更淡 |
| log X 刻度 | 旧实现将显式 minor tick 压成轴边短线 | 1–100 Hz 中 2–9 的位置难以对应上方频谱 |
| pyqtgraph 行为 | `AxisItem.generateDrawSpecs()` 在 grid 打开时会把每一级 tick 都拉到 linked view 边界 | 该行为现在正用于三张 FRF 图对齐的 minor grid |

## 3. 已定产品决策

### D1 — Tooltip 覆盖原则

只给“可能误用、缩写、会影响数值解释”的控件补充说明；已有完整 hover card 的三个
预设按钮、已有 tooltip 的交换按钮、通用导航按钮不重复造第二套文案。

FRF tooltip 文案集中放在 `contextual_frf.py` 的只读映射/小 helper 中；组合框的每个
选项使用 `Qt.ToolTipRole`，折叠状态的组合框 tooltip 随当前选项同步，避免“弹出项有
解释，但当前值悬停仍无解释”。不改全局 glass tooltip 生命周期实现。

| 控件 | Tooltip 必须讲清楚的内容 |
| --- | --- |
| 输入 x | 激励输入；必须与输出属于同一逻辑来源并共享真实时间轴 |
| 输出 y | 系统响应；FRF 表示输出相对输入的传递特性 |
| 交换输入/输出 | 交换会改变传递方向和结果含义；保留现有 tooltip 并补足方向说明 |
| 分析范围 | 全范围、当前时域快照、手动秒数三种语义；“当前”是快照，不随时域继续联动 |
| H1 | `H1 = Pxy / Pxx`；适合输出侧测量噪声占主导；默认 |
| H2 | `H2 = Pyy / conj(Pxy)`；适合输入侧测量噪声占主导；需明确选择 |
| 窗函数 | 窗函数控制泄漏与主瓣宽度；各窗口项给出简短取舍，不声称改变物理分辨率 |
| 周期窗 | 使用 FFT 周期窗语义，避免重复对称窗端点；不等于“信号必须周期” |
| 段长 | 越长频率分辨率越细，但同一时长内可平均段数更少 |
| 重叠率 | 增加分段密度与计算量，不等于增加同等数量的独立信息 |
| NFFT 模式/NFFT | 自动按段长；手动不得小于段长；零填充只加密频率采样，不提升物理分辨率 |
| 每段去均值 | 每段减均值以抑制 DC 泄漏；不是线性去趋势 |
| 幅值 dB/线性 | dB 为传递比的 `20 log10(|H|)`，不是带绝对 reference 的工程量 dB |
| 频率轴 log/线性 | log 仅在显示层隐藏 DC；不删除原始结果或导出数据 |
| 相位展开/±180° | 展开仅移除 360° 跳变；两种模式都保留真实系统延迟 |
| 相干阈值 | 只控制可信度提示/淡化；不删数据、不改变 FRF 计算 |
| 低相干淡化 | 显示开关；关闭只取消视觉淡化，不重新计算 |
| 计算频响 | 按当前 pane 的输入/输出、范围和参数重算；不足两个完整段时明确阻断 |
| 在时域查看 | 复用或创建对应输入/输出与范围的独立时域 View |
| 新增游标按钮 | 开启后在三图同步读取四项数值；关闭后不显示竖线和读数 |

H1/H2 下拉可见项改为 `H1（输出噪声）`、`H2（输入噪声）`，但保存值和计算参数仍为
稳定 token `h1` / `h2`，不以显示文案作为身份或枚举值。实施时必须在真实 Inspector
宽度下验证下拉项不截断；若闭合框空间不足，闭合框保留 `H1`/`H2`，完整含义仍在
选项 tooltip 与旁侧帮助中，不能靠压缩字体解决。

### D2 — “保留系统延迟”是状态说明，不是开关

在相位控制附近增加一条紧凑、不可交互的说明：

> 系统延迟：保留（不补偿）

其 tooltip 说明纯延迟会形成随频率下降的线性相位项，`unwrap` 只展开相位，不会移除
这段斜率。不得增加 checkbox/switch，也不得新增延迟拟合、估计或补偿算法。

### D3 — 频率游标沿用时域三态，默认关闭，按 pane 保存

- FRF 与频谱使用时域同款“关/单/双”三按钮。FRF 让三图联动；频谱在 amplitude 图放置
  单/双频率游标；
- 默认 `False`。关闭状态不处理 mouse-move，不显示三根竖线，不显示 CursorPill，
  并清空旧读数；开启后才允许三行同步移动；
- 状态归属于 `AnalysisViewState.PaneState`，新增字段
  `cursor_mode: "off" | "single" | "dual" = "off"`，按 View/pane 序列化。旧的
  `frf_cursor_enabled=True` 迁移为 `single`，其余安全回落为关闭；
- 分屏时共享工具栏按钮始终操作当前 focused pane，切换焦点时 checked 状态随目标 pane
  刷新；不得把这个状态写进多个 MainWindow mixin；
- 复制图片是否包含游标沿用既有“复制当前可见画面”语义：开启并已有读数时包含，关闭时
  不包含。

此字段是可复现的用户交互意图，与时域 `cursor_mode` 同类，不是瞬时诊断缓存；因此允许
进入项目状态。嵌套 schema 升到 5，`from_dict()` 仍兼容旧字段。

### D4 — FRF 主网格统一为 0.28

只改 FRF 三行图的初始主网格 alpha：`0.12 → 0.28`。不改 FFT、时频、阶次、Batch
通用图表的既有 0.25，也不把 0.28 抽成误导性的全局统一常量。右键恢复/重设网格路径
必须继续得到 0.28，避免首帧和交互后视觉跳变。

### D5 — log X minor grid 的精确定义

- 跨完整十进位时，在每个 decade 的 `2…9 × 10^n` 处画纵向 minor grid；例如 1–100 Hz
  出现 2–9 和 20–90；
- 主刻度/主标签仍由现有 `log_frequency_tick_levels()` 决定，不改已修复的 20–80 Hz
  窄带标签降级规则；
- 小刻度无文字、不得覆盖主刻度坐标；三张 FRF 图的 linked view 都画同一组位置，使其
  与上方频谱位置直接对齐；
- minor grid 贯穿各自 FRF plot 的画布高度，主/次网格均使用其既有透明度层级；
- linear 频率轴不使用这套 log 小刻度；
- GUI 与 Batch FRF 图片复用同一个 UI-neutral minor tick 纯函数，防止预览/导出分叉。

## 4. 实施任务（测试先行）

### Task 0 — 保护当前在途工作区

1. 记录 `git status --short` 和相关文件 diff；当前工作区已经有用户/前序 FRF 修改，
   不 reset、不 checkout 覆盖；
2. 重读本计划涉及文件的当前版本，按现状叠加最小 patch；
3. 先加能复现当前缺口的 focused RED tests，再改实现。

### Task 1 — Tooltip 与系统延迟说明

**Modify**

- `mf4_analyzer/ui/inspector_sections/contextual_frf.py`
- `mf4_analyzer/ui_kit/style.qss`（仅当静态延迟状态行需要已有 token 无法表达的样式）
- `tests/ui/test_inspector.py`

**RED**

- H1/H2 两项显示 token 与计算 token 分离，item tooltip 含正确公式及噪声假设；
- D1 表中所有控件的 `toolTip()` 非空，NFFT/窗口等 combo 当前项切换后 tooltip 同步；
- 延迟状态行可见、不可点击，文案包含“保留/不补偿”；展开和 ±180° tooltip 都明确
  不移除系统延迟；
- 预设 hover card 仍是原实现，不被标准 tooltip 覆盖。

**GREEN**

- 新增集中 tooltip map 与 combo item helper；
- 只调整展示文案和帮助信息，不改变 emitted params、默认值、validation 或计算请求。

### Task 2 — FRF/频谱游标、画布 gate 与 per-pane 状态

**Modify**

- `mf4_analyzer/ui/chart_stack/cards.py`：以复用的 `FrequencyCursorCard` 为 FRF/频谱提供
  时域同款游标关/单/双按钮；
- `mf4_analyzer/ui/chart_stack/stack.py`：FRF/FFT card factory、CursorPill 可见条件与 focused
  canvas 路由；
- `mf4_analyzer/ui/pg_canvas/frf_canvas.py` 与 `line_canvas.py`：`set_cursor_mode()`、关闭时
  清理、single hover 与 dual A/B click gate；
- `mf4_analyzer/ui/analysis_view_state.py`：`PaneState.cursor_mode` 与 schema-4 bool 兼容迁移；
- `mf4_analyzer/ui/analysis_section_page.py` 及既有 analysis view bridge：focus/View/pane
  切换时读取与回写单一 owner；
- 不在 `MainWindow` 新增跨文件状态写入；若现有 bridge 已能泛化，则只扩 bridge。

**RED**

- 新 canvas 默认关闭：所有 line 均隐藏，mouse move 不发 `cursor_info`；
- 单游标 hover 或点击显示一个频率；双游标依次放置 A、B，输出 `fA/fB/Δf` 与所有对应读数；
- 关闭会隐藏 single/A/B line、清空 pill，后续移动不复活；
- 单 pane、split 两 pane 切换焦点时按钮操作/checked 状态对应正确 pane；
- View A 开、View B 关，往返切换不串状态；project round-trip 保留新字段，旧 schema
  缺字段默认为关；
- FRF/频谱 pill 只在非 off 游标收到非空读数时显示，时域单/双游标行为无回归。

**Target tests**

- `tests/ui/test_frf_canvas.py`
- `tests/ui/test_analysis_section_page.py`
- `tests/ui/test_analysis_view_state.py`
- `tests/ui/test_analysis_view_bridge.py`
- `tests/test_project_io_analysis_views.py`
- 现有 ChartStack/cursor pill 相关用例

### Task 3 — 0.28 主网格与 log X 小刻度

**Modify**

- `mf4_analyzer/ui/pg_canvas/frf_plot_host.py`：FRF 初始主网格 alpha 改为 0.28；
- `mf4_analyzer/ui/pg_canvas/qt_plot_helpers.py`：保留 explicit log tick levels，不再把 minor
  draw specs 缩短为轴边线；
- `mf4_analyzer/ui/pg_canvas/analysis_axes.py`：FRF axis 不覆盖 pyqtgraph 的 minor-grid draw
  行为；
- `mf4_analyzer/ui/pg_canvas/frf_canvas.py`：为三张图同时设置相同 major/minor positions；
- `tests/test_render_profile.py`、`tests/ui/test_frf_canvas.py`、
  `tests/test_batch_render_qt_frf.py`。

**实现约束**

pyqtgraph grid 模式会把所有 tick level 画成全高线。这里明确利用该行为：FRF 三张图均
设置相同的 explicit `[major, minor]` levels，从而形成可与上方频谱对应的对齐纵向网格。
仍以 `AxisItem.generateDrawSpecs()` 的 deterministic probe 锁定主/次位置和 full-height
span，避免按 pen alpha 猜 level。

**RED**

- 纯函数在 1–100 Hz 返回 16 个 minor positions：2…9、20…90；不含 1/10/100；
- 20–80 Hz 保留现有主标签，minor 与主坐标去重并裁到 view range；
- 非有限、空/倒置范围返回空；linear 模式恢复自动 ticks；
- 三张 FRF plot 均存在相同第二级 tick level；
- `generateDrawSpecs()` 中 minor 与 major 都跨各自 linked view，物理位置一致；
- 主网格 alpha 为 0.28，minor 形成对齐纵向网格；

### Task 4 — 用户帮助与交互合同同步

**Modify**

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `mf4_analyzer/help/frf-guide.html`
- `docs/analyzer/specs/2026-08-08-system-identification-frf-and-batch-spec.md`

同步内容：

- FRF 游标默认关闭、由工具栏按钮开启、三图共享一根频率游标；
- H1/H2 的噪声假设与公式；
- 相位展开不等于去延迟，系统延迟始终保留；
- 低相干淡化只影响显示；
- log X 轴有无标签的小刻度，仍只有主刻度网格。

删除 `hints.py` 中“冻结交互且不增加控件”的过时注释。提示/QuickRef 文案尽量复用
同一语义常量或测试互相校验，避免 toolbar、tooltip、QuickRef 三处以后漂移。

**Target tests**

- `tests/ui/test_hints.py`
- `tests/ui/test_quickref.py`
- `tests/ui/test_quickref_status_hints.py`
- `tests/ui/test_glass_tooltip.py`（只跑既有生命周期回归，不修改实现）

## 5. 验证顺序

### 5.1 Focused / owner tests

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_render_profile.py \
  tests/ui/test_frf_canvas.py \
  tests/ui/test_inspector.py \
  tests/ui/test_analysis_section_page.py \
  tests/ui/test_analysis_view_state.py \
  tests/ui/test_analysis_view_bridge.py \
  tests/test_project_io_analysis_views.py \
  tests/test_batch_render_qt_frf.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/ui/test_quickref_status_hints.py \
  tests/ui/test_glass_tooltip.py
```

再跑 FRF 编排/主窗口回归，确认展示改动没有污染数值参数或计算生命周期：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/test_frf.py \
  tests/ui/test_frf_coordinator.py \
  tests/ui/test_frf_main_window.py
```

### 5.2 架构 gates

至少运行：

```text
tests/ui/test_pg_canvas_backref_invariants.py
tests/ui/test_import_boundaries.py
tests/test_signal_no_gui_import.py
tests/test_batch_render_import_boundary.py
tests/test_packaging_imports.py
tests/ui/test_main_window_state_ownership.py
```

`render_profile.py` 必须保持 UI-neutral；新增游标状态不得扩大 MainWindow ownership
白名单。最后运行 `git diff --check`。

### 5.3 真实前景视觉验收（不能用 offscreen 代替）

用当前真实 FRF 数据打开 macOS 前景 TraceLab，并保存一组确定性截图/裁图证据：

1. **默认态**：`游标关` 选中，三图无竖线、无读数 pill；
2. **单游标**：悬停 10 Hz 左右，三根竖线同频，pill 同时显示四项读数；**双游标**：
   依次点 A、B，显示两个频点与 `Δf`；切回关闭后全部立即消失；
3. **minor grid**：log X=1–100 Hz，肉眼及像素裁图可见 2–9、20–90 的纵向网格，三张
   图的物理位置对齐；
4. **网格**：FRF 与时域均走 alpha=0.28；对同主题背景做网格/背景像素差比较，避免
   只证明源码常量相同却仍然观感不同；
5. **Inspector**：H1/H2 下拉不截断；抽查 H1、H2、NFFT、相位、相干阈值 tooltip；
   `系统延迟：保留（不补偿）` 清楚可见且不可切换；
6. **分屏/View**：两个 pane 分别选择不同游标模式，切焦点和切 View 后按钮状态不串；
   频谱也出现同款三态控件并读出 `Δf`。

Batch 另生成一张 1–100 Hz log FRF PNG，与 GUI 自动裁图比较 major/minor X positions；
不能要求人工逐张检查。

## 6. 明确不做

- 不改 H1/H2、coherence、窗函数或分段的数值算法；
- 不实现系统延迟估计、自动拟合、移除或补偿；
- 不新增峰值追踪、十字横线或自由拖拽游标；双游标仅为 A/B 两次点击的频率读数；
- 不新增 minor tick 标签；minor grid 仅用于对齐的 FRF log X；
- 不把所有分析模式的网格统一改成 0.28；
- 不重构通用 ChartStack/AxisItem，只增加 FRF 所需的最窄能力；
- 不把 tooltip 文案变成参数身份或持久化值；
- 不把 offscreen 绿测描述成 macOS 前景或 Windows frozen 验收完成。

## 7. 建议提交切分

1. `test/fix(frf): add log minor ticks and align grid contrast`
2. `feat(frf): add explicit per-pane cursor control`
3. `docs/ui(frf): clarify estimators, parameters, and retained delay`

实施时可按真实文件重叠调整，但每个提交都必须保持可运行，且不得带入当前工作区中与
本计划无关的修改。Windows frozen acceptance 与上一份计划的 O6 一样保持独立 gate；
本轮若未实际执行，最终状态必须写 `UNVERIFIED`，不能推断通过。
