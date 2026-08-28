"""Accept/Reject/restore/cap contracts for WinWert layout import."""
from __future__ import annotations

from pathlib import Path

import pytest

from mf4_analyzer.ui.main_window.wwt_import_coordinator import (
    ACCEPT_TEXT,
    REJECT_TEXT,
    layout_dialog_text,
)
from mf4_analyzer.ui.view_state import MAX_VIEWS, ViewManager, ViewState, is_reusable_blank_view

UCAN = Path(__file__).resolve().parents[2] / "testdoc" / "WWT" / "UCAN-b6_P779_0007.wwt"


def test_layout_dialog_text_matches_ucan_copy():
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(UCAN)
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    body, informative = layout_dialog_text(
        loaded.document, proposals, available=MAX_VIEWS
    )
    assert "检测到 7 个 WinWert 数据窗口和 4 个可用计算通道。" in body
    assert "可按原排版生成 7 个时域 View，并同步加入 UltraView。" in body
    assert "第 7 个窗口与第 6 个位置重叠，将放入 UltraView 未放置区。" in body
    assert informative == ""
    capped, info = layout_dialog_text(
        loaded.document, proposals, available=3
    )
    assert "可按原排版生成 3 个时域 View" in capped
    assert info == "检测到 7 个，可创建 3 个"


def test_insert_states_reuses_blank_and_emits_once():
    manager = ViewManager()
    emissions = []
    manager.views_changed.connect(lambda: emissions.append("views"))
    manager.active_changed.connect(lambda idx: emissions.append(("active", idx)))
    first = ViewState(name="WinWert 1", tab_color="#2d7ff9")
    rest = [
        ViewState(name=f"WinWert {i}", tab_color="#2d7ff9")
        for i in range(2, 8)
    ]
    assert is_reusable_blank_view(manager.get(0))
    indexes = manager.insert_states([first, *rest], reuse_blank=True)
    assert indexes == list(range(7))
    assert manager.views[0] is first
    assert len(manager.views) == 7
    assert emissions.count("views") == 1


def test_non_empty_view_is_not_reused():
    manager = ViewManager()
    manager.views[0].checked = [("f1", "x")]
    incoming = [ViewState(name="WinWert 1", tab_color="#2d7ff9")]
    reuse = is_reusable_blank_view(manager.views[0])
    assert reuse is False
    indexes = manager.insert_states(incoming, reuse_blank=reuse)
    assert indexes == [1]
    assert manager.views[0].checked == [("f1", "x")]
    assert manager.views[1].name == "WinWert 1"


def test_accept_creates_seven_views_and_reject_keeps_data_only(qapp, tmp_path, monkeypatch):
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow

    if not UCAN.is_file():
        pytest.fail(f"required sample missing: {UCAN}")

    mw = MainWindow()
    mw.show()
    qapp.processEvents()
    asked = []

    def fake_ask(body, informative=""):
        asked.append((body, informative))
        return True

    monkeypatch.setattr(mw._wwt_import, "_ask_layout", fake_ask)
    monkeypatch.setattr(
        mw._ultraview, "add_time_views_from_native_layout", lambda items: ()
    )
    plots = []
    monkeypatch.setattr(mw, "plot_time", lambda *a, **k: plots.append("plot"))
    monkeypatch.setattr(mw, "_apply_active_view", lambda *a, **k: plots.append("apply"))
    mw._load_one(str(UCAN))
    qapp.processEvents()
    assert asked
    assert "检测到 7 个 WinWert 数据窗口和 4 个可用计算通道。" in asked[0][0]
    assert len(mw.view_manager.views) == 7
    assert mw.files
    derived = any(
        "Spurstangenkraft" in fd.data.columns
        for fd in mw.files.values()
    )
    assert derived
    assert mw.view_manager.active == 0
    assert mw.view_manager.views[0].name.startswith("WinWert 1")

    mw2 = MainWindow()
    mw2.show()
    qapp.processEvents()
    monkeypatch.setattr(mw2._wwt_import, "_ask_layout", lambda *a, **k: False)
    monkeypatch.setattr(
        mw2._ultraview, "add_time_views_from_native_layout", lambda items: ()
    )
    before_views = len(mw2.view_manager.views)
    mw2._load_one(str(UCAN))
    qapp.processEvents()
    assert len(mw2.view_manager.views) == before_views
    assert mw2.files
    assert any(
        "Spurstangenkraft" in fd.data.columns
        for fd in mw2.files.values()
    )


def test_project_restore_does_not_prompt(qapp, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    asked = []
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *a, **k: asked.append(True) or True)
    mw._restoring_project = True
    from mf4_analyzer.io.wwt_document import load_wwt_document
    loaded = load_wwt_document(UCAN)
    mw._wwt_import.offer_layout(loaded.document, [])
    assert asked == []


def test_cap_truncates_with_visible_copy():
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(UCAN)
    proposals = build_wwt_view_proposals(
        loaded.document, register_groups_for_test(loaded.groups)
    )
    _body, info = layout_dialog_text(loaded.document, proposals, available=3)
    assert info == "检测到 7 个，可创建 3 个"
    assert ACCEPT_TEXT == "按 WinWert 排版并绘图"
    assert REJECT_TEXT == "仅加载数据"
