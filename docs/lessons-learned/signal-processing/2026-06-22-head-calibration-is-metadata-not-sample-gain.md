---
role: signal-processing
tags: [hdf, head, loader, calibration, metadata, scaling, eps, zero-multiply, test-locks-bug]
created: 2026-06-22
updated: 2026-06-22
cause: insight
supersedes: []
---

# HEAD .hdf `calibration` is display metadata, not a sample gain — and cal=0 is the bug's tell

## Context

`DataLoader.load_hdf` applied `s = c.samples * float(c.calibration)`, assuming
the HEAD `calibration` field was a per-channel gain on the raw samples. But HEAD
FLOAT32 samples are ALREADY physical engineering values; `calibration` is
metadata. The multiply blew up EPS steering-angle (±694° → 8e4°), motor speed
(±73°/s → 2500), torque and acoustic/vibration channels.

## Lesson

The smoking gun for a "metadata mistaken for gain" bug is a `calibration=0.0`
channel: the multiply silently zeroed real non-zero data (e.g. `Com_RPS_Speed (C`
±311 → all-zero) while the all-NaN drop guard still passed it through, so the
channel survived but was hollowed out. A field being present in the parser does
NOT make it a compute input — only the loader multiplied; the `channel_metadata`
copy and FFT/A-weighting (`weighting.py`) never consumed the product, so dropping
the multiply has no downstream blast radius. The existing loader test
`assert_allclose(..., acc * 2.0)` was asserting the BUG, not the contract.

## How to apply

Before treating any per-channel scalar (`calibration`, `factor`, `scale`) as a
multiplicative gain, check whether the samples are already physical (HEAD
FLOAT32 are) and whether a `=0` value would nonsensically annihilate real data —
that zero case is the fastest disproof. Keep such fields as metadata only. When
removing a gain multiply, grep every `.<field>` / `'<field>'` site first to
confirm no downstream (FFT/audio/export) reads the product, and fix any test
that asserts the pre-fix scaled value (it locks the bug).
