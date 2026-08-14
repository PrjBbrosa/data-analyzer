---
id: codex-pandas-lazy-import-avoids-collect-all
status: active
owners: [codex]
keywords: [pandas, lazy-import, pyinstaller, collect-all, channel_frame, sys.modules]
paths:
  - mf4_analyzer/io/channel_frame.py
  - mf4_analyzer/io/source_adapters.py
tests:
  - tests/test_channel_frame.py
---

# `is_pandas_dataframe` Reads `sys.modules`, Never `import`s

Trigger: Touching `mf4_analyzer/io/channel_frame.py`'s `is_pandas_dataframe` /
`is_tabular_frame`, or adding a new lazy/optional dependency check inside
`mf4_analyzer/io`.

Past failure (motivation, not yet observed as a regression): a naive
`isinstance(obj, pandas.DataFrame)` type check needs `import pandas` in
scope. Doing that with a normal top-level or function-body `import pandas`
statement gets picked up by
`mf4_analyzer.io.runtime_dependencies`'s lazy-import scan (see
`codex-frozen-import-dependency-contract.md`) and by PyInstaller's static
import analysis, both of which then treat pandas as a package this module
needs to pull in — on the Windows lite build flavor that forces
`--collect-all pandas`, a large, avoidable size/scan-time cost for a
function whose only job is a type check.

Rule: `channel_frame.py:87-95`'s `is_pandas_dataframe` reads
`sys.modules.get("pandas")` instead of importing pandas itself:

```python
def is_pandas_dataframe(obj: Any) -> bool:
    # pandas is already a top-level io import on loader paths. A nested
    # ``import pandas`` here is scanned as a lazy frozen dependency and
    # would force ``--collect-all pandas``. If pandas is not loaded, no
    # DataFrame instance can exist in this process.
    pd = sys.modules.get("pandas")
    if pd is None:
        return False
    return isinstance(obj, pd.DataFrame)
```

This is safe, not just convenient: `channel_frame.py`'s sole caller,
`mf4_analyzer/io/source_adapters.py`, already has a real, unconditional
`import pandas as pd` at its module top (line 30). Any process where
`is_tabular_frame`/`is_pandas_dataframe` can be reached has therefore
already imported pandas through the normal, declared path — pandas is a
non-optional `requirements.txt` dependency (not one of the lazily-declared
optional importers like scipy/h5py). `sys.modules.get` here is purely
avoiding a *second*, redundant, statically-scannable import site; it never
changes whether pandas ends up bundled. If `is_pandas_dataframe` ever grows
a caller that can run before `source_adapters` imports, add a real,
declared `import pandas` at that caller's top instead of relying on this
function to have side-effect-imported it.

Verification: `tests/test_channel_frame.py` covers `is_pandas_dataframe` /
`is_tabular_frame` behavior with and without a real DataFrame instance.
`tests/test_native_import_boundaries.py` / the frozen dependency contract
(`codex-frozen-import-dependency-contract.md`) are the mechanical guards
that would catch a stray lazy `import pandas` being reintroduced.
