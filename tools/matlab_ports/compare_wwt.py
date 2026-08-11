#!/usr/bin/env python3
"""Compare official-port ``wwt_import`` vs TraceLab ``wwt_format.load_wwt_groups``.

This is a diagnostic tool, not a product test.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wwt_import import wwt_import  # noqa: E402
from mf4_analyzer.io.wwt_format import load_wwt_groups  # noqa: E402


def _compare_one(path: Path) -> dict:
    header, infos, channels, count = wwt_import(path)
    types = Counter(info["Typ"] for info in infos)
    matlab_named = {
        info["KanalName"]: (info, np.asarray(data))
        for info, data in zip(infos, channels)
        if info["Typ"] != "Zeit" and info["Typ"] != "Pars"
    }

    result = {
        "file": path.name,
        "matlab_ok": True,
        "matlab_error": None,
        "local_ok": True,
        "local_error": None,
        "matlab_count": count,
        "matlab_types": dict(types),
        "matlab_non_zeit": len(matlab_named),
        "local_groups": 0,
        "local_channels": 0,
        "matched": 0,
        "mismatched": [],
        "matlab_only": [],
        "local_only": [],
        "exotic_types": sorted(
            t for t in types if t not in {"Zeit", "Real", "int1", "Long", "Floa", "Pars"}
        ),
    }

    try:
        groups = load_wwt_groups(path)
    except Exception as exc:  # noqa: BLE001 — diagnostic surface
        result["local_ok"] = False
        result["local_error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["local_groups"] = len(groups)
    local_cols = {}
    for g in groups:
        for col in g["channels"]:
            if col == "Time":
                continue
            # strip disambiguation suffix " [N]" for compare
            base = col.split(" [", 1)[0]
            local_cols.setdefault(base, []).append(np.asarray(g["data"][col].to_numpy()))

    result["local_channels"] = sum(len(v) for v in local_cols.values())

    for name, (info, mdata) in matlab_named.items():
        if name not in local_cols:
            # local may have skipped curve-def / n-mismatch / Pars
            if info["Anzahl"] < 100:
                result["matlab_only"].append(f"{name} (short n={info['Anzahl']}, likely curve)")
            else:
                result["matlab_only"].append(
                    f"{name} typ={info['Typ']} n={info['Anzahl']}"
                )
            continue
        # compare against first local series with same base name
        ldata = local_cols[name][0]
        if len(mdata) != len(ldata):
            result["mismatched"].append(
                f"{name}: len matlab={len(mdata)} local={len(ldata)}"
            )
            continue
        if not np.issubdtype(mdata.dtype, np.number):
            result["matlab_only"].append(f"{name} (non-numeric matlab payload)")
            continue
        if not np.allclose(mdata.astype(np.float64), ldata.astype(np.float64),
                           rtol=1e-9, atol=1e-9, equal_nan=True):
            max_abs = float(np.nanmax(np.abs(mdata.astype(np.float64) - ldata.astype(np.float64))))
            result["mismatched"].append(f"{name}: values differ max|Δ|={max_abs:g}")
            continue
        result["matched"] += 1

    local_names = set(local_cols)
    matlab_names = set(matlab_named)
    for name in sorted(local_names - matlab_names):
        result["local_only"].append(name)

    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific .wwt files (default: testdoc batches)",
    )
    args = parser.parse_args(argv)
    paths = list(args.paths)
    if not paths:
        for folder in (ROOT / "testdoc" / "2024_3_17", ROOT / "testdoc" / "wwt"):
            paths.extend(sorted(folder.glob("*.wwt")))

    print(f"comparing {len(paths)} WWT file(s)\n")
    exotic_hits = []
    for path in paths:
        r = _compare_one(path)
        status = "OK" if r["local_ok"] and not r["mismatched"] else "DIFF"
        print(f"== {r['file']} [{status}] ==")
        print(f"  matlab: count={r['matlab_count']} types={r['matlab_types']}")
        if r["exotic_types"]:
            print(f"  exotic matlab types (not in TraceLab set): {r['exotic_types']}")
            exotic_hits.append((r["file"], r["exotic_types"]))
        if not r["local_ok"]:
            print(f"  local ERROR: {r['local_error']}")
            continue
        print(
            f"  local: groups={r['local_groups']} channels={r['local_channels']} "
            f"matched={r['matched']}"
        )
        if r["mismatched"]:
            print("  mismatched:")
            for line in r["mismatched"][:12]:
                print(f"    - {line}")
        if r["matlab_only"]:
            print("  matlab-only / skipped by local:")
            for line in r["matlab_only"][:12]:
                print(f"    - {line}")
            if len(r["matlab_only"]) > 12:
                print(f"    ... +{len(r['matlab_only']) - 12} more")
        if r["local_only"]:
            print(f"  local-only names: {r['local_only']}")
        print()

    if exotic_hits:
        print("NOTE: some files expose channel types TraceLab does not decode yet:")
        for name, types in exotic_hits:
            print(f"  {name}: {types}")
    else:
        print("NOTE: no IntB/InBT/FloT/I10T exotic types seen in this batch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
