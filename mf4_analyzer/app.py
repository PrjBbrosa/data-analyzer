"""Application entry point."""
import importlib
import os
import sys
from pathlib import Path


if __package__ in (None, ""):
    package_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(package_dir.parent))
    package_name = package_dir.name
else:
    package_name = __package__


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

    # Force desktop OpenGL in the FROZEN (PyInstaller) build only.
    #
    # The 「GPU 加速」 toggle swaps the chart viewport to a QOpenGLWidget
    # (GraphicsView.useOpenGL). That viewport only composites the curve
    # QGraphicsItems under a *desktop* GL backend; under ANGLE (D3D) or the
    # software (opengl32sw) fallback the curves vanish while axes/legend stay —
    # the exact failure the gl-viewport lesson documents.
    #
    # Running from source, Qt auto-selects the system GPU driver's desktop GL
    # (works). The frozen build bundles libEGL/libGLESv2/d3dcompiler (ANGLE) +
    # opengl32sw.dll, and Qt's auto-selection there can fall to ANGLE/software,
    # which blanks the curves the moment GPU is enabled (user-confirmed: 打包后
    # 开 GPU 曲线全没，直接跑 Python 正常). Pinning desktop GL makes the frozen
    # build use the SAME backend as source, so GPU render behaves identically.
    #
    # Frozen-only on purpose: source keeps Qt's auto fallback chain untouched.
    # Must be set before QApplication is constructed (this runs first in main).
    # If a machine genuinely lacks desktop GL the GL context creation simply
    # fails — set_gpu_render/_apply_gpu_viewport already wraps useOpenGL() in
    # try/except and stays on the CPU raster path, and GPU is opt-in (session
    # default OFF), so the rest of the (raster) UI is unaffected.
    if getattr(sys, "frozen", False):
        attr = getattr(Qt, "AA_UseDesktopOpenGL", None)
        if attr is not None:
            QCoreApplication.setAttribute(attr, True)

    # MSAA for the OpenGL viewport (GPU render toggle). Must be set before
    # QApplication is constructed. 4× samples gives line quality equal to or
    # better than CPU AA at no meaningful extra cost on modern GPUs. CPU-only
    # sessions are unaffected — QSurfaceFormat is only consumed by GL contexts.
    try:
        from PyQt5.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        QSurfaceFormat.setDefaultFormat(fmt)
    except Exception:
        pass


def _write_gl_diagnostics():
    """Probe the actual OpenGL backend and write a one-shot diagnostic log.

    The GPU-render toggle blanks the curves in the FROZEN build but not from
    source. The decisive unknown is which GL backend the frozen app actually
    gets: desktop GL (composites the curve QGraphicsItems — works) vs ANGLE
    (OpenGL ES / D3D) or software (opengl32sw) — which do NOT composite them on
    a QOpenGLWidget viewport. ``QOpenGLContext.openGLModuleType()`` and a probe
    context's ``isOpenGLES()`` answer that without needing the chart. Also
    records whether the AA_UseDesktopOpenGL force (frozen-only, set in
    _configure_high_dpi) actually took. Writes to %TEMP%/tracelab_gl_diag.txt
    (and next to the exe, best-effort). Never raises — diagnostics must not
    break startup. Runs in the frozen build, or from source with
    TRACELAB_GL_DIAG=1 set (so source vs frozen can be compared).
    """
    if not (getattr(sys, "frozen", False) or os.environ.get("TRACELAB_GL_DIAG")):
        return
    import tempfile

    from PyQt5.QtCore import Qt, QCoreApplication

    lines = []

    def add(key, val):
        lines.append(f"{key}: {val}")

    try:
        from PyQt5.QtGui import QOpenGLContext, QSurfaceFormat

        add("marker", "GL-DIAG-v1")
        add("frozen", getattr(sys, "frozen", False))
        add("executable", sys.executable)
        for name in ("AA_UseDesktopOpenGL", "AA_UseOpenGLES", "AA_UseSoftwareOpenGL"):
            attr = getattr(Qt, name, None)
            add(name, QCoreApplication.testAttribute(attr) if attr is not None else "n/a")
        try:
            mt = int(QOpenGLContext.openGLModuleType())
            add("openGLModuleType", {0: "LibGL(desktop)", 1: "LibGLES(ANGLE)"}.get(mt, mt))
        except Exception as exc:
            add("openGLModuleType.error", repr(exc))
        try:
            df = QSurfaceFormat.defaultFormat()
            add("defaultFormat.samples", df.samples())
            add("defaultFormat.renderableType", int(df.renderableType()))
        except Exception as exc:
            add("defaultFormat.error", repr(exc))
        # Probe a real context: did it create, and is it ES (ANGLE) or desktop?
        try:
            ctx = QOpenGLContext()
            created = ctx.create()
            add("probeContext.create()", created)
            if created:
                add("probeContext.isOpenGLES", ctx.isOpenGLES())
                f = ctx.format()
                add("probeContext.version", f"{f.majorVersion()}.{f.minorVersion()}")
                add("probeContext.renderableType", int(f.renderableType()))
        except Exception as exc:
            add("probeContext.error", repr(exc))
    except Exception as exc:  # pragma: no cover - defensive
        add("fatal", repr(exc))

    text = "\n".join(str(x) for x in lines) + "\n"
    targets = []
    try:
        targets.append(os.path.join(tempfile.gettempdir(), "tracelab_gl_diag.txt"))
    except Exception:
        pass
    try:
        targets.append(os.path.join(os.path.dirname(sys.executable), "tracelab_gl_diag.txt"))
    except Exception:
        pass
    for path in targets:
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:
            pass


def main():
    _configure_high_dpi()

    from PyQt5.QtWidgets import QApplication

    MainWindow = _import_symbol("ui", "MainWindow")
    setup_chinese_font = _import_symbol("ui_kit", "setup_chinese_font")
    load_stylesheet = _import_symbol("ui_kit", "load_stylesheet")
    install_glass_tooltips = _import_symbol("ui_kit", "install_glass_tooltips")

    setup_chinese_font()
    app = QApplication(sys.argv)
    _write_gl_diagnostics()
    from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font
    apply_global_chart_font(app)
    app.setStyle('Fusion')
    icon = _load_app_icon()
    if icon is not None:
        app.setWindowIcon(icon)
    load_stylesheet(app)
    install_glass_tooltips(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
