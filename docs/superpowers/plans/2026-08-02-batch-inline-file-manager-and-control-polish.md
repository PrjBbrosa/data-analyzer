# 批处理第一层文件管理与控件细节修正 —— 实施计划

**日期：** 2026-08-02

**状态：** 已实施；Qt 离屏矩阵 PASS，macOS 前台验收待执行

**Supersedes：**
`docs/superpowers/plans/2026-08-02-batch-compact-ui-visual-parity-remediation.md`
中 Phase 2 的 modal 文件管理策略，以及 Phase 3 的方法按钮/预设文字对齐合同；原计划其余
行为接线、Output、footer、离屏矩阵与回归合同继续有效。

**Governing design：**
`docs/superpowers/specs/2026-08-02-batch-inline-file-manager-and-control-polish-design.md`

**HTML target：**
`docs/analyzer/ui-prototypes/2026-08-02-batch-inline-file-manager.html`

## 1. 目标与当前证据

本轮实施范围固定为四项：

1. 四个分析方法按钮等宽；
2. 四张分析预设卡内文字居中；
3. 文件管理从二级 modal 展开到 Input 第一层，现有能力不减少；
4. 修复 `刻度与字体` X/Y/字号 slider 无法拖动。

当前源码证据：

- `MethodButtonGroup` 给 `fft_time` stretch=2、其余=1；500 px 探针实测宽度为
  `92 / 91 / 183 / 92`；
- `_PresetCard.paintEvent()` 使用 `Qt.AlignLeft` 绘制名称和摘要；
- `InputPanel` 创建持久 `BatchFileManagerDialog`，主栏只保留 54 px 摘要；
- `RenderStylePopover` 的 slider/spin 共用 `_on_editor_changed()`；当前离屏探针将 X slider
  从 14 设为 20 后立即回到 14，recipe 仍为 14。

### 执行结果（2026-08-02）

- 新合同红测先出现 7 个预期失败，实施后 focused UI + smoke 为 `165 passed`；
- 除独立 Qt renderer parity 基线外，完整 batch cluster 为 `843 passed, 1 warning`；
- Inspector preset focused suite 为 `211 passed`；
- 1080×760 / 1440×900 Qt 离屏证据位于
  `/tmp/tracelab-batch-inline-files-proof-final.JDzjYA`；方法按钮宽度最大差值 1 px，
  长列表固定为 4 行视口并可滚动，slider/spin/recipe 实测为 `20 / 14 / 125%`；
- 独立 `tests/test_batch_qt_render_parity.py` 仍是既有 14-reference parity 基线失败，
  本轮未修改该 renderer 或参考图；macOS 前台验收未执行，不能由离屏结果替代。

## 2. 实施原则

- 先写行为/几何红测，再改 widget；不重构 BatchRunner 或 source adapters。
- `FileListWidget` 继续是唯一文件状态权威，只改变宿主层级和尺寸策略。
- HTML 的操作映射完整落到 Qt；原型中的模拟状态不进入产品常量。
- 视觉完成必须有真实 QSS Qt 截图；绿色 pytest 不能替代目视。
- 本轮不提交、推送或合并，除非用户后续明确要求。

## 3. Phase 0 — 冻结红色合同与基线

**Files**

- `tests/ui/test_batch_method_buttons.py`
- `tests/ui/test_batch_input_panel.py`
- `tests/ui/test_batch_compact_contract.py`
- `tests/ui/test_batch_output_panel.py`
- `tools/render_batch_compact_ui.py`

**工作**

- [x] 新增方法按钮等宽断言：显示后四按钮宽度最大差值 ≤1 px，并用 font metrics 证明
  `FFT vs Time` 小于可用 content rect。
- [x] 新增文件第一层红测：两个添加动作和结构化列表直接 visible；不存在/不依赖 modal；
  空、ready、probing、failed、unavailable 均有稳定可见状态。
- [x] 保留现有文件能力测试，补多逻辑 source、重复路径、逐行移除后 intersection / picker /
  pipeline 刷新断言。
- [x] 新增 slider 红测：X/Y/字号分别经 `QTest.mousePress/mouseMove/mouseRelease` 改值，
  配对 spin、popover style、OutputPanel 摘要和 emitted recipe 同步。
- [x] 保存当前 1080/1440 截图，明确 modal、非等宽和预设左对齐基线。

**Gate：** 新合同在当前实现上按预期失败；既有 batch 行为测试仍绿色。

## 4. Phase 1 — 方法按钮等宽与预设文字居中

**Files**

- `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- `tests/ui/test_batch_method_buttons.py`
- `tests/ui/test_batch_compact_contract.py`

**工作**

- [x] `MethodButtonGroup` 四个按钮使用相同 stretch / size policy；不再给 `fft_time` 双倍空间。
- [x] 在 288–320 px Analysis pane 真实最窄合同下核对文字；若等宽后最窄宽度不足，优先
  收紧安全 padding / 字号度量，不恢复不等宽。
- [x] `_PresetCard.paintEvent()` 的标题与摘要改为水平居中，保留 title/summary 两层垂直节奏、
  selected 颜色、compact 38 px 状态与省略策略。
- [x] 不移动“分析预设”标题和同步徽标，不改变按钮 `text()`、槽映射或 applied/dirty 逻辑。

**Gate：** 1080/1440 的 FFT 和 FFT-vs-Time 截图中按钮等宽、长文案完整、四张预设卡视觉居中。

## 5. Phase 2 — 文件管理直接进入 Input 第一层

**Files**

- `mf4_analyzer/ui/drawers/batch/input_panel.py`
- `mf4_analyzer/ui/drawers/batch/file_list.py`（仅当拆分现有内联类可降低职责时；不强制）
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_batch_input_panel.py`
- `tests/ui/test_batch_compact_contract.py`

**工作**

- [x] 删除主栏 `管理文件` 按钮和 `BatchFileManagerDialog` 宿主；把现有
  `FileListWidget` 直接放入 `InputPanel` 的“数据文件”block。
- [x] 标题行显示实时 facts + status；操作行保留 `+ 已加载`、`+ 从磁盘…`，名称和触发
  逻辑不改。
- [x] 保留结构化行的名称、路径、group、probe 状态、tooltip 与移除按钮；补紧凑空状态。
- [x] 设定约 3–4 行的可视高度；超出后内部滚动。列表在顶/底边界继续把滚轮交给外层
  Input scroll area，保证下方目标、RPM、预处理始终可达。
- [x] `filesChanged`、`intersectionChanged`、`stateChanged` 原信号继续驱动信号宇宙、pipeline、
  预检与任务摘要；不得为标题事实另建缓存模型。
- [x] probe 生命周期不因 reparent/show-hide 重启；已加载来源不重复解析。
- [x] 移除仅删除对应物理/逻辑 source，并立即刷新共同信号和运行状态。

**操作 parity checklist**

- [x] 已加载文件菜单；
- [x] 磁盘多选对话框；
- [x] pending/probing；
- [x] ready；
- [x] failed/unavailable + 原因；
- [x] 多逻辑 source；
- [x] 重复路径去重；
- [x] 逐行移除；
- [x] tooltip/路径/group/probe cost；
- [x] 空态与列表滚动；
- [x] target picker / pipeline / preflight 同步。

**Gate：** HTML→Qt 操作映射逐项有测试；空态、三行混合状态、长列表三张截图目视通过。

## 6. Phase 3 — 修复刻度与字体 slider 双向绑定

**Files**

- `mf4_analyzer/ui/drawers/batch/render_style_popover.py`
- `tests/ui/test_batch_output_panel.py`

**工作**

- [x] 用显式 pair binding 取代六个控件共用的无来源 handler：slider 先同步配对 spin，spin
  先同步配对 slider，再从规范化控件值构造 `RenderStyle`。
- [x] 同步配对控件时阻断其 signal，防止递归和一次动作多次 emit。
- [x] 保持 preset/reset 的原子 `set_style()`；X/Y/字号自定义后重新计算 preset checks。
- [x] 验证拖动过程中 OutputPanel summary 连续更新，关闭再打开 popover、应用方案和导出
  recipe 后数值不回退。
- [x] 验证极值、字号 5% step、键盘箭头/轨道点击、spin 直接输入仍可用。

**Gate：** 三条 slider 的真实鼠标拖动测试绿色；一次动作一次最终 change，slider/spin/summary/recipe 一致。

## 7. Phase 4 — 响应式、离屏矩阵与回归

**Files**

- `tools/render_batch_compact_ui.py`
- `tests/ui/test_batch_compact_render.py`（仅在现有 probe 无法表达新状态时新增）
- `/tmp/tracelab-batch-inline-files-proof`（临时证据，不提交）

**离屏矩阵**

- [x] 1080×760：空文件、3 ready、ready+probing+failed、长列表；
- [x] 1080×760：FFT default/applied/dirty，方法按钮和预设卡可见；
- [x] 1080×760：刻度弹层 default 与自定义拖动后；
- [x] 1440×900：上述各取一张总览；
- [x] 检查 Input 外层可滚到预处理尾部，文件内层可滚到最后一行，footer 固定。

**测试与检查**

- [x] `tests/ui/test_batch_input_panel.py`
- [x] `tests/ui/test_batch_method_buttons.py`
- [x] `tests/ui/test_batch_output_panel.py`
- [x] `tests/ui/test_batch_compact_contract.py`
- [x] `tests/ui/test_batch_smoke.py`
- [x] 现有完整 batch cluster 与 Inspector preset focused suite；
- [x] `git diff --check`；
- [x] lessons completion gate。

**Gate：** 主执行者实际打开 contact sheet 并逐状态记录 PASS/FAIL；macOS 前台状态另列，不能由离屏替代。

## 8. 完成定义

只有同时满足以下条件才完成：

1. 四项用户反馈全部有实现、回归测试和渲染证据；
2. 文件管理位于第一层且 parity checklist 无缺项；
3. 四按钮等宽、预设卡文字居中、`FFT vs Time` 无裁切；
4. X/Y/字号都能真实拖动且不回弹；
5. 1080×760 / 1440×900 无重叠、横向截断或滚动死区；
6. 业务回归无新增失败，Qt 离屏和 macOS 前台证据分开报告；
7. 工作树仅包含本任务文件；不自动 commit/push。
