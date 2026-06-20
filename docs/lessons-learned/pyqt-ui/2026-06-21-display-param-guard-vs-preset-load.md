---
date: 2026-06-21
tags: [apply_params, preset, weighting, partial-dict, display-param, colorbar]
cause: insight
---

# Display-param Guard vs. Preset Load in `apply_params` / `_apply_preset_values`

## Context

Inspector section panels have two "set values from dict" paths:

- **`_apply_preset_values(d)`** — called when the user loads a saved
  preset file. `d` is a complete preset blob and any key that is absent
  should fall back to a sensible default (old presets may lack new
  fields).
- **`apply_params(d)`** — called on partial UI round-trips such as
  colorbar-drag echo: `{'z_auto': False, 'z_floor': -39, 'z_ceiling': 0}`.
  Only the keys actually present in `d` should change widget state.

## The Bug

Before the fix both paths ended with:

```python
self._apply_weighting_value(d.get('weighting', 'None'))
```

A colorbar drag sends `d = {'z_auto': …, 'z_floor': …, 'z_ceiling': …}`.
`d.get('weighting', 'None')` returns `'None'` and silently reset
A-weighting to None even though the user had not touched it.

## The Fix

**`apply_params`** (partial dict path) — guard every optional field with
`if 'key' in d:`:

```python
if 'weighting' in d:
    self._apply_weighting_value(d['weighting'])
if 'db_reference' in d:
    self.spin_db_ref.setValue(d['db_reference'])
```

**`_apply_preset_values`** (full blob path) — keep the `.get()` fallback
because old presets legitimately lack the key:

```python
self._apply_weighting_value(d.get('weighting', 'None'))
if 'db_reference' in d:
    self.spin_db_ref.setValue(d['db_reference'])
```

`db_reference` still uses `if 'key' in d:` in both paths — a preset that
omits it should leave the spinbox at its widget default (1.0), not reset
to a hard-coded value on every preset load.

## Display-Only Parameter Pattern (db_reference)

`db_reference` affects only how amplitudes are displayed — it is NOT a
compute input. Design rule:

| Location | Include `db_reference`? |
|---|---|
| `_fft_compute_cache_params()` | NO — triggers unnecessary recompute |
| `_order_compute_cache_params()` | NO |
| `_fft_render_signature()` | YES — stale-check must detect the change |
| `get_params()` / `current_params()` | YES — passed to render functions |

Wire immediate re-render via `QTimer.singleShot(0, ...)` so the display
updates on `valueChanged` without blocking the spinbox interaction:

```python
self.inspector.fft_ctx.spin_db_ref.valueChanged.connect(
    lambda _: QTimer.singleShot(0, self._enter_fft_mode)
)
```

## Order Heatmap Pre-Conversion Rule

When `amplitude_mode == 'amplitude_db'`, convert the matrix to dB
**before** calling `plot_or_update_heatmap`, then pass
`amplitude_mode='amplitude'` to the canvas:

```python
if amp_mode_token == 'amplitude_db':
    db_ref = max(float(order_params.get('db_reference', 1.0)), 1e-12)
    matrix = 20.0 * np.log10(np.clip(matrix, 1e-12, None) / db_ref)
    plot_amp_mode = 'amplitude'
    cbar_label = f'Amplitude (dB re {db_ref:g})'
```

Still set `canvas._amplitude_mode = amp_mode_token` (the original
`'amplitude_db'`) so that slice-axis labels continue to read "dB".

Passing raw linear data with `amplitude_mode='amplitude_db'` causes the
canvas to normalise by the matrix peak, which makes `z_floor/z_ceiling`
manual color-scale controls ineffective.

## Edit-Tool Uniqueness Trap

When two methods in the same file share an identical trailing block
(e.g. the `if 'amp_y' in d: ...` lines appear identically in both
`apply_params` and `_apply_preset_values`), the Edit tool's
`old_string` must include enough surrounding context from only ONE
of the two to be unique. Using a comment or code fragment that is
present only in the target method (e.g. the overlap-fraction conversion
comment in `apply_params`) solves this without touching unrelated code.
