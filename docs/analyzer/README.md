# Analyzer Documentation

This folder is the canonical home for MF4 Data Analyzer product and feature
documentation.

## Routing

| Area | Path | Use for |
| --- | --- | --- |
| Acquisition | `docs/analyzer/acquisition/` | CAN/XCP/data-acquisition feasibility reports, P0/P1 plans, runbooks, hardware notes, and acquisition-specific reviews. |
| User guide | `docs/analyzer/user-guide/` | Published user-facing guide files and rendered QA artifacts. |
| UI prototypes | `docs/analyzer/ui-prototypes/` | HTML mockups, visual references, screenshots, and interaction option demos. |
| Reviews | `docs/analyzer/reviews/` | Analyzer code reviews, re-reviews, execution reports, and follow-up audit artifacts. |

Published guide entry points:

- Analyzer guide: `docs/analyzer/user-guide/user-guide.html`
- Acquisition Cockpit guide: `docs/analyzer/user-guide/acquisition-cockpit-guide.html`

## Acquisition Rule

Acquisition already has its own feature area. Keep related future files there:

- plans: `docs/analyzer/acquisition/plans/`
- runbooks: `docs/analyzer/acquisition/`
- reviews: `docs/analyzer/acquisition/reviews/` if the review is specific to acquisition
- shared analyzer reviews: `docs/analyzer/reviews/`

## Legacy Workflow Docs

Do not move historical `docs/superpowers/` files unless a dedicated migration is
requested. They remain useful as prior implementation records, while new
analyzer-facing artifacts should point to this folder structure.
