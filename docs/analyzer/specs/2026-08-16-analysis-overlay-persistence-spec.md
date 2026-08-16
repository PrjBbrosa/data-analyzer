# 分析区点标注与频率双游标工程持久化

- 日期：2026-08-16
- 状态：**实施中**
- 基线：时域标注/游标已落地（`2026-08-16-view-markup-and-cursor-persistence-spec.md`）。
  原 spec D9 把分析区标为不做；产品要求凡有标注按钮的分析区（FFT /
  FFT vs Time / 阶次 / 频响）与频率双游标都要随工程保存。

## 0. 一句话

分析画布上的点标注和 FFT/FRF 频率双游标 A/B 落点是每个分析 View **pane**
的用户内容，进 `.tlproj`，打开后按复合通道身份重绑。标注工具开关、单游标
hover、pill HTML 仍不进工程。

## 1. 契约

| 内容 | 归属 | 重开后 |
|---|---|---|
| 点标注（通道、数据坐标、标签偏移、panel） | 每个分析 pane | 绑到该 pane 重算后仍存在的曲线/矩阵 |
| 频率双游标 A/B（Hz） | FFT / FRF pane | `cursor_mode=="dual"` 时重画竖线并重算读数 |
| `cursor_mode` | 已有 | 行为不变 |

Heatmap（FFT vs Time / 阶次）没有频率双游标，只存标注。

JSON 形状复用时域 D2/D3，分析多一个 `panel`：

- FFT：`amp` / `time`
- 热图：`heatmap`
- FRF：`magnitude` / `phase` / `coherence`

`x` 对 FFT/FRF 是物理 Hz（或时域预览的秒）；热图是时间/阶次 × 频率。恢复时按
当前结果对 `x` 做最近采样吸附，**用吸附后的 y/z**。

## 2. 设计

- `PaneState.remarks` / `cursor_placement`；分析 schema 8。顶层 `.tlproj`
  schema 仍为 2。旧工程缺字段 = 空标注、无落点。
- 三个分析画布持有 `AnalysisRemarkStore` 意图列表。`plot_spectra` /
  `set_result` / `plot_or_update_heatmap` 只丢 Qt 投影，收口再投影。
  `clear_remarks()` 与 `full_reset()` 仍是用户/关文件全清。
- `set_cursor_mode` 不销毁 A/B 频率；`restore_cursor_placement(None)` 清空。
- `remap_analysis_view_fids` 改写 `remarks[].source[0]`；落点无 fid。
- 从未打开过的分析节，保存时不拿空画布覆盖已反序列化的 pane overlay。

## 3. 明确仍不做

- pill mini/full 与拖位
- `annotation_enabled`
- 截图编辑器 `ui/markup/`
- UltraView 板级便签/箭头
