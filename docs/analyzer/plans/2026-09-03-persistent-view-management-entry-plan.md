# View 管理入口常驻实施计划

- 日期：2026-09-03
- 状态：IMPLEMENTED / OFFSCREEN VERIFIED（macOS Cocoa 前台因系统锁屏待补）
- 决策：采用方案 1；复用现有 `viewTabOverflow` 按钮和“全部 View”popup，不增加第二个入口
- 基线：`8f36b5d1`
- 对应规格：
  [`2026-09-01-view-overflow-close-interaction-spec.md`](../specs/2026-09-01-view-overflow-close-interaction-spec.md)

## 0. 目标与边界

解决“多个 View 全部排得下时，`关闭其他` / `关闭全部` 无入口”的发现性缺口。

最终状态矩阵：

| View 状态 | 常驻入口 | popup | footer |
| --- | --- | --- | --- |
| 1 个 View | `⋯` | 可打开并列出唯一 View | 两项批量操作 disabled |
| 多个 View、全部可见 | `⋯` | 可打开并列出全部 View | `关闭其他 N-1 个…` / `关闭全部 N 个…` |
| 存在隐藏 View | `»H` | 同一个 popup，列出全部 View | 同上；`H` 仅为隐藏数量 |

保持不变：

- 当前 View 色标 `×` 的重入防误触合同；
- 标签切换、双击重命名、拖拽排序和右键菜单；
- popup 行内关闭、批量确认和时域/分析 owner cleanup；
- “关闭其他”保留 stable current `view_id`；
- “关闭全部”最终留下一个重置的空白 View；
- View 上限、持久化和 UltraView 语义。

明确不做：

- 不把两个危险按钮直接放到 View 横栏；
- 不增加右键批量入口或拆分 `+` 按钮；
- 不新增撤销、manager API、MainWindow state 或确认框语义；
- 不借机重构 popup、tab close 或 QSS。

## 1. Worktree 保护与 owner

当前 worktree 有与本任务无关的 tracked 删除和 untracked 文件。实施者只能修改：

- `mf4_analyzer/ui/view_tabbar.py`
- `mf4_analyzer/ui/widgets/view_overflow_popup.py`
- `mf4_analyzer/ui/quickref.py`
- `mf4_analyzer/ui_kit/style.qss`（仅同步既有入口注释，不改样式 token）
- `tests/ui/test_view_tabbar.py`
- `tests/ui/test_quickref.py`
- 本 Spec/Plan

若实现必须超出上述范围，立即停线并向主代理说明原因。禁止还原、删除、格式化或提交
已有无关改动。

## 2. T0 — 先冻结新入口合同（红测）

Owner：`tests/ui/test_view_tabbar.py`、`tests/ui/test_quickref.py`

先增加或调整以下可执行合同：

1. roomy、多 View、零隐藏标签时，管理入口仍可见、文字为 `⋯`，点击后 popup 列出全部 View；
2. compact 但零隐藏标签时，入口仍可见且能打开 popup；
3. overflow 时同一按钮显示 `»H`，`H == len(overflow_indices())`；
4. 唯一 View 时入口仍可打开，行末关闭及两个 footer 按钮均 disabled；
5. footer 多 View 文案含精确数量和 `…`，删除一行后数量实时重投影；
6. 从 overflow 连续删到全部标签重新可见时，popup 保持打开，入口切回 `⋯`；
7. Space/Enter 打开、Esc 关闭并恢复入口焦点的既有合同在两种入口文案下均成立；
8. quickref 同时说明 `⋯` 为常驻管理入口、`»N` 为隐藏数量状态。

建议测试名：

- `test_view_management_entry_is_visible_and_opens_when_all_tabs_fit`
- `test_compact_row_without_hidden_tabs_keeps_management_entry`
- `test_overflow_entry_reports_hidden_count_on_the_same_button`
- `test_single_view_management_popup_disables_all_close_actions`
- `test_popup_bulk_labels_project_exact_counts_and_dialog_ellipsis`
- `test_popup_stays_open_when_row_close_clears_overflow`
- `test_view_management_entry_has_stable_measured_reserve`

修改生产代码前，新入口断言应红；既有切换、重命名、重排、误触保护测试必须绿。

## 3. T1 — 常驻入口与测量式宽度预算

Owner：`mf4_analyzer/ui/view_tabbar.py`

实施步骤：

1. 保留 `_overflow` 私有对象和 `viewTabOverflow` object name，避免无意义的 QSS/测试迁移；
   更新注释、tooltip 和 accessible name，使其语义成为 View 管理入口。
2. `_set_overflow(hidden)` 不再隐藏入口或仅因 `hidden == []` 关闭 popup：
   - 无隐藏项：`⋯`；tooltip `管理全部 <N> 个 View`；
   - 有隐藏项：`»H`；tooltip 同时表达“另有 H 个未显示”和“管理全部 N 个 View”。
3. `_on_overflow_clicked()` 允许零隐藏项时打开 popup；继续复用 `_overflow_rows()`、typed
   intents、popup lifecycle 和 250 ms reopen guard。
4. `_sync_overflow_popup()` 在零隐藏项时继续 `populate()`，不得关闭 popup。
5. roomy/compact/overflow 三次 fit 均永久预留入口的最宽可能文案。宽度必须来自 live
   `sizeHint()/minimumSizeHint()` 测量；不得写死像素，也不得让 `⋯ ↔ »H` 产生循环重排。
6. 入口固定在 tabs 与 `+` 之间；新增/删除 View、切换 active、解除 overflow 时不移动目标。

停线条件：

- 需要写死按钮宽度才能稳定 fit；
- 常驻入口导致当前标签被隐藏、roomy/compact/overflow 来回抖动或 QTabBar scroll arrows 常驻；
- 修改触及 tab 色标关闭的 hit-test、armed/re-entry 状态或 manager/host。

## 4. T2 — Footer 数量文案和保持打开

Owner：`mf4_analyzer/ui/widgets/view_overflow_popup.py`

实施步骤：

1. `populate(rows)` 以当前不可变 rows 投影 footer：
   - `len(rows) > 1`：`关闭其他 <N-1> 个…`、`关闭全部 <N> 个…`；
   - `len(rows) == 1`：使用不带 `0 个` 的简洁文案，保持 disabled 和既有 tooltip。
2. 保持 `close_others_requested(str keep_view_id)` 与 `close_all_requested()` 不变；数量只是
   presentation，不作为 identity 或业务参数。
3. 行关闭后的列表、计数、按钮文案和 enabled 状态在同一次重投影中一致；不得调整
   footer 高度、按钮命中区或现有 Cocoa paint/scrollbar 修复。

停线条件：

- 数量需要由 popup 自己缓存或推断 manager；
- 文案增长导致 footer 被裁切、按钮高度变化或 popup 横向滚动；
- 为保持 popup 打开引入新的 timer/native wrapper 生命周期。

## 5. T3 — 发现性文案

Owner：`mf4_analyzer/ui/quickref.py`、`tests/ui/test_quickref.py`

将时域/分析 View 帮助改为：

- `⋯` 始终可管理全部 View；
- 出现 `»N` 时，`N` 表示未显示的 View 数；
- 面板可逐项关闭、关闭其他或关闭全部；
- 至少保留一个 View，关闭全部后留下空白 View。

不增加新的轮播 hint：常驻按钮本身已有 tooltip，quickref 负责完整限制，避免制造长期提示噪声。

## 6. T4 — 验证与验收

### 6.1 聚焦 owner tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar.py tests/ui/test_quickref.py -q
```

必须额外显式复跑误触 lessons gate：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar.py -k "inactive_swatch or switched_swatch" -q
```

### 6.2 相关边界 gates

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_no_lambda_signal_connections.py \
  tests/ui_kit/test_qss_border_shorthand.py -q
```

### 6.3 macOS Cocoa 前台

通过真实入口验证：

1. 1、6、10 个全部可见 View：`⋯` 位置稳定，popup 可打开且列出全部；
2. 缩窄窗口：roomy → compact → overflow，入口同位置切换为 `»H`，H 准确；
3. 在 popup 连续关闭直到 overflow 消失：popup 不闪退，入口回到 `⋯`，footer 数量更新；
4. `关闭其他` / `关闭全部` 的确认范围正确，取消零 mutation；
5. 快速切换 View 和扫过色标不产生新的误删或 hover 残留；
6. UltraView 入口、`+`、section anchor 和 split action 无异常位移。

若无法自动操作当前 Cocoa 前台，只能报告 offscreen 通过；不得把它写成前台验收完成。

### 6.4 交付卫生

```bash
git diff --check
git status --short
git diff --name-only
```

本任务不需要 full suite。若相关源文件在测试期间变化，结果标记 `UNVERIFIED` 并在稳定
snapshot 重跑。任何提交必须只包含本计划列出的文件。

## 7. 完成定义

- [x] `⋯` 在 1 个、多 View roomy、compact 零隐藏状态均常驻且可打开 popup；
- [x] overflow 时同一入口显示精确 `»H`，无新增第二入口；
- [x] 三段 fit 永久测量预留入口，入口与标签不抖动；
- [x] popup 在无 overflow 时可打开，逐项关闭清除 overflow 后仍保持打开；
- [x] footer 数量和 `…` 精确，唯一 View disabled 且不显示 `0 个`；
- [x] typed intents、确认、原子 transaction 和 section cleanup 未修改；
- [x] tab switch/rename/reorder/right-click 与 active re-entry 防误触测试不回归；
- [x] quickref 与新入口一致；
- [x] owner/boundary tests 与 `git diff --check` 完成；
- [ ] macOS Cocoa 前台验收：应用已成功启动，但系统锁屏导致无法读取/操作窗口；待解锁后补测；
- [x] diff 未包含任何预先存在的资产删除或 untracked 文件。

## 8. 2026-09-03 执行记录

- T0 红测：新增合同选择集首次 `7 failed`；既有误触 lesson 基线 `3 passed`。
- 实现后 owner：`tests/ui/test_view_tabbar.py tests/ui/test_quickref.py`，`130 passed`。
- 误触 lesson gate：`3 passed, 93 deselected`。
- boundary：`test_view_tabbar_mount.py`、`test_no_lambda_signal_connections.py`、
  `test_qss_border_shorthand.py`，`35 passed`；仅 56 条既有 pyqtgraph/NumPy deprecation warnings。
- `git diff --check`：通过。
- lessons status：`lesson_required: False`，本次没有产生新的 durable lesson。
- Cocoa：`./.venv/bin/python -m mf4_analyzer.app` 正常启动；Computer Use 报告 Mac locked，
  因此没有形成可见窗口/点击证据。验证进程随后由主代理终止。
