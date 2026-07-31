---
id: pyqt-ui/2026-07-30-identity-sensitive-yfit-must-not-fallback-to-display-label
status: active
owners: [codex]
keywords: [pyqtgraph, channel-identity, display-label, composite-key, y-fit, multi-file]
paths: [mf4_analyzer/ui/pg_canvas/canvas.py, mf4_analyzer/ui/pg_canvas/_shared.py]
checks: [resolve_unique]
tests: [tests/ui/test_pg_multifile_samename_curves.py]
---

# Identity-sensitive Y-fit must not fall back to an ambiguous display label

Trigger: A canvas path restores, fits, caches, or mutates per-channel state and
has both a composite channel key and a user-facing display label available.

Past failure: `restore_visible_ylims` converted the composite key back to a
display label before fitting. Two files with the same displayed channel name
therefore fitted file A's axis from file B's `[100, 200]` samples.

Rule: Preserve the composite key through every identity-sensitive path. A
legacy display-label fallback is allowed only after an explicit uniqueness
check; an ambiguous label must fail closed without changing state.

Verification: Run
`QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_multifile_samename_curves.py -q`
and confirm the subplot and overlay collision cases keep file A near `[-1, 1]`.
