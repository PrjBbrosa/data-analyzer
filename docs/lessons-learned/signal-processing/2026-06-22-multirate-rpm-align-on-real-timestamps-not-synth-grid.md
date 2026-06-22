---
role: signal-processing
tags: [order, cot, rpm, multirate, resample, interp, time-base, eps, upsample]
created: 2026-06-22
updated: 2026-06-22
cause: insight
supersedes: []
---

# Multi-rate motor-speed alignment must interpolate on REAL timestamps, never the synthesized fallback grid

## Context

Order (COT) panes dropped any pane whose motor-speed channel length differed
from the signal length (`_order_rpm_for` returned `None` → "缺转速"), blocking
the common EPS multi-rate case (signal 48 kHz, motor speed 1 kHz). The fix
upsamples the speed channel onto the signal time axis via
`np.interp(t_sig, t_rpm, rpm)`. The COT core (`order_cot.py`) is already
sample-rate agnostic; the only hard constraint is three equal-length, same
time-base arrays.

## Lesson

`_dispatch_order_job` synthesizes a uniform `np.arange(n)/fs` time grid
(`t_arr`) ONLY when the real timestamps are degenerate, and feeds that to the
COT job. The speed-alignment `t_sig`, however, must be the REAL signal
timestamps (`t` from `_order_sig_for`), because the speed channel's own axis
`t_rpm` is in physical seconds — interpolating onto a synthesized grid that
doesn't equal the real timestamps would silently misalign the order base. This
stays self-consistent only because alignment is gated on STRICTLY increasing
`t_sig` AND `t_rpm`: when `t` is degenerate (so `t_arr` would diverge from it),
the guard returns `None` and the pane is skipped instead of computing on a
mismatched pair. Never downsample the wideband signal to the speed rate (it
would crush the Nyquist band and lose high orders).

## How to apply

When adding any "align channel B onto channel A's axis" resample in the order
path: pass the RAW signal time axis (not the degenerate-fallback uniform grid)
as the interpolation target, and guard both axes for strict monotonicity +
finiteness, returning `None` (skip) on failure. TDD with a linear speed ramp:
assert exact reproduction over the OVERLAPPING span and accept `np.interp`'s
endpoint clamp past the last speed sample (don't assert the naive ramp formula
over the non-overlapping tail).
