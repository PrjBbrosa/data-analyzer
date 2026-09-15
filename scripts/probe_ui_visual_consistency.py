#!/usr/bin/env python3
"""Capture a reproducible channel-tree visual baseline for T0.

This is a diagnostic probe, not an application test.  It mounts the production
``MultiFileChannelWidget`` with the shipped QSS and records real rendered
pixels for structured tree identities.  Its QSettings and generated QSS-icon
cache are redirected into the chosen evidence directory, so a run never
updates a developer's settings or ``~/.mf4-analyzer-cache``.

The probe has no platform override or private rendering toggle.  After T1 it
captures the one public cross-platform vector path and checks its observable
pixel contract.  The pre-fix red evidence remains immutable in its original
evidence directory; it is not kept alive by retaining a production-only test
branch.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from PyQt5.QtCore import QCoreApplication, QPoint, QRect, QSettings, Qt
from PyQt5.QtGui import QColor, QFontInfo, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / ".state" / "windows-ui-visual-consistency" / "t0-probe"
)
SELECTED_BG = "#b7d3f2"
CHEVRON = "#334155"
PARENT_KINDS = ("file", "source", "raster", "record_group")
LEAF_KINDS = ("channel", "record_binding")


class _SyntheticFileData:
    """Small production-shaped source with stable identity, not display keys."""

    def __init__(
        self,
        *,
        filename: str,
        channels: Iterable[str],
        nested: bool,
        raster_index: int = 0,
    ) -> None:
        self.filename = filename
        self.short_name = Path(filename).stem
        self.filepath = Path("/probe-synthetic") / filename
        self.data = list(range(240))
        self.fs = 1200.0
        self._channels = tuple(channels)
        self.channel_units = {channel: "m/s²" for channel in self._channels}
        self.label_suffix = f"Zeit {raster_index}" if nested else ""
        self.source_metadata = (
            {
                "source_kind": "wwt",
                "zeit_record_indices": [raster_index],
                "formula_channel_count": 0,
            }
            if nested
            else {}
        )

    def get_signal_channels(self) -> list[str]:
        return list(self._channels)

    def get_color_palette(self) -> list[str]:
        return ["#1769e0", "#8b5cf6", "#f43f5e", "#f59e0b"]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="empty evidence directory (default: %(default)s)",
    )
    parser.add_argument(
        "--require-public-contract",
        action="store_true",
        help="return 2 unless every expandable parent satisfies the public vector-paint contract",
    )
    return parser.parse_args()


def _prepare_output_dir(output_dir: Path) -> Path:
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(REPO_ROOT / ".state" / "windows-ui-visual-consistency")
    except ValueError as exc:
        raise SystemExit(
            "--output-dir must stay under .state/windows-ui-visual-consistency"
        ) from exc
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty evidence directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _configure_qt_isolation(output_dir: Path) -> None:
    """Keep QSettings and icon-cache writes inside this current-run evidence."""
    settings_dir = output_dir / "isolated-settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    for scope in (QSettings.UserScope, QSettings.SystemScope):
        QSettings.setPath(QSettings.IniFormat, scope, str(settings_dir))
    QCoreApplication.setOrganizationName("TraceLabVisualProbe")
    QCoreApplication.setOrganizationDomain("local.tracelab.probe")
    QCoreApplication.setApplicationName("windows-ui-visual-consistency")


def _run_git(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return completed.stdout.rstrip("\n") or "UNKNOWN"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _distribution_version(*names: str) -> str:
    for name in names:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return "UNKNOWN"


def _font_info(font) -> dict[str, Any]:
    info = QFontInfo(font)
    return {
        "requested_family": font.family(),
        "resolved_family": info.family(),
        "point_size": int(info.pointSize()),
        "pixel_size": int(info.pixelSize()),
        "weight": int(info.weight()),
        "bold": bool(info.bold()),
        "italic": bool(info.italic()),
        "exact_match": bool(info.exactMatch()),
    }


def _environment_facts(widget) -> dict[str, Any]:
    from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    from mf4_analyzer.ui_kit.layout_diagnostics import collect_environment_facts

    try:
        import qtawesome as qta

        qtawesome_version = getattr(qta, "__version__", "UNKNOWN")
    except ImportError:
        qtawesome_version = "UNKNOWN"
    status = _run_git("status", "--porcelain=v1")
    staged = _run_git("diff", "--cached", "--binary")
    unstaged = _run_git("diff", "--binary")
    return {
        "layout_diagnostics": collect_environment_facts(widget),
        "qt_version": QT_VERSION_STR,
        "pyqt_version": PYQT_VERSION_STR,
        "qtawesome_version": qtawesome_version,
        "pyinstaller_version": _distribution_version("pyinstaller", "PyInstaller"),
        "platform": platform.platform(),
        "sys_platform": sys.platform,
        "frozen": bool(getattr(sys, "frozen", False)),
        "execution_layer": "frozen" if getattr(sys, "frozen", False) else "source",
        "build_flavor": (
            os.environ.get("TRACELAB_BUILD_FLAVOR")
            or os.environ.get("MF4_ANALYZER_BUILD_FLAVOR")
            or "UNKNOWN"
        ),
        "head": _run_git("rev-parse", "HEAD"),
        "worktree_fingerprint": {
            "status_sha256": _sha256_text(status),
            "status_entry_count": 0 if status == "UNKNOWN" else len(status.splitlines()),
            "tracked_staged_diff_sha256": _sha256_text(staged),
            "tracked_unstaged_diff_sha256": _sha256_text(unstaged),
        },
        "probe_qfontinfo": _font_info(widget.font()),
    }


def _item_by_role(tree, role: tuple) -> Any:
    stack = [tree.topLevelItem(index) for index in range(tree.topLevelItemCount())]
    while stack:
        item = stack.pop()
        if item is None:
            continue
        data = item.data(0, Qt.UserRole)
        if data is not None and tuple(data) == role:
            return item
        stack.extend(item.child(index) for index in range(item.childCount()))
    raise RuntimeError(f"probe item not found for structured role {role!r}")


def _build_widget(app: QApplication, output_dir: Path):
    """Create the real widget and official stylesheet with local-only cache IO."""
    from mf4_analyzer.ui_kit import icons, load_stylesheet
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget

    icon_cache_dir = output_dir / "isolated-icon-cache"
    icon_cache_dir.mkdir(parents=True, exist_ok=True)
    # The production loader calls this module seam.  Redirecting only this
    # process keeps its real QSS/icon path while avoiding the user's cache.
    icons._icon_cache_dir = lambda: icon_cache_dir
    app.setStyle("Fusion")
    load_stylesheet(app)

    widget = MultiFileChannelWidget()
    widget.setWindowTitle("TraceLab T0 visual consistency probe")
    widget.resize(680, 620)
    flat = _SyntheticFileData(
        filename="flat-identity.mf4",
        channels=("Flat_Torque_DV", "Flat_Torque_PV"),
        nested=False,
    )
    nested = _SyntheticFileData(
        filename="source-identity.wwt",
        channels=("Raster_Acceleration_DV", "Raster_Acceleration_PV"),
        nested=True,
        raster_index=7,
    )
    widget.add_file("flat-fid", flat)
    widget.add_file("raster-fid", nested)
    widget.set_attached_file_ids(("flat-fid", "raster-fid"))
    widget.set_record_curve_rows(
        "probe-view",
        (
            {
                "binding_id": "record-binding-id",
                "owner_fid": "raster-fid",
                "record_index": 17,
                "name": "Record_Limit",
                "unit": "mm",
                "color": "#f43f5e",
                "visible": True,
            },
        ),
    )
    widget.tree.expandAll()
    widget.show()
    _flush_events(app)
    return widget


def _flush_events(app: QApplication) -> None:
    for _ in range(4):
        app.processEvents()


def _physical_rect(logical: QRect, pixmap: QPixmap, logical_width: int, logical_height: int) -> QRect:
    """Map a logical widget/viewport QRect into the capture's physical pixels."""
    scale_x = pixmap.width() / max(1, logical_width)
    scale_y = pixmap.height() / max(1, logical_height)
    left = max(0, math.floor(logical.left() * scale_x))
    top = max(0, math.floor(logical.top() * scale_y))
    right = min(pixmap.width() - 1, math.ceil((logical.right() + 1) * scale_x) - 1)
    bottom = min(pixmap.height() - 1, math.ceil((logical.bottom() + 1) * scale_y) - 1)
    return QRect(left, top, max(0, right - left + 1), max(0, bottom - top + 1))


def _rect_facts(logical: QRect, pixmap: QPixmap, logical_width: int, logical_height: int) -> dict[str, Any]:
    physical = _physical_rect(logical, pixmap, logical_width, logical_height)
    return {
        "logical": {
            "x": logical.x(), "y": logical.y(),
            "width": logical.width(), "height": logical.height(),
        },
        "physical": {
            "x": physical.x(), "y": physical.y(),
            "width": physical.width(), "height": physical.height(),
        },
    }


def _color_hex(image, x: int, y: int) -> str:
    if not (0 <= x < image.width() and 0 <= y < image.height()):
        return "OUT_OF_RANGE"
    return image.pixelColor(x, y).name().lower()


def _region_summary(image, rect: QRect) -> dict[str, Any]:
    colors: Counter[str] = Counter()
    dark_points: list[tuple[int, int]] = []
    exact_chevron = 0
    for y in range(rect.top(), rect.bottom() + 1):
        for x in range(rect.left(), rect.right() + 1):
            color = image.pixelColor(x, y)
            name = color.name().lower()
            colors[name] += 1
            if name == CHEVRON:
                exact_chevron += 1
            if color.lightness() < 175:
                dark_points.append((x, y))
    dark_bbox = None
    if dark_points:
        xs, ys = zip(*dark_points)
        dark_bbox = {
            "x": min(xs), "y": min(ys),
            "width": max(xs) - min(xs) + 1,
            "height": max(ys) - min(ys) + 1,
        }
    dominant = colors.most_common(4)
    return {
        "physical_pixel_count": sum(colors.values()),
        "dominant_colors": [
            {"hex": name, "count": count} for name, count in dominant
        ],
        "selected_bg_exact_count": colors[SELECTED_BG],
        "chevron_exact_count": exact_chevron,
        "dark_ink_count": len(dark_points),
        "dark_ink_bbox_physical": dark_bbox,
    }


def _save_pixmap(pixmap: QPixmap, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"failed to save evidence image: {path}")
    return {
        "path": str(path.relative_to(path.parents[1])),
        "physical_width": pixmap.width(),
        "physical_height": pixmap.height(),
        "device_pixel_ratio": float(pixmap.devicePixelRatioF()),
    }


def _set_window_state(widget, other_window: QLabel, requested: str, app: QApplication) -> None:
    if requested == "active":
        widget.raise_()
        widget.activateWindow()
        widget.tree.setFocus()
    elif requested == "inactive":
        other_window.raise_()
        other_window.activateWindow()
        other_window.setFocus()
    else:  # pragma: no cover - kept as a guard for future state additions
        raise ValueError(f"unknown requested window state: {requested}")
    _flush_events(app)


def _set_tree_state(tree, item, *, expanded: bool | None, selected: bool, app: QApplication) -> None:
    tree.clearSelection()
    tree.setCurrentItem(None)
    if expanded is not None:
        item.setExpanded(expanded)
    if selected:
        tree.setCurrentItem(item)
        item.setSelected(True)
    _flush_events(app)


def _capture_state(
    *,
    output_dir: Path,
    widget,
    item,
    role: tuple,
    kind: str,
    mode: str,
    selected: bool,
    expanded: bool | None,
    requested_window_state: str,
    sequence: int,
) -> dict[str, Any]:
    tree = widget.tree
    viewport = tree.viewport()
    row = tree.visualItemRect(item)
    if not row.isValid() or row.height() <= 0:
        raise RuntimeError(f"target row is not renderable for {role!r}: {row!r}")
    cell = tree.visualRect(tree.indexFromItem(item, 0))
    branch_region = QRect(0, row.top(), max(0, row.left()), row.height())
    slot_width = min(max(0, row.left()), tree.indentation())
    expander_slot = QRect(max(0, row.left() - slot_width), row.top(), slot_width, row.height())

    viewport_pixmap = viewport.grab()
    viewport_image = viewport_pixmap.toImage()
    row_physical = _physical_rect(row, viewport_pixmap, viewport.width(), viewport.height())
    branch_physical = _physical_rect(
        branch_region, viewport_pixmap, viewport.width(), viewport.height()
    )
    slot_physical = _physical_rect(
        expander_slot, viewport_pixmap, viewport.width(), viewport.height()
    )
    crop_logical = branch_region.adjusted(-2, -2, 2, 2).intersected(
        QRect(0, 0, viewport.width(), viewport.height())
    )
    crop_physical = _physical_rect(
        crop_logical, viewport_pixmap, viewport.width(), viewport.height()
    )
    stem = (
        f"{sequence:03d}-{mode}-{kind}-"
        f"{'selected' if selected else 'normal'}-"
        f"{'leaf' if expanded is None else ('open' if expanded else 'closed')}-"
        f"{requested_window_state}"
    )
    screenshot = _save_pixmap(widget.grab(), output_dir / "screenshots" / f"{stem}-full.png")
    crop = _save_pixmap(
        viewport_pixmap.copy(crop_physical),
        output_dir / "screenshots" / f"{stem}-branch.png",
    )

    body_probe_logical = QPoint(
        max(cell.left(), cell.right() - 2),
        max(row.top() + 1, min(row.bottom() - 1, row.center().y())),
    )
    body_probe_physical = _physical_rect(
        QRect(body_probe_logical.x(), body_probe_logical.y(), 1, 1),
        viewport_pixmap,
        viewport.width(),
        viewport.height(),
    )
    return {
        "id": stem,
        "structured_role": list(role),
        "kind": kind,
        "mode": mode,
        "state": {
            "selected": selected,
            "expanded": expanded,
            "window_state_requested": requested_window_state,
            "window_is_active_observed": bool(widget.isActiveWindow()),
            "active_window_observed": (
                QApplication.activeWindow().objectName()
                if QApplication.activeWindow() is not None
                else "UNKNOWN"
            ),
            "tree_has_focus_observed": bool(tree.hasFocus()),
        },
        "control_rects": {
            "tree_viewport": _rect_facts(
                QRect(0, 0, viewport.width(), viewport.height()),
                viewport_pixmap,
                viewport.width(),
                viewport.height(),
            ),
            "row": _rect_facts(row, viewport_pixmap, viewport.width(), viewport.height()),
            "column_0_cell": _rect_facts(cell, viewport_pixmap, viewport.width(), viewport.height()),
            "branch_region": _rect_facts(
                branch_region, viewport_pixmap, viewport.width(), viewport.height()
            ),
            "expander_slot": _rect_facts(
                expander_slot, viewport_pixmap, viewport.width(), viewport.height()
            ),
        },
        "capture_scale": {
            "screen_dpr": float(widget.screen().devicePixelRatio()) if widget.screen() else "UNKNOWN",
            "viewport_pixmap_dpr": float(viewport_pixmap.devicePixelRatioF()),
            "physical_per_logical_x": viewport_pixmap.width() / max(1, viewport.width()),
            "physical_per_logical_y": viewport_pixmap.height() / max(1, viewport.height()),
        },
        "font_info": {
            "tree": _font_info(tree.font()),
            "item": _font_info(item.font(0)),
        },
        "pixel_regions": {
            "branch_region": _region_summary(viewport_image, branch_physical),
            "expander_slot": _region_summary(viewport_image, slot_physical),
            "row": _region_summary(viewport_image, row_physical),
            "body_background_probe": {
                "logical": {"x": body_probe_logical.x(), "y": body_probe_logical.y()},
                "physical": {"x": body_probe_physical.x(), "y": body_probe_physical.y()},
                "color": _color_hex(viewport_image, body_probe_physical.x(), body_probe_physical.y()),
            },
        },
        "screenshots": {"full_control": screenshot, "branch_crop": crop},
    }


def _capture_matrix(widget, output_dir: Path, app: QApplication) -> list[dict[str, Any]]:
    tree = widget.tree
    source_role = ("source", str(Path("/probe-synthetic") / "source-identity.wwt"))
    targets = {
        "file": ("file", "flat-fid"),
        "source": source_role,
        "raster": ("raster", "raster-fid"),
        "record_group": ("record_group", "probe-view", "raster-fid"),
        "channel": ("channel", "raster-fid", "Raster_Acceleration_DV"),
        "record_binding": (
            "record_binding", "probe-view", "record-binding-id", "raster-fid", 17,
        ),
    }
    other_window = QLabel("inactive probe window")
    other_window.setObjectName("visualConsistencyInactiveWindow")
    other_window.resize(180, 48)
    other_window.show()
    _flush_events(app)

    records: list[dict[str, Any]] = []
    sequence = 0
    try:
        for kind in PARENT_KINDS:
            item = _item_by_role(tree, targets[kind])
            for expanded in (True, False):
                for selected in (False, True):
                    for window_state in ("active", "inactive"):
                        _set_tree_state(
                            tree, item, expanded=expanded, selected=selected, app=app
                        )
                        _set_window_state(widget, other_window, window_state, app)
                        records.append(_capture_state(
                            output_dir=output_dir,
                            widget=widget,
                            item=item,
                            role=targets[kind],
                            kind=kind,
                            mode="public_vector",
                            selected=selected,
                            expanded=expanded,
                            requested_window_state=window_state,
                            sequence=sequence,
                        ))
                        sequence += 1
            item.setExpanded(True)
        for kind in LEAF_KINDS:
            item = _item_by_role(tree, targets[kind])
            for selected in (False, True):
                for window_state in ("active", "inactive"):
                    _set_tree_state(tree, item, expanded=None, selected=selected, app=app)
                    _set_window_state(widget, other_window, window_state, app)
                    records.append(_capture_state(
                        output_dir=output_dir,
                        widget=widget,
                        item=item,
                        role=targets[kind],
                        kind=kind,
                        mode="public_vector",
                        selected=selected,
                        expanded=None,
                        requested_window_state=window_state,
                        sequence=sequence,
                    ))
                    sequence += 1
    finally:
        other_window.close()
        widget.close()
        _flush_events(app)
    return records


def _public_contract_failures(records: Iterable[dict[str, Any]]) -> list[str]:
    """Return public parent-vector violations, keeping leaves arrow-free."""
    failures = []
    for record in records:
        state = record["state"]
        summary = record["pixel_regions"]["expander_slot"]
        bbox = summary["dark_ink_bbox_physical"]
        slot = record["control_rects"]["expander_slot"]["physical"]
        if record["kind"] in PARENT_KINDS:
            if summary["dark_ink_count"] == 0 or bbox is None:
                failures.append(f"{record['id']}: missing vector ink")
                continue
            if not (
                slot["x"] <= bbox["x"]
                and slot["y"] <= bbox["y"]
                and bbox["x"] + bbox["width"] <= slot["x"] + slot["width"]
                and bbox["y"] + bbox["height"] <= slot["y"] + slot["height"]
            ):
                failures.append(f"{record['id']}: vector ink escaped expander slot")
            elif state["expanded"] and bbox["width"] <= bbox["height"]:
                failures.append(f"{record['id']}: open vector has wrong orientation")
            elif not state["expanded"] and bbox["height"] <= bbox["width"]:
                failures.append(f"{record['id']}: closed vector has wrong orientation")
        elif record["kind"] in LEAF_KINDS and summary["dark_ink_count"]:
            failures.append(f"{record['id']}: leaf gained disclosure ink")
    return failures


def main() -> int:
    args = _parse_args()
    output_dir = _prepare_output_dir(args.output_dir)
    _configure_qt_isolation(output_dir)
    app = QApplication.instance() or QApplication(["probe_ui_visual_consistency"])
    widget = _build_widget(app, output_dir)
    payload: dict[str, Any] = {
        "schema": "tracelab.windows-ui-visual-consistency.t0.v1",
        "purpose": "offscreen T0 reproduction and environment evidence only",
        "acceptance_limits": {
            "macos_cocoa_foreground": "UNKNOWN (not performed by this offscreen probe)",
            "windows_source": "UNKNOWN (not performed by this offscreen probe)",
            "windows_full_frozen": "UNKNOWN (not performed by this offscreen probe)",
            "windows_lite_frozen": "UNKNOWN (not performed by this offscreen probe)",
            "windows_popup_desktop_constraint": (
                "Future Windows popup acceptance must use a topmost host, "
                "QScreen.grabWindow(0), verified reference pixel, frameGeometry(), "
                "and DPR-aware coordinates; widget.grab()/offscreen is not acceptance."
            ),
        },
        "environment": _environment_facts(widget),
        "probe_isolation": {
            "qsettings_format": "IniFormat",
            "qsettings_dir": "isolated-settings",
            "icon_cache_dir": "isolated-icon-cache",
            "developer_config_written": False,
            "developer_icon_cache_written": False,
        },
        "render_contract": {
            "path": "public cross-platform vector expander",
            "platform_override": False,
            "private_toggle": False,
            "note": (
                "The pre-T1 red evidence is retained in its own immutable run. "
                "This run tests only the public path after removal of the platform split."
            ),
        },
    }
    try:
        records = _capture_matrix(widget, output_dir, app)
    except Exception as exc:
        payload["probe_status"] = "UNVERIFIED"
        payload["error"] = repr(exc)
        (output_dir / "evidence.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise
    contract_failures = _public_contract_failures(records)
    payload.update({
        "probe_status": "PUBLIC_CONTRACT_PASS" if not contract_failures else "PUBLIC_CONTRACT_FAIL",
        "state_count": len(records),
        "states": records,
        "public_contract_failures": contract_failures,
    })
    (output_dir / "evidence.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"evidence={output_dir / 'evidence.json'}")
    print(f"states={len(records)}")
    print(f"public_contract_failures={len(contract_failures)}")
    for failure in contract_failures:
        print(f"contract_failure={failure}")
    if args.require_public_contract and contract_failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
