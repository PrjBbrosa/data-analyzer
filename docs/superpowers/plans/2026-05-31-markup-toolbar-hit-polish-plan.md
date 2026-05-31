# Markup Toolbar Hit Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the markup editor toolbar layout and make secondary-edit handle hits forgiving enough that near-endpoint drags edit geometry instead of moving whole items.

**Architecture:** Keep all runtime changes inside `mf4_analyzer/ui/markup/editor.py`. Use focused pytest-qt tests in `tests/ui/test_markup_editor.py`; no new widgets or feature modules are needed.

**Tech Stack:** PyQt5 `QToolButton`, `QGridLayout`, `QGraphicsScene`, `QGraphicsItem`, pytest-qt offscreen tests.

---

## Files

- Modify: `mf4_analyzer/ui/markup/editor.py`
- Modify: `tests/ui/test_markup_editor.py`
- Create: `docs/superpowers/specs/2026-05-31-markup-toolbar-hit-polish-design.md`
- Create: `docs/superpowers/plans/2026-05-31-markup-toolbar-hit-polish-plan.md`

Unified test command:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

---

### Task 1: Expand handle hit zones before item-body moves

**Files:**
- Modify: `tests/ui/test_markup_editor.py`
- Modify: `mf4_analyzer/ui/markup/editor.py`

- [ ] **Step 1: Write failing tests**

Add tests that drag near, but not exactly on, line endpoints, rectangle corners, and scale handles. The expected behavior is geometry/scale change while item `pos()` stays unchanged.

- [ ] **Step 2: Run red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "near_handle or expanded_handle"
```

Expected: failures show near-handle drags are not routed to handles.

- [ ] **Step 3: Implement**

Add `_HANDLE_HIT_SCREEN_PX = 14.0` and update `handle_at()` to test a screen-normalized square centered on each handle. Pick the nearest containing handle when expanded zones overlap.

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

---

### Task 2: Lock hover cursor to the expanded handle zone

**Files:**
- Modify: `tests/ui/test_markup_editor.py`

- [ ] **Step 1: Write failing test**

Assert a point near a rectangle corner, inside the expanded handle zone but outside the old tiny handle rect, returns a resize cursor rather than `Qt.SizeAllCursor`.

- [ ] **Step 2: Run red/green**

The implementation from Task 1 should satisfy this once the test is added. Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "cursor or expanded_handle"
```

---

### Task 3: Rebuild toolbar into left / center / right groups

**Files:**
- Modify: `tests/ui/test_markup_editor.py`
- Modify: `mf4_analyzer/ui/markup/editor.py`

- [ ] **Step 1: Write failing tests**

Test for `markupToolbarLeftGroup`, `markupToolbarCenterGroup`, and `markupToolbarRightGroup`. Assert close is in the left group, style/tools/undo/redo are in the center group, and save/done are in the right group.

- [ ] **Step 2: Run red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "toolbar_layout or toolbar_close"
```

- [ ] **Step 3: Implement**

Use `QGridLayout` for the toolbar shell:

- column 0: left group, aligned left, stretch 1
- column 1: center group, aligned center
- column 2: right group, aligned right, stretch 1

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

---

### Task 4: Convert close / undo / redo to icon-only rectangular tool buttons

**Files:**
- Modify: `tests/ui/test_markup_editor.py`
- Modify: `mf4_analyzer/ui/markup/editor.py`

- [ ] **Step 1: Write failing tests**

Assert close, undo, and redo are `QToolButton`s with empty text and non-null icons. Assert clicking undo/redo still drives the undo stack.

- [ ] **Step 2: Run red**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q -k "undo_redo_icons or close_icon"
```

- [ ] **Step 3: Implement**

Replace close/undo/redo text `QPushButton`s with `QToolButton`s using qtawesome icons. Keep existing object names.

- [ ] **Step 4: Run green**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

---

### Task 5: Final verification

- [ ] **Step 1: Focused tests**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_markup_editor.py -q
```

- [ ] **Step 2: Real Qt smoke**

Run a short script without `QT_QPA_PLATFORM=offscreen` that opens `MarkupEditor`, verifies near-handle resize, grabs the widget, and closes it.

- [ ] **Step 3: Lessons gate**

```bash
/usr/bin/python3 scripts/lessons/check.py --status
```
