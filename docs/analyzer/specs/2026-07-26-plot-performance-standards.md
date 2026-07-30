# TraceLab Plot 性能准则

日期：2026-07-26
适用：TimeDomainCanvasPG；FFT/Order/Orbit 等 plot 先遵守通用层，增加各自场景后
才能声明专项达标。
基准入口：`scripts/benchmark_timedomain_interaction.py`

## 1. 目的

后续功能更新不能再以“算法快了”“离屏测试绿了”代替真实交互体验。本准则把
输入回调、强制首帧 paint、连续交互帧、quiet settle 和数据加载分开测量，并
同时设置确定性守门与真机时间守门。

## 2. 标准场景 TD-HDF-6

- 6 条普通连续物理量；
- 每条 1,188,000 个 float64 样本，共享一条单调时间轴；
- subplot，1900×1100 logical px，记录实际 DPR；
- 49.5 s 数据，20% X 窗口；
- 10 次 pan、10 次 resize、至少 8 次 warm hide/restore；
- 默认 deterministic synthetic；release candidate 追加真实 HEAD HDF；
- Cocoa 使用前台平台插件，禁止 `offscreen` 冒充 macOS live；
- Windows 发布包必须由 EXE 运行等价场景，Python 源码结果不能替代。

## 3. 指标定义

| 指标 | 起止点 | 不包含 |
|---|---|---|
| HDF parse | 调用 loader 至数据组返回 | Qt 建图 |
| initial plot | `plot_channels` 开始至一次 `viewport.repaint()` 完成 | 文件解析 |
| checkbox callback | delta API 进入至返回 | 后续 Qt paint |
| checkbox paint | callback 返回至强制 viewport repaint 完成 | 数据组装 |
| pan interactive frame | held gesture 的 range mutation 至强制 repaint 完成 | release settle |
| pan settle | release 后最终 envelope/setData/paint 完成 | held frames |
| resize interactive frame | resize mutation 至强制 repaint 完成 | quiet settle |
| resize settle | 最后 resize 后 layout/data/paint 完成 | 中间 resize frames |

报告必须输出 p50、p95、max 和原始 samples；少于 8 个有效样本不能用于发布结论。

## 4. 确定性硬门禁（普通 CI）

1. 同一 plot generation 内，每个唯一 raw X array 最多 finite-bound scan 一次；
2. buffer 内 held pan 的中间 `PlotDataItem.setData()` 为 0；
3. resize burst 的 data/layout settle 只发生在最后事件后且只发生一次；
4. 普通 subplot 的非空→非空 warm hide/restore（变更前后至少一行 active）不创建或销毁未变化的 PlotItem/ViewBox；
5. append 一个兼容通道只新增一个 PlotItem/ViewBox；
6. 非空→非空时，hidden row 高度为 0，re-show 复用原 PDI、ViewBox、颜色和 X/cursor state；
7. 普通 subplot 进入 zero-active 时必须转为 canonical empty render model；下一次 non-empty 必须 full rebuild，并在不改变外层窗口尺寸的前提下通过 shown-canvas sceneBoundingRect 几何门禁（`test_subplot_empty_view_round_trip_rebuilds_full_canvas_geometry`、`test_all_subplot_eyes_hidden_then_reopened_rebuilds_full_geometry`、`test_all_subplots_unchecked_then_rechecked_rebuilds_full_geometry`）；
8. 几何不可观测（canvas 未 shown 或 viewport 尺寸非正）时跳过该门禁并保留 warm path，不得降级为永久 full rebuild（`test_subplot_hidden_canvas_keeps_warm_path_without_geometry_check`）；
9. dense-discrete/CRC raw/display、DPR、AA hard gate 和内存 fallback 全部保留；
10. complex topology 必须显式 fallback reason，禁止静默半增量。

任一失败即阻断，不允许用时间数值更快来豁免正确性。

## 5. macOS Cocoa 参考机时间门禁

TD-HDF-6、1900×1100、当前开发机：

| 指标 | PASS 上限 | 说明 |
|---|---:|---|
| initial plot | 1300 ms | 1200 ms 为目标；冷建六行并完成首帧 |
| pan interactive p95 | 120 ms | 85 ms 为目标、100 ms 为预警、120 ms 为硬线 |
| pan settle | 150 ms | 松手后的唯一最终帧 |
| resize interactive p95 | 300 ms | Cocoa layout/paint 也计入 |
| resize settle | 250 ms | 最终尺寸的一次收口 |
| warm checkbox callback p95 | 30 ms | UI 线程必须快速归还控制 |
| warm checkbox paint p95 | 220 ms | 复用对象后的真实重绘 |

此外，任何单次 stall `>500 ms` 直接 FAIL；它比 p95 更接近“转圈”的用户故障。

## 6. 相对回退门禁

同一机器、同一平台插件、同一 DPR/尺寸、同一数据的 accepted baseline 上：

- 任一核心指标恶化超过 20% 即 FAIL，即使仍低于绝对上限；
- 改善某一指标不能抵消另一指标的回退；
- 需至少三次完整运行，使用三次 p95 的中位数做版本比较；
- 系统处于明显热降频或后台高负载时该轮标记 invalid，不挑选最好的一轮。

## 7. Windows 与其他 plot

Windows packaged EXE 首次建立 baseline 前状态为 `Windows pending`。建立后沿用
20% 相对回退门禁和 500 ms stall 硬门禁；不能直接复制 Cocoa 的绝对值。

FFT/Order/Orbit/Heatmap 必须各自补充真实输入、尺寸和操作序列。没有专项场景时，
至少遵守：输入 callback p95 `<50 ms`、held interaction 不做重复全数据计算、
同机器回退 `<20%`、单次 stall `<500 ms`。

## 8. JSON 证据

每次 release benchmark 保存：commit、平台插件、系统/架构、Python/Qt/
pyqtgraph、DPR、画布尺寸、通道/样本数、输入来源、每个阶段的 p50/p95/max/raw
samples，以及 raw-X scan、held-pan setData、bound/active PlotItem 计数。

不提交真实客户 HDF；可提交 synthetic JSON 和经脱敏的真实文件结果摘要。

## 9. 2026-07-26 Accepted Cocoa Reference

本准则的初始 accepted reference 来自真实 `TD-HDF-6`（Cocoa、1900×1100、DPR
记录于 JSON）：initial plot `981.5 ms`、held-pan p95 `84.5 ms`、pan settle
`119.2 ms`、resize p95 `128.5 ms`、resize settle `120.7 ms`、warm callback p95
`13.1 ms`、warm paint p95 `101.0 ms`。同一 run 的 raw-X scans 为 `1`、held-pan
`setData` 为 `0`。

后续版本比较必须保存完整 JSON，并以至少三轮完整 run 的 p95 中位数应用第 6 节的
20% 回退门禁；不得只选择这一轮最优数字。Windows packaged EXE 在建立自己的 accepted
baseline 前仍为 `pending`。
