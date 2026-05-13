---
id: codex-analyzer-doc-routing
status: active
owners: [codex]
keywords: [docs, analyzer, acquisition, reviews, routing, file-paths]
paths: [docs/README.md, docs/analyzer/**, docs/lessons-learned/codex-review-report-contract.md]
checks: [rg -n old docs paths, find docs/analyzer]
tests: []
---

# Codex Analyzer Doc Routing

Trigger: Creating, moving, or referencing analyzer-facing documentation and review artifacts.

Past failure: Analyzer documents were scattered across top-level `docs/`
folders such as `docs/data acquisition`, `docs/code-reviews`, `docs/report`,
`docs/reports`, `docs/ui-preview`, and `docs/ui-previews`, so new work could
easily point future reviews or plans back to stale locations.

Rule: Put new analyzer-facing artifacts under `docs/analyzer/`. Put
acquisition-specific feasibility reports, plans, runbooks, and reviews under
`docs/analyzer/acquisition/`; put shared analyzer review artifacts under
`docs/analyzer/reviews/`. Keep `docs/superpowers/` as the historical workflow
archive unless a dedicated migration is requested.

Verification: Run a path scan such as
`rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs`
and confirm new references use `docs/analyzer/`.
