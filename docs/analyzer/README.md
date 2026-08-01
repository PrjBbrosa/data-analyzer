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
| Diagnostics | `docs/analyzer/diagnostics.md` | Runtime log locations, retention, environment overrides, and support collection. |

Published guide entry points:

- Analyzer guide: `docs/analyzer/user-guide/user-guide.html`
- Acquisition Cockpit guide: `docs/analyzer/user-guide/acquisition-cockpit-guide.html`
- TraceLab 7.7 release notes (archive): `docs/analyzer/user-guide/tracelab-v7.7-release-notes.md`
- TraceLab 7.6 release notes (archive): `docs/analyzer/user-guide/tracelab-v7.6-release-notes.md`

## Current Product Baseline

The current baseline is TraceLab 7.9.1. It retains the 7.6 ASCII (`.asc`),
NI TDMS (`.tdms`), and 12-View changes, as well as the native WinWert (`.wwt`),
ZFGE2/TestRunPRO (`.zfd`), and MATLAB (`.mat`) imports introduced in 7.7.
7.8 added a draft-based channel configuration manager with View matching
preview, JSON import/export, and keep/replace/skip conflict handling. Separate
full and Analyzer-only Windows packages remain available. 7.9 makes precision-
touchpad Ctrl/Shift zoom symmetric across analysis views, restores bidirectional
Y-axis scaling in overlay mode, and tightens dense-plot interaction budgets.
7.9.1 refines batch input and image-export workflows, and resolves time-domain
custom X axes independently per source while preserving source-level failure
diagnostics.
Update the published guides when these behaviours change; preserve each loader's
timing and unit boundaries instead of describing inferred metadata as measured
truth.

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
