---
role: pyqt-ui
tags: [pyqtgraph, time-domain, filter-overlay, companion-curve, dash, setpen, emphasis, channel-lines, subplot-row, plot-data-item, y-autorange, narrow-y, shared-viewbox, home-fit, dash-pen-raster-cost, perf, comp-only, viewport-repaint-timing]
created: 2026-06-22
updated: 2026-06-24
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
data extent (`_pin_companion_axes_y_to_visible`, nice-tick framed like
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

## 2026-06-23 follow-up #3 — pin to the VISIBLE extent, NOT always the primary (本末倒置 correction)
follow-up #2 over-corrected: it pinned the shared axis to the PRIMARY's extent
**unconditionally**, ignoring whether the original is actually drawn. With
**显示原始 OFF + 显示滤波后 ON** (a common workflow — the user only wants the
filtered trace) the dense original is hidden via `setVisible(False)` but Y is
still framed to its ±5 → the ±0.02 filtered companion collapses to a flat line
near 0 → **没法用** (本末倒置: the perf fix sacrificed the actual usability).
KEY INSIGHT: the 满屏竖线墙 only forms when the dense ORIGINAL is rasterized in a
narrow Y. **Hidden original ⇒ no wall can form ⇒ Y MUST fit the visible
companion.** Fix = make all three framing paths VISIBILITY-AWARE: frame each
companion-carrying axis to the union extent of the curves whose `PlotDataItem`
`.isVisible()` is True (`_visible_raw_y_extent` over `_axis_groups`), still via
an explicit `set_ylim` (auto-range stays OFF). Behavior table: original visible
→ union covers it (wall avoided, follow-up #2 regime preserved); original hidden
+ companion visible → union = companion (filtered usable, no wall). The three
paths: (a) bind-time `_pin_companion_axes_y_to_visible`; (b) Home
`reset_view_to_data_extents` and (c) `fit_y_to_visible_x` — both rewritten to
iterate handle GROUPS (primary + its companions) and frame to the visible union,
so a post-fix Home/Y-自适应 no longer snaps Y back to the hidden ±5 (which would
re-bury the filtered data). (d) the live toggles `set_original_lines_visible` /
`set_companion_lines_visible` now RE-PIN before their `draw()` (synchronous, no
intermediate frame) so unchecking 显示原始 drops Y onto the companion and
re-checking restores the ±primary framing (wall avoidance back on the instant
the dense original is redrawn). VERIFY by mechanism (Y span < 1 when original
hidden, > 5 when visible — RED before / GREEN after) AND a real offscreen render
showing the filtered waveform fills each subplot's height. Don't trust "pin set +
unit pass" — the original bug passed 19 companion tests because every one built
with the primary VISIBLE; the missing case was orig-hidden + companion-visible.

## 2026-06-24 follow-up #4 — `setVisible(False)` is not enough: 3 data-iterating paths ignore visibility
显示原始 OFF correctly flipped each primary `PlotDataItem.isVisible()` to False
(verified subplot + overlay, before AND after pan), yet the user reported the
原始 curve "still there", "拖动加倍曲线量", and "游标命中隐藏曲线". Root cause: the
`setVisible` toggle is honored, but THREE other paths enumerate curves by DATA
presence, NOT line visibility, so a hidden curve still acts live: (1) the cursor
readout `CursorController._emit_single_cursor_html` / `_emit_dual_cursor_html`
iterate `self.channel_data.items()` (full series, hidden or not) with NO
`isVisible()` guard → hidden original/companion still shows in the cursor pill +
dual-cursor stats rows + extreme markers. `_select_overlay_channel_from_scene_pos`
was already guarded (ydrag lesson) but the value-readout was a SEPARATE,
unguarded path. Fix: a `_hidden_channel_names()` helper that walks
`_channel_lines.composite_items()` and collects DISPLAY names whose
`plot_data_item.isVisible()` is False (keyed by composite so a same-named channel
in another file is not falsely hidden), then `if ch in hidden: continue` in both
emitters. (2) `renderer._refresh_visible_data` iterates ALL `_channel_lines` and
re-runs `positions_envelope` + `setData` per pan/zoom tick on hidden lines too —
that's the "拖到加倍" cost (each channel carries a hidden original AND a visible
companion). Fix: skip `if not line_facade.plot_data_item.isVisible()` at the TOP
of the loop (before the range-key gate). CAVEAT: skipping while hidden leaves the
line's envelope stale for the current x-window if the user panned while it was
off, so on RE-SHOW (`set_*_lines_visible(True)`) you MUST drop the re-shown
lines' `_last_range_key` and call `_refresh_visible_data()` before `draw()` (the
range-key gate then recomputes them at the current view; no-op if xlim was
unchanged). (3) The idle-AA pass sets `DeviceCoordinateCache` on every
`PlotCurveItem` with no visibility filter; a hidden item's cached offscreen
raster pixmap can keep COMPOSITING after `setVisible(False)` on a GL/cached
viewport (lesson-95 #2 fingerprint) — the most likely cause of "原始 still drawn"
on the user's real GPU machine. Defensive GL-AGNOSTIC fix (NOT a viewport/GL
change): clear the hidden curve's cache (`pdi.curve.setCacheMode(NoCache)`) in
the hide branch of both setters. VERIFY: cursor exclusion + refresh-skip +
re-show-refresh are all offscreen-testable by mechanism (isVisible flag, getData
arrays, cacheMode); the actual painted framebuffer with a hidden item's GL cache
is NOT — flag it for real-machine pixel verification, do not claim it fixed from
offscreen state alone. Distinct from follow-up #3 (that was Y-framing of the
VISIBLE set; this is hidden curves staying live in cursor/refresh/cache).

## 2026-06-24 follow-up #5 — the DASHED pen itself is the comp-only paint cost
After follow-ups #1–#4 the user STILL reported "只显示滤波后 卡得很 / 只显示原始 不卡"
on Windows GPU-off, despite IDENTICAL data volume. PROFILE (4×~1.5M-pt dense
channels, AA-OFF interactive pan, timed via `viewport.repaint()` NOT `grab()`):
显示滤波后(comp-only)=47ms vs 显示原始(orig-only)=16ms — 2.9×, even though the
displayed-point count was EQUAL (2800) and the wall guard was NOT firing
(`_y_overflow_wall_active=False`, companion小幅 so data≈Y). The refresh (envelope
recompute) was actually FASTER for comp-only (hidden original is correctly
skip-enveloped per #4), so the cost was PURE RASTER. Bisecting the companion
pen on the live PlotDataItem isolated it cleanly: forcing the companion pen to
SOLID dropped comp-only to 3–7ms (the dash IS the entire 31–44ms delta), and a
pen-matrix (DashLine×{1.0,1.35,1.5,2.6}, Solid×{1.0,1.5}, cosmetic) showed the
cost is **Qt's CPU-raster dash-stroker walking the dash-phase accumulator along
EVERY segment of the stroked path** — a min/max envelope of a dense wideband
filtered signal is a high-frequency up/down ZIGZAG with thousands of tiny
segments, so a `Qt.DashLine` pen rasterizes it several× slower than a solid pen
(and erratically so: sub-pixel widths like 1.5 were the WORST, cosmetic dash was
also slow — width-tuning is NOT a stable fix). KEY INSIGHT: the dash is a PURE
VISUAL AFFORDANCE to distinguish the companion from its SOLID source; when 显示原始
is OFF there is no original on the axis to distinguish it from, so the dash is
all cost and zero benefit. FIX (small, design-aligned, NO numeric/Y/data change):
draw the companion SOLID while its source original is hidden, DASHED when shown.
Mechanics: a `_companion_source` dict (companion composite key → source composite
key, recorded at `_bind_companion` time only for `dash=True` rows, reset in
`clear()`); a `_sync_companion_dash_styles()` that flips ONLY `pen.style()`
(preserves color+width, idempotent — skips when already correct) based on
`_source_original_visible(ck)`; called at the SAME three sync points as the Y-pin
(bind-time in `plot_channels`, `set_original_lines_visible`,
`set_companion_lines_visible`) so the style is correct on the first frame AND on
every live toggle. Result: comp-only 47→7ms (now FASTER than orig-only's 16ms),
both-mode keeps dash (36ms, unchanged — user accepts that regime). VERIFY by
MECHANISM (offscreen-stable): assert `pen.style()` == SolidLine when original
hidden / DashLine when shown, round-trip on re-show, color+width preserved, and
prove load-bearing by monkeypatching `_source_original_visible→True` (pre-fix) so
the companion stays dashed (RED). The absolute paint-ms is Windows-raster-timing
only (Mac/offscreen `grab()` is a cached blit ≈1ms that HIDES it), so the slow
timing test asserts the RATIO (comp-only ≤ 1.5× orig-only), not an absolute
budget, and is timed via `viewport.repaint()`. Distinct from #1–#4: this is the
STROKE-STYLE raster cost of the visible companion, orthogonal to wall/Y-framing
(both False here) and to hidden-curve liveness (#4).
