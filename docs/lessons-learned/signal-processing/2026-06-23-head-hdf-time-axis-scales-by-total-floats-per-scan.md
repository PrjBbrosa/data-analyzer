---
role: signal-processing
tags: [head, hdf, loader, time-axis, sample-rate, fs, raster-factor, per-scan, interleave, scan-period, absolute-scale]
created: 2026-06-23
updated: 2026-06-23
cause: insight
supersedes: []
---

## Context
HEAD HDF v4「synchronised multiple」多采样率文件：abscissa 只给 `delta value` +
`nbr of scans`，头/尾都没有显式采样率。design 当时在两种 delta 读法间猜，落地了
`period = delta × (max_factor / factor)`，并自记「绝对采样率是唯一未确认硬项，须对标
HEAD Companion」。用户实测时间轴明显偏短。

## Lesson
`delta` 是「一个 scan 内所有通道**交织浮点槽**」的间隔，所以一个 scan 跨
`delta × per_scan`（`per_scan` = 每 scan 总浮点数 = Σ 所有通道 factor，**含被丢的
非 FLOAT32 / 全 NaN 通道**——它们仍占二进制槽位）。factor-f 通道采样周期 =
`(delta × per_scan)/factor`、`fs = factor/(delta × per_scan)`。误用 `max_factor`
代替 `per_scan` 会把时长压短 `per_scan/max_factor` 倍、fs 同比偏大（真实文件
259/48 ≈ 5.4×：算成 9.17 s / 129.5 kHz，实为 49.5 s / 48 kHz）。铁证：`delta × per_scan`
恰为整毫秒（1.000 ms）、各栅格 fs 落到 48 / 24 / 1 kHz 标准值；`max_factor` 给的
129.5 / 5.4 kHz 都不是标准率。

## How to apply
HEAD HDF 时间轴/采样率按 `Σfactor`（每 scan 浮点数）缩放，不是 max raster
factor——别被 design 里的 `max_factor` 公式带回去。**自洽于公式的合成测试钉不住
绝对尺度**（旧测试就放过了 5.4× 错误）：必须用 `Σfactor ≠ max_factor` 的合成用例
断言真实「每通道周期 + 跨组总时长」，并对标 HEAD Companion 显示的 fs/时长。同源问题
见 [[head-calibration-is-metadata-not-sample-gain]]（同一 loader 的另一处「系数」翻车）。
