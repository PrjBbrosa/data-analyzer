# Decomposition — FFT Welch short-signal zero-spectrum bug fix

- Date: 2026-06-13
- Mode: plan
- Top-level request: 修复 FFT「线性平均」(Welch) 路径的 bug：当 n < nfft 时
  `compute_averaged_fft` 返回全 0 谱线。根因已由 main Claude 用
  systematic-debugging 定位（`mf4_analyzer/signal/fft.py`
  `compute_averaged_fft`，约 178-209 行），不要重复诊断。

## Classification

Pure numeric algorithm bug fix in `mf4_analyzer/signal/fft.py`. Body-changing
numeric-correctness work with a TDD-first requirement → single specialist,
`signal-processing-expert`. No UI surface, no module relocation, no
cross-package import work. No keyword overlap that warrants a split.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| TDD-first fix of `compute_averaged_fft` short-signal (n < nfft) all-zero spectrum via `effective_nfft = min(nfft, n)`, rebuilding `freq`/`psd_sum`/window from the effective length; red test first, existing n>=nfft Welch tests stay green | signal-processing-expert | — | Numeric DSP correctness in `signal/fft.py`; roster maps FFT/Welch/window/nfft to signal-processing-expert; body change with TDD-first owner per the non-DSP-routing lesson |

Single node — no `depends_on` edges, no parallelization, no rework surface
(only one specialist touches only `fft.py` + its test file).

## Call-site / contract check

`compute_averaged_fft`'s return SHAPE is unchanged: still
`(freq, amp, psd)`. The fix only changes the LENGTH of those arrays in the
previously-broken n < nfft case (from `nfft//2` zeros to `effective_nfft//2`
real values). No return-type widening, so the
`return-type-change-needs-paired-callsite-update` lesson does not force a
bundled call-site subtask. The brief still instructs the specialist to grep
callers of `compute_averaged_fft` and confirm none of them assume a fixed
`nfft//2` output length (e.g. zip against a separately-computed `nfft`-length
freq axis); if a caller does, fold the guard into the same brief rather than
flag it.

## Lessons consulted

- docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md
- docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md
- docs/lessons-learned/signal-processing/2026-05-19-branch-reached-is-not-behavior-correct.md
- docs/lessons-learned/signal-processing/2026-06-12-unrealized-viewbox-width-phantom-decimates-small-traces.md
