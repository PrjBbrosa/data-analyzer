# 采集 Cockpit 实时可预览重构 Spec（第一性原理布局 + 曲线可读性）

Date: 2026-07-10
Status: Revised after implementation-readiness review
Plan: `docs/analyzer/acquisition/plans/2026-07-10-cockpit-live-preview-first-principles-implementation.md`
Source report: `docs/analyzer/acquisition/reports/2026-07-09-cockpit-live-axis-line-rendering-canape-gap-report.md`
Parent spec: `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`
Predecessor: `docs/analyzer/acquisition/specs/2026-07-08-cockpit-monitoring-phase12-spec.md`
（本 spec 只做增量；四态状态机 / 录制契约 / Health-Preflight-Persistence 契约不动。采集核心、
XCP/Vector 后端、MF4 writer、recording ring buffer 一律不碰——本 spec 纯显示层。布局重构只作用于
Cockpit **采集页**；ReplayTab 共享 `LiveCardGrid` / `RightPanel` 的既有行为必须保持。）

## 背景与采信

2026-07-09 对标报告经**逐行核对代码后采信**（当前实现事实全部属实：`_SPARK_MAX_POINTS=4096`、
录制路径 `sample_tap` 喂实时 UI、30→10fps 降频、默认显示 5 通道）。review 过程中补出报告未说透 /
漏掉的四点，纳入本 spec：

1. **报告只讲了"没连线"这一半根因**：`Sparkline.paintEvent` 的 x 是按 **bin 索引**定位
   （`live_cards.py:247` `x = idx/(len-1)*w`），低密度路径（`n<W`，`live_downsampler.py:72-77`）
下 N 个样本被挤到左侧 ~N/W 宽度、右侧空白，且横向间距与真实时间无关。这是"点状"的第二根因。
2. **`since rec start` 是真 bug 不是文案**：录制态 μ/σ/max 对 `_spark._buffer` 直接算
   （`live_cards.py:472`），buffer `maxlen=4096`——1ms 通道下"since rec start"实际只覆盖最后
   ~4s，label 在撒谎。
3. **刻度数学不重复造轮子**：仓库已有纯 Python nice-number 引擎
   `ui/pg_canvas/ticks_math.py`（`_nice_per_div`/`_frame_to_nice`/`_fmt_tick`），复用而非新写。
4. **stale / no-data 必须可辨认**：恒定值、DAQ 停更和从未收到样本不能只靠一条静止曲线猜测；本波把
   轻量状态放进卡片，但不引入采集核心告警或新的 Health band。

在此基础上，与用户第一性原理讨论后确立**布局重构**：状态健康是余光信息——绿时应安静得几乎不存在、
坏时必须躲不掉。当前"实时质量监控/录制预检"是反的（全绿时占满右列、真出问题时和平时长得一样）。
故本 spec 把所有健康信息收进顶栏、body 改 2 栏把空间还给曲线、录制事实进底栏、异常靠升级阶梯喊出来。

## 目标

- **A 曲线可读性**：采集时曲线连续可读、坐标诚实、常值不塌轴、1ms 不卡。
- **B 第一性原理布局**：健康"绿时安静、坏时躲不掉"——健康全进顶栏 strip（chip 可点看详情）、
  预检折成 strip pill、body 改 2 栏（信号｜曲线）两态同构零位移、录制事实进底栏、异常靠**分级升级
  阶梯**（green 静默 / yellow chip+nudge / red 脉冲+常驻 banner）。
- 验收门：`.venv/bin/python scripts/cockpit_ui_tour.py --assert` 扩展 A/B 不变量 +
  `.venv/bin/python scripts/cockpit_ui_tour.py --assert --onscreen --shots ...` **macOS 真机截图**（项目铁律，
  offscreen 不算数）。

## 非目标（明确不做，均报告 P1–P2，后续单独立 spec）

- Focus View（双击放大、滚轮缩放、游标 dt·dy 读数）——复用现有 `LiveCardGrid.focus_channel`
  在 center 就地放大即可，不在本波实现游标/缩放。
- 暂停显示（Pause View，冻结 UI 不停录制）。
- 越阈 / 段 event marker。
- overlay 共轴叠加、单位感知归一化。
- 时间窗切换按钮（10/30/60s）——本波默认固定 30s。
- 布局 / 监控配置持久化。
- ReplayTab 布局重构；共享控件允许增加默认关闭的能力，但 Replay 视觉与交互必须零回归。
- 采集核心、后端、writer、ring buffer、四态状态机、阈值 band 边界值——一律不动。

## 契约 A：曲线可读性

改动集中在 `widgets/live_cards.py`（painter）+ `widgets/live_downsampler.py`（如需）+ 共享刻度模块。

### A1 连续连线渲染（报告 P0）

**不变量：任何非空 buffer 的曲线必须表现为连续线，而非一串点/孤立竖线。**

- 混合渲染：
  - 低密度 `n ≤ 2·W`：用原始样本画连续 `QPainterPath` 折线（按 A2 的时间映射定位）；raw 遍历在此
    分支有 `2·W` 硬上界。
  - 高密度 `n > 2·W`：画 min/max 包络带（半透明 area）+ 连接各 bucket **代表值（该 bucket 的
    last value）** 成折线。**明确不连 min 或 max**——连极值会在单调波形上造出假锯齿。
- 真实断点：优先按通道 raster 判断，间隔 `> max(3 × raster_period, 1s)` 时 path 断开；没有 raster
  元数据时才回退到 `> 3 × 中位间隔`，不跨断点插值。
- 验收：低密度规则波形（如 60 点正弦）绘制为连续折线、无孤立点；高密度噪声信号可见包络带 + 中心线；
  单调斜坡不出现锯齿。

### A2 x 轴按时间线性映射（review 补出的第二根因）

**不变量：样本的 x 像素位置 = 其时间戳在当前可见时间窗内的线性位置，与 bin 索引无关。**

- 定义可见时间窗 `[t_anchor - window, t_anchor]`（window 默认 30s，见 A3）。`t_anchor` 明确定义为
  **该卡最新样本的 stream timestamp**，不得混用 wall clock / `time.monotonic()`；stale 时长另用样本
  到达的 monotonic 时刻计算。这样 Replay 的相对时间戳与真实采集时间戳都能保持同一映射。
- **窗口由时间 trim 实现，不由固定样本数暗含定义**：空闲与录制**都**按
  `trim_to_window(newest - window)` 裁到 30s（现录制态 `t_min=None` 不裁 → 改为裁；现空闲态裁 60s
  → 改为 30s，`live_cards.py:461-468`）。
- **buffer 容量必须容得下"诚实的 30s"**：raw `_SPARK_MAX_POINTS`（现 4096，`live_cards.py:65`）按最快
  展示 raster 下 30s 的样本数放大到 32000（1ms×30s=30000 + 边界余量）；另按 A6 同步维护增量显示
  bucket。**不变量是 raw buffer 持有的时间跨度 ≥ 标签声称的窗口**，否则回到 A4 的撒谎问题。
- 低密度与高密度统一按时间戳映射 x；高密度 bucket 也必须覆盖完整 30s 窗，而非重新按
  `[first_sample, last_sample]` 拉满。低密度不再出现"样本挤在左侧、右侧空白"。
- 无样本区间为真空白（不插值拉伸）。
- 验收：给 buffer 塞入只覆盖最近 5s 的样本，绘制时曲线只占右侧 5/30 宽度、左侧留白；间距不均的
  样本 x 位置与时间戳成比例（单测断言像素位置）；1ms 通道录制 30s 后标签"最近 30s"名副其实
  （buffer 时间跨度 ≥ 30s）；同一 5s 数据在高密度路径也只占右侧 5/30 宽度。

### A3 紧凑坐标 + 诚实可见窗口（报告需求 1+2）

**不变量：卡片显示当前可见窗口长度与 y 值范围；坐标绝不暗示显示了完整录制。**

- x 轴：底部一行窗口标签 `最近 30s`（录制态 `最近 30s（录制中）`）。
- y 轴：2–3 个刻度（顶 / 中 / 底），走共享 nice-tick（A5），5–10% padding；常值/近常值信号的
  默认最小 span 为 `max(1.0, abs(center) × 2%)`，再交给 nice-tick 扩框，避免塌轴且不对不同单位
  硬套固定 ±1。
- 卡片状态：从未收到样本显示`无样本`；距最后一次样本到达超过
  `max(1s, 3 × raster_period)` 显示低干扰 `停更 x.xs`，收到新样本立即恢复。内部状态名可用 stale，
  但面向用户保持中文。stale 只改变卡片提示与
  path 连续性，不改变全局 Health band。
- 窄窗让位：卡宽 `< 430px`（沿用 phase12 `_STATS_COLLAPSE_MIN_CARD_W`）时坐标文本让位于信号名 +
  当前值，不抢占。
- 默认窗口 30s 固定；切换（10/30/60s）留 P1。
- 验收：1ms 通道能看清窗口长度；常值信号 y 轴不塌；no-data/stale/恢复三态可区分；960px 窄窗下
  信号名 + 当前值不被坐标挤掉。

### A4 `since rec start` 统计诚实化（review 补出的 bug）

**不变量：卡片显示的统计与坐标窗口一致；标签不得声称覆盖了 buffer 容量之外的数据。**

- 录制态 μ/σ/max 与 sparkline 共享同一"最近 30s / 最近 N 样本"窗口，标签文案随之改为诚实表述
  （去掉"since rec start"暗示）。完整录制时长 / 总样本数 / 写入量归底栏事实流水（B5）与复盘弹窗。
- 验收：1ms 通道录制 >30s 后，卡片统计只反映最近窗口；单测断言标签文案不含"完整录制"暗示且统计
  样本数 ≤ 窗口应含数。

### A5 刻度数学共享（review：勿重复造轮子）

**模块边界：nice-number 刻度数学单一实现，采集侧与分析侧共用；采集侧不反向依赖分析 UI 包。**

- 把 `ui/pg_canvas/ticks_math.py` 的 `_nice_per_div` / `_frame_to_nice` / `_fmt_tick`（纯 Python、
  无 Qt/numpy）抽到共享位置（如 `mf4_analyzer/signal/` 或新 `mf4_analyzer/ui_kit/ticks_math.py`），
  旧位置留 re-export shim（分析侧调用点零改动）。由 refactor-architect 执行。
- 验收：分析侧现有 tick 相关测试零回归；采集侧 sparkline 通过共享模块取刻度；无 `acquisition_ui →
  ui.pg_canvas` 新增 import。

### A6 性能（贯穿 A，钉死 buffer 放大的代价）

**不变量：ring 健康时 1ms × 5 卡以 normal 30fps 实时显示；进入既有 degraded watermark 时以 10fps
稳定显示。放大 buffer 不得让 paint/stats 每帧扫描 30000 raw samples。**

- 风险：A2 把 buffer 放大到 30s（1ms=30000）后，`downsample_minmax` 每帧 O(n) 扫描 × 5 卡 × 30fps
  可能吃满 CPU 光栅（参见 lesson `project-timedomain-perf-raster-bound`：卡顿源于 CPU 光栅而非数据量）。
- **机制钉死为入队增量分桶，不采用 buffer-version paint cache**（实时流每帧都会改版本，cache 命中率
  近零）：保留 raw 30s deque 供诚实统计；同时维护固定 10ms 时间 bucket ring，每 bucket 保存
  `min/max/last`。`push` O(1)，过期 bucket 随窗口 trim 移除；高密度 paint 只把最多 3001 个 bucket
  合并到当前像素列，不遍历 raw deque；低密度 raw 分支最多遍历 `2·W` 个样本。
- stats 文本最多 2Hz 重算；当前值仍在每批样本到达时更新。2Hz 是显示节奏，不改变统计窗口或写盘。
- 验收：结构测试断言高密度 paint 不迭代 raw deque、显示 bucket 数有 3001 上界；目标 Mac 上 1ms×5 卡的
  `refresh+paint` p95 小于 normal 帧预算 33ms，degraded 10fps 时小于 100ms；真机录制无可感卡顿。

## 契约 B：第一性原理布局

### B1 健康全入顶栏 strip，chip 可点弹详情

**不变量：健康状态唯一的常显基线载体是顶栏 strip；chip 是唯一常显健康面，详情按需弹出。yellow/red
允许出现 B6 的条件式升级面，但 green/off 不新增常驻面。**

- `HealthChip`（`widgets/health_strip.py:48`）从"仅 hover tooltip"升级为**可点击**：点击弹一个
  `CursorPill` 式浮动圆角 popover（`WA_TranslucentBackground` + paintEvent 自绘背景，遵守项目
  嵌入浮层铁律），显示该 chip 的详情行。
- 详情数据源沿用现有：CAN→`bus_load_pct`、DAQ→`event_capacity/used`、XCP→`slave_id/timeouts`、
  REC→`ring_buffer_fill_pct`/`dropped_frames`/`write_rate`、HW→driver/channels。UI 不读自由文本。
- popover 交互：同一时刻最多一个；点当前 chip 切换关闭，点另一 chip 原位替换内容；点击外部、按 Esc、
  页面切换或窗口失焦均关闭。popover 非模态、不抢走录制快捷操作，窗口 resize 后重新锚定到 chip。
- 验收：点击任意 chip 弹出对应详情、再点/点外部/Esc 关闭；切 chip 不叠出第二张；popover 真机 dpr=2
  文字锐利、背景不透灰底。

### B2 预检折成 strip pill（聚合特例）

**不变量：预检不再单独占右列；作为顶栏一个聚合 pill 存在，点击看 5 数明细。**

- 新增「预检」pill 并入 strip，LED 取 5 项 band（`band_can_load`/`band_daq_slot`/
  `band_disk_remaining`/`band_sample_events_per_s`/`band_record_duration_s`）的**最差色**。
- 点击弹 popover：5 行 band 着色明细（CAN 负载 / DAQ slot / 磁盘剩余 / 采样事件·秒 / 预计可录
  时长）+ 底部 note`数字仅供参考·实际录制按真实样本累计`。"预计可录时长"全绿时压成`充足`，不显示
  无意义大数（如 232.7 天）。
- 可见性：连接空闲态显示；断开态显示 disabled/off，文案`连接后可用`且不可弹；**录制态隐藏**（录制时
  预检已无意义，健康由 REC/CAN/磁盘承接）。隐藏只改变 strip 内 pill，不引起 body 几何变化。
- 验收：空闲态 pill 可点弹 5 数；任一项转黄/红时 pill LED 变最差色；录制态 pill 隐藏。

### B3 body 改 2 栏，两态同构，录制零位移

**不变量：采集页 body = 左（信号选择/pin 管理）｜右（实时曲线，吃满剩余宽度）；空闲与录制布局同构；
按下 / 停止录制不引发 body 重排。ReplayTab 不在本布局重构范围。**

- 移除三栏中的健康右列（B4），splitter 变两栏。center `LiveCardGrid` 吃掉释放的宽度。
- 录制态相对空闲态的唯一视觉变化：REC chip → recording、底栏 → 事实流水、卡片红左条 + 红点 swatch
  （现有 `[recording="true"]` 机制不动）。
- 验收：`cockpit_ui_tour` 截图空闲 vs 录制，body 两栏几何一致、卡片 x 宽度不变（零位移断言）。

### B4 移除右健康列 + 数字重新落位

**不变量：`IdlePreflightPage` 与 `RecordingQualityPage` 承载的每一个数都有新家，不丢信息。**

- 只从**采集页**删除 `RightPanel` 的挂载（`_toolbar_mixin.py:494-507`）与刷新调用（window.py
  `_refresh_idle_right_panel`/`_refresh_recording_right_panel`/`show_disconnected`、
  `_settings_mixin.py:229-231`、`_polling_mixin.py:40-42`）。`widgets/right_panel.py` 暂时保留给
  ReplayTab；不得删除/stub 其类，后续若统一 Replay 布局另立 spec。
- 落位表：

  | 原右栏数据 | 新家 |
  | --- | --- |
  | CAN 总线负载 | 顶栏 CAN chip（已有）+ 点开 popover |
  | 缓冲占用（ring buffer） | REC chip 严重度 + popover |
  | 丢帧（dropped frames） | 升级信号：>0 转黄/红 → 底栏 nudge（B6） |
  | 最近帧延迟（`rec.last_rx_age_s`） | REC chip popover |
  | 磁盘剩余 | 底栏事实流水（B5）；低于阈值升 banner（B6） |
  | 写入速率 | 底栏事实流水（B5） |
  | 预检 5 数 | 预检 pill popover（B2） |

- 断开态连接清单（A2L 解析 / 硬件可用 / 选择可行）通过 `LiveCardGrid` 的**默认隐藏、采集页显式开启**
  能力折进中央引导画布；Replay 的`未加载 MF4`占位不显示 ECU 清单。
- 验收：采集页三态无右栏；每个原数据点可在其新家找到；ReplayTab 仍可加载/播放并显示既有右栏；
  `test_pinned_monitoring` / right_panel / replay 相关测试相应更新，无遗留死代码。

### B5 底栏录制事实流水

**不变量：录制的运行事实（非告警）集中在底栏 `QStatusBar`，一行紧凑呈现，不打扰。**

- 底部语义分两层：`QStatusBar` 始终是单行事实流；`EscalationBar` 以一行 overlay 锚在 status bar 上方，
  green/off 时隐藏，出现/消失不参与 layout、不改变 body 几何。告警不得覆盖或替换录制事实。
- 录制态状态栏（`_settings_mixin._update_status_bar:245`）：
  `录制中 · {mm:ss} · {n} 样本 · {x.x MB} · {写入}/s · 磁盘剩 {~时长}`；空闲态：`后端 · 已选 N·
  实时显示 P`；断开态：`后端`。
- 写入速率取 `rec.write_rate_bps`（字段名历史遗留，单位实际为 samples/s）；磁盘剩余时长复用
  `estimate_throughput_bps(selection)` + `estimate_record_duration_s(...)`，不得把 samples/s 当 bytes/s。
- 窄窗截断优先级：`录制时长 > 磁盘剩余时长 > 样本数 > 大小 > 写入速率`（后者先省略）；按字段省略，
  不做像素中间硬截断，不换行。
- 验收：录制态一行含时长 / 样本 / 大小 / 写入 / 磁盘；960px 下按优先级降级不换行、不溢出。

### B6 健康升级阶梯（藏面板的支点）

**不变量：任何 yellow/red 健康在用户即使只盯着曲线时也能被发现；green 不额外占空间或制造噪声。**

- 采集侧**新建**一个轻量升级面（顶栏 summary + 独立 `EscalationBar`），输入显式为
  `(snapshot, disk_free_bytes)`；磁盘不塞进 `HealthSnapshot`。复用现成 band 数学
  （`band_dropped_frames`/`band_disk_remaining`/`band_ring_buffer` 等），非新造判定：
- `effective_chip_levels` 取 `snapshot.levels()` 与 issue level 的逐 chip 最差值；dropped/ring/
  `last_rx_age_s` 以及磁盘问题都归 REC chip，CAN 等问题归各自 chip。这样额外 band 不会只出 banner、
  却留下一个错误的绿色 chip。
  - **green**：仅 chip 绿点；summary 与 `EscalationBar` 隐藏。
  - **off/unknown**：对应 chip 灰；summary 显示`N 项无证据`，不升级为黄/红。
  - **yellow**：对应 chip 变黄 + 右上 summary`N 项需注意` + 底栏升一行 nudge；最多展示 2 个问题，
    其余收为`另 N 项 · 查看`，点`查看`弹最严重 chip popover。
  - **red**：chip 红；进入 red 或 red 原因变化时 LED 脉冲 3 次，随后保持实心红，避免无限动画；
    `EscalationBar` 常驻红 banner。用户确认后 banner 可折叠，但红 chip + summary 仍保留；同一原因不重复
    弹出，原因变化重新展开。
- **恢复规则**：yellow/red 恢复后立即隐藏 nudge/banner、停止脉冲并清除确认 latch；下次重新越界仍会正常
  升级。这里的“不自动消”仅指没有超时自动隐藏，不得阻止健康恢复清场。
- 采集侧无既有 nudge 层（分析器 `ui/hints.py` 那套不在采集侧），本面为采集侧新增，但只做"band→
  视觉严重度"的薄映射。
- 验收：`dropped=1..10` → REC chip 黄 + nudge；`dropped>10` 或磁盘 `<1GB` → 对应 chip/summary 红、
  进入时脉冲 3 次 + banner 常驻；确认只折叠 banner；恢复后自动回 green 静默，再次越界可重新升级。

### B7 断开态 2 栏

- 采集断开态同样 2 栏；左栏"连接后载入 A2L"、中央引导画布含连接三项清单。清单状态来自结构化
  数据，不从文案反推：A2L parsed / HW available / selection feasible。
- 验收：采集断开态无右栏、中央引导含清单三项；ReplayTab 占位无该清单。

## 验收门（汇总）

- **单测**：A2 低/高密度时间-x 映射、A3 no-data/stale/恢复、A4 诚实窗口、A5 分析侧零回归、
  B1 popover 完整关闭矩阵、B2 band→pill 色映射、B6 `(snapshot,disk)`→严重度/确认/恢复状态机、
  ReplayTab 零回归。
- **tour**：`.venv/bin/python scripts/cockpit_ui_tour.py --assert` 扩 A1–A6 / B1–B7 不变量（含 B3 零位移
  几何断言）。
- **macOS 真机截图（铁律，命令显式 `--onscreen`，offscreen 不算）**：5 卡点状→连续、坐标 + 30s
  窗可读、常值不塌、低密度不
  挤左、1ms 不卡；预检 pill 与 chip popover dpr=2 文字锐利、无灰底；录制态无右栏、body 零位移、
  升级阶梯 yellow/red 真机可见（脉冲 + banner）。

## 实施相位（详见 plan）

两条线互不依赖，可独立 ship：

- **Phase A（曲线可读性）**：A1–A6。改动局部（`live_cards.py` + `live_downsampler.py` + 共享
  `ticks_math`），完成增量 bucket / perf gate 后可先行合入，独立收益。
- **Phase B（布局重构）**：B1–B7。架构性（strip 可点 + popover + 预检 pill + 移除右栏 + 底栏事实 +
  升级阶梯）。改动面 `health_strip.py` / `right_panel.py`（仅解除采集页依赖，Replay 继续使用）/
  `window.py` / `_toolbar_mixin` /
  `_settings_mixin` / `_polling_mixin` + 测试迁移。

Phase B 按无信息丢失的依赖顺序拆三批：① B1-B2 先建立顶栏目的地；② B5-B6 建立底部事实/升级目的地；
③ B3-B4-B7 最后移除采集页右栏并收口两栏。任何中间 commit 都不得先删来源、后补目的地。

## 落地分工（实现走 squad）

- **pyqt-ui-engineer**：sparkline painter + 坐标（A1–A4）、chip 可点 + popover + 预检 pill（B1-B2）、
  2 栏布局 + 移除右栏（B3-B4）、底栏事实 + 升级阶梯面（B5-B6）、断开态（B7）。
- **refactor-architect**：抽 `ticks_math` 共享（A5）、解除采集页 `RightPanel` 依赖且保留 Replay 消费者
  的模块边界清理（B4）。
- **signal-processing-expert**：复核 nice-tick / min-span 数学（A3/A5）与 10ms 增量 bucket 的极值/last
  保真及性能门（A6）。
