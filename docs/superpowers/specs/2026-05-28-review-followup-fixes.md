# Review Follow-up Fixes — Spec

源: `docs/analyzer/reviews/2026-05-27-recent-changes-review.md` (B1-B7)
目标: 不引入新依赖, 不改公共 API, 每个 bug 配最小回归测试。

**Status (2026-05-28 review): completed / historical baseline.**
This file documents the B1-B7 review-followup fixes that are already present in
the current branch. It is **not** part of the pyqtgraph TimeDomainCanvas
performance migration scope, and future performance work must not reopen these
items unless a new regression is found.

Current evidence from the live tree:

- B1 is implemented in `FFTContextual.set_signal_candidates` and
  `OrderContextual.set_signal_candidates` by preserving `prev =
  self.combo_sig.currentData()` and restoring `keep_idx`
  (`mf4_analyzer/ui/inspector_sections.py:1856-1874`,
  `mf4_analyzer/ui/inspector_sections.py:2271-2287`).
- B2 is implemented with tangent-overlap guards
  `new_hi <= cur_lo or new_lo >= cur_hi`
  (`mf4_analyzer/ui/main_window.py:430-434`).
- B3 is implemented by filtering heatmap colorbar scroll/click events
  (`mf4_analyzer/ui/canvases.py:2403`, `mf4_analyzer/ui/canvases.py:2443`).
- B4-B6 are implemented in `CockpitMainWindow`, including `closeEvent`,
  dropped-frame rearm state, and immediate transport health polling
  (`mf4_analyzer/acquisition_ui/main_window.py:214-218`, `:983`,
  `:1640-1674`, `:2010-2025`).
- B7 is implemented and covered by tests that assert traceback last-line
  preservation and long-log dump behavior (`tests/test_p0_a2l_probe.py:213-236`).

---

## B1. FFTContextual / OrderContextual 信号下拉重置

**位置**
- `mf4_analyzer/ui/inspector_sections.py:1851` `FFTContextual.set_signal_candidates`
- `mf4_analyzer/ui/inspector_sections.py:2254` `OrderContextual.set_signal_candidates`

**改动**
按 `FFTTimeContextual.set_signal_candidates` (`:2707`) 的模板，保留 `prev = combo_sig.currentData()`：
```python
prev = self.combo_sig.currentData()
self.combo_sig.blockSignals(True)
self.combo_sig.clear()
keep_idx = -1
for i, (text, data) in enumerate(candidates):
    self.combo_sig.addItem(text, data)
    if prev is not None and data == prev:
        keep_idx = i
if keep_idx >= 0:
    self.combo_sig.setCurrentIndex(keep_idx)
self.combo_sig.blockSignals(False)
# 既有的 disconnect/connect + 末尾 _on_sig_index_changed() 保留
```

**验收**: 新增 `tests/ui/test_main_window_smoke.py` 用例：
1. 载入 2 个文件
2. FFT 面板选中 file B 的某通道
3. 通过 `navigator` 编辑文件 A 新增/删除通道，触发 `_refresh_channel_dependent_controls`
4. 断言 `inspector.fft_ctx.combo_sig.currentData()` 仍指向 file B 的原通道
5. 同样断言 Order 面板

---

## B2. xlim 相切判断

**位置**: `mf4_analyzer/ui/main_window.py:431`

**改动**: `<` `>` → `<=` `>=`：
```python
if new_hi <= cur_lo or new_lo >= cur_hi:
    return
```

**验收**: `tests/ui/test_main_window_smoke.py` 增 1 个 case：构造 `_safe_restore_primary_xlim` 输入 xlim=(0, 5)、新 ax xlim=(5, 10)，断言不调用 `set_xlim`。

---

## B3. PlotCanvas 滚轮 / 单击过滤 colorbar

**位置**
- `mf4_analyzer/ui/canvases.py:2433` `PlotCanvas._on_scroll`
- `mf4_analyzer/ui/canvases.py:2392` `PlotCanvas._on_click`

**改动**: 函数入口处加一行：
```python
if self._heatmap_cbar is not None and e.inaxes is self._heatmap_cbar.ax:
    return
```

**验收**: `tests/ui/test_canvases.py` 增测：构造 `PlotCanvas.plot_or_update_heatmap`, 模拟 `event.inaxes == canvas._heatmap_cbar.ax` 的滚动事件，断言 `set_xlim/set_ylim` 不被调用。

---

## B4. Cockpit closeEvent

**位置**: `mf4_analyzer/acquisition_ui/main_window.py` `CockpitMainWindow` 类

**改动**: 在类底部加 `closeEvent`：
```python
def closeEvent(self, event):
    """Stop backend + cancel poll timers before window destruction."""
    try:
        if self._live_timer is not None and self._live_timer.isActive():
            self._live_timer.stop()
        if self._health_timer is not None and self._health_timer.isActive():
            self._health_timer.stop()
    except Exception:
        pass
    try:
        if self._backend is not None:
            self._stop_backend_best_effort(self._backend)
    except Exception:
        pass
    super().closeEvent(event)
```

**验收**: `tests/acquisition_ui/test_cockpit_close.py` 新增：构造 cockpit、装一个 fake backend 记录 `stop()` 被调用，触发 `cockpit.close()`，断言 backend.stop() 被调用且 `_health_timer.isActive() is False`。

---

## B5. dropped-frame latch 用时间+增量双阈值

**位置**: `mf4_analyzer/acquisition_ui/main_window.py`
- 字段 `_dropped_prompt_shown: bool` → `_dropped_prompt_last_ts: float | None` + `_dropped_prompt_last_count: int`
- `_poll_live` 中的判断 (line 1342-1347)
- `_show_dropped_frames_prompt` (line 1965)
- `_start_recording` 中的重置 (line 1162)
- `__init__` 中的初始化 (line 213)

**改动**:
1. 新增模块级阈值常量（写在 `_show_dropped_frames_prompt` 上方注释中）：`DROPPED_PROMPT_REARM_S = 5.0`, `DROPPED_PROMPT_REARM_DELTA = 200`
2. `_poll_live` 改为：
```python
if (
    self._state_machine.state == CockpitState.RECORDING
    and self._cumulative_dropped > thresholds.DROPPED_FRAMES_PROMPT_TOTAL
    and self._dropped_prompt_can_fire()
):
    self._show_dropped_frames_prompt()
```
3. 新方法 `_dropped_prompt_can_fire()` 检查时间冷却 + 增量。
4. `_show_dropped_frames_prompt` 末尾记录 `self._dropped_prompt_last_ts = time.monotonic(); self._dropped_prompt_last_count = self._cumulative_dropped`。
5. `_start_recording` 重置两个字段。

**验收**: 拓展现有 `tests/acquisition_ui/test_dropped_frame_prompt.py`：模拟连续两次超阈值，第一次弹后用户关掉，5 秒内不再弹；推进 monotonic 时钟+继续累积，重新弹出。

---

## B6. Transport 切换立即同步状态

**位置**: `mf4_analyzer/acquisition_ui/main_window.py:1607` `set_transport`

**改动**: 在 `set_transport` 末尾（return 之前）调度一次延后立即 poll：
```python
# 强制下一次事件循环立刻刷新 chip 颜色 / probe 结果，
# 避免最长 ~200ms 的 stale 显示
QTimer.singleShot(0, self._poll_health)
```
注：只有在 `_health_timer` 已初始化时才安排，避免构造期重入。增加一行 guard：
```python
if getattr(self, "_health_timer", None) is not None:
    QTimer.singleShot(0, self._poll_health)
```

**验收**: `tests/acquisition_ui/test_main_window_transport_chip.py` 增测：装 `_health_aggregator` 的 `_hw_probe` 改成根据 `self._transport_config` 返回，调用两次 `set_transport`（不同 channel），断言 `qApp.processEvents()` 后 `_health_aggregator.last.hw.channel_count` 反映了最后一个 transport。

---

## B7. A2L stderr 截断保留根因 + 写完整 log

**位置**: `can_logger/p0/a2l_probe.py:142-148` `_compact_process_output`

**改动**: 把 traceback 截断改成 "保留最后一行 + 完整 dump 到 %TEMP%"：
```python
import tempfile, os
def _compact_process_output(stdout: bytes, stderr: bytes) -> str:
    raw = stderr or stdout or b""
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "no output"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    detail = lines[-1] if lines else "no output"  # 改: 最后一行是真正的异常
    # 长 traceback 时另存完整副本，方便排查
    if len(text) > 800:
        try:
            fd, path = tempfile.mkstemp(prefix="a2l_probe_", suffix=".log")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            detail = f"{detail}  (full log: {path})"
        except OSError:
            pass
    return detail[:297] + "..." if len(detail) > 300 else detail
```

**验收**: 拓展 `tests/test_p0_a2l_probe.py`：调用 `_compact_process_output(b"", b"Traceback (most recent call last):\n  File \"x\", line 1, in <module>\nValueError: real error")`, 断言返回值含 "ValueError: real error"。第二个用例验证 >800 字符时返回字符串含 "full log:"。

---

## 全量回归

执行 `pytest tests/ -x --no-cov -q` 全过。变更不改任何公共 API，只新增几条测试用例。
