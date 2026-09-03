# Cursor Display Settings Specification

**Status:** Approved for implementation
**Date:** 2026-08-31
**Prototype:** `docs/analyzer/ui-prototypes/2026-08-31-cursor-display-settings.html`

## 1. Outcome

The time-domain cursor result panel shall remain readable for every combination of cursor display settings, pane size, channel count, split-pane state, and custom-X path shape. Single-cursor mode reports only values at the current cursor. Dual-cursor mode may additionally report interval statistics and chart extrema markers according to five application-global settings.

This specification turns the prototype interaction into a deterministic product contract. It covers the pyqtgraph time-domain stack only; FFT, FRF, preview, and batch rendering are unchanged.

## 2. Terms and ownership

- **Single cursor:** one cursor position.
- **Dual cursor:** two cursor positions defining an interval.
- **Time-X:** ordinary monotonic time on the horizontal axis.
- **Custom-X:** a channel supplies horizontal coordinates and may contain a rising leg (`X↑`), falling leg (`X↓`), or both.
- **Result pill:** the floating cursor result panel owned by `ui/chart_stack/`.
- **Composite identity:** logical source plus channel identity. Display labels are never identity keys.
- **Full mode:** expanded result pill.
- **Mini mode:** compact result pill.

Numerical custom-X path classification and sampling belong in `mf4_analyzer/signal/custom_x_paths.py`. Cursor state and chart markers belong in the pyqtgraph cursor collaborator. Result formatting, geometry, settings controls, and popover presentation belong under `mf4_analyzer/ui/chart_stack/` and reusable `ui/widgets/` controls. `MainWindow` does not own or mutate this state.

## 3. Preference contract

The settings popover exposes exactly five independent booleans:

| Setting | Default | Affects |
|---|---:|---|
| `show_max_point` | on | Maximum marker on the chart |
| `show_min_point` | on | Minimum marker on the chart |
| `show_max_value` | on | Maximum-value column in dual-cursor results |
| `show_min_value` | on | Minimum-value column in dual-cursor results |
| `show_avg_value` | on | Average-value column in dual-cursor results |

The values are application-global preferences stored as a versioned JSON object at `charts/time_cursor/display_options_v1` in the existing `QSettings` application namespace. They are loaded once by the chart-stack owner and propagated to every current and future time chart card/canvas. Both split panes update in the same event turn. They are not part of ViewState, project/session persistence, presets, or analysis results, and no widget object is persisted.

Point settings never add, remove, or resize result-pill content. Value settings never change marker visibility. Turning cursor mode off closes the popover but retains preferences. The settings button remains available beside the cursor controls in single and dual mode; when opened in single mode, the popover states that value statistics apply to dual cursor only.

## 4. Numerical contract for custom-X single cursor

The public, UI-neutral sampler accepts aligned X and Y arrays plus the selected custom-X value and returns zero, one, or two branch values with a diagnostic reason. It shall:

1. reuse the same finite-segment, turn-policy, and major-leg classification as dual-cursor custom-X analysis;
2. interpolate only inside each accepted physical leg, using that leg's local ordering;
3. never sort or interpolate the combined non-monotonic series;
4. never extrapolate beyond a leg's finite X extent;
5. preserve deterministic branch order: `X↑`, then `X↓`;
6. return one labelled value for a reliably unidirectional path;
7. return no value with an explicit diagnostic for empty/non-finite input, incompatible shape, an out-of-range X, or an ambiguous multi-turn path.

Input and output dtypes are numeric; values emitted to UI are finite floats. X/Y length mismatch is an incompatible-shape result, not an unexplained truncation. Existing custom-X tolerance and turn policy remain the source of truth.

## 5. Result content rules

### 5.1 Single cursor

- Time-X remains the existing current time and current channel value presentation.
- Custom-X shows the selected `X=` value and, for each visible composite channel, current branch values only.
- A two-leg path shows `X↑` followed by `X↓`; a reliable one-leg path shows its one known direction.
- Single mode never shows Minimum, Maximum, Average, Delta, or interval extrema, regardless of settings.
- A channel without a value at the selected X shows its diagnostic in the full tooltip and does not fabricate a branch value.

### 5.2 Dual cursor, Time-X, full mode

Each channel is a whole block with a source-qualified header. The invariant fields are cursor interval and `Δ`; enabled value columns follow the exact order `Min`, `Max`, `Avg`. Thus:

- all value settings on: identity, interval/`Δ`, Min, Max, Avg;
- a subset on: only those enabled columns, still ordered Min, Max, Avg;
- all value settings off: identity and interval/`Δ` remain; the panel is never blank.

### 5.3 Dual cursor, Custom-X, full mode

Each channel is a whole block. Branch rows use `X↑`, then `X↓`, or the one reliable direction. Enabled value columns follow `Min`, `Max`, `Avg`. Custom-X does not invent a time delta. With all value settings off, identity and branch labels remain. Diagnostics remain available even when no metric column is enabled.

### 5.4 Mini mode

Mini mode is a deterministic projection, not an independent calculation:

- Time-X dual keeps source/channel identity plus `Δ` on the visible face. Its tooltip contains every enabled Min/Max/Avg value and full source-qualified identity.
- Custom-X dual keeps every available branch label. For each branch it shows one enabled metric by priority `Avg`, then `Max`, then `Min`, and labels that metric explicitly. With no value metric enabled it shows branch identity only. Its tooltip contains all enabled metrics and diagnostics.
- Custom-X single shows current branch values. If visual width forces label elision, the tooltip retains full source-qualified identity and unabridged values.

Mini mode must not make two different sources with the same channel display name indistinguishable in the tooltip.

## 6. Layout and geometry rules

The presentation model shall generate only populated columns and whole channel/branch blocks. It shall never emit empty table cells solely to reserve disabled features, orphan a header from its values, or leave a visible empty pill.

### 6.1 Width policy

1. Use the natural horizontal layout while its size hint fits the pane's safe rectangle.
2. The safe rectangle is the parent content rectangle inset by 8 px on every edge; result width therefore never exceeds parent width minus 16 px.
3. When natural width does not fit, switch to a constrained stacked layout: source/channel header on its own row, then label/value rows. Metric order and branch order do not change.
4. In constrained mode only, long visual labels use middle elision. The tooltip always carries the complete source-qualified identity and complete values.

### 6.2 Height policy

The result pill never exceeds the safe rectangle height. It includes as many whole channel blocks as fit and replaces omitted blocks with one `+N channels` summary row. No partial channel block is shown. The tooltip contains the complete untruncated result. Changes in settings, content, mode, pane size, or font metrics recalculate this projection.

### 6.3 Anchoring and collision policy

All content and mode changes continue through the chart stack's single pill-update path. A user-moved pill preserves its top/right relationship and is clamped into the safe rectangle; a default-position pill re-anchors deterministically.

The settings popover is anchored to the settings button. If its open geometry would intersect the result pill, the pill is displaced to the nearest non-overlapping position with an 8 px gap, preferring leftward displacement. Closing the popover restores the pill to its prior anchor and then clamps it once. Repeated settings toggles must not accumulate drift or visible jitter.

## 7. Marker rules

- Minimum markers use a green (`#16a34a`) circle.
- Maximum markers use a red (`#dc2626`) diamond.
- Marker ordering and selection use composite source/channel identity, including every coaxis member that independently qualifies.
- Hidden-channel filtering uses composite keys, not display names. Hiding `source A / Speed` must not hide `source B / Speed`.
- Marker switches apply immediately to both split panes. Disabled point types are absent from `ScatterPlotItem` data; they are not transparent placeholders.
- Marker toggles do not alter result HTML, layout mode, size hint, or pill anchor; disabled markers are removed rather than retained as invisible items.

## 8. Split-pane and lifecycle rules

Both panes share one immutable value-object snapshot of current preferences and receive updates together. Each pane continues to compute results only from its own canvas contributions; no rows or markers cross panes. The active chart card owns the visible settings popover, while controls in both panes reflect the same preference values. New cards and restored layouts receive current preferences before their first cursor result render.

Canvas collaborator declarations must include every new owned or delegated name. Cursor cleanup clears transient results/markers and disconnects controls without resetting global preferences.

## 9. Error and diagnostic presentation

Diagnostics are observable and source-qualified. At minimum, the existing custom-X reason taxonomy must distinguish:

- no finite data or selected X outside every valid leg;
- incompatible X/Y shape;
- same-direction or otherwise incomplete branch evidence;
- ambiguous multi-turn data that cannot be classified reliably.

A recoverable data condition produces an empty/value-missing row plus tooltip/status text, not an exception dialog. Programming errors, unexpected imports, and invalid collaborator wiring continue to propagate. No broad exception suppression is introduced.

## 10. Settings-state matrix

There are 32 preference combinations. The formatter/presentation-model test matrix shall evaluate all 32 in each of these semantic contexts:

- Time-X dual and Custom-X dual;
- one channel and multiple channels;
- full and mini projection.

Assertions cover deterministic ordering, absence of disabled fields, absence of blank/orphan cells, invariant fields, complete tooltip content, and stable result identity. Since the two point bits do not affect result content, tests additionally prove that changing only those bits leaves the presentation model and size category unchanged.

Qt geometry tests cover representative equivalence classes rather than rendering 256 redundant widgets: natural width, constrained width, constrained height, single custom-X, split pane, popover collision, user-moved anchor, duplicate display names, and marker-only toggles.

## 11. Documentation and compatibility

The user-visible interaction is documented in both `mf4_analyzer/ui/hints.py` and `mf4_analyzer/ui/quickref.py`. Existing public imports and legacy cursor-info signals remain supported. Structured result data may be added alongside legacy formatted text, but compatibility facades remain thin and no UI dependency enters `signal/`.

## 12. Acceptance criteria

The feature is accepted when:

1. all single-cursor, dual-cursor, 32-combination, duplicate-identity, split-sync, geometry, collision, and marker contracts above have focused automated tests;
2. numerical tests cover empty, short, non-finite, dtype, shape, endpoint, in-leg, out-of-range, one-leg, two-leg, and ambiguous multi-turn cases;
3. an offscreen deterministic render proves normal and narrow layouts stay within bounds with no overlaps, and a Windows foreground probe verifies the running widget path;
4. relevant import, back-reference, QSS, signal-connection, paint-timer, and state-ownership gates pass;
5. `git diff --check`, literal-requirement scan, and unresolved-marker scan are clean.

## 13. Non-goals

- No statistics in single-cursor mode.
- No setting for `Δ`, branch direction, selected-X labels, precision, units, or channel visibility.
- No FFT, FRF, preview, batch-render, acquisition, or project-file schema change.
- No new MainWindow state, raw display-name identity map, parallel rendering policy, or duplicated custom-X calculation.
- No redesign of cursor dragging, snapping, or dual-cursor interval semantics.

## 14. 2026-09-03 erratum (current implementation of §3 only)

This erratum does not rewrite the 2026-08-31 historical contract. The current
product has **six** application-global booleans, not the five listed in §3:
the five recorded settings plus `show_delta_value` (default on), which controls
the dual-cursor difference value. The preference remains global and is not
stored in ViewState, project/session state, presets, or analysis results.
