# Batch 0 Contact Sheet 目视签字

**日期：** 2026-08-01

**执行者：** `/root/batch0_spike`（pyqt-ui-engineer）

**查看方式：** `view_image(detail="original")`，逐张打开最终生成文件
**结论：** PASS

| Contact sheet | 结论 | 目视记录 |
|---|---|---|
| `time-dual-y-parity.png` | PASS | batch 使用 pyqtgraph auto-range padding 后复用现有 `_frame_to_nice` 10 分格语义，reference 不写死 Y 范围；机器实测两侧 X 均为 `[0,10]`、Acceleration Y 均为 `[-1,1]`、Speed Y 均为 `[1320,1720]`，绝对容差 `1e-9` 断言通过。蓝/绿双 Y 曲线、左右轴、legend 完整，无漏线、裁切、重叠或默认按钮/chrome。reference 的 live envelope 细节更密，但峰谷与覆盖范围一致，无显示信息丢失。 |
| `time-subplot8-parity.png` | PASS | 8 行均可读、色轮和波形顺序一致、仅底行 X 标签；关闭 auto SI prefix 后两侧均为 `g` 与实际 ±0.5 量级，无文本相交。batch 居中 `Channel n · g` 是 Spec B3 批报告标题，reference 左上内嵌标签是交互 canvas 表现，属于批准的报告层差异。 |
| `fft-parity.png` | PASS | 三个峰的位置、幅值范围、网格/轴与线宽一致；batch/reference 均显示 `Channel` legend，无空图、裁切或默认 chrome。 |
| `heatmap-parity.png` | PASS | 修正后两侧均走 `_SmoothImageItem` bilinear；非对称 2×3 matrix 的四角方向、turbo 色序、extent、`[0,1]` levels 和 colorbar 一致，无转置/翻转/色条裁切。 |
| `all-cases-three-themes.png` | PASS | white/transparent/dark 共 12 个 batch 页面均完整；transparent 棋盘透出正确，dark 轴/文字/曲线可辨；仅含获批图头、facts、绘图区、legend/colorbar、页脚，无导航、toolbar/status、frame、scrollbar 或 focus rect。 |
| `cjk-ink-proof.png` | PASS | `单帧振动加速度` 字形清晰，未见 tofu/空白；空标题对照确实移除标题墨迹，机器差异为 3313 pixels。 |

初版目视曾发现并修复三个 Spike 自身问题：heatmap 使用 nearest 而 reference 使用
bilinear、FFT batch 缺少 `Channel` legend、subplot 左轴误启 auto SI prefix。后续原图
复核又发现 dual-Y batch 手写范围与 single-file 自动量程/刻度显示不一致；现已删除手写
范围，加入 batch/reference X/Y 数值硬断言并完整重生成。最终签字基于这些修正后的六张
contact sheet 逐张以 original detail 重新打开，不沿用旧图或旧 evidence 判断。
