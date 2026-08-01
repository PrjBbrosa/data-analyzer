# 批处理时域分组 + canvas 加固 —— 执行结果复核

**复核范围：** `d4a77fd..07c73e5`（24 个 commit，54 文件，+10774/−364），对应计划
`docs/superpowers/plans/2026-07-31-batch-time-domain-layout-and-xaxis.md`。
**产品基线：** `6cf1360`（计划自己声明的基线）。
**复核日期：** 2026-08-01 · macOS / Python 3.12 / `.venv`

---

## 0. 结论速览

功能主干是**可用的**：`render_group_by=channel` + `x_source=channel` 的真机导出正确；
recipe 规范化、manifest render_groups 日志、resume/retry 矩阵、spool 上限护栏的
单元覆盖都很扎实（`pytest tests/test_batch_*.py` 468 passed）。

但有 **1 个已上线的功能回归** 和 **4 个真机渲染缺陷**，后者全部被"属性设上了 +
单测过"掩盖了——正是 `CLAUDE.md` 里那条"验真机渲染"gotcha 描述的失败模式。

| 级别 | 编号 | 问题 | 证据 |
|---|---|---|---|
| 高 | A1 | `source_paths`/`file_paths` 驱动的批处理运行整体 blocked | 4 个红测 + git 二分 |
| 高 | B1 | 双 Y 单位叠加时两条曲线**同色同线型** | 真机渲染 + 颜色断言 |
| 高 | B2 | subplot 布局 >3 面板即不可读（Y 标签糊成一团、面板标题压刻度） | 真机渲染 6/8 面板 |
| 中 | B3 | source 分组的 subplot 面板标题全是同一个文件名 | 端到端导出图 |
| 中 | B4 | 图头泄露原始 JSON group_key（含绝对路径）且重复两遍 | 端到端导出图 |
| 低 | D1–D6 | manifest 单位丢失、spool `id()` 生命周期、`run()` 体量等 | 代码走查 |

---

## 1. A1（高）—— 懒加载路径驱动的批处理被整体 blocked

### 现象

```
status=blocked
blocked=["…/steering_1.mf4:EpsDrvrSteerTq: source_id '…/steering_1.mf4'
          not returned by physical source; available: mdf:8eaab37cb8d75063…"]
```

红测（在基线 `6cf1360` 全绿）：

- `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_uses_batch_runner_for_three_mf4_csv_pdf_sets`
- `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_rejects_manifest_source_not_in_requested_set`
- `tests/test_frozen_batch_acceptance.py::test_frozen_batch_acceptance_binds_executable_sha_to_frozen_smoke`
- `tests/test_batch_source_integration.py::test_legacy_file_paths_migrate_to_all_registry_logical_sources`

### 二分结果

在 worktree 上逐 commit 跑 `tests/test_frozen_batch_acceptance.py`：

```
6cf1360 :: 34 passed      ← 基线
3d854a6 :: 34 passed
03bb10d :: 3 failed       ← 引入点：Fix grouped execution boundary contracts
14d9381 … 07c73e5 :: 3 failed（此后 9 个 commit 一直红）
```

### 根因

`03bb10d` 把第一次任务展开改成无条件 `allow_source_load=False`，并把
"任务为空则带加载重新展开"的兜底挪到了 renderer probe 之后：

```python
# 之前
tasks = list(self._expand_tasks(preset, allow_source_load=(
    not explicit_grouping and resume_data is None and retry_scope is None)))
# 之后
tasks = list(self._expand_tasks(preset, allow_source_load=False))
...
if not tasks:                      # 只有"空"才会迁移
    tasks = list(self._expand_tasks(preset, allow_source_load=True))
```

`_scope_source_keys(allow_source_load=False)` 对 `source_paths` 分支直接
`return list(dict.fromkeys(source_paths))`——**返回原始路径当 source key**。
配合显式 `target_signals` + `target_policy=common`：`channels_by_source[path] = None`
→ `known_sets = []` → `common = selected` → 任务列表**非空**（键是路径）。
于是 `if not tasks:` 兜底永不触发，路径→逻辑 source_id 的迁移被跳过，
`_resolve_task_file` 拿路径去比对物理源返回的 `mdf:<hash>` / `hdf:<group>`，全部失败。

### 影响面

- **GUI 不受影响**：`sheet.get_preset()` 始终同时写 `source_ids` 和 `source_paths`，
  `_scope_source_keys` 走 `source_ids` 分支。
- **受影响**：`mf4_analyzer/frozen_batch_acceptance.py`（项目自己的冻结验收 CLI，
  只传 `source_paths`）、任何只带 `file_paths`/`source_paths` 的脚本或旧 preset。
- 也就是说：**发版验收通道当前是坏的，而且已经坏了 9 个 commit 没人发现**。

### 修复方向

不要靠"tasks 是否为空"来判断是否需要迁移。让 `_scope_source_keys` 在
`allow_source_load=False` 且只有 `source_paths`/`file_paths`（无 `source_ids`）时
返回空——把"路径还没解析成逻辑源"这一事实显式表达出来，而不是伪装成合法 source key；
或者在 `_build_run_plan` 之前显式判断"当前 key 是否是未迁移路径"并强制走带加载展开。
必须补一条测试：**显式 `target_signals` + 纯 `source_paths` + 多逻辑源容器**。

---

## 2. B —— 真机渲染缺陷（全部经实际出图验证）

### B1（高）双 Y 单位叠加：两条曲线同色同线型

`_render_time_spec_panel` 用 `axis.twinx()` 建右轴，两个 Axes **各自持有独立的
property cycler**，都从 `C0` 开始：

```
voltage (0.1215, 0.4666, 0.7058) -
speed   (0.1215, 0.4666, 0.7058) -
```

合并图例里两个色块完全一样。"两种 Y 单位走左右轴"是本次的招牌能力，
而在最常见的"每种单位各一条曲线"场景下**用户无法区分哪条是哪条**。
现有测试 `test_time_spec_two_y_units_use_one_combined_legend` 只断言 ylabel 和
legend 文本，对颜色零断言，所以全绿。

**修法：** 在 spec 渲染路径里显式分配颜色（跨左右轴统一取一个色轮），
并加一条"所有 series 的 (color, linestyle) 组合互不相同"的断言。

### B2（高）subplot 布局在文档上限处不可读

`_build_batch_figure_in_context` 对所有布局统一执行
`figure.subplots_adjust(left=0.10, right=0.91, bottom=0.13, top=0.84)`，
N 面板情况下既没有 `hspace` 也没有 `constrained_layout`：

- 每个面板都 `set_ylabel("Amplitude (…)")`，8 面板时纵向标签**互相重叠糊成一条**；
- 每个面板的 `set_title(...)` 落在上一面板的底部刻度上，`run_1.mf4` 直接压住上面的 `-1`。

8 面板正是计划写死的 `_MAX_SUBPLOT_PANELS`，也就是说**上限工况本身就是坏的**。
渲染件见 `scratchpad/probe_subplot6.png` / `probe_subplot8.png`。

**修法：** 分支处理 subplot——只在最底部面板放 xlabel（已有）、只在整图左侧放一个
共享 ylabel（或按单位放一个），面板标题改用 `axis.text` 内嵌左上角或减小字号 +
显式 `hspace`，并用 `constrained_layout` / `tight_layout` 兜底。

### B3（中）source 分组的 subplot 面板标题全一样

`_render_group` 里：

```python
panel_titles = tuple(
    result_by_task[member.identity.task_id].item.file_name
    if member.identity.task_id in result_by_task else member.channel
    for member in group.members
)
```

source 分组的成员是**同一个文件的不同通道**，于是每个面板标题都是同一个文件名。
端到端导出图 `e2e/out/src-1__default__time__source__*.png` 两个面板都写着 `src-1.csv`。
（顺带：同一个表达式在"任务没算过"时又回退成 `member.channel`，同一张图里标题语义不一致。）

**修法：** 标题按 `group.group_by` 决定——`source` 分组用 channel，`channel` 分组用文件名。

### B4（中）图头泄露 JSON group_key + 绝对路径 + 重复

`_render_group` 构造：

```python
context = BatchRenderContext(
    source_display_name=str(group.group_key),
    group=group.group_key,
    channel=(group.group_key if group.group_by == 'channel' else ''),
    ...)
```

而 `_apply_figure_context` 的两行标题是 `source_display_name · group` /
`channel · method`。结果：

- `channel` 分组 → `加速度_X · 加速度_X` / `加速度_X · time`，同一个词出现三次；
- `source` 分组 → `group_key` 是 `json.dumps([source_identity, group_identity])`，
  图头直接印出 `["/Users/donghang/Downloads/measurements/run_2026_0…` ——
  **每一张 source 分组导出图都带上用户的绝对路径**，还重复两遍。

**修法：** 给 `RenderGroup` 增加一个人类可读的 display 字段（source 分组用
`Path(source_identity).name` + group_identity，channel 分组用通道名），
`group_key` 保持机器身份用途，不要塞进图头。

---

## 3. C —— 为什么这些缺陷能通过验收

1. **单测只断言结构量。** 11 个 `test_time_spec_*` 断言的是 axes 数量、xlabel、
   xlim、legend 文本、linestyle 字符串，没有一条断言颜色可区分或文字不重叠。
2. **验收脚本没覆盖出事的两个模式。** `mf4_analyzer/batch_time_group_acceptance.py`
   只用 `params = {"render_group_by": group_by}`，**从不设置 `render_layout=subplot`，
   也从不设置 `x_source=channel`**。缺陷最集中的两个组合端到端零覆盖。
3. **没跑全量 `pytest`。** A1 从 `03bb10d` 起就红，后续 9 个 commit（含 3 个自称
   "acceptance evidence" 的 commit）都没触发。

---

## 4. D —— 低优先级代码问题

| 编号 | 位置 | 问题 |
|---|---|---|
| D1 | `batch.py:1656,1669` | `record_item(item, item.file_id)` 不传 `fd`，`record = upsert_task` 是整条替换 → manifest 的 `channel_unit` 被写回 `''`（组警告 / 组取消路径） |
| D2 | `batch_series_spool.py:167,178` | mmap 以 `id(BatchSeries)` 为键；`id()` 会复用，`release_loaded` 又显式 `mmap.close()` 而 `BatchSeries.x` 是该 mmap 的 base-ndarray 视图 → 一旦有路径漏调 `release_loaded` 或 id 撞车就是 use-after-free |
| D3 | `batch.py:2067-2145` | `_recover_lazy_manifest_tasks` 边扫边写 `_source_locators` / `_source_group_identity_hints`，却可能在后面的 entry 上 `return []`；被拒绝的恢复仍留下 runner 的副作用 |
| D4 | `batch.py:556-2012` | `run()` 单方法约 1450 行，分组分支是 670 行内联块；且 `1240` 行无条件 `group.members`，而 `1409/1537` 行写 `if group is not None`，护栏语义自相矛盾 |
| D5 | `batch.py:3076` | 组图 `effective_facts = dict(params)` 用的是 requested 参数，不是 preprocess 后的 effective（如降采样后的 fs），组图事实条与单任务图不同源 |
| D6 | `batch_render.py:365-372` | 三种 Y 单位全局 fail closed，但 subplot 下每个面板本可以各自持有单位，限制偏严 |
| D7 | `tests/test_windows_build_script.py` | 无条件调用 `powershell.exe`，非 Windows 上恒失败，应加平台 skip |

---

## 5. E —— 测试套件健康度（非本次 wave 造成，但影响判断）

- **`pytest`（README/CLAUDE.md 的默认开发命令）在 macOS 上跑不完**：
  `tests/acquisition_ui/test_review_handoff.py::test_analyzer_main_window_has_public_load_file`
  段错误退出（pyqtgraph `LabelItem.resizeEvent` → `wrapped C/C++ object has been deleted`
  → `Fatal Python error: Segmentation fault`）。单独跑该文件不复现，是套件内交互污染。
- 用 `--ignore=tests/acquisition_ui` 跑完整套件：**68 failed / 4056 passed / 8 skipped**。
- 把这 14 个失败文件在基线 `6cf1360` 上重跑：**61 failed**，主干上 **65 failed**。
  **差值恰好 = 4 = A1 的四个红测**。其余 61 个（`test_split_*`、`test_main_window_smoke`、
  `test_head_hdf_rail`、`test_channel_widget_setters` 等）是既有欠债，与本次无关。

---

## 6. 后续 Plan

### P0 —— 恢复发版通道（本周内）

1. **修 A1**：`_scope_source_keys` 在 `allow_source_load=False` 且只有路径没有
   `source_ids` 时返回空（或等价地在 `_build_run_plan` 前显式检测未迁移路径），
   让 `if not tasks:` 兜底重新生效。
   - 先写红测：显式 `target_signals` + 纯 `source_paths` + 一个物理文件出多个逻辑源。
   - 验收：`pytest tests/test_frozen_batch_acceptance.py tests/test_batch_source_integration.py`
     全绿，并实跑一次 `frozen_batch_acceptance` CLI。
2. **加一条 CI/pre-commit 级别的全量门禁**：至少
   `pytest --ignore=tests/acquisition_ui -q` 的失败数不得超过基线数（当前 61），
   否则拒绝合并。没有这条，A1 这类回归还会再发生。

### P1 —— 修渲染缺陷（下一轮）

3. **B1 双 Y 配色**：spec 路径统一分配颜色，跨左右轴不复用。
   红测：`test_time_spec_dual_y_units_use_distinct_colors`——断言所有 series 的
   `(color, linestyle)` 两两不同。
4. **B2 subplot 排版**：subplot 分支单独做 margin/hspace，共享 ylabel，
   面板标题改内嵌或缩字号。
   红测：渲染 8 面板后用 `Text.get_window_extent()` 断言相邻面板标题与上方刻度
   bbox **不相交**、相邻 ylabel bbox 不相交（这是能自动化的"真机"断言）。
5. **B3 面板标题**：按 `group_by` 分派标题来源，去掉 fallback 的语义不一致。
6. **B4 图头身份**：给 `RenderGroup` 加 `display_name`，`group_key` 不入图头；
   断言导出图头不含 `[` / `"` / 绝对路径分隔符。

### P2 —— 补验收与清理

7. **扩验收矩阵**：`batch_time_group_acceptance.py` 增加
   `render_layout=subplot` 与 `x_source=channel` 两个组合，并把产出的 PNG
   走一遍上面的 bbox 断言。
8. **D1/D2/D3** 逐条修：`record_item` 补传 `fd`（或改成部分更新）、
   spool 改用显式 handle 而不是 `id()`、`_recover_lazy_manifest_tasks` 改成
   先算完整结果再统一提交副作用。
9. **D4 拆 `run()`**：把分组执行分支提成独立方法/类，统一 `group` 的 None 契约。
   （这条属于重构，按仓库规则要走 agent squad 流程。）
10. **D7** 给 `test_windows_build_script.py` 加 `@pytest.mark.skipif(sys.platform != "win32")`。

### P3 —— 套件健康度（独立于本 wave）

11. 定位 `tests/acquisition_ui` 段错误的污染源（pyqtgraph LabelItem 在跨测试
    生命周期里被提前析构），让 `pytest` 裸命令能跑完。
12. 把 61 个既有失败分类归档，逐批消化或显式标记 xfail，否则"跑一次全量"
    永远得不到可用信号。

---

## 附：本次复核的可复现命令

```bash
.venv/bin/python -m pytest -q -p no:randomly tests/test_batch_runner.py tests/test_batch_manifest.py tests/test_batch_renderer.py tests/test_batch_series_spool.py tests/test_batch_output.py tests/test_batch_recipe.py tests/test_batch_validation.py tests/test_batch_preprocess.py tests/test_batch_time_group_acceptance.py   # 468 passed
.venv/bin/python -m pytest -q -p no:randomly --ignore=tests/acquisition_ui                                                       # 68 failed / 4056 passed
git worktree add <tmp> 6cf1360 && (cd <tmp> && pytest -q tests/test_frozen_batch_acceptance.py)                                  # 34 passed（基线全绿）
```
