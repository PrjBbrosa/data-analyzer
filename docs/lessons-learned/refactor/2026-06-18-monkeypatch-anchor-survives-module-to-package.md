# monkeypatch-anchor-survives-module-to-package

**Date:** 2026-06-18
**Updated:** 2026-06-18
**Cause:** insight
**Tags:** [arch][import-cycle][monkeypatch][package-split][same-named-package]

## Context

Splitting a monolithic `.py` into a same-named package (`X.py` → `X/`)
introduces a subtle test-compatibility problem: any test that does

```python
monkeypatch.setattr("mf4_analyzer.ui.inspector_sections.QMenu", _StubMenu)
```

expects to patch the `QMenu` name that the CODE inside the old module used.
In the monolithic file, `_show_menu` referenced the module-level `QMenu`
name — the same name the monkeypatch targeted.

After the split, `PresetBar._show_menu` lives in
`mf4_analyzer.ui.inspector_sections.presets`, which has its own
`from PyQt5.QtWidgets import QMenu` binding. Monkeypatching
`mf4_analyzer.ui.inspector_sections.QMenu` (the `__init__.py` re-export)
does NOT patch `presets.QMenu`, so `_show_menu` keeps calling the real
`QMenu`, which blocks on an event loop waiting for user input.

## Fix

In the sub-file that owns the method, replace the static import-time
binding with a **runtime lookup through `sys.modules`** at call time:

```python
def _show_menu(self, slot, pos):
    import sys as _sys
    _pkg = _sys.modules.get('mf4_analyzer.ui.inspector_sections')
    _QMenu = getattr(_pkg, 'QMenu', QMenu) if _pkg is not None else QMenu
    menu = apply_rounded_menu_chrome(_QMenu(self))
```

By the time any user calls `_show_menu`, the package is already imported
(no circular-import risk). The `sys.modules` lookup finds the
`__init__.py` namespace; monkeypatch can then substitute its `StubMenu`
there, and the sub-file's call picks it up.

## Second confirmed case (phase C — chart_stack)

`tests/ui/test_split_per_pane_controls.py` patches
`mf4_analyzer.ui.chart_stack.QFileDialog.getSaveFileName`. After
`chart_stack.py` was split into `chart_stack/`, `save_figure()` moved to
`toolbar.py` (which imports `QFileDialog` from `PyQt5.QtWidgets`). The same
failure pattern occurred: the monkeypatch target (`chart_stack.QFileDialog`)
was not the binding `save_figure()` called.

Fix applied verbatim: `QFileDialog` imported in `__init__.py` (monkeypatch
anchor), and `save_figure()` uses `sys.modules.get('mf4_analyzer.ui.chart_stack')`
at call time.

## Rules

1. When splitting a monolith into a package, **grep for every symbol that
   tests monkeypatch** in the old module path. Each such symbol must either
   stay in `__init__.py` (not delegated to sub-files) OR the sub-file code
   that uses it must do a deferred `sys.modules` lookup so the monkeypatch
   target is the package namespace.

2. A re-export (`from .presets import QMenu`) in `__init__.py` alone is
   NOT sufficient — it creates a copy of the binding, not an alias to it,
   so patching `__init__.QMenu` does not affect `presets.QMenu`.

3. The `sys.modules.get(package_name)` pattern is safe because Python
   guarantees the package module object exists in `sys.modules` from the
   moment its `__init__.py` finishes executing — well before any user code
   calls instance methods.

4. **Grep pattern to use before splitting any `.py`:** search both the
   test suite and production callers for `monkeypatch.setattr("<old_module_path>.*")`
   — every symbol found is a required anchor.
