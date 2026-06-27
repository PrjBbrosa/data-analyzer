# 文件窗口拖动导入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户把文件从 Finder/资源管理器拖入主窗口任意位置即可导入，行为与「打开」菜单完全一致。

**Architecture:** 在 `MainWindow` 上 `setAcceptDrops(True)` 并由新 `DropImportMixin` 重写
drag/drop 事件；拖入路径过滤后走从 `open_files_or_project` 抽取出的共享分发函数
`_open_paths(paths)`，零行为分叉。拖拽期间整窗叠一层自绘半透明高亮遮罩 `_DropOverlay`。

**Tech Stack:** PyQt5（QMainWindow / QDragEnterEvent / QDropEvent / QMimeData / QPainter）、pytest-qt。

## Global Constraints

- `_load_one(fp, *, blf_dbc_paths=None)` 本体**一行不动**（`_project_io_mixin.py:182`）。
- 受支持扩展名**单一来源**：从 `_project_io_mixin.DATA_FILE_GLOB` 派生，并 ∪ `{.tlproj}`。
- 遮罩遵守项目两条铁律：① 背景必须 `paintEvent` 自绘，不靠 QSS（`WA_TranslucentBackground`
  会让本体 QSS 失效）；② macOS UI 必须真机渲染验真（截图），不靠"属性设上+单测过"。
- 遮罩 `WA_TransparentForMouseEvents=True`，绝不拦截拖放事件。
- 拖入加载保持**同步**（与菜单一致，不引线程）。
- 测试用 pytest-qt，fixture `qapp`/`qtbot`，`from mf4_analyzer.ui.main_window import MainWindow`。

---

### Task 1: 抽取共享分发函数 `_open_paths(paths)`（纯重构，行为不变）

把 `open_files_or_project()` 中"拿到 `fps` 之后"的分发体原样搬进
`ProjectIOMixin._open_paths(paths)`，让对话框与（后续的）拖放走同一条路。

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_project_io_mixin.py:44-78`
- Test: `tests/ui/test_drop_import.py`（新建）

**Interfaces:**
- Produces: `ProjectIOMixin._open_paths(self, paths) -> None` — 接受 `list[str]`，对其做
  projects/data 拆分 + 单项目替换确认 + 分发到 `_load_one`/`open_project`，逻辑与旧
  `open_files_or_project` 完全一致。
- Produces（保留）: `open_files_or_project(self) -> None` — 仅负责弹对话框取 `fps`，再委托 `_open_paths(fps)`。

- [ ] **Step 1: 写失败测试**

新建 `tests/ui/test_drop_import.py`：

```python
import mf4_analyzer.ui.main_window as mw
from mf4_analyzer.ui.main_window import MainWindow


def test_open_files_or_project_delegates_to_open_paths(qapp, qtbot, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileNames",
        lambda *a, **k: (["/x/a.csv", "/x/b.mf4"], ""),
    )
    w.open_files_or_project()
    assert captured == [["/x/a.csv", "/x/b.mf4"]]


def test_open_files_or_project_no_selection_skips_dispatch(qapp, qtbot, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    monkeypatch.setattr(mw.QFileDialog, "getOpenFileNames", lambda *a, **k: ([], ""))
    w.open_files_or_project()
    assert captured == []


def test_open_paths_dispatches_data_files_to_load_one(qapp, qtbot, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    loaded = []
    monkeypatch.setattr(w, "_load_one", lambda fp, **k: loaded.append(fp))
    w._open_paths(["/x/a.csv", "/x/b.mf4"])
    assert loaded == ["/x/a.csv", "/x/b.mf4"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_drop_import.py -q`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute '_open_paths'`（前两个用例
因 monkeypatch `_open_paths` 也会 AttributeError；第三个同样无 `_open_paths`）。

- [ ] **Step 3: 重构实现**

在 `mf4_analyzer/ui/main_window/_project_io_mixin.py`，把现有 `open_files_or_project`
（`:44-78`）替换为下面两个方法（分发体逐行搬入 `_open_paths`，不改逻辑）：

```python
    def open_files_or_project(self):
        """统一打开入口：文件对话框同时接受数据文件和 .tlproj。"""
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        fps, _ = _QFileDialog.getOpenFileNames(
            self, "打开", "", PROJECT_OR_DATA_FILTER,
        )
        if not fps:
            return
        self._open_paths(fps)

    def _open_paths(self, paths):
        """共享分发：数据文件追加；单个 .tlproj 替换（先确认）；项目+文件先开项目再
        追加；≥2 个项目拒绝。由「打开」菜单和拖放共用，行为零分叉。"""
        from pathlib import Path
        projects = [p for p in paths if Path(p).suffix.lower() == ".tlproj"]
        data_files = [p for p in paths if Path(p).suffix.lower() != ".tlproj"]

        if len(projects) >= 2:
            QMessageBox.warning(self, "无法打开", "一次只能打开一个项目（.tlproj）。")
            return

        if projects:
            if self.files:
                resp = QMessageBox.question(
                    self, "打开项目",
                    f"打开项目将关闭当前 {len(self.files)} 个文件，是否继续？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    return
            self.open_project(projects[0])
            for fp in data_files:
                self._load_one(fp)
            return

        for fp in data_files:
            self._load_one(fp)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_drop_import.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: 跑既有 IO/smoke 回归确认无行为变化**

Run: `pytest tests/ui/test_main_window_smoke.py -q && pytest -k "project or open or load" -q`
Expected: 全绿（重构等价，行为不变）。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/main_window/_project_io_mixin.py tests/ui/test_drop_import.py
git commit -m "refactor(io): extract _open_paths shared dispatch from open_files_or_project"
```

---

### Task 2: `DropImportMixin` 拖放导入（功能层，无遮罩）

新建 mixin 实现 drag/drop 事件 + 路径过滤 + 调用 `_open_paths`，并接入 `MainWindow`。
本任务只做**功能**（拖入即导入），视觉遮罩留给 Task 3。

**Files:**
- Create: `mf4_analyzer/ui/main_window/_drop_import_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py:44`（加 import）、`:63`（加基类）、`:121-122`（加 `_init_drop_import()` 调用）
- Test: `tests/ui/test_drop_import.py`

**Interfaces:**
- Consumes: `ProjectIOMixin._open_paths(paths)`（Task 1）；`self.toast(msg, level='info')`（`window.py:463`）。
- Produces: 模块级 `SUPPORTED_DROP_EXTS: set[str]`；`DropImportMixin` 含
  `_init_drop_import()`、`_has_supported_urls(mime) -> bool`、`_dropped_paths(mime) -> list[str]`、
  `dragEnterEvent(e)`、`dragMoveEvent(e)`、`dropEvent(e)`。`MainWindow` 继承之，`__init__` 调用 `_init_drop_import()`。

- [ ] **Step 1: 写失败测试**

追加到 `tests/ui/test_drop_import.py`：

```python
from pathlib import Path

from PyQt5.QtCore import QMimeData, QUrl, QPoint, Qt
from PyQt5.QtGui import QDragEnterEvent, QDropEvent


def _mime(paths):
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def _enter(mime):
    return QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)


def _drop(mime):
    return QDropEvent(QPoint(10, 10), Qt.CopyAction, mime,
                      Qt.LeftButton, Qt.NoModifier)


def test_accept_drops_enabled(qapp, qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    assert w.acceptDrops() is True


def test_drag_enter_accepts_supported(qapp, qtbot, tmp_path):
    w = MainWindow(); qtbot.addWidget(w)
    f = tmp_path / "a.csv"; f.write_text("x")
    ev = _enter(_mime([f]))
    w.dragEnterEvent(ev)
    assert ev.isAccepted()


def test_drag_enter_ignores_unsupported(qapp, qtbot, tmp_path):
    w = MainWindow(); qtbot.addWidget(w)
    f = tmp_path / "a.txt"; f.write_text("x")
    ev = _enter(_mime([f]))
    w.dragEnterEvent(ev)
    assert not ev.isAccepted()


def test_drop_supported_calls_open_paths(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    csv = tmp_path / "a.csv"; csv.write_text("x")
    mf4 = tmp_path / "b.mf4"; mf4.write_text("x")
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    w.dropEvent(_drop(_mime([csv, mf4])))
    assert captured == [[str(csv), str(mf4)]]


def test_drop_filters_unsupported_and_toasts(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    csv = tmp_path / "a.csv"; csv.write_text("x")
    txt = tmp_path / "a.txt"; txt.write_text("x")
    captured, toasts = [], []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    monkeypatch.setattr(w, "toast", lambda msg, level='info': toasts.append((msg, level)))
    w.dropEvent(_drop(_mime([csv, txt])))
    assert captured == [[str(csv)]]
    assert len(toasts) == 1 and "1" in toasts[0][0]


def test_drop_directory_is_filtered(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    d = tmp_path / "sub"; d.mkdir()
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    w.dropEvent(_drop(_mime([d])))
    assert captured == []


def test_drop_tlproj_passes_through(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    proj = tmp_path / "p.tlproj"; proj.write_text("{}")
    captured = []
    monkeypatch.setattr(w, "_open_paths", lambda paths: captured.append(list(paths)))
    w.dropEvent(_drop(_mime([proj])))
    assert captured == [[str(proj)]]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_drop_import.py -q`
Expected: 新增用例 FAIL（`acceptDrops()` 为 False / `dragEnterEvent` 走基类不接受 / `dropEvent` 不调用 `_open_paths`）。

- [ ] **Step 3: 创建 `_drop_import_mixin.py`**

```python
"""DropImportMixin: file drag & drop import for MainWindow.

拖入主窗口任意位置即导入，走与「打开」菜单相同的 ProjectIOMixin._open_paths
分发逻辑（行为零分叉）。视觉遮罩 _DropOverlay 在 Task 3 加入。
"""

from pathlib import Path

from PyQt5.QtCore import Qt

from ._project_io_mixin import DATA_FILE_GLOB

# 受支持扩展名单一来源：数据文件 glob 派生 ∪ 项目扩展名。
SUPPORTED_DROP_EXTS = {
    tok.lower().lstrip("*") for tok in DATA_FILE_GLOB.split()
} | {".tlproj"}


class DropImportMixin:
    """Domain mixin: 文件拖放导入。重写 QMainWindow 的 drag/drop 事件。"""

    def _init_drop_import(self):
        self.setAcceptDrops(True)
        self._drop_overlay = None  # Task 3 惰性创建

    # ---- mime 解析 ----
    def _has_supported_urls(self, mime):
        if not mime.hasUrls():
            return False
        for url in mime.urls():
            p = url.toLocalFile()
            if p and Path(p).suffix.lower() in SUPPORTED_DROP_EXTS:
                return True
        return False

    def _dropped_paths(self, mime):
        out = []
        if not mime.hasUrls():
            return out
        for url in mime.urls():
            p = url.toLocalFile()
            if not p:
                continue
            pp = Path(p)
            if pp.is_file() and pp.suffix.lower() in SUPPORTED_DROP_EXTS:
                out.append(p)
        return out

    # ---- drag/drop 事件 ----
    def dragEnterEvent(self, event):
        if self._has_supported_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._has_supported_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        mime = event.mimeData()
        paths = self._dropped_paths(mime)
        total = sum(1 for u in mime.urls() if u.toLocalFile()) if mime.hasUrls() else 0
        if paths:
            event.acceptProposedAction()
            self._open_paths(paths)
        else:
            event.ignore()
        skipped = total - len(paths)
        if skipped > 0:
            self.toast(f"忽略 {skipped} 个不支持的文件", "warning")
```

- [ ] **Step 4: 接入 `MainWindow`**

在 `mf4_analyzer/ui/main_window/window.py`：

1. 第 44 行后加 import：

```python
from ._drop_import_mixin import DropImportMixin
```

2. 类基类列表（`:63`）加入 `DropImportMixin`（置于最前，确保其事件重写在 MRO 优先）：

```python
class MainWindow(
    DropImportMixin,
    AnalysisMixin, FFTMixin, OrderMixin, FFTTimeMixin, ProjectIOMixin,
    ViewMixin, QMainWindow,
):
```

3. `__init__` 中 `self._init_ui()`（`:121`）之后、`self._connect()`（`:122`）之前加一行：

```python
        self._init_ui();
        self._init_drop_import()
        self._connect()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/ui/test_drop_import.py -q`
Expected: PASS（含 Task 1 共 ~10 passed）。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/main_window/_drop_import_mixin.py mf4_analyzer/ui/main_window/window.py tests/ui/test_drop_import.py
git commit -m "feat(ui): drag & drop file import on the main window"
```

---

### Task 3: `_DropOverlay` 整窗高亮遮罩 + 真机验真

拖拽期间整窗叠一层自绘半透明高亮遮罩，并真机验证 macOS 渲染。

**Files:**
- Modify: `mf4_analyzer/ui/main_window/_drop_import_mixin.py`
- Test: `tests/ui/test_drop_import.py`

**Interfaces:**
- Consumes: Task 2 的 `dragEnterEvent`/`dropEvent`、`self._drop_overlay`、`self.centralWidget()`。
- Produces: `_DropOverlay(QWidget)`；`DropImportMixin._show_drop_overlay()`、`_hide_drop_overlay()`；
  并给 `dragEnterEvent` 加显示、`dropEvent` 加隐藏、新增 `dragLeaveEvent` 隐藏。

- [ ] **Step 1: 写失败测试**

追加到 `tests/ui/test_drop_import.py`：

```python
from PyQt5.QtGui import QDragLeaveEvent


def test_overlay_shows_on_enter_hides_on_leave(qapp, qtbot, tmp_path):
    w = MainWindow(); qtbot.addWidget(w)
    f = tmp_path / "a.csv"; f.write_text("x")
    w.dragEnterEvent(_enter(_mime([f])))
    assert w._drop_overlay is not None
    assert not w._drop_overlay.isHidden()
    w.dragLeaveEvent(QDragLeaveEvent())
    assert w._drop_overlay.isHidden()


def test_overlay_hidden_after_drop(qapp, qtbot, tmp_path, monkeypatch):
    w = MainWindow(); qtbot.addWidget(w)
    f = tmp_path / "a.csv"; f.write_text("x")
    monkeypatch.setattr(w, "_open_paths", lambda paths: None)
    w.dragEnterEvent(_enter(_mime([f])))
    w.dropEvent(_drop(_mime([f])))
    assert w._drop_overlay.isHidden()


def test_overlay_transparent_to_mouse(qapp, qtbot, tmp_path):
    w = MainWindow(); qtbot.addWidget(w)
    f = tmp_path / "a.csv"; f.write_text("x")
    w.dragEnterEvent(_enter(_mime([f])))
    assert w._drop_overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_drop_import.py -k overlay -q`
Expected: FAIL（`_drop_overlay` 仍为 None；无 `dragLeaveEvent`）。

- [ ] **Step 3: 加 `_DropOverlay` 与 show/hide**

在 `_drop_import_mixin.py` 顶部 import 补充：

```python
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QWidget
```

文件末尾新增 `_DropOverlay`：

```python
class _DropOverlay(QWidget):
    """整窗拖入高亮遮罩。自绘背景（铁律②：WA_TranslucentBackground 让 QSS 背景失效）；
    WA_TransparentForMouseEvents 确保不拦截拖放事件。"""

    _ACCENT = QColor(37, 99, 235)  # 真机可调

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        fill = QColor(self._ACCENT); fill.setAlpha(30)
        p.fillRect(rect, fill)
        pen = QPen(self._ACCENT, 2, Qt.DashLine); pen.setColor(self._ACCENT)
        p.setPen(pen)
        inset = rect.adjusted(10, 10, -10, -10)
        p.drawRoundedRect(inset, 12, 12)
        f = QFont(self.font()); f.setPointSize(18); f.setBold(True)
        p.setFont(f)
        p.setPen(self._ACCENT)
        p.drawText(rect, Qt.AlignCenter, "松手导入文件")
        p.end()
```

在 `DropImportMixin` 内加两个方法：

```python
    def _show_drop_overlay(self):
        cw = self.centralWidget()
        if cw is None:
            return
        if self._drop_overlay is None:
            self._drop_overlay = _DropOverlay(cw)
        self._drop_overlay.setGeometry(cw.rect())
        self._drop_overlay.raise_()
        self._drop_overlay.show()

    def _hide_drop_overlay(self):
        if self._drop_overlay is not None:
            self._drop_overlay.hide()
```

把 `dragEnterEvent`/`dropEvent` 改为带遮罩，并新增 `dragLeaveEvent`：

```python
    def dragEnterEvent(self, event):
        if self._has_supported_urls(event.mimeData()):
            event.acceptProposedAction()
            self._show_drop_overlay()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._hide_drop_overlay()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._hide_drop_overlay()
        mime = event.mimeData()
        paths = self._dropped_paths(mime)
        total = sum(1 for u in mime.urls() if u.toLocalFile()) if mime.hasUrls() else 0
        if paths:
            event.acceptProposedAction()
            self._open_paths(paths)
        else:
            event.ignore()
        skipped = total - len(paths)
        if skipped > 0:
            self.toast(f"忽略 {skipped} 个不支持的文件", "warning")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_drop_import.py -q`
Expected: 全绿（Task 1+2+3 全部 passed）。

- [ ] **Step 5: 真机渲染验真（macOS，强制 — 铁律①）**

启动 GUI，从 Finder 拖一个文件到窗口上方但先不松手，截图确认：

```bash
python "MF4 Data Analyzer V1.py"
```

逐项核对（用截图，不靠"属性设上了"）：
- 拖入悬停时整窗出现半透明高亮 + 虚线圆角边 + 居中「松手导入文件」，文字清晰不糊；
- 半透明能透出底下三栏内容（不是纯色盖死）；
- 松手后遮罩消失且文件被导入（左侧文件列表出现新行）；
- 拖一个 `.txt` 等不支持文件，悬停不亮起高亮、松手不导入、出 toast 提示；
- 颜色/alpha 若刺眼，调 `_DropOverlay._ACCENT` 或 fill alpha 后重新截图复核。

把关键截图留存或贴给 user 确认。

- [ ] **Step 6: 全量回归 + 提交**

> ⚠️ 项目在 ~/Downloads，子 agent 跑全量 pytest 可能触发 TCC EPERM（见 memory
> `env-tcc-downloads-blocks-access`）。若由子 agent 执行，**只跑相关用例**，全量回归交由主
> 会话或在已授 Full Disk Access 的终端执行。

Run（主会话）: `pytest -q`
Expected: 全绿，零回归。

```bash
git add mf4_analyzer/ui/main_window/_drop_import_mixin.py tests/ui/test_drop_import.py
git commit -m "feat(ui): drop-import highlight overlay with on-screen render verification"
```

---

## Self-Review

**Spec coverage（逐节核对 spec → task）：**
- §1 接收区=整窗 → Task 2（`setAcceptDrops` + 窗口级事件）✅
- §1 视觉反馈=高亮遮罩 → Task 3 ✅
- §1 复用现有分发 → Task 1（`_open_paths`）+ Task 2（`dropEvent` 调用之）✅
- §3.1 `DropImportMixin` + window.py 两处接入 → Task 2 Step 3-4 ✅
- §3.2 抽 `_open_paths` → Task 1 ✅
- §3.3 `_DropOverlay` 三条属性 + paintEvent 自绘 → Task 3 Step 3 ✅
- §4 子控件吞 drop → 已核实通道树/widgets 0 处 acceptDrops，风险排除；窗口级兜底覆盖 ✅
- §4 macOS 真机渲染 → Task 3 Step 5 强制截图 ✅
- §5 测试 1-6 → Task 1/2/3 各步覆盖（含 .tlproj、过滤、遮罩显隐、回归）✅
- §6 可发现性 → 标注为可选 follow-up，不入本 plan（与 spec 一致）

**Placeholder scan：** 无 TBD/TODO；每个 code step 给出完整代码与精确路径/命令。`_ACCENT`
颜色注明"真机可调"是显式调参点，非占位。

**Type consistency：** `_open_paths(paths)`、`_has_supported_urls(mime)`、`_dropped_paths(mime)`、
`_show_drop_overlay()`/`_hide_drop_overlay()`、`_drop_overlay`、`SUPPORTED_DROP_EXTS`、
`toast(msg, level)` 在各 task 间命名/签名一致。`_drop_overlay` 在 Task 2 Step 3 初始化为 None、
Task 3 惰性赋值，前后一致。
