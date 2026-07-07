# Cockpit 渲染审查修复 — Implementation Plan

> **For agentic workers (Codex):** 按任务顺序执行，checkbox 跟踪进度。每个任务
> 自带测试闭环：先写失败测试 → 实现 → 跑绿 → commit。不要跨任务合并 commit。
> 全程不要 `run_in_background` 跑全量 pytest（TCC 教训）；用前台命令。

Date: 2026-07-07
Spec: `docs/analyzer/acquisition/specs/2026-07-07-cockpit-render-review-fixes-spec.md`

**Goal:** 修掉渲染审查实证的 3 个 P0（sparkline 时基裁剪恒空白、空闲 ring 无消费
者锁死录制+幽灵弹窗、左栏勾选滚动跳顶）与 F4–F13 一批 P1/P2，并把审查驱动脚本
收编为 `scripts/cockpit_ui_tour.py --assert` 端到端验收门。

**Architecture:** 全部是 UI 层/显示层修复：卡片 trim 改流时间基准（下限从缓冲
自身最新样本导出）；ring 收缩为录制路径专属、auto-stop 权威回归 controller 的
5s sustain；左栏改增量行更新；健康灯加 no-evidence 证据位（frozen dataclass 追加
默认字段）。capture core 的录制契约（controller/writer/stop-flush-finalize）
不动。

**Tech Stack:** PyQt5 + pytest-qt（offscreen）。无新依赖。

## Global Constraints

- 命令一律用 `.venv/bin/python`（如 `.venv/bin/python -m pytest ...`）。
- 不要 `run_in_background` 跑 pytest；全部前台。
- 样本形状全链路 `(channel_name, timestamp, value)`。
- `ui_kit` 不得 import `ui.*` / `acquisition_ui.*`。
- 既有 objectName 全部保留（QSS `cockpit*` / `review*` / `measurement*` 选择器在用）。
- probe/后端的英文错误串（如 `"transport not configured"`）**原样保留**——
  `tests/acquisition_ui/test_record_backend_swap.py:382` 等契约在用；只翻译 UI 层
  自有文案。
- 文案含中文的文件 IO 显式 `encoding="utf-8"`。
- controller / ring_buffer / writer 的录制路径行为不动（本 plan 只动窗口端接线）。
- 每个任务后跑该任务的目标测试文件；Task 15 跑全量。

---

### Task 1: F1 — 卡片时间基准（sparkline 恒空白修复）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py:103,124`
- Test: `tests/acquisition_ui/test_live_cards.py`（追加）

**Interfaces:**
- Produces: `LiveSignalCard.refresh()`（无参）；`LiveCardGrid.refresh_all()`
  （无参）；`LiveCardGrid.reset_buffers() -> None`。Task 4/15 依赖
  `reset_buffers`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/acquisition_ui/test_live_cards.py`，
  沿用该文件既有 fixture 风格；若文件用 `qtbot`，参数写 `qtbot`）

```python
def test_idle_refresh_keeps_stream_time_samples(qtbot):
    """样本 ts 是流相对秒（0~n）；refresh 后必须保留（spec 2026-07-07 §F1）。"""
    card = LiveSignalCard("MotSpd", unit="rpm", raster="event_10ms")
    qtbot.addWidget(card)
    for i in range(100):
        card.push_sample(i * 0.01, float(i))
    card.refresh()
    assert card._spark.sample_count == 100
    assert "max 99.00" in card._stats_label.text()


def test_idle_refresh_trims_to_last_60s_of_stream_time(qtbot):
    """trim 下限 = 缓冲最新样本 ts - 60，与 wall clock 无关。"""
    card = LiveSignalCard("MotSpd")
    qtbot.addWidget(card)
    for t in (0.0, 30.0, 70.0, 100.0, 119.0):
        card.push_sample(t, 1.0)
    card.refresh()
    kept = [ts for ts, _ in card._spark._buffer]
    assert kept == [70.0, 100.0, 119.0]


def test_set_recording_true_resets_buffer(qtbot):
    """录制起点即缓冲起点：进录制清空，退录制不清（spec §F1）。"""
    card = LiveSignalCard("MotSpd")
    qtbot.addWidget(card)
    card.push_sample(1.0, 5.0)
    card.set_recording(True, 12345.0)
    assert card._spark.sample_count == 0
    card.push_sample(0.1, 7.0)
    card.set_recording(False)
    assert card._spark.sample_count == 1


def test_grid_reset_buffers(qtbot):
    grid = LiveCardGrid()
    qtbot.addWidget(grid)
    grid.set_signals([("A", "", None), ("B", "", None)])
    grid.push_sample("A", 0.0, 1.0)
    grid.push_sample("B", 0.0, 2.0)
    grid.reset_buffers()
    assert all(c._spark.sample_count == 0 for c in grid.cards.values())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -v -k "stream_time or resets_buffer or reset_buffers"`
Expected: FAIL（`refresh()` 现在要求 `now_ts` 关键字用法不同 / 缓冲被裁光 /
`reset_buffers` 不存在）。

- [ ] **Step 3: 实现**

`live_cards.py` — `LiveSignalCard.refresh` 整体替换为：

```python
    def refresh(self) -> None:
        """Recompute stats label and trim the idle rolling window.

        Time-base invariant (2026-07-07 spec §F1): the trim floor is
        derived from the buffer's own newest sample (stream time) —
        never from a wall clock. Recording mode never trims: the
        cumulative-since-rec-start window is realised by clearing the
        buffer in :meth:`set_recording`.
        """
        if self._recording:
            label = STATS_WINDOW_LABEL_RECORDING
            t_min: float | None = None
        else:
            label = STATS_WINDOW_LABEL_IDLE
            buf = self._spark._buffer  # noqa: SLF001 - sibling widget.
            t_min = (buf[-1][0] - _IDLE_WINDOW_S) if buf else None
        self._spark.trim_to_window(t_min)
        self._spark.request_repaint()
        self._stats_label.setToolTip(f"Stats window: {label}")

        values = [v for _, v in list(self._spark._buffer)]  # noqa: SLF001 - sibling widget.
        if not values:
            self._stats_label.setText("μ — · σ — · max —")
            return
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(var)
        peak = max(values)
        self._stats_label.setText(
            f"μ {mean:.2f} · σ {std:.2f} · max {peak:.2f}"
        )
```

`LiveSignalCard.set_recording` 里：`self._recording = bool(recording)` 之后加
清空逻辑，并把末尾 `self.refresh(now_ts=None)` 改为 `self.refresh()`：

```python
        self._recording = bool(recording)
        self._rec_start_ts = rec_start_ts if recording else None
        if self._recording:
            # Spec §F1: recording 的 cumulative 窗口从清空后的缓冲开始，
            # 同时消除 controller 重启后端导致的 ts 归零交错。
            self._spark.reset()
```

`LiveCardGrid` 追加方法（放在 `refresh_all` 旁）并改 `refresh_all` 签名：

```python
    def refresh_all(self) -> None:
        for card in self._cards.values():
            card.refresh()

    def reset_buffers(self) -> None:
        """Clear every card's sparkline buffer.

        必须在底层流每次 (re)start 时调用（spec §F1 不变量）：
        `_resume_idle_stream`、空闲选择变更重启（Task 4）。
        """
        for card in self._cards.values():
            card.reset_buffer()
```

`_polling_mixin.py` 两处调用点：`_poll_live` 里
`self._center.refresh_all(now_ts=time.monotonic())` → `self._center.refresh_all()`；
`_poll_live_recording` 里同样改为 `self._center.refresh_all()`。

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -v`
Expected: 全 PASS（含既有用例；若既有用例传了 `refresh(now_ts=...)` /
`refresh_all(now_ts=...)`，同步删掉该实参——语义不变）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/live_cards.py mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py tests/acquisition_ui/test_live_cards.py
git commit -m "fix(acquisition): sparkline trim uses stream-time base, not wall clock"
```

---

### Task 2: F2a — 空闲态不入 ring + 状态栏 idle 去 buf

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py:97-107`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py:231-236`
- Test: `tests/acquisition_ui/test_status_bar_text.py:29`（更新）+ 新用例

**Interfaces:**
- Produces: 空闲态 `ring.level_pct` 恒 0 —— Task 3/15 的验收依赖。

- [ ] **Step 1: 更新/新增测试**

`test_status_bar_text.py:29` 的断言改为：

```python
        assert window.statusBar().currentMessage() == "streaming · 0 evt/s"
```

同文件追加：

```python
def test_idle_polling_does_not_fill_ring(qtbot):
    """spec 2026-07-07 §F2: ring 是录制路径专属；空闲轮询不得入队。"""
    window = _make_idle_window(qtbot)  # 沿用本文件既有的 idle 构造 helper；
    # 若无现成 helper，用与 line 29 用例相同的构造/转态样板。
    for _ in range(20):
        window._poll_live()
    assert window.ring_buffer.level_pct == 0.0
```

（`_make_idle_window` 指本文件把窗口驱动到 CONNECTED_IDLE 的既有样板代码；
与 line 29 用例同一套，抽不抽 helper 都行，断言不变。）

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_status_bar_text.py -v`
Expected: 两处 FAIL（旧文案含 buf；ring level > 0）。

- [ ] **Step 3: 实现**

`_polling_mixin.py` `_poll_live` 的样本循环与计数段替换为：

```python
        for channel, ts, value in samples:
            # Spec 2026-07-07 §F2: ring 是录制路径专属结构；空闲流只喂卡片。
            self._center.push_sample(channel, ts, value)
        # Repaint sparklines.
        self._center.refresh_all()
        # Update cumulative counters.
        self._cumulative_rx_count += len(samples)
        if self._state_machine.state == CockpitState.RECORDING:
            # 无 controller 的 legacy 录制路径才走到这里；保留丢帧同步。
            self._cumulative_dropped = self._ring.dropped_frames
```

`_settings_mixin.py` `_update_status_bar` 的 CONNECTED_IDLE 分支替换为：

```python
        if state == CockpitState.CONNECTED_IDLE:
            self._status.showMessage(
                f"streaming · {self._event_rate_per_s()} evt/s"
            )
            return
```

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_status_bar_text.py tests/acquisition_ui/test_demo_smoke.py -v`
Expected: test_status_bar_text 全 PASS。`test_demo_smoke` 若因 watermark 用例
失败，属 Task 3 范围——只允许那一个失败，其余必须绿。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py tests/acquisition_ui/test_status_bar_text.py
git commit -m "fix(acquisition): idle polling no longer fills the ring buffer"
```

---

### Task 3: F2b — watermark 只降帧；auto-stop 权威回归 controller

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py:141-151,161-245`
- Modify: `mf4_analyzer/acquisition_ui/__main__.py:76-80`（self-test 注释核对，行为不变）
- Test: `tests/acquisition_ui/test_demo_smoke.py:70-80`（重写）、
  `tests/acquisition_ui/test_state_machine.py:513-543`（重写）

**Interfaces:**
- Consumes: controller 侧 `_check_auto_stop`（5s sustain，已存在，不动）。
- Produces: `_on_ring_watermark_changed` 只调 `set_target_fps`；
  `_on_auto_stop_request` 仅在 RECORDING 态做事。

- [ ] **Step 1: 重写编码了错误契约的两个测试**

`test_demo_smoke.py::test_red_drop_sustained_emits_auto_stop` 整体替换为：

```python
def test_red_drop_sustained_only_degrades_fps(qapp):
    """spec 2026-07-07 §F2: 瞬时 watermark 只降帧，绝不 auto-stop。

    5s sustain 的 auto-stop 权威在 CaptureController._check_auto_stop。
    """
    window = CockpitMainWindow()
    fired = []
    window.auto_stop_requested.connect(lambda reason: fired.append(reason))
    window._ring.watermark_changed.emit("red_drop_sustained")
    assert window._target_fps == 10
    assert fired == []
    assert window._review_modal is None
    window.close()
```

`test_state_machine.py:513-543`（CR2 fix #6 的 watermark auto-stop 段）替换为
controller 驱动的接线测试（保留该段原有的 import/fixture 风格）：

```python
class _AutoStoppedController:
    """poll_step 后 running=False + auto_stopped=True 的最小桩。"""

    running = False
    auto_stopped = True

    def poll_step(self) -> int:
        return 0


def test_controller_auto_stop_routes_to_stop_and_review(qapp, monkeypatch):
    """spec 2026-07-07 §F2: controller sustain 判定 → stop&review(auto_stop=True)。"""
    window = CockpitMainWindow()
    calls: list[bool] = []
    monkeypatch.setattr(
        window,
        "request_stop_and_review",
        lambda *, auto_stop=False: calls.append(auto_stop),
    )
    window._poll_live_recording(_AutoStoppedController())
    assert calls == [True]
    window.close()
```

该段内其余直接 `watermark_changed.emit("red_drop_sustained")` 后断言
`controller.stop()`/弹窗的用例一并删除（契约已由上面两条覆盖）。

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_demo_smoke.py tests/acquisition_ui/test_state_machine.py -v`
Expected: 新 fps 用例 FAIL（现实现会发 auto_stop_requested 并开 placeholder）。

- [ ] **Step 3: 实现**

`_polling_mixin.py` `_on_ring_watermark_changed` 整体替换：

```python
    def _on_ring_watermark_changed(self, level: WatermarkLevel) -> None:
        """Bridge from the non-Qt observer to Qt slots — FPS only.

        Auto-stop authority（spec 2026-07-07 §F2）：录制中 ≥95% 持续 5s 由
        CaptureController._check_auto_stop 判定；磁盘余量由
        _check_recording_auto_stop 判定。瞬时 watermark 水位不得停录制。
        """
        if level in ("green", "yellow_low"):
            self.set_target_fps(thresholds.LIVE_FPS_NORMAL)
        else:
            self.set_target_fps(thresholds.LIVE_FPS_DEGRADED)
```

`_on_auto_stop_request` 删除非 RECORDING 死臂（placeholder 弹窗 + 空闲
controller.stop），整体替换为：

```python
    def _on_auto_stop_request(self, reason: str) -> None:
        """Auto-stop entry point — RECORDING 态专用（spec 2026-07-07 §F2）。

        调用方：磁盘余量判定 `_check_recording_auto_stop`（`_poll_health`
        已 gate 到 RECORDING）。controller 的 sustain auto-stop 不走这里
        （`_poll_live_recording` 直接检测 `controller.running`）。
        """
        self.auto_stop_requested.emit(reason)
        self._status.showMessage(f"自动停止已请求 ({reason})")
        if self._state_machine.state != CockpitState.RECORDING:
            return
        self.request_stop_and_review(auto_stop=True)
        if self._last_session_summary is None:
            self._last_session_summary = SessionSummary(auto_stop=True)
        else:
            self._last_session_summary.auto_stop = True
        if (
            self._state_machine.state == CockpitState.RECORDING
            and self._capture_controller is not None
        ):
            # stop/flush/finalize 中途抛异常时仍要终结四态循环。
            self._state_machine.request_stop_recording(finalized=True)
```

同时删掉该文件顶部现在多余的 `from .window import _PlaceholderReviewModal`
懒导入（在被删的死臂里）。

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_demo_smoke.py tests/acquisition_ui/test_state_machine.py tests/acquisition_ui/test_dropped_frame_prompt.py tests/acquisition_ui/test_stop_flush_finalize.py -v`
Expected: 全 PASS。另跑 self-test 冒烟：
`.venv/bin/python -m mf4_analyzer.acquisition_ui --demo --self-test`，期望 exit 0。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/_polling_mixin.py tests/acquisition_ui/test_demo_smoke.py tests/acquisition_ui/test_state_machine.py
git commit -m "fix(acquisition): watermark only degrades FPS; auto-stop authority is the controller"
```

---

### Task 4: F5 — 空闲选择变更 debounce 重启流 + 计数重置

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`（`__init__` 计时器
  + `_on_selection_changed`）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py`
  （新方法 + `_resume_idle_stream` 重置）
- Test: `tests/acquisition_ui/test_capture_session.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `LiveCardGrid.reset_buffers()`。
- Produces: `CockpitMainWindow._restart_idle_stream_for_selection()`（tour 脚本
  Task 15 直接调用以绕过 debounce 等待）。

- [ ] **Step 1: 写失败测试**（追加到 `test_capture_session.py`）

```python
class _SpyFakeBackend(FakeRecorderBackend):
    def __init__(self) -> None:
        super().__init__()
        self.start_calls: list[tuple[str, ...]] = []

    def start(self, selected):
        self.start_calls.append(tuple(m.name for m in selected))
        super().start(selected)


def test_idle_selection_change_restarts_stream(qtbot):
    """spec 2026-07-07 §F5: 空闲态新勾通道必须重启后端流并清卡片缓冲。"""
    backend = _SpyFakeBackend()
    pool = (
        MeasurementSummary(
            name="A", address=0x40000000, datatype="UWORD", unit="",
            conversion="", available_events=("event_10ms",),
        ),
        MeasurementSummary(
            name="B", address=0x40000004, datatype="UWORD", unit="",
            conversion="", available_events=("event_10ms",),
        ),
    )
    window = CockpitMainWindow(
        backend=backend, initial_pool=pool, allow_fake_backend=True
    )
    qtbot.addWidget(window)
    window.left_pane._set_measurement_selected("A", True)
    window._begin_connection_attempt()
    window._poll_live()      # 首帧
    window._poll_health()    # healthy → CONNECTED_IDLE
    assert window.state_machine.state == CockpitState.CONNECTED_IDLE

    window.left_pane._set_measurement_selected("B", True)
    assert window._idle_restart_timer.isActive()
    window._restart_idle_stream_for_selection()  # 绕过 300ms debounce
    assert backend.start_calls[-1] == ("A", "B")
    window._poll_live()
    assert window._center.cards["B"]._spark.sample_count > 0
    window.close()
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -v -k restarts_stream`
Expected: FAIL（`_idle_restart_timer` 不存在）。

- [ ] **Step 3: 实现**

`window.py` `__init__` 的 timers 段（`self._live_timer` 之后）追加：

```python
        # F5: 空闲态选择变更 → debounce 重启空闲流（spec 2026-07-07 §F5）。
        self._idle_restart_timer = QTimer(self)
        self._idle_restart_timer.setSingleShot(True)
        self._idle_restart_timer.setInterval(300)
        self._idle_restart_timer.timeout.connect(
            self._restart_idle_stream_for_selection
        )
```

`window.py` `_on_selection_changed` 的 CONNECTED_IDLE 分支末尾追加：

```python
            self._idle_restart_timer.start()
```

`_capture_session_mixin.py` 顶部补 import：

```python
from mf4_analyzer.acquisition_ui.state import CockpitState
```

新方法（放 `_resume_idle_stream` 之前）：

```python
    def _restart_idle_stream_for_selection(self) -> None:
        """Debounced idle-stream restart after a selection edit (spec §F5).

        空闲流只携带 connect 时传给 ``backend.start`` 的通道；空闲态新勾的
        通道不重启就永远无数据。best-effort：失败走状态栏，不弹窗。
        """
        if self._state_machine.state != CockpitState.CONNECTED_IDLE:
            return
        if self._capture_controller is not None:
            return
        selection = list(self._left_pane.current_selection())
        if not selection:
            selection = [SelectedMeasurement(name="DemoSignal")]
        try:
            self._backend.start(selection)
        except Exception as exc:  # noqa: BLE001 - best-effort restart
            logger.warning("idle stream restart failed: %s", exc)
            self._status.showMessage(f"实时流重启失败: {exc}")
            return
        self._center.reset_buffers()
        self._stream_start_ts = time.monotonic()
        self._cumulative_rx_count = 0
```

`_resume_idle_stream` 的 `self._backend.start(selection)` 成功路径（try 之后）
追加同样的重置三行：

```python
        self._center.reset_buffers()
        self._stream_start_ts = time.monotonic()
        self._cumulative_rx_count = 0
```

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_capture_session.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/window.py mf4_analyzer/acquisition_ui/main_window/_capture_session_mixin.py tests/acquisition_ui/test_capture_session.py
git commit -m "fix(acquisition): restart idle stream on selection change so new cards get data"
```

---

### Task 5: F3 — 左栏增量更新 + 滚动保持 + 冻结即时置灰

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
- Test: `tests/acquisition_ui/test_left_pane.py`（追加）

**Interfaces:**
- Produces: `LeftPane._update_row_for(name: str) -> None`；
  `LeftPane._row_items: dict[str, QListWidgetItem]`。

- [ ] **Step 1: 写失败测试**（追加到 `test_left_pane.py`；`_make_pool` 若该文件
  已有等价 helper 就复用）

```python
def _make_pool(n: int) -> tuple[MeasurementSummary, ...]:
    return tuple(
        MeasurementSummary(
            name=f"Sig_{i:02d}", address=0x40000000 + 4 * i, datatype="UWORD",
            unit="", conversion="", available_events=("event_10ms", "event_100ms"),
        )
        for i in range(n)
    )


def test_checkbox_toggle_preserves_scroll_and_widgets(qtbot):
    """spec 2026-07-07 §F3: 勾选不重建列表、不动滚动条。"""
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(50))
    pane.resize(420, 400)
    pane.show()
    qtbot.waitExposed(pane)
    sb = pane._list.verticalScrollBar()
    sb.setValue(sb.maximum())
    anchor = sb.value()
    assert anchor > 0
    last_item = pane._list.item(pane._list.count() - 1)
    widget_before = pane._list.itemWidget(last_item)
    checkbox = widget_before.findChild(QCheckBox, "measurementCheckBox")
    checkbox.click()
    assert sb.value() == anchor
    assert pane._list.itemWidget(pane._list.item(pane._list.count() - 1)) is widget_before
    assert [m.name for m in pane.current_selection()] == ["Sig_49"]


def test_batch_event_change_updates_rows_in_place(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    for name in ("Sig_00", "Sig_01"):
        pane._set_measurement_selected(name, True)
    item = pane._row_items["Sig_01"]
    widget_before = pane._list.itemWidget(item)
    combo = pane._batch_bar.event_combo
    idx = combo.findData("event_100ms")
    combo.setCurrentIndex(idx)
    assert pane._list.itemWidget(pane._row_items["Sig_01"]) is widget_before
    row_combo = widget_before.findChild(QComboBox, "measurementEventSelect")
    assert row_combo.currentData() == "event_100ms"


def test_set_frozen_disables_row_controls_in_place(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(3))
    pane.set_frozen(True)
    for item in pane._row_items.values():
        row = pane._list.itemWidget(item)
        assert not row.findChild(QCheckBox, "measurementCheckBox").isEnabled()
        assert not row.findChild(QComboBox, "measurementEventSelect").isEnabled()
    pane.set_frozen(False)
    row = pane._list.itemWidget(pane._row_items["Sig_00"])
    assert row.findChild(QCheckBox, "measurementCheckBox").isEnabled()


def test_only_selected_rebuild_restores_scroll(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(50))
    pane.resize(420, 400)
    pane.show()
    qtbot.waitExposed(pane)
    for i in range(40, 50):
        pane._set_measurement_selected(f"Sig_{i}", True)
    pane._only_selected_chip.setChecked(True)
    sb = pane._list.verticalScrollBar()
    sb.setValue(sb.maximum())
    anchor = sb.value()
    pane._set_measurement_selected("Sig_49", False)  # 行消失 → 全量重建
    assert sb.value() == min(anchor, sb.maximum())
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py -v -k "preserves_scroll or in_place or restores_scroll"`
Expected: FAIL（滚动跳 0 / `_row_items` 不存在 / widget 身份变化）。

- [ ] **Step 3: 实现**

`left_pane.py` `__init__` 状态段追加：

```python
        self._row_items: dict[str, QListWidgetItem] = {}
```

`_refresh_list` 整体替换：

```python
    def _refresh_list(self) -> None:
        # 全量重建仅限 pool/搜索/过滤变更；勾选/事件走 _update_row_for
        # （spec 2026-07-07 §F3）。重建必须保存并恢复滚动位置。
        scrollbar = self._list.verticalScrollBar()
        previous_scroll = scrollbar.value()
        self._list.blockSignals(True)
        self._list.clear()
        self._row_items = {}
        pool = self._filtered_pool()
        hits, used_search = self._hits_for_query(pool)
        rows: list[tuple[MeasurementSummary, list[tuple[int, int]]]]
        if used_search:
            rows = [(hit.measurement, hit.match_spans) for hit in hits]
        else:
            rows = [(m, []) for m in pool]
        self._visible_count = len(rows)
        for measurement, match_spans in rows:
            item = self._build_row(measurement, match_spans)
            self._list.addItem(item)
            self._list.setItemWidget(item, self._build_row_widget(measurement))
            self._row_items[measurement.name] = item
        self._list.blockSignals(False)
        scrollbar.setValue(min(previous_scroll, scrollbar.maximum()))
        self._refresh_summary()
        self._refresh_footer()
```

新增 `_update_row_for`（放 `_refresh_list` 之后）：

```python
    def _update_row_for(self, name: str) -> None:
        """原地更新单行：选中背景、checkbox、事件 combo。

        不重建、不动滚动、不更换 row widget 实例（spec §F3 不变量）。
        """
        item = self._row_items.get(name)
        measurement = self._measurement_by_name(name)
        if item is None or measurement is None:
            return
        selected = name in self._selected_names
        item.setBackground(QBrush(_SELECTED_ROW_BG) if selected else QBrush())
        row = self._list.itemWidget(item)
        if row is None:
            return
        checkbox = row.findChild(QCheckBox, "measurementCheckBox")
        if checkbox is not None:
            old = checkbox.blockSignals(True)
            checkbox.setChecked(selected)
            checkbox.blockSignals(old)
        combo = row.findChild(QComboBox, "measurementEventSelect")
        if combo is not None:
            event = self._selected_event_for(measurement)
            idx = combo.findData(event) if event is not None else -1
            if idx >= 0:
                old = combo.blockSignals(True)
                combo.setCurrentIndex(idx)
                combo.blockSignals(old)
```

`_set_measurement_selected` 尾部（`if before == self._selected_names: return`
之后）替换：

```python
        if self._only_selected_chip.isChecked():
            # 行要出现/消失 → 全量重建（滚动在 _refresh_list 内恢复）。
            self._refresh_list()
        else:
            self._update_row_for(name)
            self._refresh_summary()
            self._refresh_footer()
        self.selection_changed.emit()
```

`_set_measurement_event` 尾部 `if selected_changed or event_changed:` 分支替换：

```python
        if selected_changed or event_changed:
            self._update_row_for(name)
            self._refresh_summary()
            self._refresh_footer()
            self.selection_changed.emit()
```

`_on_batch_event_changed` 的 `if changed:` 分支替换：

```python
        if changed:
            for name in sorted(self._selected_names):
                self._update_row_for(name)
            self._refresh_footer()
            self.selection_changed.emit()
```

`_clear_context_selection` 里的 `self._refresh_list()` 保留（多行同时消失，
重建合理，滚动已在 `_refresh_list` 内恢复）。

`set_frozen` 整体替换：

```python
    def set_frozen(self, frozen: bool) -> None:
        """Recording state: A2L/raster controls become read-only.

        原地置灰全部行控件（spec §F3）——不等用户交互才回弹。
        """
        self._frozen = bool(frozen)
        self._has_daq_chip.setEnabled(self._a2l_has_daq_events and not self._frozen)
        self._only_selected_chip.setEnabled(not self._frozen)
        for item in self._row_items.values():
            row = self._list.itemWidget(item)
            if row is None:
                continue
            checkbox = row.findChild(QCheckBox, "measurementCheckBox")
            if checkbox is not None:
                checkbox.setEnabled(not self._frozen)
            combo = row.findChild(QComboBox, "measurementEventSelect")
            if combo is not None:
                combo.setEnabled(combo.count() > 0 and not self._frozen)
        self._refresh_batch_bar()
```

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py tests/acquisition_ui/test_right_click_menu.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/left_pane.py tests/acquisition_ui/test_left_pane.py
git commit -m "fix(acquisition): incremental left-pane row updates, scroll preserved, frozen grays out in place"
```

---

### Task 6: F4 — `&` 助记符转义

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py:400`
- Modify: `mf4_analyzer/acquisition_ui/settings_dialog.py:344`
- Test: `tests/acquisition_ui/test_visual_shell.py`（追加）

- [ ] **Step 1: 写失败测试**（追加到 `test_visual_shell.py`）

```python
def test_stop_button_ampersand_escaped(qtbot):
    """spec 2026-07-07 §F4: '&' 必须写 '&&'，否则 Qt 吞成助记符。"""
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    sm = window.state_machine
    sm.request_connect(HealthyPredicateResult.from_components(
        hw_ok=True, xcp_connected=True, first_frame_received=True))
    sm.request_start_recording()
    assert window.main_button.text() == "■ Stop && 复盘"
    window.close()
```

（import 沿用该文件已有的 `CockpitMainWindow`；`HealthyPredicateResult` 从
`mf4_analyzer.acquisition_ui.state` import。）

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_visual_shell.py -v -k ampersand`
Expected: FAIL（现值 `"■ Stop & 复盘"`）。

- [ ] **Step 3: 实现**

`window.py:400`：`self._main_btn.setText("■ Stop & 复盘")` →
`self._main_btn.setText("■ Stop && 复盘")`。
`settings_dialog.py:344`：`layout.addRow("Seed&Key DLL", seed_row)` →
`layout.addRow("Seed&&Key DLL", seed_row)`。

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_visual_shell.py tests/acquisition_ui/test_settings_transport_tab.py -v`
Expected: 全 PASS（若 transport tab 测试断言了旧 label 文本，同步更新为
`"Seed&&Key DLL"`）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/window.py mf4_analyzer/acquisition_ui/settings_dialog.py tests/acquisition_ui/test_visual_shell.py
git commit -m "fix(acquisition): escape & in Stop button and Seed&Key label"
```

---

### Task 7: F6 — 预检「磁盘剩余」标题 + 时长人性化

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
- Test: `tests/acquisition_ui/test_right_panel.py`（追加）

**Interfaces:**
- Produces: `right_panel._humanize_duration_s(seconds: float) -> str`（模块级）。

- [ ] **Step 1: 写失败测试**

```python
def test_humanize_duration_bands():
    from mf4_analyzer.acquisition_ui.widgets.right_panel import _humanize_duration_s
    assert _humanize_duration_s(float("inf")) == "∞"
    assert _humanize_duration_s(45 * 60) == "45.0 min"
    assert _humanize_duration_s(5 * 3600) == "5.0 h"
    assert _humanize_duration_s(3 * 86400) == "3.0 d"


def test_idle_page_titles(qtbot):
    page = IdlePreflightPage()
    qtbot.addWidget(page)
    titles = [
        lab.text()
        for lab in page.findChildren(QLabel, "rightMetricTitle")
    ]
    assert "磁盘剩余" in titles
    assert "预计可录时长" in titles
    assert "磁盘写速" not in titles
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_right_panel.py -v -k "humanize or idle_page_titles"`
Expected: FAIL。

- [ ] **Step 3: 实现**

`right_panel.py` 模块级（`_format_band_value` 之后）新增：

```python
def _humanize_duration_s(seconds: float) -> str:
    """人性化时长（spec 2026-07-07 §F6）：∞ / min / h / d 四档。"""
    if seconds == float("inf"):
        return "∞"
    minutes = seconds / 60.0
    if minutes < 90.0:
        return f"{minutes:.1f} min"
    hours = minutes / 60.0
    if hours < 48.0:
        return f"{hours:.1f} h"
    return f"{hours / 24.0:.1f} d"
```

`IdlePreflightPage.__init__`：`"磁盘写速"` → `"磁盘剩余"`；`"输出"` →
`"预计可录时长"`。

`IdlePreflightPage.apply` 的 duration 段替换：

```python
        throughput = estimate_throughput_bps(selection)
        duration_s = estimate_record_duration_s(throughput, disk_free_bytes)
        if duration_s == float("inf"):
            self._row_duration.setText(_format_band_value("off", "∞"))
        else:
            self._row_duration.setText(
                _format_band_value(
                    band_record_duration_s(duration_s),
                    _humanize_duration_s(duration_s),
                )
            )
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_right_panel.py -v`
Expected: 全 PASS（若既有用例断言 `" min"` 旧格式，按新格式更新）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/right_panel.py tests/acquisition_ui/test_right_panel.py
git commit -m "fix(acquisition): idle preflight disk label and humanized duration"
```

---

### Task 8: F7 — no-evidence 灰灯

**Files:**
- Modify: `mf4_analyzer/acquisition_capture/health.py`（dataclass 字段 + level 函数）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`（探针置位）
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`（`__init__` 加
  `_connection_ever_attempted`；`_begin_connection_attempt` 置 True）
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
  （DisconnectedPage UI 文案本地化）
- Test: `tests/test_acquisition_capture_health.py` 或
  `tests/acquisition_ui/test_health_strip.py`（追加）

**Interfaces:**
- Produces: `HwHealth.probed: bool = True`、`XcpHealth.attempted: bool = True`、
  `RecHealth.evidence: bool = True`（frozen dataclass 追加默认字段，既有构造点
  零改动）。

- [ ] **Step 1: 写失败测试**（level 函数单测放 health 测试文件；集成断言放
  `test_health_strip.py`）

```python
def test_level_no_evidence_maps_to_off():
    """spec 2026-07-07 §F7: 无证据 → off；报警色只给尝试过且失败。"""
    hw = HwHealth(ok=False, driver_version=None, channel_count=0,
                  last_probe_ts=time.monotonic(), error="transport not configured",
                  probed=False)
    assert level_hw(hw) == "off"
    assert level_xcp(XcpHealth(connected=False, attempted=False)) == "off"
    assert level_xcp(XcpHealth(connected=False, attempted=True)) == "red"
    assert level_daq(DaqHealth()) == "off"
    rec = RecHealth(state="off", ring_buffer_fill_pct=0.0, dropped_frames=0,
                    write_rate_bps=0.0, last_rx_age_s=0.0,
                    writer_thread_alive=False, evidence=False)
    assert level_rec(rec) == "off"


def test_fresh_cockpit_shows_all_chips_off(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window._poll_health()
    levels = window.health_strip.current_levels()
    assert set(levels.values()) == {"off"}
    assert window.health_strip._summary.text() == "5 off"
    window.close()
```

- [ ] **Step 2: 确认失败** — Run 上述两个测试文件 `-k "no_evidence or all_chips_off"`。
Expected: FAIL（TypeError 未知字段 / DAQ green / HW red）。

- [ ] **Step 3: 实现**

`health.py` dataclass 追加字段（各类末尾）：

```python
class HwHealth:
    ...
    error: str | None = None
    probed: bool = True   # False = 从未探测（无 transport 且未尝试连接）

class XcpHealth:
    ...
    consecutive_timeouts: int = 0
    attempted: bool = True  # False = 从未发起过连接尝试

class RecHealth:
    ...
    writer_thread_alive: bool
    evidence: bool = True   # False = 从未收到帧且非录制
```

level 函数：

```python
def level_hw(snap, *, now=None, poll_interval_s=None) -> HealthLevel:
    if not snap.probed:
        return "off"
    ...（其余不动）

def level_xcp(snap: XcpHealth) -> HealthLevel:
    if not snap.connected and not snap.attempted:
        return "off"
    ...（其余不动）

def level_daq(snap: DaqHealth) -> HealthLevel:
    if snap.overflow:
        return "red"
    if not snap.event_capacity:
        return "off"
    return "green"

def level_rec(snap: RecHealth) -> HealthLevel:
    if snap.state == "off" and not snap.evidence:
        return "off"
    ...（其余不动）
```

`window.py` `__init__`（core state 段）追加：

```python
        self._connection_ever_attempted = False
```

`_connection_mixin.py` `_begin_connection_attempt` 在
`self._connection_attempt_started = time.monotonic()` 处一起置：

```python
        self._connection_ever_attempted = True
```

探针置位：

```python
    def _probe_hw(self) -> HwHealth:
        ...
        if self._transport_config is None:
            return HwHealth(
                ok=False, driver_version=None, channel_count=0,
                last_probe_ts=time.monotonic(),
                error="transport not configured",
                probed=self._connection_ever_attempted,
            )
        ...

    def _probe_xcp(self) -> XcpHealth:
        return XcpHealth(
            connected=self._fake_xcp_connected,
            slave_id=0x55 if self._fake_xcp_connected else None,
            last_response_age_s=0.0,
            consecutive_timeouts=0,
            attempted=self._connection_ever_attempted,
        )

    def _probe_rec(self) -> RecHealth:
        ...（last_age 计算不动）
        return RecHealth(
            state=self._fake_rec_state,  # type: ignore[arg-type]
            ring_buffer_fill_pct=self._ring.level_pct,
            dropped_frames=self._ring.dropped_frames,
            write_rate_bps=0.0,
            last_rx_age_s=last_age,
            writer_thread_alive=self._fake_rec_state == "recording",
            evidence=(
                self._fake_last_rx_monotonic is not None
                or self._fake_rec_state != "off"
            ),
        )
```

（demo 路径的 `_probe_hw` 首分支 `ok=True` 不用动——它本身就 gate 在
`connection_attempt_started is not None or _fake_xcp_connected`。）

`right_panel.py` `DisconnectedPage.apply` 的 UI 自有文案本地化：
`"ok"` → `"正常"`、`"connected"` → `"已连接"`、`"断开"` → `"未连接"`。
（`snapshot.hw.error or "未连接"` 的 error 透传保留英文原样。）

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_health_strip.py tests/acquisition_ui/test_right_panel.py tests/test_acquisition_capture_health.py -v`
（health 单测文件名以 `ls tests/ | grep health` 实际为准；断言旧 green/red
预期的既有用例按新契约更新——只允许「无证据态」的预期变化。）
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_capture/health.py mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py mf4_analyzer/acquisition_ui/main_window/window.py mf4_analyzer/acquisition_ui/widgets/right_panel.py tests/
git commit -m "fix(acquisition): no-evidence health maps to gray, alarms only after an attempt"
```

---

### Task 9: F8 — 写入速率真值 + 状态栏「缓冲中」

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`
  （`_probe_rec` 差分）
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`（`__init__` 加
  `_write_rate_prev`）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py`
  （状态栏 MB 段）
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py`
  （RecordingQualityPage）
- Test: `tests/acquisition_ui/test_status_bar_text.py:40`（更新）、
  `tests/acquisition_ui/test_right_panel.py`（追加）

- [ ] **Step 1: 更新/新增测试**

`test_status_bar_text.py:40` 期望串改为：

```python
            "RECORDING · 00:00 · 0 samples · 缓冲中 · drop 0 · buf 0.0%"
```

`test_right_panel.py` 追加：

```python
def test_recording_write_rate_display(qtbot):
    page = RecordingQualityPage()
    qtbot.addWidget(page)
    snap = _make_snapshot(write_rate_bps=123.0)  # 沿用本文件既有 snapshot helper
    page.apply(snapshot=snap, disk_free_bytes=10 * 1024 ** 3)
    assert "123 样本/s" in page._row_write.text()
    snap0 = _make_snapshot(write_rate_bps=0.0)
    page.apply(snapshot=snap0, disk_free_bytes=10 * 1024 ** 3)
    assert "—" in page._row_write.text()
```

（`_make_snapshot` 指该文件既有构造 HealthSnapshot 的 helper；没有就按
`HealthSnapshot(hw=..., can=..., xcp=..., daq=..., rec=RecHealth(...),
captured_at=0.0)` 全字段写一个。）

- [ ] **Step 2: 确认失败** — 跑上述两个文件。Expected: FAIL。

- [ ] **Step 3: 实现**

`window.py` `__init__`（core state 段）追加：

```python
        # F8: writer.write_count 差分 → 写入速率（样本/s）。
        self._write_rate_prev: tuple[int, float] | None = None
```

`_connection_mixin.py` `_probe_rec` 里 `write_rate_bps=0.0` 替换为差分计算
（return 之前插入）：

```python
        write_rate = 0.0
        if self._capture_controller is not None and self._fake_rec_state == "recording":
            try:
                count = int(self._capture_controller.writer.write_count)
            except Exception:  # noqa: BLE001 - 注入的测试 controller 可能不完整
                count = None
            if count is not None:
                now = time.monotonic()
                if self._write_rate_prev is not None:
                    prev_count, prev_ts = self._write_rate_prev
                    dt = now - prev_ts
                    if dt > 0:
                        write_rate = max(0.0, (count - prev_count) / dt)
                self._write_rate_prev = (count, now)
        else:
            self._write_rate_prev = None
```

并把 `write_rate_bps=0.0` 改为 `write_rate_bps=write_rate`（语义 = 样本/s，
在 `RecHealth` 字段注释处补一句 `# 语义：样本/s（2026-07-07 §F8）`）。

`right_panel.py` `RecordingQualityPage.__init__`：`"write rate"` →
`"写入速率"`。`apply` 的 write 行替换：

```python
        if rec.write_rate_bps > 0:
            self._row_write.setText(
                _format_band_value("green", f"{rec.write_rate_bps:.0f} 样本/s")
            )
        else:
            self._row_write.setText(_format_band_value("off", "—"))
```

`_settings_mixin.py` `_update_status_bar` RECORDING 分支替换：

```python
        if state == CockpitState.RECORDING:
            elapsed = self._recording_elapsed_text()
            size_mb = self._recording_file_size_mb()
            size_part = f"{size_mb:.1f} MB" if size_mb > 0 else "缓冲中"
            self._status.showMessage(
                f"RECORDING · {elapsed} · {self._sample_count()} samples · "
                f"{size_part} · "
                f"drop {self._cumulative_dropped} · buf {self._ring.level_pct:.1f}%"
            )
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_status_bar_text.py tests/acquisition_ui/test_right_panel.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py mf4_analyzer/acquisition_ui/main_window/window.py mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py mf4_analyzer/acquisition_ui/widgets/right_panel.py tests/
git commit -m "fix(acquisition): real write rate from writer deltas; status bar shows 缓冲中 before first flush"
```

---

### Task 10: F9 — 复盘弹窗：关闭按钮 + 丢弃确认 + 诊断口径

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/review_modal.py`
- Test: `tests/acquisition_ui/test_review_handoff.py`（更新 :295 + 追加）

- [ ] **Step 1: 更新/新增测试**

`test_review_handoff.py:295` `modal.do_discard()` →
`modal.do_discard(confirmed=True)`（同文件其他 `do_discard()` 调用点用
`grep -n "do_discard" tests/` 全找出来同样处理）。追加：

```python
def test_discard_requires_confirmation(qtbot, tmp_path):
    modal = _make_modal(tmp_path)  # 沿用本文件既有 modal 构造 helper
    mf4 = modal.context.mf4_path
    mf4.write_bytes(b"x")
    modal.do_discard()  # 未确认
    assert mf4.exists()
    assert modal._discard_confirm_box is not None
    modal.do_discard(confirmed=True)
    assert not mf4.exists()


def test_close_button_rejects_without_action(qtbot, tmp_path):
    modal = _make_modal(tmp_path)
    modal._btn_close.click()
    assert modal.result() == QDialog.Rejected
    assert modal.chosen_action is None


def test_diagnostics_line_uses_selected_channel_count(qtbot, tmp_path):
    modal = _make_modal(tmp_path)  # expected_channels=("A", "B") 之类
    label = modal.findChild(QLabel, "reviewPreflight")
    assert f"已选通道 {len(modal.context.expected_channels)}" in label.text()
    assert "缺失" in label.text()
    assert "MDF 通道总数" in label.toolTip()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_review_handoff.py -v`
Expected: 新用例 FAIL。

- [ ] **Step 3: 实现**

`review_modal.py`：

`__init__` 状态段追加 `self._discard_confirm_box: QMessageBox | None = None`。

`_build_ui` 按钮行：`self._btn_discard.clicked.connect(self.do_discard)` 改为

```python
        self._btn_discard.clicked.connect(lambda _checked=False: self.do_discard())
```

`btn_row` 末尾（analyzer 按钮之后）追加：

```python
        self._btn_close = QPushButton("关闭", self)
        self._btn_close.setObjectName("reviewBtnClose")
        self._btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_close)
```

`do_discard` 签名与前置替换：

```python
    def do_discard(self, *, confirmed: bool = False) -> None:
        """``丢弃（不归档）`` — 需确认后才删除（spec 2026-07-07 §F9）。

        测试可 ``do_discard(confirmed=True)`` 直达删除路径。
        """
        if not confirmed:
            self._show_discard_confirm()
            return
        ...（原删除逻辑整体保留）
```

新增（`do_discard` 之后）：

```python
    def _show_discard_confirm(self) -> None:
        """受管 window-modal 确认框（仿 _warn_a2l_load_problems 模式）。"""
        box = QMessageBox(self)
        box.setObjectName("reviewDiscardConfirm")
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("丢弃录制")
        box.setText(
            f"将删除 {self._ctx.mf4_path.name} 及其 sidecar，不可恢复。"
        )
        confirm_btn = box.addButton("确认删除", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setWindowModality(Qt.WindowModal)

        def _on_clicked(btn) -> None:
            if btn is confirm_btn:
                self.do_discard(confirmed=True)

        box.buttonClicked.connect(_on_clicked)
        self._discard_confirm_box = box
        if self.isVisible():
            box.open()
```

诊断 label 构造（`pf_text_parts` 段）替换：

```python
        pf = self._ctx.preflight
        pf_text_parts = [
            f"诊断: rows={pf.rows} · "
            f"已选通道 {len(self._ctx.expected_channels)} · "
            f"缺失 {len(pf.missing_channels)} · "
            f"fs≈{pf.estimated_fs_hz:.1f} Hz",
        ]
        if pf.problems:
            pf_text_parts.append("警告: " + " | ".join(pf.problems))
        pf_label = QLabel("\n".join(pf_text_parts), body)
        pf_label.setObjectName("reviewPreflight")
        pf_label.setWordWrap(True)
        pf_label.setToolTip(
            f"MDF 通道总数 {len(pf.channels)}（含时间通道）"
        )
        body_layout.addWidget(pf_label)
```

（原 `缺失通道 (N)` 独立行删除——计数已并入诊断行；missing 列表控件本身保留。）

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_review_handoff.py tests/acquisition_ui/test_stop_flush_finalize.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/review_modal.py tests/acquisition_ui/test_review_handoff.py
git commit -m "fix(acquisition): review modal close button, discard confirmation, honest diagnostics counts"
```

---

### Task 11: F10 — 回放 tab 占位文案 + 右栏加载前隐藏

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（新 API）
- Modify: `mf4_analyzer/acquisition_ui/replay_tab.py`（`__init__` 尾 +
  `load_file`）
- Test: `tests/acquisition_ui/test_replay_tab.py`（追加）

**Interfaces:**
- Produces: `LiveCardGrid.set_placeholder_copy(*, title, body, action)`。

- [ ] **Step 1: 写失败测试**

```python
def test_replay_placeholder_copy_is_replay_specific(qtbot):
    tab = ReplayTab()
    qtbot.addWidget(tab)
    canvas = tab._live_cards._disconnected_canvas
    title = canvas.findChild(QLabel, "cockpitDisconnectedTitle").text()
    action = canvas.findChild(QLabel, "cockpitDisconnectedAction").text()
    assert title == "未加载 MF4"
    assert "连接 ECU" not in action
    assert not tab._right_panel.isVisible()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_replay_tab.py -v -k placeholder`
Expected: FAIL。

- [ ] **Step 3: 实现**

`live_cards.py` `LiveCardGrid` 追加：

```python
    def set_placeholder_copy(self, *, title: str, body: str, action: str) -> None:
        """替换空态占位文案（spec 2026-07-07 §F10）。

        采集页保持默认；ReplayTab 装回放专属文案。
        """
        canvas = self._disconnected_canvas
        canvas.findChild(QLabel, "cockpitDisconnectedTitle").setText(title)
        canvas.findChild(QLabel, "cockpitDisconnectedCopy").setText(body)
        canvas.findChild(QLabel, "cockpitDisconnectedAction").setText(action)
```

`replay_tab.py` `__init__` 在 `self._build_ui()` 之后追加：

```python
        self._live_cards.set_placeholder_copy(
            title="未加载 MF4",
            body="回放会在这里显示信号趋势与当前值。",
            action="使用左上「选择 MF4」打开录制文件",
        )
        # spec §F10: 加载前右栏（连接前检查页）没有意义，隐藏。
        self._right_panel.setVisible(False)
```

`load_file`（:164）在 `self._source = source` 之后追加：

```python
        self._right_panel.setVisible(True)
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_replay_tab.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/live_cards.py mf4_analyzer/acquisition_ui/replay_tab.py tests/acquisition_ui/test_replay_tab.py
git commit -m "fix(acquisition): replay tab gets its own placeholder copy; right panel hidden until load"
```

---

### Task 12: F11 — 窄宽布局 + 工具栏溢出优先级

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py:109`
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`（`__init__`）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py`
  （`_build_acquisition_page` + `_recompute_toolbar_overflow`）
- Test: `tests/acquisition_ui/test_toolbar_overflow_priority.py`（新建）

- [ ] **Step 1: 写失败测试**（新文件）

```python
"""spec 2026-07-07 §F11: 窄宽下主导航最后降级，中央不被压死。"""
from PyQt5.QtWidgets import QApplication

from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def test_mode_segment_demoted_last_at_960(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(960, 600)
    window.show()
    qtbot.waitExposed(window)
    QApplication.processEvents()
    window._recompute_toolbar_overflow()
    demoted = {
        w.objectName(): bool(w.property("cockpitOverflowHidden"))
        for w, _a in window._toolbar_overflow_items
    }
    # 有降级发生时，transport chip 必须先于模式段进溢出菜单。
    if any(demoted.values()):
        assert demoted["cockpitTransportStatusChip"] or not demoted["cockpitModeSegment"]
        assert not demoted["cockpitModeSegment"]
    window.close()


def test_center_minimum_width_at_960(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    window.resize(960, 600)
    window.show()
    qtbot.waitExposed(window)
    QApplication.processEvents()
    assert window._center.width() >= 300
    window.close()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_toolbar_overflow_priority.py -v`
Expected: FAIL（模式段先被降级 / 中央 <300）。

- [ ] **Step 3: 实现**

`left_pane.py:109`：`self.setFixedWidth(420)` 替换为：

```python
        self.setMinimumWidth(320)
        self.setMaximumWidth(460)
```

`live_cards.py` `LiveCardGrid.__init__` 开头（outer layout 之前）追加：

```python
        # spec §F11: 三栏 min 之和 320+300+280 < 最小窗宽 960。
        self.setMinimumWidth(300)
```

`_toolbar_mixin.py` `_build_acquisition_page` 在 `layout.addWidget(splitter)`
之前追加：

```python
        # 1280 默认布局锚定（左 420 不变，spec §F11 像素回归约束）。
        splitter.setSizes([420, 560, 300])
```

`_recompute_toolbar_overflow` 的 demote 选择改为显式优先级：在
`shown: list[QWidget] = [w for w, _, dv in eligible if dv]` 之后插入：

```python
        # spec §F11: 降级次序与菜单显示序解耦。rank 越小越先降级；
        # 模式段（主导航）最后降级。
        demote_rank = {
            self._transport_chip: 0,
            self._output_btn: 1,
            self._settings_btn: 2,
            self._segment_btn: 3,
            self._a2l_btn: 4,
            self._mode_segment_widget: 5,
        }
        shown.sort(key=lambda w: demote_rank.get(w, -1), reverse=True)
```

（`while running > outer_w and shown: victim = shown.pop()` 保持不变——pop
现在按 rank 从 0 开始弹。溢出菜单顺序仍由 `eligible` 的 L→R 序重建，不受影响。）

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_toolbar_overflow_priority.py tests/acquisition_ui/test_cockpit_polish_integration.py tests/acquisition_ui/test_visual_shell.py -v`
Expected: 全 PASS（既有溢出用例若断言旧的「模式段先降级」次序，按新次序更新）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/left_pane.py mf4_analyzer/acquisition_ui/widgets/live_cards.py mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py tests/acquisition_ui/test_toolbar_overflow_priority.py
git commit -m "fix(acquisition): flexible pane widths at narrow window; mode segment demoted last"
```

---

### Task 13: F12 — 搜索高亮渲染进 name label

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
- Test: `tests/acquisition_ui/test_left_pane.py`（追加）

**Interfaces:**
- Produces: `left_pane._highlight_name_html(name, spans) -> str`（模块级）。

- [ ] **Step 1: 写失败测试**

```python
def test_search_highlight_renders_in_name_label(qtbot):
    """spec 2026-07-07 §F12: 高亮必须落在可见的 name label 上。"""
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    pane._search.setText("Sig_00")
    item = pane._row_items["Sig_00"]
    row = pane._list.itemWidget(item)
    name_label = row.findChild(QLabel, "measurementName")
    assert "<span" in name_label.text()
    pane._search.setText("")
    row = pane._list.itemWidget(pane._row_items["Sig_00"])
    assert "<span" not in row.findChild(QLabel, "measurementName").text()


def test_highlight_name_html_escapes_and_wraps():
    from mf4_analyzer.acquisition_ui.widgets.left_pane import _highlight_name_html
    out = _highlight_name_html("a<b", [(0, 1)])
    assert out == '<span style="color:#1769E0;font-weight:600;">a</span>&lt;b'
    assert _highlight_name_html("abc", []) == "abc"
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py -v -k highlight`
Expected: FAIL。

- [ ] **Step 3: 实现**

`left_pane.py` 顶部 `import re` 旁加 `import html as _html`。模块级新增
（`_format_event_label` 附近）：

```python
def _highlight_name_html(name: str, spans: Sequence[tuple[int, int]]) -> str:
    """把 match_spans（半开区间，针对 name）渲染为高亮 rich text。

    spans 为空返回原文（PlainText 渲染）。命中段用项目交互蓝加粗。
    """
    if not spans:
        return name
    out: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        start = max(start, cursor)
        if start >= end:
            continue
        out.append(_html.escape(name[cursor:start]))
        out.append('<span style="color:#1769E0;font-weight:600;">')
        out.append(_html.escape(name[start:end]))
        out.append("</span>")
        cursor = end
    out.append(_html.escape(name[cursor:]))
    return "".join(out)
```

`_build_row_widget` 签名加 `match_spans: Sequence[tuple[int, int]] = ()`，
name label 构造替换：

```python
        name_label = QLabel(_highlight_name_html(m.name, match_spans), row)
        name_label.setObjectName("measurementName")
        name_label.setTextFormat(Qt.RichText if match_spans else Qt.PlainText)
        name_label.setToolTip(m.name)
        name_label.setMinimumWidth(0)
```

`_refresh_list` 的 setItemWidget 行改为传 spans：

```python
            self._list.setItemWidget(
                item, self._build_row_widget(measurement, match_spans)
            )
```

`_build_row` 删除 match_spans 的 foreground/tooltip 死代码段（
`if match_spans:` 整块删除；形参保留，item 只存 name/data/背景）。

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/left_pane.py tests/acquisition_ui/test_left_pane.py
git commit -m "fix(acquisition): search match highlight renders in the visible name label"
```

---

### Task 14: F13 — 历史 tab 本地化 + issue_tags 空态隐藏

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/history_tab.py:486-512,594-606`
- Test: `tests/acquisition_ui/test_history_tab.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_filter_labels_are_localized(qtbot):
    tab = HistoryTab()
    qtbot.addWidget(tab)
    labels = [lab.text() for lab in tab.findChildren(QLabel)]
    for cn in ("车辆", "场景", "存储", "数据集"):
        assert cn in labels
    for en in ("vehicle", "scenario", "path_kind", "set"):
        assert en not in labels


def test_issue_tags_bar_hidden_when_no_tags(qtbot):
    tab = HistoryTab()
    qtbot.addWidget(tab)
    assert not tab._tag_bar.isVisible()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_history_tab.py -v -k "localized or tags_bar"`
Expected: FAIL。

- [ ] **Step 3: 实现**

`_build_ui`（:497-504）四个 label 改中文：

```python
        filter_row.addWidget(QLabel("车辆", self))
        filter_row.addWidget(self._vehicle_filter)
        filter_row.addWidget(QLabel("场景", self))
        filter_row.addWidget(self._scenario_filter)
        filter_row.addWidget(QLabel("存储", self))
        filter_row.addWidget(self._path_kind_filter)
        filter_row.addWidget(QLabel("数据集", self))
        filter_row.addWidget(self._set_filter)
```

tag 行（:508-512）改为可隐藏的容器 widget：

```python
        self._tag_bar = QWidget(self)
        self._tag_bar.setObjectName("historyTagBar")
        self._tag_row = QHBoxLayout(self._tag_bar)
        self._tag_row.setContentsMargins(0, 0, 0, 0)
        self._tag_row.setSpacing(6)
        self._tag_row.addWidget(QLabel("问题标签", self._tag_bar))
        self._tag_row.addStretch(1)
        self._tag_bar.setVisible(False)
        root.addWidget(self._tag_bar)
```

tag chips 重建处（:594-606，`while self._tag_row.count() > 2:` 所在方法）末尾
追加可见性同步（chips 插入循环之后）：

```python
        self._tag_bar.setVisible(bool(self._tag_checks))
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_history_tab.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/history_tab.py tests/acquisition_ui/test_history_tab.py
git commit -m "fix(acquisition): localize history filters, hide empty issue-tags bar"
```

---

### Task 15: 验收门 — `scripts/cockpit_ui_tour.py --assert` + 全量回归

**Files:**
- Create: `scripts/cockpit_ui_tour.py`

**Interfaces:**
- Consumes: Task 1-14 的全部修复；`CockpitMainWindow` 公开属性
  （`state_machine/main_button/health_strip/left_pane/ring_buffer/review_modal`）
  与 Task 4 的 `_restart_idle_stream_for_selection`。

- [ ] **Step 1: 写脚本**（完整内容）

```python
"""Scripted end-to-end tour of the Acquisition Cockpit (offscreen by default).

打开 → 选通道(底部勾选) → 连接 → 空闲流 → 空闲加通道 → 录制 → 停止复盘 →
仅保存 → 关闭 → 空闲 soak → 窄宽。--assert 校验 2026-07-07 spec 的端到端
不变量，违例 exit 1。--shots DIR 每步截图（人工比对用）。

用法:
    .venv/bin/python scripts/cockpit_ui_tour.py --assert
    .venv/bin/python scripts/cockpit_ui_tour.py --onscreen --shots /tmp/shots
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _build_pool():
    from can_logger.p0.a2l_probe import MeasurementSummary

    named = [
        ("MotSpd", "rpm", "UWORD", ("event_1ms", "event_10ms")),
        ("StrWhlTrq", "Nm", "SWORD", ("event_1ms", "event_10ms")),
        ("MotTrq", "Nm", "SWORD", ("event_1ms", "event_10ms")),
        ("EcuTemp", "degC", "SWORD", ("event_100ms",)),
        ("BattVolt", "V", "UWORD", ("event_10ms", "event_100ms")),
    ]
    pool = []
    addr = 0x40000000
    for name, unit, dtype, events in named:
        pool.append(MeasurementSummary(
            name=name, address=addr, datatype=dtype, unit=unit,
            conversion="", available_events=events))
        addr += 4
    for i in range(40):
        pool.append(MeasurementSummary(
            name=f"EpsDiagSig_{i:02d}", address=addr, datatype="UWORD",
            unit="", conversion="", available_events=("event_10ms",)))
        addr += 4
    return tuple(pool)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cockpit UI end-to-end tour")
    parser.add_argument("--assert", dest="do_assert", action="store_true",
                        help="校验 spec 不变量，违例 exit 1")
    parser.add_argument("--shots", type=Path, default=None, help="截图输出目录")
    parser.add_argument("--out", type=Path, default=None, help="录制文件输出目录")
    parser.add_argument("--onscreen", action="store_true",
                        help="真实屏幕渲染（默认 offscreen）")
    args = parser.parse_args()

    if not args.onscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    out_dir = args.out or Path(tempfile.mkdtemp(prefix="cockpit_tour_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QCheckBox

    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
    from mf4_analyzer.acquisition_ui.review_modal import ReviewModal
    from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font

    setup_chinese_font()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        load_stylesheet(app)
    except Exception as exc:  # noqa: BLE001
        print(f"[tour] stylesheet load failed: {exc!r}")

    window = CockpitMainWindow(initial_pool=_build_pool(), allow_fake_backend=True)
    window._output_dir_label = str(out_dir)
    window.show()

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        tag = "PASS" if cond else "FAIL"
        print(f"[assert] {tag} {msg}")
        if not cond:
            failures.append(msg)

    def shot(widget, name: str) -> None:
        if args.shots is None:
            return
        pm = widget.grab()
        pm.save(str(args.shots / f"{name}.png"))
        print(f"[shot] {name} {pm.width()}x{pm.height()}")

    steps: list[tuple[int, str, object]] = []

    def at(ms: int, name: str):
        def deco(fn):
            steps.append((ms, name, fn))
            return fn
        return deco

    @at(400, "select-bottom")
    def s_select_bottom():
        lp = window.left_pane
        sb = lp._list.verticalScrollBar()
        sb.setValue(sb.maximum())
        anchor = sb.value()
        item = lp._list.item(lp._list.count() - 1)
        cb = lp._list.itemWidget(item).findChild(QCheckBox)
        cb.click()
        check(sb.value() == anchor, f"F3 勾选后滚动保持 ({anchor} -> {sb.value()})")
        shot(window, "01-scrolled-select")
        lp._set_measurement_selected("EpsDiagSig_39", False)
        for name in ("MotSpd", "StrWhlTrq", "MotTrq"):
            lp._set_measurement_selected(name, True)
        sb.setValue(0)

    @at(800, "connect")
    def s_connect():
        window.main_button.click()

    @at(3000, "idle-check")
    def s_idle():
        from mf4_analyzer.acquisition_ui.state import CockpitState
        check(window.state_machine.state == CockpitState.CONNECTED_IDLE,
              "连接后进入 CONNECTED_IDLE")
        cards = window._center.cards
        check(bool(cards) and all(c._spark.sample_count > 0 for c in cards.values()),
              "F1 idle 态卡片缓冲非空")
        shot(window, "02-idle")

    @at(3200, "idle-add-channel")
    def s_add():
        window.left_pane._set_measurement_selected("BattVolt", True)
        window._restart_idle_stream_for_selection()

    @at(4600, "idle-added-check")
    def s_added():
        card = window._center.cards.get("BattVolt")
        check(card is not None and card._spark.sample_count > 0,
              "F5 空闲新增通道有数据")
        shot(window, "03-idle-added")

    @at(4800, "record")
    def s_record():
        window.main_button.click()

    @at(7400, "recording-check")
    def s_recording():
        from mf4_analyzer.acquisition_ui.state import CockpitState
        check(window.state_machine.state == CockpitState.RECORDING, "进入 RECORDING")
        check(window.main_button.text() == "■ Stop && 复盘",
              "F4 Stop 按钮 && 转义")
        cards = window._center.cards
        check(all(c._spark.sample_count > 0 for c in cards.values()),
              "F1 recording 态卡片缓冲非空")
        shot(window, "04-recording")

    @at(7600, "stop")
    def s_stop():
        window.main_button.click()

    @at(8400, "review-check")
    def s_review():
        modal = window.review_modal
        check(isinstance(modal, ReviewModal), "停止后打开真实 ReviewModal")
        shot(modal if modal is not None else window, "05-review")
        if isinstance(modal, ReviewModal):
            modal.do_save_only()
            modal.reject()

    @at(15400, "soak-check")
    def s_soak():
        # review 关闭后空闲 ~7s：F2 后 ring 恒 0、按钮可用、无幽灵弹窗。
        from mf4_analyzer.acquisition_ui.state import CockpitState
        check(window.state_machine.state == CockpitState.CONNECTED_IDLE,
              "review 关闭回 CONNECTED_IDLE")
        check(window.ring_buffer.level_pct == 0.0,
              f"F2 空闲 ring 恒 0 (实测 {window.ring_buffer.level_pct:.1f}%)")
        levels = window.health_strip.current_levels()
        check(levels.get("REC") != "red", f"F2 REC 不红 (实测 {levels.get('REC')})")
        check(window.main_button.isEnabled(), "F2 采集按钮保持可用")
        check(window._review_modal is None, "F2 无幽灵复盘弹窗")
        shot(window, "06-soak")

    @at(15800, "narrow")
    def s_narrow():
        window.resize(960, 600)

    @at(16800, "narrow-check")
    def s_narrow_check():
        check(window._center.width() >= 300, f"F11 中央 ≥300px (实测 {window._center.width()})")
        check(not bool(window._mode_segment_widget.property("cockpitOverflowHidden")),
              "F11 模式段未被降级")
        shot(window, "07-narrow")

    @at(17400, "finish")
    def s_finish():
        produced = sorted(p.name for p in out_dir.glob("capture_*"))
        check(any(n.endswith(".mf4") for n in produced), "落盘 MF4 存在")
        check(any(n.endswith(".session_summary.json") for n in produced),
              "session_summary.json 存在")
        check(any(n.endswith(".preflight.json") for n in produced),
              "preflight.json 存在")
        print(f"[runs] {produced}")
        window.close()
        app.exit(0)

    for ms, name, fn in steps:
        def runner(fn=fn, name=name):
            try:
                fn()
            except Exception:  # noqa: BLE001
                failures.append(f"step {name} raised")
                print(f"[step-fail] {name}\n{traceback.format_exc()}")
        QTimer.singleShot(ms, runner)

    app.exec_()
    if args.do_assert and failures:
        print(f"[tour] {len(failures)} invariant(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("[tour] all invariants passed" if args.do_assert else "[tour] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 跑验收门**

Run: `.venv/bin/python scripts/cockpit_ui_tour.py --assert`
Expected: `[tour] all invariants passed`，exit 0。任何 FAIL 都指向具体
F 编号——回对应任务修。

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -x -q`（前台，不用 run_in_background）
Expected: 与 main 基线一致的通过数，0 新增失败。已知既有失败（如 perf 基线）
不算回归——对照执行前记录的基线。

- [ ] **Step 4: Commit**

```bash
git add scripts/cockpit_ui_tour.py
git commit -m "test(acquisition): add cockpit UI tour script as end-to-end acceptance gate"
```

---

## Self-Review 核对表（写完后已过一遍）

- Spec 覆盖：F1→T1、F2→T2/T3、F3→T5、F4→T6、F5→T4、F6→T7、F7→T8、F8→T9、
  F9→T10、F10→T11、F11→T12、F12→T13、F13→T14、验证工具→T15。无遗漏。
- 类型/命名一致：`reset_buffers`（T1 定义，T4/T15 消费）；
  `_restart_idle_stream_for_selection`（T4 定义，T15 消费）；
  `_row_items`/`_update_row_for`（T5 定义，T13/T15 消费）；
  `_humanize_duration_s` / `_highlight_name_html` 模块级、测试直接 import。
- 已知联动：T2 改状态栏 idle 文案（test line 29）、T9 改 recording 文案
  （test line 40）——两处都在各自任务里给了新期望串，不冲突。
