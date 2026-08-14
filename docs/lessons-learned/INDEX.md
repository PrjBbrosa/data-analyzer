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
| [PyQt Dialog Scroll Keeps Actions Visible](pyqt-dialog-scroll-keeps-actions-visible.md) | Touching PyQt dialogs with header/body/footer layouts, especially chart options or settings dialogs with enough fields to exceed short laptop screens. | See lesson |
| [Shared Wheel Dispatch Needs Event-Route Coverage](shared-wheel-dispatch-needs-event-route-coverage.md) | Changing the shared pyqtgraph ``_ModifierWheelViewBox`` wheel-dispatch payload or any canvas ``_handle_wheel_dispatch`` callback signature. | See lesson |
| [Relocated Inspector Fields Keep Their Trailing Alignment](inspector-relocated-field-keeps-trailing-alignment.md) | Moving a capped Inspector control from a `QFormLayout` into a | See lesson |
| [FFT-vs-Time Custom-X Cache Invalidation](codex-fft-time-custom-xaxis-cache-invalidation.md) | Change a display control whose semantics are absent from the | See lesson |
| [Qt Worker Callbacks Retain Run Context](codex-qt-worker-callback-context.md) | Changing worker completion/progress callbacks or QThread cleanup in | See lesson |
| [Release Version Labels Stay Synchronized](codex-release-version-labels-stay-synchronized.md) | Bumping the TraceLab application release version, especially when its | See lesson |
| [Help Screenshot Generator Must Follow The Current Analysis Service](codex-help-screenshot-generator-follows-analysis-service.md) | Regenerating application-help screenshots after analysis orchestration, | See lesson |
| [Custom X Axis Title Includes Source Unit](custom-x-axis-title-includes-source-unit.md) | Changing the TimeDomain label used for a channel-backed custom X axis. | See lesson |
| [PowerShell Foreach Output Must Be Collected Before Piping](codex-powershell-foreach-pipeline-grouping.md) | Building Windows PowerShell commands that send the output of a | See lesson |
| [Keep Headless PyQt Test Fixtures And Modals Deterministic](codex-pytest-ui-suite-fixtures-and-modals.md) | Running explicit PyQt test-file lists, especially after adding a | See lesson |
| [Guard QTreeWidget Checkbox Handlers By Column](codex-qt-tree-itemchanged-column-guard.md) | Editing icons, tooltips, colors, or other item data in a | See lesson |
| [Co-axis Dual Cursor Must Retain Every Member Extremum](codex-coaxis-dual-cursor-extrema.md) | Changing dual-cursor min/max markers, co-axis groups, or TimeDomain | See lesson |
| [Channel Config Picker Uses Structured Rows](codex-channel-config-picker-structured-rows.md) | Changing the TimeDomain saved-channel configuration picker or its | See lesson |
| [Channel Config UI Needs Host-Width Render Proof](codex-channel-config-host-geometry-render.md) | Changing the channel configuration rail, its combo popup, or the | See lesson |
| [CRC-like curves need raw profiling, an AA gate, and a cached smooth layer](crc-like-high-variation-envelope-rendering.md) | A modest-size CRC, rolling counter, byte-valued, or dense discrete time-domain channel is slow to select, pan, or zoom, especially when the UI reports that antialiasing is active. | See lesson |
| [Channel Tree Leaf Delegate Geometry](codex-channel-tree-leaf-delegate-geometry.md) | Changing selected-state presentation or icons in the channel tree. | See lesson |
| [QMessageBox QSS Content Width](codex-qmessagebox-qss-content-width.md) | Adding or changing text buttons in a styled QMessageBox, especially | See lesson |
| [Approved HTML Requires Operation Parity](codex-approved-html-operation-parity.md) | A user supplies or approves an HTML prototype as the implementation | See lesson |
| [Release Notes Cover Implemented Features](codex-release-notes-cover-implemented-features.md) | Preparing or correcting a TraceLab release entry while the checkout contains implemented user-facing feature work. | See lesson |
| [Frozen Import Dependencies Need One Contract](codex-frozen-import-dependency-contract.md) | Adding, removing, or packaging a supported data-file importer whose | See lesson |
| [Channel Tree Refresh Must Not Detach A View File](codex-channel-tree-refresh-preserves-view-state.md) | Refreshing channel rows after a channel-editor add/remove operation, | See lesson |
| [Lite SciPy Pruning Needs Frozen Import Smoke](codex-lite-scipy-pruning-smoke.md) | Reducing SciPy collection or native DLLs in the Windows analyzer-only | See lesson |
| [Channel Configuration Manager Must Open Above the Taskbar](codex-channel-config-manager-taskbar-height.md) | Changing the default geometry or fixed-height regions of the Channel | See lesson |
| [Pyqtgraph TimeDomain Shared-X Consumer Budget](pg-timedomain-shared-x-consumer-budget.md) | Change TimeDomain buffered pan/zoom, resize settling, selection delta, | See lesson |
| [Batch Output Identity Must Survive Publish Races](signal-processing/2026-07-28-batch-output-identity.md) | Batch exports derive paths for multiple sources, groups, channels, or recipes, especially when names contain Unicode or an output directory is reused. | See lesson |
| [Batch Dynamic Scroll Panes Need Minimum Content Policy](batch-dynamic-scroll-pane-size-policy.md) | Changing BatchSheet columns, dynamic method fields, or any | See lesson |
| [Batch Output Validation Has One Pure Authority](batch-output-validation-single-authority.md) | Adding or changing batch output fields, formats, sizes, conflict policies, resume settings, or UI preflight behavior. | See lesson |
| [Batch Render Facts Must Use Producer-Shaped Tests](batch-render-facts-use-producer-contract.md) | Adding or renaming effective analysis facts shown in batch titles, subtitles, labels, or manifests. | See lesson |
| [Batch Operations Keep Runtime State Out Of Presets](batch-operations-runtime-state.md) | Changing BatchSheet run lifecycle, manifest resume, retry-failed, worker arguments, or consecutive-run result handling. | See lesson |
| [Qt Batch Render Proof Includes CJK Glyph And Ink Coverage](batch-render-cjk-glyph-coverage.md) | Changing Qt batch text, PNG output, or cross-platform font fallback. | `tests/test_batch_render_qt.py::test_cjk_font_support_and_header_ink_proof` |
| [Qt Offscreen Batch Rendering Owns GUI Thread And Application Lifecycle](signal-processing/2026-08-02-qt-batch-render-lifecycle.md) | Changing Qt batch dispatch, scene paint, PNG encode, DPI metadata, or render probes. | `tests/test_batch_render_qt.py`; native Cocoa heartbeat |
| [Batch Task List Height Follows Its Information](batch-task-list-information-weighted-height.md) | Changing BatchSheet task preview rows, task statuses, disclosure behavior, or the bottom task-list layout. | See lesson |
| [Raw Wheel Pixel Delta Survives Scene Routing](raw-wheel-pixel-delta-survives-scene-routing.md) | Changing pyqtgraph wheel routing, modifier zoom behavior, the | See lesson |
| [Qt Timer Rate Limits Need A Timeout-Time Guard](qt-timer-rate-limit-recheck-at-timeout.md) | Implementing or reviewing a hard interaction refresh-rate ceiling with | See lesson |
| [Overlay Wheel Zoom Covers All Tick Densities](codex-overlay-wheel-zoom-covers-all-tick-densities.md) | Changing overlay Y-axis Shift-wheel zoom, nice-step selection, range | See lesson |
| [Channel Tree Selection Color Has Multiple Painters](codex-channel-tree-selection-color-has-multiple-painters.md) | Changing the selected-row color or painting behavior of the Analyzer | See lesson |
| [Channel Tree Drag Selection Guard](codex-channel-tree-drag-selection-guard.md) | Changing channel-tree selection modes or mouse press, move, release, | See lesson |
| [Codex Overlay Wheel Anchor Invariants](codex-overlay-wheel-anchor-invariants.md) | Load when changing overlay wheel zoom, nice-step selection, tick | See lesson |
| [Overlay Free-Phase Changes Need A Consumer Audit](codex-overlay-free-phase-consumer-audit.md) | Changing an overlay or analysis Y-wheel transform from globally aligned | See lesson |
| [Nice-Step Tolerance Must Check Neighboring Candidates](codex-nice-step-tolerance-checks-neighbors.md) | Adding an approximate nice-step guard around a helper that deliberately | See lesson |
| [Tick Label Truthfulness Comes Before Compactness](codex-tick-label-truthfulness-before-compactness.md) | Changing tick formatting, explicit `AxisItem.setTicks()` labels, axis | See lesson |
| [Superseded Plans Use New Dated Files](codex-superseded-plans-use-new-dated-files.md) | Revising an approved or committed implementation plan after its core | See lesson |
| [Numeric Hazard Rates Need The Real Caller Path](codex-numeric-hazard-rate-needs-caller-path.md) | Using a numerical sweep or extracted-expression probe to justify a | See lesson |
| [Codex PG Subplot Reuse Needs Realized Geometry](codex-pg-subplot-reuse-needs-realized-geometry.md) | Changing or reviewing time-domain subplot selection-delta reuse, | See lesson |
| [Identity-sensitive Y-fit must not fall back to an ambiguous display label](pyqt-ui/2026-07-30-identity-sensitive-yfit-must-not-fallback-to-display-label.md) | Identity-sensitive canvas paths have both a composite channel key and a display label. | See lesson |
| [`dict.setdefault` bypasses aliased-key resolution in a dict subclass](pyqt-ui/2026-07-30-dict-setdefault-bypasses-aliased-key-resolution.md) | A dict subclass aliases external labels to stored composite keys. | See lesson |
| [`np.convolve(mode="same")` follows the longer operand's length](signal-processing/2026-07-30-convolve-same-output-length-follows-longer-operand.md) | A UI-controlled smoothing window may be longer than the selected signal. | See lesson |
| [An actionable audit needs a fixed commit SHA](refactor/2026-07-30-audit-baseline-requires-commit-sha.md) | An audit reports source counts, line locations, probes, priorities, or estimates. | See lesson |
| [Canvas backref write-through needs an explicit whitelist](pyqt-ui/2026-07-30-canvas-backref-write-through-needs-explicit-whitelist.md) | A collaborator delegates unknown attribute reads or writes to a shared canvas. | See lesson |
| [Diagnostic throttles must account for every pending count](diagnostic-throttle-pending-count-lifecycle.md) | Changing a bounded diagnostic throttle, its rollover, eviction, or shutdown behavior. | See lesson |
| [Windows Vendoring Network Failures Keep The Gate Red](codex-windows-vendoring-network-retry.md) | A Windows folder build fails while pip vendors the pinned Vector/XCP | See lesson |
| [Batch Render Degradation Stops At The Probe](batch-render-degradation-stops-at-probe.md) | Changing batch image/PDF backend imports, effective output selection, | See lesson |
| [Windows Popup Pixel Probes Need Topmost Host And Frame Geometry](pyqt-ui/2026-07-31-windows-popup-pixel-probes-need-topmost-host-and-frame-geometry.md) | Verifying a translucent, rounded Qt popup or tooltip on a real Windows desktop with `QScreen.grabWindow(0)`. | See lesson |
| [Close Batch Spool Mmaps Before Cleanup](batch-spool-mmap-close-before-cleanup.md) | Changing batch series spooling, memory-mapped array loading, grouped | See lesson |
| [Manifest Resume Requires Complete Source Facts](manifest-resume-requires-complete-source-facts.md) | Changing manifest validation, resume lookup, source provenance facts, | See lesson |
| [Register Lazy Locators Before Group Identity](batch-register-lazy-locators-before-group-identity.md) | Changing lazy batch `source_paths`, locator registration, task/group | See lesson |
| [Acceptance Evidence Must Prove Physical Artifacts](acceptance-evidence-rejects-artifact-aliases.md) | An acceptance harness claims exact artifact counts, grouping semantics, | See lesson |
| [Batch UI Separates Sparse Defaults From Missing Facts](batch-ui-sparse-defaults-preserve-missing-facts.md) | Applying full batch recipes, incremental parameter patches, or | See lesson |
| [Batch Preview Never Escalates Full-Cost Probes](batch-preview-never-escalates-full-cost-probes.md) | Resolving lazy source descriptors or output identities during a batch | See lesson |
| [Batch Deferred Terminals Preserve Task Order](batch-deferred-terminals-preserve-task-order.md) | Deferring batch task terminal events or progress callbacks until a | See lesson |
| [Batch Preview Probe Failure Stays Planning-Local](batch-preview-probe-failure-stays-planning-local.md) | Adding metadata-only source probing to a no-load preview that runs | See lesson |
| [Custom X Unit Cohort Follows Drawable Eligibility](custom-x-unit-cohort-after-eligibility.md) | Changing multi-source TimeDomain custom-X range filtering, finite-X | See lesson |
| [Producer Result Contracts Include Mock Consumers](producer-result-contract-mock-consumers.md) | Changing a shared producer from a primitive payload such as a list or | See lesson |
| [Batch UI Layout Migrations Isolate Hidden And Method State](batch-ui-layout-migrations-isolate-hidden-and-method-state.md) | Replacing a Batch Qt form/layout while retaining compatibility widgets, | See lesson |
| [Full Qt UI Gate Must Finish Before It Is Evidence](qt-full-ui-stylesheet-gate-must-finish.md) | A change requires the complete `tests/ui` stability gate, especially | See lesson |
| [Paired Qt Editors Sync Before Aggregate State Reconstruction](paired-qt-editors-sync-before-aggregate-state.md) | A slider and spinbox edit the same value while one handler rebuilds an | See lesson |
| [Batch Range Modes Need Exclusive Layout Pages](batch-statistics-range-mode-layout.md) | Adding a compact Batch setting that changes a one-line control group | See lesson |
| [Batch Custom-X Statistics Need Major Legs Before Range Clipping](batch-custom-x-major-legs-before-range-clipping.md) | Changing Batch time-chart statistics for channel-backed X, especially | See lesson |
| [Available-Per-Source Custom X Must Share a Logical Source With Its Target](batch-available-per-source-custom-x-coavailability.md) | Changing Batch time-chart custom-X candidates, task expansion, | See lesson |
| [Batch Non-Finite Values Stay Out Of Identity And Warning Bounds](batch-nonfinite-values-stay-out-of-identity-and-warning-bounds.md) | Changing batch recipe normalization, recipe fingerprints, heatmap | See lesson |
| [Qt Composite Disabled Cues Follow Effective State](qt-composite-disabled-cues-follow-effective-state.md) | Changing disabled styling or interaction cues on a composite Qt | See lesson |
| [Free-Config Batch RPM Keeps Its Logical Source](batch-free-config-cross-source-rpm-pairing.md) | Editing BatchSheet free-config order analysis, RPM-channel selection, | See lesson |
| [Changelog Slides Keep Recent Front And Pack History At End](changelog-slides-reserve-bottom-safe-area.md) | Adding or editing entries in the application-help changelog deck. | See lesson |
| [Qt Popup Singletons Validate The C++ Lifetime](qt-popup-singleton-validates-cpp-lifetime.md) | Keeping a parentless QWidget or popup in a Python class-level singleton | See lesson |
| [Zsh Path Variables Can Clobber Command Search](zsh-path-variable-clobbers-command-search.md) | Writing an inline zsh loop or helper that assigns a shell variable | See lesson |
| [TimeDomain X-Axis Interaction Keeps Layout Stable](timedomain-xaxis-interaction-keeps-layout-stable.md) | Changing TimeDomain target X ticks, X-range interaction, the interaction quiet window, or bottom AxisItem sizing. | See lesson |
| [Action Button Natural Height Under Wrapped Label Pressure](pyqt-ui/2026-08-08-action-button-natural-height-under-wrapped-label-pressure.md) | A compact vertical Qt form places a user action between elastic controls and a word-wrapped description, especially during mode switching or widget reparenting. | See lesson |
| [Validate FRF Data After Applying The Shared Physical-Time Mask](frf-range-mask-before-data-validation.md) | Changing FRF range selection, timebase validation, or GUI/Batch | See lesson |
| [Deferred Analysis Restore Uses Stable View Identity](deferred-analysis-restore-uses-stable-view-identity.md) | Adding deferred project restore or asynchronous compute for analysis | See lesson |
| [Text Actions Must Not Reuse Icon-Only QSS Roles](pyqt-ui/2026-08-09-text-action-role-avoids-icon-qss-height.md) | Adding or reviewing a textual button in a compact Qt form that uses a | See lesson |
| [Batch Picker Layout Uses The Current Stack Page And Readable Empty State](batch-current-stack-page-and-empty-picker-height.md) | Changing a Batch stacked field that swaps compact and multi-row pages, or the signal-picker popup's empty/list geometry. | See lesson |
| [Batch Filter Fields Share One Form Column](batch-filter-fields-share-form-column.md) | Editing batch dialog form rows that wrap short combo/spin editors, | See lesson |
| [Comma List Inputs Accept Chinese Separators](comma-list-inputs-accept-chinese-separators.md) | Adding or editing a user-typed comma-separated field (slice | See lesson |
| [Binary Batch Combos Prefer SegmentedChoice](binary-batch-combos-prefer-segmented-choice.md) | Replacing or reviewing a product control that has exactly two fixed | See lesson |
| [Chart Statistics UI Redesigns Keep Param Wiring](chart-statistics-ui-keep-param-wiring.md) | Restyling Batch 图内统计 (SegmentedChoice, chips, field bars) or any | See lesson |
| [Analysis View Tests Must Seed Attachments](analysis-view-tests-seed-attachments.md) | Writing or updating integration tests that switch into FFT / FFT-vs-Time / | See lesson |
| [Codex Analysis Mode Entry Applies View Params](codex-analysis-mode-entry-apply-view-params.md) | Load when changing analysis mode entry (`_on_mode_changed` / `_enter_fft_mode`) or any path that can capture live Inspector params into an analysis View. | See lesson |
| [Guard programmatic analysis-View restore at both signal and projection boundaries](codex-analysis-view-restore-projection-guards.md) | Changing analysis View application, project restore, shared Inspector | See lesson |
| [Channel Tree Uses visualRect And Fixed Pts Width](codex-channel-tree-stable-visualrect-pts-fixed.md) | Changing channel-tree selection chrome, checkbox painting, Pts column | See lesson |
| [Stateful Icon Buttons Need active QSS And String Attrs](codex-stateful-icon-button-active-qss.md) | Adding or changing a non-checkable icon `QToolButton` whose on/off | See lesson |
| [Fixed-size bytearray headers must use equal-length slice assigns](codex-bytearray-slice-assign-fixed-size.md) | Packing fixed binary headers with `bytearray(N)` and slice assignment. | See lesson |
| [QSS Combined qproperty Flags Need Quotes](qss-qproperty-combined-flags-need-quotes.md) | Editing `mf4_analyzer/ui_kit/style.qss` (or any app-wide QSS template), | See lesson |
| [FFT Preview Zoom Does Not Auto-Arm Time Range](fft-preview-zoom-no-auto-arm-time-range.md) | Changing FFT time-preview pan/zoom wiring, shared `chk_range` | See lesson |
| [Confirm Unchecked Local Time Range Before Compute](analysis-compute-confirm-unchecked-local-range.md) | Wiring analysis compute entry points (`do_fft` / `do_fft_time` / | See lesson |
| [「全部」用图面已绘制通道时长，不用通道树最长加载文件](time-range-all-uses-plotted-extent.md) | Changing Inspector「全部」/ `_plotted_time_extent` / analysis-mode framing | See lesson |
| [ViewState Composite-Key Tables Stay In Sync](codex-viewstate-composite-key-tables-stay-in-sync.md) | Touching `remap_view_fids`, close-file ViewState cleanup, or any | See lesson |
| [Toast providers stay weak; selected expanders avoid QMacStyle primitives](qt-lifecycle-toast-and-macstyle-expander.md) | ``Toast(margin_provider=bound_method)``; Darwin channel-tree | See lesson |
| [FFT Time Preview Empty Keeps Y Graticule](fft-time-preview-empty-keeps-y-graticule.md) | Changing `PgLineCanvas` time-preview overlay grid, `_build_time_y_grid`, empty `plot_time_preview([])`, or `full_reset`. | See lesson |
| [UltraView Time Capture Uses Plotted Ink And Stable Digest](ultraview-time-capture-ink-and-stable-digest.md) | Changing UltraView preview capture, `_host_has_real_result`, presentation digest, or `source_revision_for` in the time-preview path. | See lesson |
| [Independent Tool Window Must Clear Transient Parent](independent-tool-window-must-clear-transient-parent.md) | Adding or changing a non-modal QDialog tool window parented to MainWindow | See lesson |
| [UltraView Idle Recapture Keeps Armed Cursor And Cursor Digest](ultraview-idle-digest-keeps-armed-cursor.md) | Changing UltraView capture, presentation digest, `hide_transient_overlays`, idle recapture, or copy-as-image pill compositing. | See lesson |
| [Channel Tree Selected Fill Must Stay Rectangular](codex-channel-tree-selected-fill-must-stay-rectangular.md) | Changing channel-tree selected-row QSS, `drawBranches`, or the | See lesson |
| [QDrag.exec_ Must Outlive Its Source Widget](ultraview-qdrag-exec-must-outlive-source.md) | Implementing or testing Qt drag-drop that rebuilds the library, grid, | See lesson |
| [Toolbar Enable Matrix At Construction](pyqt-ui/2026-08-14-toolbar-enable-matrix-at-construction.md) | Changing toolbar button enable/disable rules, `set_enabled_for_mode`, or any gated QPushButton whose live state is applied only on a later event. | See lesson |
| [CAN Log Probe Samples Decode And Defers ZOH](2026-08-14-can-log-probe-sample-and-lazy-zoh.md) | Changing BLF/CANoe ASC import, DBC probe strength, or the shared-time ZOH assemble that turns CAN signals into a FileData table. | See lesson |
| [ColorBarItem setLevels Poisons Live Drag](pyqt-ui/2026-08-14-colorbar-setlevels-poisons-live-drag.md) | Heatmap colorbar drag, `ColorBarItem.setLevels`, inspector `apply_params` of `z_floor`/`z_ceiling`, `levels_changed`, or locked-levels sibling mirror. | See lesson |
| [Project Open Recomputes Every Analysis View](project-open-recomputes-every-analysis-view.md) | Changing project save/open, analysis View restore, FFT pane.sources capture, or any path that used to call `do_fft` / `do_order_time` / `do_fft_time` / `do_frf` after loading a `.tlproj`. | See lesson |
| [UltraView Zoom Maps Receiver Local Pos](pyqt-ui/2026-08-14-ultraview-zoom-maps-receiver-local-pos.md) | UltraView board zoom, Ctrl+wheel, trackpad pinch, `handle_zoom_wheel`, `handle_pinch`, or `_cursor_in_scroll_viewport`. | See lesson |
| [QLabel Pixmap Scale To ContentsRect](pyqt-ui/2026-08-14-qlabel-pixmap-scale-to-contentsrect.md) | Fitting a pixmap into a `QLabel` that has QSS `padding`, especially UltraView `QLabel#ultraViewCardImage`. | See lesson |
| [UltraView Full-Bleed Canvas Parks Fit At Origin](pyqt-ui/2026-08-14-ultraview-full-bleed-fit-origin.md) | Changing UltraView `FloatingLayout.board`, BoardScrollArea geometry, `zoom_fit`, or zoom-at-cursor scroll math. | See lesson |
| [Project Restore Progress Yields The Event Loop](project-restore-progress-yields-event-loop.md) | Changing project open, analysis-view restore scheduling, compute progress, or any `processEvents` on the restore path. | See lesson |
| [UltraView Card Context Follows Page Selection](pyqt-ui/2026-08-14-ultraview-card-context-follows-selection.md) | Changing UltraView `CardContextIsland`, Esc, empty-canvas click, `UltraViewPage._selected`, or `FreeGridBoard` gesture selection. | See lesson |
| [UltraView Overlap Asks Then Auto-Avoids](pyqt-ui/2026-08-14-ultraview-overlap-asks-auto-avoid.md) | Changing UltraView free-grid drag/resize commit, overlap toasts, or `plan_overlap_avoidance`. | See lesson |
| [UltraView Island SizeHint Uses isHidden](pyqt-ui/2026-08-14-ultraview-island-sizehint-uses-ishidden.md) | Changing UltraView floating-island `sizeHint`, `GlobalIsland.set_edit_visible`, or `_chrome_sizes` / `_apply_floating_layout` geometry. | See lesson |
| [UltraView QSS ID Ignores Ancestor Qualifier](pyqt-ui/2026-08-14-ultraview-qss-id-ignores-ancestor.md) | Styling an UltraView control with a page-level QSS descendant plus a child `#objectName`, especially `ultraViewGlobalPresentationButton`. | See lesson |
| [UltraView Stale Means Digest Mismatch; Sync Recaptures](pyqt-ui/2026-08-14-ultraview-stale-means-digest-sync-recaptures.md) | Changing UltraView card status, `derive_preview_status`, presentation digest, idle recapture, or adding a Board sync/refresh control. | See lesson |
| [Heatmap Slice Y-Fit Uses Visible X](pyqt-ui/2026-08-14-heatmap-slice-yfit-uses-visible-x.md) | Changing FFT-vs-Time / Order slice context menus, `y_autofit_handler`, or slice amplitude ranging. | See lesson |
| [UltraView Zoom Zero Local Is Not Cursor](pyqt-ui/2026-08-14-ultraview-zoom-zero-local-is-not-cursor.md) | UltraView board zoom, Ctrl+wheel, trackpad pinch, `_cursor_in_scroll_viewport`, or any fix that maps `event.position()` as the zoom anchor. | See lesson |
| [Compute Progress Elides From QSS Chrome Not Long Copy](pyqt-ui/2026-08-14-compute-progress-elides-from-qss-chrome.md) | Changing `ComputeProgressWidget`, status-bar load/compute labels, or QSS for `#computeProgressLabel` / `#computeProgressBar`. | See lesson |
| [UltraView Edge Shrinks Neighbours Instead Of Dead-Ending](pyqt-ui/2026-08-14-ultraview-edge-shrinks-neighbors.md) | Changing UltraView free-grid drag/resize commit, `FEEDBACK_OUT_OF_GRID`, `plan_boundary_yield`, or `plan_neighbor_shrink`. | See lesson |
| [UltraView Layout Rail Tracks Template Mode](pyqt-ui/2026-08-14-ultraview-layout-rail-tracks-template.md) | Changing UltraView `ToolRail` button order, layout/free-grid `active` chrome, or `_sync_button_states`. | See lesson |

## Selection Rules

- Use keywords, file paths, failing test names, and user prompt terms to select
  at most 1-5 relevant lessons.
- Prefer lessons with executable checks over prose-only lessons.
- If a task creates a new durable rule, add or update one lesson and update this
  table.
