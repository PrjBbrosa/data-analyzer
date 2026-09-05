# T0–T4 offscreen implementation note

Date: 2026-09-05. Platform: macOS offscreen Qt (`QT_QPA_PLATFORM=offscreen`). Status: **partial**.

HEAD at implementation: `e5ec1fa9a52f6316fe14f0c1af24dc2e9d1e7c0e`. Worktree also contains unrelated dirty files outside this task; those were not reverted or staged.

## Gates

| Gate | Result |
|---|---|
| G1 owner tests (geometry, message dialog, dirty guard, P1 windows) | PASS, offscreen |
| G2 focused/boundary listed in the plan | PARTIAL: T0–T4 owners and listed boundaries PASS; T5 ledger still pending |
| G3 Cocoa demo | UNVERIFIED |
| G4 Windows 100% native demo | UNVERIFIED |
| G5 Full/Lite frozen | UNVERIFIED |

T5/T6/T7 were not started. The unsaved-project prompt is wired to `AppMessageDialog`; other `QMessageBox` call sites stay in place until G3/G4 pass.

## Commands

Focused owners and boundaries were run with:

`TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -q <owner files>`

`tests/acquisition_ui/test_message_box_button_fit.py` was run in a separate process after the helper stopped writing `min-width` into widget stylesheets.

Full `tests/ui` and the two-process product suite were not run.

## Not claimed

Foreground Cocoa pixels, Windows native geometry, frozen Full/Lite, or “Windows dialog layout is fixed.”
