# TraceLab Porcelain Surface Layering — Design Spec

**Date:** 2026-06-19
**Status:** Approved visual direction, ready for implementation
**Scope owner:** PyQt UI shell + QSS surface system
**Primary reference:** `docs/surface-layering-options.html` with default `data-theme="porcelain"`
**User-selected direction:** `B 更浅: 瓷白托盘`

---

## 1. Decision

Implement the TraceLab shell as a layered surface system:

1. A quiet **porcelain tray** behind the app surfaces.
2. A long rounded **white topbar** and a long rounded **white bottombar**.
3. Three rounded white main panels: file navigator, chart stack, inspector.
4. Only the meaningful content groups inside those panels become smaller floating cards.

This replaces the current partially-rounded result where gray tray bands remain visible as cheap strips, rounded corners reveal unwanted backing color, the global top/bottom bars still read as flat gray bands, and the chart toolbar was incorrectly promoted into a bordered rounded inner card.

## 2. Visual Contract

The UI should read like this:

```text
porcelain tray
┌──────────────────────────────── top white rounded surface ────────────────────────────────┐
│ Open / Save / Batch              mode tabs                         brand / panel toggle    │
└────────────────────────────────────────────────────────────────────────────────────────────┘

┌ file panel ┐  ┌──────────────────────── chart panel ────────────────────────┐  ┌ inspector panel ┐
│ file card  │  │ flat chart toolbar, no card chrome                           │  │ title            │
│            │  │ ┌──────────────────── canvas card ────────────────────────┐ │  │ ┌ form card ┐    │
│ channel    │  │ │                                                            │ │  │ └──────────┘    │
│ card       │  │ └────────────────────────────────────────────────────────────┘ │  │ ┌ form card ┐    │
└────────────┘  │ ┌──────── view/status inner bar ─────────────────────────────┐ │  │ └──────────┘    │
                └───────────────────────────────────────────────────────────────┘  └─────────────────┘

┌──────────────────────────────── bottom white rounded surface ─────────────────────────────┐
│ mode hint / status text                                                        version    │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 3. Tokens

Use one neutral palette. Do not introduce a new hue family.

| Token | Hex | Role |
|---|---:|---|
| `tray` | `#f2f4f7` | QMainWindow background, central tray, splitter gaps, outside rounded surfaces |
| `tray-edge` | `#dbe2eb` | topbar/bottombar/panel outlines |
| `panel` | `#ffffff` | topbar, bottombar, FileNavigator, ChartStack, Inspector |
| `panel-soft` | `#fafbfc` | internal panel bodies where a white inner card needs contrast |
| `hairline` | `#eef2f7` | soft separators inside one card |
| `accent` | `#1769e0` | primary actions, selected tabs, links, checked controls |
| `accent-wash` | `#e8efff` | selected/checked fill |
| `ink` | `#111827` | primary text |
| `muted` | `#64748b` | secondary text |

Qt note: QSS has no real `box-shadow`. v1 uses radius + border + tray/panel contrast. Do not add `QGraphicsDropShadowEffect` in this pass unless the final rendered screenshot proves the design is still flat after the token pass.

## 4. Geometry Contract

These are the current approved values from the HTML sketch and earlier live tuning:

| Area | Target |
|---|---|
| Topbar height | `50px` fixed visual height |
| Bottombar height | `40px` fixed visual height |
| Top/work/bottom vertical spacing | `5px` |
| Outer tray margin | keep `5px` in `MainWindow._init_ui` |
| Main splitter handle/gap | keep `3px` hit area, tray-colored |
| Main panel radius | `10px` |
| Top/bottom bar radius | `13px` |
| Main splitter sizes | keep `[250, 900, 288]` |
| Inspector content width | keep `_INSPECTOR_CONTENT_MAX_WIDTH = 272` |

Do not change panel min widths, signal-processing code, pyqtgraph numeric logic, file loading, or analysis cache behavior.

## 5. Required Implementation Structure

### Phase 1 — Shell Surfaces

Create the correct app shell before tuning inner widgets.

- `QMainWindow` and `QWidget#centralTray` paint the porcelain tray.
- `Toolbar` paints a white rounded top surface, fixed to 50px.
- The status area remains a real `QStatusBar` instance for API compatibility, but is displayed as a bottom white rounded surface inside the central tray, fixed to 40px.
- `self.statusBar.showMessage`, `currentMessage`, `clearMessage`, `insertPermanentWidget`, `addPermanentWidget`, and `removeWidget` must keep working.
- Do not replace `self.statusBar` with a plain `QWidget`.
- This app's existing public contract is the `self.statusBar` attribute. `MainWindow.statusBar()` callable compatibility is not a current contract because the attribute already shadows the inherited `QMainWindow.statusBar` method.

### Phase 2 — Main Panels And Inner Floating Surfaces

Make the three panels the primary surfaces. Make only meaningful internal groups float.

- `FileNavigator`, `ChartStack`, and `Inspector` stay rounded white panels.
- `fileScroll` and `MultiFileChannelWidget` become left-panel inner cards.
- Inspector signal/params cards stay white inner cards with neutral borders. No resting green/blue backgrounds.
- Chart canvas remains the dominant inner surface.
- `QWidget#chartToolbar` / `QToolBar#chartToolbar` must have no border, no radius, no white-card background, and no bottom divider. It is a flat tool row inside the chart panel.
- `QWidget#viewTabBar` and `QFrame#chartHintBar` remain shared chrome, not parent-specific to TimeDomain.

### Phase 3 — Cleanup, Tests, And Render Verification

Clean up duplicate QSS overrides and prove the result visually.

- Remove or consolidate tail-end QSS overrides that fight earlier rules, especially duplicate `QStatusBar`, `chartHintBar`, `viewTabBar`, and `centralTray` blocks.
- Add focused tests for surface owner widgets and QSS selectors.
- Add or run a rendered corner/pixel check for rounded shell/panel surfaces.
- Capture rendered after screenshots for Time, FFT, FFT vs Time, and Order.

## 6. Acceptance Criteria

1. The default visual theme is porcelain tray, not cool gray tray.
2. Top and bottom are long white rounded floating surfaces.
3. The three main panels are rounded white cards separated by porcelain tray gaps.
4. Rounded corners do not show an opaque rectangular backing.
5. Chart toolbar has no card border/radius/background of its own.
6. Left file/channel areas and right Inspector form groups read as inner floating surfaces.
7. Blue appears only for interaction and selection, not as resting panel/card background.
8. All existing status-bar callers still work against `self.statusBar`.
9. The View tab bar shared QSS contract still applies outside TimeDomain.
10. Focused UI tests and rendered screenshots are collected before calling the work done.

## 7. Test / Verification Requirements

Run at minimum:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_toolbar.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_main_window_smoke.py::test_inspector_default_slot_matches_content_width_under_stylesheet \
  -q
```

Also run a rendered screenshot or probe for all four modes. Screenshot-only QSS proof is not enough; verify corner pixels or actual rendered corners.

## 8. Risks And Guardrails

- **Status bar risk:** `self.statusBar` is heavily used as a `QStatusBar`. Keep the object type and attribute API; do not introduce a second status bar.
- **QSS override risk:** tail rules can silently override earlier surface rules. The cleanup phase must grep for duplicate selectors after implementation.
- **Rounded-corner risk:** QSS `border-radius` alone is not proof. Render/pixel-check the result.
- **Mockup drift risk:** `docs/surface-layering-options.html` is the visual contract, but the live PyQt app is the source of truth before closeout.
- **Dirty worktree risk:** do not revert or commit unrelated files. Agents must list touched paths and leave commits to an explicit user decision.
