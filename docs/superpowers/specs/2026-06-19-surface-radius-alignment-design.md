# TraceLab Surface Radius And Layer Alignment — Design Spec

**Date:** 2026-06-19
**Status:** User-approved refinement, ready for implementation
**Scope owner:** PyQt shell widgets + QSS surface layering
**Base spec:** `docs/superpowers/specs/2026-06-19-surface-system-redesign-design.md`
**User-approved decisions:**
- Compact radius scale: `8 / 7 / 6 / 5`
- Bottom-right version affordance: transparent icon + text, not a nested rounded button

---

## 1. Problem Statement

The porcelain tray direction is correct, but the current implementation still
has five visible polish failures:

1. Rounded corners are too large for a dense desktop analysis tool.
2. Several rounded surfaces lose part of their line/border because child
   widgets or scroll viewports repaint opaque rectangles over the parent shell.
3. The center and right panels have places where the lowest visible layer does
   not read as a rounded outer surface.
4. The left panel has the same class of missing rounded lowest layer at the
   bottom/inner-card boundary.
5. The `v7.0` update affordance is a rounded child button pressed against a
   rounded bottom bar, so two radii overlap instead of aligning.

These are one system-level issue: radius, inset, and background ownership are
not yet consistent across nested Qt widgets.

## 2. Radius Tokens

Use this compact radius scale for the porcelain shell. Do not keep the current
large `13px`, `12px`, `11px`, or `10px` radii on these shell surfaces.

| Token | Radius | Applies To |
|---|---:|---|
| `surface-bar-radius` | `8px` | topbar and bottom status surface |
| `surface-panel-radius` | `7px` | FileNavigator, ChartStack, Inspector |
| `surface-card-radius` | `6px` | inner file/channel/chart/inspector cards |
| `surface-control-radius` | `5px` | compact child controls near a surface edge |

Only keep larger radii where the component is outside this surface system, such
as popups/menus or legacy unrelated dialogs.

## 3. Layer Ownership Contract

Every visible rounded surface has exactly one widget responsible for its outer
background, border, and radius.

| Layer | Paint Owner | Rule |
|---|---|---|
| App tray | `QWidget#centralTray` | Paints porcelain tray only; no border/radius |
| Top surface | `Toolbar#surfaceTopBar` plus `Toolbar.paintEvent` | White, 1px edge, radius `8px` |
| Bottom surface | `QStatusBar#surfaceStatusBar` | White, 1px edge, radius `8px` |
| Left panel | `FileNavigator` | White, 1px edge, radius `7px` |
| Center panel | `ChartStack` | White, 1px edge, radius `7px` |
| Right panel | `Inspector` | White, 1px edge, radius `7px` |
| Inner cards | named cards only | White/card fill, radius `6px`, inset from parent |

Generic descendants must not repaint a full rectangular white background at the
outer edge. The global `QWidget { background-color: #ffffff; }` remains a risk:
if a child reaches a rounded parent's edge, explicitly make that child
transparent or inset it.

## 4. Inset And Alignment Contract

Qt does not clip child widgets to a parent's `border-radius`. Therefore rounded
parent surfaces need a real content inset.

Rules:

1. A child that paints an opaque background may not touch a rounded parent's
   edge.
2. Main panel content needs at least `3px` inset from the outer shell on any
   side where the child paints.
3. Inner card radius must be smaller than its parent radius. Use `6px` inside a
   `7px` panel only when there is visible inset; otherwise make the child
   transparent instead of rounded.
4. Edge-aligned status/version controls must either be transparent or inset
   enough for their radius center to visually align with the parent radius.
5. Do not add broad margins that disturb the chart toolbar geometry. Prefer
   making backing containers transparent or adding localized bottom/status
   insets.

## 5. Version Affordance Contract

The bottom-right update affordance remains clickable and keeps the cloud icon
plus `v7.0` text, but it should not read as a second rounded pill sitting on the
bottom bar.

Implementation rules:

- Give the widget a stable object name: `surfaceVersionButton`.
- Remove the inline stylesheet that paints it like a button.
- Default state: transparent background, no border.
- Hover state: very light wash is allowed, radius `5px`.
- It must be inset from the bottom/status surface edge; no corner overlap with
  `QStatusBar#surfaceStatusBar`.

## 6. Specific Areas To Fix

### 6.1 Top Bar

`Toolbar#surfaceTopBar` QSS and `Toolbar.paintEvent` must use the same `8px`
radius. A mismatch will leave aliasing or a phantom larger curve.

### 6.2 Left Panel

`FileNavigator` keeps the outer shell. The file scroll card and channel card
are inner cards, radius `6px`, with enough inset so their borders do not hide
the outer shell. Scroll viewport/holder widgets should not repaint square
corners over the scroll card.

### 6.3 Center Panel

`ChartStack` keeps the outer shell. The chart toolbar remains flat and
transparent. Bottom tab/hint/status areas must not cover the center panel's
outer rounded corners. Do not change splitter sizes or analysis plotting
geometry.

### 6.4 Right Panel

`Inspector` keeps the outer shell. `QScrollArea#inspectorScroll` and its host
widgets must not cover the panel border/radius. Inspector signal and parameter
cards use radius `6px` and stay visually inset inside the panel body.

## 7. Verification Contract

Must run all of:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_surface_layering.py \
  tests/ui/test_toolbar.py \
  tests/ui/test_file_navigator.py \
  tests/ui/test_channel_widget.py \
  tests/ui/test_chart_stack.py \
  tests/ui/test_inspector.py \
  tests/ui/test_view_tabbar.py \
  tests/ui/test_view_switch_integration.py \
  tests/ui/test_update_indicator.py \
  -q
```

Also regenerate representative screenshots for all four modes under
`docs/surface-redesign-after/` and inspect at least the Order-mode screenshot,
because the user screenshot that exposed these issues is Order mode.

The existing rounded-corner alpha test must keep passing, and new tests should
cover the compact radius tokens plus the transparent version affordance.

## 8. Out Of Scope

- No FFT, FFT-vs-Time, Order, pyqtgraph, cache, file-load, or numeric changes.
- No splitter size changes.
- No new shadow system.
- No broad rewrite of global `QWidget` styling in this pass.
