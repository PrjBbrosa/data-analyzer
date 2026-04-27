# Master Lessons Index

Format: `- [<slug>](<role>/YYYY-MM-DD-<slug>.md) [tag1][tag2] — one-line hook`

Write protocol: `docs/lessons-learned/README.md`.

## orchestrator

- [task-tool-unavailable-blocks-dispatch](orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md) [dispatch][tooling][architecture][planner-executor-split] — Task absence is EXPECTED, not a blocker; orchestrator plans, main Claude dispatches.
- [move-then-tighten-causes-cross-specialist-rework](orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md) [decomposition][rework][cross-specialist] — Splitting "create file body" and "tighten file imports" across two specialists causes file-level rework; fold mechanical metadata edits into the body creator's brief unless domain expertise is required.
- [refactor-then-ui-same-file-boundary-disjoint](orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md) [rework][boundary-adjustment][cross-specialist] — Rework detection fires on refactor→ui sequential edits of the same file even when method scopes are disjoint; the fix is enumerating forbidden methods per brief, not disabling the rule.
- [parallel-same-file-drawer-task-collision](orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md) [decomposition][parallel-serialization] — Parallelising same-expert tasks that each touch the same shared file (even for 1-line edits) causes `git add` commit-collision races; serialize or bundle shared-file edits into a single specialist's brief.
- [silent-boundary-leak-bypasses-rework-detection](orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md) [boundary][reporting][reviewer-discipline] — files_changed records files not symbols; specialists must list symbols_touched and reviewers must grep forbidden symbols, otherwise silent overscope passes both rework detection and review.
- [codex-prompt-file-for-long-review](orchestrator/2026-04-25-codex-prompt-file-for-long-review.md) [codex][review][tooling][shell] — Long Codex prompts with shell syntax must use `--prompt-file`; add `--write` when the output contract includes report artifacts.
- [interactive-playground-unblocks-ui-alignment](orchestrator/2026-04-26-interactive-playground-unblocks-ui-alignment.md) [ui][alignment][playground][decision-velocity][brainstorming] — When ≥3 UI proposals differ on visual/feel rather than logic, write a one-shot HTML playground (project-QSS palette, per-proposal toggles, copy-out prompt) instead of more text round-trips.

## signal-processing

- [envelope-cache-bucket-width-quantization](signal-processing/2026-04-25-envelope-cache-bucket-width-quantization.md) [envelope][downsample][cache][viewport] — Quantize viewport-cache keys to one bucket width (span/pixel_width), not a fixed percentage; the quantum must come from the same constant that discretizes the result.
- [cache-consumer-must-be-grepped-not-just-surface](signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md) [cache][hot-path][dead-code][audit] — A cache reachable + invalidatable but never read on the hot path is dead code; grep the uncached helper at the consumer end, not just the cache method on the producer end.
- [batched-fft-transient-buffers-dominate-chunk-budget](signal-processing/2026-04-26-batched-fft-transient-buffers-dominate-chunk-budget.md) [fft][batch][chunk][memory] — A batched FFT pipeline transiently holds 3-4× chunk-frames-bytes (work + complex spectra + abs); use in-place arithmetic and explicit `del` to keep peak memory inside a 4× headroom contract.
- [plan-verbatim-source-must-reconcile-with-recent-removals](signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md) [batch][dispatch][supported-methods][plan-staleness] — A `SUPPORTED_*` gate must be a strict subset of live dispatcher handlers; cross-check plan-verbatim enums against `git log` removals or a ghost value falls through to `else: raise`.

## pyqt-ui

- [responsive-pane-containers](pyqt-ui/2026-04-24-responsive-pane-containers.md) [layout][inspector][navigator][wide-pane] — Use scroll/splitters; verify wide pane (1.5×~3× default) so Expanding children stay capped.
- [flush-after-axis-mutation-not-before](pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md) [debounce][qtimer][xlim-changed][ordering] — Drain debounced refresh AFTER the set_xlim/set_ylim mutation that re-schedules it; use try/finally for one-call-site coverage of all return paths.
- [cache-invalidation-event-conditional](pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md) [cache][qtimer][handler-replay] — Invalidate state-derived caches on a last-value diff, not on handler entry; QTimer.singleShot(0, handler) replays will otherwise wipe the cache every tick.
- [matplotlib-axes-callbacks-lifecycle](pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md) [matplotlib][callbacks][lifecycle] — Axes.callbacks survive fig.clear(); store cids and disconnect-before-rebuild, otherwise callbacks accumulate or wire to dead axes.
- [qthread-wait-deadlocks-queued-quit](pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md) [qthread][worker][signal-slot][deadlock][testing] — `thread.wait()` blocks the main loop; AutoConnection + queued thread.quit deadlocks; use Qt.DirectConnection for thread-safe slots in standalone tests.
- [tightbbox-survives-offscreen-qt](pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt.md) [matplotlib][bbox][export][clipboard][offscreen] — Axes.get_tightbbox returns usable coords under QT_QPA_PLATFORM=offscreen; default to bbox crop with a degenerate-rect fallback, not to full-canvas grab.
- [defer-retry-from-worker-failed-slot](pyqt-ui/2026-04-25-defer-retry-from-worker-failed-slot.md) [qthread][worker][retry][qtimer][re-entry-guard] — Synchronous retry from a queued worker-failed handler hits the host's isRunning re-entry guard; defer with QTimer.singleShot(0) so thread.finished clears the ref first.
- [conditional-visibility-init-sync-and-paired-field-children](pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md) [visibility][init][qformlayout][paired-field][isHidden][inspector] — Conditional-visibility helpers must run once at __init__ end to seed initial state, and must propagate setVisible to paired-field children so per-widget isHidden() stays honest.
- [action-button-on-group-title-needs-qframe-header](pyqt-ui/2026-04-26-action-button-on-group-title-needs-qframe-header.md) [groupbox][title][header][action-button][layout][inspector][wa-styledbackground] — Use QFrame[label+stretch+button] for inline-action titles; pair every wrapper QFrame with a QSS objectName rule or QFrame{bg:#fff} re-polishes white.
- [inspector-content-max-width-and-tinted-card-bleed](pyqt-ui/2026-04-26-inspector-content-max-width-and-tinted-card-bleed.md) [layout][inspector][splitter][qframe][wa-styledbackground][max-width][rework-risk] — Splitter-pane content must cap maxWidth + left-anchor; wrapper QFrames need paired QSS; setFixedSize on tool buttons needs scoped QSS to escape global QPushButton sizing.
- [popover-accept-deactivate-race](pyqt-ui/2026-04-26-popover-accept-deactivate-race.md) [qdialog][accept][reject][windowdeactivate][race][idempotency][popover][focus-out][offscreen] — QDialog.done is not idempotent; auto-reject on WindowDeactivate after accept silently flips result. Add _is_closing guard in accept/reject and drive the race manually in offscreen tests.

## refactor

- [cross-layer-constant-promote-to-package-root](refactor/2026-04-22-cross-layer-constant-promote-to-package-root.md) [layering][constants][dependency-rules] — When two layers forbidden from importing each other share a constant, hoist it to the package root, do not duplicate it.
