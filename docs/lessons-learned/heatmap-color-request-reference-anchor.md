---
id: heatmap-color-request-reference-anchor
status: active
owners: [codex]
keywords: [heatmap, colorbar, reference, view, projection]
paths: [mf4_analyzer/ui/heatmap_color_coordinator.py, mf4_analyzer/heatmap_color_policy.py, mf4_analyzer/ui/analysis_view_bridge.py]
checks: []
tests: [tests/ui/test_heatmap_color_state_integration.py, tests/ui/test_heatmap_color_coordinator.py]
---

# 热图色阶必须从所属请求及稳定参考基准推导

Trigger: 手动热图色阶随 View 切换、reference、分屏锁定、保存或图表还原发生改变。

Past failure: 复用画布的上一次 reference 被用于解释另一个 View 的手动色阶；渲染再把派生数字写入共享 Inspector，下一次 capture 将其持久化。两 View 参考值相差 30 dB 时每轮继续累积，双 pane 还会逐个重复平移。

Rule: 请求属于 View/pane，reference 基准随同一来源意图保存；有效范围是纯投影。blockSignals 不能防主动 capture。真实编辑必须固定 owner，程序投影和无 Z 预设不得提交 Z。锁定 union 是呈现覆盖；还原图表设置必须恢复 opening 请求作用域和基准，而不只恢复当时显示数字。

Verification: 参数化真实 MainWindow 时频/阶次，20 次 View 往返、反向 pane 绘制、reference 1→10→1、项目保存重开、Apply→Restore、非 Z 预设，断言请求/基准/图像/色条/切片及原数组；使用 test_heatmap_color_state_integration.py 与 test_heatmap_color_coordinator.py。裸 canvas 历史 API 和正式 resolved API 分别测试。
