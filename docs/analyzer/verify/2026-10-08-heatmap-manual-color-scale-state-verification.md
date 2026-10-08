# 热图手动色阶状态：实施与验收记录

日期：2026-10-08。HEAD：`875221db`，未提交工作树；没有 commit、push、版本升级或发布。

对应 [Spec](../specs/2026-10-08-heatmap-manual-color-scale-state-spec.md) 和 [Plan](../plans/2026-10-08-heatmap-manual-color-scale-state-plan.md)。用户已明确授权 agent 并行实施。本记录区分源码、offscreen Qt、显示中的 Cocoa 窗口与 Windows frozen。

## 1. 结论及原因

核心漂移修复及已识别的横向入口已实现。原先复用画布的上一次 reference 被用来平移另一个 View 的手动范围，随后派生数字回写 Inspector，并在 capture 时成为下一次请求。30 dB 取决于参考值比值，不是固定增量。双 pane 会在同一轮重复消费被首个 pane 改写的控件数字。

现在请求归属 View/pane，reference 基准随来源持久化；每次有效范围直接从原始请求和稳定基准求得。参考值真实变化仍发生合法平移，View 切换不再借用另一幅图的历史。

最终核心及共享边界全部绿色；Cocoa 合成前台核心路径绿色。A17 的其他原生交互子项、用户原始项目与 A18 Windows Full/Lite 尚未验收，不能据此宣称全平台发布完成。

## 2. 实施范围与归属

父 agent 管理主流程、信号归属、输出适配和验收；三个 worker 负责共享策略/状态、画布/控件、集成与原生探针。文件所有权按阶段交接，没有同时编辑同一 owner。

| Owner | 实施结果 |
| --- | --- |
| `mf4_analyzer/heatmap_color_policy.py` | 中立纯标量解析；来源/单位/quantity/origin 验证；稳定基准的对数差；专用可处理的范围验证异常 |
| `ui/heatmap_color_coordinator.py` | prepare/complete/settle；View/pane 请求编辑；普通、本地 comparison、跨 View 锁定组；撤销 opening 快照；陈旧提交防护；生命周期清理 |
| `ui/main_window/analysis_context.py` | 显式持有协调器；preset commit 按 comparison 焦点找 owner |
| `ui/analysis_view_state.py`、`ui/project_io.py` | 可选基准、nested schema 12、深拷贝、fid remap、缺源/损坏基准处理；旧数字首帧零偏移 |
| `ui/analysis_view_bridge.py` | 捕获非 Z 参数同时保留原始请求；FFT/FRF 和旧 duck-type 接口保留原路径 |
| 两个热图 mixin、render DTO、`_analysis_mixin.py` | 正式路径显式 resolved levels；停止逐 pane 回写；最终 settle 后 reveal/UltraView；绑定具体画布；非法目标不冒充另一 View 旧图 |
| `ui/pg_canvas/heatmap_canvas.py`、`analysis_section_page.py` | 静默同步图像、色条与切片；锁定批次抑制中间 union；最终锁定范围作为双击恢复基线；裸 canvas 原 API 保留 |
| Inspector helpers、两个 contextual、PresetBar | double 精度、超出旧控件范围的显示、显式编辑与草稿、单位切换原子更新、非 Z preset、baseline 请求比较与 effective 导出分离 |
| Chart Options 与 `_axis_interaction.py` | Apply/Restore/Cancel 区分，打开时请求及基准恢复，owner/source 改变后拒绝陈旧颜色提交 |
| `window.py` 输出接缝 | remembered Batch preset 使用当前有效范围；独立 Batch recipe/渲染数学不改 |
| hints/quickref | 锁定编辑、解锁恢复各自窗口、Inspector 覆盖作用域的最小说明 |

本次未修改 DSP、采样率、计算缓存 key、自动色阶分位数或其他分析数学。

已有 FRF recovery、Windows Lite 构建、对应测试与说明均保留。hints/quickref 与 lessons INDEX 上的原有修改未回退。工作中出现的独立 `2026-10-08-head-colormap-demo.html` 原型也未修改。

## 3. 失败先行与开发问题处理

- 原始 A01/A03：真实 MainWindow 合成缓存，**4 failed**；首个 B 的实际 `[-110,-30]` 对比请求 `[-80,0]`。
- 扩展早期回归：**14 failed / 8 passed**，包含 reference、捕获精度、pane 覆盖和顺序串写。
- 项目保存测试曾错误替代高层恢复 dispatcher，跳过 pending 清理。已仅替代 section 的计算入口，保留真实项目恢复 bookkeeping；没有削弱有效窗口断言。
- 开发组合测试曾在新增的 `self.sender()` 查询处 Bus error，整次结果记为未验证。改为信号连接时显式绑定画布；同一组合后续正常结束，再经最终稳定快照门禁。
- 最终审查额外关闭：comparison 内各 View 本地锁定被忽略、单 pane 重复 settle、旧 completion 消耗新 prepare、无结果提交不投影、非 Z preset/新保存 baseline 假 dirty、非法范围留下旧 View 图、对话框陈旧 Apply、锁定双击恢复旧自然范围。
- 相应问题均有针对性回归；没有删除既有合法 reference 平移测试或放宽 ratchet。旧“auto 必须重画两次”测试更新为已解析投影可 retain，并增加请求/图像/Inspector 不变量断言。

开发原始日志在 `.state/heatmap-color-state/`，不是版本化产品依赖。

## 4. 最终测试结果

统一 offscreen 命令前缀：

```sh
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest
```

| 分组 | 实际文件/范围 | 结果 | 日志 |
| --- | --- | --- | --- |
| 最终 owner/集成 | `tests/ui/test_heatmap_color_{policy,coordinator,projection,state_integration}.py`；`test_analysis_multiview_integration.py`；comparison + regressions；bridge；AnalysisContext；preset_state | **349 passed**，34.47s | `final-owner-gate.txt` |
| 最终共享边界 | analysis_view_state、analysis_section_page、dialogs、pg_heatmap_canvas；backref、MainWindow state ownership、no-lambda、UI import、hints；source_scope 当前 schema 单项、pinned_cursor schema 单项；project_io_analysis_views | **489 passed**，24.24s | `final-boundary-gate.txt` |
| 输出与中立导入 | `test_batch_render_qt_heatmap.py`、`test_batch_heatmap_producer_contract.py`、`test_signal_no_gui_import.py`、`test_batch_render_import_boundary.py`、`test_native_import_boundaries.py`、`test_packaging_imports.py` | **96 passed, 1 skipped**，6.53s | `output-import-gate.txt` |
| Schema/草稿 | `test_analysis_time_range_intent.py::test_serialized_views_omit_drafts_and_signatures` | **1 passed**，0.96s | `schema-draft-gate.txt` |
| Cocoa 显示窗口 | 下节独立进程，最终源复验 | **2 passed**，9.07s | `native-results.txt` |

上述四组 offscreen 文件/用例不重叠，共 **935 passed, 1 skipped**。packaging 中当前构建生成的 `build/spec/TraceLab8.4.2.spec` 不存在，对应检查跳过；这不是 Windows frozen 验收。pyqtgraph/NumPy shape 弃用警告和 offscreen 平台提示保留在日志，不隐藏。

最终 owner 与共享边界使用稳定源快照；`final-source-before.json` / `final-source-after.json` 比较 39 个变更源码及测试文件，哈希与 HEAD 一致。输出/导入组随后无相关输出实现变化，复用其成功结果。本任务未运行全仓 suite，范围是受影响 owner 与明确边界。

## 5. A01–A18 对照

PASS 指表内实际列出的证据范围，不把单项通过扩成所有未执行组合。

| ID | 结果 | 证据/剩余范围 |
| --- | --- | --- |
| A01 | PASS | 时频/阶次两 View 20 次往返；不同手动参考，各自请求保持；零新计算 |
| A02 | PASS | 不同 fid 同名通道及元数据 Auto reference；复合来源隔离 |
| A03 | PASS | 两 pane、焦点 0/1、反向绘制、覆盖优先级、共享控件不串写 |
| A04 | PASS / 部分组合未单列 | 真实 reference 编辑 1→10→1；纯策略极值；既有可见 catalog 更新及渲染测试。隐藏 catalog 更新的独立端到端用例未新增 |
| A05 | PASS | 同 reference、Auto、Linear、section 往返；空结果/无结果编辑；缓存恢复已有 owner 测试 |
| A06 | PASS（Qt） | 色条/双击既有画布测试；单边精度、auto/manual、unit 原子切换；真实 dialog opener Apply→Restore/Cancel/仅标题 |
| A07 | PASS | pane 默认/覆盖；真实 PresetBar 有 Z/无 Z/保留范围；保存及重载 baseline；非 Z 编辑不改基准 |
| A08 | PASS（Qt） | union 与解锁；本地/跨 View 分组；缺结果成员；final reset baseline；图像/cbar/slice一致 |
| A09 | PASS（Qt） | comparison focus/换 host-peer/退出；既有 comparison 全文件；陈旧 completion 和 dialog owner/source guard |
| A10 | PASS | 真临时 .tlproj 可见/隐藏保存重开；旧缺基准、损坏基准、fid remap/缺源、复制深拷贝 |
| A11 | PASS | 非法标量/极值；超旧 ±500 范围；无数据不建基准；非法恢复不能保留另一 View 图片 |
| A12 | PASS | raw/display 数组、dtype/shape 不变；同 owner/reference 逐元素比较，零 DSP 提交 |
| A13 | PASS | capture/save/non-Z 不把投影持久化；未编辑 double 精度；preset baseline 比较请求，导出有效数字 |
| A14 | PASS（指定产物） | GUI→Batch current/remembered；Batch renderer 手动范围；实际 PNG 保存读取、图表复制、UltraView 异步 current preview/复制。OS clipboard 用图片 sink；未新增全格式 CSV 导出测试，raw 数组不变已有证明 |
| A15 | PASS | resolved retain/signature、真实 reference 重绘、旧 canvas API；deferred reveal 在最终 union 后执行 |
| A16 | PASS | bridge/context 非热图对照；state/backref/import/signal gates；不代表全时域/FFT/FRF 功能重新验收 |
| A17 | PARTIAL | 下节 Cocoa 显示窗口核心路径通过；原生 split/拖动/dialog/项目等完整组合、实际 DSP 原生端到端及用户原项目尚未验收 |
| A18 | UNVERIFIED | 未构建并运行新的 Windows Full/Lite frozen 包 |

## 6. Cocoa 证据

独立命令：

```sh
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python .state/heatmap-color-state/native_runner.py
```

环境：macOS 27.2 arm64，Qt 5.15.14，PyQt 5.15.11，pyqtgraph 0.14.0。真实 `MainWindow.show()`，生产 Fusion/QSS/字体，测试隔离 QSettings；每个窗口完成后关闭。

时频与阶次各两个 View：A 请求 `[-80,0]`/ref=1，B 请求 `[-65,5]`/ref=`10**1.5`；20 轮往返后实际图像、色条、切片、Inspector 和请求一致。reference 编辑 1→10→1 对 A 显示 `[-100,-20]` 再恢复 `[-80,0]`。使用可重建 typed 缓存矩阵，不冒充原生实际计算验收。

已抓取初始、中间、末轮、reference 恢复 PNG，并核对末态截图。最终轴数字区域自动比较：阶次完全相同；时频色条/切片轴分别仅 10/18 像素差 1 灰度级，超过 1 的差异为 0。整幅 canvas 在切片抗锯齿/过渡边界存在像素差，**不宣称整图像素完全相等**。

最终复验与 `final-source-before.json` 的 39 文件和 HEAD 全部匹配。详细数值、像素区域、PNG 与环境记录位于 `.state/heatmap-color-state/native-report.md`、`native-*-evidence.json` 和 `native-source-identity.json`。

## 7. 交付边界

- 已有项目里此前累计写坏的数字保留原保存值；没有按猜测减去 30/60/120 dB。新基准阻止后续重复漂移，不能重建用户遗失的原始意图。
- 原始投诉项目未提供/未使用；合成复现、源码修复、offscreen 与 Cocoa 核心行为已有独立证据。
- 没有把 Windows source/import 通过当作安装包通过。发布前仍需实际 Full/Lite frozen 与所列原生交互验收。
- 新增短 lesson `heatmap-color-request-reference-anchor.md`；lesson gate 已清。`git diff --check` 及新文档引用/路径校验作为收尾门禁。

## 8. 用户授权 commit 后的范围检查

提交准备期间，独立色图任务先完成 `4b7c20be`。本任务按上一轮 SHA-256 验收快照重建 39 个文件的任务差异，未覆盖并行任务的工作树或暂存区。先在不包含其他改动的独立快照运行色阶 integration/coordinator/projection：**94 passed**；随后与新色图提交整合，并适配其明确 `target_canvas` 的 Batch 接口，隔离快照再次 **94 passed**（11.01s）。

提交只包含本任务的代码、测试、Spec/Plan、验收记录和 lesson。共享 hints/quickref/INDEX 按变更块拆分；FRF recovery、Windows Lite 修复与色图任务留下的其他修改仍保留。本次未 push。提交阶段未重复全量测试，沿用上面的分层证据。
