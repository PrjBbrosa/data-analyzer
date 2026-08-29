# WWT WinWert 导入正确性加固计划

- 日期：2026-08-28
- 状态：已实施（产品/测试合入 `wwt-followup-integration` @ `5e46059a`；文档收口为本 Task 6）
- 修复基线：`main@676e96a3`
- 对应已实施规格：
  [`2026-08-28-wwt-winwert-layout-import-spec.md`](../specs/2026-08-28-wwt-winwert-layout-import-spec.md)
  （原合同未改写；加固项补在 §17）
- 对应已实施计划：
  [`2026-08-28-wwt-winwert-layout-import-implementation.md`](2026-08-28-wwt-winwert-layout-import-implementation.md)
  （历史步骤保留；顶部与文末注明本波次交付，并纠正 testdoc 夹具假设）
- 范围：只修复 WWT 导入、时域逐曲线绑定、项目恢复、诊断分级、native tick 防护与可复现测试
- Task 5 验证记录：`.state/wwt-followup-task5-report.md`

> 本文档是针对 `1cb54ca..676e96a3` 已落地实现的后续修复计划，不重做原功能，不扩展 WinWert 语法范围。

**本波次合入：** `9efb35d8` · `7dcf64f5` · `8810844a` · `5a43782b` / `5e46059a`。
聚焦 + 边界门禁通过。两段全套与真实前台六项仍为 **UNVERIFIED**（见 Task 5 报告）。

## 1. 一句话结论

当前 WWT 主路径已经能解析并创建布局，但还不能作为稳定交付接受：项目重开时可能丢失 record 数据，绑定失败或取消勾选后可能落回普通 Time-Y 曲线，黄色提示把“已保留的辅助记录”误报为“未导入”，真实降级又可能没有统一出口，native tick 在极端数值下也能在上限判断前溢出。修复应先建立不依赖本机客户文件的合成 WWT 测试，再分别收紧数据所有权、曲线声明语义、诊断分级和刻度枚举边界。

完成后必须同时满足：

1. 导入 WWT、保存项目、退出并重开后，channel-backed 与 record-only X/Y 绑定仍解析到原数据。
2. 某条 WWT 绑定解析失败时，不得把同一个 Y 通道静默画成普通 Time-Y 曲线。
3. 用户取消勾选 channel-backed Y 后，该 WWT 曲线立即隐藏；重新勾选后按原 X/Y 绑定恢复。
4. 已进入 `wwt_record_store` 的辅助 record 不再触发黄色“通道未导入”。
5. 不支持的显示、未知 record、长度不齐、窗口截断、布局上限等真实降级有且只有一个可见且可追踪的出口。
6. 用户已经在确认框接受 exact overlap 后，不再重复收到同一件事的黄色提示。
7. 对有限数值输入，native tick 在枚举前证明候选数受限；不得溢出，也不得先分配超大列表再检查 2000 条上限。
8. 在仓库不存在 `testdoc/WWT` 客户样本的干净 checkout 中，WWT owner 测试可完整运行，不以缺文件失败或跳过核心行为。

## 2. 当前证据与问题分级

### 2.1 基线事实

- 审查范围为 `1cb54ca..676e96a3`，共 8 个提交；当前 `main` 与 `origin/main` 同步。
- 当前真实样本 `SFNS_10_DC2E_0011.wwt` 可解析为 2 个 group、8 个 record、1 个 window，且文档级诊断为空。
- 该样本的建议曲线为 Rack Force(Y) 对 Rack Travel(X)，两个方向都由 channel reference 驱动。
- 当前实现把 `Upper limit`、`Lower limit`、`Line_X` 记入 `skipped_channels`，随后以黄色“3 个通道未导入”提示；但这些 record 已保存在 record store 中，因此提示语义与数据事实不一致。
- WWT 聚焦测试当前结果为 92 passed、15 failed、12 skipped；15 个失败都来自 3 个本机 `testdoc/WWT` 样本缺失，而 `.gitignore` 明确忽略 `testdoc/`。

### 2.2 P1：必须先修的正确性问题

| 编号 | 问题 | 当前根因 | 用户可见影响 |
| --- | --- | --- | --- |
| P1-1 | 项目恢复丢失 record store | `wwt_record_store` 只在 `WwtImportCoordinator.offer_layout()` 中临时写回 source metadata；项目恢复期间该协调器被跳过 | record-only X/Y 重开后成为 `missing_record`，同一项目不能复现 |
| P1-2 | 绑定失败后画错普通曲线 | `bound_time_plot_rows()` 只把成功的 channel-backed Y 加入 consumed 集合；失败绑定的 Y 随后进入普通 Time-Y 循环 | 用户看到“有曲线”，但 X 轴与 WWT 定义不一致，属于静默错误 |
| P1-3 | Navigator 取消勾选不隐藏绑定 | 当前逐曲线绑定直接遍历持久化 binding，没有把当前 View 的 checked channel 集合当作 channel-backed Y 的可见性条件 | 用户操作与画面不一致，无法用 Navigator 控制导入曲线 |
| P1-4 | 测试依赖本机且被忽略的客户样本 | 新测试直接读取 `testdoc/WWT/*.wwt`，缺失时 `pytest.fail` | 干净 checkout 和 CI 无法验证实现，当前绿色证据不可移植 |

### 2.3 P2：同一修复波次完成的健壮性问题

| 编号 | 问题 | 当前根因 | 用户可见影响 |
| --- | --- | --- | --- |
| P2-1 | 黄色提示语义倒置 | “保留为辅助 record”与“真正无法导入”共用 `skipped_channels` | 正常打开也出现黄色报警，用户无法判断是否真的丢数据 |
| P2-2 | 提示出口不完整且有重复 | coordinator 只处理 cap/overlap；document/proposal warning 的 outcome 未统一消费；exact overlap 在确认后又 toast | 有的问题重复报，有的问题不报，提示无法作为验收证据 |
| P2-3 | native tick 上限判断过晚 | `_values_for_step()` 先构造完整列表，再检查 grid 数；major tick 无等价上限 | 极端 range/step 可抛 `OverflowError` 或产生不可控分配 |

### 2.4 当前不能作为验收证据的内容

- 本机客户 WWT 文件存在，不等于干净 checkout 或 CI 具备相同文件。
- 解析器单测通过，不等于项目保存/重开后的数据绑定可复现。
- 出现黄色 toast，不等于用户得到准确诊断；必须验证严重度、文案、次数和持久化位置。
- stylesheet、静态代码和 offscreen Qt 均不能替代真实前台对 Navigator、曲线、提示和交互的验收。

## 3. 实施原则与非目标

### 3.1 必须保持的原则

1. **数据先于布局**：record store 属于 WWT 文档加载结果，不属于“用户是否接受布局”的 UI 分支。
2. **解析失败不猜测**：绑定失败必须保留明确 issue/placeholder，不得退化为普通 Time-Y。
3. **身份与显示分离**：继续使用复合 source/channel identity；显示名不能成为匹配键。
4. **采集时间语义不变**：channel-backed 数据继续沿用现有 acquisition-time mask 和对齐规则。
5. **恢复是单次事务**：数据恢复、binding 重建、X/Y limits、ticks 与最终 settle 只按既有顺序执行一次。
6. **诊断可观察**：同一个事实只产生一个主诊断；UI 提示、持久化 view issue 和日志各有明确职责。
7. **中性层保持可导入**：WWT parser、document、formula 与 tick policy 不得新增 MainWindow 或 UI 包反向依赖。
8. **最小所有权修改**：若需要新增状态，优先放入现有 document result、binding result 或 coordinator，不扩大 MainWindow 多文件写入白名单。

### 3.2 本波次明确不做

- 不新增 WWT canvas、项目 schema 版本或新的产品级 mutable state。
- 不扩展 WinWert 公式、未知 record 类型或导出语法。
- 不把客户 WWT 文件提交进仓库，也不复制其原始名称、测量值或业务内容到测试夹具。
- 不重做 custom X 编辑器、Navigator、View 管理器或 UltraView 微网格。
- 不改变非 WWT 文件的通用加载提示语义。
- 不改变 time-domain ink、AA、raster、150 ms idle timer 或 envelope 阈值。
- 不清理本任务无关的 dirty worktree，不自动 commit/push。

## 4. 关键技术决策

### D1. record store 由加载层拥有

`load_wwt_document()` 负责构造一次不可变的 record tuple/store，并把同一份 store 引用注入该物理 WWT 展开的每个 `LoadedSource.metadata`。coordinator 只消费 proposal，不再补写数据。

这样覆盖四条路径：

- 接受布局；
- 拒绝布局但保留加载数据；
- WWT 没有可用 display/window；
- 项目恢复时禁止弹出导入确认框。

多 group source 必须共享同一 record tuple，不复制大数组；项目序列化仍只保存 source/session 所需内容，不能把 ndarray 展开进 JSON。

### D2. binding 返回“声明”和“成功”两种集合

把当前二元返回值收敛为一个 UI-neutral 结果对象，例如：

`BoundTimePlotResult(rows, issues, claimed_channel_keys, successful_channel_keys)`

- active binding 一旦声明某个 channel-backed Y，就先进入 `claimed_channel_keys`。
- X/Y 解析、长度或时间对齐成功后，才进入 `successful_channel_keys` 并产生 row。
- MainWindow 普通 Time-Y 路径跳过 **claimed**，而不是只跳过 successful。
- 失败 binding 产生可见 issue/placeholder；不得回落到同 Y 的普通曲线。

### D3. channel-backed binding 服从当前 View 勾选状态

- channel-backed Y 只有在当前 View 的 checked composite key 中才 active。
- 取消勾选后不画该 binding；重新勾选后按持久化 X/Y 绑定恢复。
- record-only Y 没有 Navigator channel 身份，继续遵循导入时的可见性，不在本波次新增 record-only 开关 UI。
- 当前 View 新勾选、但没有被 WWT binding 声明的通道，仍追加为普通 Time-Y 曲线。

### D4. 诊断按事实分层，不再按实现分支拼接

统一定义三类结果：

1. **retained auxiliary**：已进入 record store、仅未成为 Navigator source channel；不发黄色报警。
2. **degraded import**：unsupported display/formula、unknown record、unaligned data、截断、cap/collision 等；进入稳定 code 的 warning/issue 聚合。
3. **placement outcome**：exact overlap、append/new view 等用户已确认的布局结果；成功接受后不再用黄色重复报告。

coordinator 形成一次 import summary；项目恢复不弹 toast，但 view issue 必须持久并可检查。plot-time issue 继续显示在对应 View，而不是只保留瞬时消息。

### D5. tick 在枚举前完成安全计数

- major 和 grid 都通过同一安全 candidate-count preflight。
- 先验证 range/step 为有限且方向有效，再用不会溢出的方式估算候选数。
- 候选数超过当前产品上限 `max_grid=2000` 时直接拒绝 native enumeration，并使用现有 adaptive/auto tick 路径。
- 禁止“先生成列表、再判断长度”，也禁止 major tick 绕过上限。
- 一个轴不能出现“部分 native、部分静默失败”的半应用状态。

### D6. 测试以合成字节级 WWT 为主

新增 `tests/_helpers/wwt_factory.py`，使用现有格式常量和编码规则构造小型、匿名、可审查的 WWT bytes。至少提供：

1. 单窗口 channel-X/channel-Y，并包含 invisible/limit 等 retained auxiliary record；
2. channel measurement + record-only tolerance，X 与 Y 长度可分别控制；
3. 多窗口、独立 X/Y、公式引用和 exact-overlap 场景。

数组控制在 4–32 点，名称与数值完全合成。真实客户样本只作为开发机可选 smoke/前台验收，缺失时可 skip，但核心 owner 测试不能依赖它。

## 5. 任务依赖与文件归属

```text
Task 0 合成夹具与红测
  ├─> Task 1 record store / 项目恢复
  ├─> Task 2 binding 声明、失败与勾选语义
  ├─> Task 3 诊断分级与黄色提示
  └─> Task 4 native tick 有界枚举
             ↓
       Task 5 集成与前台验收
             ↓
       Task 6 文档与 lessons 收口
```

| 任务 | 主要所有者文件 | 不应扩散到 |
| --- | --- | --- |
| Task 0 | `tests/_helpers/wwt_factory.py`、WWT owner tests | 客户样本、产品实现 |
| Task 1 | `mf4_analyzer/io/wwt_document.py`、WWT coordinator、项目恢复测试 | 新 schema、MainWindow 状态白名单 |
| Task 2 | `mf4_analyzer/ui/time_curve_bindings.py`、`ui/main_window/window.py` | custom X 编辑器、View 管理器重构 |
| Task 3 | WWT document/proposal/coordinator 诊断对象与相关 UI tests | 非 WWT 通用通知体系 |
| Task 4 | `mf4_analyzer/ui/pg_canvas/native_axes.py` 及 owner tests | render ink/AA/raster policy |
| Task 5 | owner/boundary tests 与真实前台证据 | 第二套实现 |
| Task 6 | 当前规格、旧计划状态说明、lessons | 历史文档版本重写 |

## 6. 分任务实施计划

### Task 0 — 建立可移植夹具与失败先行证据

**状态：已实施**（`9efb35d8`）。

**文件**

- 新增 `tests/_helpers/wwt_factory.py`
- 修改 `tests/test_wwt_document.py`
- 修改 `tests/test_wwt_display.py`
- 修改现有 WWT UI 测试：`tests/ui/test_wwt_import_flow.py`、`tests/ui/test_time_curve_bindings.py`、`tests/ui/test_project_session.py`（按实际 owner 分配）

**步骤**

1. 记录当前 HEAD、dirty scope 和 WWT focused baseline；不得先跑全套。
2. 复用现有 byte record/header 常量，创建三个合成 profile，不复制真实客户内容。
3. 把“核心行为”测试从 `testdoc/WWT` 迁到合成夹具；保留可选真实样本 smoke 时使用明确 skip reason。
4. 先加入以下红测：
   - save → reopen 后 record-only X/Y 仍可解析；
   - missing record X 不得产生同 Y 的普通 Time-Y fallback；
   - 取消勾选 channel-backed Y 后不产生 binding row；
   - retained auxiliary 不产生黄色“未导入”。

**接受条件**

- 干净 checkout 不再出现 missing sample 导致的 fail。
- 新增红测在修复前因预期语义失败，而不是因 Qt 生命周期、路径或夹具损坏失败。
- fixture parser round-trip 明确断言 record/window/formula 数量与引用关系。

### Task 1 — 把 record store 移到数据加载层，关闭恢复断链

**状态：已实施**（`7dcf64f5`）。

**文件**

- `mf4_analyzer/io/wwt_document.py`
- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`（只允许薄协调）
- `tests/ui/test_wwt_import_flow.py`
- `tests/ui/test_project_session.py`

**步骤**

1. 在完整 save/reopen 测试中把 `_ask_layout` 设为 fail-if-called，证明恢复路径既不弹确认框，也能恢复 record store。
2. 对恢复前后 binding 的 record hash、长度、issue code 和 resolved X/Y 做语义比较。
3. 在 document load result 构造 store，并向每个 group source metadata 注入同一对象；删除 coordinator 的补写职责。
4. 覆盖 Accept、Reject、无 display、项目恢复、多 group 五条路径。
5. 确认 session JSON 不含展开数组，且没有新增项目 schema 字段。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_import_flow.py tests/ui/test_project_session.py tests/ui/test_time_curve_bindings.py -q
```

**接受条件**

- 重开后 record-only 绑定不出现 `missing_record`。
- 多 group source 共享 store，不按 group 复制数据。
- 恢复期间没有确认弹窗或重复 toast。

### Task 2 — 收紧 binding 声明、失败和 Navigator 可见性

**状态：已实施**（`8810844a`）。

**文件**

- `mf4_analyzer/ui/time_curve_bindings.py`
- `mf4_analyzer/ui/main_window/window.py`
- `tests/ui/test_time_curve_bindings.py`
- 必要时补充现有 MainWindow plot owner test，不新增跨模块状态

**步骤**

1. 直接针对 plot payload builder 加边界测试：
   - channel Y + missing record X；
   - X/Y 长度不齐；
   - channel-backed Y 未勾选；
   - record-only Y；
   - 同一 View 另有一个普通已勾选通道；
   - acquisition-time mask 后的 X/Y 对齐。
2. 引入 `BoundTimePlotResult`（最终命名以现有代码风格为准），分离 claimed 与 successful key。
3. active binding 在解析前声明 channel-backed Y；MainWindow 合并顺序固定为：
   - 生成 WWT/native rows；
   - 收集 binding issues/placeholders；
   - 普通路径跳过 claimed key；
   - 追加未被声明的普通 checked channels。
4. checked composite key 成为 channel-backed binding 的 active 条件；不得用显示名比较。
5. 保持 record-only 可见性和现有 acquisition-time 规则，不借机重做 custom X 编辑能力。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_time_curve_bindings.py tests/ui/test_wwt_native_render.py tests/ui/test_view_channel_scope.py -q
```

> MainWindow 合并行为优先补入上述现有 owner 测试；若必须新增测试文件，应先确认没有可承载该契约的现有 payload/view-scope 测试。

**接受条件**

- 失败 binding 显示明确 issue，但不出现错误的普通 Time-Y 曲线。
- 取消/重新勾选只改变可见性，不丢失持久化 binding。
- 重名通道仍按 composite identity 正确区分。

### Task 3 — 统一 WWT 诊断分级与黄色提示出口

**状态：已实施**（与 Task 1 同提交 `7dcf64f5`）。

**文件**

- `mf4_analyzer/io/wwt_document.py`
- `mf4_analyzer/ui/wwt_view_import.py`
- `mf4_analyzer/ui/main_window/wwt_import_coordinator.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- loader 层仅在现有 WWT outcome 无法承载时做最小调整
- `tests/test_wwt_document.py`
- `tests/ui/test_wwt_import_flow.py`

**先冻结提示矩阵**

| 场景 | 预期用户提示 | 持久 issue |
| --- | --- | --- |
| retained auxiliary record | 无黄色提示 | 无错误；metadata 可追踪 |
| exact overlap，用户确认 | 确认框即为唯一说明；接受后无第二个黄色 toast | placement outcome 可记录 |
| 文件/窗口截断 | 黄色一次 | 是 |
| unknown record / unaligned binding | 对应 View issue；整个导入至多一个摘要 | 是 |
| unsupported display/formula | 黄色摘要一次 | 是 |
| view cap / collision 降级 | 黄色摘要一次 | 是 |

**步骤**

1. 将 retained auxiliary 从真正 skipped/degraded 中分离，建议使用 `wwt_auxiliary_records` 等明确 metadata 字段；最终名称需与现有模型一致。
2. 为诊断使用稳定 code/prefix，展示文案从 code 和上下文生成，避免通过中文字符串去重。
3. coordinator 消费 document、proposal 和 placement outcome，形成一次聚合摘要；`_project_io_mixin.py` 不再无声丢弃 outcome。
4. exact overlap 在确认完成后标记为已消费，不重复黄色通知。
5. plot-time `missing_record`、`unaligned` 等继续附着到 View，保证关闭 toast 后仍能定位。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_wwt_document.py tests/test_wwt_display.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_import_flow.py tests/ui/test_time_curve_bindings.py -q
```

**接受条件**

- 正常 WWT 导入不再因为辅助 record 出现黄色报警。
- 每一种真实降级都有稳定 code，且同一事实不重复提示。
- 项目恢复不弹瞬时消息，但已有 view issue 不丢失。

### Task 4 — native tick 枚举前置上限与溢出防护

**状态：已实施**（`5a43782b` / `5e46059a`）。

**文件**

- `mf4_analyzer/ui/pg_canvas/native_axes.py`
- `mf4_analyzer/ui/main_window/_view_mixin.py`（仅在现有 warning/outcome 路由需要时）
- `tests/ui/test_wwt_native_render.py`
- 相关 View restore owner tests

**步骤**

1. 先建立边界表：
   - 正常小范围 major/grid；
   - 恰好 2000 与 2001 个候选；
   - major 超限；
   - `1e308..1.1e308` 配 `1e-308`；
   - NaN、Inf、零/负 step、反向或零宽 range。
2. 用 spy/guard 证明候选数超限时枚举函数从未进入，不只断言最终 list 为空。
3. 实现安全 preflight，并让 major/grid 复用同一计数逻辑。
4. 超限、溢出风险或非法输入统一回到现有 adaptive tick，不留下半套 native ticks。
5. 保持 View restore 顺序为 X → Y → ticks → single settle；不得改写 150 ms timer 或 ink/AA 决策。

**聚焦验证**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_native_render.py tests/ui/test_pg_timedomain_canvas.py -q
```

**接受条件**

- 上述极端有限数值不抛 `OverflowError`、`MemoryError` 或超时。
- 2001 个候选在列表构造前被拒绝。
- 正常 native tick 的位置、label 和 restore settlement 不回归。

### Task 5 — 集成、边界门禁与真实前台验收

**状态：聚焦 + 边界已通过；全套与前台 UNVERIFIED**（`.state/wwt-followup-task5-report.md`）。

**实施顺序**

1. 非 UI WWT owner tests。
2. 连续列出 `tests/ui` 的 WWT owner tests，避免目录参数离开后再进入造成 fixture closure 失效。
3. 运行相关 import/state/Qt ownership 边界门禁。
4. 对一个合成项目执行 save/reopen 语义比较。
5. 用真实前台 TraceLab 做单次手工验收，保存截图/日志到 `.state/`，不提交客户数据。

**边界门禁**

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_import_flow.py tests/ui/test_time_curve_bindings.py tests/ui/test_project_session.py tests/ui/test_wwt_native_render.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_import_boundaries.py tests/ui/test_main_window_state_ownership.py tests/ui/test_no_lambda_signal_connections.py -q

TMPDIR=/tmp MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest tests/test_signal_no_gui_import.py tests/test_native_import_boundaries.py tests/test_packaging_imports.py -q
```

**真实前台清单**

1. 打开正常 WWT：辅助 limit/line record 被保留，但无黄色“未导入”。
2. 取消勾选绑定 Y：曲线隐藏；重新勾选后恢复原 X/Y。
3. 保存、关闭、重开：record-only tolerance/limit 曲线数值与范围不变。
4. exact overlap：确认后没有第二个黄色提示。
5. 打开合成 unsupported/unaligned case：只有一个摘要，View 内仍能查看 issue。
6. zoom、cursor、Home、View 切换和 UltraView 布局不出现明显回归。

**全套门禁**

只有在 Task 0–5 稳定、相关源码在运行期间不会再变化时才执行一次。先检查当前 checkout 是否已有 pytest 全套在跑，并记录运行前后的 HEAD 与 dirty scope。严格分成两个新进程，不能并发：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui
```

若测试运行期间相关文件变化、进程异常退出、超时或崩溃，结果必须标记为 `UNVERIFIED`，不能用已完成用例数推断通过。

**Task 5 结果（已记录，不重跑全套）：** 非 UI owner、连续 `tests/ui` WWT owner + 边界、其余 import/native/packaging 边界、合成 save/reopen 语义比较均通过。两段全套 **UNVERIFIED**（主套 segfault ~89%，`tests/ui/test_ultraview_page.py::test_card_drag_near_viewport_edge_starts_page_edge_timer`；与本波次 WWT 文件无关）。真实前台六项 **UNVERIFIED**（无 Cocoa 会话，未复制客户 WWT）。详见 `.state/wwt-followup-task5-report.md`。

### Task 6 — 规格、计划与 lessons 收口

**状态：已实施。** 规格 §17、原计划交付注记与 testdoc 夹具纠正、本文件状态/勾选、lesson 促进与 `git diff --check` 在本任务完成。全套与前台仍按 Task 5 记 UNVERIFIED，不在本任务重跑。

**步骤**

1. [x] 在原 WWT 规格中补充：
   - record store 的加载层所有权；
   - claimed binding 不得 fallback；
   - retained auxiliary 与 degraded import 的诊断分类；
   - tick 必须先计数再枚举。
2. [x] 在原实施计划中注明实际交付后的 follow-up，并修正“仓库包含真实 WWT 样本”的错误假设；不重写历史提交事实。
3. [x] 检查 `docs/lessons-learned/INDEX.md` 与 lessons status。若本次再次证明“gitignored 本机样本被当作必需测试夹具”是复发模式，按项目流程新增短 lesson；否则记录为何现有 lesson 已覆盖。
4. [x] 清理本任务产生的临时证据，只保留 `.state/` 中必要的本地复核材料。
5. 运行文档与补丁卫生检查：

```bash
git diff --check
rg -n 'T[B]D|T[O]DO|testdoc/WWT|dict\(|\{\*\*' docs/analyzer/specs/2026-08-28-wwt-winwert-layout-import-spec.md docs/analyzer/plans/2026-08-28-wwt-winwert-layout-import-implementation.md docs/analyzer/plans/2026-08-28-wwt-import-correctness-followup-plan.md mf4_analyzer/io/wwt_document.py mf4_analyzer/ui/time_curve_bindings.py tests
```

## 7. 验收矩阵

| 产品合同 | 自动化证据 | 前台证据 | 通过标准 |
| --- | --- | --- | --- |
| 项目重开复现 record binding | save/reopen session test | 重开同一项目 | X/Y 数值、长度、范围与 issue code 一致 |
| 绑定失败不猜测 | missing/unaligned payload tests | View issue 可见 | 无同 Y 的普通 Time-Y fallback |
| Navigator 控制 channel-backed binding | checked-state tests | 取消/重新勾选 | 曲线隐藏/恢复且 binding 不丢 |
| retained auxiliary 不误报 | diagnostic matrix tests | 正常真实 WWT | 无黄色“未导入” |
| 真降级可观察且不重复 | code + aggregation tests | unsupported/exact overlap | 一个事实一个主提示，View issue 可追踪 |
| native tick 有界 | 2000/2001、极端指数测试 | zoom/Home/View restore | 枚举前拒绝，无溢出、无半应用 |
| 测试可移植 | 无 `testdoc/` 的 owner suite | 不适用 | 核心测试不 fail、不依赖客户文件 |
| 架构边界不扩散 | import/state ownership gates | 不适用 | 无 UI 反向依赖，无新增 MainWindow state whitelist |

## 8. 停止条件

遇到以下任一情况，应停止扩大修改并重新评审，而不是继续打补丁：

1. 合成夹具无法在不复制客户数据的情况下复现关键语义。
2. record store 修复需要把数组写入 session JSON 或新增项目 schema。
3. 实现需要扩大 `tests/ui/test_main_window_state_ownership.py` 白名单。
4. 修复开始改变非 WWT custom X、通用加载通知或 Navigator 产品语义。
5. tick 修复需要调整 ink/AA/raster 阈值或 150 ms settle timer。
6. 工作区出现与这些 owner 文件重叠的并发编辑。
7. 需求扩展为新的 WinWert 公式、display 或导出兼容范围。

## 9. 完成定义

本计划只有在以下项目全部满足时才算完成：

- [x] 合成 WWT factory 已覆盖三类 profile，且不含客户数据。
- [x] 干净 checkout 的 WWT owner tests 不依赖 `testdoc/WWT`。
- [x] record store 在加载层建立，所有 group source 恢复路径可用。
- [x] save/reopen 后 record-only 与 channel-backed binding 均可复现。
- [x] claimed/successful 语义已分离，失败 binding 不再 fallback。
- [x] channel-backed binding 服从当前 View checked composite key。
- [x] retained auxiliary 不再触发黄色“未导入”。
- [x] 真实降级统一聚合，exact overlap 不重复报警。
- [x] major/grid tick 均在枚举前完成有界计数。
- [x] owner tests 与相关边界门禁通过。
- [ ] 稳定快照上的两段全套测试通过，或明确记录为 `UNVERIFIED` 及原因。 **UNVERIFIED** — 主套 segfault ~89%；见 `.state/wwt-followup-task5-report.md`。不得用已完成点推断通过。
- [ ] 真实前台六项清单完成，证据与 offscreen 测试分开记录。 **UNVERIFIED** — 无 Cocoa 前台会话，未复制客户 `testdoc/WWT`；Windows frozen 未跑。同上报告。
- [x] 规格、旧计划状态和必要 lesson 已同步。
- [x] `git diff --check` 通过，补丁只包含本任务文件；本 Task 6 允许本地 docs commit，不 push。

## 10. 建议执行节奏

按 Task 0 → Task 1/2/3/4 → Task 5 → Task 6 执行。Task 1–4 可在夹具契约冻结后分别开发，但集成验证由一个稳定快照统一负责。优先关闭“数据恢复”和“错误 fallback”两个正确性风险，再处理黄色提示与 tick 健壮性；不要先用文案调整掩盖底层所有权问题。
