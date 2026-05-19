---
role: refactor
tags: [defaults, fallback, observability, silent-failure, ui-contract, backend, dependency-injection]
created: 2026-05-19
updated: 2026-05-19
cause: insight
supersedes: []
---

# Default-constructed fallback dependencies must announce themselves

## Context

Cockpit `__init__` had `self._backend: RecorderBackend = backend or FakeRecorderBackend()`. The intent was "tests inject a backend; production gets fake until Vector wiring lands." Vector wiring landed (PR-2's `VectorXcpRecorderBackend` class), but nothing ever constructed it at runtime — the `or FakeRecorderBackend()` branch quietly remained the only path. Settings → Transport stored a `TransportConfig` that no record-time code read back. Operators could configure app_name / channel / bitrate, click Record, and get a synthetic sine-wave MF4 — visually identical to a real recording. There was no warning chip, no status message, no exit code. The fallback was indistinguishable from the primary path until you opened the MF4 in Analyzer and saw it was the demo signals.

Symptom-side, three independent things had to be true for the silent failure to take over: (a) the production backend class existed in a different module than the constructor default, (b) the operator-controlled config flowed to a private field but never to a constructor, (c) the fallback type was functionally valid (`FakeRecorderBackend` implements the full `RecorderBackend` protocol). Each individual line of code looked fine in review.

## Lesson

Whenever a default-constructed dependency does something *functionally different* from the primary one — fake vs. real, mock transport vs. live transport, in-memory vs. on-disk — the runtime must publish which path it took. `backend or FakeBackend()` is fine; the danger is when the call site that picks the path never tells anyone. The signal can be lightweight: a status-bar `[FAKE backend]` prefix, a chip-state property, a structured log line — but it has to fire **on the path that activates the fallback**, not on the path that explains what was intended.

T1-3's fix is the pattern: `_maybe_swap_to_vector_backend()` checks the preconditions (isinstance Fake / transport set / ifdata set / pool non-empty) and either swaps to Vector or emits `[FAKE backend] 不录真实 ECU: <reason>` to the status bar — naming the missing precondition. The operator can no longer not-notice. Tests assert the message text contains the precondition tag.

## How to apply

When wiring up a dependency that has a no-op / synthetic / mock default constructor:
1. The default must satisfy the protocol so test injection works (this is fine).
2. At the runtime moment the fallback is chosen (record start, request fire, etc.), emit a user- or log-visible signal naming **why** the primary path was unreachable. Status bar, chip text, structured log — pick one and assert it in tests.
3. When the dependency is selectable by injection, gate the auto-swap with `isinstance(self._dep, FallbackType)` so caller-injected overrides survive untouched. Never swap a non-Fake injection.
