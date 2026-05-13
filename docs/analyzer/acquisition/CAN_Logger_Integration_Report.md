# CAN Logger Integration Feasibility Report

**Version:** v2.0 feasibility rewrite  
**Date:** 2026-05-13  
**Repo:** `/Users/donghang/Downloads/data analyzer`  
**Goal:** Add a data-acquisition entry point to the current MF4/CSV/Excel analyzer, starting with XCP-over-CAN feasibility before committing to full UI integration.

---

## 1. Decision

**P0 can proceed. Full "DAQ tab + production acquisition" cannot proceed directly from the v1 draft.**

The correct next step is a small evidence-producing branch that proves:

1. A real A2L can be parsed into measurement names, ECU addresses, data types, units, and conversion metadata.
2. A Vector CAN device can be opened from the actual Windows/PyCharm environment.
3. XCP `CONNECT` and one known-variable `SHORT_UPLOAD` can read a sane value.
4. The captured sample can be saved as `.mf4` and opened by the existing analyzer loader.

Only after those four checks pass should the project move to DAQ streaming and UI integration.

---

## 2. Current Repo Facts

These are local facts from the current checkout, not assumptions.

| Area | Current evidence | Meaning for acquisition work |
| --- | --- | --- |
| App entry | `MF4 Data Analyzer V1.py` imports `mf4_analyzer.app.main`. `mf4_analyzer/app.py` constructs `mf4_analyzer.ui.MainWindow`. | Do not build a parallel `main.py` first. Extend the existing app entry path or add a clean sidecar prototype. |
| Main window | `mf4_analyzer/ui/main_window.py` defines `MainWindow(QMainWindow)`. | The v1 draft's `AnalysisWidget` does not exist in this repo. |
| File load path | `MainWindow.load_files()` calls private `_load_one(fp)` for MF4/CSV/Excel. | P0 should not wire UI to `analysis.load_file`; later work should add a public `open_file_from_path(fp)` wrapper. |
| MF4 reading | `mf4_analyzer/io/loader.py::DataLoader.load_mf4` uses `asammdf.MDF(fp)` and numeric channels. | P0 can prove compatibility by writing a small MF4 and loading it through `DataLoader`. |
| Existing deps | `requirements.txt` currently lists `numpy`, `pandas`, `PyQt5`, `matplotlib`, `scipy`, `asammdf`, `openpyxl`, `pytest`, `pytest-qt`. | Acquisition deps must be added in a feature branch, not silently assumed. |
| Local venv | `.venv` is Python 3.12.13; `asammdf` is installed; `python-can`, `pyxcp`, `pya2l`, `pya2ldb`, and `pyelftools` are not installed. | P0 must begin with dependency probing. |

---

## 3. External Dependency Position

Verified against official package/documentation pages on 2026-05-13.

| Dependency | Recommended P0 status | Reason |
| --- | --- | --- |
| `python-can[vector]` | Required on Windows for Vector access. | python-can's Vector interface documentation says Vector is Windows-only and uses Vector Hardware Configuration / `app_name`. |
| `pyxcp` | Evaluate, do not hard-wire first. | PyPI currently shows `pyxcp 0.29.8` and describes CAN/Ethernet/USB/Serial XCP support. It may be useful later, but P0 can use raw CAN frames for `CONNECT` and `SHORT_UPLOAD` to keep the proof small. |
| `pya2ldb` | Preferred A2L candidate for P0. | PyPI currently shows `pya2ldb 1.0.332`; it provides SQLite-backed A2L parsing and ORM access. |
| `pya2l` | Not preferred for main path. | PyPI currently shows `pya2l 0.1.10`, not the v1 draft's `pya2l>=0.3.0`; its API is parser/tree oriented and differs from `pya2l.load(...)`. |
| `pyelftools` | Optional fallback, not P0-critical. | Useful only if A2L addresses must be cross-checked against ELF/DWARF. The import package is `elftools`, not `pyelftools`. |
| `asammdf` | Already in repo; required. | P0 should use `MDF.append([Signal(...)])` then verify with `DataLoader.load_mf4`. |

P0 dependency target:

```txt
python-can[vector]>=4.6,<5
pyxcp==0.29.8
pya2ldb==1.0.332
pyelftools==0.32
```

Do not put these into `requirements.txt` until P0 proves they install and run in the Windows target environment.

---

## 4. Revised Architecture Direction

### 4.1 P0 Shape

P0 is not a UI feature. It is a command-line feasibility harness:

```text
can_logger/
  p0/
    mf4_probe.py              # write/load a tiny MF4 compatibility proof
    a2l_probe.py              # parse real A2L, print a small measurement summary
    vector_probe.py           # list/open Vector channels on Windows
    xcp_short_upload_probe.py # CONNECT + one SHORT_UPLOAD by known address
```

The acceptance artifact is a small `.mf4` created from a real or simulated acquisition value and opened by the current analyzer loader.

### 4.2 Later Production Shape

Only after P0 passes:

```text
can_logger/
  core/
    models.py
    a2l_adapter.py
    xcp_transport.py
    mf4_writer.py
  ui/
    acquisition_widget.py
    signal_selector.py
    realtime_plot.py
```

`mf4_analyzer.ui.MainWindow` should get a small public method:

```python
def open_file_from_path(self, fp: str) -> None:
    self._load_one(fp)
```

Then acquisition UI can emit the completed MF4 path and call that public method. Avoid inventing `AnalysisWidget` unless the existing main window is intentionally split in a later refactor.

---

## 5. Important Corrections From v1 Draft

| v1 draft item | Correction |
| --- | --- |
| `from mf4_analyzer.main_window import AnalysisWidget` | Invalid for current repo. Use existing `mf4_analyzer.ui.MainWindow`; later add `open_file_from_path`. |
| `self.analysis.load_file` | No such public method exists. Current load path is `load_files()` -> `_load_one(fp)`. |
| `pya2l>=0.3.0` and `pya2l.load(...)` | Not confirmed. Prefer `pya2ldb` P0 adapter and verify against a real A2L. |
| "实时追加写 MF4" | The v1 code buffered in memory and saved at stop. That is acceptable for P0, but it is not true streaming persistence. |
| DAQ first | Too risky. P0 should start with `SHORT_UPLOAD`; DAQ requires ECU capability discovery first. |
| `PID = DAQ List index` | Too optimistic for production. Needs ECU-specific proof and DAQ processor info before relying on it. |
| macOS Vector validation | Not viable for Vector hardware. python-can Vector interface is Windows-only. Use the Windows/PyCharm mirror for hardware checks. |

---

## 6. Branch Strategy

**Do not create an orphan/blank branch.** P0 must reuse the analyzer's current loader, tests, package layout, and history.

Recommended strategy:

1. Keep the current `main` history as the base.
2. Because this working tree already has unrelated modified UI/lesson files, run P0 implementation in a clean feature worktree:

   ```bash
   git worktree add ../data-analyzer-xcp-p0 -b feat/xcp-acquisition-p0 main
   cd ../data-analyzer-xcp-p0
   ```

3. Commit P0 in small checkpoints:
   - `docs: revise xcp acquisition feasibility`
   - `test: prove p0 mf4 output opens in analyzer`
   - `feat: add p0 a2l summary probe`
   - `feat: add p0 vector and xcp short-upload probes`
   - `docs: add p0 acquisition runbook results`

If the current uncommitted document changes should be included in the P0 branch, either commit them first on a docs branch or apply/copy the document patch into the clean P0 worktree. Avoid mixing unrelated UI work into the acquisition branch.

---

## 7. P0 Execution Plan Summary

Full implementation plan: `docs/analyzer/acquisition/plans/2026-05-13-xcp-acquisition-p0.md`

P0 should run in this order:

1. Create clean worktree branch from `main`.
2. Install dependencies in the target environment.
3. Run a hardware-free MF4 writer/loader test on macOS and Windows.
4. Run A2L parsing against the real ECU A2L.
5. On Windows, verify Vector channel listing/opening.
6. With ECU powered and CAN connected, run XCP `CONNECT`.
7. Read one known variable with `SHORT_UPLOAD`.
8. Save the read value to MF4 and open it through the analyzer loader.

P0 passes only if all evidence is captured in a small runbook section with command, environment, output summary, and any failure details.

---

## 8. P0 Acceptance Criteria

| Check | Pass condition |
| --- | --- |
| Dependency probe | Imports pass on Windows target venv: `can`, `pyxcp`, `pya2l`, `elftools`, `asammdf`. |
| MF4 compatibility | P0-generated MF4 opens through `DataLoader.load_mf4` and returns expected signal values/units. |
| A2L parse | Real A2L returns non-empty measurement list and at least one known variable's address/type/unit. |
| Vector access | Windows environment lists or opens the expected Vector channel. |
| XCP connect | ECU responds positively to `CONNECT`. |
| Known read | One known variable can be read via `SHORT_UPLOAD` and decoded to a plausible physical/raw value. |
| Evidence | Results are documented with exact command lines and output snippets. |

---

## 9. Go / No-Go Rules

Proceed to P1 UI prototype only if P0 passes.

Stay in P0 if:

- A2L parser cannot reliably extract measurement addresses.
- Vector driver/config cannot open the device.
- XCP `CONNECT` is unstable.
- `SHORT_UPLOAD` requires address extension, seed/key unlock, or ECU-specific setup that is not understood.
- Generated MF4 cannot be loaded by the current analyzer without loader changes.

Proceed to DAQ streaming only after:

- `GET_DAQ_PROCESSOR_INFO` / related DAQ capability discovery is implemented.
- ODT packing rules are validated against the target ECU.
- Timestamp semantics are defined.
- A fallback polling mode remains available.

---

## 10. References

- pyXCP PyPI: https://pypi.org/project/pyxcp/
- pya2ldb PyPI: https://pypi.org/project/pya2ldb/
- pya2l PyPI: https://pypi.org/project/pya2l/
- python-can Vector docs: https://python-can.readthedocs.io/en/stable/interfaces/vector.html
- asammdf API docs: https://asammdf.readthedocs.io/en/latest/api.html
