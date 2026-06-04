# View Tabs Bottom Dock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move time-domain View tabs to a full-width bottom dock using layout option A and Workbench Rail style 2.

**Architecture:** `ChartStack` owns one shared time-domain bottom dock below the stacked chart area. The time splitter contains only the primary and secondary chart panes, so side-by-side plot heights stay equal. `ViewTabBar` remains the tab UI component, but it is parented to the shared dock instead of a single `TimeChartCard`.

**Tech Stack:** PyQt5 widgets/QSS, pytest-qt UI tests.

---

### Task 1: Pin The Shared Dock Contract

**Files:**
- Modify: `tests/ui/test_view_tabbar_mount.py`
- Modify: `tests/ui/test_split_container.py`

- [ ] **Step 1: Write failing tests**

Update tests to assert `ChartStack.attach_view_tabbar()` parents the tab bar to a `QFrame#timeViewBottomDock`, keeps it visible only in time mode, and does not mount it inside `_time_card`.

- [ ] **Step 2: Run tests to verify red**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_tabbar_mount.py tests\ui\test_split_container.py -q`

Expected: failures because the current implementation mounts the tab bar in `_time_card` above `_hint_bar`.

### Task 2: Implement The Dock

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`

- [ ] **Step 1: Move bottom hint ownership**

Create `ChartStack._time_bottom_dock`, `ChartStack._time_hint_bar`, and centered hint labels below `self.stack`.

- [ ] **Step 2: Mount ViewTabBar into the dock**

Make `attach_view_tabbar()` create `ViewTabBar(manager, self._time_bottom_dock)` and insert it above the centered hint row.

- [ ] **Step 3: Remove card-level tab mounting dependency**

Keep `TimeChartCard.view_tabbar` for compatibility but leave it `None`; do not insert the tab bar into card layouts.

### Task 3: Apply Workbench Rail Styling

**Files:**
- Modify: `mf4_analyzer/ui/view_tabbar.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`

- [ ] **Step 1: Add stable object names/properties**

Keep `#viewTabBar`, `#viewTabs`, and `#viewTabPlus`; set fixed dock-friendly height and let the tab rail expand horizontally.

- [ ] **Step 2: Add QSS for style 2**

Use a quiet full-width rail, transparent inactive tabs, light-blue selected tab, and a compact rounded plus button.

### Task 4: Verify

**Files:**
- Test: `tests/ui/test_view_tabbar_mount.py`
- Test: `tests/ui/test_split_container.py`
- Test: `tests/ui/test_view_tabbar.py`

- [ ] **Step 1: Run targeted tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ui\test_view_tabbar_mount.py tests\ui\test_split_container.py tests\ui\test_view_tabbar.py -q`

- [ ] **Step 2: Run a focused visual smoke if available**

Run the existing view-tab or split smoke script/test that exercises the time-domain tab bar and side-by-side mode.
