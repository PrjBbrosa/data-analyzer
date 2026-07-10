# 采集 Cockpit 实时曲线坐标与连线渲染对标报告

- 日期：2026-07-09
- 范围：采集 Cockpit 中心实时卡片、坐标显示、当前区间自动坐标、
  连线渲染，以及对标 CANape 采集数据时的显示能力。
- 模式：只做分析和报告，不改源代码。
- 本地证据：
  - `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
  - `mf4_analyzer/acquisition_ui/widgets/live_downsampler.py`
  - `mf4_analyzer/acquisition_ui/main_window/window.py`
  - `mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py`
  - `tests/acquisition_ui/test_live_cards.py`
  - `tests/acquisition_ui/test_pinned_monitoring.py`
  - `scripts/cockpit_ui_tour.py`
- CANape 对标资料：
  - Vector CANape Product Information：
    https://cdn.vector.com/cms/content/products/canape/Docs/CANape_ProductInformation_EN.pdf
  - Vector CANape Version History：
    https://cdn.vector.com/cms/content/products/canape/Docs/CANape_VersionHistory_EN.pdf

## 结论

你提出的三个方向都可行，而且是当前采集 Cockpit 最应该补的显示层能力：

1. 增加坐标显示。
2. 当前可见区间自动设定 x/y 坐标。
3. 把现在偏“点状/竖线”的 sparkline 改成连续连线渲染。

当前采集链路已经能把 idle 和 recording 的样本推到中心卡片，默认只实时显示 5
个固定通道，其他通道仍会录制。也就是说，下一步主要不是改采集核心，而是改曲线
可读性。

建议分两层做：

- 小卡片层：轻量坐标、自动区间、连续曲线、窗口标签、stale 状态。
- 聚焦大图层：对标 CANape Graphic Window，做游标、暂停、缩放、手动坐标、
  少量通道叠加、事件标记。

不要把每张小卡片都做成完整 CANape 图窗。那样信息密度太高，会把采集 Cockpit
从“快速监控”变成“拥挤分析页”。

## 当前实现事实

### 已经具备的能力

中心区域由 `LiveCardGrid` 和 `LiveSignalCard` 组成。每张卡片里有一个
`Sparkline`。当前实现有几个重要保护：

- 每张卡片最多保留 `_SPARK_MAX_POINTS = 4096` 个样本。
- `Sparkline.paintEvent()` 按控件宽度做 min/max downsample。
- UI 刷新不是按每个样本刷新，而是由 timer 限频。
- 默认只实时显示 `DEFAULT_LIVE_PIN_COUNT = 5` 个通道。
- 多选通道仍然进入录制配置，不因为未显示而丢录。

录制路径也已经接上实时显示。`CaptureController` 构造时传入
`sample_tap=self._on_capture_samples`，录制轮询时先把新样本 tap 给 UI，然后再进
ring/writer。因此“边采集边看趋势”不是 demo 假象。

### 当前曲线为什么像点线

截图中曲线看起来像点状，不一定是数据断了，而是当前 painter 的绘制方式造成的。

当前逻辑是：

1. 画浅色网格线。
2. 把 buffer 降采样成每个像素列一个 `(min, max)`。
3. 如果某列 `min == max`，画一个点。
4. 如果某列 `min != max`，画一根竖线。

它没有把相邻采样点或 bucket 连接成折线。所以在低密度或规则波形下，就会显得像
一串点，而不是连续曲线。

这个问题可以局部修在 `Sparkline`，不需要动 XCP/Vector 后端、MF4 writer 或
状态机。

### 当前坐标显示缺口

现在只有网格，没有坐标文本。用户看不到：

- 当前显示的是最近几秒。
- x 轴范围是 `0-10s`、`last 30s` 还是 buffer 保留范围。
- y 轴的 min/max 是多少。
- 坐标是自动还是固定。
- 当前波形是否因为 buffer 滚动而只显示最近一段。

还有一个必须提前修正的语义点：当前录制态 stats 文案偏向“since rec start”，但
底层 sparkline buffer 仍然最多 4096 点。对于 1 ms 通道，这只相当于约 4.1 秒的
原始样本。加坐标后，这个问题会被放大。所以坐标显示必须诚实表达“当前可见窗口”，
不要暗示小卡片显示了完整录制过程。

## CANape 对标理解

根据 Vector 官方资料，CANape 的采集显示不只是画线，还包括一组工程分析能力：

- 时间同步实时采集，并写入 MDF/MF4。
- 测量数据可在多种 display window 中查看。
- 支持 signal-over-time 和 X/Y 表示。
- 支持 zoom、search、measurement marker。
- Graphic window 中有 measurement cursor，并能显示 marker 的精确时间。
- 可以自动适配 time/value axes。
- 大曲线和 envelope 显示做过性能优化，避免阻塞应用。

对我们的意义：

- 小卡片先做到“看得懂、不卡、坐标准确”。
- CANape 式的 cursor/zoom/manual axis 不适合塞进每张小卡片。
- 这些能力应该放进一个“聚焦查看”大图。

## 需求拆解

### 1. 增加坐标显示

可行性：高。风险：低到中。

建议小卡片显示：

- x 轴窗口标签：例如 `last 10 s`、`last 30 s`、`0.0-12.4 s`。
- y 轴 2 到 3 个刻度：顶部、中部、底部。
- header 保留当前值、单位、raster。
- 坐标文本尽量轻，不要抢信号名和当前值的位置。

不建议在小卡片里放完整外框坐标轴和密集 tick。五张卡片同时显示时，密集坐标会
让界面变乱。

实现建议：

- 增加一个轻量 scale helper，例如 `SparklineScale`。
- 输入当前可见 samples/bins，输出：
  - `x_min`
  - `x_max`
  - `y_min`
  - `y_max`
  - `y_ticks`
  - `x_label`
- y 轴自动加 5% 到 10% padding。
- tick 用 nice number，不直接显示原始浮点极值。
- 常值信号要给最小 y span，避免坐标塌成一条线。

验收点：

- 1 ms 通道能看清当前窗口长度。
- 常值信号也有合理 y 轴范围。
- 960 px 窄窗口下，信号名和当前值不被坐标挤掉。

### 2. 自动设定当前区间坐标

可行性：高。风险：中。

风险点不是算 min/max，而是自动 y 轴容易抖。每帧都按精确 min/max 改坐标，会让
曲线视觉上跳动。

建议策略：

- x 轴按明确的可见时间窗定义，而不是按 4096 点 buffer 暗含定义。
- 默认窗口建议先用 `10 s` 或 `30 s`，后续加切换。
- y 轴按当前可见窗口自动 fit。
- y 轴加 padding 和 rounded ticks。
- 可选 hysteresis：只有新值越界或范围变化明显时才扩/缩坐标。

小卡片推荐默认展示“最近窗口”，即使在 recording 也一样。完整录制时长、总样本数、
写入数放在状态栏和复盘弹窗，不要让小卡片承担完整录制趋势图职责。

### 3. 增加连线渲染

可行性：高。风险：低。

建议采用混合渲染：

| 数据密度 | 渲染策略 |
| --- | --- |
| `samples <= 2 * width` | 用原始样本画连续 `QPainterPath` 或 polyline |
| `samples > 2 * width` | 保留 min/max envelope，同时画一条 representative line |
| 有明显断点或 stale | path 断开，不跨断点强行插值 |

这样既能解决截图里的点状曲线，又不会在高采样率下把所有 raw samples 都硬画出来。

小卡片不必立刻换 pyqtgraph。当前 `QPainter` 路线更轻，改动面更小。pyqtgraph 更适合
后面的聚焦大图。

## 其他真实需要的显示功能

### P0：可见窗口说明

加坐标时必须同时告诉用户当前曲线代表哪个窗口。

示例：

- `last 10 s`
- `0.0-8.3 s`
- `visible 4096 samples`

这能避免把 bounded buffer 误读成完整录制。

### P0：每卡 stale/no-data 状态

采集时很容易遇到某个信号不再刷新。没有状态提示时，用户分不清：

- 信号真实恒定；
- ECU/DAQ 没再发；
- 后端断流；
- UI 暂停。

建议每张卡有轻量状态：

- 正常：显示曲线和当前值。
- stale：显示最后值，同时标 `stale 1.8 s`。
- no samples：显示 `无样本`。

### P1：暂停显示，不暂停录制

这很接近真实 CANape 使用习惯。用户看到异常瞬间后，希望冻结画面看数值，但录制不
应该停。

建议：

- `Pause View` 只冻结 UI buffer 和 cursor。
- 后端继续采集，MF4 继续写。
- 恢复后回到最新窗口。

### P1：游标和差值读数

这是从“看趋势”变成“能诊断”的关键。

Focus View 应支持：

- 当前 cursor 时间。
- 当前通道值。
- 双 cursor 的 `dt` 和 `dy`。
- 当前采样点 timestamp。

这个功能放小卡片会太挤，应放聚焦大图。

### P1：手动 y 轴锁定

自动坐标适合第一次看，但工程师经常要固定 y 轴对比前后变化。

建议：

- 小卡片先自动。
- Focus View 增加 `Auto Y` toggle 和手动 `min/max`。

### P1：单位感知的叠加

CANape 常见多信号叠加，但不是所有通道都适合共轴。

建议：

- 同单位：允许共享 y 轴。
- 混合单位：使用归一化显示，或者分轴。
- boolean/status：做数字/阶梯 lanes，不要当普通模拟曲线。

### P2：事件和段标记

采集中如果有 segment marker 或用户注释，应在 Focus View 里显示竖线标记。这样
复盘时能快速找到“打方向、过坎、异常声响”等时刻。

### P2：布局和监控配置持久化

建议记住：

- pinned live channels；
- 当前 time window；
- Focus View 的 axis 模式；
- 常用 overlay 组合。

这会让日常采集更像 CANape 工程配置，而不是每次重新摆界面。

## 可行性矩阵

| 功能 | 价值 | 复杂度 | 风险 | 建议阶段 |
| --- | --- | --- | --- | --- |
| 连续连线渲染 | 高 | 低 | 低 | P0 |
| 小卡片坐标标签 | 高 | 低到中 | 中 | P0 |
| 可见窗口说明 | 高 | 低 | 低 | P0 |
| stale/no-data 状态 | 高 | 低到中 | 低 | P0/P1 |
| time window 切换 | 高 | 中 | 中 | P1 |
| 暂停显示 | 高 | 中 | 中 | P1 |
| Focus View 大图 | 高 | 中 | 中 | P1 |
| cursor/delta 读数 | 高 | 中 | 中 | P1 |
| 手动坐标锁定 | 中到高 | 中 | 中 | P1 |
| pinned 通道叠加 | 中到高 | 中到高 | 中 | P1/P2 |
| 事件/段标记 | 中 | 中 | 低到中 | P2 |
| CANape 式布局持久化 | 中 | 中 | 中 | P2 |

## 推荐实施顺序

### Phase A：先修小卡片可读性

可能涉及文件：

- `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- `mf4_analyzer/acquisition_ui/widgets/live_downsampler.py`
- `tests/acquisition_ui/test_live_cards.py`
- `scripts/cockpit_ui_tour.py`

任务：

1. 提取 sparkline scale/tick helper。
2. 绘制 x/y 坐标标签。
3. 低密度样本改成连续 path。
4. 高密度样本保留 min/max envelope。
5. 增加 helper 测试和渲染测试。
6. 跑 acquisition UI focused tests 和 cockpit tour。

### Phase B：定义 live window 语义

任务：

1. 明确小卡片默认时间窗，比如 `10 s` 或 `30 s`。
2. 修正 recording 小卡片“since rec start”的误导风险。
3. 显示当前 visible window。
4. 累计录制事实继续放状态栏、右栏、复盘弹窗。

### Phase C：增加 Focus View

任务：

1. 用 pyqtgraph 做大图，不替换小卡片。
2. 支持 cursor、time window、auto/manual y、pause。
3. 支持 2 到 4 个 pinned 通道叠加。
4. 用 offscreen 测试和截图 tour 验证。

## 性能判断

当前设计有几个对抗卡顿的基础：

- 正常 30 fps，压力高时降到 10 fps。
- 默认只显示 5 张实时卡。
- 每张卡 buffer 有上限。
- downsample 按像素宽度而不是按样本数画。

坐标标签本身很便宜。连续连线也不贵，前提是低密度画 raw path，高密度仍走 envelope。

真正要避免的是：

- 高采样率下逐点画所有 raw samples。
- 每帧 y 轴精确 min/max 导致视觉抖动。
- 把 cursor、zoom、manual axis 全塞到每张小卡片。

## 建议验收方式

focused 测试：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py \
  tests/acquisition_ui/test_pinned_monitoring.py \
  tests/acquisition_ui/test_demo_smoke.py \
  tests/acquisition_ui/test_capture_session.py -q
```

端到端 tour：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert --shots output/cockpit-live-axis-tour
```

人工/截图验收：

- 五张实时卡从点状变为连续曲线。
- 每张卡显示紧凑坐标和当前时间窗。
- 常值信号不塌轴。
- 1 ms 通道不卡顿。
- 选中 12、实时显示 5 的行为不变。
- 录制仍包含全部选中通道，不只录可见卡片。

## 最终建议

先做 P0：小卡片坐标、当前窗口自动坐标、连线渲染、visible window 说明。这个阶段
收益最大、改动最局部，也最贴合你截图里的问题。

下一阶段做 Focus View，把 CANape 式的 cursor、zoom、pause、manual axis 和少量通道
叠加放进去。这样既能对标 CANape 采集时的图形窗口能力，又不会牺牲 Cockpit 主界面
的监控效率。
