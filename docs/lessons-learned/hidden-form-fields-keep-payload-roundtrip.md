---
id: hidden-form-fields-keep-payload-roundtrip
status: active
owners: [codex]
keywords: [get_params, apply_params, visible_field_names, overlap, hidden-field, batch, fft]
paths: [mf4_analyzer/ui/drawers/batch/method_buttons.py]
checks: [git diff --check]
tests: [tests/ui/test_batch_method_buttons.py]
---

# Hidden Form Fields Keep Payload Round-Trip

Trigger: Hiding a Batch/Inspector form field because it is no longer applicable to the current method or mode.

Past failure: FFT ordinary `overlap` was removed from the visible field list. `get_params()` only emitted keys in `visible_field_names()`, so old recipes and 单帧 `effective_facts` would have dropped `overlap` on the next save even though `apply_params` still accepted it.

Rule: Visibility and serialization are separate. If a historical payload key still lives on a hidden widget, `get_params()` / `apply_params()` must keep reading and writing that widget value. Do not clear, normalize away, or change DSP meaning just because the row is hidden. If numeric or historical interpretation must change, revise the spec first.

Verification: `tests/ui/test_batch_method_buttons.py::test_fft_hides_ordinary_overlap_but_round_trips_old_payload` and `test_phase2_all_method_controls_round_trip`; do not edit `batch_compute.py` for a hide-only change.
