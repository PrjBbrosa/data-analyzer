---
task: "FFT plot Y-axis label to Chinese ('幅值') and amplitude-scaling normalization sanity check"
date: 2026-04-22
updated: 2026-04-22
---

# Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| Change FFT plot Y-axis label from `'Amplitude'` to `'幅值'` at `MF4 Data Analyzer V1.py` line 2038, and review line 2173 (RPM-side FFT) for consistency; update if it is the same visual context. | pyqt-ui-engineer | (none) | Pure label/text change on matplotlib axis inside Qt embedded canvas. Keywords `label`, `axis`, `canvas` map to `pyqt-ui-engineer`. Surface-level concern (text rendered to user), not a computation, so UI specialist wins even though `FFT` appears in context. |
| Sanity-check amplitude normalization in `FFTAnalyzer.compute_fft` around line 247 (`amp = 2 * np.abs(fft_r[:nh]) / n / np.mean(w)`). Verify `/ np.mean(w)` correctly compensates for window mean amplitude loss. Return `status: done` with `tests_run` demonstrating the normalization (e.g., pure sine → amplitude recovered within tolerance across window types), or `needs_info` if ambiguous. Do NOT change code if correct. | signal-processing-expert | (none) | FFT amplitude scaling, window compensation, Welch-adjacent — all squarely in `signal-processing-expert` domain per routing table. Explicit read-only sanity check, still requires a test (numerical proof), consistent with the TDD contract. |

# Notes

- Two subtasks, both parallelizable — no `depends_on` edges. UI edit touches display code (~L2038/L2173); sig-proc check touches/reads computation code (~L247). No `files_changed` overlap expected.
- UI specialist must NOT change numeric code; sig-proc specialist must NOT change labels. Cross-bleed would trigger rework detection.
- Sig-proc return contract: if normalization is correct, `status: done`, no code change, `files_changed: []`, `tests_run` populated with the sanity harness. If normalization is wrong or ambiguous, return `needs_info` with the discrepancy — do NOT self-dispatch a fix without user confirmation (user said "don't change it if it's already correct").
- UI specialist should decide on line 2173 based on whether it is the same FFT visualization context (consistency) or a different chart type with different semantics (leave alone). That judgment is theirs, not the orchestrator's.
- No keyword overlap ambiguity — `label` / `axis` for subtask 1, `FFT` / `amplitude` / `window` for subtask 2.
- Applicable lesson: `orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md` — this is plan mode; return the plan-mode contract, not the aggregation contract.
