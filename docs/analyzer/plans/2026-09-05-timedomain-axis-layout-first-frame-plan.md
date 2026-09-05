# TimeDomain 轴空间恢复与首帧稳定性执行 Plan

日期：2026-09-05

状态：**待审阅；本轮文档任务不实施产品变更**

合同：[配套 Spec](../specs/2026-09-05-timedomain-axis-layout-first-frame-spec.md)

## 1. 执行原则

按 T0→T1→T2→T3→T4 顺序由同一实施者推进；不安排并行代理，不假定本文件已获实施授权。
A 是确定缺陷，B 是用户报告且完整应用根因待证实，两条验收记录独立。
T0 对 B 的调查不能阻止已确认 A 的定向修复；B 无证据时保留 UNKNOWN，不盲目加缓存或延时。
本计划不会触碰无关 dirty 文件或提交／推送。后续执行另有授权时按授权范围处理 Git。

## 2. T0：刷新证据与捕获完整切换链

**归属**：只读生产代码；可写 `.state/timedomain-axis-layout/` 探针与记录。

1. 记录 HEAD、dirty scope、相关源文件 hash、Qt/pyqtgraph 版本、平台、窗口尺寸和 DPR。
   不复用不匹配工作树的历史绿色结果，不运行通用全套 baseline。
2. 阅读相关 lessons：`codex-pg-subplot-reuse-needs-realized-geometry`、
   `codex-pg-subplot-layout-settle`、`timedomain-xaxis-interaction-keeps-layout-stable`、
   `overlay-right-axis-columns-need-post-tick-realize`。只载入这些相关条目。
3. 在当前源码重跑 A：三行→第一行／中间行／末行，直接单图作对照；记录 axis.height、
   fixedHeight、真实文字框和绘图区边界。确认不是仅 `showValues=True` 的结构断言。
4. 用确定性数据经 MainWindow 的真实模式控件／信号入口触发 B；保留用户截图场景为前台目标。
   对照独立 canvas 路径，标记 build、范围恢复、轴 finalization、内部布局、paint 的时间戳。
5. 观测实际 viewport paint，不在观测前调用额外 flush/grab/repaint 消除中间帧。
   测量 hook 不得触发新布局或事件循环；可配前台录屏，截图只作静态证据。
6. 明确 B 属于几何二次收缩、半成品绘制、清空背景还是 AA/光栅转换。
   若只是 AA 差异，记录与本 spec 几何问题的差别，不擅改质量阈值。

**定向 baseline**：现有 `TestTimeDomainCanvasPGSelectionDelta`、
`TestViewRestoreSettlement`、`TestDiscreteSettle`，加实际模式入口相关既有测试。
**产出**：原因表、调用序列、A 红探针、B 已复现／UNKNOWN，以及 C3 选型依据。
**通过门槛**：A 可重现；B 信息不足时写明缺失的具体数据／操作，继续 T1，不伪造结论。

## 3. T1：轴角色完整恢复（修复 A）

**文件归属**：`ui/pg_canvas/canvas.py`、确有必要时 `overlay_axes.py`；
测试在现有 `tests/ui/test_pg_timedomain_canvas.py` 和 `test_subplot_shared_axis.py`。

- 先补实际显示 canvas 的失败回归：3→2→1、3→1、1→3，分别保留首／中／末行。
- 修复高度同步的单行边界，使最底轴包括唯一轴都能恢复；复用现有收尾入口。
  优先最小 owner 修复，不另建通用布局框架或全局常量。
- 同一 helper 重复调用应幂等；上层仍收起，最底轴按字体／内容自动预留。
- 覆盖零选择→恢复、隐藏→显示，以及两曲线共轴唯一槽，避免混淆轴数与曲线数。
- 断言实际 X 数字／标题框不侵入 ViewBox；另断言对象复用、范围、曲线身份。

**Gate**：Spec G1/G2；定向 selection-delta 类、subplot-shared-axis、
`tests/ui/test_subplot_left_axis_metrics.py`，并核对单图／分屏底轴已有几何测试。
A 完成后可单独记录通过，不将 B 自动勾选。

## 4. T2：首帧测量与统一收尾（依据 B 证据）

**文件归属**：canvas owner；仅 T0 定位需要时进入 `overlay_axes.py`、
`tick_density.py`、`axis_metrics.py`；测试扩展实际命中的 owner。

1. 先把 T0 异常顺序固定为失败 probe／回归，明确目标首帧与稳定帧边界。
2. 将目标轴角色、刻度和标题的空间确定放到用户可见新帧之前。
   复用已有字体度量与轴 helper；需要新测量时先证明既有 helper 无法覆盖。
3. 先内层 PlotItem，再外层布局，再同步 overlay aux 几何；收尾使用最终 X/Y。
4. 验证几何收尾没有造成第二遍 envelope/ink/质量结算，不改 150 ms timer。
5. 比较目标首帧与稳定帧的 physical-pixel 边界；记录字体／DPR 变化后的重新度量。

**Gate**：Spec G3/G5；`TestViewRestoreSettlement`、`TestDiscreteSettle`、
`tests/ui/test_subplot_left_axis_metrics.py`、`tests/ui/test_overlay_grid_ticks.py`、
`tests/ui/test_view_switch_integration.py` 中相关路径以及新首帧测试。
若 B 无法复现，不凭推测修改跨层调用链；保留 T2 未完成和准确的下一条采证动作。

## 5. T3：仅在需要时保护展示事务

**进入条件**：T0/T2 证据显示正确布局过程中仍有可见半成品帧。
若现有同步收尾已经满足 G3/G4，记录“无需额外展示机制”并跳过实现。

**归属**：canvas 内短生命周期状态；MainWindow / `_view_mixin.py` 仅编排。
不得扩大 `window.py` 状态面或重建 `TimeRenderGate`。

- 同步路径优先最小作用域抑制新帧展示；恢复原 updatesEnabled 状态、嵌套作用域与异常路径。
- 仅确认跨事件循环不可避免后才实现保留旧画面；先记录 C3 的所有者、边界和内存约束。
- 保留画面不能作为“ready”证据；检查新图真正完成、旧图撤去及输入身份一致。
- 覆盖快速切换、窗口关闭、失败重建、隐藏画布、DPR 改变；错误可观察，不吞编程异常。

**Gate**：Spec G4/G6；`tests/ui/test_view_switch_reentrancy.py`、相关 MainWindow 模式切换测试、
新事务异常恢复测试。若未实现展示事务，不为不存在的机制编写测试。

## 6. T4：集成验证与交付

实施者先跑改变 owner 的定向测试，再跑实际适用边界。不得仅因改 UI 就跑整个 tests/ui。
使用项目运行时，例如：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_pg_timedomain_canvas.py::TestTimeDomainCanvasPGSelectionDelta \
  tests/ui/test_pg_timedomain_canvas.py::TestViewRestoreSettlement \
  tests/ui/test_pg_timedomain_canvas.py::TestDiscreteSettle \
  tests/ui/test_subplot_shared_axis.py
```

按实际变更追加：

| 涉及边界 | Gate |
|---|---|
| canvas/collaborator | `tests/ui/test_pg_canvas_backref_invariants.py`、`tests/ui/test_no_lambda_signal_connections.py` |
| 导入或新增 helper | `tests/ui/test_import_boundaries.py`；若触及中立层再加对应无 GUI/import gate |
| MainWindow 编排 | `tests/ui/test_main_window_state_ownership.py`、view-switch-reentrancy 与命中路径测试 |
| 角色／布局热路径 | `tests/ui/test_timedomain_hotpath_perf.py`；真实机器同机 A/B，不拿 offscreen 耗时作性能结论 |
| quality／raster 调度实际受影响 | 对应 `test_pg_dense_raster.py` 定向用例、ViewRestoreSettlement、DiscreteSettle、既有 paint backstop 定向测试 |
| QSS 若确实改变 | `tests/ui_kit/test_qss_border_shorthand.py`；本计划默认不改 QSS |

运行测试前确认相关 fixture 作用域和 Qt ownership；绘图 widget 显式持有并正确关闭、清理 deferred delete。
不新增排序依赖，不修改 root conftest 来绕过 fixture 问题。
本任务默认无需 full suite；只有实际变更扩大到跨边界集成才说明理由，由一个实施者独占执行，
先检查同 checkout 的 pytest 进程；主套与 acquisition_ui 两个新进程顺序执行。

前台验收：

- 原生 Cocoa 绘制 G1–G4，使用当前实际 widget 路径；完整 TraceLab 模式切换单独记录。
- 客户文件可用时复核用户操作；不可用则说明合成 fixture 和真实文件的证据边界。
- G4 每方向至少 10 次；G6 至少 20 次暖切同机 A/B，记录首个正确画面等待时长。
- Windows 真机字体／缩放验证单列；不能用源码打包检查或 macOS 代替。
- 对帧序列的边界和轴文本做自动比较；无需让用户逐张判断图片。

交付记录表逐项列 G1–G6、证据路径和 passed / failed / UNKNOWN / UNVERIFIED。
若需要可提交的报告，放 `docs/analyzer/verify/`；原始临时图片和运行日志默认留 `.state/`。
最后检查 named-path diff、`git diff --check`、相关 lessons 状态；不清除其他会话的 lesson requirement。
只有新增／改名用户交互时才同步 `ui/hints.py` 和 `ui/quickref.py`；纯几何修复不制造新入口。

## 7. 回退与停止扩大范围的条件

- A 最小高度恢复与 B 时序修复保持可独立审阅；B 未通过不撤销已验证的 A。
- 暂时关闭有问题的展示抑制时必须恢复原更新状态；旧画面机制不得残留在生产画布。
- 不通过“永久固定底轴高度”、强制整图重建、睡眠、关闭 AA 或放宽几何容差来凑通过。
- 若问题来自其他分析画布或新性能瓶颈，记录单独问题；不扩展本批 DSP／缓存架构。

## 8. 本轮文档交付检查

本轮只新增配套 spec 与本 plan。检查两者范围、交叉引用、源符号、Gate 编号和证据状态一致，
以及 named-path `git diff --check`。文档没有改变运行行为或现有可执行文档合同，因此无需运行 runtime suite。
