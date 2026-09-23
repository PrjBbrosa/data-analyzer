#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

from mf4_analyzer.extensions.probe import PROBE_ARGV_FLAGS


class _WindowedArgumentParser(argparse.ArgumentParser):
    """Hidden children must not depend on console streams (windowed EXE)."""

    def _print_message(self, message, file=None):
        if not message:
            return
        stream = sys.stderr if file is None else file
        writer = getattr(stream, "write", None)
        if not callable(writer):
            return
        try:
            writer(str(message))
        except (OSError, ValueError, AttributeError):
            return


def _reject_abbreviated_probe_flags(argv) -> None:
    """Exact ``--extension-probe-*`` flags only.  Abbreviations must not route."""

    allowed = frozenset(PROBE_ARGV_FLAGS)
    for token in argv:
        if not token.startswith("--"):
            continue
        name = token.split("=", 1)[0]
        if name.startswith("--extension-probe") and name not in allowed:
            raise SystemExit(2)


_SPLASH_ARGV_FLAGS = frozenset(
    {
        "--startup-splash-child",
        "--startup-splash-session",
        "--startup-splash-endpoint",
        "--startup-splash-token",
    }
)


def _reject_abbreviated_splash_flags(argv) -> None:
    """Exact ``--startup-splash-*`` flags only.  Abbreviations must not route."""

    for token in argv:
        if not token.startswith("--"):
            continue
        name = token.split("=", 1)[0]
        if name.startswith("--startup-splash") and name not in _SPLASH_ARGV_FLAGS:
            raise SystemExit(2)


def _valid_splash_endpoint(endpoint: str) -> bool:
    text = str(endpoint).strip()
    if text.count(":") != 1:
        return False
    host, _, port_text = text.partition(":")
    if host != "127.0.0.1":
        return False
    try:
        port = int(port_text)
    except ValueError:
        return False
    return 1 <= port <= 65535


def _splash_child_argv(args) -> list[str]:
    return [
        "--startup-splash-child",
        "--startup-splash-session",
        str(args.startup_splash_session),
        "--startup-splash-endpoint",
        str(args.startup_splash_endpoint),
        "--startup-splash-token",
        str(args.startup_splash_token),
    ]


def _probe_child_argv(args) -> list[str]:
    argv = [
        "--extension-probe-request",
        str(args.extension_probe_request),
    ]
    if args.extension_probe_result is not None:
        argv.extend(["--extension-probe-result", str(args.extension_probe_result)])
    if args.extension_probe_staging is not None:
        argv.extend(["--extension-probe-staging", str(args.extension_probe_staging)])
    if args.extension_probe_staging_nonce is not None:
        argv.extend(
            ["--extension-probe-staging-nonce", str(args.extension_probe_staging_nonce)]
        )
    if args.extension_probe_staging_handle is not None:
        argv.extend(
            [
                "--extension-probe-staging-handle",
                str(int(args.extension_probe_staging_handle)),
            ]
        )
    return argv


def _probe_app_root(staging: Path | None) -> Path | None:
    if staging is None:
        return None
    resolved = Path(staging).expanduser().resolve()
    try:
        return resolved.parents[2]
    except IndexError:
        return resolved.parent


if __name__ == "__main__":
    _reject_abbreviated_probe_flags(sys.argv[1:])
    _reject_abbreviated_splash_flags(sys.argv[1:])
    parser = _WindowedArgumentParser(add_help=False, allow_abbrev=False)
    hidden_mode = parser.add_mutually_exclusive_group()
    hidden_mode.add_argument("--acquisition-runtime-smoke", action="store_true")
    hidden_mode.add_argument("--pyxcp-import-probe-child", action="store_true")
    hidden_mode.add_argument("--pya2l-import-probe-child", action="store_true")
    hidden_mode.add_argument("--a2l-probe-child", action="store_true")
    parser.add_argument("--a2l-path", type=Path)
    parser.add_argument("--a2l-limit", type=int)
    hidden_mode.add_argument("--importer-runtime-smoke", action="store_true")
    parser.add_argument("--import-path", type=Path, action="append", default=[])
    hidden_mode.add_argument("--batch-render-runtime-smoke", action="store_true")
    hidden_mode.add_argument("--frozen-batch-acceptance", action="store_true")
    parser.add_argument("--batch-source", type=Path, action="append", default=[])
    parser.add_argument("--batch-channel", default="EpsDrvrSteerTq")
    parser.add_argument("--frozen-smoke-json", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--json", type=Path)
    # Probe *mode* token joins the exclusive hidden group.  Sibling payload
    # flags share allow_abbrev=False; they must not appear without the mode.
    hidden_mode.add_argument("--extension-probe-request", type=Path)
    parser.add_argument("--extension-probe-result", type=Path)
    parser.add_argument("--extension-probe-staging", type=Path)
    parser.add_argument("--extension-probe-staging-nonce")
    parser.add_argument("--extension-probe-staging-handle", type=int)
    # Splash child mode joins the exclusive group; session/endpoint/token are
    # sibling payload flags (same pattern as extension-probe).
    hidden_mode.add_argument("--startup-splash-child", action="store_true")
    parser.add_argument("--startup-splash-session")
    parser.add_argument("--startup-splash-endpoint")
    parser.add_argument("--startup-splash-token")
    args, _unknown = parser.parse_known_args()
    probe_payload_present = any(
        (
            args.extension_probe_result is not None,
            args.extension_probe_staging is not None,
            args.extension_probe_staging_nonce is not None,
            args.extension_probe_staging_handle is not None,
        )
    )
    if probe_payload_present and args.extension_probe_request is None:
        raise SystemExit(2)
    splash_payload_present = any(
        (
            args.startup_splash_session is not None,
            args.startup_splash_endpoint is not None,
            args.startup_splash_token is not None,
        )
    )
    if splash_payload_present and not args.startup_splash_child:
        raise SystemExit(2)
    if args.startup_splash_child:
        if (
            args.startup_splash_session is None
            or args.startup_splash_endpoint is None
            or args.startup_splash_token is None
            or not _valid_splash_endpoint(args.startup_splash_endpoint)
        ):
            raise SystemExit(2)
        from mf4_analyzer.startup_splash_child import child_main as splash_child_main

        raise SystemExit(splash_child_main(_splash_child_argv(args)))
    if args.extension_probe_request is not None:
        from mf4_analyzer.extensions.probe import (
            ProbeError,
            assert_result_path_safe,
            child_main,
        )

        if args.extension_probe_result is not None:
            try:
                assert_result_path_safe(
                    args.extension_probe_result,
                    app_root=_probe_app_root(args.extension_probe_staging),
                    extra_protected=(Path(sys.executable),),
                )
            except ProbeError:
                raise SystemExit(2)
        raise SystemExit(child_main(_probe_child_argv(args)))
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
    from mf4_analyzer.startup_timing import (  # noqa: E402 - after hidden children
        STAGE_PYTHON_ENTRY,
        mark as _startup_mark,
    )

    _startup_mark(STAGE_PYTHON_ENTRY)
    from mf4_analyzer.app import main

    # Hidden smoke/acceptance still bootstrap here; ordinary GUI lets app.main()
    # own bootstrap so StartupFeedback can start first.
    needs_early_bootstrap = (
        args.importer_runtime_smoke
        or args.batch_render_runtime_smoke
        or args.frozen_batch_acceptance
    )
    if needs_early_bootstrap:
        bootstrap = getattr(
            sys.modules["mf4_analyzer.app"], "bootstrap_extension_runtime", None
        )
        if callable(bootstrap):
            bootstrap()
    if args.importer_runtime_smoke:
        if args.json is None or not args.import_path:
            raise SystemExit(
                "--importer-runtime-smoke requires --import-path <path> and --json <path>"
            )
        from mf4_analyzer.io.importer_runtime_smoke import run

        raise SystemExit(run(args.import_path, args.json))
    if args.batch_render_runtime_smoke:
        if args.json is None or args.output_dir is None:
            raise SystemExit(
                "--batch-render-runtime-smoke requires --output-dir <path> and --json <path>"
            )
        from mf4_analyzer.batch_render_smoke import run

        raise SystemExit(run(args.output_dir, args.json))
    if args.frozen_batch_acceptance:
        if args.batch_channel != "EpsDrvrSteerTq":
            raise SystemExit(2)
        if (
            args.json is None
            or args.output_dir is None
            or not args.batch_source
            or args.frozen_smoke_json is None
        ):
            raise SystemExit(
                "--frozen-batch-acceptance requires three --batch-source <path>, "
                "--output-dir <path>, --json <path>, and "
                "--frozen-smoke-json <path>"
            )
        from mf4_analyzer.frozen_batch_acceptance import run

        raise SystemExit(
            run(
                args.batch_source,
                args.output_dir,
                args.json,
                frozen_smoke_json=args.frozen_smoke_json,
            )
        )
    main()
