#!/usr/bin/env python3
"""Capture an offscreen QSS visual baseline for style.qss consolidation.

Task 0 of ``docs/analyzer/plans/2026-08-15-qss-consolidation-plan.md``.
Task 2 uses these PNG hashes as the "zero-pixel-change" control when
deleting dead QSS rules.

Output is PNG files plus a sha256 manifest JSON. Default destination is a
temp directory; this script refuses to write under tracked ``docs/`` paths
(including ``docs/superpowers/verify/``).

Usage::

    TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \\
        .venv/bin/python scripts/capture_qss_offscreen_baseline.py \\
        --output-dir /tmp/qss-consolidation-baseline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = Path("/tmp/qss-consolidation-baseline")
WINDOW_SIZE = (1440, 900)
CHANNEL_CONFIG_SIZE = (1180, 680)
BATCH_SHEET_SIZE = (1280, 800)
MODES = ("time", "fft", "fft_time", "order", "frf")


def _refuse_tracked_docs(output_dir: Path) -> None:
    """Keep evidence out of Git-tracked docs trees (CLAUDE.md verify lesson)."""
    resolved = output_dir.resolve()
    docs = (REPO / "docs").resolve()
    try:
        resolved.relative_to(docs)
    except ValueError:
        return
    raise SystemExit(
        f"refusing to write baseline evidence under {docs}; "
        "pass a temp --output-dir (default /tmp/qss-consolidation-baseline/)"
    )


def _git_meta() -> dict[str, str]:
    def _run(*args: str) -> str:
        try:
            out = subprocess.check_output(
                ["git", "-C", str(REPO), *args],
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError):
            return ""
        return out.decode("utf-8", "replace").strip()

    return {
        "branch": _run("rev-parse", "--abbrev-ref", "HEAD"),
        "head": _run("rev-parse", "HEAD"),
        "head_short": _run("rev-parse", "--short", "HEAD"),
    }


def _isolate_qsettings(tmp_dir: Path) -> None:
    """Mirror ``tests/ui/conftest.py::_isolate_qsettings``.

    Without this, constructing MainWindow / BatchSheet / Inspector writes
    into the developer's real MF4Analyzer/DataAnalyzer store.
    """
    from PyQt5.QtCore import QSettings

    import mf4_analyzer.ui.batch_settings as _batch_settings_mod
    import mf4_analyzer.ui.inspector_sections as _pkg
    import mf4_analyzer.ui.inspector_sections._helpers as _helpers_mod
    import mf4_analyzer.ui.inspector_sections.collapsible as _collapsible_mod
    import mf4_analyzer.ui.inspector_sections.presets as _presets_mod
    import mf4_analyzer.ui.inspector_sections.persistent_top as _persistent_top_mod

    ini = str(tmp_dir / "qsettings.ini")

    def _temp_settings(*_args, **_kwargs):
        return QSettings(ini, QSettings.IniFormat)

    for mod in (
        _pkg,
        _helpers_mod,
        _collapsible_mod,
        _presets_mod,
        _persistent_top_mod,
    ):
        if hasattr(mod, "_preset_settings"):
            mod._preset_settings = _temp_settings
    _batch_settings_mod._default_settings = _temp_settings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_dir))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope, str(tmp_dir))


def _disable_qt_chrome_noise(app) -> None:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    for effect in (
        Qt.UI_AnimateMenu,
        Qt.UI_AnimateCombo,
        Qt.UI_AnimateTooltip,
        Qt.UI_AnimateToolBox,
        Qt.UI_FadeMenu,
        Qt.UI_FadeTooltip,
        Qt.UI_AnimateTooltip,
    ):
        try:
            app.setEffectEnabled(effect, False)
        except Exception:
            pass
    QApplication.setEffectEnabled(Qt.UI_General, False)


def _stop_timers_and_animations(root) -> None:
    """Freeze hint rotation, idle quality, hover collapse, toasts, etc."""
    from PyQt5.QtCore import QAbstractAnimation, QTimer
    from PyQt5.QtWidgets import QWidget

    if root is None:
        return
    timers = list(root.findChildren(QTimer))
    if isinstance(root, QTimer):
        timers.append(root)
    for timer in timers:
        try:
            timer.stop()
        except RuntimeError:
            continue
    animations = list(root.findChildren(QAbstractAnimation))
    if isinstance(root, QAbstractAnimation):
        animations.append(root)
    for animation in animations:
        try:
            animation.stop()
        except RuntimeError:
            continue
    if isinstance(root, QWidget):
        for child in root.findChildren(QWidget):
            try:
                child.setUpdatesEnabled(True)
            except RuntimeError:
                continue


def _pump(app, rounds: int = 8) -> None:
    for _ in range(rounds):
        app.processEvents()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture(widget, output_dir: Path, name: str, app) -> dict:
    _stop_timers_and_animations(widget)
    _pump(app, 6)
    pixmap = widget.grab()
    path = output_dir / f"{name}.png"
    if not pixmap.save(str(path), "PNG"):
        raise SystemExit(f"failed to write {path}")
    record = {
        "name": path.name,
        "sha256": _sha256_file(path),
        "width": int(pixmap.width()),
        "height": int(pixmap.height()),
        "bytes": path.stat().st_size,
    }
    print(
        f"[shot] {record['name']} {record['width']}x{record['height']} "
        f"{record['sha256'][:12]}…"
    )
    return record


def _channel_config_dialog():
    from mf4_analyzer.ui.channel_config import (
        ChannelConfigPreview,
        ChannelSelectionConfig,
    )
    from mf4_analyzer.ui.widgets.channel_config_manager import (
        ChannelConfigManagerDialog,
    )

    configs = [
        ChannelSelectionConfig.create(
            "drive",
            "动力分析",
            ("EPS_CRC", "Missing", "Torque"),
            now="2026-08-15T00:00:00+00:00",
            channel_unit_hints={"Torque": "Nm"},
        ),
        ChannelSelectionConfig.create(
            "thermal",
            "温度",
            ("Temp",),
            now="2026-08-15T00:00:00+00:00",
        ),
    ]
    preview = ChannelConfigPreview(
        target_file_count=3,
        available_names=frozenset({"EPS_CRC", "Torque"}),
        unit_hints=(("EPS_CRC", ""), ("Torque", "Nm")),
        inconsistent_unit_names=frozenset({"Torque"}),
    )
    dialog = ChannelConfigManagerDialog(
        configs,
        selected_id="drive",
        preview=preview,
        checked_channel_hints={"EPS_CRC": "", "Torque": "Nm"},
        id_factory=iter(("new-1", "new-2", "new-3")).__next__,
        open_file=lambda: "",
        save_file=lambda _path: "",
    )
    dialog._confirm_discard_changes = lambda: True
    return dialog


def _batch_sheet(tmp_dir: Path):
    from PyQt5.QtCore import QSettings

    from mf4_analyzer.ui.batch_settings import BatchPanelPrefsStore
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    store = BatchPanelPrefsStore(
        settings=QSettings(str(tmp_dir / "batch-prefs.ini"), QSettings.IniFormat)
    )
    return BatchSheet(None, files={}, current_preset=None, prefs_store=store)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture offscreen QSS baseline PNGs + sha256 manifest"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="directory for PNG + manifest.json (must not be under docs/)",
    )
    args = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("TMPDIR", "/tmp")
    os.environ.setdefault("MPLCONFIGDIR", "/tmp")
    sys.path.insert(0, str(REPO))

    output_dir = args.output_dir.expanduser()
    _refuse_tracked_docs(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    tmp_root = Path(tempfile.mkdtemp(prefix="qss_baseline_"))

    from PyQt5.QtCore import QSize
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    _disable_qt_chrome_noise(app)
    _isolate_qsettings(tmp_root)

    from mf4_analyzer.ui_kit.fonts import setup_chinese_font
    from mf4_analyzer.ui_kit.stylesheet import load_stylesheet

    setup_chinese_font()
    try:
        from mf4_analyzer.ui.pg_canvas.fonts import apply_global_chart_font

        apply_global_chart_font(app)
    except Exception as exc:  # noqa: BLE001 — baseline should still capture
        print(f"[baseline] chart font setup failed: {exc!r}")
    load_stylesheet(app)

    from mf4_analyzer.ui.main_window import MainWindow

    shots: list[dict] = []
    window = MainWindow()
    window.resize(*WINDOW_SIZE)
    window.setFixedSize(QSize(*WINDOW_SIZE))
    window.show()
    _pump(app, 10)

    for mode in MODES:
        window.toolbar._set_mode(mode)
        _pump(app, 8)
        _stop_timers_and_animations(window)
        _pump(app, 4)
        shots.append(_capture(window, output_dir, f"main-{mode.replace('_', '-')}", app))

    config_dialog = _channel_config_dialog()
    config_dialog.resize(*CHANNEL_CONFIG_SIZE)
    config_dialog.setFixedSize(QSize(*CHANNEL_CONFIG_SIZE))
    config_dialog.show()
    _pump(app, 8)
    shots.append(
        _capture(config_dialog, output_dir, "dialog-channel-config-html", app)
    )
    config_dialog.close()
    _pump(app, 4)

    batch = _batch_sheet(tmp_root)
    batch.resize(*BATCH_SHEET_SIZE)
    batch.setFixedSize(QSize(*BATCH_SHEET_SIZE))
    batch.show()
    _pump(app, 8)
    shots.append(_capture(batch, output_dir, "dialog-batch-sheet", app))
    batch.close()
    _pump(app, 4)

    window.close()
    _pump(app, 4)

    qss_path = REPO / "mf4_analyzer" / "ui_kit" / "style.qss"
    qss_text = qss_path.read_text(encoding="utf-8")
    meta = _git_meta()
    manifest = {
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": str(REPO),
        "branch": meta["branch"],
        "head": meta["head"],
        "platform": os.environ.get("QT_QPA_PLATFORM", ""),
        "window_size": list(WINDOW_SIZE),
        "style_qss": {
            "path": "mf4_analyzer/ui_kit/style.qss",
            "lines": qss_text.count("\n"),
            "bytes": qss_path.stat().st_size,
            "sha256": _sha256_file(qss_path),
        },
        "loader": "mf4_analyzer.ui_kit.stylesheet.load_stylesheet",
        "shots": shots,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[manifest] {manifest_path}")
    print(f"[dir] {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
