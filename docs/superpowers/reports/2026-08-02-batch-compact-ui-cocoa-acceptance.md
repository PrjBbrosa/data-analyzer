# 批处理紧凑 UI — macOS Cocoa 前台验收

**日期：** 2026-08-02

**实施分支：** `codex/batch-post-merge-hardening`

**结论：** **NO-GO（验收不完整，未把 macOS 合包状态改为 GO）**

## 已验证的真实前台状态

使用实施 worktree 启动 `PYTHONPATH=. .venv/bin/python -m mf4_analyzer.app`，在真实
macOS Cocoa 前台的 `TraceLab v7.9.1` 中进入“批处理分析”。实际可用显示面为
**1080×760**；下列截图均为该前台窗口所采集的 JPEG，不混入 offscreen probe。

| 状态 | 结果 | 前台事实 | 证据 |
|---|---|---|---|
| Time | PASS | 实际鼠标切换后步骤摘要为“时域 · 每项单独”；频谱参数、dB 参考和幅值单位行均隐藏。 | `/tmp/tracelab-batch-d-cocoa-acceptance/time-method-real-cocoa.jpeg` |
| FFT dB | PASS | dB 参考、频率/幅值轴及独立“幅值单位: dB”行同时可见；输出摘要为 `XLSX · PNG 1920×1080 · 冲突自动编号`。 | `/tmp/tracelab-batch-d-cocoa-acceptance/fft-db-real-cocoa.jpeg` |
| FFT Linear | PASS | 将独立幅值单位切到 `Linear` 后，FFT 行仍可见，方法切换后值能保留。 | `/tmp/tracelab-batch-d-cocoa-acceptance/fft-linear-real-cocoa.jpeg` |
| FFT vs Time | PASS | 摘要切到 `FFT vs Time`；时间/频率轴、幅值单位和色阶行都可见。 | `/tmp/tracelab-batch-d-cocoa-acceptance/fft-vs-time-real-cocoa.jpeg` |
| Order | PASS | 摘要切到“阶次”；RPM 通道、阶次参数、独立幅值单位与色阶行均可见。 | `/tmp/tracelab-batch-d-cocoa-acceptance/order-method-real-cocoa.jpeg` |
| 文件管理 | PASS | 前台 modal 显示 `1 个数据源 · 共同信号 1 个`；临时 `smoke.csv` 已完成 full probe。 | `/tmp/tracelab-batch-d-cocoa-acceptance/file-manager-real-cocoa.jpeg` |

实际点击当前方法行会完整刷新下游；为防止该路径只在程序化 `apply_method()` 下工作，
新增了 `QTest.mouseClick` 回归，断言参数表单、输出坐标上下文和幅值单位行同步刷新。

## 未通过或未能覆盖的项

| 项目 | 状态 | 原因与影响 |
|---|---|---|
| 1440×900 前台矩阵 | GAP | 当前 Cocoa 前台虚拟显示仅提供 1080 像素宽，无法把窗口置于 1440×900 进行真实显示验收。 |
| 1080 信号选择器的真实选择、running、completed footer | GAP | 临时 CSV 已经通过真实文件管理导入；但 Computer Use 的 accessibility bridge 不暴露 `Qt.Popup` 内的信号复选框，坐标点击也不能落入该独立 popup。因此不能诚实地声称完成真实运行态。 |
| 全量 `tests/ui` 连续两次 | FAIL / 未完成 | 第 1 轮在约 10% 后持续占用 CPU；`sample` 显示停在 `QApplication.setStyleSheet()` 的 Qt 样式递归。约 5 分钟后安全终止。此现象与外部 review 的 D7 “全量 UI 时序不稳”同族，C1 专项修复不足以将该门禁标为通过。 |

该前台过程还发现：Accessibility 对可勾选方法按钮的“按元素”操作可能只改视觉选中值而不发出 Qt `clicked`；实际鼠标坐标点击会正常刷新。故本报告的 PASS 方法切换均以实际鼠标坐标为准，而不是该 accessibility 快捷路径。

## 门禁结论

- 合并后紧凑 Batch UI 的 macOS Cocoa：**NO-GO**，原因是 1440×900 与 running/completed 未验证，且完整 UI 稳定性门禁未完成。
- Qt Batch renderer 原有 macOS Gate 4.5：本轮未以本报告替代其独立结论。
- Windows full/lite onedir：**NO-GO**，本轮未执行 Windows gate。

## 可复现前提

前台导入仅使用过本轮创建的非敏感临时数据
`/tmp/tracelab-batch-d-cocoa-acceptance/smoke.csv`；验收结束后该 CSV 已删除。
所有截图仍位于同一临时目录，未加入 Git。
