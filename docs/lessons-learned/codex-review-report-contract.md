---
id: codex-review-report-contract
status: active
owners: [codex]
keywords: [review, code-review, plan-review, spec-review, commit-review, report, citation, evidence, verdict, stdout]
paths: [docs/code-reviews/*, docs/superpowers/*, mf4_analyzer/*, tests/*]
checks: [git show --name-status --oneline, rg -n, nl -ba, rg -n '^## ']
tests: []
---

# Codex Review Report Contract

Trigger: Load for review-only tasks in this repository, especially when the user asks for a code review, plan review, spec review, commit review, exact citations, fixed verdict vocabulary, or a single markdown report.

Past failure: Review output became untrustworthy when it used plausible summaries, broad grep output, stale prompt baselines, or a rewritten report shape instead of exact source evidence and the user's requested contract.

Rule: Treat reviews as evidence artifacts. Read the relevant files before drafting findings, preserve the user's headings/verdict tokens/stdout contract, cite exact file:line or explicit grep/git output for every substantive claim, and write only the requested report file unless the user broadens scope.

Verification: Start commit reviews with `git show --name-status --oneline <sha>`, use `nl -ba` and `rg -n` for cited evidence, name exact negative-evidence scopes, then re-read the report and check required headings or line budgets before finalizing.
