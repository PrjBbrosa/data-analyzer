# 批处理内核拆分与稳定性加固 · 实施计划

> **For agentic workers:** 按任务逐条执行,checkbox（`- [ ]`）跟踪进度。每个任务
> 自成一个可验证增量:完成即跑该任务的验证命令,失败集必须与基线一致才能进入下一任务。

**目标:** 执行 [2026-08-04-batch-core-decomposition-design.md](../specs/2026-08-04-batch-core-decomposition-design.md)
的 D1–D9:把 `batch.py` 的 DTO / DSP / 字节 IO 拆成独立模块、中立化渲染数据契约、
公开化切片契约(第一步,零行为变化);随后引入日志兜底、收口进度与记录、拆解
`run()` 巨型函数(第二步,稳定性加固)。

**基线:** `main` @ `e385ce5a`(v7.9.3 + 通道表达式功能)。所有行号以此为准。
**独立分支执行**。

**测试环境:** `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest`
(下文简写为 `PYTEST`)。批处理全量 = `tests/test_batch*.py tests/test_frozen_batch*.py tests/ui/test_batch*.py`。

## 全局约束

- 公共 API 不破坏:`from mf4_analyzer.batch import ...` 的每个既有名字保持可用。
- 测试文件**一行不改**(第一步)——39 处 `BatchRunner._xxx` 私有引用靠类级别名兼容。
- 每个任务一个 commit;移动代码与修改代码不混在同一 commit。
- 任何任务后 `tests/test_batch_render_import_boundary.py` 必须绿。
- 不触碰 `batch_render_qt/_builder.py` 的实现代码(只允许 D5 的再导出层新增)。
- 禁止臆造采样率等产品约束照旧(本工作不碰导入层,列出以防波及)。

---

## Task 0: 基线采集

- [x] **Step 1:** 建分支 `refactor/batch-core-decomposition`。
- [x] **Step 2:** 跑批处理全量,把失败集(测试 ID 列表)存入
  `docs/analyzer/verify/batch-decomposition-baseline.txt`,同时记录
  `git rev-parse HEAD`、`wc -l mf4_analyzer/batch.py`、
  `grep -c "except Exception" mf4_analyzer/batch.py`(预期 20)。

Run: `PYTEST tests/test_batch*.py tests/test_frozen_batch*.py tests/ui/test_batch*.py -q`

---

## 第一步 · 结构拆分(D1–D5,逐任务零行为变化)

### Task 1: DTO 层 → `batch_types.py`(D1)

**Files:**
- Create: `mf4_analyzer/batch_types.py`
- Modify: `mf4_analyzer/batch.py`

- [x] **Step 1:** 核对 `AnalysisPreset.from_current_single`(`batch.py:270`)与
  `free_config`(`:295`)的函数体依赖。若引用 runner 侧符号 → 改延迟 import 或参数注入;
  确认不会形成 `batch_types → batch` 环。
- [x] **Step 2:** 移动 `batch.py:177-446` 全部数据类 + `_LoadFailure` / `_ResolvedSource` /
  `_BatchCancelled` / `_ImageBackendUnavailable` 到 `batch_types.py`;所需常量
  (如 `_LEGACY_IMAGE_FORMATS` 若被 dataclass 引用)一并评估归属。
- [x] **Step 3:** `batch.py` 顶部显式回导全部名字(非 `*`),模块 docstring 注明
  「数据契约在 batch_types,此处仅兼容再导出」。
- [x] **Step 4:** 验证。

Run: `PYTEST tests/test_batch_preset_dataclass.py tests/test_batch_preset_io.py tests/test_batch_runner.py tests/test_batch_render_import_boundary.py -q`

### Task 2: DSP 计算层 → `batch_compute.py`(D2)

**Files:**
- Create: `mf4_analyzer/batch_compute.py`
- Modify: `mf4_analyzer/batch.py`

- [x] **Step 1:** 迁移 `batch.py:4563-5189` 中除 `_rpm_values` 外的 27 个方法为模块级
  函数(去装饰器,`cls.` 互调改直呼;函数名去前导下划线得公开名,如
  `compute_fft_dataframe`);`_check_cancel` 一并迁入,`_BatchCancelled` 从
  `batch_types` import。
- [x] **Step 2:** 迁移 `_Spectro2D`(`:5200-5343`)、`_matrix_to_long_dataframe`(`:5346`)、
  `_guess_rpm_channel`(`:5191`)。段内惰性 import(`signal.filters` / `signal.spectrogram` /
  `signal.order_cot` / `batch_statistics`)保持函数体内位置不变。
- [x] **Step 3:** `BatchRunner` 类体内集中放兼容别名段:
  `_compute_fft_dataframe = staticmethod(batch_compute.compute_fft_dataframe)` 等
  覆盖全部 27 个迁移名 + 三个 `_write_*`(Task 3 后补),注释「兼容层——新代码直接
  import batch_compute」。`batch.py` 其余调用点改直呼 `batch_compute.xxx`。
- [x] **Step 4:** 确认 `import mf4_analyzer.batch_compute` 导入期不拉 Qt/matplotlib
  (纯 numpy + 惰性 signal)。
- [x] **Step 5:** 验证(含直接引用私有方法最多的文件)。

Run: `PYTEST tests/test_batch_runner.py tests/test_batch_weighting.py tests/test_batch_slice_export.py tests/test_batch_render_import_boundary.py -q`

### Task 3: 字节 IO → `batch_output.py`(D3)

**Files:**
- Modify: `mf4_analyzer/batch_output.py`, `mf4_analyzer/batch.py`

- [x] **Step 1:** 迁移 `_write_dataframe`(`:5108`)/ `_write_workbook`(`:5135`)/
  `_write_image`(`:5163`)为 `batch_output` 模块级函数(公开名 `write_dataframe` 等);
  随迁 `_XLSX_MAX_DATA_ROWS`、`_SLICE_CSV_FALLBACK_WARNING`。`_write_image` 体内的
  `from .batch_render import ...` 惰性导入原样保留。
- [x] **Step 2:** `BatchRunner` 补三个别名(测试引用 `_write_image` ×6、`_write_workbook` ×3、
  `_write_dataframe` ×2)。
- [x] **Step 3:** 验证,并断言 `import mf4_analyzer.batch_output` 后 `sys.modules`
  无 `PyQt5`(在 `tests/test_batch_output.py` 加一条子进程断言,仿 boundary test)。

Run: `PYTEST tests/test_batch_output.py tests/test_batch_runner.py tests/test_batch_slice_export.py tests/test_batch_render_import_boundary.py -q`

### Task 4: 渲染数据契约中立化 → `batch_render_models.py`(D4)

**Files:**
- Create: `mf4_analyzer/batch_render_models.py`
- Modify: `mf4_analyzer/batch_render_qt/_models.py`(变 shim)、
  `mf4_analyzer/batch_render_qt/_palette.py`、`mf4_analyzer/batch_series_spool.py`、
  `mf4_analyzer/batch_render.py`
- Modify: `tests/test_batch_series_spool.py`(仅新增断言)

- [x] **Step 1:** `_models.py` 全文上移为 `batch_render_models.py`;
  `MAX_SLICE_POSITIONS` 移入其中,`_palette.py` 改为从它 import;
  `_models.py` 变纯再导出 shim(仿 `_fonts.py` 范式,docstring 指向实体)。
- [x] **Step 2:** `batch_series_spool.py:12` 改
  `from .batch_render_models import BatchSeries`。
- [x] **Step 3:** `batch_render.py` 门面确认仍再导出全部数据契约名(路径改走中立模块)。
- [x] **Step 4:** `tests/test_batch_series_spool.py` 加子进程断言:
  `import mf4_analyzer.batch_series_spool` 后 `sys.modules` 无 `PyQt5`。
- [x] **Step 5:** 验证。

Run: `PYTEST tests/test_batch_series_spool.py tests/test_batch_renderer.py tests/test_batch_render_qt.py tests/test_batch_render_qt_heatmap.py tests/test_batch_render_import_boundary.py -q`

### Task 5: 切片契约公开化 → `batch_render_qt/contract.py`(D5)

**Files:**
- Create: `mf4_analyzer/batch_render_qt/contract.py`
- Modify: `mf4_analyzer/batch.py`(`_load_slice_render_contract`,`:111-148`)

- [x] **Step 1:** `contract.py` 以公开名 + `__all__` 再导出:
  `linear_amplitude_label`、`render_in_db`、`slice_clamp_warning`(实现在 `_builder`)、
  `plan_heatmap_slice`(经 Task 4 已在中立模块)、`default_method_labels`
  (= `_page._DEFAULT_METHOD`)、`effective_fact_items`(`_page`)。docstring 写明
  「batch runner 的稳定契约面,改动需同步 `batch.py:_load_slice_render_contract`」。
- [x] **Step 2:** `_load_slice_render_contract` 改 import `contract`;ImportError 降级
  语义(`:134-137`)与返回结构不变。
- [x] **Step 3:** 第一步收尾:跑批处理全量对比基线失败集;跑一次四 kind 冒烟导出
  核对产物字节(`--batch-render-runtime-smoke` 或 `tools/verify_batch_qt_render_parity.py`);
  ~~确认 `wc -l batch.py` ≤ 3400~~ —— 见下方偏差记录。

Run: `PYTEST tests/test_batch*.py tests/test_frozen_batch*.py tests/ui/test_batch*.py -q`

**第一步执行记录(2026-08-05):**

| 项 | 结果 |
| --- | --- |
| commit | `a3ebfd64` (T1) · `2a91db08` (T2) · `a233d5cc` (T3) · `ed2a2a76` (T4) · `b7a0b395` (T5) |
| 全量批处理测试 | 3 failed / 1170 passed —— 失败集与基线**逐条一致**(passed 比基线 1168 多 2 条,是 T3/T4 各新增的一条 Qt 边界断言) |
| 四 kind 冒烟导出 | time / fft / fft_time / order_time 四张 PNG 与 `a233d5cc` 的产物 SHA-256 **逐字节一致**,零输出漂移 |
| Qt 边界 | `import mf4_analyzer.batch_series_spool` / `batch_render_models` / `batch_compute` / `batch_output` 后 `sys.modules` 均无 PyQt5 |
| `wc -l batch.py` | 5357 → **4445**(未达 ≤3400) |

**偏差:验收线 `batch.py` ≤ 3400 在 D1–D5 范围内不可达。** 算术上:原 5357 行,
DTO(`batch_types.py` 290)+ DSP(`batch_compute.py` 674)+ 字节 IO(并入
`batch_output.py` 112)共迁出约 1076 行,回填的再导出/别名层约 170 行,净剩 4445。
Task 4/5 基本不动 `batch.py`;而 Task 7/8 是把闭包提升为方法、代码仍留在本文件,
不会再掉约 1000 行。设计文档收益表里「`BatchRunner` 4727 → ≈3000」同样偏乐观
(段内可迁出的只有约 720 行)。**未为凑数字做计划外抽取**;若确需 ≤3400,应另立
一轮拆分(候选:resume/manifest 编排段、`_run_one` 的 kind 分派段)。

---

## 第二步 · 稳定性加固(D6–D9)

### Task 6: 日志兜底(D6)

**Files:**
- Modify: `mf4_analyzer/batch.py`, `mf4_analyzer/batch_compute.py`,
  `mf4_analyzer/batch_output.py`, `mf4_analyzer/batch_manifest.py`

- [ ] **Step 1:** 四个模块建 `logger = logging.getLogger(__name__)`。
- [ ] **Step 2:** 按 spec D6 表格逐条核销 10 处静默点(`record_item` 处留到 Task 7),
  每处 `logger.warning(..., exc_info=True)`,**不改变任何控制流**。
- [ ] **Step 3:** 验证:失败集与基线一致。

Run: `PYTEST tests/test_batch_runner.py tests/test_batch_manifest.py -q`

### Task 7: `_RunReporter` 收口(D7)

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Create: `tests/test_batch_run_reporter.py`

- [ ] **Step 1:** 先写失败测试:reporter 的 `emit` 事件顺序、`record` 在 recorder 抛错时
  计数进 `manifest_errors` 并 `logger.warning`(用 caplog 断言)、旧
  `progress_callback(int,int)` 兼容层仍被调用。
- [ ] **Step 2:** 实现 `_RunReporter`(batch.py 内部类,不进公共 API):吸收
  `record_item` 闭包(`:1019-1107`)、16 处 `on_event(...)` 发射、
  `emit_cancelled_range`(`:1431`)。`run()` 构造单实例,两条路径共用。
- [ ] **Step 3:** 验证。

Run: `PYTEST tests/test_batch_run_reporter.py tests/test_batch_runner.py tests/ui/test_batch_runner_thread.py tests/ui/test_batch_task_list.py -q`

### Task 8: `run()` 拆骨架(D8)

**Files:**
- Modify: `mf4_analyzer/batch.py`

四刀,**每刀一个 commit + 全量批处理测试对比基线**:

- [ ] **Step 1:** 剩余闭包提升为方法:`finish_result`(`:955`)→`_finish_result`、
  `apply_retry_scope`(`:1194`)、`task_file_name`(`:1389`)、`cancelled_item`(`:1398`)、
  `planned_group_item`(`:1498`)。捕获的局部量改显式参数。
- [ ] **Step 2:** 非分组路径(`:2134-2380`)提为 `_run_sequential(...)`。
- [ ] **Step 3:** 分组路径拆 `_run_grouped_compute(...)`(`:1605-1937`,spool 上下文
  归属取最小 diff)与 `_run_grouped_render(...)`(`:1942-2088`)。
- [ ] **Step 4:** 确认 `run()` <300 行、0 闭包;跑全量。

Run: `PYTEST tests/test_batch*.py tests/test_frozen_batch*.py tests/ui/test_batch*.py -q`

### Task 9: 异常分类审计(D9)+ 收尾

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Modify: 本文件(记录审计结论)

- [ ] **Step 1:** 对 `batch.py` 剩余每处 `except Exception` 归档三档结论
  (item 级失败 / 基础设施降级 / 收窄类型),在下方审计表逐行记录;能安全收窄的收窄
  (如 `:1171-1182` 的裸兜底)。
- [ ] **Step 2:** 全量批处理测试 + boundary test;`grep -c "except Exception"` 记入审计表。
- [ ] **Step 3:** 手动冒烟(真实 MF4,分组 + 非分组各一轮):进度、取消、失败 item
  展示与基线一致;按验真机渲染纪律核对一张导出图。
- [ ] **Step 4:** 若 `CLAUDE.md` 架构段描述与新模块布局有出入,同步一句话
  (`batch*.py` 列表本身无需变更)。

**审计表(Task 9 执行时填写):**

| 位置 | 归类 | 处置 |
| --- | --- | --- |
| (待填) | | |
