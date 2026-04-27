# FFT / Order Analysis · HEAD Parity Design Spec

**Date:** 2026-04-28
**Author:** Claude (Sonnet 4.6)
**Status:** Draft → review pending

---

## 1. Background

Users compare our FFT and Order analysis output against HEAD acoustics' ArtemiS suite. Two
specific complaints surfaced on test file `T08_YuanDi_FOC_CurrentMode_0-1-2_Ripple.MF4`
(fs=100Hz, ~176s, with ±300 RPM step changes):

1. FFT spectra at the same `nfft=4096` look noticeably noisier in our app than in HEAD
2. Order analysis cannot resolve the visible 2nd-order ripple — the order ridge is smeared
   across order 1-3 instead of forming a clean horizontal line at order=2

A third orthogonal request: every channel-selection dropdown in the app needs a search box,
because long channel lists in MF4 files (50-300 channels) are tedious to navigate.

## 2. Findings — what's algorithm vs. what's display

### 2.1 FFT (`mf4_analyzer/signal/fft.py`)

**Mathematics is correct and matches HEAD.** Verified:
- Bin-aligned 1.0-amplitude sine: peak = 1.0000 (exact)
- Off-bin 10.3 Hz sine: peak = 0.9919 (Hann scallop loss, identical in HEAD)
- One-sided amplitude formula `2·|X|/sum(w)`: textbook correct
- DC and Nyquist bins correctly NOT doubled

**Visual gap with HEAD comes from**:
- (a) HEAD averages multiple frames (Welch / linear average); our FFT view shows single frame
- (b) `compute_averaged_fft` exists at `fft.py:179` but is never called from the UI
- (c) HEAD's typical signals (run-up, steady-state) average cleanly; non-stationary signals
  like T08 still look noisy even with averaging

**Conclusion**: enable Welch averaging in the FFT view; document that non-stationary signals
will not become "perfectly clean" no matter what.

### 2.2 Order (`mf4_analyzer/signal/order.py`)

**Algorithm fundamentally differs from HEAD**:

| Dimension | Our `OrderAnalyzer` | HEAD COT |
|-----------|---------------------|----------|
| Domain | Time-domain FFT | Angle-domain FFT |
| Pipeline | Time window → FFT → map freq→order via mean RPM | RPM → integrate to angle θ(t) → resample s(t)→s(θ) at uniform Δθ → FFT s(θ) → orders direct |
| Variable RPM | Order frequency walks across bins → smearing | Orders are stationary in angle domain → no smearing |
| `nfft=4096` at varying RPM | Smeared ridge | Clean ridge |

**Conclusion**: implement Computed Order Tracking (COT) as a new analyzer. Existing
frequency-mapped analyzer stays as fast-path option for short stationary segments.

### 2.3 Display

Several genuine display issues independent of algorithm:

- Order heatmap renders linear-amplitude with auto vmin/vmax, dominated by transient
  vertical stripes when RPM steps; no dB option at all
- Sub-bin "orders" (e.g. order 0.1 at low RPM where df·60/RPM > 0.1) accumulate DC drift
  content, dominate `vmax`, hide real ridges
- FFT 1D view's PSD subplot is hardcoded to dB; user wants linear option for parity with
  the Amplitude subplot
- FFT vs Time dB dynamic range options are `[Auto, 60dB, 80dB]`; user reports daily
  workflow uses 30-50dB

### 2.4 Channel selection UX

All channel-pick dropdowns currently use plain `QComboBox`. With long channel lists
(50-300 entries), users cannot search. Need to add type-to-filter behavior to:
`TimeContextual`, `FFTContextual.combo_sig`, `OrderContextual.combo_sig`,
`OrderContextual.combo_rpm`, `FFTTimeContextual.combo_sig`, batch dialog channel pickers,
edit-channels dialog.

## 3. Goals

| Goal | Done when |
|------|-----------|
| G1 — FFT view matches HEAD on stationary signals | Welch averaging mode toggle in `FFTContextual`; on a synthetic 30-sec stationary 10Hz tone the averaged spectrum noise floor is visibly lower than single-frame |
| G2 — FFT amplitude/PSD axis can be switched between linear and dB | Two combos in `FFTContextual`; user can pick per axis independently |
| G3 — Order heatmap visibility matches HEAD on variable-RPM data | dB rendering + 30/50/80dB dynamic range option, default 30dB; sub-bin pseudo-orders auto-clipped |
| G4 — Order analysis matches HEAD on variable-RPM data | New COT analyzer that produces a clean order=2 ridge on T08 file (visually verifiable + numerical RMS test) |
| G5 — Channel pick dropdowns are searchable | Type-to-filter case-insensitive substring match; works on every existing channel-pick combo |

## 4. Non-Goals

- Real-time / streaming analysis
- 3rd-octave band analysis
- Vold-Kalman order tracking (a more advanced filter-based method; keep the simpler resampling COT)
- Replacing the existing time-domain `OrderAnalyzer` (it stays as a fast option)
- Tach-pulse-based order tracking (we only have continuous RPM channels)
- Mac-native SF Symbols icon library swap (deferred; qtawesome MDI already in)

## 5. Sub-projects

This spec covers FOUR independently shippable sub-projects. Each has its own implementation
plan and can ship without the others.

### SP1 — Searchable channel dropdowns
- New widget `mf4_analyzer/ui/widgets/searchable_combo.py`
- Replace every channel-pick `QComboBox` instantiation
- Independent of FFT/order changes; ships first

### SP2 — FFT 1D view enhancements
- Add Welch averaging toggle and overlap to `FFTContextual`
- Add per-axis linear/dB toggles
- Wire to `compute_averaged_fft`
- Independent of order work

### SP3 — Order heatmap rendering polish
- Add dB rendering to `plot_or_update_heatmap`
- Add `combo_amp_mode` and `combo_dynamic` to `OrderContextual`
- Add sub-bin pseudo-order floor to `OrderAnalyzer._orders`
- Independent of COT work

### SP4 — Computed Order Tracking (COT)
- New module `mf4_analyzer/signal/order_cot.py`
- New `COTOrderAnalyzer` class parallel to existing `OrderAnalyzer`
- Add algorithm-pick combo to `OrderContextual` (frequency-mapped vs COT)
- Depends on SP3 only for shared rendering polish; otherwise standalone

## 6. Architecture decisions

### 6.1 New widget: `SearchableComboBox`
Subclass of `QComboBox` that:
- Sets `setEditable(True)`
- Attaches a `QCompleter` with `MatchContains` + `CaseInsensitive`
- Auto-rebinds completer model on every `addItem`/`addItems`/`clear`/`setCurrentText`
- Default popup behavior: type-to-narrow with arrow keys to confirm; `Esc` clears filter
- Drop-in replacement for `QComboBox` — same signals, same methods

### 6.2 dB rendering for order heatmap
Reuse the dB conversion logic already in `SpectrogramCanvas` (`canvases.py:1310-1345`).
Add `amplitude_mode` and `dynamic` parameters to `PlotCanvas.plot_or_update_heatmap`. The
canvas computes dB internally from the linear matrix passed in; analyzer always returns
linear amplitude (no DSP-layer change).

### 6.3 Sub-bin floor in `OrderAnalyzer._orders`
Currently `_orders` returns `np.arange(order_res, max_order + ε, order_res)`. After fix:

```python
def _orders(max_order, order_res, fs=None, nfft=None, rpm=None):
    base = np.arange(order_res, max_order + order_res * 0.5, order_res)
    if fs is None or nfft is None or rpm is None:
        return base                                      # legacy callers stay untouched
    df = fs / nfft
    rpm_max = float(np.nanmax(np.abs(rpm)))
    if rpm_max <= 0:
        return base
    min_order = max(order_res, df * 60.0 / rpm_max)
    return base[base >= min_order]
```

`compute_time_order_result` and `extract_order_track_result` pass the optional args.
Backwards compatible: legacy callers without args get the old behaviour.

### 6.4 COT algorithm

Pipeline implemented in `order_cot.py`:

```
1. abs_rpm = np.abs(rpm)                       # treat reverse rotation as forward
2. omega   = abs_rpm * 2π / 60                 # rad/s
3. theta   = cumtrapz(omega, t, initial=0)     # rad, monotonic
4. theta_max = theta[-1]
5. dtheta = 2π / samples_per_rev               # default samples_per_rev = 256
6. theta_uniform = arange(0, theta_max, dtheta)
7. s_theta  = np.interp(theta_uniform, theta, sig)
8. For each order frame (nfft samples in angle domain, hop):
     w = hann(nfft)
     X = rfft(s_theta[start:start+nfft] * w)
     amp = 2*|X| / sum(w)                      # one-sided, window-corrected
     orders[k] = k * (samples_per_rev / nfft)  # bin → order direct
9. Frame center time = interp(theta_at_frame_center → t)
```

**Edge cases**:
- **RPM=0 segments**: theta is flat → `np.interp` repeats samples → spurious DC. Detect
  near-zero RPM frames (mean |RPM| < `min_rpm_floor`, default 10) and zero out their amplitude
- **Sign change (forward/reverse)**: using `|RPM|` collapses both directions. First version
  ignores; future enhancement: split into ±RPM segments

Unit tests with synthetic signals:
- Constant RPM + pure 2nd order → COT shows clean spike at order=2, no smearing
- Variable RPM (5→50 rad/s sweep) + pure 2nd order → COT still shows spike at order=2;
  frequency-mapped analyzer smears across multiple orders

### 6.5 UI parameter persistence
All new combo/spinbox state must round-trip through existing preset save/load logic
(`current_params()` / `apply_params()` on each contextual widget). No new persistence
mechanism — extend the existing dict.

## 7. Verification strategy

| Sub-project | Verification |
|-------------|--------------|
| SP1 | Unit test: type "Rte_RPS" into searchable combo, only matching items remain in popup |
| SP2 | Unit test: averaged FFT noise floor lower than single-frame on synthetic noisy stationary signal; per-axis linear/dB toggle reflected in rendered y-label |
| SP3 | Unit test: order heatmap with `amplitude_mode='amplitude_db', dynamic='30 dB'` clamps display matrix to [-30, 0]; sub-bin floor drops orders < df·60/max\|RPM\| |
| SP4 | Unit test: synthetic constant-RPM 2nd order → COT amp at order=2 ≥ 10× amp at order=1.5; sweeping RPM → same property holds; legacy `OrderAnalyzer` smears (control case) |

End-to-end manual check (deferred to user):
- Open T08 file
- Switch order analyzer to COT
- Verify horizontal bright line at order=2 across the entire RPM-active window

## 8. Open questions

None. All design choices made, defaults specified, edge cases noted.

## 9. Out of scope risks

- **macOS-specific RPM channel sign**: this app reads positive AND negative RPM. COT v1
  uses `|RPM|`. If user has data where reverse rotation has different orders, v1 will
  alias them onto forward-rotation orders. Documented; v2 issue.
- **Welch averaging on non-stationary signals**: noise reduction is small (~1dB on T08).
  This is honest behavior, not a bug. Documented in tooltip.
