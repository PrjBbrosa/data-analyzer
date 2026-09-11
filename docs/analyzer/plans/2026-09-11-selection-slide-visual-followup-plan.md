# 选中背景滑动：视觉修复 Follow-up Plan

> 执行方式：获得实施授权后，使用 `superpowers:executing-plans` 按 T1–T3 顺序推进；单执行者，不派生 agent。当前仅分析与计划，未实施。

**Goal:** 保留滑动反馈，恢复原有按钮质感，消除圆角白底，并使静止端点与关闭动画时的样式一致。

**Architecture:** 在 `ui_kit/widgets/selection_indicator.py` 统一修复底板绘制；各控件 owner 提供自己的外观参数。业务状态、信号、动画驱动继续由现有 owner 管理。

**Tech Stack:** 项目 PyQt5 / Qt 5、生产 QSS、pytest-qt、原生 Windows 控件探针。

**依据：** 当前代码及提交 `f036d2f2`；[原 Spec](../specs/2026-09-10-selection-slide-rollout-spec.md) 的 P1 范围和交互合同。历史验收报告不代表本轮通过。本计划补充视觉验收，不重做原推广计划。

## 全局调查结论

“全局”限定为本次滑动效果的所有生产接入点，不扩展成整个软件重设计。源码中共享滑块有四类调用方：

| 区域 / owner（路径相对 `mf4_analyzer/`） | 已发现问题与本轮处理 |
| --- | --- |
| `ui/toolbar.py:Toolbar` 顶部五模式 | 原白→`CONTROL_ACCENT_WASH` 渐变被纯白替代；恢复渐变。原 QSS 有水平 margin，底板却取完整 widget rect，须实测并对齐可见边框。 |
| `ui/drawers/batch/method_buttons.py:MethodButtonGroup` 五方法 | 同样丢失选中渐变；checked:hover 原有更深渐变也被局部透明规则覆盖。恢复普通/悬停层次，检查 pressed/focus 的实际级联结果。 |
| `ui_kit/widgets/segmented_choice.py:SegmentedChoice` | 原选中面就是纯白，保留它；修圆角白底与边框几何。覆盖下方所有 Inspector/Batch 实例。 |
| `ui/chart_stack/cards.py:_ChartChoiceMotionMixin` | 时域分屏/叠加、时域及频率/FRF 游标组原本是纯白选中面；修底板透明性和几何，检查双组层叠及焦点目标切换。 |

SegmentedChoice 覆盖清单：Inspector 的 FRF 五组、FFT 幅值/计权、时频计权、阶次转速来源/计权、共用幅值单位、时域横轴；Batch 的 `_BINARY_CHOICE_FIELDS` 动态参数，以及 input_panel 的来源策略、slice_panel 的切片轴、chart_statistics_panel 的统计区间模式。共享修复为主，不逐处复制补丁。

**已证实：** `_SelectionPlate` 开启 `WA_StyledBackground`，命中全局 QWidget 白底，圆角外暴露矩形白色底。生产 QSS 离屏探针中，同一 SegmentedChoice 角外像素：Off=`#EEF1F6`，Light=`#FFFFFF`，仅把底板背景设透明后恢复 `#EEF1F6`。临时证据在 `.state/selection-review/`，不提交。

**待验证：** 所有 owner 的 margin/半像素边框差异，以及 hover/pressed/focus 组合态。当前 painter 用整数矩形、1px pen，存在边缘覆盖不对称风险；不能仅凭源码认定每处都已出现可见缺陷。上一轮探针不是 Windows 前台验收。

## 保持的合同

- 导航 400 ms、参数/图卡 300 ms 和现有 easing 不变；本轮不调速度。
- 业务立即生效；只有直接操作的组动画，程序恢复/联动直接定位；Off/Reduced 恢复静态样式。
- 不改按钮尺寸、点击区域、标签、图标、快捷键、数据计算、项目 schema 或 MainWindow 状态。
- 不修改全局 QWidget 白底来绕过局部问题，不引入全局动画开关、额外 timer 或每个 owner 一套 painter。
- 不推广到热图切片、View/Board、UltraView、采集等原 P2 区域。
- 本轮没有交互入口增删/改名，因此无需改 `ui/hints.py` / `ui/quickref.py`；若实施扩大到此类变化，必须同时更新。

## T1 — 统一修复透明底与边框几何

**文件：** `mf4_analyzer/ui_kit/widgets/selection_indicator.py`；`tests/ui_kit/test_selection_indicator.py`。

- [ ] 先在生产 QSS 下加入失败像素用例：灰色轨道上的圆角外像素必须保持轨道色；白色和带色父背景均不得出现额外矩形。抓取 host 的合成结果，不能只抓孤立 plate。
- [ ] 为底板设置精确限定的透明背景；保留输入穿透、生命周期和现有堆叠合同。修复后验证中间帧也不留下白块。
- [ ] 对照 QSS 静态端点测量可见边框；使绘制矩形包含真实 margin/inset 和浮点描边边界。只在证实差异时调整，不能移动或缩小按钮点击区域，也不能把 Toolbar 的 margin 全局硬编码给其他 owner。
- [ ] 运行该 owner 测试，覆盖 DPR 1/可用高 DPI 下的四角、四边、非等宽按钮、禁用和快速反向；确认旧信号/生命周期测试继续通过。

**交付：** 单一底板 owner 不再露白，外观几何有像素证据；保持现有 `follow` / `snap_to_selection` 接口。

## T2 — 恢复各组原有质感和状态反馈

**文件：** `selection_indicator.py`、`ui_kit/control_style.py`、`ui_kit/style.qss`（均位于 `mf4_analyzer/`，前者完整路径见 T1）；四类 owner 见调查表。

- [ ] 先对 Toolbar/MethodButtonGroup 增加 Off 与 Light 静止端点的填充区域对照，要求顶部/底部采样呈现原渐变；Batch 增加 checked:hover 对照。现有纯白实现应失败。
- [ ] 以兼容方式扩展 `SelectionIndicatorStyle` 的可选渐变/状态参数，旧构造仍可用；QSS 与 painter 共用 `control_style.py` 的色值，避免复制第二套 palette。Toolbar/Batch 恢复原渐变，二选一与图卡保留纯白。
- [ ] 核对 normal/hover/pressed/focus/disabled 组合态，由 owner 提供外观、helper 观察呈现状态；透明 checked 规则只抑制重复底板，不吞掉原本有效的反馈。单按钮或祖先禁用仍使用禁用色，不能复活亮色渐变。
- [ ] 运行 `tests/ui_kit/test_segmented_choice.py`、`tests/ui/test_toolbar.py`、`tests/ui/test_batch_method_buttons.py`、`tests/ui/test_chart_selection_slide.py`；验证 Off/Reduced、程序 setter、恢复、重复点击与连点终态，信号次数不变。

**交付：** 四类控件静止时恢复各自原貌，移动中保持相同材质；不把所有选中面统一改成渐变。

## T3 — 生产覆盖与原生视觉收口

**文件：** `scripts/probe_selection_slide.py`、`tests/ui/test_selection_slide_probe.py`；必要的接入断言进入 `tests/ui/test_inspector.py`、`tests/ui/test_batch_input_panel.py`、`tests/ui/test_batch_slice_panel.py`、`tests/ui/test_batch_chart_statistics.py`。

- [ ] 扩展现有探针，覆盖调查表全部生产实例；输出 Off/Light 端点、25%/50% 中间帧、hover/focus/disabled 局部截图及自动差分。抗锯齿边缘允许明确的窄容差，圆角外背景必须匹配父表面；同时以原 QSS 渐变色验证绝对正确性，不仅比较两条路径。
- [ ] 在 Windows 前台运行真实 widget 路径和生产 QSS，记录实际缩放/DPR；验证当前缩放及一个可用的不同缩放，覆盖正常/紧凑 Toolbar、Batch 方法与动态参数、Inspector 转速来源、两类图卡。检查文字图标、边框、焦点和滑动中间帧，不依赖截图文件的样式 token。
- [ ] 先运行新增/修改的探针及接入测试，再跑边界：`tests/ui_kit/test_qss_border_shorthand.py`、`tests/ui/test_no_lambda_signal_connections.py`、`tests/ui/test_import_boundaries.py`、`tests/ui/test_main_window_state_ownership.py`。仅在修改相应 owner 时补充其 focused tests，不跑全套或整个 `tests/ui`。
- [ ] 保存 HEAD/相关文件指纹及图像到 `.state/selection-slide-visual-followup/`；结束时执行 `git diff --check`。报告 Windows 前台、离屏和未运行的 Cocoa 为独立证据，未跑的平台不得标通过。

**完成标准：** 四类 owner 与全部接入点有覆盖；无矩形白底；导航渐变和 Batch 悬停反馈恢复；静止外观、点击几何及业务信号保持合同。测试通过但缺前台证据时，视觉验收仍为 UNVERIFIED。

## 本次文档验证

本次只新增计划，检查引用、范围和 `git diff --check`，不运行 runtime suite；未改变可执行行为。以上 checkbox 均为未来实施任务，不代表已通过。
