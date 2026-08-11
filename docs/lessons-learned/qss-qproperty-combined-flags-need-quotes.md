---
id: qss-qproperty-combined-flags-need-quotes
status: active
owners: [codex]
keywords: [qss, stylesheet, qproperty-alignment, style.qss, parse failure, platform default chrome]
paths: [mf4_analyzer/ui_kit/style.qss, mf4_analyzer/ui_kit/stylesheet.py, tests/ui_kit/test_stylesheet_parses.py]
checks:
  - TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui_kit/test_stylesheet_parses.py -q
  - "rg -n \"qproperty-[a-zA-Z-]+:\\s*[^';\\n]*\\\\|\" mf4_analyzer/ui_kit/style.qss && exit 1 || true"
tests: [tests/ui_kit/test_stylesheet_parses.py]
---

# QSS Combined qproperty Flags Need Quotes

Trigger: Editing `mf4_analyzer/ui_kit/style.qss` (or any app-wide QSS template),
especially `qproperty-*` declarations, alignment/flags, or any value that uses
`|` / multiple tokens.

Past failure: `650fecdf` wrote
`qproperty-alignment: AlignVCenter | AlignLeft` without quotes on
`#computeProgressLabel`. Qt rejects that as QSS syntax, and **drops the entire
application stylesheet** — every widget silently falls back to platform-default
chrome (segmented-control grey fill gone, default button radii, lost text
colors, View chrome looking “restyled”). The failure is lazy: it only surfaces
when a live widget is polished, so widget-local unit tests never catch it.
Claude fixed it in `3ab58b48` by quoting
`qproperty-alignment: 'AlignVCenter | AlignLeft'` and adding
`tests/ui_kit/test_stylesheet_parses.py`.

Rule: In app-wide QSS, any `qproperty-*` value with combined flags **must** be
a single quoted string (e.g. `'AlignVCenter | AlignLeft'`). Prefer setting
such properties in Python (`setAlignment(...)`) when touching only one widget,
instead of risking the global sheet. After any `style.qss` edit, run
`tests/ui_kit/test_stylesheet_parses.py` — do not treat “local widget tests
passed” as proof the app sheet still parses. A sudden “whole UI theme
disappeared / colors and positions look wrong” after a tiny QSS tweak is this
failure until proven otherwise; do not chase unrelated bottom-dock or layout
commits first.

Verification:
- `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui_kit/test_stylesheet_parses.py -q`
- Grep new `qproperty-` lines in `style.qss` for unquoted `|` combinations.
- If the change is visual, confirm foreground chrome (segmented controls /
  status bar) still carries product QSS, not platform defaults.
