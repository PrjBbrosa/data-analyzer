---
id: mf4-shared-axis-repairs-non-strict-time
status: active
owners: [codex]
keywords: [MF4, MDF, load_mf4, timestamps, duplicate time, interpolation]
paths:
  - mf4_analyzer/io/loader.py
checks:
  - rg -n "np.all\\(np.diff\\(d\\['t'\\]\\) > 0\\)" mf4_analyzer/io/loader.py
tests:
  - QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/test_mf4_loader.py -q
---

# MF4 Shared Axis Repairs Non-Strict Time

Trigger: Changing `DataLoader.load_mf4` or any shared-time alignment that
decides which MF4/MDF channels reach the channel list.

Past failure: A CANape MF4 showed two channels because five numeric ECU
signals shared a raster with two duplicate timestamps. The loader required
`diff(t) > 0` and otherwise dropped the whole channel. A later revision
sorted backward steps, which kept only the later segment of a clock reset.

Rule: Collapse exact duplicate MF4 timestamps and keep the last sample.
Reject a backward step as `time-regression` instead of sorting it onto one
axis. Interpolate onto the longest prepared axis only when the ranges
overlap, and record range loss, endpoint fill, and skips. Time masters are
the X axis, not signal columns.

Verification: `tests/test_mf4_loader.py` covers duplicate timestamps, clock
reset rejection, coverage loss, no-overlap, and single-sample rules.
