---
id: 2026-08-14-can-log-probe-sample-and-lazy-zoh
status: active
owners: [codex]
keywords: [blf, asc, canoe, dbc, probe, zoh, cantools, LazyZohFrame]
paths: [mf4_analyzer/io/blf_format.py, mf4_analyzer/io/asc_can_format.py, tests/test_blf_loader.py, tests/test_asc_can_loader.py]
checks: [PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/test_asc_can_loader.py -q]
tests: [tests/test_blf_loader.py, tests/test_asc_can_loader.py]
---

# CAN Log Probe Samples Decode And Defers ZOH

Trigger: Changing BLF/CANoe ASC import, DBC probe strength, or the shared-time ZOH assemble that turns CAN signals into a FileData table.

Past failure: Large CANoe logs were fully decoded once to rank DBC candidates and again to load, then every signal was ZOH-expanded onto the longest message axis before any channel was plotted. Using `sample_decoded / total_frames` for probe strength turned a correct DBC into a weak match as soon as decode was capped.

Rule: Probe payload decode is a sample (`_PROBE_DECODE_CAP`); ID overlap still scans every frame. Scale decoded counts from the sample success rate, never `sample_decoded / total_frames`. Keep per-signal event series through import and ZOH only when a column is read. Do not decode from scratch on channel check.

Verification: Large in-memory frame lists must decode fewer than `_PROBE_DECODE_CAP` payloads and still report strong/weak correctly. `load_blf` must not call `_zoh_resample` until a cross-rate column is accessed. Run `PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/test_asc_can_loader.py -q`.
