# 时域图拖动去抖优化 + GPU 改动回滚 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除分屏时域图拖动卡顿——把拖动时每个鼠标移动 tick 的同步重活（刻度重算 + 信号级联）去抖到「松手/停顿」;同时回滚没有解决问题的 OpenGL 开关改动。

**Architecture:** `_on_xrange_changed` 每个 sigXRangeChanged tick 只保留廉价、视觉必需的工作（降质 + 子图 x 范围同步）;把昂贵的 `_apply_target_x_ticks_to_all_axes`（实测 5.68ms/次）与 `_emit_xrange_changed`（驱动 MainWindow 每 tick 捕获范围）移入已去抖的 `_refresh_visible_data`。GPU 开关相关代码全部移除,事件过滤器安装还原为切换前的内联形式。

**Tech Stack:** PyQt5, pyqtgraph, pytest（offscreen Qt）。

**前置：** 用 `superpowers:using-git-worktrees` 建隔离工作区,从 `main`（或当前工作分支)切出新分支。commit 消息结尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

**根因证据（本次实测,分屏 7 通道 全屏 2560×1400 dpr=2):**
- `_apply_target_x_ticks_to_all_axes()` = **5.68ms/次**,在 `_on_xrange_changed`（`pg_canvases.py:3638`）每个 tick 同步执行,**未去抖**;对 7 个轴逐个 `setTicks`（`pg_canvases.py:3200`）。
- 模拟一次拖动 30 个 tick = **1220ms 主线程阻塞**（~40ms/tick）→ 用户体感「拖一次像在等渲染、渲染时点啥都卡」。
- 与 CPU/GPU 无关（GPU 只加速画线,碰不到刻度重算/事件级联）→ 这正是「勾 GPU 感觉不到差异」的原因。
- 监听者:`xrange_changed`→`_on_time_canvas_xrange_changed`、`visible_range_changed`→`_capture_canvas_ranges_for_bound_view`（`main_window.py:441/447`),均每 tick 跑,松手做即可。

---

## 文件结构

- `mf4_analyzer/ui/pg_canvases.py` — 去抖核心改动(`_on_xrange_changed` 瘦身、`_refresh_visible_data` 收尾补刻度/发信号);GPU 回滚(移除 `set_gpu_render`/`_apply_gpu_viewport`/`_install_viewport_event_filter`/`_cpu_raster_for_grab`/相关属性,还原内联事件过滤器与 `grab_pixmap`)。
- `mf4_analyzer/app.py` — 移除 `_configure_gl_surface_format`。
- `mf4_analyzer/ui/main_window.py` — 移除 GPU 持久化 helper、`set_gpu_render`、`_sync_gpu_render_pref`、信号连接。
- `mf4_analyzer/ui/inspector.py` — 移除 GPU 勾选框、信号、`set_gpu_toggle_checked`。
- `tests/ui/test_gpu_render_toggle.py` — 删除。
- `tests/ui/test_xrange_debounce.py` — 新增去抖行为测试。

---

# 阶段 A — 回滚 OpenGL 改动（先回到干净 CPU 基线）

> 用「正向删除」而非 `git revert`:GPU 提交之后又叠了 view 相关提交,revert 会冲突。按下列精确落点删除,最后用 grep 验证无残留 + 全测试绿。

## Task A1: 删除画布层 GPU 代码并还原内联事件过滤器

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`

- [ ] **Step 1: 删除 `__init__` 中 GPU 状态属性**

删除 `pg_canvases.py:1062-1064`：

```python
        self._gpu_render_requested = False
        self._gpu_render_on = False
        self._gpu_viewport_filter_target = None
```

- [ ] **Step 2: 还原内联事件过滤器安装**

把 `pg_canvases.py:1201` 的：

```python
        self._install_viewport_event_filter()
```

还原为切换前的内联形式：

```python
        try:
            viewport = self._glw.viewport()
            if viewport is not None:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
        except Exception:
            pass
```

- [ ] **Step 3: 删除 `plot_channels` 末尾 GPU 重试**

删除 `pg_canvases.py:1456-1457`：

```python
        if bool(getattr(self, "_gpu_render_requested", False)) != bool(getattr(self, "_gpu_render_on", False)):
            self._apply_gpu_viewport()
```

- [ ] **Step 4: 删除 `_install_viewport_event_filter` / `set_gpu_render` / `_apply_gpu_viewport`**

删除整段 `pg_canvases.py:4728-4784`（`def _install_viewport_event_filter` 到 `_apply_gpu_viewport` 结束,即 `disable_interactive_quality` 定义之前的全部 GPU 方法）。

- [ ] **Step 5: 还原 `grab_pixmap`,删除 `_cpu_raster_for_grab`**

删除 `_cpu_raster_for_grab` 上下文管理器（`pg_canvases.py:4995` 起整段定义）。
在 `grab_pixmap`（`pg_canvases.py:5009`)中,把：

```python
        with self._cpu_raster_for_grab():
            if affordable:
                with self._curves_antialiased():
                    pix = _grab_first_good()
            else:
                pix = _grab_first_good()
```

还原为（去掉外层 `with`,整体左移一层）：

```python
        if affordable:
            with self._curves_antialiased():
                pix = _grab_first_good()
        else:
            pix = _grab_first_good()
```

- [ ] **Step 6: 验证画布无 GPU 残留**

Run: `grep -nE "_gpu_render|set_gpu_render|_apply_gpu_viewport|_install_viewport_event_filter|_cpu_raster_for_grab|_gpu_viewport_filter_target" mf4_analyzer/ui/pg_canvases.py`
Expected: 无输出。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvases.py
git commit -m "revert(pg): remove GPU render toggle plumbing from TimeDomainCanvasPG"
```

## Task A2: 删除 app.py / main_window.py / inspector.py 的 GPU 代码

**Files:**
- Modify: `mf4_analyzer/app.py`, `mf4_analyzer/ui/main_window.py`, `mf4_analyzer/ui/inspector.py`
- Delete: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: app.py 移除 MSAA helper**

删除 `app.py:64-73` 的 `def _configure_gl_surface_format(): ...` 整个函数,并删除 `main()` 中 `app.py:75` 的调用行 `_configure_gl_surface_format()`。

- [ ] **Step 2: main_window.py 移除 GPU 持久化与入口**

删除以下片段：
- `main_window.py:32-48`：`GPU_RENDER_SETTINGS_ORG/APP/KEY` 三个常量 + `gpu_render_settings()` + `read_gpu_render_pref()` + `write_gpu_render_pref()`。
- `main_window.py:134`：`self._sync_gpu_render_pref()`。
- `main_window.py:337`：`self.inspector.gpu_render_toggled.connect(self.set_gpu_render)`。
- `main_window.py:735-743`：`def _sync_gpu_render_pref(self)` 与 `def set_gpu_render(self, on)` 两个方法。

- [ ] **Step 3: main_window.py 清理 QSettings import（条件)**

Run: `grep -nE "QSettings" mf4_analyzer/ui/main_window.py`
若仅剩 import 行(无其它用法),从 `from PyQt5.QtCore import ...` 中移除 `QSettings`;若有其它用法则保留。

- [ ] **Step 4: inspector.py 移除勾选框/信号/方法**

删除：
- `inspector.py:60`：`gpu_render_toggled = pyqtSignal(bool)`。
- `inspector.py:120-124`：`self.gpu_toggle = QCheckBox(...)` 创建与 `lay.addWidget(self.gpu_toggle)` 共 5 行。
- `inspector.py:167-172`：`def set_gpu_toggle_checked(self, on)` 方法。
- import 块中的 `QCheckBox`（若 inspector.py 无其它处使用;先 `grep -n QCheckBox mf4_analyzer/ui/inspector.py` 确认）。

- [ ] **Step 5: 删除 GPU 测试文件**

Run: `git rm tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 6: 全仓库验证无 GPU 残留**

Run:
```bash
grep -rnE "gpu_render|set_gpu_render|GPU_RENDER|gpu_toggle|_configure_gl_surface_format|GPU 加速" mf4_analyzer/ tests/
```
Expected: 无输出（docs/ 下的旧 spec/plan 保留作历史,不在此 grep 范围）。

- [ ] **Step 7: 全量 UI 测试绿**

Run: `.venv/bin/python -m pytest tests/ui -q`
Expected: 全绿（GPU 测试已删,其余不受影响）。

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "revert(ui): remove GPU render toggle UI, persistence, MSAA and tests"
```

---

# 阶段 B — 拖动去抖优化（真修复）

## Task B1: 把刻度重算 + 范围信号从 per-tick 移到去抖路径

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（`_on_xrange_changed` 约 `3624`;`_refresh_visible_data` 末尾)
- Test: `tests/ui/test_xrange_debounce.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_xrange_debounce.py
import numpy as np
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _subplot_canvas():
    c = TimeDomainCanvasPG()
    c.resize(800, 600)
    t = np.linspace(0, 10, 5000)
    rows = [(f"ch{i}", True, t, np.sin(t + i), "#1769e0", "u", "fid") for i in range(3)]
    c.plot_channels(rows, mode="subplot")
    return c


def test_tick_recompute_is_debounced_not_per_drag_tick(qapp):
    c = _subplot_canvas()
    calls = {"n": 0}
    orig = c._apply_target_x_ticks_to_all_axes
    c._apply_target_x_ticks_to_all_axes = lambda: (calls.__setitem__("n", calls["n"] + 1), orig())[1]

    src = c._primary_xaxis_ax
    for _ in range(20):  # 模拟拖动:连发 20 个 tick,去抖定时器不触发
        c._on_xrange_changed(src)
    assert calls["n"] == 0, "刻度重算不得在每个拖动 tick 同步执行"

    c._flush_pending_refresh()  # 松手:去抖刷新
    assert calls["n"] >= 1, "刻度重算必须在松手/去抖刷新时执行"


def test_emit_xrange_is_debounced_not_per_drag_tick(qapp):
    c = _subplot_canvas()
    emitted = {"n": 0}
    c.xrange_changed.connect(lambda lo, hi: emitted.__setitem__("n", emitted["n"] + 1))

    src = c._primary_xaxis_ax
    for _ in range(20):
        c._on_xrange_changed(src)
    assert emitted["n"] == 0, "xrange_changed 不得每个拖动 tick 发一次"

    c._flush_pending_refresh()
    assert emitted["n"] >= 1, "松手时必须发一次 xrange_changed"


def test_sibling_propagation_stays_per_tick(qapp):
    c = _subplot_canvas()
    cnt = {"n": 0}
    orig = c._propagate_xlim_to_siblings
    c._propagate_xlim_to_siblings = lambda source=None: (cnt.__setitem__("n", cnt["n"] + 1), orig(source=source))[1]

    src = c._primary_xaxis_ax
    for _ in range(10):
        c._on_xrange_changed(src)
    assert cnt["n"] == 10, "子图 x 范围同步必须保持每 tick(拖动中子图要一起平移)"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_xrange_debounce.py -v`
Expected: 前两个 FAIL（当前 `_on_xrange_changed` 每 tick 调刻度重算+发信号,`calls["n"]==20`、`emitted["n"]==20`);第三个 PASS。

- [ ] **Step 3: 瘦身 `_on_xrange_changed`**

把 `pg_canvases.py:3638-3647` 当前：

```python
        self.disable_interactive_quality()
        # Propagate first so the sibling axes are in sync BEFORE the
        # debounced refresh runs.
        self._propagate_xlim_to_siblings(source=source_handle)
        self._apply_target_x_ticks_to_all_axes()
        self._emit_xrange_changed(source_handle)
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()
```

改为（移除 per-tick 的刻度重算与发信号;它们随去抖刷新执行）：

```python
        self.disable_interactive_quality()
        # 拖动中只做廉价、视觉必需的工作:降质 + 子图 x 范围同步(子图要一起平移)。
        # 刻度重算(_apply_target_x_ticks_to_all_axes ~5.68ms/次)与范围信号
        # (_emit_xrange_changed → MainWindow 捕获)是重活,移到去抖的
        # _refresh_visible_data,避免每个鼠标移动 tick 同步阻塞主线程。
        self._propagate_xlim_to_siblings(source=source_handle)
        if self._refresh_pending:
            return
        self._refresh_pending = True
        self._refresh_timer.start()
```

- [ ] **Step 4: 在 `_refresh_visible_data` 收尾补刻度重算 + 发信号**

`_refresh_visible_data` 末尾当前为：

```python
        self._refresh = True
        self.schedule_idle_quality()
```

改为（在置位前补两步;拖动中由 40ms 去抖定时器节流,松手由 `_flush_pending_refresh` 兜底）：

```python
        # 去抖收尾:刻度重算与范围信号从 per-tick 迁来,随刷新节流执行。
        self._apply_target_x_ticks_to_all_axes()
        self._emit_xrange_changed()
        self._refresh = True
        self.schedule_idle_quality()
```

> 说明:`_emit_xrange_changed(source_handle=None)` 会回退到 `_primary_xaxis_ax`;子图模式下各轴范围已同步,从主轴发信号正确。

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_xrange_debounce.py -v`
Expected: 3 项全 PASS。

- [ ] **Step 6: 防回归——跑相关既有测试**

Run: `.venv/bin/python -m pytest tests/ui/test_split_routing.py tests/ui/test_split_focus_routing.py tests/ui/test_view_switch_integration.py tests/ui/test_pg_timedomain_canvas.py -q`
Expected: 全绿(范围同步/分屏路由/刻度行为不回归)。

- [ ] **Step 7: 提交**

```bash
git add tests/ui/test_xrange_debounce.py mf4_analyzer/ui/pg_canvases.py
git commit -m "perf(pg): debounce x-tick recompute and range signals out of per-drag-tick path"
```

---

# 阶段 C — 验证

## Task C1: 量化拖动成本下降（脚本基线对比）

**Files:** 无（一次性测量脚本,不入库）

- [ ] **Step 1: 改前基线已知**

改前实测(本计划根因证据):分屏 7 通道全屏,模拟 30 tick 拖动 ≈ **1220ms**,`_apply_target_x_ticks_to_all_axes` 5.68ms/tick。

- [ ] **Step 2: 改后复测**

跑下列脚本(分屏 7 通道,全屏尺寸),对比每 tick 同步成本：

```bash
cd "/Users/donghang/Downloads/data analyzer" && .venv/bin/python - <<'PY' 2>&1 | grep -vE "qt.qpa|^QApplication|deprecat"
import numpy as np, time
from asammdf import MDF
from PyQt5.QtWidgets import QApplication
app=QApplication([])
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
m=MDF("testdoc/tiaodamping.MF4"); chans=[]
for grp in m.groups:
    for c in grp.channels:
        nm=c.name
        if not nm or nm.lower() in ("time","t","comment"): continue
        sig=m.get(nm)
        if len(sig.samples)>1000 and np.issubdtype(sig.samples.dtype,np.number):
            chans.append((nm,np.asarray(sig.timestamps,float),np.asarray(sig.samples,float)))
    if len(chans)>=7: break
m.close()
lo,hi=chans[0][1][0],chans[0][1][-1]
cv=TimeDomainCanvasPG(); cv.resize(2560,1400); cv._glw.resize(2560,1400); cv.show()
for _ in range(8): app.processEvents()
cv.plot_channels([(nm,True,t,s,"#1769e0","u","fid") for nm,t,s in chans[:7]], mode="subplot")
for _ in range(6): app.processEvents()
src=cv._primary_xaxis_ax; vb=src.view_box; span=(hi-lo)*0.5
N=30; t0=time.perf_counter()
for k in range(N):
    off=lo+(k/N)*span*0.2; vb.setXRange(off,off+span,padding=0); app.processEvents()
print(f"改后:模拟拖动 {N} tick 总耗时 = {(time.perf_counter()-t0)*1000:.1f} ms (改前 ~1220ms)")
cv.hide(); app.quit()
PY
```
Expected: 总耗时显著下降(去掉了 5.68ms/tick 的刻度重算 + 每 tick 的范围捕获级联)。

## Task C2: 真机冒烟（必做）

> 脚本测不到 GPU/屏上真实交互;拖动跟手感必须真机确认。

- [ ] **Step 1: 启动**

Run: `.venv/bin/python -m mf4_analyzer.app`（5K 全屏)。

- [ ] **Step 2: 复现场景**

加载 `testdoc/tiaodamping.MF4`,**分屏**模式勾 7 个通道,用「移动曲线」拖动 X。

- [ ] **Step 3: 确认**
- 拖动跟手,不再出现「拖一次卡住等渲染」;
- 松手后刻度密度正确刷新(拖动中刻度跟随平移、密度松手再更新,可接受);
- 分屏各子图拖动时**一起平移**(子图同步未被破坏);
- 右侧「图表设置」面板**不再有** GPU 勾选框(回滚生效)。

---

## Self-Review（计划 vs 目标)

- **覆盖:** 真优化(去抖)→ B1;GPU 回滚 → A1(画布)/A2(app/main_window/inspector/测试);验证 → C1(量化)/C2(真机)。
- **占位符扫描:** 无 TBD;每步给出精确文件:行与替换/删除代码。
- **行为正确性:** 保留 per-tick 的 `disable_interactive_quality` + `_propagate_xlim_to_siblings`(子图拖动一起平移);仅把 `_apply_target_x_ticks_to_all_axes` + `_emit_xrange_changed` 迁到去抖 `_refresh_visible_data`。测试用「调用计数」而非计时,确定性。
- **回滚完整性:** grep 验证(A1 Step6 / A2 Step6)确保无 `gpu_render`/`set_gpu_render`/`GPU 加速` 等残留;还原内联事件过滤器与 `grab_pixmap`;删 GPU 测试。
- **命名一致:** 复用既有 `_apply_target_x_ticks_to_all_axes`/`_emit_xrange_changed`/`_propagate_xlim_to_siblings`/`_refresh_visible_data`/`_flush_pending_refresh`,无新符号漂移。
