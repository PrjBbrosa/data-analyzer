# ZFD 长记录鲁棒性执行 Plan

日期：2026-09-09
状态：计划已编写，产品代码未按此计划修改。本次仅文档。
唯一行为合同：[Spec](../specs/2026-09-09-zfd-long-record-robustness-spec.md)

## 1. 执行方式与范围

单一执行者顺序推进 A、B 两阶段，不要求子代理。只处理 ZFD 读取及必要的消费者衔接，不触碰无关预设、Batch 面板、搜索控件等工作区修改。
A 修复确认缺陷；B 完成结构化读取、可信时基与明确失败。A 完成不能替代 B 的验收；本计划不授权发布、提交或推送。

本次文档 gate：全文、引用、合同覆盖及 `git diff --check`。没有可执行变更，不再运行 runtime suite。

实现时统一命令前缀：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <focused files> -q
```

## 2. 步骤 0：记录现场与冻结回归输入

Owner：执行者；只读代码，证据放 `.state/zfd-robustness/`。

- 记录 HEAD、`git status --short` 和本次 owner 文件差异；禁止覆盖别的任务修改。当前 Spec 基于 `ff705ead96f08dfb916d933e9c04a17f2de440b68` 及当日工作区。
- 对照 `zfd_format.py`、`testdoc/zfd_import.m`、移植脚本、`FileData`、GUI ZFD 分支、source adapter 的真实实现，确认 Spec 引用未漂移。
- 查看现有 pytest 进程及 cwd，避免与同 checkout 的集成门禁冲突。只跑 `tests/test_zfd_format.py` 的受影响 baseline，不跑全套。
- 重现六份真实样本的 type、count、X 引用与时间单位；保留简明 JSON 对照，包含样本路径/哈希。文件缺失时 A4 标为未验证，不用 skip 数量冒充兼容通过。

Gate：明确原厂 `int32` 与产品 `<H` 差异；已有样本仍落在 Spec profile 内。若发现真实样本属于 profile 外，先修订 Spec 支持边界，不直接增加猜测路径。

## 3. 步骤 1 / A：先用长记录红测固定点数缺陷

Owner 文件：`tests/test_zfd_format.py`；必要时新增 `tests/zfd_fixtures.py` 作为无运行期依赖的测试构造器。

- 写符合原厂布局的完整头/type 0/type 4 fixture，点数用 `struct.pack('<i', count)`，不复用当前把 count 编为 H 的错误假设。
- 参数化 A1；添加 A2 小时级用例，前中后设可检查特征，验证所有点数、末点和真实跨度。至少一例真实调用 `DataLoader.load_zfd`→`FileData`，不是直接 mock 返回组。
- 添加 A3 的零/负/超大声明和末尾截断；记录修复前失败原因。
- 大用例一个代表性通道即可，不在每个测试生成多通道百万点数组；不提交大二进制样本到 Git。

Gate：65,536 点、65,537 点及小时级用例稳定暴露错误，红测失败来自点数/完整性，不是 fixture 格式错误。正常 fixture 可被参考移植读取，数值期望独立计算。

## 4. 步骤 2 / A：修复 32 位读取与长度校验

Owner 文件：`mf4_analyzer/io/zfd_format.py`、上述测试。

- 把普通通道 count 改为小端 signed int32，修正误导性格式注释。
- 分配前校验声明 count 和数据区字节边界。已识别测量记录截断时抛明确错误；不能把末条损坏通道当成假 marker 跳过后仍成功。
- 不扩大类型支持；先保留现有时间路径，阶段记录明确 dt 回退等风险仍未消除。
- 按 A4 比较六份真实样本；保留原有七通道锚点、重名和端到端测试。

Focused：`tests/test_zfd_format.py`、`tests/test_io_load_notices.py`。
Gate：A1/A2/A3 点数相关部分通过；A4 无退化。若旧 marker 路径不能可靠区分结构损坏与假候选，不堆启发式，步骤 2 与步骤 3 合并完成后再认领 A3；记录为 partial。

## 5. 步骤 3 / B：按声明记录解析受支持 profile

Owner 文件：`mf4_analyzer/io/zfd_format.py`、`tests/test_zfd_format.py`、fixture helper。

- 先补 A5/A7/A8 的结构红测：头行/注释截断、通道数不足、未知/整数类型、多个时间记录、错误 X 引用、数据区及尾区伪 marker。
- 在原 owner 中加入带 offset 的精确读取辅助函数，逐条验证长度。无需另建通用二进制框架。
- 按 Spec §4 解析 header、annotations、type 0/4，所有声明记录确认完整后才构造 DataFrame。不导入 `tools/matlab_ports`，不保留猜测扫描 fallback。
- 保留有 marker 名字的显示行为，补无 marker、同名 Time、重复 marker 的身份/消歧测试。
- 记录 trailing_bytes；不把非测量尾区解释成通道，也不声称尾区语义已支持。

Focused：`tests/test_zfd_format.py`。
Gate：A3 结构部分、A5、A8、A9 命名部分通过；六份真实样本再次比较仅因解析实现已变化。未知类型立即失败，不能绕过变成成功组。

## 6. 步骤 4 / B：时基事实、metadata 与消费者一致

Owner 文件：`zfd_format.py`、`mf4_analyzer/io/file_data.py` 的窄 ZFD 适配；必要时 `mf4_analyzer/io/source_adapters.py` 与 `mf4_analyzer/ui/main_window/_project_io_mixin.py` 只接入共用构造事实。

- 先补 A6/A7/A9/A10：非零起点、慢采样、单点、NaN/Inf 测量值、单位和时间可表示性、metadata 与数组一致。
- 构造 `t0 + arange(n)*dt`；不丢 t0，不因一点记录缺 diff 而回退默认 Fs；禁止借用重建时间轴路径覆盖文件时间。
- 明确按 Spec 单时间轴/同 count 验证；成功元数据统一输出 `zfd_import`，不把两种 dt 算法分散到 GUI 和 adapter。
- 移除自动 1 kHz 回退及 3,600 秒 dt 上限。`dt=7200` 应加载；非法 dt 应报错。这是有意的产品行为变更。
- 保持 group identity 和公开返回字段兼容；不扩展到多时间轴项目迁移。

必须同步旧测试：

| 现有测试/fixture | 处理 |
| --- | --- |
| `_write_minimal_zfd` / `_write_zfd_duplicate_names` | 改为完整格式 fixture；保留其他测试的导入入口或同步全部调用者 |
| `test_zfd_dt_above_hour_falls_back_to_estimated_1khz` | 改为合法超慢时基保留；新增非法 dt 拒绝，不保留旧回退断言 |
| `tests/ui/test_project_session.py::test_load_zfd_estimated_fs_toasts_estimate_wording` | 改为非法时基拒绝/不注册与合法慢采样加载两类行为 |
| `tests/test_io_load_notices.py` 的通用 formatter 单测 | 公共 formatter 仍兼容时可保留；不能据此要求新 ZFD 生成估算时基 |

Focused：`tests/test_zfd_format.py`、`tests/test_source_adapters.py`、`tests/test_io_load_notices.py`、`tests/test_file_data_time_axis.py`、`tests/test_file_data_audio.py`；后两项保护现有时间列、手动重建及显式 Fs 行为，不能只跑新 ZFD 分支。
Boundary：`tests/ui/test_import_boundaries.py`、`tests/test_signal_no_gui_import.py`。若改变 MainWindow 衔接，加 `tests/ui/test_main_window_state_ownership.py`。
Gate：A6/A7/A9/A10 通过，GUI 与 adapter 对同一 fixture 返回相同 n/t0/dt/Fs；无新增 GUI 反向依赖。

## 7. 步骤 5 / B：加载失败、Batch 与帮助

Owner 文件：`tests/ui/test_project_session.py`、`tests/test_source_adapters.py`、`tests/test_batch_source_integration.py`；必要的产品错误衔接仅改现有 owner。帮助仅 `ui/hints.py`、`ui/quickref.py` 及当前说明。

- 先测末通道损坏、时基错误在 GUI 中不新增源、不发成功提示，已有源/选择不受损；项目恢复时诊断不被吞掉。
- 用真实 ZFD 临时文件测试 adapter probe/load 失败，而非只有 mock registry。
- 用一坏一好两个输入测试 Batch：坏文件产生现有失败结果，好文件继续；坏项没有成功分析产物。使用现有 `_RunReporter`，不新建 emit/record 支路。
- 错误带文件、记录与长度上下文；复用 toast/加载错误表面，不新增弹窗或状态管理器。
- 更新帮助的支持范围和时基失败说明，检查当前说明中 `ZFD`/`1 kHz`/`估算` 的旧行为，历史资料保持原样。

Focused：`tests/ui/test_project_session.py -k zfd`、`tests/test_io_load_notices.py`、`tests/test_source_adapters.py`、`tests/test_batch_source_integration.py`、`tests/ui/test_hints.py`、`tests/ui/test_quickref.py`。新增项目恢复用例名称包含 zfd，以便被 focused 选择。
Boundary：若更改 Batch orchestration，运行 `tests/test_batch_run_reporter.py`；若修改 UI 信号连接，运行 `tests/ui/test_no_lambda_signal_connections.py`。改变帮助 HTML 时追加 `tests/test_help_content.py` 的相关用例。
Gate：A11；hints/quickref 含一致的受支持范围与失败规则，未引入新的控件或 QSS 变化。

## 8. 步骤 6：整合与前台验收

Owner：同一执行者。

- 整合后只补跑受后续编辑影响的 focused/boundary，不为了“更保险”重复全部已通过测试。本轮不要求 full suite；若后续明确进入发布/大范围整合，再由一个执行者遵循仓库双进程顺序 full gate。
- Cocoa 前台启动当前工作区程序，加载 3,608,000 点合成文件，展示 Time 轴完整范围与尾部特征；验证非零起点/一点记录，并打开一个无效文件确认错误与旧源保留。采集实际范围值及截图到 `.state/zfd-robustness/`；已有开着的旧进程不充当新实现证据。
- 不修改用户文件。探针生成的文件用完清理；证据与脚本保留在 `.state/`，不提交生成大文件。
- 逐条填写 Spec A1–A12 的结果、命令/证据路径、未完成项。原用户文件同因确认保持 UNKNOWN，找到后对照源软件实际点数/Fs/起止时刻再验收。
- `git diff --check`、owner scope 审查、检查 lessons 状态。实现产生可复用的二进制字段宽度/长记录边界教训时按 project-lessons 流程沉淀；文档阶段不提前声称已修复。

Gate：A12 有实际前台证据；否则整体状态标 partial 并点明剩余门禁。无需为原文件缺失再阻断已授权的确定缺陷修复。

## 9. 风险与停止扩展条件

- **格式支持收紧**：旧扫描器可能偶然读过 profile 外文件；新实现会明确拒绝。不得为了维持“能打开”恢复猜测路径。遇到新增真实样本先保留并分析，再修订 Spec。
- **参考脚本不等于完美实现**：正确文件可用其对照；边界错误、非零起点与资源安全用独立预期验证。
- **大记录内存**：先校验长度，控制测试通道数；不以截短解决内存压力。真实大文件性能问题另有测量后再扩展读取架构。
- **已有工作区修改**：hints/quickref、项目恢复测试等可能已有他人改动，只编辑本任务片段，最终 scope 按 diff 审查。
- **无法确认原用户文件**：可完成通用缺陷修复，不能报告其数据已恢复或现场原因已闭环。
