# 坐标刻度宽度与边缘可见性执行 Plan

日期：2026-09-09
状态：仅文档完成，尚未实施。
唯一产品合同：[Spec](../specs/2026-09-09-axis-label-width-and-edge-visibility-spec.md)

## 1. 执行与范围约束

默认单一执行者顺序完成，不要求子代理。Batch 时域、FRF、热图都修改同一 `_builder.py`，避免平行写入冲突。用户当前授权只写 Spec / Plan；实施需后续执行指令。

保留当前其他任务的未提交改动，包括 ZFD、分析 View、预设、Batch 面板、帮助与 QSS。不要修改 CLAUDE.md，不恢复或清理无关文件，不提交 `.state/` 探针和客户数据。

本轮文档 gate：完整阅读本 Plan 与 Spec、核对路径/符号和验收映射、检查文档差异；无可执行变更，不运行运行时 suite。实施不要求全量 baseline；按各步骤的 focused owner 测试先红后绿，再跑相关边界。

## 2. Task 0：锁定复现与验收输入

Owner：执行者；只读检查与临时证据。

1. 记录 HEAD 与相关 dirty scope，确认没有其他任务同时修改将要编辑的 owner 文件。
2. 阅读相关 lessons：`codex-pg-subplot-layout-settle.md`、`overlay-right-axis-columns-need-post-tick-realize.md`、`subplot-bottom-axis-role-must-release-height.md`；旧 `2026-08-04-y-axis-tick-label-clipping-design.md` 只作历史参考。
3. 核对 Spec D1–D4 的现有符号、公共 `ui_kit/axis_metrics.py` 及当前 pyqtgraph 的 AxisItem/ColorBarItem 行为。不修改第三方包。
4. 从 `.state/axis-audit-20260909/` 提炼自包含合成 fixture；若临时文件不在，以 Spec 的输入重建，不把临时路径当测试依赖。
5. 将 D1/D2/D3/D3b 变成修改前会失败的目标测试；D4 先记录完整几何和实际标签，冻结失败模式。

Gate：每项缺字可以和“合理选稀刻度”“精确端点裁剪”区分；记录期望集合与实际绘出集合。客户 WWT 可选 skip-guarded，核心测试无客户文件依赖。检查本次要跑的 pytest 是否与其他任务重叠，避免重复 gate。

## 3. Task 1：Batch 时域分屏与 FRF 左轴

Owner 文件：`mf4_analyzer/batch_render_qt/_builder.py`。测试归属：`tests/test_batch_render_qt.py`、`tests/test_batch_render_qt_frf.py`。

先写 A1/A2 的最小失败用例：单行分屏±510在250%字体、±500000在100%字体；FRF六位线性幅值在250%字体。扩展多行、dB、相位模式和手动范围的参数化场景。

实现步骤：

1. 用现有 `pin_left_axes_to_common_width` 替换两个 callback 的“release→读 width→pin”序列，不复制测宽公式。
2. 确保两个路径都在最终 tick density、范围、字体和标题设置后测量；FRF 注册最终刻度后的 layout callback。
3. 同时激活 owning PlotItem 与外层 GraphicsLayout；保留行高与共享 X 轴布局，不在 paint 中引入重入布局循环。
4. 验证单行分屏不被“少于两轴直接返回”的通用假设遗漏；重复 settle 不能继续扩宽。

Focused：以上两个测试文件。通过后，本步骤边界运行 `tests/test_batch_render_import_boundary.py`、`tests/test_signal_no_gui_import.py`。若公共辅助无需修改，其他消费者只在 Task 4 运行一次非回归。

Gate：A1、A2及A6中的范围/输入保持。Qt字体与像素需真实可用；textSpecs非空不足以过关，必须检查全部期望内部主刻度与标题相交情况。

## 4. Task 2：Batch 与主界面色条

Owner 文件：`mf4_analyzer/batch_render_qt/_builder.py`、`mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`。若确需共享小型测量方法，放 `mf4_analyzer/ui_kit/axis_metrics.py`，不新建跨 MainWindow 状态。

测试归属：`tests/test_batch_render_qt_heatmap.py`；主界面优先在 `tests/ui/test_pg_heatmap_canvas.py` 增补局部色条测试，如独立性明显则新建 `tests/ui/test_heatmap_colorbar_axis_metrics.py`。

修改前必须复现：Batch 100%字体0.1×480000～480000、250%字体0.1～1；主界面−123.4568～−123.4561。用标准色阶作对照。

实现步骤：

1. 明确数字轴与标题轴，释放数字轴继承的45 px固定宽度；保持色带宽度与普通装饰右轴不变。
2. 沿用现有创建/更新/level变化 owner，完成最终字体与range后的预量或自然尺寸收敛。先验证直接释放是否足够，再决定是否需要共享辅助。
3. 主界面复用同一色条更新窄→宽→窄，覆盖清理重建和level拖动。不新增重复连接或signal循环。
4. Batch 在色条尺寸完成后重验热图/切片左右对齐、图例预留与页边界；不能靠把文字画到页面外解决。

Focused：Batch heatmap 文件及新增/已定位的主界面色条用例。Boundary：`tests/ui/test_pg_canvas_backref_invariants.py`；仅改signal wiring时追加 `tests/ui/test_no_lambda_signal_connections.py`。若改共享辅助，追加 `tests/ui/test_stacked_left_axis_metrics.py`、`tests/ui/test_subplot_left_axis_metrics.py`、`tests/ui/test_split_layout_alignment.py` 并作为Task 4可复用结果。

Gate：A3、A4；色阶与矩阵不变，实际绘出数字、标题和色带互不遮挡。主界面和Batch分别验收，不能以一条路径通过代替另一条。

## 5. Task 3：关闭切片 X 轴边缘缺字

Owner 文件：优先 `_builder.py` 的 `_fit_axis_ticks`、`_labels_fit` 或切片布局实际责任函数，具体位置由诊断确定。测试归属：`tests/test_batch_render_qt_heatmap.py`。

1. 使用 Spec D4 合成输入，记录475000的最终映射位置、完整文字矩形、边界余量；验证首次PNG和重新绘制是否一致。
2. 分别检查最终几何后的retick是否发生、fitter估计是否包含端部标签半宽、AxisItem边界裁剪与缓存是否一致。
3. 冻结真实原因再做最小修改。若改变的是tick选择，统一选取可容纳的nice-step并验证所有最终选择；不得只删除一个失败标签或改变X数据范围。
4. 覆盖切片有/无、FFT-time/Order、正/负X、100%/250%字体及960/1920宽。区分允许的整体密度调整和异常单个标签丢失。

Focused：该文件的新增边缘用例与已有切片范围、布局、手动Z范围用例；若改通用tick fitter，再运行 `tests/test_batch_render_qt.py` 的tick-density和manual-range用例。只有影响到新消费者时才扩大到对应文件。

Gate：A5和A6范围保持。若需要共享裁剪策略变更，先修订Spec和本步骤的影响面，再继续；D4不得因其余修复通过而被静默删除。

## 6. Task 4：集成非回归与真实渲染

由同一执行者负责集成，复用同快照已通过结果。对齐逻辑变化会改变绘图区，故本步骤补充以下直接相关合同，不启动全量tests/ui：

- `tests/test_batch_render_qt_ssaa.py`：导出抗锯齿/线宽合同。
- `tests/test_batch_render_qt_display_envelope.py`：最终几何变化后的显示包络。
- `tests/ui/test_subplot_left_axis_metrics.py`、`tests/ui/test_stacked_left_axis_metrics.py`：已有主界面测宽消费者。
- `tests/ui/test_split_layout_alignment.py`：共享辅助或主界面色条尺寸影响跨pane布局时运行。
- 若新增模块或变更导入，再加 `tests/ui/test_import_boundaries.py`、`tests/test_packaging_imports.py`；未变更则不追加。

测试命令模板：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest <本步骤测试文件或nodeid> -q
```

真实Cocoa验证另开新进程，使用 `QT_QPA_PLATFORM=cocoa`。复查A1–A7矩阵中的关键失败输入，保留PNG、textSpecs、轴/标题/页面几何及运行环境；自动比较集合/矩形和图片差异，不把全部图片交给用户目测。

前台TraceLab验证：用可获得的WWT或合成文件打开Batch，切换合并与分屏/叠加、100%/250%字体，确认代表预览与最终导出一致；查看FRF三联图、FFT-time/Order色条和切片。Cocoa孤立画布不冒充前台验证；无法完成则A8为partial。Windows Full/Lite冻结版本另列结果，未跑标记UNVERIFIED。

Gate：A6–A8。几何修正导致的像素变化先解释再调整期望；不通过放宽全部像素/宽度断言隐藏回归。异常退出、崩溃或中断为UNVERIFIED。

## 7. 收尾与完成报告

1. 完整对照Spec A1–A8，每项列出对应测试/渲染证据及剩余平台gate；明确D4是否关闭。
2. 核对changed-file scope并运行 `git diff --check`；仅提交被授权范围，用户未要求commit/push时不执行。
3. 检查 `scripts/lessons/check.py --status`。本设计已由既有轴测宽/布局教训覆盖；若实施发现新反复模式，再按project-lessons登记并归档，不批量改写旧教训。
4. 临时证据保留在 `.state/`，测试仅依赖版本化合成fixture；本轮不清理其他任务产物。

不要求全量suite。若后续实施扩大到跨边界重构或发布，另明确全量gate原因、单一执行owner及稳定快照；按仓库规定主suite与acquisition_ui顺序分进程，禁止重叠运行。
