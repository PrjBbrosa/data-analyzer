"""Which launches may show the native startup panel.

The public Windows launcher is the only caller. Source and the runtime
executable keep the Qt splash unless a verified native session is already
attached. Unknown options never flash a panel; Python still validates them.
"""
from __future__ import annotations

from typing import Mapping

ENV_SPLASH = "TRACELAB_STARTUP_SPLASH"
ENV_BACKEND = "TRACELAB_STARTUP_BACKEND"
ENV_LAYOUT_PROBE = "TRACELAB_LAYOUT_PROBE"
ENV_QT_PLATFORM = "QT_QPA_PLATFORM"

_FALSEY = frozenset({"0", "false", "off", "no"})

# Known hidden / help flags. Any other leading-dash token is also passthrough.
PASSTHROUGH_FLAGS = (
    "--help",
    "-h",
    "--acquisition-runtime-smoke",
    "--pyxcp-import-probe-child",
    "--pya2l-import-probe-child",
    "--a2l-probe-child",
    "--importer-runtime-smoke",
    "--batch-render-runtime-smoke",
    "--frozen-batch-acceptance",
    "--extension-probe-request",
    "--startup-splash-child",
)


def _env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None:
        return ""
    return str(value).strip()


def should_present_native_panel(
    argv: list[str],
    env: Mapping[str, str],
) -> bool:
    """Return True only for an ordinary GUI launch on the public launcher.

    ``argv`` is the argument vector without the executable path.
    """

    if _env(env, ENV_SPLASH).lower() in _FALSEY:
        return False
    backend = _env(env, ENV_BACKEND).lower() or "auto"
    if backend not in {"auto", "native"}:
        return False
    if _env(env, ENV_LAYOUT_PROBE) == "1":
        return False
    if _env(env, ENV_QT_PLATFORM).lower() == "offscreen":
        return False
    for token in argv:
        text = str(token)
        if text.startswith("-"):
            return False
    return True
