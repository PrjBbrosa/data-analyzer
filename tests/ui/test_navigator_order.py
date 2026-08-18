"""Qt-free tests for the workspace navigator order model."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mf4_analyzer.ui.navigator_order import NavigatorOrderState


REPO_ROOT = Path(__file__).resolve().parents[2]


def _state(*files):
    order = NavigatorOrderState()
    for fid, channels in files:
        order.register_file(fid, channels)
    return order


def test_register_appends_unknown_and_duplicate_is_noop():
    order = NavigatorOrderState()
    order.register_file("f1", ["a", "b"])
    order.register_file("f2", ["c"])
    order.register_file("f1", ["z"])

    assert order.file_fids() == ("f1", "f2")
    assert order.channel_order("f1") == ("a", "b")
    assert order.channel_order("f2") == ("c",)


def test_register_normalizes_to_strings_and_skips_empty_or_duplicate_channels():
    order = NavigatorOrderState()
    order.register_file(1, [None, "a", "a", " b ", ""])

    assert order.file_fids() == ("1",)
    assert order.channel_order("1") == ("a", "b")


def test_accessors_return_copies():
    order = _state(("f1", ["a", "b"]))
    fids = order.file_fids()
    channels = order.channel_order("f1")
    by_fid = order.channel_order_by_fid()

    with pytest.raises(AttributeError):
        fids.append("f2")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        channels.append("c")  # type: ignore[attr-defined]
    by_fid["f1"].append("c")
    by_fid["f9"] = ["x"]

    assert order.file_fids() == ("f1",)
    assert order.channel_order("f1") == ("a", "b")
    assert "f9" not in order.channel_order_by_fid()


def test_set_file_order_keeps_unknown_registered_fids_appended():
    order = _state(("a", ["x"]), ("b", ["y"]), ("c", ["z"]))
    order.set_file_order(["c", "missing", "a"])
    assert order.file_fids() == ("c", "a", "b")


def test_move_file_block_head_to_tail_and_tail_to_head():
    order = _state(("a", ["x"]), ("b", ["y"]), ("c", ["z"]))

    assert order.move_file_block(["a"], "c", "after") is True
    assert order.file_fids() == ("b", "c", "a")
    assert order.move_file_block(["a"], "b", "before") is True
    assert order.file_fids() == ("a", "b", "c")


def test_move_file_block_same_position_is_noop():
    order = _state(("a", ["x"]), ("b", ["y"]), ("c", ["z"]))
    snapshot = order.file_fids()

    assert order.move_file_block(["b"], "a", "after") is False
    assert order.move_file_block(["b"], "c", "before") is False
    assert order.move_file_block(["b"], "b", "after") is False
    assert order.file_fids() == snapshot


def test_move_file_block_moves_grouped_fids_atomically():
    order = _state(
        ("a1", ["x"]),
        ("a2", ["y"]),
        ("b", ["z"]),
        ("c", ["w"]),
    )

    assert order.move_file_block(["a2", "a1"], ["c"], "after") is True
    assert order.file_fids() == ("b", "c", "a1", "a2")

    assert order.move_file_block(["a1", "a2"], "b", "before") is True
    assert order.file_fids() == ("a1", "a2", "b", "c")


def test_move_file_block_rejects_unknown_malformed_and_empty():
    order = _state(("a", ["x"]), ("b", ["y"]))

    assert order.move_file_block([], "b", "before") is False
    assert order.move_file_block(["missing"], "b", "before") is False
    assert order.move_file_block(["a"], "missing", "after") is False
    assert order.move_file_block(["a"], "b", "around") is False
    assert order.file_fids() == ("a", "b")


def test_move_channel_same_fid_only_and_noop_at_same_slot():
    order = _state(("f1", ["a", "b", "c"]), ("f2", ["d"]))

    assert order.move_channel("f1", "c", "a", "before") is True
    assert order.channel_order("f1") == ("c", "a", "b")
    assert order.move_channel("f1", "c", "a", "after") is True
    assert order.channel_order("f1") == ("a", "c", "b")
    assert order.move_channel("f1", "c", "a", "after") is False
    assert order.move_channel("f1", "c", "b", "before") is False
    assert order.move_channel("f1", "c", "d", "after") is False
    assert order.move_channel("f2", "d", "a", "before") is False
    assert order.move_channel("missing", "a", "b", "after") is False
    assert order.channel_order("f1") == ("a", "c", "b")
    assert order.channel_order("f2") == ("d",)


def test_order_checked_follows_file_then_channel_and_preserves_identity():
    order = _state(
        ("f1", ["a", "b", "c"]),
        ("f2", ["x", "y"]),
    )
    checked = [
        ("f2", "y", "#111"),
        ("f1", "c"),
        ("f1", "a", "#aaa"),
        ("f1", "c"),
        ("f2", "x", "#222"),
    ]

    ordered = order.order_checked(checked)

    assert ordered == [
        ("f1", "a", "#aaa"),
        ("f1", "c"),
        ("f2", "x", "#222"),
        ("f2", "y", "#111"),
    ]


def test_order_checked_appends_unregistered_but_valid_inputs_stably():
    order = _state(("f1", ["a"]))
    checked = [
        ("ghost", "z"),
        ("f1", "a"),
        ("ghost", "w"),
        ("other", "q"),
        ("f1", "new"),
    ]

    assert order.order_checked(checked) == [
        ("f1", "a"),
        ("f1", "new"),
        ("ghost", "z"),
        ("ghost", "w"),
        ("other", "q"),
    ]


def test_order_checked_skips_malformed_entries():
    order = _state(("f1", ["a"]))
    assert order.order_checked([None, "a", ("f1",), ("", "a"), ("f1", ""), ("f1", "a")]) == [
        ("f1", "a")
    ]


def test_refresh_channels_keeps_live_order_appends_new_and_drops_deleted():
    order = _state(("f1", ["a", "b", "c"]))
    order.move_channel("f1", "c", "a", "before")
    order.refresh_channels("f1", ["c", "d", "a"])

    assert order.channel_order("f1") == ("c", "a", "d")


def test_refresh_channels_registers_unknown_fid_from_loader_order():
    order = NavigatorOrderState()
    order.refresh_channels("f9", ["m", "n"])
    assert order.file_fids() == ("f9",)
    assert order.channel_order("f9") == ("m", "n")


def test_remove_fid_clears_file_and_channel_tables():
    order = _state(("f1", ["a"]), ("f2", ["b"]))
    order.remove_fid("f1")
    order.remove_fid("missing")

    assert order.file_fids() == ("f2",)
    assert order.channel_order("f1") == ()
    assert order.channel_order("f2") == ("b",)
    assert order.order_checked([("f1", "a"), ("f2", "b")]) == [("f2", "b"), ("f1", "a")]


def test_apply_channel_order_restores_saved_then_appends_loader_new():
    order = _state(("f1", ["a", "b", "c", "d"]))
    order.apply_channel_order("f1", ["d", "gone", "b"])

    assert order.channel_order("f1") == ("d", "b", "a", "c")


def test_move_channel_among_visible_keeps_hidden_relative_order():
    order = _state(("f1", ["a", "b", "c", "d"]))
    assert order.move_channel_among_visible(
        "f1", "c", "a", "before", ["a", "c"]
    ) is True
    assert order.channel_order("f1") == ("c", "b", "a", "d")
    assert order.move_channel_among_visible(
        "f1", "c", "a", "before", ["c", "a"]
    ) is False


def test_navigator_order_module_has_no_qt_or_widget_imports():
    path = REPO_ROOT / "mf4_analyzer" / "ui" / "navigator_order.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    forbidden = (
        "PyQt5",
        "pyqtgraph",
        "mf4_analyzer.ui.main_window",
        "mf4_analyzer.ui.file_navigator",
        "mf4_analyzer.ui.widgets",
        "mf4_analyzer.ui.chart_stack",
    )
    offenders = [
        name
        for name in imported
        if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert not offenders
