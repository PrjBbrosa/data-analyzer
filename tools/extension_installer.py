#!/usr/bin/env python3
"""Standalone TraceLab extension manager entry.

This process is independent of the Qt main app. It never kills TraceLab.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_repo_on_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    text = str(root)
    if text not in sys.path:
        sys.path.insert(0, text)
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extension-installer",
        description="TraceLab 扩展管理器",
    )
    parser.add_argument(
        "--app-root",
        default="",
        help="目标 TraceLab 安装目录。缺省为当前工作目录或本程序所在目录。",
    )
    parser.add_argument(
        "--manager-version",
        default="",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--repository-config", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--self-test-json", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_repo_on_path()
    args = build_parser().parse_args(argv)
    if args.self_test_json is not None:
        return self_test(args.self_test_json, config_path=args.repository_config)
    from tools.extension_manager.app import run_app

    return run_app(
        app_root=args.app_root or None,
        manager_version=args.manager_version or None,
        repository_config=args.repository_config,
    )


def self_test(output: Path, *, config_path: Path | None = None) -> int:
    import json
    import tempfile
    import threading
    from mf4_analyzer.extensions.probe import assert_result_path_safe, ProbeError
    from tools.extension_manager.app import MANAGER_VERSION
    from tools.extension_manager.config import create_repository, default_config_path

    try:
        assert_result_path_safe(output, app_root=Path(sys.executable).resolve().parent,
                                extra_protected=(config_path or default_config_path(),))
        if output.exists():
            return 2
    except ProbeError:
        return 2
    payload = {"manager_version": MANAGER_VERSION, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        import tkinter
        with tempfile.TemporaryDirectory(prefix="tracelab-manager-check-") as directory:
            create_repository(Path(directory), manager_version=MANAGER_VERSION,
                              cancel_event=threading.Event(), config_path=config_path)
        unexpected = [name for name in ("PyQt5", "numpy", "pandas", "av", "scipy", "h5py")
                      if name in sys.modules]
        if unexpected:
            raise RuntimeError(f"manager imported target dependencies: {unexpected}")
        payload.update(ok=True, tk_version=tkinter.TkVersion,
                       tcl_patchlevel=tkinter.Tcl().eval("info patchlevel"))
    except Exception as exc:
        payload.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
