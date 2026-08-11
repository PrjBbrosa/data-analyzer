# Section View 安静锚点实施计划

- 日期：2026-08-11
- 状态：待执行
- 对应 spec：
  [`2026-08-11-section-view-quiet-anchor-spec.md`](../specs/2026-08-11-section-view-quiet-anchor-spec.md)
- 范围：只改共享 `ViewTabBar` 的展示、预算和两个产品挂载点；不改 View 状态模型、
  持久化、收纳算法或探索 HTML

## 成功定义

实施完成必须同时满足：五个产品 section 有正确安静锚点；锚点进入实测预算；当前
`roomy → compact → overflow` 行为逐项不变；用户截图中的「当前 12 留在条上、其余
尾部项进入 `»N`」仍成立；真实 macOS 底栏仍为单行 28px。

## Task 0 — 基线与工作区对账（不改代码）

1. 记录 `git status --short`，保留现有未跟踪 UI prototype，不纳入本任务。
2. 运行锚点前基线：

   ```bash
   TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
     .venv/bin/python -m pytest \
     tests/ui/test_view_tabbar.py \
     tests/ui/test_view_tabbar_mount.py \
     tests/ui/test_analysis_section_page.py -q
   ```

3. 用现有测试 helper 的真实 `sizeHint()` 记录 12 Views 的 roomy、compact、固定控件
   overhead；不保存硬编码像素为产品阈值。
4. 保存一组真实 macOS 前台基线截图：宽状态、compact 状态、当前 View 12 的
   overflow 状态。截图只作视觉对比，不替代测试。

验收：基线结果、已有失败和未跟踪文件归属清楚；不把历史红灯算成新回归。

## Task 1 — 先冻结锚点合同（测试先行）

责任文件：`tests/ui/test_view_tabbar.py`

新增以下聚焦测试，先确认在未实现时失败：

- `test_section_anchor_renders_known_section_identity_without_focus`
  - `section='time'` 显示 `时域`、图标非空、`Qt.NoFocus`、accessible name 正确；
  - 未知非空 section 抛 `ValueError`；`section=None` 保持无锚点兼容行为。
- `test_section_anchor_measured_width_is_reserved_from_tabs_budget`
  - 同尺寸、有/无锚点两条 bar 的 budget 差值等于 anchor 的实时 hint + spacing。
- `test_section_anchor_can_trigger_compact_without_changing_compact_labels`
  - 预算选在两种 bar 的 roomy 分界之间；有锚点者进入 compact；包括当前项在内仍全是
    顺序号，tooltip 仍取 manager 全名。
- `test_section_anchor_overflow_keeps_current_tail_view_and_count_exact`
  - current 放最后；锚点占预算后 current 仍可见，隐藏列表保持尾部规则，`»N` 精确，
    没有 switch intent。
- `test_section_anchor_and_split_actions_are_both_fixed_budget_siblings`
  - split action 出现后，锚点/`+`/`»N`/split 全在 bar 内，只增加隐藏 tab。

测试宽度全部由 `_measure()` / `_tabs_budget()` 的实时结果构造，禁止使用历史机器上的
`58px / 91px / 112px` 作为 degrade 条件。

验收：新增测试只因锚点尚不存在而红；既有测试不修改语义性断言。

## Task 2 — 在共享 ViewTabBar 增加纯展示锚点

责任文件：`mf4_analyzer/ui/view_tabbar.py`

1. 构造函数增加 keyword-only `section=None`，保持现有调用兼容。
2. 在模块内建立五个已知 section 的文案与 `Icons.mode_*()` 图标映射；不从
   `MainWindow` 导入 label helper，不把 Qt 展示对象放进 state。
3. 有合法 section 时，在 `_tabs` 前创建固定 size-policy 的 anchor widget：14px 图标、
   明文 label、NoFocus、非交互 accessible name；`section=None` 时不占 layout。
4. 未知非空 key 立即抛 `ValueError`，让新增 section 的漏接线可见。
5. 保持 `ViewTabBar` 28px、`QTabBar` 26px 和现有 layout margins/spacing；不增加
   第二行、不移动 `»`、`+` 或 split controls。

验收：Task 1 的身份/可访问性测试通过；不触发任何 manager signal 或状态写入。

## Task 3 — 把锚点接入唯一宽度预算

责任文件：`mf4_analyzer/ui/view_tabbar.py`

1. 在 `_tabs_budget()` 的 fixed siblings 计算中加入可见 anchor，复用当前
   `max(sizeHint, minimumSizeHint) + spacing` 计算。
2. 不修改 `_sync_tabbar_width()` 的三次 pass，不新增 threshold，不缓存 anchor 固定宽度。
3. 保持 overflow 最宽标签预留、split action 预留和不可见 widget 不占预算的既有规则。
4. 审计 `showEvent`、`resizeEvent`、`refresh`、active/split 变化后的重测路径；锚点是静态
   section 身份，不新增重测信号或 timer。

验收：Task 1 的 budget、compact、overflow、split 测试通过；现有 current protection、
rename、reorder、menu 测试不改即绿。

## Task 4 — QSS 只增加锚点 chrome

责任文件：`mf4_analyzer/ui_kit/style.qss`

1. selector 必须以共享 `QWidget#viewTabBar` 为根，不能挂在
   `#timeViewBottomDock`，以免分析 section 回退成平台样式。
2. 添加中性图标/文案和浅右分隔线；背景透明；无 hover/pressed/selected 状态。
3. padding 只负责呼吸感，宽度继续由 Qt hint 测量；不写 112px 固定宽。
4. 不修改 `QTabBar#viewTabs::tab`、compact、selected、overflow、plus 现有规则，避免
   把 anchor 变更伪装成 View tab 重设计。

验收：`tests/ui/test_view_tabbar.py::test_shared_tabbar_qss_is_not_scoped_to_time_dock`
继续通过，并新增 anchor selector 的共享作用域断言。

## Task 5 — 接入五个产品 section

责任文件：

- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/analysis_section_page.py`
- `tests/ui/test_view_tabbar_mount.py`
- `tests/ui/test_analysis_section_page.py`

步骤：

1. `ChartStack.attach_view_tabbar()` 构造时传 `section='time'`。
2. `AnalysisSectionPage` 已有 `self.section`，构造共享 bar 时直接传
   `section=self.section`；不在 page 内再建 anchor。
3. mount 测试断言时域 anchor 为「时域」；参数化分析页测试覆盖
   `fft / fft_time / frf / order` 的「频谱 / 时频 / 频响 / 阶次」。
4. 确认五个 bar 仍各自连接原 manager，时域 cap 12、分析 cap 6 不变。

验收：五个真实挂载点不漏项；section 切换只改变可见页面，不修改 manager active。

## Task 6 — 聚焦验证与真实渲染

### 6.1 自动化

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_tabbar_mount.py \
  tests/ui/test_analysis_section_page.py \
  tests/ui/test_view_switch_integration.py -q

TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py -q

git diff --check
```

`ViewTabBar` 是共享 UI，若聚焦测试全绿，再按仓库当前两进程规则跑主 suite 与
`tests/acquisition_ui`；异常退出、超时或未运行均报告 `UNVERIFIED`，不由局部绿灯推断。

### 6.2 macOS 前台验收

在真实 TraceLab 依次检查五个模式，并自动保存/对比以下状态：

1. 时域 12 Views 宽窗口：单行、锚点安静、所有完整名可见或仅因真实预算合理降级。
2. 调窄到 compact：所有 View（含 current）只显示编号，tooltip 是完整名。
3. current 设为 View 12 再调窄到 overflow：12 留在条上，`»N` 精确，无静默切换。
4. 打开合并/分析对比动作：固定动作与锚点不被挤压，tab 进一步收纳。
5. 从 `»N` 选隐藏 View、重命名、拖拽重排、再拉宽：状态可逆且无错位。

截图差异重点检查：bar 高度、锚点与 tab 基线、右分隔线、首个 tab 间距、`»N` / `+`
位置、底栏背景和左右边缘。不要用探索 HTML 作为像素目标。

验收：自动合同与前台视觉同时通过；任一 gate 未执行都在交付中单列。

## Task 7 — 文档与范围收尾

1. 不改项目 schema、帮助 deck、preset、ViewState 或 View 色板。
2. 因锚点不可交互且现有 compact / overflow 文案仍准确，本次不改
   `mf4_analyzer/ui/hints.py` 与 `mf4_analyzer/ui/quickref.py`。
3. 复查 diff，只应包含本计划列出的产品/测试/QSS文件；保留无关未跟踪 prototype。
4. 若实施过程中发现必须改变 compact 或 overflow 语义，立即停止并回到 spec 评审，
   不以“适配锚点”为由顺手重写算法。

## 实施顺序与提交边界

顺序固定为 `Task 0 → 1 → 2/3/4 → 5 → 6 → 7`。建议一个窄提交包含锚点实现、
接线、测试与 QSS；不包含三个探索 HTML。用户未要求 commit/push 时只保留工作区改动。
