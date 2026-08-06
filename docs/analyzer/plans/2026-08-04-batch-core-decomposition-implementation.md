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

- [x] **Step 1:** 四个模块建 `logger = logging.getLogger(__name__)`。
- [x] **Step 2:** 按 spec D6 表格逐条核销 10 处静默点(`record_item` 处留到 Task 7),
  每处 `logger.warning(..., exc_info=True)`,**不改变任何控制流**。
- [x] **Step 3:** 验证:失败集与基线一致。

> **补记(Task 9 Step 1b):** D6 表格里「`:1567-1596` spool 建立失败降级」的**文字描述**
> 指的是 `validate_group_shape` 的 `except ValueError`,但行号落在了隔壁的
> `upsert_render_group` 上,Task 6 因此只补了后者;另有一处 D6 表格从未列出的
> `upsert_render_group`(组循环中把组标成 `'running'` 的那次)同样静默。两处已由
> Task 9 的 `02d1f420` 按同一范式补 log,控制流不变。

Run: `PYTEST tests/test_batch_runner.py tests/test_batch_manifest.py -q`

### Task 7: `_RunReporter` 收口(D7)

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Create: `tests/test_batch_run_reporter.py`

- [x] **Step 1:** 先写失败测试:reporter 的 `emit` 事件顺序、`record` 在 recorder 抛错时
  计数进 `manifest_errors` 并 `logger.warning`(用 caplog 断言)、旧
  `progress_callback(int,int)` 兼容层仍被调用。
- [x] **Step 2:** 实现 `_RunReporter`(batch.py 内部类,不进公共 API):吸收
  `record_item` 闭包(`:1019-1107`)、16 处 `on_event(...)` 发射、
  `emit_cancelled_range`(`:1431`)。`run()` 构造单实例,两条路径共用。
- [x] **Step 3:** 验证。

Run: `PYTEST tests/test_batch_run_reporter.py tests/test_batch_runner.py tests/ui/test_batch_runner_thread.py tests/ui/test_batch_task_list.py -q`

### Task 8: `run()` 拆骨架(D8)

**Files:**
- Modify: `mf4_analyzer/batch.py`

四刀,**每刀一个 commit + 全量批处理测试对比基线**:

- [x] **Step 1:** 剩余闭包提升为方法:`finish_result`(`:955`)→`_finish_result`、
  `apply_retry_scope`(`:1194`)、`task_file_name`(`:1389`)、`cancelled_item`(`:1398`)、
  `planned_group_item`(`:1498`)。捕获的局部量改显式参数。
- [x] **Step 2:** 非分组路径(`:2134-2380`)提为 `_run_sequential(...)`。
- [x] **Step 3:** 分组路径拆 `_run_grouped_compute(...)`(`:1605-1937`,spool 上下文
  归属取最小 diff)与 `_run_grouped_render(...)`(`:1942-2088`)。
- [x] **Step 4:** ~~确认 `run()` <300 行~~、0 闭包;跑全量。——「<300 行」未达成,
  见下方第二步执行记录的偏差条目。

Run: `PYTEST tests/test_batch*.py tests/test_frozen_batch*.py tests/ui/test_batch*.py -q`

### Task 9: 异常分类审计(D9)+ 收尾

**Files:**
- Modify: `mf4_analyzer/batch.py`
- Modify: 本文件(记录审计结论)

- [x] **Step 1:** 对 `batch.py` 剩余每处 `except Exception` 归档三档结论
  (item 级失败 / 基础设施降级 / 收窄类型),在下方审计表逐行记录;能安全收窄的收窄
  (如 `:1171-1182` 的裸兜底)。——结论:**一处都没收窄**,逐条理由见审计表。
- [x] **Step 2:** 全量批处理测试 + boundary test;`grep -c "except Exception"` 记入审计表。
- [x] **Step 3:** ~~手动冒烟~~ → 改做**真实 MF4 的字节级 A/B**(比手动冒烟更强且可复跑),
  详见第二步执行记录。
- [x] **Step 4:** 复核 `CLAUDE.md` 架构段 —— `batch*.py` 的 glob 覆盖 D1–D4 新增的
  `batch_types.py` / `batch_compute.py` / `batch_render_models.py`,「GUI-free runner +
  Qt 渲染导出」的分工描述仍然成立,**无需改动**。

### 审计表

按「函数名 + 代码锚点」定位,**不用裸行号**——本文件的行号已经在六轮改动里失效过。
`ValueError` 两行是 Step 1b 顺带归类的近邻分支,一并列出以免下一个人重新推一遍。

| # | 位置(函数 + 代码锚点) | 归类 | 处置 |
| --- | --- | --- | --- |
| 1 | `_RunReporter.record` — `recorder.record(entry)` | 基础设施 | 保留。清单条目写失败不该杀掉整轮跑;T6/T7 已加 log + 计入 `manifest_errors`。 |
| 2 | `run` — `output_dir.mkdir(parents=True, exist_ok=True)` | 基础设施 | 保留。`OSError` 家族十余个子类(含本仓库常见的 macOS TCC `PermissionError`),窄化只会漏;已 blocked + log。 |
| 3 | `run` — `recipe_id = recipe_fingerprint(...)` | 坏 preset / 疑似编程错误 | 保留。`normalize_batch_params` 对畸形 preset 会抛 `ValueError`/`KeyError`/`TypeError` 三类,都必须落成 blocked 而不是穿透到 GUI 线程;已 log。 |
| 4 | `run` — `BatchManifestRecorder(...)` + `recorder.start()` | 基础设施 | 保留。磁盘 / 权限 / JSON 序列化三类失败,已 blocked + log。 |
| 5 | `run` — resume 分支 `load_batch_manifest(candidate)` | 基础设施 + 坏数据 | 保留。段内除 `ManifestValidationError`(`ValueError` 子类)外还有 `directory.glob` / `path.stat()` 的 `OSError` 与 `Path()` 的 `TypeError`;已 log。 |
| 6 | `run` — retry 分支紧跟 `except ManifestRecipeMismatch` 的裸兜底 `blocked=[f"cannot load retry manifest: {exc}"]` | 基础设施 + 坏数据 | **计划点名的收窄候选,评估后保留**,理由见表下「关于第 6 行」。 |
| 7 | `run` — `self._expand_tasks(preset, allow_source_load=False)` | 坏数据 / 坏 scope | 保留。展开要读通道表、解析 pattern、可能触发 IO;已 blocked + log。 |
| 8 | `run` — `_ImageBackendUnavailable` 分支内 `recorder.upsert_render_group(..., status='failed')` | 基础设施 | 保留降级。**仍无 log**,见表下「遗留」。 |
| 9 | `run` — `self._expand_tasks(preset, allow_source_load=True)` | 同第 7 行 | 保留,已 log。 |
| 10 | `run` — 组预循环 `recorder.upsert_render_group(... 'done'/'degraded'/'pending')` | 基础设施 | 保留,T6 已 log。 |
| 11 | `_run_grouped_compute` — 单任务 catch-all(`data_reservation.release()` → `status='failed'`) | **预期的 item 级失败** | 保留。这正是「数据坏 / 通道缺 / 后端不可用」的落点,status+message 机制原样不动。 |
| 12 | `_run_grouped_render` — 组循环中 `upsert_render_group(..., status='running')` | 基础设施 | 保留;**Task 9 Step 1b 补 log**(D6 表格漏项)。 |
| 13 | `_run_grouped_render` — `self._render_group(...)` → `RenderGroupResult(status='failed')` | 预期的组级失败 | 保留。与第 11 行同档,只是粒度是组。 |
| 14 | `_run_grouped_render` — 组收尾 `upsert_render_group(..., status=outcome.status)` | 基础设施 | 保留,T6 已 log。 |
| 15 | `_run_sequential` — 单任务 catch-all | 预期的 item 级失败 | 保留。非分组路径的第 11 行对应物。 |
| 16 | `_finish_result` — `recorder.finish(...)` + `derive_summary(recorder.entries)` | 基础设施 | 保留降级(追加 `blocked` + `done`→`partial`)。**仍无 log**,见表下「遗留」。 |
| 17 | `_load_physical_sources` — 加载 + `_normalize_loaded_sources(...)` | **不是吞异常** | 保留。`except` 体末尾是裸 `raise`,只做「把失败缓存成 `_LoadFailure`」的记账;窄化会让部分失败不进缓存,同一物理文件被反复重载。 |
| 18 | `_resolve_task_file` — `self._load_physical_sources(...)`(已带 `# noqa: BLE001`) | 预期的 item 级失败 | 保留。任何加载失败转 `_LoadFailure`,由调用方变成该 item 的 `failed`;宽是刻意的,`noqa` 就是当初的声明。 |
| 19 | `_compute_group_task` — `spool.append(...)` 的 catch-all | 预期的 item 级失败 | 保留。同一 `try` 里 `ValueError`→`blocked`、`_BatchCancelled`→`raise` 已各自分流,三档语义本就分好了。 |
| V1 | `run` — `spool_module.validate_group_shape(...)` 的 `except ValueError` | 基础设施降级 | 保留控制流;**Task 9 Step 1b 补 log**(D6 表格描述的就是它,行号却指向了第 10 行)。 |
| V2 | `_compute_group_task` — `spool.append(...)` 的 `except ValueError` | 预期的 item 级失败 | 保留。`ValueError` 是 spool 的配额 / 形状契约,转 `blocked` 是产品语义不是意外。 |

**关于第 6 行(计划点名的收窄候选):结论是保留,不收窄。** 三条理由:

1. **可收窄的类型集本身就不窄。** `load_batch_manifest` 把 JSON 解析错误统一转成
   `ManifestValidationError`(`ValueError` 子类),但 `path.read_text()` 会抛
   `OSError` / `UnicodeDecodeError`,`Path(path_or_manifest)` 会抛 `TypeError`,
   `retry_failed_scope` 在 `render_groups` 缺 `group_id` 时会抛 `KeyError`。
   写成 `except (ValueError, OSError, TypeError, KeyError)` 与 `except Exception`
   实际覆盖面几乎相同,只多了一份会腐化的清单。
2. **漏网的那一类会退化成更差的行为,而不是更响的失败。** 这里不是「让它浮出到 item
   失败」——`run()` 里没有更外层的 item 兜底。异常逃出 `run()` 后:`_finish_result`
   不会执行 → `recorder.finish()` 不写最终清单、`batch-manifest__*.partial.json`
   留在盘上;`run_finished` 事件不发 → 任务列表停在 running 态;
   `BatchRunnerThread.run` 的 `except Exception`(`ui/drawers/batch/runner_thread.py`)
   把它变成 `runner crashed: ...`,用户看到的信息比现在的
   `cannot load retry manifest: ...` 更少。
3. **D9 的原意已经由 Task 6 满足了。** 「疑似编程错误被压成字符串」的真正代价是查不到,
   而不是捕获得宽;可见性由 log 解决,控制流没有需要改的地方。

**遗留(明确记录,不在本任务的两处补 log 范围内):** 第 6、8、16 行三处至今没有
`logger.warning`——它们都不在 D6 表格里,Task 6 因此没碰,Task 9 的授权范围也只包含
Step 1b 点名的两处。三处的控制流都正确,缺的只是可见性;下一次碰批处理清单代码时
按同一范式补上即可(参数:第 6 行 `retry_failed_manifest`、第 8 行 `group_id`、
第 16 行 `run_status`)。

**`except Exception` 计数:基线 20 → 现 19。** 这 1 的减少来自 Task 2 的模块搬迁
(`channel_reference_facts` 连同它的 `except Exception` 迁进了 `batch_compute.py`),
**不是收窄**——`batch.py` + `batch_compute.py` 合计仍是 20。设计文档验收准则里的
「较基线显著下降」因此未达成;这是第二个标定偏差,与 ≤3400 行、<300 行同源,
详见下方执行记录。

---

**第二步执行记录(2026-08-05):**

| 项 | 结果 |
| --- | --- |
| commit | `97e924f9` (T6) · `fff82338` (T7) · `5200ff1d` / `c5cdecf9` / `4ca85215` / `63cb7bbc` (T8 四刀) · `02d1f420` (T9 代码) |
| 全量批处理测试 | **3 failed / 1187 passed** —— 失败集与基线**逐条一致**(仍是那三条既有失败;passed 比基线 1168 多 19,是第一步两条 Qt 边界断言 + T7 新增的 `tests/test_batch_run_reporter.py` 17 条) |
| Qt 边界 | `tests/test_batch_render_import_boundary.py` 3 passed |
| 事件预言机 | 单文件双通道 · 分组 / 非分组 / 取消三轮的完整事件序列 + 结果快照,与 D7 开工前(`97e924f9` 树态,T6 之后 / T7 之前)捕获的黄金文件 **`diff` 为空**;T7 / T8 / T9 四次复跑哈希全同 |
| 真实 MF4 字节级 A/B | 见下 |
| `run()` 形状 | **605 行、0 具名闭包**(仅剩 resume 清单排序的一个无捕获 `key=lambda`);T8 收尾时 599 行,本任务的 spool 形状校验日志加 6 行 |
| `grep -c "except Exception" batch.py` | 20 → **19**(见审计表末尾:唯一的减少是模块搬迁,不是收窄) |
| `wc -l batch.py` | 4445(第一步收尾)→ **4801**(T7 的 `_RunReporter` + T8 的方法签名/docstring 回填) |

**真实 MF4 字节级 A/B(替代计划 Step 3 的手动冒烟)。** 计划原本要求「真实 MF4 手动
冒烟一轮」,这里改成可复跑的双树对照,判据从「看起来一样」升级为「字节一样」:

- 对照组:`git worktree add --detach` 出 `b886a30e`(Task 0 的父提交,重构前)。
- 数据:`testdoc/yuandi.MF4`(533 KB,8922 × 25),取 4 个真实 EPS 扭矩通道
  (`Rte_TAS_mTorsionBarTorque_xds16` / `Rte_SteerCtrl_mNomMotTrq_xds16` /
  `Rte_PA_mAtMotorTorque_xds16` / `Rte_FricComp_mFricCompMotTorq_xds16`,同为 `Nm`,
  以免撞上「时域图最多两种 y 单位」的护栏)。
- 四轮:分组(`render_group_by='source'`)、非分组、分组取消、非分组取消;
  每轮都开 `export_data` + `export_image`,取消点由 `on_event` 在第 2 个
  `task_started` 上置 token,两棵树因此在同一位置取消。
- 比对:16 份产物的 SHA-256、32 条进度事件的全字段序列、16 条 item 的
  status/message/task_id/产物名、2 条组结果,外加剥掉 `run_id` 与时间戳后的完整
  manifest JSON。
- 结果:**逐字节一致**(唯一需要归一化的是输出根目录的绝对路径前缀——两棵树按构造
  写进不同目录)。分组轮的组图 `yuandi__time__320ea5e2.png`、非分组轮的 4 张单图、
  两轮取消的部分产物,SHA-256 全部相同。

关于「验真机渲染」纪律:本仓库要求**视觉 / UI** 结论必须走真实渲染而不是 offscreen。
这里的判据不是视觉相似而是**输出字节相同**,由 SHA-256 直接判定,比人眼核对一张图更强,
因此 offscreen 在这条结论上不构成弱化。

**偏差:D8 的 `run()` <300 行不可达(已接受,不再追)。** 「0 闭包」达成,「<300 行」没有。
算术上:`run()` 现在 605 行,其中约 389 行是初始化(输出目录 / recipe 指纹 / 清单
recorder / resume 与 retry 决策 / 任务展开 / `_build_run_plan` / 生效输出解析),
另有约 120 行是必须先于 spool 上下文完成的分组预处理(`group_for_task`、
`group_recovery`、可复用条目、组形状校验与初始清单状态),真正的分派只剩约 66 行
(签名 + docstring 另占 28 行)。
而 **D8 Step 4 本身就写明 `run()` 应当「保留初始化」**——目标数字与目标形状互相矛盾,
这是与第一步 ≤3400 行同一类的标定失误(见 Task 5 的偏差记录),不是执行没做到。
**未为凑数字做计划外抽取。** 自然的后续是把那段初始化整体抽成
`_prepare_run(...)`(返回一个 run-context 对象或具名元组),`run()` 即可落到 200 行
以内;那是一次独立的、有自己验证面的改动,不塞进本轮。

**本轮已知未做的事:** 审计表第 6、8、16 行的 log 补齐(理由见「遗留」);
`except Exception` 计数的实质性下降(审计结论是无处可安全收窄);
`batch.py` ≤3400 与 `run()` <300 两个数字目标(标定失误,已如实记录)。
`CLAUDE.md` 架构段经复核无需改动。
