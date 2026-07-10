# 采集 Cockpit 实时可预览重构 — Implementation Plan

> **For agentic workers (Codex / squad specialists):** 按任务顺序执行，checkbox 跟踪进度。
> 每个任务自带测试闭环：先写失败测试 → 实现 → 跑绿 → commit。不要跨任务合并 commit。
> **全程不要 `run_in_background` 跑全量 pytest（TCC 教训 `env-tcc-downloads-blocks-access`）**；
> 用前台 focused 命令。UI/视觉改动**必须真机验收**（截图/objc），offscreen 单测过≠修好
> （`feedback-verify-ui-visually`）。

Date: 2026-07-10
Spec: `docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-preview-first-principles-spec.md`

**Goal:** 让采集时曲线连续可读、坐标诚实（Phase A），并把健康信息收进顶栏、body 改 2 栏把空间
还给曲线、异常靠分级升级阶梯喊出来（Phase B）。

**Architecture:** 纯显示层。Phase A 改 `widgets/live_cards.py` 的 sparkline painter + 30s 时间窗，刻度数学
抽到共享模块；raw deque 保留诚实统计，另维护 10ms 增量显示 bucket，paint 不扫 raw。Phase B 先建立
顶栏/底栏目的地，再只从**采集页**解除 `RightPanel`；ReplayTab 继续使用现有 `RightPanel`。底部告警
`EscalationBar` 作为 status bar 上方 overlay，与 `QStatusBar` 事实流分层且不改变 body 几何。采集核心 /
后端 / writer / recording ring buffer / 四态状态机 /
阈值 band 边界一律不碰。

**Tech Stack:** PyQt5 + pytest-qt（offscreen）+ QPainter/canvas。无新依赖。

## Global Constraints

- 命令一律用 `.venv/bin/python`；pytest 全部前台 focused 跑，禁 `run_in_background` 全量。
- 既有 objectName 全部保留；新增走本 plan 明列的 objectName。
- 嵌入浮层/popover 的自定义 QWidget 必须透明背景 + **paintEvent 自绘圆角背景**兜底
  （`WA_TranslucentBackground` 会让本体 QSS 失效，`feedback-no-gray-bg-embedded-widgets`）。
- `ui_kit` 不得 import `ui.*` / `acquisition_ui.*`；`acquisition_ui` 不得新增 import `ui.pg_canvas.*`
  （A5 抽共享模块正是为此）。
- 录制契约 / 采集核心 / ring / writer / 阈值 band 边界不动；本 plan 全是显示层。
- 默认可见时间窗 = **30s**；窗口切换按钮不做（P1）。
- 文案含中文的文件 IO 显式 `encoding="utf-8"`；独立 HTML 交付带 `<meta charset="utf-8">`。
- 健康严重度一律走现成 band helper（`band_can_load`/`band_daq_slot`/`band_disk_remaining`/
  `band_sample_events_per_s`/`band_record_duration_s`/`band_dropped_frames`/`band_ring_buffer`），
  不新写阈值判定。
- `HealthSnapshot` 不新增磁盘字段；需要磁盘判断的 view-model 显式接收 `disk_free_bytes`。
- `LiveCardGrid` / `RightPanel` 是 Capture 与 Replay 的共享面：共享 API 改动必须 grep 全部消费者并跑
  `tests/acquisition_ui/test_replay_tab.py`；本波不改 Replay 布局。
- 视觉验收分两层：offscreen `--assert` 是自动门；带截图的真机门必须显式传 `--onscreen`，二者不可互换。

---

# Phase A — 曲线可读性（显示层、先发）

改动面：`widgets/live_cards.py`、`widgets/live_downsampler.py`、新共享 `ticks_math`、相关测试。
Phase A 合入后即有独立收益，不依赖 Phase B。

### Task A-1: 抽 `ticks_math` 为共享纯模块（A5）

**Files:**
- Create: `mf4_analyzer/ui_kit/ticks_math.py`（迁入 `_nice_per_div`/`_frame_to_nice`/`_fmt_tick`/
  `_NICE_STEP_MANTISSAS`/`_snap_y_to_divisions`/`_adjacent_nice_step`，并定义覆盖这些私有名的 `__all__`）
- Modify: `mf4_analyzer/ui/pg_canvas/ticks_math.py` → 显式 re-export 上述 helper；
  `_quantize_range_key` 与包含它的旧 `__all__` 留在原模块
- Test: `tests/ui_kit/test_ticks_math.py`（新）、跑现有 pg_canvas tick 测试验零回归

**Interfaces:**
- Produces: `mf4_analyzer.ui_kit.ticks_math` 暴露 `_nice_per_div(raw) -> float|None`、
  `_frame_to_nice(lo, hi, n) -> (bottom, top, ticks)`、`_fmt_tick(value) -> str`。

- [ ] **Step 1: 写共享模块测试**（新文件）

```python
from mf4_analyzer.ui_kit.ticks_math import _nice_per_div, _frame_to_nice, _fmt_tick

def test_nice_per_div_snaps_up():
    assert _nice_per_div(0.7) == 0.8
    assert _nice_per_div(23) == 25

def test_frame_to_nice_returns_n_plus_one_ticks():
    bottom, top, ticks = _frame_to_nice(0.0, 9.7, 4)
    assert len(ticks) == 5 and bottom <= 0.0 and top >= 9.7

def test_fmt_tick_compact():
    assert _fmt_tick(0.0) == "0"
    assert _fmt_tick(1500) == "1500"
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/ui_kit/test_ticks_math.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 迁移实现 + shim**

把 `ui/pg_canvas/ticks_math.py` 的纯函数体整体移入 `ui_kit/ticks_math.py`（逐字，不改逻辑）；
`_quantize_range_key` 保留在原文件（pg_canvas 私有，不迁）。原文件顶部改：

```python
from mf4_analyzer.ui_kit.ticks_math import (  # noqa: F401 re-export
    _NICE_STEP_MANTISSAS, _snap_y_to_divisions, _nice_per_div,
    _adjacent_nice_step, _fmt_tick, _frame_to_nice,
)
```

- [ ] **Step 4: 跑绿 + 分析侧零回归**

Run: `.venv/bin/python -m pytest tests/ui_kit/test_ticks_math.py tests/ui/ -q -k "tick or canvas or axis"`
Expected: PASS（含现有 pg_canvas tick 测试）。

- [ ] **Step 5: Commit** — `refactor(ticks): lift nice-number tick math into shared ui_kit.ticks_math`

---

### Task A-2: 时间窗 trim + buffer 容量（A2 / A4 前置）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（`_SPARK_MAX_POINTS`、`_IDLE_WINDOW_S`→
  统一 `_LIVE_WINDOW_S=30.0`、`refresh()` 的 trim 逻辑 `:461-468`）
- Test: `tests/acquisition_ui/test_live_cards.py`（追加）

**Interfaces:**
- Produces: 模块常量 `_LIVE_WINDOW_S = 30.0`；`Sparkline` 在空闲与录制都按最新 **stream timestamp**
  `newest - _LIVE_WINDOW_S` trim；raw `_SPARK_MAX_POINTS = 32000`，容得下 30s@1ms 并留边界余量。

- [ ] **Step 1: 写失败测试**

```python
def test_recording_trims_to_live_window(qtbot):
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_1ms")
    qtbot.addWidget(card)
    card.set_recording(True, rec_start_ts=0.0)
    for i in range(40000):            # 40s @ 1ms
        card.push_sample(i / 1000.0, float(i))
    card.refresh()
    buf = card._spark._buffer
    span = buf[-1][0] - buf[0][0]
    assert span <= 30.0 + 1e-6        # 录制态也裁到 30s（旧行为 t_min=None 不裁）
    assert span >= 29.0               # 且确实持有近 30s（buffer 容量足够）
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py::test_recording_trims_to_live_window -q`
Expected: FAIL（现录制 `t_min=None` 不裁 / 或 4096 上限只留 ~4s，span 达不到 29）。

- [ ] **Step 3: 实现**

- `_SPARK_MAX_POINTS = 32000`（≥30s@1ms 的安全上限；这是 display raw deque，不是 recording ring）。
- 合并窗口常量为 `_LIVE_WINDOW_S = 30.0`（替换 `_IDLE_WINDOW_S`）。
- `refresh()`：录制与空闲都 `t_min = buf[-1][0] - _LIVE_WINDOW_S if buf else None`（删掉录制态
  `t_min=None` 分支）；stats 也据此窗口算（承接 A-5）。

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -q`
Expected: PASS。

- [ ] **Step 5: Commit** — `fix(live-cards): trim sparkline to honest 30s window in both idle and recording`

---

### Task A-3: 连续连线 + 时间轴 x 定位（A1 + A2 painter）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（`Sparkline.paintEvent` `:205-256`）
- Test: `tests/acquisition_ui/test_live_cards.py`（追加，用 `QImage` 抓像素/或 path 顶点断言）

**Interfaces:**
- Consumes: A-1 `ui_kit.ticks_math`（此任务先只做连线与 x 定位，坐标标签留 A-4）。
- Produces: `paintEvent` 低密度画连续 `QPainterPath`、高密度画 min/max 包络带 + last-value 折线；
  x 按时间戳映射到 `[t_anchor - 30s, t_anchor]`。

- [ ] **Step 1: 写失败测试**（低密度不再是孤立点：绘制后统计非背景像素的连通性 / 或重构出可测的
  纯函数 `_build_polyline(samples, w, h, window, t_anchor) -> list[QPointF]` 并断言其顶点数 == 样本数、
  x 单调随时间）

```python
def test_low_density_builds_connected_polyline():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_polyline
    now = 10.0
    samples = [(now - 30 + i*(30/59), float(i)) for i in range(60)]  # 含窗口两端
    pts = _build_polyline(samples, w=600, h=64, window=30.0, t_anchor=now, ymin=0, ymax=59)
    assert len(pts) == 60                      # 连成折线而非孤点
    xs = [p.x() for p in pts]
    assert xs == sorted(xs)                    # x 随时间单调
    assert xs[-1] > 590 and xs[0] < 10         # 铺满全宽（末点贴右、首点靠左边界内）

def test_x_is_time_proportional_not_index():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _build_polyline
    now = 10.0
    samples = [(now - 5.0, 0.0), (now - 2.5, 1.0), (now, 2.0)]    # 只覆盖最近 5s
    pts = _build_polyline(samples, w=600, h=64, window=30.0, t_anchor=now, ymin=0, ymax=2)
    assert pts[0].x() > 480                     # 最早样本落在右侧 5/30 区域，非左边缘
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -q -k "polyline or time_proportional"`
Expected: FAIL（`_build_polyline` 不存在 / 现 x 按 bin 索引）。

- [ ] **Step 3: 实现**

- 抽纯函数 `_build_polyline` / `_build_envelope`：x = `w * (ts - (t_anchor - window)) / window`，
  y = `h - (v - ymin)/(ymax - ymin) * h`。
- `paintEvent` 判密度：`n <= 2 * w` → `_build_polyline` 画 `QPainterPath`；否则 `_build_envelope`
  返回 `(band_path, line_pts)`，band 用 `hexA(color, ~0.16)` 填充、line 连各 bucket **last value**
  （非 min/max）。
- 高密度 `_build_envelope` 的 bucket 边界同样基于完整 `[t_anchor-window, t_anchor]`；补测试证明只有 5s
  数据时包络也只占右侧 5/30，不能按 `[first,last]` 拉满。
- gap 优先走 `> max(3×raster_period, 1s)`；无 raster 才回退 `>3×中位间隔`。返回分段 path，类型不得
  用无法表达断点的单一 `list[QPointF]` 冒充。

- [ ] **Step 4: 跑绿 + 真机初判**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -q`
真机：`.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/a3-lines`，目视 5 卡为连续线。

- [ ] **Step 5: Commit** — `feat(live-cards): continuous polyline + envelope render with time-based x`

---

### Task A-4: 坐标标签 + nice 刻度 + no-data/stale + 常值不塌轴（A3）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（`Sparkline.paintEvent` 画 y ticks +
  x 窗标签；窄窗 <430 让位）
- Test: `tests/acquisition_ui/test_live_cards.py`（追加纯 scale 函数断言）

**Interfaces:**
- Consumes: A-1 `ui_kit.ticks_math._frame_to_nice`/`_fmt_tick`。
- Produces: `_spark_scale(ymin, ymax) -> (lo, hi, ticks[list[float]])`，内部最小 span =
  `max(1.0, abs(center)*0.02)`；`_sample_state(last_arrival, now, raster_period)` 返回
  `"no-data"|"live"|"stale"`。`LiveSignalCard` 接受可注入 monotonic arrival clock，避免测试 sleep。

- [ ] **Step 1: 写失败测试**

```python
def test_constant_signal_keeps_min_span():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _spark_scale
    lo, hi, ticks = _spark_scale(54.30, 54.34)
    assert (hi - lo) >= 1.0                 # 按 center 规则取最小 span
    assert len(ticks) >= 3

def test_scale_uses_nice_ticks():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _spark_scale
    lo, hi, ticks = _spark_scale(0.0, 2360.0)
    assert hi >= 2360.0 and lo <= 0.0       # 含数据 + padding
    assert all(t == round(t, 6) for t in ticks)

def test_sample_state_recovers_after_new_arrival():
    from mf4_analyzer.acquisition_ui.widgets.live_cards import _sample_state
    assert _sample_state(None, now=10.0, raster_period=0.001) == "no-data"
    assert _sample_state(8.0, now=10.0, raster_period=0.001) == "stale"
    assert _sample_state(10.0, now=10.0, raster_period=0.001) == "live"
```

- [ ] **Step 2: 确认失败** — Run focused pytest，Expected: FAIL（`_spark_scale` 不存在）。

- [ ] **Step 3: 实现** — `_spark_scale` 先按上述动态 min span 扩展、加 5–10% padding，再调用
  `_frame_to_nice(..., 2)`；`paintEvent` 画顶/中/底 y 文本和窗口标签。卡宽<430 时不画 y 文本。
  arrival monotonic 只判 no-data/stale；x 坐标继续用 stream timestamp。新样本到达立即清 stale。

- [ ] **Step 4: 跑绿 + 真机** — focused pytest PASS；
  `.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/a4-axis`
  目视坐标可读、常值 EcuTemp 不塌、960 窄窗名/值不被挤。

- [ ] **Step 5: Commit** — `feat(live-cards): compact y-ticks + honest 30s window label`

---

### Task A-5: `since rec start` 统计诚实化（A4）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（`STATS_WINDOW_LABEL_RECORDING`、
  `refresh()` stats 文案/tooltip `:46-48,461-483`）
- Test: `tests/acquisition_ui/test_live_cards.py`

- [ ] **Step 1: 写失败测试**

```python
def test_recording_stats_label_is_honest(qtbot):
    card = LiveSignalCard("MotSpd", raster="event_1ms")
    qtbot.addWidget(card)
    card.set_recording(True, rec_start_ts=0.0)
    for i in range(40000):
        card.push_sample(i/1000.0, float(i))
    card.refresh()
    tip = card._stats_label.toolTip()
    assert "rec start" not in tip and "完整" not in tip
    assert "最近 30s" in tip                # 与坐标窗口一致
```

- [ ] **Step 2: 确认失败** — Expected: FAIL（现 tooltip 为 `since rec start`）。

- [ ] **Step 3: 实现** — `STATS_WINDOW_LABEL_RECORDING = "最近 30s"`（与空闲统一为窗口表述）；
  stats 已因 A-2 只在 30s buffer 上算，无需再改计算，仅改标签/tooltip 文案诚实化。

- [ ] **Step 4: 跑绿** — focused pytest PASS。

- [ ] **Step 5: Commit** — `fix(live-cards): honest recording stats window label (drop "since rec start")`

---

### Task A-6: 性能——10ms 增量 bucket + stats 2Hz + 实测门（A6）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_downsampler.py`（新增 `RollingDisplayBuckets`）
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（push/trim/paint 接 bucket；stats 最多 2Hz）
- Create: `scripts/benchmark_live_cards.py`（5 卡、30s@1ms、normal/degraded 两档，打印 p50/p95）
- Test: `tests/acquisition_ui/test_live_downsampler.py`、`test_live_cards.py`

- [ ] **Step 1: 写失败测试** — 30s@1ms push 后：raw span ≥29s；bucket 数 ≤3001；每 bucket 保存
  `min/max/last`；trim 同时移除 raw 与过期 bucket；在 30000 raw 的高密度场景 spy raw deque，断言
  paint 不迭代它；另断言低密度 raw 分支输入数始终 `≤2·W`；
  100 次、每次推进 10ms 的 `refresh()` 内 stats 重算次数 ≤3（注入 clock，覆盖 2Hz 上限）。

- [ ] **Step 2: 确认失败** — `RollingDisplayBuckets` 不存在，且当前 paint/stats 会扫描 raw。

- [ ] **Step 3: 实现** — 固定 `_DISPLAY_BUCKET_S=0.010`；`push` O(1) 更新当前 bucket 的
  `min/max/last`，跨 bucket 时 append；高密度 paint 将最多 3001 bucket 合并到 W 像素列，低密度才走
  `≤2·W` raw 折线。保留 raw 供 30s
  统计，但 stats 文本以注入 monotonic clock 限到 2Hz。禁止再保留“版本缓存”备选路径。

- [ ] **Step 4: 跑绿 + 性能/真机门** — 结构测试 PASS；运行
  `.venv/bin/python scripts/benchmark_live_cards.py`，目标 Mac 五卡 `refresh+paint` p95：30fps 档 <33ms、
  10fps 档 <100ms；再用 onscreen tour 录制目视不卡。计时只在脚本/真机门判断，不把跨机器毫秒阈值塞进
  普通 pytest，避免 flaky。

- [ ] **Step 5: Commit** — `perf(live-cards): bound per-frame downsample cost for 30s@1ms buffers`

> **Phase A 收口**：先跑 offscreen
> `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python scripts/cockpit_ui_tour.py --assert --shots output/phase-a-offscreen`；
> 再跑真机 `.venv/bin/python scripts/cockpit_ui_tour.py --assert --onscreen --shots output/phase-a-onscreen`。
> 确认 5 卡连续/坐标/no-data-stale/常值/不挤左/不卡后，Phase A 可独立合入 main。

---

# Phase B — 第一性原理布局（架构性，A 之后）

改动面：`widgets/health_strip.py`、新 `health_popover.py` / `escalation_bar.py`、采集页
`main_window/*`、`live_cards.py` + 测试。`widgets/right_panel.py` **不删除**，ReplayTab 继续消费。

按“先建目的地、再拆来源”分三批：

1. B-1/B-2：顶栏详情 + 预检目的地；
2. B-3：底部事实 + 升级目的地；
3. B-4/B-5/B-6：移除采集页右栏、接断开清单、跑完整验收。

### Task B-1: `HealthChip` 可点弹详情 popover（B1）

**Files:**
- Create: `mf4_analyzer/acquisition_ui/widgets/health_popover.py`（`HealthPopover(QFrame)`，
  CursorPill 式：`WA_TranslucentBackground` + paintEvent 自绘圆角背景）
- Modify: `mf4_analyzer/acquisition_ui/widgets/health_strip.py`（`HealthChip` 加 clickable + 点击
  发信号 / 弹 popover）
- Test: `tests/acquisition_ui/test_health_strip.py`（新/追加）

**Interfaces:**
- Produces: `HealthChip.clicked = pyqtSignal(str)`（chip name）；`HealthPopover.set_rows(list[(k, v,
  level)])` + `show_at(anchor_widget)` + `dismiss()`；`HealthStrip.detail_for(name, snapshot) ->
  list[(k,v,level)]`。`HealthStrip` 持有唯一 popover 和当前 anchor name。

- [ ] **Step 1: 写失败测试** — 覆盖完整交互矩阵：点 chip 打开；再点同 chip 关闭；点另一 chip 只替换
  内容且始终只有一个 popover；点外部 / Esc / 窗口失焦 / mode tab 切换关闭；resize 后仍锚定对应 chip。
  另断言 `HealthPopover` 渲染 N 行且 paintEvent 后中心像素非透明灰底。
- [ ] **Step 2: 确认失败** — Expected: FAIL（chip 无 clicked 信号 / popover 不存在）。
- [ ] **Step 3: 实现** — `HealthChip.mousePressEvent` 左键 emit `clicked(name)`；`HealthPopover`
  参照 `ui/chart_stack/cursor_pill.py` 的自绘背景（radius 9、bg rgba(255,255,255,.96)、border
  #d8e0eb）；用 application eventFilter 处理 outside click/Esc/focus-out，只有点击同时位于 popover 与
  当前 anchor 之外才算 outside，避免“filter 先关、chip handler 又重开”；关闭时卸载 filter，避免泄漏。
  popover 非模态；切换 chip 复用实例，窗口 resize 时重新 `show_at(anchor_widget)`。
- [ ] **Step 4: 跑绿 + 真机** — focused pytest PASS；运行
  `.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/b1-popover`，实点各 chip、外部、Esc，
  确认 dpr=2 文字锐利、无灰底、无叠层。
- [ ] **Step 5: Commit** — `feat(health-strip): clickable chips with detail popover`

---

### Task B-2: 预检 pill（聚合 popover）（B2）

**Files:**
- Create: `mf4_analyzer/acquisition_ui/preflight_view_data.py`（纯函数
  `build_preflight_rows(selection, event_capacity, disk_free_bytes, bitrate_bps)`）
- Modify: `mf4_analyzer/acquisition_ui/widgets/health_strip.py`（独立 `PreflightPill`，不混入固定五健康
  `CHIP_NAMES`；LED = 5 band 最差色）
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py`（`IdlePreflightPage` 复用同一 row builder，
  保持 Replay 视觉/API 不变）
- Modify: `main_window/window.py`（把原 `IdlePreflightPage` 的 5 数计算喂给 pill；可见性：空闲显示、
  断开灰、录制隐藏）
- Test: `tests/acquisition_ui/test_health_strip.py`

**Interfaces:**
- Consumes: 现有 estimator/band（`estimate_can_bus_load` 等）；把 `right_panel.py:389-448` 的“计算→展示行”
  抽成纯 row builder，`IdlePreflightPage` 与 `PreflightPill` 双方消费，避免复制一套预检判定。
- Produces: `PreflightPill.apply(selection, event_capacity, disk_free_bytes, *, state)`；connected-idle 可点，
  disconnected 显示 off/`连接后可用`且 disabled，recording 隐藏；点击复用 B-1 唯一 popover。

- [ ] **Step 1: 写失败测试** — 全绿选择 → pill LED green、popover 5 行；令一项越黄阈 → pill LED
  变最差色；`预计可录时长` 全绿时文本为 `充足`；断开态不可打开且文案正确；录制态隐藏但
  `LiveCardGrid.geometry()` 不变；同一输入下 pill rows 与 `IdlePreflightPage` rows 相等。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: 实现** — pill 复用 B-1 popover；5 数计算复用现成 estimator+band（不重写）；
  `预计可录时长` band==green 时压成 `充足`，否则 `_humanize_duration_s`。
- [ ] **Step 4: 跑绿 + 真机** — pytest PASS；运行
  `.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/b2-preflight`，确认空闲弹 5 数、
  断开不可点、录制隐藏且 body 不移动。
- [ ] **Step 5: Commit** — `feat(health-strip): preflight pill with aggregate popover`

---

### Task B-3: 底部事实流 + 升级阶梯目的地（B5 + B6）

**Files:**
- Create: `mf4_analyzer/acquisition_ui/widgets/escalation_bar.py`（独立于 `QStatusBar` 的单行 overlay）
- Modify: `main_window/window.py`（创建 overlay、在 resize 时锚到 status bar 上方，不加入 body layout）
- Modify: `main_window/_settings_mixin.py:245`（录制事实流 + 按字段降级）、
  `main_window/_polling_mixin.py`（把 `(snapshot, disk_free_bytes)` 喂 escalation）、
  `health_strip.py`（非绿 summary + red 进入动画）
- Test: `tests/acquisition_ui/test_escalation.py`（新）
- Test: `tests/acquisition_ui/test_status_bar_text.py`（更新）

**Interfaces:**
- Produces: `escalation_state(snapshot, *, disk_free_bytes) -> EscalationState(level, issues)`；每个 issue
  包含 `source_chip/message/level/reason_key`。`EscalationBar.apply(state)`、`acknowledge()`、`reset()`。
  磁盘上下文显式传参，不修改 `HealthSnapshot`。
- Produces: `effective_chip_levels(snapshot, state)`：取 `snapshot.levels()` 与 issue level 的逐 chip 最差；
  disk/ring/dropped/last-rx 都映射到 REC，避免 banner 已红而 REC chip 仍绿。
- Produces: `EscalationBar.reanchor(status_bar)`；bar 的出现/隐藏不改变 splitter / `LiveCardGrid` geometry。
- Produces: `_recording_fact_parts(width_px) -> list[str]`，按
  `时长 > 磁盘剩余时长 > 样本数 > 文件大小 > 写入速率`逐字段省略；磁盘时长复用 preflight estimator，
  `rec.write_rate_bps` 只按 samples/s 显示。

- [ ] **Step 1: 写失败测试**

```python
GB = 1024 ** 3
MB = 1024 ** 2

def test_dropped_frames_escalates_to_yellow():
    state = escalation_state(make_snapshot(dropped=3, ring=68.0), disk_free_bytes=10 * GB)
    assert state.level == "yellow"
    assert {issue.source_chip for issue in state.issues} == {"REC"}

def test_dropped_over_ten_is_red():
    assert escalation_state(
        make_snapshot(dropped=12, ring=10.0), disk_free_bytes=10 * GB
    ).level == "red"

def test_low_disk_escalates_to_red():
    state = escalation_state(make_snapshot(), disk_free_bytes=512 * MB)
    assert state.level == "red" and any("磁盘" in i.message for i in state.issues)
    assert effective_chip_levels(make_snapshot(), state)["REC"] == "red"

def test_ack_collapses_banner_but_recovery_rearms_it(qtbot):
    health_strip, bar = make_escalation_widgets(qtbot)
    bar.apply(red_state("disk"))
    bar.acknowledge()
    assert bar.is_collapsed and health_strip.summary_text()
    bar.apply(green_state())
    assert bar.isHidden()
    bar.apply(red_state("disk"))
    assert not bar.is_collapsed

def test_red_pulse_runs_three_loops_then_stops(qtbot):
    health_strip, bar = make_escalation_widgets(qtbot)
    rec_chip = health_strip.chip("REC")
    bar.apply(red_state("disk"))
    assert rec_chip.pulse_animation.loopCount() == 3
```

另补状态栏/几何测试：1280px 含时长/磁盘时长/样本/大小/写入五项；960px 只按既定优先级省略完整
字段，不得出现半截字段或把 `write_rate_bps` 当作 bytes/s 计算磁盘时长；green/yellow/red/ack/recovery
各态的 `LiveCardGrid.geometry()` 相等。

- [ ] **Step 2: 确认失败** — 新 view-model / bottom layer 不存在；旧状态栏仍混放丢帧/缓冲告警。
- [ ] **Step 3: 实现** — 所有严重度调用现成 band helper：`dropped=1..10` yellow、`>10` red；ring 输入
  始终是百分数。先合成 effective chip levels 再刷新 chip/summary。green 隐藏 summary/bar；off 只出
  `N 项无证据`；yellow 最多显示 2 项；red 在进入或
  `reason_key` 改变时脉冲 3 次后实心。ack 只折叠 banner，chip/summary 保留；恢复 green 时停止动画、
  隐藏 bar、清 latch。事实流用 `QFontMetrics.horizontalAdvance` 逐字段装配，不做字符串中间 elide；
  事实流与告警条是两个 widget，互不覆盖。
- [ ] **Step 4: 跑绿 + 真机** — focused pytest PASS；运行
  `.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/b3-escalation`，依次注入
  yellow→red→ack→green→red，确认进入/确认/恢复/再触发闭环；960px 下事实流按字段省略且不换行。
- [ ] **Step 5: Commit** — `feat(acq): separate recording facts from health escalation states`

---

### Task B-4: 移除右栏 + body 2 栏 + 数据落位（B3 + B4）

**Files:**
- Modify: `main_window/_toolbar_mixin.py:494-507`（splitter 去掉 `RightPanel`，两栏）
- Modify: `main_window/window.py`（删 `_refresh_idle_right_panel`/`_refresh_recording_right_panel`
  `:844-865`、`show_disconnected` 右栏分支）、`_settings_mixin.py:229-231`、`_polling_mixin.py:40-42`
- Keep as Replay consumers: `widgets/right_panel.py`、`replay_tab.py`；不得删除/stub 或改变 Replay 布局，
  只移除采集页 import/实例/刷新链（B-2 对预检 row builder 的内部复用除外）
- Test: 更新 `test_pinned_monitoring.py`、`test_state_machine.py`；保留并运行 `test_right_panel.py`、
  `test_replay_tab.py`

- [ ] **Step 1: 写失败测试** — 断言主窗口无 `_right_panel`（或 splitter count==2）；空闲 vs 录制
  center 几何一致（B3 零位移，抓 `LiveCardGrid.geometry().width()` 两态相等）；同时断言
  `ReplayTab.right_panel` 仍存在、加载 MF4 后可见且 play/stop 正常。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: 实现** — 采集页 splitter 只加 left + center；删采集主窗口的右栏刷新调用链与 accessor；
  不碰 `right_panel.py`/Replay 调用。逐项核对原右栏数据已在 B-1/B-2/B-3 有目的地：CAN→CAN、ring/
  dropped/`rec.last_rx_age_s`→REC、disk/write→底部、preflight→pill。
- [ ] **Step 4: 跑绿 + 真机** — capture + right_panel + replay focused tests PASS；运行
  `.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/b4-columns`，确认采集三态无右栏、
  录制切换 body 零位移；再打开 Replay 验证既有右栏仍在。
- [ ] **Step 5: Commit** — `refactor(acq): drop right health pane, 2-column body, relocate metrics`

---

### Task B-5: 采集断开态清单入中央，Replay 默认不启用（B7）

**Files:**
- Modify: `widgets/live_cards.py`（为 `cockpitDisconnectedCanvas` 增加默认隐藏的结构化 checklist API）
- Modify: `main_window/window.py`（仅采集页显式开启并更新 checklist）
- Test: `tests/acquisition_ui/test_live_cards.py`、`test_state_machine.py`、`test_replay_tab.py`

- [ ] **Step 1: 写失败测试** — `set_connection_checklist(rows)` 后采集占位显示 3 个结构化状态；
  `set_connection_checklist(None)` 隐藏且不留空白高度；`ReplayTab()` 默认无 ECU 清单，调用其既有
  `set_placeholder_copy(...)` 后仍只显示 MF4 文案。
- [ ] **Step 2: 确认失败。**
- [ ] **Step 3: 实现** — API 接受 `list[(key, label, state, detail)] | None`，state 只允许
  `ok|pending|error|off`；采集主窗口从 A2L parsed / HW available / selection feasible 的结构化状态
  更新三行，不解析自由文本。默认 `None`，所以 Replay 不变。
- [ ] **Step 4: 跑绿 + 真机** — focused tests PASS；运行
  `.venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots output/b5-disconnected`，确认采集断开中央
  见清单；切到 Replay 只见`未加载 MF4`，没有 ECU 语义和多余留白。
- [ ] **Step 5: Commit** — `feat(acq): opt-in capture checklist without changing replay placeholder`

---

### Task B-6: tour 断言扩展 + 真机验收收口（B 全量）

**Files:**
- Modify: `scripts/cockpit_ui_tour.py`（`--assert` 扩 B1–B7 不变量：无右栏、pill 可弹、零位移几何、
  升级阶梯 yellow/red/ack/recovery、capture checklist 与 Replay 隔离）
- Test: 全 acquisition_ui focused 套件

- [ ] **Step 1: 扩 tour 断言** — 加 capture splitter count==2、空闲/录制 center 宽相等、popover 单实例
  与关闭矩阵、preflight 三态、yellow→red→ack→green→red 升级闭环、capture checklist；Replay 断言留在
  focused pytest，避免 tour 引入 MF4 fixture IO。
- [ ] **Step 2: 跑 offscreen tour** —
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python scripts/cockpit_ui_tour.py --assert --shots output/phase-b-offscreen`
  Expected: 全绿。这一步是自动结构门，不代替 Step 4。
- [ ] **Step 3: focused 套件**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py tests/acquisition_ui/test_live_downsampler.py tests/acquisition_ui/test_health_strip.py tests/acquisition_ui/test_escalation.py tests/acquisition_ui/test_pinned_monitoring.py tests/acquisition_ui/test_status_bar_text.py tests/acquisition_ui/test_right_panel.py tests/acquisition_ui/test_replay_tab.py tests/acquisition_ui/test_state_machine.py -q`

- [ ] **Step 4: macOS 真机截图验收（铁律）** — 运行
  `.venv/bin/python scripts/cockpit_ui_tour.py --assert --onscreen --shots output/phase-b-onscreen`；三态 +
  yellow/red/ack/recovery 各留证，确认无右栏、body 零位移、pill/popover dpr=2 锐利无灰底、red 仅进入
  时脉冲 3 次、banner 恢复即清。
- [ ] **Step 5: Commit** — `test(acq): extend cockpit tour asserts for first-principles layout`

---

## Self-Review（plan↔spec 覆盖核对）

- A1↔A-3、A2↔A-2/A-3、A3↔A-4、A4↔A-2/A-5、A5↔A-1、A6↔A-6 — 全覆盖。
- B1↔B-1、B2↔B-2、B3/B4↔B-4、B5/B6↔B-3、B7↔B-5，B-6 汇总验收 — 全覆盖。
- 命名一致：`_LIVE_WINDOW_S`（A-2 定义，A-3/A-5 消费）、`_build_polyline`/`_spark_scale`（A-3/A-4）、
  `HealthChip.clicked`/`HealthPopover`（B-1，B-2 消费）、`escalation_state(snapshot, disk_free_bytes)`
  （B-3）、`set_connection_checklist(...)`（B-5，默认关闭）。
- Replay 边界：`right_panel.py` 保留；共享 `LiveCardGrid` 新能力默认关闭；B-4/B-5/B-6 都跑
  `test_replay_tab.py`。
- 验收分层：A/B 各有 offscreen `--assert` 自动门与显式 `--onscreen` 真机门；任何未带 `--onscreen` 的
  screenshot 不得记作真机证据。
