---
id: codex-plan-spec-literal-evidence
status: active
owners: [codex]
keywords: [plan, spec, rev, checklist, needs-rework, partial, correction-list, exact-identifiers, batch-blocks, rpm_order, fft_time]
paths: [docs/superpowers/plans/*, docs/superpowers/specs/*, docs/superpowers/reports/*]
checks: [rg -n, nl -ba]
tests: []
---

# Codex Plan And Spec Literal Evidence

Trigger: Load for plan/spec reviews, rev-fix verification, checklist reviews, or any request that asks whether a plan/spec can proceed to implementation.

Past failure: Plans looked fixed after adding new text while stale sections, retired identifiers, or mismatched test snippets remained elsewhere; marking these as resolved produced false green lights.

Rule: Absence of explicit evidence is a review result. Preserve exact identifiers from the prompt, read the whole requested artifact set, grep for retired names and stale section references, and mark ambiguous or missing fixes as `partial`, `needs revision before plan`, or `NEEDS REWORK` according to the user's vocabulary.

Verification: Build a checklist keyed to the user's item numbers before drafting, then do a second pass for stale identifiers such as retired method names, section labels, widget classes, precision snippets, and test names.
