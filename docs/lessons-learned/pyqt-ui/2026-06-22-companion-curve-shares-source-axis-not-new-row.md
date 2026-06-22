---
role: pyqt-ui
tags: [pyqtgraph, time-domain, filter-overlay, companion-curve, dash, setpen, emphasis, channel-lines, subplot-row, plot-data-item]
created: 2026-06-22
updated: 2026-06-22
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
