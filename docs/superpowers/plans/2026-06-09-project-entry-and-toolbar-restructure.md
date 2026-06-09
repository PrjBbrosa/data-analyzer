# Project Entry + Toolbar Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `.tlproj` save/load into the UI — split the blue toolbar button into 打开 (unified file/project open) + 保存项目, and relocate 导出 from the toolbar into a new section of the channel-editor dialog.

**Architecture:** Three new `MainWindow` handlers (`open_files_or_project`, `save_project_via_dialog`, `_do_export_excel`) carry behavior and are unit-tested by direct call; the toolbar widget and channel-editor dialog are then re-wired to them. The channel-editor collects export choices and emits a signal — MainWindow does the actual Excel write (keeps pandas/inspector context in MainWindow).

**Tech Stack:** Python 3, PyQt5, pytest + pytest-qt (`tests/ui/conftest.py` → `qapp` fixture, offscreen platform). Repo venv: `.venv/bin/python`.

---

## File Structure

**Modified:**
- `mf4_analyzer/ui/main_window.py` — `open_files_or_project`, `save_project_via_dialog`, `_project_path` tracking, `_do_export_excel`; rewire toolbar signals + channel-editor export signal; drop old `export_excel`.
- `mf4_analyzer/ui/toolbar.py` — relabel 添加文件→打开, rename signal, add 保存项目 button+signal, remove 导出 button+signal, update `set_enabled_for_mode`.
- `mf4_analyzer/ui/dialogs.py` — new 导出 `QGroupBox` section + `export_requested` signal + populate export list.
- `mf4_analyzer/ui/drawers/channel_editor_drawer.py` — re-emit `export_requested`.
- `tests/ui/test_toolbar.py` — update stale `btn_export` assertions.

**New test files:**
- `tests/ui/test_open_and_save_entry.py` — unified open partition + save path tracking.
- `tests/ui/test_channel_editor_export.py` — export section + signal + `_do_export_excel`.

---

## Task C1: MainWindow.open_files_or_project (unified open handler)

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (add method near `load_files`, ~line 1291)
- Test: `tests/ui/test_open_and_save_entry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_open_and_save_entry.py
import csv
from PyQt5.QtWidgets import QFileDialog, QMessageBox


def _csv(path, n=30):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "rpm"])
        for i in range(n):
            w.writerow([i / 100.0, float(i)])


def test_open_data_files_appends(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    b = tmp_path / "b.csv"; _csv(b)
    mw = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(a), str(b)], ""))
    mw.open_files_or_project()
    assert [fd.filename for fd in mw.files.values()] == ["a.csv", "b.csv"]


def test_open_single_project_replaces(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)

    mw2 = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(proj)], ""))
    mw2.open_files_or_project()
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv"]


def test_open_replace_confirm_cancel_aborts(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    b = tmp_path / "b.csv"; _csv(b)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)

    # session already has b.csv loaded; opening a project must confirm first
    mw._load_one(str(b))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(proj)], ""))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a_, **k: QMessageBox.No)
    before = [fd.filename for fd in mw.files.values()]
    mw.open_files_or_project()
    assert [fd.filename for fd in mw.files.values()] == before  # unchanged


def test_open_project_plus_files_adds_on_top(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    extra = tmp_path / "extra.csv"; _csv(extra)
    proj = tmp_path / "s.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)

    mw2 = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(proj), str(extra)], ""))
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a_, **k: QMessageBox.Yes)
    mw2.open_files_or_project()
    assert sorted(fd.filename for fd in mw2.files.values()) == ["a.csv", "extra.csv"]


def test_open_multiple_projects_rejected(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    p1 = tmp_path / "x.tlproj"; p1.write_text("{}", encoding="utf-8")
    p2 = tmp_path / "y.tlproj"; p2.write_text("{}", encoding="utf-8")
    mw = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a_, **k: ([str(p1), str(p2)], ""))
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a_, **k: warned.setdefault("hit", True))
    mw.open_files_or_project()
    assert warned.get("hit") is True
    assert len(mw.files) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_open_and_save_entry.py -q`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'open_files_or_project'`.

- [ ] **Step 3: Add `open_files_or_project` to `MainWindow`**

```python
    def open_files_or_project(self):
        """Unified 打开 entry: one file dialog that accepts data files and/or a
        single .tlproj. Data files append; a project replaces the session
        (confirmed when non-empty); a project + files opens the project then
        appends the extras; >= 2 projects is rejected."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        fps, _ = QFileDialog.getOpenFileNames(
            self, "打开", "",
            "所有支持的文件 (*.mf4 *.csv *.xlsx *.xls *.tlproj);;"
            "项目 (*.tlproj);;数据文件 (*.mf4 *.csv *.xlsx *.xls)",
        )
        if not fps:
            return
        projects = [p for p in fps if Path(p).suffix.lower() == ".tlproj"]
        data_files = [p for p in fps if Path(p).suffix.lower() != ".tlproj"]

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

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_open_and_save_entry.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_open_and_save_entry.py
git commit -m "feat(open): unified open_files_or_project (data appends, project replaces, mix)"
```

---

## Task C2: Save-project handler + project-path tracking

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (`__init__` init flag; `save_project`/`open_project` set path; new `save_project_via_dialog`)
- Test: `tests/ui/test_open_and_save_entry.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_save_via_dialog_first_time_prompts(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QFileDialog
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "new.tlproj"
    mw = MainWindow(); mw._load_one(str(a))
    assert mw._project_path is None
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(proj), ""))
    mw.save_project_via_dialog()
    assert proj.exists()
    assert str(mw._project_path) == str(proj)


def test_save_via_dialog_overwrites_known_path(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QFileDialog
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "p.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)   # sets _project_path
    called = {"n": 0}
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: called.__setitem__("n", called["n"] + 1) or ("", ""))
    mw.save_project_via_dialog()
    assert called["n"] == 0          # no Save-As prompt; overwrote known path
    assert proj.exists()


def test_open_project_sets_project_path(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    proj = tmp_path / "p.tlproj"
    mw = MainWindow(); mw._load_one(str(a)); mw.save_project(proj)
    mw2 = MainWindow(); mw2.open_project(proj)
    assert str(mw2._project_path) == str(proj)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_open_and_save_entry.py -k save_via_dialog -q`
Expected: FAIL with `AttributeError: ... '_project_path'` / `'save_project_via_dialog'`.

- [ ] **Step 3: Init the flag**

In `MainWindow.__init__`, next to `self._active = None` (line ~93), add:

```python
        self._project_path = None
```

- [ ] **Step 4: Set the path in save/open**

At the end of `save_project` (after `pio.save_project_to_json(doc, path)`), add:

```python
        self._project_path = path
```

At the end of `open_project`'s success path (just before the final `self.statusBar.showMessage(f"已打开项目: {path.name}")`), add:

```python
        self._project_path = path
```

- [ ] **Step 5: Add `save_project_via_dialog`**

```python
    def save_project_via_dialog(self):
        """保存项目 handler: overwrite the current .tlproj if one is open,
        otherwise prompt Save-As."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog
        if self._project_path is not None:
            self.save_project(self._project_path)
            return
        fp, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "TraceLab 项目 (*.tlproj)")
        if not fp:
            return
        if not fp.lower().endswith(".tlproj"):
            fp = fp + ".tlproj"
        self.save_project(Path(fp))
```

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_open_and_save_entry.py -q`
Expected: PASS (all open + save tests).

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_open_and_save_entry.py
git commit -m "feat(save): save_project_via_dialog + _project_path tracking"
```

---

## Task C3: Toolbar — split into 打开/保存项目, remove 导出

**Files:**
- Modify: `mf4_analyzer/ui/toolbar.py`
- Modify: `mf4_analyzer/ui/main_window.py:337-338` (rewire signals)
- Modify: `tests/ui/test_toolbar.py` (stale btn_export asserts)
- Test: `tests/ui/test_toolbar.py` (+ new asserts)

- [ ] **Step 1: Write/adjust the failing test**

Replace the three `btn_export` references in `tests/ui/test_toolbar.py`. First read the file to see their context:

Run: `grep -n "btn_export" tests/ui/test_toolbar.py`

Then update each:
- Lines 24 & 28 (`assert tb.btn_export.isEnabled()` / `assert not tb.btn_export.isEnabled()`): retarget to `tb.btn_save_project` (it is the has_file-gated button now).
- Line 44 (`tb.btn_batch.icon().cacheKey() != tb.btn_export.icon().cacheKey()`): retarget to `tb.btn_add.icon().cacheKey()`.

Add a new assertion block at the end of `test_toolbar.py`:

```python
def test_toolbar_open_save_split_and_no_export(qtbot):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar(); qtbot.addWidget(tb)
    assert tb.btn_add.text() == "打开"
    assert hasattr(tb, "btn_save_project")
    assert tb.btn_save_project.text() == "保存项目"
    assert not hasattr(tb, "btn_export")
    assert hasattr(tb, "open_requested")
    assert hasattr(tb, "save_project_requested")
    assert not hasattr(tb, "export_requested")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar.py -q`
Expected: FAIL (btn_export gone / btn_save_project absent).

- [ ] **Step 3: Edit `toolbar.py` — signals**

Replace the signal block (lines 12-19):

```python
    # Left segment
    file_add_requested = pyqtSignal()
    export_requested = pyqtSignal()
    batch_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'fft_time' | 'order'
    # Right segment
    acquisition_cockpit_requested = pyqtSignal()
```

with:

```python
    # Left segment
    open_requested = pyqtSignal()
    save_project_requested = pyqtSignal()
    batch_requested = pyqtSignal()
    # Center segment
    mode_changed = pyqtSignal(str)  # 'time' | 'fft' | 'fft_time' | 'order'
    # Right segment
    acquisition_cockpit_requested = pyqtSignal()
```

- [ ] **Step 4: Edit `toolbar.py` — buttons**

Replace the button-creation block (lines 28-37):

```python
        self.btn_add = QPushButton("添加文件", self)
        self.btn_add.setIcon(Icons.add_file(QColor("#ffffff")))
        self.btn_add.setProperty("role", "primary")
        self.btn_export = QPushButton("导出", self)
        self.btn_export.setIcon(Icons.export())
        self.btn_batch = QPushButton("批处理", self)
        self.btn_batch.setIcon(Icons.batch())
        self.btn_acquisition_cockpit = QPushButton("Cockpit", self)
        self.btn_acquisition_cockpit.setIcon(Icons.plot())
        self.btn_acquisition_cockpit.setToolTip("打开 Acquisition Cockpit")
```

with:

```python
        self.btn_add = QPushButton("打开", self)
        self.btn_add.setIcon(Icons.add_file(QColor("#ffffff")))
        self.btn_add.setProperty("role", "primary")
        self.btn_add.setToolTip("打开数据文件或项目（.tlproj）")
        self.btn_save_project = QPushButton("保存项目", self)
        self.btn_save_project.setIcon(Icons.export())
        self.btn_save_project.setToolTip("保存当前会话为 .tlproj 项目")
        self.btn_batch = QPushButton("批处理", self)
        self.btn_batch.setIcon(Icons.batch())
        self.btn_acquisition_cockpit = QPushButton("Cockpit", self)
        self.btn_acquisition_cockpit.setIcon(Icons.plot())
        self.btn_acquisition_cockpit.setToolTip("打开 Acquisition Cockpit")
```

(Icon for 保存项目 reuses `Icons.export()` as a placeholder; a dedicated save glyph is a follow-up.)

- [ ] **Step 5: Edit `toolbar.py` — icon-size loop + left cluster**

In the `setIconSize` loop (lines 49-53), replace `self.btn_export` with `self.btn_save_project`:

```python
        for b in (self.btn_add, self.btn_save_project, self.btn_batch,
                  self.btn_acquisition_cockpit,
                  self.btn_mode_time, self.btn_mode_fft, self.btn_mode_fft_time,
                  self.btn_mode_order):
            b.setIconSize(QSize(16, 16))
```

In the left-cluster loop (lines 58-64), replace `self.btn_export` with `self.btn_save_project`:

```python
        for b in (
            self.btn_add,
            self.btn_save_project,
            self.btn_batch,
            self.btn_acquisition_cockpit,
        ):
            left.addWidget(b)
```

- [ ] **Step 6: Edit `toolbar.py` — wiring + enabled-state**

In `_wire` (lines 129-132), replace the add/export connects:

```python
        self.btn_add.clicked.connect(self.file_add_requested)
        self.btn_export.clicked.connect(self.export_requested)
        self.btn_batch.clicked.connect(self.batch_requested)
        self.btn_acquisition_cockpit.clicked.connect(self.acquisition_cockpit_requested)
```

with:

```python
        self.btn_add.clicked.connect(self.open_requested)
        self.btn_save_project.clicked.connect(self.save_project_requested)
        self.btn_batch.clicked.connect(self.batch_requested)
        self.btn_acquisition_cockpit.clicked.connect(self.acquisition_cockpit_requested)
```

In `set_enabled_for_mode` (lines 154-157), replace:

```python
    def set_enabled_for_mode(self, mode, has_file):
        """Implements the §7.1 enabled-state matrix."""
        self.btn_export.setEnabled(has_file)
        self.btn_batch.setEnabled(True)
```

with:

```python
    def set_enabled_for_mode(self, mode, has_file):
        """Implements the §7.1 enabled-state matrix."""
        self.btn_save_project.setEnabled(has_file)
        self.btn_batch.setEnabled(True)
```

- [ ] **Step 7: Rewire signals in `main_window.py`**

Replace lines 337-338:

```python
        self.toolbar.file_add_requested.connect(self.load_files)
        self.toolbar.export_requested.connect(self.export_excel)
```

with:

```python
        self.toolbar.open_requested.connect(self.open_files_or_project)
        self.toolbar.save_project_requested.connect(self.save_project_via_dialog)
```

- [ ] **Step 8: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar.py tests/ui/test_toolbar_i18n.py tests/ui/test_side_panel_widgets.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/ui/toolbar.py mf4_analyzer/ui/main_window.py tests/ui/test_toolbar.py
git commit -m "feat(toolbar): split 添加文件 into 打开/保存项目, remove 导出 button"
```

---

## Task D1: MainWindow._do_export_excel (relocated export core)

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (replace `export_excel` body with `_do_export_excel`)
- Test: `tests/ui/test_channel_editor_export.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_channel_editor_export.py
import csv
import openpyxl
from PyQt5.QtWidgets import QFileDialog


def _csv(path, n=20):
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time", "rpm", "spd"])
        for i in range(n):
            w.writerow([i / 100.0, float(i), float(2 * i)])


def test_do_export_excel_writes_selected(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    a = tmp_path / "a.csv"; _csv(a)
    out = tmp_path / "out.xlsx"
    mw = MainWindow(); mw._load_one(str(a))
    fid = next(iter(mw.files))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a_, **k: (str(out), ""))
    mw._do_export_excel(fid, ["rpm"], include_time=True, use_range=False)
    assert out.exists()
    wb = openpyxl.load_workbook(out)
    headers = [c.value for c in wb.active[1]]
    assert headers == ["Time", "rpm"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_channel_editor_export.py -q`
Expected: FAIL with `AttributeError: ... '_do_export_excel'`.

- [ ] **Step 3: Replace `export_excel` with `_do_export_excel`**

Delete the whole `export_excel` method (`main_window.py:1843-1874`) and add:

```python
    def _do_export_excel(self, fid, channels, include_time, use_range):
        """Write the given channels of file ``fid`` to an Excel file. Invoked
        by the channel-editor's 导出 section (export_requested). Time column and
        time-range filter mirror the former toolbar-export behavior."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        import pandas as pd
        fd = self.files.get(fid)
        if fd is None or not channels:
            return
        fp, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "", "Excel (*.xlsx)")
        if not fp:
            return
        try:
            df = pd.DataFrame()
            if include_time and fd.time_array is not None:
                df['Time'] = fd.time_array
            for ch in channels:
                if ch in fd.data.columns:
                    df[ch] = fd.data[ch].values
            if use_range and fd.time_array is not None:
                lo, hi = self.inspector.top.range_values()
                m = (fd.time_array >= lo) & (fd.time_array <= hi)
                df = df.loc[m].reset_index(drop=True)
            df.to_excel(fp, index=False, engine='openpyxl')
            self.statusBar.showMessage(
                f"导出完成: {Path(fp).name} ({len(df)} 行 × {len(df.columns)} 列)"
            )
            self.toast(
                f"已导出 {Path(fp).name} · {len(df)} 行 × {len(df.columns)} 列",
                "success",
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_channel_editor_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_channel_editor_export.py
git commit -m "refactor(export): relocate export core to _do_export_excel(fid, channels, ...)"
```

---

## Task D2: Channel-editor 导出 section + signal

**Files:**
- Modify: `mf4_analyzer/ui/dialogs.py` (`ChannelEditorDialog`: signal, section, populate)
- Test: `tests/ui/test_channel_editor_export.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def _make_files(tmp_path):
    import pandas as pd
    import numpy as np
    from mf4_analyzer.io.file_data import FileData
    df = pd.DataFrame({"time": np.arange(20) / 100.0,
                       "rpm": np.arange(20.0), "spd": np.arange(20.0) * 2})
    fd = FileData(str(tmp_path / "demo.mf4"), df, list(df.columns), {}, 0)
    return {"f0": fd}


def test_editor_has_export_section_between_dual_and_delete(qapp, tmp_path):
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    from PyQt5.QtWidgets import QGroupBox
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    boxes = [b.title() for b in dlg.findChildren(QGroupBox)]
    assert "导出" in boxes
    # order: 双通道运算 ... 导出 ... 删除
    assert boxes.index("导出") > boxes.index("双通道运算 (A ⊕ B)")
    assert boxes.index("导出") < boxes.index("删除")
    # checkable export list, defaults checked
    assert dlg.list_export.count() == 2  # rpm, spd (time excluded)


def test_editor_export_button_emits_signal(qapp, tmp_path):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.dialogs import ChannelEditorDialog
    dlg = ChannelEditorDialog(None, _make_files(tmp_path), "f0")
    # uncheck spd, keep rpm
    for i in range(dlg.list_export.count()):
        it = dlg.list_export.item(i)
        it.setCheckState(Qt.Checked if it.text() == "rpm" else Qt.Unchecked)
    captured = {}
    dlg.export_requested.connect(
        lambda fid, chs, t, r: captured.update(fid=fid, chs=chs, t=t, r=r))
    dlg.chk_export_time.setChecked(True)
    dlg.chk_export_range.setChecked(False)
    dlg.btn_export.click()
    assert captured["fid"] == "f0"
    assert captured["chs"] == ["rpm"]
    assert captured["t"] is True and captured["r"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_channel_editor_export.py -k editor -q`
Expected: FAIL (`export_requested`/`list_export` missing).

- [ ] **Step 3: Add the signal**

At the top of `class ChannelEditorDialog` (after the class docstring / before `INPUT_WIDTH`, line ~45), add:

```python
    # (fid, channels, include_time, use_range) — the 导出 section asks
    # MainWindow to perform the Excel write (pandas + inspector range live there).
    export_requested = pyqtSignal(str, list, bool, bool)
```

Ensure `pyqtSignal` is imported (it is — `from PyQt5.QtCore import ... pyqtSignal` at the top of dialogs.py; confirm via `grep -n "pyqtSignal" mf4_analyzer/ui/dialogs.py` and add to the import if absent).

- [ ] **Step 4: Insert the 导出 section between 双通道运算 and 删除**

In `__init__`, between `bl.addWidget(g2)` (line 169) and the `# 删除通道` comment (line 171), insert:

```python
        # 导出（在双通道运算之下、删除之上）
        gx = QGroupBox("导出")
        gxl = QVBoxLayout(gx)
        gxl.setSpacing(8)
        self.list_export = QListWidget()
        self.list_export.setObjectName("channelExportList")
        self.list_export.setMinimumHeight(108)
        self.list_export.setMaximumHeight(120)
        gxl.addWidget(self.list_export)
        self.chk_export_time = QCheckBox("包含时间列")
        self.chk_export_time.setChecked(True)
        self.chk_export_range = QCheckBox("仅导出选定时间范围")
        gxl.addWidget(self.chk_export_time)
        gxl.addWidget(self.chk_export_range)
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setObjectName("channelCreateBtn")
        self.btn_export.setProperty("role", "create")
        self.btn_export.clicked.connect(self._on_export_clicked)
        gxl.addWidget(self.btn_export, 0, Qt.AlignLeft)
        bl.addWidget(gx)
```

Ensure `QCheckBox` is imported in dialogs.py (add to the `from PyQt5.QtWidgets import (...)` block if missing — confirm with `grep -n "QCheckBox" mf4_analyzer/ui/dialogs.py`).

- [ ] **Step 5: Populate the export list + emit handler**

In `_populate_channels` (line 272), after the `list_rm` fill loop (lines 289-291), add:

```python
        self.list_export.clear()
        for ch in chs:
            it = QListWidgetItem(ch)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list_export.addItem(it)
```

Ensure `QListWidgetItem` is imported (add if missing — `grep -n "QListWidgetItem" mf4_analyzer/ui/dialogs.py`).

Add the click handler as a method on the dialog (e.g. after `_populate_channels`):

```python
    def _on_export_clicked(self):
        if self.current_fid is None:
            return
        channels = [
            self.list_export.item(i).text()
            for i in range(self.list_export.count())
            if self.list_export.item(i).checkState() == Qt.Checked
        ]
        if not channels:
            QMessageBox.information(self, "导出", "请先勾选要导出的通道。")
            return
        self.export_requested.emit(
            self.current_fid, channels,
            self.chk_export_time.isChecked(),
            self.chk_export_range.isChecked(),
        )
```

Ensure `QMessageBox` is imported in dialogs.py (`grep -n "QMessageBox" mf4_analyzer/ui/dialogs.py`; add if missing).

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_channel_editor_export.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/dialogs.py tests/ui/test_channel_editor_export.py
git commit -m "feat(channel-editor): 导出 section (own channel checkboxes) emitting export_requested"
```

---

## Task D3: Wire dialog export through the drawer to MainWindow

**Files:**
- Modify: `mf4_analyzer/ui/drawers/channel_editor_drawer.py` (re-emit signal)
- Modify: `mf4_analyzer/ui/main_window.py:1786-1787` (connect)
- Test: `tests/ui/test_channel_editor_export.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_drawer_reemits_export_requested(qapp, tmp_path):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
    drawer = ChannelEditorDrawer(None, _make_files(tmp_path), "f0")
    got = {}
    drawer.export_requested.connect(
        lambda fid, chs, t, r: got.update(fid=fid, chs=chs))
    drawer._inner.btn_export.click()
    assert got["fid"] == "f0"
    assert got["chs"] == ["rpm", "spd"]   # both default-checked
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_channel_editor_export.py -k drawer -q`
Expected: FAIL (`ChannelEditorDrawer` has no `export_requested`).

- [ ] **Step 3: Re-emit on the drawer**

In `mf4_analyzer/ui/drawers/channel_editor_drawer.py`, add a signal to `ChannelEditorDrawer` (next to `applied`, line 21):

```python
    export_requested = pyqtSignal(str, list, bool, bool)
```

In `__init__`, after `self._inner.accepted.connect(self._on_applied)` (line 39), add:

```python
        self._inner.export_requested.connect(self.export_requested)
```

(`pyqtSignal` is already imported in this file.)

- [ ] **Step 4: Connect at the drawer open site in `main_window.py`**

After `drawer.applied.connect(self._apply_channel_edits)` (line 1787), add:

```python
        drawer.export_requested.connect(self._do_export_excel)
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_channel_editor_export.py -q`
Expected: PASS (all export tests).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/drawers/channel_editor_drawer.py mf4_analyzer/ui/main_window.py tests/ui/test_channel_editor_export.py
git commit -m "feat(channel-editor): wire 导出 section through drawer to _do_export_excel"
```

---

## Final regression gate + visual check

- [ ] Full suite for the touched areas:

```bash
.venv/bin/python -m pytest tests/ui/ tests/test_project_io.py -q
```

Expected: all PASS.

- [ ] Visual check (project rule — verify UI on a real render). Run `.venv/bin/python -m mf4_analyzer.app` and confirm:
  - Left toolbar reads `[打开][保存项目][批处理][Cockpit]`; no 导出 button.
  - 打开 → file dialog lists `.tlproj` + data files; picking a `.tlproj` with files loaded prompts the replace confirm; picking data files appends.
  - 保存项目 → first time prompts Save-As; once a project is open, overwrites silently.
  - 编辑通道 drawer shows a 导出 section between 双通道运算 and 删除, with a checkable channel list + 包含时间列 / 仅导出选定时间范围 + 导出 Excel; clicking exports the checked channels.

---

## Self-Review

**Spec coverage:**
- §2.1 unified open + partition + replace guard → C1 (5 tests incl. confirm-cancel).
- §2.2 save button + `_project_path` (first=Save-As, then overwrite) → C2.
- §2.3 remove 导出, update `set_enabled_for_mode`, fix `test_toolbar.py` → C3.
- §3.1 导出 section placement (between 双通道/删除) + own checkboxes + options → D2 (order asserted).
- §3.2 `export_requested` signal + drawer re-emit + `_do_export_excel` write → D1, D2, D3.

**Placeholder scan:** No TBD; every code step is complete. The only deferred cosmetic (a dedicated 保存 icon vs reused export glyph) is called out explicitly in C3 step 4.

**Type consistency:** `export_requested = pyqtSignal(str, list, bool, bool)` is identical in `ChannelEditorDialog` (D2), the drawer (D3), and matches `_do_export_excel(self, fid, channels, include_time, use_range)` (D1). `open_requested`/`save_project_requested` defined in C3 are connected to `open_files_or_project`/`save_project_via_dialog` defined in C1/C2. `list_export`/`chk_export_time`/`chk_export_range`/`btn_export` referenced only where defined (D2).

**Import guards:** D2/D3 steps explicitly grep-and-add `QCheckBox`, `QListWidgetItem`, `QMessageBox`, `pyqtSignal` to the dialogs.py imports if absent — these are the only new widget imports the section needs.

**Known dependency:** C3 rewires `main_window.py:337-338` to `open_files_or_project`/`save_project_via_dialog`, which C1/C2 already added — so C3 never references an undefined handler. D3 connects to `_do_export_excel` added in D1. Order C1→C2→C3→D1→D2→D3 keeps every task's suite green.
