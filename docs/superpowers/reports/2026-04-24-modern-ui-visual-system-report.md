# Modern UI Visual System · Planning Report

**Date:** 2026-04-24
**Trigger:** User requested a modern/high-end UI direction, asked whether it can be implemented in Python/PyQt, then asked to preserve the direction in agents and prepare a superpowers-style plan/report for later agent execution.
**Status:** Implemented in current workspace; focused UI tests and full test suite pass.

---

## 1. Outputs Created

- `docs/ui-design-showcase.html` — static visual showcase with four selectable design directions.
- `.claude/agents/pyqt-ui-engineer.md` — persistent UI design direction added.
- `.claude/agents/squad-orchestrator.md` — persistent UI routing memory added.
- `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md` — executable implementation plan.
- `docs/superpowers/reports/2026-04-24-modern-ui-visual-system-report.md` — this planning report.
- `docs/lessons-learned/orchestrator/decompositions/2026-04-24-modern-ui-visual-system.md` — agent decomposition audit.

---

## 2. Design Decision

The recommended default direction is **Precision Light**.

Rationale:

- It best fits a professional engineering/data-analysis tool.
- It improves hierarchy and polish without making the application decorative.
- It is feasible in PyQt5 with existing `style.qss`, `QPainter` icons, and current widget topology.
- It avoids high-cost CSS-like glass/blur effects that are awkward in PyQt5.

Other showcase directions remain available as later optional themes:

- `Graphite Lab` — useful for dark mode / demonstration.
- `Aero Glass` — visually premium but higher implementation risk in PyQt5.
- `Signal Studio` — calmer instrumentation style for production environments.

---

## 3. Agent Memory Changes

### `pyqt-ui-engineer`

Added a `Persistent UI design direction` section.

Key memory:

- Default visual direction is `Precision Light`.
- Use `docs/ui-design-showcase.html` as the reference.
- Preserve the three-pane topology.
- Use QSS/palette tokens.
- Replace emoji affordances with consistent line icons.
- Keep UI chrome colors separate from data-series colors.
- Treat the other themes as optional later work.

### `squad-orchestrator`

Added a `Persistent UI design routing` section.

Key routing:

- UI modernization, style, color, icons, toolbar, pane, Inspector, drawer, chart workspace, cursor pill, stats strip, and QSS tasks route to `pyqt-ui-engineer`.
- Dispatch briefs should include the Precision Light project-level style memory.
- Graphite/Aero/Signal themes are not default unless selected by the user.

No changes were made to `signal-processing-expert` or `refactor-architect` because this memory belongs to UI routing and execution.

---

## 4. Implementation Strategy

The plan deliberately serializes the UI work:

1. QSS token baseline.
2. Icon system and toolbar.
3. Left pane polish.
4. Chart workspace polish.
5. Inspector and drawer polish.
6. Final verification.

This avoids known same-file UI collisions from the prior drawer work. In particular, `widgets.py`, drawer shared files, and `main_window.py` should not be touched by parallel UI subtasks unless the write ownership is explicitly split.

---

## 5. Scope Boundaries

In scope:

- PyQt/QSS styling.
- Programmatic icon drawing.
- Visual hierarchy and layout polish.
- Matplotlib visual styling.
- UI smoke tests and manual verification.

Out of scope:

- FFT/order numerical changes.
- Data loader changes.
- Channel math changes.
- New dependencies.
- True glass/backdrop blur as a v1 requirement.
- Replacing PyQt with web tech.

---

## 6. Verification Plan

Each implementation wave should run focused tests:

- Toolbar: `python -m pytest tests/ui/test_toolbar.py -q`
- Navigator: `python -m pytest tests/ui/test_file_navigator.py -q`
- Chart stack: `python -m pytest tests/ui/test_chart_stack.py -q`
- Inspector/drawers: `python -m pytest tests/ui/test_inspector.py tests/ui/test_drawers.py -q`

Final verification:

```bash
python -m pytest tests/ui -q
python -m pytest tests -q
```

Manual desktop smoke is required before calling the visual upgrade complete.

---

## 7. Risks

- PyQt5 cannot cheaply reproduce CSS `backdrop-filter`; Aero Glass must stay optional.
- Matplotlib toolbar icons may remain visually inconsistent unless replaced or heavily styled.
- Current code has mojibake-like Chinese string artifacts in several files; visual polish may expose them more clearly, but fixing encoding/text content is a separate task unless explicitly included.
- Prior lessons show parallel drawer/shared-file edits can create commit collisions; this plan avoids parallel UI waves.
- Headless tests do not prove visual quality. Human screenshot/manual review is still required.

---

## 8. Handoff

Implementation was executed against the current PyQt codebase using the plan's `pyqt-ui-engineer` ownership boundaries. Future refinements should continue from the same plan, starting with real desktop visual review rather than another structural pass.

Primary follow-up:

- Run the app in a real desktop session with representative MF4/CSV/Excel files.
- Compare against `docs/ui-design-showcase.html`, especially the Precision Light mockup.
- Tweak spacing/contrast from screenshots if needed.

---

## 9. Execution Result

Implemented:

- Rewrote `mf4_analyzer/ui/style.qss` around Precision Light tokens.
- Extended `mf4_analyzer/ui/icons.py` with a consistent PyQt-native line-icon set.
- Rebuilt `Toolbar` into a three-zone command bar with icon/text actions and icon-only chart tools.
- Polished `FileNavigator` rows with subtle active state, count badge, close/menu icons, and metadata hierarchy.
- Added channel color swatches and cleaner channel search/action styling.
- Updated ChartStack card spacing and toolbar sizing.
- Aligned matplotlib figure/axes/grid/tick/remark styling with the new visual system.
- Updated Inspector action/choice button roles and removed play/clock emoji affordances from primary controls.
- Added drawer/sheet/popover object names and action roles for unified QSS styling.
- Updated `FILE_PALETTES` to a data-series color set that stays distinct from UI chrome blue.

Files changed by the implementation:

- `mf4_analyzer/_palette.py`
- `mf4_analyzer/ui/style.qss`
- `mf4_analyzer/ui/icons.py`
- `mf4_analyzer/ui/toolbar.py`
- `mf4_analyzer/ui/file_navigator.py`
- `mf4_analyzer/ui/widgets.py`
- `mf4_analyzer/ui/chart_stack.py`
- `mf4_analyzer/ui/canvases.py`
- `mf4_analyzer/ui/inspector_sections.py`
- `mf4_analyzer/ui/drawers/channel_editor_drawer.py`
- `mf4_analyzer/ui/drawers/export_sheet.py`
- `mf4_analyzer/ui/drawers/axis_lock_popover.py`
- `mf4_analyzer/ui/drawers/rebuild_time_popover.py`

Verification:

```bash
.\.venv\Scripts\python.exe -c "from mf4_analyzer.app import main; print('ok')"
# ok

.\.venv\Scripts\python.exe -m pytest tests/ui/test_toolbar.py tests/ui/test_file_navigator.py tests/ui/test_chart_stack.py tests/ui/test_inspector.py tests/ui/test_drawers.py -q
# 37 passed

.\.venv\Scripts\python.exe -m pytest tests -q
# 53 passed
```

Note: the full test suite needed to run outside the sandbox because pytest/pytest-qt could not access Windows temp/cache paths from the sandbox. The same suite passed once run with normal filesystem access.

Manual real-desktop visual review is still pending.

---

## 10. Screenshot Feedback Fixes

After visual review of the updated UI screenshot, a follow-up polish pass addressed five concrete issues:

1. Active file row contrast was too strong. The selected file row now uses a much lighter blue-tinted surface with a narrow accent indicator.
2. Right Inspector controls could stack/clip when the window narrows. Persistent and contextual forms now use `QFormLayout` growth policies, expanding fields, and wider pane minimums (`navigator=220`, `inspector=280`).
3. Spinbox/combobox button chrome looked too plain. QSS now styles dropdown and spinbox sub-buttons with subtle separated surfaces and hover states.
4. FFT amplitude axis text rendered poorly as a rotated Chinese label. FFT/order amplitude y-axis labels now use stable English labels (`Amplitude`, `PSD (dB)`) with label padding.
5. Time-domain y-axis titles could be clipped. Time-domain labels now use ellipsis compaction, extra label padding, and larger subplot margins.

Verification after this pass:

```bash
.\.venv\Scripts\python.exe -m pytest tests -q
# 53 passed
```

Follow-up after subsequent layout review:

- Latest decision: keep compact form rows and solve narrow-window overflow with a dedicated vertical `QScrollArea` on the right Inspector.
- The left navigator now uses a vertical splitter between the file list and channel tree. The file list gets a larger initial height and can be resized by dragging the divider, so multiple loaded files are visible before the channel tree.
- Removed the QSS triangle-arrow hack that rendered as square/dot artifacts in spinbox and combobox controls.

Verification:

```bash
.\.venv\Scripts\python.exe -m pytest tests -q
# 53 passed
```
