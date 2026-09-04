# “最近打开”搜索弹层优化实施计划

- 日期：2026-09-04
- 状态：READY FOR REVIEW / NOT STARTED
- 当前动作：只完成 HTML、Spec 与实施计划；未修改生产 Python / QSS
- 冻结分析基线：`a9a2f562`
- 现有功能基线：`a3a9736e`
- 对应规格：
  [`2026-09-04-recent-open-search-popup-spec.md`](../specs/2026-09-04-recent-open-search-popup-spec.md)
- 视觉参考：
  [`2026-09-04-recent-open-search-panel.html`](../ui-prototypes/2026-09-04-recent-open-search-panel.html)

## 0. 目标、边界与执行前提

把当前“打开”箭头下的普通 `QMenu` 替换为收窄的可搜索 popup，并一次性关闭以下五项：

| 合同 | 实施结果 |
| --- | --- |
| 更多记录 | store 默认保留文件 40 / 项目 10；popup 统一混排 |
| 更高面板 | 最大高 700px、40px 行、正常桌面至少 13 个完整行 |
| 名称 / 路径分隔 | 800px 最大宽度，42/58 双列与真实 divider |
| Everything 式模糊搜索 | 最近记录内即时 token + subsequence 搜索，不做磁盘索引 |
| 用户最新反馈“太宽” | HTML 与 Qt 最大宽度统一为 800px，不由长路径撑宽 |

执行前提：用户确认 Spec 的四个提案数值——800px、700px、文件 40 + 项目 10、
`⌘K / Ctrl+K`。若只确认视觉而未确认容量或快捷键，只实施已确认部分，不自行替用户扩大
产品合同。

本计划不启动 agent、不改代码、不提交；后续用户明确要求实施时，再按本计划执行。

## 1. Worktree 保护与 owner

### 1.1 当前 checkout 事实

- branch：`main`，相对 `origin/main` ahead 6；
- HEAD：`a9a2f562bc55620138f2b15de25cf65510cb8198`；
- 现有 recent-open 功能来自 `a3a9736e`；
- 当前存在与本功能无关的 tracked 删除：
  `assets/icons/tracelab.icns`、`assets/wwt/winwert_export_template.wwt`、两张
  `docs/reports/*.png`；
- 当前存在与本功能无关的 untracked：`code_stats_report.html`、根目录 `ssh-keygen`；
- `docs/analyzer/plans/2026-09-04-honesty-effective-facts-quick-open-plan.md` 是既有未跟踪
  综合计划，不在本轮改写范围；本计划只聚焦已上线 recent-open 的 follow-up。

实施者不得恢复、删除、格式化、stage 或提交上述无关路径。任何发布操作只允许 named-path
staging；禁止 `git add -A`。

### 1.2 文件 ownership

| owner | 允许修改 | 职责 |
| --- | --- | --- |
| recent data / matcher | `mf4_analyzer/ui/recent_files.py`、`tests/ui/test_recent_files_store.py` | 容量、全局 MRU、纯搜索 |
| popup presentation | `mf4_analyzer/ui/widgets/recent_open_popup.py`（新）、`mf4_analyzer/ui_kit/style.qss`、`tests/ui/test_recent_open_popup.py`（新） | chrome、双列、焦点、selection、geometry |
| toolbar / window integration | `mf4_analyzer/ui/toolbar.py`、`mf4_analyzer/ui/main_window/window.py`、`tests/ui/test_toolbar.py`、`tests/ui/test_open_and_save_entry.py` | 单实例 popup、typed intent、store 投影 |
| command / discovery | `mf4_analyzer/ui/command_registry.py`、`mf4_analyzer/ui/main_window/command_coordinator.py`、`mf4_analyzer/ui/hints.py`、`mf4_analyzer/ui/quickref.py`、主帮助页及对应 tests | Ctrl/Cmd+K、文案单一事实源 |

不要把 popup widget 放进 `window.py`，不要把 matcher 放进 `toolbar.py`，不要为了复用私有
paint code 去修改 `ViewOverflowPopup`。若实施中需要扩大 MainWindow state whitelist 或新增跨
mixin 写入，立即停线并重新判断 owner。

## 2. 依赖顺序与里程碑

```text
T0 红测 / 基线冻结
 ├── T1 store + 纯 matcher
 └── T2 popup widget + scoped QSS（可用冻结 DTO 开始）
          ↓
      T3 toolbar / MainWindow 接线
          ↓
      T4 command registry + hints / QuickRef / help
          ↓
      T5 owner + boundary + Cocoa 验收
```

T1 与 T2 只有在不同实施者拥有完全独立文件时可并行；T3 必须等待两者接口稳定。T3/T4 都会
触及 toolbar / window command seam，不并行改同一文件。全量 gate 不是本任务的入口或默认
收尾；本计划只跑聚焦 owner 和相关边界测试。

## 3. T0 — 冻结新合同（先红后绿）

### 3.1 执行前快照

```bash
git status --short --branch
git rev-parse HEAD
pgrep -afil pytest
```

确认同一 checkout 没有正在运行的 full pytest。记录与本任务有关的 dirty fingerprint；若测试
期间相关源文件变化，本轮结果标为 `UNVERIFIED` 并在稳定 snapshot 重跑。

### 3.2 受影响基线

仅运行当前功能的现有测试，不跑全套：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_recent_files_store.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_open_and_save_entry.py \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_quickref.py \
  tests/ui/test_hints.py \
  tests/test_help_content.py \
  tests/ui_kit/test_search_field.py
```

若出现与 current HEAD 已有行为有关的失败，先记录为 baseline issue；不得借本任务修无关项。

### 3.3 新红测

先新增 / 修订测试并确认因**缺少新行为**而失败：

1. `test_recent_files_store.py`
   - 默认文件 / 项目 cap 为 40 / 10；
   - `all_entries()` 保持跨 kind 的全局 MRU；
   - 旧 v1 JSON 直接读取；
   - `lowfri 0526` 跨字段 token；`w250lf` subsequence；大小写 / NFKC / 路径分隔符；
   - 排序 tier、gap、MRU tie-break 和 spans 确定；
   - matcher 调用期间 settings / exists probe 为 0。
2. 新建 `test_recent_open_popup.py`
   - `RecentOpenPopup` 存在、单实例 shell 属性正确；
   - 800×700、42/58、40px 行、至少 13 行、screen clamp；
   - filename / path 独立列与无 horizontal scrollbar；
   - 搜索计数、高亮 projection、missing / empty / clear；
   - Up/Down/Enter/两段 Esc、外点关闭、20 次重开无实例增长。
3. `test_toolbar.py` / `test_open_and_save_entry.py`
   - recent QMenu actions 的旧断言改为 popup typed intent；
   - 箭头不触发主 open；双击 / Enter 只发一次；clear 后在打开 popup 内显示空态；
   - MainWindow 投影使用全局 MRU。
4. `test_standard_desktop_interactions.py`
   - `CommandId.OPEN_RECENT` 的 fallback、NativeText、WindowShortcut 和唯一 QAction；
   - shortcut 关闭时打开 popup，已开时聚焦 / selectAll；
   - 不与 `OPEN_PROJECT` / `FIND` 双发。
5. discovery / help tests
   - 旧 `4` / `8` 断言先改成 10 / 40；
   - 搜索、缺失、清除和 native shortcut 文案从正式 owner 投影。

红测证据记录精确 node id 与失败原因。若新增测试在无实现时已绿，说明测试没有锁住目标，
先修测试再继续。

## 4. T1 — Recent store 与纯 matcher

### 4.1 `ui/recent_files.py`

- 将 constructor 默认值改为 `max_files=40, max_projects=10`；显式注入值和分类型 `_evict`
  算法保持。
- 新增 `all_entries()`，直接以 tuple 返回 `_load()` 的全局序列；`entries(kind)` 保留。
- 保留 `KEY_RECENT_V1`、`RecentEntry`、JSON 字段和 warning-once 容错，不做 schema migration。
- 保留 `format_recent_label` / `missing_recent_label` 作为兼容 helper；popup 不再依赖它们。

### 4.2 纯搜索边界

在同一 neutral-ish recent domain 中新增冻结 DTO 与纯函数，建议接口：

```python
@dataclass(frozen=True)
class RecentMatch:
    entry: RecentEntry
    filename: str
    display_parent: str
    name_spans: tuple[tuple[int, int], ...]
    path_spans: tuple[tuple[int, int], ...]
    rank: tuple

def match_recent_entries(
    entries: tuple[RecentEntry, ...],
    query: str,
    *,
    home: str | None = None,
) -> tuple[RecentMatch, ...]:
    ...
```

实现 NFKC + casefold + slash 统一时，同时建立 normalized-index → source-index 映射，排序与
highlight 共用同一 matcher 结果。空 query 返回输入 MRU 顺序；非空 query 执行 Spec §4 的
AND / tier / gap / recency 规则。

不得在 matcher 中调用 QSettings、`Path.exists()`、QIcon 或 QWidget。不要把时间字符串重新
解析为排序事实；`all_entries()` 的输入位置就是最终 recency tie-break，避免 malformed / 时区
比较产生第二套顺序。

### 4.3 T1 gate

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/ui/test_recent_files_store.py
```

Stop rule：纯 matcher 若需要 UI font metrics 或 MainWindow context 才能给出结果，owner 错误，
不得继续接 popup。

## 5. T2 — 新建 presentation-only popup

### 5.1 组件结构

新建 `mf4_analyzer/ui/widgets/recent_open_popup.py`：

- `RecentOpenPopup(QFrame, Qt.Popup)`：唯一 top-level transient owner；
- `_RecentOpenSurface`：paint 12px 圆角白底与 1px border；
- `SearchField`：复用 `ui_kit.widgets.SearchField`，不新造 clear / search icon；
- 内部两列表格模型：只接 immutable `RecentMatch` / exists snapshot；
- `QTableView` 或同等级 model/view：row selection、固定 40px、header、vertical scrollbar
  always on、horizontal off；
- scoped `QStyledItemDelegate`：filename / path、项目 badge、missing badge、匹配 spans 与
  current row；
- footer：键盘提示与 `清除最近记录`。

首选 model/view 而不是为 50 行各挂一组按钮 / label：selection、scroll、column width 和
keyboard current 只有一个 owner，也避免 row rebuild 积累 Qt child wrappers。

### 5.2 信号与状态

- signals：`open_requested(str)`、`clear_requested()`、`closed()`；
- public methods：`populate(entries)`、`show_at(anchor)`、`focus_search(select_all=False)`、
  `reset_for_show()`；仅暴露完成集，不把内部 model / delegate 变成 Toolbar API；
- 显式初始化 `_entries`、`_matches`、`_exists_by_identity`、`_current_identity`、
  `_closed_emitted`；hide / close / new show 对称复位；
- `populate()` 只在 entry snapshot 变化时做一次 `RecentFilesStore.exists`；搜索只过滤缓存；
- missing rows disabled 且导航跳过；如果全部 missing / 无结果，current invalid、Enter no-op；
- table 维持 NoFocus 或等价策略，让搜索输入保持文本焦点；event filter 捕获 Up/Down，
  `returnPressed` 打开 current，`escape_requested` 关闭。

### 5.3 chrome 与 geometry

- constructor 第一帧前调用 `apply_popup_shell(self)`，外层 NoFrame / NoSystemBackground；
- surface / list well 留 1px paint guard；divider 由 viewport/delegate paint；
- 常量精确实现 Spec：max width 800、target height 700、row 40、screen margin 8、anchor gap 4；
- `show_at()` 使用 anchor 所在 screen 的 `availableGeometry()`；先 size、后 move、再 show；
- popup 已显示时 populate 不改 outer width / height；
- 每次 projection 后只 flush 自己必要的 layout request，不调用全局 `processEvents()`。

### 5.4 scoped QSS

在 `ui_kit/style.qss` 只增加 `#recentOpen*` selectors：search 周边、header、table、footer、
button states。不得修改全局 `QMenu`、`QTableView` 或 `QToolButton` 家族；SearchField icon 继续由
既有高 specificity rule 保护。任何边框写 long-form 属性，避免 `border:` shorthand 抹掉圆角。

### 5.5 T2 gate

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_recent_open_popup.py \
  tests/ui_kit/test_search_field.py \
  tests/ui_kit/test_qss_border_shorthand.py
```

Stop rules：

- 第一帧出现 native 方形 backing / 双框时，修 shell / pixel owner，不用加大 radius 掩盖；
- 分隔线若只能在 parent grab 看见、实际 table viewport 看不见，测试与实现都退回修正；
- row selection 若抢走搜索输入导致普通字符不能继续输入，不接受以“再点搜索框”作为交互。

## 6. T3 — Toolbar 与 MainWindow 接线

### 6.1 Toolbar

- 从 `toolbar.py` 删除 recent 专用 `QMenu` actions、`_recent_clear_action`、
  `_add_recent_action` 与不再使用的 imports；保存 split 的 QMenu 保持不变。
- `_make_open_split()` 创建一个 parented `RecentOpenPopup` 单实例。
- 新增唯一 public method `show_recent_popup()`：
  1. 已显示 → 只 `focus_search(select_all=True)`；caret click 的 toggle-close 在它的 named
     click handler 中明确处理；
  2. 未显示 → 同步 emit `recent_menu_about_to_show`；
  3. owner `set_recent_entries()` 已完成后 reset + `show_at(self._open_split)`。
- popup intents 只转发到既有 Toolbar signals；popup closed 对称更新 caret expanded property。
- `set_recent_entries(entries)` 只调用 popup.populate，不排序 / 搜索 / 打开文件。

保留 signal 名 `recent_menu_about_to_show` 与 hint id `toolbar.recent_menu`，不同时新增 popup
命名 alias。内部 `_recent_menu` 删除后，测试不得继续用 private QAction 结构取巧。

### 6.2 MainWindow

- `_populate_recent_menu()` 方法名可保留，body 改为
  `toolbar.set_recent_entries(self._recent_files.all_entries())`；不新增窗口 state。
- `_clear_recent_files()`：owner clear 后投影空 tuple，使仍打开的 popup 即时显示空态。
- `_open_recent_path()` 与 `_open_paths([path])` seam 原样保留；打开成功后 discovery 退役，
  race / missing 时 remove 仍可观察。

### 6.3 T3 gate

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_toolbar.py \
  tests/ui/test_open_and_save_entry.py \
  tests/ui/test_recent_open_popup.py
```

另外运行一次机械 grep，确认 recent path 只剩 popup typed intents，没有第二个打开路径：

```bash
rg -n "_recent_menu|_add_recent_action|recent_open_requested|_open_recent_path" \
  mf4_analyzer/ui tests/ui
```

## 7. T4 — Command registry 与发现性文案

### 7.1 唯一快捷键 owner

- `CommandId.OPEN_RECENT = "open_recent"`；metadata：`打开最近…`、fallback `Ctrl+K`、
  `CommandScope.WINDOW`、help `搜索最近打开的项目和文件`；
- 加入 `CommandCoordinator._INSTALL_WINDOW_SHORTCUTS`，唯一 QAction 用
  `Qt.WindowShortcut`；
- `_connect_host_slots()` 连接 named `_on_open_recent`，只调用
  `host.toolbar.show_recent_popup()`；popup 已开时同一方法聚焦 / 全选；
- Toolbar caret tooltip 从 `tooltip_for(CommandId.OPEN_RECENT)` 投影或由 coordinator
  bind 注入，禁止在 toolbar 再手写 `⌘K` / `Ctrl+K`；
- 不创建额外 `QShortcut`，不改变 `CommandId.FIND` 的 SearchField 路由。

### 7.2 文案扇出

- `ui/hints.py`：保持 id / retire / priority，文案改为
  `打开旁箭头可搜索最近的项目和文件`，继续通过 `HINT_MAX_WIDTH`；
- `ui/quickref.py`：“打开数据 / 项目”精确写 10 项目、40 文件、名称 / 路径搜索、缺失、
  清除与 registry NativeText；
- `mf4_analyzer/help/TraceLab-使用说明.html` load slide 同步；只改当前说明，不重写旧版本
  changelog；
- 若帮助 deck 使用结构化 JS 数据，保持其 schema / 排版，不把 HTML prototype 嵌进去。

### 7.3 T4 gate

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_quickref.py \
  tests/ui/test_hints.py \
  tests/test_help_content.py
```

用 `rg` 搜索旧容量和硬编码 shortcut；旧的 dated plan/spec 可保留历史事实，但当前帮助 / 测试 /
运行时代码不得残留：

```bash
rg -n "最近 4 个项目|8 个文件|Ctrl\+K|⌘K|_recent_menu" \
  mf4_analyzer tests
```

Stop rule：若 `Ctrl/Cmd+K` 与现有真实 binding 冲突，先回到用户决策；不得暗中换键或注册两个
相同 WindowShortcut。

## 8. T5 — 集成、边界与真实前台验收

### 8.1 聚焦 owner tests

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_recent_files_store.py \
  tests/ui/test_recent_open_popup.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_open_and_save_entry.py \
  tests/ui/test_standard_desktop_interactions.py \
  tests/ui/test_quickref.py \
  tests/ui/test_hints.py \
  tests/test_help_content.py \
  tests/ui_kit/test_search_field.py
```

### 8.2 边界 gates

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui/test_qsettings_isolation.py \
  tests/ui/test_qmenu_density.py \
  tests/ui_kit/test_qss_border_shorthand.py
```

这里没有 signal/DSP、batch renderer、pg canvas backref 或 packaging seam 变更，因此不跑
signal / batch / pg canvas 的无关边界套件。

### 8.3 离屏确定性 probe

用 50 条 deterministic entries 构造 production `RecentOpenPopup`，QSettings 必须注入临时 INI；
不得读取或修改开发者真实 `MF4Analyzer/DataAnalyzer` store。至少记录：

- popup outer / search / header / viewport / footer rect；
- 两列实际宽度与 divider x；
- full-row count、scrollbar gutter、horizontal scrollbar 状态；
- 800×700 正常屏幕、窄屏、矮屏和负坐标副屏 clamp；
- 20 次 open/Esc 后 child / signal / top-level popup 数。

离屏 probe 只证明结构与逻辑，不写“视觉验收通过”。

### 8.4 macOS Cocoa 前台

使用当前项目 runtime 和 production stylesheet 打开真实 Toolbar → recent popup；若需要构造
50 条数据，使用临时 QSettings / isolated host，不污染真实 recent history。保存日志与截图到：

`docs/analyzer/verify/2026-09-04-recent-open-search-popup/`

逐项验收：

1. 最大宽度 800px 的视觉比例与收窄 HTML 一致，不遮住不必要的大块图表；
2. 700px 高时完整显示至少 13 行，最后一行不被 footer 裁切；
3. 文件名 / 路径 divider 从 header 到全部 rows 共线，无白色 child 覆盖、无内缩台阶；
4. 四圆角无 native 方框 / 原生阴影泄漏；搜索 icon / clear icon 不变成白色胶囊；
5. 输入 `lowfri 0526`、`w250lf`、`p166 tlproj`，相关度 / 高亮 / 计数符合 Spec；
6. Up/Down/Enter、双层 Esc、`⌘K`、外点关闭和 caret expanded 状态正确；
7. 长中文 / 英文文件名与长路径只在各自列省略，tooltip 显示完整绝对路径；
8. missing、0 结果、clear 后空态可区分，持续输入无肉眼卡顿。

真实 Cocoa 未完成时必须写 `UNVERIFIED`；不得用 HTML、offscreen 或 source inspection 替代。
Windows 前台 / frozen executable 本任务不要求；若未运行，同样显式 `UNVERIFIED`。

### 8.5 交付卫生

```bash
git diff --check
git status --short --branch
git diff --name-only
/usr/bin/python3 scripts/lessons/check.py --status
```

本任务不需要 full suite。若后续并入 release，由 release 协调者在稳定 snapshot 复用一次正式
两段式 full gate，不在本 feature branch 重复运行。

## 9. Stop rules

任一条件成立即停线并报告，不以局部绿测继续：

- 需要全盘扫描 / watcher / 索引服务才能满足搜索；这超出已确认“最近记录”范围；
- popup 搜索每次输入触发 QSettings 或文件存在性 I/O；
- 新快捷键与现有 registry 真实冲突；
- MainWindow ownership whitelist、lambda 棘轮或 import boundary 需要放宽；
- 只能用全局 QMenu/QTableView QSS 才能得到目标视觉；
- popup 在 Cocoa 首帧有方形 backing、双框、body 四边台阶或搜索 icon 白块；
- 测试为了通过而硬编码执行顺序、sleep、xfail 或吞掉异常；
- focused tests 运行期间相关文件变化，使结果不再对应稳定 snapshot。

## 10. 完成定义

- [ ] Spec 数值与 shortcut 经用户确认；
- [ ] T0 新合同测试先红且失败原因精确；
- [ ] store 保留 40 文件 + 10 项目，旧 v1 兼容，全局 MRU 正确；
- [ ] matcher 的 token、subsequence、排序、spans 与无 I/O 合同全绿；
- [ ] popup 最大 800×700、42/58 双列、40px 行、至少 13 行且屏幕夹取正确；
- [ ] mouse / keyboard / missing / empty / clear / lifecycle 全绿且只发一次 intent；
- [ ] recent 打开继续唯一复用 `_open_recent_path` → `_open_paths`；
- [ ] OPEN_RECENT 由 command registry / coordinator 单一拥有，无手写 shortcut 副本；
- [ ] hints、QuickRef、主帮助页与 10/40 / 搜索行为一致；
- [ ] focused owner 与 boundary gates 全绿，未放宽任何棘轮；
- [ ] Cocoa 前台证据完成，任何未跑平台明确 `UNVERIFIED`；
- [ ] `git diff --check` 通过；diff / stage / commit 不含现有资产删除、综合计划或根目录杂项。
