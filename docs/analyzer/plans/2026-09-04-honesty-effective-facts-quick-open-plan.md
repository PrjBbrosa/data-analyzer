# 诚实性批次 · 有效事实推广 · 快速打开 实施计划

- 日期：2026-09-04
- 状态：IMPLEMENTED（2026-09-04 合入 `main`；Cocoa 前台 C5 / A4 五色与升版仍待）
- 基线：`56862a12`（worktree 另有与本计划无关的 tracked 删除 / untracked 文件，见 §1）
- 来源：2026-09-04 Codex 只读 review 的 P0 #1/#2/#3、P1 #7、P2「红点语义」，
  外加用户提出的「打开」旁最近文件 / 项目下拉。三者独立成批，可分别验收。
- 版本：本计划**不升版本**。三批合入后按 `CLAUDE.md` 扇出面统一升版，
  `help/TraceLab-使用说明.html` 的 changelog 条目届时一起补。

## 0. 目标与边界

三批的共同合同（借 DBC 候选匹配的既有范式）：

> 输入事实 → 候选结果 → 置信度与理由 → 用户确认 → 实际参数与来源记录

| 批次 | 要修的问题 | 一句话目标 |
| --- | --- | --- |
| A 诚实性 | 三个「名为智能、实际无输入」的功能 + 红点误报 | 软件不再对外承诺它没做的事 |
| B 有效事实 | FFT / 时频 / 阶次只显示 `自动(N)`，请求值≠实际值时用户不知道 | 四个分析分区都像 FRF 一样显示「实际生效参数」 |
| C 快速打开 | 每次都走文件对话框；没有任何 MRU | 「打开」旁加下拉，列最近项目和文件 |

明确不做（留给后续批次，不在本计划验收）：

- 预设推荐不扩展到「通道名角色 / 采样率 / 信号特征」，不改「频率 / 均衡 / 时间」的命名；
- UltraView 不新增「设为主卡 / 次卡」显式交互；
- 时间轴重建**不做**「派生分析副本」，不保留原 `time_array` 数组本体（只留统计量）；
- provenance **不写进导出图片**（属于「复制证据卡」批次）；
- 不改任何 AA / ink / 光栅准入阈值，红点只改状态语义与颜色，不改决策；
- 数据健康摘要只做 NaN / 常值 / 时间抖动 / 多源 Fs 冲突，不做削顶检测；
- 快速打开不做「最近通道组合」「为这组文件建立对比」等动作型入口，不加快捷键。

## 1. Worktree 保护与文件 owner

当前 worktree 有与本任务无关的 tracked 删除（`assets/icons/tracelab.icns`、
`assets/wwt/*.wwt`、两张 `docs/reports/*.png`）和 untracked 文件（`code_stats_report.html`、
`ssh-keygen`），以及一批 help / 打包脚本改动。实施者**不得**还原、删除、格式化或提交这些改动；
提交只包含本计划各 Task 列出的文件。

各批允许触碰的文件（超出即停线说明原因）：

| 批 | 生产代码 | 测试 | 文档 |
| --- | --- | --- | --- |
| A1 | `analysis_presets.py` · `ui/inspector_sections/_helpers.py` · `ui/inspector_sections/presets.py`（仅 tooltip） | `tests/test_analysis_presets.py` · `tests/ui/test_inspector.py` · `tests/ui/test_main_window_smoke.py` | `help/TraceLab-使用说明.html` |
| A2 | `ultraview_core/smart_layout.py` | `tests/test_ultraview_smart_layout.py` · `tests/ui/test_ultraview_free_grid.py` · `tests/ui/test_ultraview_smart_layout_integration.py` | — |
| A3 | `io/file_data.py` · `ui/project_io.py` · `ui/main_window/_project_io_mixin.py` · `ui/main_window/window.py`（`_check_uniform_or_prompt` 与 popover Accept 两处） · `ui/main_window/_frf_mixin.py` · `ui/chart_stack/cards.py` · `ui/chart_stack/toolbar.py`（如芯片放头部） · `ui_kit/style.qss` · `batch_compute.py` · `batch_manifest.py` | `tests/test_file_data_time_axis.py`（新） · `tests/ui/test_project_session.py` · `tests/ui/test_main_window_smoke.py` · `tests/ui/test_cursor_pill_formatting.py` 或新建 `tests/ui/test_card_provenance_chip.py` · `tests/test_batch_compute_time_axis.py` · `tests/test_batch_manifest.py` | — |
| A4 | `ui/pg_canvas/quality.py` · `ui/pg_canvas/line_canvas.py` · `ui/pg_canvas/frf_canvas.py` · `ui/chart_stack/cursor_pill.py`（`_QualityStatusIndicator`） | `tests/ui/test_pg_timedomain_canvas.py` · `tests/ui/test_pg_line_canvas.py` · `tests/ui/test_frf_canvas.py` · `tests/ui/test_pg_dense_raster.py` | `help/*-guide.html` 若有红点说明 |
| B | `signal/fft.py` · `signal/spectrogram.py` · `signal/order.py`（各加 facts DTO） · `ui/inspector_sections/_effective_facts.py`（新） · `contextual_fft.py` · `contextual_fft_time.py` · `contextual_order.py` · `contextual_frf.py`（改为复用共享格式器） · `ui/main_window/_fft_mixin.py` · `_fft_time_mixin.py` · `_analysis_mixin.py` · `batch_compute.py` | `tests/signal/test_*_effective_facts.py`（新） · `tests/ui/test_inspector.py` · `tests/test_effective_facts_parity.py`（新） | 四个分析指南 · `ui/quickref.py` |
| C | `ui/recent_files.py`（新） · `ui/toolbar.py` · `ui_kit/style.qss` · `ui/main_window/window.py` · `ui/main_window/_project_io_mixin.py` · `ui/hints.py` · `ui/quickref.py` | `tests/ui/test_recent_files_store.py`（新） · `tests/ui/test_toolbar.py` · `tests/ui/test_open_and_save_entry.py` · `tests/ui/test_quickref.py` · `tests/ui/test_hints.py` | `help/TraceLab-使用说明.html` |

推荐执行顺序：A1、A2、A4、C 四者文件互不相交，可并行；**A3 先于 B**（B 的「时间抖动」
健康行读 A3 的 provenance），二者都碰 `_fft_mixin.py` / 各 contextual section，串行执行。

---

## 2. 批次 A —— 诚实性

### A1 智能预设：未知单位不再推荐

现状：`analysis_presets.py:296-303` `recommend_builtin_preset` 对未知单位兜底返回
`"vibration"`；`tests/test_analysis_presets.py:256-270` 把 `kg` / `None` → `vibration`
钉成了合同；`help/TraceLab-使用说明.html:428-437` 写的是「按单位自动推荐」。唯一生产调用点
是 `ui/inspector_sections/_helpers.py:81-89 recommend_preset_for_unit`，下游
`PresetBar.set_recommended(slot)`（`presets.py:689-704`）已经支持 `slot=None` 清空徽标。

步骤：

1. `recommend_builtin_preset` 返回类型改 `str | None`：命中 `_TORQUE_UNITS` → `"torque"`，
   命中 `_VIBRATION_UNITS` → `"vibration"`，**其他一律 `None`**。docstring 与
   `recommend_preset_for_unit` docstring 同步（删掉「fall back to vibration」）。
2. 三个 `set_recommended_for_unit`（`contextual_fft.py:572-581` ·
   `contextual_order.py:511-517` · `contextual_fft_time.py:965-971`）确认 `None` 路径走
   `preset_bar.set_recommended(None)`，不再取默认槽位。
3. 「依据」可见化：`PresetBar._refresh_states` 在 `recommended` 为真的按钮 tooltip 末尾追加
   一行 `按单位「{unit}」推荐`。需要 `set_recommended(slot, *, unit=None)` 多带一个展示用参数；
   徽标本身仍无鼠标事件，不加 tooltip。
4. 帮助文案改为：「仅当通道单位可识别（N·m / Nm 系列 → 扭矩；g / m/s² 系列 → 振动）时显示
   「荐」徽标；单位缺失或不可识别时不做推荐，请按分析目的手动选择。」

测试合同（先红后绿）：

- `tests/test_analysis_presets.py`：`kg`、`""`、`None`、`bar` → `None`；已有扭矩 / 振动别名用例不变。
- `tests/ui/test_inspector.py:6053-6120`：未知单位 → 徽标全部隐藏、所有按钮 `recommended="false"`；
  可识别单位 → 对应按钮 tooltip 含「按单位」。
- `tests/ui/test_main_window_smoke.py:954+`：从 `N·m` 通道切到无单位通道，徽标消失。
- `tests/test_help_content.py`：若它钉了 428 行附近文案，随文案更新。

停线条件：发现除 `_helpers.recommend_preset_for_unit` 之外还有调用者依赖非 `None` 返回值。

### A2 UltraView「保留主次」：从当前面积生成 salience 快照

现状：`SmartCardFact.source_salience`（`smart_layout.py:75`）全仓只有 4 处引用，全部在核心内部；
`smart_layout_facts_from_placements`（`:313-404`）在没有 `prior` 时写 `None`，而 UI 入口
`free_grid.py:954-990 plan_smart_layout` **从不传 `prior_facts`**。所以 `_card_target_area`
（`:923-936`）的 `preserve_salience` 分支在生产中永远拿到 `None`，退化为 `balanced`。
测试用 `_compressed_salience(area, median)`（`tests/test_ultraview_smart_layout.py:101-103`）
手工补了这个缺口。

步骤：

1. 把测试里的压缩公式提升为核心公开纯函数
   `salience_from_area(area: float, median_area: float) -> float`
   （`exp(0.35·ln(area/median))`，clamp 到 `[0.75, PRESERVE_AREA_RATIO]`；`median_area<=0`
   或非有限 → `1.0`）。测试改为 import 它，删掉本地副本。
2. `smart_layout_facts_from_placements`：`prior is None` 时
   `salience = salience_from_area(rect.width*rect.height, median_of_all_current_rects)`；
   中位数取全部 placements（含锁定卡）的当前面积；单卡 → `1.0`。`prior` 存在时维持沿用
   `prior.source_salience`（不变）。
3. `canonicalize_smart_card_facts` 与 `_Work` 不改；确认 `_ratio_cap("preserve_salience")`
   = `PRESERVE_AREA_RATIO` 仍是唯一放大上限。

测试合同：

- `test_preserve_salience_snapshot_keeps_dominant_card_larger`：Codex 的复现输入
  （12×12 主卡 + 两张小卡，同一 `layout_revision`），`preserve_salience` 结果中主卡面积
  **严格大于**任一小卡；`balanced` 结果三卡面积相等或差值 ≤ 1 格；两模式结果不相同。
- `test_facts_from_placements_stamps_salience_without_prior`：无 `prior_facts` 时所有
  `source_salience` 非 `None`、在 `[0.75, 1.80]` 内、面积中位卡为 `1.0`。
- `test_salience_from_area_is_monotonic_and_clamped`。
- 既有 `preserve_salience` 参数化（`:545`）、budget（`:584-602`）、topology、fixed-point 用例不回归。

停线条件：加了 salience 后 fixed-point（连续两次 smart layout 收敛）用例红——那说明面积
快照与求解结果互相追逐，需要回到 spec
`2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md` 讨论，不要在 plan 内硬修。

### A3 自动重建时间轴：`auto_rebuilt` 标记 + provenance + 持续芯片

现状：`io/file_data.py:116-121 rebuild_time_axis` 直接覆写 `fs` / `time_array` 并把
`_time_source` 写成 `'manual'`——自动重建（`window.py:5290 _check_uniform_or_prompt`、
`_frf_mixin.py:293 _frf_auto_rebuild_source_time_axis`）与用户 popover 手动确认
（`window.py:2571`）从此不可区分。原 Fs、抖动量都丢；工程只持久化 `fs` + `time_source`
（`_project_io_mixin.py:2179-2184` / `:2240-2248`）；反馈只有 toast + 状态栏
（`window.py:5324-5329`、`_frf_mixin.py:302-317`）。批处理自己重建
（`batch_compute.py:233-243`、`:469-511`）并只写字符串 warning。

步骤：

1. **`io/file_data.py`**
   - 新增冻结 dataclass `TimeAxisProvenance`：`reason`
     （`'auto_nonuniform' | 'manual' | 'project_restore'`）· `method`（固定 `'median_dt'`）·
     `original_fs` · `original_time_source` · `estimated_fs` · `relative_jitter` ·
     `dt_min` · `dt_max` · `n_samples` · `applied_at`（ISO 字符串）。提供 `to_dict()` /
     `from_dict()`，无 Qt 依赖。
   - `FileData.__init__` 显式初始化 `self.time_axis_provenance = None`。
   - 新增公开只读方法 `time_axis_relative_jitter() -> float | None`，复用
     `is_time_axis_uniform` 里那段 `max|dt−1/fs|/(1/fs)` 的计算（抽成私有 helper 两处共用，
     不复制公式），并返回 `dt_min / dt_max`。
   - `rebuild_time_axis(fs, *, reason='manual')`：先用旧轴算 provenance 快照，再覆写，
     `_time_source` 按 `reason` 写 `'manual'` 或 `'auto_rebuilt'`；`project_restore` 时
     `_time_source` 沿用工程里保存的值，provenance 由调用方从工程回填。
2. **调用方**
   - `window.py:5290`、`_frf_mixin.py:293` → `reason='auto_nonuniform'`；toast 文案不变，
     状态栏文案加上 `原 Fs≈… · 抖动 …`。
   - `window.py:2571` popover Accept → `reason='manual'`。
   - `_frf_mixin.py:333-338` / `batch_compute.py:170-174` 只拒绝 `generated`，
     `auto_rebuilt` 走 `manual` 同样的路径，无需改动但要有测试证明。
3. **工程持久化**（`ui/project_io.py` + `_project_io_mixin.py`）
   - `ProjectFileRef` 增加可选字段 `time_axis_provenance: dict | None`，**additive**，
     schema 版本保持 v3；旧工程读出 `None`。
   - 保存：`fd.time_axis_provenance.to_dict()`；恢复：`time_source in ('manual','auto_rebuilt')`
     时按 `fs` 重建（现有逻辑），然后回填 `TimeAxisProvenance.from_dict(...)`。
4. **持续可见芯片**（`ui/chart_stack/cards.py`）
   - 新增 `timeAxisProvenanceChip`（`QLabel`，objectName 同名），与 `chartQualityIndicator`
     同排放在卡片头部；文案 `已重采样 Fs≈{estimated_fs:g} Hz`；tooltip 列出全部 provenance
     字段（原 Fs、抖动、方法、时间、影响：本文件所有通道）。默认隐藏。
   - 卡片 API：`set_time_axis_provenance(text: str | None, tooltip: str | None)`——
     卡片只管展示，不持有 `FileData`。
   - MainWindow 侧在 `_analysis_mixin.py:1538` 附近既有的「chart_rebuilt 时 stamp fact」
     位置，汇总当前卡片所有来源文件中 `reason == 'auto_nonuniform'` 的 provenance 并推给卡片；
     文件移除 / 清空 / 工程切换时推 `None`（对称重置）。
   - QSS：`QLabel#timeAxisProvenanceChip` 用现有 pill 基线；状态规则**不得**用 `border:` 简写。
5. **批处理**：`batch_compute.py` 两处重建点，在既有 warning 字符串旁把结构化字典写进
   `effective_facts['time_axis']`（字段与 `TimeAxisProvenance.to_dict()` 一致，`reason='auto_nonuniform'`）；
   `batch_manifest.py:417-431` 的 `effective_facts` 已是每条 entry 必有字段，additive 无需改 schema。

测试合同：

- `tests/test_file_data_time_axis.py`（新；现有 `test_file_data_audio.py` / `test_file_data_short_name_ellipsis.py` 不覆盖时间轴）：`rebuild_time_axis(reason='auto_nonuniform')` 后 `_time_source ==
  'auto_rebuilt'`、provenance 各字段正确、`relative_jitter` 与 `is_time_axis_uniform` 判据一致；
  `reason='manual'` 后 `_time_source == 'manual'`；连续两次重建，provenance 记录的是**紧邻上一轴**。
- `tests/ui/test_project_session.py`：带 provenance 的工程往返；旧 v3 工程无该字段可正常加载。
- `tests/ui/test_main_window_smoke.py`：非均匀 MF4 触发自动重建 → 卡片芯片可见、文案含 Fs；
  换到均匀文件 → 芯片隐藏；FRF 自动重建同理。
- 卡片芯片用例（新建 `tests/ui/test_card_provenance_chip.py`）：`set_time_axis_provenance(None)` 隐藏、字符串显示。
- `tests/test_batch_compute_time_axis.py` / `tests/test_batch_manifest.py`：manifest entry 含
  `effective_facts.time_axis`。
- FRF / batch 对 `auto_rebuilt` 来源不拒绝（补一条正向用例）。

护栏：`tests/ui/test_main_window_state_ownership.py`（`time_axis_provenance` 只在 `FileData`
上，不在 MainWindow 上新增多文件写属性）· `tests/ui_kit/test_qss_border_shorthand.py` ·
`tests/test_batch_render_import_boundary.py`（`io/` 仍不拉 UI）。

### A4 图表质量点：区分「流畅预览」与「绘制异常」

现状：`quality.py:1179-1328 quality_status` 把「无曲线」、「按墨迹预算关闭 AA」、「密度不可读取」、
「实测帧超时」全部返回 `state="red"`，`_QualityStatusIndicator`（`cursor_pill.py:781-785`）
一律画 `#ef4444`。`line_canvas.py:1147-1216` / `frf_canvas.py:767+` 有平行实现。

新状态词表（只改标签与颜色，**不改任何 AA 决策**）：

| state | 颜色 | 含义 | 迁入的现有分支 |
| --- | --- | --- | --- |
| `idle` | 灰 `#9ca3af` | 无曲线 | `抗锯齿未激活：无曲线` |
| `preview` | 蓝 `#60a5fa` | 流畅预览：按预算关闭 AA，是正常决策 | 高光栅成本 / 满幅振荡 / 波形填满绘图区 / `{叠加\|曲线}密度 M > B` |
| `yellow` | 不变 | 正在细化 | 现有 yellow |
| `green` | 不变 | 精细显示 | 现有 green |
| `red` | 不变 | 绘制异常，需要注意 | 密度不可读取 · 实测帧超时 · 兜底 |

步骤：

1. `quality.py`：上表映射；tooltip 前缀改为 `流畅预览：…（已按墨迹预算关闭抗锯齿）`、
   `正在细化：…`、`精细显示`、`无曲线`、`绘制异常：…`。返回字典其余键不变。
2. `line_canvas.py` / `frf_canvas.py` 的平行实现同样映射（`实测帧超时` 留 red）。
3. `_QualityStatusIndicator` 增加两个颜色；未知 state 回落灰色并 `logger.warning`。
4. 若 `help/*-guide.html` 有红点说明，同步词表。

测试合同：四个测试文件中现有 `state == "red"` 断言按上表**逐条**改成 `preview` / `idle`，
只有「密度不可读取」「实测帧超时」「兜底」保留 `red`；新增 `test_quality_dot_vocabulary_is_closed`
枚举五个 state 都有颜色。**不许**改动 `TestInkBudget`、`TestViewRestoreSettlement`、
`TestDiscreteSettle`、`test_frame_paint_backstop_is_installed_on_real_canvas` 及三条分析画布
AA 闸门用例的任何断言。

Cocoa 前台：五种颜色在白底卡片头部可辨、蓝点不与 View 色标混淆。

---

## 3. 批次 B —— 「有效事实」推广到 FFT / 时频 / 阶次

现状：FRF 有 `FrfEffectiveFacts`（`signal/frf.py:254-274`）→ `contextual_frf.format_effective_facts`
（`:112-142`）→ `frfFactsCard`（`:428-452`）→ `_frf_mixin.py:100 set_effective_facts` 的完整链路。
FFT 只有折叠摘要 `自动(N)`（`contextual_fft.py:387-404`），时频 / 阶次同理
（`contextual_fft_time.py:324-335`、`contextual_order.py:330-341`）。FFT 的实际 NFFT 由
`_fft_mixin._resolve_fft_effective_params` 算出（`nfft_effective`），`FFTAnalyzer.compute_fft`
还会二次 clamp（`signal/fft.py:245-258`），但都没回传给用户。

### B1 中立 DTO（`signal/`，无 Qt）

各分析器旁新增冻结 dataclass，字段命名与 `FrfEffectiveFacts` 对齐以便共享格式器：

| DTO | 位置 | 字段 |
| --- | --- | --- |
| `FftEffectiveFacts` | `signal/fft.py` | `fs` · `nfft_requested` · `nfft` · `df` · `window` · `window_s`（nfft/fs） · `frames`（单帧=1；平均 / 峰值保持=段数） · `overlap` · `n_samples` · `weighting` · `shortened: bool`（`nfft < nfft_requested` 或段数 < `min_frames`） · `time_start/time_end` |
| `SpectrogramEffectiveFacts` | `signal/spectrogram.py` | `fs` · `nfft_requested` · `nfft` · `df` · `window` · `window_s` · `hop_s` · `frames` · `overlap` · `n_samples` · `shortened` |
| `OrderEffectiveFacts` | `signal/order.py` | `fs` · `nfft` · `order_res_requested` · `order_res` · `max_order` · `samples_per_rev` · `revolutions` · `rpm_min/rpm_max` · `n_samples` · `shortened` |

要求：`compute_*` 已有的 clamp 逻辑不复制——在 `_fft_mixin._fft_compute_arrays`（`:146-176`）
由 `_resolve_fft_effective_params` 的输出 + `len(sig)` 构造，时频 / 阶次由各自 `Result.params`
+ metadata 构造；`batch_compute.py:628-637` 同源构造。数据健康字段（`nan_count` ·
`is_constant` · `time_axis: TimeAxisProvenance.to_dict() | None` · `fs_conflict: bool`）挂在同一
DTO 上，由调用方填。

### B2 共享格式器与 Inspector 卡片

1. 新建 `ui/inspector_sections/_effective_facts.py`：把 `contextual_frf.format_effective_facts`
   与 `normalize_effective_warnings` 迁入并泛化为「按字段存在性输出行」的表驱动格式器；
   `contextual_frf` 改 import（保留原名再导出，`tests/ui/test_inspector.py:565-671` 不动）。
   行文案统一：`实际 Fs` · `NFFT（请求 → 实际）`（相同时只显示一个值） · `频率分辨率 Δf` ·
   `窗口时长` · `完整帧数` · `有效时间范围` · `最大时间抖动（相对 dt）` · `时间轴：已自动重建（原 Fs …）` ·
   `数据健康：NaN n 个 / 常值 / 多源 Fs 冲突`。
2. `contextual_fft` / `contextual_fft_time` / `contextual_order` 各加一张 facts 卡
   （objectName `fftFactsCard` / `fftTimeFactsCard` / `orderFactsCard`，结构镜像 `frfFactsCard`），
   API `set_effective_facts(facts | None)`；`None` 隐藏卡片。折叠摘要保持 `自动(N)` 不变，
   仅当 `shortened` 时摘要追加 `· 已缩短`。
3. `shortened` 为真时 warnings 行写明原因：「数据过短：请求 NFFT n，仅能提供 m；Δf 由 … 降为 …」。

### B3 接线与批处理对齐

- `_fft_mixin` / `_fft_time_mixin` / `_analysis_mixin`（阶次）在计算完成、结果推到画布的同一处
  调用对应 `set_effective_facts`（镜像 `_frf_mixin.py:100`）；换信号、移除文件、切工程时推 `None`。
  facts 在 worker 结果里以 dataclass 携带（纯数据，跨线程安全）。
- 多源 FFT：facts 取代表源，`fs_conflict=True` 时 warnings 行列出各源 Fs。
- `batch_compute.py`：`asdict(facts)` 写进 `effective_facts`（与 A3 的 `time_axis` 子键并列）。

测试合同：

- `tests/signal/test_fft_effective_facts.py` 等三个：短信号 clamp → `shortened=True` 且 `nfft`
  与 `compute_fft` 实际使用值一致（用 `freq` 长度反推）；正常信号 `shortened=False`；
  空 / 非有限输入行为明确。
- `tests/ui/test_inspector.py`：`test_fft_facts_card_*` 镜像 FRF 那组；`set_effective_facts(None)` 隐藏。
- `tests/test_effective_facts_parity.py`：同一段合成信号，GUI 路径（`_fft_compute_arrays`）与
  `batch_compute` 路径产出的 facts 字段相等——这是本批的 parity 护栏。
- 护栏：`tests/test_signal_no_gui_import.py` · `tests/test_batch_render_import_boundary.py` ·
  `tests/ui/test_main_window_state_ownership.py`（facts 不成为 MainWindow 多文件写属性；
  若要缓存，放 `_state_holders.py` 的具名 holder）。

文档：四个分析指南各加一段「有效事实卡」说明；`quickref.py` 分析组加一行。

---

## 4. 批次 C —— 「打开」旁的快速打开下拉

### C0 设计

**入口**：把 `btn_add`（`toolbar.py:136-141`，primary 蓝色填充）改成与 `toolbarSaveSplit`
（`:416-456`）同构的分裂按钮：

```
┌──────────────┬────┐
│ ⎘ 打开        │ ⌄  │   ← 同一枚蓝色 pill；主按钮右侧圆角抹平，caret 左侧圆角抹平，
└──────────────┴────┘      中间 1px 分隔线用 rgba(255,255,255,0.35)，caret 宽 20（沿用 _SAVE_CARET_WIDTH）
```

- 主按钮：属性名保持 `btn_add`、文案「打开」、`role="primary"`、仍绑定
  `CommandId.OPEN_PROJECT`，行为零变化；objectName `toolbarOpenMain`。
- caret：`btn_open_caret`，objectName `toolbarOpenCaret`，`role="primary"`，icon-only 白色下箭头，
  tooltip「最近打开的项目和文件」。
- host：`toolbarOpenSplit`。

**菜单**（`apply_rounded_menu_chrome(QMenu)`，与另存为菜单同 chrome；懒填充，`aboutToShow` 时刷新）：

```
 ▣ P166_对比.tlproj  ·  ~/Documents/EPS/2026-09
 ▣ 台架复测.tlproj    ·  ~/Documents/EPS/2026-08
 ─────────────────────────────────────────────
 ▤ SFNS_40_X04-CSER_000009.wwt  ·  ~/…/testdoc/2024_3_17
 ▤ SFNS_40_X04-CSER_000010.wwt  ·  ~/…/testdoc/2024_3_17
 ▤ run_0312.mf4  ·  /Volumes/DATA/P166        （未找到）   ← disabled
 ─────────────────────────────────────────────
   清除最近记录
```

- 上组最近**项目** ≤ 4 条，下组最近**文件** ≤ 8 条，按最近打开时间倒序；两组用分隔线区分、
  以图标区分类型（项目用 `Icons.save_disk`，文件用 `Icons.file`；`ui_kit/icons.py` 没有专门的项目图标，不为此新画），不加文字标题
  （避免 disabled 标题项与「未找到」disabled 项混淆）。
- 每行文案 = `文件名  ·  父目录`，父目录把 home 折成 `~`；整行超过 **56 个字符**时先中间省略父目录，
  文件名本身只有超过 40 字符才省略。tooltip 显示完整路径 + `最近打开 2026-09-04 21:32`。
  文案由中立纯函数 `format_recent_label(path, *, max_chars=56, home=...)` 生成，可无字体测试。
- 文件不存在（含未挂载卷）→ 行 disabled、文案末尾 `（未找到）`；**不自动删除**，只在用户点
  「清除最近记录」或条目被挤出上限时移除。
- 空态：单条 disabled 项「暂无最近记录」，footer disabled。
- 一次多选打开 N 个文件 → 记 N 条文件记录；`.tlproj` 打开 / 保存 / 另存为成功 → 记项目记录并置顶。
- 点击条目 → `MainWindow._open_paths([path])`，与拖放、对话框同一分发口；条目在菜单弹出后被删除
  的竞态由 `_open_paths` 既有错误路径接住并 toast，随后 `store.remove(path)`。

**存储**：`QSettings("MF4Analyzer", "DataAnalyzer")` 键 `files/recent_v1`，值为 JSON 字符串
`[{"path","kind":"file|project","opened_at"}]`；按规范化绝对路径去重；分类型上限 8 / 4。
走 QSettings 是为了让 `tests/ui/test_qsettings_isolation.py` 的隔离夹具自动覆盖它。

### C1 存储层 `ui/recent_files.py`（新）

- `RecentEntry(path, kind, opened_at)` 冻结 dataclass；`RecentFilesStore(settings_factory=None, *,
  max_files=8, max_projects=4)`；方法 `record_file` · `record_project` · `entries(kind) -> tuple` ·
  `remove(path)` · `clear()`；`exists(entry)` 在读取时用 `Path.exists()` 判定。
- 容错：JSON 损坏 / 非列表 / 缺字段 → 视为空并 `logger.warning` 一次，不抛。
- 不 import `ui.main_window`（`ui/` 内部但与窗口无关；`ui_kit` 不 import 它）。

测试 `tests/ui/test_recent_files_store.py`：去重置顶、上限裁剪、分类型独立、损坏 JSON、
`format_recent_label` 省略规则（短路径不省略 / 长目录中间省略 / 超长文件名省略 / `~` 折叠）。

### C2 工具栏分裂按钮 `ui/toolbar.py` + QSS

- `_make_open_split()` 镜像 `_make_save_split()`；`bind_command_actions(open_action, …)`
  仍只把 `open_action` 绑到主按钮。
- 新增信号：`recent_menu_about_to_show()` · `recent_open_requested(str)` · `recent_clear_requested()`；
  新增 API `set_recent_entries(projects: Sequence[RecentEntry], files: Sequence[RecentEntry])`
  重建菜单 actions。条目连接用 `functools.partial(self._emit_recent_open, path)`，
  **`toolbar.py` 的 lambda 计数保持 1**。
- 与保存分裂一致：空会话下 caret 仍可用（最近记录不依赖当前会话）。
- QSS（`ui_kit/style.qss:1076-1092` 旁）：`Toolbar QWidget#toolbarOpenSplit` 透明；
  `#toolbarOpenMain` 右圆角 0、无右边框；`#toolbarOpenCaret` 左圆角 0、primary 填充、
  `border-left: 1px solid rgba(255,255,255,0.35)`；hover / pressed 状态**只写 `background-color`**，
  不用 `border:` 简写。

测试 `tests/ui/test_toolbar.py`：结构（`btn_add.text()=="打开"`、`toolbarOpenSplit/Main/Caret`
存在、caret 宽 = `_SAVE_CARET_WIDTH`、两者 `role=="primary"`）；宽度断言从「`btn_add` 内容宽 ≤
save split」改为「open split 内容宽 ≤ batch 且高度对齐」；`set_recent_entries` 后菜单 action 文案 /
顺序 / 分隔线 / disabled（未找到）/ 空态；点击条目发 `recent_open_requested(path)`；footer 发
`recent_clear_requested`；`bind_command_actions` 不双发（`test_standard_desktop_interactions.py` 既有合同）。

### C3 窗口接线 `window.py` + `_project_io_mixin.py`

- `window.py` 初始化处创建 `self._recent_files = RecentFilesStore()`（单文件写，
  状态所有权棘轮不受影响；mixin 只调用方法）。
- 连接（bound method，不加 lambda）：`recent_menu_about_to_show → _populate_recent_menu`
  （读 store → `toolbar.set_recent_entries`）；`recent_open_requested → _open_recent_path`
  （`_open_paths([path])`，失败后 `store.remove`）；`recent_clear_requested → store.clear()`。
  **不要**再连 `toolbar.open_requested`（`window.py:1103-1105` 既有双发警告）。
- 记录点（`_project_io_mixin.py`）：`_open_paths` 每个成功加载的数据文件 → `record_file`；
  `open_project` 成功 → `record_project`；`save_project_via_dialog` / `save_project_as_via_dialog`
  成功 → `record_project`。失败不记录。

测试：`tests/ui/test_open_and_save_entry.py` 扩展——打开两个文件后 `entries('file')` 顺序正确；
保存工程后 `entries('project')[0]` 是该路径；`_populate_recent_menu` 后工具栏菜单条目与 store 一致；
发 `recent_open_requested` 走到 `_open_paths`（monkeypatch 断言）；不存在路径不触发 `_open_paths`。
护栏：`tests/ui/test_no_lambda_signal_connections.py`（`window.py` ≤ 30）·
`tests/ui/test_main_window_state_ownership.py` · `tests/ui/test_qsettings_isolation.py`。

### C4 发现性与帮助

- `ui/hints.py`：新增 `toolbar.recent_menu`（text「打开旁箭头可快速打开最近的项目和文件」，
  `surface="discovery"`，`retire_on="recent_open"`，priority 与 `toolbar.save_as_menu` 同级）；
  `_open_recent_path` 成功后 `mark_discovered("recent_open")`。
- `ui/quickref.py:101` 「打开数据 / 项目」行加 `sub`：「箭头展开最近 4 个项目与 8 个文件；
  不存在的条目灰显；可一键清除记录。」
- `help/TraceLab-使用说明.html` 「打开」段落加一句同义说明。
- 测试：`tests/ui/test_quickref.py` · `tests/ui/test_hints.py` · `tests/test_help_content.py`。

### C5 Cocoa 前台验收（不可用 offscreen 替代）

1. 分裂按钮与保存分裂视觉一致：同高、同圆角、蓝色 pill 无缝、分隔线可见但不刺眼；
2. hover 主按钮 / hover caret 只有各自区域变色；
3. 弹出菜单：长路径省略正确、`~` 折叠、disabled 行灰显、图标区分项目 / 文件、footer 可点；
4. 打开一条最近文件后菜单顺序更新；清除后空态；
5. 与「保存」菜单并排打开无位置错位。
截图存 `docs/analyzer/verify/2026-09-04-quick-open/`（真机证据，按现有 verify 目录规范）。

---

## 5. 验证

### 5.1 各批 owner tests（聚焦，改前先跑一遍取基线）

```bash
RUN="TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q"

# A1
$RUN tests/test_analysis_presets.py tests/ui/test_inspector.py -k "recommend or badge or preset"
# A2
$RUN tests/test_ultraview_smart_layout.py tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_smart_layout_integration.py
# A3
$RUN tests/test_file_data_time_axis.py tests/ui/test_project_session.py tests/test_batch_compute_time_axis.py tests/test_batch_manifest.py \
     tests/ui/test_main_window_smoke.py -k "rebuild or uniform or provenance"
# A4
$RUN tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_line_canvas.py tests/ui/test_frf_canvas.py \
     tests/ui/test_pg_dense_raster.py -k "quality or status or aa"
# B
$RUN tests/signal/test_*_effective_facts.py tests/test_effective_facts_parity.py tests/ui/test_inspector.py -k "facts"
# C
$RUN tests/ui/test_recent_files_store.py tests/ui/test_toolbar.py tests/ui/test_open_and_save_entry.py \
     tests/ui/test_quickref.py tests/ui/test_standard_desktop_interactions.py
```

### 5.2 边界护栏（每批合入前各跑一次）

```bash
$RUN tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py \
     tests/ui/test_import_boundaries.py tests/test_signal_no_gui_import.py \
     tests/test_batch_render_import_boundary.py tests/test_native_import_boundaries.py \
     tests/test_packaging_imports.py tests/ui_kit/test_qss_border_shorthand.py \
     tests/ui/test_qsettings_isolation.py tests/test_help_content.py
```

A4 额外显式复跑：`tests/ui/test_pg_timedomain_canvas.py -k "InkBudget or ViewRestoreSettlement or
DiscreteSettle or backstop"` 与 `tests/ui/test_pg_line_canvas.py tests/ui/test_frf_canvas.py -k "aa_off or ink_gate or backstop"`，
证明只改了标签没改决策。

### 5.3 不跑全量

三批都不是跨边界重构，按 `CLAUDE.md` 测试门禁**不跑全量**。若三批合并后要发版，由发版协调者按
两条命令串行跑一次，并记录 `HEAD` 与脏文件范围。

### 5.4 交付卫生

```bash
git diff --check
git status --short
git diff --name-only   # 只能出现 §1 列出的文件
```

---

## 6. 完成定义

批次 A

- [ ] 未知 / 缺失单位不显示「荐」徽标；可识别单位的按钮 tooltip 写明依据；帮助文案一致
- [ ] `preserve_salience` 在生产路径拿到非 `None` salience；12×12 + 两小卡复现用例主卡更大；
      fixed-point 用例不回归
- [ ] 自动重建写 `auto_rebuilt` + `TimeAxisProvenance`；工程往返保留；卡片芯片随来源出现 / 消失；
      批处理 manifest 有 `effective_facts.time_axis`
- [ ] 质量点五态词表落地，AA 决策相关全部既有断言零改动；Cocoa 颜色可辨

批次 B

- [ ] FFT / 时频 / 阶次三张 facts 卡与 FRF 同构，`shortened` 有原因说明
- [ ] GUI 与 batch 的 facts parity 测试绿；`signal/` 无 GUI import 护栏绿
- [ ] 四个分析指南 + quickref 更新

批次 C

- [ ] 「打开」分裂按钮与「保存」视觉一致（Cocoa 截图入 verify）
- [ ] 最近项目 ≤ 4 / 文件 ≤ 8，去重置顶，未找到灰显不自动删，清除可用，空态正确
- [ ] 记录点覆盖打开文件 / 打开工程 / 保存 / 另存为；`_open_paths` 单一分发口
- [ ] `toolbar.py` lambda 计数 1、`window.py` ≤ 30；QSettings 隔离护栏绿
- [ ] hints / quickref / 使用说明同步

通用

- [ ] 各批 owner + §5.2 护栏绿，`git diff --check` 通过
- [ ] diff 未包含 §1 所列无关的预存改动
