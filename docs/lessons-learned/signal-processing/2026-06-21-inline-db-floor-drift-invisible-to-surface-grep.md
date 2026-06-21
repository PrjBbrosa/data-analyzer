---
role: signal-processing
tags: [dB, floor, convergence, helper, amplitude, semantic-drift]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

# Inline dB floor constants silently diverge across call sites

## Context

Three production sites all implemented `20*log10(...)` independently. Two used
`np.clip(amp, 1e-12, None)` (floor ~-240 dB @ref=1) and one used
`np.maximum(amp, np.finfo(float).tiny)` (floor ~-6153 dB @ref=1). Reading either
alone looks like "prevent log(0)"; the difference is invisible without side-by-side
comparison.

## Lesson

A 5 000 dB divergence between `1e-12` and `tiny` floors is undetectable by grep
on individual call sites and transparent for in-range data — only sub-floor signals
would reveal it. Converging to a single helper eliminates the drift without changing
any in-range output.

## How to apply

When a formula like `20*log10(...)` appears ≥ 2 times: grep ALL call sites and
compare floor constants explicitly before deciding they are equivalent. Write a
spy-based TDD test (`monkeypatch` + call count) that goes RED on the inline code
and GREEN only after the delegation is wired — this is the only reliable way to
verify the convergence at the call site rather than just at the helper.
