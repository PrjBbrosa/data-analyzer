"""Owner tests for the channel-edit log and its replay."""
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from mf4_analyzer.io.blf_format import LazyZohFrame
from mf4_analyzer.io.channel_edit_log import (
    ChannelEditLog,
    fold_entries,
    replay,
)
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.signal.channel_recipe import make_dual, make_expression, make_single


def _fd():
    frame = pd.DataFrame({
        "time": [0.0, 0.1, 0.2, 0.3],
        "speed": [0.0, 1.0, 3.0, 6.0],
        "torque": [2.0, 2.0, 0.0, 4.0],
    })
    return FileData(
        "demo.csv", frame, list(frame.columns),
        {"speed": "rpm", "torque": "Nm"},
    )


def test_replay_chain_then_remove_intermediate_and_recreate_same_name():
    from mf4_analyzer.signal.channel_recipe import RemoveEntry

    fd = _fd()
    added = make_dual("sum_tq", "Nm", "add", "speed", "torque")
    derived = make_single("d_dt_sum_tq", "Nm", "derivative", "sum_tq", None)
    log = ChannelEditLog()
    log.record_derive(added)
    log.record_derive(derived)
    log.record_remove(["sum_tq"])
    assert [entry.name for entry in log.entries if hasattr(entry, "name")] == [
        "sum_tq", "d_dt_sum_tq",
    ]
    assert log.entries[-1].names == ("sum_tq",)

    results = replay(fd, log)
    assert all(result.applied for result in results)
    assert "sum_tq" not in fd.channels
    assert "d_dt_sum_tq" in fd.channels
    speed = np.array([0.0, 1.0, 3.0, 6.0])
    torque = np.array([2.0, 2.0, 0.0, 4.0])
    expected = np.gradient(speed + torque, fd.time_array)
    np.testing.assert_array_equal(fd.data["d_dt_sum_tq"].to_numpy(), expected)

    again = make_dual("speed", "rpm", "add", "torque", "torque")
    blocked = replay(fd, [again])
    assert blocked[0].reason == "输出名已被加载器通道占用"
    assert "speed" in fd.data.columns
    replaced = replay(fd, [
        RemoveEntry(("speed",)),
        again,
        make_single("speed", "", "abs", "torque", None),
    ])
    assert replaced[0].applied and replaced[1].applied
    assert replaced[2].reason == "输出名已被占用"
    np.testing.assert_array_equal(fd.data["speed"].to_numpy(), torque * 2)


def test_compression_drops_unused_chain_and_keeps_a_used_input():
    log = ChannelEditLog([
        make_single("a", "", "abs", "speed", None),
        make_single("b", "", "abs", "a", None),
        make_single("c", "", "abs", "b", None),
    ])
    log.record_remove(["a", "b", "c"])
    assert log.entries == []

    kept = ChannelEditLog([
        make_single("a", "", "abs", "speed", None),
        make_single("b", "", "abs", "a", None),
    ])
    kept.record_remove(["a"])
    assert [getattr(entry, "name", None) for entry in kept.entries if hasattr(entry, "name")] == ["a", "b"]
    assert kept.entries[-1].names == ("a",)


def test_fold_merges_a_later_delete_into_history():
    from mf4_analyzer.signal.channel_recipe import RemoveEntry

    history = ChannelEditLog([make_single("a", "", "abs", "speed", None)])
    fold_entries(history, [RemoveEntry(("a",))])
    assert history.entries == []


def test_skipped_upstream_does_not_stop_an_independent_recipe(caplog):
    import logging
    fd = _fd()
    missing = make_single("gone", "", "abs", "missing", None)
    other = make_single("abs_speed", "rpm", "abs", "speed", None)
    child = make_single("child", "", "abs", "gone", None)
    with caplog.at_level(logging.WARNING, logger="mf4_analyzer.io.channel_edit_log"):
        results = replay(fd, [missing, child, other, {"op": "nope"}])
    assert [result.reason for result in results] == [
        "输入通道不存在",
        "依赖的上游配方被跳过",
        None,
        "条目无法识别",
    ]
    assert "abs_speed" in fd.channels
    assert "gone" not in fd.channels
    assert any("gone" in record.message and "输入通道不存在" in record.message for record in caplog.records)


def test_expression_failure_and_non_numeric_are_visible():
    fd = _fd()
    fd.data["label"] = ["a", "b", "c", "d"]
    fd.channels.append("label")
    bad_expr = make_expression("bad", "", "log(A)", "torque", None)
    # torque contains a zero, so log is entirely invalid
    fd.data["torque"] = 0.0
    results = replay(fd, [
        bad_expr,
        make_single("copy", "", "abs", "label", None),
        make_single("short", "", "derivative", "speed", None),
    ])
    # derivative of the real speed is valid; replace with a one-row source below
    assert results[0].reason == "表达式结果全部无效"
    assert results[1].reason == "非数值输入"

    tiny = FileData(
        "tiny.csv",
        pd.DataFrame({"time": [0.0], "speed": [1.0]}),
        ["time", "speed"],
        {"speed": "rpm"},
    )
    short = replay(tiny, [make_single("d", "", "derivative", "speed", None)])
    assert short[0].reason == "长度不符"
    tiny.time_array = None
    missing_time = replay(tiny, [make_single("d", "", "derivative", "speed", None)])
    assert missing_time[0].reason == "时间轴不可用"


def test_lazy_frame_replay_does_not_materialize_unread_columns(tmp_path):
    time = np.array([0.0, 0.1, 0.2, 0.3])
    frame = LazyZohFrame(
        time,
        {
            "speed": (time, np.array([1.0, 2.0, 3.0, 4.0])),
            "other": (time, np.array([9.0, 9.0, 9.0, 9.0])),
        },
        ["Time", "speed", "other"],
    )
    fd = FileData(tmp_path / "can.blf", frame, ["Time", "speed", "other"], {"speed": "rpm", "other": "Nm"})
    replay(fd, [make_single("abs_speed", "rpm", "abs", "speed", None)])
    assert "abs_speed" in fd.channels
    assert "other" not in fd.data._cache
    np.testing.assert_array_equal(fd.data["abs_speed"].to_numpy(), [1, 2, 3, 4])


def test_log_roundtrip_preserves_only_referenced_expression_inputs():
    entry = make_expression("expr_t", "", "t * 2", None, None)
    payload = ChannelEditLog([entry]).to_json()
    assert payload == [{
        "op": "derive", "name": "expr_t", "unit": "", "kind": "expression", "expr": "t * 2",
    }]
    assert ChannelEditLog(payload).entries == [entry]


def test_importing_the_log_does_not_import_the_ui_package():
    repo = Path(__file__).resolve().parents[1]
    script = """
import json, sys
import mf4_analyzer.io.channel_edit_log
import mf4_analyzer.signal.channel_recipe
blocked = sorted(name for name in sys.modules if name == 'mf4_analyzer.ui' or name.startswith('mf4_analyzer.ui.'))
print(json.dumps(blocked))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=repo, env=env,
        text=True, capture_output=True, check=False, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
