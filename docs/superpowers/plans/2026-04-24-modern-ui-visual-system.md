# Modern UI Visual System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing PyQt5 three-pane MF4 Analyzer UI from a plain/default-widget look into a modern professional engineering/data-analysis workbench, using the `Precision Light` direction from `docs/ui-design-showcase.html` as the default visual system.

**Scope:** Visual system, QSS, icons, pane hierarchy, chart workspace polish, Inspector polish, and verification. No signal-processing formulas, loaders, channel math, FFT/order algorithms, or feature removals.

**Primary owner:** `pyqt-ui-engineer`

**Support owner:** `refactor-architect` only if a later implementation requires module moves or import-boundary changes. This plan currently does not require refactor ownership.

**Non-owner:** `signal-processing-expert` is not expected to participate; this is surface/UI work.

**Design reference:** `docs/ui-design-showcase.html`

**Agent memory:** `.claude/agents/pyqt-ui-engineer.md` and `.claude/agents/squad-orchestrator.md` now record `Precision Light` as the persistent default UI direction.

---

## 0. Design Contract

Future UI work must preserve these constraints:

- Existing three-pane topology stays: left file/channel navigator, center chart workspace, right Inspector.
- Default theme is **Precision Light**.
- The app should feel like a professional engineering workbench, not a decorative dashboard.
- Use QSS/palette tokens instead of scattered hard-coded colors.
- Replace emoji affordances with a consistent line-icon language.
- Keep UI chrome colors separate from chart/data colors.
- Keep density compact and readable; avoid oversized hero-like UI patterns.
- Do not introduce new dependencies unless explicitly approved.
- Avoid v1 reliance on true glass/backdrop blur effects; PyQt5 cannot match CSS `backdrop-filter` cheaply.

Target visual tokens:

```text
App background      #F1F5F9
Pane background     #F8FAFC
Surface             #FFFFFF
Border subtle       #D7DEE8
Border strong       #CBD5E1
Text primary        #111827
Text secondary      #4B5563
Text muted          #64748B
Primary blue        #1769E0
Success green       #059669
Warning amber       #D97706
Danger red          #DC2626
```

Target data colors:

```text
#2563EB, #059669, #DC2626, #EA580C,
#0891B2, #7C3AED, #BE123C, #64748B
```

---

## File Structure

**Reference / documentation already added:**

- `docs/ui-design-showcase.html`
- `.claude/agents/pyqt-ui-engineer.md`
- `.claude/agents/squad-orchestrator.md`

**Likely modified files during implementation:**

- `mf4_analyzer/ui/style.qss`
- `mf4_analyzer/ui/icons.py`
- `mf4_analyzer/ui/toolbar.py`
- `mf4_analyzer/ui/file_navigator.py`
- `mf4_analyzer/ui/widgets.py`
- `mf4_analyzer/ui/chart_stack.py`
- `mf4_analyzer/ui/canvases.py`
- `mf4_analyzer/ui/inspector.py`
- `mf4_analyzer/ui/inspector_sections.py`
- `mf4_analyzer/ui/drawers/*.py`
- `tests/ui/*.py` as needed for UI smoke/contract coverage

**Not touched:**

- `mf4_analyzer/signal/**`
- `mf4_analyzer/io/**`
- `mf4_analyzer/signal/channel_math.py`
- Numeric tests except incidental full-suite verification

---

## Phase 1: Theme Tokens and Baseline QSS

**Owner:** `pyqt-ui-engineer`

**Intent:** Make the whole app visually coherent before touching individual widgets.

**Files:**

- Modify: `mf4_analyzer/ui/style.qss`
- Optional modify: `mf4_analyzer/_palette.py`, `mf4_analyzer/_fonts.py`

- [ ] **Step 1.1: Audit current QSS selectors**

  Read `style.qss` and list selectors currently used by:

  - `Toolbar`
  - `FileNavigator`
  - `Inspector`
  - `ChartStack`
  - `StatsStrip`
  - `#fileRow`
  - `#cursorPill`

  Keep existing object names stable unless a new one is required for styling.

- [ ] **Step 1.2: Replace theme colors with Precision Light tokens**

  Rewrite the global QSS around the token set in this plan. Required coverage:

  - `QMainWindow`, `QWidget`
  - `QSplitter::handle`
  - `QPushButton`, `QToolButton`
  - `QLineEdit`, `QComboBox`, `QSpinBox`, `QDoubleSpinBox`
  - `QScrollArea`, `QScrollBar`
  - `QGroupBox` / section-like containers
  - `QStatusBar`

  Do not hard-code theme colors inside widget constructors if QSS can own them.

- [ ] **Step 1.3: Add semantic dynamic-property selectors**

  Prefer dynamic properties for roles such as:

  - `role="primary"`
  - `role="tool"`
  - `role="segmented"`
  - `state="active"`
  - `density="compact"`

  Keep this small. Do not create an over-large design system.

- [ ] **Step 1.4: Import smoke check**

  Run:

  ```bash
  python -c "from mf4_analyzer.app import main; print('ok')"
  ```

  Expected: `ok`.

- [ ] **Step 1.5: UI startup check**

  Start the app in a real desktop session if available:

  ```bash
  python "MF4 Data Analyzer V1.py"
  ```

  Verify:

  - Window opens.
  - No QSS parse warnings in console.
  - Toolbar, panes, status bar all use the new background/border system.

---

## Phase 2: Icon System and Toolbar Command Bar

**Owner:** `pyqt-ui-engineer`

**Intent:** Remove emoji/default-button look and establish the app command language.

**Files:**

- Modify: `mf4_analyzer/ui/icons.py`
- Modify: `mf4_analyzer/ui/toolbar.py`
- Optional modify: `tests/ui/test_toolbar.py`

- [ ] **Step 2.1: Extend `Icons` with required line icons**

  Add PyQt-native icon factories for:

  - add file
  - edit/sliders
  - export/download
  - time waveform
  - FFT bars
  - order grid/spectrum
  - crosshair/reset cursor
  - axis lock
  - close
  - kebab/menu if needed by navigator

  Icons should use shared colors and consistent stroke width.

- [ ] **Step 2.2: Remove emoji text from toolbar**

  Replace current labels such as `＋ 添加文件`, `🔧 编辑通道`, `📥 导出`, `🔒` with icon + text or icon-only controls:

  - Left group: add/edit/export, icon + text.
  - Center group: mode segmented, icon + short text.
  - Right group: cursor reset / axis lock, icon-only with tooltip.

- [ ] **Step 2.3: Rebuild toolbar spacing**

  Keep the command-bar grouping:

  ```text
  [data actions]      [time | FFT | order]      [chart tools]
  ```

  The center segmented control should remain visually centered when the window is wide.

- [ ] **Step 2.4: Preserve enabled-state matrix**

  Verify `Toolbar.set_enabled_for_mode(mode, has_file)` still implements:

  - edit/export disabled without files
  - cursor reset and axis lock only enabled in time mode with files

- [ ] **Step 2.5: Toolbar tests**

  Run:

  ```bash
  python -m pytest tests/ui/test_toolbar.py -q
  ```

---

## Phase 3: Left Pane File and Channel Hierarchy

**Owner:** `pyqt-ui-engineer`

**Intent:** Make the left pane readable and useful at high channel counts.

**Files:**

- Modify: `mf4_analyzer/ui/file_navigator.py`
- Modify: `mf4_analyzer/ui/widgets.py`
- Optional modify: `tests/ui/test_file_navigator.py`

- [ ] **Step 3.1: File row visual hierarchy**

  Update `_FileRow` styling and structure:

  - Active file: subtle tinted background + narrow left accent indicator.
  - Filename: primary text, ellipsized.
  - Metadata: secondary text.
  - Close button: line icon, low visual weight, visible on hover or quiet by default.

- [ ] **Step 3.2: Header and menu polish**

  Update the file header and kebab/menu affordance:

  - Header text stays compact.
  - Count badge uses muted chip styling.
  - Kebab menu uses line icon or consistent text fallback, not emoji.

- [ ] **Step 3.3: Channel search/action row**

  Style search and `All / None / Inv` as compact controls.

  Preserve existing behavior:

  - filter updates visible channels
  - All/None/Inv still emit `channels_changed`
  - `MAX_CHANNELS_WARNING` behavior is unchanged

- [ ] **Step 3.4: Channel color swatches**

  Ensure checked channel rows visually expose the line color that will be used in matplotlib.

  If current `MultiFileChannelWidget` already stores color in item foreground, prefer adding a small swatch widget/delegate rather than relying on text color alone.

- [ ] **Step 3.5: Navigator tests**

  Run:

  ```bash
  python -m pytest tests/ui/test_file_navigator.py -q
  ```

---

## Phase 4: Chart Workspace and Matplotlib Styling

**Owner:** `pyqt-ui-engineer`

**Intent:** Make the chart area the visual center of the application.

**Files:**

- Modify: `mf4_analyzer/ui/chart_stack.py`
- Modify: `mf4_analyzer/ui/canvases.py`
- Modify: `mf4_analyzer/ui/widgets.py`
- Optional modify: `tests/ui/test_chart_stack.py`

- [ ] **Step 4.1: Chart workspace surface**

  Update `ChartStack` / `_ChartCard` styling:

  - Quiet outer workspace background.
  - White chart card/surface.
  - Thin border around chart surface.
  - Slim navigation toolbar area.

- [ ] **Step 4.2: Matplotlib rc/style alignment**

  In canvas setup/plot paths, align:

  - figure facecolor
  - axes facecolor
  - grid line color/alpha
  - axis label color
  - tick color
  - title size/weight
  - default data color cycle

  Do not alter numeric data, sampling, FFT/order computation, or plotting semantics.

- [ ] **Step 4.3: Overlay axis readability**

  Keep overlay behavior intact, but reduce visual noise:

  - subtler right-side axis spine/tick colors
  - label colors match series colors
  - no saturated UI blue reused for every data line

- [ ] **Step 4.4: Cursor pill polish**

  Update `#cursorPill` style and placement if needed:

  - readable over chart surface
  - no dark/green terminal look
  - compact text and stable sizing

- [ ] **Step 4.5: Stats strip polish**

  Update `StatsStrip` to visually match the chart card footer:

  - muted background
  - compact metrics
  - no layout jump when no channels are selected

- [ ] **Step 4.6: Chart tests**

  Run:

  ```bash
  python -m pytest tests/ui/test_chart_stack.py -q
  ```

---

## Phase 5: Inspector and Drawer Polish

**Owner:** `pyqt-ui-engineer`

**Intent:** Make the right pane feel like a professional parameter inspector rather than stacked default group boxes.

**Files:**

- Modify: `mf4_analyzer/ui/inspector.py`
- Modify: `mf4_analyzer/ui/inspector_sections.py`
- Modify: `mf4_analyzer/ui/drawers/*.py`
- Optional modify: `tests/ui/test_inspector.py`, `tests/ui/test_drawers.py`

- [ ] **Step 5.1: Inspector section hierarchy**

  Update section styles:

  - compact headers
  - optional section icons from `Icons`
  - aligned label/control rows
  - one clear primary action per context

- [ ] **Step 5.2: Segmented controls**

  Keep plot mode and cursor mode controls as segmented choices.

  Ensure checked state, hover, disabled, and focus states are visually clear.

- [ ] **Step 5.3: Contextual action buttons**

  Make mode-specific actions visually consistent:

  - `绘图`
  - `计算 FFT`
  - `时间-阶次`
  - `转速-阶次`
  - `阶次跟踪`

  These should look like action buttons without dominating the pane.

- [ ] **Step 5.4: Drawer/sheet/popover surface**

  Align drawers with Precision Light:

  - consistent border
  - subtle shadow where applicable
  - compact title/header
  - consistent close affordance
  - no emoji-only action glyphs

  Avoid parallel agent edits across the same drawer shared files. If several drawer files need the same shared update, bundle the shared update into one subtask.

- [ ] **Step 5.5: Inspector/drawer tests**

  Run:

  ```bash
  python -m pytest tests/ui/test_inspector.py tests/ui/test_drawers.py -q
  ```

---

## Phase 6: End-to-End Verification

**Owner:** `pyqt-ui-engineer`

**Intent:** Confirm visual polish did not regress behavior.

- [ ] **Step 6.1: Run focused UI tests**

  ```bash
  python -m pytest tests/ui -q
  ```

- [ ] **Step 6.2: Run non-UI regression tests**

  ```bash
  python -m pytest tests -q
  ```

  If a known pre-existing flaky Qt paint issue appears, document the exact failing node and whether it passes alone.

- [ ] **Step 6.3: Manual desktop smoke test**

  In a real desktop session:

  - launch app
  - load MF4/CSV/Excel sample if available
  - switch files
  - select/deselect channels
  - plot time-domain subplot and overlay
  - move single cursor
  - switch dual cursor
  - use range selector
  - switch to FFT and back
  - open channel editor drawer
  - open export sheet
  - open axis lock popover

- [ ] **Step 6.4: Visual acceptance checklist**

  Confirm:

  - no emoji affordances remain in primary chrome
  - panes have clear hierarchy
  - chart area is visually primary
  - Inspector is compact and aligned
  - active file and active mode are clear
  - disabled states are clear
  - text does not overlap at 1100x640
  - graph colors are distinguishable from UI selection blue

---

## Agent Dispatch Plan

The follow-up execution should dispatch in this order:

| Wave | Subtask | Expert | Parallel? | Notes |
|---|---|---|---|---|
| 1 | `qss-token-baseline` | `pyqt-ui-engineer` | no | Establish tokens first; everything else depends on it. |
| 2 | `icon-system-and-toolbar` | `pyqt-ui-engineer` | no | Touches `icons.py` + `toolbar.py`; verify toolbar tests. |
| 3 | `left-pane-polish` | `pyqt-ui-engineer` | no | Touches `file_navigator.py` + `widgets.py`; avoid concurrent `widgets.py` edits. |
| 4 | `chart-workspace-polish` | `pyqt-ui-engineer` | no | Touches `chart_stack.py`, `canvases.py`, maybe `widgets.py`; run after Wave 3 because of `widgets.py`. |
| 5 | `inspector-and-drawers-polish` | `pyqt-ui-engineer` | no | Touches multiple shared UI files; serialize to avoid known same-file drawer collision. |
| 6 | `final-ui-verification` | `pyqt-ui-engineer` | no | Full test + manual desktop smoke report. |

No planned parallelism. This is intentional: previous lessons show same-expert, same-file UI polish tasks can race through `git add` and produce confusing commits.

---

## Specialist Briefs

Use these as dispatch prompts.

### Brief 1: `qss-token-baseline`

Implement Phase 1 of `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`. You are `pyqt-ui-engineer`. Use `Precision Light` from `docs/ui-design-showcase.html` as the visual baseline. Touch only QSS/palette/font UI files. Do not alter algorithms, loaders, or feature behavior. Return your normal JSON contract with `files_changed`, `ui_verified`, tests attempted, and notes.

### Brief 2: `icon-system-and-toolbar`

Implement Phase 2 of `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`. You are `pyqt-ui-engineer`. Extend `mf4_analyzer/ui/icons.py` with consistent line icons and update `toolbar.py` to remove emoji affordances while preserving signal/slot behavior and enabled-state rules. Run `tests/ui/test_toolbar.py`. Return the normal JSON contract.

### Brief 3: `left-pane-polish`

Implement Phase 3 of `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`. You are `pyqt-ui-engineer`. Polish `file_navigator.py` and channel-list visuals in `widgets.py` using the Precision Light direction. Preserve search, All/None/Inv, active file switching, close-all, and >8 warning behavior. Run `tests/ui/test_file_navigator.py`.

### Brief 4: `chart-workspace-polish`

Implement Phase 4 of `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`. You are `pyqt-ui-engineer`. Polish `chart_stack.py`, `canvases.py`, and `StatsStrip` visuals. Align matplotlib figure/axes/grid/tick/data colors with Precision Light without changing numeric computation or plot semantics. Run `tests/ui/test_chart_stack.py`.

### Brief 5: `inspector-and-drawers-polish`

Implement Phase 5 of `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`. You are `pyqt-ui-engineer`. Polish `inspector.py`, `inspector_sections.py`, and drawer/sheet/popover surfaces. Keep all existing signals, getters, and behavior. Do not split this into parallel drawer subtasks because prior lessons show shared-file drawer collisions. Run `tests/ui/test_inspector.py tests/ui/test_drawers.py`.

### Brief 6: `final-ui-verification`

Execute Phase 6 of `docs/superpowers/plans/2026-04-24-modern-ui-visual-system.md`. You are `pyqt-ui-engineer`. Run focused UI tests and full tests, then perform a real desktop smoke test if possible. Return a concise verification report listing pass/fail, any known flaky tests, and manual visual findings.

