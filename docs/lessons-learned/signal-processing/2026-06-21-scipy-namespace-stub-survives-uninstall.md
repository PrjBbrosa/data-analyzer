---
role: signal-processing
tags: [scipy, numpy, window, dependency-removal, pip-uninstall]
created: 2026-06-21
updated: 2026-06-21
cause: insight
supersedes: []
---

## Context

After `pip uninstall scipy`, `import scipy` still succeeds (no ModuleNotFoundError)
but returns a namespace package stub with no attributes — `scipy.__version__`
raises AttributeError and `from scipy.signal import get_window` raises ModuleNotFoundError.

## Lesson

`pip uninstall scipy` removes the binary submodules but may leave a namespace package
entry, so `import scipy` succeeding is NOT proof scipy is available; only
`from scipy.signal import get_window` (or equivalent submodule import) proves it.

## How to apply

When verifying scipy removal, test `from scipy.signal import X` explicitly — not bare
`import scipy`. Golden-reference tests that avoid scipy imports are the correct
post-uninstall guard; they prove the runtime path is clean without relying on the
misleading namespace stub.
