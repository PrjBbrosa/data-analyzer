# 分析 View 对比修复与验证记录

日期：2026-10-05（Asia/Shanghai）。基线 HEAD：`6306b3b1fd4ef40bccc8bf612d07fdd99569fa13`。以下为本轮修复的提交前验证记录。

## 修复结果

对应 `docs/analyzer/reviews/2026-10-04-analysis-view-implementation-review.md` 的 R1–R9：

| Review | 落地行为 |
| --- | --- |
| R1 结束对比串参数 | 关闭前捕获当前焦点，关闭后按原 View 恢复参数、来源、时间与画布。菜单替换对比也先捕获离焦状态。 |
| R2 隐藏保存串参数 | 捕获控件时保留对比焦点的 View 身份，不因 section 隐藏就把 B 的参数写给 manager.active=A。实际项目 JSON 用例覆盖四模块。 |
| R3 范围模式写错 View | “全时段/指定范围”按焦点 View/pane 路由，与数值编辑使用相同目标。 |
| R4 显示参数跨 View 混用 | FFT、FFT-time、Order 渲染从绑定 View 取显示参数；dB reference 可按该 View 的 Auto/Manual 意图和实际来源解析。保留非对比旧调用兼容入口。 |
| R5 FRF 显示写错画布 | 直接显示编辑和 display-only preset 都从目标 View/pane 查找画布。 |
| R6 结果有效性写错目标 | 当前请求查缓存、stale 标记、恢复结果都使用目标 state。FRF 的 peer 也参与可见结果更新。 |
| R7 FRF 范围还原仍重算 | lookup 不再要求上次 effective_time_range 非空；请求重新匹配缓存时恢复图、facts、有效范围和 pin，不提交新 job。 |
| R8 FRF 视窗捕获串侧 | 按 canvas binding 捕获目标 View 的 X 与三个 Y 面板范围，焦点离开也捕获 FRF 相机。 |
| R9 不兼容轴联动 | log/linear 不一致时拒绝联动；已开启的联动在尺度改变后解除。热图锁色阶核对实际来源的 quantity/unit/reference，而非仅比较控件值。 |

横向补齐：

- 后台热图绘制不再回写焦点侧的自动色阶；色条拖动只有所属焦点 pane 可以回写 Inspector，并立即持久化该 View 的参数。
- FFT-time 迟到完成取所属 View 的最新显示意图；facts/状态反馈校验 View 和 pane，而不仅校验 View。
- 对比中增加/关闭主侧内部 pane 后重建 canvas binding，保留 peer 焦点。
- Cocoa 原生检查发现双 pane 从左右转上下时沿用旧尺寸比例，导致一个 FRF canvas 仅约 115 px 高；在方向真正改变时重新均分尺寸，后续 resize 保留用户拖动比例。主侧和 peer 复用同一方向处理。
- hints/quickref 补充兼容性要求；没有更改数值算法、版本号或原始采样数据。

## 正式回归

新增 `tests/ui/test_analysis_view_comparison_regressions.py`，31 个用例覆盖：

- 四分析模块关闭对比、隐藏保存与时间范围模式切换；
- FFT 独立显示和不同 Manual dB reference；
- FRF 显示更新、相机捕获、真实 job 的范围改回缓存复用、不兼容轴及开启后改轴尺度；
- FFT-time/Order 后台色阶隔离、异步显示归属、色条操作回写；
- 四模块动态增加/删除 pane 的绑定；
- 真实来源 Auto reference 不一致时禁止锁色阶；
- 四 FRF pane 方向变化后的高度比例。

修复前九项原始 probes：`9 failed`。新增横展曾得到 `7 failed, 2 passed`（其中色图测试使用了 Inspector 不支持的 cmap，改为有效的幅值模式差异后验证异步显示归属）；色条路由 `2 failed`；布局回归 `140 / 782 < 0.35`。最终全部 31 个用例通过。

## 验证结果

日志和前后源码指纹均在 `.state/analysis-view-review-20261004/`。`run_gate.py` 对生产 Python 与测试 Python 文件做 SHA-256 快照，记录 HEAD、命令及运行期间变化。

| Gate | 结果 | 源码稳定性 |
| --- | --- | --- |
| `final-owner` | **330 passed**, 33.48 s | stable=true，changed=[] |
| `final-boundary` | **97 passed**, 4.58 s | stable=true，changed=[] |
| `final-layout-integration` | **219 passed, 2 failed**, 15.23 s | stable=true，changed=[] |
| `native-styled-fixed` | **1 passed**, 2.28 s，macOS Cocoa | stable=true，changed=[] |

- Owner：新旧 comparison、FRF MainWindow、analysis time isolation、multiview、source scope、view bridge、AnalysisContext、cache residency、preset guard、production auto range。
- Boundary：MainWindow 状态所有权、UI import、lambda signal ratchet、FRF/FFT-time coordinator、Order cache key、dB reference controls/settings、项目 analysis payload。
- Layout integration：AnalysisSectionPage、31 个新增回归、既有 comparison、ViewTabBar、项目比较关系恢复、QSS border/radius gate。
- Owner gate 后仅新增了方向均分的 page 改动和测试调整；由后续 layout integration 与 styled Cocoa 覆盖。未为同一稳定快照重复运行全套。
- `git diff --check` 通过。

两个既有失败与 Grok 修改前全套结果的断言数值完全一致：

| 既有失败 | 修改前 / 本轮相同的断言值 |
| --- | --- |
| `test_split_frf_plot_areas_align_all_three_rows` | left=56.475，期待 59.6±1 |
| `test_split_fft_time_heatmap_and_slice_plot_areas_align` | width=451.659375，期待 459.51875±1 |

它们是现有单 View split 的绘图区对齐缺口，本轮没有把它们改为 skip/xfail，也没有放宽断言。不能将 layout gate 或整个仓库宣称为全绿。

## 原生与其他工作区改动

Cocoa 探针使用真实 MainWindow、Fusion、生产 stylesheet 与图表字体，构造两 View 各两 FRF pane，点击 peer 的第二 pane、修改显示并结束对比。抓图 `native-four-frf-panes.png` 已做视觉检查，四个窗格均可见，没有修复前主侧明显压缩的问题。第一轮未加载生产样式的截图不作外观验收；styled 探针暴露布局失败后修复并重新通过。

这是独立原生测试窗口与合成结果，**不是用户原始文件的前台验收，也不是 Windows frozen 验收**。没有触碰用户正在使用的项目数据。

工作中发现另一个会话同时修改时间范围边界确认、PersistentTop、FRF 淡化绘图及其文档/测试。已保留这些改动；与本轮共享 `_analysis_mixin.py`、hints/quickref 的不同修改片段也保留。各最终 gate 的源码指纹稳定。本报告不将另一会话的功能归入本轮交付。

Grok 既有全套结果：主套件 `54 failed, 13175 passed, 68 skipped, 3 deselected`；acquisition UI `369 passed, 2 skipped, 1 error`。本轮未再运行约四小时的 full gate，以上 focused/boundary/native 结果不能替代仓库全绿或 Windows Full/Lite 验收。

## 提交前隔离检查

另一个会话已将其改动独立提交为 `da2e9e87`。本轮仅暂存 View 修复、31 个回归用例及对应 plan/review/验证记录。为确认未隐含依赖另一个会话的修改，以原基线加本轮补丁导出的独立源码快照运行新增回归：**31 passed**，6.00 s；当前组合工作区同一组回归 **31 passed**，5.31 s。提交前 `git diff --cached --check` 通过。
