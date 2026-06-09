# Project I/O + Toolbar Branding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reference-only `.tlproj` save/load底层 (no UI entry yet) and rework the toolbar to move Cockpit left, show the BOSCH logo top-right, and put a cloud-download "update" icon in the status bar linking to the Feishu release page.

**Architecture:** Workstream A keeps all serialization in a pure, Qt-free `project_io.py` (mirrors `batch_preset_io.py`); `MainWindow.save_project()/open_project()` are thin orchestrators that re-read source files and reinstall saved `ViewState`s, remapping fids via a pure helper. Workstream B touches `toolbar.py` (Cockpit move + logo `QLabel`), `ui_kit/icons.py` (new programmatic icon), and the `QStatusBar` (update button + version label). A new `app_meta.py` centralizes version/URL/asset-path.

**Tech Stack:** Python 3, PyQt5, pytest + pytest-qt (`tests/ui/conftest.py` provides the `qapp` fixture and offscreen platform). The repo venv is `.venv` (`.venv/bin/python`).

---

## File Structure

**New files:**
- `mf4_analyzer/app_meta.py` — app name/version, release URL, `asset_path()` resolver (PyInstaller-aware). Shared by A & B.
- `mf4_analyzer/ui/project_io.py` — pure `.tlproj` (de)serialization + path resolution + fid remap.
- `assets/branding/bosch_hasco_logo.png` — trimmed, transparent BOSCH logo asset.
- `tests/test_project_io.py` — pure serialization/remap unit tests (no Qt).
- `tests/ui/test_project_session.py` — `MainWindow` save/open round-trip.
- `tests/ui/test_toolbar_branding.py` — Cockpit-left + logo presence.
- `tests/ui/test_update_indicator.py` — status-bar update button + version + URL.
- `tests/ui/test_icons_cloud.py` — cloud-download icon renders.

**Modified files:**
- `mf4_analyzer/ui/main_window.py` — window title via `app_meta`; `save_project`/`open_project`; status-bar update indicator; one-line hint-bar insert change.
- `mf4_analyzer/ui/toolbar.py` — move Cockpit button to left cluster; add logo `QLabel` to right band.
- `mf4_analyzer/ui_kit/icons.py` — add `Icons.cloud_download()`.
- `tools/build_windows_folder.ps1` — bundle `assets/branding`.

---

## Task A1: app_meta module + window title

**Files:**
- Create: `mf4_analyzer/app_meta.py`
- Modify: `mf4_analyzer/ui/main_window.py:87`
- Test: `tests/ui/test_project_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_project_session.py
from mf4_analyzer import app_meta


def test_app_meta_constants():
    assert app_meta.APP_VERSION == "v6.5"
    assert app_meta.WINDOW_TITLE == "TraceLab v6.5"
    assert app_meta.RELEASE_URL.startswith("https://")


def test_window_title_uses_app_meta(qapp):
    from mf4_analyzer.ui.main_window import MainWindow
    mw = MainWindow()
    assert mw.windowTitle() == app_meta.WINDOW_TITLE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_project_session.py -q`
Expected: FAIL with `ModuleNotFoundError: mf4_analyzer.app_meta`.

- [ ] **Step 3: Create `mf4_analyzer/app_meta.py`**

```python
"""Single source of truth for app identity, release URL, and asset paths."""
from __future__ import annotations

import sys
from pathlib import Path

APP_NAME = "TraceLab"
APP_VERSION = "v6.5"
WINDOW_TITLE = f"{APP_NAME} {APP_VERSION}"

# Feishu release/download page opened by the status-bar update icon.
RELEASE_URL = "https://jcnubq178nzc.feishu.cn/wiki/LkfAwEotfiSO6GktmPvcYPRznhd"


def asset_path(*parts: str) -> Path:
    """Resolve a bundled asset path. PyInstaller exposes the bundle root via
    ``sys._MEIPASS``; in dev fall back to the repo root (parent of this
    package). Mirrors ``mf4_analyzer/app.py:_load_app_icon``."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base is not None else Path(__file__).resolve().parent.parent
    return root.joinpath("assets", *parts)
```

- [ ] **Step 4: Wire the title in `main_window.py`**

At the top of `mf4_analyzer/ui/main_window.py`, add to the imports block:

```python
from .. import app_meta
```

Replace line 87:

```python
        self.setWindowTitle("TraceLab v6.5")
```

with:

```python
        self.setWindowTitle(app_meta.WINDOW_TITLE)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ui/test_project_session.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/app_meta.py mf4_analyzer/ui/main_window.py tests/ui/test_project_session.py
git commit -m "feat(meta): add app_meta (version/url/asset_path) and use for window title"
```

---

## Task A2: project_io — save/load JSON

**Files:**
- Create: `mf4_analyzer/ui/project_io.py`
- Test: `tests/test_project_io.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_io.py
import json
import pytest
from mf4_analyzer.ui import project_io as pio


def _doc():
    return pio.ProjectDocument(
        active_file="f0",
        current_mode="time",
        files=[
            pio.ProjectFileRef(fid="f0", path_abs="/data/a.mf4",
                               path_rel="a.mf4", fs=2000.0, time_source="manual"),
        ],
        views=[{"name": "View 1", "tab_color": "#2d7ff9", "checked": [["f0", "rpm"]]}],
        view_manager={"active": 0, "split_pairs": {}},
    )


def test_roundtrip(tmp_path):
    path = tmp_path / "s.tlproj"
    pio.save_project_to_json(_doc(), path)
    loaded = pio.load_project_from_json(path)
    assert loaded.active_file == "f0"
    assert loaded.current_mode == "time"
    assert loaded.files[0].fid == "f0"
    assert loaded.files[0].fs == 2000.0
    assert loaded.files[0].time_source == "manual"
    assert loaded.views[0]["name"] == "View 1"
    assert loaded.view_manager["active"] == 0


def test_schema_version_written(tmp_path):
    path = tmp_path / "s.tlproj"
    pio.save_project_to_json(_doc(), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == pio.SCHEMA_VERSION


def test_unknown_version_rejected(tmp_path):
    path = tmp_path / "s.tlproj"
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(pio.UnsupportedProjectVersion):
        pio.load_project_from_json(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_project_io.py -q`
Expected: FAIL with `ModuleNotFoundError: mf4_analyzer.ui.project_io`.

- [ ] **Step 3: Create `mf4_analyzer/ui/project_io.py`**

```python
"""JSON serialization for TraceLab project sessions (.tlproj).

Reference-only: stores file *paths* (+ per-file fs/time_source overrides) and
the full View list — never parsed data. Mirrors ``batch_preset_io.py``'s
versioned save/load shape. Pure (no Qt, no MainWindow) so it round-trips
through tests without a running app.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


class UnsupportedProjectVersion(ValueError):
    """Raised when reading a .tlproj whose schema_version is unknown."""


@dataclass
class ProjectFileRef:
    fid: str
    path_abs: str
    path_rel: str | None
    fs: float
    time_source: str


@dataclass
class ProjectDocument:
    active_file: str | None
    current_mode: str
    files: list = field(default_factory=list)        # list[ProjectFileRef]
    views: list = field(default_factory=list)         # list[dict] (ViewState.to_dict)
    view_manager: dict = field(default_factory=dict)  # {"active": int, "split_pairs": {}}


def save_project_to_json(doc: ProjectDocument, path) -> None:
    path = Path(path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "active_file": doc.active_file,
        "current_mode": doc.current_mode,
        "files": [
            {
                "fid": r.fid,
                "path_abs": r.path_abs,
                "path_rel": r.path_rel,
                "fs": float(r.fs),
                "time_source": r.time_source,
            }
            for r in doc.files
        ],
        "views": doc.views,
        "view_manager": doc.view_manager,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_project_from_json(path) -> ProjectDocument:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid project JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("project JSON must be a JSON object")

    version = raw.get("schema_version")
    if version is None:
        version = 1
    if version != SCHEMA_VERSION:
        raise UnsupportedProjectVersion(
            f"project schema_version={version} not supported "
            f"(this app reads v{SCHEMA_VERSION})"
        )

    files = [
        ProjectFileRef(
            fid=str(f["fid"]),
            path_abs=str(f["path_abs"]),
            path_rel=f.get("path_rel"),
            fs=float(f.get("fs", 1000.0)),
            time_source=str(f.get("time_source", "generated")),
        )
        for f in raw.get("files", [])
    ]
    return ProjectDocument(
        active_file=raw.get("active_file"),
        current_mode=str(raw.get("current_mode", "time")),
        files=files,
        views=list(raw.get("views", [])),
        view_manager=dict(raw.get("view_manager", {})),
    )


def make_relative(path_abs: str, project_path) -> str | None:
    """Path of ``path_abs`` relative to the .tlproj dir; None across drives."""
    try:
        return os.path.relpath(path_abs, Path(project_path).parent)
    except ValueError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_project_io.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/project_io.py tests/test_project_io.py
git commit -m "feat(project-io): versioned .tlproj save/load (reference-only)"
```

---

## Task A3: project_io — resolve_file_path

**Files:**
- Modify: `mf4_analyzer/ui/project_io.py`
- Test: `tests/test_project_io.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_resolve_prefers_relative(tmp_path):
    (tmp_path / "data").mkdir()
    real = tmp_path / "data" / "a.csv"
    real.write_text("x", encoding="utf-8")
    proj = tmp_path / "s.tlproj"
    ref = pio.ProjectFileRef(fid="f0", path_abs="/gone/a.csv",
                             path_rel="data/a.csv", fs=1000.0, time_source="generated")
    assert pio.resolve_file_path(ref, proj) == real.resolve()


def test_resolve_falls_back_to_abs(tmp_path):
    real = tmp_path / "b.csv"
    real.write_text("x", encoding="utf-8")
    proj = tmp_path / "s.tlproj"
    ref = pio.ProjectFileRef(fid="f0", path_abs=str(real),
                             path_rel="missing/b.csv", fs=1000.0, time_source="generated")
    assert pio.resolve_file_path(ref, proj) == real


def test_resolve_missing_returns_none(tmp_path):
    proj = tmp_path / "s.tlproj"
    ref = pio.ProjectFileRef(fid="f0", path_abs="/gone/x.csv",
                             path_rel="also/gone.csv", fs=1000.0, time_source="generated")
    assert pio.resolve_file_path(ref, proj) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_project_io.py -k resolve -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'resolve_file_path'`.

- [ ] **Step 3: Add `resolve_file_path` to `project_io.py`**

```python
def resolve_file_path(ref: ProjectFileRef, project_path) -> "Path | None":
    """Locate a referenced file: path_rel (relative to the .tlproj) first,
    then path_abs. Returns None when neither exists."""
    project_dir = Path(project_path).parent
    if ref.path_rel:
        cand = (project_dir / ref.path_rel).resolve()
        if cand.exists():
            return cand
    cand = Path(ref.path_abs)
    if cand.exists():
        return cand
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_project_io.py -k resolve -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/project_io.py tests/test_project_io.py
git commit -m "feat(project-io): resolve_file_path (relative-first, absolute fallback)"
```

---

## Task A4: project_io — remap_view_fids

**Files:**
- Modify: `mf4_analyzer/ui/project_io.py`
- Test: `tests/test_project_io.py`

The fid in a saved view (`checked`, `colors`, `overlay_primary`, `axis_opts.x_axis.fid`)
must be rewritten to the fid the file gets when re-loaded, because `_load_one`
mints fresh sequential fids and a skipped (missing) file shifts the sequence.
`ylims` is keyed by axis label, not fid, so it passes through untouched.

- [ ] **Step 1: Write the failing test (append)**

```python
def test_remap_rewrites_and_drops():
    view = {
        "name": "V", "tab_color": "#fff",
        "checked": [["f0", "rpm"], ["f1", "spd"]],
        "colors": {'["f0","rpm"]': "#ff0000", '["f1","spd"]': "#00ff00"},
        "overlay_primary": ["f1", "spd"],
        "ylims": {"[a] rpm": [0.0, 10.0]},
        "axis_opts": {"x_axis": {"mode": "channel", "fid": "f1",
                                 "channel": "spd", "label": "spd"}},
    }
    # f0 -> f3 kept; f1 missing (absent from map) -> dropped
    out = pio.remap_view_fids([view], {"f0": "f3"})[0]
    assert out["checked"] == [["f3", "rpm"]]
    assert out["colors"] == {'["f3","rpm"]': "#ff0000"}
    assert out["overlay_primary"] is None
    assert out["ylims"] == {"[a] rpm": [0.0, 10.0]}          # untouched
    assert out["axis_opts"]["x_axis"]["fid"] is None
    assert out["axis_opts"]["x_axis"]["mode"] == "time"


def test_remap_identity_when_map_matches():
    view = {"name": "V", "tab_color": "#fff",
            "checked": [["f0", "rpm"]], "colors": {}, "overlay_primary": None}
    out = pio.remap_view_fids([view], {"f0": "f0"})[0]
    assert out["checked"] == [["f0", "rpm"]]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_project_io.py -k remap -q`
Expected: FAIL with `AttributeError: ... 'remap_view_fids'`.

- [ ] **Step 3: Add `remap_view_fids` (+ helper) to `project_io.py`**

```python
def _encode_channel_key(fid: str, channel: str) -> str:
    # Matches ui.view_state._encode_channel_key exactly.
    return json.dumps([fid, channel], ensure_ascii=False, separators=(",", ":"))


def remap_view_fids(views: list, fid_map: dict) -> list:
    """Rewrite the fid of every channel reference in a list of
    ``ViewState.to_dict()`` payloads, dropping references whose fid is absent
    from ``fid_map`` (the file went missing on load)."""
    out = []
    for view in views:
        v = dict(view)

        v["checked"] = [
            [fid_map[fid], ch]
            for fid, ch in (tuple(x) for x in view.get("checked", []))
            if fid in fid_map
        ]

        new_colors = {}
        for key, color in (view.get("colors") or {}).items():
            fid, ch = json.loads(key)
            if fid in fid_map:
                new_colors[_encode_channel_key(fid_map[fid], ch)] = color
        v["colors"] = new_colors

        op = view.get("overlay_primary")
        v["overlay_primary"] = (
            [fid_map[op[0]], op[1]] if op and op[0] in fid_map else None
        )

        axis = dict(view.get("axis_opts") or {})
        if "x_axis" in axis:
            xaxis = dict(axis["x_axis"])
            xfid = xaxis.get("fid")
            if xfid is not None and xfid in fid_map:
                xaxis["fid"] = fid_map[xfid]
            elif xfid is not None:
                xaxis["fid"] = None
                xaxis["channel"] = None
                xaxis["mode"] = "time"
            axis["x_axis"] = xaxis
            v["axis_opts"] = axis

        out.append(v)
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_project_io.py -q`
Expected: PASS (all project_io tests).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/project_io.py tests/test_project_io.py
git commit -m "feat(project-io): remap_view_fids for reload fid reassignment"
```

---

## Task A5: MainWindow.save_project

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (add method near other view helpers, e.g. after `_capture_focused_view`)
- Test: `tests/ui/test_project_session.py`

- [ ] **Step 1: Write the failing test (append)**

```python
import csv


def _write_csv(path, n=40):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "rpm"])
        for i in range(n):
            w.writerow([i / 100.0, float(i)])


def test_save_project_writes_file(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import project_io as pio
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw.view_manager.rename(0, "主视图")
    proj = tmp_path / "s.tlproj"
    mw.save_project(proj)

    doc = pio.load_project_from_json(proj)
    assert [f.path_abs for f in doc.files] == [str(csv_a.resolve())]
    assert doc.files[0].path_rel == "a.csv"
    assert doc.views[0]["name"] == "主视图"
    assert doc.current_mode == "time"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_project_session.py -k save_project -q`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute 'save_project'`.

- [ ] **Step 3: Add `save_project` to `MainWindow`**

```python
    def save_project(self, path):
        """Serialize the current session (open files + all Views) to a
        reference-only ``.tlproj`` JSON file. No UI entry point yet — this is
        the底层 callable used by tests and a future menu/button."""
        from pathlib import Path
        from . import project_io as pio
        path = Path(path)

        # Flush the active view's live canvas/control state into its ViewState
        # so an unsaved zoom/selection is captured before serialization.
        self._capture_focused_view()

        file_refs = []
        for fid, fd in self.files.items():
            abs_p = str(Path(fd.filepath).resolve())
            file_refs.append(pio.ProjectFileRef(
                fid=fid,
                path_abs=abs_p,
                path_rel=pio.make_relative(abs_p, path),
                fs=float(fd.fs),
                time_source=fd._time_source,
            ))

        vm = {
            "active": int(self.view_manager.active),
            "split_pairs": {
                str(host): int(src)
                for host, src in self.view_manager._split_pairs.items()
            },
        }
        doc = pio.ProjectDocument(
            active_file=self._active,
            current_mode=self.chart_stack.current_mode(),
            files=file_refs,
            views=[v.to_dict() for v in self.view_manager.views],
            view_manager=vm,
        )
        pio.save_project_to_json(doc, path)
        self.statusBar.showMessage(f"已保存项目: {path.name}")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_project_session.py -k save_project -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_project_session.py
git commit -m "feat(project-io): MainWindow.save_project (.tlproj writer)"
```

---

## Task A6: MainWindow.open_project

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (add method next to `save_project`)
- Test: `tests/ui/test_project_session.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_open_project_roundtrip(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.view_manager.rename(0, "主视图")
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv", "b.csv"]
    assert mw2.view_manager.views[0].name == "主视图"
    assert mw2.chart_stack.current_mode() == "time"


def test_open_project_skips_missing(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.save_project(proj)
    csv_b.unlink()  # make one file missing

    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("hit", True))
    mw2 = MainWindow()
    mw2.open_project(proj)
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv"]
    assert warned.get("hit") is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_project_session.py -k open_project -q`
Expected: FAIL with `AttributeError: ... 'open_project'`.

- [ ] **Step 3: Add `open_project` to `MainWindow`**

```python
    def open_project(self, path):
        """Restore a session from a ``.tlproj`` file: re-read referenced source
        files (skipping missing ones), reinstall saved Views with fids remapped
        to freshly minted ids, and select the saved active file / mode."""
        from pathlib import Path
        from PyQt5.QtWidgets import QMessageBox
        from . import project_io as pio
        from .view_state import ViewState
        path = Path(path)

        doc = pio.load_project_from_json(path)
        self.close_all()

        fid_map = {}
        missing = []
        for ref in doc.files:
            resolved = pio.resolve_file_path(ref, path)
            if resolved is None:
                missing.append(ref.path_abs)
                continue
            before = len(self.files)
            self._load_one(str(resolved))
            if len(self.files) <= before:
                missing.append(ref.path_abs)
                continue
            new_fid = next(reversed(self.files))
            fid_map[ref.fid] = new_fid
            fd = self.files[new_fid]
            fd.fs = float(ref.fs)
            if ref.time_source in ("generated", "manual"):
                fd.rebuild_time_axis(float(ref.fs))

        # Reinstall views with fids remapped to the freshly minted ids.
        remapped = pio.remap_view_fids(doc.views, fid_map)
        states = [ViewState.from_dict(v) for v in remapped]
        if not states:
            states = [self.view_manager._make(0)]
        self.view_manager.views = states
        self.view_manager._split_pairs = {
            int(host): int(src)
            for host, src in (doc.view_manager.get("split_pairs") or {}).items()
            if 0 <= int(host) < len(states) and 0 <= int(src) < len(states)
        }
        active_idx = int(doc.view_manager.get("active", 0))
        self.view_manager.active = max(0, min(active_idx, len(states) - 1))
        self.view_manager._set_active_split_from_pairs()
        self.view_manager.views_changed.emit()

        # Active file + display mode.
        self._active = fid_map.get(doc.active_file)
        self.chart_stack.set_mode(doc.current_mode)

        # Refresh the UI to the active view (best-effort render).
        self._apply_active_view(self.view_manager.active)

        if missing:
            QMessageBox.warning(
                self, "部分文件缺失",
                "以下文件找不到，已跳过：\n" + "\n".join(missing),
            )
        self.statusBar.showMessage(f"已打开项目: {path.name}")
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_project_session.py -q`
Expected: PASS (all project_session tests).

- [ ] **Step 5: Run the full project_io + session suite as a regression gate**

Run: `.venv/bin/python -m pytest tests/test_project_io.py tests/ui/test_project_session.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_project_session.py
git commit -m "feat(project-io): MainWindow.open_project (reload + view remap + missing-file skip)"
```

---

## Task B1: Move Cockpit button to the left cluster

**Files:**
- Modify: `mf4_analyzer/ui/toolbar.py:58-63` (add to left) and `:92-93` (remove from right)
- Test: `tests/ui/test_toolbar_branding.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_toolbar_branding.py
def test_cockpit_button_in_left_cluster(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    assert tb.btn_acquisition_cockpit.parentWidget() is tb._left_widget
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar_branding.py -q`
Expected: FAIL — button's parent is still `_right_widget`.

- [ ] **Step 3: Edit `toolbar.py`**

Add the Cockpit button to the left layout. Replace lines 58-63:

```python
        for b in (
            self.btn_add,
            self.btn_export,
            self.btn_batch,
        ):
            left.addWidget(b)
```

with:

```python
        for b in (
            self.btn_add,
            self.btn_export,
            self.btn_batch,
            self.btn_acquisition_cockpit,
        ):
            left.addWidget(b)
```

Remove the Cockpit button from the right layout. Replace lines 89-93:

```python
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)
        right.addWidget(self.btn_acquisition_cockpit)
```

with:

```python
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar_branding.py -q`
Expected: PASS.

- [ ] **Step 5: Run existing toolbar tests as a regression gate**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar.py tests/ui/test_toolbar_i18n.py -q`
Expected: PASS (Cockpit signal/handler unchanged).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui/toolbar.py tests/ui/test_toolbar_branding.py
git commit -m "feat(toolbar): move Cockpit button next to 批处理"
```

---

## Task B2: cloud_download icon

**Files:**
- Modify: `mf4_analyzer/ui_kit/icons.py` (add classmethod to `Icons`)
- Test: `tests/ui/test_icons_cloud.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_icons_cloud.py
def test_cloud_download_renders(qapp):
    from mf4_analyzer.ui_kit.icons import Icons
    icon = Icons.cloud_download()
    assert not icon.isNull()
    assert not icon.pixmap(20, 20).isNull()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_icons_cloud.py -q`
Expected: FAIL with `AttributeError: type object 'Icons' has no attribute 'cloud_download'`.

- [ ] **Step 3: Add `cloud_download` to the `Icons` class**

Add inside `class Icons` (e.g. after `export`):

```python
    @classmethod
    def cloud_download(cls):
        """Cloud outline + down arrow — 'get the latest version'."""
        def draw(p):
            cloud = QPainterPath()
            cloud.moveTo(6.0, 13.0)
            cloud.cubicTo(2.6, 13.0, 2.6, 8.6, 6.3, 8.4)
            cloud.cubicTo(6.7, 4.7, 12.4, 4.4, 13.2, 8.1)
            cloud.cubicTo(16.6, 7.9, 16.9, 12.7, 13.8, 13.0)
            cloud.lineTo(6.0, 13.0)
            p.drawPath(cloud)
            p.drawLine(QPointF(10.0, 9.5), QPointF(10.0, 16.8))
            p.drawLine(QPointF(7.4, 14.0), QPointF(10.0, 16.8))
            p.drawLine(QPointF(12.6, 14.0), QPointF(10.0, 16.8))
        return _line_icon(draw, GRAY)
```

(`QPainterPath`, `QPointF`, `_line_icon`, `GRAY` are already imported/defined in `icons.py`.)

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_icons_cloud.py -q`
Expected: PASS.

- [ ] **Step 5: Visual check (the project requires verifying UI visually)**

Run: `.venv/bin/python -c "from PyQt5.QtWidgets import QApplication; app=QApplication([]); from mf4_analyzer.ui_kit.icons import Icons; Icons.cloud_download().pixmap(64,64).save('/tmp/cloud.png'); print('saved /tmp/cloud.png')"`
Open `/tmp/cloud.png` and confirm it reads as a cloud + down arrow. Adjust the cubic control points if the silhouette looks off.

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/ui_kit/icons.py tests/ui/test_icons_cloud.py
git commit -m "feat(icons): add cloud_download glyph for update link"
```

---

## Task B3: BOSCH logo in the toolbar right band

**Files:**
- Create: `assets/branding/bosch_hasco_logo.png`
- Modify: `mf4_analyzer/ui/toolbar.py` (imports + right layout)
- Modify: `tools/build_windows_folder.ps1`
- Test: `tests/ui/test_toolbar_branding.py`

- [ ] **Step 1: Prepare the asset (trim white already done; make background transparent)**

The trimmed source logo (white-bg, 1860×171) lives at
`.superpowers/brainstorm/60093-1780927006/content/logo-full-trim.png`.
Generate a transparent-background PNG into the repo:

```bash
cd "/Users/donghang/Downloads/data analyzer"
mkdir -p assets/branding
.venv/bin/python - <<'PY'
from PIL import Image
import numpy as np
src = ".superpowers/brainstorm/60093-1780927006/content/logo-full-trim.png"
im = Image.open(src).convert("RGBA")
a = np.array(im)
# near-white -> transparent; keep silver emblem / red / black text
white = (a[..., 0] > 248) & (a[..., 1] > 248) & (a[..., 2] > 248)
a[white, 3] = 0
Image.fromarray(a).save("assets/branding/bosch_hasco_logo.png")
print("wrote assets/branding/bosch_hasco_logo.png", im.size)
PY
```

Expected: prints the size `(1860, 171)` and the file exists.

- [ ] **Step 2: Write the failing test (append to test_toolbar_branding.py)**

```python
def test_toolbar_shows_logo(qapp):
    from mf4_analyzer.ui.toolbar import Toolbar
    tb = Toolbar()
    assert tb._logo_label.parentWidget() is tb._right_widget
    pm = tb._logo_label.pixmap()
    assert pm is not None and not pm.isNull()
```

- [ ] **Step 3: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar_branding.py -k logo -q`
Expected: FAIL with `AttributeError: 'Toolbar' object has no attribute '_logo_label'`.

- [ ] **Step 4: Edit `toolbar.py` imports**

Replace the import block (lines 2-8):

```python
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QWidget,
)

from ..ui_kit.icons import Icons
```

with:

```python
from PyQt5.QtCore import QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QWidget,
)

from .. import app_meta
from ..ui_kit.icons import Icons
```

- [ ] **Step 5: Add the logo `QLabel` to the right layout in `toolbar.py`**

In the right-layout block (now ending at `right.addStretch(1)` after Task B1), append the logo. Replace:

```python
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)
```

with:

```python
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addStretch(1)

        # BOSCH brand logo occupies the old Cockpit band (≈ Inspector width),
        # right-aligned at 190px with breathing room. DPR-aware scale keeps it
        # crisp on Retina (mirrors ui_kit.icons device-pixel-ratio handling).
        self._logo_label = QLabel(self)
        self._logo_label.setToolTip("博世华域转向系统有限公司")
        _logo_src = QPixmap(str(app_meta.asset_path("branding", "bosch_hasco_logo.png")))
        if not _logo_src.isNull():
            _app = QApplication.instance()
            _dpr = _app.devicePixelRatio() if _app is not None else 1.0
            _dpr = _dpr if _dpr and _dpr >= 1.0 else 1.0
            _scaled = _logo_src.scaledToWidth(int(190 * _dpr), Qt.SmoothTransformation)
            _scaled.setDevicePixelRatio(_dpr)
            self._logo_label.setPixmap(_scaled)
        right.addWidget(self._logo_label)
```

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_toolbar_branding.py -q`
Expected: PASS (cockpit-left + logo).

- [ ] **Step 7: Bundle the asset in the Windows build script**

In `tools/build_windows_folder.ps1`, after the `$AddDataIcons = "$IconsDir;assets\icons"` line (~105), add:

```powershell
$BrandingDir = Join-Path $RepoRoot "assets\branding"
$AddDataBranding = "$BrandingDir;assets\branding"
```

And in the PyInstaller args list, after the `"--add-data", $AddDataIcons,` line (~154), add:

```powershell
    "--add-data", $AddDataBranding,
```

Verify both edits landed:

Run: `grep -n "AddDataBranding" tools/build_windows_folder.ps1`
Expected: two matching lines (definition + args entry).

- [ ] **Step 8: Visual check (real render)**

Run the app (`.venv/bin/python -m mf4_analyzer.app`) and confirm: the BOSCH logo sits top-right where Cockpit used to be, ~190px wide, no white box behind it, not blurry; Cockpit now sits next to 批处理.

- [ ] **Step 9: Commit**

```bash
git add assets/branding/bosch_hasco_logo.png mf4_analyzer/ui/toolbar.py tools/build_windows_folder.ps1 tests/ui/test_toolbar_branding.py
git commit -m "feat(toolbar): BOSCH logo in right band + bundle assets/branding"
```

---

## Task B4: status-bar update indicator

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py` (`_init_ui` call + two methods + one hint-bar line)
- Test: `tests/ui/test_update_indicator.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ui/test_update_indicator.py
def test_update_button_opens_release_url(qapp, monkeypatch):
    from PyQt5.QtGui import QDesktopServices
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer import app_meta

    captured = {}
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        lambda url: captured.__setitem__("url", url.toString()) or True)

    mw = MainWindow()
    assert mw._update_btn.toolTip() == "检查更新"
    assert mw._version_label.text() == app_meta.APP_VERSION
    mw._update_btn.click()
    assert captured["url"] == app_meta.RELEASE_URL
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/ui/test_update_indicator.py -q`
Expected: FAIL with `AttributeError: 'MainWindow' object has no attribute '_update_btn'`.

- [ ] **Step 3: Keep the hint bar left of the update widgets**

In `mf4_analyzer/ui/main_window.py`, change line 244 from:

```python
        self.statusBar.addPermanentWidget(self._status_hint_bar, 1)
```

to:

```python
        self.statusBar.insertPermanentWidget(0, self._status_hint_bar, 1)
```

(`insertPermanentWidget(0, …)` pins the hint bar to the left of the permanent
area so the update indicator, added once below, always stays at the far right
even when the hint bar is swapped on mode change.)

- [ ] **Step 4: Install the indicator from `_init_ui`**

In `_init_ui`, immediately after line 220 (`self.statusBar.showMessage("Ready")`), add:

```python
        self._install_update_indicator()
```

- [ ] **Step 5: Add the two methods to `MainWindow`**

```python
    def _install_update_indicator(self):
        """Far-right status-bar update affordance: a cloud-download icon
        (no text, hover '检查更新') + the app version, linking to the release
        page. Conventional spot for app-meta/update info."""
        from PyQt5.QtCore import Qt, QSize
        from PyQt5.QtWidgets import QToolButton, QLabel
        from ..ui_kit.icons import Icons
        from .. import app_meta

        self._update_btn = QToolButton(self)
        self._update_btn.setIcon(Icons.cloud_download())
        self._update_btn.setIconSize(QSize(18, 18))
        self._update_btn.setAutoRaise(True)
        self._update_btn.setCursor(Qt.PointingHandCursor)
        self._update_btn.setToolTip("检查更新")
        self._update_btn.clicked.connect(self._open_release_page)

        self._version_label = QLabel(app_meta.APP_VERSION, self)
        self._version_label.setObjectName("versionTag")

        # Added after the hint bar (which is pinned at index 0) -> far right.
        self.statusBar.addPermanentWidget(self._update_btn)
        self.statusBar.addPermanentWidget(self._version_label)

    def _open_release_page(self):
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        from .. import app_meta
        QDesktopServices.openUrl(QUrl(app_meta.RELEASE_URL))
```

- [ ] **Step 6: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/ui/test_update_indicator.py -q`
Expected: PASS.

- [ ] **Step 7: Regression gate + visual check**

Run: `.venv/bin/python -m pytest tests/ui/test_main_window_smoke.py tests/ui/test_hints.py -q`
Expected: PASS (status bar + hint bar still healthy).

Then run the app and confirm the cloud icon + `v6.5` sit at the bottom-right, the
hint text ("Ctrl + 滚轮 缩放 X …") stays to their left, and clicking the icon
opens the Feishu page in the browser.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_update_indicator.py
git commit -m "feat(statusbar): cloud-download update icon + version, links to release page"
```

---

## Final regression gate

- [ ] Run the full new-test set plus the touched-area suites:

```bash
.venv/bin/python -m pytest tests/test_project_io.py tests/ui/test_project_session.py \
  tests/ui/test_toolbar_branding.py tests/ui/test_icons_cloud.py \
  tests/ui/test_update_indicator.py tests/ui/test_toolbar.py \
  tests/ui/test_main_window_smoke.py tests/ui/test_hints.py -q
```

Expected: all PASS.

---

## Self-Review

**Spec coverage:**
- §3.1 reference-only + manual document model → A2 (`.tlproj` writer/reader), A5/A6.
- §3.2 file format (schema_version, files, views, view_manager) → A2.
- §3.3 `project_io.py` mirroring `batch_preset_io.py` → A2-A4.
- §3.4 save/open methods, capture-active-view-first, fid reuse via remap → A5, A6.
- §3.5 missing-file warn+skip, relative-first/absolute-fallback → A3 + A6 (`test_open_project_skips_missing`).
- §3.6 tests (roundtrip, version reject, resolve, remap, save/open, missing) → A2-A6.
- §2 "no UI entry point" → A5/A6 expose methods only; no menu/button/shortcut added. ✓
- §4.1 Cockpit migration, signal/handler unchanged → B1 (+ regression gate on toolbar tests).
- §4.2 logo asset (trimmed+transparent), QLabel 190px right band, build-script add-data → B3.
- §4.3 cloud-download icon, no text, tooltip, version label, QDesktopServices to RELEASE_URL, app_meta → B2, B4, A1.
- §4.4 visual verification → B2 step 5, B3 step 8, B4 step 7.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; the only "future" item (UI entry) is intentionally out of scope per spec §2.

**Type consistency:** `ProjectFileRef`/`ProjectDocument` field names match across A2/A5/A6; `_encode_channel_key` in A4 matches `view_state._encode_channel_key`'s `json.dumps([fid,ch], ensure_ascii=False, separators=(",",":"))`; `asset_path("branding","bosch_hasco_logo.png")` used identically in B3 and matches the file created in B3 step 1; `_update_btn`/`_version_label`/`_logo_label` referenced only where defined.

**Known integration risk (flagged, not a placeholder):** A6's final `_apply_active_view` triggers a live render; the round-trip tests assert on the in-memory model (files/views/mode), which does not depend on render success. If headless rendering of an empty view ever throws, wrap that single call in a guarded try and surface via `statusBar` — but do not weaken the model-restore assertions.
