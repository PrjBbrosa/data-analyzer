---
role: pyqt-ui
tags: [pyqtgraph, time-domain, filter-overlay, companion-curve, dash, setpen, emphasis, channel-lines, subplot-row, plot-data-item, y-autorange, narrow-y, shared-viewbox, home-fit]
created: 2026-06-22
updated: 2026-06-23
cause: insight
supersedes: []
---

## Context
Time-domain filter overlay: `plot_channels` allocates one subplot row/axis
PER ``vis`` entry, so appending a filtered trace as its own row doubled the
subplot count instead of overlaying the filtered (dashed) curve on its source
channel's axis. Adding a companion curve onto an EXISTING `PgAxisHandle`
(not a new row) is the fix.

## Lesson
(1) To overlay a paired curve without spawning a row: bind a new
`PlotDataItem` onto the SOURCE handle's `view_box` (reuse `add_line_item`),
register it in `_channel_lines` + `channel_data` under its OWN name (so the
viewport-envelope refresh in `renderer._refresh_visible_data` and `grab`
export pick it up like any channel), but DO NOT append a new `PgAxisHandle`
to `axes_list` — that keeps `len(axes_list) == source-channel count` in both
subplot and overlay mode. Track companions in a `_companion_names` set so the
stats path (`get_statistics`) and emphasis logic can exclude them from
real-channel behavior. (2) `plot_channels`'s `if not visible: continue` drops
invisible rows entirely; a companion whose visibility toggles (显示滤波后) must
be EXEMPT from that skip and instead bound with `pdi.setVisible(flag)` so
unchecking just hides the dashed curve rather than removing it. (3) THE TRAP:
`_apply_overlay_emphasis` → `_apply_pdi_emphasis` rebuilds the pen via
`pg.mkPen(color=..., width=...)` on every selection change, which SILENTLY
RESETS a dashed pen back to `Qt.SolidLine` — read `pen.style()` off the
existing `QPen` and pass it through `mkPen(..., style=...)` so the dash
survives emphasis re-apply. (4) Carry the pairing through the data tuple as an
optional 8th `meta` dict (`{"companion_of": <source name>, "dash": True}`);
legacy 6/7-tuple rows stay primary, so the change is backward compatible — but
every existing consumer that unpacks the plot-data rows with a fixed-arity
`for name, vis, x, sig, color, unit, fid in data:` then breaks on the 8-tuple;
grep those and switch to `row[:6]`-style slicing.

## How to apply
For any "overlay a derived/paired trace on its source's axis (dashed) without
adding a subplot row" request on the pyqtgraph time-domain canvas: bind onto
the source handle, register under a unique name + a companion-name set, exempt
it from the invisible-row skip, preserve `pen.style()` in the emphasis
re-pen, and audit fixed-arity tuple unpacks of the plot-data list. Verify with
a narrow-X zoom grab (the dash is invisible at full-signal zoom when the
filtered curve sits near zero inside a dense envelope) and confirm
`len(axes_list) == source count` plus companion `isVisible()==False` after the
toggle.

## 2026-06-23 follow-up — axis belongs to the CHANNEL, and live toggles
(5) The invisible-row skip `if not visible: continue` was STILL a blank-chart
trap for the inverse case "显示原始 off + 显示滤波后 on": skipping the
(invisible) original meant its axis was never built, so the companion (which
binds onto the SOURCE's existing handle) had no anchor → the whole chart went
blank, and re-plotting stayed blank. Fix: make the subplot/axis belong to the
CHANNEL, not to the original line. Build the axis when `original_visible OR
(channel has a visible companion)`; always add the original line but
`setVisible(p_visible)` it so the companion can still anchor on the same
ViewBox while the solid original is hidden. Both-off → no axis (blank
acceptable). Carry the original's own visibility as an extra `vis` tuple
element and grep every `vis` unpack (`for ... in vis`, `vis[0]`, `*vis[0]`) —
widening the 6-tuple breaks fixed-arity unpacks just like the 8-tuple did.
(6) Live "秒生效不重绘" display toggles (`chk_orig`/`chk_filt`) must NOT route
through the submit-on-绘图 `filter_changed` signal; give the panel dedicated
`*_visibility_changed(bool)` signals wired to canvas helpers
(`set_*_lines_visible`) that walk `_channel_lines` (companions via
`_companion_names`), call `pdi.setVisible` + one `draw()`, and RETURN the
count toggled so the host can fall back to a full plot only when nothing was
bound yet (e.g. turning the filtered overlay ON before the first 绘图).
Hiding the original live must keep its axis (companion still on it) — same
invariant as the re-plot fix.

## 2026-06-23 follow-up #2 — shared-axis Y MUST be pinned to the PRIMARY, never auto/companion
(7) A tiny-amplitude companion (低通 100 Hz ≈ ±0.02) sharing its source's
ViewBox with a LARGE original (±2~6) makes the shared axis's DEFAULT Y
auto-range a latency trap: a companion `setData` can fire a Y auto-range pass
that frames the axis to the companion's ±0.04 for a transient frame, then the
dense original rasterizes inside that narrow Y as a full-height vertical-stroke
wall (满屏竖线墙) — the most expensive raster regime — for every dense channel
(用户实测 Windows 十几秒；Y re-settles to ±5 after). Fix: after binding all
companions, PIN each companion-carrying axis's Y EXPLICITLY to the PRIMARY's RAW
data extent (`_pin_companion_axes_y_to_primary`, nice-tick framed like
`reset_view_to_data_extents`); an explicit `setYRange`/`set_ylim` turns Y
auto-range OFF (`vb.state['autoRange'][1] is False`) so no companion `setData`
can ever re-narrow it. Gate to companion-carrying axes only — no-companion rows
keep default Y auto-range (no behavior change for non-filter plots). (8) THE
SAME OVERWRITE bites `reset_view_to_data_extents` (Home) and
`fit_y_to_visible_x` (Y 轴自适应): both iterate `_channel_lines` and `set_ylim`
per entry, so the companion (sharing the source ViewBox, iterated AFTER the
primary) OVERWRITES the primary framing → Home collapses Y to ±0.025 (reproduced
offscreen). Skip `name in _companion_names` in BOTH loops; the primary already
frames the shared axis. (9) ENV CAVEAT for verification: the narrow-Y TRANSIENT
is a Windows event-loop/auto-range-timing artifact — it does NOT reproduce on
macOS offscreen OR cocoa (painted `viewRange()` Y is already the primary union
on both, so there is NO paint-ms delta to show on Mac). Prove the fix by the
MECHANISM (assert `autoRange[1] is False` + Y span ≈ primary, RED before / GREEN
after) and by the CONCRETE Mac-reproducible Home/fit collapse, NOT by a Mac
paint-ms number. Distinct from the dense-bucket-cap raster cost (that wall
persists at ~110 ms/frame on Mac cocoa regardless — same channels, both before
and after — and is a SEPARATE cost axis already capped).
