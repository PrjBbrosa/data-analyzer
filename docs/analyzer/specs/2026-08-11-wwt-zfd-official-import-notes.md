# WWT / ZFD Official Import Notes (2026-08-11)

Research note from comparing ZFLS MATLAB importers (`testdoc/wwt_import.m`,
`testdoc/zfd_import.m`) against TraceLab `mf4_analyzer/io/wwt_format.py` and
`zfd_format.py`, plus a batch run on `testdoc` samples. Standalone faithful
ports live in `tools/matlab_ports/` (not wired into the product).

## Sources

| Artifact | Role |
| --- | --- |
| `testdoc/wwt_import.m` | ZFLS official WinWert reader (Lars Bartschat, 2008–2009) |
| `testdoc/zfd_import.m` | ZFLS official ZFD reader (2008) |
| `tools/matlab_ports/wwt_import.py` | Faithful Python port of the `.m` |
| `tools/matlab_ports/zfd_import.py` | Faithful Python port of the `.m` |
| `tools/matlab_ports/compare_wwt.py` | Diff official WWT port vs TraceLab |
| `mf4_analyzer/io/wwt_format.py` | Product WWT loader |
| `mf4_analyzer/io/zfd_format.py` | Product ZFGE2/TestRunPRO loader |

WinWert as a format dates to ~1995; the MATLAB scripts document later
extensions (notably 2009-08 channel types).

## Short blocks (tolerance / limit curves)

Channels such as `Tol_*`, `Grenze *`, `y_pos` / `y_neg`, `Force oben`,
`travel limit` often appear with **n ≈ 5–20** (sometimes up to ~65–158).

These are **on-plot tolerance / evaluation curves**, not time-series
measurement. Product decision: **do not import**. TraceLab already skips when:

- the owning `Zeit` block has `n < _MIN_TIMESERIES_SAMPLES` (100), or
- a data channel’s `n` does not match its owning `Zeit`.

Official MATLAB imports them as ordinary channels; that is intentional for
WinWert-style post-processing, not for TraceLab’s time-domain workspace.

## Exotic WWT types (`IntB` / `InBT` / `FloT` / `I10T`)

Not seen in the 2026-08-11 `testdoc` WWT batch (13 files). Meanings from the
official script comments / code:

| Tag | Storage | Notes |
| --- | --- | --- |
| `IntB` | `uint16` | Fixed-point; apply `×scale + offset`. Same header layout as `int1`. |
| `InBT` | `int16` + `teiler` | Decimated channel: after `anzahl`, an extra `long teiler`; file stores `ceil(n/teiler)` samples; reader repeats each value `teiler` times to fill `n` (hold). Example use: climate-chamber temperature. |
| `FloT` | `float32` + `teiler` | Same expand pattern as `InBT`. |
| `I10T` | `int16` + `teiler` | Same expand pattern; `.m` comment says float, **code reads int16**. |

These are **2009-era specialty extensions** (slow / unsigned channels), not the
1995 core set. Mainstream EPS / bench files use `Zeit`, `Real`, `int1`,
`Long`, `Floa`, and sometimes `Pars`.

**Layout warning:** `*T` types insert 4 bytes (`teiler`) after the sample
count. TraceLab’s fixed 156-byte record header assumption does **not** apply
to them. Today they fall into the unknown-tag + resync path and are skipped
safely. Do not add them to `_TAG_DTYPES` without a dedicated `teiler` branch
and expand logic.

`Pars` is a WinWert arithmetic channel (formula string, no samples). Official
script does not evaluate it; TraceLab skips and records the formula in
`skipped_channels`. Keep that behavior.

## `xkanalnr`（record header +0x9, u16）

官方 `.m` 读出并存为 `XKanalNr` 但不消费。2026-08-11 实测：**WinWert 显示侧
也不读它**（探针把它从 8 改成 6，曲线设置对话框仍显示 8）。它是采集侧遗留
字段，数值上确实等于当时的 X 通道记录序号，但改它不影响任何显示。

真正决定横坐标的是**尾块曲线记录 +18 的 u16**（0 = 时间）——TraceLab 导入
侧两者都忽略（我们总按时域组织），导出侧必须改后者。完整字段表见
`2026-08-11-wwt-export-dual-compat-spec.md` §显示轴机制。

## Batch compare snapshot (2026-08-11)

### WWT (`testdoc/2024_3_17/*.wwt` + `testdoc/wwt/*.wwt`, 13 files)

- 11/13: TraceLab time-series channels match the official port numerically.
- 2/13 (`U-Can_*.wwt`): name collisions where official keeps a short curve as
  `Rack Force` while TraceLab keeps the long measurement series — expected
  given short-block policy.
- Short-block-only channels appear as matlab-only / TraceLab-skipped.
- No `IntB` / `InBT` / `FloT` / `I10T` in this corpus.
- Multi-`Zeit` files (e.g. `SFNS_40_*`) become multiple TraceLab groups when
  `(n, dt, t0)` differ; official script stays flat.

### ZFD (`testdoc/RWS/*.zfd` + `testdoc/wwt/end of travel_1.zfd`)

- Official typ path and TraceLab marker scan both succeed on ZFGE2 files.
- Matching by **marker id** (`A2`, `E3`, …): time axis and all float channels
  bit-identical. Matching by bare channel name alone is wrong when names
  repeat (`Fzyl 1` on `A2` and `E3`).
- Samples were typ 0 (equidistant time) + typ 4 (float32). No typ 1–3 in
  corpus. Official `.m` stores scale/offset for typ 2/3 but does not apply
  them to samples.

## Product parsers: room to improve?

**Current corpus: no urgent gap.** TraceLab WWT is already stronger for product
use than the official script (multi-`Zeit` merge, short-block skip, Pars /
unknown resync, unreliable `count` + trailer end).

Worth doing **only when a real file arrives**:

1. **WWT `IntB`** — same layout as `int1`, unsigned read. Cheap.
2. **WWT `InBT` / `FloT` / `I10T`** — `teiler` header + hold-expand; do not
   treat as fixed 156-byte headers.
3. **WWT skip taxonomy** — distinguish curve / Pars / exotic in
   `skipped_channels` for support (optional).
4. **ZFD non-ZFGE2 or typ 1–3** — consider a typed-record path like the
   official `.m`; leave alone while all customer files are ZFGE2 float.
5. **Do not** implement `Pars` formula evaluation.

## How to re-check

```bash
PYTHONPATH=. .venv/bin/python tools/matlab_ports/compare_wwt.py
PYTHONPATH=. .venv/bin/python tools/matlab_ports/wwt_import.py path/to/file.wwt
PYTHONPATH=. .venv/bin/python tools/matlab_ports/zfd_import.py path/to/file.zfd
```

## Export (dual compatibility)

Product goal to **write** `.wwt` that TraceLab re-reads and WinWert opens:
see `docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md`.
The blocking unknown is the `DatenFenste2` display trailer (large, not shared
verbatim across files); measurement body layout is already well understood.
