"""Application entry point."""
import importlib
import os
import sys
from pathlib import Path
from typing import Any


USE_EXTENSIONS_ENV = "TRACELAB_USE_EXTENSIONS"

_BOOTSTRAPPED = False
_RUNTIME_LEASE = None
_DLL_DIRECTORY_HANDLES: list[Any] = []
_LAST_RUNTIME_SNAPSHOT = None


if __package__ in (None, ""):
    package_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(package_dir.parent))
    package_name = package_dir.name
else:
    package_name = __package__


from mf4_analyzer.diagnostics import (  # noqa: E402 - direct-script path first
    install_excepthooks,
    install_qt_message_handler,
    setup_logging,
)


def _import_symbol(module_name: str, symbol_name: str):
    module = importlib.import_module(f"{package_name}.{module_name}")
    return getattr(module, symbol_name)


def _load_app_icon():
    """Build a multi-resolution QIcon from assets/icons/tracelab_*.png.

    Uses pre-rendered PNGs (not .ico/.icns) so the icon shows correctly on every
    platform regardless of which Qt image-format plugins are installed.
    """
    from PyQt5.QtCore import QSize
    from PyQt5.QtGui import QIcon

    # PyInstaller --onedir/--onefile expose the bundle root via sys._MEIPASS.
    # In dev, fall back to the repo root (parent of the mf4_analyzer package).
    base = getattr(sys, "_MEIPASS", None)
    if base is not None:
        icon_dir = Path(base) / "assets" / "icons"
    else:
        icon_dir = Path(__file__).resolve().parent.parent / "assets" / "icons"
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256, 512):
        png = icon_dir / f"tracelab_{size}.png"
        if png.exists():
            icon.addFile(str(png), QSize(size, size))
    return icon if not icon.isNull() else None


def _configure_high_dpi():
    """Enable Qt's per-monitor DPI scaling before QApplication is created."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

    from PyQt5.QtCore import QCoreApplication, Qt
    from PyQt5.QtGui import QGuiApplication

    for attribute_name in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
        attribute = getattr(Qt, attribute_name, None)
        if attribute is not None:
            QCoreApplication.setAttribute(attribute, True)

    policy_enum = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
    if policy_enum is not None and hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy_enum.PassThrough)


def resolve_install_root() -> Path:
    """Directory that owns the EXE / source checkout, not ``sys._MEIPASS``."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _env_use_extensions() -> bool | None:
    raw = os.environ.get(USE_EXTENSIONS_ENV)
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def apply_extension_search_path(planned) -> list[Any]:
    """Register allowed module roots and keep Windows DLL handles until exit."""

    handles: list[Any] = []
    for root in getattr(planned, "module_roots", ()) or ():
        path = Path(root)
        if not path.is_dir():
            continue
        text = os.fspath(path)
        if text not in sys.path:
            sys.path.insert(0, text)
    add_dll_directory = getattr(os, "add_dll_directory", None)
    for directory in getattr(planned, "dll_directories", ()) or ():
        path = Path(directory)
        if not path.is_dir() or not callable(add_dll_directory):
            continue
        handle = add_dll_directory(os.fspath(path))
        handles.append(handle)
        _DLL_DIRECTORY_HANDLES.append(handle)
    return handles


def extension_dll_directory_handles() -> tuple[Any, ...]:
    return tuple(_DLL_DIRECTORY_HANDLES)


def reset_extension_bootstrap_for_tests() -> None:
    """Undo process-wide bootstrap so focused tests stay isolated."""

    global _BOOTSTRAPPED, _RUNTIME_LEASE, _LAST_RUNTIME_SNAPSHOT
    _BOOTSTRAPPED = False
    lease = _RUNTIME_LEASE
    _RUNTIME_LEASE = None
    _LAST_RUNTIME_SNAPSHOT = None
    _DLL_DIRECTORY_HANDLES.clear()
    if lease is not None:
        closer = getattr(lease, "release", None) or getattr(lease, "close", None)
        if callable(closer):
            closer()
    from mf4_analyzer.io.source_adapters import bind_extension_runtime

    bind_extension_runtime(None)


def bootstrap_extension_runtime(
    *,
    app_root: Path | None = None,
    frozen: bool | None = None,
    use_extensions: bool | None = None,
):
    """Identify source/bundled/modular and take the shared lease before av/MAT.

    Bundled frozen never reads a neighbouring ``extensions/`` tree.  Source
    uses the project venv unless an explicit test switch is set.  Modular
    consumes ``load_runtime()`` and keeps DLL search handles alive.
    """

    global _BOOTSTRAPPED, _RUNTIME_LEASE, _LAST_RUNTIME_SNAPSHOT
    if _BOOTSTRAPPED and app_root is None and frozen is None and use_extensions is None:
        return _LAST_RUNTIME_SNAPSHOT

    from mf4_analyzer.extensions.contract import OFFICIAL_COMPONENTS, ReasonCode, ExtensionError
    from mf4_analyzer.extensions.runtime import (
        ComponentAvailability,
        MODE_BUNDLED,
        MODE_MODULAR,
        RuntimeSnapshot,
        STATUS_NOT_INSTALLED,
        detect_runtime_mode,
        load_runtime,
    )
    from mf4_analyzer.io.source_adapters import bind_extension_runtime

    root = Path(app_root) if app_root is not None else resolve_install_root()
    root = root.expanduser().resolve()
    if use_extensions is None:
        use_extensions = _env_use_extensions()
    mode = detect_runtime_mode(frozen=frozen, app_root=root, use_extensions=use_extensions)
    snapshot: RuntimeSnapshot
    if mode == MODE_MODULAR or use_extensions:
        try:
            snapshot = load_runtime(
                root,
                frozen=frozen if frozen is not None else mode != MODE_SOURCE,
                use_extensions=True if use_extensions else None,
            )
        except ExtensionError:
            components = {
                name: ComponentAvailability(
                    component=name,
                    status=STATUS_NOT_INSTALLED,
                    reason_code=ReasonCode.COMPONENT_MISSING,
                )
                for name in sorted(OFFICIAL_COMPONENTS)
            }
            snapshot = RuntimeSnapshot(
                mode=MODE_MODULAR,
                app_root=root,
                core=None,
                active=None,
                lease=None,
                components=components,
            )
        _RUNTIME_LEASE = snapshot.lease
        apply_extension_search_path(snapshot.planned)
    elif mode == MODE_BUNDLED:
        # Historical Full/Lite have no core.json.  Do not scan nearby extensions.
        components = {
            name: ComponentAvailability(
                component=name,
                status=STATUS_NOT_INSTALLED,
                reason_code=ReasonCode.COMPONENT_MISSING,
            )
            for name in sorted(OFFICIAL_COMPONENTS)
        }
        snapshot = RuntimeSnapshot(
            mode=MODE_BUNDLED,
            app_root=root,
            core=None,
            active=None,
            lease=None,
            components=components,
        )
    else:
        snapshot = load_runtime(root, acquire_lease=False, frozen=False)
    bind_extension_runtime(snapshot)
    _LAST_RUNTIME_SNAPSHOT = snapshot
    _BOOTSTRAPPED = True
    return snapshot


def main():
    setup_logging()
    bootstrap_extension_runtime()
    _configure_high_dpi()

    from PyQt5.QtWidgets import QApplication

    MainWindow = _import_symbol("ui", "MainWindow")
    setup_chinese_font = _import_symbol("ui_kit", "setup_chinese_font")
    load_stylesheet = _import_symbol("ui_kit", "load_stylesheet")
    install_glass_tooltips = _import_symbol("ui_kit", "install_glass_tooltips")

    setup_chinese_font()
    app = QApplication(sys.argv)
    install_qt_message_handler()
    from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font
    apply_global_chart_font(app)
    app.setStyle('Fusion')
    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    load_stylesheet(app)
    install_glass_tooltips(app)
    if os.environ.get("TRACELAB_LAYOUT_PROBE") == "1":
        from mf4_analyzer.ui.layout_probe import run_layout_probe
        sys.exit(run_layout_probe(app))
    window = MainWindow()
    install_excepthooks(on_error=lambda text: window.toast(text, "error"))
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
