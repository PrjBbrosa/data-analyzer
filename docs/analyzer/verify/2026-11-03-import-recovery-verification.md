# 文件导入容错与异常提示：实施与验收记录

日期：2026-11-02–2026-11-03。对应 [执行计划](../plans/2026-11-02-import-recovery-and-diagnostics-plan.md)。

结论：本轮功能实施及定向、真实 Cocoa 验收完成；**整仓回归未通过，不能作为发布绿灯**。本轮未提交、推送、打包或发布，保留了任务开始时的无关工作区修改。

## 已实现的行为

- WWT 完整的零点 Zeit 记录保留物理编号和归属边界，并给出警告；有效数据继续导入。真实截断、非法声明和无法确认的记录边界仍失败。
- CSV/Excel/表格 ASCII 保留信号缺口及原行号，不自动插值、补值或删除测量行；时间轴必须可信，不再隐式生成默认 1 kHz 时基。明确保存的手动采样率可用于项目恢复。
- TDMS 隔离缺少可靠时基等不可用通道，披露对齐处理；ZFD 仅在完整、已知记录结构下跳过不兼容测量通道。无有效来源仍失败。
- 结构化诊断传到文件卡详情、加载摘要、项目重读及 Batch 结果/manifest。项目保存不持久化本次运行诊断；恢复时重新读取源文件。
- GUI/Batch 计算拒绝所选区间内的非有限值；原始时域查看及导出保留缺口。没有修改 FFT/COT/FRF 数学公式。

## 客户文件与真实窗口

`NLTNP_72deg.wwt`：584,595 字节；11 条物理记录。第 6 条 `Time`、偏移 `0x3109d` 为完整的零点时间记录，旧正点数检查误报截断。

真实 Cocoa MainWindow 验证：导入 5 个测量通道，各 24,941 点，0–24.94 s；显示 5 条曲线、一次非阻断提示；详情可定位原记录。真实损坏文件失败后，之前的来源、对象身份和曲线仍保留。

CSV/TDMS/ZFD 合成案例的异常详情、XLSX 缺口断线、项目恢复后重新生成详情、关闭来源时删除详情窗口均通过 Cocoa 验收。项目及 QSettings 使用隔离测试数据。

客户文件在实施前、Cocoa 验收后和最终收尾时的 SHA-256 一致：

```text
fb99e8fd8b23348ca7c3a04327bc569b3045b10f15d2d618a1e91fbcac052a2d
```

证据保存在 `.state/import-recovery/main-window-cocoa/`、`restore-cocoa/`，含验收说明、截图和机器可读事实。Cocoa WWT 使用“仅数据”选择；布局分支有定向测试，但未作本轮真实前台布局导入验收。Windows Full/Lite frozen 程序未验证。

## 测试结果与稳定快照

基线 HEAD：`b1fc5753b3806ca80e23aeca9f2d2ce02d990971`，包含任务开始时已有的未提交修改。主套件和独立采集 UI 门禁期间，HEAD 及所有跟踪/未忽略源文件内容均未变化。指纹分别保存在 `full-before.json`、`full-main-after.json`、`full-acquisition-after.json`。

| 检查 | 实际结果 |
| --- | --- |
| WWT/ZFD/IO notices 定向组 | 132 passed，11 skipped |
| 表格/TDMS/FileData/MF4 定向组 | 117 passed，1 skipped |
| Batch owner 定向组 | 317 passed |
| 导入、恢复、缺口、帮助收尾集成组 | 首次 61 passed、2 failed；修订提示预期与帮助句式后，两项补测 2 passed |
| IO/Signal/UI ownership/连接及包装等相关边界 | 定向分组通过；记录在本任务日志中 |
| 主套件 `--ignore=tests/acquisition_ui -q` | **14,123 passed，69 failed，71 skipped，3 deselected，2 errors**；3,753 warnings；14,318.13 s；退出码 1 |
| 主套件完成后独立 `tests/acquisition_ui -q` | **369 passed，2 skipped**；15.88 s；退出码 0 |

不同定向组有重叠，不将它们相加。完整原始日志为 `.state/import-recovery/full-main.txt`、`full-acquisition.txt`；收尾日志为 `final-focused.txt`、`final-contract-rerun.txt`。

主套件结束后只调整测试合同、当前帮助及本计划/记录，未再修改 Python 产品代码。因此补跑对应失败节点，没有重复四小时主套件；上述全套数字是原始运行结果，不能改写成最终全绿。

## 69 个失败的最终分类

| 类别 | 数量 | 处理与证据 |
| --- | ---: | --- |
| 收尾已调整的测试合同 | 3 | 两个 FRF 恢复测试改为构造真实历史项目，验证明确 manual Fs 保留、未知 generated 时基拒绝且保留可信来源；提示顺序测试加入本轮详情入口及工作区已有的两条提示预期。均已定向通过，未放宽产品时基合同。 |
| 任务前已存在、此轮未修复 | 61 | 用 HEAD 加任务开始时原有补丁重建隔离副本，精确节点复现。涉及旧 View/result binding fixture、回调签名、颜色映射警告、样式 token/颜色数量等，也包含原有产品行为；不能把所有失败都概括为测试过时。两个 teardown error 同样在该副本复现。 |
| 完整会话中出现、原因 UNKNOWN | 5 | 当前与任务前副本的精确节点及整个 owner 文件均通过，但全套失败；没有足够现场状态确定原因，不认定为旧问题，也不认定为本轮回归。 |

最初共有 62 项失败能在任务前复现，其中提示顺序预期已在收尾同步，故上表未修复项为 61。另两个恢复用例原先在创建旧无 Time 项目时依赖现已禁止的默认时基；新测试真实验证历史项目恢复，而非删除保护断言。

5 个待确认节点：

- `tests/ui/test_pill_switch.py::test_pill_switch_hover_and_pressed_change_ink_not_geometry[False]`
- `tests/ui/test_pill_switch.py::test_pill_switch_hover_and_pressed_change_ink_not_geometry[True]`
- `tests/ui/test_pinned_cursor_panels.py::test_live_consumed_after_single_pin_returns_on_next_move`
- `tests/ui/test_pinned_cursor_panels.py::test_dual_pin_hides_live_and_keeps_placement`
- `tests/ui/test_pinned_cursor_panels.py::test_live_p_button_pins_current_readout_not_button_coords`

实际失败分别为 idle/hover 像素相同、后续鼠标移动没有恢复 live 线、hover 集合为空、按钮点击没有新增记录。前置固定操作部分已经成功，不能统一解释为 active-window 或键盘门控失败。缺少当时的窗口、鼠标及 gesture 状态，未制造人工扰动来替代历史归因。

完整名单与双快照证据索引保存在 `.state/import-recovery/final-failing-nodeids.json`、`full-failure-attribution.json`、各 `*-triage.md` 和 `pointer-state-final-attribution.md`。主套件另有 PinnedCursorController 删除回调的 stderr 异常，保留原始日志，未在此轮扩大修复。

## 验收范围

本轮导入行为、原数据保留、结构/时间硬失败、缺口计算保护、诊断传递及 Cocoa 交互已有定向证据；整体应用的全套稳定性仍有上述限制。长会话出现明显清理成本：一次一秒进程采样中，64/79 个主线程样本位于 Python `gc_collect`。这不是已证实泄漏的结论，本轮未改测试框架或垃圾回收策略。

文档检查使用范围/引用/一致性检查与 `git diff --check`，不因本记录新增而再运行 runtime suite。
