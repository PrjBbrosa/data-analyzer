# Inspector Axis B Polish Design

**Date:** 2026-04-29
**Status:** Approved direction from browser preview, ready for implementation

## User-Approved Direction

Use option B from `docs/ui-previews/axis-ui-options.html`, with one correction:
the application already has separate Inspector contextual panels. Do not add a
new Inspector panel, tab strip, or outer mode switch. Optimize the existing
`FFTTimeContextual` and `OrderContextual` panels in place.

## Problems To Solve

1. Numeric spin boxes show unnecessary up/down stepper buttons. They consume
   horizontal space and contribute to the unreadable axis rows. Combo boxes
   must keep their down-arrow affordance.
2. FFT Time's axis controls are semantically wrong. The current panel describes
   FFT Time as `X = frequency` and `Y = amplitude`, but the actual spectrogram
   canvas renders `X = time`, `Y = frequency`, and color/Z = amplitude. This is
   the critical defect.
3. FFT Time and Order axis rows show too many numeric fields at once. Automatic
   range rows should not show editable min/max controls. Manual rows must show
   lower/upper inputs.
4. The Order contextual background is tinted/gray-orange. Remove that special
   background so Order matches the neutral Inspector surface.

## Target Behavior

### Shared Axis Row Behavior

Each axis row keeps the same conceptual structure:

```text
<axis label>  [自动]  <range display>
```

When `自动` is checked:

```text
Y 阶次  [✓ 自动]  0 → 最大阶次
```

- Min/max spin boxes are hidden.
- A read-only summary label is visible.
- The user can see what the automatic range means without numeric clutter.

When `自动` is unchecked:

```text
Y 阶次  [ ] 自动  0 → 20
```

- The summary label is hidden.
- Lower/upper numeric inputs are visible and enabled.
- Numeric inputs have no up/down stepper buttons.

### FFT Time Axis Semantics

`FFTTimeContextual` must expose axis rows matching the actual plotted
spectrogram:

| Row | Meaning | Downstream use |
| --- | --- | --- |
| X 时间 | Time range on the spectrogram X axis | `x_auto/x_min/x_max`; passed to `SpectrogramCanvas.plot_result` |
| Y 频率 | Frequency range on the spectrogram Y axis | `y_auto/y_min/y_max`; also backs legacy `freq_auto/freq_min/freq_max` |
| 色阶 | Amplitude/color scale | `z_auto/z_floor/z_ceiling` plus `combo_amp_unit` |

The legacy `freq_*` keys remain for callers and presets, but they must now map
to the Y-frequency row, not the X row.

`SpectrogramCanvas.plot_result` must accept and honor `x_auto/x_min/x_max` for
manual time-axis limits, matching the existing Order heatmap API.

### Order Axis Semantics

`OrderContextual` already has the correct conceptual mapping and should retain
it:

| Row | Meaning |
| --- | --- |
| X 时间 | Time range |
| Y 阶次 | Order range |
| 色阶 | Amplitude/color scale |

The row display behavior changes to the shared automatic/manual model above.
The `spin_y_max` clamp to `spin_mo` remains unchanged.

### Styling

- Inspector numeric `QSpinBox` / `QDoubleSpinBox` controls use
  `QAbstractSpinBox.NoButtons`.
- Combo boxes keep `QComboBox::drop-down` and `QComboBox::down-arrow` styling.
- `QWidget#orderContextual` uses a neutral/transparent surface rather than the
  previous tinted background.

## Non-Goals

- No FFT or Order signal-processing algorithm changes.
- No new Inspector mode, tab bar, or outer navigation.
- No removal of backward-compatible preset keys in this pass.
- No change to the main chart labels; they already render FFT Time as
  `Time (s)` / `Frequency (Hz)` and Order as `Time (s)` / `Order`.

## Verification

Add PyQt tests for:

- FFT Time axis labels are `时间 (X)` / `频率 (Y)`.
- FFT Time legacy `freq_*` keys map to the Y-frequency row.
- FFT Time manual X time range is passed to `SpectrogramCanvas.plot_result` and
  controls `set_xlim`.
- Automatic axis rows show summary labels and hide spin boxes; manual rows show
  spin boxes and hide summary labels.
- Inspector spin boxes use `NoButtons`, while combo boxes remain normal combo
  boxes.
- Order contextual background tint is removed from `style.qss`.

