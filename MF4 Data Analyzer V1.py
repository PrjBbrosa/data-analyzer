#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--acquisition-runtime-smoke", action="store_true")
    parser.add_argument("--pyxcp-import-probe-child", action="store_true")
    parser.add_argument("--pya2l-import-probe-child", action="store_true")
    parser.add_argument("--a2l-probe-child", action="store_true")
    parser.add_argument("--a2l-path", type=Path)
    parser.add_argument("--a2l-limit", type=int)
    parser.add_argument("--importer-runtime-smoke", action="store_true")
    parser.add_argument("--import-path", type=Path, action="append", default=[])
    parser.add_argument("--json", type=Path)
    args, _unknown = parser.parse_known_args()
    if args.pyxcp_import_probe_child:
        from mf4_analyzer.acquisition_capture.runtime_smoke import (
            run_import_probe_child,
        )

        raise SystemExit(run_import_probe_child())
    if args.pya2l_import_probe_child:
        from mf4_analyzer.acquisition_capture.runtime_smoke import (
            run_pya2l_import_probe_child,
        )

        raise SystemExit(run_pya2l_import_probe_child())
    if args.a2l_probe_child:
        if args.a2l_path is None:
            raise SystemExit("--a2l-probe-child requires --a2l-path <path>")
        from can_logger.p0._a2l_subprocess import main as a2l_child_main

        child_args = [str(args.a2l_path)]
        if args.a2l_limit is not None:
            child_args.extend(["--limit", str(args.a2l_limit)])
        raise SystemExit(a2l_child_main(child_args))
    if args.acquisition_runtime_smoke:
        if args.json is None:
            raise SystemExit("--acquisition-runtime-smoke requires --json <path>")
        from mf4_analyzer.acquisition_capture.runtime_smoke import run

        raise SystemExit(run(args.json))
    if args.importer_runtime_smoke:
        if args.json is None or not args.import_path:
            raise SystemExit(
                "--importer-runtime-smoke requires --import-path <path> and --json <path>"
            )
        from mf4_analyzer.io.importer_runtime_smoke import run

        raise SystemExit(run(args.import_path, args.json))
    from mf4_analyzer.app import main

    main()
