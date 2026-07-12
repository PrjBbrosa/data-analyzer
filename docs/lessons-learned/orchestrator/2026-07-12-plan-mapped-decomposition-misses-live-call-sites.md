# Plan-mapped decomposition misses cross-cutting live call sites — budget for dispatcher follow-ups

Date: 2026-07-12
Cause: decomposition
Task: dB reference defaults implementation (12 subtasks mapped 1:1 to plan Task 0–11/10A)

## What happened

The decomposition mapped subtasks 1:1 onto an already-detailed implementation plan's
task list, inheriting the plan's **named file lists** as each expert's authorization
boundary. Execution surfaced three gaps that were all the same failure shape —
a contract landed in the named files, but the *live call site* that makes it real
sat outside them:

1. Task 7 shipped per-source heatmap labels, but `window.py`'s
   `_render_cached_heatmap` (view-switch/project-open restore path) wasn't in
   Task 7's file list → dispatched as PART A of Task 8.
2. Task 9 injected the Batch catalog snapshot at `window.py open_batch()` — which
   turned out to be **dead code** (`dlg.exec_()` never returns Accepted); the live
   Run path lives in `BatchSheet._on_run_clicked` (a QDialog, outside the signal
   expert's boundary) → dispatched as PART A of Task 10.
3. Task 10A registered the nudge + predicate, but the HintState feed pattern
   actually lives in `chart_stack/cards.py` (not `window.py` as briefed), outside
   the authorized list → dedicated follow-up dispatch with explicit file-authorization
   expansion.

All three were caught because experts **flagged instead of scope-creeping**, and the
dispatcher folded each fix into the next same-expert task (or a small follow-up)
without breaking the serial chain. Net cost: +1 dispatch, zero rework.

## Why

A plan's per-task file list enumerates where the *new* code goes, not where the
existing behavior is *actually reachable from*. Entry-point reachability (dead vs
live call sites), restore/cache-hit paths, and cross-layer feed patterns routinely
live one file outside the list. Boundary discipline then correctly blocks the expert.

## How to apply

- When decomposing from a plan, treat each task's file list as the **write set**,
  and have the brief explicitly ask: "if the live call site / feed point is outside
  this list, FLAG it — do not expand scope."
- Dispatcher: expect ~1 flagged live-call-site gap per 3–4 consumer-wiring tasks;
  fold the fix into the next task owned by the right expert (PART A pattern) instead
  of re-planning.
- For anything injected at an entry point, the receiving brief should require a
  reachability check ("prove this constructor call is on the live path"), per
  signal-processing/2026-07-12-mechanical-passthrough-entry-point-reachability.md.
