# Stage 8 Real-A2L Follow-Up Report

- Date: 2026-05-19
- Branches updated: `stage8/pr1` (parser fix + fixture), `stage8/pr3` (cockpit fallback)
- Reviewer: main Claude
- Source A2L: `C0202_T04/A/ERD6_01_01_A0_C_02_02_T04_CANape_Aside.a2l`
  (1.5 MB ASAP2 1.7 emitted by `CANAPE_VERSION 14 0 39`, 323 MEASUREMENT entries)

## Why this exists

PR-1 / PR-2 / PR-3 all carried an `O-1 real A2L fixture` open item — every
synthetic A2L test passes, but no real CANape A2L had been parsed end-to-end.
The user provided one. Running it through the Stage 8 stack surfaced two
production-relevant gaps:

1. The parser returns a phantom second IF_DATA block whose `cmd_id` /
   `resp_id` are both `0x0` and whose `available_events` is empty.
2. The A2L declares its 5 DAQ events globally (typical AUTOSAR / Rte
   convention) and binds *zero* MEASUREMENTs to events via per-MEASUREMENT
   `DAQ_EVENT FIXED_EVENT_LIST`. The cockpit's event picker would have been
   empty for every signal.

Both gaps would have blocked PR-4 bench validation on day 1, so they are
fixed in this follow-up.

## Real-A2L parse summary

| Field | Value |
|---|---|
| Tool | CANape 14.0.39, ASAP2 1.7 |
| Transport | Classic CAN, 11-bit IDs (`cmd=0x6C7`, `resp=0x6C6`) |
| MAX_CTO / MAX_DTO | 8 / 8 |
| Byte order | `MSB_LAST` (little endian) |
| DAQ timestamp size | **0** — no timestamp in DAQ packets |
| Address granularity | `BYTE` |
| Global events (5) | `Rte_Appl_OS_Task_100ms` (100 ms), `Rte_OsTask_BSW_10ms` (10 ms), `Rte_OsTask_BSW_1ms` (1 ms), `Rte_OsTask_BSW_5ms` (5 ms), `BSW_2ms` (2 ms) |
| MEASUREMENT count | 323 |
| Per-MEASUREMENT `DAQ_EVENT` refs | **0** |

Raw text contains four blocks matching `/begin IF_DATA XCP`-prefixed openers:

| Block | Opener | Content | Parser before fix | Parser after fix |
|---|---|---|---|---|
| 0 | `IF_DATA XCP` | full XCP transport + DAQ | parsed (real) | parsed |
| 1 | `IF_DATA XCPplus` | full XCPplus transport | skipped (regex `XCP\b`) | skipped |
| 2 | `IF_DATA XCPplus` | SEGMENT/CHECKSUM only | skipped (regex `XCP\b`) | skipped |
| 3 | `IF_DATA XCP` | SEGMENT/CHECKSUM only | parsed as `cmd_id=0x0, resp_id=0x0, events=()` | **filtered out** |

## Fix A — `parse_ifdata_xcp_text` filters non-transport blocks

[`can_logger/p0/ifdata_xcp.py`](../../../can_logger/p0/ifdata_xcp.py) —
`parse_ifdata_xcp_text` now drops every parsed block whose `cmd_id`,
`resp_id`, and `available_events` are all empty. The doc-string explains
why: CANape and similar tools emit additional `IF_DATA XCP`-prefixed
fragments describing calibration pages / segments, and they share the
opener but carry no `XCP_ON_CAN` transport.

Downstream consumers (`A2LSummary.event_capacity`,
`MainWindow._cached_ifdata`) previously had to know to pick the first
non-empty block; they now receive a filtered list and can use `blocks[0]`
directly.

## Fix B — `_fill_ifdata_events` global-event fallback

[`can_logger/p0/a2l_probe.py`](../../../can_logger/p0/a2l_probe.py) —
when the A2L has global `IF_DATA XCP DAQ EVENT` entries but
`parse_measurement_events()` returns empty (no per-MEASUREMENT
`DAQ_EVENT FIXED_EVENT_LIST` bindings), every MEASUREMENT's
`available_events` is now populated with the global event tuple.

Behavior matrix:

| `event_capacity` | per-MEASUREMENT refs | `MeasurementSummary.available_events` |
|---|---|---|
| empty | empty | `()` — no DAQ events at all (unchanged) |
| populated | per-measurement | per-measurement (unchanged) |
| populated | **empty** | **global event tuple** (new — AUTOSAR / CANape case) |
| populated | partial (some present) | per-measurement only; **no fallback** for the missing ones |

The "partial" case is left strict on purpose: when *some* measurements
have explicit bindings, the unbound ones are *deliberately* unbound, not
just under-declared. The cockpit can still surface global events via
`A2LSummary.event_capacity` if it ever needs to UX-relax this further.

End-to-end verification against the real A2L:

```
capacity (5): {'Rte_Appl_OS_Task_100ms': 1, 'Rte_OsTask_BSW_10ms': 1, ...}
measurement_events: 0 entries
has_daq: True
  m0: available_events = (5 global events)
  m1: available_events = (5 global events)
  m2: available_events = (5 global events)
```

## Test coverage

| Test file | New tests | What they prove |
|---|---|---|
| `tests/test_ifdata_xcp_parser.py` | `test_parses_real_canape14_xcp_block` | real CANape fixture parses to expected `cmd_id`, transport, 5 events |
|  | `test_parser_filters_segment_only_canape_companion_block` | filter survives source-order shuffle |
| `tests/test_acquisition_a2l_events.py` | `test_fill_ifdata_events_falls_back_to_global_events_when_no_per_measurement_refs` | AUTOSAR case populates `available_events` |
|  | `test_fill_ifdata_events_per_measurement_refs_win_over_global_fallback` | partial-binding case stays strict |

Fixtures added under `tests/fixtures/ifdata_xcp/`:

- `canape14_real_aside.a2l_snippet` (3.9 KB) — real transport block 0
- `canape14_real_aside_segment_only.a2l_snippet` (669 B) — SEGMENT-only
  fragment proving the filter is needed

Full suite delta: **944 → 948 passed**, 1 skipped (unchanged).

## What this closes / leaves open

Closes (across PR-1 / PR-2 / PR-3):

- `O-1 real A2L fixture` — covered by `canape14_real_aside.a2l_snippet`.

Still open (PR-4 bench validation):

- `O-2` Vector `app_name` on the real Windows test PC.
- `O-3` real CAN bus + powered ECU.
- `O-4` ECU unlock state (`RESOURCE.DAQ`) or working Seed&Key DLL.
- `O-5` 5-minute expected frame rate per event.

Newly identified (not in this follow-up's scope):

- The real ECU exposes `ts_size=0` (no DAQ timestamps). `dto_decode`
  handles this via the `base_monotonic_s` path — verified by
  `tests/test_dto_decode.py::test_decode_no_timestamp_uses_base` — but
  PR-4 should explicitly cross-check that frame-arrival monotonic time
  is sane enough to drive MF4 timestamps.
- `XCPplus` parsing: our parser skips XCPplus via the `XCP\b` regex. If
  a future ECU only ships XCPplus (not classic XCP), the parser would
  return no blocks and the cockpit would silently disable the backend.
  Out of scope here; flag for a later parser-extension PR.
- `O-2` operator handover: when the Vector app_name is obtained, the
  cockpit Transport tab should validate via `vector_hw_probe` before the
  XCP probe stage — that two-stage flow is already in PR-3 (#14), so
  the operator open-item is purely data acquisition, not code.

## Commit landing

- Fix A (`parse_ifdata_xcp_text` filter) + new fixtures land on
  `stage8/pr1` as a follow-up commit on PR #12. `stage8/pr2` and
  `stage8/pr3` are rebased onto the new pr1 tip and force-pushed.
- Fix B (`_fill_ifdata_events` fallback) and its tests land on
  `stage8/pr3` as a follow-up commit on PR #14.
