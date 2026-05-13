#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from mf4_analyzer.acquisition.manifest import (
    load_manifest,
    resolve_entry_path,
    select_entries,
)
from mf4_analyzer.acquisition.regression import (
    build_snapshot,
    compare_snapshot,
    load_json,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MF4 dataset regression snapshots.")
    parser.add_argument("dataset", help="manifest set name such as smoke, golden, issue")
    parser.add_argument("--manifest", default="data/manifest.local.json")
    parser.add_argument("--snapshot-dir", default="data/snapshots")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--rel-tol", type=float, default=1e-4)
    parser.add_argument("--abs-tol", type=float, default=1e-6)
    args = parser.parse_args()

    entries = select_entries(load_manifest(args.manifest), args.dataset)
    if not entries:
        print(f"no entries for dataset {args.dataset}")
        return 2

    failed = False
    for entry in entries:
        mf4_path = resolve_entry_path(entry, manifest_path=args.manifest)
        if not Path(mf4_path).exists():
            if entry.required:
                failed = True
                print(f"{entry.id}: FAIL — missing file {mf4_path}")
            else:
                print(f"{entry.id}: SKIP — optional file {mf4_path} absent")
            continue
        current = build_snapshot(mf4_path, channels=entry.expected_channels)
        snapshot_path = Path(args.snapshot_dir) / f"{entry.id}.golden.json"
        if args.update or not snapshot_path.exists():
            write_json(snapshot_path, current)
            print(f"updated {snapshot_path}")
            continue
        diffs = compare_snapshot(
            load_json(snapshot_path),
            current,
            rel_tol=args.rel_tol,
            abs_tol=args.abs_tol,
        )
        if diffs:
            failed = True
            print(f"{entry.id}: FAIL")
            for diff in diffs:
                print(f"  - {diff}")
        else:
            print(f"{entry.id}: PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
