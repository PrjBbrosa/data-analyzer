# Manual Order RPM Design

## Goal

Allow Order/COT analysis to run when no RPM channel exists by letting the user switch the Order panel to a manually entered constant RPM.

## User Experience

- The Order signal card keeps the existing signal selector and RPM-channel selector.
- Add a compact RPM source mode control above or beside the RPM row:
  - `转速通道`: current behavior. Use the selected RPM channel and `RPM系数`.
  - `手动 RPM`: use a numeric RPM input instead of requiring an RPM channel.
- Default manual RPM is `1000 rpm`.
- Manual RPM input range is `1` to `100000 rpm`.
- Switching to manual mode should be quick: no modal, no separate dialog, and the compute button remains the same `计算阶次图`.
- In manual mode the RPM-channel row is disabled or hidden enough that the user understands it is not required.

## Computation

- Do not change `COTOrderAnalyzer.compute(...)`.
- Add the fallback in UI-side RPM resolution:
  - `转速通道`: keep `_order_rpm_for(rpm_source, n, ...)` behavior.
  - `手动 RPM`: return `np.full(n, manual_rpm, dtype=float)`.
- The manual RPM array must be length-matched to the signal after the selected time range is applied.
- Existing speed suitability warnings still run on the resulting RPM array.
- Split Order views use the active Order panel mode:
  - Manual mode applies to every queued pane.
  - Channel mode keeps pane-local `rpm_source` behavior.

## Cache And Persistence

- Order cache keys must include the RPM mode and manual RPM value.
- Switching between channel RPM and manual RPM must force recomputation.
- Changing manual RPM must force recomputation.
- `OrderContextual.get_params()` / `current_params()` should emit:
  - `rpm_mode`: `"channel"` or `"manual"`
  - `manual_rpm`: float
- `OrderContextual.apply_params(...)` should restore those keys so project/session persistence works through existing `AnalysisViewState.params`.
- Existing project `pane.rpm_source` persistence remains unchanged.

## Batch Boundary

This change is scoped to the interactive Order panel. It does not add manual RPM support to batch free-config execution in this pass.

## Testing

- `OrderContextual` tests cover default channel mode, switching to manual mode, parameter round-trip, and row enablement.
- Order mixin tests cover manual RPM producing a constant RPM array, bypassing missing `rpm_source`, and making cache params differ by mode/value.
- Existing Order multiview and Inspector tests remain green.

## Acceptance Criteria

- A user can compute Order/COT with a signal selected and no RPM channel selected by switching to `手动 RPM` and entering an RPM.
- Existing RPM-channel workflows continue to behave as before.
- Manual RPM is saved/restored with analysis view parameters.
- Focused tests pass in the repo `.venv`.
