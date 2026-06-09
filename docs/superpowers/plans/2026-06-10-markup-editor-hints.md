# Markup Editor Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the markup editor's hidden keyboard/gesture vocabulary discoverable via one first-open toast plus filled-in tooltip shortcuts, extending the curated hint registry to its first non-chart consumer.

**Architecture:** Add a `scope` dimension to the `Hint` dataclass so the chart bottom bar (`scope="chart"`, the default) and the markup editor (`scope="markup"`) draw from one registry without cross-contamination. The markup editor becomes a new consumer: on first open it shows the reshaped `markup.capabilities` discovery hint through a `Toast` parented to itself, retiring it via the shared `QSettings` `chartHints/discovered` set. Four button tooltips gain their shortcut suffixes.

**Tech Stack:** Python, PyQt5 (`QSettings`, `QToolButton`, `Toast` widget), pytest + pytest-qt (`qtbot`, `tmp_path`).

Spec: `docs/superpowers/specs/2026-06-09-markup-editor-hints-design.md`

---

### Task 1: Registry — `scope` field, reshape `markup.capabilities`, scope-gated accessors

**Files:**
- Modify: `mf4_analyzer/ui/hints.py` (dataclass ~line 14-28; `markup.capabilities` entry lines 113-120; `context_hints` lines 195-202; `discovery_hint` lines 205-215)
- Test: `tests/ui/test_hints.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_hints.py` (it already imports `hints` and `HintState`):

```python
def test_hint_scope_defaults_to_chart():
    assert all(
        hint.scope == "chart"
        for hint in hints.all_hints()
        if hint.id != "markup.capabilities"
    )


def test_markup_capabilities_is_markup_scoped_ship_now_discovery():
    hint = next(h for h in hints.all_hints() if h.id == "markup.capabilities")
    assert hint.scope == "markup"
    assert hint.surface == "discovery"
    assert hint.ship == "now"
    assert "箭头键" in hint.text
    assert "双击文本" in hint.text


def test_chart_discovery_queue_excludes_markup_scope():
    state = HintState()
    ids = []
    while (hint := hints.discovery_hint(state)) is not None:
        ids.append(hint.id)
        state = HintState(discovered=state.discovered | {hint.id})
    assert "markup.capabilities" not in ids


def test_markup_scope_discovery_returns_then_retires_capabilities():
    fresh = HintState()
    assert hints.discovery_hint(fresh, scope="markup").id == "markup.capabilities"
    retired = HintState(discovered=frozenset({"markup.capabilities"}))
    assert hints.discovery_hint(retired, scope="markup") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/ui/test_hints.py -k "scope or markup_capabilities" -v`
Expected: FAIL — `markup.capabilities` text/scope mismatch and `discovery_hint()` raising `TypeError` for the unexpected `scope=` keyword.

- [ ] **Step 3: Add the `scope` field to `Hint`**

In `mf4_analyzer/ui/hints.py`, insert `scope` right after `surface` (it has a default, so ordering stays valid):

```python
@dataclass(frozen=True)
class Hint:
    id: str
    text: str
    surface: str
    scope: str = "chart"
    tier: str = "S"
    modes: frozenset[str] = field(default_factory=frozenset)
```

- [ ] **Step 4: Reshape the `markup.capabilities` entry**

Replace the existing entry (currently lines 113-120) with:

```python
    Hint(
        id="markup.capabilities",
        text="箭头键移动标注，Shift 加速 · 双击文本可编辑 · 工具支持单键切换（悬停按钮看键位）",
        surface="discovery",
        scope="markup",
        retire_on="markup_open",
        priority=40,
        ship="now",
    ),
```

- [ ] **Step 5: Scope-gate the accessors**

Add a `scope` parameter (default `"chart"`, keeping every existing call site unchanged) to both functions:

```python
def context_hints(state, scope="chart"):
    matches = [
        hint for hint in _HINTS
        if hint.surface == "context"
        and hint.scope == scope
        and hint.id not in state.recently_used
        and _matches_state(hint, state)
    ]
    return tuple(sorted(matches, key=_context_sort_key))


def discovery_hint(state, scope="chart"):
    candidates = [
        hint for hint in _HINTS
        if hint.surface == "discovery"
        and hint.scope == scope
        and hint.ship == "now"
        and hint.id not in state.discovered
        and _matches_state(hint, state)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda hint: -hint.priority)[0]
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `python -m pytest tests/ui/test_hints.py -k "scope or markup_capabilities" -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Run the full hints suite to prove no chart regression**

Run: `python -m pytest tests/ui/test_hints.py -v`
Expected: PASS — including the pre-existing `test_discovery_hint_returns_priority_order_and_skips_discovered` (its `all_now` set now also contains `markup.capabilities`, which is harmless: the default chart-scoped `discovery_hint` excludes it by scope and still returns `None`) and `test_design_curated_ids_exist_in_registry`.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/hints.py tests/ui/test_hints.py
git commit -m "feat(hints): add scope field; promote markup.capabilities to markup-scoped card"
```

---

### Task 2: Markup editor — fill tooltip shortcut gaps

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py` (lines 863, 881, 950, 962 — inside `_build_toolbar`)
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ui/test_markup_editor.py` (`QToolButton` is already imported there):

```python
def test_toolbar_buttons_expose_their_shortcuts(qtbot):
    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    tips = {
        name: editor.findChild(QToolButton, name).toolTip()
        for name in (
            "markupCloseButton",
            "markupUndoButton",
            "markupRedoButton",
            "markupStyleButton",
        )
    }
    assert tips["markupCloseButton"] == "关闭 (Esc)"
    assert tips["markupUndoButton"] == "撤销 (Ctrl+Z)"
    assert tips["markupRedoButton"] == "重做 (Ctrl+Y)"
    assert tips["markupStyleButton"] == "样式（颜色 / 线宽） · [ ] 调线宽"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/ui/test_markup_editor.py::test_toolbar_buttons_expose_their_shortcuts -v`
Expected: FAIL — tooltips still read `关闭`, `撤销`, `重做`, `样式（颜色 / 线宽）`.

- [ ] **Step 3: Update the four tooltip strings**

In `mf4_analyzer/ui/markup/editor.py`, make exactly these four edits inside `_build_toolbar`:

- Line 863: `close_btn.setToolTip("关闭")` → `close_btn.setToolTip("关闭 (Esc)")`
- Line 881: `self._style_button.setToolTip("样式（颜色 / 线宽）")` → `self._style_button.setToolTip("样式（颜色 / 线宽） · [ ] 调线宽")`
- Line 950: `undo_btn.setToolTip("撤销")` → `undo_btn.setToolTip("撤销 (Ctrl+Z)")`
- Line 962: `redo_btn.setToolTip("重做")` → `redo_btn.setToolTip("重做 (Ctrl+Y)")`

(The eight tool buttons already append their single-key shortcut at line 930 — leave that alone.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/ui/test_markup_editor.py::test_toolbar_buttons_expose_their_shortcuts -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): show Esc/Ctrl+Z/Ctrl+Y/[] shortcuts in button tooltips"
```

---

### Task 3: Markup editor — first-open discovery toast

**Files:**
- Modify: `mf4_analyzer/ui/markup/editor.py` (import line 6; `__init__` ~line 587; `showEvent` lines 612-616; add two methods)
- Test: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ui/test_markup_editor.py`. Add these imports at the top of the file if absent: `from PyQt5.QtCore import QSettings` (extend the existing `from PyQt5.QtCore import ...` line) and `from mf4_analyzer.ui import hints`. `QApplication` is already imported.

```python
def _temp_hint_settings(tmp_path):
    return QSettings(str(tmp_path / "markup-hints.ini"), QSettings.IniFormat)


def test_first_open_shows_capability_toast_and_retires_it(qtbot, tmp_path):
    settings = _temp_hint_settings(tmp_path)
    assert "markup.capabilities" not in hints.load_discovered(settings)

    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_hint_settings(settings)
    editor.show()
    QApplication.processEvents()

    assert editor._hint_toast is not None
    assert editor._hint_toast.isVisible()
    assert "markup.capabilities" in hints.load_discovered(settings)


def test_capability_toast_not_shown_when_already_discovered(qtbot, tmp_path):
    settings = _temp_hint_settings(tmp_path)
    hints.mark_discovered(settings, "markup.capabilities")

    editor = MarkupEditor(_pixmap())
    qtbot.addWidget(editor)
    editor.set_hint_settings(settings)
    editor.show()
    QApplication.processEvents()

    assert editor._hint_toast is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/ui/test_markup_editor.py -k capability_toast -v`
Expected: FAIL — `MarkupEditor` has no `set_hint_settings` / `_hint_toast` attribute (`AttributeError`).

- [ ] **Step 3: Import `QSettings` in the editor**

In `mf4_analyzer/ui/markup/editor.py`, line 6, add `QSettings`:

```python
from PyQt5.QtCore import QLineF, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer
```

- [ ] **Step 4: Add hint state to `__init__`**

In `MarkupEditor.__init__`, immediately after `self._auto_fit = True` (line 587), add:

```python
        self._hint_settings = QSettings()
        self._hint_toast = None
        self._capability_hint_shown = False
```

- [ ] **Step 5: Trigger the hint from `showEvent` and add the helper methods**

Replace `showEvent` (lines 612-616) and add the two methods directly after it:

```python
    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_fit_done:
            self._initial_fit_done = True
            QTimer.singleShot(0, self.fit_to_window)
        self._maybe_show_capability_hint()

    def set_hint_settings(self, settings):
        """Inject a QSettings store (tests pass a temp INI)."""
        self._hint_settings = settings

    def _maybe_show_capability_hint(self):
        if self._capability_hint_shown:
            return
        self._capability_hint_shown = True
        from .. import hints
        state = hints.HintState(
            discovered=hints.load_discovered(self._hint_settings)
        )
        hint = hints.discovery_hint(state, scope="markup")
        if hint is None:
            return
        if self._hint_toast is None:
            from ..widgets import Toast
            self._hint_toast = Toast(self)
        self._hint_toast.show_message(hint.text, level="info")
        hints.mark_discovered(self._hint_settings, hint.id)
```

(The `hints` and `Toast` imports are deferred inside the method to mirror the lazy `from .widgets import Toast` pattern in `main_window.py` and avoid import-time cycles.)

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `python -m pytest tests/ui/test_markup_editor.py -k capability_toast -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Run the full markup + hints suites**

Run: `python -m pytest tests/ui/test_markup_editor.py tests/ui/test_hints.py -v`
Expected: PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/markup/editor.py tests/ui/test_markup_editor.py
git commit -m "feat(markup): show one-shot capability hint toast on first editor open"
```

---

### Task 4: Inventory doc note + final cross-suite verification

**Files:**
- Modify: `docs/analyzer/ui-hints.md` (the "Current State" table)

- [ ] **Step 1: Record the new consumer in the inventory**

In `docs/analyzer/ui-hints.md`, under the `## Current State` table, add this row (markup is now a live hint consumer, no longer chart-only):

```markdown
| Markup editor capability card | `markup/editor.py` `_maybe_show_capability_hint` | One-shot `markup.capabilities` toast on first open (scope="markup"); retires via shared `chartHints/discovered`. |
```

- [ ] **Step 2: Run the whole UI test directory to confirm no regressions**

Run: `python -m pytest tests/ui/ -q`
Expected: PASS — including `test_hints.py::test_design_curated_ids_exist_in_registry` (the spec keeps `markup.capabilities` in prose, not a curated table, so the doc-sync test does not require it and stays green).

- [ ] **Step 3: Commit**

```bash
git add docs/analyzer/ui-hints.md
git commit -m "docs: note markup editor as a live hint consumer"
```

---

## Self-Review

**Spec coverage:**
- Registry `scope` field + chart-scope default → Task 1 (steps 3, 5).
- Reshape `markup.capabilities` (scope/ship/text) → Task 1 (step 4).
- Markup editor first-open toast (showEvent, persisted retire, `Toast(self)`) → Task 3.
- Tooltip gaps undo/redo/close/style → Task 2.
- Tests: hints scope isolation → Task 1; editor toast one-shot + tooltips → Tasks 2-3; doc-sync stays green → Tasks 1 & 4.
- Acceptance "chart discovery queue unchanged" → Task 1 step 7 + `test_chart_discovery_queue_excludes_markup_scope`.

**Placeholder scan:** none — every code/test step shows full content.

**Type consistency:** `discovery_hint(state, scope=...)` / `context_hints(state, scope=...)` signatures match between definition (Task 1) and call site (Task 3 `_maybe_show_capability_hint`). `set_hint_settings`, `_hint_toast`, `_capability_hint_shown` defined in Task 3 `__init__` and used consistently in the same task and in Task 3 tests. Button objectNames (`markupCloseButton`/`markupUndoButton`/`markupRedoButton`/`markupStyleButton`) match the editor source.
