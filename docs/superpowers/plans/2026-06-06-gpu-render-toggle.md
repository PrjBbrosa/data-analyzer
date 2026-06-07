# 时域图 GPU 加速开关 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给时域画布 `TimeDomainCanvasPG` 加一个用户可控、默认关、持久化的「GPU 加速」开关，开启后走 pyqtgraph 的 OpenGL viewport 路解决全屏/高分屏/多通道卡顿。

**Architecture:** 只作用于唯一的 pyqtgraph 画布 `canvas_time`（FFT/阶次是 matplotlib，OpenGL 不适用）。GPU 模式只用 GL viewport 路（Qt GPU 画引擎，保留线宽/虚线/AA 的 QPainter 语义），**不**用需要 PyOpenGL 的 raw-GL 路。Canvas 内部分离 requested/applied 状态，`useOpenGL()` 替换 viewport 后必须重装现有 event filter；开关在右侧 Inspector 底部，状态存显式 `QSettings("MF4Analyzer", "DataAnalyzer")`；GPU 下导出通过同一 viewport 切换 helper 临时切回 CPU 光栅再抓图。

**Tech Stack:** PyQt5, pyqtgraph (GraphicsLayoutWidget.useOpenGL), QSurfaceFormat (MSAA), QSettings, pytest（offscreen Qt）。

**前置：** 实现前用 `superpowers:using-git-worktrees` 建隔离工作区，并从 `main` 切出新分支（当前 `docs/timedomain-view-tabs-plan` 不是本特性分支）。所有 commit 消息结尾加 `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。设计依据：`docs/superpowers/specs/2026-06-06-gpu-render-toggle-design.md`。

---

## 文件结构

- `mf4_analyzer/ui/pg_canvases.py` — 画布开关 `set_gpu_render`；`_gpu_render_requested` / `_gpu_render_on`；viewport event-filter 绑定 helper；导出 CPU 回切上下文管理器。
- `mf4_analyzer/app.py` — 启动期 MSAA 默认 surface format。
- `mf4_analyzer/ui/main_window.py` — QSettings 读写 helper、`MainWindow.set_gpu_render`、启动同步与信号连接。
- `mf4_analyzer/ui/inspector.py` — 右侧底部 `GPU 加速` 勾选框与 `gpu_render_toggled` 信号。
- `tests/ui/test_gpu_render_toggle.py` — 新增全部单测。

---

## Task 1: 画布渲染后端开关 + viewport event-filter 重绑

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（`__init__` 内 `self._glw = ...` 之后约 `1045` 行；替换 viewport event-filter 安装块约 `1198-1203` 行；`plot_channels()` 末尾约 `1458` 行；类内新增方法）
- Test: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_gpu_render_toggle.py
import numpy as np
from PyQt5.QtCore import QCoreApplication, QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG


def _gpu_canvas(qapp):
    c = TimeDomainCanvasPG()
    c.resize(640, 360)
    c.show()
    QCoreApplication.processEvents()
    return c


class _SwappingGlw:
    """Tiny GraphicsLayoutWidget fake: useOpenGL swaps the viewport object."""

    def __init__(self):
        self.calls = []
        self.cpu_viewport = QWidget()
        self.gpu_viewport = QWidget()
        for viewport in (self.cpu_viewport, self.gpu_viewport):
            viewport.resize(120, 80)
            viewport.show()
        self._viewport = self.cpu_viewport

    def useOpenGL(self, on):
        self.calls.append(bool(on))
        self._viewport = self.gpu_viewport if on else self.cpu_viewport

    def viewport(self):
        return self._viewport

    def update(self):
        pass


def test_set_gpu_render_tracks_requested_applied_and_is_idempotent(qapp):
    c = _gpu_canvas(qapp)
    glw = _SwappingGlw()
    c._glw = glw
    c._gpu_viewport_filter_target = None
    assert c._gpu_render_requested is False
    assert c._gpu_render_on is False
    c.set_gpu_render(True)
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is True
    assert c._gpu_viewport_filter_target is glw.gpu_viewport
    c.set_gpu_render(True)  # 幂等
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is True
    c.set_gpu_render(False)
    assert c._gpu_render_requested is False
    assert c._gpu_render_on is False
    assert glw.calls == [True, False]


def test_gpu_render_rebinds_viewport_event_filter_after_switch(qapp, monkeypatch):
    c = _gpu_canvas(qapp)
    glw = _SwappingGlw()
    c._glw = glw
    c._gpu_viewport_filter_target = None
    c._install_viewport_event_filter()
    seen = []
    monkeypatch.setattr(
        c,
        "_handle_viewport_double_click",
        lambda pos: seen.append(pos),
    )
    c.set_gpu_render(True)
    viewport = glw.gpu_viewport
    assert c._gpu_viewport_filter_target is viewport
    QTest.mouseDClick(viewport, Qt.LeftButton, Qt.NoModifier, QPoint(12, 12))
    QCoreApplication.processEvents()
    assert seen, "double-click must still enter eventFilter after viewport swap"


def test_set_gpu_render_failure_keeps_applied_false_and_can_retry(qapp):
    c = _gpu_canvas(qapp)

    class BoomThenOk:
        def __init__(self):
            self.calls = []

        def useOpenGL(self, on):
            self.calls.append(bool(on))
            if len(self.calls) == 1:
                raise RuntimeError("no GL here")

        def viewport(self):
            return None

        def update(self):
            pass

    glw = BoomThenOk()
    c._glw = glw
    c._gpu_render_requested = False
    c._gpu_render_on = False
    c._gpu_viewport_filter_target = None

    c.set_gpu_render(True)  # 不得抛
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is False  # applied 状态不能假装已开启

    c._apply_gpu_viewport()  # 模拟 plot_channels 末尾重试
    assert c._gpu_render_on is True
    assert glw.calls == [True, True]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -v`
Expected: FAIL（`AttributeError: 'TimeDomainCanvasPG' object has no attribute '_gpu_render_requested'` / `set_gpu_render` / `_gpu_viewport_filter_target`）

- [ ] **Step 3: 初始化标志**

在 `__init__` 中 `self._glw = pg.GraphicsLayoutWidget(self)`（约 `1045` 行）之后新增：

```python
        # GPU 渲染开关状态（仅时域图）。requested 是用户/持久化期望，
        # on 是当前 viewport 实际 applied 状态；导出路径只看 applied。
        self._gpu_render_requested = False
        self._gpu_render_on = False
        self._gpu_viewport_filter_target = None
```

并把 `__init__` 里当前直接安装 `viewport.installEventFilter(self)` 的 try-block（约 `1198-1203`）替换为：

```python
        self._install_viewport_event_filter()
```

- [ ] **Step 4: 实现 set_gpu_render**

在类内（建议紧邻 `disable_interactive_quality` 附近，约 `4729` 行前后）新增：

```python
    def _install_viewport_event_filter(self) -> None:
        """Install this canvas' QWidget eventFilter on the current GLW viewport.

        ``GraphicsView.useOpenGL`` replaces the viewport widget. The event
        filter owns double-click chart options, overlay selection/Y-drag, and
        cursor press/move/release, so every CPU/GL swap must rebind it.
        """
        previous = getattr(self, "_gpu_viewport_filter_target", None)
        if previous is not None:
            try:
                previous.removeEventFilter(self)
            except Exception:
                pass
        viewport = None
        try:
            viewport = self._glw.viewport()
        except Exception:
            viewport = None
        if viewport is not None:
            try:
                viewport.setMouseTracking(True)
                viewport.installEventFilter(self)
            except Exception:
                viewport = None
        self._gpu_viewport_filter_target = viewport

    def set_gpu_render(self, on: bool) -> None:
        """在 CPU 软件光栅与 OpenGL viewport 之间切换时域画布。

        GPU 模式只用 pyqtgraph 的 GL *viewport* 路（Qt 的 QOpenGLPaintEngine），
        不用需要 PyOpenGL 的实验性 raw-GL 逐曲线路 —— 因此线宽、虚线光标、抗锯齿
        都保持 QPainter 语义，与 CPU 一致。
        """
        self._gpu_render_requested = bool(on)
        self._apply_gpu_viewport()

    def _apply_gpu_viewport(self) -> None:
        """Apply requested GPU state to the actual GraphicsView viewport.

        Failure keeps ``_gpu_render_requested`` intact but does not mark
        ``_gpu_render_on`` true. ``plot_channels`` retries this helper after a
        rebuild, so a transient driver/context failure can recover later.
        """
        desired = bool(getattr(self, "_gpu_render_requested", False))
        if desired == bool(getattr(self, "_gpu_render_on", False)):
            self._install_viewport_event_filter()
            return
        glw = getattr(self, "_glw", None)
        if glw is None:
            self._gpu_render_on = False
            return
        try:
            glw.useOpenGL(desired)
        except Exception as exc:  # noqa: BLE001 - 任何驱动异常都退化，不崩
            _log.warning("useOpenGL(%s) failed; will retry after next plot: %s", desired, exc)
            return
        self._gpu_render_on = desired
        self._install_viewport_event_filter()
        try:
            self._flush_pending_refresh()
        except Exception:
            pass
        try:
            glw.update()  # 把现有 scene 重绘进新 viewport
        except Exception:
            pass
```

- [ ] **Step 4b: 在 plot_channels 末尾补重试**

在 `plot_channels()` 末尾 `_run_replot_callbacks()` 后、`disable_interactive_quality()` 前加入：

```python
        if bool(getattr(self, "_gpu_render_requested", False)) != bool(getattr(self, "_gpu_render_on", False)):
            self._apply_gpu_viewport()
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -v`
Expected: PASS（3 项）

- [ ] **Step 6: 提交**

```bash
git add tests/ui/test_gpu_render_toggle.py mf4_analyzer/ui/pg_canvases.py
git commit -m "feat(pg): add set_gpu_render OpenGL-viewport toggle on TimeDomainCanvasPG"
```

---

## Task 2: GPU 下导出临时切回 CPU 抓图

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py`（新增上下文管理器；`grab_pixmap` 约 `4937` 行包裹抓图段）
- Test: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: 写失败测试**

```python
def test_grab_pixmap_roundtrips_gl_off_then_on_when_gpu(qapp):
    c = _gpu_canvas(qapp)
    calls = []
    real_glw = c._glw

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def useOpenGL(self, on):
            calls.append(bool(on))

        def __getattr__(self, k):
            return getattr(self._inner, k)

    c._glw = Spy(real_glw)
    c._gpu_render_requested = True
    c._gpu_render_on = True
    pix = c.grab_pixmap()
    assert pix is not None and not pix.isNull()
    assert calls == [False, True]  # 抓图前关 GL，finally 恢复
    assert c._gpu_render_requested is True
    assert c._gpu_render_on is True


def test_grab_pixmap_no_gl_toggle_when_cpu(qapp):
    c = _gpu_canvas(qapp)
    calls = []
    real_glw = c._glw

    class Spy:
        def __init__(self, inner):
            self._inner = inner

        def useOpenGL(self, on):
            calls.append(bool(on))

        def __getattr__(self, k):
            return getattr(self._inner, k)

    c._glw = Spy(real_glw)
    c._gpu_render_requested = False
    c._gpu_render_on = False
    c.grab_pixmap()
    assert calls == []  # CPU 模式不动 viewport


def _pixmap_has_nonblank_content(pix):
    from PyQt5.QtGui import QColor, QImage

    img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    if img.width() <= 1 or img.height() <= 1:
        return False
    step_x = max(1, img.width() // 80)
    step_y = max(1, img.height() // 50)
    for y in range(0, img.height(), step_y):
        for x in range(0, img.width(), step_x):
            c = QColor(img.pixel(x, y))
            if c.alpha() > 0 and (c.red() < 245 or c.green() < 245 or c.blue() < 245):
                return True
    return False


def test_gpu_grab_pixmap_cpu_roundtrip_returns_nonblank_content(qapp):
    c = _gpu_canvas(qapp)
    t = np.linspace(0, 1, 200)
    c.plot_channels([
        ("speed", True, t, np.sin(t * 20), "#1769e0", "rpm", "f")
    ])
    QCoreApplication.processEvents()
    c._gpu_render_requested = True
    c._gpu_render_on = True

    pix = c.grab_pixmap(scale=1.0)

    assert pix is not None and not pix.isNull()
    assert pix.width() > 1 and pix.height() > 1, "must not return 1x1 fallback"
    assert _pixmap_has_nonblank_content(pix), "GPU export fallback must contain chart pixels"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k grab_pixmap -v`
Expected: FAIL（`calls == []`，因为现在 grab_pixmap 不切换 GL；若手动伪造空白抓图，nonblank 测试也会暴露 fallback）

- [ ] **Step 3: 新增 CPU 回切上下文管理器**

在 `grab_pixmap` 方法前新增（`contextmanager` 已在文件头 import，见 `pg_canvases.py:63`）：

```python
    @contextmanager
    def _cpu_raster_for_grab(self):
        """GPU 模式下导出时临时切回 CPU 光栅，抓完恢复。

        GL viewport 内容对 QWidget.grab() 不可见（抓出空白），且 grabFramebuffer
        在无头/部分环境实测返回空白不可靠。导出非性能敏感，故复用已验证可用的
        CPU 抓图路径：关 GL → 抓 → 恢复 GL（try/finally 保证恢复）。
        OFF/ON 都走 _apply_gpu_viewport()，让 viewport event filter 随新 viewport 重绑。
        """
        restore_requested = bool(getattr(self, "_gpu_render_requested", False))
        restore_applied = bool(getattr(self, "_gpu_render_on", False))
        if restore_applied:
            self._gpu_render_requested = False
            self._apply_gpu_viewport()
        try:
            yield
        finally:
            self._gpu_render_requested = restore_requested
            if restore_applied or restore_requested:
                self._apply_gpu_viewport()
```

- [ ] **Step 4: 包裹 grab_pixmap 的抓图段**

把 `grab_pixmap` 中的这段：

```python
        if affordable:
            with self._curves_antialiased():
                pix = _grab_first_good()
        else:
            pix = _grab_first_good()
```

改为：

```python
        with self._cpu_raster_for_grab():
            if affordable:
                with self._curves_antialiased():
                    pix = _grab_first_good()
            else:
                pix = _grab_first_good()
```

（`_grab_widget_scaled` 是 `grab_pixmap` 内部调用，无需单独改。）

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -v`
Expected: PASS（6 项）

- [ ] **Step 6: 提交**

```bash
git add tests/ui/test_gpu_render_toggle.py mf4_analyzer/ui/pg_canvases.py
git commit -m "fix(pg): export grabs via CPU raster roundtrip when GPU render is on"
```

---

## Task 3: 启动期 MSAA 默认 surface format

**Files:**
- Modify: `mf4_analyzer/app.py`（新增 `_configure_gl_surface_format`；`main()` 中 `_configure_high_dpi()` 后、`QApplication(sys.argv)` 前调用）
- Test: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: 写失败测试**

```python
def test_configure_gl_surface_format_sets_msaa(qapp):
    from PyQt5.QtGui import QSurfaceFormat
    from mf4_analyzer.app import _configure_gl_surface_format

    _configure_gl_surface_format()
    assert QSurfaceFormat.defaultFormat().samples() == 4


def test_main_configures_gl_surface_format_before_qapplication():
    import inspect
    import mf4_analyzer.app as appmod

    src = inspect.getsource(appmod.main)
    assert src.index("_configure_high_dpi()") < src.index("_configure_gl_surface_format()")
    assert src.index("_configure_gl_surface_format()") < src.index("QApplication(")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k surface_format -v`
Expected: FAIL（`ImportError: cannot import name '_configure_gl_surface_format'`，或源码顺序断言失败）

- [ ] **Step 3: 实现 helper**

在 `app.py` 的 `_configure_high_dpi` 定义之后新增：

```python
def _configure_gl_surface_format():
    """为默认 GL surface 申请 4× MSAA（GPU 渲染开启时时域画布用）。

    必须在 QApplication 创建任何 GL 上下文之前运行。对 CPU 光栅路径无影响。
    """
    from PyQt5.QtGui import QSurfaceFormat

    fmt = QSurfaceFormat.defaultFormat()
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
```

- [ ] **Step 4: 在 main() 中调用**

在 `main()` 里 `_configure_high_dpi()` 之后新增一行（务必在 `app = QApplication(sys.argv)` 之前）：

```python
    _configure_high_dpi()
    _configure_gl_surface_format()
```

- [ ] **Step 5: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k surface_format -v`
Expected: PASS（2 项）

- [ ] **Step 6: 提交**

```bash
git add tests/ui/test_gpu_render_toggle.py mf4_analyzer/app.py
git commit -m "feat(app): request 4x MSAA default surface format for GL render path"
```

---

## Task 4: QSettings 持久化 helper

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`（模块级新增 key 与读写函数）
- Test: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: 写失败测试**

```python
def test_gpu_render_pref_roundtrip(tmp_path, qapp):
    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.main_window import (
        gpu_render_settings,
        read_gpu_render_pref,
        write_gpu_render_pref,
    )

    path = str(tmp_path / "s.ini")
    s = QSettings(path, QSettings.IniFormat)
    assert read_gpu_render_pref(s) is False  # 默认关
    write_gpu_render_pref(s, on=True)
    s.sync()
    s2 = QSettings(path, QSettings.IniFormat)
    assert read_gpu_render_pref(s2) is True

    default_settings = gpu_render_settings()
    assert default_settings.organizationName() == "MF4Analyzer"
    assert default_settings.applicationName() == "DataAnalyzer"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k pref_roundtrip -v`
Expected: FAIL（`ImportError: cannot import name 'read_gpu_render_pref'`）

- [ ] **Step 3: 实现 helper**

在 `main_window.py` 模块顶部（`class MainWindow` 定义之前）新增：

```python
GPU_RENDER_SETTINGS_ORG = "MF4Analyzer"
GPU_RENDER_SETTINGS_APP = "DataAnalyzer"
GPU_RENDER_SETTINGS_KEY = "render/use_opengl"


def gpu_render_settings():
    """Return the explicit app settings namespace used by analyzer UI prefs."""
    return QSettings(GPU_RENDER_SETTINGS_ORG, GPU_RENDER_SETTINGS_APP)


def read_gpu_render_pref(settings=None) -> bool:
    """从 QSettings 读 GPU 渲染开关（默认 False）。"""
    settings = settings or gpu_render_settings()
    return bool(settings.value(GPU_RENDER_SETTINGS_KEY, False, type=bool))


def write_gpu_render_pref(settings=None, *, on: bool) -> None:
    """写 GPU 渲染开关到 QSettings。"""
    settings = settings or gpu_render_settings()
    settings.setValue(GPU_RENDER_SETTINGS_KEY, bool(on))
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k pref_roundtrip -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tests/ui/test_gpu_render_toggle.py mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): add QSettings read/write helpers for GPU render pref"
```

---

## Task 5: Inspector 右下角 GPU 开关

**Files:**
- Modify: `mf4_analyzer/ui/inspector.py`（QtWidgets import 加 `QCheckBox`；类新增信号与控件；`body_lay.addStretch(1)` 前插入；新增 `set_gpu_toggle_checked`）
- Test: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: 写失败测试**

```python
def test_inspector_has_gpu_toggle_emitting_signal(qapp):
    from mf4_analyzer.ui.inspector import Inspector

    insp = Inspector()
    assert hasattr(insp, "gpu_toggle")
    received = []
    insp.gpu_render_toggled.connect(lambda on: received.append(on))
    insp.gpu_toggle.setChecked(True)
    assert received == [True]


def test_inspector_set_gpu_toggle_checked_is_silent(qapp):
    from mf4_analyzer.ui.inspector import Inspector

    insp = Inspector()
    received = []
    insp.gpu_render_toggled.connect(lambda on: received.append(on))
    insp.set_gpu_toggle_checked(True)
    assert insp.gpu_toggle.isChecked() is True
    assert received == []  # 静默设置，不发信号
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k inspector -v`
Expected: FAIL（`AttributeError: 'Inspector' object has no attribute 'gpu_toggle'`）

- [ ] **Step 3: import 加 QCheckBox**

`inspector.py:8` 的 `from PyQt5.QtWidgets import (` 块内加入 `QCheckBox,`（保持字母序，放在 `QWidget` 之前合适位置）。

- [ ] **Step 4: 新增信号**

在 `class Inspector` 信号区（约 `58` 行 `preset_acknowledged` 之后）新增：

```python
    # GPU 渲染开关（仅时域图）。MainWindow 接此信号写 QSettings + 切画布。
    gpu_render_toggled = pyqtSignal(bool)
```

- [ ] **Step 5: 在 body_lay 插入控件**

把 `__init__` 中：

```python
        body_lay.addWidget(self.contextual_stack)
        body_lay.addStretch(1)
```

改为：

```python
        body_lay.addWidget(self.contextual_stack)
        self.gpu_toggle = QCheckBox("GPU 加速（时域图）", self._scroll_body)
        self.gpu_toggle.setToolTip(
            "大图 / 多通道 / 高分屏卡顿时开启；导出仍正常，渲染与 CPU 一致"
        )
        self.gpu_toggle.toggled.connect(self.gpu_render_toggled)
        body_lay.addWidget(self.gpu_toggle)
        body_lay.addStretch(1)
```

- [ ] **Step 6: 新增静默设置方法**

在 `Inspector` 类内新增（用于启动同步，不回发信号）：

```python
    def set_gpu_toggle_checked(self, on: bool) -> None:
        """同步勾选态而不触发 gpu_render_toggled（启动期用）。"""
        self.gpu_toggle.blockSignals(True)
        self.gpu_toggle.setChecked(bool(on))
        self.gpu_toggle.blockSignals(False)
```

- [ ] **Step 7: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k inspector -v`
Expected: PASS（2 项）

- [ ] **Step 8: 提交**

```bash
git add tests/ui/test_gpu_render_toggle.py mf4_analyzer/ui/inspector.py
git commit -m "feat(inspector): add GPU render toggle checkbox in bottom panel"
```

---

## Task 6: MainWindow 串联（信号连接 + 启动同步）

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`（确保 `QSettings` 已 import；新增 `set_gpu_render`；连接 inspector 信号；启动读取并应用）
- Test: `tests/ui/test_gpu_render_toggle.py`

- [ ] **Step 1: 写失败测试**

```python
def test_main_window_gpu_toggle_wired(qapp):
    from mf4_analyzer.ui.main_window import (
        GPU_RENDER_SETTINGS_KEY,
        MainWindow,
        gpu_render_settings,
        read_gpu_render_pref,
    )

    settings = gpu_render_settings()
    settings.remove(GPU_RENDER_SETTINGS_KEY)
    w = MainWindow()
    try:
        assert hasattr(w.inspector, "gpu_toggle")
        w.inspector.gpu_toggle.setChecked(True)
        qapp.processEvents()
        assert w.canvas_time._gpu_render_on is True
        assert read_gpu_render_pref(settings) is True
        w.inspector.gpu_toggle.setChecked(False)
        qapp.processEvents()
        assert w.canvas_time._gpu_render_on is False
        assert read_gpu_render_pref(settings) is False
    finally:
        settings.remove(GPU_RENDER_SETTINGS_KEY)
        w.close()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -k main_window_gpu -v`
Expected: FAIL（toggle 未连到画布，`_gpu_render_on` 仍 False）

- [ ] **Step 3: 确保 QSettings 已 import**

确认 `main_window.py` 顶部 `from PyQt5.QtCore import ...` 含 `QSettings`；若无则加入。

- [ ] **Step 4: 新增 MainWindow.set_gpu_render**

在 `MainWindow` 类内新增：

```python
    def set_gpu_render(self, on: bool) -> None:
        """切换时域图 GPU 渲染：写持久化 + 应用到画布。"""
        on = bool(on)
        write_gpu_render_pref(on=on)
        self.canvas_time.set_gpu_render(on)
```

- [ ] **Step 5: 连接信号**

在信号连接区（如 `main_window.py:336` `self.inspector.plot_time_requested.connect(...)` 附近）新增：

```python
        self.inspector.gpu_render_toggled.connect(self.set_gpu_render)
```

- [ ] **Step 6: 启动期读取并应用**

在 `__init__` 中 `self.canvas_time`（约 `203` 行）与 `self.inspector`（约 `143` 行）都已就绪、且信号已连接之后（建议放在 `__init__` 末尾绘图之前），新增：

```python
        _gpu_on = read_gpu_render_pref()
        self.inspector.set_gpu_toggle_checked(_gpu_on)
        self.canvas_time.set_gpu_render(_gpu_on)
```

- [ ] **Step 7: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/ui/test_gpu_render_toggle.py -v`
Expected: PASS（全部）

- [ ] **Step 8: 跑全量 UI 测试防回归**

Run: `.venv/bin/python -m pytest tests/ui -q`
Expected: 全绿（无新增失败）

- [ ] **Step 9: 提交**

```bash
git add tests/ui/test_gpu_render_toggle.py mf4_analyzer/ui/main_window.py
git commit -m "feat(ui): wire GPU render toggle through MainWindow with persistence"
```

---

## Task 7: 真机视觉验收（手动，必做）

> 这一步无法在 offscreen 自动化（无头抓不到 GL 渲染），必须在真实运行的 app 里做，遵循「UI 必须验真实渲染」。

- [ ] **Step 1: 真机启动 app**

Run: `.venv/bin/python -m mf4_analyzer.app`
（在 5K Studio Display 全屏。）

- [ ] **Step 2: 开关对比**

加载 `testdoc/tiaofri.MF4`，勾 5 / 10 / 20 通道。开/关右下角「GPU 加速」各观察：
- 关→开后 pan/缩放主观顺滑度明显改善（对照 spec §2.4 的 37/99/346ms）。
- 线宽强调（选中加粗、其余变细）在 GPU 下**仍有粗细差**。
- 虚线光标在 GPU 下**仍是虚线**。
- 开→关→开后双击图表选项、游标点击/移动、overlay 选择/Y 拖拽仍响应（证明新 viewport 的 event filter 已重绑）。

- [ ] **Step 3: 导出验证**

GPU 开启状态下点「导出」/复制图，确认导出图**非空白、内容正确**。
导出完成后继续 pan/zoom/游标点击一次，确认 CPU 回切再恢复 GPU 后交互没有丢。

- [ ] **Step 4: 持久化验证**

开 GPU → 关 app → 重开，确认开关仍为开、且时域图直接走 GPU。

- [ ] **Step 5: 记录结论**

若线宽/虚线在某平台仍有偏差，回填 spec §6 并决定是否需要补救；否则标记验收通过。

---

## Self-Review（计划 vs spec）

- **Spec 覆盖：** §5.1 渲染开关 + requested/applied 状态 + viewport event-filter 重绑→Task 1；§5.2 MSAA + QApplication 前顺序→Task 3；§5.3 UI+显式 namespace 持久化→Task 4/5/6；§5.4 导出 CPU 回切 + 恢复 event filter + 非空白内容→Task 2；§5.5 默认关→Task 6 启动读取 default False；§6 风险（异常安全/回退/错误 namespace/viewport 替换）→Task 1/4/7；§7.1 单测→Task 1-6；§7.2 真机→Task 7。无遗漏。
- **占位符扫描：** 无 TBD/TODO；每个代码步骤含完整代码。
- **类型/命名一致：** `_gpu_render_requested` / `_gpu_render_on` / `_gpu_viewport_filter_target`（Task 1/2/6）、`set_gpu_render` + `_apply_gpu_viewport` + `_install_viewport_event_filter`（Task 1）、`gpu_render_toggled` 信号 + `gpu_toggle` 控件 + `set_gpu_toggle_checked`（Task 5/6）、`gpu_render_settings` + `read_/write_gpu_render_pref` + `GPU_RENDER_SETTINGS_KEY`（Task 4/6）全程一致。
