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
    fft_time = HintState(mode="fft_time", chart_kind="fft_time")
    assert [hint.id for hint in hints.context_hints(fft_time)] == [
        "spectrogram.slice",
    ]

    order_without_annotation = HintState(mode="order", chart_kind="order")
    assert "annotation.mode" not in {
        hint.id for hint in hints.context_hints(order_without_annotation)
    }

    order_with_annotation = HintState(
        mode="order",
        chart_kind="order",
        annotation_on=True,
    )
    assert [hint.id for hint in hints.context_hints(order_with_annotation)] == [
        "annotation.mode",
    ]


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
    assert "箭头键" in hint.text
    assert "双击文本" in hint.text


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
