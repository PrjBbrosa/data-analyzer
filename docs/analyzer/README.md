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
| Plans | `docs/analyzer/plans/` | Feature/execution plans for analyzer work (acquisition plans stay in their own area). |
| Specs | `docs/analyzer/specs/` | Feature design specs and technical decision records. |
| Diagnostics | `docs/analyzer/diagnostics.md` | Runtime log locations, retention, environment overrides, and support collection. |

Published guide entry points:

- Analyzer guide: `docs/analyzer/user-guide/user-guide.html`
- Acquisition Cockpit guide: `docs/analyzer/user-guide/acquisition-cockpit-guide.html`
- TraceLab 7.7 release notes (archive): `docs/analyzer/user-guide/tracelab-v7.7-release-notes.md`
- TraceLab 7.6 release notes (archive): `docs/analyzer/user-guide/tracelab-v7.6-release-notes.md`

## Current Product Baseline

The current baseline is TraceLab 8.1.0. It retains the 7.6 ASCII (`.asc`),
NI TDMS (`.tdms`), and 12-View changes, as well as the native WinWert (`.wwt`),
ZFGE2/TestRunPRO (`.zfd`), and MATLAB (`.mat`) imports introduced in 7.7.
7.8 added a draft-based channel configuration manager with View matching
preview, JSON import/export, and keep/replace/skip conflict handling. Separate
full and Analyzer-only Windows packages remain available. 7.9 makes precision-
touchpad Ctrl/Shift zoom symmetric across analysis views, restores bidirectional
Y-axis scaling in overlay mode, and tightens dense-plot interaction budgets.
7.9.1 refines batch input and image-export workflows, and resolves time-domain
custom X axes independently per source while preserving source-level failure
diagnostics. 7.9.2 fits the batch panel and its preview window to the available
screen so the footer actions stay reachable on a laptop, tightens the panel's
two header rows, and ranks the batch action buttons through the global
primary/accent/destructive roles. 7.9.2 also adds optional slice export to
Batch FFT-vs-Time and Order-vs-Time: one fixed-time or fixed-frequency/order
dimension with up to four overlaid positions, an extra chart row on the
exported PNG, and a compact slice workbook that replaces the full long-format
data file when the toggle is on (off leaves both byte-identical to before);
the same pass also fixes time-domain chart-statistics extrema markers to
render at their intended on-canvas size. 7.9.3 pairs a uniquely named RPM
signal from another batch source with the selected order-analysis signal, so
multi-rate inputs can be aligned on time instead of failing source lookup.
Its batch heatmap exports also add a translucent red highlight band behind each
slice marker while preserving the curve-matched centre line. 7.9.4 moves the
COT order spectrogram's supporting points onto an evenly spaced *time* grid
(ArtemiS Step Size semantics) instead of hopping through the angle domain, so
frame centres land on multiples of the requested time resolution and a batch
slice at t=10 s hits 10.000 s exactly; the reported coverage now spans only the
analysed range, so the time axis no longer implies data outside it. The batch
representative-image preview also surfaces the renderer's slice clamp/merge
warnings instead of dropping them. 7.9.5 recovers complete HEAD HDF channel
names from the file's extended-name field, shows their full text in channel-tree
tooltips while middle-eliding long rows, and limits analysis signal pickers and
the time-domain X viewport to sources attached to the current View. TimeDomain
rendering now uses measured on-screen ink to govern envelope downsampling,
anti-aliasing, and raster-cache admission, with a frame-time fallback for
unexpected expensive paints. The Cocoa acceptance gate passed; Windows ink
threshold recalibration remains a separate release gate. The same release also
repairs the covered right corners of combo boxes and standardises them at 7 px.
7.9.6 adds single-analysis and Batch FRF system identification with explicit
input/output pairing, H1/H2 transfer estimates, magnitude/phase/coherence
panels, and CSV/PNG/manifest output. 7.9.7 then unifies the analysis and Batch
control surfaces, simplifies parameters that did not alter the default
calculation, and completes FRF's shared frequency interactions: linked
single/dual cursor readouts, physical-Hz log ticks, and the same point-markup
and clear controls as TimeDomain. Current-View file removal is also available
while analysis modes are active. 7.9.8 gives every analysis View its own
attached-file scope — new Views start empty, switching restores each View's own
scope, and copying a View is what inherits the full configuration — and
upgrades the file-pane link button into a composable file-scope follow menu:
attach new loads to the active context, inherit file scope on newly created
Views, and fill an empty analysis View from the TimeDomain focus on mode entry.
With attach-on-load enabled, loading while an analysis section is active now
attaches to that section's active View instead of the background TimeDomain
View. Batch sheets accept drag-and-drop file intake and reuse the main-window
BLF+DBC pairing dialogs for disk imports. 8.0 adds UltraView as a read-only,
multi-Board comparison workspace for existing Time, FFT, FFT-vs-Time, FRF,
and Order Views. It supports template and 12-column free-grid layouts, direct
card manipulation, canvas zoom/pan/minimap navigation, per-Board undo/redo,
project persistence, and PNG export without recomputing or mutating source
Views. Project saves use atomic replacement, restored source-bearing analysis
Views are recomputed across inactive tabs, and large BLF/ASC imports avoid
eagerly materializing one dense shared table.
8.0.1 refines UltraView exports to fit their populated free-grid content,
centres fit cards vertically while preserving the captured preview ratio, and
uses right-drag for canvas panning while left-drag continues to box-select. In
the Time workspace, channels can be dragged into the current View or its X band,
and the left-side file/channel order now determines both subplot and overlay
ordering.
8.1.0 establishes the current product release baseline and synchronizes the
application title, published guides, and Windows Full/Analyzer package defaults.
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
