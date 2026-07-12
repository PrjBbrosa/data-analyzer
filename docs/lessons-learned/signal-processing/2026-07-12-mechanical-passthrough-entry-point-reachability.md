---
role: signal-processing
tags: [batch, entry-point, dead-code, qdialog, boundary, reachability, mechanical-passthrough]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

# A boundary-refused "entry point" fix may leave the only LIVE path unfixed

## Context

Plan Task 9 named two "Batch entry points" for the same mechanical
constructor-kwarg pass-through (inject a catalog snapshot into
`BatchRunner(...)`): `MainWindow.open_batch()` (`window.py`, a plain
method) and `BatchSheet._on_run_clicked()` (`sheet.py`, a `QDialog`
subclass). The hard boundary correctly allowed editing the former and
refused the latter. Tracing reachability afterward showed
`open_batch()`'s `if dlg.exec_() != QDialog.Accepted: return` guard can
only pass when something calls `self.accept()`, and `BatchSheet` never
does (`_btn_cancel` wires to `reject`; `_on_run_clicked` starts its own
async `BatchRunnerThread` and never `accept()`s the dialog) — so the
`BatchRunner(self.files)` call inside `open_batch()` the plan pointed at
is dead code. The actual live Run path is entirely inside the `QDialog`
method the boundary rule required flagging instead.

## Lesson

A plan that lists two call sites as symmetric "entry points" for one
mechanical fix can be asymmetric in RUNTIME REACHABILITY — one may be
dead code already superseded by the other. Doing the allowed edit and
flagging the refused one can look like complete, proportionate coverage
in a diff review while the actual live behavior stays entirely broken,
because the fixed call site never executes.

## How to apply

Before treating "fixed the allowed site + flagged the refused site" as
sufficient, trace whether the allowed edit's call site is reachable at
all (e.g., does the guarding `dlg.exec_() != Accepted` ever return
False? grep the dialog class for `.accept()`/`.done()` call sites). If
the allowed edit turns out to be dead code, say so explicitly in the
flag text so the receiving specialist understands the real fix is
entirely theirs, not an optional duplicate of something already done.
