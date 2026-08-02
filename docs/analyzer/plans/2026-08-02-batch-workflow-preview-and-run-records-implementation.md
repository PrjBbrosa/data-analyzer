# 批处理工作流收口：术语、来源提示、运行预览与运行记录 Implementation Plan

- **状态**：待执行（本文件仅为计划，未修改产品代码）
- **日期**：2026-08-02
- **建议顺序**：先执行本计划，再执行 `2026-08-02-batch-in-chart-statistics-implementation.md`
- **当前观察基线**：`feat/batch-settings-persistence@783d5d8`；执行前必须重新确认 HEAD、工作树与 `main/origin/main` 关系

> 用户决定：删除“紧凑工作流”；用户可见术语统一为“分屏”；解释并收口“等待来源信息”；运行前提供真实单图预览；普通输出目录不再散落多份 manifest JSON。
>
> 本计划不实现区间统计。统计属于第二份计划，避免 UI 工作流与数值/渲染模型同时改动。

---

## 1. Goal

把 Batch 从“配置完成后立即全量运行”收口为可理解、可预览、输出目录干净的工作流：

1. 产品界面删除开发性标签“紧凑工作流”，统一使用“分屏 / 叠加”。
2. dB reference 的来源状态有明确对象和原因，不再出现孤立的“等待来源信息”。
3. 底栏增加“预览”，先显示无加载的任务/文件预估，再由用户显式生成一个代表输出组的真实 PNG。
4. 预览不发布正式文件、不写 XLSX、不写 manifest、不改变本次运行状态。
5. manifest 保留恢复/重试/追溯能力，但移入 Batch 自己管理的运行记录目录；普通结果区主要只显示 PNG/XLSX。

## 2. Baseline and conflict boundary

### 2.1 当前分支事实

执行计划时不得假定 `main` 已包含当前 Batch 选择器改造：

- 当前观察到 `feat/batch-settings-persistence` 与 `feat/batch-signal-picker-option-a` 指向同一 `783d5d8`。
- `main/origin/main` 当前观察为 `1f69db9`。
- 当前分支相对 `main` 已包含 signal picker、QuickRef 和两份既有计划。
- 本计划编写期间已观察到配置记忆 lane 正在修改 `sheet.py`、`output_panel.py`、`tests/ui/conftest.py`、`tests/ui/test_batch_smoke.py`，并新增 `ui/batch_settings.py`、`tests/ui/test_batch_settings.py`；这些不是本计划的改动。
- `.playwright-cli/*` 是既有未跟踪文件，不删除、不纳入本计划。

实施前先固定一个明确基线；当前配置记忆 lane 必须先完成、形成可复核 checkpoint，或明确暂停并移交文件所有权，不能并行编辑 `sheet.py` / `output_panel.py`。

### 2.2 与第二份计划的文件所有权

| Lane | 主要文件 | 规则 |
| --- | --- | --- |
| 本计划 UI | `sheet.py`、`output_panel.py`、新 `preview_dialog.py`、`method_buttons.py`、`ui/hints.py` | 先完成并冻结公共接口 |
| 本计划 core | `batch.py`、`batch_manifest.py`、必要的 preview contract/helper | UI RED tests 后串行进入 |
| 图内统计计划 | `batch_statistics.py`、`batch_render_qt/*`、`batch_series_spool.py`、`analysis_panel.py` | 不与本计划同时修改 `batch.py`；等待本计划 core 合入后再开始 connector |

## 3. Fixed product decisions

### 3.1 术语

用户可见文字采用：

| 现状 | 目标 |
| --- | --- |
| 顶栏“批处理分析  紧凑工作流” | 只保留“批处理分析” |
| 图内布局：`叠加 / 子图` | 图内布局：`叠加 / 分屏` |
| “滚轮作用于鼠标所在子图” | “滚轮作用于鼠标所在分屏图” |
| “Shift + 滚轮 缩放当前子图 Y” | “Shift + 滚轮：缩放鼠标所在分屏图 Y 轴” |

内部兼容标识 **不改名**：`subplot`、`btn_subplot`、`render_layout="subplot"` 和旧 preset JSON 都继续有效。历史设计文档中的“子图”不做机械替换；只修改当前产品 UI、QuickRef、提示和对应测试。

### 3.2 dB 来源提示

“等待来源信息”只属于 FFT / FFT vs Time / 阶次的 dB reference 解析，不是整个 Batch 的运行状态。

状态文案冻结为：

| 条件 | 文案 |
| --- | --- |
| 任一来源仍在 path pending / probing | `dB 参考：等待文件解析` |
| 来源已解析但未选择目标 | `dB 参考：请选择目标信号` |
| 目标存在但无可解析组合 | `dB 参考：所选目标缺少可用单位/来源` |
| 已解析 | `dB 参考：{N} 个目标：{grouped resolution}` |
| 时域 | 整个 dB reference 行和来源说明隐藏 |

只保留一个可见来源说明：由 `DbReferenceControl` 自己显示。移除其下方重复的 `_effective_preview` 可见标签；如测试或兼容调用仍需要 `effective_preview_text()`，让 accessor 读取同一个 control 文本，不保留第二个视觉真相源。

### 3.3 两级预览

预览分为两类，成本和语义必须分开：

1. **自动计划预估（no-load）**：复用 `BatchRunner.preview_outputs()`，只显示任务数、PNG/XLSX 数、冲突数和代表输出组列表；不得完整加载 HDF/CSV/MDF 等 full-cost 来源，不得预留输出路径。
2. **用户显式图片预览（selected-group load）**：用户点击“预览”并选择一个代表组后，允许加载该组所需来源并生成一张真实 PNG。它不是 no-load probe，UI 必须明确显示“将读取 N 个来源，只生成 1 张临时图片”。

图片预览必须使用正式运行的预处理、分析和 Qt renderer；不得复制一套简化数值算法。

### 3.4 manifest 变为内部运行记录

manifest 仍是恢复、重试、冲突归属和问题追溯的权威，不直接关闭 `write_manifest`。

新布局：

```text
<用户输出目录>/
  result-1.xlsx
  result-1.png
  ...
  .tracelab/
    runs/
      batch-manifest__{run_id}.partial.json
      batch-manifest__{run_id}.json
```

规则：

- clean terminal run 删除对应 `.partial.json`，保留 final manifest。
- 不自动清理历史 manifest；删除/保留策略涉及用户恢复能力，另开任务决定。
- resume 自动发现优先扫描 `.tracelab/runs/`，然后兼容旧输出根目录的 `batch-manifest__*.json`。
- 传入显式 manifest 路径的 core API 行为不变。
- manifest 不计入用户看到的“预计输出文件数”。
- 预览永远不创建 `.tracelab/`。
- 本阶段不增加“随结果导出 manifest”开关；如未来需要可移植审计包，再单独设计。

这是一项对 Phase 3“manifest 位于输出根目录”旧约定的有意修订；读取兼容必须保留，写入只采用新位置。

## 4. Execution order

### First tranche — 可先独立执行的低风险工作

#### Task 0 — Freeze baseline and RED tests

**Read/check**

- `git status --short --branch`
- `git log --oneline --decorate -8`
- 记录本计划涉及文件相对基线的 diff。
- 跑现有术语、output panel、compact contract 和 hint focused tests，记录基线。

**RED tests**

- Batch 顶栏不存在“紧凑工作流”。
- Batch 图内布局可见文本为“分屏”，数据仍为 `subplot`。
- chart hints/QuickRef 不再出现当前产品语境下的“子图”。
- time method 不显示 dB reference 来源；FFT pending/no-target/resolved 三态文案准确。
- 界面只有一个可见 dB 来源说明。

#### Task 1 — Terminology cleanup

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Modify: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Modify: `mf4_analyzer/ui/hints.py`
- Modify only if current wording is exposed there: `mf4_analyzer/ui/quickref.py`
- Tests: `tests/ui/test_batch_compact_contract.py`、`tests/ui/test_batch_method_buttons.py`、`tests/ui/test_chart_stack.py`、`tests/ui/test_quickref.py`

**Implementation**

- 删除 `_toolbar_meta` 的可见标签和相应无用布局占位。
- Combo 只改 display text，不改 data。
- 精确修改两条运行提示，不对源码注释、变量名和历史文档做全仓机械替换。

#### Task 2 — dB reference state ownership

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py` only for inputs passed to the formatter
- Tests: `tests/ui/test_batch_output_panel.py`、`tests/ui/test_batch_smoke.py`

**Implementation**

- 提取一个无副作用的状态 formatter/resolver，输入为 method、row states、selected targets、resolved groups。
- `update_effective_preview()` 只更新 `DbReferenceControl` 的来源文本。
- 删除独立可见 `_effective_preview`；兼容 accessor 指向同一文本。
- unknown/missing facts 不得被默认单位伪装成已解析。

完成 Task 1–2 后可以形成第一个小提交；它们不改 runner、manifest、数值和 Qt renderer。

### Second tranche — 运行预览

#### Task 3 — Preview plan contract（no-load）

**Files**

- Modify: `mf4_analyzer/batch.py`
- Prefer create: a small GUI-free preview contract/helper module if `batch.py` 会继续膨胀
- Tests: `tests/test_batch_runner.py`、`tests/test_batch_source_integration.py`

**Contract**

在现有 `BatchOutputPreview` 计数之外，提供稳定的代表输出组描述：

- `group_id`
- display name
- grouping mode (`none/source/channel`)
- member/task count
- required source count
- planned artifact stem

要求 task/group/stem/identity 与正式运行一致。metadata-cost probe 可用时复用缓存；full/unknown-cost adapter 使用 deterministic unresolved identity，不能因预览而加载。

#### Task 4 — Explicit one-group image preview

**Files**

- Modify: `mf4_analyzer/batch.py`
- Create: `mf4_analyzer/ui/drawers/batch/preview_dialog.py`
- Modify: `mf4_analyzer/ui/drawers/batch/runner_thread.py` or create a dedicated preview worker
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Tests: `tests/test_batch_runner.py`、`tests/ui/test_batch_runner_thread.py`、`tests/ui/test_batch_smoke.py`

**Core behavior**

- 新增显式 `preview_group(...)` API，只执行所选 planned group。
- 复用正式 preprocessing/analyzer/render-group 路径；若需抽取共享函数，先用 producer-shaped tests 冻结正式 run 行为。
- 输出到 `QTemporaryDir`/等价私有临时目录；固定 image-only、PNG、`write_manifest=False`。
- 不调用正式 output reservation，不检查/占用最终图片名，不写 data artifact。
- 返回 image path、group identity、warnings、loaded source count；关闭预览后清理临时目录。
- group-by-channel 预览可能需要读取该信号涉及的所有来源，不能冒充“只读一个文件”。

**UI behavior**

- 底栏：`关闭 | 预览 | 运行`，预览为 secondary，运行保持 primary/default。
- 与 Run 使用同一 preflight；配置不完整时两者均不可用。
- 打开 dialog 立即显示 no-load 计数与代表组；默认选择第一组。
- 用户确认生成后启动可取消 worker；不阻塞 Qt 主线程。
- dialog actions：`返回修改`、`重新生成`、`运行全部`。
- “运行全部”仍进入现有 `_on_run_clicked()`，不得让 preview result 成为 `_last_result`，不得把 preview manifest/path 写入 preset。
- preview worker 的 unlock/cleanup 由其 `QThread.finished` 唯一驱动。

### Third tranche — manifest 运行记录目录

#### Task 5 — Separate artifact directory from manifest directory

**Files**

- Modify: `mf4_analyzer/batch_manifest.py`
- Modify: `mf4_analyzer/batch.py`
- Tests: `tests/test_batch_manifest.py`、`tests/test_batch_runner.py`

**Implementation**

- `BatchManifestRecorder` 显式接收 manifest directory；不要从 artifact path 反推。
- runner 建立 `<output>/.tracelab/runs` 只发生在正式 run 且 `write_manifest=True` 时。
- final/partial 原子性、checksum、cancel、status rewrite 契约保持不变。
- auto-resume discovery 新目录优先、旧根目录兼容；候选排序和严格 schema/source facts 校验不放宽。
- output artifact path 继续指向用户输出目录；manifest 自身路径指向 run store。
- preview tests 断言输出目录与 `.tracelab` 均未创建。

#### Task 6 — UI completion facts

**Files**

- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Tests: `tests/ui/test_batch_smoke.py`、`tests/ui/test_batch_runner_thread.py`

**Implementation**

- 完成状态显示用户产物数，不把 manifest 算入。
- 如需要暴露运行记录，只提供显式“查看运行记录”动作；不得完成后自动打开 Finder。
- preview、run、cancel 连续执行时，运行状态和临时目录互不串线。

## 5. Verification matrix

### Focused automated

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_batch_compact_contract.py \
  tests/ui/test_batch_method_buttons.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_smoke.py \
  tests/ui/test_batch_runner_thread.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_quickref.py \
  tests/test_batch_runner.py \
  tests/test_batch_manifest.py \
  tests/test_batch_source_integration.py
```

### Required behavior probes

1. production full-cost HDF adapter：打开/重算 no-load 预估时 loader 调用次数为 0。
2. explicit preview：只生成 1 张临时 PNG，不生成 XLSX/JSON，不创建正式输出目录 reservation。
3. source/channel/none 三种 grouping：预览组选取与正式 run 的 group id/member/stem 一致。
4. preview cancel：临时文件清理，controls 恢复，随后 Run 可正常启动。
5. 正式 run：PNG/XLSX 在根目录，final/partial manifest 只在 `.tracelab/runs`。
6. 旧根目录 manifest：仍可显式加载并通过严格 resume 检查。

### Visual acceptance

- 1080×760 和 1440×900 各生成 BatchSheet 前台截图。
- 核对顶部没有多余 meta、分屏术语一致、dB 来源说明不孤立。
- 预览 dialog 在两种窗口尺寸都能看到图片、计数、warning 和底部动作。
- 使用真实 Cocoa/TraceLab 前台确认；offscreen 截图只作为结构证据。

## 6. Acceptance criteria

| ID | 验收 |
| --- | --- |
| W1 | 产品 UI 不再显示“紧凑工作流”，当前用户提示统一为“分屏” |
| W2 | dB source 的 pending/no-target/missing/resolved/time 状态对象明确，且只有一个可见真相源 |
| W3 | 自动预估对 full-cost adapter 零完整加载、零 reservation、零目录写入 |
| W4 | 用户显式预览只执行一个选择组，使用正式算法/renderer，生成一张可取消的临时 PNG |
| W5 | preview 不改变 preset、task list runtime、`_last_result`、manifest 或正式输出文件 |
| W6 | 正式 run 的用户输出目录不散落 manifest JSON；运行记录位于 `.tracelab/runs` |
| W7 | 新旧 manifest 均可严格读取/恢复，不因目录迁移放宽 identity/fingerprint/checksum 校验 |
| W8 | focused tests、真实 PNG、1080×760/1440×900 前台 UI 均完成独立验证 |

## 7. Stop conditions

- no-load 预估触发 full-cost source load：停止本计划，不接 UI。
- preview 通过构造简化数据绕开正式 preprocessing/renderer：停止交付。
- preview 在用户输出目录留下 PNG、XLSX、JSON、reservation 或 `.tracelab`：停止交付。
- manifest 迁移后旧路径 resume 静默失效：停止交付。
- 术语只改 Batch combo、但运行提示/QuickRef 仍混用：不得宣称全局一致。
- 只有 offscreen 结构证明、没有前台 TraceLab 预览窗口检查：不得完成视觉验收。

## 8. Non-goals

- 不在本计划计算最大值/最小值/平均值。
- 不改变 `subplot` 的序列化值或升级 preset schema。
- 不把 manifest 变成项目文件或长期数据库。
- 不自动删除旧 manifest，不自动打开 Finder，不发布外部系统。
- 不在预览时运行全部组，也不承诺代表图证明所有来源都有效。
- 不 commit/push/merge/清理分支，除非用户后续明确要求。

## 9. Execution record（执行时填写）

```text
baseline SHA:
first tranche tests:
preview core/UI tests:
manifest migration tests:
1080×760 foreground proof:
1440×900 foreground proof:
real representative preview:
legacy manifest compatibility:
```
