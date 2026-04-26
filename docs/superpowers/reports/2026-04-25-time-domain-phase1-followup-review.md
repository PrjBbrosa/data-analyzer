# Time-Domain Phase 1 Follow-Up Review

Date: 2026-04-25
Reviewer chain: superpowers:code-reviewer (Phase A), superpowers:code-reviewer (Phase B), 5-agent cross-cutting review (this round)
Scope reviewed: full session diff for the 2026-04-25 time-domain plot performance refactor (canvases.py, main_window.py, tests/ui/test_envelope.py, tests/ui/test_xlim_refresh.py, 5 lessons, .state.yml).

## Summary

Phase 1 items 1–6 of `docs/superpowers/reports/2026-04-25-time-domain-plot-performance-report.md` have been implemented. 89/89 tests green, UI smoke verified. After cross-cutting review with five parallel agents and confidence scoring, **one finding crossed the publish threshold (≥80)** and is documented below. All other findings (process-compliance gaps, defensive hardening, comment/spec wording deviations, pre-existing lines) scored below threshold and are listed for completeness without action items.

## Confirmed Finding

### F-1 (blocker, score 90) — `_is_monotonic` cache is never consumed; `_envelope` runs `np.all(np.diff(t) >= 0)` on every viewport refresh

**Where**

- Cache method definition: `mf4_analyzer/ui/canvases.py:588` (`TimeDomainCanvas._is_monotonic(self, t, custom_xaxis_fid=None, custom_xaxis_ch=None)`).
- Invalidation API: `mf4_analyzer/ui/canvases.py:703` (`invalidate_monotonicity_cache`), wired at 5 sites in `mf4_analyzer/ui/main_window.py` (sites 1, 2a, 2b, 3, 5 of the cache-invalidation map).
- Actual call site `_envelope` uses: `mf4_analyzer/ui/canvases.py:439`

```python
if n_total >= 2 and not _is_monotonic_array(t):
    return self._ds_legacy(t, sig)
```

**Evidence of dead code**

`grep "self\\._is_monotonic\\b" mf4_analyzer/` — 0 matches. The cached method is never called from anywhere. `_is_monotonic_array(t)` is the module-level uncached helper; it allocates `np.diff(t)` and scans the full array every invocation.

**Why this matters**

The Phase 1 spec (item 6) calls out monotonicity caching specifically to avoid this per-frame cost:

> `np.all(np.diff(t) >= 0)` allocates `diff` and scans the whole array. At tens of millions of samples this is not free and would otherwise run on every viewport refresh. Compute it once per `(custom_xaxis_fid, custom_xaxis_ch)` and cache the boolean.

The cache infrastructure is plumbed correctly (storage + invalidation), but the consumption path was never connected. For a 48 kHz / multi-minute capture (millions of samples), every `xlim_changed → _refresh_visible_data → _envelope` chain incurs an O(n) scan that the cache exists to skip. Functionally the plot is still correct; the smoothness improvement claimed by the report's "Expected Impact" section is partially under-delivered for long captures with many viewport changes.

**How it slipped past the prior reviews**

- Phase A code review verified the cache *exists* and *invalidates* correctly. It did not verify the cache is *consumed* on the hot path.
- Phase B code review verified the new wiring (debounce, release flush, set_data refresh) without re-auditing the inherited Phase A surface.
- Tests cover monotonicity-cache hits and invalidations directly via `_is_monotonic`, so the cache is exercised in tests but not from production callers.

This is the second instance in this session of "verified surface, unverified consumer" — the first was the Phase A boundary leak captured in `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`. Both share a root cause: reviewers narrate diffs against the brief frame instead of grepping for end-to-end paths.

**Two acceptable fix shapes**

The follow-up specialist may choose either; both are local to `canvases.py`.

- **Shape (a) — pass keys into `_envelope`.** Add `*, custom_xaxis_fid=None, custom_xaxis_ch=None` to `_envelope` (and the corresponding kwarg flow through `_envelope_cached` / `_refresh_visible_data`). Inside `_envelope`, call `self._is_monotonic(t, custom_xaxis_fid, custom_xaxis_ch)` instead of `_is_monotonic_array(t)`. For the default-time-axis case (where there is no custom-x channel), pass `None` for `custom_xaxis_ch` and let the cached method either short-circuit (default time axes are guaranteed monotonic by mdf semantics) or store the result keyed by `(fid, None)`.

- **Shape (b) — stash per-channel monotonicity at plot_channels build time.** In `plot_channels`, compute `is_monotonic_t` once when the channel is bound to a Line2D and store it in a parallel dict `_channel_is_monotonic[name]`. `_refresh_visible_data` reads from this dict and passes a precomputed `is_monotonic: Optional[bool]` kwarg into `_envelope`. `_envelope`'s contract becomes: if `is_monotonic` is supplied, trust it; otherwise fall back to the uncached scan as a safety net. Invalidate the new dict in `clear()` and on the same events that already invalidate `_channel_data_id`.

Shape (a) reuses existing cache infrastructure but expands the `_envelope` signature; shape (b) is a smaller surface change and avoids growing `_envelope`'s parameter list. Either is acceptable; shape (b) is marginally simpler.

## Below-threshold findings (informational, no action required this round)

| Source | Score | Description | Why below threshold |
|---|---|---|---|
| Reviewer A | 75 | Per-pair `cause: rework` lessons not written for (S1, S2) test_envelope.py overlap and (S1, S3) canvases.py overlap. | A meta-lesson (`silent-boundary-leak-bypasses-rework-detection.md`) names the same experts and files and captures the more general failure mode; literal CLAUDE.md compliance is incomplete but the substantive insight is recorded. |
| Reviewer A | 10 | Skills `superpowers:test-driven-development` and `superpowers:verification-before-completion` not invoked. | False positive — the reviewer cannot see Skill tool invocations from outside the session. Both were invoked. |
| Reviewer B | 50 | `_disconnect_xlim_listener` does not null `self._primary_xaxis_ax`. | Currently only called from `clear()` (which nulls the field at line 235) and from inside `_connect_xlim_listener` (defensive disconnect-before-reconnect, where the field is overwritten immediately). No dangling-axes path exists today. |
| Reviewer B | 35 | `_envelope_cached` returns shared cache views; `.copy()` on store would harden API. | Matplotlib `set_data` copies internally; statistics path reads from `channel_data` not the cache. Hardening, not a bug. |
| Reviewer C | 30 | No artifact shows the executor ran the mandated `grep -nE` forbidden-symbol pre-check. | Process-compliance gap, not a code defect; the new orchestrator lesson already captures the protocol — the gap is in operationalization. |
| Reviewer C | 25 | No `shared_files` field in decomposition plan JSON. | Same — process-compliance, not code. |
| Reviewer C | 35 | AC#5 silently degrades for legacy 6-tuple `plot_channels` callers. | No production caller uses the 6-tuple form (`main_window.plot_time` always passes the 7-tuple with `data_id`). Latent compatibility concern only. |
| Reviewer D | 30 | `fd.channels.append(name)` at `main_window.py:624` has no dedup guard. | Pre-existing line, not modified by this session. Out of scope. |
| Reviewer D | 25 | Comment around `_primary_xaxis_ax.bbox.width` imprecisely conflates twinx-shared-bbox with sharex-equal-width. | Documentation nit; does not affect runtime. |
| Reviewer E | 35 | `_on_release` flush does not cover keyboard pan (no `button_release_event` fires). | Spec only mandates mouse-release flush; keyboard pan is not in scope for Phase 1. |
| Reviewer E | 35 | Comment "Phase 1 items 2 + 5" at `canvases.py:171` mistags item 5 — that block is item 2 only. | Comment-only; harmless. |
| Reviewer E | 30 | Fallback comment in `_refresh_visible_data` conflates `data_id is None` with non-monotonic. | Comment-only. |
| Reviewer E | 15 | rcParams applied at module import rather than `__init__`. | Spec body explicitly permits "module scope or in `__init__`"; the module-import choice is correct (idempotent, single-application). False-positive against the section header alone. |

## Recommended action

Single follow-up subtask, dispatched to `signal-processing-expert` under the squad runbook with TDD discipline:

- Wire `_envelope`'s monotonicity check through `self._is_monotonic` (shape a or b — specialist's choice).
- Add a regression test asserting that, for a captured-and-cached default time axis, repeated `_envelope` / `_envelope_cached` calls do NOT re-run `np.diff(t)` (e.g. by patching `_is_monotonic_array` to count calls and asserting one-shot semantics across multiple refreshes).
- Add a regression test asserting that on a fresh `invalidate_monotonicity_cache(custom_xaxis_fid=fid)`, the next refresh recomputes (cache miss).
- Forbidden during this fix: any change to plot wiring (xlim debounce, button_release flush, rcParams), to the LRU envelope cache class, or to `main_window.py`. The fix is local to `canvases.py` (and the test file).

Phase 2 / Phase 3 of the original report remain out of scope.
