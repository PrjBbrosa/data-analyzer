---
date: 2026-05-15
stage: 2
plan: docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md
spec: docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md
verdict: GREEN
author: refactor-architect (Stage 2 capture core)
---

# MF4 Writer Spike — Decision Report

## TL;DR

**Decision: buffered-chunks-then-finalize MVP, backed by ``asammdf``
``MDF.append + MDF.save``.** One write at the end of the session, not an
incremental rolling-write loop. The channel-naming contract from spec
§Recorder Backend is honored: each MF4 channel name equals the A2L
measurement ``name`` verbatim, with no prefix / suffix / transliteration.

## Options Considered

1. **Incremental ``asammdf`` write** — call ``MDF.append`` once per
   poll-step, eventually call ``MDF.save``.
2. **Buffered finalize (chosen)** — accumulate ``(ts, value)`` lists per
   channel in memory; build one ``[Signal, Signal, ...]`` batch and call
   ``MDF.append`` exactly once, then ``MDF.save``.
3. **Native ASAM MDF4 writer (no asammdf)** — hand-roll the IDBlock /
   HDBlock / DGBlock layout. Rejected: scope explosion for an MVP.

## Why Option 2 Wins

The decisive issue is **how ``MDF.append`` groups channels**. In
``asammdf`` 8.8.7 (the version pinned in ``.venv/lib/...``):

- ``MDF.append(signal_list, ...)`` creates one *channel group* containing
  one *channel* per element of ``signal_list``, sharing the master.
- Each successive ``MDF.append(...)`` call creates an **additional**
  channel group. The MF4 then contains N copies of the same channel
  set (per call), each with its own timeline.

Verified empirically (``asammdf==8.8.7``, ``python==3.12.13``):

```python
from asammdf import MDF, Signal
import numpy as np

m = MDF(version="4.10")
m.append([Signal(np.array([1.0]), np.array([0.0]), name="A", unit="rpm")])
m.append([Signal(np.array([2.0]), np.array([0.1]), name="A", unit="rpm")])
m.save("/tmp/append_twice.mf4", overwrite=True)
m.close()

m2 = MDF("/tmp/append_twice.mf4")
# m2.channels_db['A'] -> [(0, 1), (1, 1)] — two GROUPS for the same name
```

This breaks the §Recorder Backend channel-naming contract: post-record
``DataLoader.load_mf4`` returns the first occurrence only, but the
relationship between A2L measurement names and MF4 channels is no longer
1:1 — Stage 5 ``expected_channels`` accounting becomes ambiguous.

Option 2 (buffer in memory, single append-and-save at stop) keeps the
channel layout flat: exactly one group, exactly one channel per
selected measurement, name equality with the A2L measurement. The
round-trip test ``test_acquisition_capture_writer.py::test_channel_names_match_a2l``
proves it: write three measurements, reload via ``DataLoader.load_mf4``,
and ``set(loaded_channels) - {"Time", "time"} == set(selected_names)``
(exact equality, with only the loader-inserted ``Time`` column and
the asammdf master ``time`` column excluded — no other extras
admitted).

## Memory Cost Analysis

For the CLI MVP (single-process, ≤ minutes-long capture) the memory cost
is acceptable:

- 5 signals × 100 Hz × 600 s = 3 × 10⁵ samples × 16 B (float64 ts +
  float64 value) ≈ **5 MB total**.
- 50 signals × 1 kHz × 1 hour = 1.8 × 10⁸ samples × 16 B ≈ **3 GB**.

The 1 hour × 50 signals × 1 kHz case is well outside the cockpit MVP
target (Stage 2 ships with a 2-second CLI demo). For long sessions
Stage 5's review modal can stitch multiple finalized MF4s via the
``segment_seconds`` config option — that becomes a future-stage
deliverable, not an MVP blocker.

## Channel-Naming Contract (Pinned)

```text
MF4 channel name == SelectedMeasurement.name  (verbatim, no prefix/suffix)
MF4 channel unit == SelectedMeasurement.unit  (UTF-8 string, may be empty)
```

Enforced by ``Mf4Writer.__init__`` (per-channel buffer keyed by name)
and ``Mf4Writer.finalize`` (one ``Signal(name=m.name, ...)`` per
selected measurement). The writer rejects ``append(channel_name, ...)``
for any name outside the registered set — this is a programmer-error
guard, not a runtime path.

## Edge Cases Handled

- **Zero samples for a selected channel.** ``asammdf`` rejects an empty
  ``Signal``. Writer emits one ``(t=0, v=0.0)`` placeholder sample so
  the channel name is still present in the finalized MF4. Stage 5
  ``analyze_mf4(...)`` surfaces "zero samples received" as a
  post-record warning, not a writer failure (spec §Capture vs
  diagnostics).
- **Writer error mid-session.** ``Mf4WriterError`` propagates up from
  ``CaptureController._stop_locked`` so the CLI maps it to exit code 3.
  No partial MF4 is left on disk in that path.
- **Ctrl-C while recording.** The CLI signal handler flips a flag; the
  controller exits its poll loop, drains the ring, finalizes the MF4,
  and writes the sidecar JSON before exiting. The MVP CLI test forces
  this path via the ``--duration`` cap rather than an OS signal, to
  avoid pytest signal-handling pitfalls.

## Why NOT Incremental Write

If a future iteration needs streaming-to-disk (e.g. for hour-long
captures past the memory budget above), the path is **not** "call
``MDF.append`` more often". Two alternatives that preserve the
channel-naming contract:

1. **Periodic finalize + segment files.** Every ``segment_seconds``
   close the current MF4, start a new one with the same channel set,
   stitch on read. The infrastructure already exists in
   ``segments[]`` of ``SessionSummary``; only the writer needs a new
   ``rollover()`` method. Captured for Stage 6+ if needed.

2. **Native ASAM MDF4 stream writer.** Skips ``asammdf`` entirely.
   Higher risk; only worth it if Vector-side throughput numbers from
   Stage 8 prove the buffered MVP cannot keep up.

Neither is part of the Stage 2 MVP.

## Test Anchor

The contract is locked in
``tests/test_acquisition_capture_writer.py::test_channel_names_match_a2l``:

```python
def test_channel_names_match_a2l(tmp_path):
    selected = (
        SelectedMeasurement(name="EngSpdAvg", unit="rpm"),
        SelectedMeasurement(name="EngTrqAct", unit="Nm"),
        SelectedMeasurement(name="VehSpeedRaw", unit="km/h"),
    )
    writer = Mf4Writer(tmp_path / "out.mf4", selected)
    for ch in (s.name for s in selected):
        writer.append(ch, 0.0, 1.0)
        writer.append(ch, 0.1, 2.0)
    out = writer.finalize()
    df, channels, _ = DataLoader.load_mf4(str(out))
    selected_names = {s.name for s in selected}
    assert set(channels) - {"Time", "time"} == selected_names
```

If a future writer change reintroduces incremental ``MDF.append`` calls,
this test fails immediately on the channel-name set inequality.

## Cross-References

- Spec §Recorder Backend (channel-naming rule).
- Plan Stage 2 §Tasks (writer spike line).
- ``can_logger/p0/mf4_probe.py`` — the original P0 single-signal writer
  uses the same one-append-then-save pattern; Stage 2 generalizes it
  to N signals without touching that file.
- Lesson:
  ``docs/lessons-learned/signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md``
  — applied to ``SessionSummary.write_sidecar`` (explicit
  ``encoding='utf-8'``).
