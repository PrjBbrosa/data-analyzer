# 切换平顺性复审修正与验证

日期：2026-09-23。修正基线：`1e672f97b1e1fb1904aff43ed029d2b97b8774d9`，原审查范围 `ef63e1e6..1e672f97`。

## 修正范围

| 问题 | 修正 | 回归证据 |
| --- | --- | --- |
| 全局冻结使动态循环对象无法回收 | 删除启动、加载、关闭路径的 freeze/unfreeze，保留默认 GC | 真实自引用对象，重复加载、单源关闭、全部关闭后 GC + 弱引用验证 |
| 复用热力图已有 AA 穿过 hold | hold 主动关闭切片 AA，idle/direct 入口遵守 token，释放后结算，清空/销毁重置 | 真实画布从 AA-on 开始；普通释放、重定向、旧 token 释放、150 ms idle 间隔 |
| 延后的 UltraView 预览在源 Section 隐藏后无法更新 | 在隐藏前按现有绑定、稳定性、digest 合同补齐延后预览 | 真实 MainWindow：FFT 换信号重算 → 切到 time → 打开 Board / 保存 sidecar，预览内容更新 |
| 探针漏记热力图 AA | 读取切片实际子曲线 AA；paint 前记录源 Section、hold、过渡阶段与 generation | 指标单测 + 真实 Section 探针，未知 AA 单独计数 |
| 刻度快照绑定某一平台字体 | 同一字体度量下与 `ef63e1e6` 独立参考算法逐项比较 | 336 组输入 × 4 种 DPR；保留 memo 命中与失效检查 |

另修正三个旧项目 pin 测试的前置条件：使用 `ensure_analysis_page_ready("fft")` 后再访问画布。原 `1e672f97` 隔离源码与当前源码均复现相同的 charts-not-ready 失败；业务断言保持原样。

## 聚焦测试

运行环境：项目 `.venv`，`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。

1. 新增缺陷用例先在修改前运行：5 项失败；修正后同组 5 项通过。
2. 核心组合：**530 passed, 1 skipped**（87.55 s）。覆盖以下 owner 和边界：
   - `tests/test_switch_smoothness_metrics.py`
   - `tests/ui/test_gc_freeze_on_load.py`
   - `tests/ui/test_discrete_quality_hold.py`
   - `tests/ui/test_ultraview_capture.py`
   - `tests/ui/test_ultraview_mode_integration.py`
   - `tests/ui/test_analysis_axes.py`
   - `tests/ui/test_pg_heatmap_canvas.py`
   - `tests/ui/test_slice_panel.py`
   - `tests/ui/test_page_transition_integration.py`
   - `tests/ui/test_section_page_transition.py`
   - `tests/ui/test_pg_canvas_backref_invariants.py`
   - `tests/ui/test_main_window_state_ownership.py`
   - `tests/ui/test_import_boundaries.py`
   - `tests/ui/test_no_lambda_signal_connections.py`
3. 启动、项目生命周期和包装导入补充：`test_startup_preload.py`、`test_project_session.py`、`test_ultraview_project_session.py`、`tests/test_packaging_imports.py`：初次 **102 passed, 1 skipped, 3 failed**（30.09 s）。上述三个测试的懒加载前置条件修正后，单独重跑 **3 passed**（1.55 s）。未重复运行已通过且未改动的用例。

最终各聚焦检查合计 635 项通过、2 项跳过，不是一次全套测试的结果。警告来自 pyqtgraph 对 NumPy 数组 shape 赋值的弃用提示。未运行全套测试。

## 真实 Section 切换探针

命令主体：

```sh
.venv/bin/python scripts/probe_switch_smoothness.py \
  --scenario section --reps 2 --win-w 1536 --win-h 824 --out <result.json>
```

每通道 200,000 点；time、FFT、order、FFT-time 的 12 个方向各跑两圈，motion=light。

| 证据环境 | 实际 DPR | 切换数 | 取消 / 超时 | 目标页淡入期间 AA paint | 未知 AA paint |
| --- | --- | --- | --- | --- | --- |
| macOS offscreen，scale=1 | 1.041656 | 24 | 0 | 0 | 0 |
| macOS Cocoa，scale=1.25 | 2.5 | 24 | 0 | 0 | 0 |

两次都实测到热力图淡入 paint，AA 为 false；并非因没有目标页绘制而计数为零。Cocoa 的 12 次热力图淡入 paint 均保持 AA-off。

### 尚未通过的性能目标

- Cocoa 热跑进入 FFT-time 的最大单次 paint 约 183 ms，发生在淡入结束后；离开 FFT-time 的截图仍有约 208–216 ms 的 AA paint。
- Cocoa 热跑最大事件循环间隔约 300 ms。目标页淡入 AA 问题已修正，但原 spec 的整体 ≤100 ms 阻塞目标仍未达成。
- 撤回 freeze 后，GC 停顿问题仍需后续设计。循环可回收性不等于长会话 RSS 验收。
- UltraView 隐藏前补截仍遵守稳定性检查。切走时尚未稳定或仍在计算的源不强制截取；高速打断的恢复行为需另行覆盖，不能据本次稳定重算场景认定所有延后预览均已闭环。
- 本次没有同参数 Cocoa 修改前基线，不报告速度提升百分比；offscreen 与 Cocoa 的比例及字体不同，不互相比较性能。
- 未调整 ink/AA 阈值，未完成切片准入标定、Windows 源码前台或 Full/Lite frozen 验收。Cocoa 探针不等于完整交互与视觉验收。

本机原始结果和运行日志保存在 `.state/switch-smoothness-review/`，不进入 Git。规格与计划已同步撤回 D-I；既有 Windows 优化目标仍按原计划单独验收。
