---
role: pyqt-ui
tags: [channel-storage, identity-vs-label, composite-key, multi-file, same-name, dict-subclass, viewport-cache, get-statistics, return-contract, companion, color-sync, plot-data-item-identity, fresh-wrapper, middle-ellipsis, fixture-premise, regression-guard]
created: 2026-06-24
updated: 2026-06-24
cause: insight
supersedes: []
---

## Context
The pyqtgraph time-domain canvas keyed `channel_data` / `_channel_lines` /
`_channel_data_id` / `_channel_is_monotonic` / `_companion_names` /
`_last_range_key` / `_line_wall_state` on the channel's prefixed DISPLAY name
(`[short_name] ch`). When two files' `short_name` truncated to the same prefix
(`file_data.py` `stem[:18]`), their display names collided, the second-bound
channel OVERWROTE the first's storage slot, and checking-all then unchecking one
made a surviving curve vanish (its slot had been clobbered). A sibling dict,
`_channel_view_state_lines`, already keyed on the non-colliding composite
`_view_state_channel_key(data_id, name)` — the correct identity existed but was
only used for view-state restore.

## Lesson
A display string used as BOTH a dict key AND a user-visible label couples
identity to presentation: any two rows that must look the same are then forced
to BE the same. Decouple by keying storage on a composite identity
`(data_id, name)` that distinct files never share — but do NOT rewrite the dozens
of bare-name call sites/tests (`canvas._channel_lines["torque"]`,
`for ch in channel_data.items()`). A `dict` subclass (`_ChannelKeyDict`) that
(a) stores under the composite key, (b) resolves reads/`in`/`pop` by EITHER the
composite key OR a bare name, (c) iterates yielding the display name as the key
(so display/stats/cursor consumers see a label) while still yielding BOTH
colliding entries as separate pairs, and (d) exposes `composite_items()` →
`(composite_key, display_name, value)` for identity-sensitive hot paths, fixes
the root collision with near-zero churn. The renderer's per-line viewport caches
(`_last_range_key` / `_line_wall_state`) MUST key on the composite key via
`composite_items()`, never the display name, or two same-named channels
cross-contaminate (one's cache-HIT suppresses the other's refresh — the
per-(fid,name)-cache rule). Companion membership and the `companion_of` source
lookup must also use the composite key (build `_view_state_channel_key(cdata_id,
companion_of)`), else a companion anchors onto the wrong file's same-named source.
`get_statistics` returning a `_ChannelKeyDict` keyed by composite + a
`display_label` field keeps bare-name reads (`stats["speed"]`) working while the
contract becomes collision-safe — return the subclass, not a plain dict, to avoid
forcing every caller/test to learn the composite key.

## How to apply
When a UI stores per-thing state in dicts keyed on a name that is ALSO shown to
the user and can collide (multi-file, multi-source), introduce a key-dict
subclass keyed on a stable composite identity with name-resolving reads + a
display-name iteration surface + a `composite_items()` accessor; migrate every
identity-sensitive cache (viewport range/wall caches) and cross-row lookup
(companion source) to the composite key, leave display/label consumers on the
name surface, and return the subclass from contract methods so bare-name reads
survive. Verify with a LIVE two-file same-display-name harness: assert two
distinct `PlotDataItem`s (distinct ids + distinct amplitudes) survive a
check-all → uncheck-one sequence — "attribute set + unit test passed" hides the
orphan; count the visible curves.

## Follow-ups (2026-06-24, S2 finishing run)
* WRITE paths are the same class as the storage dicts: the color-sync sites
  (`overlay_axes._sync_pg_channel_color` via `_axis_handle.sync_line_axis_color`,
  reached from `ChartOptionsDialog`) wrote `channel_data[name] = (...)` by BARE
  display name → `_ChannelKeyDict._resolve` picks LAST-bound on a collision, so a
  color edit on file A landed on file B (cosmetic, t/sig pass through verbatim,
  zero numeric impact). Fix: resolve the COMPOSITE key of the EXACT curve and
  write by it. `get_lines()` returns a FRESH `_PgLineHandle` each call, so the
  `line` arg is NOT the stored handle — match on the underlying `plot_data_item`
  identity (`is`) against `_channel_lines.composite_items()`, not handle `is`.
  Resolve the composite back to its `display_label` for the inside-axis-label
  comparison. The matplotlib-fallback in `dialogs.py` (`raw_line.axes`) is inert
  for PG (`PgAxisHandle` has no `.axes`, `self.ax is None` → early return), so the
  single PG fix is at `_axis_handle.sync_line_axis_color`.
* A label-format change that REDUCES collisions silently invalidates a
  collision-repro fixture. Switching `short_name` from head-truncation
  (`stem[:18]`) to a MIDDLE ellipsis made two stems differing only in the TAIL
  stop colliding, so the Task-1 fixtures (same-head, different-tail) all turned
  GREEN-by-non-reproduction. Express the repro PREMISE as the invariant
  (`get_prefixed_channel(a) == get_prefixed_channel(b)`), NOT the truncation
  mechanism (`a[:18] == b[:18]`), and pick fixtures robust to the format: two
  stems sharing the same HEAD and TAIL but differing in the MIDDLE still collide
  under middle-ellipsis. Prove the guard is real by monkeypatching the storage
  back to name-keyed (collapses 2→1) / the sync back to bare-name (color leaks)
  and watching the test go RED.
