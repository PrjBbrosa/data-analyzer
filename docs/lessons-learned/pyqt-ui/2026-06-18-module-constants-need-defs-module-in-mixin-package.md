---
role: pyqt-ui
tags: [package-split][mixin][constants][circular-import][monkeypatch]
created: 2026-06-18
updated: 2026-06-18
cause: insight
supersedes: []
---

## Context

When splitting a monolithic QMainWindow file into a `main_window/` package
with mixin subfiles, module-level string constants (e.g. `DBC_DISABLED_TOOLTIP`,
`REPLAY_TAB_TITLE`) that were at the top of the monolith need a home.

## Lesson

Put shared module-level constants in a dedicated `_defs.py` inside the
package rather than in `window.py` or `__init__.py`. If the constants were
in `window.py`, mixins that import them would create a circular import
(`window.py` imports mixins; a mixin importing from `window.py` closes the
cycle). If they were in `__init__.py`, the same circular problem appears
because `__init__.py` imports from `window.py`. A neutral `_defs.py` that
imports nothing from the package breaks the cycle.

## How to apply

When extracting a mixin package from a QMainWindow: (1) identify all
module-level constants the mixins reference; (2) move them verbatim to
`_defs.py` with no intra-package imports; (3) have `window.py` and each
mixin import from `._defs`; (4) re-export the constants from `__init__.py`
so callers using the old `from package import CONSTANT` path still work.
