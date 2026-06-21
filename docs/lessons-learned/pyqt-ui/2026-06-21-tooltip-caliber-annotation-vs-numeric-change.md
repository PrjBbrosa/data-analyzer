---
role: pyqt-ui
tags: [tooltip, caliber, welch, rms, characterization-test, user-facing-text]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

## Context

FFT 线图的"线性平均"（Welch）比"单帧/峰值保持"约低 3 dB（RMS vs 峰值口径），
用户切换平均模式时幅值跳变易困惑。数值两种归一化都正确，不宜改算法。

## Lesson

算法口径差异（如 RMS vs 峰值）应通过 tooltip / 就近说明向用户解释，而不是
改变数值——改数值会破坏物理含义（功率谱的能量等价性）。
Characterization test 应钉住实测 dB 偏移（不是 "amp != 0" 这种弱断言），
这样未来无声的归一化漂移立即可被发现。
tooltip 验证用 `widget.toolTip()` 读取实际属性（offscreen QApp），
而不是凭"setToolTip 调用在代码里"来判断——两者行为可能不同。

## How to apply

遇到"两种归一化都正确但用户会困惑"的场景：优先 tooltip 标注，不改数值。
写 characterization test 时断言具体数值（如 -3.01 dB ± 0.3 dB），
并在 tooltip 测试中直接读 `toolTip()` 属性而非检查源码。
