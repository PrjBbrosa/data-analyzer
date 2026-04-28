---
cause: planning-gap
date: 2026-04-28
experts: [refactor-architect, pyqt-ui-engineer]
overlapping_files: [mf4_analyzer/ui/drawers/batch/sheet.py]
tags: [routing, decomposition, return-type, downstream-coupling]
related_run: 2026-04-28-remove-order-track-feature
---

# Return-type contract change requires paired call-site adaptation

## What happened

Order-track removal squad. S4 (refactor-architect) was given `mf4_analyzer/batch_preset_io.py` to add a whitelist filter that gracefully skips legacy `order_track` presets. The cleanest implementation changed `load_preset_from_json`'s return type from `AnalysisPreset` to `AnalysisPreset | None` (None = "preset references a method no longer in `SUPPORTED_METHODS`, skip silently").

Original decomposition plan put `sheet.py` in S4's scope but did NOT explicitly authorize S4 to add a None-guard at the call site. S4 stayed inside boundary discipline, raised a `flagged[]` entry to pyqt-ui-engineer, and returned. Wave-C dispatch (S3, pyqt-ui-engineer, originally only main_window + canvases comments) had its brief expanded mid-execution to include the sheet.py one-line guard.

Net effect: same file (`sheet.py`) was touched by two specialists across two waves. Mechanical rework detection fires (S4=refactor, S3=pyqt, both touched `sheet.py`). But this isn't rework — it's downstream call-site coupling that the plan failed to anticipate as a single coherent unit of work.

## Root cause

When a refactor changes a function's **return-type contract** (e.g. `T → T | None`, or adding/removing an exception type, or widening an enum), every call site is implicitly part of the change. Original decomposition treated the call site (`BatchSheet._on_import_preset`) as a separate concern owned by a different specialist, when it should have been bundled with the contract change.

## Rule

When decomposing a task whose contract surface includes a return-type narrowing/widening:

1. **List call sites in the brief.** The orchestrator should grep call sites of the function whose return type is changing, and either (a) include them in the same specialist's scope with explicit authorization, or (b) factor them out as a properly-sequenced subtask with `depends_on` set.

2. **Don't rely on `flagged[]` for predictable downstream couplings.** `flagged[]` is for surprises — issues a specialist discovers mid-execution that the planner couldn't have known. Return-type contract widening is NOT a surprise; it's a known consequence of the design choice. Plan it.

3. **Cross-specialist boundary on the same file is acceptable when authorized.** What's not acceptable is forcing a flag round-trip when the coupling is foreseeable. The "boundary discipline" forbidden-symbol enumeration should explicitly call out: "this file MAY also be touched by you to add a one-line None-guard for the new return contract."

## How to apply

Decomposition checklist for any subtask whose `symbols_touched` is expected to include a function-return-type change:

- [ ] Grep callers of the changed function (`grep -rn "<funcname>(" mf4_analyzer/ tests/`).
- [ ] For each caller, decide: (a) bundle into this subtask's scope with explicit authorization, (b) factor out as a sequenced subtask, or (c) document why the caller doesn't need adaptation.
- [ ] In the brief's "files in scope" section, list every caller-touched file alongside the canonical change site.
- [ ] In the brief's "forbidden" section, explicitly carve out the call-site adaptation from the boundary fence.

## Why this matters

Mechanical rework detection misclassifies planned-but-unforeseen-coupling as rework. The lesson corpus drifts toward false positives. Plus, flag round-trips burn one specialist dispatch cycle per coupling (~5-10 minutes wall time each). Two of these per run is the cost of one wave.

## Verbatim flag from S4 (verbatim, for reference)

> "load_preset_from_json now returns AnalysisPreset | None (None signals 'skip legacy method' per the silent-skip filter). BatchSheet._on_import_preset (mf4_analyzer/ui/drawers/batch/sheet.py:365) currently calls self.apply_preset(preset) and preset.name unconditionally — needs an `if preset is None: self._toast('preset 中的方法不再被支持，已跳过', kind='warning'); return` guard so the UI surfaces a friendly toast rather than an AttributeError when a user imports a legacy order_track preset. Refactor-architect deliberately did NOT add this guard to stay within the 'no behaviour changes' boundary; the unit-level contract (does-not-raise) is satisfied at the loader layer."

The flag was correct boundary-keeping behavior. The planning gap was upstream of the specialist.
