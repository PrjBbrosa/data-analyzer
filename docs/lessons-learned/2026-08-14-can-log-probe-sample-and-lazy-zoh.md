---
id: 2026-08-14-can-log-probe-sample-and-lazy-zoh
status: active
owners: [codex]
keywords: [blf, asc, canoe, dbc, probe, zoh, cantools, LazyZohFrame, ChannelFrame]
paths: [mf4_analyzer/io/blf_format.py, mf4_analyzer/io/asc_can_format.py, mf4_analyzer/io/channel_frame.py, tests/test_blf_loader.py, tests/test_asc_can_loader.py, tests/test_channel_frame.py]
checks: [PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/test_asc_can_loader.py tests/test_channel_frame.py -q]
tests: [tests/test_blf_loader.py, tests/test_asc_can_loader.py, tests/test_channel_frame.py]
---

# CAN Log Probe Samples Decode And Defers ZOH

Trigger: Changing BLF/CANoe ASC import, DBC probe strength, ChannelFrame/lazy ZOH assemble, or UI copy that reports decoded frame counts.

Past failure: Large CANoe logs were fully decoded once to rank DBC candidates and again to load, then every signal was ZOH-expanded onto the longest message axis before any channel was plotted. Using `sample_decoded / total_frames` for probe strength turned a correct DBC into a weak match as soon as decode was capped. A later probe then linearly scaled sample hits into a fake exact `decoded_frame_count`, and the UI showed `帧 estimated/total`.

Rule: Probe payload decode stays a bounded sample (`_PROBE_DECODE_CAP`); ID overlap may still scan every frame. Keep exact totals, sample counts, and optional estimates as separate fields. Never scale sample success into a displayed exact `帧 A/B`. UI may show `完整匹配 A/B` and/or `抽样解码 C/D (x%)`. `load_blf()` returns `ChannelFrame`, not pandas; callers that need a DataFrame opt in with `load_blf_dataframe()`. Keep per-signal event series through import and ZOH only when a column is read. Do not decode from scratch on channel check.

Verification: Large in-memory frame lists must decode fewer than `_PROBE_DECODE_CAP` payloads and still report strong/weak correctly. UI/model tests must reject `帧 estimated/total`. `load_blf` must not call `_zoh_resample` until a cross-rate column is accessed. Run `PYTHONPATH=. .venv/bin/python -m pytest tests/test_blf_loader.py tests/test_asc_can_loader.py tests/test_channel_frame.py -q`.
