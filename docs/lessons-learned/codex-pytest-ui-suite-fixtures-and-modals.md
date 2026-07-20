---
id: codex-pytest-ui-suite-fixtures-and-modals
status: active
owners: [codex]
keywords: [pytest, pyqt, conftest, qmessagebox, offscreen]
paths: [tests/ui/**]
checks:
  - Keep explicit tests/ui paths contiguous in one pytest invocation, or run non-UI tests separately.
  - Stub modal confirmation decisions before QTest mouse/keyboard actions in offscreen tests.
tests:
  - tests/ui/test_main_window_smoke.py::test_multi_selected_channel_checkbox_plots_all_selected
  - tests/ui/test_split_focus_routing.py
---

# Keep Headless PyQt Test Fixtures And Modals Deterministic

Trigger: Running explicit PyQt test-file lists, especially after adding a
confirmation dialog to an interaction exercised through QTest.

Past failure: A pytest command entered `tests/ui`, collected a non-UI test,
then returned to `tests/ui`; the later files lost `tests/ui/conftest.py` and
reported `loaded_csv` missing. In the same verification run, an old QTest
checkbox click opened the new native confirmation dialog without a stub and
the offscreen Qt process ended with an access violation.

Rule: Keep all explicit `tests/ui` paths contiguous (put non-UI paths last or
run them separately). Before an offscreen QTest action that opens a modal,
patch the dialog/decision seam to an explicit result and assert the expected
confirmation call.

Verification: Re-run the UI file list without leaving and re-entering
`tests/ui`; run the modal interaction test directly and confirm it completes
without a live dialog or Qt crash.
