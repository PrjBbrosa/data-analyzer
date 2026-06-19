# 计算反馈契约 + 阶次缓存键修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复「改 RPM系数 点计算图不刷新」的缓存键漏字段 bug，并为三个计算按钮及其它静默操作建立统一、可见、可区分的反馈契约。

**Architecture:** P0 补 order 缓存键（三处同源注入）+ 修保存图片吞异常；P1 抽纯函数 `summarize_compute` + 薄 Qt 出口 `_emit_compute_feedback`，接到三个计算按钮的既有终点与 per-pane 跳过点；P2 兜底其余静默 no-op。每个任务先红后绿、独立可提交。

**Tech Stack:** Python / PyQt5 / pytest（offscreen Qt）。测试命令统一：
`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest <path> -q`

设计文档：`docs/superpowers/specs/2026-06-19-compute-feedback-and-cache-key-design.md`

---

## 已核对锚点（verified）

- 键权威点：`mf4_analyzer/ui/main_window/_order_mixin.py:140-153` `_order_compute_cache_params`（`@staticmethod`，可脱 Qt 直接调用）。
- 键注入路径：`_analysis_mixin.py:382-391`（HIT 检查）、`_order_mixin.py:300-319`（存储）。
- `contextual_order.py:522-542` `get_params()` 不含 `rpm_factor`/`fs`；getter 在 `:511`(fs)、`:519`(rpm_factor)。
- 保存图片：`ui/chart_stack/toolbar.py:652-655`（`pix.save` 被 `except: return` 吞）。
- `toast(msg, level)`：`window.py:284`。三个计算入口：`do_order_time` `_order_mixin.py:183`、`do_fft` `_fft_mixin.py:124`、`do_fft_time` `_fft_time_mixin.py`（re-entry `:228-233`，终点 `:286-298`）。
- 缓存键测试范式：`tests/ui/test_analysis_cache.py`（`make_key` 用法）。

## 文件结构

- 新建：`mf4_analyzer/ui/compute_feedback.py` — 纯函数 summarizer + `ComputeOutcome`（无 Qt）。
- 新建：`tests/ui/test_compute_feedback.py` — summarizer 全分支单测（无 Qt）。
- 新建：`tests/ui/test_order_cache_key_params.py` — 键漏字段回归（无 Qt）。
- 修改：`_order_mixin.py`、`_analysis_mixin.py`、`_fft_mixin.py`、`_fft_time_mixin.py`、`contextual_order.py`、`chart_stack/toolbar.py`、`window.py`、`dialogs.py`、`heatmap_canvas.py`、`_project_io_mixin.py`。
- 测试落点：`tests/ui/test_order_cache_key_params.py`、`tests/ui/test_compute_feedback.py`、`tests/ui/test_chart_stack.py`、`tests/ui/test_analysis_multiview_integration.py`、`tests/ui/test_dialogs.py`。

---

# P0 — 正确性 + 数据安全

## Task A: order 缓存键补 `rpm_factor` + `fs`

**Files:**
- Test: `tests/ui/test_order_cache_key_params.py`（新建）
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py:140-153`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py:382-391`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py:534-542`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_order_cache_key_params.py
"""Regression: order cache-key params must include rpm_factor and fs,
so changing either alone produces a different key (no stale cache hit)."""
from mf4_analyzer.ui.main_window._order_mixin import OrderMixin

_BASE = {
    'nfft_effective': 8192, 'nfft_mode': 'auto', 'max_order': 10,
    'order_res': 0.1, 'time_res': 0.05, 'samples_per_rev': 512,
    'rpm_factor': 1.0, 'fs': 100.0,
}


def test_rpm_factor_changes_cache_params():
    a = OrderMixin._order_compute_cache_params(dict(_BASE), None, None)
    b = OrderMixin._order_compute_cache_params(dict(_BASE, rpm_factor=2.0), None, None)
    assert a != b
    assert a['rpm_factor'] == 1.0 and b['rpm_factor'] == 2.0


def test_fs_changes_cache_params():
    a = OrderMixin._order_compute_cache_params(dict(_BASE), None, None)
    b = OrderMixin._order_compute_cache_params(dict(_BASE, fs=200.0), None, None)
    assert a != b
    assert a['fs'] == 100.0 and b['fs'] == 200.0
```

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_cache_key_params.py -q`
Expected: FAIL — `KeyError: 'rpm_factor'`（当前键 dict 无此键）。

- [ ] **Step 3: 在键里加两字段**

`_order_mixin.py:144-153` 的返回 dict 末尾加（并在 `return` 上方加规约注释）：

```python
    @staticmethod
    def _order_compute_cache_params(p, rpm_source, time_range):
        nfft = p.get('nfft_effective', p.get('nfft'))
        if nfft is None:
            nfft = p.get('nfft_preview') or 256
        # 规约：凡进入 COT 计算的用户可调参数都必须在此登记，否则改了不刷新。
        return {
            'nfft': int(nfft),
            'nfft_mode': p.get('nfft_mode', 'fixed'),
            'max_order': p.get('max_order'),
            'order_res': p.get('order_res'),
            'time_res': p.get('time_res'),
            'samples_per_rev': p.get('samples_per_rev'),
            'rpm_factor': p.get('rpm_factor'),
            'fs': p.get('fs'),
            'rpm_source': list(rpm_source) if rpm_source else None,
            'time_range': time_range,
        }
```

- [ ] **Step 4: 运行，确认通过**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_order_cache_key_params.py -q`
Expected: PASS

- [ ] **Step 5: 让两条键路径都携带这两个字段（否则 HIT/STORE 键不一致，永不命中）**

5a. `contextual_order.py:get_params()`（`:534-542`）的返回 dict 增加两行：

```python
        return dict(
            max_order=self.spin_mo.value(),
            order_res=self.spin_order_res.value(),
            time_res=self.spin_time_res.value(),
            nfft=nfft,
            nfft_mode=nfft_mode,
            nfft_preview=nfft_preview,
            nfft_effective=nfft_effective,
            rpm_factor=self.spin_rf.value(),
            fs=self.spin_fs.value(),
        )
```

5b. `_analysis_mixin.py:382-391`（order 分支手建 dict）增加两键：

```python
        return {
            'nfft': p.get('nfft'),
            'nfft_mode': p.get('nfft_mode'),
            'nfft_preview': p.get('nfft_preview'),
            'nfft_effective': p.get('nfft_effective'),
            'max_order': p.get('max_order'),
            'order_res': p.get('order_res'),
            'time_res': p.get('time_res'),
            'samples_per_rev': ctx.current_params().get('samples_per_rev'),
            'rpm_factor': p.get('rpm_factor'),
            'fs': p.get('fs'),
        }
```

（`_dispatch_order_job` 的 `op = dict(get_params())` 因 5a 自动携带，无需改。）

- [ ] **Step 6: 回归全套，确认无破坏**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_cache.py tests/ui/test_analysis_multiview_integration.py tests/ui/test_inspector.py tests/test_order_analysis.py -q`
Expected: PASS（注意 `test_inspector` 若断言 `get_params()` 精确键集合，按新增两键更新断言）。

- [ ] **Step 7: 提交**

```bash
git add tests/ui/test_order_cache_key_params.py mf4_analyzer/ui/main_window/_order_mixin.py mf4_analyzer/ui/main_window/_analysis_mixin.py mf4_analyzer/ui/inspector_sections/contextual_order.py
git commit -- tests/ui/test_order_cache_key_params.py mf4_analyzer/ui/main_window/_order_mixin.py mf4_analyzer/ui/main_window/_analysis_mixin.py mf4_analyzer/ui/inspector_sections/contextual_order.py
```
提交信息：`fix(order): include rpm_factor+fs in COT cache key so param edits recompute`

---

## Task B: 保存图片失败弹窗（修吞异常 + 假成功）

**Files:**
- Test: `tests/ui/test_chart_stack.py`（追加；若保存逻辑测试在别处，按 grep `save_pixmap`/`保存图片` 定位）
- Modify: `mf4_analyzer/ui/chart_stack/toolbar.py:652-655`

- [ ] **Step 1: 写失败测试**

```python
def test_save_image_failure_warns(qtbot, monkeypatch):
    """pix.save() 返回 False（坏路径/无权限）时必须弹 QMessageBox.warning，
    且不静默吞掉。"""
    import mf4_analyzer.ui.chart_stack as cs
    tb = _make_toolbar_with_dummy_pixmap(qtbot)          # 复用现有 toolbar fixture
    monkeypatch.setattr(cs.QFileDialog, 'getSaveFileName',
                        staticmethod(lambda *a, **k: ('/bad/path.png', 'PNG (*.png)')))
    calls = []
    monkeypatch.setattr(cs.QMessageBox, 'warning',
                        staticmethod(lambda *a, **k: calls.append(a)))
    # 让 pix.save 返回 False
    monkeypatch.setattr(cs, '_grab_pixmap_hidpi', lambda c: _pixmap_that_fails_save())
    tb._on_save_image()                                   # 按实际方法名调整
    assert calls, "save failure must raise a warning dialog"
```

> 若现有 toolbar 测试已有 fixture/调用范式，沿用之；`_make_toolbar_with_dummy_pixmap` /
> `_pixmap_that_fails_save` 用现有 helper 或最小 `QPixmap()`（空 pixmap `.save` 返回 False）。

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q -k save_image`
Expected: FAIL — `QMessageBox.warning` 未被调用。

- [ ] **Step 3: 改实现**

`toolbar.py:652-655` 替换为：

```python
        ok = False
        try:
            ok = bool(pix.save(path))
        except Exception:
            ok = False
        if not ok:
            QMessageBox.warning(self, "保存失败", f"无法保存图片到：\n{path}")
            return
```

确认文件顶部已 import `QMessageBox`（若无则补 `from ...qt import QMessageBox` 按本仓 import 范式）。

- [ ] **Step 4: 运行，确认通过**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_chart_stack.py -q -k save_image`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tests/ui/test_chart_stack.py mf4_analyzer/ui/chart_stack/toolbar.py
git commit -- tests/ui/test_chart_stack.py mf4_analyzer/ui/chart_stack/toolbar.py
```
提交信息：`fix(chart): warn on image save failure instead of silent swallow`

---

# P1 — 统一反馈契约

## Task C: 纯函数 summarizer（无 Qt）

**Files:**
- Create: `mf4_analyzer/ui/compute_feedback.py`
- Test: `tests/ui/test_compute_feedback.py`（新建）

- [ ] **Step 1: 写失败测试（全分支）**

```python
# tests/ui/test_compute_feedback.py
from mf4_analyzer.ui.compute_feedback import ComputeOutcome, summarize_compute


def test_busy():
    assert summarize_compute(ComputeOutcome(), busy=True, section_label="时间-阶次") \
        == ('info', "时间-阶次进行中，请稍候…")


def test_nothing_to_do_returns_none():
    assert summarize_compute(ComputeOutcome()) is None


def test_all_cached():
    assert summarize_compute(ComputeOutcome(cached=3)) \
        == ('info', "已用缓存结果（参数未变）· 3 图")


def test_all_computed():
    assert summarize_compute(ComputeOutcome(computed=2), section_label="FFT") \
        == ('success', "FFT完成 · 2 图")


def test_all_skipped():
    out = ComputeOutcome(skipped=["信号过短", "信号过短", "缺转速"])
    assert summarize_compute(out) == ('warning', "无可计算的图：2 个信号过短、1 个缺转速")


def test_partial_skip():
    out = ComputeOutcome(computed=1, cached=1, skipped=["信号过短"])
    assert summarize_compute(out) == ('warning', "2 图已出 · 1 图跳过（1 个信号过短）")


def test_all_failed():
    assert summarize_compute(ComputeOutcome(failed=2), section_label="阶次") \
        == ('error', "阶次失败：2 个图计算出错")
```

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_compute_feedback.py -q`
Expected: FAIL — `ModuleNotFoundError: mf4_analyzer.ui.compute_feedback`。

- [ ] **Step 3: 写实现**

照设计文档「反馈契约」节，把 `ComputeOutcome` + `summarize_compute` + `_skip_text`
完整写入 `mf4_analyzer/ui/compute_feedback.py`。

- [ ] **Step 4: 运行，确认通过**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_compute_feedback.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/compute_feedback.py tests/ui/test_compute_feedback.py
git commit -- mf4_analyzer/ui/compute_feedback.py tests/ui/test_compute_feedback.py
```
提交信息：`feat(feedback): pure compute-outcome summarizer`

---

## Task D: 反馈出口 + 接 `do_order_time`

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`（加 `_emit_compute_feedback`）
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py:183-247,267-274,420-440`
- Test: `tests/ui/test_analysis_multiview_integration.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_order_all_cached_emits_info_toast(order_window_with_cached_result, monkeypatch):
    w = order_window_with_cached_result          # 已算过一次、缓存已填的窗口 fixture
    toasts = []
    monkeypatch.setattr(type(w), 'toast', lambda self, m, lvl='info': toasts.append((lvl, m)))
    w.do_order_time()                            # 再次点：应全命中
    assert ('info', "已用缓存结果（参数未变）· 1 图") in toasts


def test_order_skip_short_signal_warns(order_window_short_signal, monkeypatch):
    w = order_window_short_signal                # 唯一 pane 的信号 < 100 点
    toasts = []
    monkeypatch.setattr(type(w), 'toast', lambda self, m, lvl='info': toasts.append((lvl, m)))
    w.do_order_time()
    assert any(lvl == 'warning' and "信号过短" in m for lvl, m in toasts)
```

> fixture 复用 `test_analysis_multiview_integration.py` 既有构造窗口/加数据的范式；
> 若无「短信号」fixture，构造一个 < 100 点的通道注入到 pane source。

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -q -k "order_all_cached or order_skip_short"`
Expected: FAIL — 当前命中只 statusBar、跳过静默。

- [ ] **Step 3: 加 `_emit_compute_feedback`（`_analysis_mixin.py`）**

```python
    def _emit_compute_feedback(self, outcome, *, busy=False, section_label="计算"):
        from ..compute_feedback import summarize_compute
        res = summarize_compute(outcome, busy=busy, section_label=section_label)
        if res is None:
            return False
        level, msg = res
        self.toast(msg, level)
        self.statusBar.showMessage(msg)
        return True
```

- [ ] **Step 4: 接 `do_order_time`（`_order_mixin.py`）**

在 `do_order_time` 顶部 re-entry 分支（`:202-204`）改：

```python
        from ..compute_feedback import ComputeOutcome
        if getattr(self, '_order_thread', None) is not None and self._order_thread.isRunning():
            self._emit_compute_feedback(ComputeOutcome(), busy=True, section_label="时间-阶次")
            return
```

pane 循环里建 `outcome = ComputeOutcome()`；命中分支（`:229-231`）`outcome.cached += 1`；
源被跳过时（把 `_dispatch_order_job` 的 `len(sig)<100` / `rpm is None` 判定前移到队列构建，
或在 dispatch 失败时回填）`outcome.skipped.append("信号过短")` / `append("缺转速")`。
队列空（`:235-242`）改为：

```python
        if not queue:
            if not any_source:
                self._do_order_time_single()
                return
            self._order_outcome = outcome
            self._emit_compute_feedback(outcome, section_label="时间-阶次")
            return
        self._order_outcome = outcome
        self._order_queue = queue
        ...
```

job 完成回调（`_on_order_finished` / 存结果处 `:434-436`）`self._order_outcome.computed += 1`；
队列 drain 终点（`_start_next_order_job` 退出，`:273-274`）：

```python
        # Queue drained.
        self.inspector.order_ctx.set_progress("")
        out = getattr(self, '_order_outcome', None)
        if out is not None:
            self._emit_compute_feedback(out, section_label="时间-阶次")
            self._order_outcome = None
```

- [ ] **Step 5: 运行，确认通过**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -q -k "order_all_cached or order_skip_short"`
Expected: PASS

- [ ] **Step 6: 回归 + 提交**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py tests/ui/test_main_window_smoke.py -q`
```bash
git add mf4_analyzer/ui/main_window/_analysis_mixin.py mf4_analyzer/ui/main_window/_order_mixin.py tests/ui/test_analysis_multiview_integration.py
git commit -- mf4_analyzer/ui/main_window/_analysis_mixin.py mf4_analyzer/ui/main_window/_order_mixin.py tests/ui/test_analysis_multiview_integration.py
```
提交信息：`feat(order): unified compute feedback (cache-hit/skip/busy toasts)`

---

## Task E: 接 `do_fft_time`

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py:228-301,_on_*_finished,_start_next_fft_time_job`
- Test: `tests/ui/test_analysis_multiview_integration.py`（追加）

- [ ] **Step 1: 写失败测试** — 镜像 Task D：`test_fft_time_all_cached_emits_info_toast`、
  `test_fft_time_reentry_busy_toast`（构造 `_fft_time_thread.isRunning()` 为真）。

```python
def test_fft_time_all_cached_emits_info_toast(fft_time_window_with_cached_result, monkeypatch):
    w = fft_time_window_with_cached_result
    toasts = []
    monkeypatch.setattr(type(w), 'toast', lambda self, m, lvl='info': toasts.append((lvl, m)))
    w.do_fft_time()
    assert any(lvl == 'info' and "已用缓存结果" in m for lvl, m in toasts)
```

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -q -k fft_time_all_cached`
Expected: FAIL（当前仅 statusBar `:292-298`）。

- [ ] **Step 3: 改实现** — 同 Task D 范式：
  - re-entry（`:228-233`）→ `_emit_compute_feedback(ComputeOutcome(), busy=True, section_label="FFT-vs-Time")`。
  - pane 循环 `outcome.cached += 1`（命中 `:278-282`）；`_dispatch_fft_time_job` 的 4 处
    `return False`（`:413,418,422,435`）回填 `outcome.skipped`（原因：`"样本不足"`/`"信号过短"`）。
  - 队列空 `any_source`（`:286-298`）→ `_emit_compute_feedback(outcome, section_label="FFT-vs-Time")` 取代 statusBar。
  - 暂存 `self._fft_time_outcome`，job 完成 `computed += 1`，drain 终点 emit。

- [ ] **Step 4: 运行，确认通过**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -q -k fft_time`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/main_window/_fft_time_mixin.py tests/ui/test_analysis_multiview_integration.py
git commit -- mf4_analyzer/ui/main_window/_fft_time_mixin.py tests/ui/test_analysis_multiview_integration.py
```
提交信息：`feat(fft-time): unified compute feedback`

---

## Task F: 接 `do_fft`（同步路径）

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_fft_mixin.py:124-193`
- Test: `tests/ui/test_analysis_multiview_integration.py`（追加）

- [ ] **Step 1: 写失败测试** — `test_fft_all_skipped_warns`（所有源 < 10 点 → 现状静默 `return`）：

```python
def test_fft_all_sources_too_short_warns(fft_window_all_short, monkeypatch):
    w = fft_window_all_short
    toasts = []
    monkeypatch.setattr(type(w), 'toast', lambda self, m, lvl='info': toasts.append((lvl, m)))
    w.do_fft()
    assert any(lvl == 'warning' for lvl, _ in toasts)
```

- [ ] **Step 2: 运行，确认失败**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py -q -k fft_all_sources_too_short`
Expected: FAIL（`:187-191` 静默 return）。

- [ ] **Step 3: 改实现** — 在 `do_fft` pane 循环建 `outcome`：
  - `len(sig)<10` / 非均匀（`:158-166`）→ `outcome.skipped.append("信号过短")` / `append("非均匀且未重建")` 后 `continue`。
  - 命中 `cache.get` 非空 → `outcome.cached += 1`；新算成功 → `outcome.computed += 1`；
    `except` 分支（`:176-178`）`outcome.failed += 1`（保留现有 `QMessageBox.critical`）。
  - 循环结束（`:187-193`）：`if any_multi:` 内统一 `if not self._emit_compute_feedback(outcome, section_label="FFT"): self._do_fft_single()`；
    `not any_multi` 仍直接 `_do_fft_single()`。删去原 `'FFT 完成'` 双写（由 summarizer 覆盖）。

- [ ] **Step 4: 运行，确认通过**

Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py tests/ui/test_fft_fetch_signal.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/main_window/_fft_mixin.py tests/ui/test_analysis_multiview_integration.py
git commit -- mf4_analyzer/ui/main_window/_fft_mixin.py tests/ui/test_analysis_multiview_integration.py
```
提交信息：`feat(fft): unified compute feedback`

---

## Task G: 导出 / 通道编辑 缺通道提示

**Files:**
- Modify: `mf4_analyzer/ui/main_window/window.py:1806-1807`
- Modify: `mf4_analyzer/ui/dialogs.py:341,361,375,376,409`
- Test: `tests/ui/test_dialogs.py`、`tests/ui/test_channel_editor_export.py`（追加）

- [ ] **Step 1: 写失败测试** — 通道编辑器在源通道缺失时点确定应弹 `QMessageBox.warning`：

```python
def test_single_channel_missing_source_warns(qtbot, monkeypatch):
    dlg = _make_channel_editor(qtbot)            # 现有 fixture
    calls = []
    monkeypatch.setattr(dialogs.QMessageBox, 'warning', staticmethod(lambda *a, **k: calls.append(a)))
    dlg._build_single_channel_with_missing_source()   # 触发 :341 的 return 分支
    assert calls
```

- [ ] **Step 2: 运行，确认失败** →
  Run: `PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ui/test_dialogs.py -q -k missing_source` → FAIL。

- [ ] **Step 3: 改实现** — 每个静默 `return` 前加提示：
  - `window.py:1806`：`self.toast("没有可导出的数据或未勾选通道", "warning")` 然后 `return`。
  - `dialogs.py` 各点：`QMessageBox.warning(self, "无法创建", "源通道不存在或参数越界")` 然后 `return`。

- [ ] **Step 4: 运行，确认通过** → 同 Step 2 命令 → PASS。

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/dialogs.py tests/ui/test_dialogs.py
git commit -- mf4_analyzer/ui/main_window/window.py mf4_analyzer/ui/dialogs.py tests/ui/test_dialogs.py
```
提交信息：`fix(export,channel-editor): warn instead of silent no-op on missing inputs`

---

# P2 — 体验兜底

## Task H: 切片手势落空轻提示

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:1529,1533-1539`（经已有信号/回调把消息转主窗口 toast）
- Test: `tests/ui/test_canvases.py` 或 `test_chart_stack.py`（按 heatmap 测试落点）

- [ ] **Step 1: 写失败测试** — 在结果未就绪时点击取片，应发出一个「提示」信号/回调（断言被调用）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 改实现** — `_matrix_disp/_slice_curve/_extents is None` → 发提示「先点计算生成谱图」；
  点击越界（`if x0<=x<=x1` 加 `else`）→ 提示「点击位置超出谱图范围」。复用 heatmap 既有
  「取片」信号通道把文案传到 `MainWindow.toast`（避免画布直接依赖主窗口）。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** — `feat(heatmap): hint when slice gesture lands on empty/out-of-range`。

## Task I: 切 Tab 空图占位

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py:531-537`
- Test: `tests/ui/test_analysis_section_page.py`（追加）

- [ ] **Step 1: 写失败测试** — 命中缺失渲染时，pane 画布进入「空态占位」标志位为真（而非纯空）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 改实现** — 在仅 statusBar 提示处，调用 pane 画布的空态占位（复用现有 hint/empty-state
  控件；若无则在画布中心画「点击『计算』生成」文字层）。保留状态栏文案。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** — `feat(analysis): empty-state placeholder on cache-miss tab switch`。

## Task J: 被吞异常恢复路径告警

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py:466-467`、`_project_io_mixin.py:329-331`
- Test: `tests/ui/test_project_io_analysis_views.py`（追加）

- [ ] **Step 1: 写失败测试** — 让恢复期 compute 抛异常，断言 `toast('warning')` 被调用（而非 `pass`）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 改实现** — `except Exception:` 分支由 `pass`/仅状态栏 改为
  `self.toast("恢复渲染失败，请手动点计算", "warning")`（仍吞异常不崩，但用户可感知）。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** — `fix(project-io): surface recovery-render failures via toast`。

## Task K: 保存项目成功 toast 对称

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py:225`
- Test: `tests/ui/test_project_io.py` 或 `tests/test_project_io.py`（追加）

- [ ] **Step 1: 写失败测试** — 保存成功后断言 `toast('success', "已保存项目")` 被调用。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 改实现** — `:225` 状态栏后补 `self.toast("已保存项目", "success")`。
- [ ] **Step 4: 运行确认通过。**
- [ ] **Step 5: 提交** — `feat(project-io): success toast on save (parity with export/load)`。

## Task L（可选，perf）: fft_time 键去 `db_reference`

**Files:**
- Modify: `_fft_time_mixin.py:61`、`_analysis_mixin.py:378`（+ `SpectrogramParams` 评估）
- Test: `tests/ui/test_analysis_multiview_integration.py` / `tests/test_spectrogram.py`

- [ ] **Step 1: 写失败测试** — 只改 `db_reference` 后，fft_time 分析键不变（命中、不重算）。
- [ ] **Step 2: 运行确认失败。**
- [ ] **Step 3: 改实现** — 从两处键移除 `db_reference`。⚠️ `SpectrogramParams` 为 `frozen` 且
  `db_reference` 持久化于 `result.params`：评估能否安全移除；若牵动过大则**不做**，仅在键层不参与即可。
- [ ] **Step 4: 运行确认通过（含 `test_spectrogram.py` 全绿）。**
- [ ] **Step 5: 提交** — `perf(fft-time): drop display-only db_reference from compute key`。

---

## 收尾验收

- [ ] 全量：`PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`，全绿、无新 warning。
- [ ] 真机复核（offscreen 无法证可见性）：
  1. 阶次页改 RPM系数 → 点计算 → 图变化 + `success` toast；不改再点 → `info`「已用缓存结果」。
  2. 保存图片到只读/坏路径 → 弹「保存失败」。
  3. 某 pane 注入 < 100 点信号 → 计算结束有 `warning` 跳过汇总 toast。
- [ ] 标注真机验证状态；未验的 UI 可见性项不得声称「已解决」（memory `feedback-verify-ui-visually`）。

## 自检（writing-plans self-review）

- **Spec 覆盖**：P0-1/P0-2/P1(C–G)/P2(H–L) 一一对应设计文档各节，无遗漏。
- **占位符**：无 TBD；每个代码步骤给出可粘贴代码或精确锚点 + 范式。
- **类型一致**：`ComputeOutcome` 字段（computed/cached/failed/skipped）、`summarize_compute(outcome, *, busy, section_label)`、`_emit_compute_feedback(outcome, *, busy, section_label)` 在 C–F 全程一致。
- **风险/回滚**：每任务独立可 revert；P0 两任务零依赖可先单独落地（直接解决用户投诉）；P1 依赖 Task C 先行；P2 全部可选、互不依赖。
