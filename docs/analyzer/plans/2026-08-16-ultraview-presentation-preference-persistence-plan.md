# UltraView 展示偏好持久化与会话状态收口计划

**状态：** Implemented（相关自动门禁通过；macOS 前台人工验收待执行）

**日期：** 2026-08-16

**执行基线：** `b41dec42 fix(ultraview): compensate extent rebase with the exact pitch`
**范围：** 解决“常驻显示卡片操作”默认值、新建 Board 继承、工程保存/恢复，以及
筛选与 View 库钉住状态的生命周期边界；不改变卡片操作、只读快照、画布缩放或布局交互。

**执行结果（2026-08-16）：** Task 0–3 已完成。相关 owner 验收为 `316 passed, 1 skipped,
2 deselected`；两项 deselect 是本批之外、当前自由网格额外弱提示造成的既有 Toast 精确匹配
失败。结构与帮助门禁为 `94 passed`。未运行全量 pytest 或 macOS 前台 / Windows frozen 验收。

## 0. 决策摘要

### 0.1 用户可见合同

1. 「常驻显示卡片操作」默认**不勾选**。未勾选时，操作条只在卡片 hover 或键盘焦点
   到达卡片时显示；现有图标、排序、快捷键和删除语义不变。
2. 该选项是**当前 UltraView 工作区偏好**，而不是 Board 内容：切换、复制、新建 Board
   都使用同一个值；用户不应在新建 Board 后重新设置一次。
3. 偏好保存到当前 `.tlproj`，项目保存后重开仍保持；新项目从默认的“不勾选”开始。
   本批不写 `QSettings`，因此不承诺跨未保存项目或跨所有工程的全局记忆。
4. 「显示卡片标题」「显示来源文件」继续是 **Board 级展示内容**。本批不把它们暗中
   改成全局开关；若后续希望它们也由新 Board 继承，另立明确产品决定。
5. 对比筛选和 View 库“钉住”是 Sheet 会话态：关闭 UltraView Sheet、关闭全部文件
   或恢复另一项目时回到“全部 / 未钉住”，不得泄漏到下一工程；它们不进入项目 JSON。
6. 现行「每次打开 UltraView 均适应画布」的相机合同保持不动。它是有意的视口策略，
   不是本计划定义的设置丢失。

### 0.2 状态归属表

| 状态 | 实施后 owner | 保存边界 | 关闭 Sheet | 新建/切换 Board |
|---|---|---|---|---|
| 常驻显示卡片操作 | `UltraViewWorkspaceState.show_card_actions` | 当前 `.tlproj` | 保留 | 保留 |
| 标题 / 来源摘要 | `UltraViewBoardState` | 当前 `.tlproj` | 保留 | 各 Board 自己的值 |
| 对比筛选 | `UltraViewPage` session | 不保存 | 复位为“全部” | 不随 Board 复制 |
| View 库钉住 | `UltraViewPage` session | 不保存 | 复位为“未钉住” | 不随 Board 复制 |
| 选择、替换 arm、焦点层、演示 | `UltraViewPage` session | 不保存 | 保持既有复位 | 不得泄漏 |
| 缩放 / 平移 | Board payload + 页面运行态 | 仍可保存，但打开时 Fit | 按既有 Fit | 按既有 Fit |

## 1. 已核实的根因与非根因

### 1.1 确定根因：错误的 owner 和默认值

- `UltraViewBoardState.show_card_actions` 当前默认 `True`，`default_board()` 也显式写
  `True`；`create_board()` 每次调用 `default_board()`。因此新建 Board 一定回到勾选。
- 该值虽然已经在 `_board_payload()` / `normalize_board_payload()` 中往返，且关闭 Sheet、
  保存并重开同一 `.tlproj` 都不会丢失，但它被放在了错误层级：这是用户的工作方式偏好，
  不是某张 Board 的内容属性。
- `show_titles` 与 `show_sources` 也具有同一「Board 默认值 + 新 Board 重建」结构，但
  两者展示的是 Board 内容，不能顺手跟随本批移动。

### 1.2 已排除的误判

- 独立 offscreen 探针确认：切为 `False` 后，`Sheet close → open` 仍是 `False`。
- 独立临时 `.tlproj` 探针确认：保存 `False` 后，新的 `MainWindow.open_project()` 仍为
  `False`。
- 所以“每次打开都重置”不是 Sheet 的 `reset_sheet_session()` 直接造成的；它更可能是
  新建 Board，或退出后没有保存工程而重新创建了默认 workspace。

### 1.3 需同时收口的反向问题

`compare_filter` 与 View 库 pin 当前只存于 Page，既不序列化，也未被
`reset_sheet_session()` / `reset_project_state()` 清理。它们在同一进程中会跨 Board、甚至
跨项目残留，属于 session state 泄漏；本批在不扩大持久化范围的前提下修正。

### 1.4 明确不处理

- 不修改 `fit_on_open()`、弹性 halo、minimap、canvas extent 或 Board viewport 的恢复策略。
  弹性画布计划已经定义「每次打开和切换 Board 时 Fit」。
- 不将偏好写入全局 `QSettings`；这会使不同工程相互覆盖，且会把“项目可复现状态”与
  “本机偏好”混在一起。
- 不修改卡片动作本身、图标、hover 触发、删除/撤销、页面布局或现有项目数据之外的
  TraceLab 设置。

## 2. 数据与迁移合同

### 2.1 新 payload 形态

将嵌套 UltraView schema 从 3 升至 4（顶层 `ProjectDocument` schema 不升级）：

```json
{
  "schema": 4,
  "workspace": {
    "active_board_id": "…",
    "show_card_actions": false,
    "boards": [
      {
        "board_id": "…",
        "show_titles": true,
        "show_sources": true
      }
    ]
  }
}
```

- `show_card_actions` 从 Board payload 移除，成为 workspace 的唯一字段；Board dataclass、
  `_copy_board()`、`_BOARD_PAYLOAD_KEYS` 和 `set_presentation_flags()` 不再拥有它。
- 新 `set_workspace_show_card_actions(workspace, checked)` 是唯一 Qt-free mutator；它必须
  调用 `mark_workspace_mutated()`，但不得改变 Board membership、布局、viewport 或 digest。
- schema 升级保证旧应用遇到 schema 4 时走现有 future-schema opaque 保留，而不是读取后
  静默丢掉该字段。

### 2.2 旧工程迁移

- schema 1–3 或缺少 `workspace.show_card_actions` 的工程，统一迁移为 `False`，以落实新的
  默认合同；不尝试从旧的每 Board `show_card_actions=True` 猜测用户意图。
- 旧 Board 中同名字段视为已退休字段：读取时消费但不写入 `passthrough`，下一次保存时从
  Board payload 移除，避免产生“双真相”。
- 当前项目若用户希望常驻，可重新勾选一次；之后值会随该项目保存。迁移不改 View、卡片、
  布局、来源、预览或导出内容，也不弹阻塞对话框。
- schema 大于 4 的 opaque payload 保留、警告、用户显式 mutation 后再写的现有合同不得退化。

## 3. 实施任务

### Task 0 — 冻结状态矩阵并先写红测

**Files:** `tests/ui/test_ultraview_state.py`、`tests/ui/test_ultraview_page.py`、
`tests/ui/test_ultraview_mode_integration.py`、`tests/ui/test_ultraview_project_session.py`。

1. 记录执行时 HEAD、dirty scope 和当前 `show_card_actions` 的所有读/写点；若
   `ultraview_state.py`、`page.py`、`widgets.py` 或 coordinator 正被并行修改，先明确
   基线，不能把这批改动混进其他提交。
2. 新增失败测试：default workspace 的开关为 `False`；切换开关后创建、复制、切换多个
   Board 都是同一个值；标题/来源仍保持各 Board 的独立值。
3. 新增失败测试：schema 1/2/3 与缺字段输入迁移为 false；schema 4 round-trip 只在
   `workspace` 写一次；退休的 Board 字段不会从 `passthrough` 重现；future schema opaque
   合同不变。
4. 新增真实 Page/Coordinator 测试：菜单和右上「显示」浮层同步、取消常驻仍可 hover/
   keyboard focus 显示动作条；关闭再打开 Sheet、保存重开项目、新建 Board 均不改该值。
5. 将已发现的 `UltraView viewport: unknown board …` 生命周期警告单独写成最小复现；它不是
   本计划的根因。若与本批变更无关，保留为独立 follow-up，不得通过吞日志掩盖。

**退出条件：** 红测能分别抓住「默认错误」「新 Board 重置」「项目恢复」「会话泄漏」，而
不是只断言一个 checkbox 的初始值。

### Task 1 — Qt-free workspace preference 与 schema 4 迁移

**Files:** `mf4_analyzer/ui/ultraview_state.py`、`tests/ui/test_ultraview_state.py`。

1. 在 `UltraViewWorkspaceState` 添加 `show_card_actions: bool = False`；让
   `default_workspace()` 明确生成 false。
2. 将卡片常驻开关从 `UltraViewBoardState`、Board copy、Board serializer/parser 和
   Board presentation mutator 移除；保留 title/source 的现有 Board owner。
3. 增加 workspace mutator 与 schema 4 serializer/parser；正常 payload 只出现一个
   `workspace.show_card_actions`，不得在任何 Board 再出现同名键。
4. 实现 §2.2 的迁移/retired-key 消费，并为 schema 1–4、非法类型、future opaque、
   多 Board、复制 Board 建立 deterministic 测试。
5. 保持 state 模块 Qt-free；不得因为这一个布尔值向状态层引入 Page、QSettings、
   MainWindow 或 widget import。

**退出条件：** 所有新/旧项目可解析、重新保存稳定；新建 Board 不再参与这个偏好的默认决策。

### Task 2 — Page 投影与 Coordinator 单一写入口

**Files:** `mf4_analyzer/ui/chart_stack/ultraview/page.py`、
`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、
`mf4_analyzer/ui/main_window/ultraview_coordinator.py`、相应 page/integration tests。

1. 保留现有 `show_card_actions_toggled(bool)` 用户意图 signal 和两个显示入口的交互；只将
   receiver 改为 workspace mutator，避免引入第二套控件或重做 hover 行为。
2. `Page.set_workspace()` 在投影 active Board 前同步 workspace preference；`set_board()`、
   `_apply_lod_chrome()` 和两个 `CardViewModel` 构造点均读取同一个页面投影值。测试专用
   `set_board()` 路径应默认 false，不能靠已废弃 Board 字段兜底。
3. toolbar 的 action 构造默认改为 unchecked；右上 display popover 的 checkbox 也从
   workspace 值设置，并在 `blockSignals` 中双向同步，避免 programmatic refresh 误写状态。
4. Coordinator 的 handler 调 workspace mutator 后仅刷新 Page；不重新 capture preview、不改
   card placement、不写 viewport，也不让 board/title/source owner 混入这条路径。
5. 在 display popover 的说明中补一行非阻断文案：
   `适用于当前工程的所有 Board；保存项目后保留。` 同步 `ui/hints.py`、`ui/quickref.py`
   与 UltraView guide 中相应帮助文字和测试。

**退出条件：** 任何入口一次 toggle，两个入口、所有当前/后续 Board 的动作条同时更新；
取消常驻时 hover/focus reveal、可访问性、删除入口和原有图标操作均不回退。

### Task 3 — 会话态显式复位，杜绝跨工程泄漏

**Files:** `page.py`、必要时 `widgets.py`；`tests/ui/test_ultraview_page.py`、
`tests/ui/test_ultraview_mode_integration.py`、`tests/ui/test_ultraview_project_session.py`。

1. 为 `reset_sheet_session()` 增加明确的 transient reset：对比筛选回到
   `COMPARE_FILTER_ALL`，View 库 pin 回到 false，然后沿用现有 focus/panel/selection/
   replacement/presentation 清理顺序。
2. `reset_project_state()` 与项目 restore 都经既有 `_reset_page_runtime()` 走这条路径；
   断言从项目 A 选择筛选/钉住后，项目 B 与新 workspace 不会继承它。
3. 不把筛选、pin、弹层开关、选择、搜索词、分组展开状态写入 Board/workspace payload；
   它们不是可复现的对比内容。若发现某个状态会在 close 后保留，只能在测试中明确其
   session 规则，不能借此新增静默持久化。
4. 保持 `fit_on_open()` 既有行为；与本任务有关的测试不得恢复“开窗回到上次 pan/zoom”
   的旧断言。

**退出条件：** 关闭/重开 Sheet 不会影响工作区偏好和 Board 内容，但不会带着筛选/pin
进入下一次会话或另一工程。

### Task 4 — 相关门禁、文档与前台验收

**Files:** 测试及既有帮助文件；生成证据仅放 `.state/ultraview-preference-persistence/`。

1. 先跑 owner tests：

   ```bash
   TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
     .venv/bin/python -m pytest \
     tests/ui/test_ultraview_state.py \
     tests/ui/test_ultraview_page.py \
     tests/ui/test_ultraview_mode_integration.py \
     tests/ui/test_ultraview_project_session.py -q
   ```

2. 再跑相关结构与帮助门禁：

   ```bash
   TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
     .venv/bin/python -m pytest \
     tests/ui/test_no_lambda_signal_connections.py \
     tests/ui/test_main_window_state_ownership.py \
     tests/ui/test_import_boundaries.py \
     tests/test_signal_no_gui_import.py \
     tests/ui/test_hints.py tests/ui/test_quickref.py tests/test_help_content.py -q
   git diff --check
   ```

3. 不因本批 UI/state 小改动默认跑全套 pytest；若后续合并为发布里程碑，由唯一协调者按
   `AGENTS.md` 的两段全量门禁执行。
4. macOS 前台人工验收：初次进入为未勾选；hover 与 Tab 焦点显示操作；勾选后新增/
   切换/复制 Board 仍常驻；保存 `.tlproj` 后重开仍常驻；关闭 Sheet 后仍常驻；筛选/pin
   在关闭或切工程后确实复位。Windows frozen 仍是独立发布门。

## 4. 验收矩阵

| ID | 场景 | 自动化断言 | 前台观察 |
|---|---|---|---|
| PP-01 | 新项目首次打开 | workspace 值为 false；两个 checkbox false | 操作条不常驻，hover 可见 |
| PP-02 | 单次切换 | 一个 mutator 调用；两个入口同步 | 无闪烁、无重复 Toast |
| PP-03 | 新建/复制/切换 Board | 统一 workspace 值保持 | 不需要重新勾选 |
| PP-04 | 保存/重开 | schema 4 JSON 只写 workspace 字段；恢复值相同 | `.tlproj` 重开一致 |
| PP-05 | 旧 payload 迁移 | schema 1–3 → false；退休 key 不回写 | 旧工程不丢 View/布局 |
| PP-06 | 关闭 Sheet | preference/Board 内容不变；filter/pin reset | 再打开无筛选残留 |
| PP-07 | 切换/恢复另一工程 | filter/pin 不跨工程；workspace preference 只来自目标项目 | 项目 A 不污染项目 B |
| PP-08 | 可访问性与行为 | hover/focus reveal、action focus 顺序、删除入口回归 | 鼠标与键盘均可发现操作 |

## 5. 风险与回滚

- **迁移风险：** schema 3 的旧 Board 值为 true 无法区分默认和用户显式选择。本计划选择
  新默认 false，并通过帮助文案明确可重新启用；这是有意的 UX 迁移，不应伪装成无损迁移。
- **双真相风险：** 若只添加 workspace 字段却保留 Board 同名字段，切换 Board 后会再次
  回退。Task 1 必须完整移除 retired Board key 的读写和 passthrough 回灌。
- **范围蔓延风险：** session reset 只处理已审计的 filter/pin；不能趁机改画布、布局、
  preview residency 或全局设置。
- **回滚：** 若 schema 4 导致第三方/旧安装互操作问题，回滚整个 schema 4 提交；不得通过
  降级 schema 数字但保留新字段来伪造兼容。

## 6. 执行前提

- 本工作区当前有 View markup/cursor persistence 等并行未提交文件。实施前必须再次检查
  `git status --short`，只暂存本计划的 owner 文件；本计划文本本身不授权改动这些文件。
- 每个任务先写能失败的聚焦测试，再写实现；运行期探针使用隔离临时项目，不向真实
  `QSettings` 写设置。
