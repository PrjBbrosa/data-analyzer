"""Startup visual contract: one tip list, one clock rule, one resource hash."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from mf4_analyzer.app_meta import APP_VERSION
from mf4_analyzer.startup_visual_contract import (
    SLOW_AFTER_MS,
    SLOW_STATUS,
    STAGE_PREPARING,
    TIP_INTERVAL_MS,
    TIP_RECORDS,
    TIPS,
    StartupTip,
    breathe_opacity,
    choose_opening_index,
    content_hash,
    display_scale_for_work_area,
    status_label,
    tip_by_id,
    tip_index_for_elapsed,
    validate_tip_records,
    visual_payload,
)
from tools.generate_startup_launcher_resources import generate

ROOT = Path(__file__).resolve().parents[1]


def test_tip_catalog_is_frozen_at_twenty_six_ordered_ids():
    assert len(TIP_RECORDS) == 26
    assert len(TIPS) == 26
    assert [tip.tip_id for tip in TIP_RECORDS] == [f"tip-{i:02d}" for i in range(1, 27)]
    assert TIPS[0] == ("找回全局视野", "点 Home 或按 Ctrl+R，查看已绘通道的全部范围。")
    assert any("电机转速" in tip.body for tip in TIP_RECORDS)
    validate_tip_records(TIP_RECORDS)


def test_opening_index_is_chosen_once_and_elapsed_does_not_reroll():
    rng = random.Random(7)
    opening = choose_opening_index(rng.randrange)
    again = choose_opening_index(rng.randrange)
    assert opening != again or len(TIP_RECORDS) == 1
    assert tip_index_for_elapsed(opening, 0) == opening
    assert tip_index_for_elapsed(opening, 4999) == opening
    assert tip_index_for_elapsed(opening, 5000) == (opening + 1) % 26
    assert tip_index_for_elapsed(opening, 9999) == (opening + 1) % 26
    assert tip_index_for_elapsed(opening, 10000) == (opening + 2) % 26
    assert tip_index_for_elapsed(opening, 12000) == (opening + 2) % 26
    assert tip_index_for_elapsed(3, 0) == 3
    assert tip_index_for_elapsed(3, TIP_INTERVAL_MS * 26) == 3


def test_slow_status_does_not_reset_the_tip_sequence():
    assert status_label(STAGE_PREPARING, 11999) != SLOW_STATUS
    assert status_label(STAGE_PREPARING, SLOW_AFTER_MS) == SLOW_STATUS
    assert status_label(STAGE_PREPARING, 12000, slow=False) == SLOW_STATUS
    assert tip_index_for_elapsed(0, 12000) == 2
    assert status_label("loading_components", 0, slow=True) == SLOW_STATUS


def test_invalid_tip_lists_are_rejected():
    with pytest.raises(ValueError, match="empty"):
        validate_tip_records(())
    with pytest.raises(ValueError, match="duplicate"):
        validate_tip_records(
            (
                StartupTip("tip-01", "a", "b", 0),
                StartupTip("tip-01", "c", "d", 1),
            )
        )
    with pytest.raises(ValueError, match="missing"):
        validate_tip_records((StartupTip("tip-09", "title", "  ", 0),))
    with pytest.raises(ValueError, match="unknown"):
        tip_by_id("tip-99")
    with pytest.raises(ValueError, match="out of range"):
        tip_index_for_elapsed(26, 0)


def test_stage_and_scale_do_not_live_in_a_second_copy_of_the_version():
    payload = visual_payload()
    assert payload["app_version"] == APP_VERSION
    source = (ROOT / "mf4_analyzer" / "startup_visual_contract.py").read_text(encoding="utf-8")
    assert "APP_VERSION" in source
    assert 'APP_VERSION = "' not in source
    assert display_scale_for_work_area(2560, 1440) == 1.5
    assert display_scale_for_work_area(1920, 1080) == 1.0
    assert breathe_opacity(0.0, reduced_motion=True) == 1.0
    moving = breathe_opacity(0.5, reduced_motion=False)
    assert moving != breathe_opacity(0.0, reduced_motion=False)


def test_generated_resources_match_the_python_hash(tmp_path):
    manifest = generate(tmp_path)
    payload = visual_payload()
    assert manifest["content_hash"] == content_hash(payload)
    assert manifest["app_version"] == APP_VERSION
    assert manifest["tip_count"] == 26
    header = (tmp_path / "startup_resources.h").read_text(encoding="utf-8")
    assert APP_VERSION in header
    assert manifest["content_hash"] in header
    assert "tip-01" in header
    assert "tip-26" in header
    assert "--startup-splash-child" in header
    assert "Microsoft YaHei UI" in header
    saved = json.loads((tmp_path / "startup_resources.json").read_text(encoding="utf-8"))
    assert saved["content_hash"] == manifest["content_hash"]
    assert ROOT.joinpath("mf4_analyzer/startup_visual_contract.py").is_file()
