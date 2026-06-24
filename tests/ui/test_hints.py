import re
from pathlib import Path

from PyQt5.QtCore import QSettings

from mf4_analyzer.ui import hints
from mf4_analyzer.ui.hints import HintState


def test_persistent_hints_are_curated_universal_set():
    assert hints.persistent_hints() == (
        "Ctrl + 滚轮 缩放 X",
        "Shift + 滚轮 缩放 Y",
    )


def test_hint_display_width_counts_full_width_glyphs_only():
    # CJK ideographs and full-width punctuation count 1; narrow ASCII/Latin
    # glyphs (letters, digits, spaces, "·", "→") count 0.
    assert hints.hint_display_width("缩放") == 2
    assert hints.hint_display_width("Ctrl + 滚轮 缩放 X / Y") == 4
    assert hints.hint_display_width("右键图表 → 查看全部 · 轴范围 · 网格") == 13
    assert hints.hint_display_width("，（）") == 3  # full-width punctuation counts


def test_every_registry_hint_stays_within_length_budget():
    # The footer's two edge-anchored slots only fit side by side when each hint
    # is short; this guards the cap at definition time so new hints stay in
    # budget instead of eliding on a normal-width bar.
    too_long = [
        (hint.id, hints.hint_display_width(hint.text), hint.text)
        for hint in hints.all_hints()
        if hints.hint_display_width(hint.text) > hints.HINT_MAX_WIDTH
    ]
    assert not too_long, too_long


def test_context_hints_filter_by_mode_and_tier_priority():
    overlay = HintState(mode="time", plot_mode="overlay")
    assert [hint.id for hint in hints.context_hints(overlay)] == [
        "overlay.drag_y",
    ]

    subplot = HintState(mode="time", plot_mode="subplot")
    assert [hint.id for hint in hints.context_hints(subplot)] == [
        "subplot.wheel_target",
        "subplot.shift_y",
    ]

    dual = HintState(mode="time", plot_mode="overlay", cursor_mode="dual")
    assert [hint.id for hint in hints.context_hints(dual)][0] == "cursor.dual_ab"


def test_context_hints_filter_special_chart_modes_and_requirements():
    # FFT-vs-Time keeps the slice hint as its lead context hint; the redesign
    # adds spectrogram colorbar/divider tips that also surface on this section.
    fft_time = HintState(mode="fft_time", chart_kind="fft_time")
    fft_time_ids = [hint.id for hint in hints.context_hints(fft_time)]
    assert fft_time_ids[0] == "spectrogram.slice"
    assert "spectrogram.colorbar_scale" in fft_time_ids
    assert "spectrogram.divider" in fft_time_ids

    order_without_annotation = HintState(mode="order", chart_kind="order")
    assert "annotation.mode" not in {
        hint.id for hint in hints.context_hints(order_without_annotation)
    }

    order_with_annotation = HintState(
        mode="order",
        chart_kind="order",
        annotation_on=True,
    )
    # Annotation mode surfaces the add/delete hint; the redesign keeps it as the
    # lead while also offering the order slice + spectrogram tips on this section.
    order_annot_ids = [
        hint.id for hint in hints.context_hints(order_with_annotation)
    ]
    assert order_annot_ids[0] == "annotation.mode"
    assert "order.slice" in order_annot_ids


def test_context_hints_suppress_recently_used_ids():
    state = HintState(
        mode="time",
        plot_mode="subplot",
        recently_used=frozenset({"subplot.wheel_target"}),
    )
    assert [hint.id for hint in hints.context_hints(state)] == [
        "subplot.shift_y",
    ]


def test_discovery_hint_returns_priority_order_and_skips_discovered():
    fresh = HintState()
    assert hints.discovery_hint(fresh).id == "toolbar.shortcuts_exist"

    after_shortcut = HintState(
        discovered=frozenset({"toolbar.shortcuts_exist"})
    )
    assert hints.discovery_hint(after_shortcut).id == "chart.copy_image"

    all_now = HintState(
        discovered=frozenset(
            hint.id
            for hint in hints.all_hints()
            if hint.surface == "discovery" and hint.ship == "now"
        )
    )
    assert hints.discovery_hint(all_now) is None


def test_mark_discovered_round_trips_through_qsettings():
    temp_dir = Path(".pytmp") / "test_hints"
    temp_dir.mkdir(parents=True, exist_ok=True)
    settings_path = temp_dir / "hint-settings.ini"
    if settings_path.exists():
        settings_path.unlink()
    settings = QSettings(str(settings_path), QSettings.IniFormat)

    assert hints.load_discovered(settings) == frozenset()
    hints.mark_discovered(settings, "toolbar.shortcuts_exist")
    hints.mark_discovered(settings, "chart.copy_image")
    settings.sync()

    reloaded = QSettings(str(settings_path), QSettings.IniFormat)
    assert hints.load_discovered(reloaded) == frozenset(
        {"toolbar.shortcuts_exist", "chart.copy_image"}
    )
    state = HintState(discovered=hints.load_discovered(reloaded))
    assert hints.discovery_hint(state).id == "chart.right_click_menu"


def test_shortcut_tooltip_returns_exact_registered_key():
    assert hints.shortcut_tooltip("pan") == "Ctrl+G"
    assert hints.shortcut_tooltip("btn_overlay") == "Ctrl+2"
    assert hints.shortcut_tooltip("missing") is None


def test_hint_scope_defaults_to_chart():
    assert all(
        hint.scope == "chart"
        for hint in hints.all_hints()
        if hint.id != "markup.capabilities"
    )


def test_markup_capabilities_is_markup_scoped_ship_now_discovery():
    hint = next(h for h in hints.all_hints() if h.id == "markup.capabilities")
    assert hint.scope == "markup"
    assert hint.surface == "discovery"
    assert hint.ship == "now"
    assert "箭头移动标注" in hint.text
    assert "双击编辑文本" in hint.text


def test_chart_discovery_queue_excludes_markup_scope():
    state = HintState()
    ids = []
    while (hint := hints.discovery_hint(state)) is not None:
        ids.append(hint.id)
        state = HintState(discovered=state.discovered | {hint.id})
    assert "markup.capabilities" not in ids


def test_markup_scope_discovery_returns_then_retires_capabilities():
    fresh = HintState()
    assert hints.discovery_hint(fresh, scope="markup").id == "markup.capabilities"
    retired = HintState(discovered=frozenset({"markup.capabilities"}))
    assert hints.discovery_hint(retired, scope="markup") is None


def test_legacy_hints_dwell_defaults_derive_from_priority():
    # No legacy hint sets dwell_ms/weight explicitly, so they must fall back to
    # the priority-derived defaults (behavior-preserving for the original 15).
    for hint in hints.all_hints():
        if hint.id.startswith("anchor."):
            continue  # anchors deliberately set explicit dwell/weight
        if hint.dwell_ms is None:
            expected = 4000 + max(0, hint.priority) * 80
            expected = max(3500, min(13000, expected))
            assert hint.effective_dwell_ms() == expected
        if hint.weight is None:
            assert hint.base_weight() == hint.priority


def test_rotation_pool_anchor_leads_each_section():
    # Line sections (time/fft) lead with the Ctrl/Shift wheel anchor; heatmap
    # sections (fft_time/order) lead with the slice/colorbar anchor.
    for mode, chart_kind, plot_mode, lead in [
        ("time", "time", "subplot", "anchor.line_wheel"),
        ("fft", "fft", "", "anchor.line_wheel"),
        ("fft_time", "fft_time", "", "anchor.heatmap_gesture"),
        ("order", "order", "", "anchor.heatmap_gesture"),
    ]:
        state = HintState(mode=mode, chart_kind=chart_kind, plot_mode=plot_mode)
        rot = hints.rotation_hints(state)
        assert rot, f"empty rotation pool for {mode}"
        assert rot[0].id == lead, (mode, [h.id for h in rot])
        # Anchor lingers longest in the lap.
        assert hints.rotation_dwell_ms(rot[0]) >= max(
            hints.rotation_dwell_ms(h) for h in rot
        )


def test_rotation_pool_section_gating_keeps_tips_off_other_pages():
    time_ids = {h.id for h in hints.rotation_hints(
        HintState(mode="time", chart_kind="time", plot_mode="subplot")
    )}
    assert "order.slice" not in time_ids
    assert "spectrogram.colorbar_scale" not in time_ids
    assert "fft.preview_pick_source" not in time_ids


def test_rotation_used_tip_drops_but_anchor_only_demotes():
    used = HintState(
        mode="order", chart_kind="order",
        recently_used=frozenset({"order.slice", "anchor.heatmap_gesture"}),
    )
    ids = [h.id for h in hints.rotation_hints(used)]
    assert "order.slice" not in ids  # used tip leaves the lap
    assert "anchor.heatmap_gesture" in ids  # base gesture stays reachable


def test_rotation_discovered_echo_retires_tip_across_sessions():
    disc = HintState(
        mode="order", chart_kind="order",
        discovered=frozenset({"spectrogram.colorbar"}),
    )
    ids = [h.id for h in hints.rotation_hints(disc)]
    assert "spectrogram.colorbar_scale" not in ids


def test_flash_tip_registry_has_section_gestures():
    assert hints.flash_tip("preset.right_click")
    assert hints.flash_tip("spectrogram.slice_pick")
    assert hints.flash_tip("fft.preview_source")
    assert hints.flash_tip("missing.id") is None


def test_design_curated_ids_exist_in_registry():
    spec = (
        "docs/superpowers/specs/2026-06-01-chart-hint-system-design.md"
    )
    text = open(spec, encoding="utf-8").read()
    curated_sections = re.findall(
        r"### (?:Persistent|Discovery|Rotating context — Tier S|Rotating context — Tier A)"
        r"(.*?)(?=\n### |\n## )",
        text,
        flags=re.S,
    )
    table_lines = "\n".join(
        line
        for section in curated_sections
        for line in section.splitlines()
        if line.startswith("|")
    )
    spec_ids = {
        match
        for match in re.findall(r"`([a-z0-9_.]+)`", table_lines)
    }
    registry_ids = {hint.id for hint in hints.all_hints()}
    assert spec_ids <= registry_ids


def test_zoom_guard_describes_all_channel_box_zoom():
    # c87de0fb: overlay box-zoom now scales X and Y for ALL channels (no
    # selection needed), retiring the stale "拖框优先于选择曲线" guard framing.
    hint = next(h for h in hints.all_hints() if h.id == "zoom.guard")
    assert "优先" not in hint.text  # old "拖框优先于选择曲线" framing is gone
    assert "通道" in hint.text       # now describes the all-channels Y behavior


def test_coaxis_hints_staged_ship_later_and_hidden_on_every_surface():
    # 共轴组 (overlay shared-axis) is designed but not yet built; its hints are
    # pre-staged with ship="later" so they are registered (tracked) yet surface
    # NOWHERE — not just absent from the discovery queue — until the flag flips.
    coaxis = {h.id: h for h in hints.all_hints() if h.id.startswith("coaxis.")}
    assert {"coaxis.merge", "coaxis.gesture"} <= set(coaxis)
    assert all(h.ship == "later" for h in coaxis.values())

    overlay = HintState(mode="time", plot_mode="overlay")
    # discovery queue (exhausted) never offers a ship="later" hint
    seen, state = set(), overlay
    while (h := hints.discovery_hint(state)) is not None and h.id not in seen:
        seen.add(h.id)
        state = HintState(
            mode="time", plot_mode="overlay", discovered=frozenset(seen)
        )
    assert "coaxis.merge" not in seen
    # context + rotation must hide ship="later" too (the gap this guards)
    assert "coaxis.gesture" not in {h.id for h in hints.context_hints(overlay)}
    assert "coaxis.gesture" not in {h.id for h in hints.rotation_hints(overlay)}
