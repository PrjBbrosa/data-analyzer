# 批处理内核拆分与稳定性加固 · 设计

- 日期：2026-08-04
- 基线：`main` @ `6236a5fe`（v7.9.3）。**本文所有行号以此 commit 为准。**
- 来源：2026-08-04 批处理架构评审（三路并行结构探查：`batch.py` 内部结构 /
  `batch_render_qt` 渲染层 / 卫星模块与测试覆盖，结论均已在本机核实关键锚点）。
- 实施计划：[2026-08-04-batch-core-decomposition-implementation.md](../plans/2026-08-04-batch-core-decomposition-implementation.md)

## 为什么现在做（收益论证）

维护数据，不是代码审美：

- `batch.py` 近两个月被改 **42 次**，近两周有 **21 条 `fix(batch*)` 提交**；
  这些修复几乎全部落进同一个函数——`BatchRunner.run()`（`batch.py:885-2397`，**1513 行**）。
- `run()` 内有**两套并行实现**：分组路径 684 行（`:1449-2132`）与非分组路径 247 行
  （`:2134-2380`）。同一编排语义（取消、进度、清单记录、异常兜底）要改两遍，
  是近期修复反复回锅的结构性原因。
- 全文件 42 个 `try:` 中约 45% 是 `except Exception`，其中至少 10 处**静默吞掉**
  基础设施失败（如 `record_item` 内部失败 `:1104-1107`、manifest 初始化 `:893-919`）；
  且整个批处理内核**没有任何 logging**——真 bug 被压平成「某个 item 失败了」的字符串，
  连日志痕迹都不留。排查成本直接体现在上面 21 条 fix 的定位时间里。

两步的预期收益：

| 步骤 | 收益 | 量化锚点 |
| --- | --- | --- |
| 第一步（结构拆分） | 变更影响面从 5357 行缩到职责文件；为第二步创造可行性；解开 spool→Qt 隐式依赖；私有渲染契约转正、消除暗雷 | `BatchRunner` 从 4727 行降到 ≈3000 行编排层；拆出的 DSP/IO 段 27/28 个方法本就是 static/classmethod，零行为变化 |
| 第二步（稳定性加固） | 故障留痕（吞异常处全部有日志）；横切逻辑单点实现，修复不再需要「记得改两处」；编排层可单测 | `run()` 从 1513 行降到 <300 行骨架；闭包 6→0；静默吞异常 10 处→0 处 |

## 目标 / 非目标

**目标**

1. `batch.py` 按既有卫星模块的粒度完成「最后一轮拆分」：DTO、DSP 计算、字节 IO 各自成模块。
2. 渲染数据契约（`BatchSeries` 等）中立化，`batch_series_spool` 不再拉起 Qt 门面。
3. `batch.py:126-132` 依赖的 6 个渲染层私有符号转为公开契约。
4. 引入日志兜底；进度发射与结果记录收口成单一 reporter；`run()` 闭包提升、
   两条路径的循环编排方法化。

**非目标**

- 不合并「分组 vs 逐任务」两条产品语义路径（它们的差异是真实的：spool、组渲染、
  组级 resume）。本轮只消除**横切逻辑**的双份实现，「统一单任务计算核心」留作后续可选。
- 不动 preset → recipe → manifest 链路、线程模型、`renderer_import_policy` 边界机制。
- 不改任何输出字节（文件名、PNG、xlsx、manifest schema）。
- 不做渲染层 `_SceneBuilder` 重构与 pg_canvas 去重（评审第三步，另行立项）。
- 公共 API 不破坏：`from mf4_analyzer.batch import AnalysisPreset, BatchOutput, BatchRunner, ...`
  全部保持可用（产品侧 8 处消费者 + 全部测试都走这条路）。

## 现状证据（拆分边界为什么是安全的）

- **DTO 段**（`batch.py:177-446`）：16 个 dataclass/异常，纯数据，无 runner 状态。
- **DSP 段**（`batch.py:4563-5189`）：28 个方法中 **27 个是 `@staticmethod`/`@classmethod`**，
  唯一例外 `_rpm_values`（`:5034`，实例方法，依赖跨源查找状态）。`classmethod` 的 `cls`
  只用于互相调用，不读类状态。段内对 `signal.filters` / `signal.spectrogram` /
  `batch_statistics` 均为函数内惰性 import。
- **IO 段**（`batch.py:5108-5189`）：`_write_dataframe` / `_write_workbook` / `_write_image`
  三个 staticmethod；`_write_image` 惰性 import `batch_render`。
- **附属**：`_Spectro2D`（`:5200-5343`）、`_matrix_to_long_dataframe`（`:5346`）、
  `_guess_rpm_channel`（`:5191`）均为模块级纯计算。
- **测试对私有方法的直接引用**（必须保兼容）：`BatchRunner._compute_fft_dataframe` ×14、
  `._write_image` ×6、`._compute_order_time_spectro` ×4、`._write_workbook` ×3、
  `._compute_fft_time_spectro` ×3 等，共约 39 处。
- **`batch_render_qt/_models.py` 零 Qt import**（已核实：仅 numpy、`..batch_statistics`、
  `._palette` 的一个常量），整体可上移为中立模块。
- **`batch_series_spool.py:12`** `from .batch_render import BatchSeries` →
  `batch_render.py:11` import `batch_render_qt` → `__init__` 拉 `_builder` → PyQt5。
  纯落盘模块因一个 dataclass 绑上了整个 Qt 渲染栈。

## 设计决策

### 第一步 · 结构拆分（D1–D5，逐条零行为变化）

**D1 · DTO 层 → `mf4_analyzer/batch_types.py`**

`batch.py:177-446` 的全部数据类与两个控制流异常（`_BatchCancelled` /
`_ImageBackendUnavailable`）整体移入新模块。`batch.py` 顶部以**显式名单**回导
（不用 `*`），对外 import 路径不变。`AnalysisPreset` 的两个工厂
（`from_current_single:270` / `free_config:295`）随类走；若工厂体内引用了 runner
侧符号，改为延迟 import 或参数注入（实施时核对，不得引入 `batch_types → batch` 的环）。

**D2 · DSP 计算层 → `mf4_analyzer/batch_compute.py`**

`batch.py:4563-5189` 中除 `_rpm_values` 外的 27 个方法降级为**模块级函数**
（去掉 `@staticmethod`/`@classmethod` 装饰，`cls.` 互调改为模块内直呼），
`_Spectro2D`、`_matrix_to_long_dataframe`、`_guess_rpm_channel` 一并迁入。
段内惰性 import 原样保留（`batch_compute` 导入期不得拉起 scipy 重路径之外的东西，
与现状一致）。

- `_rpm_values` 留在 `BatchRunner`（唯一实例方法，跨源状态属于编排层）。
- `_check_cancel` 迁入 `batch_compute`，`_BatchCancelled` 从 `batch_types` import——
  取消语义跟着计算走，签名不变（显式收 `cancel_token`）。
- **兼容别名**：`BatchRunner` 类体内保留
  `_compute_fft_dataframe = staticmethod(batch_compute.compute_fft_dataframe)` 形式的
  全套别名，39 处测试引用零改动。别名段集中放置并注明「兼容层，新代码直接
  import batch_compute」。

**D3 · 字节 IO → 并入 `mf4_analyzer/batch_output.py`**

`_write_dataframe` / `_write_workbook` / `_write_image` 变成 `batch_output` 的模块级
函数（该模块本就管原子写与输出身份，主题一致）。随迁常量：`_XLSX_MAX_DATA_ROWS`、
`_SLICE_CSV_FALLBACK_WARNING`。`_write_image` 对 `batch_render` 的惰性 import 保留在
函数体内——`batch_output` 的导入期无 Qt 性质不变，由既有
`tests/test_batch_render_import_boundary.py` 守护。`BatchRunner` 同样保留别名。

**D4 · 渲染数据契约中立化 → `mf4_analyzer/batch_render_models.py`**

仿照 `qt_chart_fonts.py` ⇄ `batch_render_qt/_fonts.py` 的既有范式：

- `batch_render_qt/_models.py` **整体上移**为顶层 `batch_render_models.py`；
  包内 `_models.py` 变纯再导出 shim，包内其余模块的 `from ._models import ...` 不动。
- `MAX_SLICE_POSITIONS` 常量移入中立模块，`batch_render_qt/_palette.py` 反向引用它
  （解开对包内的最后一条依赖）。
- `batch_series_spool.py:12` 改为 `from .batch_render_models import BatchSeries`——
  纯落盘模块从此不碰 Qt 门面。
- `batch.py` 内对 `BatchSeries` / `BatchTimeFigureSpec` / `BatchRenderContext` /
  `plan_heatmap_slice` 的惰性 import 可改走中立模块（Qt-free，无需再延迟，但保持
  函数内 import 亦可——实施取最小 diff）。
- `batch_render.py` 门面继续再导出全部名字，公共 API 不变。

**D5 · 切片渲染契约公开化 → `mf4_analyzer/batch_render_qt/contract.py`**

`batch.py:126-132` 目前直接 import 6 个私有符号（`_builder._linear_amplitude_label` /
`._render_in_db` / `._slice_clamp_warning`、`_models.plan_heatmap_slice`、
`_page._DEFAULT_METHOD` / `.effective_fact_items`）。新增 `contract.py`，以公开名 +
`__all__` 再导出这些符号（实现留在原处），并在模块 docstring 写明：**这是
batch runner 依赖的稳定契约面，改动需同步 `batch.py:_load_slice_render_contract`**。
`_load_slice_render_contract` 改 import `contract`；ImportError 降级语义
（`batch.py:134-137`）不变。`plan_heatmap_slice` 经 D4 后从中立模块导出，
`contract.py` 转发即可。

### 第二步 · 稳定性加固（D6–D9）

**D6 · 日志兜底**

`batch.py` / `batch_compute.py` / `batch_output.py` / `batch_manifest.py` 各建
`logger = logging.getLogger(__name__)`。凡「捕获后仅记字符串或 pass」的位置一律补
`logger.warning(..., exc_info=True)`。**行为零变化，只加可见性。** 静默点清单
（基线行号，实施时逐条核销）：

| 位置 | 现状 | 处置 |
| --- | --- | --- |
| `batch.py:893-902` manifest 目录初始化失败 | 只发一条 progress event | + log |
| `:904-919` recorder 构造失败 | 同上 | + log |
| `:927-953` recorder 写入失败 | 塞 `manifest_errors` 字符串 | + log |
| `:1104-1107` `record_item` 内部失败 | **完全静默** | 收进 D7 reporter，计数 + log |
| `:1140-1166` resume manifest 解析失败 | 字符串 | + log |
| `:1238-1246`、`:1345-1353` | 静默/字符串 | + log |
| `:1567-1596` spool 建立失败降级 | 字符串 | + log |
| `:2073-2088` 组渲染收尾 | 字符串 | + log |
| `:4585-4588` reference facts | **静默 pass** | + log |

**D7 · 进度与记录收口 → `_RunReporter`**

`batch.py` 内新增小类（不进公共 API），封装三件横切事：

1. `emit(event)`：包掉 16 处散落的 `on_event(BatchProgressEvent(...))` 与旧
   `progress_callback(int,int)` 兼容层；
2. `record(...)`：包掉 `record_item` 闭包（`:1019-1107`）与 recorder 异常兜底——
   失败不再静默，`logger.warning` + 计入 `manifest_errors`（该列表已存在于
   `:922` 并随 `BatchRunResult` 返回，复用，不加新字段）；
3. 取消事件的批量发射（`emit_cancelled_range` 闭包 `:1431`）。

`run()` 构造一个 reporter 实例，两条路径共用——**这是「同一语义两处实现」问题的
主要消除点**：进度/记录行为从此单点定义。

**D8 · `run()` 拆骨架**

分四刀，每刀之后全量批处理测试失败集必须与基线一致：

1. **闭包提升为方法**：`finish_result`(:955) → `_finish_result`，
   `apply_retry_scope`(:1194) → `_apply_retry_scope`，`task_file_name` /
   `cancelled_item` / `planned_group_item` 同理；`record_item` / 
   `emit_cancelled_range` 并入 D7 reporter。闭包捕获的局部量改为显式参数或
   构造进 reporter。
2. **非分组路径**（`:2134-2380`）循环体提为 `_run_sequential(...)`。
3. **分组路径**（`:1449-2132`）拆两个方法：`_run_grouped_compute(...)`
   （逐任务计算循环 `:1605-1937`，含 spool 上下文）与 `_run_grouped_render(...)`
   （逐组渲染循环 `:1942-2088`）。`with spool_context` 保留在 run() 或
   compute 方法内，以最小 diff 为准。
4. 收尾后 `run()` 仅剩：初始化（manifest / recipe 校验 / resume 决策 /
   `_build_run_plan`）→ 按 `render_groups` 分派 → 缓存清理与 `_finish_result`。
   目标 **<300 行、0 闭包**。

**D9 · 异常分类学（审计而非重写）**

对 `run()` 及两条路径中剩余的 `except Exception` 逐处归类三档：

- **预期的 item 级失败**（数据坏、通道缺、后端不可用）：保留 status+message 机制不变；
- **基础设施失败**（manifest IO、缓存 evict、facts 采集）：D6 加日志后维持降级继续；
- **疑似编程错误**（如 `except ManifestRecipeMismatch` 后紧跟的裸兜底 `:1171-1182`）：
  收窄捕获类型或让其浮出到 item 失败，逐处判断并在实施计划中记录结论。

不引入新的 Result/Either 抽象——三层错误语义（校验异常 / status+message / 降级）
本身是合理的，问题只在「静默」和「过宽」。

## 风险与守护

| 风险 | 守护 |
| --- | --- |
| 移动代码引入行为漂移 | 批处理相关测试约 2.5 万行（`test_batch_runner.py` 6450 行为主）；每个任务完成即跑聚焦测试，阶段收尾跑全量并对比**基线失败集**（`main` 上 `tests/ui/` 既有 `test_split_*` 红,先记录再动手） |
| 破坏 GUI-free 边界 | `tests/test_batch_render_import_boundary.py`（子进程投毒法）在每个任务的验证清单里 |
| 测试引用私有方法断裂 | D2/D3 的类级 `staticmethod(...)` 别名策略，39 处引用零改动 |
| 渲染字节漂移 | 本设计不触碰 `_builder.py` 实现（D5 只加再导出层）；切片关闭路径已有逐字节 parity 测试 |
| `AnalysisPreset` 工厂隐藏依赖 | 实施计划 Task 1 内置依赖核对步骤 |
| 与在途工作冲突 | 基线 `6236a5fe` 工作区有未提交的 `signal/expression` 改动，与批处理无交集;本工作独立分支进行 |

## 验收准则

**第一步（D1–D5）**：

1. 全量批处理测试（`tests/test_batch_*.py` + `tests/ui/test_batch_*.py`）失败集与基线一致。
2. `import mf4_analyzer.batch` 后 `sys.modules` 无 Qt/UI（既有边界测试通过）。
3. `import mf4_analyzer.batch_series_spool` 后 `sys.modules` 无 PyQt5（新增断言）。
4. `batch.py` 总行数 ≤ 3400；对外 import 路径全部不变（`grep` 8 处产品消费者零改动）。
5. 输出零字节漂移：跑一次四 kind 冒烟导出,产物与基线逐字节一致（图片可用现有
   parity/冒烟工具核对）。

**第二步（D6–D9）**：

1. 测试失败集仍与基线一致；新增 reporter 行为单测（事件顺序、record 失败计数）。
2. D6 清单 10 处全部核销（每处有 `logger.warning` 或已并入 reporter）。
3. `run()` <300 行、0 闭包；`grep -c "except Exception" batch.py` 较基线（20）显著下降,
   剩余每处在实施计划中有归档结论。
4. 手动冒烟：真实 MF4 跑一次分组 + 非分组批处理,进度条、取消、失败 item 展示与基线一致。
