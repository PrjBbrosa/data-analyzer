# MF4 Data Analyzer 当前架构评估报告

- 日期：2026-07-12
- 模式：只读架构审阅；未改动产品源码、测试或现有 WIP。
- 审阅快照：当前 `main` 工作区存在未提交的 dB-reference / 分析视图相关改动。本报告把它们视为正在演进的当前代码，不视为已发布基线。
- 验证范围：源码结构、状态/缓存/线程边界和现有测试组织；未运行 pytest、Qt 离屏探针或实机采集验证。

## 结论

**总体判断：PROCEED WITH INCREMENTAL GOVERNANCE。**

该仓库已经不是单一 PyQt 工具，而是具备导入、信号计算、批处理、项目持久化和实时采集子系统的桌面分析平台。核心方向是健康的：纯领域模块、版本化项目文件和采集状态机都已经出现，并且边界比典型的“所有逻辑塞进窗口类”清晰。

当前主要风险不是算法能力或功能缺失，而是分析编排正在集中到一个由多个 mixin 组成、依赖隐式 `self` 协作的协调层。继续按现有方式添加跨 FFT / FFT-vs-Time / Order 的功能，会增加缓存失效、视图恢复和信号连线的回归概率。建议治理，而不是重写。

## 当前架构快照

```text
PyQt shell
  MainWindow + mixins
    Toolbar / FileNavigator / ChartStack / Inspector
    project open-save / analysis routing / worker dispatch / UI signal wiring

Pure or mostly pure domain
  io + FileData          -> import normalization
  signal                -> FFT / spectrogram / order calculations
  db_reference          -> catalog + resolver + validation
  project_io            -> versioned .tlproj serialization
  acquisition_capture   -> capture session/config/transport

Specialized execution surfaces
  batch                 -> preset expansion + numeric run + export
  acquisition_ui        -> Cockpit Qt shell over a pure state machine
```

`MainWindow` 通过 `DropImportMixin`、`AnalysisMixin`、FFT / Order / FFT-vs-Time mixin、`ProjectIOMixin` 和 `ViewMixin` 组合能力（`mf4_analyzer/ui/main_window/window.py:64`）。它建立三栏主界面（`window.py:182`），并在 `_connect()` 中承接 toolbar、navigator、inspector 与 chart stack 的大量信号连线（`window.py:553`）。

## 已做得好的部分

### 1. 领域规则开始脱离 UI

`mf4_analyzer/db_reference.py` 明确声明为纯 dB-reference 域模块：不导入 PyQt，也不访问 QSettings，并可被 interactive UI 与 Batch 共用（`mf4_analyzer/db_reference.py:1`、`:5`）。对应的 `DbReferenceSettingsStore` 只负责版本化 QSettings 持久化，复用纯 resolver 的校验规则（`mf4_analyzer/ui/db_reference_settings.py:1`、`:4`）。

这是应该继续复制的模式：数值/业务规则放纯模块，Qt 控件仅负责收集输入、展示输出和触发动作。

### 2. 采集核心的状态边界清楚且可测试

Cockpit 状态机只接收预先计算好的健康 verdict，而不是直接依赖 Qt、Health 或 writer；它因此可在不 mock UI 或硬件的情况下单测（`mf4_analyzer/acquisition_ui/state.py:18`）。四态转换和非法转换保护都集中在该纯 Python 模块中（`state.py:37`、`:133`、`:199`）。

`SessionConfig` 也在进入 capture 前冻结输出路径、所选测量、后端和超时等输入（`mf4_analyzer/acquisition_capture/session.py:49`、`:74`）。这为真实硬件与 replay/fake 后端保留了可信的边界。

### 3. 项目文件有独立、版本化的持久化模型

`.tlproj` 的 serializer 不依赖 `MainWindow`，只保存文件引用、视图和分析视图状态，不保存已解析的原始数组（`mf4_analyzer/ui/project_io.py:1`、`:15`、`:39`）。这使项目文件更小，也让版本迁移和 round-trip 测试有明确落点。

### 4. 分析视图已经有明确的状态切换模型

`AnalysisMixin` 将分析视图描述为“capture → switch → apply → render”，并规定常规切换只从缓存渲染、不隐式重算（`mf4_analyzer/ui/main_window/_analysis_mixin.py:158`、`:168`、`:204`）。这是避免分屏/多 View UI 状态失控的重要基础。

## 主要发现与改进建议

### AR-01 · P1：MainWindow 已成为“分布式 God Object”

**证据。** `window.py` 本体约 2,967 行，另有约 4,300 行 main-window mixin。它不仅保有文件、线程、队列和 dB-reference store（`window.py:74`、`:90`、`:97`、`:123`），还同时构造 UI、绑定信号、切换视图、调度计算和恢复项目。跨三个分析区的 dB-reference 连接本身就需要在窗口层逐一接入（`window.py:601`、`:626`）。

**影响。** 一个跨分析区的新功能通常需要同时理解窗口字段、mixin 方法解析顺序、Inspector 控件、ChartStack 页面、缓存和 QTimer 信号。功能仍能交付，但修改范围变宽，测试也更依赖完整窗口构造。

**建议。** 引入一个不持有 QWidget 的 `AnalysisSession` / `AnalysisCoordinator`：

- 统一拥有 `files`、active file、analysis view managers、result caches 和 worker/queue 生命周期；
- 对 UI 暴露明确的命令和事件，例如 `request_analysis()`、`switch_analysis_view()`、`catalog_changed()`；
- `MainWindow` 保留 Qt signal-slot 适配、对话框和 toast，不再直接保存分析领域状态。

不要一次迁移全部模块。先以 FFT-vs-Time 为试点：它已经同时涉及队列、缓存、单/双 pane 和重渲染，是最能验证新边界的路径。

### AR-02 · P1：FFT-vs-Time 结果存在双缓存与双失效协议

**证据。** 通用 `AnalysisResultCache` 已用于三个分析区（`mf4_analyzer/ui/main_window/window.py:258`、`:263`）；但 FFT-vs-Time 同时保留自己的 `_fft_time_cache` 和独立 key 构造（`mf4_analyzer/ui/main_window/_fft_time_mixin.py:90`、`:116`）。worker 完成后，同一个 result 会写入两套缓存（`_fft_time_mixin.py:780`、`:783`）；关闭全部文件时也必须分别 clear legacy cache 与 per-section caches（`mf4_analyzer/ui/main_window/_project_io_mixin.py:779`、`:782`）。

**影响。** 当前代码已经认真处理失效，但两个实现会让未来新增参数、按 file 失效、强制重算或恢复项目时有“只改到一边”的风险；同时会保存同一结果的两份引用。

**建议。** 以 `AnalysisResultCache` 为唯一计算结果库，统一所有 section 的 key/invalidate/get/put；保留独立的 render signature，但它只能决定“是否重绘”，不能再保存第二份计算结果。dB reference 继续保持 render-only，不进入 compute key——当前实现已经正确遵守这一点（`_fft_time_mixin.py:55`、`:57`）。

### AR-03 · P2：分析 View 的所有权是可运行的折中，但语义不够单一

**证据。** `ChartStack` 创建并持有三个 `ViewManager`，理由是 `ViewTabBar` 构造时需要它们（`mf4_analyzer/ui/chart_stack/stack.py:118`、`:127`）；而 `MainWindow` 又以 `self.analysis_managers = self.chart_stack.analysis_managers` 取得别名、持有缓存并连接所有路由（`window.py:258`、`:262`、`:693`）。

**影响。** 实际对象只有一份，但“ChartStack 是 owner、MainWindow 负责路由/compute”的约定主要存在于注释。以后新增另一种视图状态或导出状态时，容易再次出现“控件层创建、窗口层变更、mixin 层恢复”的三方协作。

**建议。** 把 `ViewManager` 的领域所有权迁到 `AnalysisSession`，以构造参数注入 `ChartStack` 和 `ViewTabBar`。如果短期不迁移，至少建立一个明确的 `AnalysisViewRegistry`，禁止新的代码直接从任意 widget 取得/修改 manager。

### AR-04 · P2：BatchRunner 的“GUI-free”契约被图片导出路径稀释

**证据。** 模块开头明确说明 runner 只应依赖 `FileData` 和 signal modules（`mf4_analyzer/batch.py:1`、`:8`）。但图片导出仍由 `BatchRunner` 内部创建 offscreen `QApplication`（`batch.py:978`），再创建 PyQtGraph 场景（`batch.py:1013`、`:1030`）。

**影响。** 对桌面批处理而言它可工作，但批量数值计算的可复用性受 Qt 运行时约束；CLI、CI 或未来服务端只要需要 PNG，就会被迫携带 Qt。

**建议。** 抽出 `BatchImageExporter` 适配器：`BatchRunner` 只生成结构化绘图 payload / DataFrame，桌面应用注入 PyQtGraph exporter；无 GUI 环境可以选择 Matplotlib、Plotly 或完全跳过图片。这样“数值 run”和“图片呈现”分别测试、分别部署。

## 优化后的预期收益

| 优化 | 用户侧收益 | 工程侧收益 |
| --- | --- | --- |
| 单一分析缓存与 job 生命周期 | 更少旧图、重复计算、切换后状态错位 | 失效规则有唯一入口，降低回归面 |
| `AnalysisSession/Coordinator` | 项目恢复、分屏和分析切换更稳定 | 新分析功能不再同时修改 MainWindow、多份 mixin 和 UI 控件 |
| 单一 View ownership | 视图行为更可预测 | 状态恢复与导出有清晰依赖方向 |
| Batch export adapter | 批量任务在无界面环境更可靠 | 可单测、可替换、可用于 CLI/自动化 |

这些优化不会让单次 FFT 的数学算法自动变快；直接收益是减少不必要的重算、重复结果驻留和跨层状态同步。长期收益是显著降低后续功能的修改成本与回归概率。

## 推荐演进顺序

1. **先统一缓存和 worker/job 生命周期。** 保留现有 UI，清除 FFT-vs-Time 的 legacy result cache；用测试固定“display-only 改动不重算、compute-input 改动必失效”。
2. **建立 `AnalysisSession` 并迁 FFT-vs-Time。** 仅迁一个 section，验证项目恢复、分屏、取消和缓存命中四条路径。
3. **迁 Order 与 FFT，并收紧 View ownership。** 此时消除 `ChartStack` / `MainWindow` 的 manager 别名关系。
4. **拆 Batch 图片导出。** 先定义 payload 和 exporter 协议，再迁 PyQtGraph 实现；不改变现有导出视觉结果。
5. **最后评估项目序列化 DTO 的加强。** 当前 schema 已经可用；只在需要更复杂迁移或跨版本兼容时，把 `views` / `analysis_views` 的自由 dict 收紧为更强类型的 DTO。

## 2026-07-13 Phase 1 disposition

本报告的 AR-01 / AR-02 已由
`docs/analyzer/specs/2026-07-13-analysis-orchestration-governance-spec.md`
收敛并实施为「统一 FFT-vs-Time 结果库 → `AnalysisJobService` →
`FftTimeCoordinator` 试点」。这里记录两项经复核后的边界，避免把本报告的原始
建议误当作本轮待做项：

- **AR-03（View ownership）延期至 Phase 2。** `ChartStack` / `MainWindow` 的
  `ViewManager` 构造时序与导航、项目 IO 深度耦合；本轮没有迁移所有权，也没有
  引入 `AnalysisSession` 状态桶。后续 Order / 普通 FFT coordinator 迁移时再与该
  所有权问题一并立项。
- **AR-04（Batch 图片导出）降级为非目标。** 核实后发现 Qt 图片导出已封装在
  `BatchRunner` 的可选 `export_image` 路径内，当前没有 CLI、CI 或服务端消费者；
  数值批处理路径与纯数值测试不依赖该路径。因此本轮不抽 `BatchImageExporter`，待
  headless 图片导出需求真实出现时再按该接口方向实施。

## 非目标与验证边界

- 本报告不建议大规模重写 UI，也不建议废弃 PyQt/mixin 机制；问题是状态与执行所有权，不是框架选择本身。
- 本报告没有执行测试，因此不声明当前 WIP 的行为已绿；结论仅说明架构方向、依赖关系和演进风险。
- 未进行 Qt 截图、性能 profile、真实 Vector/XCP 或 ECU 验证；这些需要独立的验证计划与证据。

## 最终建议

保持当前“纯领域模块 + 薄 UI 适配”的方向；将下一阶段定义为**分析编排治理**，而不是再叠加一轮功能。最小、最有价值的第一步是让 FFT-vs-Time 只使用一套结果缓存，并由一个显式 coordinator 管理其 worker 与 view state。
