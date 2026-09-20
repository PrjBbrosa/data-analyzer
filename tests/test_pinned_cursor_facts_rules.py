"""Qt-free pinned-cursor identity / reconcile / diagnostic-row rules.

HTML coordinate cases import ``cursor_display`` pin helpers lazily so module
collection does not pull Qt. The poison-import test runs in a subprocess.
"""
from __future__ import annotations

import ast
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayBranch,
    CursorDisplayChannel,
    CursorExtremaFact,
    FrequencyCursorChannel,
    FrfCursorSample,
    PinnedCursorSample,
)
from mf4_analyzer.ui.pinned_cursor_facts import (
    HIDDEN_CHANNEL_TEXT,
    UNCHECKED_TEXT,
    UNAVAILABLE_TEXT,
    _binding_key,
    _finite,
    _hidden_channel_row,
    _hidden_keys_from_sample,
    _identity_key,
    _key_in,
    _reconcile_sample,
    _sample_has_hidden,
    _sample_has_numeric,
    _sample_has_unchecked,
)
from mf4_analyzer.ui.pinned_cursor_state import (
    PinnedCursorBinding,
    PinnedCursorIntent,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FACTS_PATH = REPO_ROOT / "mf4_analyzer" / "ui" / "pinned_cursor_facts.py"
_PINNED_CURSOR_FACTS_IMPORT_TIMEOUT_S = 30


def _intent(**overrides):
    data = {
        "record_id": str(uuid4()),
        "ordinal": 1,
        "mode": "single",
        "domain": "time",
        "x": 1.25,
        "x_unit": "s",
        "bindings": (PinnedCursorBinding(fid="f0", channel="torque"),),
    }
    data.update(overrides)
    return PinnedCursorIntent(**data)


def _channel(**overrides):
    data = {
        "identity": ("f0", "torque"),
        "source_label": "eps",
        "channel_label": "torque",
        "current_value": 1.5,
    }
    data.update(overrides)
    return CursorDisplayChannel(**data)


def _sample(channels=(), **overrides):
    data = {
        "domain": "time",
        "mode": "single",
        "x": 1.25,
        "channels": tuple(channels),
    }
    data.update(overrides)
    return PinnedCursorSample(**data)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (True, None),
        (False, None),
        ("nope", None),
        (math.inf, None),
        (-math.inf, None),
        (math.nan, None),
        (1.25, 1.25),
        (0, 0.0),
        ("2.5", 2.5),
    ],
)
def test_finite_rejects_bool_and_non_finite(value, expected):
    result = _finite(value)
    if expected is None:
        assert result is None
    else:
        assert result == expected


@pytest.mark.parametrize(
    "identity, expected",
    [
        (None, None),
        (("f0", "torque"), ("f0", "torque")),
        (("f0", "torque", ""), ("f0", "torque")),
        (("f0", "torque", "bind-a"), ("f0", "torque", "bind-a")),
        (["f0", "torque", "bind-a"], ("f0", "torque", "bind-a")),
        (("", "torque"), None),
        (("f0", ""), None),
        ('["f0", "torque"]', ("f0", "torque")),
        ('["f0", "torque", "bind-a"]', None),
        ("not-json", None),
        (42, None),
    ],
)
def test_identity_key_contract(identity, expected):
    """JSON 3-list currently fails plot_helpers (len==2 only). Do not 'fix'."""
    assert _identity_key(identity) == expected


def test_binding_key_includes_optional_binding_id():
    plain = PinnedCursorBinding(fid="f0", channel="torque")
    with_id = PinnedCursorBinding(fid="f0", channel="torque", binding_id="bind-a")
    assert _binding_key(plain) == ("f0", "torque")
    assert _binding_key(with_id) == ("f0", "torque", "bind-a")


@pytest.mark.parametrize(
    "key, pool, expected",
    [
        (None, {("f0", "torque")}, False),
        (("f0", "torque"), set(), False),
        (("f0", "torque"), {("f0", "torque")}, True),
        (("f0", "torque", "bind-a"), {("f0", "torque", "bind-a")}, True),
        (("f0", "torque"), {("f0", "torque", "bind-a")}, True),
        (("f0", "torque", "bind-a"), {("f0", "torque")}, True),
        (("f0", "torque", "bind-a"), {("f0", "torque", "bind-b")}, True),
        (("f0", "speed"), {("f0", "torque")}, False),
        (("f1", "torque"), {("f0", "torque")}, False),
        (("", "torque"), {("", "torque")}, True),
        (("", "torque"), {("f0", "torque")}, False),
    ],
)
def test_key_in_matches_fid_channel_with_optional_binding_id(key, pool, expected):
    """Existing contract: exact hit, else fid+channel ignoring binding_id."""
    assert _key_in(key, pool) is expected


def test_reconcile_empty_bindings_returns_sample_unchanged():
    sample = _sample(channels=(_channel(),))
    intent = _intent(bindings=())
    out, next_intent, dropped = _reconcile_sample(
        intent, sample, bound={("f0", "torque")}, hidden=set(),
    )
    assert out is sample
    assert next_intent is intent
    assert dropped is False


def test_reconcile_empty_sample_marks_unchecked_and_unavailable():
    intent = _intent(bindings=(
        PinnedCursorBinding(fid="f0", channel="torque"),
        PinnedCursorBinding(fid="f0", channel="speed"),
    ))
    sample, next_intent, dropped = _reconcile_sample(
        intent, None, bound={("f0", "speed")}, hidden=set(),
    )
    assert dropped is False
    assert next_intent is intent
    assert sample is not None
    assert sample.x == 1.25
    assert [ch.diagnostic for ch in sample.channels] == [
        UNCHECKED_TEXT, UNAVAILABLE_TEXT,
    ]


def test_reconcile_hidden_strips_numeric_and_filters_extrema():
    hidden_identity = ("f0", "torque")
    sample = _sample(
        channels=(_channel(current_value=9.0),),
        extrema=(
            CursorExtremaFact(identity=hidden_identity, min_x=0, min_y=0, max_x=1, max_y=1),
            CursorExtremaFact(identity=("f0", "speed"), min_x=0, min_y=0, max_x=1, max_y=1),
        ),
    )
    out, _next, dropped = _reconcile_sample(
        _intent(), sample, bound={hidden_identity}, hidden={hidden_identity},
    )
    assert dropped is False
    assert len(out.channels) == 1
    row = out.channels[0]
    assert row.diagnostic == HIDDEN_CHANNEL_TEXT
    assert row.current_value is None
    assert [item.identity for item in out.extrema] == [("f0", "speed")]


def test_reconcile_binding_id_matches_two_tuple_pool():
    binding = PinnedCursorBinding(fid="f0", channel="torque", binding_id="bind-a")
    sample = _sample(channels=(_channel(identity=("f0", "torque", "bind-a")),))
    out, _next, dropped = _reconcile_sample(
        _intent(bindings=(binding,)),
        sample,
        bound={("f0", "torque")},
        hidden=set(),
    )
    assert dropped is False
    assert out.channels[0].current_value == 1.5
    assert out.channels[0].diagnostic == ""


def test_hidden_channel_row_builds_identity_with_binding_id():
    binding = PinnedCursorBinding(fid="f0", channel="torque", binding_id="bind-a")
    row = _hidden_channel_row(binding, None)
    assert row.identity == ("f0", "torque", "bind-a")
    assert row.diagnostic == HIDDEN_CHANNEL_TEXT
    assert row.current_value is None


@pytest.mark.parametrize(
    "sample, numeric, hidden, unchecked",
    [
        (None, False, False, False),
        (_sample(), False, False, False),
        (_sample(channels=(_channel(),)), True, False, False),
        (
            _sample(channels=(_channel(current_value=None, diagnostic=HIDDEN_CHANNEL_TEXT),)),
            False, True, False,
        ),
        (
            _sample(channels=(_channel(current_value=None, diagnostic=UNCHECKED_TEXT),)),
            False, False, True,
        ),
        (
            _sample(channels=(_channel(current_value=None, diagnostic=UNAVAILABLE_TEXT),)),
            False, False, False,
        ),
        (
            _sample(channels=(
                FrequencyCursorChannel(
                    identity=("f0", "fft"), source_label="", channel_label="mag",
                    value=3.0,
                ),
            )),
            True, False, False,
        ),
        (
            _sample(channels=(), frf_sample=FrfCursorSample(frequency_hz=10.0)),
            True, False, False,
        ),
        (
            _sample(channels=(_channel(
                current_value=None,
                branches=(CursorDisplayBranch(label="X↑", current_value=1.0),),
            ),)),
            True, False, False,
        ),
    ],
)
def test_sample_status_predicates(sample, numeric, hidden, unchecked):
    assert _sample_has_numeric(sample) is numeric
    assert _sample_has_hidden(sample) is hidden
    assert _sample_has_unchecked(sample) is unchecked


def test_hidden_keys_from_sample_include_hidden_and_unchecked_only():
    sample = _sample(channels=(
        _channel(identity=("f0", "hidden"), current_value=None, diagnostic=HIDDEN_CHANNEL_TEXT),
        _channel(identity=("f0", "unchecked"), current_value=None, diagnostic=UNCHECKED_TEXT),
        _channel(identity=("f0", "live"), current_value=1.0),
        _channel(identity=("f0", "missing"), current_value=None, diagnostic=UNAVAILABLE_TEXT),
    ))
    assert _hidden_keys_from_sample(sample) == {("f0", "hidden"), ("f0", "unchecked")}
    assert _hidden_keys_from_sample(None) == set()


def _pin_html():
    from mf4_analyzer.ui.chart_stack.cursor_display import (
        pin_coord_html,
        pin_format_coord_html,
        pin_format_dual_html,
        pin_format_number,
        pin_format_value,
        pin_live_primary_html,
        pin_primary_html,
        pin_status_primary_html,
    )
    return {
        "coord": pin_coord_html,
        "format_coord": pin_format_coord_html,
        "format_dual": pin_format_dual_html,
        "format_number": pin_format_number,
        "format_value": pin_format_value,
        "live": pin_live_primary_html,
        "primary": pin_primary_html,
        "status": pin_status_primary_html,
    }


@pytest.mark.parametrize(
    "domain, value, unit, expected",
    [
        ("time", 1.25, "s", "t=1.2500s"),
        ("time", 1.25, "", "t=1.2500s"),
        ("channel", 12.5, "Nm", "X=12.5 Nm"),
        ("channel", 12.5, "", "X=12.5"),
        ("frequency", 50.0, "Hz", "f=50 Hz"),
        ("frequency", 50.0, "", "f=50 Hz"),
        ("frf", 80.0, "Hz", "f=80 Hz"),
    ],
)
def test_format_value_domains(domain, value, unit, expected):
    html = _pin_html()
    assert html["format_value"](domain, value, unit) == expected


@pytest.mark.parametrize(
    "domain, ax, bx, unit, expect_a, expect_b",
    [
        ("time", 1.0, 1.0, "s", "1.0000s", "1.0000s"),
        ("time", 1.0, 2.0, "s", "1.0000s", "2.0000s"),
        ("frequency", 10.0, 10.0, "Hz", "10 Hz", "10 Hz"),
        ("frequency", 10.0, 20.0, "", "10 Hz", "20 Hz"),
        ("channel", 1.5, 2.5, "Nm", "1.5 Nm", "2.5 Nm"),
        ("frf", 8.0, 9.0, "Hz", "8 Hz", "9 Hz"),
    ],
)
def test_format_dual_html_a_equals_and_a_greater_than_b(
    domain, ax, bx, unit, expect_a, expect_b,
):
    html = _pin_html()
    rendered = html["format_dual"](domain, ax, bx, unit)
    assert f"A={expect_a}" in rendered
    assert f"B={expect_b}" in rendered
    assert "color:#cbd5e1;" in rendered
    assert "&nbsp;│&nbsp;" in rendered


def test_format_coord_html_non_finite_is_em_dash():
    html = _pin_html()
    rendered = html["format_coord"]("time", math.nan, "s")
    assert rendered == '<span style="color:#111827;">—</span>'
    assert html["format_coord"]("time", None, "s") == rendered
    assert html["format_coord"]("time", True, "s") == rendered


def test_primary_and_status_html_preserve_escaping_and_colors():
    html = _pin_html()
    intent = _intent(ordinal=3, x=1.25)
    primary = html["primary"](intent)
    assert "P3" in primary
    assert "t=1.2500s" in primary
    status = html["status"](intent, "a <b> & c")
    assert "P3" in status
    assert "a &lt;b&gt; &amp; c" in status
    assert "color:#64748b;" in status


def test_live_and_coord_html_follow_mode():
    html = _pin_html()
    sample = _sample(x=2.5, ax=1.0, bx=3.0)
    live_single = html["live"]("time", "single", sample)
    live_dual = html["live"]("time", "dual", sample)
    assert "t=2.5000s" in live_single
    assert "A=1.0000s" in live_dual
    assert "B=3.0000s" in live_dual
    dual_intent = _intent(mode="dual", ax=1.0, bx=1.0, x=None)
    coord = html["coord"](dual_intent)
    assert "A=1.0000s" in coord
    assert "B=1.0000s" in coord


def test_facts_source_has_no_qt_or_chart_stack_imports():
    tree = ast.parse(FACTS_PATH.read_text(encoding="utf-8"), filename=str(FACTS_PATH))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    blob = " ".join(imported)
    assert all("Qt" not in name and "PyQt" not in name for name in imported)
    assert "pyqtgraph" not in blob
    assert "chart_stack" not in blob
    assert "PyQt5" not in blob
    assert "plot_helpers" in blob


def test_pinned_cursor_facts_import_does_not_load_qt():
    script = r"""
import json
import sys

sys.modules["PyQt5"] = None
sys.modules["PyQt5.QtCore"] = None
sys.modules["PyQt5.QtGui"] = None
sys.modules["PyQt5.QtWidgets"] = None
sys.modules["pyqtgraph"] = None
sys.modules["mf4_analyzer.ui.chart_stack"] = None
sys.modules["mf4_analyzer.ui.chart_stack.pinned_cursor_controller"] = None
sys.modules["mf4_analyzer.ui.chart_stack.cursor_display"] = None
sys.modules["mf4_analyzer.ui.chart_stack.stack"] = None
sys.modules["mf4_analyzer.ui.main_window"] = None
sys.modules["mf4_analyzer.ui.pg_canvas"] = None

try:
    import PyQt5  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print(json.dumps({"error": "poison_ineffective"}))
    raise SystemExit(2)

try:
    import mf4_analyzer.ui.chart_stack  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print(json.dumps({"error": "poison_ineffective_chart_stack"}))
    raise SystemExit(2)

import mf4_analyzer.ui.pinned_cursor_facts as facts

from mf4_analyzer.ui.pinned_cursor_state import PinnedCursorBinding
key = facts._binding_key(PinnedCursorBinding(fid="f0", channel="torque"))
assert key == ("f0", "torque")
assert facts._identity_key(("f0", "torque")) == ("f0", "torque")
assert facts._finite(True) is None

live = sorted(
    name
    for name, mod in sys.modules.items()
    if mod is not None
    and (
        name == "PyQt5"
        or name.startswith("PyQt5.")
        or name == "pyqtgraph"
        or name.startswith("pyqtgraph.")
        or name == "mf4_analyzer.ui.chart_stack"
        or name.startswith("mf4_analyzer.ui.chart_stack.")
        or name == "mf4_analyzer.ui.main_window"
        or name.startswith("mf4_analyzer.ui.main_window.")
    )
)
print(
    json.dumps(
        {
            "live": live,
            "chart_stack": "mf4_analyzer.ui.chart_stack" in sys.modules
            and sys.modules["mf4_analyzer.ui.chart_stack"] is not None,
            "key": list(key),
        }
    )
)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=_PINNED_CURSOR_FACTS_IMPORT_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload.get("error") is None, payload
    assert payload["live"] == []
    assert payload["chart_stack"] is False
    assert payload["key"] == ["f0", "torque"]
