---
role: pyqt-ui
tags: [visibility, init, qformlayout, paired-field, isHidden, inspector, reparent, shared-widget, per-mode-state, chk_range]
created: 2026-04-26
updated: 2026-06-14
cause: insight
supersedes: []
---

## Context

While compactifying the Inspector, three QFormLayout rows became
conditional (xaxis 通道 row, range 开始/结束 row, FFT-time 频率上下限 row).
A unit test asserted `spin_start.isHidden() == True` on a freshly
constructed `PersistentTop` whose `chk_range` defaulted to unchecked,
and the assertion failed — even though the row was visually hidden in
the running app.

## Lesson

Two distinct traps stack on top of each other for conditional-visibility
rows in PyQt5:

1. **Initial-state sync.** Visibility helpers wired only to a
   `toggled`/`currentIndexChanged` signal do not run before the user (or
   a programmatic `setChecked`) actually fires that signal. The widget
   keeps its constructor-default visibility until then, and any
   reset/snapshot/test that inspects the widget pre-show observes a
   "dirty" half-shown state. Fix: invoke the visibility helper once at
   the end of `__init__` (or `_wire`) with the current control value, so
   the row is correctly hidden/shown before `show()` is ever reached.

2. **Paired-field children keep their own `WA_WState_Hidden` flag.**
   When the form field is a `_pair_field(spin_a, label, spin_b)` host
   wrapping multiple inner widgets, `host.setVisible(False)` hides the
   wrapper but leaves each inner spin's *own* hidden flag untouched, so
   `spin_a.isHidden()` keeps returning `False` even though the user sees
   nothing. `isHidden()` reflects an explicit per-widget flag, not the
   parent's visibility. Fix: have the row-toggle helper iterate the
   wrapper's direct child widgets and propagate the visibility flag to
   each, so per-widget `isHidden()` is honest.

## How to apply

When introducing a conditional QFormLayout row whose field is either a
single widget or a `_pair_field` wrapper:

- At the end of `__init__` (after `_wire`), call the visibility helper
  once with the current control value — never rely on the toggled signal
  alone for initial state.
- If the field is a `_pair_field` (or any container wrapping multiple
  controls), make sure the helper propagates `setVisible` to direct
  children too — a wrapper-only toggle silently breaks downstream
  `isHidden()` checks (tests, snapshot diffs, and any code branching on
  per-widget visibility).
- Mirror the helper across all conditional rows in the same widget
  family (we now hide range, xaxis-channel, and FFT-time freq rows the
  same way) — a missing initial sync on any of them is a latent timing
  bomb that only surfaces when a snapshot/test runs before the first
  toggle.

## 2026-06-14 addendum — shared/reparented checkbox leaks state across modes

The same `chk_range` QCheckBox is a SINGLE instance reparented across
time/fft/fft_time/order modes (`inspector._place_range_group_for_mode`).
An FFT time-window region drag routed through `set_range_from_span`,
which force-checks the box so the FFT compute (gated on
`PersistentTop.range_enabled()`) uses the dragged window — but because
the *instance* is shared, the checked flag leaked into Time-Domain the
moment the user switched back.

Lesson: a reparented control carries ONE checked/visibility flag for ALL
modes; "each mode keeps its own intent" cannot be expressed by the widget
alone. Decouple by snapshotting the outgoing mode's state and restoring
the incoming mode's at the single reparent point
(`PersistentTop.checkout_range_for_mode(mode)` called from
`_place_range_group_for_mode`), defaulting unknown modes to unchecked.

How to apply: when a stateful widget (checkbox, spin, combo) is shared by
reparenting across N contexts, do NOT rely on the widget to remember
per-context state — keep a `{mode: value}` dict on the owner and
save-old/restore-new at the switch boundary. Restore with `blockSignals`
(the mode switch drives its own replot pipeline, and any `toggled` slot
wired in MainWindow must not fire spuriously), and re-run the conditional
row-visibility helper for the restored value so the paired-field
`isHidden()` sync stays honest. Pin it with a regression that drives the
LIVE handler (`MainWindow._on_fft_preview_range_changed`) in FFT mode then
switches back to time and asserts `not range_enabled()` — it must FAIL on
the pre-fix code.
