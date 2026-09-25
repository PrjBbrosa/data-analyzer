"""Application entry point."""
import importlib
import logging
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

    from mf4_analyzer.qt_app_support import configure_high_dpi

    configure_high_dpi()


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
        MODE_SOURCE,
        RuntimeSnapshot,
        STATUS_NOT_INSTALLED,
        STATUS_REPAIR_REQUIRED,
        detect_runtime_mode,
        load_runtime,
    )

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
        except ExtensionError as exc:
            logging.getLogger(__name__).error("Extension bootstrap failed (%s): %s", exc.reason_code, exc)
            components = {
                name: ComponentAvailability(
                    component=name,
                    status=STATUS_REPAIR_REQUIRED,
                    reason_code=exc.reason_code,
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
        if snapshot.lease is not None:
            from mf4_analyzer.extensions.health import ensure_runtime_health
            snapshot = ensure_runtime_health(snapshot)
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
    from mf4_analyzer.io.source_adapters import bind_extension_runtime
    bind_extension_runtime(snapshot)
    _LAST_RUNTIME_SNAPSHOT = snapshot
    _BOOTSTRAPPED = True
    return snapshot


def _report_startup_failure(exc: BaseException, *, qapp_ready: bool) -> None:
    """Surface a one-shot startup failure without restarting the app."""

    message = f"TraceLab 启动失败：{exc}"
    if qapp_ready:
        try:
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.critical(None, "TraceLab", message)
            return
        except Exception:
            logging.getLogger(__name__).exception(
                "startup failure dialog could not be shown"
            )
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0, message, "TraceLab", 0x10
            )
            return
        except Exception:
            logging.getLogger(__name__).exception(
                "startup failure MessageBoxW could not be shown"
            )
    logging.getLogger(__name__).error("%s", message)


def _arm_startup_observation(app, window, feedback=None, handover=None) -> None:
    """Watch first paint for timing probes only — never drives splash.finish.

    Splash handover is owned by ``StartupHandover`` (hide ACK → show once).
    ``show()`` returning and a lone 0 ms timer are never treated as ready.
    Interactive probe wiring stays gated on the timing switch.
    """

    from PyQt5.QtCore import QEvent, QObject, QSocketNotifier, QTimer

    from mf4_analyzer import startup_timing as st

    timing_on = st.enabled()

    class _StartupObserver(QObject):
        def __init__(self):
            super().__init__(window)
            self._framed = False
            self._sock = None
            self._notifier = None
            self._responded = False

        def eventFilter(self, obj, event):  # noqa: N802 - Qt API
            if self._framed or obj is not window:
                return False
            if event.type() != QEvent.Paint:
                return False
            self._framed = True
            if handover is not None:
                try:
                    handover.mark_first_frame()
                except Exception:
                    logging.getLogger(__name__).exception(
                        "startup handover first-frame mark failed"
                    )
            if timing_on:
                try:
                    st.mark(st.STAGE_FIRST_FRAME)
                except st.StartupTimingError as exc:
                    print(f"startup timing: {exc}", file=sys.stderr)
                # Queued connect only arms the probe channel; it is not interactive.
                QTimer.singleShot(0, self._connect_probe)
            return False

        def _connect_probe(self) -> None:
            if not timing_on:
                return
            sock = st.connect_probe_socket(timeout_s=5.0)
            if sock is None:
                return
            self._sock = sock
            self._notifier = QSocketNotifier(
                sock.fileno(), QSocketNotifier.Read, self
            )
            self._notifier.activated.connect(self._on_readable)

        def _on_readable(self, *_args) -> None:
            if self._sock is None or self._responded:
                return
            request = st.read_probe_request(self._sock)
            if request is None:
                return
            if request.get("cmd") != "interactive_probe":
                return
            token = str(request.get("token") or "")
            # Respond on a later event-loop turn (queued interaction).
            QTimer.singleShot(0, lambda: self._respond(token))

        def _respond(self, token: str) -> None:
            if self._sock is None or self._responded:
                return
            self._responded = True
            try:
                st.write_probe_response(self._sock, token=token, ok=True)
                st.mark(st.STAGE_INTERACTIVE_PROBE_HANDLED, token=token)
            except Exception as exc:
                print(f"startup timing probe response failed: {exc}", file=sys.stderr)
            finally:
                if self._notifier is not None:
                    self._notifier.setEnabled(False)
                if st.exit_after_probe():
                    # Measurement runs only; never the default product path.
                    QTimer.singleShot(0, app.quit)

    observer = _StartupObserver()
    window.installEventFilter(observer)
    window._tracelab_startup_observer = observer  # prevent GC


def main():
    from mf4_analyzer.startup_feedback import (
        STAGE_LOADING_COMPONENTS,
        STAGE_PREPARING_WORKSPACE,
        create_startup_feedback,
    )
    from mf4_analyzer.startup_timing import (
        STAGE_GUI_MODULES_IMPORTED,
        STAGE_MAINWINDOW_CONSTRUCTED,
        STAGE_PYTHON_ENTRY,
        STAGE_QAPPLICATION_READY,
        mark as startup_mark,
    )

    startup_mark(STAGE_PYTHON_ENTRY)
    setup_logging()

    feedback = create_startup_feedback()
    qapp_ready = False
    try:
        # QT_QPA_PLATFORM is consulted inside splash_enabled via environ;
        # do not pass allow_offscreen on the production path.
        feedback.start(
            layout_probe=(os.environ.get("TRACELAB_LAYOUT_PROBE") == "1"),
        )
        feedback.publish(STAGE_LOADING_COMPONENTS)
        bootstrap_extension_runtime()
        _configure_high_dpi()

        from PyQt5.QtWidgets import QApplication

        MainWindow = _import_symbol("ui", "MainWindow")
        setup_chinese_font = _import_symbol("ui_kit", "setup_chinese_font")
        load_stylesheet = _import_symbol("ui_kit", "load_stylesheet")
        install_glass_tooltips = _import_symbol("ui_kit", "install_glass_tooltips")
        startup_mark(STAGE_GUI_MODULES_IMPORTED)

        setup_chinese_font()
        app = QApplication(sys.argv)
        qapp_ready = True
        # Keep the controller reachable for the QApplication lifetime.
        app._tracelab_startup_feedback = feedback
        install_qt_message_handler()
        from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font
        apply_global_chart_font(app)
        app.setStyle('Fusion')
        icon = _load_app_icon()
        if icon is not None:
            app.setWindowIcon(icon)
        load_stylesheet(app)
        install_glass_tooltips(app)
        startup_mark(STAGE_QAPPLICATION_READY)
        if os.environ.get("TRACELAB_LAYOUT_PROBE") == "1":
            from mf4_analyzer.ui.layout_probe import run_layout_probe
            code = run_layout_probe(app)
            feedback.close()
            sys.exit(code)
        feedback.publish(STAGE_PREPARING_WORKSPACE)
        window = MainWindow()
        startup_mark(STAGE_MAINWINDOW_CONSTRUCTED)
        install_excepthooks(on_error=lambda text: window.toast(text, "error"))
        from mf4_analyzer.startup_handover import StartupHandover

        # Construct without show; handover owns the single reveal after splash hide.
        handover = StartupHandover(app, window, feedback)
        app._tracelab_startup_handover = handover
        # Timing / interactive probe only — must not call feedback.finish().
        _arm_startup_observation(app, window, feedback, handover)
        # Listener before finish so a fast hidden ACK cannot be missed.
        handover.begin()
        code = app.exec_()
        try:
            handover.close()
        except Exception:
            logging.getLogger(__name__).exception("startup handover close failed")
        feedback.close()
        sys.exit(code)
    except SystemExit:
        raise
    except BaseException as exc:
        try:
            feedback.close()
        except Exception:
            logging.getLogger(__name__).exception(
                "startup feedback close failed during error handling"
            )
        logging.getLogger(__name__).exception("TraceLab startup failed")
        _report_startup_failure(exc, qapp_ready=qapp_ready)
        sys.exit(1)


if __name__ == "__main__":
    main()
