# 项目恢复按逻辑来源身份对应：优化计划

- 日期：2026-11-10。
- 状态：**T0–T6 已实施**（2026-11-11）。offscreen Qt 上的聚焦用例与边界护栏通过。没有用真实 EPS 文件，也没有在 macOS 前台或 Windows 冻结包上验收。
- 源码基线：`c5ed18a38bd1afffc164ceda0b3e377ce2347aab`（`main`，TraceLab v8.4.6，已含 PR #36 的通道编辑随项目保存）。
- 问题：一个物理文件拆成多个逻辑来源时，项目重开是**按位置**把保存的来源行对应到重新加载出来的组。位置一旦对不上，这一行上挂的所有东西都落到别的来源上：派生通道配方、采样率、时间轴来源、通道顺序、View 与分析引用。
- 推荐路线：**项目里给每个来源行存组身份，重开时按身份对应，不按位置。** 身份复用批处理已有的那一套。对不上身份时只在证据唯一的情况下推断；确认不了的来源，不把会改变数值的状态落上去，并明确告知。

## 1. 成功标准与范围

实施完成必须满足：

1. 同一路径的源文件组序变化后重开：每条配方、采样率、通道顺序、View 引用仍落在保存时的那个逻辑来源上。
2. 同一路径的源文件组数变少后重开：文件只加载一次；已不存在的来源被明确报告，不会出现重复来源。
3. 没有组身份的旧项目（schema 1–5）：证据唯一时自动对应，结果与今天「文件没变」时一致；证据不唯一时不回放配方、不套用保存的采样率，并给出提示。
4. 文件没变、来源没动的现有项目，重开结果与今天一致，不多出提示。
5. 批处理的来源身份（`source_id`）一个字节都不变。
6. 导航里整卡片重排、整卡片关闭的现有行为不变。

不在范围内：

- 改变组身份的定义。那同时是批处理的身份，要动得另立计划。
- 单来源文件「保存的采样率覆盖文件时间列」的问题（§2 的 P6）。它与身份无关，另行处理。
- 升版本号。见 §9。

## 2. 当前事实

`_restore_project_file_refs`（`ui/main_window/_project_io_mixin.py`）按解析后的路径把来源行分桶，同一路径只调一次 `_load_one`，然后 `pending_by_path[key].pop(0)`：第 k 行拿第 k 个新来源。这段逻辑来自 `091150df`（2026-06-19），早于 PR #36。来源行里没有任何组标识。

探针全部走真实的 `MainWindow` 保存与重开，offscreen Qt，Linux 云端。探针脚本在 `/tmp`，没有入库；T0 把它们改写成常驻用例。

| 编号 | 做法 | 结果 |
| --- | --- | --- |
| P0 | 加载器替身：一个 `.hdf` 返回 A、B 两组，都有 `torque`。在 B 上建倍乘通道，用 `navigator_order.set_file_order` 把 A、B 对调，保存，重开。 | 配方落到 A，B 上没有；没有任何提示。输入名只在 B 上存在时，配方被跳过并提示「项目恢复不完整」。 |
| P1 | 真实 MAT 加载器（两种长度 → 两组）加一个 CSV。通过导航的重排入口把 CSV 整卡片移到 MAT 前面，保存，重开。 | 正确。配方仍在 50 Hz 组上。 |
| P2 | 同上，通过导航入口请求把 MAT 的第二组移到第一组前面。 | 无效操作，顺序不变。 |
| P3 | P1 的项目不动，把同一路径的 `.mat` 重新导出：第二组多了两个通道，于是加载器把它排到第一。重开。 | 两组的 `fs` 互换（50 Hz 的组被写成 100，100 Hz 的组被写成 50，时间轴本身没变）。配方落到另一组上被跳过，只有这一条有提示。 |
| P4 | 同一路径的 `.mat` 重新导出成只有一组。重开。 | 文件被加载两次，出现两个相同的来源；第二个的 `fs` 是 50，时间轴是 100 Hz。 |
| P5 | 不含任何通道编辑的项目（schema 4），View 勾了 A 的 `torque` 和 B 的 `rack`。文件按 P3 的方式重新导出后重开。 | `fs` 同样互换，FFT 面板的 Fs 对 50 Hz 的组显示 100。View 引用指向已经不含该通道的来源。**没有任何提示**，恢复状态也不是 degraded。 |
| P6 | 单来源 CSV，保存项目后把文件改成 4 倍采样率，重开。 | `fs` 仍是保存的 10，时间轴是 40 Hz，没有提示。 |

由此得出：

- **缺陷是真实的，而且早于 PR #36。** 没有通道编辑的项目同样会把采样率和 View 引用套到错误的来源上（P5），FFT 的有效采样率取自 `fd.fs`。PR #36 把可被套错的东西扩大到了派生通道的数值。
- **「在界面里对调同一文件的两个来源」目前走不到。** 导航的拖拽、Alt+上下、通道树拖拽都把一个物理文件的全部来源当成一块移动，块内相对顺序不变；关闭也是整块（P1、P2）。P0 用的 `set_file_order` 是程序接口，产品界面没有等价入口。
- **界面走得到的触发条件是位置对应本身失效**：同一路径的源文件被替换或重新导出，组序或组数变了（P3–P5）；或者不同版本的加载器对同一个文件给出不同的组序、组数。
- **同名输入且毫无提示的套错**（P0 的第一种结果）只在替身上复现过。真实加载器上已证实的是采样率与 View 引用的无提示套错（P5），以及配方被跳过并提示（P3）。没有用真实 EPS 文件复现。
- 仓库里没有 `testdoc/` 样本，P 系列都是合成文件。

批处理一侧已经有组身份：`io/source_adapters.py` 的 `_group_identity`，HDF 用 raster factor、点数、dt、t0，WWT 用点数、dt、t0，MAT 用长度与 dt，ZFD 用点数与 dt，单来源是 `root`；结果写进 `source_metadata["group_id"]`，同一文件内重复时报 `SourceIdentityError`。GUI 的 `_load_one` 直接调 `DataLoader`，没有经过这段，所以 GUI 的 `FileData` 上没有组身份。

P3 里两组的长度与 dt 都没变，按这套身份可以正确对应。

## 3. 设计决定

### D1 身份只有一套

逻辑来源身份 =（物理路径，组身份）。组身份就是批处理已有的那一个，不新造第二套。

- 把 `_group_identity` 提升为 `io/source_adapters.py` 的公开函数，并提供一个给一批组盖章的函数。批处理的 `_loaded_groups` 与 GUI 的四个分组分支（HDF、WWT、ZFD、MAT）都调它，键仍是 `source_metadata["group_id"]`。
- 身份在加载器返回的组上计算，早于任何时间轴重建。
- 同一文件内出现重复身份：批处理维持现在的报错；GUI 不让加载失败，但这个文件的所有组都不盖章，并写一条日志。没有身份的来源在保存和重开时按 D3 的后两级处理。

### D2 项目文件加一个可选字段

`files[]` 的每一行增加 `source_group`，值是组身份字符串，**只在不是 `root` 时写出**。读取时缺省为空。

项目文件里不用 `group_id` 这个键名，因为 UI 里 `group_id` 已经指共轴分组。

不升 schema 版本号。旧读者按键取值，会忽略这个字段，行为与今天相同。这个决定的前提见 §10 的第 2 点。

### D3 重开时的对应规则

按物理路径分桶，每条路径只加载一次。桶内用一个不依赖 Qt 的纯函数做对应，按下面的顺序：

1. **身份相同。** 保存的 `source_group` 等于某个已加载组的身份。
2. **证据唯一。** 对剩下的来源行与组，用项目里已经存着的事实找候选：
   - 该行保存的加载器通道名必须全部存在于候选组。加载器通道名 = `channel_order` 里的名字，去掉该行配方产生的名字，加上该行配方删除的名字。
   - 仍有多个候选时，看保存的 `fs` 是否等于候选组从文件得到的采样率。只在该行 `time_source` 不是 `manual` / `generated` 时使用这一条。
   - 只有当剩下的行与组之间存在**唯一**的一一对应时才采用。没有可用证据（例如很旧的项目没有 `channel_order`）不算唯一。
3. **只剩一行一组。** 这一组就是这个文件本身，按已确认处理：回放配方、套用保存的采样率，不提示。单来源文件改了列、或很旧的项目没有 `channel_order`，都走这里。实施时补上这一级，否则单来源项目会被误报成「无法确认」，配方的真实跳过原因也出不来。
4. **无法确认。** 还剩下不止一个来源时，数量相等就按相对位置对应，并标记为「未确认」。数量不等时，多出来的行视为「来源已不存在」，不再第二次加载文件；多出来的组留在会话里，没有引用。

第 2 级沿用了仓库里已有的做法：旧 WWT 通道绑定也是在「现场可证明」时才迁移。

### D4 不同级别带回什么

| 状态 | 身份相同 / 证据唯一 / 只剩一行一组 | 未确认 |
| --- | --- | --- |
| View、分析、Board 的来源引用 | 带回 | 按位置带回 |
| 通道顺序 | 带回 | 按位置带回 |
| 保存的采样率、时间轴来源与出处 | 带回（既有规则不变） | **不带回**，保留文件自己的时间轴 |
| 派生通道配方 | 回放 | **不回放**，逐条报告，原因「来源对应关系无法确认」 |

划线的依据：会改变数值的状态，不落到确认不了的来源上。按位置带回的 View 引用显示的是带来源标签的原始通道，标签是真的。

「来源已不存在」的行走既有的缺失路径：它的 View 与分析引用被移除并计入报告。

### D5 让用户看得见

`ProjectRestoreHealth` 增加两个列表：未确认的来源、文件里已不存在的来源。两者都使恢复状态为 degraded，于是进入既有的「项目恢复不完整」提示和再次保存前的确认。

提示文案区分三种情况，不再共用「文件找不到」：

- 文件找不到。
- 文件还在，但其中的某个来源已不存在。
- 来源对应关系无法确认：列出来源标签，以及因此没有回放的派生通道数、没有套用的采样率设置数。

证据唯一的推断只写日志，不打扰用户。

### D6 保存

`_assemble_project_document` 把每个来源的组身份写进 `source_group`。来源顺序仍取自 `navigator_order`。

未确认的来源，用户在确认框里选择保存后，按当前对应关系写入身份。确认框本来就说明「保存会固化当前状态」。

## 4. 文件所有权与修改边界

| Owner | 允许的实现工作 | 禁止的扩张 |
| --- | --- | --- |
| `io/source_adapters.py` | 公开组身份函数与盖章函数；批处理改调公开函数 | 改变任何格式的身份字符串；引入 `ui` |
| `ui/main_window/_project_io_mixin.py` 的 `_load_one` 分组分支 | 注册前给组盖章 | 在 mixin 里再写一份身份算法 |
| `ui/project_io.py` | `ProjectFileRef.source_group` 的读写与摘要 | 在编解码层做对应或求值 |
| `ui/project_source_match.py`（新增，不依赖 Qt） | D3 的纯函数与结果类型 | 读文件、碰 `MainWindow`、猜测性打分 |
| `_project_io_mixin.py` 的 `_restore_project_file_refs`、`_assemble_project_document` | 改成「先加载、再对应、再按级别套用」；写出身份 | 新增多文件写入的窗口属性 |
| `ui/main_window/_state_holders.py` | `ProjectFileRestoreResult`、`ProjectRestoreHealth` 的新字段与对称清理 | 把运行期诊断写进项目文件 |
| 导航与通道树 | 不改 | 改整卡片重排 / 关闭语义 |

## 5. 执行分步与聚焦门禁

每个 Task 先跑自己的 owner 用例，再跑列出的边界护栏。不跑全量套件：改动集中在项目恢复一条路径和一个 io 函数的可见性，没有跨边界重构。记录每个 pytest 进程的退出码，非零退出按 `UNVERIFIED` 报告。

### T0 把探针变成红用例

- 真实加载器夹具：`scipy.io.savemat` 写两种长度的 `.mat`；HDF 用 `tests/_helpers/head_hdf_factory.py`。
- 在 `tests/ui/test_project_session.py` 新增，改动前应为红：
  - 文件重新导出、组序翻转后重开：配方、`fs`、通道顺序、View 引用跟着身份走（P3、P5）。
  - 文件重新导出、组数变少后重开：来源数不翻倍，缺失来源被报告（P4）。
  - 旧项目、两组同名同采样率（加载器替身）：配方不回放，出现「无法确认」提示（P0）。
- 守住现状，改动前应为绿：
  - 整卡片重排后保存重开结果正确（P1）。
  - 对同一文件的两个来源发重排请求是无效操作（P2），放在 `tests/ui/test_file_navigator.py`。
  - `test_open_project_multi_group_hdf_no_duplication`、`test_project_restore_rebuilds_wwt_record_rows_and_hidden_ids`、`test_project_restore_migrates_live_proven_legacy_wwt_channel_binding`。

### T1 身份公开并在 GUI 盖章

- owner 用例：`tests/test_source_adapters.py`（四种格式的身份字符串逐字不变；重复身份在批处理仍报错）；新增 GUI 用例断言 `_load_one` 之后每个分组来源的 `source_metadata["group_id"]` 与批处理适配器给出的相同。
- 边界护栏：`tests/test_batch_source_integration.py`、`tests/test_batch_runner.py` 里与 `source_id` 有关的节点、`tests/test_native_import_boundaries.py`、`tests/test_batch_render_import_boundary.py`、`tests/ui/test_import_boundaries.py`。

### T2 项目编解码

- owner 用例：`tests/test_project_io.py`（有身份才写键；缺省读成空；旧版本文件照常读）、`tests/ui/test_project_dirty_guard.py` 的摘要节点（重开后摘要等于磁盘，不变脏）。
- 边界护栏：无新增。

### T3 对应纯函数

- owner 用例：新增 `tests/test_project_source_match.py`，表驱动覆盖：三级各自命中；证据不唯一；没有证据；行多于组、组多于行；部分行有身份、部分没有；身份不可用的文件。
- 这是纯函数，不需要 Qt。

### T4 恢复与保存接线

- owner 用例：T0 的全部节点转绿；`tests/ui/test_project_session.py` 里通道编辑往返、跳过配方可见、HDF 采样率恢复的既有节点保持绿。
- 边界护栏：`tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`。

### T5 文档

- `docs/analyzer/user-guide/channel-axis-order-guide.html` 的 FAQ 补一段：项目按来源身份恢复；源文件结构变了会看到什么提示。
- `ui/hints.py`、`ui/quickref.py` 不改：没有增删交互。
- 纯文档改动不跑运行时测试，只做 `git diff --check` 与引用检查。

### T6 收口

- 重跑 T0–T4 的 owner 文件各一次并记录退出码；`git diff --check`。
- 回填本文状态行与实测结果。

实施时的门禁（都是退出码 0，offscreen Qt）：

- `tests/test_project_source_match.py`、`tests/test_project_io.py`、`tests/test_source_adapters.py`、`tests/test_batch_source_integration.py`、`tests/test_batch_render_import_boundary.py`、`tests/test_native_import_boundaries.py`
- `tests/ui/test_project_session.py`（含 T0 的四个新节点和既有的 HDF / WWT / 通道编辑往返）
- `tests/ui/test_file_navigator.py::test_tree_reorder_inside_one_physical_file_is_a_noop`
- `tests/ui/test_project_dirty_guard.py::test_channel_edit_marks_dirty_and_reopen_without_skips_is_clean`
- `tests/ui/test_main_window_state_ownership.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`
- `git diff --check`

没有跑全量套件。真实 EPS 文件、macOS 前台和 Windows 冻结包仍未验收。

## 6. 验收矩阵

| 场景 | 期望 | 证据层级 |
| --- | --- | --- |
| 分组文件未变，保存重开 | 与今天一致，无提示 | offscreen 用例 |
| 同一路径文件重新导出，组序变化 | 全部状态跟随身份 | offscreen 用例，真实 MAT 加载器 |
| 同一路径文件重新导出，组数变少 | 不重复加载，缺失来源被报告 | offscreen 用例，真实 MAT 加载器 |
| 8.4.6 及更早保存的项目，各组通道名不相交 | 证据唯一，自动对应，无提示 | offscreen 用例；真机用 `SFNS_40_X04-CSER_000009.wwt` 这类真实拆分文件 |
| 旧项目，各组同名且采样率相同 | 配方不回放、采样率不套用、有提示 | offscreen 用例（加载器替身） |
| 批处理来源身份 | 逐字不变 | 既有批处理用例 |
| 真实 EPS 多来源文件（WWT、HEAD HDF）上的保存与重开 | 派生通道、采样率落在正确来源 | macOS 前台，**本环境无法执行** |
| Windows 冻结包 | 同上 | **本环境无法执行** |

## 7. 风险与边界

- **身份随点数和时间参数变化。** 换成另一段时长不同的录制后，身份不再相同，会落到证据唯一那一级。各组通道名不相交时仍能自动对应；同名时会提示。这是有意的保守方向。
- **证据规则过严或过松。** 过严只会多一次提示；过松会套错。所以规则只接受唯一的一一对应，不打分、不取最接近。
- **首次打开旧项目可能多一次提示。** 只出现在各组同名同采样率的文件上；确认保存一次后身份写入，之后不再提示。
- **加载器将来改变分组规则**时，身份字符串也可能变。那时同样先落到证据唯一那一级，而不是静默错位。

## 8. 回退

`source_group` 是可选字段。回退代码后，带这个字段的项目仍可被旧逻辑读取，行为回到按位置对应。不需要迁移项目文件。

## 9. 发版时要带上的事项

- PR #36 之后 `main` 仍标着 v8.4.6，但已经能写出旧 8.4.6 打不开的 schema 5 项目。建议本修复与 PR #36 一起，以一个新版本号发出，changelog 写明：派生通道随项目保存；含通道编辑的项目需要该版本或更高版本；分组来源按身份恢复。
- 版本号的扇出面按仓库既有清单同步。本计划的实现任务不包含升版。

## 10. 需要确认的三点

1. **「未确认」时的保守程度（D4）。** 推荐不回放配方、不套用保存的采样率。代价：各组同名同采样率的旧项目，如果用户手动改过采样率，第一次打开会丢掉这个设置并看到提示。另一种做法是照旧按位置全部带回、只加提示；那样常见情况不受影响，但确认不了的来源上会出现按位置套上去的数值。
2. **是否需要新的 schema 版本（D2）。** 推荐不升，前提是 PR #36 之后、本修复之前的构建没有外发。如果已经外发，那些构建打开新项目时仍按位置回放配方；要挡住它们，就得在「分组来源带通道编辑」时写 schema 6。
3. **P6 是否另开一项。** 单来源文件被替换后，保存的采样率仍会覆盖文件时间列得到的采样率，且没有提示。它不属于身份问题，本计划不处理。
