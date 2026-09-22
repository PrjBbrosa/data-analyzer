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
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_repo_on_path()
    args = build_parser().parse_args(argv)
    from tools.extension_manager.app import run_app

    return run_app(
        app_root=args.app_root or None,
        manager_version=args.manager_version or None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
