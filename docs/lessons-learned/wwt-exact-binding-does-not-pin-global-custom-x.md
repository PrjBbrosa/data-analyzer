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
  - tests/ui/test_wwt_view_import.py::test_cross_source_channel_xy_keeps_exact_curve_binding
---

# WWT Exact Bindings Must Not Pin Global Custom X

Trigger: Changing WWT View proposals, curve bindings, or the Inspector custom-X
resolver for a native channel-backed X axis.

Past failure: A fresh WWT import correctly stored its original curve's concrete
X ``fid`` in ``TimeCurveBinding.x_ref``, then copied that identity into the
View-wide ``exact_source`` Inspector spec. A later same-named source therefore
used the old file's X; unequal lengths were skipped and equal lengths could
silently plot against the wrong physical coordinates.

Rule: Expose a shared channel-backed Inspector X as ``per_source_name`` so
ordinary curves added later use their own source's X. A fresh WWT curve may
drop its exact binding only when its X and Y resolve from the same logical
source and the ordinary Custom-X path is equivalent. Cross-source,
record-backed, or otherwise non-equivalent X/Y must retain the curve-local
exact binding. Reserve View-wide ``exact_source`` for historical persisted-
state compatibility.

Verification: Use committed synthetic fixtures to combine a fresh WWT View
with same-name sources whose X arrays are both equal-length/different-value and
unequal-length. Assert ordinary curves use their own X, an explicitly cross-
source WWT curve retains both concrete ``fid`` values, and legacy project
restore stays exact.
