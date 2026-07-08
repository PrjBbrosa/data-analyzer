"""Scripted end-to-end tour of the Acquisition Cockpit.

Offscreen by default. ``--assert`` validates the 2026-07-07 cockpit
render-review invariants and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _build_pool():
    from can_logger.p0.a2l_probe import MeasurementSummary

    named = [
        ("MotSpd", "rpm", "UWORD", ("event_1ms", "event_10ms")),
        ("StrWhlTrq", "Nm", "SWORD", ("event_1ms", "event_10ms")),
        ("MotTrq", "Nm", "SWORD", ("event_1ms", "event_10ms")),
        ("EcuTemp", "degC", "SWORD", ("event_100ms",)),
        ("BattVolt", "V", "UWORD", ("event_10ms", "event_100ms")),
    ]
    pool = []
    addr = 0x40000000
    for name, unit, dtype, events in named:
        pool.append(
            MeasurementSummary(
                name=name,
                address=addr,
                datatype=dtype,
                unit=unit,
                conversion="",
                available_events=events,
            )
        )
        addr += 4
    for i in range(40):
        pool.append(
            MeasurementSummary(
                name=f"EpsDiagSig_{i:02d}",
                address=addr,
                datatype="UWORD",
                unit="",
                conversion="",
                available_events=("event_10ms",),
            )
        )
        addr += 4
    return tuple(pool)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cockpit UI end-to-end tour")
    parser.add_argument(
        "--assert",
        dest="do_assert",
        action="store_true",
        help="validate invariants and exit 1 on failure",
    )
    parser.add_argument("--shots", type=Path, default=None, help="screenshot dir")
    parser.add_argument("--out", type=Path, default=None, help="recording output dir")
    parser.add_argument(
        "--onscreen",
        action="store_true",
        help="use the real screen instead of offscreen",
    )
    args = parser.parse_args()

    if not args.onscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    out_dir = args.out or Path(tempfile.mkdtemp(prefix="cockpit_tour_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QCheckBox, QLabel

    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
    from mf4_analyzer.acquisition_ui.main_window._settings_mixin import (
        compact_path_display,
    )
    from mf4_analyzer.acquisition_ui.review_modal import ReviewModal
    from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font

    setup_chinese_font()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        load_stylesheet(app)
    except Exception as exc:  # noqa: BLE001 - tour should still expose failures
        print(f"[tour] stylesheet load failed: {exc!r}")

    window = CockpitMainWindow(initial_pool=_build_pool(), allow_fake_backend=True)
    window.set_output_dir(out_dir)
    window.show()

    failures: list[str] = []

    def check(cond: bool, msg: str) -> None:
        tag = "PASS" if cond else "FAIL"
        print(f"[assert] {tag} {msg}")
        if not cond:
            failures.append(msg)

    def shot(widget, name: str) -> None:
        if args.shots is None:
            return
        pm = widget.grab()
        pm.save(str(args.shots / f"{name}.png"))
        print(f"[shot] {name} {pm.width()}x{pm.height()}")

    steps: list[tuple[int, str, object]] = []

    def at(ms: int, name: str):
        def deco(fn):
            steps.append((ms, name, fn))
            return fn

        return deco

    @at(400, "select-bottom")
    def s_select_bottom():
        lp = window.left_pane
        sb = lp._list.verticalScrollBar()
        sb.setValue(sb.maximum())
        anchor = sb.value()
        value_label = window._output_btn.findChild(QLabel, "cockpitSelectorValue")
        check(
            value_label is not None
            and value_label.text() == compact_path_display(str(out_dir))
            and window._output_btn.toolTip() == str(out_dir),
            "tour output selector shows --out",
        )
        item = lp._list.item(lp._list.count() - 1)
        cb = lp._list.itemWidget(item).findChild(QCheckBox)
        cb.click()
        check(sb.value() == anchor, f"F3 scroll kept ({anchor} -> {sb.value()})")
        shot(window, "01-scrolled-select")
        lp._set_measurement_selected("EpsDiagSig_39", False)
        for name in ("MotSpd", "StrWhlTrq", "MotTrq"):
            lp._set_measurement_selected(name, True)
        sb.setValue(0)

    @at(800, "connect")
    def s_connect():
        window.main_button.click()

    @at(3000, "idle-check")
    def s_idle():
        from mf4_analyzer.acquisition_ui.state import CockpitState

        check(
            window.state_machine.state == CockpitState.CONNECTED_IDLE,
            "connected idle reached",
        )
        cards = window._center.cards
        check(
            bool(cards) and all(c._spark.sample_count > 0 for c in cards.values()),
            "F1 idle card buffers non-empty",
        )
        shot(window, "02-idle")

    @at(3200, "idle-add-channel")
    def s_add():
        window.left_pane._set_measurement_selected("BattVolt", True)
        window._restart_idle_stream_for_selection()

    @at(4600, "idle-added-check")
    def s_added():
        card = window._center.cards.get("BattVolt")
        check(
            card is not None and card._spark.sample_count > 0,
            "F5 idle-added channel receives data",
        )
        shot(window, "03-idle-added")

    @at(5000, "pin-default-check")
    def s_pin():
        lp = window.left_pane
        for i in range(8):
            lp._set_measurement_selected(f"EpsDiagSig_{i:02d}", True)
        window._restart_idle_stream_for_selection()
        cards = window._center.cards
        check(len(cards) == 5, f"G6 默认 5 张卡 (实测 {len(cards)})")
        bar = window._center._summary_bar
        check(
            (not bar.isHidden())
            and bar.text() == "已选 12 · 实时显示 5 · 其余通道仍会录制",
            f"G6 计数条 (实测 '{bar.text()}')",
        )
        shot(window, "03b-pinned")

    @at(5400, "record")
    def s_record():
        window.main_button.click()

    @at(8000, "recording-check")
    def s_recording():
        from mf4_analyzer.acquisition_ui.state import CockpitState

        check(window.state_machine.state == CockpitState.RECORDING, "recording reached")
        check(window.main_button.text() == "■ Stop && 复盘", "F4 && escaped")
        msg = window._status.currentMessage()
        check(
            msg.startswith("录制中") and "丢帧" in msg and "RECORDING" not in msg,
            f"G2 状态栏中文 (实测 '{msg}')",
        )
        cards = window._center.cards
        check(
            all(c._spark.sample_count > 0 for c in cards.values()),
            "F1 recording card buffers non-empty",
        )
        shot(window, "04-recording")

    @at(8200, "stop")
    def s_stop():
        window.main_button.click()

    @at(9000, "review-check")
    def s_review():
        modal = window.review_modal
        check(isinstance(modal, ReviewModal), "real ReviewModal opened")
        result = window.last_stop_result
        check(
            result is not None and len(result.selected_measurement_names) == 12,
            "G6 录制含全部 12 通道",
        )
        shot(modal if modal is not None else window, "05-review")
        if isinstance(modal, ReviewModal):
            modal.do_save_only()
            modal.reject()

    @at(16000, "soak-check")
    def s_soak():
        from mf4_analyzer.acquisition_ui.state import CockpitState

        check(
            window.state_machine.state == CockpitState.CONNECTED_IDLE,
            "review close returned to connected idle",
        )
        check(
            window.ring_buffer.level_pct == 0.0,
            f"F2 idle ring stays 0 ({window.ring_buffer.level_pct:.1f}%)",
        )
        levels = window.health_strip.current_levels()
        check(levels.get("REC") != "red", f"F2 REC not red ({levels.get('REC')})")
        check(window.main_button.isEnabled(), "F2 record button remains enabled")
        check(window._review_modal is None, "F2 no ghost review modal")
        shot(window, "06-soak")

    @at(16400, "narrow")
    def s_narrow():
        window.resize(960, 600)

    @at(17400, "narrow-check")
    def s_narrow_check():
        check(window._center.width() >= 300, f"F11 center >=300 ({window._center.width()})")
        check(
            not bool(window._mode_segment_widget.property("cockpitOverflowHidden")),
            "F11 mode segment remains visible",
        )
        for name, card in window._center.cards.items():
            check(card._stats_label.isHidden(), f"G1 {name} stats 已折叠")
            check(bool(card._name_label.visible_text()), f"G1 {name} 名称可见")
        first_card = next(iter(window._center.cards.values()), None)
        if first_card is not None:
            stats = first_card.findChild(QLabel, "liveCardStats")
            value = first_card.findChild(QLabel, "liveCardValue")
            check(
                stats is not None and not stats.isVisible(),
                "polish narrow stats collapse",
            )
            check(
                value is not None
                and value.geometry().right() <= first_card.contentsRect().right(),
                "polish narrow current value visible",
            )
        shot(window, "07-narrow")

    @at(18000, "finish")
    def s_finish():
        produced = sorted(p.name for p in out_dir.glob("capture_*"))
        check(any(n.endswith(".mf4") for n in produced), "MF4 exists")
        check(
            any(n.endswith(".session_summary.json") for n in produced),
            "session_summary.json exists",
        )
        check(any(n.endswith(".preflight.json") for n in produced), "preflight.json exists")
        print(f"[runs] {produced}")
        window.close()
        app.exit(0)

    for ms, name, fn in steps:
        def runner(fn=fn, name=name):
            try:
                fn()
            except Exception:  # noqa: BLE001 - collect all failures
                failures.append(f"step {name} raised")
                print(f"[step-fail] {name}\n{traceback.format_exc()}")

        QTimer.singleShot(ms, runner)

    app.exec_()
    if args.do_assert and failures:
        print(f"[tour] {len(failures)} invariant(s) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("[tour] all invariants passed" if args.do_assert else "[tour] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
