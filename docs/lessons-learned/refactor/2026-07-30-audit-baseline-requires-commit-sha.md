---
id: refactor/2026-07-30-audit-baseline-requires-commit-sha
status: active
owners: [codex]
keywords: [audit, baseline, git-sha, reproducibility, evidence, drift]
paths: [docs/robustness-audit-2026-07-30.md]
checks: [git rev-parse HEAD]
tests: []
---

# An actionable audit needs a fixed commit SHA

Trigger: A robustness, architecture, or refactor audit reports source counts,
line locations, probes, priorities, or remediation estimates.

Past failure: Headline counts from the first robustness audit drifted or were
wrong when re-measured. Without a fixed source SHA, reviewers could not tell
whether the report, the code, or both had changed.

Rule: Put the full Git commit SHA, version, platform, runtime dependencies, and
probe method in the audit baseline. Re-run every claimed count and reproduction
against that exact Git object before implementation begins.

Verification: Record `git rev-parse HEAD`, execute the appendix commands
verbatim, and paste numeric results into the implementation plan's baseline log.
