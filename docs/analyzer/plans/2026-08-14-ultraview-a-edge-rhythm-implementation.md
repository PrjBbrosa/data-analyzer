# UltraView A edge-rhythm implementation plan

Date: 2026-08-14

Status: IMPLEMENTED IN DEDICATED WORKTREE, UNCOMMITTED. The user selected
prototype A and authorized product-source edits on 2026-08-15. The implementation
lives only on `codex/ultraview-a-edge-rhythm`, based on `f3c540bd`.

Prototype: [2026-08-14-ultraview-control-alignment-options.html](../ui-prototypes/2026-08-14-ultraview-control-alignment-options.html), scheme A. The user then clarified that the left ToolRail must be content-height and vertically centred; it must not be a tall white column.

Related documents: [2026-08-14-ultraview-miro-narrow-rail-spec.md](../specs/2026-08-14-ultraview-miro-narrow-rail-spec.md) and [2026-08-14-ultraview-miro-narrow-rail-implementation.md](2026-08-14-ultraview-miro-narrow-rail-implementation.md) record the earlier B narrow-rail direction. This is an additive A geometry/polish plan. It must not silently rewrite those historical documents or restart their full UI migration.

## Execution record (2026-08-15)

- Implemented the pure A geometry in `floating_layout.py`; page geometry
  continues to consume that one Qt-free contract.
- Added pure-layout and actual-widget assertions for edge axes, content height,
  and vertical centring. The offscreen visual manifest now records and verifies
  those facts at 1280×800 and 800×560.
- Pruned only source-proven dead UltraView QSS selectors. Active Board menu and
  existing presentation-state styling remain unchanged.
- Final focused test batches: 153 passed (changed geometry/page/chrome/QSS
  parse) and 86 passed (viewport/mode/job-isolation/QSS-border/lambda guards).
  The offscreen visual verifier produced a post-change contact sheet and
  manifest. A separate pre-change baseline was not captured in this new
  worktree, and macOS Cocoa foreground/zero-compute acceptance remains
  unverified.

## 1. Outcome and non-goals

The outcome is a single, testable edge rhythm:

- BoardIsland, ToolRail, and StatusIsland share the left safe edge.
- GlobalIsland and NavigationIsland share the right safe edge.
- The top and bottom island rows share 40 px baselines.
- ToolRail is 48 px wide, uses only its content height, and is vertically centred in the safe stage.
- The card fit area remains to the right of the rail, so cards, zoom, free-grid, minimap, focus, and scrolling retain their current safe placement.

Do not:

- restore a permanent library, full toolbar, or full-height rail;
- implement C's card alignment/distribution controls;
- change signals, Board mutation paths, payload/digest, schema, PreviewStore, sidecar, compositor, analysis jobs, or zero-compute contracts;
- turn a visual patch into a fix bundle for unverified Board-menu, replacement, tray, or P3 issues;
- add per-card shadows, global QSS rewrites, or MainWindow state.

## 2. Current source evidence

| Owner | Current responsibility | A delta |
|---|---|---|
| `mf4_analyzer/ui/chart_stack/ultraview/floating_layout.py` | Qt-free owner of stage, rail, island, fit, minimap, and overlay rects. Rail is already limited by `RAIL_CONTENT_HEIGHT = 196`, but is top-pinned after BoardIsland. | Make it content-height and vertically centred; establish shared left/right axes. |
| `mf4_analyzer/ui/chart_stack/ultraview/page.py` | Passes actual widget size hints to the pure layout and applies rects to CanvasHost children. | Adapt only if the pure API changes; do not calculate a second geometry model. |
| `mf4_analyzer/ui/chart_stack/ultraview/chrome.py` | ToolRail owns its 48 px width, buttons, badges, focus and drag/drop. | Prove actual size hint and rect use; do not add stretch/spacer widgets. |
| `mf4_analyzer/ui_kit/style.qss` | Shared short-island material and 30 px icon optical boxes; no border shorthand. | Only source-proven selector/pixel corrections. |
| `tests/ui/test_ultraview_floating_layout.py` | Pure geometry/bounds/overlay/minimap/card-context contract. | Replace old B-only left relation with A axes and centred rail tests. |
| `tests/ui/test_ultraview_page.py` | Real widget geometry, overlay, rail/drop, card-context and page behavior. | Add pure-layout-to-widget parity and no-stretch checks. |
| `tools/verify_ultraview_visuals.py` | Named offscreen screenshots and geometry manifest under `.state/`. | Add A axis/rail-height facts for before/after review. |

Expected source scope is limited to the owners above and their focused tests. `ui/hints.py` and `ui/quickref.py` stay unchanged because A does not rename or remove an interaction. If implementation changes visible command wording, update both under the repository contract.

## 3. Geometry contract

Let `safe = stage.inset(SAFE_MARGIN)` and retain existing constants: `SAFE_MARGIN = 12`, `RAIL_WIDTH = 48`, `RAIL_TO_CANVAS_GAP = 18`, and `ISLAND_HEIGHT = 40`.

At normal sizes:

- `rail.left == board_island.left == status_island.left == safe.left`.
- `global_island.right == navigation_island.right == safe.right`.
- `board_island.top == global_island.top == safe.top`.
- `status_island.bottom == navigation_island.bottom == safe.bottom`.
- `fit.left == rail.right + RAIL_TO_CANVAS_GAP`.
- `rail.height == min(actual rail content height, safe.height)`.
- `abs(rail.vertical_center - safe.vertical_center) <= 1`.

For tiny, zero, negative, or non-finite stages, every rect remains non-negative and clamped inside stage. The bottom navigation/minimap and CardContextIsland avoidance rules remain active.

Rail/global overlays keep their existing contract in this scope: opening one does not change `board`, `fit`, fixed-island, zoom, scroll, or Board-state geometry; rail overlays remain right of the rail and below the top island row. Do not introduce per-button trigger-centred popover placement without a separate design decision, because it changes current focus and drag/drop geometry.

## 4. Gate before edits

1. Record `git status --short --branch`, `git log -1 --oneline`, and `git diff --check`.
2. Preserve the existing untracked floating UI review and A HTML prototype. Do not stage them unless this task explicitly edits them and the resulting diff is reviewed.
3. Characterize any still-reproducible issues from the untracked floating UI review. Replacement/rebind, unplaced, Board-menu, and P3 correctness findings remain outside A unless they block the geometry proof. A blocking prerequisite gets a RED test and its own commit.
4. Capture a pre-change matrix with `tools/verify_ultraview_visuals.py` to `.state/ultraview-a-edge-rhythm/baseline` at 800x560, 1280x800, and 1440x900.
5. Run the focused baseline: `test_ultraview_floating_layout.py`, `test_ultraview_chrome.py`, `test_ultraview_page.py`, `test_ultraview_viewport.py`, `test_ultraview_mode_integration.py`, and `test_ultraview_job_isolation.py`. A crash, timeout, or interruption is UNVERIFIED.

## 5. Task 0: red tests for A

In `tests/ui/test_ultraview_floating_layout.py`, write failing tests before source edits:

1. At 1280x800, assert the four A edge axes, 40 px top/bottom baselines, `fit.left` rail gap, and no persistent chrome intersections.
2. Parametrize 800x560, 1280x800, and 1440x900. Assert content-height rail and safe-stage vertical centring to one pixel.
3. Keep bounded-rect coverage for tiny/invalid input; add the centred-y fallback to it.
4. Assert rail/global overlay open and closed layouts retain identical board/fit/fixed-island rects and preserve existing overlay bounds.
5. Feed the new BoardIsland rect into CardContextIsland avoidance coverage.

In `tests/ui/test_ultraview_page.py`, add a real-widget parity test: after each resize, the CanvasHost children equal the pure layout rects. Open each rail/global panel, overview, and presentation; rail must not stretch or drift and BoardScrollArea geometry/zoom/scroll must remain unchanged.

The old `board_island.x == fit.x` assertion must fail and then be replaced; do not use `xfail`, waits, or size-specific exceptions.

## 6. Task 1: pure-layout implementation

Only edit `calculate_floating_layout()` in `floating_layout.py`:

1. Retain `content_left = safe.left + RAIL_WIDTH + RAIL_TO_CANVAS_GAP` for `fit` and card parking.
2. Introduce `left_axis = safe.left` for BoardIsland and StatusIsland. Recalculate BoardIsland maximum width from that axis so it cannot overlap GlobalIsland.
3. Keep the requested rail height sourced from `rail_size`, clamp it to safe height, then calculate `rail.y = safe.top + (safe.height - rail.height) // 2` before final bounds clamping.
4. Preserve all constants and the overlay/minimap/card-context algorithms unless a RED test proves a direct A conflict.
5. Update the docstring to distinguish full-bleed board, card fit area, and compact centred chrome.

The module must remain Qt-free: no PyQt imports, widgets, Page, PreviewStore, Board state, or persistence references.

## 7. Task 2: Qt integration and visual finish

1. Make only the minimum `page.py` wiring change needed by Task 1. `_apply_floating_layout()` remains the one place that maps pure rects to widgets.
2. Verify `ToolRail.sizeHint()` represents the actual button stack. If it does not, add a focused chrome RED test and fix the size hint locally; do not hard-code extra height in Page.
3. Keep ToolRail panel signals, free-grid toggle, badge position, drag/drop target, keyboard focus and accessible names unchanged. Add a drag test using the new vertically centred rail location.
4. In the visual verifier, add manifest facts for left/right/top/bottom axis deltas, requested/actual rail height, rail-centre delta, and fit-to-rail gap. Assert 0 or <=1 px error across the three target sizes.
5. Review the existing island QSS via source search. Remove only selectors with no live object name; preserve active `QMenu#ultraViewBoardPopover` and existing radius/border-shorthand discipline. Do not make a theme change merely because A changes positions.

## 8. Verification and acceptance

Run the changed-owner tests first, then the existing UltraView focused cluster and boundary gates:

    TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
      .venv/bin/python -m pytest \
      tests/ui/test_ultraview_floating_layout.py \
      tests/ui/test_ultraview_chrome.py \
      tests/ui/test_ultraview_page.py \
      tests/ui/test_ultraview_viewport.py \
      tests/ui/test_ultraview_mode_integration.py \
      tests/ui/test_ultraview_job_isolation.py \
      tests/ui_kit/test_qss_border_shorthand.py \
      tests/ui/test_no_lambda_signal_connections.py -q

Then run `tools/verify_ultraview_visuals.py` to `.state/ultraview-a-edge-rhythm/after` and compare it with baseline. The change may move chrome only; unexplained BoardScrollArea, card payload, zoom, scroll, or minimap geometry changes are failures.

The zero-compute probe must cover page open, Board switch, all rail/global panels, zoom/fit/reset/minimap/overview/presentation, copy/export, and save. Analysis compute, job submission, and store-write counts remain zero.

macOS Cocoa foreground acceptance is separate and required before declaring visual completion: 800x560, 1280x800, 1440x900, Retina DPR, all rail panels, Library/Unplaced drag-drop, badge/warning/focus states, free-grid/minimap/card-context/overview/presentation, and a 24-card zoom/pan check. Windows frozen validation is a separate release gate if a release includes Windows.

QSS C-class hangover (from `docs/analyzer/specs/2026-08-15-qss-consolidation-spec.md` §5.2): the nine names (`ultraViewBoardColumn`, `ultraViewPopover`, `ultraViewFilterPopover`, `ultraViewLibraryPopover`, `ultraViewUnplacedPopover`, `ultraViewUnplacedBadge`, `ultraViewFilterWarning`, `ultraViewNavigationZoomLabel`, `ultraViewStatusIslandText`) are **already absent** from `style.qss` on `3971d5a3`. Keep `tests/ui_kit/test_qss_selector_liveness.py` `MIGRATION_OBJECT_NAMES` empty and do not reintroduce those selectors. The QSS consolidation batch must not add them back.

## 9. Commit boundaries and done definition

Suggested commits:

1. `test(ultraview): freeze A edge-rhythm geometry contract`
2. `fix(ultraview): center compact rail and align floating chrome axes`
3. `style(ultraview): verify A chrome rhythm and prune proven stale selectors`

Any correctness prerequisite stays separate from these commits. Before every commit, inspect status, `git diff --check`, staged diff check, and staged stat; stage no unrelated dirty work.

Done means all of the following are true:

- A axes and vertically centred content-height rail have RED-to-green proof at all target and tiny sizes.
- Cards still park right of the rail, and overlays do not reflow Board or lose focus/drag/drop behavior.
- Existing actions, state, zero-compute behavior, import/state-ownership/lambda/QSS gates remain green.
- Offscreen baseline/after geometry evidence and Cocoa foreground evidence are reported separately and honestly.
- No broad stylesheet cleanup, source-contract change, or unrelated worktree file entered the patch.
