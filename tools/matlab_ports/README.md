# Official MATLAB importer ports (standalone)

Faithful Python translations of ZFLS reference scripts — **not** part of the
TraceLab runtime.

Format findings (short blocks, exotic types, product-parser gaps):
[`docs/analyzer/specs/2026-08-11-wwt-zfd-official-import-notes.md`](../../docs/analyzer/specs/2026-08-11-wwt-zfd-official-import-notes.md).

| Script | Source | Purpose |
| --- | --- | --- |
| `wwt_import.py` | `testdoc/wwt_import.m` | WinWert `.wwt` |
| `zfd_import.py` | `testdoc/zfd_import.m` | ZFGE2 / TestRunPRO `.zfd` |
| `compare_wwt.py` | — | Diff official WWT port vs `mf4_analyzer.io.wwt_format` |
| `emit_wwt_export_candidates.py` | — | Synthetic `.wwt` for WinWert open trials |

Product writer: `mf4_analyzer/io/wwt_writer.py` (channel-editor 导出 → WinWert).

```bash
PYTHONPATH=. .venv/bin/python tools/matlab_ports/wwt_import.py testdoc/wwt/NLTNP_000089.wwt
PYTHONPATH=. .venv/bin/python tools/matlab_ports/zfd_import.py testdoc/RWS/Axial_000031.zfd
PYTHONPATH=. .venv/bin/python tools/matlab_ports/compare_wwt.py
PYTHONPATH=. .venv/bin/python tools/matlab_ports/emit_wwt_export_candidates.py
```

Requires only `numpy` (and TraceLab's venv if you run `compare_wwt.py` / the emitter).
