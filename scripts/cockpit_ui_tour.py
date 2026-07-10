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


def _synth_snapshot(*, dropped: int = 0, ring: float = 10.0, last_rx: float = 0.1):
    """A green baseline ``HealthSnapshot`` with overridable REC fields.

    Mirrors ``tests/acquisition_ui/test_escalation.py::make_snapshot`` so the
    tour can inject the yellow/red escalation ladder deterministically (the
    FAKE demo backend always has a green 10 GB+ disk, so real polling never
    reaches yellow/red on its own — Task B-6).
    """
    import time as _time

    from mf4_analyzer.acquisition_capture.health import (
        CanHealth,
        DaqHealth,
        HealthSnapshot,
        HwHealth,
        RecHealth,
        XcpHealth,
    )

    return HealthSnapshot(
        hw=HwHealth(
            ok=True,
            driver_version="tour",
            channel_count=1,
            last_probe_ts=_time.monotonic(),
            error=None,
        ),
        can=CanHealth(bus_load_pct=10.0),
        xcp=XcpHealth(connected=True, slave_id=0x55),
        daq=DaqHealth(
            event_capacity={"event_10ms": 32}, event_used={"event_10ms": 1}
        ),
        rec=RecHealth(
            state="recording",
            ring_buffer_fill_pct=ring,
            dropped_frames=dropped,
            write_rate_bps=0.0,
            last_rx_age_s=last_rx,
            writer_thread_alive=True,
        ),
        captured_at=_time.monotonic(),
    )


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

    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QFrame,
        QLabel,
        QPushButton,
    )

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
    # Cross-step scratch (e.g. idle body geometry captured for the B3 zero-shift
    # comparison against the recording state).
    ctx: dict[str, object] = {}

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

    @at(250, "disconnected-check")
    def s_disconnected():
        # B-2: while disconnected the preflight pill is VISIBLE but disabled
        # and reads ``连接后可用`` (never openable). B-5: the capture center
        # hosts the structured connection checklist (3 structured rows), while
        # Replay — which never calls set_connection_checklist — keeps its plain
        # placeholder (asserted in focused pytest, not here, to avoid MF4 IO).
        strip = window.health_strip
        pill = strip.preflight_pill
        check(
            pill.isVisible() and not pill.isEnabled() and not pill.is_openable(),
            f"B2 disconnected pill disabled (vis={pill.isVisible()} "
            f"en={pill.isEnabled()} open={pill.is_openable()})",
        )
        check(
            pill.label_text() == "连接后可用",
            f"B2 disconnected pill label ({pill.label_text()!r})",
        )
        frame = window._center.findChild(QFrame, "cockpitConnectionChecklist")
        check(
            frame is not None and frame.isVisible(),
            "B5 capture connection checklist visible while disconnected",
        )
        leds = window._center.findChildren(QLabel, "cockpitChecklistLed")
        keys = {led.property("checklistKey") for led in leds}
        check(
            len(leds) == 3 and keys == {"a2l", "hw", "selection"},
            f"B5 checklist has 3 structured rows ({sorted(keys)})",
        )
        shot(window, "00-disconnected")

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

    @at(3050, "idle-preflight-check")
    def s_idle_preflight():
        # B-2: connected-idle lights the preflight pill (visible, enabled,
        # openable, its own name — not混入五健康 chips). Capture the idle body
        # geometry so the recording step can prove B3 zero-shift (the pill
        # hiding on record must not move the center).
        from mf4_analyzer.acquisition_ui.widgets.health_strip import PreflightPill

        pill = window.health_strip.preflight_pill
        check(
            pill.isVisible() and pill.isEnabled() and pill.is_openable(),
            f"B2 idle pill openable (vis={pill.isVisible()} "
            f"en={pill.isEnabled()} open={pill.is_openable()})",
        )
        check(
            pill.label_text() == PreflightPill.NAME,
            f"B2 idle pill label ({pill.label_text()!r})",
        )
        ctx["idle_center_geo"] = window._center.geometry()

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

    @at(4650, "popover-matrix")
    def s_popover_matrix():
        # B-1/B-2: the health strip owns ONE HealthPopover reused across all
        # chips and the preflight pill. Exercise the close matrix: open →
        # same-chip toggle-close → switch chip (single instance) → Esc-close →
        # pill aggregate popover (single instance, 5 rows).
        from mf4_analyzer.acquisition_ui.widgets.health_strip import PreflightPill

        strip = window.health_strip
        hw_chip = strip.chip("HW")
        can_chip = strip.chip("CAN")
        rec_chip = strip.chip("REC")

        QTest.mouseClick(hw_chip, Qt.LeftButton)
        pop = strip.detail_popover
        check(
            pop is not None and pop.isVisible() and strip.active_chip() == "HW",
            f"B1 chip click opens popover anchored HW ({strip.active_chip()})",
        )
        check(pop.row_count() > 0, f"B1 popover has rows ({pop.row_count()})")
        pop_id = id(pop)
        shot(window, "03d-popover-hw")

        # Same-chip click toggles it closed.
        QTest.mouseClick(hw_chip, Qt.LeftButton)
        check(
            not strip.detail_popover.isVisible() and strip.active_chip() is None,
            "B1 same-chip toggle closes popover",
        )

        # Switching chips reuses the single instance (no second popover).
        QTest.mouseClick(can_chip, Qt.LeftButton)
        check(
            strip.detail_popover.isVisible() and id(strip.detail_popover) == pop_id,
            "B1 CAN reuses the single popover instance",
        )
        QTest.mouseClick(rec_chip, Qt.LeftButton)
        check(
            id(strip.detail_popover) == pop_id
            and strip.active_chip() == "REC"
            and strip.detail_popover.title_text() == "REC",
            f"B1 REC switch reuses single instance ({strip.active_chip()})",
        )

        # Esc closes the popover (application-level event filter).
        QTest.keyClick(window, Qt.Key_Escape)
        check(
            strip.active_chip() is None and not strip.detail_popover.isVisible(),
            "B1 Esc closes popover",
        )

        # B-2: the preflight pill reuses the SAME single popover with its 5
        # aggregate rows.
        pill = strip.preflight_pill
        QTest.mouseClick(pill, Qt.LeftButton)
        check(
            strip.detail_popover.isVisible()
            and strip.active_chip() == PreflightPill.NAME
            and id(strip.detail_popover) == pop_id,
            f"B2 pill reuses single popover ({strip.active_chip()})",
        )
        check(
            strip.detail_popover.row_count() == 5,
            f"B2 preflight popover has 5 rows ({strip.detail_popover.row_count()})",
        )
        shot(window, "03e-preflight-popover")
        QTest.mouseClick(pill, Qt.LeftButton)
        check(strip.active_chip() is None, "B2 pill toggle closes popover")

    @at(5000, "focus-card")
    def s_focus_card():
        card = window._center.cards.get("StrWhlTrq")
        check(card is not None, "Focus card target exists")
        if card is not None:
            QTest.mouseClick(card, Qt.LeftButton)

    @at(5400, "focus-card-check")
    def s_focus_card_check():
        cards = window._center.cards
        bar = window._center.findChild(QLabel, "liveFocusBar")
        check(window._center.focused_channel == "StrWhlTrq", "F12 card click focuses StrWhlTrq")
        check(list(cards) == ["StrWhlTrq"], f"F12 only focused card visible ({list(cards)})")
        check(
            bar is not None and bar.isVisible() and "聚焦查看" in bar.text(),
            f"F12 focus bar visible ({bar.text() if bar is not None else '<missing>'})",
        )
        shot(window, "03c-focused-card")

    @at(5700, "focus-card-back")
    def s_focus_card_back():
        button = window._center.findChild(QPushButton, "liveFocusBackButton")
        if button is not None:
            button.click()
        else:
            window._center.clear_focus()
        check(window._center.focused_channel is None, "F12 focus returns to all cards")

    @at(6100, "pin-default-check")
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

    @at(6500, "record")
    def s_record():
        window.main_button.click()

    @at(9500, "recording-check")
    def s_recording():
        from mf4_analyzer.acquisition_ui.state import CockpitState

        check(window.state_machine.state == CockpitState.RECORDING, "recording reached")
        check(window.main_button.text() == "■ Stop && 复盘", "F4 && escaped")
        msg = window._status.currentMessage()
        # B-3: the status bar streams neutral Chinese FACTS (时长/磁盘剩余
        # 时长/样本/大小/写入速率). Dropped/ring anomalies moved to the
        # escalation ladder + REC chip, so "丢帧" is no longer here.
        check(
            "样本" in msg and "剩余" in msg and "RECORDING" not in msg
            and "丢帧" not in msg,
            f"G2 状态栏中文 (实测 '{msg}')",
        )
        cards = window._center.cards
        check(
            all(c._spark.sample_count > 0 for c in cards.values()),
            "F1 recording card buffers non-empty",
        )
        # B-2: recording HIDES the preflight pill (the strip is a fixed-height
        # row above the splitter, so this never reflows the body).
        pill = window.health_strip.preflight_pill
        check(not pill.isVisible(), "B2 recording hides preflight pill")
        # B-3/B-4 zero-shift: the capture body geometry is identical in idle and
        # recording (pill hide + escalation overlay must not move the center).
        idle_geo = ctx.get("idle_center_geo")
        rec_geo = window._center.geometry()
        check(
            idle_geo is not None and rec_geo == idle_geo,
            f"B3 idle↔recording body zero-shift (idle={idle_geo}, rec={rec_geo})",
        )
        shot(window, "04-recording")

    @at(9550, "escalation-ladder")
    def s_escalation_ladder():
        # B-6 escalation ladder: inject synthetic snapshots (FAKE demo disk is
        # always green, so real polling never reaches yellow/red) and walk
        # yellow → red → ack → green → red. ``bar.apply`` drives BOTH the banner
        # and the strip (REC chip + summary) via the wired ``applied`` signal.
        # The banner is an off-layout overlay, so the body geometry must stay
        # pinned across every state (proven vs a captured baseline).
        from mf4_analyzer.acquisition_ui.widgets.escalation_bar import (
            escalation_state,
        )

        gb = 1024 ** 3
        mb = 1024 ** 2
        bar = window._escalation_bar
        strip = window.health_strip
        rec_chip = strip.chip("REC")
        base_geo = window._center.geometry()

        def geo_pinned(tag: str) -> None:
            g = window._center.geometry()
            check(g == base_geo, f"B3 body zero-shift @{tag} (base={base_geo}, {tag}={g})")

        # yellow entry (dropped=3 + ring=68% is a known-yellow combo).
        yellow = escalation_state(
            _synth_snapshot(dropped=3, ring=68.0), disk_free_bytes=10 * gb
        )
        bar.apply(yellow)
        check(
            bar.state.level == "yellow" and not bar.isHidden(),
            f"B6 yellow banner visible ({bar.state.level})",
        )
        check(
            rec_chip.property("level") == "yellow",
            f"B6 REC chip escalates to yellow ({rec_chip.property('level')})",
        )
        check(bool(strip.summary_text()), "B6 yellow summary non-empty")
        geo_pinned("yellow")
        shot(window, "09-esc-yellow")

        # red entry — pulses the REC chip 3 loops on entry / reason change.
        red = escalation_state(_synth_snapshot(), disk_free_bytes=512 * mb)
        bar.apply(red)
        check(
            bar.state.level == "red" and not bar.isHidden(),
            f"B6 red banner visible ({bar.state.level})",
        )
        check(
            rec_chip.property("level") == "red",
            f"B6 REC chip escalates to red ({rec_chip.property('level')})",
        )
        check(
            rec_chip.pulse_animation.loopCount() == 3
            and rec_chip.pulse_animation.state()
            == rec_chip.pulse_animation.Running,
            "B6 red pulse runs 3 loops on entry",
        )
        geo_pinned("red")
        shot(window, "10-esc-red")

        # acknowledge — collapse the banner but keep the summary latched.
        bar.acknowledge()
        check(
            bar.is_collapsed and bar.isHidden(),
            "B6 ack collapses the banner",
        )
        check(bool(strip.summary_text()), "B6 ack keeps the strip summary")
        geo_pinned("ack")
        shot(window, "11-esc-ack")

        # green recovery — hide, clear the ack latch, stop pulsing.
        green = escalation_state(_synth_snapshot(), disk_free_bytes=10 * gb)
        bar.apply(green)
        check(
            bar.isHidden() and not bar.is_collapsed,
            "B6 green recovery hides the banner + clears latch",
        )
        geo_pinned("recovery")
        shot(window, "12-esc-recovery")

        # red re-arm — a fresh alarm re-shows after recovery.
        bar.apply(red)
        check(
            not bar.is_collapsed and not bar.isHidden(),
            "B6 red re-arms after recovery",
        )
        geo_pinned("re-arm")
        # Restore green so the stop/review flow is not polluted by the inject.
        bar.apply(green)

    @at(9700, "stop")
    def s_stop():
        window.main_button.click()

    @at(10500, "review-check")
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

    @at(17500, "soak-check")
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

    @at(17900, "narrow")
    def s_narrow():
        # B-4: the body is two columns now, so at the 960px window minimum
        # (a toolbar clamp) the lone-column cards stay ~490px wide — above the
        # ``_STATS_COLLAPSE_MIN_CARD_W`` compact threshold. Drive the compact
        # regime the honest way: widen the left navigator via the splitter so
        # the center (and each full-width card) drops below the threshold.
        window.resize(960, 600)
        window._splitter.setSizes([560, 400])

    @at(18900, "narrow-check")
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

    @at(19400, "collapse-panels")
    def s_collapse_panels():
        window.resize(1280, 760)
        splitter = window._splitter
        # B-4: two-column body (left navigator + center). The right health
        # pane was relocated to the top strip / bottom facts.
        splitter.setSizes([0, 960])

    @at(20200, "collapse-panels-check")
    def s_collapse_panels_check():
        splitter = window._splitter
        sizes = splitter.sizes()
        check(splitter.count() == 2, f"F13 body is two columns ({splitter.count()})")
        check(splitter.isCollapsible(0), "F13 left panel collapsible")
        check(not splitter.isCollapsible(1), "F13 center panel not collapsible")
        check(sizes[0] == 0, f"F13 left panel hidden ({sizes})")
        check(sizes[1] >= 900, f"F13 center expands after hide ({sizes})")
        shot(window, "08-panels-hidden")

    @at(20800, "finish")
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
