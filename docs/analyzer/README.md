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
- TraceLab 7.6 release notes: `docs/analyzer/user-guide/tracelab-v7.6-release-notes.md`

## Current Product Baseline

The current baseline is TraceLab 7.6. Its user-facing changes include generic
ASCII (`.asc`) import, waveform-based NI TDMS (`.tdms`) import, and up to 12
time-domain Views with responsive compact/overflow tab handling. Update the
published guides when these behaviours change; do not treat `.tdms_index` as a
data file or describe ASCII/TDMS timing as guessed.

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
