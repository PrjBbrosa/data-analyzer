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
    # coaxis.gesture (tier A) shipped 2026-06-27 and trails the tier-S drag_y.
    assert [hint.id for hint in hints.context_hints(overlay)] == [
        "overlay.drag_y",
        "coaxis.gesture",
    ]

    subplot = HintState(mode="time", plot_mode="subplot")
    # coaxis applies to subplot too (shared Y = compare amplitude); the tier-A
    # gesture trails the subplot wheel/shift-Y tips.
    assert [hint.id for hint in hints.context_hints(subplot)] == [
        "subplot.wheel_target",
        "subplot.shift_y",
        "coaxis.gesture",
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
        "coaxis.gesture",
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


def test_batch_export_options_discovery_states_slice_and_folder_limits():
    batch_hint = next(
        hint for hint in hints.all_hints() if hint.id == "batch.export_options"
    )
    assert "≤4" in batch_hint.text
    assert "FFT-时间" in batch_hint.text and "阶次" in batch_hint.text
    assert "完成后" in batch_hint.text and "目录" in batch_hint.text
    assert "记住" in batch_hint.text

    seen = frozenset(
        hint.id for hint in hints.all_hints()
        if hint.surface == "discovery"
        and hint.ship == "now"
        and hint.id != batch_hint.id
    )
    assert hints.discovery_hint(HintState(discovered=seen)) == batch_hint


def test_frf_hints_cover_cursor_display_and_time_domain_limits():
    frf_hints = {
        hint.id: hint.text
        for hint in hints.all_hints()
        if hint.id.startswith("frf.")
    }
    assert set(frf_hints) == {
        "frf.linked_cursor",
        "frf.coherence_display_only",
        "frf.custom_x_limit",
        "frf.view_in_time_domain",
    }
    joined = " ".join(frf_hints.values())
    for phrase in (
        "工具栏", "游标", "三图", "读数", "阈值", "显示", "自定义 X", "不是秒",
        "时域查看", "新建或复用",
    ):
        assert phrase in joined

    fft_hints = {hint.id: hint.text for hint in hints.all_hints() if hint.id.startswith("fft.")}
    assert fft_hints["fft.frequency_cursor"] == "频谱工具栏：关/单/双游标，双游标读 Δf"


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


def test_wwt_export_storage_is_a_shipped_discovery_hint():
    hint = next(
        h for h in hints.all_hints() if h.id == "channel.export_wwt_storage"
    )
    assert hint.surface == "discovery"
    assert hint.ship == "now"
    assert "WWT" in hint.text
    assert "无损" in hint.text and "紧凑" in hint.text
    assert hints.hint_display_width(hint.text) <= hints.HINT_MAX_WIDTH


def test_custom_action_slot_discovery_surfaces_and_retires():
    # After the higher-priority discoveries are seen, the custom-action-slot
    # tip surfaces; rebinding (marking the id) retires it.
    seen = {
        "toolbar.shortcuts_exist",
        "chart.copy_image",
        "chart.right_click_menu",
        "channel.right_click",
        "file.scope_follow",
        # 58030e4d: landed WWT lossless/compact export; same default-mode
        # discovery pool as custom_action_slot (priority 70 > 50).
        "channel.export_wwt_storage",
        "view.history",
    }
    state = HintState(discovered=frozenset(seen))
    assert hints.discovery_hint(state).id == "chart.custom_action_slot"
    after = HintState(discovered=frozenset(seen | {"chart.custom_action_slot"}))
    nxt = hints.discovery_hint(after)
    assert nxt is None or nxt.id != "chart.custom_action_slot"


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


def test_fft_preview_hints_match_overlay_wheel_contract():
    by_id = {h.id: h for h in hints.all_hints()}
    for hid in (
        "fft.preview_wheel",
        "fft.preview_axis_gutter",
        "fft.preview_left_axis",
        "fft.preview_dblclick",
        "fft.time_range_manual",
    ):
        assert hid in by_id, hid
        assert by_id[hid].modes == frozenset({"fft"})
    wheel = by_id["fft.preview_wheel"].text
    assert "平滚轮平移" in wheel
    assert "Shift" in wheel and "Ctrl" in wheel
    assert "平移 Y" in hints.flash_tip("fft.preview_source")
    manual = by_id["fft.time_range_manual"].text
    assert "预览" in manual and "起止" in manual
    assert "勾选" in manual and "计算" in manual
    confirm = by_id["analysis.time_range_confirm"]
    assert confirm.modes == frozenset({"fft", "fft_time", "order", "frf"})
    assert "局部" in confirm.text and "询问" in confirm.text
    assert "勾选" in confirm.text


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


def test_coaxis_hints_shipped_and_surface_in_overlay_and_subplot():
    # 共轴组 (shared-axis groups) shipped 2026-06-27 (designed in the overlay
    # shared-axis spec, landed + user-verified on-device). Both hints flip
    # ship="now" and apply to overlay AND subplot (shared Y = compare amplitude).
    coaxis = {h.id: h for h in hints.all_hints() if h.id.startswith("coaxis.")}
    assert {"coaxis.merge", "coaxis.gesture"} <= set(coaxis)
    assert all(h.ship == "now" for h in coaxis.values())
    assert all(
        h.plot_modes == frozenset({"overlay", "subplot"})
        for h in coaxis.values()
    )

    for plot_mode in ("overlay", "subplot"):
        state = HintState(mode="time", plot_mode=plot_mode)
        # coaxis.merge now appears in the discovery queue (walk until exhausted).
        seen, walked = set(), state
        while (h := hints.discovery_hint(walked)) is not None and h.id not in seen:
            seen.add(h.id)
            walked = HintState(
                mode="time", plot_mode=plot_mode, discovered=frozenset(seen)
            )
        assert "coaxis.merge" in seen, plot_mode
        # coaxis.gesture now surfaces as a context + rotation tip.
        assert "coaxis.gesture" in {h.id for h in hints.context_hints(state)}
        assert "coaxis.gesture" in {h.id for h in hints.rotation_hints(state)}


class _MultiChannelStub:
    """Minimal FileData stand-in: two signal channels so the right-click menu
    can offer 合并为共轴 (needs >=2 selected)."""

    data = [1, 2, 3]

    def get_signal_channels(self):
        return ["speed", "torque"]

    def get_color_palette(self):
        return ["#1769e0", "#f43f5e"]


def test_axis_group_menu_open_retires_coaxis_merge_discovery(qapp, qtbot, monkeypatch):
    # Released coaxis.merge is surface="discovery" + retire_on="axis_group_menu",
    # but nothing fired the retire event. Opening the channel-tree context menu
    # with >=2 channels selected (the 合并为共轴 item present) must call
    # mark_discovered("coaxis.merge") so the footer stops rotating it. Without
    # this wiring the released hint rotates forever.
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget

    recorded = []
    monkeypatch.setattr(
        "mf4_analyzer.ui.widgets.hints.mark_discovered",
        lambda _settings, hint_id: recorded.append(hint_id),
    )
    # The menu is modal/blocking; stub exec_ so the test does not hang.
    monkeypatch.setattr(
        "mf4_analyzer.ui.widgets.QMenu.exec_",
        lambda _menu, *a, **k: None,
    )

    widget = MultiFileChannelWidget()
    qtbot.addWidget(widget)
    widget.resize(320, 240)
    widget.show()
    qtbot.waitExposed(widget)
    widget.add_file("file-a", _MultiChannelStub())
    # Unattached rows are filtered out of the tree, so visualItemRect would be
    # empty and the right-click would land on no item at all.
    widget.set_attached_file_ids(["file-a"])
    widget.tree.expandAll()
    QCoreApplication.processEvents()

    file_item = widget._file_items["file-a"]
    first, second = file_item.child(0), file_item.child(1)
    widget.tree.scrollToItem(first)
    QCoreApplication.processEvents()
    first.setSelected(True)
    second.setSelected(True)

    pos = widget.tree.visualItemRect(first).center()
    assert widget.tree.itemAt(pos) is first  # menu opens on a channel row
    widget._on_context_menu(pos)
    assert "coaxis.merge" in recorded  # 合并为共轴 present → discovery retired

    # Single-channel right-click (no 合并为共轴 item) must NOT retire it early.
    recorded.clear()
    widget.tree.clearSelection()
    solo_pos = widget.tree.visualItemRect(second).center()
    widget._on_context_menu(solo_pos)
    assert "coaxis.merge" not in recorded


def test_analysis_view_scope_surfaces_on_every_analysis_section():
    """The View-scoped signal pickers need an explanation on all three pages.

    The pickers offer only the active analysis View's attached files. When a
    wanted channel is absent there is no error and no gesture to discover —
    the list is simply short — so the footer carries the rule on the sections
    where the pickers live, and nowhere else.
    """
    scope = next(h for h in hints.all_hints() if h.id == "analysis.view_scope")
    assert "分析 View" in scope.text
    assert "×" in scope.text
    for mode in ("fft", "fft_time", "order", "frf"):
        ids = [hint.id for hint in hints.context_hints(HintState(mode=mode))]
        assert "analysis.view_scope" in ids, mode

    time_ids = [
        hint.id
        for hint in hints.context_hints(
            HintState(mode="time", plot_mode="overlay")
        )
    ]
    assert "analysis.view_scope" not in time_ids, (
        "time domain picks channels in the tree, not through the signal picker"
    )


def test_analysis_view_scope_trails_the_section_headline_gesture():
    """Scope explanation must not displace a section's primary gesture."""
    ids = [
        hint.id
        for hint in hints.context_hints(
            HintState(mode="order", chart_kind="order")
        )
    ]
    assert ids.index("order.slice") < ids.index("analysis.view_scope")


def test_ultraview_hints_cover_add_menu_escape_presentation_and_export():
    by_id = {hint.id: hint for hint in hints.all_hints() if hint.id.startswith("ultraview.")}
    required = {
        "ultraview.view_rail",
        "ultraview.add_from_tab",
        "ultraview.card_menu",
        "ultraview.sync",
        "ultraview.sync_all",
        "ultraview.escape",
        "ultraview.presentation",
        "ultraview.export",
        "ultraview.tray",
        "ultraview.statuses",
        "ultraview.readonly",
        "ultraview.empty_board",
        "ultraview.direct_manip",
        "ultraview.display",
        "ultraview.idle",
        "ultraview.filter",
        "ultraview.library_fold",
        "ultraview.library_pin",
        "ultraview.library_toggle",
        "ultraview.free_grid",
        "ultraview.resize",
        "ultraview.avoid",
        "ultraview.replace_ring",
        "ultraview.undo",
        "ultraview.preset",
        "ultraview.minimap",
        "ultraview.zoom",
        "ultraview.autofit",
        "ultraview.inspect",
        "ultraview.lod",
        "ultraview.boards",
        "ultraview.limits",
        "ultraview.pan",
        "ultraview.remove",
    }
    assert required <= set(by_id)
    source_modes = frozenset({"time", "fft", "fft_time", "frf", "order"})
    rail_hint = by_id["ultraview.view_rail"]
    assert rail_hint.surface == "discovery"
    assert rail_hint.modes == source_modes
    assert rail_hint.text == "View 栏右侧 UltraView 可打开只读总览"
    add_hint = by_id["ultraview.add_from_tab"]
    assert add_hint.surface == "discovery"
    assert add_hint.modes == source_modes
    assert "加入总览" in add_hint.text
    uv_state = HintState(mode="ultraview")
    uv_ids = {hint.id for hint in hints.context_hints(uv_state)}
    assert {
        "ultraview.card_menu",
        "ultraview.sync",
        "ultraview.sync_all",
        "ultraview.escape",
        "ultraview.presentation",
        "ultraview.export",
        "ultraview.tray",
        "ultraview.statuses",
        "ultraview.readonly",
        "ultraview.empty_board",
        "ultraview.display",
        "ultraview.idle",
        "ultraview.filter",
        "ultraview.library_fold",
        "ultraview.library_pin",
        "ultraview.library_toggle",
    } <= uv_ids
    time_ids = {hint.id for hint in hints.context_hints(HintState(mode="time", plot_mode="overlay"))}
    assert not any(hid.startswith("ultraview.") for hid in time_ids)
    for mode in ("time", "fft", "fft_time", "frf", "order"):
        state = HintState(mode=mode, plot_mode="overlay" if mode == "time" else "")
        seen = set()
        walked = state
        found_rail = False
        while (hint := hints.discovery_hint(walked)) is not None and hint.id not in seen:
            if hint.id == "ultraview.view_rail":
                found_rail = True
                break
            seen.add(hint.id)
            walked = HintState(
                mode=mode,
                plot_mode=state.plot_mode,
                discovered=frozenset(seen),
            )
        assert found_rail, mode
    haystack = " ".join(hint.text for hint in by_id.values())
    for banned in (
        "PDF", "SVG", "sidecar", "live card", "后台补图", "实时", "直播", "Alt+拖",
        "逻辑画布固定", "默认适应视口", "铺满视口", "12 列受控",
    ):
        assert banned not in haystack
    assert "标尺" in by_id["ultraview.limits"].text
    assert "24" in by_id["ultraview.limits"].text
    assert "200" in by_id["ultraview.limits"].text
    assert "切板" in by_id["ultraview.zoom"].text
    assert "适应" in by_id["ultraview.zoom"].text
    assert "300%" in by_id["ultraview.zoom"].text
    assert "100%" in by_id["ultraview.zoom"].text
    assert "300%" in by_id["ultraview.inspect"].text
    assert "Esc" in by_id["ultraview.inspect"].text
    assert "四向" in by_id["ultraview.pan"].text
    assert "不删" in by_id["ultraview.remove"].text
    assert "Ctrl/Cmd+Z" in by_id["ultraview.undo"].text
    display_hint = by_id["ultraview.display"].text
    assert "工程" in display_hint
    assert "保存" in display_hint
