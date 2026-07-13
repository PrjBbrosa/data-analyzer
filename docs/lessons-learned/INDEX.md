# Lessons Learned Index

This index routes Codex to a small set of relevant lessons. Do not read every
lesson by default.

## Active Lessons

| Lesson | Trigger | Checks |
| --- | --- | --- |
| [Codex Review Report Contract](codex-review-report-contract.md) | Review-only code/plan/spec/commit reports with citations or fixed verdicts. | `git show`, `rg -n`, `nl -ba`, report heading check |
| [Codex Plan And Spec Literal Evidence](codex-plan-spec-literal-evidence.md) | Plan/spec rev verification, checklists, proceed/no-go reviews. | Full-artifact read, retired-identifier grep, checklist pass |
| [Codex Runtime Verification Entrypoints](codex-runtime-verification-entrypoints.md) | Running pytest, Qt/offscreen checks, Matplotlib-backed validation. | `.venv/bin/python -m pytest`, `TMPDIR=/tmp`, `MPLCONFIGDIR=/tmp` |
| [Codex Order Batch Boundaries](codex-order-batch-boundaries.md) | Order-analysis, batch runner, batch presets, current/free config flows. | Grep canonical FFT helpers and GUI-free `BatchRunner`; focused tests |
| [Codex FFT Time Review Shields](codex-fft-time-review-shields.md) | FFT-vs-Time wiring, cache/worker/export, validation reports. | Grep signal plumbing, cache keys, `SpectrogramResult`; reconcile fresh tests |
| [Codex Performance And UI Audit Flow](codex-performance-ui-audit-flow.md) | Performance research before edits; read-only UI audits. | Report-first flow; grep toast/modal paths and related tests |
| [Codex Order Canvas Wave Review](codex-order-canvas-wave-review.md) | Order-canvas wave reviews, stale-generation tests, strict scope. | `git status`, `git diff`, `git show HEAD:<file>`, scoped pytest |
| [Codex Publish Flow Lightweight](codex-publish-flow-lightweight.md) | Publish already-local changes: commit, push, open/write PR. | Bounded git status/diff/checks; no audit-style exploration |
| [Codex Lessons System Maintenance](codex-lessons-system-maintenance.md) | Codex lessons system changes, hook tuning, master-kit sync, or `scripts/lessons/*` edits. | `scripts/lessons/check.py --doctor --verbose` |
| [Confirmed Issue List Means Remaining Scope](codex-confirmed-issue-list-means-remaining-scope.md) | Numbered issue follow-ups where the user approves some items and asks a design question about another. | `git status --short`, `git diff --stat`, explicit checklist |
| [Chart Toolbar Label Order](pyqt-ui/2026-05-12-chart-toolbar-label-order.md) | Chart toolbar layout, Matplotlib locLabel, in-toolbar hint text, or per-card controls. | `tests/ui/test_chart_stack.py` |
| [Matplotlib Resize And Modal Nav State](pyqt-ui/2026-05-13-matplotlib-resize-and-modal-nav-state.md) | Touching Matplotlib-backed PyQt canvases, splitter/inspector resize behavior, chart-options double-click flows, or chart toolbar navigation actions. | See lesson |
| [Codex Analyzer Doc Routing](codex-analyzer-doc-routing.md) | Creating, moving, or referencing analyzer-facing documentation and review artifacts. | See lesson |
| [Acquisition Validation Evidence Gates](codex-acquisition-validation-evidence-gates.md) | Acquisition validation docs, preflight/regression tooling, smoke runners, or P0 probe evidence. | See lesson |
| [Acquisition Threshold Defaults Use Current Values](codex-acquisition-threshold-defaults-use-current-values.md) | Acquisition Cockpit editable thresholds, settings auto-load, `SessionConfig` defaults, health helper defaults, or preflight UI defaults. | See lesson |
| [Visual Parity Requires Rendered Screenshot](codex-visual-parity-rendered-screenshot.md) | Touching PyQt visual parity, QSS, toolbar controls, compact chips, or a UI implementation that is supposed to match an HTML prototype or screenshot. | See lesson |
| [Codex MF4 Source Path Alias Dedupe](codex-mf4-source-path-alias-dedupe.md) | Touching MF4 channel enumeration, analyzer channel lists, batch MF4 | See lesson |
| [Windows Native Imports Need Isolated Probe](codex-windows-native-import-guard.md) | Touching Windows acquisition backends, Cockpit startup/import paths, or optional native dependencies such as `pya2l`, `pyxcp`, or Vector `python-can`. | See lesson |
| [Phantom API Surface Guards](codex-phantom-api-surface-guards.md) | Mocking external library surfaces for acquisition probes or optional native dependencies. | Structured fakes/autospec; focused Vector probe tests |
| [Owned Backend Invalidation](codex-owned-backend-invalidation.md) | Touching Acquisition Cockpit backend swapping, transport/A2L settings, | See lesson |
| [PyQt Channel Universe Refresh](pyqt-channel-universe-refresh.md) | Touching file load/close, channel editor application, or live channel selectors. | See lesson |
| [Custom X Axis Keeps Time Range Filtering](pyqt-ui/2026-05-26-custom-x-time-range-filter.md) | Touching `plot_time`, Inspector range controls, custom X-axis channel | See lesson |
| [TimeDomain State Preservation](pyqt-ui/2026-05-26-timedomain-state-preservation.md) | Touching TimeDomain replots, channel selection/editing, plot mode | See lesson |
| [Overlay Selection Drops Pan](pyqt-ui/2026-05-27-overlay-selection-drops-pan.md) | Click-to-enter / click-to-exit gestures on a matplotlib canvas while the nav toolbar is in pan/zoom. | `tests/ui/test_chart_stack.py` |
| [Pyqtgraph Subplot Layout Settle](codex-pg-subplot-layout-settle.md) | Load when changing pyqtgraph TimeDomain subplot axes, grid, tick | See lesson |
| [Markup Group Child Normalization](codex-markup-group-child-normalization.md) | Markup editor scene traversal, selection, copy/paste, crop, or undo with grouped annotations | `tests/ui/test_markup_editor.py` |
| [Rounded Qt Popups Need Translucent Shell](codex-rounded-qt-popups-need-translucent-shell.md) | Rounded Qt popup/menu/popover shells or QSS `border-radius` surfaces. | See lesson |
| [HiDPI Pixmaps And Blocked Axis Sync](codex-hidpi-pixmap-and-axisitem-sync.md) | Copy/edit chart pixmaps or signal-blocked pyqtgraph X range sync. | See lesson |
| [Codex Hooks Use Windows Python Entrypoint](codex-hooks-use-windows-python-entrypoint.md) | Editing Codex hook configuration or diagnosing repeated hook failures | See lesson |
| [Pyqtgraph TimeDomain Frame And Dense Spacing](codex-pg-timedomain-frame-and-spacing.md) | Touching pyqtgraph TimeDomain PlotItem/ViewBox frame styling, | See lesson |
| [Rounded Child Widgets Need Pixel Corner Check](codex-rounded-child-widgets-need-pixel-corner-check.md) | Load when changing child-widget floating pills, hover cards, chart | See lesson |
| [Lazy Parser Import Boundaries](codex-lazy-parser-import-boundaries.md) | Touching A2L parsing, acquisition measurement summaries, or modules | See lesson |
| [Qt Checkbox Doubleclick Hit Region](codex-qt-checkbox-doubleclick-hit-region.md) | Load when custom PyQt item-view checkbox hit handling is changed, | See lesson |
| [Codex Qt Rounded Popup Chrome](codex-qt-rounded-popup-chrome.md) | Changing rounded popup/dropdown/menu styling or adding a new `QMenu`, | See lesson |
| [Qt Checkbox Press Release Toggle](codex-qt-checkbox-press-release-toggle.md) | Changing custom PyQt item-view checkbox hit handling, especially | See lesson |
| [Overlay Graticule And Wheel Contract](codex-overlay-graticule-wheel-contract.md) | Work touching TimeDomain pyqtgraph overlay-mode grid lines, per-channel | See lesson |
| [Cursor Pill View Apply](codex-cursor-pill-view-apply.md) | Touching view-tab apply/render paths, cursor mode restoration, or split-pane cursor pill routing. | See lesson |
| [Timedomain New Channel Y-Fit After Restore](codex-timedomain-new-channel-yfit-after-restore.md) | Touching timedomain channel-selection replots, ViewState | See lesson |
| [Pyqtgraph Heatmap Split Layout Alignment](codex-pg-heatmap-split-layout-alignment.md) | Touching Analysis split panes for Order or FFT-vs-Time heatmaps, | See lesson |
| [Shared ViewTabBar And Pyqtgraph Frames](codex-shared-viewtabbar-and-pg-frames.md) | Touching ViewTabBar QSS, TimeDomain or analysis-section view tab | See lesson |
| [Codex FFT Spectrum Time Preview](codex-fft-spectrum-time-preview.md) | Load when changing the FFT spectrum UI, FFT overlay source routing, or `PgLineCanvas.plot_spectra`. | See lesson |
| [Analysis View-All Visual Padding](codex-analysis-view-all-visual-padding.md) | Touching pyqtgraph analysis canvas Home/View-All behavior for FFT, | See lesson |
| [Analysis Section State Needs Pane-Local Sources](codex-analysis-section-state-needs-pane-local-sources.md) | Work on analysis View tabs, split panes, FFT source colors, or project | See lesson |
| [Tick Density Lives In Chart Toolbar Popout](codex-tick-density-toolbar-popout.md) | Touching global tick-density controls, Inspector persistent chart | See lesson |
| [Codex Time Range Preserve Xaxis Draft](codex-time-range-preserve-xaxis-draft.md) | Changing time-range toggles, custom X-axis controls, or time-domain | See lesson |
| [Analysis Bottom Axis Explicit Ticks Retick On Range Change](analysis-bottom-axis-explicit-ticks-retick-on-range-change.md) | Changing pyqtgraph Analysis bottom-axis tick generation from adaptive density to explicit `AxisItem.setTicks(...)`. | See lesson |
| [Bottom Tick Fitter Reject Over-Fine Not Thin](pyqt-ui/2026-06-17-bottom-tick-fitter-reject-overfine-not-thin.md) | Touching `_apply_target_bottom_ticks` / `_fit_x_tick_labels` target-count tick fitting; FFT/heatmap X ticks non-round or truncated short of the right edge. | `tests/ui/test_pg_heatmap_canvas.py` |
| [Signal Time-Window Heatmap Coverage Extents](signal-time-window-heatmap-coverage-extents.md) | Touching FFT-vs-Time, Order/COT, or any heatmap that plots a matrix | See lesson |
| [Qt Render Probes Isolate QSettings](codex-qt-render-probes-isolate-qsettings.md) | Writing or running Qt screenshot/render probes, smoke scripts, or UI | See lesson |
| [Pyqt Heatmap Slice Curve AA Interaction Guard](pyqt-heatmap-slice-curve-aa-interaction-guard.md) | Touching `PgHeatmapCanvas` slice-curve rendering, slice marker | See lesson |
| [Pyqt Heatmap Copy Includes Widget Overlays](pyqt-heatmap-copy-includes-widget-overlays.md) | Touching heatmap copy/export, `PgHeatmapCanvas.grab_pixmap`, or | See lesson |
| [Status Hint Buttons Need Rendered Geometry](codex-status-hint-button-geometry.md) | Changing the bottom status-line hint bar, the quickref `?` button, or | See lesson |
| [PyQt Drag Event MimeData Lifetime](pyqt-drag-event-mimedata-lifetime.md) | Writing pytest-qt tests that manually construct `QDragEnterEvent`, | See lesson |
| [Overlay Live Visibility Retick](codex-overlay-live-visibility-retick.md) | Touching TimeDomain overlay-mode live visibility toggles for filter | See lesson |
| [Status Facts Preserve Their Field Semantics](b5-status-facts-preserve-field-semantics.md) | Editing the Acquisition Cockpit recording fact stream or its | See lesson |
| [Pinned Protocol Adapters Own Vendor ABI](codex-pinned-protocol-adapters-own-vendor-abi.md) | Implementing or reviewing Seed&Key, native DLL calls, multi-part XCP | See lesson |
| [Frozen Probes Do Not Require Console Streams](codex-frozen-probes-do-not-require-console-streams.md) | Adding a hidden child command, import probe, parser subprocess, or | See lesson |
| [Claude Native Wrapper Stub Recovery](claude-native-wrapper-stub-recovery.md) | `claude` resolves to the global npm install but prints `claude native binary not installed` on Apple Silicon. | See lesson |
| [Shared Wheel Dispatch Needs Event-Route Coverage](shared-wheel-dispatch-needs-event-route-coverage.md) | Changing the shared pyqtgraph ``_ModifierWheelViewBox`` wheel-dispatch payload or any canvas ``_handle_wheel_dispatch`` callback signature. | See lesson |
| [Relocated Inspector Fields Keep Their Trailing Alignment](inspector-relocated-field-keeps-trailing-alignment.md) | Moving a capped Inspector control from a `QFormLayout` into a | See lesson |
| [FFT-vs-Time Custom-X Cache Invalidation](codex-fft-time-custom-xaxis-cache-invalidation.md) | Change a display control whose semantics are absent from the | See lesson |
| [Qt Worker Callbacks Retain Run Context](codex-qt-worker-callback-context.md) | Changing worker completion/progress callbacks or QThread cleanup in | See lesson |

## Selection Rules

- Use keywords, file paths, failing test names, and user prompt terms to select
  at most 1-5 relevant lessons.
- Prefer lessons with executable checks over prose-only lessons.
- If a task creates a new durable rule, add or update one lesson and update this
  table.
