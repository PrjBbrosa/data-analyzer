# 四模块计算／缓存／显示统一验证

日期：2026-10-11。HEAD：`4667dd06c98d624b6d5e5663eeb69e4b8911e60e`。在原有 dirty 工作区实施，未提交、未推送；保留先前对比修复及其他工作。

对应：[spec](../specs/2026-10-11-analysis-explicit-compute-and-display-spec.md)、[followup plan](../plans/2026-10-11-analysis-explicit-compute-and-display-followup-plan.md)。

## 实施结果

四模块使用会话内请求快照和 `PaneState.result_binding`，只有显式计算成功／缓存命中可以应用新结果。参数／源／范围编辑保留旧图并标记待计算；显示刷新、View 和对比切换读取已应用键及原始源上下文。dB 编辑器与管理对话框统一走显示刷新，不调用计算入口。当前与旧项目重开都恢复意图并等待点击计算，不保存计算结果或修改项目 schema。

异步完成检查 pane 身份与请求修订；编辑再改回不能复活旧请求。拒绝完成撤回临时新增 pin，后台失败不覆盖当前 View 提示；失败、预检失败和主动取消保留旧结果且待计算。FFT 部分成功只绑定成功来源；三个兼容单信号入口也纳入绑定。

## 修复前与过程证据

- 共享交互回归初始 **10 failed / 1 passed**：显示修改清空结果、dB 保存自动计算、其他 View 公共缓存未经计算便出图。`.state/analysis-explicit-compute-20261011/root-red.log`。
- 项目恢复初始 **8 failed**，真实按钮／服务和同步 DSP 计数证明 draft 与计算过的项目均自动启动；新旧格式矩阵随后通过。
- FRF、FFT family 的过期完成 pin、后台失败、取消、legacy 缓存命中等新增用例先红后修；分别保留在 `.state/frf-*.log` 与 `.state/explicit-family-*.log`。
- 旧测试若只向公共缓存 put 就期待显示，改为明确绑定“已计算结果”的 fixture。项目重开测试先断言空图，再显式计算；保留色阶、来源、标注、视口等原行为断言。
- shared renderer 回归曾发现空白 FFT View 残留上个 View 标题，恢复空图路径的 chart appearance 投影，原失败节点通过。

## 稳定整合门禁

**246 passed，836 warnings，73.40 s**，日志 `.state/analysis-explicit-compute-20261011/stable-integration.log`。包含：

- 新模型、FFT family、共享刷新、FRF、项目恢复 5 个合同测试文件；
- 之前对比交互、状态、游标、共享 toolbar、半色标签及两组 comparison 回归；
- MainWindow 状态所有权、导入边界、lambda signal shrink-only 门禁。

使用项目 `.venv`、`TMPDIR=/tmp`、`MPLCONFIGDIR=/tmp`、`QT_QPA_PLATFORM=offscreen`、`PYTHONPATH=.`。源与测试文件指纹记录在 `stable-before.json` / `stable-after.json`，整合及后续 Cocoa 期间 58 个 source/test 文件指纹完全一致。

## 最终原生四模块图面检查

同一稳定源码快照，Cocoa 真实 Qt 窗口 **15 passed，16 warnings，17.04 s**，日志 `.state/analysis-explicit-compute-20261011/native-final-fixed.log`。使用真实窗函数、显示单位和 dB 对话框按钮信号，覆盖四模块编辑／显示、空白 View 禁止借公共缓存和范围修改后切 View 返回。保存 15 张窗口图，实际检查 FFT 与 FFT-time 的保留曲线／热图及“上次计算结果”事实卡；草稿范围与上次结果参数明确分离。

初次取证在 pytest-qt 已销毁窗口后的 fixture teardown 截图，产生 7 个 `RuntimeError`，该轮不作为通过。仅将测试取证移至 call 阶段，产品源码未改变，重新完成上述 15 项；不把截图工具时序错误归为产品缺陷。

## 其他 owner 门禁（不累加成总数）

| 范围 | 结果／证据 |
| --- | --- |
| FFT family 现存 owner、multi-view、coordinator、Order smoke | **152 passed / 1 deselected**，`.state/explicit-family-stable.log`；另 9 类入口边界 **63 passed** |
| FRF 新合同、MainWindow、coordinator、validation recovery | Cocoa **102 passed**，`.state/frf-cancel-preflight-green-cocoa.log` |
| 范围意图、确认与四模块显示恢复 | **139 passed**，`.state/analysis-explicit-compute-20261011/range-boundary.log` |
| heatmap 色阶状态 | **52 passed**，`color-fixture-migration-final.log`；保留全部色阶断言 |
| dB 控件／设置与 analysis View bridge | 在 display-boundary 过程中通过；该轮的失败均属于后来完成迁移的 heatmap fixtures |
| 项目旧格式／当前格式与提示指南 | 增补复验 **59 passed**，source boundary **6 passed**；项目 owner 初轮其余 **210 passed**，失败节点均定向修复复验 |
| state/model/cache/import/signal 边界 | **76 passed**；后来移除 3 个 dB lambda 连接后，将 whitelist 从 30 缩至 27，**2 passed** |

## 独立既有失败与验收限制

`test_fft_time_chart_options_restore_reverts_range_and_color` 仍期望旧默认色图 `gnuplot2`，当前默认为 `tracelab.head-style.v1`。完整 owner 轮记录了该失败（`explicit-family-gate2.log`），最终 focused 轮仅排除此已确认独立问题，未改产品色图或用 xfail 掩盖。

本次不是发布，未运行全库。Cocoa 为真实 macOS Qt 测试窗口；用户原运行实例／解锁后的前台人工验收、Windows 应用／冻结包未验证。不得据此宣称 Windows 或发布验收通过。

新增 durable lesson：`analysis-cache-is-not-result-publication-authority`，明确缓存存在不等于可以发布结果，并覆盖同一能力的编辑器／对话框两条入口。
