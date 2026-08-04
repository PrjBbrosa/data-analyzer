---
id: batch-free-config-cross-source-rpm-pairing
status: active
owners: [codex]
keywords: [batch, order, rpm, cross-source, multirate, hdf, interpolation]
paths:
  - mf4_analyzer/ui/drawers/batch/sheet.py
  - mf4_analyzer/batch.py
  - tests/ui/test_batch_input_panel.py
checks:
  - git diff --check
tests:
  - tests/ui/test_batch_input_panel.py::test_free_order_preset_binds_unique_cross_source_rpm
  - tests/test_batch_source_integration.py
---

# Free-Config Batch RPM Keeps Its Logical Source

Trigger: Editing BatchSheet free-config order analysis, RPM-channel selection,
or multi-rate logical-source handling such as HEAD HDF raster groups.

Past failure: The free-config UI retained only the RPM channel name. When a
wideband target signal and its low-rate RPM lived in different logical sources,
the batch runner searched for that RPM name on the target source and failed;
the runner's existing cross-source interpolation path was never selected.

Rule: If the selected free-config RPM channel occurs in exactly one loaded
logical source, attach its transient `(source_id, channel)` pair to the
`AnalysisPreset`. Keep a name-only RPM selection when it is available from
multiple sources, and reuse `BatchRunner._rpm_values()` for interpolation and
time-axis validation. Never serialize that runtime source identity into a
portable preset.

Verification: Run
`tests/ui/test_batch_input_panel.py::test_free_order_preset_binds_unique_cross_source_rpm`
and `tests/test_batch_source_integration.py`; run `git diff --check`.
