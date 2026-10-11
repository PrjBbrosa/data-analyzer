# 四模块显式计算与显示刷新 Followup Plan

日期：2026-10-11。执行依据：[统一规范](../specs/2026-10-11-analysis-explicit-compute-and-display-spec.md)。状态：实施与定向整合完成；用户原实例及 Windows 验收未执行。

## 目标与边界

修复编辑参数时自动出图、缓存回退突然换图、显示调整清空旧图、dB 保存启动 DSP 和项目重开隐式计算。保留此前对比视图修复及工作区其他未提交变更；不改 DSP、版本、打包、CLAUDE.md；不提交或推送。

## 并行所有权

| 包 | owner | 唯一写入范围 | 检查 |
| --- | --- | --- | --- |
| A 请求快照与 FFT 家族 | comparison_state | analysis_view_state.py、新 analysis_result_state.py、_fft_mixin.py、_fft_time_mixin.py、_order_mixin.py；必要对应 coordinator；新家族测试及受影响旧测试 | 先红：显式接受/cache-hit/legacy/过期完成；owner suites |
| B FRF | comparison_chrome | _frf_mixin.py、必要 frf_coordinator.py、新 FRF 测试及其受影响旧测试 | 先红：草稿缓存不发布、display保留、后台身份、失败 |
| C 项目恢复与用户说明 | comparison_tabs | _project_io_mixin.py、hints.py、quickref.py、四分析指南、user-guide、项目恢复相关测试 | 未计算和已计算项目重开零提交；提示一致性 |
| D 共享刷新与集成 | 主 agent | _analysis_mixin.py、必要 window.py、新跨模块交互测试、本 plan/spec/verify | dB真实保存；四模块编辑/显示/View/对比矩阵；边界与整合 |

所有 agent 共用目录，不回滚其他编辑，不执行全库。A 先固定共享模型接口，B/D 依接口实施，接口变更由主 agent 协调。共享文件只由列出的 owner 编辑。

## 顺序与门禁

1. 保存当前 HEAD/dirty 范围，复用既有修复前探针；新增能失败的 focused tests，不重复全库基线。
2. 固定会话内 `PaneState.result_binding` / `request_revision` 与请求快照接口；不序列化结果绑定。
3. A/B 接入显式计算成功/cache-hit和完成准入；D 改共享缓存恢复与显示入口；C 去掉项目自动请求并更新用户说明。
4. 每包运行自己的 focused gates。将旧“缓存存在即能显示”的 fixture 改为明确已计算绑定，不通过宽松断言保留旧语义；与本次无关的失败单独报告。
5. 主 agent 检查完成/编辑/保存恢复边界；统一跑新测试和受影响对比测试，另跑 main_window_state_ownership、import_boundaries、no_lambda_signal_connections 等实际涉及边界。无需 full suite；只有新增污染证据才扩大。
6. Cocoa 测试窗口验证真实控件与图存在/身份；用户原应用和 Windows 未验则明确标出。检查 docs 全文、引用、过期规则、git diff --check 和 lessons 状态。
7. 写 verification 记录每包结果、测试数量、已知独立失败与未验门禁，更新本计划状态。

## 风险控制

结果存入缓存不等于允许发布；必须先通过提交修订/pane token。显示标签/effective facts同样读取绑定快照。缓存清理不能误删仍显示的旧键。FFT部分成功与兼容单信号入口必须覆盖。项目重开统一手动计算是有意的交互更改，不能仅隐藏旧行为测试失败。禁止临时替换 Inspector/草稿状态来渲染旧结果，避免信号重入和状态污染。

## 执行闭环

A/B/C/D 均已完成并冻结源文件。最终稳定整合 **246 passed**，同快照原生四模块窗口 **15 passed**；其他 owner 门禁与独立既有色图断言见[验证记录](../verify/2026-10-11-analysis-explicit-compute-and-display.md)。未做全库或发布验收。`git diff --check` 与 lesson gate 通过，无提交／推送。

落实的追加回归包括取消不发 failed 回调、迟到完成临时 pin 清理、后台状态提示隔离及空白 FFT View 标题清理。旧仅 seed 公共缓存的测试改为显式结果绑定，未删去来源／色阶／对比断言。
