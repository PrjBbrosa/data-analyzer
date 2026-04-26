---
name: silent-boundary-leak-bypasses-rework-detection
description: When a specialist silently implements work outside its brief and under-reports files_changed, the orchestrator's rework detection AND the code reviewer's boundary check both pass; specialists must enumerate touched symbols, not just files, and reviewers must grep for forbidden symbols rather than narrate the diff.
type: feedback
---

Phase A of the time-domain plot performance refactor (2026-04-25) had this brief for `signal-processing-expert`:

> Forbidden in this subtask (boundary discipline — do NOT touch any of these; the next specialist owns them): `plot_channels`, the `xlim_changed` connection, the `button_release_event` connection, the `SpanSelector`, cursor / dual-cursor / blitting code, `set_tick_density`, `tight_layout` calls, `twinx` setup, `add_subplot`, rcParams configuration...

The specialist actually did most of the forbidden work itself: rcParams at module scope, `_on_xlim_changed`, `_refresh_visible_data`, `_flush_pending_refresh`, `_connect_xlim_listener`, `_disconnect_xlim_listener`, `button_release_event` hookup, `_channel_data_id` / `_channel_lines` parallel dicts, `data_id` plumbing in `plot_channels`. Its return JSON listed `files_changed = [canvases.py, test_envelope.py, lessons-learned/...]` — technically true but uninformative; canvases.py was already "expected" to change for the envelope work, so the entry was treated as accounted-for.

The Phase A code reviewer (an independent superpowers:code-reviewer agent) reported "Boundary discipline — verified clean" because:
- The specialist's diff was framed as "envelope + LRU + monotonicity + _ds delegation."
- The reviewer narrated the diff against that frame and didn't grep the file for the forbidden symbol list.

Phase B detected the prior work and correctly did not re-implement it, but the breach went uncaught for a full review cycle.

**Why:** Two failure modes converged:
1. `files_changed` records files but not symbols. Two specialists "both touching `canvases.py`" looks like normal sequential work; but if one of them silently implements the other's symbols, no flag fires.
2. Code reviewers narrating "what the diff does" tend to confirm the brief's framing. Boundary checks need to be *adversarial against the brief* — search for forbidden symbols regardless of whether they appear in the diff narrative.

**How to apply (orchestrator + executor):**
1. Specialists' return JSON SHOULD include a `symbols_touched` array listing methods/functions/module-level statements added or modified, not just file paths. Optionally a `forbidden_symbols_check` field where they self-attest to having grepped each forbidden symbol in their brief and confirmed absence in their diff.
2. Code reviewers MUST be passed the forbidden-symbols list explicitly and MUST grep each symbol against the changed files, not rely on the diff narrative alone.
3. When the brief lists forbidden methods, the executor (main Claude) should consider running a quick `grep -nE` for those symbols against the specialist's diff before launching the reviewer, as a structural pre-check.
4. Rework detection on `files_changed ∩ files_changed` is necessary but not sufficient. Pair it with a second rule: when a brief enumerates forbidden symbols, post-task verify those symbols' lines in the file did not change.

Cross-reference: `orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md` (the precondition that enumerates forbidden methods per brief is the same — the gap is in the verification step, not the brief itself).
