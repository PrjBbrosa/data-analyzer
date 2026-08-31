---
id: wwt-exact-binding-does-not-pin-global-custom-x
status: active
owners: [codex]
keywords: [wwt, custom-x, exact-source, per-source-name, curve-binding, same-name]
paths:
  - mf4_analyzer/ui/wwt_view_import.py
  - mf4_analyzer/ui/time_curve_bindings.py
  - mf4_analyzer/ui/time_xaxis.py
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_wwt_view_import.py tests/ui/test_wwt_import_flow.py -q
tests:
  - tests/ui/test_wwt_import_flow.py::test_fresh_wwt_view_uses_later_sources_own_same_name_x
---

# WWT Exact Bindings Must Not Pin Global Custom X

Trigger: Changing WWT View proposals, curve bindings, or the Inspector custom-X
resolver for a native channel-backed X axis.

Past failure: A fresh WWT import correctly stored its original curve's concrete
X ``fid`` in ``TimeCurveBinding.x_ref``, then copied that identity into the
View-wide ``exact_source`` Inspector spec. A later same-named source therefore
used the old file's X; unequal lengths were skipped and equal lengths could
silently plot against the wrong physical coordinates.

Rule: Keep native WWT curve identity exact inside each binding, but expose a
shared channel-backed Inspector X as ``per_source_name`` so ordinary curves
added later use their own source's X. Reserve View-wide ``exact_source`` for
historical persisted-state compatibility.

Verification: Use committed synthetic fixtures to combine a fresh WWT View
with same-name sources whose X arrays are both equal-length/different-value and
unequal-length. Assert every curve uses its own X, while the original binding
still retains its concrete ``fid`` and legacy project restore stays exact.
