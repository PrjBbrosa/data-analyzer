---
id: switch-optimization-retained-hidden-lifecycle
status: active
owners: [codex]
keywords: [switch, retained, heatmap, AA, UltraView, deferred, GC]
paths: [mf4_analyzer/ui/pg_canvas/slice_panel.py, mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py, scripts/probe_switch_smoothness.py]
checks: []
tests: [tests/ui/test_discrete_quality_hold.py, tests/ui/test_ultraview_mode_integration.py, tests/ui/test_gc_freeze_on_load.py, tests/test_switch_smoothness_metrics.py]
---

# 切换优化要验证复用和隐藏后的生命周期

Trigger: 修改页面保留揭示、AA 延后结算、隐藏预览或 GC 性能优化时。

Past failure: 仅停止待触发的 timer 漏掉了已开启 AA 的复用热力图；把预览留到 Board 显示时才截，却在此前隐藏了源画布；mock GC 调用次数未发现 freeze 后循环垃圾无法回收。探针读错热力图 AA 字段又把漏测记为无成本。

Rule: 用真实 owner 走完“已稳定 → 复用 → 重定向/释放”和“内容变化 → 隐藏源 → 打开/保存”的组合路径。性能计数读取实际绘制对象，区分源截图、目标淡入与未知状态；GC 优化同时证明循环对象可回收。独立方法的 mock 调用数不能替代这些证据。

Verification: 上述聚焦测试；`scripts/probe_switch_smoothness.py --scenario section --reps 2` 的 held/phase/AA 原始记录。offscreen、Cocoa、Windows 源码与 frozen 证据分别报告，不以减少计数替代生命周期正确性。
