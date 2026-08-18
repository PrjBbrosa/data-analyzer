# 时域通道拖放与左侧顺序管理实施计划

- 日期：2026-08-18
- 状态：待执行
- 基线：`main@8383a7ee`
- 对应 Spec：
  [`2026-08-18-timedomain-drag-drop-and-navigator-order-spec.md`](../specs/2026-08-18-timedomain-drag-drop-and-navigator-order-spec.md)
- 总体边界：画布只接收“加入曲线/设为横坐标”，不实现画布内曲线或分屏行排序；排序
  只发生在左侧文件卡片和通道树。

## 成功定义

交付完成必须同时满足：四个原生拖动手势可用；左侧文件/通道顺序是分屏与叠加的唯一
顺序；自定义 X 按来源同名匹配且部分失败不阻塞；主/副 View 路由准确；项目保存恢复
顺序；原复选框、多选、眼睛、文件附件和坐标设置行为无回归。

## Task 0 — 基线与测试清单（不改产品代码）

责任范围：工作区对账、现有行为冻结。

1. 记录 `HEAD` 与 `git status --short`，保留所有不属于本任务的现有改动。
2. 运行受影响 owner 的聚焦基线，不先跑全套：

   ```bash
   TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
     .venv/bin/python -m pytest \
     tests/ui/test_channel_widget.py \
     tests/ui/test_file_navigator.py \
     tests/ui/test_time_xaxis.py \
     tests/ui/test_view_state.py \
     tests/test_project_io.py -q
   ```

3. 冻结以下现状：
   - 文件 MIME 拖到通道面板仍发出一次 `files_attach_requested`；
   - 左键跨行移动不扩展蓝色选择；checkbox 与 eye 不互相串扰；
   - `PER_SOURCE_NAME` 每来源解析、时间范围使用 acquisition time；
   - 主/副 View 的 `focused_canvas` 与 `_view_index_for_canvas` 映射；
   - 新通道加入后只给新通道做可见 X 内 Y-fit。
4. 把 Spec 的 12 条验收标准映射到测试文件/前台步骤，缺失项先列红测名称。

验收：只报告真实基线；崩溃、超时或中断为 `UNVERIFIED`，不从已完成用例推断通过。

## Task 1 — 建立 Qt 无关的唯一顺序模型（测试先行）

责任文件：

- 新建 `mf4_analyzer/ui/navigator_order.py`
- 新建或扩展 `tests/ui/test_navigator_order.py`

先写失败测试，再实现 `NavigatorOrderState`：

1. 文件注册按首次出现追加；重复注册 no-op。
2. `move_file_block(fids, target, placement)` 原子移动 grouped fids，不重复、不拆散。
3. `move_channel(fid, channel, target_channel, placement)` 只允许同 fid。
4. `order_checked(checked)` 按文件块 → logical-source → 通道顺序排序，同时：
   - 保留复合键身份；
   - 去除重复输入；
   - 未注册但仍有效的输入稳定追加，不能静默丢曲线。
5. `refresh_channels` 保留存活顺序、删除消失通道、新通道按来源原序追加。
6. `remove_fid` 对称清理文件和通道表。
7. 所有公开输入归一化为字符串，返回副本/tuple，外部不能直接改内部列表。

实现保持 Qt/UI/MainWindow import-free；不在 `ViewState` 增加 `plot_order`。

验收：纯模型测试覆盖空列表、首尾移动、同位 no-op、畸形/未知身份、group block、刷新与
删除；`tests/ui/test_import_boundaries.py` 证明中性模型没有反向 UI 依赖。

## Task 2 — 文件卡片排序入口与投影

责任文件：

- `mf4_analyzer/ui/file_navigator.py`
- `tests/ui/test_file_navigator.py`
- 必要时 `mf4_analyzer/ui_kit/style.qss`

步骤：

1. 保持 `_FileRow` 现有文件 MIME 和 channel-pane Copy drop 合同。
2. 给文件列表 viewport/holder 安装 drop receiver：解析已知 grouped fids、计算 before/after
   位置、发结构化 `file_order_requested(fids, target_fids, placement)`。
3. drop action 在文件列表为 Move、在通道面板为 Copy；测试两者不串路由。
4. 插入线只在合法目标显示；leave/drop/no-op 后保证清除。
5. `QDrag` parent 改为稳定 host/window；drop 不删除 source row，不让异常逃出 Qt virtual。
6. MainWindow/协调器接受 intent 后先更新 `NavigatorOrderState`，再调用 navigator
   `project_file_order(...)` 移动现有 layout widgets 与通道树文件/source 节点。
7. grouped card 作为一个块；内部 fids 顺序不变，active fid 和卡片 active chrome 不变。

测试必须覆盖：首→尾、尾→首、同位 no-op、group card、未知/畸形 MIME、插入线清理、
Copy/Move 目标区分以及排序不发关闭/附件信号。合成事件要把 `QMimeData` 引用挂在事件或
fixture 上，避免 wrapper 提前回收。

验收：文件卡片和通道树文件块顺序一致；现有文件 attach/drop/close 测试不修改语义即绿。

## Task 3 — 通道拖动源与树内排序

责任文件：

- `mf4_analyzer/ui/widgets/channel_tree.py`
- 如需封装 MIME，新建 `mf4_analyzer/ui/channel_drag.py`
- `tests/ui/test_channel_widget.py`

步骤：

1. 定义版本化 channel MIME 的纯 encode/decode，负载只含 version/kind/fid/raw channel。
2. `_CheckTolerantTree` 在 press 时区分 checkbox、eye、父节点和通道正文；只有正文保存
   drag candidate。
3. `mouseMoveEvent` 保留现有“左键跨行不扩展选择”护栏，但候选通道超过系统阈值时启动
   单通道 QDrag；不能简单删除现有 early-return。
4. tree viewport 接受自身 channel MIME，显示 before/after 插入线；只对同 fid/raster
   发 `channel_order_requested`。
5. 搜索非空或分析投影时不发内部排序 intent，但仍允许外部 drag 继续到 View/X。
6. “已选”过滤下的移动只调整可见选中项相对顺序，未显示通道保持相对顺序。
7. 状态模型确认移动成功后重投影 child items；保留展开、当前项、蓝色多选、checkbox、
   eye、颜色、共轴组、tooltip 和 hover detach 状态。
8. `refresh_file` 从顺序模型恢复旧顺序并追加新通道，不因编辑通道回到导入顺序。

聚焦红测：

- 正文拖动会生成准确复合 MIME；checkbox/eye/父节点不生成；
- 短位移仍是 click；Ctrl/Shift 和 drag-selection guard 不回归；
- 同 fid 合法移动，跨 fid/raster、搜索态、分析态无副作用；
- 排序后 `get_checked_channels()` 与 `order_checked()` 一致；
- 通道刷新保序并追加新列。

验收：用户能在树内调整通道顺序，但不能借排序把通道改变数据所属来源。

## Task 4 — 工作区顺序接入绘图与项目持久化

责任文件：

- `mf4_analyzer/ui/main_window/window.py` 或所属既有协调 mixin
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/project_io.py`
- `mf4_analyzer/ui/view_bridge.py`
- `tests/ui/test_project_session.py`
- `tests/test_project_io.py`
- `tests/ui/test_view_state.py`

步骤：

1. MainWindow 初始化一个明确的 `NavigatorOrderState` 协作者；禁止在多个 mixin 新增平行
   `file_order/channel_order` list。
2. 文件加载/刷新/关闭只通过协作者的 register/refresh/remove 方法维护顺序。
3. `_build_time_plot_data` 进入数值装配前调用 `order_checked(...)`；renderer 不自行排序。
4. 文件/通道排序成功后只重绘当前可见时域主/副 canvas；顺序变化不清理数值数据或分析
   结果缓存。调用现有 view-aware replot，保留 xlim/已有 ylims。
5. `ProjectFileRef` 增加 `channel_order`；项目 schema 升为 3，并继续支持 1/2。
6. 保存 `ProjectDocument.files` 时使用模型文件顺序；grouped logical refs 连续。
7. 恢复文件后用 old fid→new fid 映射把每条 ref 的 channel order 应用给对应 logical source；
   缺失文件删除，剩余顺序稳定。
8. `ViewState.checked` 继续兼容读写，不增加 View 内顺序字段；文档/测试明确绘制前由工作区
   顺序排序。

项目测试至少覆盖：

- v3 文件顺序 + 两个 logical source 的独立通道顺序往返；
- v1/v2 缺字段默认加载顺序；
- grouped 文件连续恢复；
- 缺失文件的 degraded restore 不打乱剩余项；
- 新/删通道恢复规则；
- 保存时未知但仍有效 fid 兜底追加，不丢项目来源。

验收：关闭重开项目后左侧顺序、分屏顺序和图例顺序一致；不扩大 ViewState 复合键清理面。

## Task 5 — 通道 drop 到目标时域 View

责任文件：

- `mf4_analyzer/ui/chart_stack/cards.py`
- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/main_window/_view_mixin.py`
- `mf4_analyzer/ui/main_window/window.py`
- `tests/ui/test_split_focus_routing.py`
- 新建或扩展 `tests/ui/test_time_channel_drop.py`

步骤：

1. 在 TimeChartCard/canvas viewport 层增加 drop 路由，不把 View/session 状态写入
   `pg_canvas` renderer。
2. 复用 `_card_for_object`、`set_focused_card`、`_view_index_for_canvas`，以鼠标所在 card
   为目标，不读取拖动开始前的旧焦点。
3. drop router 只发 `channel_drop_requested(canvas, key, zone)`；MainWindow service 负责：
   - 验证 fid/channel 仍存在；
   - 原子加入目标 View attachment + checked；
   - 已存在时 no-op；
   - view-aware replot。
4. 加入曲线是非语义 X 变化：保留 xlim；旧通道 ylims 保留，新通道执行既有可见 X
   Y-fit。
5. drop 过程中用 card/viewport property 显示“加入 View”高亮；leave/drop 后清理。
6. 程序化投影、项目恢复、分析模式不消费这类 drop。

红测覆盖：单栏加入、重复 no-op、来源未 attach 时自动 attach、主/副栏准确路由、drop
期间 View 切换/通道删除后的安全 ignore、X/Y 范围保持。

验收：外部 drag 只提交结构化意图；目标 View 是唯一状态写入对象，不通过 navigator
当前投影误写另一个 View。

## Task 6 — 横坐标 drop 与 Inspector 单一应用事务

责任文件：

- `mf4_analyzer/ui/time_xaxis.py`
- `mf4_analyzer/ui/chart_stack/cards.py`
- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/view_bridge.py`
- `tests/ui/test_time_xaxis.py`
- `tests/ui/test_main_window_smoke.py`
- `tests/ui/test_split_focus_routing.py`
- `tests/ui/test_time_channel_drop.py`

步骤：

1. 用最底部实际 AxisItem/label geometry 计算 X drop zone；绘图区与 X zone 互斥，X zone
   优先。
2. 从 `_apply_xaxis()` 提取 `apply_time_xaxis_spec(spec, canvas, *, sync_inspector)`：统一负责
   兼容 shim、Inspector、ViewState、缓存失效、xlim reset、view-aware replot 和诊断。
3. Inspector“应用”先把草稿转 `CustomXAxisSpec` 再调用服务；drop 直接构造
   `PER_SOURCE_NAME` spec 调用同一服务。
4. drop 先聚焦目标 card，右侧面板同步显示目标 View 的“指定通道”、候选项和标签。
5. 保持 range mask 在 `FileData.time_array`；按来源 resolver、有限值、长度与 unit cohort
   规则完全复用现有 `resolve_custom_xaxis`，不复制数值算法。
6. 0/N 与部分成功均保留已应用 spec；不显示矛盾成功 toast，不回滚到时间轴。

聚焦验证：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_time_xaxis.py \
  tests/ui/test_main_window_smoke.py -q -k \
  "custom_xaxis or xaxis or time_range or unit_cohort"
```

另跑精确回归：按来源同名、长度不匹配、时间范围、范围内有限值、空单位 cohort、主/副
View Inspector 同步和项目 roundtrip。

验收：鼠标 drop 与右侧“应用”产生完全相同的 applied spec、缓存副作用和恢复结果。

## Task 7 — 分屏占位行与叠加非阻塞诊断

责任文件：

- `mf4_analyzer/ui/main_window/window.py`
- `mf4_analyzer/ui/chart_stack/cards.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py`
- 如由 collaborator 承担，更新对应 `_CanvasBackref` 声明
- `tests/ui/test_pg_timedomain_canvas.py`
- `tests/ui/test_main_window_smoke.py`

步骤：

1. 在 `TimePlotBuildResult` 增加有序 slot DTO；每个 attempted `(fid, channel)` 产生一个
   success row 或 recoverable placeholder，禁止用两个未关联列表事后猜位置。
2. subplot renderer 按 slot 建轴：success 画曲线，placeholder 画中性空行和准确原因；空行
   不参加光标、统计、Y-fit、AA/ink 预算或数据 extent。
3. overlay renderer 只消费 success rows；诊断 pill 使用同一 slot/issue 顺序显示 N/M。
4. `missing_x_channel`、`unaligned`、`empty_after_time_range`、`non_finite_x`、
   `x_unit_incompatible` 等可恢复 issue 都保留 slot；programming error 继续传播，不降级成
   占位。
5. 全失败时 subplot 有 N 个占位、overlay 有 0/N 空态；两者都保留 applied X spec。
6. 排序后占位与成功行一起按工作区顺序移动。

测试覆盖：混合成功/缺失、全缺失、长度不一致、单位不兼容、排序后 slot、取消勾选移除
slot、placeholder 不进入游标/统计/ink，以及 overlay 不创建空轴。

若触及 canvas collaborator，运行：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_pg_timedomain_canvas.py -q
```

验收：失败是可见、可解释、局部的；既不借错数据，也不把一个来源失败放大成整次拒绝。

## Task 8 — 提示、快捷参考与视觉收尾

责任文件：

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- 必要时 `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_hints.py`
- `tests/ui/test_quickref.py`
- `tests/ui/test_quickref_panel.py`

步骤：

1. 时域提示加入“拖到绘图区加入”“拖到底部设横坐标”“左侧拖动排序”，明确画布内不能
   拖行排序。
2. QuickRef 同步三条交互和“分屏占位 / 叠加跳过 + N/M”降级语义。
3. drop 高亮不遮曲线、不改 card 圆角；插入线在浅色背景和选中行上均可辨认。
4. 增加 accessible name；如加入右键上移/下移，保持扁平直接动作。
5. 不借此重做文件卡片、通道树或右侧 Inspector 视觉系统。

验收：hints/quickref 同步；截图重点检查 X zone、绘图区、文件插入线、通道插入线和
placeholder 文案，不以 QSS token 代替渲染证据。

## Task 9 — 聚焦门禁、前台手势与集成验收

### 9.1 自动化聚焦门禁

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_navigator_order.py \
  tests/ui/test_channel_widget.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_time_channel_drop.py \
  tests/ui/test_time_xaxis.py \
  tests/ui/test_split_focus_routing.py \
  tests/ui/test_view_state.py \
  tests/ui/test_project_session.py \
  tests/test_project_io.py \
  tests/ui/test_pg_timedomain_canvas.py -q

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_pg_canvas_backref_invariants.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py -q

git diff --check
```

只在稳定集成快照、聚焦门禁全绿后运行一次仓库全门禁；按仓库规则串行分两进程：主 suite
忽略 `tests/acquisition_ui`，完成后再单独运行 `tests/acquisition_ui`。记录运行前后 HEAD 与
相关 dirty scope；测试期间相关文件变化则该结果为 `UNVERIFIED`。

### 9.2 真实 macOS 前台验收

用至少三份文件：A/B 含同名 X，C 缺失 X；其中一份物理文件展开多个 logical sources。

逐项执行并录屏/截图：

1. 通道正文 → 单 View 绘图区；checkbox/eye 起拖失败符合预期。
2. 左右对比中分别拖到主栏、副栏；只修改鼠标所在 View，右侧面板随焦点切换。
3. 通道 → 最底部 X 带；高亮区域准确，Inspector 同步。
4. subplot 下 A/B 正常、C 同位置占位；overlay 下 C 不画且 pill 显示 2/3。
5. 拖文件卡片首尾互换；grouped 卡片整块移动，分屏行随之变化。
6. 同一 fid 内拖通道；跨 fid drop 禁止；搜索态只允许外部 drop。
7. 在已缩放 X/Y 状态完成加入/排序，确认旧范围保留、新通道 Y-fit 正确。
8. 保存项目、关闭、重开：文件/通道/X 设置/占位顺序一致。
9. 连续拖动、拖到无效区域、拖动中删除/关闭目标后的程序不崩溃，无 stuck highlight。

原生拖放事件循环和命中区域必须由前台证据证明；离屏 Qt 只能证明状态/事件合同。Windows
冻结包验收若本轮不执行，交付中明确标记 `UNVERIFIED`，不由 macOS 结果代替。

## Task 10 — 范围复核与交付

1. 全文 grep 旧/冲突语义：不得把“画布内拖动排序”“跨文件拖通道”“失败即拒绝”写成
   正向能力；Spec 的非目标/禁止项可保留这些词用于明确边界。
2. 检查 source diff：只包含本计划责任文件、测试、hints/quickref 和项目 schema 变更。
3. 检查所有新 mutable state 有单一 owner、初始化、close/refresh/project restore 对称清理。
4. 核对 schema 3、帮助、测试与实际字段名一致；不存在计划写 `channel_order`、实现另取名的
   stale identifier。
5. 若实现需要跨 logical source 移通道、每 View 独立排序、自动插值或画布内重排，停止并
   先修订 Spec，不顺手扩大 P0。
6. 用户未要求 commit/push 时不提交、不发布；交付时分别报告自动化、macOS 前台和 Windows
   冻结证据，证据类别不混用。

## 实施顺序与提交边界

固定顺序：

```text
Task 0
  → Task 1
  → Task 2 / Task 3
  → Task 4
  → Task 5 / Task 6
  → Task 7
  → Task 8
  → Task 9
  → Task 10
```

建议拆为三个窄提交：

1. 顺序模型 + 左侧文件/通道排序 + 项目持久化；
2. channel→View / channel→X 路由 + Inspector 单一应用事务；
3. subplot placeholder + 提示文档 + 集成验证。

每个提交只在自身聚焦门禁通过后形成；全套只由最终稳定集成提交运行一次。
