# Decomposition — FFT/Order "compute vs display" root-cause fix + 4 structural measures

- **Date:** 2026-06-21
- **Mode:** plan
- **Top-level request:** Root-fix the "drag color-scale ≠ recompute" bug class
  across FFT line / FFT-vs-Time / Order, plus structural measures A–D. Strict
  TDD. Baseline: 2349 non-slow passed.
- **Skill invoked:** `superpowers:writing-plans` (>3 dispatches, deep
  cross-module coupling). Plan path attached in return `notes`.

## Routing principle applied

The dominant risk is NOT mis-routing — it is **same-file / shared-git-index
collision** (lesson `parallel-mutators-share-git-index-even-disjoint-files`)
and **contract-change call-site coupling** (lesson
`return-type-change-needs-paired-callsite-update`). Frozen dataclass
`SpectrogramParams` / `COTParams` are contracts; every cache-key call site,
every serializer (batch / preset IO / project IO), and the canvas `_result_db_token`
memo are implicit consumers and MUST move with the contract. Therefore items
are grouped into **serial phases by file-cluster**, not split per numbered
issue. Within a phase the same expert owns the whole cluster so no two
mutators contend on the same `.py`.

Surface-vs-computation rule: dB-matrix math, cache keys, dataclass contracts,
and the dB helper are **computation** → `signal-processing-expert`. Tooltips,
inspector spin echo, color-scale `display-only` invariant tests, preset-load
guards in the contextual panels, and the canvas display branch are **surface /
fixtures** → `pyqt-ui-engineer`. Where the canvas dB *conversion* itself is the
numeric concern (item ⑥ delete-clip, item ⑦ helper convergence in
`heatmap_canvas.py`) it is bundled with the signal cluster that owns the helper,
because splitting the same file across two experts is exactly the false-rework
trap.

## Decomposition table

| # | subtask | expert | depends_on | rationale |
|---|---|---|---|---|
| P0 | Skill gate: emit a written plan (`superpowers:writing-plans`) before any dispatch | main Claude (skill) | — | >3 dispatches + deep coupling; plan must sequence the phases and the contract-change blast radius |
| P1 (=C, ⑦) | Converge all dB conversion onto one `amplitude_to_db` helper (floor=tiny, absolute ref, ref<=0 caller-guarded); replace the 4+ divergent copies | signal-processing-expert | P0 | dB helper is numeric correctness; it is the foundation every later dB path reads. Single helper first = no churn later |
| P2 (=B, ⑥) | Delete the `np.clip(m_disp,...)` + peak-ref dB branch in `heatmap_canvas.py`; extend the manual `z_auto=False` display-only invariant test to every heatmap canvas branch | signal-processing-expert (canvas dB math) + pyqt-ui-engineer (invariant UI tests) | P1 | The clip/peak-ref form is numeric (same shape as 7c27071); the canvas file is shared with P3, so same expert owns the math edit. The cross-canvas invariant assertions are UI fixtures |
| P3 (=A, ①③④⑨) | Make frozen `SpectrogramParams`/`COTParams` the sole "compute-param" definition; derive cache keys from the dataclass; remove `db_reference` from `SpectrogramParams` + 5 keys; add fs to fft compute key; add `window` to order key; guard test (every field read by compute, no display-only field) | signal-processing-expert | P1, P2 | Cache-key + dataclass contract = computation. Contract change → bundle ALL consumers (batch, preset IO, project IO, canvas memo) in one node to avoid cross-specialist false-rework |
| P4 (=D, ① part, ④) | Single cache-invalidation entry `_invalidate_all_analysis_caches_for_fid`; route rebuild/Fs-change/close through it; fallback key reuses main key func | signal-processing-expert | P3 | Same mixin/window cluster as P3; serial with P3 because both touch the `_*_mixin.py` family + `window.py:1233` |
| P5 (=②) | COT actually consumes `time_res` → derive hop via angle-domain mapping (honor tooltip); keep `time_res` in cache key | signal-processing-expert | P3 | Numeric algorithm change in `order_cot.py`; key already in P3's dataclass scope, so sequence after P3 to avoid re-touching the key |
| P6 (=③ canvas, ⑤) | Canvas dB conversion reads inspector current `db_reference` (mirror Order path); add `if 'weighting' in d` guard to `_apply_preset_values` in the 3 contextual panels | pyqt-ui-engineer | P3 (db_reference removed from compute), P5 | Inspector echo + preset-load guard + canvas display branch = surface/contextual panels. Depends on P3 so the display-only contract is settled first |
| P7 (=⑧, ②-tooltip) | UI/doc annotation of the Welch −3 dB caliber difference + tooltip update for COT `time_res`; lock current numbers with a test | pyqt-ui-engineer | P5 | No numeric change — annotation + tooltip + characterization test. After P5 so tooltip matches the now-real `time_res` behavior |

## Phase ordering rationale (serial unless noted)

```
P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7
        (C)   (B)   (A)   (D)   (②)  (③⑤) (⑧)
```

- **P1 first:** the dB helper is read by P2/P3/P6; landing it first means later
  phases import the converged helper rather than re-touching divergent copies.
- **P2 before P3:** both touch `heatmap_canvas.py`; do the clip-deletion +
  invariant test while the file is open, before the cache-key refactor reaches
  the same file's `_result_db_token` memo.
- **P3 before P4/P5/P6:** the dataclass contract is the spine. P4 (invalidation)
  and P5 (`time_res`) edit the same mixin/`order_cot.py` cluster; P6 needs the
  `db_reference`-is-display-only contract finalized.
- **P6/P7 are the only nodes a different expert (pyqt-ui) may own** and they run
  AFTER all signal nodes, so no UI/signal node ever co-edits a file in the same
  wave. The one shared-file risk (`heatmap_canvas.py`) is contained inside the
  signal cluster (P1/P2/P3); P6's canvas edit is the display-branch only —
  enumerate forbidden symbols in the brief so it cannot drift into the dB-math
  lines P1/P2 own.

## Cross-specialist same-file watch (rework pre-empt)

`heatmap_canvas.py` is touched by P2 (delete clip), P3 (memo key), P6 (display
db_reference read). All three are inside one expert's hands EXCEPT P6 (pyqt).
P6's brief MUST forbid the `amplitude_to_db` / clip / `_result_db_token` lines
and restrict it to the inspector-`db_reference`-read display path. If P6 returns
`files_changed` overlapping P2/P3 dB-math symbols → genuine rework, escalate.

The 3 `contextual_*.py` panels are touched only by P6 (preset guard + canvas
wiring) → no overlap with signal nodes.

## Lessons consulted (step 4)

- `docs/lessons-learned/signal-processing/2026-04-25-cache-consumer-must-be-grepped-not-just-surface.md`
- `docs/lessons-learned/pyqt-ui/2026-06-21-display-param-guard-vs-preset-load.md`
- `docs/lessons-learned/pyqt-ui/2026-06-11-cache-key-stability-id-reuse-and-param-roundtrip.md`
- `docs/lessons-learned/pyqt-ui/2026-06-11-slice-must-read-same-display-matrix-as-heatmap.md`
- `docs/lessons-learned/pyqt-ui/2026-06-21-heatmap-auto-level-absolute-vs-relative.md`
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`
- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
