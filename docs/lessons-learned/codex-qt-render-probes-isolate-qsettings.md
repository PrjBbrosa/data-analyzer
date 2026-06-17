---
id: codex-qt-render-probes-isolate-qsettings
status: active
owners: [codex]
keywords: [qt, qsettings, render-probe, screenshot, inspector, persistence]
paths: [mf4_analyzer/ui/**, tools/*screenshot*.py, scripts/*smoke*.py, tests/ui/**]
checks: [rg -n "QSettings|set_expanded|setChecked|sync\\(" tools scripts tests mf4_analyzer/ui]
tests: [tests/ui/test_inspector.py]
---

# Qt Render Probes Isolate QSettings

Trigger: Writing or running Qt screenshot/render probes, smoke scripts, or UI
tests that instantiate persistent widgets backed by `QSettings`.

Past failure: A one-off offscreen Inspector render probe called
`set_expanded(True)` on the real `_CollapsibleParamSection`, which wrote
`inspector/{fft,order,fft_time}/params_expanded=true` into the local
`MF4Analyzer/DataAnalyzer` settings store. The next app launch appeared to
violate the default-collapsed spec even though the code default was correct.

Rule: Render probes must isolate persistent UI state. Use a temp INI
`QSettings` when the widget supports injection, or snapshot and restore/remove
the exact real settings keys around the probe. Do not call persistence-writing
setters on real application settings without cleanup.

Verification: Before finishing a Qt visual probe, grep for `QSettings` and
persistent setters in the probe path, then verify affected real keys are either
unchanged or cleared. For Inspector param sections, confirm fresh construction
prints `expanded=False` for `fft`, `order`, and `fft_time`.
