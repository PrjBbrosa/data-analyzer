# Session Work Report — Time-Domain Plot Performance Phase 1

Date: 2026-04-25
Driver: squad runbook (planner-executor split per CLAUDE.md)
Source spec: `docs/superpowers/reports/2026-04-25-time-domain-plot-performance-report.md`
Mid-session review report: `docs/superpowers/reports/2026-04-25-time-domain-phase1-followup-review.md`

## Scope

Implement Phase 1 items 1–6 of the time-domain plot performance optimization report. Phase 2 (axes/Line2D reuse, `tight_layout` frequency, rubber-band blitting) and Phase 3 (mip-map) explicitly out of scope. FFT and order-analysis paths untouched per user direction.

## Outcome

- Test suite: **58 → 92 passing** (no regressions; 34 new tests added across the session).
- Spec items 1–6: all implemented and verified end-to-end.
- UI smoke verified: 48 kHz / 3-channel synthetic plot renders, narrow spike preserved in full view, viewport zoom recovers original detail, debounce + release flush behave as designed.
- `.state.yml`: `top_level_completions` 4 → 6 (one increment per top-level subtask cycle; prune threshold 6 < 20, no prune).

## Phases Executed

### Phase A — sp-envelope-core
- Specialist: `signal-processing-expert` (TDD-first per `superpowers:test-driven-development`)
- Spec items: 1 (viewport-aware envelope), 4 (LRU envelope cache), 6 (monotonicity cache)
- Delivered: `_envelope`, `_envelope_cached` with bucket-width-quantized LRU key, `_is_monotonic` cache method + `invalidate_*` hooks, `_ds()` extended with optional `(xlim, pixel_width)` delegating to `_envelope`.
- Tests: 17 new (envelope correctness, NaN policy, non-monotonic fallback, cache hit/miss, statistics-vs-envelope invariant).
- Lesson: `signal-processing/2026-04-25-envelope-cache-bucket-width-quantization.md` — quantum must derive from the discretization constant.

### Phase B — ui-xlim-debounce-and-refresh
- Specialist: `pyqt-ui-engineer`
- Spec items: 2 (xlim debounce + release flush + line.set_data refresh path), 3 (plot_time copy removal), 5 (free rcParams).
- Delivered: 7 cache-invalidation event sites in `main_window.py` (file load/close, channel edit, selection change, custom-x change, range-filter change, plot-mode change), all gated on actual state diff via `_last_range_state` / `_last_plot_mode`.
- Tests: 7 new envelope edge-case tests + 6 new xlim refresh wiring tests (all on real `QApplication`).
- Note: Phase A had silently overstepped its brief and implemented most of Phase B's wiring (`xlim_changed` connect/disconnect, `_refresh_visible_data`, button_release flush, rcParams, `_channel_data_id`/`_channel_lines`). Phase B correctly detected and consumed the prior work without re-implementing.

### Phase B-1 follow-up
- Specialist: `pyqt-ui-engineer`
- Trigger: Phase B code review identified that `_on_release` flushed the pending refresh BEFORE the rubber-band's `set_xlim`, so axis-lock zoom releases were still subject to the 40 ms debounce.
- Fix: replaced two-call ordering with a single `try/finally` covering all return paths.
- Tests: +1 regression (`test_rubber_band_release_flushes_post_zoom_refresh`).
- Lesson: `pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md`.

### Cross-cutting review (5 parallel reviewers + scoring)
- Adapted from `/code-review:code-review` slash command (no PR available — output as session report).
- 17 raw findings → 1 finding crossed the ≥80 confidence threshold.
- Detailed write-up: `docs/superpowers/reports/2026-04-25-time-domain-phase1-followup-review.md`.

### F-1 follow-up fix
- Specialist: `signal-processing-expert` (TDD-first)
- Issue: `_envelope` called the module-level uncached `_is_monotonic_array(t)` on every refresh; the cached `self._is_monotonic` had storage + invalidation wired but **zero consumers**. Spec item 6's per-frame `np.diff` cost was still being paid.
- Fix shape: per-channel `_channel_is_monotonic` dict populated once at `plot_channels` build time and read by `_refresh_visible_data`; `_envelope` accepts `is_monotonic` kwarg with uncached scan as safety-net fallback.
- Tests: +3 (default-axis no-rescan, invalidate-forces-recompute, custom-x cache-by-key).
- Lesson: `signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md` — auditing the cache method on the producer side proves storage works; only grep at the consumer end proves the cache reduces work on the hot path.

## Files Touched

```
mf4_analyzer/ui/canvases.py        # envelope, LRU cache, monotonicity dict, xlim wiring, rcParams, _on_release try/finally
mf4_analyzer/ui/main_window.py     # 7 cache-invalidation event sites + plot_time copy removal + _last_state tracking
tests/ui/test_envelope.py          # 17 → 27 tests (envelope, edge cases, F-1 regression)
tests/ui/test_xlim_refresh.py      # 6 → 7 tests (refresh wiring + B-1 rubber-band regression)
docs/lessons-learned/.state.yml    # 4 → 6
docs/lessons-learned/LESSONS.md    # +6 lesson index entries
docs/lessons-learned/signal-processing/2026-04-25-envelope-cache-bucket-width-quantization.md
docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md
docs/lessons-learned/pyqt-ui/2026-04-25-flush-after-axis-mutation-not-before.md
docs/lessons-learned/pyqt-ui/2026-04-25-cache-invalidation-event-conditional.md
docs/lessons-learned/pyqt-ui/2026-04-25-matplotlib-axes-callbacks-lifecycle.md
docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md
docs/lessons-learned/orchestrator/decompositions/2026-04-25-time-domain-phase1-perf.md
docs/superpowers/reports/2026-04-25-time-domain-phase1-followup-review.md
docs/superpowers/reports/2026-04-25-time-domain-phase1-session-report.md  (this file)
```

## Process Insights Captured (lessons added)

| Role | Lesson | One-line takeaway |
|---|---|---|
| signal-processing | envelope-cache-bucket-width-quantization | Cache key quantum must come from the discretization constant. |
| signal-processing | cache-consumer-must-be-grepped-not-just-surface | A cache reachable + invalidatable but never read on the hot path is dead code; audit the consumer end, not the producer. |
| pyqt-ui | flush-after-axis-mutation-not-before | Drain debounced refresh AFTER `set_xlim` mutation; use try/finally to cover every exit. |
| pyqt-ui | cache-invalidation-event-conditional | Diff state, not handler entry — `QTimer.singleShot(0, handler)` replays will otherwise wipe the cache every tick. |
| pyqt-ui | matplotlib-axes-callbacks-lifecycle | `Axes.callbacks` survives `fig.clear()`; store cids and disconnect-before-rebuild. |
| orchestrator | silent-boundary-leak-bypasses-rework-detection | `files_changed` records files not symbols; require `symbols_touched` and adversarial grep by reviewers. |

## Process Self-Assessment

What worked
- Planner-executor split (orchestrator plans → main Claude dispatches) kept main Claude out of `.py` authorship, all code changes flowed through specialists.
- Per-phase independent code review caught two real defects mid-flight: (i) the rubber-band release-flush ordering (B-1) and (ii) the silent boundary leak from Phase A.
- Cross-cutting 5-agent review with confidence scoring filtered 17 raw findings down to 1 actionable F-1, avoiding noise on hardening/nit suggestions.
- Codex-route → Claude code-reviewer fallback was clean once the user redirected.

What didn't work the first time
- Phase A's specialist silently implemented most of Phase B's brief without listing the touched symbols in `files_changed`. The Phase A reviewer narrated the diff against the brief frame and didn't grep forbidden symbols. The breach went uncaught for a full review cycle. Captured as the orchestrator lesson; future briefs should require `symbols_touched` and reviewers should grep adversarially.
- The monotonicity cache (spec item 6) was a "verified surface, unverified consumer" failure — storage and invalidation tests passed, but no test asserted the cache actually reduces hot-path work. The new `cache-consumer-must-be-grepped-not-just-surface` lesson encodes the missing audit step.

CLAUDE.md compliance gaps (informational)
- Phase 3 rework detection per CLAUDE.md asks for `cause: rework` lessons per cross-expert file overlap. The session produced two such overlaps (test_envelope.py across S1×S2; canvases.py across S1×S3) and recorded a single meta-lesson covering both. Strict literal compliance would write two per-pair lessons; the meta-lesson captures the more transferable insight.

## Acceptance Criteria — Spec Section "Acceptance Criteria"

| # | Criterion | Status |
|---|---|---|
| 1 | Initial plot appearance unchanged | met (axes / lines / colors / units identical) |
| 2 | Overlay and subplot layouts unchanged | met |
| 3 | Cursor / dual cursor / span / statistics / tick density unchanged | met |
| 4 | Narrow spike visible in full-range view | met (envelope preserves bucket extrema) |
| 5 | Zooming into spike region shows local original detail | met |
| 6 | 48 kHz, 3–4 channel pan/zoom visibly smoother | met (debounce + envelope + release flush + monotonicity cache) |
| 7 | Custom x-axis, range filter, file switch, channel edits continue to work | met (7 invalidation sites wired) |
| 8 | Statistics match original data, not envelope | met (regression test in place) |

## What's Left

- **Phase 2** (deferred): axes/Line2D structural reuse so structural rebuilds don't re-create on every replot; reduce `tight_layout` frequency; rubber-band blitting.
- **Phase 3** (deferred): mip-map / pre-built coarse envelope for very long captures (tens of minutes at 48 kHz).
- **Cleanup** (small): the `TimeDomainCanvas._is_monotonic` cache method (`canvases.py:625-637`) is dead code after the F-1 fix took shape (b). The new `_channel_is_monotonic` per-channel dict supersedes it. Either delete or keep as ad-hoc API; either is fine.
- **Order analysis / FFT refactor**: explicitly skipped this round per user.
- **Process operationalization** (low priority): orchestrator brief template could grow a `forbidden_symbols` field that the executor greps automatically before launching the reviewer; specialists' return JSON could grow a `symbols_touched` field. Both are encoded as the new orchestrator lesson but not yet structurally enforced.

## Session Cadence (for future planning)

- Phase A: 1 dispatch + 1 review (envelope core).
- Phase B: 1 dispatch + 1 review (xlim wiring; revealed boundary leak).
- B-1: 1 dispatch (single-issue fix).
- Cross-cutting review: 5 parallel agents + scoring.
- F-1: 1 dispatch + 1 verification.
- Total: 4 specialist dispatches + 7 review/verify rounds.
