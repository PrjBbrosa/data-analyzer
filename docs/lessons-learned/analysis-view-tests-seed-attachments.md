---
id: analysis-view-tests-seed-attachments
status: active
owners: [codex]
keywords: [analysis_views, attached_file_ids, source-isolation, pytest]
paths:
  - tests/ui/test_analysis_multiview_integration.py
  - tests/ui/test_frf_main_window.py
  - mf4_analyzer/ui/main_window/_channel_scope_mixin.py
checks:
  - "rg -n \"_seed_active_analysis_attachments|_attach_files_to_active_context|attached_file_ids\" tests/ui/test_analysis_multiview_integration.py tests/ui/test_frf_main_window.py"
tests:
  - "TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_analysis_multiview_integration.py tests/ui/test_frf_main_window.py tests/ui/test_analysis_source_scope.py -q"
---

# Analysis View Tests Must Seed Attachments

Trigger: Writing or updating integration tests that switch into FFT / FFT-vs-Time /
Order / FRF and then tick navigator channels, Inspector combos, or compute.

Past failure: Stage 1 source isolation left analysis Views with empty
``attached_file_ids`` by default (auto-attach on load only joins the time View).
Tests that switched mode and asserted checked channels / pickers / compute saw
``set()`` or empty combos even though files were loaded.

Rule: After entering an analysis section, seed the active analysis View via
``_attach_files_to_active_context`` (or set ``attached_file_ids`` on constructed
``AnalysisViewState``) before selecting signals or computing. Do not auto-copy
time attachments in product code. Keep new empty analysis Views unseeded when
the test asserts emptiness. Mock ``_confirm_global_channel_delete`` in headless
tests that delete channels referenced by Views.

Verification: Focused pytest on the analysis multiview / FRF / source-scope
suites under offscreen Qt; confirm new analysis View emptiness tests still pass
without seeding.
