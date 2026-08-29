"""Accept/Reject/restore/cap contracts for WinWert layout import."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.ui.main_window.wwt_import_coordinator import (
    ACCEPT_TEXT,
    REJECT_TEXT,
    WwtImportOutcome,
    format_wwt_placement_summary,
    layout_dialog_text,
)
from mf4_analyzer.ui.view_state import MAX_VIEWS, ViewManager, ViewState, is_reusable_blank_view
from tests._helpers import wwt_factory as wwt

_ROOT = Path(__file__).resolve().parents[2]


def _stub_wwt_ui(mw, monkeypatch, accept=True, *, projected=None):
    asked = []

    def fake_ask(body, informative=""):
        asked.append((body, informative))
        return accept

    monkeypatch.setattr(mw._wwt_import, "_ask_layout", fake_ask)
    if projected is None:
        monkeypatch.setattr(
            mw._ultraview,
            "add_time_views_from_native_layout",
            lambda items, **_kwargs: (),
        )
    else:
        real = mw._ultraview.add_time_views_from_native_layout

        def _capture(items, **kwargs):
            projected.append(tuple(
                (str(view_id), rect) for view_id, rect in items
            ))
            return real(items, **kwargs)

        monkeypatch.setattr(
            mw._ultraview, "add_time_views_from_native_layout", _capture
        )
    monkeypatch.setattr(mw, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(mw, "_apply_active_view", lambda *a, **k: None)
    return asked


def _store_of(fd):
    return (getattr(fd, "source_metadata", None) or {}).get("wwt_record_store")


def _array_sig(values):
    array = np.ascontiguousarray(np.asarray(values, dtype=np.float64))
    return (
        int(array.shape[0]),
        hashlib.sha1(array.tobytes()).hexdigest(),
    )


def _assert_store_on_every_file(mw):
    stores = [_store_of(fd) for fd in mw.files.values()]
    assert stores and all(store is not None for store in stores)
    first = stores[0]
    assert all(store is first for store in stores)
    return first


def test_layout_dialog_text_matches_multi_window_copy(tmp_path):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(
        wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    )
    registered = register_groups_for_test(loaded.groups, owner_fid="f1")
    proposals = build_wwt_view_proposals(loaded.document, registered)
    body, informative = layout_dialog_text(
        loaded.document, proposals, available=MAX_VIEWS
    )
    visible_y_windows = sum(
        1
        for window in loaded.document.windows
        if any(row.visible for row in window.curves[1:])
    )
    assert visible_y_windows == wwt.MULTI_WINDOW_COUNT
    assert (
        f"检测到 {wwt.MULTI_WINDOW_COUNT} 个 WinWert 数据窗口和 "
        f"{wwt.MULTI_FORMULA_COUNT} 个可用计算通道。"
    ) in body
    assert (
        f"可按原排版生成 {wwt.MULTI_WINDOW_COUNT} 个时域 View，并同步到独立 Board。"
    ) in body
    assert "仅生成时域 View" not in body
    assert "同步加入 UltraView" not in body
    assert "重叠" in body
    assert "第 3 个窗口与第 2 个" in body
    assert informative == ""
    capped, info = layout_dialog_text(
        loaded.document, proposals, available=1
    )
    assert "可按原排版生成 1 个时域 View，仅生成时域 View。" in capped
    assert "同步到独立 Board" not in capped
    assert "同步加入 UltraView" not in capped
    assert info == f"检测到 {wwt.MULTI_WINDOW_COUNT} 个，可创建 1 个"


def test_layout_dialog_text_single_window_does_not_promise_ultraview(tmp_path):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(
        wwt.channel_xy_with_auxiliaries(tmp_path / "one.wwt")
    )
    proposals = build_wwt_view_proposals(
        loaded.document, register_groups_for_test(loaded.groups, owner_fid="f1")
    )
    body, informative = layout_dialog_text(
        loaded.document, proposals, available=MAX_VIEWS
    )
    assert "仅生成时域 View" in body
    assert "同步加入 UltraView" not in body
    assert "同步到独立 Board" not in body
    assert informative == ""


def test_layout_dialog_text_counts_visible_y_windows_not_kept_proposals(tmp_path):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(
        wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    )
    proposals = build_wwt_view_proposals(
        loaded.document, register_groups_for_test(loaded.groups, owner_fid="f1")
    )
    body, _info = layout_dialog_text(
        loaded.document, proposals[:1], available=MAX_VIEWS
    )
    assert f"检测到 {wwt.MULTI_WINDOW_COUNT} 个 WinWert 数据窗口" in body


def test_insert_states_reuses_blank_and_emits_once():
    manager = ViewManager()
    emissions = []
    manager.views_changed.connect(lambda: emissions.append("views"))
    manager.active_changed.connect(lambda idx: emissions.append(("active", idx)))
    first = ViewState(name="WinWert 1", tab_color="#2d7ff9")
    rest = [
        ViewState(name=f"WinWert {i}", tab_color="#2d7ff9")
        for i in range(2, 4)
    ]
    assert is_reusable_blank_view(manager.get(0))
    indexes = manager.insert_states([first, *rest], reuse_blank=True)
    assert indexes == list(range(3))
    assert manager.views[0] is first
    assert len(manager.views) == 3
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


def test_accept_creates_views_and_reject_keeps_data_only(qapp, tmp_path, monkeypatch):
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.time_xaxis import CHANNEL_MODE, EXACT_SOURCE, CustomXAxisSpec

    path = wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    mw = MainWindow()
    mw.show()
    qapp.processEvents()
    apply_active_view = mw._apply_active_view
    asked = _stub_wwt_ui(mw, monkeypatch, accept=True)
    mw._load_one(str(path))
    qapp.processEvents()
    assert asked
    assert (
        f"检测到 {wwt.MULTI_WINDOW_COUNT} 个 WinWert 数据窗口和 "
        f"{wwt.MULTI_FORMULA_COUNT} 个可用计算通道。"
    ) in asked[0][0]
    assert len(mw.view_manager.views) == wwt.MULTI_WINDOW_COUNT
    assert mw.files
    derived = any(wwt.FORM_Y in fd.data.columns for fd in mw.files.values())
    assert derived
    assert mw.view_manager.active == 0
    assert mw.view_manager.views[0].name.startswith("WinWert 1")
    active = mw.view_manager.views[0]
    expected_y_keys = {
        json.dumps(
            [fid, mw.files[fid].get_prefixed_channel(channel)],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for fid, channel in active.checked
    }
    assert set(active.ylims) == expected_y_keys
    x_axis = CustomXAxisSpec.from_axis_opts(
        active.axis_opts["x_axis"]
    )
    assert x_axis.mode == CHANNEL_MODE
    assert x_axis.resolver == EXACT_SOURCE
    assert x_axis.channel == wwt.CHAN_X
    apply_active_view(mw.view_manager.active)
    assert mw._custom_xaxis_spec == x_axis

    mw2 = MainWindow()
    mw2.show()
    qapp.processEvents()
    _stub_wwt_ui(mw2, monkeypatch, accept=False)
    before_views = len(mw2.view_manager.views)
    mw2._load_one(str(path))
    qapp.processEvents()
    assert len(mw2.view_manager.views) == before_views
    assert mw2.files
    assert any(wwt.FORM_Y in fd.data.columns for fd in mw2.files.values())
    _assert_store_on_every_file(mw)
    _assert_store_on_every_file(mw2)


def test_project_restore_does_not_prompt(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.main_window import MainWindow

    path = wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    mw = MainWindow()
    asked = []
    monkeypatch.setattr(
        mw._wwt_import, "_ask_layout", lambda *a, **k: asked.append(True) or True
    )
    mw._restoring_project = True
    loaded = load_wwt_document(path)
    mw._wwt_import.offer_layout(loaded.document, [])
    assert asked == []


def test_cap_truncates_with_visible_copy(tmp_path):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from mf4_analyzer.ui.wwt_view_import import (
        build_wwt_view_proposals,
        register_groups_for_test,
    )

    loaded = load_wwt_document(
        wwt.multi_window_overlap_and_formula(tmp_path / "multi.wwt")
    )
    proposals = build_wwt_view_proposals(
        loaded.document, register_groups_for_test(loaded.groups)
    )
    _body, info = layout_dialog_text(loaded.document, proposals, available=1)
    assert info == f"检测到 {wwt.MULTI_WINDOW_COUNT} 个，可创建 1 个"
    assert ACCEPT_TEXT == "按 WinWert 排版并绘图"
    assert REJECT_TEXT == "仅加载数据"


def test_save_reopen_keeps_record_only_y_bindings(qapp, tmp_path, monkeypatch):
    """Restore skips offer_layout and keeps record-only Y bindings."""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.time_curve_bindings import resolve_time_curve_binding

    path = wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt")
    mw = MainWindow()
    mw.show()
    qapp.processEvents()
    asked = _stub_wwt_ui(mw, monkeypatch, accept=True)
    mw._load_one(str(path))
    qapp.processEvents()
    assert asked
    bindings = [
        item for view in mw.view_manager.views for item in view.curve_bindings
    ]
    assert bindings
    assert any(item.y_ref.kind == "wwt_record" for item in bindings)
    record_binding = next(
        item for item in bindings if item.y_ref.kind == "wwt_record"
    )
    x, y, issue = resolve_time_curve_binding(record_binding, mw.files)
    assert issue is None and y is not None and x is not None
    original = (_array_sig(x), _array_sig(y), None if issue is None else issue.code)

    proj = tmp_path / "wwt.tlproj"
    assert mw.save_project(proj) is True
    payload = proj.read_text(encoding="utf-8")
    assert "wwt_record_store" not in payload
    session = json.loads(payload)

    def _walk(node):
        if isinstance(node, dict):
            assert "wwt_record_store" not in node
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            if (
                len(node) >= wwt.CHANNEL_N
                and all(isinstance(item, (int, float)) for item in node[:8])
            ):
                pytest.fail("session JSON dumped a numeric array")
            for item in node:
                _walk(item)

    _walk(session)

    restored = MainWindow()
    restored.show()
    qapp.processEvents()
    restore_toasts = []

    def fail_if_called(*_a, **_k):
        pytest.fail("layout dialog must not run during project restore")

    monkeypatch.setattr(restored._wwt_import, "_ask_layout", fail_if_called)
    monkeypatch.setattr(
        restored._ultraview,
        "add_time_views_from_native_layout",
        lambda items, **_kwargs: (),
    )
    monkeypatch.setattr(restored, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(restored, "_apply_active_view", lambda *a, **k: None)
    monkeypatch.setattr(
        restored, "toast",
        lambda msg, level="info": restore_toasts.append((msg, level)),
    )
    restored.open_project(proj)
    qapp.processEvents()

    _assert_store_on_every_file(restored)
    restored_bindings = [
        item
        for view in restored.view_manager.views
        for item in view.curve_bindings
    ]
    assert restored_bindings
    assert any(item.y_ref.kind == "wwt_record" for item in restored_bindings)
    restored_binding = next(
        item for item in restored_bindings if item.y_ref.kind == "wwt_record"
    )
    x, y, issue = resolve_time_curve_binding(restored_binding, restored.files)
    assert issue is None, issue
    assert y is not None
    restored_sig = (
        _array_sig(x), _array_sig(y), None if issue is None else issue.code,
    )
    assert restored_sig == original
    warn = [(m, lv) for m, lv in restore_toasts if lv in {"warning", "warn"}]
    assert warn == [], warn


def test_reject_and_no_display_still_attach_record_store(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    path = wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt")
    mw = MainWindow()
    _stub_wwt_ui(mw, monkeypatch, accept=False)
    mw._load_one(str(path))
    store = _assert_store_on_every_file(mw)
    names = [getattr(item, "name", None) for item in store]
    assert wwt.TOL_Y in names
    assert wwt.LINE_X in names

    n = wwt.CHANNEL_N
    bare = wwt.write_wwt_file(
        tmp_path / "bare.wwt",
        (
            wwt.WwtRecordSpec("Zeit", wwt.TIME_NAME, "s", n=n, dt=wwt.DT, t0=wwt.T0),
            wwt.WwtRecordSpec(
                "Real", wwt.CHAN_Y, wwt.CHAN_Y_UNIT, n=n,
                values=np.linspace(wwt.CHAN_Y_LO, wwt.CHAN_Y_HI, n),
            ),
        ),
    )
    mw2 = MainWindow()

    def fail_if_called(*_a, **_k):
        pytest.fail("layout dialog must not run when the file has no display")

    monkeypatch.setattr(mw2._wwt_import, "_ask_layout", fail_if_called)
    monkeypatch.setattr(mw2, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(mw2, "_apply_active_view", lambda *a, **k: None)
    mw2._load_one(str(bare))
    _assert_store_on_every_file(mw2)


def test_record_only_overlap_is_reported_without_raw_code_toast(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.main_window import MainWindow

    path = wwt.multi_window_overlap_and_formula(tmp_path / "overlap.wwt")
    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(
        mw, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    projected = []
    asked = _stub_wwt_ui(mw, monkeypatch, accept=True, projected=projected)
    mw._load_one(str(path))
    assert asked
    assert "重叠" in asked[0][0]
    assert "第 3 个窗口与第 2 个" in asked[0][0]
    assert projected
    assert len(projected[0]) == wwt.MULTI_WINDOW_COUNT
    warn = [(m, lv) for m, lv in toasts if lv in {"warning", "warn"}]
    leaked = [
        msg for msg, _lv in warn
        if "exact_overlap" in str(msg)
        or "quantized_collision" in str(msg)
        or "placed_limit" in str(msg)
        or "duplicate_ref" in str(msg)
    ]
    assert leaked == [], warn
    board = mw._ultraview.board
    history = mw._ultraview._workspace_controller.grid_histories[board.board_id]
    assert len(history.undo) == 1
    assert len(board.free_grid) == wwt.MULTI_WINDOW_COUNT
    assert board.unplaced == []
    info = [msg for msg, level in toasts if level == "info"]
    assert any("已生成 3 个 WinWert View" in msg and "已放置" in msg for msg in info)


def test_format_wwt_placement_summary_reports_counts_and_stub_fallback():
    full = format_wwt_placement_summary(
        WwtImportOutcome(
            detected=7,
            created=7,
            view_ids=tuple(f"v{i}" for i in range(7)),
            warnings=(),
            accepted=True,
            placed_count=7,
            unplaced_count=0,
        )
    )
    assert full == "已生成 7 个 WinWert View：7 个已放置，0 个在未放置区"
    mixed = format_wwt_placement_summary(
        WwtImportOutcome(
            detected=7,
            created=7,
            view_ids=tuple(f"v{i}" for i in range(7)),
            warnings=(),
            accepted=True,
            placed_count=6,
            unplaced_count=1,
        )
    )
    assert mixed == "已生成 7 个 WinWert View：6 个已放置，1 个在未放置区"
    stub = format_wwt_placement_summary(
        WwtImportOutcome(
            detected=3,
            created=3,
            view_ids=("a", "b", "c"),
            warnings=(),
            accepted=True,
        )
    )
    assert stub == "已生成 3 个 WinWert View"


def test_wwt_inspector_lists_record_only_and_hide_does_not_touch_navigator(
    qapp, tmp_path, monkeypatch,
):
    from mf4_analyzer.ui.inspector_sections.contextual_time import TimeContextual
    from mf4_analyzer.ui.main_window import MainWindow

    panel = TimeContextual()
    panel.set_record_curves([])
    assert panel._record_curves._row_widgets == []
    panel.set_record_curves([{
        "binding_id": "a",
        "name": "TolY",
        "color": "#ff0000",
        "visible": True,
    }])
    assert len(panel._record_curves._row_widgets) == 1

    path = wwt.measurement_plus_record_only_tolerance(path=tmp_path / "tol.wwt")
    mw = MainWindow()
    _stub_wwt_ui(mw, monkeypatch, accept=True)
    mw._load_one(str(path))
    state = mw.view_manager.get(mw.view_manager.active)
    record_ids = [
        binding.binding_id
        for binding in state.curve_bindings
        if binding.y_ref.kind == "wwt_record"
    ]
    assert len(record_ids) == 1
    checked_before = mw.navigator.get_checked_channels()
    bindings_before = list(state.curve_bindings)
    mw._on_record_curve_visibility_toggled(record_ids[0], False)
    assert record_ids[0] in state.hidden_curve_binding_ids
    assert mw.navigator.get_checked_channels() == checked_before
    assert state.curve_bindings == bindings_before
    mw._refresh_record_curve_inspector(state)
    assert len(mw.inspector.time_ctx._record_curves._row_widgets) == 1


def test_optional_customer_wwt_import_smoke_when_present(qapp, tmp_path, monkeypatch):
    pytest.importorskip("pytestqt")
    from mf4_analyzer.ui.main_window import MainWindow

    folder = _ROOT / "testdoc" / "WWT"
    samples = sorted(folder.glob("*.wwt")) if folder.is_dir() else []
    if not samples:
        pytest.skip(f"optional customer WWT sample missing: {folder}")
    mw = MainWindow()
    _stub_wwt_ui(mw, monkeypatch, accept=False)
    mw._load_one(str(samples[0]))
    qapp.processEvents()
    assert mw.files
