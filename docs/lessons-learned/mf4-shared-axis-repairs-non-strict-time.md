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
`diff(t) > 0` and otherwise dropped the whole channel, for every numeric
dtype, with no skipped-channel notice.

Rule: Do not drop an MF4 numeric channel because its timestamps repeat or step
backward. Collapse exact duplicate times (keep the last sample), stable-sort
backward steps, and interpolate onto the longest prepared axis. Record
non-numeric, empty, and unreadable channels in `skipped_channels`. Time
masters are the X axis, not signal columns.

Verification: `tests/test_mf4_loader.py` covers duplicate timestamps, a
backward step, same-count different clocks, and a non-numeric skip.
