# HDF 时间域交互性能回退分析报告

日期：2026-07-26
状态：已完成（macOS Cocoa 真实 HDF 已验证；Windows packaged EXE 待验证）。
复现文件：`260417-ripple-PK2C-电机加热-1.hdf`

## 1. 结论

当前 v7.8 的卡顿不是 HDF 解析退化，而是绘图交互热路径的组合回退：

1. `5a565fcf` 引入 25% buffer/coarse/settle 后，原本只在建图和 Home
   使用的 `_data_x_union()` 进入每次 settled/coarse 平移与缩放；
2. 六条 HDF 通道共享同一条 1,188,000 点时间轴，当前实现却对每条通道重复
   `isfinite`、复制有限值、`min/max`；
3. 六条连续物理量被分类为 `general`，不会进入现有 dense-discrete 缓存位图，
   交互质量切换又会清除 native curve cache，导致每帧重新绘制六条矢量 envelope；
4. 6 月的 resize 优化只延后标签/轴重排 40 ms。当一次 repaint 本身超过
   40 ms 时，timer 会在拖动尚未结束时触发，随后又进入 buffer 和原始 X 扫描；
5. 7 月 23 日方案要求通道 add/remove delta，但当前多分屏增减通道仍明确回退
   `subplot-topology-change -> clear() -> plot_channels()`，所以每次勾选都重建轴、
   标签、ViewBox 和曲线对象。

最优方案不是回退 v7.8，也不是全局降低绘图质量，而是分层消除热路径：

- 把不可变原始 X 范围提升为 plot-generation 缓存；
- 把 resize 改成真正的静默窗口，拖动期间不运行 data/tick/layout settle；
- 保留连续 HDF 的 native vector 路径：实测把它直接套进 dense-discrete 位图后端
  会让六张 DPR2 pixmap 的合成成为新瓶颈，不能以更差的方案替换原路径；
- 分屏通道增减复用既有 PlotItem/ViewBox，折叠/恢复旧行，新增行只建一个对象；
- 以确定性调用次数守门 CI，以真实 Cocoa `viewport.repaint()` 守门用户体验。

## 2. 证据范围

### 2.1 真实数据

- 24 kHz raster；49.50 s；每个通道 1,188,000 点；
- 复现选择：`L`、`R`、`MOTOR Y`、`MOTOR X`、`输出轴 z`、`输出轴 y`；
- 文件约 49 MiB，为 HEAD acoustics hybrid ASCII/binary HDF，不是 HDF5。

### 2.2 同文件、隔离源码的历史 Cocoa 对比

| 版本 | 六通道建图 | 平移 p50 / p95 | resize p50 / p95 |
|---|---:|---:|---:|
| v7.5 | 814 ms | 184 / 195 ms | 214 / 251 ms |
| v7.6 | 766 ms | 178 / 195 ms | 224 / 277 ms |
| v7.7 | 747 ms | 182 / 197 ms | 226 / 320 ms |
| `014513b6`（5a 前） | 748 ms | 182 / 195 ms | 223 / 267 ms |
| 当前 v7.8 | 804 ms | 213 / 222 ms | 271 / 296 ms |

绝对值受机器负载影响，不能单独作为发布判据；相同数据、相同机器、隔离源码下
的相对变化证明用户对 v7.5/v7.6 更顺滑的记忆有代码和测量依据。

### 2.3 热点归因

- 纯 HDF parse 约 0.26 s，未出现近期回退；
- 八个 settled pan window：v7.5/v7.6/v7.7/5a 前的
  `_data_x_union()` 调用均为 0，当前为 8 次，隔离探针累计约 280 ms；
- 八个 resize step：历史版本调用 0 次，当前调用 4 次，约 137 ms；
- 当前六通道初始建图 cProfile 约 0.827 s，其中 `_add_plot_item` 约
  0.358 s、`_bind_channel` 约 0.240 s、label/QTextDocument 约 0.16 s；
- 当前八帧 pan 中 paint 约 0.522 s、`drawLines` 约 0.318 s；
- 当前五帧 resize 中 paint 约 0.467 s、`drawLines` 约 0.211 s，
  axes/ticks 约 0.160 s。

## 3. 为什么旧优化没有兜住

### 3.1 resize 旧优化存在，但边界不完整

`816c2083` 已把标签和轴重排放到 40 ms 单次 timer；这解决了“每个 resize
event 重建标签”，没有解决“单帧 paint 已慢于 timer 窗口”。当前
`_on_resize_settled()` 又启动 100 ms data settle，形成 resize → 40 ms →
data settle → idle AA 的多级链，并可能与还在发生的 resize 交错。

### 3.2 X 范围以前不需要缓存，因为以前不在交互热路径

`_data_x_union()` 早已存在，但 5a 前只服务初始建图和 Home，缓存收益有限。
25% buffer 把它变为每次 coarse/settled 刷新的前置条件后，原实现的 O(通道数 ×
样本数) 才成为交互级回退。

### 3.3 CRC 位图优化没有覆盖连续 HDF

现有 `DenseDiscreteRasterLayer` 的 raw/display 分离、DPR、内存上限、generation
失效和 native fallback 都是正确资产，但候选仅限 `dense_discrete`。HDF 连续
通道虽有百万原始点，profile 仍是 `general`，所以只能走 native vector paint。

### 3.4 selection delta 是计划目标，不是当前事实

单通道 hide/re-show 已保留对象；多分屏 active set 变化却被当前代码主动拒绝。
因此“7 月 23 日已有 delta 方案”不能作为勾选不卡的完成证据。

## 4. 方案比较

| 方案 | 收益 | 风险 | 结论 |
|---|---|---|---|
| 回退 5a/7.8 renderer | 快速恢复部分历史路径 | 丢失 CRC、buffer、generation 修复 | 不采用 |
| 只缓存 `_data_x_union` | 去掉明确的 20–35 ms/次扫描 | 不能消除六行 vector paint 和全量建图 | 必做但不充分 |
| 全局降低 envelope/关闭 AA | 易实现 | 牺牲普通曲线外观，仍有轴/对象重建 | 不采用 |
| 所有 general 曲线都转位图 | 平移便宜 | 过度扩大语义、内存和画质风险 | 不采用 |
| 条件化 dense-continuous 位图 | 理论上可复用成熟后端 | 六张 DPR2 pixmap 合成比 native vector 更慢 | 已实测否决，不采用 |
| 分屏对象复用/行折叠 | 直接消除全图 clear/rebuild | overlay/axis-group/companion 更复杂 | 先覆盖普通分屏，复杂拓扑显式 fallback |
| GPU/新绘图库 | 潜在上限高 | 跨平台和发布风险大、周期长 | 本轮不采用 |

## 5. 执行边界

本轮覆盖普通 HDF 分屏、单轴线性连续信号、现有 dense-discrete/CRC 回归。
overlay、log 轴、axis-group 结构变化、filter companion 结构变化保留显式 full
rebuild fallback，不用不完整的增量逻辑冒充通用支持。

不改变：原始数据、时间/单位、cursor/stat/FFT/filter/export 数据源、通道顺序、
颜色、保存 View 语义和 BLF/CRC 的 raster/AA/DPR 规则。

## 6. 发布判定

最终必须同时满足：

- 确定性：同一 plot generation 内 raw-X 每个唯一时间数组最多扫描一次，之后
  pan/resize 为 0 次；
- 行为：普通分屏增减一个通道不销毁未变化 PDI/ViewBox；
- 数据：raw array identity/长度、cursor/stat/export 仍来自原数组；
- 用户体验：真实 Cocoa 的六通道 continuous pan、resize、warm checkbox 达到
  配套性能准则；
- 兼容：dense-discrete 专项与 focused time-domain suite 全绿；
- 证据边界：macOS 前台、Qt offscreen、Windows packaged EXE 分开报告。

## 7. 修复后结果

### 7.1 已实施的最优组合

1. 原始 X 的 finite bounds 以 array fingerprint 在一个 plot generation 内缓存；
   共享时间轴只扫描一次，pan/resize 不会再次扫描。数据重绑、clear 或真实 source
   revision 才失效。
2. resize 改为 150 ms quiet window：每次 event 都停止旧 coarse/refresh，最后一次
   才做一次 label/tick/layout/data settle，不再启动第二层 data timer。
3. 普通、无 group/companion 的 subplot 使用 retained rows：取消选择时行高折叠为 0，
   恢复时复用同一 PlotItem/ViewBox；末尾新增只新建一行。中间插入、overlay、
   axis group、companion 等复杂拓扑仍返回明确 fallback reason。

### 7.2 被否决的候选

曾把六条 `general` 连续曲线接入 dense-discrete raster 的 DPR-aware pixmap 路径。
真实 HDF/Cocoa 测量显示其 held-pan p50/p95 为 `176.6/179.9 ms`、resize p50/p95
为 `271.4/359.8 ms`，比 native vector 的对应探针慢；瓶颈是六张 DPR2 image 的
组合而非曲线对象本身。因此该实验代码已完全撤回，并有负向回归测试确保普通连续
曲线不意外进入该后端。

### 7.3 最终门禁运行

命令：

```bash
.venv/bin/python scripts/benchmark_timedomain_interaction.py \
  --hdf '/Users/donghang/Downloads/260417-ripple-PK2C-电机加热-1.hdf' \
  --channels 'L,R,MOTOR Y,MOTOR X,输出轴 z,输出轴 y' \
  --assert-standards
```

真实 HDF、1900×1100、Cocoa、六行、1,188,000 samples/row 的通过结果：

| 指标 | 实测 | 准则 | 判定 |
|---|---:|---:|---|
| initial plot | 981.5 ms | ≤1300 ms | PASS |
| held pan p50 / p95 / max | 74.8 / 84.5 / 86.2 ms | p95 ≤120 ms | PASS（达到 85 ms 目标） |
| pan settle | 119.2 ms | ≤150 ms | PASS |
| resize p50 / p95 / max | 125.5 / 128.5 / 128.6 ms | p95 ≤300 ms | PASS |
| resize settle | 120.7 ms | ≤250 ms | PASS |
| warm checkbox callback p50 / p95 | 12.2 / 13.1 ms | p95 ≤30 ms | PASS |
| warm checkbox paint p50 / p95 | 99.5 / 101.0 ms | p95 ≤220 ms | PASS |
| raw-X scan / held-pan `setData` | 1 / 0 | 1 / 0 | PASS |

专项回归：hotpath `16 passed`、dense-raster `23 passed`、完整 pg-canvas
`362 passed, 1 deselected`。这证明源码与真实 Cocoa canvas 达标；未运行 Windows
打包 EXE，因此 Windows 状态仍为 `pending`，不能据此宣称跨平台发布完成。
