"""Render deterministic offscreen proof for the batch input/output polish.

Outputs live under ``.state/batch-input-output-polish-proof`` and use the
actual PyQt widgets plus the production Matplotlib batch renderer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("TMPDIR", "/tmp/tracelab-batch-input-output-proof")
os.environ.setdefault(
    "XDG_CONFIG_HOME", "/tmp/tracelab-batch-input-output-proof/xdg"
)

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from mf4_analyzer.batch_image_options import BatchRenderOptions  # noqa: E402
from mf4_analyzer.batch_render import (  # noqa: E402
    BatchRenderContext,
    render_batch_image,
)
from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel  # noqa: E402
from mf4_analyzer.ui.drawers.batch.signal_picker import (  # noqa: E402
    SignalChip, SignalPickerPopup,
)
from mf4_analyzer.ui_kit.stylesheet import load_stylesheet  # noqa: E402


PROOF_DIR = REPO_ROOT / ".state" / "batch-input-output-polish-proof"


def _process(app: QApplication) -> None:
    for _ in range(4):
        app.processEvents()


def _save_picker_proofs(app: QApplication) -> dict[str, object]:
    signals = tuple(
        f"Rte_ActRetPlausi_mActiveReturnMotorTorque_xds16_variant_{index:02d}"
        for index in range(20)
    )
    picker = SignalPickerPopup(signals)
    picker.set_selected(signals)
    picker.resize(288, 38)
    picker.show()
    _process(app)

    closed_path = PROOF_DIR / "signal-picker-20-selected.png"
    assert picker.grab().save(str(closed_path))

    frame = picker._display_frame
    bounded_children = (
        picker._chip_host,
        picker._overflow_label,
        picker._search,
        picker._arrow_button,
    )
    for child in bounded_children:
        if child.isVisible():
            right = child.mapTo(frame, child.rect().bottomRight()).x()
            assert right <= frame.width(), (child.objectName(), right, frame.width())
    assert picker.height() == 38
    assert picker._overflow_label.text() == "+19"
    closed_visible_chip_count = len(
        picker._chip_host.findChildren(SignalChip)
    )
    closed_overflow_text = picker._overflow_label.text()

    picker.set_search_text("variant_1")
    picker.show_popup()
    _process(app)
    top = picker.grab()
    popup = picker._popup.grab()
    gap = 4
    composite = QPixmap(max(top.width(), popup.width()), top.height() + gap + popup.height())
    composite.fill(QColor("white"))
    painter = QPainter(composite)
    painter.drawPixmap(0, 0, top)
    painter.drawPixmap(0, top.height() + gap, popup)
    painter.end()
    popup_path = PROOF_DIR / "signal-picker-inline-search.png"
    assert composite.save(str(popup_path))

    metrics = {
        "picker_width": picker.width(),
        "picker_height": picker.height(),
        "display_width": frame.width(),
        "closed_visible_chip_count": closed_visible_chip_count,
        "closed_overflow_text": closed_overflow_text,
        "active_search_width": picker._search.width(),
        "visible_search_matches": len(picker.visible_items()),
        "popup_has_second_line_edit": bool(picker._popup.findChildren(type(picker._search))),
    }
    picker.hide_popup()
    picker.close()
    return metrics


def _save_output_proofs(app: QApplication) -> dict[str, object]:
    panel = OutputPanel()
    panel.resize(360, 1050)
    panel.show()
    _process(app)
    assert not panel._output_settings.isVisible()
    collapsed = panel.grab().copy(0, 0, panel.width(), 470)
    collapsed_path = PROOF_DIR / "output-settings-collapsed.png"
    assert collapsed.save(str(collapsed_path))

    panel._btn_output_settings.click()
    panel.resize(360, max(1180, panel.sizeHint().height()))
    _process(app)
    assert panel._output_settings.isVisible()
    expanded = panel.grab().copy(0, 0, panel.width(), 900)
    expanded_path = PROOF_DIR / "output-settings-expanded.png"
    assert expanded.save(str(expanded_path))

    settings_right = panel._output_settings.geometry().right()
    assert settings_right <= panel.width()
    metrics = {
        "panel_width": panel.width(),
        "default_settings_collapsed": True,
        "expanded_settings_right": settings_right,
        "default_background": panel.get_outputs().image_background,
        "default_line_width": panel.get_outputs().image_line_width,
        "summary": panel._output_summary.text(),
    }
    panel.close()
    return metrics


def _save_batch_image_proof() -> dict[str, object]:
    samples = 1400
    time_s = np.linspace(0.0, 12.0, samples)
    rows = []
    for index, name in enumerate(("front-left", "front-right", "rear-left")):
        values = 0.7 * np.sin((1.2 + index * 0.12) * time_s + index * 0.45)
        values += 0.12 * np.sin(8.0 * time_s + index)
        rows.append(
            pd.DataFrame({"time_s": time_s, "series": name, "value": values})
        )
    frame = pd.concat(rows, ignore_index=True)
    target = PROOF_DIR / "batch-render-white-1px.png"
    options = BatchRenderOptions(
        width_px=960,
        height_px=540,
        dpi=120,
        format="png",
        background="white",
        line_width=1.0,
    )
    render_batch_image(
        ("time", frame),
        target,
        options=options,
        context=BatchRenderContext(
            source_display_name="batch-demo.mf4",
            channel="Rte_TAS_mTorsionBarTorque_xds16",
            unit="Nm",
            method="时域",
            task_id="offscreen-proof",
        ),
    )
    from PIL import Image

    with Image.open(target) as image:
        assert image.size == (960, 540)
        corner = image.convert("RGBA").getpixel((0, 0))
        assert corner[:3] == (255, 255, 255)
    return {
        "image_size": [960, 540],
        "background": options.background,
        "line_width": options.line_width,
        "corner_rgba": list(corner),
    }


def main() -> int:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    load_stylesheet(app)

    report = {
        "signal_picker": _save_picker_proofs(app),
        "output_panel": _save_output_proofs(app),
        "batch_image": _save_batch_image_proof(),
    }
    report_path = PROOF_DIR / "proof.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
